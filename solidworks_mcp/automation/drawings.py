"""
SolidWorks Drawing Operations
------------------------------
Access and operate on drawing (.slddrw) documents.
"""

import datetime
import json
import os
import logging
import re
import string
from contextlib import ExitStack, contextmanager
from math import ceil, sqrt
from typing import Any, Dict, List, Optional, Tuple

from .. import com_backend
from .com_params import (
    ComSignature, Param, REQUIRED, enum_to_int, to_bool, to_meters, to_optional_object,
    to_radians,
)
from ..constants import SwErrors, SwDocumentTypes, SwFileTypes
from ..constants_drawing import (
    SwAddOrdinateDims,
    SwAlignViewTypes,
    SwAutodimEntities,
    SwAutodimHorizontalPlacement,
    SwAutodimScheme,
    SwAutodimStatus,
    SwAutodimVerticalPlacement,
    SwCreateOrdDimError,
    SwCreateSectionViewAtOptions,
    SwCustomInfoType,
    SwCustomPropertyAddOption,
    SwDatumDisplayType,
    SwDetCircleShowType,
    SwDetViewStyle,
    SwDimensionTextParts,
    SwDimensionType,
    SwDisplayMode,
    SwDrawingProjectionType,
    SwDrawingViewTypes,
    SwDwgPaperSizes,
    SwDwgTemplates,
    SwDxfFormat,
    SwDxfMultisheet,
    SwEdrawingSaveAsOption,
    SwExportDataFileType,
    SwExportDataSheetsToExport,
    SwFileSaveError,
    SwImportModelItemsSource,
    SwInConfigurationOpts,
    SwInsertAnnotation,
    SwInsertOptions,
    SwLeaderStyle,
    SwRenameOptions,
    SwSaveAsOptions,
    SwSaveAsVersion,
    SwSetValueInConfiguration,
    SwSetValueReturnStatus,
    SwUserPreferenceIntegerValue,
    SwUserPreferenceStringListValue,
    SwUserPreferenceToggle,
    SwViewAlignment,
    decode_save_error,
)
from ..utils import find_template

logger = logging.getLogger(__name__)

# `IDrawingDoc::NewSheet4`/`SetupSheet5`'s PaperSize argument (swDwgPaperSizes_e),
# keyed by the short paper-size names this tool layer accepts: (landscape, portrait).
# `None` for a size with no documented vertical/portrait variant -- see
# docs/api/01-documents-and-sheets.md's swDwgPaperSizes_e table.
_PAPER_SIZES = {
    "A": (SwDwgPaperSizes.swDwgPaperAsize, SwDwgPaperSizes.swDwgPaperAsizeVertical),
    "B": (SwDwgPaperSizes.swDwgPaperBsize, None),
    "C": (SwDwgPaperSizes.swDwgPaperCsize, None),
    "D": (SwDwgPaperSizes.swDwgPaperDsize, None),
    "E": (SwDwgPaperSizes.swDwgPaperEsize, None),
    "A4": (SwDwgPaperSizes.swDwgPaperA4size, SwDwgPaperSizes.swDwgPaperA4sizeVertical),
    "A3": (SwDwgPaperSizes.swDwgPaperA3size, None),
    "A2": (SwDwgPaperSizes.swDwgPaperA2size, None),
    "A1": (SwDwgPaperSizes.swDwgPaperA1size, None),
    "A0": (SwDwgPaperSizes.swDwgPaperA0size, None),
}

# Reverse of `_PAPER_SIZES`, keyed by the raw `swDwgPaperSizes_e` int code --
# what `list_sheets`/`get_active_sheet` use to render `ISheet::GetProperties2`'s
# `paperSize` element back into one of this tool layer's own short names.
# Portrait variants get a "-vertical" suffix so the name round-trips through
# `add_sheet`'s own `paper_size` argument only for the landscape half (that
# tool has no separate orientation parameter -- see its docstring); a sheet
# actually created in a portrait size still reports a distinguishable name
# here rather than silently collapsing onto its landscape sibling's name.
# `swDwgPapersUserDefined` (12) is `add_sheet`'s own "custom" spelling, not a
# `_PAPER_SIZES` member (that dict only holds the eleven named sizes).
_PAPER_SIZE_NAMES = {int(SwDwgPaperSizes.swDwgPapersUserDefined): "custom"}
for _size_name, (_landscape, _portrait) in _PAPER_SIZES.items():
    _PAPER_SIZE_NAMES[int(_landscape)] = _size_name
    if _portrait is not None:
        _PAPER_SIZE_NAMES[int(_portrait)] = f"{_size_name}-vertical"
del _size_name, _landscape, _portrait


def _paper_size_name(code: Any) -> Optional[str]:
    """Readable `add_sheet`-style name for a `swDwgPaperSizes_e` code read
    back off `ISheet::GetProperties2`, or `f"unknown paper size {code!r}"`
    for anything `_PAPER_SIZE_NAMES` doesn't recognize -- `None` only when
    `code` itself couldn't be read at all."""
    if code is None:
        return None
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        return f"unknown paper size {code!r}"
    return _PAPER_SIZE_NAMES.get(code_int, f"unknown paper size {code_int}")


def _template_in_name(code: Any) -> Optional[str]:
    """Readable `SwDwgTemplates` member name for a `templateIn` code read
    back off `ISheet::GetProperties2` (index 1) -- e.g. `"swDwgTemplateNone"`
    or `"swDwgTemplateCustom"`, or `f"unknown template {code!r}"` for
    anything unrecognized. `None` only when `code` itself couldn't be read.
    """
    if code is None:
        return None
    try:
        return SwDwgTemplates(int(code)).name
    except (TypeError, ValueError):
        return f"unknown template {code!r}"


def _scale_ratio_string(scale_num: Any, scale_denom: Any) -> Optional[str]:
    """`"1:2"`-style readable ratio for `get_sheet_properties`, alongside the
    numeric `scale_num`/`scale_denom` pair it's derived from. Whole-valued
    floats (`GetProperties2`'s own return type) render without a trailing
    `.0` (`"1:2"`, not `"1.0:2.0"`); `None` if either component is missing."""
    if scale_num is None or scale_denom is None:
        return None

    def _fmt(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return str(int(number)) if number.is_integer() else str(number)

    return f"{_fmt(scale_num)}:{_fmt(scale_denom)}"


def _normalize_sheet_names(raw: Any) -> List[str]:
    """`IDrawingDoc::GetSheetNames` returns a `Variant` array of strings at
    the COM layer, but per docs/api/01-documents-and-sheets.md's Gotchas
    that's a `System.Object` a caller must cast -- and in practice this
    project has seen it arrive as a Python tuple/list, a bare single string
    (some interop layers unwrap a one-element safearray), or `None` (a
    brand-new drawing before any sheet exists, or a load failure). Normalize
    all three shapes to a plain list of names so every sheet-management tool
    can treat `GetSheetNames`'s result uniformly."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


# `IDrawingDoc::NewSheet4`'s positional signature, in the exact order
# documented in docs/api/01-documents-and-sheets.md: Name, PaperSize,
# TemplateIn, Scale1, Scale2, FirstAngle, TemplateName, Width, Height,
# PropertyViewName, ZoneLeftMargin, ZoneRightMargin, ZoneTopMargin,
# ZoneBottomMargin, ZoneRow, ZoneCol. 16 positional parameters -- ComSignature
# per this issue's working agreement (>6 params).
#
# `add_sheet` has no zone-grid parameters of its own (not requested by this
# issue's acceptance criteria), so the six Zone*/ZoneRow/ZoneCol arguments are
# always bound to their "no zone grid" default here. Per the dossier's own
# Gotchas, the official worked example never demonstrates a zero-zone call
# and how to fully suppress the grid is explicitly unverified -- `0` for
# every margin and for both ZoneRow/ZoneCol is this wrapper's own convention
# for "caller didn't ask for zones", not a dossier-confirmed suppression
# value; same unverified-convention caveat this file already applies to
# `_OPEN_DOC_OPTION_READ_ONLY`/`_LEADER_SIDE_DEFAULT` above. The Zone*Margin
# params also have no converter (`identity`, not `to_meters`): the dossier's
# own worked example shows a 0.5 margin on a 0.2794 m sheet, which is
# geometrically impossible in meters, so their real unit is unverified and
# is deliberately *not* guessed at here via a mm-to-meters conversion.
NEW_SHEET4 = ComSignature("NewSheet4", [
    Param("name", REQUIRED),
    Param("paper_size", REQUIRED, enum_to_int),
    Param("template_in", REQUIRED, enum_to_int),
    Param("scale1", 1.0),
    Param("scale2", 1.0),
    Param("first_angle", False, to_bool),
    Param("template_name", ""),
    Param("width", 0.0, to_meters),
    Param("height", 0.0, to_meters),
    Param("property_view_name", ""),
    Param("zone_left_margin", 0.0),
    Param("zone_right_margin", 0.0),
    Param("zone_top_margin", 0.0),
    Param("zone_bottom_margin", 0.0),
    Param("zone_row", 0, enum_to_int),
    Param("zone_col", 0, enum_to_int),
])

# `IDrawingDoc::SetupSheet5`'s positional signature, in the exact order
# documented in docs/api/01-documents-and-sheets.md: Name, PaperSize,
# TemplateIn, Scale1, Scale2, FirstAngle, TemplateName, Width, Height,
# PropertyViewName, RemoveModifiedNotes. 11 positional parameters --
# ComSignature per this issue's working agreement (>6 params). Like
# `NewSheet4`, this is a method on `IDrawingDoc` itself (not `ISheet`) --
# `Name` identifies *which* sheet to reconfigure, it does not rename it.
#
# `set_sheet_properties` has no `property_view_name` parameter of its own
# (not requested by this issue's acceptance criteria), so it's always bound
# to `""` here -- same "caller didn't ask for it" convention `add_sheet`
# already applies to `NewSheet4`'s own zone parameters. `remove_modified_notes`
# is likewise always bound to `False` (the least-destructive default: leave
# modified notes alone) -- not exposed as a public parameter either.
SETUP_SHEET5 = ComSignature("SetupSheet5", [
    Param("name", REQUIRED),
    Param("paper_size", REQUIRED, enum_to_int),
    Param("template_in", REQUIRED, enum_to_int),
    Param("scale1", REQUIRED),
    Param("scale2", REQUIRED),
    Param("first_angle", False, to_bool),
    Param("template_name", ""),
    Param("width", 0.0, to_meters),
    Param("height", 0.0, to_meters),
    Param("property_view_name", ""),
    Param("remove_modified_notes", False, to_bool),
])

# `ISldWorks::OpenDoc6`'s `Options` argument (swOpenDocOptions_e) is only
# referenced by name, not enumerated, in docs/api/01-documents-and-sheets.md's
# parameter table (see that record's Gotchas). help.solidworks.com's swconst
# pages 403 for every version tried (the same WAF block the dossier hit
# fetching SOLIDWORKS forum threads), and the one mirror site that responded
# lists the member names with no numeric values. These two bit values are
# corroborated only by consistent secondary-source citation (multiple
# independent SOLIDWORKS macro blogs), not a primary source -- treat them as
# this wrapper's own convention, same caveat as `selection.py`'s
# `_VIEW_ENTITY_TYPES`.
_OPEN_DOC_OPTION_READ_ONLY = 2
_OPEN_DOC_OPTION_LOAD_LIGHTWEIGHT = 128

# `IAnnotation::SetLeader3`'s `LeaderSide` argument (`swLeaderSide_e`) has three
# confirmed *member names* (`swLS_LEFT`/`swLS_RIGHT`/`swLS_SMART`, per
# docs/api/03-annotations.md's Enums section) but no accessible source states
# their numeric values -- the swconst page itself hit the same WAF block noted
# throughout this dossier. `add_note` does not expose `LeaderSide` as a public
# parameter (not required by sw-1xx.3's acceptance criteria); this is this
# wrapper's own convention value for "let SolidWorks pick a side", same
# unverified-convention caveat as `_OPEN_DOC_OPTION_READ_ONLY` above -- do not
# treat this as a confirmed `swLS_*` mapping.
_LEADER_SIDE_DEFAULT = 0

# `IAnnotation::SetLeader3`'s `LeaderStyle` argument -- the four shapes
# `add_note`'s `leader["style"]` accepts, mapped to `SwLeaderStyle`'s low-value
# (non-bitmask) members. Per that record's own Gotchas, all four are valid on
# notes specifically ("Only notes support underline leaders").
_NOTE_LEADER_STYLES = {
    "none": SwLeaderStyle.swNO_LEADER,
    "straight": SwLeaderStyle.swSTRAIGHT,
    "bent": SwLeaderStyle.swBENT,
    "underline": SwLeaderStyle.swUNDERLINED,
}

# `export_dxf_dwg`'s `export_fonts_as` -> `swUserPreferenceIntegerValue_e.swDxfOutputFonts`
# value, per docs/api/05-export-and-layers.md's Enums section (the only two
# documented values for this member: AutoCAD STANDARD-font-only geometry, or
# true TrueType fonts).
_DXF_FONT_MODES = {"geometry": 0, "truetype": 1}

# `export_dxf_dwg`'s `version` -> `SwDxfFormat` member, keyed by the release
# name with the shared "swDxfFormat_" prefix stripped (e.g. "R2018").
_DXF_VERSION_BY_NAME = {
    member.name[len("swDxfFormat_"):]: member for member in SwDxfFormat
}

# `export_edrawings`'s "is this a missing-add-in failure" decoder: which
# `swFileSaveError_e` bits, per docs/api/05-export-and-layers.md's Gotchas,
# plausibly indicate the eDrawings add-in/format isn't available rather than
# an ordinary save failure.
_EDRAWINGS_ADDIN_ERROR_BITS = (
    int(SwFileSaveError.swFileSaveFormatNotAvailable)
    | int(SwFileSaveError.swFileSaveAsBadEDrawingsVersion)
    | int(SwFileSaveError.swFileSaveAsNotSupported)
)


_BATCH_EXPORT_FORMAT_EXTENSIONS = {
    "pdf": ".pdf",
    "dxf": ".dxf",
    "dwg": ".dwg",
    "edrawings": ".edrw",
}

# Which `batch_export_pack` formats need the target sheet made active before
# their per-sheet export, because they have no "these specific sheets" mode of
# their own: DXF/DWG and eDrawings are driven by user preferences that only
# reach the active sheet, while PDF has `IExportPdfData::SetSheets`. Consulted
# both to decide whether a sheet switch is needed at all and to attribute an
# activation failure only to the formats it actually blocks.
_BATCH_EXPORT_NEEDS_ACTIVE_SHEET = frozenset({"dxf", "dwg", "edrawings"})

# `batch_export_pack`'s "does this pattern discriminate between sheets?"
# check. Matched as a `str.format` replacement field rather than as the bare
# literals `"{sheet}"`/`"{index}"`, so a pattern carrying a conversion or
# format spec -- `{index:02d}`, `{sheet!s}` -- is recognized as the
# per-sheet token it is instead of being rejected as if it had none.
_PER_SHEET_TOKEN_RE = re.compile(r"\{(sheet|index)\b[^{}]*\}")

# Characters illegal in a Windows file/directory name, plus C0 control
# characters -- `batch_export_pack`'s filename_pattern tokens (a sheet name
# in particular) are caller/model-controlled data, not a path this project
# constructs itself, so each resolved token is sanitized before it ever
# reaches `os.path.join` rather than trusting it not to contain `/`, `\`, or
# `:` (which could otherwise escape `output_dir` or be misread as a drive/
# alternate-data-stream separator).
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename_component(value: Any) -> str:
    """Replace every Windows-illegal character in `value` with `_` and trim
    the leading/trailing dots and spaces Windows also disallows at the end
    of a name. May return an empty string -- e.g. `batch_export_pack`'s
    `{rev}` token is legitimately `""` when no revision custom property is
    set, and that has to stay empty here rather than being forced into a
    literal `"_"` inside the middle of a larger pattern. Callers that need
    a single sanitized value to *itself* be a non-empty path segment (a
    whole formatted filename, not one token feeding into it) are
    responsible for that fallback themselves.
    """
    text = _ILLEGAL_FILENAME_CHARS.sub("_", str(value))
    return text.strip(" .")


def _com_bool(value: Any) -> Optional[bool]:
    """Coerce a COM-returned Boolean-ish value to a real `bool`, or `None`
    when it carries no usable Boolean.

    A `VARIANT_BOOL` reaches Python as a genuine `bool` through some interop
    layers and as a plain `int` (`0`/`-1`) through others -- the same
    numeric/Boolean duality `_count_sheet_views` guards against for
    `IView::Type`. An identity test (`is False`) silently misses the `int`
    form, so `ILayer::Visible == 0` would read as "not hidden" and the whole
    show-hidden-layers pass would become a no-op. Anything that is neither
    (`None` from a failed `_read_prop`, or the fake-COM harness's
    auto-vivified wrapper for an unscripted member) yields `None`, so callers
    can tell "no answer" apart from a definite `False`.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _looks_like_missing_addin(message: str) -> bool:
    """Best-effort heuristic for `export_edrawings`: does a raised COM
    exception's message look like a missing/unavailable eDrawings add-in,
    rather than some unrelated COM failure? No fetched page documents a
    specific exception shape for this case (the dossier notes "no add-in
    requirement is documented on any fetched page"), so this is a
    string-matching convention, not a verified API contract -- callers
    should treat a `False` result as "inconclusive", not "definitely not an
    add-in problem".

    Deliberately does *not* key on a bare `"edrawings"`: every target of this
    export ends in `.edrw` and operators routinely export into a directory
    like `C:\\Exports\\eDrawings\\`, so any unrelated COM failure whose
    message quotes the path (permission denied, path too long) would
    otherwise be reported as a missing add-in and send the operator to load
    one that is already there. Only wording that names an add-in as such
    counts.
    """
    lowered = message.lower()
    return any(keyword in lowered for keyword in ("add-in", "addin"))


# `IModelDocExtension::SaveAs3`'s positional signature, in the exact order
# documented in docs/api/05-export-and-layers.md: Name, Version, Options,
# ExportData, AdvancedSaveAsOptions, Errors, Warnings. 7 positional
# parameters -- ComSignature per this issue's working agreement (>6 params),
# and the one COM call this package makes from the most call sites
# (`save_drawing`, all three export tools, and `batch_export_pack`'s native
# archive copy), so a transposed `version`/`options` pair -- a silently wrong
# save -- is exactly what binding by keyword rules out here.
#
# `errors`/`warnings` are byref out-parameters: the caller creates them with
# `com_backend.byref_int()` and reads `.value` after the call, so they bind
# through unconverted rather than carrying a default.
SAVE_AS3 = ComSignature("SaveAs3", [
    Param("path", REQUIRED),
    Param("version", SwSaveAsVersion.swSaveAsCurrentVersion, enum_to_int),
    Param("options", SwSaveAsOptions.swSaveAsOptions_Silent, enum_to_int),
    Param("export_data", None, to_optional_object),
    Param("advanced_options", None, to_optional_object),
    Param("errors", REQUIRED),
    Param("warnings", REQUIRED),
])


class _PreferenceError(Exception):
    """A `Get`/`SetUserPreference*` call raised while entering
    `DrawingOperations._user_preference`.

    Carries the caller-facing message so each export tool can return its own
    `_result(False, str(e), ...)` without having to know which half of the
    snapshot-then-set pair failed.
    """


# `_user_preference`'s dispatch table: which `ISldWorks` getter/setter pair
# reaches a given preference enum, and how a value is coerced on the way in.
# Keyed by the enum class itself, so the accessor kind travels with the
# constant instead of being re-picked by hand at each call site (picking
# `SetUserPreferenceIntegerValue` for a toggle is otherwise a silent no-op,
# not an error).
#
# Restore values are passed back exactly as the getter returned them, with no
# re-coercion -- an unscripted preference read against the fake-COM harness
# hands back a wrapper object with no `__int__`, while a real COM read already
# hands back a genuine `int`/`bool`/list.
#
# The 4th element is whether the setter reports success: per
# docs/api/05-export-and-layers.md, `SetUserPreferenceIntegerValue` and
# `SetUserPreferenceStringListValue` are `Function ... As Boolean` ("True if
# the value was set, false if not"), while `SetUserPreferenceToggle` is a
# `Sub` with no return at all -- so only the first two have a status worth
# checking, and truth-testing the toggle's `None` would fail every call.
_PREFERENCE_ACCESSORS = {
    SwUserPreferenceToggle: (
        "GetUserPreferenceToggle", "SetUserPreferenceToggle", bool, False),
    SwUserPreferenceIntegerValue: (
        "GetUserPreferenceIntegerValue", "SetUserPreferenceIntegerValue", int, True),
    SwUserPreferenceStringListValue: (
        "GetUserPreferenceStringListValue", "SetUserPreferenceStringListValue", list, True),
}


# `IDrawingDoc::CreateDrawViewFromModelView3`'s `ViewName` argument accepts the
# asterisk-prefixed standard-orientation names (docs/api/02-views.md's "Front"
# vs "*Front" gotcha -- every working example uses the "*"-prefixed form).
# Keyed lowercase with no leading "*", so callers can pass "Front", "front",
# or "*Front" interchangeably; `insert_model_view` rejects anything else
# rather than guessing at an unprefixed custom named view.
_STANDARD_MODEL_VIEWS = {
    "front": "*Front",
    "top": "*Top",
    "right": "*Right",
    "left": "*Left",
    "bottom": "*Bottom",
    "back": "*Back",
    "isometric": "*Isometric",
    "dimetric": "*Dimetric",
    "trimetric": "*Trimetric",
    "current": "*Current",
}

# `IDrawingDoc::CreateUnfoldedViewAt3`'s `direction` -> (dx sign, dy sign,
# NotAligned) used by `insert_projected_view`. The four cardinal directions
# keep the projected view orthographically aligned to its parent (NotAligned
# =False, the "drag off an edge" UI behavior docs/api/02-views.md's
# CreateUnfoldedViewAt3 record documents) -- an aligned view can only move
# along the alignment vector shared with its parent, so it makes sense for
# these to stay aligned. The four diagonals have no aligned-projection
# equivalent in the SolidWorks UI at all (an orthographic projection is
# always straight up/down/left/right of its parent), so those break
# alignment (NotAligned=True) to be freely positionable off-axis -- this is
# this wrapper's own convention, not something the dossier's projected-view
# record specifies, since the API has no native "diagonal projected view"
# concept.
_PROJECTED_VIEW_DIRECTIONS = {
    "right": (1, 0, False),
    "left": (-1, 0, False),
    "up": (0, 1, False),
    "down": (0, -1, False),
    "upright": (1, 1, True),
    "upleft": (-1, 1, True),
    "downright": (1, -1, True),
    "downleft": (-1, -1, True),
}

# Sheet-space nudge (meters) used only to bias `CreateUnfoldedViewAt3`'s
# required X/Y toward the requested direction when the caller doesn't pass
# an explicit `offset` -- for an aligned view SolidWorks snaps the
# perpendicular axis to the parent's alignment vector regardless of the
# exact value passed, per docs/api/02-views.md's `IView::Position` Gotchas
# ("if this view is aligned to another view, it can only move along the
# alignment vector"). Not sourced from the dossier; this wrapper's own
# convention for "some reasonable default offset" pending a real
# SolidWorks session to validate against.
_DEFAULT_PROJECTED_VIEW_STEP_M = 0.05

# `IDrawingDoc::CreateAuxiliaryViewAt2`'s positional signature, in the exact
# order documented in docs/api/02-views.md: X, Y, Z, NotAligned, Label,
# Showarrow, Flip. 7 positional parameters -- ComSignature per this issue's
# working agreement (>6 params).
CREATE_AUXILIARY_VIEW_AT2 = ComSignature("CreateAuxiliaryViewAt2", [
    Param("x", REQUIRED, to_meters),
    Param("y", REQUIRED, to_meters),
    Param("z", 0.0, to_meters),
    Param("not_aligned", False, to_bool),
    Param("label", ""),
    Param("show_arrow", True, to_bool),
    Param("flip", False, to_bool),
])

# `IDrawingDoc::CreateSectionViewAt5`'s positional signature, in the exact
# order documented in docs/api/02-views.md: X, Y, Z, SectionLabel, Options,
# ExcludedComponents, SectionDepth. 7 positional parameters -- ComSignature
# per this issue's working agreement (>6 params). `insert_section_view`
# doesn't support component exclusion or a non-default cut depth, so those
# two always bind to their converter's "no-op" default (null dispatch / 0).
CREATE_SECTION_VIEW_AT5 = ComSignature("CreateSectionViewAt5", [
    Param("x", REQUIRED, to_meters),
    Param("y", REQUIRED, to_meters),
    Param("z", 0.0, to_meters),
    Param("label", ""),
    Param("options", 0, enum_to_int),
    Param("excluded_components", None, to_optional_object),
    Param("section_depth", 0.0, to_meters),
])

# `insert_section_view`'s `section_type` -> `swCreateSectionViewAtOptions_e`
# bit, per docs/api/02-views.md's `CreateSectionViewAt5` and `IDrSection`
# records. "full" is the enum's own unmarked default (no bit set -- a normal,
# complete section snapped into alignment with its parent). "aligned" is
# `OffsetSection`, whose own help-page text literally reads "an aligned
# section view is created" despite the record's noted self-contradiction
# with `NotAligned`. "half" has NO true half-section member anywhere in this
# API under any name (the dossier's `CreateSectionViewAt5` Gotchas is
# explicit that `Partial` is "a distinct concept; don't conflate") -- binding
# it to `Partial` is this wrapper's own convention, not a dossier-endorsed
# mapping, chosen because it's the closest documented behavior (a section
# that doesn't cut the model's full extent) and because `half_section`'s own
# validation below restricts it to a straight 2-point cut line, ruling out
# the multi-segment/offset case `Partial`'s own text doesn't address either
# way.
_SECTION_TYPE_OPTIONS = {
    "full": 0,
    "aligned": int(SwCreateSectionViewAtOptions.swCreateSectionView_OffsetSection),
    "half": int(SwCreateSectionViewAtOptions.swCreateSectionView_Partial),
}

# `IDrawingDoc::CreateDetailViewAt4`'s positional signature, in the exact order
# documented in docs/api/02-views.md: X, Y, Z, Style, Scale1, Scale2, LabelIn,
# Showtype, FullOutline, JaggedOutline, NoOutline, ShapeIntensity. 12 positional
# parameters -- ComSignature per this issue's working agreement (>6 params).
# `Style` (swDetViewStyle_e -- border/leader look) is not one of
# `insert_detail_view`'s own parameters; it's always bound to its own default
# below (swDetViewSTANDARD), since none of that tool's arguments map to this
# enum -- see docs/api/02-views.md's `swDetViewStyle_e` record for why.
CREATE_DETAIL_VIEW_AT4 = ComSignature("CreateDetailViewAt4", [
    Param("x", REQUIRED, to_meters),
    Param("y", REQUIRED, to_meters),
    Param("z", 0.0, to_meters),
    Param("style", int(SwDetViewStyle.swDetViewSTANDARD), enum_to_int),
    Param("scale1", REQUIRED),
    Param("scale2", REQUIRED),
    Param("label", ""),
    Param("showtype", REQUIRED, enum_to_int),
    Param("full_outline", False, to_bool),
    Param("jagged_outline", False, to_bool),
    Param("no_outline", False, to_bool),
    Param("shape_intensity", 1, enum_to_int),
])

# `insert_detail_view`'s `style` -> `swDetCircleShowType_e`'s `Showtype`
# parameter, per docs/api/02-views.md's `CreateDetailViewAt4` and
# `swDetCircleShowType_e` records. The task-spec-requested `style` name turns
# out to actually mean this enum, not `swDetViewStyle_e` (a separate,
# unrelated "border/leader look" enum this tool doesn't expose at all) --
# `"circle"`'s default value is literally `swDetCircleCIRCLE`'s own name, and
# `insert_detail_view` always sketches a circle (never an arbitrary profile),
# matching `CreateDetailViewAt4`'s official example workflow (sketch a circle,
# call immediately, Showtype:=swDetCircleCIRCLE "use sketch circle to create
# detail view").
_DETAIL_VIEW_SHOWTYPE = {
    "circle": int(SwDetCircleShowType.swDetCircleCIRCLE),
    "profile": int(SwDetCircleShowType.swDetCirclePROFILE),
    "none": int(SwDetCircleShowType.swDetCircleDONTSHOW),
}

# `insert_model_items`'s `types` -> `swInsertAnnotation_e` bit(s), per
# docs/api/03-annotations.md's `InsertModelAnnotations3`/`4` and
# `swInsertAnnotation_e` records. Only the members the source research issue
# actually asked for are exposed here (plus a couple of closely-related ones
# that cost nothing to expose) -- the full 25-member bitmask also covers
# axes/curves/planes/sketches/etc., out of scope for "model annotations" as
# this tool understands the phrase.
#
# `center_marks`/`centerlines` are deliberately NOT here: `swInsertAnnotation_e`
# (independently re-fetched from help.solidworks.com for this issue) has no
# center-mark or centerline member at all -- center marks are a wholly
# separate mechanism, `IDrawingDoc::InsertCenterMark3`, explicitly scoped to
# sibling issue sw-1xx.6 ("batch center mark and centerline tools"). The
# task's own acceptance criteria named center marks as part of the default
# `types`, but that can't be satisfied through this bitmask -- confirmed
# against the live enum, not guessed; see sw-1xx.1's issue notes.
_MODEL_ITEM_TYPES = {
    "dimensions": int(SwInsertAnnotation.swInsertDimensions),
    "datums": int(SwInsertAnnotation.swInsertDatums),
    "datum_targets": int(SwInsertAnnotation.swInsertDatumTargets),
    "gtols": int(SwInsertAnnotation.swInsertGTols),
    "surface_finishes": int(SwInsertAnnotation.swInsertSFSymbols),
    "welds": int(SwInsertAnnotation.swInsertWelds),
    "notes": int(SwInsertAnnotation.swInsertNotes),
    "hole_callouts": int(SwInsertAnnotation.swInsertholeCallout),
    "cosmetic_threads": int(SwInsertAnnotation.swInsertCThreads),
    "instance_counts": int(SwInsertAnnotation.swInsertInstanceCounts),
}

# Per the issue's Requirements: "default to dimensions + hole callouts +
# center marks" -- center marks dropped per the Gotcha above.
_DEFAULT_MODEL_ITEM_TYPES = ("dimensions", "hole_callouts")

# `insert_model_items`'s `sources` -> `swImportModelItemsSource_e`, per
# docs/api/03-annotations.md's `InsertModelAnnotations3`/`4` and
# `swImportModelItemsSource_e` records (the *corrected*, post-2008-SP3
# member/value mapping). The task's Requirements additionally asked for a
# "DimXpert" source option, mapped "to the documented source enum" -- but
# `swImportModelItemsSource_e` (independently re-fetched for this issue) has
# exactly these 4 members and no DimXpert member of any kind. DimXpert
# annotation import is a real, but entirely separate, SOLIDWORKS-2025+-only
# mechanism (`IView::ImportAnnotations`'s `IncludeDimXpertAnnotations` flag --
# a boolean toggle, not a source enum, with no per-type `Types` control) --
# out of scope for this `Option`-parameter-driven tool. An unrecognized
# `sources` string (including `"dimxpert"`) fails with `swInvalidInput` rather
# than silently aliasing to a different source.
_MODEL_ITEM_SOURCES = {
    "model": int(SwImportModelItemsSource.swImportModelItemsFromEntireModel),
    "selected_feature": int(SwImportModelItemsSource.swImportModelItemsFromSelectedFeature),
    "selected_component": int(SwImportModelItemsSource.swImportModelItemsFromSelectedComponent),
    "assembly_only": int(SwImportModelItemsSource.swImportModelItemsFromAssemblyOnly),
}
_DEFAULT_MODEL_ITEM_SOURCE = "model"

# `IDrawingDoc::InsertModelAnnotations4`'s positional signature, in the exact
# order documented in docs/api/03-annotations.md: Option, Types, AllViews,
# DuplicateDims, HiddenFeatureDims, UsePlacementInSketch,
# InsertAllAnnotations, InsertAllReferenceGeometry. 8 positional parameters
# -- ComSignature per this issue's working agreement (>6 params). Preferred
# over the 6-param `InsertModelAnnotations3` per the dossier's own Gotchas
# ("prefer it over InsertModelAnnotations3 for new tool-layer code").
# `insert_model_items` always drives type selection through `Types`, so
# `InsertAllAnnotations`/`InsertAllReferenceGeometry` are never exposed as
# tool parameters -- both always bind False. `AllViews` is likewise always
# bound False: `insert_model_items` handles its own `all_views` iteration
# (one call per view, selected atomically) so it can report per-view counts,
# which the single whole-drawing `AllViews=True` call cannot do.
INSERT_MODEL_ANNOTATIONS4 = ComSignature("InsertModelAnnotations4", [
    Param("option", REQUIRED, enum_to_int),
    Param("types", REQUIRED, enum_to_int),
    Param("all_views", False, to_bool),
    Param("duplicate_dims", True, to_bool),
    Param("hidden_feature_dims", False, to_bool),
    Param("use_placement_in_sketch", False, to_bool),
    Param("insert_all_annotations", False, to_bool),
    Param("insert_all_reference_geometry", False, to_bool),
])

# `list_view_entities`' entity-reference shape (`{"kind": "edge"/"vertex"/"face",
# "x", "y", "z"}`) -> `SelectByID2`'s uppercase `Type` string, per
# docs/api/03-annotations.md's `SelectByID2` Type-string table. `add_dimension`/
# `add_ordinate_dimensions` accept entity references in exactly this shape (per
# their own Requirements: "entities is a list of entity references (as returned
# by list_view_entities)"). `add_datum_feature`/`add_gtol` (sw-1xx.4) extend this
# with `"dimension"` -> `"DIMENSION"` (`IDisplayDimension`), per their own
# Requirements ("place a datum tag on a selected edge/face/dimension").
_ENTITY_KIND_TYPE_STR = {
    "edge": "EDGE", "vertex": "VERTEX", "face": "FACE", "dimension": "DIMENSION",
}

# `add_dimension`'s `dimension_type` -> which COM creation call to use, the
# minimum entity count SolidWorks needs to unambiguously produce that dimension
# (per the dossier's AddDimension/AddDimension2/AddHorizontalDimension2/
# AddVerticalDimension2 records: "the selected entities must unambiguously
# define what's being dimensioned"), and the `swDimensionType_e` value that
# dimension type documents as its outcome.
#
# Only "horizontal" and "vertical" have a dedicated creation method
# (AddHorizontalDimension2/AddVerticalDimension2). SolidWorks has no dedicated
# creation call for a radial, diameter, or angular dimension -- confirmed by
# this dossier's own "Dimensions" section: `IModelDoc2::AddDimension2` is the
# *only* generic ("smart") creation call documented, and what dimension type it
# actually produces is inferred by SolidWorks from what's selected (a
# circle/arc -> radial or diameter; two non-parallel lines -> angular; two
# points -> linear), not chosen by any parameter at creation time.
# "smart"/"radial"/"diameter"/"angular" therefore all route through the same
# `AddDimension2` call -- `dim_type_enum` records what each string *documents*
# as the expected result (returned in `data["dim_type_enum"]`). For
# "radial"/"diameter" specifically, `add_dimension` corrects the outcome
# post-creation via `IDisplayDimension::Diametric` (fetched sw-1xx.2, a real,
# documented radius<->diameter toggle for a radial-capable dimension) and
# reports the dimension's actual resulting type via `IDisplayDimension::Type2`
# (also fetched sw-1xx.2) in `data["type_code"]`, so a caller isn't left
# trusting `dim_type_enum` alone.
# `add_gtol`'s `symbol` -> the `IGTOL` library's `<LibraryName-SymbolName>` token
# (gtol.sym), per docs/api/03-annotations.md's GD&T section ("Symbol syntax is
# `<LibraryName-SymbolName>`" / library set `GTOL`/`IGTOL`/`GGTOL`, 14 tolerance
# symbols per library: `ANGULAR, CIRC, CONC, CYL, FLAT, LPROF, PARA, PERP, POSI,
# SPROF, SRUN, STRAIGHT, SYMMETRY, TRUN`). This project always uses the `IGTOL`
# (ISO) library, matching the dossier's own official worked example
# (`<IGTOL-POSI>`) rather than the ASME `GTOL`/`GGTOL` variants.
_GTOL_SYMBOLS = {
    "straightness": "STRAIGHT",
    "flatness": "FLAT",
    "circularity": "CIRC",
    "cylindricity": "CYL",
    "profile_of_a_line": "LPROF",
    "profile_of_a_surface": "SPROF",
    "angularity": "ANGULAR",
    "perpendicularity": "PERP",
    "parallelism": "PARA",
    "position": "POSI",
    "concentricity": "CONC",
    "symmetry": "SYMMETRY",
    "circular_runout": "SRUN",
    "total_runout": "TRUN",
}

# Form tolerances (per ASME Y14.5) apply to a single feature in isolation and
# can never carry a datum reference -- `add_gtol` rejects `datums` for these.
_GTOL_FORM_SYMBOLS = {"straightness", "flatness", "circularity", "cylindricity"}

# Orientation/location/runout tolerances are meaningless without at least one
# datum reference -- `add_gtol` requires a non-empty `datums` for these (the
# task's own Acceptance Criteria calls this out explicitly for "position").
# Profile-of-a-line/profile-of-a-surface are deliberately excluded: a profile
# tolerance may legally control form alone, with no datum reference.
_GTOL_DATUM_REQUIRED_SYMBOLS = {
    "position", "perpendicularity", "parallelism", "angularity",
    "concentricity", "symmetry", "circular_runout", "total_runout",
}

# `add_gtol`'s `material_condition` / per-datum modifier -> the `MOD` library's
# token, per the GD&T section's `SetFrameSymbols2` Gotchas (`<MOD-MMC>`/
# `<MOD-LMC>` confirmed from the official worked example; `<MOD-RFS>` per this
# dossier's sw-1xx.4 addendum -- search-corroborated, not independently
# verified against a live session).
_GTOL_MATERIAL_CONDITIONS = {
    "MMC": "<MOD-MMC>",
    "LMC": "<MOD-LMC>",
    "RFS": "<MOD-RFS>",
}

# Datum letters ASME Y14.5 reserves and never assigns (easily confused with
# digits/other symbols) -- `add_datum_feature`'s auto-lettering skips these,
# and rejects them if explicitly requested as `label`.
_GTOL_RESERVED_DATUM_LETTERS = {"I", "O", "Q"}

# `add_datum_feature`'s `style` -> `IDatumTag::SetDisplayStyle`'s `Style`
# (`swDatumDisplayType_e`, per docs/api/03-annotations.md's Enums section).
_DATUM_DISPLAY_STYLES = {
    "default": int(SwDatumDisplayType.swDatumDisplayType_Default),
    "square": int(SwDatumDisplayType.swDatumDisplayType_Square),
    "round": int(SwDatumDisplayType.swDatumDisplayType_Round),
}

# `add_datum_target`'s `area_type` -> `InsertDatumTargetSymbol3`'s `AreaStyle`,
# per that record's Parameters table ("0 = point, 1 = circle, 2 = rectangle").
_DATUM_TARGET_AREA_TYPES = {"point": 0, "circle": 1, "rectangle": 2}

# `IGtol::SetFrameSymbols2`'s positional signature, in the exact order
# documented in docs/api/03-annotations.md: FrameNumber, GCS, TolDia1, TolMC1,
# TolDia2, TolMC2, DatumMC1, DatumMC2, DatumMC3. 9 positional parameters --
# ComSignature per this issue's working agreement (>6 params). `add_gtol`
# never populates a second tolerance value or `DatumMC1..3` (the dossier's own
# Gotchas flag the official worked example embedding MOD tokens inline in
# `SetFrameValues2`'s Datum1/2/3 strings instead, treated here as the safe,
# officially-demonstrated pattern) -- both always bind their own defaults.
SET_FRAME_SYMBOLS2 = ComSignature("SetFrameSymbols2", [
    Param("frame_number", REQUIRED, enum_to_int),
    Param("gcs", REQUIRED),
    Param("tol_dia1", False, to_bool),
    Param("tol_mc1", ""),
    Param("tol_dia2", False, to_bool),
    Param("tol_mc2", ""),
    Param("datum_mc1", ""),
    Param("datum_mc2", ""),
    Param("datum_mc3", ""),
])

# `IModelDocExtension::InsertDatumTargetSymbol3`'s positional signature, in the
# exact order documented in docs/api/03-annotations.md: Datum1, Datum2, Datum3,
# AreaStyle, AreaOutside, Value1, Value2, ValueStr1, ValueStr2, ArrowsSmart,
# ArrowStyle, LeaderLineStyle, LeaderBent, ShowArea, ShowSymbol,
# MoveableDatumStyle. 16 positional parameters -- ComSignature per this issue's
# working agreement (>6 params). `add_datum_target` exposes only `label`/
# `area_type`/`size`, so the leader/arrow/moveable-style cosmetics all bind
# their own SolidWorks-sensible defaults (smart arrows on, solid leader, area
# + symbol both shown).
INSERT_DATUM_TARGET_SYMBOL3 = ComSignature("InsertDatumTargetSymbol3", [
    Param("datum1", REQUIRED),
    Param("datum2", ""),
    Param("datum3", ""),
    Param("area_style", REQUIRED, enum_to_int),
    Param("area_outside", False, to_bool),
    Param("value1", 0.0, to_meters),
    Param("value2", 0.0, to_meters),
    Param("value_str1", ""),
    Param("value_str2", ""),
    Param("arrows_smart", True, to_bool),
    Param("arrow_style", 0, enum_to_int),
    Param("leader_line_style", 0, enum_to_int),
    Param("leader_bent", False, to_bool),
    Param("show_area", True, to_bool),
    Param("show_symbol", True, to_bool),
    Param("moveable_datum_style", 0, enum_to_int),
])

_DIMENSION_TYPES = {
    "smart": {
        "method": "smart", "min_entities": 1,
        "dim_type_enum": int(SwDimensionType.swDimensionTypeUnknown),
    },
    "horizontal": {
        "method": "horizontal", "min_entities": 2,
        "dim_type_enum": int(SwDimensionType.swHorLinearDimension),
    },
    "vertical": {
        "method": "vertical", "min_entities": 2,
        "dim_type_enum": int(SwDimensionType.swVertLinearDimension),
    },
    "radial": {
        "method": "smart", "min_entities": 1,
        "dim_type_enum": int(SwDimensionType.swRadialDimension),
    },
    "diameter": {
        "method": "smart", "min_entities": 1,
        "dim_type_enum": int(SwDimensionType.swDiameterDimension),
    },
    "angular": {
        "method": "smart", "min_entities": 2,
        "dim_type_enum": int(SwDimensionType.swAngularDimension),
    },
}

# `add_ordinate_dimensions`'s `direction` -> `IModelDocExtension::
# AddOrdinateDimension`'s `DimType` (swAddOrdinateDims_e).
_ORDINATE_DIRECTIONS = {
    "auto": int(SwAddOrdinateDims.swOrdinate),
    "horizontal": int(SwAddOrdinateDims.swHorizontalOrdinate),
    "vertical": int(SwAddOrdinateDims.swVerticalOrdinate),
    "angular": int(SwAddOrdinateDims.swAngularOrdinate),
}

# `autodimension_view`'s string params -> their `swAutodim*_e` values.
# `swAutodimSchemeCenterline` is deliberately excluded from `_AUTODIM_SCHEMES`
# -- the dossier's own `AutoDimension` Gotchas quote it as "Not supported in
# sketches or drawings; do not use".
_AUTODIM_SCHEMES = {
    "baseline": int(SwAutodimScheme.swAutodimSchemeBaseline),
    "ordinate": int(SwAutodimScheme.swAutodimSchemeOrdinate),
    "chain": int(SwAutodimScheme.swAutodimSchemeChain),
}
_AUTODIM_ENTITIES = {
    "all": int(SwAutodimEntities.swAutodimEntitiesAll),
    "based_on_preselect": int(SwAutodimEntities.swAutodimEntitiesBasedOnPreselect),
    "selected": int(SwAutodimEntities.swAutodimEntitiesSelected),
}
_AUTODIM_HORIZONTAL_PLACEMENTS = {
    "above": int(SwAutodimHorizontalPlacement.swAutodimHorizontalPlacementAbove),
    "below": int(SwAutodimHorizontalPlacement.swAutodimHorizontalPlacementBelow),
}
_AUTODIM_VERTICAL_PLACEMENTS = {
    "left": int(SwAutodimVerticalPlacement.swAutodimVerticalPlacementLeft),
    "right": int(SwAutodimVerticalPlacement.swAutodimVerticalPlacementRight),
}


def _parse_entity_ref(entity: Any) -> Tuple[Optional[Tuple[str, float, float, float]], Optional[str]]:
    """One `add_dimension`/`add_ordinate_dimensions` entity reference ->
    `(type_str, x, y, z)` (caller's default unit, unconverted) or an error
    message -- exactly one of the two return slots is populated.

    Accepts the shape `list_view_entities` returns (`kind`/`x`/`y`/`z`), plus
    `type` as an alias for `kind` for a caller that already has a raw
    `SelectByID2` type string handy. `z` defaults to `0` -- `list_view_entities`
    always supplies one, but a caller building a reference by hand for a 2D
    drawing view often won't.
    """
    if not isinstance(entity, dict):
        return None, f"entity reference must be an object, got {type(entity).__name__}"

    kind_raw = entity.get("kind", entity.get("type"))
    kind = (kind_raw or "").strip().lower() if isinstance(kind_raw, str) else ""
    type_str = _ENTITY_KIND_TYPE_STR.get(kind)
    if type_str is None:
        return None, (
            f"unknown entity kind {kind_raw!r}; expected one of "
            f"{sorted(_ENTITY_KIND_TYPE_STR)!r}"
        )

    x, y = entity.get("x"), entity.get("y")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) \
            or not isinstance(y, (int, float)):
        return None, f"entity reference needs numeric x/y, got {entity!r}"

    z = entity.get("z", 0)
    if isinstance(z, bool) or not isinstance(z, (int, float)):
        z = 0

    return (type_str, float(x), float(y), float(z)), None


def _enum_name(enum_cls, code: Any) -> str:
    """Readable member name for a `swconst` return/status code, or a
    `f"unknown status {code!r}"` fallback for a code the enum doesn't declare
    -- so an unrecognized status is diagnosable from the message rather than
    silently rendered as a bare number."""
    try:
        return enum_cls(code).name
    except (ValueError, TypeError):
        return f"unknown status {code!r}"


class DrawingOperations:
    """
    Mixin class for drawing document operations

    Requires parent class to have:
    - self._sw_app: SolidWorks application object
    - self.is_connected: Connection status property
    - self.connect(): Connection method
    - self._result(): Result factory method
    - self._units: UnitConverter instance

    Also uses `self.get_active_doc()` (defined on the base automation class)
    the same way the other operation mixins do.
    """

    def get_drawing_doc(self) -> Tuple[Any, Optional[Dict]]:
        """
        Get the active document with auto-connect, verifying it is a drawing.

        Like `get_active_doc`, but also checks `IModelDoc2::GetType` and
        fails with a clear error if the active document is not a drawing.

        Returns:
            Tuple of (document, error_result)
            - If successful: (document, None)
            - If failed (not connected, no active doc, or the active
              document isn't a drawing): (None, error_dict)
        """
        doc, err = self.get_active_doc()
        if err:
            return None, err

        doc_type = self._get_doc_type(doc)
        if doc_type != int(SwDocumentTypes.swDocDRAWING):
            type_name = SwDocumentTypes.name_of(doc_type)
            return None, self._result(
                False,
                f"Active document is a {type_name}, not a drawing. "
                "Open or create a drawing document first.",
                SwErrors.swInvalidInput,
            )

        return doc, None

    def _get_doc_type(self, doc) -> Optional[int]:
        """Get document type code (handles property/method difference)"""
        try:
            doc_type = doc.GetType
            if callable(doc_type):
                return doc_type()
            return doc_type
        except:
            return None

    # ========================================================================
    # Document / session tools
    # ========================================================================

    def get_document_type(self) -> Dict:
        """
        Tell part/assembly/drawing apart via `IModelDoc2::GetType`, mapped to
        a readable name via `SwDocumentTypes`. Works against whatever
        document type is active -- unlike `get_drawing_doc`, this never
        rejects a non-drawing active document, since its whole job is
        telling the types apart.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        doc_type = self._get_doc_type(doc)
        type_name = SwDocumentTypes.name_of(doc_type)

        return self._result(
            True, f"Active document is a {type_name}", SwErrors.swSuccess,
            {"type": type_name, "type_code": doc_type},
        )

    def new_drawing_from_template(
        self, template_path: Optional[str] = None, paper_size: str = "A3",
        orientation: str = "landscape", scale_num: float = 1, scale_denom: float = 1,
    ) -> Dict:
        """
        Create a new drawing document via `ISldWorks::NewDocument`.

        Args:
            template_path: Path to a `.drwdot` template. When omitted, falls
                back to `utils.sw_finder.find_template("drawing")`; if that
                also finds nothing, fails with `swTemplateNotFound`.
            paper_size: One of `"A"`, `"B"`, `"C"`, `"D"`, `"E"`, `"A0"`-`"A4"`
                (case-insensitive) -- resolved to `swDwgPaperSizes_e` and
                passed as `NewDocument`'s `PaperSize` argument.
            orientation: `"landscape"` (default) or `"portrait"`
                (case-insensitive; anything else fails with
                `swInvalidInput`). Only `"A"` and `"A4"` have a documented
                vertical/portrait paper-size variant; other sizes ignore
                this and use the landscape value.
            scale_num, scale_denom: `NewDocument` has no scale parameter --
                sheet scale is a `SetupSheet5`/`SetupSheet6` concern (a later
                sheet-management tool), not this one. Echoed back in `data`
                as the caller's requested values, not applied here.

        Returns:
            Result dict; on success, `data` has `name` (document title) and
            `sheet_name` (the first sheet `GetSheetNames` reports).
        """
        if not self.is_connected:
            r = self.connect()
            if not r["success"]:
                return r

        if not template_path:
            template_path = find_template("drawing")
        if not template_path:
            return self._result(
                False,
                "No drawing template found. Pass template_path explicitly, "
                "or install a default .drwdot template.",
                SwErrors.swTemplateNotFound,
            )

        sizes = _PAPER_SIZES.get(paper_size.upper())
        if sizes is None:
            return self._result(
                False,
                f"Unknown paper_size {paper_size!r}; expected one of "
                f"{sorted(_PAPER_SIZES)!r}",
                SwErrors.swInvalidInput,
            )
        landscape_size, portrait_size = sizes
        # Normalized like `paper_size` above -- a caller passing "Portrait"
        # would otherwise silently get the landscape size, with `data`
        # echoing back the requested "Portrait" and hiding the mismatch.
        orientation_key = orientation.lower()
        if orientation_key not in ("landscape", "portrait"):
            return self._result(
                False,
                f"Unknown orientation {orientation!r}; expected "
                "'landscape' or 'portrait'",
                SwErrors.swInvalidInput,
            )
        paper_size_value = (
            portrait_size if orientation_key == "portrait" and portrait_size is not None
            else landscape_size
        )

        try:
            doc = self._sw_app.NewDocument(template_path, int(paper_size_value), 0, 0)
        except Exception as e:
            logger.error(f"new_drawing_from_template error: {e}")
            return self._result(False, f"Create drawing error: {e}", SwErrors.swFileLoadError)

        if doc is None:
            return self._result(
                False, f"Failed to create drawing from template {template_path!r}",
                SwErrors.swFileLoadError,
            )

        title = self._get_doc_title(doc)
        try:
            sheet_names = doc.GetSheetNames() or []
        except Exception:
            sheet_names = []
        if not isinstance(sheet_names, (list, tuple)):
            sheet_names = []
        sheet_name = sheet_names[0] if sheet_names else None

        return self._result(
            True, f"Created drawing: {title}", SwErrors.swSuccess,
            {
                "name": title, "sheet_name": sheet_name, "template_path": template_path,
                "paper_size": paper_size, "orientation": orientation,
                # NewDocument has no scale parameter -- these are the
                # caller's requested values, not (yet) applied to the sheet.
                # Sheet scale is set by the sheet-setup tools (SetupSheet5/6).
                "requested_scale": {"num": scale_num, "denom": scale_denom},
            },
        )

    def open_or_activate_document(self, filepath: str, read_only: bool = False,
                                   lightweight: bool = False) -> Dict:
        """
        Open `filepath` via `ISldWorks::OpenDoc6`, or -- if *this same file*
        is already loaded -- bring it to the foreground via
        `ISldWorks::ActivateDoc3` instead (`OpenDoc6` does not activate an
        already-loaded document, per the dossier's Gotchas).
        """
        if not self.is_connected:
            r = self.connect()
            if not r["success"]:
                return r

        if not os.path.exists(filepath):
            return self._result(False, f"File not found: {filepath}", SwErrors.swFileNotFoundError)

        title = os.path.basename(filepath)
        existing, existing_title = self._find_open_document(title, filepath)

        if existing is not None:
            errors = com_backend.byref_int()
            try:
                activated = self._sw_app.ActivateDoc3(existing_title, True, 0, errors)
            except Exception as e:
                logger.error(f"open_or_activate_document activate error: {e}")
                return self._result(False, f"Activate error: {e}", SwErrors.swFileLoadError)

            if activated is None:
                return self._result(
                    False, f"Failed to activate {existing_title} (error {errors.value})",
                    SwErrors.swFileLoadError,
                )

            return self._result(
                True, f"Activated: {existing_title}", SwErrors.swSuccess,
                {"name": existing_title, "path": filepath, "activated": True},
            )

        doc_type = SwFileTypes.doc_type_for(os.path.splitext(filepath)[1])

        options = 0
        if read_only:
            options |= _OPEN_DOC_OPTION_READ_ONLY
        if lightweight:
            options |= _OPEN_DOC_OPTION_LOAD_LIGHTWEIGHT

        errors = com_backend.byref_int()
        warnings = com_backend.byref_int()
        try:
            doc = self._sw_app.OpenDoc6(filepath, int(doc_type), options, "", errors, warnings)
        except Exception as e:
            logger.error(f"open_or_activate_document open error: {e}")
            return self._result(False, f"Open error: {e}", SwErrors.swFileLoadError)

        # `OpenDoc6` can hand back a document *and* a nonzero
        # `swFileLoadError_e` bitmask (partial load, repair required,
        # future-version file). Reporting plain success there would hide a
        # diagnosis `DocumentOperations.open_document` already surfaces.
        if doc is None or errors.value != 0:
            return self._result(
                False, f"Failed to open {filepath} (error {errors.value})",
                SwErrors.swFileLoadError,
            )

        opened_title = self._get_doc_title(doc)
        return self._result(
            True, f"Opened: {opened_title}", SwErrors.swSuccess,
            {"name": opened_title, "path": filepath, "activated": False},
        )

    def _find_open_document(self, title: str, path: str) -> Tuple[Any, Optional[str]]:
        """The already-open document (per `ISldWorks::GetFirstDocument`/
        `IModelDoc2::GetNext`) that *is* the file at `path`, or
        `(None, None)`.

        Both a title and a path, because neither alone is enough. Titles are
        compared case-insensitively, since `IModelDoc2::GetTitle` returns
        SolidWorks' own casing for the file extension (e.g.
        `"Bracket.SLDPRT"`), which won't match a caller-supplied path's
        casing (e.g. `"Bracket.sldprt"`) -- and the matched title is what
        gets returned, so the caller passes `ActivateDoc3` the exact string
        SolidWorks itself reported. But a title is only a basename:
        `rev_a\\Bracket.slddrw` and `rev_b\\Bracket.slddrw` share one, so
        matching on it alone would activate whichever revision happened to
        be open while reporting success against the path the caller asked
        for -- and the caller would go on to edit and save the wrong file.
        Hence the `IModelDoc2::GetPathName` confirmation. A document
        reporting no path (never saved, still "Draw1") never matches a file
        on disk.
        """
        target = title.lower()
        target_path = os.path.normcase(os.path.abspath(path))
        try:
            doc = self._sw_app.GetFirstDocument()
        except Exception:
            return None, None

        while doc:
            doc_title = self._get_doc_title(doc)
            if doc_title and str(doc_title).lower() == target:
                doc_path = self._get_doc_path(doc)
                if doc_path and os.path.normcase(os.path.abspath(str(doc_path))) == target_path:
                    return doc, doc_title

            try:
                doc = doc.GetNext()
            except Exception:
                break

        return None, None

    def rebuild_document(self, force: bool = True, top_level_only: bool = False) -> Dict:
        """
        Rebuild the active document -- `IModelDoc2::ForceRebuild3` (`force`)
        or the cheaper incremental `IModelDoc2::EditRebuild3` otherwise.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        try:
            if force:
                rebuilt = doc.ForceRebuild3(top_level_only)
            else:
                rebuilt = doc.EditRebuild3()
        except Exception as e:
            logger.error(f"rebuild_document error: {e}")
            return self._result(False, f"Rebuild error: {e}", SwErrors.swUnknownError)

        data = {"force": force, "top_level_only": top_level_only}
        if not rebuilt:
            return self._result(False, "Rebuild failed", SwErrors.swUnknownError, data)

        return self._result(True, "Rebuild successful", SwErrors.swSuccess, data)

    # ========================================================================
    # Shared export primitives
    # ========================================================================
    #
    # Every export tool below (`export_pdf`, `export_dxf_dwg`,
    # `export_edrawings`, and `batch_export_pack`'s native archive copy) is
    # the same four steps in the same order: validate which sheets to export,
    # prepare the output path, apply the user preferences that format needs
    # (restoring them afterward no matter how the call ends), then drive
    # `SaveAs3` and decode its byref `Errors`/`Warnings`. Each of those four
    # steps lives here exactly once so a format tool contains only what is
    # actually specific to its format.

    def _prepare_output_path(
        self, output_path: str, *, expected_ext: Optional[str] = None,
        probe_writable: bool = False,
    ) -> Tuple[str, Optional[Dict]]:
        """Absolutize `output_path`, check its extension, and create its
        parent directory -- returning `(path, None)` or `(path, error_result)`.

        Args:
            expected_ext: Required lowercase extension including the dot
                (e.g. `".dxf"`). `None` skips the check (PDF export accepts
                any extension the caller asks for, as `SaveAs3` keys the
                conversion off it).
            probe_writable: Open the target for append and delete it again if
                the probe created it, so an unwritable destination fails here
                with a diagnosis rather than as whatever generic COM
                exception `SaveAs3` happens to raise. The single most common
                real-world export failure is the target file already being
                open in a viewer.
        """
        output_path = os.path.abspath(output_path)

        if expected_ext is not None and os.path.splitext(output_path)[1].lower() != expected_ext:
            return output_path, self._result(
                False,
                f"output_path must end with {expected_ext!r}, got {output_path!r}",
                SwErrors.swInvalidInput)

        dir_path = os.path.dirname(output_path)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
            except OSError as e:
                return output_path, self._result(
                    False, f"Could not create output directory {dir_path!r}: {e}",
                    SwErrors.swExportError)

        if probe_writable:
            existed_before = os.path.exists(output_path)
            try:
                with open(output_path, "ab"):
                    pass
            except OSError as e:
                return output_path, self._result(
                    False,
                    f"Cannot write to {output_path!r} -- the file may be open in "
                    f"another program (e.g. a PDF viewer) or the location is not "
                    f"writable: {e}",
                    SwErrors.swExportError,
                )
            if not existed_before:
                try:
                    os.remove(output_path)
                except OSError:
                    pass

        return output_path, None

    def _resolve_export_sheets(
        self, doc: Any, sheets: Any, *, allow_list: bool = True,
    ) -> Tuple[List[str], str, Optional[Dict]]:
        """Resolve an export tool's `sheets` argument into
        `(sheet_names, mode, error_result)`, where `mode` is `"all"`,
        `"current"`, or `"list"`.

        Shared by every export tool so "which sheets does this mean" is
        answered one way. An explicit list is validated against
        `IDrawingDoc::GetSheetNames` *before* any COM export call -- an
        unknown name fails fast with the available sheet names in the
        message, rather than surfacing whatever `SetSheets`/`SaveAs3` would
        have done with a bad name (undocumented on either method's page).

        Args:
            allow_list: `False` for a format with no "these specific sheets"
                mode of its own (eDrawings -- `swEdrawingSaveAsOption_e`'s
                third member saves the current `ISelectionMgr` selection, not
                a named-sheet list), which then rejects a list outright
                instead of silently reinterpreting it.
        """
        try:
            available_sheets = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            logger.error(f"GetSheetNames error: {e}")
            return [], "", self._result(
                False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)

        if isinstance(sheets, str) and sheets == "all":
            if not available_sheets:
                return [], "all", self._result(
                    False, "Drawing has no sheets to export", SwErrors.swFeatureError)
            return available_sheets, "all", None

        if isinstance(sheets, str) and sheets == "current":
            try:
                current_sheet = doc.GetCurrentSheet()
            except Exception:
                current_sheet = None
            current_name = self._read_prop(current_sheet, "Name") if current_sheet else None
            if not current_name:
                return [], "current", self._result(
                    False, "Could not determine the active sheet's name",
                    SwErrors.swFeatureError)
            return [current_name], "current", None

        if allow_list and isinstance(sheets, (list, tuple)):
            requested = list(sheets)
            unknown = [s for s in requested if s not in available_sheets]
            if unknown:
                return [], "list", self._result(
                    False,
                    f"Unknown sheet(s) {unknown!r}; available sheets: "
                    f"{available_sheets!r}",
                    SwErrors.swInvalidInput,
                    {"unknown_sheets": unknown, "available_sheets": available_sheets},
                )
            return requested, "list", None

        expected = (
            "'all', 'current', or a list of sheet names" if allow_list
            else "'all' or 'current'"
        )
        return [], "", self._result(
            False, f"sheets must be {expected}, got {sheets!r}", SwErrors.swInvalidInput)

    @contextmanager
    def _user_preference(self, pref: Any, value: Any):
        """Set the `ISldWorks` user preference `pref` to `value` for the
        duration of the block, restoring whatever it held on entry when the
        block exits -- normally, by exception, or by an early `return`.

        The getter/setter pair and the inbound coercion come from
        `_PREFERENCE_ACCESSORS`, keyed by `pref`'s own enum class, so a
        toggle can't accidentally be written through the integer setter (a
        silent no-op rather than an error). Compose several with the
        `ExitStack` this module already uses for `selected()`, and they
        unwind last-in-first-out.

        Raises:
            _PreferenceError: if reading or writing the preference raises, or
                if the setter reports failure through its documented `Boolean`
                return (`SetUserPreferenceIntegerValue`/
                `SetUserPreferenceStringListValue` -- see
                `_PREFERENCE_ACCESSORS`; `SetUserPreferenceToggle` is a `Sub`
                and has no status to check). A refused write raises nothing on
                its own, so without this check a tool would export under
                whatever setting the session happened to hold and still report
                success. A tool that can't establish the setting it needs must
                fail rather than export under an inherited one -- exactly the
                kind of silent output change these tools exist to rule out.
        """
        accessors = _PREFERENCE_ACCESSORS.get(type(pref))
        if accessors is None:
            raise _PreferenceError(
                f"No user-preference accessor is declared for {type(pref).__name__}")
        getter_name, setter_name, coerce, setter_reports_status = accessors
        pref_id = int(pref)

        try:
            original = getattr(self._sw_app, getter_name)(pref_id)
        except Exception as e:
            logger.error(f"read preference {pref!r} error: {e}")
            raise _PreferenceError(f"Read preference error: {e}")

        try:
            set_ok = getattr(self._sw_app, setter_name)(pref_id, coerce(value))
        except Exception as e:
            logger.error(f"set preference {pref!r} error: {e}")
            raise _PreferenceError(f"Set preference error: {e}")
        if setter_reports_status and not set_ok:
            logger.error(f"set preference {pref!r} refused by {setter_name}")
            raise _PreferenceError(
                f"{setter_name} refused to set {pref!r} to {value!r}")

        try:
            yield
        finally:
            try:
                getattr(self._sw_app, setter_name)(pref_id, original)
            except Exception as e:
                logger.error(f"restore preference {pref!r} error: {e}")

    @contextmanager
    def _shown_hidden_layers(self, doc: Any):
        """Temporarily make every hidden layer (`ILayer::Visible == False`,
        via `ILayerMgr::GetLayerList`/`GetLayer`) visible for the duration of
        the block, restoring each to hidden on exit.

        This is `export_pdf`'s `keep_invisible_layers`: SolidWorks has no
        documented, numerically verifiable `IExportPdfData`/user-preference
        lever for "include hidden layers in this export"
        (`swPDFExportIncludeLayersNotToPrint` is both semantically distinct --
        it's about `ILayer::Printable`, not `ILayer::Visible` -- and has no
        published numeric value anywhere; see docs/api/05-export-and-layers.md's
        Enums section). Layer visibility is the one documented, unambiguous
        lever that actually controls whether hidden-layer geometry renders
        into any export.

        `ILayer::Visible`'s own Gotchas warn that setting `Visible` can change
        `ILayer::Printable` as a side effect, so each touched layer's
        `Printable` is snapshotted before `Visible` is flipped and re-asserted
        (Visible first, then Printable, per that record's documented ordering)
        after `Visible` is restored -- without this, the export could silently
        leave a layer's printable state different from what it found.
        """
        # Each entry is (layer, prior_printable).
        restore_layers: List[Tuple[Any, Any]] = []
        try:
            layer_mgr = doc.GetLayerManager()
            layer_names = list(layer_mgr.GetLayerList() or []) if layer_mgr else []
        except Exception as e:
            logger.error(f"GetLayerManager error: {e}")
            layer_names = []

        for name in layer_names:
            try:
                layer = layer_mgr.GetLayer(name)
            except Exception as e:
                logger.error(f"GetLayer({name!r}) error: {e}")
                continue
            if layer is None:
                continue
            # `_com_bool`, not `is False`: an interop layer that hands back
            # `VARIANT_BOOL` as `0` rather than `False` would otherwise make
            # this whole pass -- and `export_pdf(keep_invisible_layers=True)`
            # with it -- a silent no-op.
            if _com_bool(self._read_prop(layer, "Visible")) is False:
                prior_printable = _com_bool(self._read_prop(layer, "Printable"))
                try:
                    layer.Visible = True
                    restore_layers.append((layer, prior_printable))
                except Exception as e:
                    logger.error(f"show layer {name!r} error: {e}")

        try:
            yield
        finally:
            for layer, prior_printable in restore_layers:
                try:
                    layer.Visible = False
                    # `prior_printable` is already `_com_bool`-normalized, so
                    # `None` here means "the snapshot read gave no usable
                    # value" -- the only case where re-asserting would write a
                    # guess over whatever `Visible` did to it.
                    if prior_printable is not None:
                        layer.Printable = prior_printable
                except Exception as e:
                    logger.error(f"restore layer visibility error: {e}")

    @contextmanager
    def _active_sheet_restored(self, doc: Any):
        """Re-activate whichever sheet was current on entry when the block
        exits -- normally, by exception, or by an early `return`.

        Any export that walks sheets one at a time has to call
        `IDrawingDoc::ActivateSheet`, which leaves the *last* sheet visited
        active. Every other session mutation in this file is
        snapshot-and-restored (user preferences via `_user_preference`, layer
        visibility via `_shown_hidden_layers`), and the active sheet is no
        different: without this, a caller that does `activate_sheet("Sheet1")`
        then a per-sheet export then `export_pdf(sheets="current")` gets a PDF
        of whatever sheet the export happened to stop on.

        Best-effort by design: if the sheet name can't be read on entry, or
        re-activating it fails on exit, that is logged rather than raised --
        failing an otherwise-successful export over a cosmetic UI state would
        be the worse trade.
        """
        original_name = None
        try:
            current_sheet = doc.GetCurrentSheet()
            if current_sheet is not None:
                original_name = self._read_prop(current_sheet, "Name")
        except Exception as e:
            logger.error(f"read active sheet for restore error: {e}")

        try:
            yield
        finally:
            if isinstance(original_name, str) and original_name:
                try:
                    doc.ActivateSheet(original_name)
                except Exception as e:
                    logger.error(f"restore active sheet {original_name!r} error: {e}")

    def _save_as3(
        self, doc: Any, path: str, *, label: str,
        options: Any = SwSaveAsOptions.swSaveAsOptions_Silent,
        export_data: Any = None, extra_data: Optional[Dict] = None,
        raise_com_errors: bool = False,
    ) -> Dict:
        """Drive `IModelDocExtension::SaveAs3` at `path` and turn its result
        into this project's standard result dict.

        The one place every *export* path calls `SaveAs3`, so the byref
        `Errors`/`Warnings` decoding, the "a nonzero `Errors` bitmask fails
        even if the boolean return claimed success" rule, and the on-disk
        existence check are defined once rather than per format.
        `save_drawing` is the only other call site in this module -- it binds
        through the same `SAVE_AS3` signature, but keeps its own call because
        it has to choose between `Save3` and `SaveAs3` and reports "Saved:"
        rather than an export label. A `SaveAs3`
        call that returns `True` with `Errors == 0` but writes no file is a
        real, distinct failure mode from either of the other two, so it's
        checked explicitly rather than trusted.

        Args:
            label: Human-readable operation name for the messages, e.g.
                `"PDF export"` -- used as `"{label} failed: ..."` and
                `"{label} error: ..."`.
            options: `swSaveAsOptions_e` bitmask; `swSaveAsOptions_Silent`
                unless a caller needs more (`_save_native_copy` adds
                `swSaveAsOptions_Copy`).
            export_data: A PDF `IExportPdfData`, or `None` for every other
                format (that parameter is PDF-only).
            extra_data: Format-specific keys merged into the returned
                `data` dict, present on both the success and failure paths.
            raise_com_errors: Let a `SaveAs3` exception propagate instead of
                becoming a `"{label} error: ..."` result. For a caller that
                has to classify the exception itself -- `export_edrawings`
                reads the message to tell "the add-in isn't loaded" apart
                from an ordinary COM failure, which it can only do with the
                exception in hand.

        Returns:
            Result dict whose `data` always has `path`, `errors`, `warnings`,
            and `decoded_errors`, plus `size_bytes` on success.
        """
        errors = com_backend.byref_int()
        warnings = com_backend.byref_int()
        data: Dict[str, Any] = dict(extra_data or {})
        data["path"] = path

        try:
            args = SAVE_AS3.bind(
                path=path, options=options, export_data=export_data,
                errors=errors, warnings=warnings,
            )
            saved = doc.Extension.SaveAs3(*args)
        except Exception as e:
            if raise_com_errors:
                raise
            logger.error(f"{label} error: {e}")
            return self._result(
                False, f"{label} error: {e}", SwErrors.swFileSaveError, data)

        error_code = int(errors.value or 0)
        warning_code = int(warnings.value or 0)
        decoded = decode_save_error(error_code)
        data.update({
            "errors": error_code, "warnings": warning_code, "decoded_errors": decoded,
        })

        if not saved or error_code != 0:
            reason = decoded if error_code != 0 else "SaveAs3 returned false"
            return self._result(
                False, f"{label} failed: {reason}", SwErrors.swFileSaveError, data)

        if not os.path.exists(path):
            return self._result(
                False,
                f"SaveAs3 reported success but no file was written to {path!r}",
                SwErrors.swExportError, data,
            )

        data["size_bytes"] = os.path.getsize(path)
        return self._result(True, f"{label} complete: {path}", SwErrors.swSuccess, data)

    def save_drawing(self, filepath: Optional[str] = None) -> Dict:
        """
        Save the active document -- `IModelDoc2::Save3` in place, or
        `IModelDocExtension::SaveAs3` when `filepath` is given -- decoding
        the `Errors`/`Warnings` byref outputs via `decode_save_error`. A
        nonzero `Errors` bitmask fails the result even if the call's own
        boolean return claimed success, so a partial/warned save can't
        silently read as a clean one.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        errors = com_backend.byref_int()
        warnings = com_backend.byref_int()

        try:
            if filepath:
                filepath = os.path.abspath(filepath)
                dir_path = os.path.dirname(filepath)
                if dir_path and not os.path.exists(dir_path):
                    os.makedirs(dir_path)

                # Bound through `SAVE_AS3` rather than hand-transcribed: this
                # is the same 7-positional call the `ComSignature` exists for,
                # and a transposed `version`/`options` pair here would be a
                # silently wrong save. `export_data`/`advanced_options` default
                # to a null `VT_DISPATCH` via `to_optional_object`.
                args = SAVE_AS3.bind(path=filepath, errors=errors, warnings=warnings)
                saved = doc.Extension.SaveAs3(*args)
                saved_path = filepath
            else:
                saved = doc.Save3(int(SwSaveAsOptions.swSaveAsOptions_Silent), errors, warnings)
                saved_path = self._get_doc_path(doc)
        except Exception as e:
            logger.error(f"save_drawing error: {e}")
            return self._result(False, f"Save error: {e}", SwErrors.swFileSaveError)

        error_code = int(errors.value or 0)
        warning_code = int(warnings.value or 0)
        decoded = decode_save_error(error_code)
        data = {
            "path": saved_path, "errors": error_code, "warnings": warning_code,
            "decoded_errors": decoded,
        }

        if not saved or error_code != 0:
            reason = decoded if error_code != 0 else "Save3/SaveAs3 returned false"
            return self._result(False, f"Save failed: {reason}", SwErrors.swFileSaveError, data)

        return self._result(True, f"Saved: {saved_path}", SwErrors.swSuccess, data)

    def export_pdf(
        self, output_path: str, sheets: Any = "all", open_after: bool = False,
        keep_invisible_layers: bool = False, high_quality: bool = True,
    ) -> Dict:
        """
        Export the active drawing to PDF via `IModelDocExtension::SaveAs3` +
        an `IExportPdfData` built from `ISldWorks::GetExportFileData`, per
        docs/api/05-export-and-layers.md. Decodes the `Errors`/`Warnings`
        byref outputs via `decode_save_error`, the same nonzero-error-bits-
        fail-even-if-the-bool-return-is-true rule `save_drawing` enforces.

        Args:
            output_path: Destination `.pdf` path. Its parent directory is
                created if missing. Checked for writability (a probe open,
                deleted again if it created the file) before any COM call is
                made -- the single most common real-world PDF-export
                failure is the target file already being open in a viewer,
                and that failure is much clearer reported here than as
                whatever generic COM exception `SaveAs3` happens to raise.
            sheets: `"all"` (default) -> `swExportData_ExportAllSheets`;
                `"current"` -> `swExportData_ExportCurrentSheet` (resolved
                via `IDrawingDoc::GetCurrentSheet`); or an explicit list of
                sheet names -> `swExportData_ExportSpecifiedSheets`, order
                preserved (the dossier's `SetSheets` gotchas note sheet
                order is presumed to control PDF page order). An explicit
                list is validated against `IDrawingDoc::GetSheetNames`
                *before* any COM export call -- an unknown name fails fast
                with the available sheet names in the message, rather than
                surfacing whatever `SetSheets`/`SaveAs3` would have done
                with a bad name (undocumented on either method's page).
            open_after: `IExportPdfData::ViewPdfAfterSaving`. Leave `False`
                for unattended/batch export -- see that record's Gotchas
                for why the dossier calls out `True` as the wrong default
                for automation.
            keep_invisible_layers: Temporarily show every hidden layer for
                the duration of the export, restoring each afterward -- see
                `_shown_hidden_layers` for why layer visibility is the lever
                this has to use.
            high_quality: `swPDFExportHighQuality` user-preference toggle,
                snapshotted and restored around the call via
                `_user_preference` -- so a batch export run never silently
                leaves the operator's SolidWorks install on a different
                quality setting than it found.

        Returns:
            Result dict. On success, `data` has `path`, `sheets` (the sheet
            names actually exported), `size_bytes`, `errors`, `warnings`,
            and `decoded_errors`. Fails (with the same `data` where
            available) if: the drawing can't be read, an explicit sheet name
            isn't found, the output path can't be written to,
            `IExportPdfData::SetSheets` refuses the sheet selection, or
            `SaveAs3` reports a nonzero `Errors` bitmask, a false return, or
            wrote no file (see `_save_as3`).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        export_sheet_names, mode, err = self._resolve_export_sheets(doc, sheets)
        if err:
            return err
        which = int({
            "all": SwExportDataSheetsToExport.swExportData_ExportAllSheets,
            "current": SwExportDataSheetsToExport.swExportData_ExportCurrentSheet,
            "list": SwExportDataSheetsToExport.swExportData_ExportSpecifiedSheets,
        }[mode])

        output_path, err = self._prepare_output_path(output_path, probe_writable=True)
        if err:
            return err

        try:
            with ExitStack() as restore:
                restore.enter_context(self._user_preference(
                    SwUserPreferenceToggle.swPDFExportHighQuality, high_quality))
                if keep_invisible_layers:
                    restore.enter_context(self._shown_hidden_layers(doc))

                export_data = self._sw_app.GetExportFileData(
                    int(SwExportDataFileType.swExportPdfData))
                # `SetSheets` returns False when the selection was not applied
                # (docs/api/05-export-and-layers.md). Unchecked, a refused call
                # exports whatever page set the `IExportPdfData` defaults to --
                # a PDF with the wrong sheets that `_save_as3` still reports as
                # a clean success, since the file exists and `Errors == 0`.
                if not export_data.SetSheets(which, list(export_sheet_names)):
                    return self._result(
                        False,
                        f"IExportPdfData::SetSheets refused the sheet selection "
                        f"{export_sheet_names!r} ({mode} mode)",
                        SwErrors.swExportError,
                        {"path": output_path, "sheets": export_sheet_names},
                    )
                export_data.ViewPdfAfterSaving = bool(open_after)

                return self._save_as3(
                    doc, output_path, label="PDF export", export_data=export_data,
                    extra_data={"sheets": export_sheet_names})
        except _PreferenceError as e:
            return self._result(False, str(e), SwErrors.swUnknownError)
        except Exception as e:
            logger.error(f"export_pdf error: {e}")
            return self._result(False, f"PDF export error: {e}", SwErrors.swFileSaveError)

    def export_dxf_dwg(
        self, output_path: str, format: str = "dxf", sheets: Any = "all",
        version: Optional[str] = None, map_file: Optional[str] = None,
        export_fonts_as: str = "geometry", multisheet: str = "single_file",
    ) -> Dict:
        """
        Export the active drawing's sheet(s) to DXF/DWG.

        **Not** `IPartDoc::ExportToDWG2` -- per docs/api/05-export-and-layers.md's
        intro discrepancy list and this record's "Resolution (sw-jcq.2)" note,
        that method lives on `IPartDoc` (not `IDrawingDoc`), requires a
        pre-selected multi-body sheet-metal feature, and exports flat-pattern
        geometry -- it is not a drawing-sheet export mechanism, so there is no
        `ExportToDWG2` positional tuple to build here. Instead this uses the
        same `IModelDocExtension::SaveAs3` entry point `save_drawing`/
        `export_pdf` already use, with a `.dxf`/`.dwg` `output_path`, driven
        entirely by `ISldWorks::SetUserPreferenceIntegerValue`/
        `SetUserPreferenceToggle` -- non-native-format saves have no
        `Options`-bitmask equivalent of PDF's `IExportPdfData` (dossier's
        `swSaveAsOptions_e` Gotchas).

        Every preference this call touches is snapshotted and restored via
        `_user_preference` on a single `ExitStack` -- success, a decoded
        `SaveAs3` failure, or a raised exception all take the same
        last-in-first-out restore path, so a batch run never leaves the
        operator's SolidWorks install on different DXF/DWG settings than it
        found:

        - `swDxfOutputFonts` (`export_fonts_as`) -- always set; there is no
          "leave inherited" option, since an inherited font setting is
          exactly the kind of silent output change this tool exists to rule
          out.
        - `swDxfMultiSheetOption` (`multisheet` / `sheets`, see below) --
          always set.
        - `swDxfVersion` (`version`) -- set only when `version` is given;
          left untouched (and therefore not restored) when omitted.
        - `swDxfMapping`, `swDXFDontShowMap`, `swDxfMappingFiles` (a
          `SetUserPreferenceStringListValue` call, snapshotting and
          restoring the *entire* prior list, not just appending),
          `swDxfMappingFileIndex` -- set only when `map_file` is given, per
          the dossier's `swDxfMappingFileIndex` Gotchas worked example
          (`SetUserPreferenceStringListValue` then re-check/initialize the
          index). `swDXFDontShowMap` is what keeps an unattended export from
          hanging on the layer-mapping dialog once `swDxfMapping = True`.

        Args:
            output_path: Destination path. Its extension must match `format`
                ("dxf"/"dwg") -- checked before any COM call, same
                fail-fast-on-a-predictable-mistake convention `export_pdf`
                uses for an unwritable path. Its parent directory is created
                if missing. In per-sheet mode (see `sheets`/`multisheet`
                below) this is a *base* path: each sheet's own file is named
                `<output_path without extension>_<sheet name><extension>`
                alongside it -- deterministic and collision-free across
                sheets, unlike relying on whatever undocumented file-naming
                SolidWorks' own `swDxfSeparateSheets` multi-file mode might
                use internally (not stated on any fetched page). The sheet
                name is run through `_sanitize_filename_component` first
                (a sheet name is free text, not a filename), and a name that
                sanitizes onto one already used in this call gets a `_2`,
                `_3`, ... suffix so the collision-free guarantee survives
                sanitization.
            format: `"dxf"` (default) or `"dwg"` -- both are driven by the
                exact same `SaveAs3` + preference mechanism, differing only
                in `output_path`'s extension (dossier: "the file extension
                indicates the conversion to perform").
            sheets: `"all"` (default), `"current"`, or an explicit list of
                sheet names -- same three shapes `export_pdf` accepts, but
                resolved differently, because DXF/DWG export has no
                `IExportPdfData`/`SetSheets` equivalent (PDF-only per the
                dossier):
                - `"all"` + `multisheet="single_file"` (the default pair):
                  one `SaveAs3` call at `output_path`, with
                  `swDxfMultiSheetOption = swDxfMultiSheet` so SolidWorks
                  combines every sheet into that one file.
                - `"all"` + `multisheet="separate_files"`: loops every sheet
                  (`IDrawingDoc::ActivateSheet` + a `SaveAs3` call per sheet,
                  the same per-sheet loop shape as this dossier's own
                  official "Save Drawing Sheets as DXF Example (VBA)", just
                  with `SaveAs3` instead of the superseded `SaveAs4`), each
                  written to its own per-sheet file (see `output_path`
                  above), with `swDxfMultiSheetOption = swDxfActiveSheetOnly`
                  set once before the loop (each call only wants its
                  currently-activated sheet).
                - `"current"`: a single `SaveAs3` call at `output_path` for
                  whatever sheet `IDrawingDoc::GetCurrentSheet` reports,
                  `swDxfMultiSheetOption = swDxfActiveSheetOnly`, `multisheet`
                  ignored (there is only ever one sheet to place).
                - An explicit list: always loops (same per-sheet mechanism as
                  the `"all"`+`separate_files` case above), *regardless* of
                  `multisheet` -- there is no documented "combine only these
                  N named sheets into one file" mode, so honoring an explicit
                  subset can only mean one file per requested sheet. Combining
                  an explicit list would require silently ignoring the
                  caller's `multisheet="single_file"` request or silently
                  dropping sheets from a "combined" export; this tool does
                  neither -- it always does exactly what a named-sheet list
                  can actually mean. Validated against
                  `IDrawingDoc::GetSheetNames` before any COM call, same as
                  `export_pdf`.
            version: DXF/DWG release, e.g. `"R2018"`, `"R12"` (matches
                `SwDxfFormat`'s member suffixes, case-insensitive) -- sets
                `swDxfVersion`. `None` (default) leaves the current session
                setting untouched.
            map_file: Path to a layer-mapping file. Checked with
                `os.path.exists` *before* any COM call (including before any
                preference is touched) -- a missing map file must fail fast,
                not surface as a mid-export COM error. `None` (default): no
                layer mapping is configured (the mapping-related preferences
                above are left untouched).
            export_fonts_as: `"geometry"` (default, `swDxfOutputFonts = 0` --
                AutoCAD STANDARD font only) or `"truetype"`
                (`swDxfOutputFonts = 1`) -- the only two documented values.
            multisheet: `"single_file"` (default) or `"separate_files"` --
                see `sheets` above for exactly how this combines with each
                `sheets` shape.

        Returns:
            Result dict. On success, `data` has `format`, `sheets` (the sheet
            names considered for export), `multisheet`, `export_mode`
            (`"combined"`/`"current"`/`"per_sheet"`, whichever this call
            actually resolved to), and `files` -- a list of
            `{"path", "sheet", "size_bytes"}` entries, one per file actually
            verified to exist on disk afterward (`"sheet"` is `None` for a
            combined whole-drawing file). Fails if: the drawing can't be
            read; `format`/`sheets`/`multisheet`/`export_fonts_as`/`version`
            is invalid; `map_file` doesn't exist; `output_path`'s extension
            doesn't match `format`; a requested sheet can't be found/
            activated; any `SaveAs3` call reports a nonzero `Errors` bitmask
            or a false return (same `decode_save_error` decoding `export_pdf`
            uses); or any expected output file doesn't actually exist on disk
            afterward (`export_pdf`'s "SaveAs3 said success but wrote
            nothing" failure mode, checked per-file here).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        fmt = str(format).lower()
        if fmt not in ("dxf", "dwg"):
            return self._result(
                False, f"format must be 'dxf' or 'dwg', got {format!r}",
                SwErrors.swInvalidInput)
        ext = "." + fmt

        if multisheet not in ("single_file", "separate_files"):
            return self._result(
                False,
                f"multisheet must be 'single_file' or 'separate_files', got {multisheet!r}",
                SwErrors.swInvalidInput)

        fonts_value = _DXF_FONT_MODES.get(export_fonts_as)
        if fonts_value is None:
            return self._result(
                False,
                f"export_fonts_as must be one of {sorted(_DXF_FONT_MODES)!r}, "
                f"got {export_fonts_as!r}",
                SwErrors.swInvalidInput)

        version_member = None
        if version is not None:
            version_member = _DXF_VERSION_BY_NAME.get(str(version).upper())
            if version_member is None:
                return self._result(
                    False,
                    f"version must be one of {sorted(_DXF_VERSION_BY_NAME)!r} "
                    f"or omitted, got {version!r}",
                    SwErrors.swInvalidInput)

        if map_file is not None and not os.path.exists(map_file):
            return self._result(
                False, f"Map file not found: {map_file}", SwErrors.swFileNotFoundError)

        output_path, err = self._prepare_output_path(output_path, expected_ext=ext)
        if err:
            return err

        target_sheets, mode, err = self._resolve_export_sheets(doc, sheets)
        if err:
            return err
        if mode == "current":
            export_mode = "current"
        elif mode == "all" and multisheet == "single_file":
            export_mode = "combined"
        else:
            # An explicit list always exports one file per sheet, regardless
            # of `multisheet` -- see this method's `sheets` docs for why a
            # named subset can only mean that.
            export_mode = "per_sheet"

        base, _ = os.path.splitext(output_path)
        written_files: List[Dict[str, Any]] = []
        # Sanitizing a sheet name can map two distinct names onto one
        # ("1/2" and "1_2" both become "1_2"), so per-sheet paths are also
        # deduped -- the docs below promise collision-free per-sheet files,
        # and silently overwriting one sheet's export with another's is the
        # exact failure that promise exists to rule out.
        used_sheet_paths: Dict[str, int] = {}
        try:
            with ExitStack() as restore:
                def apply(pref, value):
                    restore.enter_context(self._user_preference(pref, value))

                apply(SwUserPreferenceIntegerValue.swDxfOutputFonts, fonts_value)
                apply(
                    SwUserPreferenceIntegerValue.swDxfMultiSheetOption,
                    SwDxfMultisheet.swDxfMultiSheet if export_mode == "combined"
                    else SwDxfMultisheet.swDxfActiveSheetOnly)
                if version_member is not None:
                    apply(SwUserPreferenceIntegerValue.swDxfVersion, version_member)
                if map_file is not None:
                    apply(SwUserPreferenceToggle.swDxfMapping, True)
                    apply(SwUserPreferenceToggle.swDXFDontShowMap, True)
                    apply(SwUserPreferenceStringListValue.swDxfMappingFiles, [map_file])
                    apply(SwUserPreferenceIntegerValue.swDxfMappingFileIndex, 0)

                if export_mode in ("combined", "current"):
                    result = self._save_as3(
                        doc, output_path, label="DXF/DWG export",
                        extra_data={"sheets": target_sheets})
                    if not result["success"]:
                        return result
                    written_files.append({
                        "path": output_path,
                        "sheet": None if export_mode == "combined" else target_sheets[0],
                        "size_bytes": result["data"]["size_bytes"],
                    })
                else:  # per_sheet
                    # The loop below activates each sheet in turn; put the
                    # caller's own active sheet back afterward, the same way
                    # every preference this method touches is restored.
                    restore.enter_context(self._active_sheet_restored(doc))
                    for sheet_name in target_sheets:
                        try:
                            activated = doc.ActivateSheet(sheet_name)
                        except Exception as e:
                            logger.error(f"export_dxf_dwg activate sheet error: {e}")
                            return self._result(
                                False, f"Activate sheet error: {e}", SwErrors.swInvalidInput,
                                {"sheet_name": sheet_name, "files": written_files})
                        if not activated:
                            return self._result(
                                False, f"Sheet {sheet_name!r} not found",
                                SwErrors.swInvalidInput,
                                {"sheet_name": sheet_name, "files": written_files})

                        # Sheet names are free text in the drawing tree, not
                        # filenames: `1/2 SCALE` or `REV:A` would otherwise
                        # become a path segment (into a directory nobody
                        # created -- `_prepare_output_path` ran on the
                        # caller's `output_path` only) and a name containing
                        # `..` would escape the output directory entirely.
                        # Same sanitizer `batch_export_pack` puts on its own
                        # `{sheet}` token.
                        safe_sheet = _sanitize_filename_component(sheet_name) or "sheet"
                        seen = used_sheet_paths.get(safe_sheet, 0)
                        used_sheet_paths[safe_sheet] = seen + 1
                        if seen:
                            safe_sheet = f"{safe_sheet}_{seen + 1}"
                        sheet_path = f"{base}_{safe_sheet}{ext}"
                        result = self._save_as3(
                            doc, sheet_path,
                            label=f"DXF/DWG export for sheet {sheet_name!r}",
                            extra_data={"sheet": sheet_name, "files": written_files})
                        if not result["success"]:
                            return result
                        written_files.append({
                            "path": sheet_path, "sheet": sheet_name,
                            "size_bytes": result["data"]["size_bytes"],
                        })
        except _PreferenceError as e:
            return self._result(False, str(e), SwErrors.swUnknownError)
        except Exception as e:
            logger.error(f"export_dxf_dwg error: {e}")
            return self._result(
                False, f"DXF/DWG export error: {e}", SwErrors.swFileSaveError,
                {"files": written_files})

        return self._result(
            True, f"Exported {len(written_files)} {fmt.upper()} file(s)", SwErrors.swSuccess,
            {
                "format": fmt, "sheets": target_sheets, "multisheet": multisheet,
                "export_mode": export_mode, "files": written_files,
            },
        )

    def export_edrawings(self, output_path: str, sheets: Any = "all") -> Dict:
        """
        Export the active drawing to eDrawings (`.edrw`) via
        `IModelDocExtension::SaveAs3`, for review-only stakeholders who don't
        have SolidWorks itself. Per `SaveAs3`'s own Remarks (dossier's
        worked example), eDrawings export is driven purely by the `.edrw`
        file extension plus `swEdrawingsSaveAsSelectionOption` -- there is no
        eDrawings-specific `ExportData` object (that parameter is PDF-only).

        Args:
            output_path: Destination path; must end with `.edrw` (the
                drawing-document eDrawings extension -- `.eprt`/`.easm` are
                part/assembly-only and out of scope for a tool gated behind
                `get_drawing_doc`). Its parent directory is created if
                missing.
            sheets: `"all"` (default) or `"current"` -- mapped to
                `SwEdrawingSaveAsOption.swEdrawingSaveAll`/`swEdrawingSaveActive`.
                Unlike `export_pdf`/`export_dxf_dwg`, an explicit sheet-name
                list is **not** accepted: `swEdrawingSaveAsOption_e`'s third
                member, `swEdrawingSaveSelected`, saves whatever is currently
                selected via `ISelectionMgr`, not a named-sheet list -- there
                is no documented "these specific sheets" mode for eDrawings
                export to fall back to, so this tool fails fast on anything
                else rather than silently reinterpreting it.

        Returns:
            Result dict. On success, `data` has `path`, `sheets`,
            `size_bytes`, `errors`, `warnings`, `decoded_errors`, and
            `addin_available: True`. On failure, `data["addin_available"]`
            is `False` when the failure looks like a missing/unavailable
            eDrawings add-in specifically -- either a decoded `SaveAs3`
            error bitmask containing `swFileSaveFormatNotAvailable`,
            `swFileSaveAsBadEDrawingsVersion`, or `swFileSaveAsNotSupported`
            (the dossier's own troubleshooting note ties
              `swFileSaveAsNotSupported` to automation-specific failure
            modes), or a raised COM exception whose message mentions
            "add-in"/"addin"/"edrawings" -- and `True` for any other kind of
            failure (bad sheets value, unwritable path, etc.), so a caller
            can distinguish "eDrawings itself isn't available" from an
            ordinary export failure without parsing the message text.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        if not (isinstance(sheets, str) and sheets in ("all", "current")):
            return self._result(
                False,
                "sheets must be 'all' or 'current' for eDrawings export -- "
                "swEdrawingSaveAsOption_e has no 'specified sheets' mode "
                f"(got {sheets!r})",
                SwErrors.swInvalidInput,
                {"addin_available": True},
            )
        selection_value = (
            SwEdrawingSaveAsOption.swEdrawingSaveAll if sheets == "all"
            else SwEdrawingSaveAsOption.swEdrawingSaveActive)

        output_path, err = self._prepare_output_path(output_path, expected_ext=".edrw")
        if err:
            # Every failure of this tool carries `addin_available` (see the
            # Returns docs); a bad extension or an uncreatable directory is an
            # ordinary input failure, not evidence about the add-in.
            err.setdefault("data", {})["addin_available"] = True
            return err

        try:
            with self._user_preference(
                SwUserPreferenceIntegerValue.swEdrawingsSaveAsSelectionOption,
                selection_value,
            ):
                result = self._save_as3(
                    doc, output_path, label="eDrawings export",
                    extra_data={"sheets": sheets}, raise_com_errors=True)
        except _PreferenceError as e:
            # `addin_available` is documented as present on *every* failure of
            # this tool, and `_result` drops the whole `data` key when it is
            # falsy -- so this branch has to carry it explicitly or a caller
            # reading `result["data"]["addin_available"]` gets a `KeyError`.
            # A refused preference write says nothing about the add-in.
            return self._result(
                False, str(e), SwErrors.swUnknownError, {"addin_available": True})
        except Exception as e:
            logger.error(f"export_edrawings error: {e}")
            addin_unavailable = _looks_like_missing_addin(str(e))
            message = (
                f"eDrawings export failed, possibly because the eDrawings "
                f"add-in is not loaded: {e}"
            ) if addin_unavailable else f"eDrawings export error: {e}"
            return self._result(
                False, message, SwErrors.swExportError,
                {"addin_available": not addin_unavailable})

        data = result["data"]
        if result["success"]:
            data["addin_available"] = True
            return result

        # A `swFileSaveError_e` bitmask that names one of the eDrawings-specific
        # failures gets the add-in remediation hint appended to `_save_as3`'s
        # already-decoded reason, so a caller can tell "eDrawings itself isn't
        # available" from an ordinary export failure without parsing the text.
        error_code = data.get("errors") or 0
        addin_related = bool(error_code & _EDRAWINGS_ADDIN_ERROR_BITS)
        data["addin_available"] = not addin_related
        if addin_related:
            result["message"] = (
                f"{result['message']} -- this may mean the eDrawings add-in is "
                f"not loaded, or (if running SOLIDWORKS Connected) that "
                f"eDrawings export is unsupported in that mode"
            )
        return result

    def get_custom_properties(self, configuration: Optional[str] = None) -> Dict:
        """
        Read custom properties via `IModelDocExtension::CustomPropertyManager`
        + `ICustomPropertyManager::Get6`, resolved (evaluated) values.

        `configuration=None`/`""` reaches the document-level property set,
        per the dossier's `CustomPropertyManager` record; an actual
        configuration name reaches that configuration's own set.

        Enumerates via `ICustomPropertyManager::GetNames` -- not itself in
        docs/api/01-documents-and-sheets.md (only `Get6`/`Add3`/`Set2`/
        `CustomPropertyManager` are), but corroborated as a real, no-argument,
        string-array-returning member by multiple independent
        help.solidworks.com page titles across SW versions 2012-2024
        (direct fetch of the page bodies 403s, the same WAF block the
        dossier hit elsewhere) -- treat as unsourced-but-confirmed-to-exist,
        not a numeric-value guess.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        config_name = configuration or ""
        try:
            mgr = doc.Extension.CustomPropertyManager(config_name)
            names = mgr.GetNames() or []
        except Exception as e:
            logger.error(f"get_custom_properties error: {e}")
            return self._result(False, f"Get custom properties error: {e}", SwErrors.swUnknownError)

        if not isinstance(names, (list, tuple)):
            # GetNames is documented (see docstring) to return a string
            # array; anything else (e.g. an unscripted COM stub in tests, or
            # a document with zero custom properties on some SW versions)
            # means "nothing to enumerate" rather than something to iterate.
            names = []

        properties: Dict[str, Any] = {}
        for name in names:
            try:
                val_out = com_backend.byref_str()
                resolved_out = com_backend.byref_str()
                was_resolved = com_backend.byref_bool()
                link_to_property = com_backend.byref_bool()
                mgr.Get6(name, False, val_out, resolved_out, was_resolved, link_to_property)
                properties[name] = resolved_out.value
            except Exception as e:
                logger.debug(f"get_custom_properties: Get6({name!r}) failed: {e}")
                properties[name] = None

        count = len(properties)
        return self._result(
            True, f"{count} custom propert{'y' if count == 1 else 'ies'}",
            SwErrors.swSuccess, {"configuration": config_name, "properties": properties},
        )

    def set_custom_properties(self, properties: Dict[str, Any],
                               configuration: Optional[str] = None) -> Dict:
        """
        Write custom properties via `ICustomPropertyManager::Add3`, using
        `swCustomPropertyReplaceValue` (add-or-overwrite: create the property
        if it's new, replace its value if it already exists) -- per the
        dossier's Gotchas, `swCustomPropertyOnlyIfNew` would silently no-op
        on an existing name instead.

        Every value is written as `swCustomInfoText` -- `properties` is a
        plain `{name: value}` dict with no per-value type, and text is the
        type every value stringifies into cleanly.

        Per-key `success` means the `Add3` COM call completed without
        raising -- it is not an interpretation of `Add3`'s return code
        (`swCustomInfoAddResult_e`), which is not in this project's sourced
        dossiers. The raw code is still reported per key (`result_code`) for
        callers that want to interpret it themselves. Overall `success` is
        the AND of every per-key `success`, so one failing key can't be
        masked by the others succeeding.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        config_name = configuration or ""
        try:
            mgr = doc.Extension.CustomPropertyManager(config_name)
        except Exception as e:
            logger.error(f"set_custom_properties error: {e}")
            return self._result(False, f"Set custom properties error: {e}", SwErrors.swUnknownError)

        results: Dict[str, Any] = {}
        for name, value in (properties or {}).items():
            try:
                code = mgr.Add3(
                    name, int(SwCustomInfoType.swCustomInfoText), str(value),
                    int(SwCustomPropertyAddOption.swCustomPropertyReplaceValue),
                )
                results[name] = {
                    "success": True,
                    "result_code": int(code) if code is not None else None,
                }
            except Exception as e:
                logger.debug(f"set_custom_properties: Add3({name!r}) failed: {e}")
                results[name] = {"success": False, "result_code": None, "error": str(e)}

        count = len(results)
        overall_success = all(r["success"] for r in results.values())
        message = (
            f"Set {count} custom propert{'y' if count == 1 else 'ies'}" if overall_success
            else f"{sum(not r['success'] for r in results.values())} of {count} custom propert"
                 f"{'y' if count == 1 else 'ies'} failed"
        )
        return self._result(
            overall_success, message,
            SwErrors.swSuccess if overall_success else SwErrors.swUnknownError,
            {"configuration": config_name, "results": results},
        )

    # ========================================================================
    # Composite batch export
    # ========================================================================

    def _resolve_batch_export_filename(
        self, pattern: str, *, drawing: str, sheet: str, index: int, date: str, rev: str,
    ) -> str:
        """Resolve `batch_export_pack`'s `filename_pattern` (a `str.format`
        template over the `{drawing}`/`{sheet}`/`{index}`/`{date}`/`{rev}`
        tokens) into a filesystem-safe base filename (no extension).

        Each token value is sanitized individually via
        `_sanitize_filename_component` *before* substitution -- not only the
        final formatted string -- so a `/` or `:` inside a sheet name can't
        be read as a path separator once it lands inside the larger pattern
        string. The fully-formatted result is sanitized once more afterward
        to catch anything the caller's own pattern literal introduced.

        Raises:
            ValueError: if `pattern` references any token other than the
                five documented ones (an unresolvable `str.format` field).
        """
        tokens = {
            "drawing": _sanitize_filename_component(drawing),
            "sheet": _sanitize_filename_component(sheet),
            "index": index,
            "date": date,
            "rev": _sanitize_filename_component(rev),
        }
        try:
            name = pattern.format(**tokens)
        except (KeyError, IndexError) as e:
            raise ValueError(
                f"filename_pattern {pattern!r} references an unknown token: {e}; "
                f"supported tokens are {{drawing}}, {{sheet}}, {{index}}, {{date}}, {{rev}}"
            )
        # Unlike each individual token above, the fully-formatted name must
        # not be empty -- it's used directly as a path segment.
        return _sanitize_filename_component(name) or "_"

    def _batch_export_call(self, fmt: str, path: str, sheet_name: Optional[str]):
        """The zero-argument callable that exports `fmt` to `path` for
        `batch_export_pack` -- one sheet when `sheet_name` is given, or the
        whole drawing combined when it is `None`.

        The single place that knows how each format's own export tool spells
        "just this sheet": PDF takes an explicit name list, while DXF/DWG and
        eDrawings can only export the *active* sheet (see
        `_BATCH_EXPORT_NEEDS_ACTIVE_SHEET`), so the caller activates it first
        and they take `sheets="current"`. Keeping that here means the combined
        and per-sheet loops in `batch_export_pack` are the same two lines
        rather than two copies of a per-format `if` ladder.
        """
        if fmt == "pdf":
            sheets: Any = "all" if sheet_name is None else [sheet_name]
            return lambda: self.export_pdf(path, sheets=sheets)

        sheets = "all" if sheet_name is None else "current"
        if fmt == "edrawings":
            return lambda: self.export_edrawings(path, sheets=sheets)
        return lambda: self.export_dxf_dwg(
            path, format=fmt, sheets=sheets, multisheet="single_file")

    def _save_native_copy(self, doc: Any, path: str) -> Dict:
        """Save a `.SLDDRW` copy of `doc` at `path` for `batch_export_pack`'s
        `include_native`, via `IModelDocExtension::SaveAs3` with
        `swSaveAsOptions_Silent | swSaveAsOptions_Copy`.

        Unlike `save_drawing`'s plain `Silent`-only `Save3`/`SaveAs3` (which
        re-points the open document at a given `filepath`), the `Copy` bit
        here writes `path` as a side copy and leaves the active document's
        own identity/path untouched -- the behavior an "archive copy" of a
        drawing that's still being worked on needs. The option bitmask is the
        only thing that differs from the export tools; everything else comes
        from the shared `_save_as3` primitive.
        """
        return self._save_as3(
            doc, path, label="Native archive save",
            options=(
                int(SwSaveAsOptions.swSaveAsOptions_Silent)
                | int(SwSaveAsOptions.swSaveAsOptions_Copy)
            ),
        )

    def batch_export_pack(
        self, output_dir: str, formats: Optional[List[str]] = None,
        per_sheet: bool = False, filename_pattern: str = "{drawing}_{sheet}",
        include_native: bool = True, rebuild_first: bool = True,
        overwrite: bool = False,
    ) -> Dict:
        """
        Export every deliverable for the active drawing in one call -- a
        genuinely higher-level tool, not a raw API wrapper, so a caller
        doesn't have to orchestrate N per-sheet/per-format calls to
        `export_pdf`/`export_dxf_dwg`/`export_edrawings` itself. Builds on
        those three tools plus `rebuild_document`, `activate_sheet`, and
        `get_custom_properties`; the only COM this method makes directly is
        `IModelDoc2::GetTitle`/`IDrawingDoc::GetSheetNames` (to resolve
        filename tokens) and, for `include_native`, its own `SaveAs3` copy
        (see `_save_native_copy`).

        Per this project's "continue on a per-file failure" rule, one file
        failing does not abort the batch -- every other file is still
        attempted, and the failure is named in the returned manifest.
        Overall `success` is `False` if *any* file failed.

        Args:
            output_dir: Destination directory for every produced file plus
                `manifest.json`. Created (including parents) if missing.
            formats: Export formats to produce, from `{"pdf", "dxf", "dwg",
                "edrawings"}` (case-insensitive). Defaults to `["pdf"]` when
                omitted (`None`); an explicit `[]` produces no per-format
                files (only useful with `include_native=True`). Any entry
                outside that set fails with `swInvalidInput` before any COM
                call -- there is no "native" entry here, since a whole-
                document archive copy is `include_native`, not a per-format
                export.
            per_sheet: `False` (default): one combined multi-sheet file per
                format, via that export tool's own `sheets="all"` mode.
                `True`: one file per sheet per format, each named from
                `filename_pattern` and exported via that sheet specifically
                (`export_pdf`'s `sheets=[name]`, or `activate_sheet` +
                `sheets="current"` for `export_dxf_dwg`/`export_edrawings`,
                which have no "these specific sheets" mode of their own).
            filename_pattern: `str.format`-style pattern used for every
                produced file's base name (extension appended
                separately). Supported tokens:
                - `{drawing}`: the active drawing's title
                  (`IModelDoc2::GetTitle`), file extension stripped.
                - `{sheet}`: the sheet name being exported; `"all"` for a
                  combined (`per_sheet=False`) or native-archive file, which
                  aren't tied to one sheet.
                - `{index}`: the sheet's 1-based position in
                  `IDrawingDoc::GetSheetNames`'s order; `0` for a combined
                  or native-archive file.
                - `{date}`: today's date as `YYYY-MM-DD`.
                - `{rev}`: the document-level `"Revision"` or `"Rev"`
                  custom property (case-insensitive key match, first one
                  found), or `""` if neither is set.
                Any other `{...}` field fails with `swInvalidInput` before
                any COM call. Each token's *value* is sanitized for the
                filesystem before it's substituted (see `overwrite` below),
                so a sheet name containing `/` or `:` can't inject a path
                separator. `per_sheet=True` additionally requires the
                pattern to contain `{sheet}` and/or `{index}` -- without
                either, every sheet would resolve to the identical
                filename, which would either silently overwrite sheet 2
                onward (`overwrite=True`) or refuse to export them
                (`overwrite=False`); rejected up front instead of letting
                either happen silently.
            include_native: Also save a `.SLDDRW` copy of the active
                drawing into `output_dir` for archive (see
                `_save_native_copy` -- a side copy, not a re-point of the
                open document).
            rebuild_first: Force a rebuild (`rebuild_document(force=True)`)
                before the first export -- dimension values and BOM
                quantities can be stale otherwise. A rebuild failure is
                recorded in the result's `data["rebuild"]` but does not
                abort the batch; every export is still attempted (its own
                per-file success/failure reflects the drawing's actual
                state, rebuilt or not).
            overwrite: `False` (default): refuse to touch (no COM call) any
                output path that already exists in `output_dir` -- recorded
                as a failed manifest entry rather than skipped silently.
                `True`: overwrite freely.

        Returns:
            Result dict. `data` has `output_dir`, `manifest_path` (the
            written `manifest.json`, or `None` if it could not be written --
            including when `overwrite=False` and one is already there, since
            the manifest is an output of this tool like any other and
            truncating the previous run's record is exactly what
            `overwrite=False` was asked to prevent),
            `files` (one entry per attempted output: `path`, `format`
            (`"pdf"`/`"dxf"`/`"dwg"`/`"edrawings"`/`"native"`), `sheet`
            (`None` for a combined/native file), `success`, `size_bytes`,
            `timestamp`, and `error` when failed), `total`/`succeeded`/
            `failed` counts, `failures` (the failed subset only, for a
            quick look without scanning all of `files`), and `rebuild`
            (`{"attempted", "success", "message"}`). Overall `success` is
            `False` if any file failed, if there is nothing to export
            (`formats` is `[]` and `include_native` is `False`), or for any
            of the fail-fast input-validation cases documented above.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        fmt_list = ["pdf"] if formats is None else [str(f).lower() for f in formats]
        unknown_formats = [f for f in fmt_list if f not in _BATCH_EXPORT_FORMAT_EXTENSIONS]
        if unknown_formats:
            return self._result(
                False,
                f"Unknown format(s) {unknown_formats!r}; expected one of "
                f"{sorted(_BATCH_EXPORT_FORMAT_EXTENSIONS)!r}",
                SwErrors.swInvalidInput,
            )

        if not fmt_list and not include_native:
            return self._result(
                False,
                "Nothing to export: formats is empty and include_native is False",
                SwErrors.swInvalidInput,
            )

        if not isinstance(filename_pattern, str) or not filename_pattern.strip():
            return self._result(
                False, "filename_pattern must be a non-empty string", SwErrors.swInvalidInput)

        # A token match, not a substring match: `"{index:02d}"` is a perfectly
        # good per-sheet discriminator that `str.format` handles, and a plain
        # `"{index}" not in pattern` test would reject it.
        if per_sheet and not _PER_SHEET_TOKEN_RE.search(filename_pattern):
            return self._result(
                False,
                "per_sheet=True requires filename_pattern to contain {sheet} and/or "
                "{index}, or every sheet would resolve to the same filename",
                SwErrors.swInvalidInput,
            )

        try:
            self._resolve_batch_export_filename(
                filename_pattern, drawing="drawing", sheet="sheet", index=0,
                date="date", rev="rev")
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)

        try:
            available_sheets = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            logger.error(f"batch_export_pack GetSheetNames error: {e}")
            return self._result(
                False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)
        if not available_sheets:
            return self._result(
                False, "Drawing has no sheets to export", SwErrors.swFeatureError)

        output_dir = os.path.abspath(output_dir)
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            return self._result(
                False, f"Could not create output directory {output_dir!r}: {e}",
                SwErrors.swExportError)

        title = self._get_doc_title(doc)
        drawing_name = os.path.splitext(title)[0] if title else "drawing"

        rev = ""
        try:
            props_result = self.get_custom_properties()
            if props_result.get("success"):
                properties = (props_result.get("data") or {}).get("properties") or {}
                for key, value in properties.items():
                    if isinstance(key, str) and key.strip().lower() in ("revision", "rev") and value:
                        rev = str(value)
                        break
        except Exception as e:
            logger.debug(f"batch_export_pack: could not read {{rev}} custom property: {e}")

        date_str = datetime.date.today().strftime("%Y-%m-%d")

        if rebuild_first:
            rebuild_result = self.rebuild_document(force=True)
            rebuild_data = {
                "attempted": True, "success": bool(rebuild_result.get("success")),
                "message": rebuild_result.get("message"),
            }
        else:
            rebuild_data = {"attempted": False, "success": None, "message": None}

        manifest_entries: List[Dict[str, Any]] = []

        def _attempt(path: str, fmt: str, sheet_name: Optional[str], export_fn) -> None:
            if os.path.exists(path) and not overwrite:
                manifest_entries.append({
                    "path": path, "format": fmt, "sheet": sheet_name,
                    "success": False, "size_bytes": None,
                    "error": f"{path!r} already exists (overwrite=False)",
                    "timestamp": datetime.datetime.now().isoformat(),
                })
                return
            try:
                result = export_fn()
            except Exception as e:
                logger.error(f"batch_export_pack export error ({fmt}, {sheet_name}): {e}")
                result = {"success": False, "message": str(e)}
            success = bool(result.get("success"))
            entry: Dict[str, Any] = {
                "path": path, "format": fmt, "sheet": sheet_name, "success": success,
                "timestamp": datetime.datetime.now().isoformat(),
            }
            if success:
                export_data = result.get("data") or {}
                size = export_data.get("size_bytes")
                if size is None and os.path.exists(path):
                    size = os.path.getsize(path)
                entry["size_bytes"] = size
            else:
                entry["size_bytes"] = None
                entry["error"] = result.get("message")
            manifest_entries.append(entry)

        # Resolved with the *real* token values, so unlike the placeholder
        # pre-flight above this can still fail here: a pattern whose
        # formatting depends on a value -- `"{rev[0]}"` against a drawing with
        # no Revision property, where `rev` is `""` -- passes pre-flight and
        # raises only now. A tool must return a result dict rather than let
        # that escape.
        try:
            # The base name for anything not tied to one sheet: a combined
            # per-format file, and the native archive copy in either mode.
            combined_base = self._resolve_batch_export_filename(
                filename_pattern, drawing=drawing_name, sheet="all", index=0,
                date=date_str, rev=rev)
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)

        if per_sheet:
            # Only the formats with no "these specific sheets" mode of their
            # own need the sheet made active first; `export_pdf` drives
            # `IExportPdfData::SetSheets` instead. With the default
            # `formats=["pdf"]` this skips one `ActivateSheet` per sheet --
            # a sheet switch regenerates its views, the most expensive COM
            # call in this loop.
            needs_active_sheet = any(
                f in _BATCH_EXPORT_NEEDS_ACTIVE_SHEET for f in fmt_list)
            # Only entered when the loop will actually switch sheets: with the
            # default `formats=["pdf"]` nothing below touches the active sheet,
            # so there is nothing to put back.
            with ExitStack() as sheet_restore:
                if needs_active_sheet:
                    sheet_restore.enter_context(self._active_sheet_restored(doc))
                for index, sheet_name in enumerate(available_sheets, start=1):
                    activate_result = (
                        self.activate_sheet(sheet_name) if needs_active_sheet else None)
                    activate_ok = activate_result is None or bool(activate_result["success"])
                    try:
                        filename_base = self._resolve_batch_export_filename(
                            filename_pattern, drawing=drawing_name, sheet=sheet_name,
                            index=index, date=date_str, rev=rev)
                    except ValueError as e:
                        return self._result(False, str(e), SwErrors.swInvalidInput)
                    for fmt in fmt_list:
                        path = os.path.join(
                            output_dir, filename_base + _BATCH_EXPORT_FORMAT_EXTENSIONS[fmt])
                        if not activate_ok and fmt in _BATCH_EXPORT_NEEDS_ACTIVE_SHEET:
                            # Routed through `_attempt` with a pre-failed result
                            # so the manifest entry is built in exactly one place.
                            message = (
                                f"Could not activate sheet {sheet_name!r}: "
                                f"{activate_result.get('message')}")
                            _attempt(
                                path, fmt, sheet_name,
                                lambda m=message: {"success": False, "message": m})
                            continue
                        _attempt(
                            path, fmt, sheet_name,
                            self._batch_export_call(fmt, path, sheet_name))
        else:
            for fmt in fmt_list:
                path = os.path.join(
                    output_dir, combined_base + _BATCH_EXPORT_FORMAT_EXTENSIONS[fmt])
                _attempt(path, fmt, None, self._batch_export_call(fmt, path, None))

        if include_native:
            native_path = os.path.join(output_dir, combined_base + ".slddrw")
            _attempt(
                native_path, "native", None,
                lambda p=native_path: self._save_native_copy(doc, p))

        manifest_path = os.path.join(output_dir, "manifest.json")
        manifest_document = {
            "generated_at": datetime.datetime.now().isoformat(),
            "drawing": drawing_name,
            "output_dir": output_dir,
            "files": manifest_entries,
        }
        try:
            # `"x"` under `overwrite=False`: the manifest is an output of this
            # tool like any other, and `manifest.json` is the file most likely
            # to already be there from a prior export into the same folder.
            # Truncating it while refusing to touch every *other* existing
            # path would destroy the previous run's record -- exactly what
            # `overwrite=False` was asked to prevent.
            with open(manifest_path, "w" if overwrite else "x") as f:
                json.dump(manifest_document, f, indent=2)
        except OSError as e:
            logger.error(f"batch_export_pack manifest write error: {e}")
            manifest_path = None

        # At least one entry is guaranteed: the "nothing to export" case
        # (`formats == []` with `include_native=False`) and the no-sheets case
        # both fail fast above, so every path through the loops appends.
        failures = [e for e in manifest_entries if not e["success"]]
        succeeded = len(manifest_entries) - len(failures)
        overall_success = not failures

        message = f"Exported {succeeded}/{len(manifest_entries)} file(s)"
        if failures:
            message += f"; {len(failures)} failed"

        data = {
            "output_dir": output_dir,
            "manifest_path": manifest_path,
            "files": manifest_entries,
            "total": len(manifest_entries),
            "succeeded": succeeded,
            "failed": len(failures),
            "failures": [
                {
                    "path": e["path"], "format": e["format"], "sheet": e["sheet"],
                    "error": e.get("error"),
                }
                for e in failures
            ],
            "rebuild": rebuild_data,
        }
        return self._result(
            overall_success, message,
            SwErrors.swSuccess if overall_success else SwErrors.swExportError, data)

    # ========================================================================
    # Sheet management tools
    # ========================================================================

    def add_sheet(self, name: str, template_path: Optional[str] = None,
                  paper_size: str = "A3", scale_num: float = 1, scale_denom: float = 1,
                  first_angle: bool = False, width: Optional[float] = None,
                  height: Optional[float] = None) -> Dict:
        """
        Create a new drawing sheet via `IDrawingDoc::NewSheet4`.

        Args:
            name: Name for the new sheet.
            template_path: Full path to a custom sheet-format `.slddrt`
                template. When given, `NewSheet4`'s `TemplateIn` is bound to
                `swDwgTemplateCustom` and this path becomes `TemplateName`.
                Omitted (default): `TemplateIn` is `swDwgTemplateNone`, so
                `paper_size` (and, for `paper_size="custom"`, `width`/
                `height`) determine the sheet's size instead.
            paper_size: One of `"A"`, `"B"`, `"C"`, `"D"`, `"E"`, `"A0"`-`"A4"`
                (case-insensitive -- the *landscape* `swDwgPaperSizes_e`
                value; this tool has no separate orientation parameter), or
                `"custom"` to size the sheet from `width`/`height` instead.
            scale_num, scale_denom: `NewSheet4`'s `Scale1`/`Scale2` --
                dimensionless, passed through unconverted.
            first_angle: `NewSheet4`'s raw `FirstAngle` boolean -- `True` for
                first-angle projection, `False` (default) for third-angle.
            width, height: Sheet dimensions in the caller's unit, converted
                to meters at the COM boundary. Only valid when
                `paper_size="custom"` -- passing either alongside any other
                `paper_size` fails with `swInvalidInput`, and
                `paper_size="custom"` without both fails the same way.

        Returns:
            Result dict; `data` echoes back the resolved sheet parameters on
            success. Fails with `swFeatureError` if `NewSheet4` itself
            returns `False` -- its own dossier record documents no specific
            failure cause (e.g. a duplicate `name`) for that, so the message
            says so rather than guessing one.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        paper_key = (paper_size or "").strip().upper()
        is_custom = paper_key == "CUSTOM"

        if is_custom:
            if width is None or height is None:
                return self._result(
                    False,
                    "paper_size='custom' requires both width and height",
                    SwErrors.swInvalidInput,
                )
            paper_size_value = int(SwDwgPaperSizes.swDwgPapersUserDefined)
        else:
            if width is not None or height is not None:
                return self._result(
                    False,
                    "width/height are only valid when paper_size='custom' "
                    f"(got paper_size={paper_size!r})",
                    SwErrors.swInvalidInput,
                    {"paper_size": paper_size},
                )
            sizes = _PAPER_SIZES.get(paper_key)
            if sizes is None:
                valid = sorted(_PAPER_SIZES) + ["custom"]
                return self._result(
                    False,
                    f"Unknown paper_size {paper_size!r}; expected one of {valid!r}",
                    SwErrors.swInvalidInput,
                )
            paper_size_value = int(sizes[0])

        if template_path:
            template_in = int(SwDwgTemplates.swDwgTemplateCustom)
            template_name = template_path
        else:
            template_in = int(SwDwgTemplates.swDwgTemplateNone)
            template_name = ""

        try:
            args = NEW_SHEET4.bind(
                units=self._units,
                name=name, paper_size=paper_size_value, template_in=template_in,
                scale1=scale_num, scale2=scale_denom, first_angle=first_angle,
                template_name=template_name,
                width=width if width is not None else 0,
                height=height if height is not None else 0,
            )
            ok = doc.NewSheet4(*args)
        except Exception as e:
            logger.error(f"add_sheet error: {e}")
            return self._result(False, f"Add sheet error: {e}", SwErrors.swUnknownError)

        data = {
            "name": name,
            # Reuses the exact same lookup `list_sheets`/`get_active_sheet` use
            # to render `ISheet::GetProperties2`'s `paperSize` element, so a
            # sheet just created here reports the same `paper_size` spelling
            # a caller would see reading it back (e.g. "A3", not "a3").
            "paper_size": _paper_size_name(paper_size_value),
            "template_path": template_path,
            "scale_num": scale_num, "scale_denom": scale_denom,
            "first_angle": bool(first_angle),
            "width": width, "height": height,
        }

        if not ok:
            return self._result(
                False,
                f"Failed to create sheet {name!r} -- NewSheet4 returned false "
                "(possibly a duplicate name; SolidWorks does not document a "
                "specific failure cause for this call)",
                SwErrors.swFeatureError, data,
            )

        return self._result(True, f"Created sheet {name!r}", SwErrors.swSuccess, data)

    def activate_sheet(self, name: str) -> Dict:
        """
        Make `name` the active sheet via `IDrawingDoc::ActivateSheet`.

        Args:
            name: Sheet name to activate.

        Returns:
            Result dict. Fails with `swInvalidInput` (listing the sheets
            that do exist, via `GetSheetNames`) if `ActivateSheet` returns
            `False` -- its own dossier record documents that as the "no
            sheet with that name" signal.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            ok = doc.ActivateSheet(name)
        except Exception as e:
            logger.error(f"activate_sheet error: {e}")
            return self._result(False, f"Activate sheet error: {e}", SwErrors.swUnknownError)

        if not ok:
            try:
                available = _normalize_sheet_names(doc.GetSheetNames())
            except Exception:
                available = []
            return self._result(
                False,
                f"Sheet {name!r} not found; available sheets: {available!r}",
                SwErrors.swInvalidInput,
                {"name": name, "available_sheets": available},
            )

        return self._result(True, f"Activated sheet {name!r}", SwErrors.swSuccess, {"name": name})

    def _sheet_properties(self, sheet: Any) -> Dict[str, Any]:
        """`ISheet::GetProperties2` -> `{scale_num, scale_denom,
        paper_size_code, paper_size, projection, width, height}`, shared by
        `list_sheets` and `get_active_sheet`.

        Defensive against anything other than the documented 8-element
        `Double` array -- `None`, a short/empty sequence, a non-sequence
        auto-vivified COM stand-in, or a sequence whose individual elements
        aren't the numbers they're documented to be -- every field comes
        back `None` rather than raising, so a sheet whose properties can't
        be read still shows up in `list_sheets`' results instead of the
        whole call raising out of the tool (this project's own "never raise
        out of a tool" rule).
        """
        empty = {
            "scale_num": None, "scale_denom": None,
            "paper_size_code": None, "paper_size": None,
            "projection": None, "width": None, "height": None,
        }

        try:
            props = sheet.GetProperties2()
        except Exception:
            return empty

        if not isinstance(props, (list, tuple)) or len(props) < 7:
            return empty

        try:
            paper_size_code = int(props[0])
            first_angle = bool(props[4])
            return {
                "scale_num": float(props[2]),
                "scale_denom": float(props[3]),
                "paper_size_code": paper_size_code,
                "paper_size": _paper_size_name(paper_size_code),
                "projection": (
                    SwDrawingProjectionType.swDrawing1stAngleProjection.name if first_angle
                    else SwDrawingProjectionType.swDrawing3rdAngleProjection.name
                ),
                "width": self._units.from_meters(float(props[5])),
                "height": self._units.from_meters(float(props[6])),
            }
        except (TypeError, ValueError):
            return empty

    def _count_sheet_views(self, sheet: Any) -> int:
        """Real (non-sheet-pseudo-view) view count on `sheet` via
        `ISheet::GetViews`, filtered the same way `list_views` filters its
        own results (docs/api/02-views.md's Gotchas on that pseudo-entry)."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception:
            views_raw = []
        if not isinstance(views_raw, (list, tuple)):
            return 0

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        count = 0
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            count += 1
        return count

    def list_sheets(self) -> Dict:
        """
        Enumerate every sheet in the active drawing via
        `IDrawingDoc::GetSheetNames`, resolving each name to its `ISheet`
        (via `IDrawingDoc::Sheet`) for its scale/paper-size/projection-type/
        dimensions (`ISheet::GetProperties2`) and view count
        (`ISheet::GetViews`).

        Handles `GetSheetNames` arriving as a tuple, a bare single string, or
        `None` (see `_normalize_sheet_names`) -- the COM-layer quirk this
        issue's acceptance criteria calls out explicitly.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            raw_names = doc.GetSheetNames()
        except Exception as e:
            logger.error(f"list_sheets error: {e}")
            return self._result(False, f"List sheets error: {e}", SwErrors.swUnknownError)

        names = _normalize_sheet_names(raw_names)

        sheets = []
        for sheet_name in names:
            try:
                sheet = doc.Sheet(sheet_name)
            except Exception:
                sheet = None
            if not sheet:
                sheets.append({
                    "name": sheet_name, "scale_num": None, "scale_denom": None,
                    "paper_size_code": None, "paper_size": None, "projection": None,
                    "width": None, "height": None, "view_count": 0,
                })
                continue
            sheets.append({
                "name": sheet_name,
                **self._sheet_properties(sheet),
                "view_count": self._count_sheet_views(sheet),
            })

        return self._result(
            True, f"{len(sheets)} sheet(s)", SwErrors.swSuccess, {"sheets": sheets},
        )

    def get_active_sheet(self) -> Dict:
        """
        Report the currently active sheet's name/scale/paper-size via
        `IDrawingDoc::GetCurrentSheet` + `ISheet::GetProperties2`.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            sheet = doc.GetCurrentSheet()
        except Exception as e:
            logger.error(f"get_active_sheet error: {e}")
            return self._result(False, f"Get active sheet error: {e}", SwErrors.swUnknownError)

        if not sheet:
            return self._result(False, "No active sheet", SwErrors.swFeatureError)

        name = self._read_prop(sheet, "Name")
        data = {"name": name, **self._sheet_properties(sheet)}
        message = f"Active sheet: {name!r}" if name else "Active sheet"
        return self._result(True, message, SwErrors.swSuccess, data)

    def _resolve_named_sheet(
        self, doc: Any, sheet_name: Optional[str],
    ) -> Tuple[Any, Optional[str], Optional[Dict]]:
        """Resolve `sheet_name` (via `IDrawingDoc::Sheet`) or, if omitted,
        the current sheet (via `IDrawingDoc::GetCurrentSheet`), for
        `set_sheet_properties`/`set_sheet_scale`/`get_sheet_properties`.

        Distinct from the file's other `_resolve_sheet` helper (used by the
        view-insertion tools) -- this one also returns the resolved sheet's
        *name* (needed as `SetupSheet5`'s own `Name` argument) and lists
        available sheets on an unknown `sheet_name`, matching
        `activate_sheet`'s own error convention rather than that helper's
        plainer "not found" message.

        Returns `(sheet, name, None)` on success, or `(None, None, error)` --
        `swInvalidInput` (listing available sheets, same convention as
        `activate_sheet`) for an unknown `sheet_name`, `swFeatureError` for
        "no active sheet" when `sheet_name` is omitted.
        """
        if sheet_name:
            try:
                sheet = doc.Sheet(sheet_name)
            except Exception as e:
                logger.error(f"resolve sheet error: {e}")
                return None, None, self._result(
                    False, f"Resolve sheet error: {e}", SwErrors.swUnknownError)
            if not sheet:
                try:
                    available = _normalize_sheet_names(doc.GetSheetNames())
                except Exception:
                    available = []
                return None, None, self._result(
                    False,
                    f"Sheet {sheet_name!r} not found; available sheets: {available!r}",
                    SwErrors.swInvalidInput,
                    {"name": sheet_name, "available_sheets": available},
                )
            return sheet, sheet_name, None

        try:
            sheet = doc.GetCurrentSheet()
        except Exception as e:
            logger.error(f"resolve sheet error: {e}")
            return None, None, self._result(
                False, f"Resolve sheet error: {e}", SwErrors.swUnknownError)
        if not sheet:
            return None, None, self._result(False, "No active sheet", SwErrors.swFeatureError)
        return sheet, self._read_prop(sheet, "Name"), None

    def _read_sheet_setup_state(self, sheet: Any) -> Optional[Dict[str, Any]]:
        """Raw `ISheet::GetProperties2`/`GetTemplateName` fields needed to
        preserve whichever `set_sheet_properties` parameters the caller
        omits: `paper_size_code`, `template_in_code`, `scale_num`,
        `scale_denom`, `first_angle` (a raw bool, unlike `_sheet_properties`'s
        rendered `projection` name string), `width`/`height` (converted to
        the caller's unit via `self._units.from_meters`, same as
        `_sheet_properties` -- so they can be fed straight back into
        `SETUP_SHEET5`'s `to_meters`-converting `width`/`height` Params
        without a caller ever seeing raw meters), and `template_path`.

        `template_path` is `None` whenever `ISheet::GetTemplateName` fails,
        or returns its documented `"*.drt"` sentinel for "this sheet doesn't
        use a real template file" (docs/api/01-documents-and-sheets.md's
        `GetTemplateName` Gotchas) -- a `GetTemplateName` failure alone
        doesn't invalidate the rest of this read, unlike a malformed
        `GetProperties2` array below.

        Returns `None` on anything that isn't the documented 8-element
        `GetProperties2` array -- mirrors `_sheet_properties`'s own
        defensiveness, but returns `None` rather than an all-`None` dict
        since callers here need to distinguish "couldn't read current
        state" (an error) from "read it, every field happened to be None".
        """
        try:
            props = sheet.GetProperties2()
        except Exception:
            return None
        if not isinstance(props, (list, tuple)) or len(props) < 7:
            return None
        try:
            template_path = sheet.GetTemplateName()
        except Exception:
            template_path = None
        if not template_path or template_path == "*.drt":
            template_path = None
        try:
            return {
                "paper_size_code": int(props[0]),
                "template_in_code": int(props[1]),
                "scale_num": float(props[2]),
                "scale_denom": float(props[3]),
                "first_angle": bool(props[4]),
                "width": self._units.from_meters(float(props[5])),
                "height": self._units.from_meters(float(props[6])),
                "template_path": template_path,
            }
        except (TypeError, ValueError):
            return None

    def set_sheet_properties(
        self, sheet_name: Optional[str] = None, paper_size: Optional[str] = None,
        template_path: Optional[str] = None, scale_num: Optional[float] = None,
        scale_denom: Optional[float] = None, first_angle: Optional[bool] = None,
        width: Optional[float] = None, height: Optional[float] = None,
    ) -> Dict:
        """
        Update an existing sheet's setup via `IDrawingDoc::SetupSheet5`,
        preserving every field the caller doesn't pass.

        Unlike `add_sheet`/`NewSheet4` (no prior state to preserve),
        `SetupSheet5` is a full positional overwrite -- passing it a
        caller's *partial* update naively would silently reset every field
        the caller didn't mean to touch. This wrapper reads the sheet's
        current setup first (`ISheet::GetProperties2`) and only substitutes
        the fields actually supplied.

        Args:
            sheet_name: Sheet to update. Omitted (default): the current
                active sheet (`IDrawingDoc::GetCurrentSheet`).
            paper_size: One of `"A"`, `"B"`, `"C"`, `"D"`, `"E"`, `"A0"`-`"A4"`
                (case-insensitive), or `"custom"` to size the sheet from
                `width`/`height` instead. Omitted: keeps the sheet's current
                paper size. Switching a named size on a sheet whose
                `TemplateIn` is `swDwgTemplateNone` sends the sheet's
                current `Width`/`Height` alongside it (see that parameter
                below) -- the dossier's SetupSheet5 table doesn't state
                which one SolidWorks honors in that combination, so whether
                the sheet visibly resizes is unconfirmed against a live
                session.
            template_path: Full path to a custom `.slddrt` sheet-format
                template -- binds `TemplateIn` to `swDwgTemplateCustom` and
                this path as `TemplateName`. Omitted: keeps the sheet's
                current `TemplateIn`/`TemplateName`, read back via
                `GetProperties2`'s `templateIn` element and
                `ISheet::GetTemplateName` respectively -- if the sheet
                currently uses a custom template but `GetTemplateName`
                can't be read back (an unexpected COM failure; not the
                normal path), this fails with `swInvalidInput` rather than
                guessing a `TemplateName`, since a wrong guess there would
                silently replace the sheet's actual current sheet-format
                file (per the dossier's SetupSheet5 Gotchas).
            scale_num, scale_denom: Scale numerator/denominator. Omitted:
                keeps the sheet's current scale. `scale_denom=0` fails with
                `swInvalidInput` without touching COM.
            first_angle: `True` for first-angle projection, `False` for
                third-angle. Omitted: keeps the sheet's current projection.
                Per the dossier's SetupSheet5 Gotchas, a projection change
                only takes visible effect after a rebuild -- this method
                calls `IModelDoc2::ForceRebuild3` itself (best-effort,
                ignored on failure) whenever the effective projection
                actually changes.
            width, height: Sheet dimensions in the caller's unit, converted
                to meters at the COM boundary. Passing either requires the
                *effective* paper size (after applying `paper_size`, or the
                sheet's current one otherwise) to be `"custom"` --
                `swInvalidInput` otherwise. Either given must be positive;
                `swInvalidInput` otherwise. Omitted: keeps the sheet's
                current dimensions (`ISheet::GetProperties2`'s own
                `width`/`height`) regardless of the effective paper size --
                per the dossier's SetupSheet5 table, `Width`/`Height` are
                live SolidWorks-side whenever `TemplateIn` is
                `swDwgTemplateNone`, which this wrapper only ever binds
                `TemplateIn` to besides `swDwgTemplateCustom` -- so passing
                the sheet's real current size here, not `0`, is what keeps
                e.g. a scale-only update from silently shrinking it.

        Returns:
            Result dict; `data` echoes the resolved sheet parameters on
            success. Fails with `swFeatureError` if `SetupSheet5` itself
            returns `False` -- its own dossier record documents no specific
            failure cause for that.
        """
        if scale_denom is not None and scale_denom == 0:
            return self._result(
                False, "scale_denom must be nonzero", SwErrors.swInvalidInput)
        if width is not None and width <= 0:
            return self._result(
                False, f"width must be positive (got {width!r})", SwErrors.swInvalidInput)
        if height is not None and height <= 0:
            return self._result(
                False, f"height must be positive (got {height!r})", SwErrors.swInvalidInput)

        doc, err = self.get_drawing_doc()
        if err:
            return err

        sheet, name, err = self._resolve_named_sheet(doc, sheet_name)
        if err:
            return err
        if not name:
            return self._result(
                False, "Could not determine the target sheet's name -- "
                "SetupSheet5 requires it to identify which sheet to update",
                SwErrors.swUnknownError,
            )

        current = self._read_sheet_setup_state(sheet)
        if current is None:
            return self._result(
                False, f"Could not read current properties for sheet {name!r}",
                SwErrors.swUnknownError, {"name": name},
            )

        if paper_size is not None:
            paper_key = paper_size.strip().upper()
            if paper_key == "CUSTOM":
                effective_paper_size = int(SwDwgPaperSizes.swDwgPapersUserDefined)
            else:
                sizes = _PAPER_SIZES.get(paper_key)
                if sizes is None:
                    valid = sorted(_PAPER_SIZES) + ["custom"]
                    return self._result(
                        False,
                        f"Unknown paper_size {paper_size!r}; expected one of {valid!r}",
                        SwErrors.swInvalidInput,
                    )
                effective_paper_size = int(sizes[0])
        else:
            effective_paper_size = current["paper_size_code"]

        is_custom = effective_paper_size == int(SwDwgPaperSizes.swDwgPapersUserDefined)
        if (width is not None or height is not None) and not is_custom:
            return self._result(
                False,
                "width/height are only valid when the effective paper_size is "
                f"'custom' (got paper_size={paper_size!r})",
                SwErrors.swInvalidInput,
                {"paper_size": paper_size},
            )

        # Per the dossier's SetupSheet5 table, Width/Height are valid
        # whenever TemplateIn is swDwgTemplateNone *or* PaperSize is
        # swDwgPapersUserDefined -- an OR, not an AND restricted to a custom
        # paper size. This wrapper only ever binds TemplateIn to
        # swDwgTemplateNone or swDwgTemplateCustom (never one of the
        # swDwgTemplates_e sized-template members), so on the common
        # TemplateIn=None sheet -- e.g. anything `add_sheet` created with its
        # own defaults -- Width/Height are live even for a plain named
        # paper_size like "A3". Defaulting them to `current`'s real
        # dimensions here (rather than `0`) whenever the caller didn't
        # override them is what keeps a scale-only update from silently
        # zeroing out the sheet's actual size on exactly that sheet.
        effective_width = width if width is not None else current["width"]
        effective_height = height if height is not None else current["height"]

        if template_path:
            template_in = int(SwDwgTemplates.swDwgTemplateCustom)
            template_name = template_path
        elif current["template_in_code"] == int(SwDwgTemplates.swDwgTemplateCustom):
            if not current["template_path"]:
                return self._result(
                    False,
                    f"Sheet {name!r} reports TemplateIn=swDwgTemplateCustom, but "
                    "ISheet::GetTemplateName doesn't report a real template file "
                    "for it (a COM read failure, or its documented \"*.drt\" "
                    "no-real-template sentinel); pass template_path explicitly "
                    "to avoid silently clearing whatever it's actually set to",
                    SwErrors.swInvalidInput,
                    {"name": name},
                )
            template_in = int(SwDwgTemplates.swDwgTemplateCustom)
            template_name = current["template_path"]
        else:
            template_in = current["template_in_code"]
            template_name = ""

        effective_scale_num = scale_num if scale_num is not None else current["scale_num"]
        effective_scale_denom = scale_denom if scale_denom is not None else current["scale_denom"]
        effective_first_angle = first_angle if first_angle is not None else current["first_angle"]

        try:
            args = SETUP_SHEET5.bind(
                units=self._units,
                name=name, paper_size=effective_paper_size, template_in=template_in,
                scale1=effective_scale_num, scale2=effective_scale_denom,
                first_angle=effective_first_angle, template_name=template_name,
                width=effective_width, height=effective_height,
            )
            ok = doc.SetupSheet5(*args)
        except Exception as e:
            logger.error(f"set_sheet_properties error: {e}")
            return self._result(False, f"Set sheet properties error: {e}", SwErrors.swUnknownError)

        data = {
            "name": name,
            "paper_size": _paper_size_name(effective_paper_size),
            "template_path": (
                template_name if template_in == int(SwDwgTemplates.swDwgTemplateCustom) else None
            ),
            "scale_num": effective_scale_num, "scale_denom": effective_scale_denom,
            "first_angle": bool(effective_first_angle),
            "width": effective_width, "height": effective_height,
        }

        if not ok:
            return self._result(
                False,
                f"Failed to update sheet {name!r} -- SetupSheet5 returned false "
                "(SolidWorks does not document a specific failure cause for this call)",
                SwErrors.swFeatureError, data,
            )

        if bool(effective_first_angle) != current["first_angle"]:
            # Per docs/api/01-documents-and-sheets.md's SetupSheet5 Gotchas:
            # a projection change needs a rebuild to actually show up in the
            # drawing views. Best-effort -- SetupSheet5 itself already
            # succeeded, so a rebuild failure here doesn't fail the call.
            try:
                doc.ForceRebuild3(False)
            except Exception as e:
                logger.warning(f"set_sheet_properties: post-update rebuild failed: {e}")

        return self._result(True, f"Updated sheet {name!r}", SwErrors.swSuccess, data)

    def set_sheet_scale(
        self, scale_num: float, scale_denom: float, sheet_name: Optional[str] = None,
    ) -> Dict:
        """Thin convenience over `set_sheet_properties` -- update only a
        sheet's scale, leaving every other field untouched."""
        return self.set_sheet_properties(
            sheet_name=sheet_name, scale_num=scale_num, scale_denom=scale_denom)

    def get_sheet_properties(self, sheet_name: Optional[str] = None) -> Dict:
        """
        Read back a sheet's name, paper size, scale (numeric pair and a
        readable `"1:2"`-style ratio string), projection angle, dimensions,
        and template info via `ISheet::GetProperties2` + `GetTemplateName`.

        Args:
            sheet_name: Sheet to read. Omitted (default): the current active
                sheet (`IDrawingDoc::GetCurrentSheet`).

        Returns:
            Result dict. `data["template_path"]` is `None` when the sheet
            doesn't use a real template file -- `GetTemplateName`'s
            documented `"*.drt"` sentinel for that case, per the dossier's
            `ISheet::GetTemplateName` Gotchas -- otherwise the template's
            full path.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        sheet, name, err = self._resolve_named_sheet(doc, sheet_name)
        if err:
            return err
        if not name:
            return self._result(
                False, "Could not determine the sheet's name", SwErrors.swUnknownError)

        current = self._read_sheet_setup_state(sheet)
        if current is None:
            return self._result(
                False, f"Could not read properties for sheet {name!r}",
                SwErrors.swUnknownError, {"name": name},
            )

        data = {
            "name": name,
            "paper_size_code": current["paper_size_code"],
            "paper_size": _paper_size_name(current["paper_size_code"]),
            "scale_num": current["scale_num"], "scale_denom": current["scale_denom"],
            "scale_ratio": _scale_ratio_string(current["scale_num"], current["scale_denom"]),
            "projection": (
                SwDrawingProjectionType.swDrawing1stAngleProjection.name
                if current["first_angle"]
                else SwDrawingProjectionType.swDrawing3rdAngleProjection.name
            ),
            "width": current["width"], "height": current["height"],
            "template_in": _template_in_name(current["template_in_code"]),
            "template_path": current["template_path"],
        }
        return self._result(True, f"Sheet {name!r} properties", SwErrors.swSuccess, data)

    def copy_sheet(self, source_sheet: str, new_name: Optional[str] = None,
                    count: int = 1) -> Dict:
        """
        Duplicate a sheet via the select + `IModelDoc2::EditCopy` +
        `IDrawingDoc::PasteSheet` workaround -- `IDrawingDoc` has no direct
        `CopySheet` API (docs/api/01-documents-and-sheets.md's `PasteSheet`
        record: confirmed absent from the `IDrawingDoc` member index, same
        as `DeleteSheet`).

        Per this issue's acceptance criteria, this workaround is guarded
        rather than looped blindly: after each copy, the sheet list is
        re-read and the copy is refused/reported as failed unless exactly
        one new sheet name actually appears (`PasteSheet`'s own `Boolean`
        return has no documented failure cause to rely on alone).

        Args:
            source_sheet: Name of the sheet to copy. Re-selected fresh
                before each copy (matching SolidWorks' own worked example)
                -- never consumed, renamed, or itself modified.
            new_name: Rename the single created copy to this name. Only
                valid with `count=1`: `PasteSheet` has no name parameter
                (SolidWorks auto-names each copy, e.g. `"Sheet1(2)"`), and
                this tool does not guess a naming pattern for multiple
                copies -- `new_name` with `count != 1` fails with
                `swInvalidInput` before any COM call.
            count: Number of copies to create. Must be a positive integer.

        Returns:
            Result dict. `data["created"]` lists the new sheet name(s), in
            creation order; `data["sheets"]` is the full sheet list
            re-read after the last copy. Fails with `swInvalidInput` if
            `source_sheet` doesn't exist, `new_name` already exists, or
            `count`/`new_name` are combined invalidly -- none of these make
            any COM call. Fails with `swFeatureError` if `PasteSheet`
            itself returns `False`, or if the sheet count doesn't actually
            increase by one after a `PasteSheet` that returned `True`.
        """
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return self._result(
                False, f"count must be a positive integer (got {count!r})",
                SwErrors.swInvalidInput,
            )
        if new_name is not None and count != 1:
            return self._result(
                False,
                "new_name is only valid with count=1 -- PasteSheet has no name "
                "parameter (SolidWorks auto-names each copy) and this tool "
                "doesn't guess a naming pattern for multiple copies",
                SwErrors.swInvalidInput,
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            before_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            logger.error(f"copy_sheet error: {e}")
            return self._result(False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)

        if source_sheet not in before_names:
            return self._result(
                False,
                f"Sheet {source_sheet!r} not found; available sheets: {before_names!r}",
                SwErrors.swInvalidInput,
                {"name": source_sheet, "available_sheets": before_names},
            )
        if new_name is not None and new_name in before_names:
            return self._result(
                False, f"Sheet {new_name!r} already exists", SwErrors.swInvalidInput,
                {"new_name": new_name, "available_sheets": before_names},
            )

        try:
            before_count = int(doc.GetSheetCount())
        except Exception as e:
            logger.error(f"copy_sheet error: {e}")
            return self._result(False, f"Could not read sheet count: {e}", SwErrors.swUnknownError)

        seen = set(before_names)
        created: List[str] = []

        for i in range(count):
            with self.selected(source_sheet, "SHEET", 0, 0, 0) as sel:
                if not sel["success"]:
                    return self._result(
                        False,
                        f"Created {created!r} but could not select {source_sheet!r} "
                        f"to copy: {sel['message']}",
                        SwErrors.swSelectionError, {"created": created},
                    )
                try:
                    doc.EditCopy()
                    # swInsertOption_MoveToEnd, not *_AfterSelectedSheet: since
                    # source_sheet is re-selected fresh before every copy (see
                    # this method's own docstring), *_AfterSelectedSheet would
                    # insert each new copy immediately after source_sheet,
                    # pushing every earlier copy further along -- reversing
                    # tab order relative to data["created"]'s creation order
                    # for count>1. MoveToEnd keeps both orders the same.
                    pasted = doc.PasteSheet(
                        int(SwInsertOptions.swInsertOption_MoveToEnd),
                        int(SwRenameOptions.swRenameOption_No),
                    )
                except Exception as e:
                    logger.error(f"copy_sheet error: {e}")
                    return self._result(
                        False, f"Created {created!r} but copy {i + 1} failed: {e}",
                        SwErrors.swUnknownError, {"created": created},
                    )

            if not pasted:
                return self._result(
                    False,
                    f"Created {created!r} but PasteSheet returned false for copy {i + 1}",
                    SwErrors.swFeatureError, {"created": created},
                )

            # The guard this issue's acceptance criteria calls for: don't
            # trust PasteSheet's own Boolean alone -- confirm the sheet
            # count (IDrawingDoc::GetSheetCount) actually went up by
            # exactly one before treating this copy as real.
            try:
                after_count = int(doc.GetSheetCount())
            except Exception as e:
                return self._result(
                    False,
                    f"Created {created!r}, but could not re-read the sheet count "
                    f"after copy {i + 1}: {e}",
                    SwErrors.swUnknownError, {"created": created},
                )

            if after_count != before_count + 1:
                return self._result(
                    False,
                    f"Created {created!r}, but the sheet count did not increase by "
                    f"one after copy {i + 1} (was {before_count}, now {after_count}) "
                    "-- PasteSheet reported success but no new sheet appeared",
                    SwErrors.swFeatureError, {"created": created},
                )

            try:
                after_names = _normalize_sheet_names(doc.GetSheetNames())
            except Exception as e:
                return self._result(
                    False,
                    f"Created {created!r}, but could not re-read sheet names after "
                    f"copy {i + 1}: {e}",
                    SwErrors.swUnknownError, {"created": created},
                )

            new_names = [n for n in after_names if n not in seen]
            if len(new_names) != 1:
                return self._result(
                    False,
                    f"Created {created!r}, and the sheet count increased after copy "
                    f"{i + 1}, but the new sheet's name could not be identified "
                    f"unambiguously: {new_names!r}",
                    SwErrors.swUnknownError, {"created": created},
                )

            pasted_name = new_names[0]
            seen.add(pasted_name)
            created.append(pasted_name)
            before_count = after_count

        if new_name is not None:
            [only] = created
            try:
                sheet = doc.Sheet(only)
            except Exception as e:
                return self._result(
                    False, f"Created {only!r} but could not resolve it to rename: {e}",
                    SwErrors.swUnknownError, {"created": created},
                )
            if not sheet:
                return self._result(
                    False, f"Created {only!r} but could not resolve it to rename",
                    SwErrors.swUnknownError, {"created": created},
                )
            try:
                sheet.SetName(new_name)
            except Exception as e:
                return self._result(
                    False, f"Created {only!r} but rename to {new_name!r} failed: {e}",
                    SwErrors.swUnknownError, {"created": created},
                )

        try:
            final_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            return self._result(
                False,
                f"Copies created ({created!r}) but could not re-read the final "
                f"sheet list: {e}",
                SwErrors.swUnknownError, {"created": created},
            )

        if new_name is not None:
            # SetName is a bare Sub with no return value/failure signal
            # (docs/api/01-documents-and-sheets.md's SetName record) -- same
            # "confirm what actually happened" check rename_sheet does.
            if new_name not in final_names:
                return self._result(
                    False,
                    f"SetName({new_name!r}) did not raise, but {new_name!r} does "
                    f"not appear in the sheet list afterward: {final_names!r}",
                    SwErrors.swUnknownError, {"created": created, "sheets": final_names},
                )
            created = [new_name]

        return self._result(
            True, f"Created {len(created)} sheet(s): {created!r}", SwErrors.swSuccess,
            {"created": created, "sheets": final_names},
        )

    def delete_sheet(self, name: str) -> Dict:
        """
        Delete a sheet via the select + `IModelDocExtension::DeleteSelection2`
        workaround -- `IDrawingDoc` has no direct `DeleteSheet` API (this
        dossier's own `DeleteSheet` record: confirmed absent from the
        `IDrawingDoc` member index).

        Refuses to delete the last remaining sheet -- a drawing with zero
        sheets is not a state any other tool in this project expects --
        without making any COM call.

        Args:
            name: Sheet to delete.

        Returns:
            Result dict. `data["sheets"]` is the sheet list re-read after
            the deletion (or, on a refusal/failure, the sheet list as read
            before attempting anything). Fails with `swInvalidInput` if
            `name` doesn't exist or is the only remaining sheet -- neither
            makes a `DeleteSelection2` call. Fails with `swFeatureError` if
            `DeleteSelection2` itself returns `False`.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            before_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            logger.error(f"delete_sheet error: {e}")
            return self._result(False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)

        if name not in before_names:
            return self._result(
                False,
                f"Sheet {name!r} not found; available sheets: {before_names!r}",
                SwErrors.swInvalidInput,
                {"name": name, "available_sheets": before_names},
            )
        if len(before_names) <= 1:
            return self._result(
                False,
                f"Cannot delete {name!r} -- it is the only remaining sheet",
                SwErrors.swInvalidInput,
                {"name": name, "sheets": before_names},
            )

        with self.selected(name, "SHEET", 0, 0, 0) as sel:
            if not sel["success"]:
                return self._result(
                    False, f"Could not select {name!r} to delete: {sel['message']}",
                    SwErrors.swSelectionError, {"name": name, "sheets": before_names},
                )
            try:
                deleted = doc.Extension.DeleteSelection2(0)
            except Exception as e:
                logger.error(f"delete_sheet error: {e}")
                return self._result(
                    False, f"Delete sheet error: {e}", SwErrors.swUnknownError,
                    {"name": name, "sheets": before_names},
                )

        if not deleted:
            return self._result(
                False, f"Failed to delete sheet {name!r}",
                SwErrors.swFeatureError, {"name": name, "sheets": before_names},
            )

        try:
            after_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            return self._result(
                False, f"Deleted {name!r} but could not re-read sheet names: {e}",
                SwErrors.swUnknownError, {"name": name},
            )

        return self._result(
            True, f"Deleted sheet {name!r}", SwErrors.swSuccess,
            {"name": name, "sheets": after_names},
        )

    def rename_sheet(self, old_name: str, new_name: str) -> Dict:
        """
        Rename a sheet via `ISheet::SetName` -- a bare `Sub` with no return
        value or documented failure signal (this dossier's own `SetName`
        record), so this wrapper checks for a name collision itself before
        calling it and re-reads `GetSheetNames` afterward to confirm what
        actually happened rather than trusting the call silently worked.

        Args:
            old_name: Sheet to rename.
            new_name: New name. Fails with `swInvalidInput` (no COM call)
                if a sheet with this name already exists.

        Returns:
            Result dict. `data["sheets"]` is the sheet list re-read after
            the rename. Fails with `swInvalidInput` if `old_name` doesn't
            exist or `new_name` collides with an existing sheet. Fails
            with `swUnknownError` if, after calling `SetName`, `new_name`
            doesn't actually appear in the re-read sheet list -- `SetName`
            gives no other way to detect that.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            before_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            logger.error(f"rename_sheet error: {e}")
            return self._result(False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)

        if old_name not in before_names:
            return self._result(
                False,
                f"Sheet {old_name!r} not found; available sheets: {before_names!r}",
                SwErrors.swInvalidInput,
                {"name": old_name, "available_sheets": before_names},
            )
        if new_name in before_names:
            return self._result(
                False, f"Sheet {new_name!r} already exists", SwErrors.swInvalidInput,
                {"new_name": new_name, "available_sheets": before_names},
            )

        try:
            sheet = doc.Sheet(old_name)
        except Exception as e:
            logger.error(f"rename_sheet error: {e}")
            return self._result(False, f"Resolve sheet error: {e}", SwErrors.swUnknownError)
        if not sheet:
            return self._result(
                False, f"Sheet {old_name!r} not found; available sheets: {before_names!r}",
                SwErrors.swInvalidInput,
                {"name": old_name, "available_sheets": before_names},
            )

        try:
            sheet.SetName(new_name)
        except Exception as e:
            logger.error(f"rename_sheet error: {e}")
            return self._result(
                False, f"Rename sheet error: {e}", SwErrors.swUnknownError,
                {"name": old_name, "new_name": new_name},
            )

        try:
            after_names = _normalize_sheet_names(doc.GetSheetNames())
        except Exception as e:
            return self._result(
                False,
                f"Renamed {old_name!r} to {new_name!r} but could not re-read sheet "
                f"names: {e}",
                SwErrors.swUnknownError, {"name": old_name, "new_name": new_name},
            )

        if new_name not in after_names:
            return self._result(
                False,
                f"SetName({new_name!r}) did not raise, but {new_name!r} does not "
                f"appear in the sheet list afterward: {after_names!r}",
                SwErrors.swUnknownError,
                {"name": old_name, "new_name": new_name, "sheets": after_names},
            )

        return self._result(
            True, f"Renamed sheet {old_name!r} to {new_name!r}", SwErrors.swSuccess,
            {"name": old_name, "new_name": new_name, "sheets": after_names},
        )

    # ========================================================================
    # View creation / discovery tools
    # ========================================================================

    @staticmethod
    def _read_prop(obj: Any, name: str) -> Any:
        """Read a COM member that some SolidWorks interop layers expose as a
        bare attribute and others as a zero-arg method -- the same
        property/method duality `_get_doc_type` above works around, reused
        here for `IView::Type`/`ScaleDecimal`/`Position` and `ISheet::Name`
        (all documented as VB properties in docs/api/02-views.md, but the
        fake-COM harness's dual-purpose wrapper -- and, per this project's
        prior experience, some real interop layers -- makes every one of
        them callable too).

        Returns `None` (never raises) if the member is missing or the read
        itself fails, so callers can treat a failed/unsupported read the
        same as "no data" rather than special-casing it.
        """
        try:
            value = getattr(obj, name)
        except Exception:
            return None
        if callable(value):
            try:
                return value()
            except Exception:
                return None
        return value

    def _resolve_model_view_name(self, view_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Map a friendly orientation name to the `*Name` form
        `CreateDrawViewFromModelView3` expects (docs/api/02-views.md's
        "Front" vs "*Front" gotcha).

        Returns `(resolved_name, None)` on success, or `(None,
        error_message)` for anything not in `_STANDARD_MODEL_VIEWS` --
        listing the valid names, rather than passing an unrecognized string
        straight through to SolidWorks and letting a typo silently fail as
        `CreateDrawViewFromModelView3` returning `Nothing`.
        """
        key = (view_name or "").strip().lstrip("*").lower()
        resolved = _STANDARD_MODEL_VIEWS.get(key)
        if resolved is None:
            valid = ", ".join(
                _STANDARD_MODEL_VIEWS[k] for k in sorted(_STANDARD_MODEL_VIEWS)
            )
            return None, f"Unknown view_name {view_name!r}; expected one of: {valid}"
        return resolved, None

    def insert_model_view(self, model_path: str, view_name: str = "*Front",
                           x: float = 0, y: float = 0,
                           sheet_name: Optional[str] = None) -> Dict:
        """
        Place a model view on a drawing sheet via
        `IDrawingDoc::CreateDrawViewFromModelView3`.

        Args:
            model_path: Full pathname of the model document
                (.sldprt/.sldasm) to project a view of.
            view_name: One of Front/Top/Right/Left/Bottom/Back/Isometric/
                Dimetric/Trimetric/Current (case-insensitive, with or
                without a leading "*") -- resolved to the `*Name` form via
                `_resolve_model_view_name`. Anything else fails with
                `swInvalidInput` listing the valid names.
            x, y: View center, in the caller's default unit (`set_units`) --
                converted to sheet-space meters here. `LocZ` is always `0`:
                sheet space is 2D, and the dossier confirms it's inert.
            sheet_name: Sheet to place the view on, activated via
                `IDrawingDoc::ActivateSheet` first. Omitted: whichever sheet
                is already active.

        Returns:
            Result dict. On success, `data["view_name"]` is the created
            view's actual name (`IView::GetName2`) -- what later
            annotation/view tools address it by. A `None` return from
            `CreateDrawViewFromModelView3` (the dossier's documented
            failure signal -- no error code, just `Nothing`) fails with
            `swFeatureError`, naming the model path and resolved view name.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        resolved_view_name, error_message = self._resolve_model_view_name(view_name)
        if resolved_view_name is None:
            return self._result(
                False, error_message, SwErrors.swInvalidInput, {"view_name": view_name},
            )

        if sheet_name:
            try:
                activated = doc.ActivateSheet(sheet_name)
            except Exception as e:
                logger.error(f"insert_model_view activate sheet error: {e}")
                return self._result(False, f"Activate sheet error: {e}", SwErrors.swInvalidInput)
            if not activated:
                return self._result(
                    False, f"Sheet {sheet_name!r} not found", SwErrors.swInvalidInput,
                    {"sheet_name": sheet_name},
                )

        x_m = self._units.to_meters(x)
        y_m = self._units.to_meters(y)

        try:
            view = doc.CreateDrawViewFromModelView3(model_path, resolved_view_name, x_m, y_m, 0.0)
        except Exception as e:
            logger.error(f"insert_model_view error: {e}")
            return self._result(False, f"Insert model view error: {e}", SwErrors.swFeatureError)

        if view is None:
            return self._result(
                False,
                f"Failed to create view {resolved_view_name!r} from model {model_path!r}",
                SwErrors.swFeatureError,
                {"model_path": model_path, "view_name": resolved_view_name},
            )

        created_name = self._read_prop(view, "GetName2")

        return self._result(
            True, f"Inserted view {created_name or resolved_view_name!r}", SwErrors.swSuccess,
            {
                "model_path": model_path, "view_name": created_name,
                "requested_view_name": resolved_view_name,
                "x": x, "y": y, "sheet_name": sheet_name,
            },
        )

    def insert_standard_3_view(self, model_path: str, first_angle: bool = False,
                                auto_scale: bool = True) -> Dict:
        """
        Insert the standard three-view set via
        `IDrawingDoc::Create3rdAngleViews2` (ANSI/third-angle, the default)
        or `Create1stAngleViews2` (ISO/first-angle, `first_angle=True`).

        Both methods respect the `swAutomaticScaling3ViewDrawings` user
        preference rather than taking a scale argument of their own
        (docs/api/02-views.md's Gotchas on both records). This wrapper
        snapshots the preference's current value via
        `ISldWorks::GetUserPreferenceToggle`, writes `auto_scale` via
        `SetUserPreferenceToggle` for the duration of the call, and restores
        the original value afterward in a `finally` -- on both the success
        and the exception path -- so the operator's SolidWorks install
        setting is never silently left changed by an automation run.

        Args:
            model_path: Full pathname of the model document to build the
                3-view set from.
            first_angle: `False` (default) uses `Create3rdAngleViews2`
                (ANSI); `True` uses `Create1stAngleViews2` (ISO).
            auto_scale: Value to write to `swAutomaticScaling3ViewDrawings`
                for the duration of this call.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        toggle = int(SwUserPreferenceToggle.swAutomaticScaling3ViewDrawings)
        try:
            original_auto_scale = self._sw_app.GetUserPreferenceToggle(toggle)
        except Exception as e:
            logger.error(f"insert_standard_3_view read preference error: {e}")
            return self._result(False, f"Read preference error: {e}", SwErrors.swUnknownError)

        try:
            self._sw_app.SetUserPreferenceToggle(toggle, bool(auto_scale))
        except Exception as e:
            logger.error(f"insert_standard_3_view set preference error: {e}")
            return self._result(False, f"Set preference error: {e}", SwErrors.swUnknownError)

        data = {"model_path": model_path, "first_angle": first_angle, "auto_scale": auto_scale}
        try:
            if first_angle:
                created = doc.Create1stAngleViews2(model_path)
            else:
                created = doc.Create3rdAngleViews2(model_path)
        except Exception as e:
            logger.error(f"insert_standard_3_view error: {e}")
            return self._result(False, f"Insert standard 3 view error: {e}",
                                SwErrors.swFeatureError, data)
        finally:
            try:
                self._sw_app.SetUserPreferenceToggle(toggle, bool(original_auto_scale))
            except Exception as e:
                logger.error(f"insert_standard_3_view restore preference error: {e}")

        if not created:
            return self._result(
                False, f"Failed to create standard 3-view set from {model_path!r}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True, f"Inserted standard 3-view set from {model_path!r}", SwErrors.swSuccess, data,
        )

    def _view_referenced_model(self, view: Any, base_view: Any = None) -> Optional[str]:
        """Best-effort "what model does this view come from", via
        `IView::ReferencedDocument` -- falling back to the base/parent
        view's `ReferencedDocument` for section/detail views, which have
        none of their own (docs/api/02-views.md's `ReferencedDocument`
        record's Gotchas).
        """
        for candidate in (view, base_view):
            if candidate is None:
                continue
            ref_doc = self._read_prop(candidate, "ReferencedDocument")
            if not ref_doc:
                continue
            path = self._get_doc_path(ref_doc)
            if path:
                return path
            title = self._get_doc_title(ref_doc)
            if title and title != "Unknown":
                return title
        return None

    def _describe_view(self, view: Any) -> Dict:
        """One view's `list_views` record: name, type, scale, position
        (docs/api/02-views.md's "View naming, type, alignment" and "View
        properties" records), plus referenced model and parent view (this
        issue's "View enumeration and metadata" addendum to that dossier).
        """
        name = self._read_prop(view, "GetName2")

        type_code = self._read_prop(view, "Type")
        type_name = None
        if isinstance(type_code, (int, float)) and not isinstance(type_code, bool):
            try:
                type_name = SwDrawingViewTypes(int(type_code)).name
            except ValueError:
                type_name = f"unknown type {int(type_code)}"

        scale = self._read_prop(view, "ScaleDecimal")
        if not isinstance(scale, (int, float)) or isinstance(scale, bool):
            scale = None

        position = self._read_prop(view, "Position")
        x = y = None
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                x = self._units.from_meters(float(position[0]))
                y = self._units.from_meters(float(position[1]))
            except (TypeError, ValueError):
                x = y = None

        base_view = None
        try:
            candidate = view.GetBaseView()
        except Exception:
            candidate = None
        if candidate:
            base_view = candidate
        parent_view = self._read_prop(base_view, "GetName2") if base_view else None

        return {
            "name": name,
            "type": type_name,
            "type_code": int(type_code) if isinstance(type_code, (int, float))
                and not isinstance(type_code, bool) else None,
            "scale": scale,
            "x": x,
            "y": y,
            "referenced_model": self._view_referenced_model(view, base_view),
            "parent_view": parent_view,
        }

    def list_views(self, sheet_name: Optional[str] = None) -> Dict:
        """
        Enumerate views on a sheet -- name, type, scale, position,
        referenced model, and parent view -- via `ISheet::GetViews`. The
        discovery tool every later view/annotation tool needs to address a
        view by name.

        Args:
            sheet_name: Sheet to enumerate, resolved via `IDrawingDoc::Sheet`.
                Omitted: whichever sheet `IDrawingDoc::GetCurrentSheet`
                reports as active.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            if sheet_name:
                sheet = doc.Sheet(sheet_name)
                if not sheet:
                    return self._result(
                        False, f"Sheet {sheet_name!r} not found", SwErrors.swInvalidInput,
                        {"sheet_name": sheet_name},
                    )
            else:
                sheet = doc.GetCurrentSheet()
                if not sheet:
                    return self._result(False, "No active sheet", SwErrors.swFeatureError)
                raw_name = self._read_prop(sheet, "Name")
                sheet_name = raw_name if isinstance(raw_name, str) else None

            views_raw = sheet.GetViews()
        except Exception as e:
            logger.error(f"list_views error: {e}")
            return self._result(False, f"List views error: {e}", SwErrors.swUnknownError)

        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        # `ISheet::GetViews`'s own record documents it as *not* heading its
        # array with the sheet's own pseudo-view entry, unlike
        # `IDrawingDoc::GetViews` -- but that's an inference from one working
        # macro's unconditional `For Each`, flagged unverified in the
        # dossier. Filtering defensively here costs nothing on a harness
        # that behaves as documented, and avoids surfacing a bogus
        # "Sheet1"/`swDrawingSheet` entry as an addressable view if it
        # doesn't. Only filter when `type_code` was actually readable --
        # a real view with an unreadable `Type` must not silently vanish.
        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        views = []
        for view in views_raw:
            described = self._describe_view(view)
            if described["type_code"] == sheet_type_code:
                continue
            views.append(described)

        return self._result(
            True, f"{len(views)} view(s) on sheet {sheet_name!r}", SwErrors.swSuccess,
            {"sheet_name": sheet_name, "views": views},
        )

    def _resolve_sheet(self, doc, sheet_name: Optional[str]) -> Tuple[Any, Optional[Dict]]:
        """Resolve `sheet_name` (or the active sheet if omitted) to an
        `ISheet` reference -- the shared entry point `insert_projected_view`/
        `insert_auxiliary_view`/`insert_predefined_views` use to find the
        views already on a sheet, mirroring `list_views`' own resolution.
        """
        try:
            if sheet_name:
                sheet = doc.Sheet(sheet_name)
                if not sheet:
                    return None, self._result(
                        False, f"Sheet {sheet_name!r} not found", SwErrors.swInvalidInput,
                        {"sheet_name": sheet_name},
                    )
            else:
                sheet = doc.GetCurrentSheet()
                if not sheet:
                    return None, self._result(False, "No active sheet", SwErrors.swFeatureError)
        except Exception as e:
            logger.error(f"_resolve_sheet error: {e}")
            return None, self._result(False, f"Resolve sheet error: {e}", SwErrors.swUnknownError)

        return sheet, None

    def _sheet_view_fill_state(self, sheet: Any) -> Dict[str, bool]:
        """`{view_name: has_referenced_model}` for every real
        (non-sheet-pseudo-view) view on `sheet`, via `ISheet::GetViews` +
        `IView::ReferencedDocument` -- what `insert_predefined_views` uses to
        tell an *unfilled* predefined-view placeholder from a filled one.

        A predefined-view placeholder is a real, named view object on the
        sheet from the moment it's authored on the template (Insert >
        Drawing View > Predefined) -- `InsertModelInPredefinedView` only
        fills it, per docs/api/02-views.md's Gotchas, it doesn't create a new
        tree entry. So a before/after diff of *view names* never changes
        (the placeholder was already named), and would wrongly read as "no
        predefined views" even on a real fill. Whether the placeholder
        references a model (`IView::ReferencedDocument`, non-empty only
        once a model has actually been inserted into it) is what actually
        flips across the call, so that -- not name-appearance -- is the
        fill signal."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception:
            views_raw = []
        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        state: Dict[str, bool] = {}
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            state[name] = bool(self._read_prop(view, "ReferencedDocument"))
        return state

    def _find_view_by_name(self, doc, view_name: str,
                            sheet_name: Optional[str] = None) -> Tuple[Any, List[str], Optional[Dict]]:
        """Resolve `view_name` to its raw `IView` object on `sheet_name` (or
        the active sheet), via `ISheet::GetViews` -- what `insert_projected_view`
        and `insert_auxiliary_view` use to validate a caller-supplied parent
        view name against what's actually on the sheet, listing the real
        names on a miss rather than passing an unrecognized string straight
        through to a COM call whose only failure signal is a bare `Nothing`.

        Returns:
            `(view, names, None)` on a sheet-resolution success -- `view` is
            `None` (with `names` populated) if no view on the sheet has that
            name. `(None, [], error_dict)` if the sheet itself couldn't be
            resolved.
        """
        sheet, err = self._resolve_sheet(doc, sheet_name)
        if err:
            return None, [], err

        try:
            views_raw = sheet.GetViews() or []
        except Exception as e:
            logger.error(f"_find_view_by_name error: {e}")
            return None, [], self._result(False, f"List views error: {e}", SwErrors.swUnknownError)
        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        names = []
        match = None
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            name = self._read_prop(view, "GetName2")
            if name:
                names.append(name)
            if name == view_name:
                match = view

        return match, names, None

    def insert_projected_view(self, parent_view_name: str, direction: str,
                               offset: Optional[float] = None,
                               sheet_name: Optional[str] = None) -> Dict:
        """
        Project a new drawing view off an existing one via
        `IDrawingDoc::CreateUnfoldedViewAt3` -- the API's real name for what
        the UI calls "Insert Projected View" (docs/api/02-views.md's
        Projected views section: no `*Project*`-named method exists on
        `IDrawingDoc`/`IView`; `CreateUnfoldedViewAt3` is the same
        operation).

        Args:
            parent_view_name: Name of the existing drawing view to project
                from (`IView::GetName2`, e.g. from `list_views`). Selected
                via `selected(..., "DRAWINGVIEW", ...)` before the call --
                `CreateUnfoldedViewAt3` takes no parent-view parameter and
                operates on whatever is currently selected. An unrecognized
                name fails with `swInvalidInput` listing every view actually
                on the sheet, rather than reaching the COM call and getting
                back an unexplained `Nothing`.
            direction: One of `up`/`down`/`left`/`right`/`upleft`/`upright`/
                `downleft`/`downright` (case-insensitive). The four cardinal
                directions keep the projection orthographically aligned to
                its parent (`NotAligned=False`, matching drag-off-an-edge UI
                behavior); the four diagonals have no aligned-projection
                equivalent in SolidWorks, so those break alignment
                (`NotAligned=True`) to be freely positioned off-axis.
            offset: Distance from the parent view's center to the new
                view's center, in the caller's default unit (`set_units`).
                `CreateUnfoldedViewAt3` always requires *some* X/Y (there is
                no "just use the default placement" call shape), so a small
                fixed nudge in the requested direction is used for the
                creation call itself regardless of `offset` -- when `offset`
                is given, the view is then moved to the exact requested
                distance afterward via the `IView::Position` setter (plus an
                `EditRebuild3` to force the regenerate its Gotchas call for),
                rather than pretending `CreateUnfoldedViewAt3`'s own X/Y
                argument is an honored placement request for an aligned view
                (docs/api/02-views.md's `IView::Position` Gotchas: an aligned
                view "can only move along the alignment vector" regardless
                of what's passed to the creation call).
            sheet_name: Sheet the parent view lives on, resolved the same
                way `list_views` does. Omitted: whichever sheet
                `IDrawingDoc::GetCurrentSheet` reports as active.

        Returns:
            Result dict. On success, `data["view_name"]` is the created
            view's name. Scale is never touched here -- a projected view
            inherits its parent's scale by default, and nothing in this
            method changes that.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        direction_key = (direction or "").strip().lower()
        mapping = _PROJECTED_VIEW_DIRECTIONS.get(direction_key)
        if mapping is None:
            return self._result(
                False,
                f"Unknown direction {direction!r}; expected one of "
                f"{sorted(_PROJECTED_VIEW_DIRECTIONS)!r}",
                SwErrors.swInvalidInput, {"direction": direction},
            )
        dx_sign, dy_sign, not_aligned = mapping

        parent_view, available_views, find_err = self._find_view_by_name(
            doc, parent_view_name, sheet_name)
        if find_err:
            return find_err
        if parent_view is None:
            return self._result(
                False,
                f"Unknown parent view {parent_view_name!r}; available views: "
                f"{available_views!r}",
                SwErrors.swInvalidInput,
                {"parent_view_name": parent_view_name, "available_views": available_views},
            )

        parent_position = self._read_prop(parent_view, "Position")
        if isinstance(parent_position, (list, tuple)) and len(parent_position) >= 2:
            parent_x_m, parent_y_m = float(parent_position[0]), float(parent_position[1])
        else:
            parent_x_m, parent_y_m = 0.0, 0.0

        create_x_m = parent_x_m + dx_sign * _DEFAULT_PROJECTED_VIEW_STEP_M
        create_y_m = parent_y_m + dy_sign * _DEFAULT_PROJECTED_VIEW_STEP_M

        data = {
            "parent_view_name": parent_view_name, "direction": direction_key,
            "offset": offset, "sheet_name": sheet_name,
        }

        with self.selected(parent_view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                view = doc.CreateUnfoldedViewAt3(create_x_m, create_y_m, 0.0, not_aligned)
            except Exception as e:
                logger.error(f"insert_projected_view error: {e}")
                return self._result(False, f"Insert projected view error: {e}",
                                    SwErrors.swFeatureError, data)

        if view is None:
            return self._result(
                False,
                f"Failed to create projected view ({direction_key}) off "
                f"{parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        created_name = self._read_prop(view, "GetName2")
        data["view_name"] = created_name

        if offset is not None:
            offset_m = self._units.to_meters(offset)
            final_x_m = parent_x_m + dx_sign * offset_m
            final_y_m = parent_y_m + dy_sign * offset_m
            try:
                view.Position = [final_x_m, final_y_m]
                doc.EditRebuild3()
            except Exception as e:
                # The view itself was created successfully -- only the
                # requested exact offset failed to apply -- but reporting
                # plain success here would silently hand back a view at the
                # wrong position while `data["offset"]` claims the requested
                # one was honored. Same "a partial/warned operation can't
                # silently read as a clean one" rule `save_drawing` follows
                # for its own Errors/Warnings bitmask.
                logger.error(f"insert_projected_view: offset reposition failed: {e}")
                return self._result(
                    False,
                    f"Created projected view {created_name or ''!r} but failed to "
                    f"move it to the requested offset: {e}",
                    SwErrors.swFeatureError, data,
                )

        return self._result(
            True,
            f"Inserted projected view {created_name or ''!r} "
            f"({direction_key} of {parent_view_name!r})",
            SwErrors.swSuccess, data,
        )

    def insert_predefined_views(self, model_path: str, sheet_name: Optional[str] = None) -> Dict:
        """
        Fill every predefined-view placeholder on a sheet via
        `IDrawingDoc::InsertModelInPredefinedView` -- placeholders
        pre-positioned/pre-configured on a template beforehand (Insert >
        Drawing View > Predefined in the UI), left empty until a model is
        inserted into them.

        No selection is made before the call, per the dossier's Gotchas:
        selecting specific placeholders first would narrow the fill to just
        those, but this tool's contract is "fill every placeholder on the
        sheet."

        Args:
            model_path: Full pathname of the model document to insert into
                every predefined-view placeholder on the sheet.
            sheet_name: Sheet to target, activated via `IDrawingDoc::
                ActivateSheet` first -- required per the dossier's
                multi-sheet Gotcha (only the *last active* sheet's
                placeholders get filled). Omitted: whichever sheet is
                already active.

        Returns:
            Result dict. `InsertModelInPredefinedView` returns only a bare
            `Boolean` with no view handle, and a predefined-view placeholder
            is already a real, named view object on the sheet before it's
            filled (the dossier: this method only fills existing
            placeholders, it does not create them) -- so which placeholders
            got filled can't be read off which view *names* are new. Instead,
            `_sheet_view_fill_state` snapshots which named views already
            reference a model (`IView::ReferencedDocument`) before the call;
            `data["filled_views"]` is whichever of the previously-unfilled
            names reference one afterward. If the sheet has zero unfilled
            placeholders to begin with, this fails with `swFeatureError`
            before even calling `InsertModelInPredefinedView` -- naming the
            sheet, rather than reporting a silent success that filled
            nothing.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        if sheet_name:
            try:
                activated = doc.ActivateSheet(sheet_name)
            except Exception as e:
                logger.error(f"insert_predefined_views activate sheet error: {e}")
                return self._result(False, f"Activate sheet error: {e}", SwErrors.swInvalidInput)
            if not activated:
                return self._result(
                    False, f"Sheet {sheet_name!r} not found", SwErrors.swInvalidInput,
                    {"sheet_name": sheet_name},
                )

        sheet, sheet_err = self._resolve_sheet(doc, None)
        if sheet_err:
            return sheet_err
        before_state = self._sheet_view_fill_state(sheet)
        unfilled_before = [name for name, has_model in before_state.items() if not has_model]

        data = {"model_path": model_path, "sheet_name": sheet_name}

        if not unfilled_before:
            return self._result(
                False,
                f"No predefined-view placeholders found on sheet "
                f"{sheet_name or '(active)'!r} -- every named view already references "
                "a model, or none exist. Predefined views must be authored on the "
                "drawing template beforehand (Insert > Drawing View > Predefined).",
                SwErrors.swFeatureError, data,
            )

        try:
            inserted = doc.InsertModelInPredefinedView(model_path)
        except Exception as e:
            logger.error(f"insert_predefined_views error: {e}")
            return self._result(False, f"Insert predefined views error: {e}",
                                SwErrors.swFeatureError, data)

        if not inserted:
            return self._result(
                False, f"Failed to insert model {model_path!r} into predefined view(s)",
                SwErrors.swFeatureError, data,
            )

        sheet, sheet_err = self._resolve_sheet(doc, None)
        if sheet_err:
            return sheet_err
        after_state = self._sheet_view_fill_state(sheet)
        filled = [name for name in unfilled_before if after_state.get(name)]

        if not filled:
            return self._result(
                False,
                f"InsertModelInPredefinedView reported success but none of the "
                f"{len(unfilled_before)} unfilled placeholder(s) on sheet "
                f"{sheet_name or '(active)'!r} now reference {model_path!r}.",
                SwErrors.swFeatureError, data,
            )

        data["filled_views"] = filled
        count = len(filled)
        return self._result(
            True, f"Filled {count} predefined view{'s' if count != 1 else ''} with "
            f"{model_path!r}", SwErrors.swSuccess, data,
        )

    def insert_auxiliary_view(self, parent_view_name: str, edge_selection: Dict[str, float],
                               x: float, y: float, label: str = "", flip: bool = False,
                               not_aligned: bool = False, show_arrow: bool = True,
                               sheet_name: Optional[str] = None) -> Dict:
        """
        Insert an auxiliary view off an edge of an existing view via
        `IDrawingDoc::CreateAuxiliaryViewAt2` -- unlike "projected view,"
        the API's name for this UI action matches the task's expectation
        (docs/api/02-views.md's Auxiliary views section).

        Args:
            parent_view_name: Name of the existing drawing view the
                reference edge belongs to (`IView::GetName2`). Not itself a
                `CreateAuxiliaryViewAt2` parameter -- the call operates
                entirely off whatever edge is selected -- but validated
                against the sheet's actual views first, so an unrecognized
                name fails with `swInvalidInput` listing every view really
                on the sheet, the same as `insert_projected_view`.
            edge_selection: `{"x": ..., "y": ..., "z": 0}` -- a sheet-space
                point (caller's default unit) on the reference edge to
                project from, selected via `selected(..., "EDGE", ...)`
                before the call (the dossier's documented ambient-selection
                pattern -- `CreateAuxiliaryViewAt2` takes no edge parameter
                of its own). `"z"` defaults to `0` if omitted.
            x, y: Center of the new auxiliary view, in the caller's default
                unit -- converted to sheet-space meters here. `Z` is always
                `0` (sheet space is 2D).
            label: Auxiliary view letter label (e.g. `"A"`).
            flip: `True` flips which side of the reference edge the view
                projects toward.
            not_aligned: `False` (default) keeps the view aligned/locked to
                its parent along the projection direction; `True` breaks
                alignment.
            show_arrow: `True` (default) shows the projection arrow on the
                parent view.
            sheet_name: Sheet the parent view lives on, resolved the same
                way `list_views` does. Omitted: whichever sheet is active.

        Returns:
            Result dict. `CreateAuxiliaryViewAt2` returning `Nothing` (no
            edge selected, or the wrong thing selected) fails with
            `swFeatureError` naming the parent view.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        parent_view, available_views, find_err = self._find_view_by_name(
            doc, parent_view_name, sheet_name)
        if find_err:
            return find_err
        if parent_view is None:
            return self._result(
                False,
                f"Unknown parent view {parent_view_name!r}; available views: "
                f"{available_views!r}",
                SwErrors.swInvalidInput,
                {"parent_view_name": parent_view_name, "available_views": available_views},
            )

        if not isinstance(edge_selection, dict) or "x" not in edge_selection or "y" not in edge_selection:
            return self._result(
                False,
                "edge_selection must be a dict with 'x' and 'y' (and optional 'z') "
                "sheet-space coordinates of a point on the reference edge",
                SwErrors.swInvalidInput,
            )
        edge_x = edge_selection["x"]
        edge_y = edge_selection["y"]
        edge_z = edge_selection.get("z", 0)

        data = {
            "parent_view_name": parent_view_name, "label": label, "x": x, "y": y,
            "flip": flip, "not_aligned": not_aligned, "show_arrow": show_arrow,
        }

        with self.selected("", "EDGE", edge_x, edge_y, edge_z) as sel:
            if not sel["success"]:
                return sel
            try:
                args = CREATE_AUXILIARY_VIEW_AT2.bind(
                    units=self._units, x=x, y=y, z=0, not_aligned=not_aligned,
                    label=label, show_arrow=show_arrow, flip=flip,
                )
                view = doc.CreateAuxiliaryViewAt2(*args)
            except Exception as e:
                logger.error(f"insert_auxiliary_view error: {e}")
                return self._result(False, f"Insert auxiliary view error: {e}",
                                    SwErrors.swFeatureError, data)

        if view is None:
            return self._result(
                False, f"Failed to create auxiliary view off {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        created_name = self._read_prop(view, "GetName2")
        data["view_name"] = created_name
        return self._result(
            True, f"Inserted auxiliary view {created_name or ''!r} off {parent_view_name!r}",
            SwErrors.swSuccess, data,
        )

    @staticmethod
    def _normalize_cut_points(cut_points: Any) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
        """Validate and normalize `insert_section_view`'s `cut_points` into a
        list of `(x, y)` float tuples, in the caller's default unit (not yet
        converted to meters -- that happens per-segment once a parent view
        is confirmed to exist).

        Each point may be `[x, y]`/`(x, y)` or `{"x": ..., "y": ...}`.
        Returns `(points, None)` on success, or `(None, error_message)` for
        anything that isn't a valid 2+-point, 2+-distinct-point list --
        checked entirely in Python, before any COM call, per this issue's
        Acceptance Criteria ("no COM call" for an invalid `cut_points`).
        """
        if not isinstance(cut_points, (list, tuple)) or len(cut_points) < 2:
            got = len(cut_points) if isinstance(cut_points, (list, tuple)) else cut_points
            return None, f"cut_points must have at least 2 (x, y) pairs; got {got!r}"

        points: List[Tuple[float, float]] = []
        for i, raw in enumerate(cut_points):
            if isinstance(raw, dict):
                if "x" not in raw or "y" not in raw:
                    return None, f"cut_points[{i}] must have 'x' and 'y'; got {raw!r}"
                px, py = raw["x"], raw["y"]
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                px, py = raw[0], raw[1]
            else:
                return None, (
                    f"cut_points[{i}] must be [x, y] or {{'x': ..., 'y': ...}}; got {raw!r}"
                )
            try:
                points.append((float(px), float(py)))
            except (TypeError, ValueError):
                return None, f"cut_points[{i}] has non-numeric coordinates: {raw!r}"

        if len(set(points)) < 2:
            return None, "cut_points must contain at least 2 distinct points"

        return points, None

    def insert_section_view(
        self, parent_view_name: str, cut_points: List[Any], x: float, y: float,
        label: Optional[str] = None, flip_direction: bool = False,
        section_type: str = "full", auto_hatch: bool = True,
        display_only: bool = False, use_sheet_scale: bool = True,
    ) -> Dict:
        """
        Insert a section view off an existing drawing view via
        `IDrawingDoc::CreateSectionViewAt5` -- the fiddliest view-creation
        call in the API (docs/api/02-views.md's `CreateSectionViewAt5` and
        `IDrSection` records): the cut line must exist as sketch geometry in
        the parent view's space and be selected *before* the call, and most
        of what this tool's parameters ask for lives on the resulting
        `IDrSection` object, not `CreateSectionViewAt5`'s own `Options`
        bitmask. This method owns the whole sequence -- activate the parent
        view, sketch the cut line, select it, create the view, configure it
        -- so the caller never manages sketch or selection state.

        Args:
            parent_view_name: Name of the existing drawing view to cut
                (`IView::GetName2`, e.g. from `list_views`). Validated
                against the sheet's actual views first (`swInvalidInput`
                listing the real names on a miss), then activated via
                `IDrawingDoc::ActivateView` before any sketch geometry is
                created, so the cut-line points below land in that view's
                own coordinate space.
            cut_points: 2+ `[x, y]` (or `{"x":.., "y":..}`) pairs, in the
                parent view's coordinate space, in the caller's default unit
                (`set_units`). Two points is a straight cut line; 3+ points
                is an offset/stepped cut (one `IView::GetSection`-configured
                `IDrSection`, but N-1 separate `ISketchManager::CreateLine`
                segments). Rejected with `swInvalidInput` -- before any COM
                call -- if fewer than 2 points are given, or fewer than 2 of
                the given points are distinct.
            x, y: Placement of the resulting section view on the drawing
                sheet, in the caller's default unit -- `CreateSectionViewAt5`'s
                own `X`/`Y`, confirmed sheet-space in the dossier and
                unrelated to `cut_points`' view-space coordinates. `Z` is
                always `0` (sheet space is 2D).
            label: Section label letter (e.g. `"A"`). `None`/omitted lets
                SolidWorks auto-assign one -- `data["label"]` always reports
                back whatever `IDrSection::GetLabel()` reads after creation,
                not the requested value, since the dossier found no source
                describing `SectionLabel`'s behavior on a duplicate/omitted
                letter.
            flip_direction: `True` sets `swCreateSectionView_ChangeDirection`
                -- switches which side of the cut line the section looks
                toward.
            section_type: `"full"` (default, no special bit -- a normal,
                complete section), `"aligned"` (`swCreateSectionView_OffsetSection`
                -- per that member's own help text, "an aligned section view
                ... two lines at an angle"), or `"half"`
                (`swCreateSectionView_Partial` -- **this project's own
                convention, not a dossier-endorsed mapping**: SolidWorks has
                no true half-section member under any name, and the
                dossier's own `CreateSectionViewAt5` Gotchas explicitly warns
                against conflating `Partial` with "half"; `Partial` is used
                here as the closest documented behavior, restricted to a
                straight 2-point cut). An unrecognized value fails with
                `swInvalidInput`; `"half"` with more than 2 `cut_points`
                fails with `swInvalidInput` (SolidWorks has no half-section
                support for an offset/stepped cut).
            auto_hatch: Passed to the created view's `IDrSection::SetAutoHatch`
                after creation. Per a vendor post on this SW2018+ feature,
                applies only to assembly section views -- a no-op on a part.
            display_only: Passed to `IDrSection::SetDisplayOnlySurfaceCut`
                after creation. **Not** a true "view-only, no material cut"
                toggle -- no such toggle exists anywhere in this API (the
                dossier's `CreateSectionViewAt5` Gotchas is explicit on this);
                this is the closest real, named setting, and only affects
                surface-body cut display.
            use_sheet_scale: Sets `IView::UseSheetScale` (`1`/`0`, not a
                `Boolean` -- the dossier's own Gotcha on that property) after
                creation, followed by `IModelDoc2::EditRebuild3` to force the
                regenerate that property's record documents needing.

        Returns:
            Result dict. On success, `data["view_name"]` is the created
            view's name and `data["label"]` is the actual assigned label
            letter. Section scope (which components/ribs stay uncut on an
            assembly) is intentionally out of this tool's scope --
            `CreateSectionViewAt5`'s `ExcludedComponents` always binds to
            `Nothing` here -- per this file's `CreateSectionViewAt5` Gotchas,
            every piece of that state (`IDrSection::SetExcludedComponents`/
            `ExcludeFasteners`/`SetDontCutAllInstances`) is reachable
            programmatically with no SolidWorks-popped dialog and no
            `SetUserPreferenceToggle` mitigation found to need snapshotting.
            A view that *was* created but a post-creation setting
            (auto_hatch/display_only/label/use_sheet_scale) failed to apply
            fails with `swFeatureError` rather than reporting plain success
            with `data` claiming a setting that didn't actually take --
            `data["view_name"]` still names the view so the caller isn't
            left without a handle to it.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "parent_view_name": parent_view_name, "x": x, "y": y, "label": label,
            "flip_direction": flip_direction, "section_type": section_type,
            "auto_hatch": auto_hatch, "display_only": display_only,
            "use_sheet_scale": use_sheet_scale,
        }

        points, point_err = self._normalize_cut_points(cut_points)
        if point_err:
            return self._result(False, point_err, SwErrors.swInvalidInput, data)

        section_type_key = (section_type or "").strip().lower()
        options = _SECTION_TYPE_OPTIONS.get(section_type_key)
        if options is None:
            return self._result(
                False,
                f"Unknown section_type {section_type!r}; expected one of "
                f"{sorted(_SECTION_TYPE_OPTIONS)!r}",
                SwErrors.swInvalidInput, data,
            )
        if section_type_key == "half" and len(points) > 2:
            return self._result(
                False,
                f"section_type='half' only supports a straight 2-point cut line "
                f"({len(points)} points given) -- SolidWorks has no half-section "
                "support for an offset/stepped cut; use section_type='aligned' or "
                "'full' instead",
                SwErrors.swInvalidInput, data,
            )
        if flip_direction:
            options |= int(SwCreateSectionViewAtOptions.swCreateSectionView_ChangeDirection)

        parent_view, available_views, find_err = self._find_view_by_name(doc, parent_view_name, None)
        if find_err:
            return find_err
        if parent_view is None:
            return self._result(
                False,
                f"Unknown parent view {parent_view_name!r}; available views: "
                f"{available_views!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": available_views},
            )

        try:
            activated = doc.ActivateView(parent_view_name)
        except Exception as e:
            logger.error(f"insert_section_view activate view error: {e}")
            return self._result(False, f"Activate view error: {e}", SwErrors.swFeatureError, data)
        if not activated:
            return self._result(
                False, f"Failed to activate parent view {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        segment_midpoints: List[Tuple[float, float]] = []
        try:
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                x1_m, y1_m = self._units.to_meters(x1), self._units.to_meters(y1)
                x2_m, y2_m = self._units.to_meters(x2), self._units.to_meters(y2)
                segment = doc.SketchManager.CreateLine(x1_m, y1_m, 0.0, x2_m, y2_m, 0.0)
                if segment is None:
                    return self._result(
                        False,
                        "Failed to sketch cut-line segment -- ensure the parent view "
                        f"{parent_view_name!r} supports a section line",
                        SwErrors.swSketchError, data,
                    )
                # Selected below by a representative point in the same
                # view-local space CreateLine just used -- this wrapper's
                # own convention (not sourced in the dossier, which doesn't
                # cover SelectByID2's coordinate space for a freshly-created
                # drawing-view sketch entity), same caveat
                # `list_view_entities` flags for its own coordinate space.
                segment_midpoints.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
        except Exception as e:
            logger.error(f"insert_section_view sketch error: {e}")
            return self._result(False, f"Sketch cut line error: {e}", SwErrors.swSketchError, data)

        # Select every cut-line segment atomically before the call, per the
        # dossier's "select the section line or lines" requirement -- the
        # first `selected()` clears any stale selection (and clears again on
        # its own exit); every subsequent one appends and skips clearing on
        # both ends (see SelectionOperations.selected's docstring), so the
        # ExitStack's LIFO unwind leaves the outermost/first block to do the
        # one real clear, after everything inside it (including the create
        # call) has run.
        with ExitStack() as stack:
            for i, (mx, my) in enumerate(segment_midpoints):
                sel = stack.enter_context(
                    self.selected("", "SKETCHSEGMENT", mx, my, 0, append=(i > 0), mark=i)
                )
                if not sel["success"]:
                    return sel

            try:
                args = CREATE_SECTION_VIEW_AT5.bind(
                    units=self._units, x=x, y=y, z=0,
                    label=label or "", options=options,
                    excluded_components=None, section_depth=0,
                )
                view = doc.CreateSectionViewAt5(*args)
            except Exception as e:
                logger.error(f"insert_section_view error: {e}")
                return self._result(False, f"Insert section view error: {e}",
                                    SwErrors.swFeatureError, data)

        if view is None:
            return self._result(
                False, f"Failed to create section view off {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        created_name = self._read_prop(view, "GetName2")
        data["view_name"] = created_name

        try:
            section = view.GetSection()
        except Exception as e:
            return self._result(
                False,
                f"Created section view {created_name or ''!r} but IView::GetSection "
                f"raised: {e}",
                SwErrors.swFeatureError, data,
            )
        if section is None:
            return self._result(
                False,
                f"Created section view {created_name or ''!r} but IView::GetSection "
                "returned nothing -- could not apply auto_hatch/display_only/label",
                SwErrors.swFeatureError, data,
            )

        try:
            section.SetAutoHatch(bool(auto_hatch))
            section.SetDisplayOnlySurfaceCut(bool(display_only))
            data["label"] = section.GetLabel() or label
        except Exception as e:
            logger.error(f"insert_section_view: section configuration failed: {e}")
            return self._result(
                False,
                f"Created section view {created_name or ''!r} but failed to apply "
                f"auto_hatch/display_only/label settings: {e}",
                SwErrors.swFeatureError, data,
            )

        try:
            view.UseSheetScale = 1 if use_sheet_scale else 0
            doc.EditRebuild3()
        except Exception as e:
            logger.error(f"insert_section_view: use_sheet_scale apply failed: {e}")
            return self._result(
                False,
                f"Created section view {created_name or ''!r} but failed to apply "
                f"use_sheet_scale: {e}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True, f"Inserted section view {created_name or ''!r} off {parent_view_name!r}",
            SwErrors.swSuccess, data,
        )

    def _delete_sketch_geometry(self, doc, points: List[Tuple[float, float]]) -> None:
        """Best-effort cleanup of construction sketch geometry left behind by a
        failed `insert_detail_view`/`insert_broken_out_section` call, via
        `IModelDocExtension::DeleteSelection2` (docs/api/02-views.md's own
        record, reused here per that record's sw-8ww.4 addendum) -- selects
        every point in `points` (view-local space, caller's default unit) as
        a `"SKETCHSEGMENT"`, the same entity type/selection convention
        `insert_section_view`'s cut-line selection uses, then deletes the
        whole selection.

        Never raises and never returns a result dict -- called only from an
        already-failing path, so a cleanup failure must not replace the
        original error the caller is about to return; it's only logged.
        Harmless to call again on an already-selected/already-deleted
        entity, so callers don't need to track which failure path they're
        on -- just call this once whenever geometry may exist that the
        create call didn't consume.
        """
        if not points:
            return
        try:
            with ExitStack() as stack:
                for i, (px, py) in enumerate(points):
                    stack.enter_context(
                        self.selected("", "SKETCHSEGMENT", px, py, 0, append=(i > 0), mark=i)
                    )
                doc.Extension.DeleteSelection2(0)
        except Exception as e:
            logger.debug(f"_delete_sketch_geometry: cleanup failed: {e}")

    def insert_detail_view(
        self, parent_view_name: str, center_x: float, center_y: float, radius: float,
        x: float, y: float, label: Optional[str] = None,
        scale_num: Optional[float] = None, scale_denom: Optional[float] = None,
        style: str = "circle", full_outline: bool = False,
    ) -> Dict:
        """
        Insert a detail view off a circular region of an existing drawing view
        via `IDrawingDoc::CreateDetailViewAt4` -- requested as
        `CreateDetailViewAt5`, which does not exist (docs/api/02-views.md's
        `CreateDetailViewAt4` record: `At4` is the current highest overload).
        Owns the whole sequence -- activate the parent view, sketch the detail
        circle, select it, create the view -- the same shape
        `insert_section_view` uses for its own prior-selection requirement.

        Args:
            parent_view_name: Name of the existing drawing view to detail
                (`IView::GetName2`, e.g. from `list_views`). Validated against
                the sheet's actual views first (`swInvalidInput` listing the
                real names on a miss), then activated via
                `IDrawingDoc::ActivateView` before any sketch geometry is
                created, so `center_x`/`center_y`/`radius` land in that view's
                own coordinate space.
            center_x, center_y, radius: Detail circle, in the parent view's
                coordinate space, in the caller's default unit (`set_units`) --
                converted to sheet-space meters here and sketched via
                `ISketchManager::CreateCircleByRadius`. `radius` must be
                positive -- rejected with `swInvalidInput` before any COM call
                otherwise.
            x, y: Placement of the resulting detail view on the drawing sheet,
                in the caller's default unit -- `CreateDetailViewAt4`'s own
                `X`/`Y`. `Z` is always `0` (sheet space is 2D).
            label: Detail view label letter (e.g. `"A"`). `None`/omitted
                passes `""` -- unlike `insert_section_view`, there is no
                documented `IDrDetail`-style post-creation label readback for
                detail views in this dossier, so `data["label"]` simply echoes
                back whatever was requested, not a value read from SolidWorks.
            scale_num, scale_denom: Detail view scale ratio
                (`CreateDetailViewAt4`'s `Scale1`/`Scale2`). Must be given
                together or omitted together -- one without the other fails
                with `swInvalidInput` before any COM call. When both are
                omitted, defaults to the parent view's own scale
                (`IView::ScaleDecimal`, read via `_read_prop`) over `1`, or
                plain `1:1` if that can't be read -- "defaults to the
                sheet/parent scale" per this issue's Requirements.
            style: `"circle"` (default), `"profile"`, or `"none"` -- despite
                the name, this binds to `CreateDetailViewAt4`'s `Showtype`
                parameter (`swDetCircleShowType_e`), not its separate `Style`
                parameter (`swDetViewStyle_e`, a border/leader-look enum this
                tool doesn't expose at all -- always bound to
                `swDetViewSTANDARD`). See docs/api/02-views.md's
                `swDetViewStyle_e` record for the full reasoning: `"circle"`'s
                default value is literally `swDetCircleCIRCLE`'s own member
                name, and this tool always sketches a circle. An unrecognized
                value fails with `swInvalidInput`.
            full_outline: `CreateDetailViewAt4`'s own `FullOutline` flag
                passed straight through. `JaggedOutline` is always `False` and
                `NoOutline` is always `False` -- this tool exposes no
                parameter for either, so neither is silently turned on by
                default; `ShapeIntensity` is inert or not, but bound to `1`
                either way.

        Returns:
            Result dict. On success, `data["view_name"]` is the created
            view's name. On any failure *after* the detail circle was
            successfully sketched (selection failure, the create call itself
            raising or returning `Nothing`), the sketched circle is deleted
            via `_delete_sketch_geometry` before the error is returned, so a
            failed call never leaves a stray open sketch on the sheet.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "parent_view_name": parent_view_name, "center_x": center_x, "center_y": center_y,
            "radius": radius, "x": x, "y": y, "label": label,
            "scale_num": scale_num, "scale_denom": scale_denom,
            "style": style, "full_outline": full_outline,
        }

        if not isinstance(radius, (int, float)) or isinstance(radius, bool) or radius <= 0:
            return self._result(
                False, f"radius must be a positive number; got {radius!r}",
                SwErrors.swInvalidInput, data,
            )

        style_key = (style or "").strip().lower()
        showtype = _DETAIL_VIEW_SHOWTYPE.get(style_key)
        if showtype is None:
            return self._result(
                False,
                f"Unknown style {style!r}; expected one of "
                f"{sorted(_DETAIL_VIEW_SHOWTYPE)!r}",
                SwErrors.swInvalidInput, data,
            )

        if (scale_num is None) != (scale_denom is None):
            return self._result(
                False,
                "scale_num and scale_denom must be given together, or both "
                f"omitted; got scale_num={scale_num!r}, scale_denom={scale_denom!r}",
                SwErrors.swInvalidInput, data,
            )

        parent_view, available_views, find_err = self._find_view_by_name(doc, parent_view_name, None)
        if find_err:
            return find_err
        if parent_view is None:
            return self._result(
                False,
                f"Unknown parent view {parent_view_name!r}; available views: "
                f"{available_views!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": available_views},
            )

        try:
            activated = doc.ActivateView(parent_view_name)
        except Exception as e:
            logger.error(f"insert_detail_view activate view error: {e}")
            return self._result(False, f"Activate view error: {e}", SwErrors.swFeatureError, data)
        if not activated:
            return self._result(
                False, f"Failed to activate parent view {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        if scale_num is not None:
            scale1, scale2 = scale_num, scale_denom
        else:
            parent_scale = self._read_prop(parent_view, "ScaleDecimal")
            if (isinstance(parent_scale, (int, float)) and not isinstance(parent_scale, bool)
                    and parent_scale > 0):
                scale1, scale2 = parent_scale, 1.0
            else:
                scale1, scale2 = 1.0, 1.0

        cx_m = self._units.to_meters(center_x)
        cy_m = self._units.to_meters(center_y)
        radius_m = self._units.to_meters(radius)

        try:
            segment = doc.SketchManager.CreateCircleByRadius(cx_m, cy_m, 0.0, radius_m)
        except Exception as e:
            logger.error(f"insert_detail_view sketch error: {e}")
            return self._result(False, f"Sketch detail circle error: {e}", SwErrors.swSketchError, data)
        if segment is None:
            return self._result(
                False,
                "Failed to sketch detail circle -- ensure the parent view "
                f"{parent_view_name!r} supports a detail circle",
                SwErrors.swSketchError, data,
            )

        # Selected by a point on the circle's *boundary*, not its center --
        # the center point isn't part of the circle geometry SelectByID2
        # would hit-test there (docs/api/02-views.md's `CreateCircleByRadius`
        # Gotchas).
        boundary_point = [(center_x + radius, center_y)]

        with self.selected("", "SKETCHSEGMENT", center_x + radius, center_y, 0) as sel:
            if not sel["success"]:
                self._delete_sketch_geometry(doc, boundary_point)
                return sel

            try:
                args = CREATE_DETAIL_VIEW_AT4.bind(
                    units=self._units, x=x, y=y, z=0,
                    style=int(SwDetViewStyle.swDetViewSTANDARD),
                    scale1=scale1, scale2=scale2, label=label or "",
                    showtype=showtype, full_outline=full_outline,
                    jagged_outline=False, no_outline=False, shape_intensity=1,
                )
                view = doc.CreateDetailViewAt4(*args)
            except Exception as e:
                logger.error(f"insert_detail_view error: {e}")
                self._delete_sketch_geometry(doc, boundary_point)
                return self._result(False, f"Insert detail view error: {e}",
                                    SwErrors.swFeatureError, data)

        if view is None:
            self._delete_sketch_geometry(doc, boundary_point)
            return self._result(
                False, f"Failed to create detail view off {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        created_name = self._read_prop(view, "GetName2")
        data["view_name"] = created_name
        data["scale_num"], data["scale_denom"] = scale1, scale2

        return self._result(
            True, f"Inserted detail view {created_name or ''!r} off {parent_view_name!r}",
            SwErrors.swSuccess, data,
        )

    @staticmethod
    def _normalize_profile_points(
        profile_points: Any,
    ) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
        """Validate and normalize `insert_broken_out_section`'s
        `profile_points` into a list of `(x, y)` float tuples, in the
        caller's default unit (not yet converted to meters -- that happens
        per-segment once a parent view is confirmed to exist).

        Each point may be `[x, y]`/`(x, y)` or `{"x": ..., "y": ...}`, the
        same accepted shapes as `_normalize_cut_points`. Returns `(points,
        None)` on success, or `(None, error_message)` for anything that isn't
        a valid 3+-point, 3+-distinct-point profile -- checked entirely in
        Python, before any COM call, per this issue's Acceptance Criteria
        ("no COM call" for a profile with fewer than 3 points).

        A trailing point that duplicates the first (an already-closed input,
        e.g. `[A, B, C, A]`) is dropped before the distinctness check, so an
        explicitly pre-closed polygon isn't penalized for what
        `insert_broken_out_section`'s own auto-close step would otherwise
        turn into a degenerate zero-length closing segment.
        """
        if not isinstance(profile_points, (list, tuple)) or len(profile_points) < 3:
            got = len(profile_points) if isinstance(profile_points, (list, tuple)) else profile_points
            return None, f"profile_points must have at least 3 (x, y) pairs; got {got!r}"

        points: List[Tuple[float, float]] = []
        for i, raw in enumerate(profile_points):
            if isinstance(raw, dict):
                if "x" not in raw or "y" not in raw:
                    return None, f"profile_points[{i}] must have 'x' and 'y'; got {raw!r}"
                px, py = raw["x"], raw["y"]
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                px, py = raw[0], raw[1]
            else:
                return None, (
                    f"profile_points[{i}] must be [x, y] or {{'x': ..., 'y': ...}}; got {raw!r}"
                )
            try:
                points.append((float(px), float(py)))
            except (TypeError, ValueError):
                return None, f"profile_points[{i}] has non-numeric coordinates: {raw!r}"

        if len(points) >= 2 and points[-1] == points[0]:
            points = points[:-1]

        if len(set(points)) < 3:
            return None, "profile_points must contain at least 3 distinct points"

        return points, None

    def insert_broken_out_section(
        self, parent_view_name: str, profile_points: List[Any],
        depth: Optional[float] = None, depth_reference: Optional[Dict] = None,
        preview: bool = False,
    ) -> Dict:
        """
        Insert a broken-out section on an existing drawing view via
        `IDrawingDoc::CreateBreakOutSection` -- requested as
        `IView::InsertBrokenOutSection`, which does not exist
        (docs/api/02-views.md's `CreateBreakOutSection` record: the real
        method lives on `IDrawingDoc`, not `IView`). Owns the whole sequence
        -- activate the parent view, sketch the closed profile as line
        segments, select them, create the section -- the same shape
        `insert_section_view` uses for its own prior-selection requirement.

        Args:
            parent_view_name: Name of the existing drawing view to break open
                (`IView::GetName2`, e.g. from `list_views`). Validated against
                the sheet's actual views first (`swInvalidInput` listing the
                real names on a miss), then activated via
                `IDrawingDoc::ActivateView` before any sketch geometry is
                created.
            profile_points: 3+ `[x, y]` (or `{"x":.., "y":..}`) pairs, in the
                parent view's coordinate space, in the caller's default unit
                (`set_units`) -- the closed profile boundary, built from `N`
                `ISketchManager::CreateLine` segments (not `CreateSpline`/
                `CreatePolyLine` -- see docs/api/02-views.md's Gotchas on why).
                The loop is auto-closed: an extra segment connects the last
                point back to the first, so callers pass an *open* point
                chain (a pre-closed chain -- last point equal to the first --
                is also accepted; the duplicate is dropped first). Rejected
                with `swInvalidInput` -- before any COM call -- if fewer than
                3 points are given, or fewer than 3 of the given points (after
                dropping a pre-closing duplicate) are distinct.
            depth: Material-removal depth for the broken-out section, in the
                caller's default unit -- `CreateBreakOutSection`'s own
                `Depth`. Mutually exclusive with `depth_reference`: exactly
                one of the two must be given, or this fails with
                `swInvalidInput` before any COM call (a search-indexed
                secondary source on `IBrokenOutSectionFeatureData::Depth`
                states it "is valid only if `DepthReference` is null and the
                selection list is empty" -- independent corroboration for
                this both-or-neither rule).
            depth_reference: `{"x": ..., "y": ..., "z": 0, "type": "FACE"}` --
                a sheet-space point (caller's default unit) on the geometry
                reference to drive the section depth to, selected via
                `selected(..., type, ...)` (`type` defaults to `"FACE"`, the
                common case for "cut down to this face"). Applied
                *after* creation via `IBrokenOutSectionFeatureData
                ::DepthReference` -- `CreateBreakOutSection` itself has no
                reference-depth parameter (see docs/api/02-views.md's
                "Setting DepthReference post-creation" addendum for the full
                `FeatureByPositionReverse`/`GetDefinition`/`ModifyDefinition`
                chain this uses, and its sourcing caveats).
            preview: `True` sketches and selects the profile (validating that
                it's a usable closed profile), then deletes that construction
                geometry via `_delete_sketch_geometry` *without* ever calling
                `CreateBreakOutSection` -- a dry run. Not backed by any real
                `IBrokenOutSectionFeatureData`/`CreateBreakOutSection` COM
                concept (a type-library mirror of
                `IBrokenOutSectionFeatureData` confirms it has no
                `Preview`-named member at all) -- this is entirely this
                wrapper's own local convention for "validate without
                committing," built from primitives already used elsewhere in
                this method (sketch, select, delete).

        Returns:
            Result dict. On success (and not `preview`), `data["view_name"]`
            is the parent view's name (`CreateBreakOutSection` modifies the
            existing view in place -- it returns a bare `Boolean`, not a new
            `View`, per the dossier: "A broken-out section is part of an
            existing drawing view, not a separate view"). On any failure
            *after* the profile was successfully sketched (a segment failing
            partway through, selection failure, the create call itself
            raising or returning `False`), whatever segments were sketched
            are deleted via `_delete_sketch_geometry` before the error is
            returned, so a failed call never leaves a stray open sketch on
            the sheet. A `depth_reference` application failure is reported
            even though the section itself was created -- `data["view_name"]`
            still names the view so the caller isn't left without a handle to
            it, matching `insert_section_view`'s own "a partial/warned
            operation can't silently read as a clean one" rule for its
            post-creation settings.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "parent_view_name": parent_view_name, "depth": depth,
            "depth_reference": depth_reference, "preview": preview,
        }

        points, point_err = self._normalize_profile_points(profile_points)
        if point_err:
            return self._result(False, point_err, SwErrors.swInvalidInput, data)

        have_depth = depth is not None
        have_ref = depth_reference is not None
        if have_depth == have_ref:
            return self._result(
                False,
                "Exactly one of depth or depth_reference must be given "
                f"(depth={depth!r}, depth_reference={depth_reference!r})",
                SwErrors.swInvalidInput, data,
            )

        if have_ref and (not isinstance(depth_reference, dict)
                         or "x" not in depth_reference or "y" not in depth_reference):
            return self._result(
                False,
                "depth_reference must be a dict with 'x' and 'y' (and optional "
                f"'z'/'type'); got {depth_reference!r}",
                SwErrors.swInvalidInput, data,
            )

        parent_view, available_views, find_err = self._find_view_by_name(doc, parent_view_name, None)
        if find_err:
            return find_err
        if parent_view is None:
            return self._result(
                False,
                f"Unknown parent view {parent_view_name!r}; available views: "
                f"{available_views!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": available_views},
            )

        try:
            activated = doc.ActivateView(parent_view_name)
        except Exception as e:
            logger.error(f"insert_broken_out_section activate view error: {e}")
            return self._result(False, f"Activate view error: {e}", SwErrors.swFeatureError, data)
        if not activated:
            return self._result(
                False, f"Failed to activate parent view {parent_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        # Auto-close: an extra segment connects the last point back to the first.
        loop_points = list(points) + [points[0]]

        segment_midpoints: List[Tuple[float, float]] = []
        try:
            for (x1, y1), (x2, y2) in zip(loop_points, loop_points[1:]):
                x1_m, y1_m = self._units.to_meters(x1), self._units.to_meters(y1)
                x2_m, y2_m = self._units.to_meters(x2), self._units.to_meters(y2)
                segment = doc.SketchManager.CreateLine(x1_m, y1_m, 0.0, x2_m, y2_m, 0.0)
                if segment is None:
                    self._delete_sketch_geometry(doc, segment_midpoints)
                    return self._result(
                        False,
                        "Failed to sketch profile segment -- ensure the parent view "
                        f"{parent_view_name!r} supports a broken-out section",
                        SwErrors.swSketchError, data,
                    )
                segment_midpoints.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
        except Exception as e:
            logger.error(f"insert_broken_out_section sketch error: {e}")
            self._delete_sketch_geometry(doc, segment_midpoints)
            return self._result(False, f"Sketch profile error: {e}", SwErrors.swSketchError, data)

        with ExitStack() as stack:
            for i, (mx, my) in enumerate(segment_midpoints):
                sel = stack.enter_context(
                    self.selected("", "SKETCHSEGMENT", mx, my, 0, append=(i > 0), mark=i)
                )
                if not sel["success"]:
                    self._delete_sketch_geometry(doc, segment_midpoints)
                    return sel

            if preview:
                self._delete_sketch_geometry(doc, segment_midpoints)
                return self._result(
                    True,
                    f"Profile is valid for a broken-out section on {parent_view_name!r} "
                    "(preview=True -- not created)",
                    SwErrors.swSuccess, data,
                )

            try:
                depth_m = self._units.to_meters(depth) if have_depth else 0.0
                created = doc.CreateBreakOutSection(depth_m)
            except Exception as e:
                logger.error(f"insert_broken_out_section error: {e}")
                self._delete_sketch_geometry(doc, segment_midpoints)
                return self._result(False, f"Insert broken-out section error: {e}",
                                    SwErrors.swFeatureError, data)

        if not created:
            self._delete_sketch_geometry(doc, segment_midpoints)
            return self._result(
                False,
                f"Failed to create broken-out section on {parent_view_name!r} -- "
                "ensure profile_points form a valid closed profile",
                SwErrors.swFeatureError, data,
            )

        data["view_name"] = parent_view_name

        if have_ref:
            ref_type = str(depth_reference.get("type") or "FACE").upper()
            ref_x, ref_y = depth_reference["x"], depth_reference["y"]
            ref_z = depth_reference.get("z", 0)

            with self.selected("", ref_type, ref_x, ref_y, ref_z) as ref_sel:
                if not ref_sel["success"]:
                    return self._result(
                        False,
                        f"Created broken-out section on {parent_view_name!r} but could not "
                        f"select depth_reference geometry: {ref_sel['message']}",
                        SwErrors.swFeatureError, data,
                    )
                try:
                    ref_obj = doc.SelectionManager.GetSelectedObject6(1, -1)
                    feature = doc.FeatureByPositionReverse(0)
                    feat_data = feature.GetDefinition()
                    feat_data.DepthReference = ref_obj
                    applied = feature.ModifyDefinition(feat_data, doc, com_backend.null_dispatch())
                except Exception as e:
                    logger.error(f"insert_broken_out_section depth_reference error: {e}")
                    return self._result(
                        False,
                        f"Created broken-out section on {parent_view_name!r} but failed to "
                        f"apply depth_reference: {e}",
                        SwErrors.swFeatureError, data,
                    )

            if not applied:
                return self._result(
                    False,
                    f"Created broken-out section on {parent_view_name!r} but "
                    "ModifyDefinition rejected the depth_reference",
                    SwErrors.swFeatureError, data,
                )
            data["depth_reference_applied"] = True

        return self._result(
            True, f"Inserted broken-out section on {parent_view_name!r}",
            SwErrors.swSuccess, data,
        )

    # ========================================================================
    # View placement, alignment, display, and deletion (sw-8ww.6)
    # ========================================================================

    def move_view(self, view_name: str, x: float, y: float,
                   sheet_name: Optional[str] = None) -> Dict:
        """
        Move a drawing view to an exact sheet-space position via
        `IView::Position`.

        Args:
            view_name: Name of the view to move (`IView::GetName2`, e.g.
                from `list_views`).
            x, y: New center position, in the caller's default unit
                (`set_units`).
            sheet_name: Sheet `view_name` lives on, resolved the same way
                `list_views` does. Omitted: whichever sheet
                `IDrawingDoc::GetCurrentSheet` reports as active.

        Returns:
            Result dict. If the view is aligned to a parent view
            (`IView::GetAlignment` reports the `swViewAligned` bit --
            docs/api/02-views.md's `IView::Position` Gotchas: such a view
            "can only move along the alignment vector" regardless of what's
            requested), this fails with `swFeatureError` rather than
            silently moving the view somewhere other than `(x, y)` or
            no-op'ing -- call `align_view(view_name, alignment="break")`
            first if the view needs to move freely.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name)
        if find_err:
            return find_err
        if view is None:
            return self._result(
                False,
                f"Unknown view {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {"view_name": view_name, "available_views": names},
            )

        data = {"view_name": view_name, "x": x, "y": y, "sheet_name": sheet_name}

        try:
            alignment_code = view.GetAlignment()
        except Exception:
            alignment_code = None
        if (isinstance(alignment_code, (int, float)) and not isinstance(alignment_code, bool)
                and int(alignment_code) & int(SwViewAlignment.swViewAligned)):
            return self._result(
                False,
                f"View {view_name!r} is alignment-locked to a parent view "
                "and can only move along its alignment vector, not to an "
                "arbitrary position -- call align_view(view_name, "
                "alignment='break') first to move it freely",
                SwErrors.swFeatureError, data,
            )

        try:
            view.Position = [self._units.to_meters(x), self._units.to_meters(y)]
            doc.EditRebuild3()
        except Exception as e:
            logger.error(f"move_view error: {e}")
            return self._result(False, f"Move view error: {e}", SwErrors.swFeatureError, data)

        return self._result(
            True, f"Moved view {view_name!r} to ({x}, {y})", SwErrors.swSuccess, data,
        )

    # `align_view`'s `alignment` argument -> (swAlignViewTypes_e member,
    # requires a reference view). "default" and "none"/"break" are handled
    # separately below via the dedicated IView::UseDefaultAlignment /
    # IView::RemoveAlignment calls docs/api/02-views.md's GetAlignment
    # Gotchas point to, rather than routed through AlignWithView.
    _ALIGN_VIEW_TYPES = {
        "horizontal": SwAlignViewTypes.swAlignViewHorizontalCenter,
        "vertical": SwAlignViewTypes.swAlignViewVerticalCenter,
        "horizontal_origin": SwAlignViewTypes.swAlignViewHorizontalOrigin,
        "vertical_origin": SwAlignViewTypes.swAlignViewVerticalOrigin,
    }

    def align_view(self, view_name: str, reference_view_name: Optional[str] = None,
                    alignment: str = "horizontal",
                    sheet_name: Optional[str] = None) -> Dict:
        """
        Align a drawing view to a reference view via `IView::AlignWithView`,
        or break/reset its alignment via `IView::RemoveAlignment`/
        `UseDefaultAlignment` -- the escape hatch for `move_view`'s
        alignment-lock refusal.

        Args:
            view_name: Name of the view to align/un-align (the method's own
                instance per docs/api/02-views.md -- `AlignWithView` is
                called on the view being moved, not on the reference view
                or the document).
            reference_view_name: Name of the view to align with. Required
                for `horizontal`/`vertical`/`horizontal_origin`/
                `vertical_origin`; ignored for `default`/`none`/`break`.
            alignment: One of (case-insensitive):
                - `horizontal` (default): horizontal center alignment with
                  `reference_view_name`.
                - `vertical`: vertical center alignment.
                - `horizontal_origin` / `vertical_origin`: aligned to the
                  reference view's origin instead of its center.
                - `default`: reset to SolidWorks' default alignment
                  (`IView::UseDefaultAlignment`).
                - `none` / `break`: remove the alignment restriction
                  (`IView::RemoveAlignment`) so the view can move freely
                  via `move_view`.
            sheet_name: Sheet both views live on, resolved the same way
                `list_views` does.

        Returns:
            Result dict.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        alignment_key = (alignment or "").strip().lower()
        data = {
            "view_name": view_name, "reference_view_name": reference_view_name,
            "alignment": alignment_key, "sheet_name": sheet_name,
        }

        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name)
        if find_err:
            return find_err
        if view is None:
            return self._result(
                False,
                f"Unknown view {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": names},
            )

        if alignment_key in ("none", "break"):
            try:
                view.RemoveAlignment()
            except Exception as e:
                logger.error(f"align_view error: {e}")
                return self._result(False, f"Break alignment error: {e}",
                                    SwErrors.swFeatureError, data)
            return self._result(
                True, f"Broke alignment on view {view_name!r}", SwErrors.swSuccess, data,
            )

        if alignment_key == "default":
            try:
                view.UseDefaultAlignment()
            except Exception as e:
                logger.error(f"align_view error: {e}")
                return self._result(False, f"Default alignment error: {e}",
                                    SwErrors.swFeatureError, data)
            return self._result(
                True, f"Reset view {view_name!r} to default alignment",
                SwErrors.swSuccess, data,
            )

        align_type = self._ALIGN_VIEW_TYPES.get(alignment_key)
        if align_type is None:
            return self._result(
                False,
                f"Unknown alignment {alignment!r}; expected one of "
                f"{sorted(list(self._ALIGN_VIEW_TYPES) + ['default', 'none', 'break'])!r}",
                SwErrors.swInvalidInput, data,
            )

        if not reference_view_name:
            return self._result(
                False, f"alignment={alignment_key!r} requires reference_view_name",
                SwErrors.swInvalidInput, data,
            )

        reference_view, ref_names, ref_find_err = self._find_view_by_name(
            doc, reference_view_name, sheet_name)
        if ref_find_err:
            return ref_find_err
        if reference_view is None:
            return self._result(
                False,
                f"Unknown reference view {reference_view_name!r}; available views: "
                f"{ref_names!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": ref_names},
            )

        try:
            aligned = view.AlignWithView(int(align_type), reference_view)
        except Exception as e:
            logger.error(f"align_view error: {e}")
            return self._result(False, f"Align view error: {e}", SwErrors.swFeatureError, data)

        if not aligned:
            return self._result(
                False,
                f"Failed to align view {view_name!r} ({alignment_key}) with "
                f"{reference_view_name!r}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True,
            f"Aligned view {view_name!r} ({alignment_key}) with {reference_view_name!r}",
            SwErrors.swSuccess, data,
        )

    def set_view_scale(self, view_name: str, scale_num: Optional[float] = None,
                        scale_denom: Optional[float] = None, use_sheet_scale: bool = False,
                        sheet_name: Optional[str] = None) -> Dict:
        """
        Set a drawing view's scale independently of the sheet scale, via
        `IView::ScaleRatio` + `IView::UseSheetScale`.

        Args:
            view_name: Name of the view to rescale.
            scale_num, scale_denom: The view scale as `scale_num:scale_denom`
                (e.g. `1, 2` for 1:2). Both required together when
                `use_sheet_scale` is False; mutually exclusive with
                `use_sheet_scale=True`.
            use_sheet_scale: True links this view's scale back to the
                sheet's own scale (`IView::UseSheetScale = 1`), ignoring
                `scale_num`/`scale_denom`. False (default) sets an explicit,
                sheet-independent scale.
            sheet_name: Sheet `view_name` lives on, resolved the same way
                `list_views` does.

        Returns:
            Result dict.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "view_name": view_name, "scale_num": scale_num, "scale_denom": scale_denom,
            "use_sheet_scale": use_sheet_scale, "sheet_name": sheet_name,
        }

        if use_sheet_scale and (scale_num is not None or scale_denom is not None):
            return self._result(
                False,
                "use_sheet_scale=True and an explicit scale_num/scale_denom are "
                "mutually exclusive",
                SwErrors.swInvalidInput, data,
            )
        if not use_sheet_scale:
            if scale_num is None or scale_denom is None:
                return self._result(
                    False,
                    "scale_num and scale_denom must both be given when "
                    "use_sheet_scale is False",
                    SwErrors.swInvalidInput, data,
                )
            if scale_num <= 0 or scale_denom <= 0:
                return self._result(
                    False, "scale_num and scale_denom must both be positive",
                    SwErrors.swInvalidInput, data,
                )

        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name)
        if find_err:
            return find_err
        if view is None:
            return self._result(
                False,
                f"Unknown view {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": names},
            )

        try:
            if use_sheet_scale:
                view.UseSheetScale = 1
            else:
                view.ScaleRatio = [float(scale_num), float(scale_denom)]
                view.UseSheetScale = 0
            doc.EditRebuild3()
        except Exception as e:
            logger.error(f"set_view_scale error: {e}")
            return self._result(False, f"Set view scale error: {e}",
                                SwErrors.swFeatureError, data)

        message = (
            f"Set view {view_name!r} to use the sheet scale" if use_sheet_scale
            else f"Set view {view_name!r} scale to {scale_num}:{scale_denom}"
        )
        return self._result(True, message, SwErrors.swSuccess, data)

    # `set_view_display_mode`'s `mode` argument -> swDisplayMode_e member,
    # per the task spec's five named modes (docs/api/02-views.md's
    # swDisplayMode_e Enums entry, added for this issue).
    _DISPLAY_MODES = {
        "wireframe": SwDisplayMode.swWIREFRAME,
        "hidden-lines-visible": SwDisplayMode.swHIDDEN_GREYED,
        "hidden-lines-removed": SwDisplayMode.swHIDDEN,
        "shaded": SwDisplayMode.swSHADED,
        "shaded-with-edges": SwDisplayMode.swSHADED_EDGES,
    }

    def set_view_display_mode(self, view_name: str, mode: str, shadows: bool = False,
                               high_quality: bool = True,
                               sheet_name: Optional[str] = None) -> Dict:
        """
        Set a drawing view's display mode via `IView::SetDisplayMode3`.

        Args:
            view_name: Name of the view to update.
            mode: wireframe, hidden-lines-visible, hidden-lines-removed,
                shaded, or shaded-with-edges (case-insensitive, `_`/` `
                tolerated in place of `-`).
            shadows: `SetDisplayMode3`'s `Edges` parameter -- per
                docs/api/02-views.md, "edges are displayed when this view is
                in shaded mode." Named `shadows` per this issue's task spec
                even though the underlying COM parameter is about edge
                display, not shadow casting (no shadow-toggle parameter
                exists on this call) -- this tool's own naming convention,
                not a dossier term.
            high_quality: True (default) requests precision-quality
                geometry (`SetDisplayMode3`'s `Facetted=False`); False
                requests draft-quality/faceted display. Per the dossier,
                a view cannot be switched from precision back to draft
                quality once it has precision quality.
            sheet_name: Sheet `view_name` lives on, resolved the same way
                `list_views` does.

        Returns:
            Result dict.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        mode_key = (mode or "").strip().lower().replace("_", "-").replace(" ", "-")
        data = {
            "view_name": view_name, "mode": mode_key, "shadows": shadows,
            "high_quality": high_quality, "sheet_name": sheet_name,
        }

        mode_enum = self._DISPLAY_MODES.get(mode_key)
        if mode_enum is None:
            return self._result(
                False,
                f"Unknown mode {mode!r}; expected one of {sorted(self._DISPLAY_MODES)!r}",
                SwErrors.swInvalidInput, data,
            )

        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name)
        if find_err:
            return find_err
        if view is None:
            return self._result(
                False,
                f"Unknown view {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": names},
            )

        try:
            applied = view.SetDisplayMode3(
                False, int(mode_enum), not bool(high_quality), bool(shadows))
        except Exception as e:
            logger.error(f"set_view_display_mode error: {e}")
            return self._result(False, f"Set display mode error: {e}",
                                SwErrors.swFeatureError, data)

        if not applied:
            return self._result(
                False, f"Failed to set display mode for view {view_name!r}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True, f"Set view {view_name!r} display mode to {mode_key}",
            SwErrors.swSuccess, data,
        )

    def _view_children_map(self, sheet: Any) -> Dict[str, List[str]]:
        """`{parent_name: [direct_child_name, ...]}` for every real view on
        `sheet`, via `IView::GetBaseView` -- what `delete_view` uses to find
        a view's dependents before deleting it."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception:
            views_raw = []
        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        children: Dict[str, List[str]] = {}
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            try:
                base = view.GetBaseView()
            except Exception:
                base = None
            parent_name = self._read_prop(base, "GetName2") if base else None
            if parent_name:
                children.setdefault(parent_name, []).append(name)
        return children

    def _descendant_views(self, children_map: Dict[str, List[str]], name: str) -> List[str]:
        """Every transitive descendant of `name`, deepest-first -- a child's
        own children are listed (and would be deleted) before that child
        itself, so `delete_view`'s cascade never orphans a grandchild."""
        result: List[str] = []
        for child in children_map.get(name, []):
            result.extend(self._descendant_views(children_map, child))
            result.append(child)
        return result

    def _delete_single_view(self, doc: Any, view_name: str) -> Dict:
        """Select `view_name` and delete it via `IModelDocExtension::
        DeleteSelection2` -- the shared primitive `delete_view` calls once
        per view in its cascade, deepest descendant first."""
        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                deleted = doc.Extension.DeleteSelection2(0)
            except Exception as e:
                logger.error(f"delete_view error: {e}")
                return self._result(False, f"Delete view error: {e}",
                                    SwErrors.swFeatureError, {"view_name": view_name})

        if not deleted:
            return self._result(
                False, f"Failed to delete view {view_name!r}",
                SwErrors.swFeatureError, {"view_name": view_name},
            )
        return self._result(
            True, f"Deleted view {view_name!r}", SwErrors.swSuccess, {"view_name": view_name},
        )

    def delete_view(self, view_name: str, cascade: bool = False,
                     sheet_name: Optional[str] = None) -> Dict:
        """
        Delete a drawing view via select-then-`IModelDocExtension::
        DeleteSelection2` (docs/api/02-views.md: there is no dedicated
        `DeleteView2` call). Refuses to delete a view with dependent child
        views (section/detail/projected/auxiliary views derived from it, per
        `IView::GetBaseView`) unless `cascade=True`.

        Args:
            view_name: Name of the view to delete.
            cascade: False (default): if `view_name` has any dependent child
                views, fail and list them rather than deleting anything.
                True: delete every descendant first (deepest first), then
                `view_name` itself, reporting every view actually removed.
            sheet_name: Sheet `view_name` lives on, resolved the same way
                `list_views` does.

        Returns:
            Result dict. On success, `data["removed"]` lists every view
            name deleted, in deletion order (descendants before
            `view_name`). On a partial cascade failure, `data["removed"]`
            lists whatever was actually deleted before the failure, so a
            caller can tell a clean refusal (nothing deleted) from a
            partially-completed cascade.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {"view_name": view_name, "cascade": cascade, "sheet_name": sheet_name}

        sheet, sheet_err = self._resolve_sheet(doc, sheet_name)
        if sheet_err:
            return sheet_err

        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name)
        if find_err:
            return find_err
        if view is None:
            return self._result(
                False,
                f"Unknown view {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {**data, "available_views": names},
            )

        children_map = self._view_children_map(sheet)
        descendants = self._descendant_views(children_map, view_name)

        if descendants and not cascade:
            return self._result(
                False,
                f"View {view_name!r} has {len(descendants)} dependent view(s) "
                f"{descendants!r} -- pass cascade=True to delete them too",
                SwErrors.swFeatureError, {**data, "children": descendants},
            )

        removed: List[str] = []
        for name in descendants:
            del_result = self._delete_single_view(doc, name)
            if not del_result["success"]:
                return self._result(
                    False,
                    f"Deleted {removed!r} but failed to delete dependent view "
                    f"{name!r}: {del_result['message']}",
                    SwErrors.swFeatureError, {**data, "removed": removed},
                )
            removed.append(name)

        del_result = self._delete_single_view(doc, view_name)
        if not del_result["success"]:
            return self._result(
                False,
                f"Deleted {removed!r} but failed to delete {view_name!r}: "
                f"{del_result['message']}",
                SwErrors.swFeatureError, {**data, "removed": removed},
            )
        removed.append(view_name)

        message = f"Deleted view {view_name!r}"
        if len(removed) > 1:
            message += f" and {len(removed) - 1} dependent view(s)"
        return self._result(True, message, SwErrors.swSuccess, {**data, "removed": removed})

    # Fallback spacing between packed view groups when `auto_arrange_views`
    # is called without an explicit `margin` -- an arbitrary but reasonable
    # 10mm, this tool's own convention (not sourced from any dossier).
    _DEFAULT_ARRANGE_MARGIN_M = 0.01

    def auto_arrange_views(self, sheet_name: Optional[str] = None,
                            margin: Optional[float] = None) -> Dict:
        """
        Lay out every view on a sheet with no overlapping bounding boxes,
        via `IView::GetOutline` (per-view `[Xmin, Ymin, Xmax, Ymax]` in
        sheet-space meters -- docs/api/02-views.md's `GetOutline` record,
        added for this issue) + `IView::Position`.

        Algorithm (deterministic grid/row packing -- intentionally simple,
        not a compaction bin-packer):
          1. Group views by alignment root: every view with no
             `IView::GetBaseView` parent is a root; every other view folds
             into its ultimate root's group. Only each group's root view is
             ever repositioned -- an aligned child view can only move along
             its alignment vector (see `move_view`'s own lock check), so
             trying to set its `Position` directly would fight SolidWorks'
             own alignment mechanism instead of respecting it. SolidWorks
             carries aligned children along when their root moves, the same
             way dragging a base view in the UI drags its projected views.
             A view can also be `move_view`-locked (`IView::GetAlignment`'s
             `swViewAligned` bit set) with *no* `GetBaseView` parent at all
             -- e.g. a view explicitly aligned to another via `align_view`,
             which is a different relationship than `GetBaseView`'s
             derivation lineage. Such a view would otherwise look like a
             free-standing root here; it is excluded from placement
             entirely (reported in `data["locked"]`, left wherever it is)
             rather than having a `Position` write silently clamped/ignored
             by SolidWorks the same way `move_view` refuses it outright.
          2. Each group's bounding box is the union of every member's own
             `GetOutline` box, in original (pre-arrange) coordinates.
          3. Groups are sorted by `(-original_ymin, original_xmin,
             root_name)` -- a pure function of the input outlines/names, so
             identical input always produces identical output.
          4. Groups are packed into a grid of `ceil(sqrt(group_count))`
             columns, left-to-right/top-to-bottom in sorted order, each row's
             height set by its tallest group, cells separated by `margin` on
             every side -- guarantees no two group boxes overlap without
             needing the sheet's own dimensions (not available anywhere in
             this dossier).
          5. Each root view's `IView::Position` is shifted by the delta its
             group's bounding-box corner moved by, then the whole document
             is rebuilt once via `IModelDoc2::EditRebuild3`.

        A view whose `GetOutline` can't be read is skipped (left wherever it
        already is) rather than failing the whole call.

        Args:
            sheet_name: Sheet to arrange, resolved the same way `list_views`
                does. Omitted: whichever sheet `IDrawingDoc::GetCurrentSheet`
                reports as active.
            margin: Spacing between packed view groups, in the caller's
                default unit (`set_units`). Omitted: a 10mm default.

        Returns:
            Result dict. `data["arranged"]` lists each moved group's root
            view name, its member view names, and its new position (in the
            caller's unit).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        sheet, sheet_err = self._resolve_sheet(doc, sheet_name)
        if sheet_err:
            return sheet_err

        if margin is not None and margin < 0:
            return self._result(
                False, "margin must not be negative", SwErrors.swInvalidInput,
                {"sheet_name": sheet_name, "margin": margin},
            )
        margin_m = self._units.to_meters(margin) if margin is not None else self._DEFAULT_ARRANGE_MARGIN_M

        try:
            views_raw = sheet.GetViews() or []
        except Exception as e:
            logger.error(f"auto_arrange_views error: {e}")
            return self._result(False, f"List views error: {e}", SwErrors.swUnknownError)
        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        by_name: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        skipped: List[str] = []
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            outline = self._read_prop(view, "GetOutline")
            if not isinstance(outline, (list, tuple)) or len(outline) < 4:
                skipped.append(name)
                continue
            try:
                base = view.GetBaseView()
            except Exception:
                base = None
            parent_name = self._read_prop(base, "GetName2") if base else None

            try:
                alignment_code = view.GetAlignment()
            except Exception:
                alignment_code = None
            locked = (
                isinstance(alignment_code, (int, float)) and not isinstance(alignment_code, bool)
                and bool(int(alignment_code) & int(SwViewAlignment.swViewAligned))
            )

            by_name[name] = {
                "name": name, "view": view, "parent_name": parent_name, "locked": locked,
                "xmin": float(outline[0]), "ymin": float(outline[1]),
                "xmax": float(outline[2]), "ymax": float(outline[3]),
            }
            order.append(name)

        data = {"sheet_name": sheet_name, "margin": margin, "skipped": skipped}

        if not by_name:
            return self._result(
                True, "No views with a readable outline to arrange", SwErrors.swSuccess,
                {**data, "locked": [], "arranged": []},
            )

        def root_of(name: str) -> str:
            seen = set()
            while True:
                entry = by_name.get(name)
                parent_name = entry["parent_name"] if entry else None
                if not parent_name or parent_name not in by_name or name in seen:
                    return name
                seen.add(name)
                name = parent_name

        groups: Dict[str, List[str]] = {}
        for name in order:
            root_name = root_of(name)
            groups.setdefault(root_name, []).append(name)

        # A group's root can itself be `move_view`-locked with no
        # `GetBaseView` parent (see this method's own docstring) -- such a
        # group is reported, never placed, rather than writing a Position
        # SolidWorks would clamp/ignore.
        locked_views: List[str] = []
        for root_name in [r for r in groups if by_name[r]["locked"]]:
            locked_views.extend(groups.pop(root_name))
        data["locked"] = locked_views

        if not groups:
            return self._result(
                True, "No movable views to arrange (all locked/skipped)",
                SwErrors.swSuccess, {**data, "arranged": []},
            )

        group_boxes = []
        for root_name, member_names in groups.items():
            group_boxes.append({
                "root_name": root_name, "members": member_names,
                "xmin": min(by_name[n]["xmin"] for n in member_names),
                "ymin": min(by_name[n]["ymin"] for n in member_names),
                "xmax": max(by_name[n]["xmax"] for n in member_names),
                "ymax": max(by_name[n]["ymax"] for n in member_names),
            })
        group_boxes.sort(key=lambda g: (-g["ymin"], g["xmin"], g["root_name"]))

        columns = max(1, ceil(sqrt(len(group_boxes))))
        placements: Dict[str, Tuple[float, float]] = {}
        cursor_x = margin_m
        cursor_y = margin_m
        row_height = 0.0
        for i, g in enumerate(group_boxes):
            if i > 0 and i % columns == 0:
                cursor_y += row_height + margin_m
                cursor_x = margin_m
                row_height = 0.0
            width = g["xmax"] - g["xmin"]
            height = g["ymax"] - g["ymin"]
            placements[g["root_name"]] = (cursor_x, cursor_y)
            cursor_x += width + margin_m
            row_height = max(row_height, height)

        arranged = []
        try:
            for g in group_boxes:
                new_xmin, new_ymin = placements[g["root_name"]]
                delta_x = new_xmin - g["xmin"]
                delta_y = new_ymin - g["ymin"]

                root_entry = by_name[g["root_name"]]
                root_view = root_entry["view"]
                root_position = self._read_prop(root_view, "Position")
                if isinstance(root_position, (list, tuple)) and len(root_position) >= 2:
                    root_x_m, root_y_m = float(root_position[0]), float(root_position[1])
                else:
                    root_x_m, root_y_m = 0.0, 0.0

                new_root_x_m = root_x_m + delta_x
                new_root_y_m = root_y_m + delta_y
                root_view.Position = [new_root_x_m, new_root_y_m]

                arranged.append({
                    "view_name": g["root_name"], "members": g["members"],
                    "x": self._units.from_meters(new_root_x_m),
                    "y": self._units.from_meters(new_root_y_m),
                })
            doc.EditRebuild3()
        except Exception as e:
            logger.error(f"auto_arrange_views error: {e}")
            return self._result(
                False, f"Auto-arrange views error: {e}", SwErrors.swFeatureError,
                {**data, "arranged": arranged},
            )

        return self._result(
            True,
            f"Arranged {len(group_boxes)} view group(s) ({len(by_name)} view(s)) "
            f"on sheet {sheet_name!r}",
            SwErrors.swSuccess, {**data, "arranged": arranged},
        )

    # ========================================================================
    # Model annotation import tools
    # ========================================================================

    def _sheet_view_names(self, sheet: Any) -> List[str]:
        """Every real (non-sheet-pseudo-view) view name on `sheet`, via
        `ISheet::GetViews` -- what `insert_model_items` iterates for
        `all_views=True`, mirroring `list_views`'s own sheet-pseudo-view
        filter."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception:
            views_raw = []
        if not isinstance(views_raw, (list, tuple)):
            views_raw = []

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        names = []
        for view in views_raw:
            type_code = self._read_prop(view, "Type")
            if (isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                    and int(type_code) == sheet_type_code):
                continue
            name = self._read_prop(view, "GetName2")
            if name:
                names.append(name)
        return names

    def _insert_model_items_for_view(self, doc, view_name: str, option: int, types_bitmask: int,
                                      eliminate_duplicates: bool, hidden_features: bool) -> Dict:
        """One view's worth of `insert_model_items`: select `view_name`, call
        `InsertModelAnnotations4`, and report how many annotations it
        actually inserted.

        The inserted count comes straight off `InsertModelAnnotations4`'s own
        return value (an array of the created `IAnnotation` objects, per the
        dossier) rather than a before/after total-annotation-count diff --
        there is no documented `IView`/`IModelDocExtension`
        annotation-count member in docs/api/03-annotations.md to diff
        against (confirmed by re-reading that dossier's `IAnnotation`
        section), and the return array already answers "how many were
        imported" directly. Likewise, no `ForceRebuild3` call is made before
        reading this count: the dossier never claims
        `InsertModelAnnotations4`'s return value is stale until a rebuild.
        """
        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return {
                    "view_name": view_name, "success": False, "count": 0,
                    "message": sel["message"],
                }
            try:
                args = INSERT_MODEL_ANNOTATIONS4.bind(
                    units=self._units,
                    option=option, types=types_bitmask, all_views=False,
                    duplicate_dims=eliminate_duplicates,
                    hidden_feature_dims=hidden_features,
                    use_placement_in_sketch=False,
                    insert_all_annotations=False,
                    insert_all_reference_geometry=False,
                )
                inserted = doc.InsertModelAnnotations4(*args)
            except Exception as e:
                logger.error(f"insert_model_items({view_name!r}) error: {e}")
                return {
                    "view_name": view_name, "success": False, "count": 0,
                    "message": f"Insert model items error: {e}",
                }

        count = len(inserted) if isinstance(inserted, (list, tuple)) else 0
        return {"view_name": view_name, "success": True, "count": count}

    def insert_model_items(self, view_name: Optional[str] = None, sources: Optional[str] = None,
                            types: Optional[List[str]] = None, all_views: bool = False,
                            eliminate_duplicates: bool = True, hidden_features: bool = False) -> Dict:
        """
        Import model annotations onto a drawing view via
        `IDrawingDoc::InsertModelAnnotations4` -- the fastest route to a
        fully dimensioned view for a part modeled with design intent
        (driving dimensions / DimXpert). Supersedes the requested
        `IView::InsertModelAnnotations3`/`IModelDocExtension::
        InsertModelAnnotations3`, neither of which exists (see the dossier's
        section intro); the real member lives on `IDrawingDoc`, and this
        wrapper calls the current `...4` overload rather than `...3` per the
        dossier's own recommendation.

        Args:
            view_name: Name of the drawing view to import into (`IView::
                GetName2`, e.g. from `list_views`). Selected via
                `selected(..., "DRAWINGVIEW", ...)` before the call.
                Mutually exclusive with `all_views` -- passing both fails
                with `swInvalidInput`. Exactly one of `view_name`/`all_views`
                must be given.
            sources: Where the annotations come from -- one of `"model"`
                (default, all dimensions in the view), `"selected_feature"`,
                `"selected_component"` (assembly drawings), or
                `"assembly_only"`, mapped to `swImportModelItemsSource_e`.
                An unrecognized value (including `"dimxpert"` -- see this
                module's `_MODEL_ITEM_SOURCES` Gotcha) fails with
                `swInvalidInput`.
            types: Which annotation types to import -- any of `"dimensions"`,
                `"datums"`, `"datum_targets"`, `"gtols"`, `"surface_finishes"`,
                `"welds"`, `"notes"`, `"hole_callouts"`, `"cosmetic_threads"`,
                `"instance_counts"`, combined into `swInsertAnnotation_e`'s
                bitmask via bitwise OR. Omitted: defaults to `("dimensions",
                "hole_callouts")` (see this module's `_MODEL_ITEM_TYPES`
                Gotcha for why center marks/centerlines aren't offered).
            all_views: `True` to import into every view on the active
                sheet, one `InsertModelAnnotations4` call per view (each
                view selected atomically first) so a per-view count can be
                reported -- the COM `AllViews` argument itself is always
                bound `False`, since a single whole-drawing call gives no
                per-view breakdown. `False` (default): only `view_name`.
            eliminate_duplicates: `DuplicateDims` -- `True` (default) to
                eliminate duplicate dimensions, `False` to allow them.
            hidden_features: `HiddenFeatureDims` -- `True` to insert
                dimensions from hidden features, `False` (default) to skip
                them.

        Returns:
            Result dict. `data["views"]` is a list of `{"view_name",
            "success", "count"}` (one entry per targeted view, in `all_views`
            order when set); `data["total_imported"]` is the sum across all
            of them. A per-view COM failure fails the whole result
            (`swFeatureError`), naming every failed view. A zero-imported
            result is still reported as a *warned* success -- the message
            explicitly says `0 annotations imported` rather than reading
            like an unqualified success (this is the common silent-failure
            mode the issue calls out: the model may have no annotations of
            the requested `types`, or the wrong `sources` was picked).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        if view_name and all_views:
            return self._result(
                False,
                "view_name and all_views are mutually exclusive -- pass exactly one",
                SwErrors.swInvalidInput, {"view_name": view_name, "all_views": all_views},
            )
        if not view_name and not all_views:
            return self._result(
                False,
                "Specify either view_name (a specific view) or all_views=True "
                "(every view on the active sheet)",
                SwErrors.swInvalidInput,
            )

        source_key = (sources or _DEFAULT_MODEL_ITEM_SOURCE).strip().lower()
        source_value = _MODEL_ITEM_SOURCES.get(source_key)
        if source_value is None:
            return self._result(
                False,
                f"Unknown sources {sources!r}; expected one of "
                f"{sorted(_MODEL_ITEM_SOURCES)!r}",
                SwErrors.swInvalidInput, {"sources": sources},
            )

        if types is not None and not isinstance(types, (list, tuple)):
            return self._result(
                False,
                f"types must be a list of strings, got {type(types).__name__}",
                SwErrors.swInvalidInput, {"types": types},
            )
        type_keys = list(types) if types else list(_DEFAULT_MODEL_ITEM_TYPES)
        types_bitmask = 0
        unknown_types = []
        for type_key in type_keys:
            normalized = (type_key or "").strip().lower()
            bit = _MODEL_ITEM_TYPES.get(normalized)
            if bit is None:
                unknown_types.append(type_key)
            else:
                types_bitmask |= bit
        if unknown_types:
            return self._result(
                False,
                f"Unknown types {unknown_types!r}; expected any of "
                f"{sorted(_MODEL_ITEM_TYPES)!r}",
                SwErrors.swInvalidInput, {"types": types},
            )

        if all_views:
            sheet, sheet_err = self._resolve_sheet(doc, None)
            if sheet_err:
                return sheet_err
            target_names = self._sheet_view_names(sheet)
            if not target_names:
                return self._result(
                    False, "No views on the active sheet to import model items into",
                    SwErrors.swFeatureError,
                )
        else:
            target_view, available_views, find_err = self._find_view_by_name(doc, view_name, None)
            if find_err:
                return find_err
            if target_view is None:
                return self._result(
                    False,
                    f"Unknown view {view_name!r}; available views: {available_views!r}",
                    SwErrors.swInvalidInput,
                    {"view_name": view_name, "available_views": available_views},
                )
            target_names = [view_name]

        per_view = [
            self._insert_model_items_for_view(
                doc, name, source_value, types_bitmask, eliminate_duplicates, hidden_features,
            )
            for name in target_names
        ]

        total_imported = sum(v["count"] for v in per_view)
        failed_views = [v["view_name"] for v in per_view if not v["success"]]

        data = {
            "sources": source_key, "types": type_keys, "all_views": all_views,
            "eliminate_duplicates": eliminate_duplicates, "hidden_features": hidden_features,
            "views": per_view, "total_imported": total_imported,
        }

        if failed_views:
            return self._result(
                False, f"Failed to insert model items in view(s): {failed_views!r}",
                SwErrors.swFeatureError, data,
            )

        if total_imported == 0:
            return self._result(
                True,
                f"0 annotations imported across {len(per_view)} view(s) -- check that "
                f"the model actually has {type_keys!r} annotations from {source_key!r}",
                SwErrors.swSuccess, data,
            )

        return self._result(
            True,
            f"Imported {total_imported} annotation(s) across {len(per_view)} view(s)",
            SwErrors.swSuccess, data,
        )

    # ========================================================================
    # Dimension tools
    # ========================================================================

    def add_dimension(self, view_name: str, entities: List[Dict[str, Any]], x: float, y: float,
                       dimension_type: str = "smart") -> Dict:
        """
        Add a drawing-only reference dimension between picked entities in a
        view -- the fallback for anything DimXpert/`insert_model_items` didn't
        already carry over from the model.

        `dimension_type` picks the creation call per this module's
        `_DIMENSION_TYPES` table: `"horizontal"`/`"vertical"` go through
        `IModelDoc2::AddHorizontalDimension2`/`AddVerticalDimension2`;
        `"smart"`/`"radial"`/`"diameter"`/`"angular"` all go through the one
        generic `IModelDoc2::AddDimension2` -- SolidWorks has no dedicated
        creation call for those three, per the dossier's own "Dimensions"
        section intro (see `_DIMENSION_TYPES`'s own comment). What dimension
        actually comes out is inferred by SolidWorks from what's selected,
        not chosen by a parameter -- for `"radial"`/`"diameter"` specifically,
        this is then corrected post-creation via `IDisplayDimension::
        Diametric` (fetched sw-1xx.2; see that dossier record), which toggles
        a radial-capable dimension between radius and diameter display.

        Args:
            view_name: Drawing view the entities live in. Activated via
                `IDrawingDoc::ActivateView` before selection (same as
                `insert_section_view`/`insert_detail_view`'s parent-view
                pattern) -- entity coordinates are resolved in this view's
                active sheet-local space.
            entities: Entity references in the shape `list_view_entities`
                returns -- `{"kind": "edge"/"vertex"/"face", "x", "y", "z"}`
                (caller's default unit). Selected atomically via `selected(...)`,
                the first non-appending, the rest appending (clear-select-act-
                clear ordering, per the working agreement). Per the dossier's
                own `AddDimension2`/`AddHorizontalDimension2` records,
                selection is by location (X/Y/Z), never by name.
            x, y: Placement location for the dimension text/line, caller's
                default unit -- converted to meters at the COM boundary.
            dimension_type: One of `"smart"` (default), `"horizontal"`,
                `"vertical"`, `"radial"`, `"diameter"`, `"angular"`. An
                unrecognized value, or fewer entities than the type's
                documented minimum (2 for horizontal/vertical/angular, 1 for
                everything else), fails with `swInvalidInput` before any COM
                call is made.

        Returns:
            Result dict. `data["name"]` is the created dimension's
            `IDimension::FullName` (e.g. `"D1@Sketch1@Part1.SLDPRT"` -- also
            what `set_dimension_value`/`set_dimension_text` expect as
            `dimension_name`); `data["value"]` is its value converted back to
            the caller's default unit via `IDimension::GetSystemValue3`
            (confirmed meters, sw-1xx.2 dossier addendum).
            `data["dim_type_enum"]` is `dimension_type`'s documented
            `swDimensionType_e` value; `data["type_code"]` is the created
            dimension's *actual* type, read back via `IDisplayDimension::
            Type2` (fetched sw-1xx.2), so a caller can verify SolidWorks
            agreed rather than trusting `dim_type_enum` alone.
        """
        type_key = (dimension_type or "").strip().lower()
        type_config = _DIMENSION_TYPES.get(type_key)
        if type_config is None:
            return self._result(
                False,
                f"Unknown dimension_type {dimension_type!r}; expected one of "
                f"{sorted(_DIMENSION_TYPES)!r}",
                SwErrors.swInvalidInput, {"dimension_type": dimension_type},
            )

        if not isinstance(entities, (list, tuple)) or not entities:
            return self._result(
                False,
                f"entities must be a non-empty list of entity references, got {entities!r}",
                SwErrors.swInvalidInput, {"dimension_type": type_key, "entities": entities},
            )

        min_entities = type_config["min_entities"]
        if len(entities) < min_entities:
            return self._result(
                False,
                f"dimension_type={type_key!r} needs at least {min_entities} "
                f"entit{'y' if min_entities == 1 else 'ies'} to unambiguously define "
                f"it, got {len(entities)}",
                SwErrors.swInvalidInput,
                {"dimension_type": type_key, "entities": entities, "min_entities": min_entities},
            )

        parsed_entities = []
        for i, entity in enumerate(entities):
            parsed, entity_err = _parse_entity_ref(entity)
            if entity_err:
                return self._result(
                    False, f"entities[{i}]: {entity_err}", SwErrors.swInvalidInput,
                    {"dimension_type": type_key, "entities": entities},
                )
            parsed_entities.append(parsed)

        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}",
                SwErrors.swInvalidInput, {"dimension_type": type_key, "x": x, "y": y},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        data = {
            "view_name": view_name, "dimension_type": type_key, "x": x, "y": y,
            "entity_count": len(parsed_entities), "dim_type_enum": type_config["dim_type_enum"],
        }

        with ExitStack() as stack:
            for i, (type_str, ex, ey, ez) in enumerate(parsed_entities):
                sel = stack.enter_context(
                    self.selected("", type_str, ex, ey, ez, append=(i > 0), mark=i)
                )
                if not sel["success"]:
                    return sel

            try:
                x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
                if type_config["method"] == "horizontal":
                    created = doc.AddHorizontalDimension2(x_m, y_m, 0.0)
                elif type_config["method"] == "vertical":
                    created = doc.AddVerticalDimension2(x_m, y_m, 0.0)
                else:
                    created = doc.AddDimension2(x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"add_dimension({view_name!r}) error: {e}")
                return self._result(False, f"Add dimension error: {e}",
                                     SwErrors.swFeatureError, data)

        if created is None:
            return self._result(
                False,
                f"Failed to create a {type_key} dimension in view {view_name!r} -- check "
                "that the selected entities unambiguously define this dimension type",
                SwErrors.swFeatureError, data,
            )

        if type_key in ("radial", "diameter"):
            # `IDisplayDimension::Diametric` is the documented, real
            # accessor this module's earlier docstring said didn't exist
            # (fetched sw-1xx.2, see the dossier record) -- best-effort:
            # it only applies to a radial-capable dimension, so a "smart"
            # selection that produced something else (e.g. an angular
            # dimension) is left alone rather than failing the whole call.
            want_diameter = type_key == "diameter"
            try:
                created.Diametric = want_diameter
                doc.GraphicsRedraw2()
            except Exception as e:
                logger.warning(
                    f"add_dimension({view_name!r}): could not force "
                    f"Diametric={want_diameter!r}: {e}"
                )

        try:
            dimension = created.GetDimension2(0)
            name = self._read_prop(dimension, "FullName")
            type_code = self._read_prop(created, "Type2")
            value_m = dimension.GetSystemValue3(
                int(SwInConfigurationOpts.swThisConfiguration), com_backend.null_dispatch(),
            )
            value = self._units.from_meters(value_m)
        except Exception as e:
            logger.error(f"add_dimension({view_name!r}) read-back error: {e}")
            return self._result(
                False,
                f"Created a {type_key} dimension in view {view_name!r} but could not read "
                f"back its name/value: {e}",
                SwErrors.swFeatureError, data,
            )

        data["name"] = name
        data["value"] = value
        data["type_code"] = type_code
        return self._result(
            True, f"Created {type_key} dimension {name!r} = {value}", SwErrors.swSuccess, data,
        )

    def add_ordinate_dimensions(self, view_name: str, origin_entity: Dict[str, Any],
                                 entities: List[Dict[str, Any]], x: float, y: float,
                                 direction: str = "horizontal") -> Dict:
        """
        Start a baseline/ordinate dimension group off a datum origin via
        `IModelDocExtension::AddOrdinateDimension`.

        Per the dossier's own record for this method, selection here is not a
        clean one-shot select-then-act: the datum (`origin_entity`) and every
        member entity are all selected first (the datum is what makes the
        rest an *ordinate*, rather than independent, dimension group), then
        one `AddOrdinateDimension` call both creates the group and starts it
        accepting more members from any selection made after it returns (this
        wrapper always ends the call with `IModelDoc2::SetPickMode` to leave
        that mode, best-effort, so a later unrelated selection in this
        drawing can't silently keep extending this group).

        Args:
            view_name: Drawing view the entities live in. Activated the same
                way as `add_dimension`.
            origin_entity: The datum/origin entity reference (same shape as
                `add_dimension`'s `entities`), selected first and unmarked.
            entities: One or more additional entity references to include in
                the ordinate group, appended onto the same selection.
            x, y: Placement location for the ordinate dimension, caller's
                default unit.
            direction: `"horizontal"` (default), `"vertical"`, `"angular"`, or
                `"auto"` (orientation inferred from the selected points) --
                `swAddOrdinateDims_e`'s `DimType`.

        Returns:
            Result dict. `data["status"]` is the `swCreateOrdDimError_e`
            member name for `AddOrdinateDimension`'s own return code --
            anything other than `"swCreateOrdDimErr_Success"` fails the
            result with `swFeatureError`. `AddOrdinateDimension` returns a
            bare status code, not the created annotation objects (unlike
            `AddDimension2`/`AddHorizontalDimension2`/`AddVerticalDimension2`),
            so unlike `add_dimension` there is no per-dimension name/value to
            report here.
        """
        direction_key = (direction or "").strip().lower()
        dim_type_value = _ORDINATE_DIRECTIONS.get(direction_key)
        if dim_type_value is None:
            return self._result(
                False,
                f"Unknown direction {direction!r}; expected one of "
                f"{sorted(_ORDINATE_DIRECTIONS)!r}",
                SwErrors.swInvalidInput, {"direction": direction},
            )

        origin_parsed, origin_err = _parse_entity_ref(origin_entity)
        if origin_err:
            return self._result(
                False, f"origin_entity: {origin_err}", SwErrors.swInvalidInput,
                {"origin_entity": origin_entity},
            )

        if not isinstance(entities, (list, tuple)) or not entities:
            return self._result(
                False,
                f"entities must be a non-empty list of entity references, got {entities!r}",
                SwErrors.swInvalidInput, {"entities": entities},
            )

        parsed_entities = []
        for i, entity in enumerate(entities):
            parsed, entity_err = _parse_entity_ref(entity)
            if entity_err:
                return self._result(
                    False, f"entities[{i}]: {entity_err}", SwErrors.swInvalidInput,
                    {"entities": entities},
                )
            parsed_entities.append(parsed)

        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}",
                SwErrors.swInvalidInput, {"x": x, "y": y},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        data = {
            "view_name": view_name, "direction": direction_key, "x": x, "y": y,
            "entity_count": len(parsed_entities),
        }

        all_refs = [origin_parsed] + parsed_entities
        with ExitStack() as stack:
            for i, (type_str, ex, ey, ez) in enumerate(all_refs):
                sel = stack.enter_context(
                    self.selected("", type_str, ex, ey, ez, append=(i > 0), mark=i)
                )
                if not sel["success"]:
                    return sel

            x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
            try:
                status = doc.Extension.AddOrdinateDimension(dim_type_value, x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"add_ordinate_dimensions({view_name!r}) error: {e}")
                return self._result(False, f"Add ordinate dimension error: {e}",
                                     SwErrors.swFeatureError, data)
            finally:
                # Best-effort, and deliberately unconditional (runs whether
                # AddOrdinateDimension succeeded or raised): per the dossier's
                # own Gotcha, any call made without this leaves the document in
                # ordinate-group-building mode, silently absorbing the *next*
                # unrelated selection this drawing makes into this group.
                try:
                    doc.SetPickMode()
                except Exception as e:
                    logger.warning(f"add_ordinate_dimensions: SetPickMode cleanup failed: {e}")

        status_code = int(status) if isinstance(status, (int, float)) else None
        status_name = _enum_name(SwCreateOrdDimError, status_code)
        data["status_code"] = status_code
        data["status"] = status_name

        if status_code != int(SwCreateOrdDimError.swCreateOrdDimErr_Success):
            return self._result(
                False, f"Add ordinate dimension failed in view {view_name!r}: {status_name}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True,
            f"Added ordinate dimension group ({len(parsed_entities)} member "
            f"entit{'y' if len(parsed_entities) == 1 else 'ies'}) off datum in "
            f"view {view_name!r}",
            SwErrors.swSuccess, data,
        )

    def set_dimension_value(self, dimension_name: str, value: float) -> Dict:
        """
        Set a dimension's driving value via `IDimension::SetSystemValue3` --
        the meters-based sibling of the document-unit-based `SetValue3` (see
        that record's sw-1xx.2 Gotcha in the dossier for why this module
        calls the `System` variant).

        Args:
            dimension_name: `IDimension::FullName` (e.g.
                `"D1@Sketch1@Part1.SLDPRT"`), as returned by `add_dimension`'s
                `data["name"]`. Selected via `SelectByID2(dimension_name,
                "DIMENSION", ...)` -- a name-based, not location-based,
                selection (valid for auto-named objects like dimensions per
                the dossier's own `SelectByID2` record).
            value: New value, caller's default unit -- converted to meters at
                the COM boundary. Rejected with `swInvalidInput` before any
                COM call if not numeric.

        Returns:
            Result dict. `data["status"]` is the `swSetValueReturnStatus_e`
            member name for `SetSystemValue3`'s own return code -- anything
            other than `"swSetValue_Successful"` (e.g. a dimension driven by
            geometry, or a frozen feature owner) fails the result with
            `swFeatureError` naming the specific reason rather than a generic
            failure. `data["value"]` is read back via `GetSystemValue3` and
            converted to the caller's default unit.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self._result(
                False, f"value must be a number, got {type(value).__name__}",
                SwErrors.swInvalidInput, {"dimension_name": dimension_name, "value": value},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {"dimension_name": dimension_name, "value": value}

        dimension = None
        with self.selected(dimension_name, "DIMENSION", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                sel_mgr = doc.SelectionManager
                display_dim = sel_mgr.GetSelectedObject6(1, -1)
                if display_dim is None:
                    return self._result(
                        False,
                        f"Selected {dimension_name!r} but could not read it back as a "
                        "dimension (GetSelectedObject6 returned nothing)",
                        SwErrors.swSelectionError, data,
                    )
                dimension = display_dim.GetDimension2(0)
                value_m = self._units.to_meters(value)
                status = dimension.SetSystemValue3(
                    value_m, int(SwSetValueInConfiguration.swSetValue_InThisConfiguration),
                    com_backend.null_dispatch(),
                )
            except Exception as e:
                logger.error(f"set_dimension_value({dimension_name!r}) error: {e}")
                return self._result(False, f"Set dimension value error: {e}",
                                     SwErrors.swFeatureError, data)

        status_code = int(status) if isinstance(status, (int, float)) else None
        status_name = _enum_name(SwSetValueReturnStatus, status_code)
        data["status_code"] = status_code
        data["status"] = status_name

        if status_code != int(SwSetValueReturnStatus.swSetValue_Successful):
            return self._result(
                False, f"Failed to set {dimension_name!r} to {value}: {status_name}",
                SwErrors.swFeatureError, data,
            )

        try:
            new_value_m = dimension.GetSystemValue3(
                int(SwInConfigurationOpts.swThisConfiguration), com_backend.null_dispatch(),
            )
            data["value"] = self._units.from_meters(new_value_m)
        except Exception as e:
            logger.warning(f"set_dimension_value({dimension_name!r}): read-back failed: {e}")

        return self._result(
            True, f"Set {dimension_name!r} = {data['value']}", SwErrors.swSuccess, data,
        )

    def set_dimension_text(self, dimension_name: str, prefix: Optional[str] = None,
                            suffix: Optional[str] = None, override: Optional[str] = None) -> Dict:
        """
        Set a dimension's prefix/suffix/full-override text via
        `IDisplayDimension::SetText` -- for tolerance callouts and "TYP"/"REF"
        annotations.

        Args:
            dimension_name: `IDimension::FullName`, same as `set_dimension_value`.
            prefix: Text before the dimension value (`swDimensionTextPrefix`).
            suffix: Text after the dimension value (`swDimensionTextSuffix`).
            override: Full replacement text (`swDimensionTextAll`) -- per the
                dossier's own Gotcha, this also clears the suffix and turns
                off the live numeric value display, so combining it with
                `suffix` in the same call fights itself (each is still applied
                independently, in `override`, `prefix`, `suffix` order, if more
                than one is given -- nothing stops a caller from doing that,
                but it isn't a meaningful combination).
                At least one of `prefix`/`suffix`/`override` is required --
                rejected with `swInvalidInput` before any COM call otherwise.

        Returns:
            Result dict. `data["prefix"]`/`data["suffix"]` are read back via
            `IDisplayDimension::GetText` after the update (`swDimensionTextAll`
            is not valid for `GetText`, per the dossier, so `override` itself
            is never read back -- only its effect on the prefix slot is
            visible that way).
        """
        if prefix is None and suffix is None and override is None:
            return self._result(
                False, "Specify at least one of prefix/suffix/override",
                SwErrors.swInvalidInput, {"dimension_name": dimension_name},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "dimension_name": dimension_name, "prefix": prefix, "suffix": suffix,
            "override": override,
        }

        display_dim = None
        with self.selected(dimension_name, "DIMENSION", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                sel_mgr = doc.SelectionManager
                display_dim = sel_mgr.GetSelectedObject6(1, -1)
                if display_dim is None:
                    return self._result(
                        False,
                        f"Selected {dimension_name!r} but could not read it back as a "
                        "dimension (GetSelectedObject6 returned nothing)",
                        SwErrors.swSelectionError, data,
                    )
                if override is not None:
                    display_dim.SetText(int(SwDimensionTextParts.swDimensionTextAll), override)
                if prefix is not None:
                    display_dim.SetText(int(SwDimensionTextParts.swDimensionTextPrefix), prefix)
                if suffix is not None:
                    display_dim.SetText(int(SwDimensionTextParts.swDimensionTextSuffix), suffix)
            except Exception as e:
                logger.error(f"set_dimension_text({dimension_name!r}) error: {e}")
                return self._result(False, f"Set dimension text error: {e}",
                                     SwErrors.swFeatureError, data)

        try:
            doc.GraphicsRedraw2()
        except Exception as e:
            logger.warning(f"set_dimension_text({dimension_name!r}): GraphicsRedraw2 failed: {e}")

        try:
            data["prefix"] = display_dim.GetText(int(SwDimensionTextParts.swDimensionTextPrefix))
            data["suffix"] = display_dim.GetText(int(SwDimensionTextParts.swDimensionTextSuffix))
        except Exception as e:
            logger.warning(f"set_dimension_text({dimension_name!r}): read-back failed: {e}")

        return self._result(
            True, f"Updated text for dimension {dimension_name!r}", SwErrors.swSuccess, data,
        )

    def autodimension_view(self, view_name: str, scheme: str = "baseline", entities: str = "all",
                            horizontal_placement: str = "above",
                            vertical_placement: str = "left") -> Dict:
        """
        Bulk-dimension a drawing view via `IDrawingDoc::AutoDimension` -- a
        "just add reasonable baseline dimensions" fallback for a view with no
        usable DimXpert data. This dossier confirmed `AutoDimension` is real,
        current, and the sole member of the "autodimension family" (no
        `AutoDimension2`/`3`) -- see docs/api/03-annotations.md's own record;
        this is a genuine implementation, not an unsupported-API stub.

        Args:
            view_name: Drawing view to autodimension. Selected via
                `selected(view_name, "DRAWINGVIEW", ...)` -- per the dossier,
                `AutoDimension` also accepts no view selection at all
                (defaulting to the drawing's first view), but this wrapper
                always selects `view_name` explicitly so the caller's choice
                is never ambiguous.
            scheme: `"baseline"` (default), `"ordinate"`, or `"chain"` --
                `swAutodimScheme_e`, applied to both `HorizontalScheme` and
                `VerticalScheme` (the tool exposes one scheme, not separate
                horizontal/vertical ones). `swAutodimSchemeCenterline` is
                deliberately not offered -- documented as unsupported in
                drawings.
            entities: `"all"` (default, every supported entity in the view),
                `"based_on_preselect"`, or `"selected"` -- `swAutodimEntities_e`.
                This tool does not expose a way to mark individual entities
                with `swAutodimMarkEntities` beforehand, so `"selected"`/
                `"based_on_preselect"` only do something useful if a caller
                left a marked selection some other way; with nothing marked,
                SolidWorks falls back to `"all"` per the dossier.
            horizontal_placement: `"above"` (default) or `"below"` --
                `swAutodimHorizontalPlacement_e`.
            vertical_placement: `"left"` (default) or `"right"` --
                `swAutodimVerticalPlacement_e`.

        Returns:
            Result dict. `data["status"]` is the `swAutodimStatus_e` member
            name for `AutoDimension`'s own return code -- anything other than
            `"swAutodimStatusSuccess"` fails the result with `swFeatureError`
            naming the specific reason (e.g. no entities, an over-defined
            sketch, a missing datum).
        """
        scheme_key = (scheme or "").strip().lower()
        scheme_value = _AUTODIM_SCHEMES.get(scheme_key)
        if scheme_value is None:
            return self._result(
                False, f"Unknown scheme {scheme!r}; expected one of {sorted(_AUTODIM_SCHEMES)!r}",
                SwErrors.swInvalidInput, {"scheme": scheme},
            )

        entities_key = (entities or "").strip().lower()
        entities_value = _AUTODIM_ENTITIES.get(entities_key)
        if entities_value is None:
            return self._result(
                False,
                f"Unknown entities {entities!r}; expected one of {sorted(_AUTODIM_ENTITIES)!r}",
                SwErrors.swInvalidInput, {"entities": entities},
            )

        h_placement_key = (horizontal_placement or "").strip().lower()
        h_placement_value = _AUTODIM_HORIZONTAL_PLACEMENTS.get(h_placement_key)
        if h_placement_value is None:
            return self._result(
                False,
                f"Unknown horizontal_placement {horizontal_placement!r}; expected one of "
                f"{sorted(_AUTODIM_HORIZONTAL_PLACEMENTS)!r}",
                SwErrors.swInvalidInput, {"horizontal_placement": horizontal_placement},
            )

        v_placement_key = (vertical_placement or "").strip().lower()
        v_placement_value = _AUTODIM_VERTICAL_PLACEMENTS.get(v_placement_key)
        if v_placement_value is None:
            return self._result(
                False,
                f"Unknown vertical_placement {vertical_placement!r}; expected one of "
                f"{sorted(_AUTODIM_VERTICAL_PLACEMENTS)!r}",
                SwErrors.swInvalidInput, {"vertical_placement": vertical_placement},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "view_name": view_name, "scheme": scheme_key, "entities": entities_key,
            "horizontal_placement": h_placement_key, "vertical_placement": v_placement_key,
        }

        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                status = doc.AutoDimension(
                    entities_value, scheme_value, h_placement_value, scheme_value, v_placement_value,
                )
            except Exception as e:
                logger.error(f"autodimension_view({view_name!r}) error: {e}")
                return self._result(False, f"Autodimension error: {e}",
                                     SwErrors.swFeatureError, data)

        status_code = int(status) if isinstance(status, (int, float)) else None
        status_name = _enum_name(SwAutodimStatus, status_code)
        data["status_code"] = status_code
        data["status"] = status_name

        if status_code != int(SwAutodimStatus.swAutodimStatusSuccess):
            return self._result(
                False, f"Autodimension of view {view_name!r} failed: {status_name}",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True, f"Autodimensioned view {view_name!r} ({scheme_key})",
            SwErrors.swSuccess, data,
        )

    # ========================================================================
    # Note tools (sw-1xx.3)
    # ========================================================================

    @staticmethod
    def _format_note_text(text: str, bold: bool, italic: bool) -> str:
        """Prepend the `<FONT style=...>` instruction(s) `bold`/`italic` ask
        for -- per docs/api/03-annotations.md's "Note enumeration, formatting,
        and editing" record, `style=B`/`style=I` are independent toggles, so
        requesting both chains two instructions rather than combining values
        in one. Neither flag set returns `text` unchanged."""
        prefix = ""
        if bold:
            prefix += "<FONT style=B>"
        if italic:
            prefix += "<FONT style=I>"
        return f"{prefix}{text}"

    def _parse_leader(self, leader: Optional[Dict[str, Any]]) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Validate `add_note`/`add_property_note`'s `leader` argument before
        any COM call. `None` -- the common case -- passes through as `(None,
        None)`, which downstream leaves the freshly-created note's default
        (leaderless) state untouched, satisfying "leader=None produces a
        leaderless note" without an extra `SetLeader3` round-trip.

        `leader` shape: `{"style": "none"|"straight"|"bent"|"underline",
        "x"/"y": optional attachment point (caller's unit, both-or-neither),
        "z": optional, default 0, "smart_arrow": bool default True (the
        confirmed `SetLeader3` "arrow style" parameter is a bool, not an
        enum -- see that record's own Gotchas), "dashed"/"perpendicular"/
        "all_around": bool, default False}.
        """
        if leader is None:
            return None, None
        if not isinstance(leader, dict):
            return None, self._result(
                False, f"leader must be an object or null, got {type(leader).__name__}",
                SwErrors.swInvalidInput, {"leader": leader},
            )

        style_raw = leader.get("style", "none")
        style_key = (style_raw or "none").strip().lower() if isinstance(style_raw, str) else ""
        style_enum = _NOTE_LEADER_STYLES.get(style_key)
        if style_enum is None:
            return None, self._result(
                False,
                f"Unknown leader style {style_raw!r}; expected one of "
                f"{sorted(_NOTE_LEADER_STYLES)!r}",
                SwErrors.swInvalidInput, {"leader": leader},
            )

        x, y = leader.get("x"), leader.get("y")
        if (x is None) != (y is None):
            return None, self._result(
                False, "leader x/y must both be given or both omitted",
                SwErrors.swInvalidInput, {"leader": leader},
            )
        if x is not None and (
            isinstance(x, bool) or isinstance(y, bool)
            or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
        ):
            return None, self._result(
                False, f"leader x/y must be numbers, got x={x!r}, y={y!r}",
                SwErrors.swInvalidInput, {"leader": leader},
            )
        z = leader.get("z", 0)
        if isinstance(z, bool) or not isinstance(z, (int, float)):
            z = 0

        return {
            "style_key": style_key, "style_enum": style_enum,
            "x": x, "y": y, "z": z,
            "smart_arrow": bool(leader.get("smart_arrow", True)),
            "dashed": bool(leader.get("dashed", False)),
            "perpendicular": bool(leader.get("perpendicular", False)),
            "all_around": bool(leader.get("all_around", False)),
        }, None

    def _validate_note_geometry(self, x: float, y: float, height: Optional[float],
                                 angle: float) -> Optional[Dict]:
        """Type/range-check `add_note`/`add_property_note`'s `x`/`y`/`height`/
        `angle` -- split out from `_create_note_object` so callers can run it
        *before* any COM call (including `select_view_by_name`'s
        `ActivateView`), per the working agreement's "validate before COM
        calls" rule. Returns an error dict, or `None` if everything checks out.
        """
        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}", SwErrors.swInvalidInput,
            )
        if height is not None and (
            isinstance(height, bool) or not isinstance(height, (int, float)) or height < 0
        ):
            return self._result(
                False, f"height must be a non-negative number, got {height!r}",
                SwErrors.swInvalidInput,
            )
        if isinstance(angle, bool) or not isinstance(angle, (int, float)):
            return self._result(
                False, f"angle must be a number, got {angle!r}", SwErrors.swInvalidInput,
            )
        return None

    def _create_note_object(self, doc, text_string: str, x: float, y: float,
                             height: Optional[float], angle: float) -> Tuple[Any, Optional[Dict]]:
        """`IDrawingDoc::CreateText2(TextString, TextX, TextY, TextZ, TextHeight,
        TextAngle) As INote` -- shared by `add_note`/`add_property_note`.

        `x`/`y` are sheet-space coordinates relative to the sheet's
        lower-left corner (per the dossier's own Remarks quote), in the
        caller's default unit, converted to meters here; `TextZ` is always
        `0.0` (2D sheet space). `height` (caller's unit) converts to meters,
        or `0.0` -- SolidWorks' own "use the document's default note height"
        sentinel, by analogy with this project's other optional-dimension
        parameters -- when omitted. `angle` (degrees) converts to radians.

        Assumes `x`/`y`/`height`/`angle` were already validated via
        `_validate_note_geometry` -- callers that skip that step (there are
        none in this file) would still be caught here, just after any prior
        COM call the caller made.
        """
        geometry_err = self._validate_note_geometry(x, y, height, angle)
        if geometry_err:
            return None, geometry_err

        x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
        height_m = self._units.to_meters(height) if height is not None else 0.0
        angle_rad = to_radians(angle)

        try:
            note = doc.CreateText2(text_string, x_m, y_m, 0.0, height_m, angle_rad)
        except Exception as e:
            logger.error(f"add_note: CreateText2 error: {e}")
            return None, self._result(False, f"Create note error: {e}", SwErrors.swFeatureError)

        if note is None:
            return None, self._result(
                False, "CreateText2 returned nothing -- note not created", SwErrors.swFeatureError,
            )
        return note, None

    def _finalize_note(self, note: Any, leader_parsed: Optional[Dict],
                        layer: Optional[str]) -> Tuple[Any, Optional[Dict]]:
        """Apply `leader_parsed`/`layer` to a freshly-created `note` via its
        `IAnnotation` wrapper (`INote::GetAnnotation`), and return that
        wrapper (for name/position read-back) -- shared tail of
        `add_note`/`add_property_note`.

        Returns `(annotation, None)` on success -- `annotation` may be
        `None` if `GetAnnotation` itself came back empty, which is only a
        hard failure when there was a `leader`/`layer` to apply; a caller
        that got this far with neither still gets `(None, None)` back
        rather than an error, since nothing needed the wrapper.
        """
        try:
            annotation = note.GetAnnotation()
        except Exception as e:
            logger.error(f"add_note: GetAnnotation error: {e}")
            return None, self._result(False, f"Get note annotation error: {e}", SwErrors.swFeatureError)

        if leader_parsed is None and not layer:
            return annotation, None

        if annotation is None:
            return None, self._result(
                False, "Note has no IAnnotation wrapper (GetAnnotation returned nothing) "
                "-- cannot set leader/layer", SwErrors.swFeatureError,
            )

        if leader_parsed is not None:
            try:
                status = annotation.SetLeader3(
                    int(leader_parsed["style_enum"]), _LEADER_SIDE_DEFAULT,
                    leader_parsed["smart_arrow"], leader_parsed["perpendicular"],
                    leader_parsed["all_around"], leader_parsed["dashed"],
                )
            except Exception as e:
                logger.error(f"add_note: SetLeader3 error: {e}")
                return None, self._result(False, f"Set leader error: {e}", SwErrors.swFeatureError)

            status_code = int(status) if isinstance(status, (int, float)) else None
            if status_code != 0:
                return None, self._result(
                    False,
                    f"Could not set leader style {leader_parsed['style_key']!r} "
                    f"(SetLeader3 status {status_code})",
                    SwErrors.swFeatureError, {"status_code": status_code},
                )

            if leader_parsed["x"] is not None:
                try:
                    x_m = self._units.to_meters(leader_parsed["x"])
                    y_m = self._units.to_meters(leader_parsed["y"])
                    z_m = self._units.to_meters(leader_parsed["z"] or 0)
                    attached = annotation.SetLeaderAttachmentPointAtIndex(0, x_m, y_m, z_m)
                except Exception as e:
                    logger.error(f"add_note: SetLeaderAttachmentPointAtIndex error: {e}")
                    return None, self._result(
                        False, f"Set leader attachment point error: {e}", SwErrors.swFeatureError,
                    )
                if attached is False:
                    return None, self._result(
                        False,
                        "Could not set leader attachment point "
                        "(SetLeaderAttachmentPointAtIndex returned False)",
                        SwErrors.swFeatureError,
                    )

        if layer:
            try:
                annotation.Layer = layer
            except Exception as e:
                logger.error(f"add_note: set Layer error: {e}")
                return None, self._result(False, f"Set layer error: {e}", SwErrors.swFeatureError)

        return annotation, None

    def _note_data(self, note: Any, annotation: Any, view_name: Optional[str],
                    height: Optional[float], angle: float, bold: bool, italic: bool,
                    layer: Optional[str]) -> Dict:
        """Best-effort result payload shared by `add_note`/`add_property_note`
        -- name/position read back from `annotation` (via `IAnnotation::
        GetName`/`GetPosition`, both meters on the wire), everything else
        just the caller's own (already-validated) arguments."""
        name = self._read_prop(annotation, "GetName") if annotation is not None else None

        x = y = None
        position = self._read_prop(annotation, "GetPosition") if annotation is not None else None
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                x = self._units.from_meters(float(position[0]))
                y = self._units.from_meters(float(position[1]))
            except (TypeError, ValueError):
                x = y = None

        return {
            "name": name, "view_name": view_name, "x": x, "y": y,
            "height": height, "angle": angle, "bold": bold, "italic": italic,
            "layer": layer or None,
        }

    def add_note(self, text: str, x: float, y: float, view_name: Optional[str] = None,
                  leader: Optional[Dict[str, Any]] = None, height: Optional[float] = None,
                  angle: float = 0, bold: bool = False, italic: bool = False,
                  layer: Optional[str] = None) -> Dict:
        """
        Add a general/flag note to a drawing sheet via `IDrawingDoc::
        CreateText2`, optionally with a leader and/or a layer assignment.

        Args:
            text: Note text. `\\n` (a literal line feed) is SolidWorks' own
                multi-line separator for note text (confirmed via
                `vbLf`/`Chr(10)` -- Python's `\\n` is the same byte, so no
                translation happens here) -- passed straight through.
            x, y: Placement, relative to the sheet's lower-left corner,
                caller's default unit -- converted to meters.
            view_name: Drawing view to activate first via
                `select_view_by_name`, so the note is authored in that
                view's context. Omitted: whatever view/sheet is already
                active.
            leader: Optional dict -- see `_parse_leader`'s docstring for the
                full shape. `None` (default) leaves the note leaderless.
            height: Text height, caller's default unit -- converted to
                meters, or SolidWorks' document-default sentinel (`0.0`)
                when omitted.
            angle: Text angle in degrees (default `0`) -- converted to
                radians at the COM boundary.
            bold, italic: Wrapped as `<FONT style=B>`/`<FONT style=I>`
                instruction(s) at the start of `text` (see
                `_format_note_text`).
            layer: Optional layer name (`IAnnotation::Layer`) to file the
                note under.

        Returns:
            Result dict. `data["name"]` is the note's SolidWorks-assigned
            name (`IAnnotation::GetName`, e.g. `"Note1"`) -- what
            `edit_note`'s `note_name` expects. `data["x"]`/`["y"]` are read
            back via `IAnnotation::GetPosition` rather than echoing the
            input, so a caller sees what SolidWorks actually did with it.
        """
        if not isinstance(text, str):
            return self._result(
                False, f"text must be a string, got {type(text).__name__}",
                SwErrors.swInvalidInput, {"text": text},
            )

        leader_parsed, leader_err = self._parse_leader(leader)
        if leader_err:
            return leader_err

        geometry_err = self._validate_note_geometry(x, y, height, angle)
        if geometry_err:
            return geometry_err

        doc, err = self.get_drawing_doc()
        if err:
            return err

        if view_name:
            activated = self.select_view_by_name(view_name)
            if not activated["success"]:
                return activated

        text_string = self._format_note_text(text, bold, italic)
        note, create_err = self._create_note_object(doc, text_string, x, y, height, angle)
        if create_err:
            return create_err

        annotation, finalize_err = self._finalize_note(note, leader_parsed, layer)
        if finalize_err:
            return finalize_err

        data = self._note_data(note, annotation, view_name, height, angle, bold, italic, layer)
        data["text"] = text
        return self._result(True, f"Added note {data['name'] or '(unnamed)'!r}",
                             SwErrors.swSuccess, data)

    def add_property_note(self, property_name: str, x: float, y: float, source: str = "sheet",
                           prefix: str = "", suffix: str = "", **note_opts) -> Dict:
        """
        Convenience wrapper over `add_note` that creates a note whose text is
        entirely a custom-property link -- the mechanism that keeps a title
        block's "Weight"/"Material"/etc. fields live against the model.

        Args:
            property_name: Custom property name to link, e.g. `"SW-Mass"`.
            x, y: Placement, same as `add_note`.
            source: `"sheet"` (default) emits `$PRPSHEET:"name"` (the model
                shown in the sheet's "Use custom property values from model
                shown in" setting -- the one title blocks use for part
                properties like mass/material) or `"model"` emits
                `$PRP:"name"` (the drawing document's own properties).
            prefix, suffix: Literal text around the link, e.g.
                `add_property_note("SW-Mass", 10, 10, prefix="Weight: ")`.
            **note_opts: Any of `add_note`'s other keyword arguments
                (`view_name`, `leader`, `height`, `angle`, `bold`, `italic`,
                `layer`) -- forwarded as-is. `bold`/`italic` are applied to
                the linked-text string itself (see below), not to an
                initial `CreateText2` call, since `PropertyLinkedText`
                replaces the note's entire content.

        Returns:
            Result dict, same shape as `add_note`, plus `data["source"]`,
            `data["property_name"]`, and `data["linked_text"]` (the exact
            string assigned to `INote::PropertyLinkedText`).
        """
        prefix_map = {"sheet": "PRPSHEET", "model": "PRP"}
        source_key = (source or "").strip().lower()
        if source_key not in prefix_map:
            return self._result(
                False, f"Unknown source {source!r}; expected one of {sorted(prefix_map)!r}",
                SwErrors.swInvalidInput, {"source": source},
            )

        note_opts = dict(note_opts)
        bold = bool(note_opts.pop("bold", False))
        italic = bool(note_opts.pop("italic", False))
        leader = note_opts.pop("leader", None)
        view_name = note_opts.pop("view_name", None)
        height = note_opts.pop("height", None)
        angle = note_opts.pop("angle", 0)
        layer = note_opts.pop("layer", None)
        if note_opts:
            return self._result(
                False, f"Unknown note_opts: {sorted(note_opts)!r}",
                SwErrors.swInvalidInput, {"note_opts": note_opts},
            )

        leader_parsed, leader_err = self._parse_leader(leader)
        if leader_err:
            return leader_err

        geometry_err = self._validate_note_geometry(x, y, height, angle)
        if geometry_err:
            return geometry_err

        doc, err = self.get_drawing_doc()
        if err:
            return err

        if view_name:
            activated = self.select_view_by_name(view_name)
            if not activated["success"]:
                return activated

        note, create_err = self._create_note_object(doc, "", x, y, height, angle)
        if create_err:
            return create_err

        linked_text = self._format_note_text(
            f'{prefix}${prefix_map[source_key]}:"{property_name}"{suffix}', bold, italic,
        )
        try:
            note.PropertyLinkedText = linked_text
        except Exception as e:
            logger.error(f"add_property_note: PropertyLinkedText error: {e}")
            return self._result(False, f"Link property error: {e}", SwErrors.swFeatureError,
                                 {"linked_text": linked_text})

        annotation, finalize_err = self._finalize_note(note, leader_parsed, layer)
        if finalize_err:
            return finalize_err

        data = self._note_data(note, annotation, view_name, height, angle, bold, italic, layer)
        data.update({
            "source": source_key, "property_name": property_name, "linked_text": linked_text,
        })
        return self._result(True, f"Added property note linking {property_name!r} ({source_key})",
                             SwErrors.swSuccess, data)

    # ------------------------------------------------------------------
    # Note discovery / editing
    # ------------------------------------------------------------------

    def _iter_document_views(self, doc):
        """Walk every view in the document via `IDrawingDoc::GetFirstView` /
        `IView::GetNextView` -- per docs/api/03-annotations.md's "Note
        enumeration" record, `GetFirstView` returns the active sheet's own
        pseudo/template view first (where sheet-level/title-block notes
        live), then `GetNextView` walks every real view, then the next
        sheet's own pseudo-view, and so on across the whole document."""
        try:
            view = doc.GetFirstView()
        except Exception as e:
            logger.warning(f"_iter_document_views: GetFirstView failed: {e}")
            view = None
        while view is not None:
            yield view
            try:
                nxt = view.GetNextView()
            except Exception as e:
                logger.warning(f"_iter_document_views: GetNextView failed: {e}")
                nxt = None
            view = nxt if nxt else None

    def _iter_view_notes(self, view):
        """Walk every note attached to `view` via `IView::GetFirstNote` /
        `INote::GetNext`."""
        try:
            note = view.GetFirstNote()
        except Exception as e:
            logger.warning(f"_iter_view_notes: GetFirstNote failed: {e}")
            note = None
        while note is not None:
            yield note
            try:
                nxt = note.GetNext()
            except Exception as e:
                logger.warning(f"_iter_view_notes: GetNext failed: {e}")
                nxt = None
            note = nxt if nxt else None

    def _describe_note(self, note: Any, view_name: Optional[str]) -> Dict:
        """`list_notes`/`edit_note`'s per-note description: text, position,
        layer, and the view it was found on."""
        try:
            annotation = note.GetAnnotation()
        except Exception:
            annotation = None

        name = self._read_prop(annotation, "GetName") if annotation is not None else None
        layer = self._read_prop(annotation, "Layer") if annotation is not None else None

        x = y = None
        position = self._read_prop(annotation, "GetPosition") if annotation is not None else None
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                x = self._units.from_meters(float(position[0]))
                y = self._units.from_meters(float(position[1]))
            except (TypeError, ValueError):
                x = y = None

        is_compound = bool(self._read_prop(note, "IsCompoundNote"))
        text = self._read_prop(note, "GetText")

        return {
            "name": name, "text": text, "is_compound": is_compound,
            "x": x, "y": y, "layer": layer or None, "view_name": view_name,
        }

    def list_notes(self, view_name: Optional[str] = None,
                    sheet_name: Optional[str] = None) -> Dict:
        """
        Enumerate existing notes -- text, position, layer -- via `IView::
        GetFirstNote`/`INote::GetNext`, so an LLM can find (and then
        `edit_note`) a template's placeholder notes without a mouse.

        Args:
            view_name: Restrict to notes attached to this one view (the
                view is activated first via `select_view_by_name`).
                Mutually exclusive in effect with `sheet_name` -- if both are
                given, `view_name` wins and `sheet_name` is ignored.
            sheet_name: Restrict to notes on this sheet's own real views
                plus its sheet-level/title-block notes. Omitted (with
                `view_name` also omitted): every note in the whole document.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        notes: List[Dict] = []

        if view_name:
            activated = self.select_view_by_name(view_name)
            if not activated["success"]:
                return activated
            try:
                view = doc.ActiveDrawingView
            except Exception as e:
                logger.error(f"list_notes({view_name!r}) error: {e}")
                return self._result(False, f"List notes error: {e}", SwErrors.swSelectionError)
            notes = [self._describe_note(n, view_name) for n in self._iter_view_notes(view)]
            return self._result(
                True, f"{len(notes)} note(s) in view {view_name!r}", SwErrors.swSuccess,
                {"view_name": view_name, "sheet_name": sheet_name, "notes": notes},
            )

        allowed_view_names = None
        if sheet_name:
            sheet, err = self._resolve_sheet(doc, sheet_name)
            if err:
                return err
            try:
                views_raw = sheet.GetViews() or []
            except Exception as e:
                logger.error(f"list_notes(sheet_name={sheet_name!r}) error: {e}")
                return self._result(False, f"List notes error: {e}", SwErrors.swUnknownError)
            allowed_view_names = {
                self._read_prop(v, "GetName2") for v in views_raw
                if self._read_prop(v, "GetName2")
            }

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        for view in self._iter_document_views(doc):
            v_name = self._read_prop(view, "GetName2")
            type_code = self._read_prop(view, "Type")
            is_sheet_pseudo = (
                isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                and int(type_code) == sheet_type_code
            )
            include = True
            if allowed_view_names is not None:
                include = (v_name in allowed_view_names) or (is_sheet_pseudo and v_name == sheet_name)
            if include:
                notes.extend(self._describe_note(n, v_name) for n in self._iter_view_notes(view))

        return self._result(
            True, f"{len(notes)} note(s)" + (f" on sheet {sheet_name!r}" if sheet_name else ""),
            SwErrors.swSuccess, {"view_name": view_name, "sheet_name": sheet_name, "notes": notes},
        )

    def edit_note(self, note_name: str, text: Optional[str] = None,
                   x: Optional[float] = None, y: Optional[float] = None) -> Dict:
        """
        Update an existing note's text and/or position -- how a caller fills
        in a template's placeholder notes (e.g. a title block authored with
        a `"<PART NAME>"` placeholder note that already carries the right
        `$PRPSHEET` links elsewhere) without recreating them.

        Args:
            note_name: `IAnnotation::GetName`'s value for the target note
                (e.g. `"Note1"`, or whatever it was renamed to) -- as
                returned by `add_note`/`add_property_note`'s `data["name"]`
                or `list_notes`' `data["notes"][i]["name"]`. Unrecognized:
                fails with `swInvalidInput` listing every note name found in
                the document, rather than a bare "not found".
            text: New text (`INote::SetText`) -- same `\\n` multi-line
                convention as `add_note`.
            x, y: New position, caller's default unit -- converted to
                meters. Either may be given alone; the other axis (and Z)
                are read back from the note's current position
                (`IAnnotation::GetPosition`) and left unchanged.

        Returns:
            Result dict. Fails with `swFeatureError` if `SetText`/
            `SetPosition2` themselves report failure (SolidWorks declines
            without raising for e.g. a locked/read-only note).
        """
        if text is None and x is None and y is None:
            return self._result(
                False, "Specify at least one of text/x/y", SwErrors.swInvalidInput,
                {"note_name": note_name},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        target_note = None
        target_annotation = None
        available_names: List[str] = []
        for view in self._iter_document_views(doc):
            for note in self._iter_view_notes(view):
                try:
                    annotation = note.GetAnnotation()
                except Exception:
                    annotation = None
                name = self._read_prop(annotation, "GetName") if annotation is not None else None
                if name:
                    available_names.append(name)
                if name == note_name:
                    target_note, target_annotation = note, annotation
                    break
            if target_note is not None:
                break

        if target_note is None:
            return self._result(
                False,
                f"Note {note_name!r} not found; available notes: {sorted(set(available_names))!r}",
                SwErrors.swInvalidInput,
                {"note_name": note_name, "available_notes": sorted(set(available_names))},
            )

        data: Dict[str, Any] = {"note_name": note_name}

        if text is not None:
            try:
                set_ok = target_note.SetText(text)
            except Exception as e:
                logger.error(f"edit_note({note_name!r}) SetText error: {e}")
                return self._result(False, f"Set note text error: {e}", SwErrors.swFeatureError, data)
            if set_ok is False:
                return self._result(
                    False, f"Could not set text on note {note_name!r} (SetText returned False)",
                    SwErrors.swFeatureError, data,
                )
            data["text"] = text

        if x is not None or y is not None:
            if target_annotation is None:
                return self._result(
                    False, f"Note {note_name!r} has no IAnnotation wrapper -- cannot reposition",
                    SwErrors.swFeatureError, data,
                )
            try:
                current = target_annotation.GetPosition()
            except Exception:
                current = None
            if not isinstance(current, (list, tuple)) or len(current) < 3:
                current = (0.0, 0.0, 0.0)

            x_m = self._units.to_meters(x) if x is not None else current[0]
            y_m = self._units.to_meters(y) if y is not None else current[1]
            z_m = current[2]

            try:
                moved = target_annotation.SetPosition2(x_m, y_m, z_m)
            except Exception as e:
                logger.error(f"edit_note({note_name!r}) SetPosition2 error: {e}")
                return self._result(False, f"Set note position error: {e}", SwErrors.swFeatureError, data)
            if moved is False:
                return self._result(
                    False, f"Could not reposition note {note_name!r} (SetPosition2 returned False)",
                    SwErrors.swFeatureError, data,
                )
            if x is not None:
                data["x"] = x
            if y is not None:
                data["y"] = y

        return self._result(True, f"Updated note {note_name!r}", SwErrors.swSuccess, data)

    # ------------------------------------------------------------------
    # GD&T: datum features, feature control frames, datum targets
    # ------------------------------------------------------------------

    @staticmethod
    def _format_gtol_number(value: float) -> str:
        """Format a GTol frame numeric field (`SetFrameValues2`'s `Tol1`,
        `add_datum_target`'s `size`, `SetPTZHeight2`'s `Height`) as the plain
        display text those String-typed COM parameters want -- NOT run
        through `self._units.to_meters`. Per docs/api/03-annotations.md's
        GD&T section, `Tol1`/`Height` are document-display strings (the
        official worked example passes plain `"0.4"`), not `Double` meters
        values -- this project's own choice, flagged as an open ambiguity in
        that record's Gotchas, is to format the caller's default-unit number
        directly rather than silently converting it.

        Integral values format without a trailing `.0` (`5`, not `5.0`);
        everything else uses Python's plain `str()` (`"0.4"`, `"0.005"`) --
        deterministic for this project's own construction, not a
        SolidWorks-documented rounding/precision rule.
        """
        if isinstance(value, bool):
            value = float(value)
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
            return str(int(value))
        return str(value)

    @staticmethod
    def _next_datum_letter(existing_letters: set) -> Optional[str]:
        """`add_datum_feature`'s auto-lettering: the first unused letter in
        A-Z order, skipping `_GTOL_RESERVED_DATUM_LETTERS` (I, O, Q) --
        `None` if every non-reserved letter is already taken."""
        for letter in string.ascii_uppercase:
            if letter in _GTOL_RESERVED_DATUM_LETTERS:
                continue
            if letter not in existing_letters:
                return letter
        return None

    @staticmethod
    def _parse_gtol_datum_entry(entry: Any, index: int) -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
        """One `add_gtol`/`composite` `datums[i]` entry -> `(letter,
        modifier_token)` or an error message.

        Accepts a bare string letter (`"A"`) or an object
        `{"letter": "A", "modifier": "MMC"|"LMC"|"RFS"}`. The modifier token
        is returned ready to embed inline in the datum reference string
        (`"A<MOD-MMC>"`) -- per the GD&T section's own flagged Gotcha, the
        official worked example embeds `<MOD-MMC>`/`<MOD-LMC>` inline in
        `SetFrameValues2`'s Datum1/2/3 strings rather than via
        `SetFrameSymbols2`'s separate `DatumMC1..3` parameters, and this
        project follows that as the safe, officially-demonstrated pattern.
        """
        if isinstance(entry, str):
            letter, modifier = entry, None
        elif isinstance(entry, dict):
            letter, modifier = entry.get("letter"), entry.get("modifier")
        else:
            return None, f"datums[{index}] must be a string or an object, got {type(entry).__name__}"

        if not isinstance(letter, str) or not letter.strip():
            return None, f"datums[{index}] needs a non-empty datum letter"
        letter = letter.strip().upper()
        if len(letter) > 2:
            return None, f"datums[{index}] letter {letter!r} must be at most 2 characters"

        token = ""
        if modifier is not None:
            mod_key = modifier.strip().upper() if isinstance(modifier, str) else ""
            mod_token = _GTOL_MATERIAL_CONDITIONS.get(mod_key)
            if mod_token is None:
                return None, (
                    f"datums[{index}] modifier {modifier!r} must be one of "
                    f"{sorted(_GTOL_MATERIAL_CONDITIONS)!r}"
                )
            token = mod_token

        return (letter, token), None

    def _parse_gtol_datums(self, datums: Any, label: str) -> Tuple[Optional[List[Tuple[str, str]]], Optional[Dict]]:
        """`datums`/`composite["datums"]` -> a list of at most 3 `(letter,
        modifier_token)` pairs, or a `swInvalidInput` error dict. `label` is
        the caller-facing name of the field being parsed (`"datums"` or
        `"composite.datums"`), used in error messages."""
        datums = datums or []
        if not isinstance(datums, (list, tuple)):
            return None, self._result(
                False, f"{label} must be a list of datum references, got {type(datums).__name__}",
                SwErrors.swInvalidInput, {label: datums},
            )
        if len(datums) > 3:
            return None, self._result(
                False, f"{label} supports at most 3 references (primary/secondary/tertiary), "
                       f"got {len(datums)}",
                SwErrors.swInvalidInput, {label: datums},
            )

        parsed = []
        for i, entry in enumerate(datums):
            one, err = self._parse_gtol_datum_entry(entry, i)
            if err:
                return None, self._result(
                    False, f"{label}[{i}]: {err}", SwErrors.swInvalidInput, {label: datums},
                )
            parsed.append(one)
        return parsed, None

    def _validate_gtol_datum_requirement(self, symbol_key: str, datum_entries: List[Tuple[str, str]],
                                          label: str) -> Optional[Dict]:
        """Enforce ASME Y14.5's datum-reference rules for `symbol_key`: form
        tolerances (`_GTOL_FORM_SYMBOLS`) must NOT reference a datum;
        orientation/location/runout tolerances (`_GTOL_DATUM_REQUIRED_SYMBOLS`)
        must reference at least one. `label` names the field in the error
        message (`"symbol"` or `"composite"`)."""
        if symbol_key in _GTOL_FORM_SYMBOLS and datum_entries:
            return self._result(
                False,
                f"{symbol_key!r} is a form tolerance and cannot reference a datum "
                f"({label})",
                SwErrors.swInvalidInput, {"symbol": symbol_key, "datums": datum_entries},
            )
        if symbol_key in _GTOL_DATUM_REQUIRED_SYMBOLS and not datum_entries:
            return self._result(
                False,
                f"{symbol_key!r} requires at least one datum reference ({label})",
                SwErrors.swInvalidInput, {"symbol": symbol_key, "datums": datum_entries},
            )
        return None

    def _build_gtol_row(self, gcs: str, tolerance: float, datum_entries: List[Tuple[str, str]],
                         mc_key: Optional[str]) -> Dict[str, Any]:
        """Build one `SetFrameSymbols2`/`SetFrameValues2` frame row's content
        -- the "frame-content string" the task's Acceptance Criteria asks to
        be asserted byte-for-byte. `datum_entries` (already parsed via
        `_parse_gtol_datum_entry`) fill `datum1`/`datum2`/`datum3` in order;
        `mc_key` (`"MMC"`/`"LMC"`/`"RFS"`/`None`) becomes `tol_mc1`.
        """
        datum_strs = ["", "", ""]
        for i, (letter, token) in enumerate(datum_entries[:3]):
            datum_strs[i] = f"{letter}{token}"
        return {
            "gcs": gcs, "tol_dia1": False,
            "tol_mc1": _GTOL_MATERIAL_CONDITIONS.get(mc_key, "") if mc_key else "",
            "tol_dia2": False, "tol_mc2": "",
            "tol1": self._format_gtol_number(tolerance), "tol2": "",
            "datum1": datum_strs[0], "datum2": datum_strs[1], "datum3": datum_strs[2],
        }

    def _apply_gtol_frame(self, gtol_obj: Any, frame_number: int, row: Dict[str, Any]) -> Optional[Dict]:
        """`gtol_obj.SetFrameSymbols2(...)` then `.SetFrameValues2(...)` for
        one frame row -- shared by `add_gtol`'s primary frame (1) and its
        optional `composite` second row (2). Returns an error dict, or
        `None` on success."""
        try:
            args = SET_FRAME_SYMBOLS2.bind(
                units=self._units, frame_number=frame_number, gcs=row["gcs"],
                tol_dia1=row["tol_dia1"], tol_mc1=row["tol_mc1"],
                tol_dia2=row["tol_dia2"], tol_mc2=row["tol_mc2"],
                datum_mc1="", datum_mc2="", datum_mc3="",
            )
            gtol_obj.SetFrameSymbols2(*args)
        except Exception as e:
            logger.error(f"add_gtol: SetFrameSymbols2(frame {frame_number}) error: {e}")
            return self._result(False, f"Set frame {frame_number} symbols error: {e}", SwErrors.swFeatureError)

        try:
            status = gtol_obj.SetFrameValues2(
                frame_number, row["tol1"], row["tol2"], row["datum1"], row["datum2"], row["datum3"],
            )
        except Exception as e:
            logger.error(f"add_gtol: SetFrameValues2(frame {frame_number}) error: {e}")
            return self._result(False, f"Set frame {frame_number} values error: {e}", SwErrors.swFeatureError)
        if status is False:
            return self._result(
                False, f"Could not set frame {frame_number} values (SetFrameValues2 returned False)",
                SwErrors.swFeatureError,
            )
        return None

    def _iter_view_datum_tags(self, view: Any):
        """Walk every datum tag attached to `view` via `IView::
        GetFirstDatumTag` / `IDatumTag::GetNext` -- the datum-tag analog of
        `_iter_view_notes`'s `GetFirstNote`/`GetNext` walk (sw-1xx.3), per
        docs/api/03-annotations.md's sw-1xx.4 addendum."""
        try:
            tag = view.GetFirstDatumTag()
        except Exception as e:
            logger.warning(f"_iter_view_datum_tags: GetFirstDatumTag failed: {e}")
            tag = None
        while tag is not None:
            yield tag
            try:
                nxt = tag.GetNext()
            except Exception as e:
                logger.warning(f"_iter_view_datum_tags: GetNext failed: {e}")
                nxt = None
            tag = nxt if nxt else None

    def _describe_datum(self, tag: Any, view_name: Optional[str]) -> Dict:
        """`list_datums`'s per-tag description: label, position, and the
        view it was found on -- mirrors `_describe_note`'s shape."""
        try:
            annotation = tag.GetAnnotation()
        except Exception:
            annotation = None

        label = self._read_prop(tag, "GetLabel")
        name = self._read_prop(annotation, "GetName") if annotation is not None else None

        x = y = None
        position = self._read_prop(annotation, "GetPosition") if annotation is not None else None
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                x = self._units.from_meters(float(position[0]))
                y = self._units.from_meters(float(position[1]))
            except (TypeError, ValueError):
                x = y = None

        return {"label": label, "name": name, "x": x, "y": y, "view_name": view_name}

    def list_datums(self, sheet_name: Optional[str] = None) -> Dict:
        """
        Enumerate existing datum tags -- label, position, view -- via
        `IView::GetFirstDatumTag`/`IDatumTag::GetNext`, so `add_gtol`'s
        datum-letter validation and `add_datum_feature`'s auto-lettering have
        something to read.

        Args:
            sheet_name: Restrict to datum tags on this sheet's own real
                views (and its sheet-level pseudo-view). Omitted: every
                datum tag in the whole document.

        Returns:
            Result dict. `data["datums"]` is the per-tag list (see
            `_describe_datum`); `data["letters"]` is the sorted, deduplicated
            set of labels found, in uppercase -- what `add_gtol`/
            `add_datum_feature` compare candidate datum letters against.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        allowed_view_names = None
        if sheet_name:
            sheet, err = self._resolve_sheet(doc, sheet_name)
            if err:
                return err
            try:
                views_raw = sheet.GetViews() or []
            except Exception as e:
                logger.error(f"list_datums(sheet_name={sheet_name!r}) error: {e}")
                return self._result(False, f"List datums error: {e}", SwErrors.swUnknownError)
            allowed_view_names = {
                self._read_prop(v, "GetName2") for v in views_raw
                if self._read_prop(v, "GetName2")
            }

        sheet_type_code = int(SwDrawingViewTypes.swDrawingSheet)
        datums: List[Dict] = []
        for view in self._iter_document_views(doc):
            v_name = self._read_prop(view, "GetName2")
            type_code = self._read_prop(view, "Type")
            is_sheet_pseudo = (
                isinstance(type_code, (int, float)) and not isinstance(type_code, bool)
                and int(type_code) == sheet_type_code
            )
            include = True
            if allowed_view_names is not None:
                include = (v_name in allowed_view_names) or (is_sheet_pseudo and v_name == sheet_name)
            if include:
                datums.extend(self._describe_datum(t, v_name) for t in self._iter_view_datum_tags(view))

        letters = sorted({
            str(d["label"]).strip().upper() for d in datums
            if d.get("label") and str(d["label"]).strip()
        })
        return self._result(
            True, f"{len(datums)} datum tag(s)" + (f" on sheet {sheet_name!r}" if sheet_name else ""),
            SwErrors.swSuccess, {"sheet_name": sheet_name, "datums": datums, "letters": letters},
        )

    def add_datum_feature(self, view_name: str, entity: Dict[str, Any], label: Optional[str] = None,
                           x: float = None, y: float = None, style: Optional[str] = None) -> Dict:
        """
        Place a datum feature symbol (A, B, C...) on a selected edge/face/
        dimension via `IModelDoc2::InsertDatumTag2`.

        Args:
            view_name: Drawing view the entity lives in.
            entity: Entity reference in the shape `list_view_entities`
                returns (`{"kind": "edge"/"face"/"dimension"/"vertex", "x",
                "y", "z"}`).
            label: Datum letter, up to 2 characters (e.g. `"A"`). Omitted:
                auto-assigned as the next unused letter A-Z, reading existing
                datum tags via `list_datums`, skipping the reserved letters
                I, O, Q. Explicitly passing one of those three fails with
                `swInvalidInput` rather than silently accepting it.
            x, y: Datum symbol placement, caller's default unit -- converted
                to meters and applied via `IAnnotation::SetPosition2` after
                creation.
            style: Optional display style -- `"default"`, `"square"`, or
                `"round"` (`IDatumTag::SetDisplayStyle`'s `swDatumDisplayType_e`).
                Omitted: SolidWorks' own document default, no extra call made.

        Returns:
            Result dict. `data["label"]` is the letter actually assigned
            (whether given or auto-picked); `data["name"]` is
            `IAnnotation::GetName`'s value, read back best-effort.
        """
        parsed_entity, entity_err = _parse_entity_ref(entity)
        if entity_err:
            return self._result(
                False, f"entity: {entity_err}", SwErrors.swInvalidInput, {"entity": entity},
            )

        if x is None or y is None:
            return self._result(
                False, "x/y are required", SwErrors.swInvalidInput, {"x": x, "y": y},
            )
        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}", SwErrors.swInvalidInput,
            )

        style_key = None
        style_enum = None
        if style is not None:
            style_key = style.strip().lower() if isinstance(style, str) else ""
            style_enum = _DATUM_DISPLAY_STYLES.get(style_key)
            if style_enum is None:
                return self._result(
                    False,
                    f"Unknown style {style!r}; expected one of {sorted(_DATUM_DISPLAY_STYLES)!r}",
                    SwErrors.swInvalidInput, {"style": style},
                )

        label_final = None
        if label is not None:
            # Pure input-shape validation on an explicit `label` never needs
            # `list_datums`'s document walk -- validated (and, on failure,
            # rejected) before any COM call at all, same ordering
            # `_validate_note_geometry` uses. Only the omitted-`label`
            # auto-lettering path actually needs existing drawing state.
            if not isinstance(label, str) or not label.strip():
                return self._result(
                    False, f"label must be a non-empty string, got {label!r}",
                    SwErrors.swInvalidInput, {"label": label},
                )
            label_final = label.strip().upper()
            if len(label_final) > 2:
                return self._result(
                    False, f"label {label_final!r} must be at most 2 characters",
                    SwErrors.swInvalidInput, {"label": label_final},
                )
            if label_final in _GTOL_RESERVED_DATUM_LETTERS:
                return self._result(
                    False,
                    f"{label_final!r} is a reserved datum letter (I, O, Q are never assigned)",
                    SwErrors.swInvalidInput, {"label": label_final},
                )
        else:
            existing = self.list_datums()
            if not existing["success"]:
                return existing
            existing_letters = set(existing["data"]["letters"])
            label_final = self._next_datum_letter(existing_letters)
            if label_final is None:
                return self._result(
                    False, "No unused datum letters remain (A-Z minus reserved I/O/Q exhausted)",
                    SwErrors.swFeatureError, {"existing_datums": sorted(existing_letters)},
                )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "label": label_final, "x": x, "y": y, "style": style_key,
        }

        with self.selected("", type_str, ex, ey, ez) as sel:
            if not sel["success"]:
                return sel

            try:
                tag = doc.InsertDatumTag2()
            except Exception as e:
                logger.error(f"add_datum_feature({view_name!r}) InsertDatumTag2 error: {e}")
                return self._result(False, f"Insert datum tag error: {e}", SwErrors.swFeatureError, data)
            if tag is None:
                return self._result(
                    False, "InsertDatumTag2 returned nothing -- datum tag not created",
                    SwErrors.swFeatureError, data,
                )

            try:
                labeled = tag.SetLabel(label_final)
            except Exception as e:
                logger.error(f"add_datum_feature({view_name!r}) SetLabel error: {e}")
                return self._result(False, f"Set datum label error: {e}", SwErrors.swFeatureError, data)
            if labeled is False:
                return self._result(
                    False, f"Could not set datum label {label_final!r} (SetLabel returned False)",
                    SwErrors.swFeatureError, data,
                )

            if style_enum is not None:
                try:
                    styled = tag.SetDisplayStyle(False, int(style_enum))
                except Exception as e:
                    logger.error(f"add_datum_feature({view_name!r}) SetDisplayStyle error: {e}")
                    return self._result(
                        False, f"Set datum display style error: {e}", SwErrors.swFeatureError, data,
                    )
                if styled is False:
                    return self._result(
                        False, f"Could not set datum display style {style_key!r} "
                               "(SetDisplayStyle returned False)",
                        SwErrors.swFeatureError, data,
                    )

            try:
                annotation = tag.GetAnnotation()
            except Exception as e:
                logger.error(f"add_datum_feature({view_name!r}) GetAnnotation error: {e}")
                return self._result(False, f"Get datum annotation error: {e}", SwErrors.swFeatureError, data)
            if annotation is None:
                return self._result(
                    False, "Datum tag has no IAnnotation wrapper (GetAnnotation returned nothing) "
                    "-- cannot set position", SwErrors.swFeatureError, data,
                )

            try:
                x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
                positioned = annotation.SetPosition2(x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"add_datum_feature({view_name!r}) SetPosition2 error: {e}")
                return self._result(False, f"Set position error: {e}", SwErrors.swFeatureError, data)
            if positioned is False:
                return self._result(
                    False, "Could not set datum tag position (SetPosition2 returned False)",
                    SwErrors.swFeatureError, data,
                )

            data["name"] = self._read_prop(annotation, "GetName")

        return self._result(True, f"Added datum feature {label_final!r}", SwErrors.swSuccess, data)

    def add_gtol(self, view_name: str, entity: Dict[str, Any], symbol: str, tolerance: float,
                 datums: Optional[List[Any]] = None, x: Optional[float] = None,
                 y: Optional[float] = None, material_condition: Optional[str] = None,
                 projected_zone: Optional[float] = None, leader: bool = True,
                 composite: Optional[Dict[str, Any]] = None) -> Dict:
        """
        Add a geometric tolerance feature control frame via `IModelDoc2::
        InsertGtol` + `IGtol::SetFrameSymbols2`/`SetFrameValues2` (the
        SOLIDWORKS-pre-2022 "legacy" frame-content mechanism -- see
        docs/api/03-annotations.md's GD&T section for why: it's the only
        mechanism with a full official worked example, and this project's
        fake-COM test harness has no live document to probe which format
        `InsertGtol()` actually produces).

        Args:
            view_name: Drawing view the entity lives in.
            entity: Entity reference in the shape `list_view_entities`
                returns (`{"kind": "edge"/"face"/"dimension"/"vertex", "x",
                "y", "z"}`).
            symbol: One of the 14 geometric characteristics -- see
                `_GTOL_SYMBOLS` for the exact keys (`"position"`,
                `"flatness"`, `"perpendicularity"`, `"parallelism"`,
                `"concentricity"`, `"straightness"`, `"circularity"`,
                `"cylindricity"`, `"profile_of_a_line"`,
                `"profile_of_a_surface"`, `"angularity"`, `"symmetry"`,
                `"circular_runout"`, `"total_runout"`).
            tolerance: Tolerance zone value, a positive number in the
                caller's default unit -- formatted as GTol frame display text
                via `_format_gtol_number` (NOT converted to meters; see that
                method's own docstring).
            datums: Ordered list of up to 3 datum references (primary,
                secondary, tertiary), each either a bare letter string
                (`"A"`) or `{"letter": "A", "modifier": "MMC"|"LMC"|"RFS"}`.
                Form tolerances (`_GTOL_FORM_SYMBOLS`) must omit this;
                orientation/location/runout characteristics
                (`_GTOL_DATUM_REQUIRED_SYMBOLS`) require at least one entry.
                Every letter given must already exist on the drawing (see
                `list_datums`) -- validated before any COM call.
            x, y: Optional GTol placement, caller's default unit --
                converted to meters and applied via `IAnnotation::
                SetPosition2` after creation. Both-or-neither.
            material_condition: Optional `"MMC"`/`"LMC"`/`"RFS"` modifier on
                the tolerance value itself (`SetFrameSymbols2`'s `TolMC1`) --
                distinct from each datum's own per-reference modifier.
            projected_zone: Optional projected-tolerance-zone height, a
                positive number in the caller's default unit -- applied via
                `IGtol::SetPTZHeight2` (sw-1xx.4 dossier addendum) after the
                frame content is set.
            leader: `True` (default) selects `entity` before `InsertGtol()`
                so the GTol gets a leader attached to it, per the dossier's
                own documented `InsertGtol` selection-driven-leader behavior.
                `False` skips selection entirely, producing a freestanding
                GTol at the document origin (SolidWorks' own documented
                fallback for "no selection").
            composite: Optional second stacked frame row --
                `{"tolerance": ..., "datums": [...], "material_condition": ...}`
                (same shapes as the top-level params) -- written to frame 2
                of the same `IGtol` object via a second `SetFrameSymbols2`/
                `SetFrameValues2` call pair with an empty `gcs` (inheriting
                `symbol`'s characteristic visually, per the dossier
                addendum's documented convention for the analogous XML
                mechanism, applied here by analogy).

        Returns:
            Result dict. `data["frame"]`/`data["composite_frame"]` are the
            exact frame-content strings built and sent to COM (`gcs`,
            `tol_mc1`, `tol1`, `datum1`/`datum2`/`datum3`) -- what the task's
            Acceptance Criteria's byte-for-byte assertions check.
        """
        symbol_key = (symbol or "").strip().lower() if isinstance(symbol, str) else ""
        gtol_token = _GTOL_SYMBOLS.get(symbol_key)
        if gtol_token is None:
            return self._result(
                False, f"Unknown GD&T symbol {symbol!r}; expected one of {sorted(_GTOL_SYMBOLS)!r}",
                SwErrors.swInvalidInput, {"symbol": symbol},
            )

        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance <= 0:
            return self._result(
                False, f"tolerance must be a positive number, got {tolerance!r}",
                SwErrors.swInvalidInput, {"symbol": symbol_key, "tolerance": tolerance},
            )

        mc_key = None
        if material_condition is not None:
            mc_key = material_condition.strip().upper() if isinstance(material_condition, str) else ""
            if mc_key not in _GTOL_MATERIAL_CONDITIONS:
                return self._result(
                    False,
                    f"material_condition {material_condition!r} must be one of "
                    f"{sorted(_GTOL_MATERIAL_CONDITIONS)!r}",
                    SwErrors.swInvalidInput, {"material_condition": material_condition},
                )

        parsed_entity, entity_err = _parse_entity_ref(entity)
        if entity_err:
            return self._result(
                False, f"entity: {entity_err}", SwErrors.swInvalidInput, {"entity": entity},
            )

        datum_entries, err = self._parse_gtol_datums(datums, "datums")
        if err:
            return err
        req_err = self._validate_gtol_datum_requirement(symbol_key, datum_entries, "datums")
        if req_err:
            return req_err

        composite_tol = None
        composite_entries: List[Tuple[str, str]] = []
        composite_mc_key = None
        if composite is not None:
            if not isinstance(composite, dict):
                return self._result(
                    False, f"composite must be an object, got {type(composite).__name__}",
                    SwErrors.swInvalidInput, {"composite": composite},
                )
            composite_tol = composite.get("tolerance")
            if isinstance(composite_tol, bool) or not isinstance(composite_tol, (int, float)) \
                    or composite_tol <= 0:
                return self._result(
                    False, f"composite.tolerance must be a positive number, got {composite_tol!r}",
                    SwErrors.swInvalidInput, {"composite": composite},
                )
            composite_entries, err = self._parse_gtol_datums(composite.get("datums"), "composite.datums")
            if err:
                return err
            req_err = self._validate_gtol_datum_requirement(symbol_key, composite_entries, "composite")
            if req_err:
                return req_err

            composite_mc = composite.get("material_condition")
            if composite_mc is not None:
                composite_mc_key = composite_mc.strip().upper() if isinstance(composite_mc, str) else ""
                if composite_mc_key not in _GTOL_MATERIAL_CONDITIONS:
                    return self._result(
                        False,
                        f"composite.material_condition {composite_mc!r} must be one of "
                        f"{sorted(_GTOL_MATERIAL_CONDITIONS)!r}",
                        SwErrors.swInvalidInput, {"composite": composite},
                    )

        if (x is None) != (y is None):
            return self._result(
                False, "x/y must both be given or both omitted", SwErrors.swInvalidInput,
                {"x": x, "y": y},
            )
        if x is not None and (
            isinstance(x, bool) or isinstance(y, bool)
            or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
        ):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}", SwErrors.swInvalidInput,
            )

        if projected_zone is not None and (
            isinstance(projected_zone, bool) or not isinstance(projected_zone, (int, float))
            or projected_zone <= 0
        ):
            return self._result(
                False, f"projected_zone must be a positive number, got {projected_zone!r}",
                SwErrors.swInvalidInput, {"projected_zone": projected_zone},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        existing = self.list_datums()
        if not existing["success"]:
            return existing
        existing_letters = set(existing["data"]["letters"])

        requested_letters = {letter for letter, _ in datum_entries + composite_entries}
        missing = sorted(requested_letters - existing_letters)
        if missing:
            return self._result(
                False,
                f"Datum letter(s) {missing!r} not found on the drawing -- create them first "
                f"via add_datum_feature (existing: {sorted(existing_letters)!r})",
                SwErrors.swInvalidInput,
                {"missing_datums": missing, "existing_datums": sorted(existing_letters)},
            )

        row1 = self._build_gtol_row(f"<IGTOL-{gtol_token}>", tolerance, datum_entries, mc_key)
        row2 = None
        if composite is not None:
            row2 = self._build_gtol_row("", composite_tol, composite_entries, composite_mc_key)

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "symbol": symbol_key, "tolerance": tolerance,
            "material_condition": mc_key, "leader": bool(leader),
            "frame": row1, "composite_frame": row2,
        }

        def _create_gtol():
            try:
                gtol_obj = doc.InsertGtol()
            except Exception as e:
                logger.error(f"add_gtol({view_name!r}) InsertGtol error: {e}")
                return None, self._result(False, f"Insert GTol error: {e}", SwErrors.swFeatureError, data)
            if gtol_obj is None:
                return None, self._result(
                    False, "InsertGtol returned nothing -- GTol not created",
                    SwErrors.swFeatureError, data,
                )
            return gtol_obj, None

        if leader:
            with self.selected("", type_str, ex, ey, ez) as sel:
                if not sel["success"]:
                    return sel
                gtol_obj, create_err = _create_gtol()
                if create_err:
                    return create_err
        else:
            self.clear_selection()
            gtol_obj, create_err = _create_gtol()
            if create_err:
                return create_err

        frame_err = self._apply_gtol_frame(gtol_obj, 1, row1)
        if frame_err:
            frame_err["data"] = {**data, **frame_err.get("data", {})}
            return frame_err
        if row2 is not None:
            frame_err = self._apply_gtol_frame(gtol_obj, 2, row2)
            if frame_err:
                frame_err["data"] = {**data, **frame_err.get("data", {})}
                return frame_err

        if projected_zone is not None:
            try:
                ptz_ok = gtol_obj.SetPTZHeight2(1, 1, True, self._format_gtol_number(projected_zone))
            except Exception as e:
                logger.error(f"add_gtol({view_name!r}) SetPTZHeight2 error: {e}")
                return self._result(
                    False, f"Set projected tolerance zone error: {e}", SwErrors.swFeatureError, data,
                )
            if ptz_ok is False:
                return self._result(
                    False, "Could not set projected tolerance zone (SetPTZHeight2 returned False)",
                    SwErrors.swFeatureError, data,
                )

        try:
            annotation = gtol_obj.GetAnnotation()
        except Exception as e:
            logger.warning(f"add_gtol({view_name!r}) GetAnnotation error: {e}")
            annotation = None

        if x is not None:
            if annotation is None:
                return self._result(
                    False, "GTol has no IAnnotation wrapper (GetAnnotation returned nothing) "
                    "-- cannot set position", SwErrors.swFeatureError, data,
                )
            try:
                x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
                positioned = annotation.SetPosition2(x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"add_gtol({view_name!r}) SetPosition2 error: {e}")
                return self._result(False, f"Set position error: {e}", SwErrors.swFeatureError, data)
            if positioned is False:
                return self._result(
                    False, "Could not set GTol position (SetPosition2 returned False)",
                    SwErrors.swFeatureError, data,
                )

        data["name"] = self._read_prop(annotation, "GetName") if annotation is not None else None
        data["x"] = x
        data["y"] = y
        return self._result(
            True, f"Added {symbol_key} GTol" + (f" {data['name']!r}" if data["name"] else ""),
            SwErrors.swSuccess, data,
        )

    def add_datum_target(self, view_name: str, entity: Dict[str, Any], label: str, area_type: str,
                          size: float, x: float, y: float) -> Dict:
        """
        Add a datum target symbol via `IModelDocExtension::
        InsertDatumTargetSymbol3`.

        Args:
            view_name: Drawing view the entity lives in.
            entity: Entity reference in the shape `list_view_entities`
                returns -- a face is required per the dossier's own official
                worked example, but any `_ENTITY_KIND_TYPE_STR` kind is
                accepted here (SolidWorks itself rejects an unsupported
                selection type at the COM call).
            label: Datum target label (`InsertDatumTargetSymbol3`'s
                `Datum1`), e.g. `"a1"`.
            area_type: `"point"`, `"circle"`, or `"rectangle"`
                (`AreaStyle`).
            size: Target area diameter/width, a non-negative number in the
                caller's default unit -- converted to meters for `Value1`
                and formatted as display text for `ValueStr1` (via
                `_format_gtol_number`).
            x, y: Placement, caller's default unit -- converted to meters
                and applied via `IAnnotation::SetPosition2` after creation.

        Returns:
            Result dict. `data["name"]` is read back best-effort via
            `IAnnotation::GetName` (see the sw-1xx.4 dossier addendum's
            `IGtol::GetAnnotation` record -- `IDatumTargetSym` is assumed to
            follow the same pattern by analogy, unverified).
        """
        area_key = (area_type or "").strip().lower() if isinstance(area_type, str) else ""
        area_style = _DATUM_TARGET_AREA_TYPES.get(area_key)
        if area_style is None:
            return self._result(
                False,
                f"Unknown area_type {area_type!r}; expected one of "
                f"{sorted(_DATUM_TARGET_AREA_TYPES)!r}",
                SwErrors.swInvalidInput, {"area_type": area_type},
            )

        if not isinstance(label, str) or not label.strip():
            return self._result(
                False, f"label must be a non-empty string, got {label!r}",
                SwErrors.swInvalidInput, {"label": label},
            )

        parsed_entity, entity_err = _parse_entity_ref(entity)
        if entity_err:
            return self._result(
                False, f"entity: {entity_err}", SwErrors.swInvalidInput, {"entity": entity},
            )

        if isinstance(size, bool) or not isinstance(size, (int, float)) or size < 0:
            return self._result(
                False, f"size must be a non-negative number, got {size!r}",
                SwErrors.swInvalidInput, {"size": size},
            )
        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}", SwErrors.swInvalidInput,
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "label": label, "area_type": area_key, "size": size,
            "x": x, "y": y,
        }

        with self.selected("", type_str, ex, ey, ez) as sel:
            if not sel["success"]:
                return sel

            try:
                args = INSERT_DATUM_TARGET_SYMBOL3.bind(
                    units=self._units, datum1=label, datum2="", datum3="",
                    area_style=area_style, area_outside=False,
                    value1=size, value2=0.0,
                    value_str1=self._format_gtol_number(size), value_str2="",
                    arrows_smart=True, arrow_style=0, leader_line_style=0,
                    leader_bent=False, show_area=True, show_symbol=True,
                    moveable_datum_style=0,
                )
                created = doc.Extension.InsertDatumTargetSymbol3(*args)
            except Exception as e:
                logger.error(f"add_datum_target({view_name!r}) InsertDatumTargetSymbol3 error: {e}")
                return self._result(
                    False, f"Insert datum target error: {e}", SwErrors.swFeatureError, data,
                )
            if created is None:
                return self._result(
                    False, "InsertDatumTargetSymbol3 returned nothing -- datum target not created",
                    SwErrors.swFeatureError, data,
                )

            try:
                annotation = created.GetAnnotation()
            except Exception as e:
                logger.warning(f"add_datum_target({view_name!r}) GetAnnotation error: {e}")
                annotation = None

            if annotation is None:
                return self._result(
                    False, "Datum target has no IAnnotation wrapper (GetAnnotation returned nothing) "
                    "-- cannot set position", SwErrors.swFeatureError, data,
                )

            try:
                x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
                positioned = annotation.SetPosition2(x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"add_datum_target({view_name!r}) SetPosition2 error: {e}")
                return self._result(False, f"Set position error: {e}", SwErrors.swFeatureError, data)
            if positioned is False:
                return self._result(
                    False, "Could not set datum target position (SetPosition2 returned False)",
                    SwErrors.swFeatureError, data,
                )

            data["name"] = self._read_prop(annotation, "GetName")

        return self._result(True, f"Added datum target {label!r}", SwErrors.swSuccess, data)
