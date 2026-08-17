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
    SwArrowStyle,
    SwAutodimEntities,
    SwAutodimHorizontalPlacement,
    SwAutodimScheme,
    SwAutodimStatus,
    SwAutodimVerticalPlacement,
    SwBOMConfigurationAnchorType,
    SwBomType,
    SwBreakLineOrientation,
    SwBreakLineStyle,
    SwCenterMarkConnectionLine,
    SwCenterMarkStyle,
    SwCommands,
    SwCreateOrdDimError,
    SwCreateSectionViewAtOptions,
    SwCropViewErrors,
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
    SwNumberingType,
    SwRenameOptions,
    SwSaveAsOptions,
    SwSaveAsVersion,
    SwSetValueInConfiguration,
    SwSetValueReturnStatus,
    SwSFLaySym,
    SwSFSymType,
    SwTableAnnotationType,
    SwUserPreferenceIntegerValue,
    SwUserPreferenceStringListValue,
    SwUserPreferenceToggle,
    SwViewAlignment,
    SwWeldSymbolContourTypes,
    SwWeldSymbolField,
    SwWeldSymbolSymmetric,
    decode_save_error,
)
from .selection import _VIEW_ENTITY_TYPES
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


def _resolve_paper_size_code(paper_size: Any) -> Tuple[Optional[int], Optional[str]]:
    """`swDwgPaperSizes_e` code for one of this tool layer's short paper-size
    names (`"A"`-`"E"`, `"A0"`-`"A4"`, case-insensitive), or
    `swDwgPapersUserDefined` for `"custom"`.

    Returns `(code, None)`, or `(None, message)` for an unrecognized name.
    Shared by `add_sheet` and `set_sheet_properties`, which accept exactly
    this spelling -- keeping one copy of the accepted set and of the
    valid-values message they report on a miss.

    `new_drawing_from_template` deliberately does *not* route through here:
    it takes a separate `orientation` argument, so it needs the full
    `(landscape, portrait)` tuple, and it has no `"custom"` spelling to
    offer in its own error message.
    """
    key = str(paper_size or "").strip().upper()
    if key == "CUSTOM":
        return int(SwDwgPaperSizes.swDwgPapersUserDefined), None
    sizes = _PAPER_SIZES.get(key)
    if sizes is None:
        valid = sorted(_PAPER_SIZES) + ["custom"]
        return None, f"Unknown paper_size {paper_size!r}; expected one of {valid!r}"
    return int(sizes[0]), None


def _template_in_name(code: Any) -> Optional[str]:
    """Readable `SwDwgTemplates` member name for a `templateIn` code read
    back off `ISheet::GetProperties2` (index 1) -- e.g. `"swDwgTemplateNone"`
    or `"swDwgTemplateCustom"`, or `f"unknown template {code!r}"` for
    anything unrecognized. `None` only when `code` itself couldn't be read.

    Deliberately not routed through `_enum_name`: that helper's fallback
    reads `"unknown status ..."`, which is the wrong noun for a
    `templateIn` code.
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


def _parse_sheet_properties(props: Any) -> Optional[Dict[str, Any]]:
    """The one parser for `ISheet::GetProperties2`'s documented 8-element
    `Double` array -- `{paper_size_code, template_in_code, scale_num,
    scale_denom, first_angle, width_m, height_m}`, with `width_m`/`height_m`
    still in COM's meters (callers convert).

    Returns `None` for anything that isn't that array -- `None`, a
    short/empty sequence, a non-sequence auto-vivified COM stand-in, or a
    sequence whose elements aren't the numbers they're documented to be.
    Every consumer of this array (`_sheet_properties`' rendered view and
    `_read_sheet_setup_state`' raw one) goes through here, so the index
    mapping and the defensiveness live in exactly one place.
    """
    if not isinstance(props, (list, tuple)) or len(props) < 7:
        return None
    try:
        return {
            "paper_size_code": int(props[0]),
            "template_in_code": int(props[1]),
            "scale_num": float(props[2]),
            "scale_denom": float(props[3]),
            "first_angle": bool(props[4]),
            "width_m": float(props[5]),
            "height_m": float(props[6]),
        }
    except (TypeError, ValueError):
        return None


def _projection_name(first_angle: Any) -> str:
    """`swDrawingProjectionType_e` member name for `GetProperties2`'s
    `firstAngle` flag -- the rendering `list_sheets`/`get_active_sheet`/
    `get_sheet_properties` all report as `projection`."""
    return (
        SwDrawingProjectionType.swDrawing1stAngleProjection.name if first_angle
        else SwDrawingProjectionType.swDrawing3rdAngleProjection.name
    )


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
    numeric/Boolean duality `_iter_real_views` guards against for
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


def _com_int(value: Any) -> Optional[int]:
    """Coerce a COM-returned numeric value to a real `int`, or `None` when it
    carries no usable number -- the integer counterpart of `_com_bool`.

    Every COM enum code this file reads back (`IView::Type`,
    `IView::GetAlignment`, `swCropViewErrors_e`, ...) arrives as an `int`
    through some interop layers and a `float` through others, and a failed
    `_read_prop` yields `None`. A bare `isinstance(value, (int, float))`
    test would also accept `True`/`False`, since `bool` subclasses `int` --
    and an auto-vivified fake-COM member or a stray Boolean must not be
    mistaken for enum code `1`. Rejecting `bool` explicitly is the guard
    that was previously re-typed at every numeric COM read in this module.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
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

# `insert_break_view`'s `orientation` -> `swBreakLineOrientation_e`, per
# docs/api/02-views.md's `IView::InsertBreak3` and `swBreakLineOrientation_e`
# records (requested as `swBreakDir_e`, which does not exist).
_BREAK_LINE_ORIENTATION = {
    "vertical": int(SwBreakLineOrientation.swBreakLineVertical),
    "horizontal": int(SwBreakLineOrientation.swBreakLineHorizontal),
}

# `insert_break_view`'s `style` -> `swBreakLineStyle_e`'s `Style` parameter,
# per docs/api/02-views.md's `IView::InsertBreak3` and `swBreakLineStyle_e`
# records. `"zigzag"` is this tool's own default, matching the task's
# Requirements.
_BREAK_LINE_STYLE = {
    "straight": int(SwBreakLineStyle.swBreakLine_Straight),
    "zigzag": int(SwBreakLineStyle.swBreakLine_ZigZag),
    "curve": int(SwBreakLineStyle.swBreakLine_Curve),
    "small_zigzag": int(SwBreakLineStyle.swBreakLine_SmallZigZag),
    "jagged": int(SwBreakLineStyle.swBreakLine_Jagged),
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

# `add_surface_finish`'s `symbol_type` -> `InsertSurfaceFinishSymbol3`'s `SymType`
# (`swSFSymType_e`). Only the 3 non-JIS characteristics the task's Requirements name
# ("basic / machining required / machining prohibited") are exposed; the JIS
# variants exist in the enum but have no requested public key.
_SF_SYMBOL_TYPES = {
    "basic": int(SwSFSymType.swSFBasic),
    "machining_required": int(SwSFSymType.swSFMachining_Req),
    "machining_prohibited": int(SwSFSymType.swSFDont_Machine),
}

# `add_surface_finish`'s `lay_direction` -> `InsertSurfaceFinishSymbol3`'s
# `LaySymbol` (`swSFLaySym_e`). Omitted `lay_direction` binds `LaySymbol`'s own
# default (`swSFNone` -- no lay symbol), same as the explicit `"none"` key here.
_SF_LAY_DIRECTIONS = {
    "none": int(SwSFLaySym.swSFNone),
    "circular": int(SwSFLaySym.swSFCircular),
    "cross": int(SwSFLaySym.swSFCross),
    "multi_directional": int(SwSFLaySym.swSFMultiDir),
    "parallel": int(SwSFLaySym.swSFParallel),
    "perpendicular": int(SwSFLaySym.swSFPerp),
    "radial": int(SwSFLaySym.swSFRadial),
    "particulate": int(SwSFLaySym.swSFParticulate),
}

# `IModelDocExtension::InsertSurfaceFinishSymbol3`'s positional signature, in the
# exact order documented in docs/api/03-annotations.md: SymType, LeaderType, LocX,
# LocY, LocZ, LaySymbol, ArrowType, MachAllowance, OtherVals, ProdMethod, SampleLen,
# MaxRoughness, MinRoughness, RoughnessSpacing. 14 positional parameters --
# ComSignature per this issue's working agreement (>6 params). `add_surface_finish`
# always binds `leader_type=swSTRAIGHT` (never `swNO_LEADER`) since the tool's own
# `x`/`y` are required parameters that the dossier's own Gotchas say are silently
# ignored under `swNO_LEADER`; `arrow_type` (cosmetic, not in this task's
# Requirements) always binds its own `swOPEN_ARROWHEAD` default. `sample_len`/
# `other_vals` aren't exposed as public parameters either (not in this task's
# Requirements) and always bind `""`.
INSERT_SURFACE_FINISH_SYMBOL3 = ComSignature("InsertSurfaceFinishSymbol3", [
    Param("sym_type", REQUIRED, enum_to_int),
    Param("leader_type", int(SwLeaderStyle.swSTRAIGHT), enum_to_int),
    Param("loc_x", 0.0, to_meters),
    Param("loc_y", 0.0, to_meters),
    Param("loc_z", 0.0, to_meters),
    Param("lay_symbol", 0, enum_to_int),
    Param("arrow_type", int(SwArrowStyle.swOPEN_ARROWHEAD), enum_to_int),
    Param("mach_allowance", ""),
    Param("other_vals", ""),
    Param("prod_method", ""),
    Param("sample_len", ""),
    Param("max_roughness", ""),
    Param("min_roughness", ""),
    Param("roughness_spacing", ""),
])

# `add_weld_symbol`'s `symbol`/`other_side_symbol` -> `IWeldSymbol::SetText`'s
# `Symbol` parameter -- the fixed 16-member ISO code list documented in
# docs/api/03-annotations.md's "Surface finish and weld symbols" section Gotchas.
# Friendly aliases are given only for the 10 codes this dossier's sw-1xx.5 addendum
# corroborates with reasonable confidence; the raw code (case-insensitive) is always
# accepted too, including the 5 codes with no corroborated friendly name
# (`BUSVBR`, `BUSBR`, `SEAMC`, `JSPT`, `JSM`) -- see that addendum's "Weld symbol
# name-code semantics" record for why those aren't guessed.
_WELD_SYMBOL_CODES = {
    "BUTT", "BUSQ", "BUSV", "BUSB", "BUSVBR", "BUSBR", "BUSU", "BUSJ",
    "BACK", "FILL", "PLUG", "SPOT", "SEAM", "SEAMC", "JSPT", "JSM",
}
_WELD_SYMBOL_ALIASES = {
    "fillet": "FILL",
    "plug": "PLUG",
    "slot": "PLUG",
    "spot": "SPOT",
    "seam": "SEAM",
    "backing": "BACK",
    "butt": "BUTT",
    "square_groove": "BUSQ",
    "v_groove": "BUSV",
    "bevel_groove": "BUSB",
    "u_groove": "BUSU",
    "j_groove": "BUSJ",
}

# `add_weld_symbol`'s `contour` -> `IWeldSymbol::SetText`'s `Contour` parameter
# (`swWeldSymbolContourTypes_e`). Omitted `contour` binds `"none"`
# (`swWeldContourNone`), the same value `Contour` gets in the dossier's own official
# worked example.
_WELD_CONTOURS = {
    "none": int(SwWeldSymbolContourTypes.swWeldContourNone),
    "flat": int(SwWeldSymbolContourTypes.swWeldContourFlat),
    "convex": int(SwWeldSymbolContourTypes.swWeldContourConvex),
    "concave": int(SwWeldSymbolContourTypes.swWeldContourConcave),
}

# `add_center_marks`' `style` -> `IDrawingDoc::InsertCenterMark3`'s `Style`
# parameter (`swCenterMarkStyle_e`), per docs/api/03-annotations.md's
# `InsertCenterMark3` record.
_CENTER_MARK_STYLES = {
    "non_annotation": int(SwCenterMarkStyle.swCenterMark_NonAnnotation),
    "single": int(SwCenterMarkStyle.swCenterMark_Single),
    "linear_group": int(SwCenterMarkStyle.swCenterMark_LinearGroup),
    "circular_group": int(SwCenterMarkStyle.swCenterMark_CircularGroup),
}

# `add_center_marks`' `connection_lines` boolean -> `ICenterMark::
# ConnectionLines` (`swCenterMarkConnectionLine_e`) -- this project's own
# convention, since the enum exposes four independent line-type bits and no
# SolidWorks source documents a bool->bitmask mapping. See the sw-1xx.6
# dossier addendum's `ICenterMark::ConnectionLines` record Gotchas.
_CENTER_MARK_CONNECTION_LINES = {
    False: int(SwCenterMarkConnectionLine.swCenterMark_ShowNoConnectLines),
    True: int(SwCenterMarkConnectionLine.swCenterMark_ShowCircularConnectLines),
}


def _resolve_weld_symbol(value: Any, label: str) -> Tuple[Optional[str], Optional[str]]:
    """One `add_weld_symbol` `symbol`/`other_side_symbol` value -> its ISO code
    (`_WELD_SYMBOL_CODES` member) or an error message -- exactly one of the two
    return slots is populated. Accepts a friendly `_WELD_SYMBOL_ALIASES` key
    (case-insensitive) or a raw ISO code (case-insensitive)."""
    if not isinstance(value, str) or not value.strip():
        return None, f"{label} must be a non-empty string, got {value!r}"
    raw = value.strip()
    alias = _WELD_SYMBOL_ALIASES.get(raw.lower())
    if alias is not None:
        return alias, None
    code = raw.upper()
    if code in _WELD_SYMBOL_CODES:
        return code, None
    return None, (
        f"unknown {label} {value!r}; expected one of {sorted(_WELD_SYMBOL_ALIASES)!r} "
        f"or a raw ISO code {sorted(_WELD_SYMBOL_CODES)!r}"
    )


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


# `insert_bom_table`'s `bom_type` -> `IView::InsertBomTable6`'s `BomType`
# (`swBomType_e`). Only the 3 types this task's Requirements name
# ("top-level-only / parts-only / indented") are exposed -- `swBomType_Flattened`
# exists in the enum (docs/api/04-tables.md's Enums section) but has no
# requested public key.
_BOM_TYPES = {
    "top_level": int(SwBomType.swBomType_TopLevelOnly),
    "parts_only": int(SwBomType.swBomType_PartsOnly),
    "indented": int(SwBomType.swBomType_Indented),
}

# `insert_bom_table`'s `anchor` -> the shared `swBOMConfigurationAnchorType_e`
# every table type in this dossier's Enums section uses for `AnchorType`, not
# just BOM -- kept generically named (not `_BOM_ANCHOR_TYPES`) so a sibling
# hole/revision/weldment table tool (sw-mio.2/.3/.4) can reuse this dict
# rather than redeclaring it.
_TABLE_ANCHOR_TYPES = {
    "top_left": int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft),
    "top_right": int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopRight),
    "bottom_left": int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_BottomLeft),
    "bottom_right": int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_BottomRight),
}

# `IView::InsertBomTable6`'s positional signature, in the exact order
# documented in docs/api/04-tables.md: UseAnchorPoint, X, Y, AnchorType,
# BomType, Configuration, TableTemplate, Hidden, IndentedNumberingType,
# DetailedCutList, DissolvePartLevelRows, DisplayAsOneItem. 12 positional
# parameters -- ComSignature per this issue's working agreement (>6 params).
# `Hidden` always binds `False` (an *insert* tool has no reason to create a
# hidden table) and `DisplayAsOneItem` always binds `False` -- neither is in
# this task's Requirements as a public parameter.
INSERT_BOM_TABLE6 = ComSignature("InsertBomTable6", [
    Param("use_anchor_point", REQUIRED, to_bool),
    Param("x", 0.0, to_meters),
    Param("y", 0.0, to_meters),
    Param("anchor_type", REQUIRED, enum_to_int),
    Param("bom_type", REQUIRED, enum_to_int),
    Param("configuration", ""),
    Param("table_template", REQUIRED),
    Param("hidden", False, to_bool),
    Param("indented_numbering_type", int(SwNumberingType.swNumberingType_None), enum_to_int),
    Param("detailed_cut_list", False, to_bool),
    Param("dissolve_part_level_rows", False, to_bool),
    Param("display_as_one_item", False, to_bool),
])


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
            current_name = self._sheet_name(current_sheet) if current_sheet else None
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
                original_name = self._sheet_name(current_sheet)
        except Exception as e:
            logger.error(f"read active sheet for restore error: {e}")

        try:
            yield
        finally:
            if original_name:
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

        is_custom = (paper_size or "").strip().upper() == "CUSTOM"

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
            paper_size_value, size_err = _resolve_paper_size_code(paper_size)
            if size_err:
                return self._result(False, size_err, SwErrors.swInvalidInput)

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
            # A failed name read here is reported as "no sheets available"
            # rather than surfaced: `ActivateSheet` already told us the real
            # failure, and `_sheet_names`' own error would replace it.
            available, _ = self._sheet_names(doc, "activate_sheet")
            return self._sheet_not_found(name, available)

        return self._result(True, f"Activated sheet {name!r}", SwErrors.swSuccess, {"name": name})

    def _sheet_names(self, doc: Any, context: str) -> Tuple[List[str], Optional[Dict]]:
        """`IDrawingDoc::GetSheetNames`, normalized (`_normalize_sheet_names`)
        and with the COM-failure branch reported rather than swallowed --
        the single read every sheet-management tool goes through.

        Returns `(names, None)`, or `([], error)` with `context` naming the
        operation that wanted them (e.g. `"copy_sheet"`), so the "could not
        read sheet names" failure has one shape across all of them.
        """
        try:
            return _normalize_sheet_names(doc.GetSheetNames()), None
        except Exception as e:
            logger.error(f"{context} error: {e}")
            return [], self._result(
                False, f"Could not read sheet names: {e}", SwErrors.swUnknownError)

    def _sheet_not_found(self, name: str, available: List[str]) -> Dict:
        """The one "no such sheet" result: `swInvalidInput`, the message
        listing what does exist, and `{"name", "available_sheets"}` in
        `data` -- shared by `activate_sheet`, `_resolve_named_sheet`,
        `copy_sheet`, `delete_sheet`, and `rename_sheet` so a caller can
        handle the case uniformly whichever tool raised it."""
        return self._result(
            False,
            f"Sheet {name!r} not found; available sheets: {available!r}",
            SwErrors.swInvalidInput,
            {"name": name, "available_sheets": available},
        )

    def _sheet_properties(self, sheet: Any) -> Dict[str, Any]:
        """`ISheet::GetProperties2` -> `{scale_num, scale_denom,
        paper_size_code, paper_size, projection, width, height}`, shared by
        `list_sheets` and `get_active_sheet`.

        A rendered view over `_parse_sheet_properties` (the shared array
        parser): paper-size code and first-angle flag become readable names,
        dimensions become the caller's unit. Every field comes back `None`
        rather than raising whenever that parse fails, so a sheet whose
        properties can't be read still shows up in `list_sheets`' results
        instead of the whole call raising out of the tool (this project's
        own "never raise out of a tool" rule).
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

        parsed = _parse_sheet_properties(props)
        if parsed is None:
            return empty

        return {
            "scale_num": parsed["scale_num"],
            "scale_denom": parsed["scale_denom"],
            "paper_size_code": parsed["paper_size_code"],
            "paper_size": _paper_size_name(parsed["paper_size_code"]),
            "projection": _projection_name(parsed["first_angle"]),
            "width": self._units.from_meters(parsed["width_m"]),
            "height": self._units.from_meters(parsed["height_m"]),
        }

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

        names, err = self._sheet_names(doc, "list_sheets")
        if err:
            return err

        sheets = []
        for sheet_name in names:
            try:
                sheet = doc.Sheet(sheet_name)
            except Exception:
                sheet = None
            # No special case for an unresolvable `sheet`: `_sheet_properties`
            # already answers all-`None` and `_sheet_view_names` an empty list
            # when the COM reads on it fail, which is exactly what such a
            # sheet should report.
            sheets.append({
                "name": sheet_name,
                **self._sheet_properties(sheet),
                "view_count": sum(1 for _ in self._iter_real_views(sheet)),
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

        name = self._sheet_name(sheet)
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
                available, _ = self._sheet_names(doc, "resolve sheet")
                return None, None, self._sheet_not_found(sheet_name, available)
            return sheet, sheet_name, None

        try:
            sheet = doc.GetCurrentSheet()
        except Exception as e:
            logger.error(f"resolve sheet error: {e}")
            return None, None, self._result(
                False, f"Resolve sheet error: {e}", SwErrors.swUnknownError)
        if not sheet:
            return None, None, self._result(False, "No active sheet", SwErrors.swFeatureError)
        return sheet, self._sheet_name(sheet), None

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
        `GetProperties2` array (`_parse_sheet_properties`, the same parser
        `_sheet_properties` renders from) -- `None` rather than an all-`None`
        dict, since callers here need to distinguish "couldn't read current
        state" (an error) from "read it, every field happened to be None".
        """
        try:
            props = sheet.GetProperties2()
        except Exception:
            return None
        parsed = _parse_sheet_properties(props)
        if parsed is None:
            return None

        try:
            template_path = sheet.GetTemplateName()
        except Exception:
            template_path = None
        if not template_path or template_path == "*.drt":
            template_path = None

        return {
            "paper_size_code": parsed["paper_size_code"],
            "template_in_code": parsed["template_in_code"],
            "scale_num": parsed["scale_num"],
            "scale_denom": parsed["scale_denom"],
            "first_angle": parsed["first_angle"],
            "width": self._units.from_meters(parsed["width_m"]),
            "height": self._units.from_meters(parsed["height_m"]),
            "template_path": template_path,
        }

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
                keeps the sheet's current scale. Either given as `0` fails
                with `swInvalidInput` without touching COM -- a `0`
                numerator is as degenerate a sheet scale as a `0`
                denominator, and `SetupSheet5` reports neither.
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
        if scale_num is not None and scale_num == 0:
            return self._result(
                False, "scale_num must be nonzero", SwErrors.swInvalidInput)
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
            effective_paper_size, size_err = _resolve_paper_size_code(paper_size)
            if size_err:
                return self._result(False, size_err, SwErrors.swInvalidInput)
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
            # succeeded, so a rebuild failure here doesn't fail the call. Its
            # Boolean return is logged rather than discarded, though: a
            # `False` there means the views still show the old projection, and
            # silently dropping it is the same discarded-COM-status defect the
            # sw-ja0 review pass fixed on the export paths.
            try:
                rebuilt = doc.ForceRebuild3(False)
            except Exception as e:
                logger.warning(f"set_sheet_properties: post-update rebuild failed: {e}")
            else:
                if not rebuilt:
                    logger.warning(
                        f"set_sheet_properties: ForceRebuild3 returned false after the "
                        f"projection change on sheet {name!r} -- the drawing views may "
                        "still show the previous projection until it is rebuilt")

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
            "projection": _projection_name(current["first_angle"]),
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
                `swInvalidInput` before any COM call. The rename itself is
                delegated to `rename_sheet`, which owns the `SetName`
                no-failure-signal protocol.
            count: Number of copies to create. Must be a positive integer.

        Returns:
            Result dict. `data["created"]` lists the new sheet name(s), in
            creation order; `data["sheets"]` is the sheet list as of the
            last read (the final copy's, or `rename_sheet`'s own post-rename
            read). Fails with `swInvalidInput` if `source_sheet` doesn't
            exist, `new_name` already exists, or `count`/`new_name` are
            combined invalidly -- none of these make any COM call. Fails
            with `swFeatureError` if `PasteSheet` itself returns `False`, or
            if the sheet count doesn't actually increase by one after a
            `PasteSheet` that returned `True`. A rename failure propagates
            `rename_sheet`'s own error code, with `data["created"]` still
            reporting the copy that did succeed.
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

        before_names, err = self._sheet_names(doc, "copy_sheet")
        if err:
            return err

        if source_sheet not in before_names:
            return self._sheet_not_found(source_sheet, before_names)
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
        after_names = before_names

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

        # The last iteration's re-read is already the current sheet list --
        # nothing has touched the document since. Only the rename path below
        # needs a fresh one, and `rename_sheet` takes its own.
        final_names = after_names

        if new_name is not None:
            # Delegate rather than re-implement: `rename_sheet` already owns
            # the `ISheet::SetName` protocol (a bare Sub with no return
            # value/failure signal, per docs/api/01-documents-and-sheets.md's
            # SetName record -- so it re-reads GetSheetNames afterward to
            # confirm the rename actually took). Its pre-flight collision
            # check is redundant with this method's own at the top, which is
            # deliberate: that one fails before any COM call at all.
            [only] = created
            renamed = self.rename_sheet(only, new_name)
            if not renamed["success"]:
                return self._result(
                    False, f"Created {only!r} but rename to {new_name!r} failed: "
                    f"{renamed['message']}",
                    SwErrors(renamed["error_code"]),
                    {"created": created, **renamed.get("data", {})},
                )
            created = [new_name]
            final_names = renamed.get("data", {}).get("sheets", final_names)

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
            `DeleteSelection2` itself returns `False`, or if it returns
            `True` but `name` is still in the re-read sheet list afterward.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        before_names, err = self._sheet_names(doc, "delete_sheet")
        if err:
            return err

        if name not in before_names:
            return self._sheet_not_found(name, before_names)
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

        # Same "never guess what happened" check `copy_sheet` and
        # `rename_sheet` already apply to their own re-reads: this list was
        # fetched anyway, so confirm the sheet is really gone rather than
        # trusting DeleteSelection2's Boolean alone. It can report success
        # having deleted something else -- SelectByID2 resolves by name, and
        # nothing guarantees the "SHEET" selection landed on this sheet.
        if name in after_names:
            return self._result(
                False,
                f"DeleteSelection2 reported success, but {name!r} still appears in "
                f"the sheet list afterward: {after_names!r}",
                SwErrors.swFeatureError, {"name": name, "sheets": after_names},
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

        before_names, err = self._sheet_names(doc, "rename_sheet")
        if err:
            return err

        if old_name not in before_names:
            return self._sheet_not_found(old_name, before_names)
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
            return self._sheet_not_found(old_name, before_names)

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

    def _sheet_name(self, sheet: Any) -> Optional[str]:
        """An `ISheet`'s own name -- `ISheet::GetName` first, falling back to
        the `Name` property, and `None` (never raising) if neither answers a
        non-empty string.

        `GetName` is deliberately first. docs/api/01-documents-and-sheets.md's
        `ISheet::SetName` record fetched the real `ISheet` member index and
        found `GetName`/`SetName` -- and *no* bare `Name` property -- so this
        file's original `_read_prop(sheet, "Name")` (inferred in
        docs/api/02-views.md from a third-party Java type-library mirror, and
        flagged there as unverified) would read `None` off a real interop
        layer. That silently turned `get_active_sheet` into a nameless result
        and made `set_sheet_properties`/`set_sheet_scale`/`get_sheet_properties`
        fail outright in their no-`sheet_name` default mode -- invisible in
        tests, because the fake harness auto-vivified a truthy stand-in for
        any unscripted member. `FakeSldWorks` now pre-scripts the current
        sheet's `ISheet::GetName` to a real string instead, so the harness
        models the interface the member index actually documents.

        The `Name` fallback is kept rather than dropped: it costs one failed
        read, and it keeps working against any interop layer that really does
        expose the property (the source of the original inference). Both reads
        go through `_read_prop`, so either spelling may be a property or a
        zero-arg method. Only a non-empty `str` counts as an answer -- against
        the fake harness an unscripted `GetName` auto-vivifies to a truthy
        stand-in, and accepting that would shadow a scripted `Name`.
        """
        for member in ("GetName", "Name"):
            value = self._read_prop(sheet, member)
            if isinstance(value, str) and value:
                return value
        return None

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
            activate_err = self._activate_sheet_or_error(
                doc, sheet_name, "insert_model_view")
            if activate_err:
                return activate_err

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
        (docs/api/02-views.md's Gotchas on both records). `auto_scale` is
        therefore written through this file's own `_user_preference` context
        manager, which snapshots the preference on entry and restores exactly
        the value it read on exit -- on the success, early-return, and
        exception paths alike -- so the operator's SolidWorks install setting
        is never silently left changed by an automation run.

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

        data = {"model_path": model_path, "first_angle": first_angle, "auto_scale": auto_scale}
        try:
            with self._user_preference(
                    SwUserPreferenceToggle.swAutomaticScaling3ViewDrawings, auto_scale):
                try:
                    if first_angle:
                        created = doc.Create1stAngleViews2(model_path)
                    else:
                        created = doc.Create3rdAngleViews2(model_path)
                except Exception as e:
                    logger.error(f"insert_standard_3_view error: {e}")
                    return self._result(False, f"Insert standard 3 view error: {e}",
                                        SwErrors.swFeatureError, data)
        except _PreferenceError as e:
            logger.error(f"insert_standard_3_view preference error: {e}")
            return self._result(False, str(e), SwErrors.swUnknownError)

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

        type_code = self._read_view_type(view)
        type_name = None
        if type_code is not None:
            try:
                type_name = SwDrawingViewTypes(type_code).name
            except ValueError:
                type_name = f"unknown type {type_code}"

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

        base_view = self._base_view(view)

        return {
            "name": name,
            "type": type_name,
            "type_code": type_code,
            "scale": scale,
            "x": x,
            "y": y,
            "referenced_model": self._view_referenced_model(view, base_view),
            "parent_view": self._read_prop(base_view, "GetName2") if base_view else None,
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

        sheet, sheet_err = self._resolve_sheet(doc, sheet_name)
        if sheet_err:
            return sheet_err
        if not sheet_name:
            sheet_name = self._sheet_name(sheet)

        views_raw, views_err = self._sheet_views_or_error(sheet, "list_views")
        if views_err:
            return views_err

        # The sheet's own pseudo-view entry is filtered out before being
        # described (`_is_sheet_pseudo_view`, via `_real_views`) rather than
        # after -- `_describe_view` costs the better part of a dozen COM
        # round trips per view, and every one of them would be thrown away.
        views = [self._describe_view(view) for view in self._real_views(views_raw)]

        return self._result(
            True, f"{len(views)} view(s) on sheet {sheet_name!r}", SwErrors.swSuccess,
            {"sheet_name": sheet_name, "views": views},
        )

    def _resolve_sheet(self, doc, sheet_name: Optional[str]) -> Tuple[Any, Optional[Dict]]:
        """Resolve `sheet_name` (or the active sheet if omitted) to an
        `ISheet` reference -- the single entry point every view tool
        (`list_views`, `insert_projected_view`, `insert_auxiliary_view`,
        `insert_predefined_views`, `_find_view_by_name`, `delete_view`,
        `auto_arrange_views`) uses to find the sheet it works on.

        Distinct from `_resolve_named_sheet`, which the *sheet* tools use:
        that one also returns the resolved name and reports a miss via
        `_sheet_not_found`, listing the sheets that do exist. The two error
        shapes are deliberately left as they are here -- unifying them would
        change the failure payload of all 19 drawing-view tools.
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

    def _activate_sheet_or_error(self, doc, sheet_name: str,
                                   context: str) -> Optional[Dict]:
        """Make `sheet_name` the active sheet via `IDrawingDoc::ActivateSheet`
        -- what the view-creation tools that place a view on a named sheet do
        first, since the create calls all target whatever sheet is active.

        Returns `None` on success, or the failure result to propagate.

        Unlike the public `activate_sheet`, this takes an already-resolved
        `doc` and reports `swInvalidInput` (a bad `sheet_name` argument)
        rather than that tool's own result shape -- every caller here is
        validating one of its own parameters, not performing an activation
        the caller asked for.
        """
        try:
            activated = doc.ActivateSheet(sheet_name)
        except Exception as e:
            logger.error(f"{context} activate sheet error: {e}")
            return self._result(False, f"Activate sheet error: {e}", SwErrors.swInvalidInput)
        if not activated:
            return self._result(
                False, f"Sheet {sheet_name!r} not found", SwErrors.swInvalidInput,
                {"sheet_name": sheet_name},
            )
        return None

    def _is_sheet_pseudo_view(self, view: Any) -> bool:
        """Is `view` the sheet's own pseudo-view entry rather than a real
        drawing view? -- the single definition of the filter every
        sheet-walking helper in this file applies.

        `ISheet::GetViews`'s own record documents it as *not* heading its
        array with the sheet's own pseudo-view entry, unlike
        `IDrawingDoc::GetViews` -- but that's an inference from one working
        macro's unconditional `For Each`, flagged unverified in the dossier.
        Filtering defensively costs nothing on a harness that behaves as
        documented, and avoids surfacing a bogus "Sheet1"/`swDrawingSheet`
        entry as an addressable view if it doesn't.

        Only answers True when `Type` was actually readable *as a number*
        (`_com_int`, which also rejects the `bool` that `isinstance(x, int)`
        would let through) -- a real view with an unreadable `Type` must not
        silently vanish from a caller's listing.
        """
        return self._read_view_type(view) == int(SwDrawingViewTypes.swDrawingSheet)

    def _read_view_type(self, view: Any) -> Optional[int]:
        """`IView::Type` as an `int`, or `None` if it wasn't readable as a
        number -- the shared read behind `_is_sheet_pseudo_view` and
        `_describe_view`'s `type`/`type_code` pair."""
        return _com_int(self._read_prop(view, "Type"))

    @staticmethod
    def _base_view(view: Any) -> Any:
        """`IView::GetBaseView` -- the view this one is derived from (its
        alignment parent), or `None` if it has none or the read failed.
        Never raises: a view with no parent is the normal case, not an
        error."""
        try:
            return view.GetBaseView() or None
        except Exception:
            return None

    def _base_view_name(self, view: Any) -> Optional[str]:
        """The name of `view`'s `GetBaseView` parent, or `None` -- the
        `GetBaseView` -> `GetName2` idiom shared by `_describe_view`,
        `_view_children_map`, and `auto_arrange_views`."""
        base = self._base_view(view)
        return self._read_prop(base, "GetName2") if base else None

    def _is_alignment_locked(self, view: Any) -> bool:
        """Is `view` alignment-locked to a parent view (`IView::GetAlignment`
        & `swViewAligned`)? -- such a view can only move along its alignment
        vector, never to an arbitrary position, so `move_view` refuses it and
        `auto_arrange_views` reports rather than places it.

        Never raises; an unreadable/non-numeric `GetAlignment` reads as
        "not locked", the permissive answer that leaves the caller's own
        COM call to be the thing that fails if it really is locked."""
        try:
            alignment_code = view.GetAlignment()
        except Exception:
            return False
        code = _com_int(alignment_code)
        return code is not None and bool(code & int(SwViewAlignment.swViewAligned))

    def _iter_real_views(self, sheet: Any):
        """Yield every real (non-sheet-pseudo-view) view on `sheet` via
        `ISheet::GetViews` -- the one place the pseudo-view filter
        (docs/api/02-views.md's Gotchas on that entry) is enforced for the
        helpers that walk a sheet's views: `list_sheets`' view count,
        `_sheet_view_names`, `_sheet_view_fill_state`, `_find_view_by_name`,
        `_view_children_map`, and `auto_arrange_views`.

        Yields nothing (never raises) if `GetViews` fails or answers
        something other than a sequence. Callers that must *report* a
        `GetViews` failure rather than silently see an empty sheet call
        `_sheet_views_or_error` first and pass the list to `_real_views`.
        """
        yield from self._real_views(self._sheet_views_raw(sheet))

    @staticmethod
    def _sheet_views_raw(sheet: Any) -> List[Any]:
        """`ISheet::GetViews` as a list, or `[]` if it failed or answered a
        non-sequence -- never raises."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception:
            return []
        return list(views_raw) if isinstance(views_raw, (list, tuple)) else []

    def _real_views(self, views_raw: Any):
        """Filter an already-fetched `GetViews` array down to real views."""
        if not isinstance(views_raw, (list, tuple)):
            return
        for view in views_raw:
            if not self._is_sheet_pseudo_view(view):
                yield view

    def _sheet_views_or_error(self, sheet: Any, context: str) -> Tuple[List[Any], Optional[Dict]]:
        """`ISheet::GetViews` as a list, or `([], error_dict)` if the call
        itself raised -- for the callers that must surface a `GetViews`
        failure as a result dict instead of silently reading an empty sheet
        the way `_iter_real_views` does. A non-sequence answer is still
        treated as "no views", matching `_sheet_views_raw`."""
        try:
            views_raw = sheet.GetViews() or []
        except Exception as e:
            logger.error(f"{context} error: {e}")
            return [], self._result(False, f"List views error: {e}", SwErrors.swUnknownError)
        return (list(views_raw) if isinstance(views_raw, (list, tuple)) else []), None

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
        state: Dict[str, bool] = {}
        for view in self._iter_real_views(sheet):
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            state[name] = bool(self._read_prop(view, "ReferencedDocument"))
        return state

    def _find_view_by_name(self, doc, view_name: str,
                            sheet_name: Optional[str] = None,
                            sheet: Any = None) -> Tuple[Any, List[str], Optional[Dict]]:
        """Resolve `view_name` to its raw `IView` object on `sheet_name` (or
        the active sheet), via `ISheet::GetViews` -- what `insert_projected_view`
        and `insert_auxiliary_view` use to validate a caller-supplied parent
        view name against what's actually on the sheet, listing the real
        names on a miss rather than passing an unrecognized string straight
        through to a COM call whose only failure signal is a bare `Nothing`.

        Args:
            sheet: an already-resolved `ISheet` to search, for callers that
                needed the sheet for something else anyway -- skips the
                redundant `Sheet()`/`GetCurrentSheet()` round trip.
                `sheet_name` is then only used to describe the sheet.

        Returns:
            `(view, names, None)` on a sheet-resolution success -- `view` is
            `None` (with `names` populated) if no view on the sheet has that
            name. `(None, [], error_dict)` if the sheet itself couldn't be
            resolved.
        """
        if sheet is None:
            sheet, err = self._resolve_sheet(doc, sheet_name)
            if err:
                return None, [], err

        views_raw, views_err = self._sheet_views_or_error(sheet, "_find_view_by_name")
        if views_err:
            return None, [], views_err

        names = []
        match = None
        for view in self._real_views(views_raw):
            name = self._read_prop(view, "GetName2")
            if name:
                names.append(name)
            if name == view_name:
                match = view

        return match, names, None

    def _require_view(self, doc, view_name: str, sheet_name: Optional[str],
                       data: Optional[Dict[str, Any]] = None,
                       label: str = "view", sheet: Any = None) -> Tuple[Any, Optional[Dict]]:
        """Resolve `view_name` to its `IView`, or return the house
        "unknown view" result -- the view-side mirror of `_sheet_not_found`,
        and the one place the shape of that failure is defined.

        Every drawing-view tool validates its caller-supplied view name the
        same way (`_find_view_by_name`, then `swInvalidInput` listing the
        names that *do* exist), so the message and payload live here rather
        than being restated at each tool.

        Args:
            data: the calling tool's own context dict, merged into the
                failure payload alongside `available_views` so the error
                carries the arguments the caller passed.
            label: how the view is named in the message -- "view",
                "parent view", or "reference view", matching the role the
                name plays in that tool's signature.
            sheet: an already-resolved `ISheet`, passed straight through to
                `_find_view_by_name` to avoid re-resolving it.

        Returns:
            `(view, None)` on a hit; `(None, error_dict)` if the sheet
            couldn't be resolved, `GetViews` failed, or no view on the sheet
            has that name.
        """
        view, names, find_err = self._find_view_by_name(doc, view_name, sheet_name, sheet)
        if find_err:
            return None, find_err
        if view is None:
            return None, self._result(
                False,
                f"Unknown {label} {view_name!r}; available views: {names!r}",
                SwErrors.swInvalidInput,
                {**(data or {}), "available_views": names},
            )
        return view, None

    def _activate_view(self, doc, view_name: str, context: str,
                        data: Optional[Dict[str, Any]] = None,
                        label: str = "view") -> Optional[Dict]:
        """Make `view_name` the active drawing view via
        `IDrawingDoc::ActivateView`, so the sketch/annotation calls that
        follow land in that view's own coordinate space.

        Returns `None` on success, or the failure result to propagate.

        This is deliberately *not*
        `SelectionOperations.select_view_by_name`, which does the same COM
        call: that one re-fetches the document and reports
        `swSelectionError`, while every view-creation tool here has already
        resolved `doc` and reports the activation step as a
        `swFeatureError` against its own `data` context. Keeping the two
        distinct preserves each caller's established error contract; the
        duplication being removed here is the five byte-identical copies of
        this block, not the difference between the two contracts.
        """
        try:
            activated = doc.ActivateView(view_name)
        except Exception as e:
            logger.error(f"{context} activate view error: {e}")
            return self._result(False, f"Activate view error: {e}", SwErrors.swFeatureError, data)
        if not activated:
            return self._result(
                False, f"Failed to activate {label} {view_name!r}",
                SwErrors.swFeatureError, data,
            )
        return None

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

        # `CreateUnfoldedViewAt3` places the projection on whatever sheet is
        # active, and `SelectByID2` only resolves a view on the active sheet
        # -- so a named sheet has to be activated first, exactly as
        # `insert_model_view`/`insert_predefined_views` do, or the parent-view
        # selection silently misses and the new view lands on the wrong sheet.
        if sheet_name:
            activate_err = self._activate_sheet_or_error(
                doc, sheet_name, "insert_projected_view")
            if activate_err:
                return activate_err

        parent_view, find_err = self._require_view(
            doc, parent_view_name, sheet_name,
            {"parent_view_name": parent_view_name}, label="parent view")
        if find_err:
            return find_err

        parent_x_m, parent_y_m = 0.0, 0.0
        parent_position = self._read_prop(parent_view, "Position")
        if isinstance(parent_position, (list, tuple)) and len(parent_position) >= 2:
            try:
                parent_x_m, parent_y_m = float(parent_position[0]), float(parent_position[1])
            except (TypeError, ValueError):
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
            activate_err = self._activate_sheet_or_error(
                doc, sheet_name, "insert_predefined_views")
            if activate_err:
                return activate_err

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

        # The sheet is re-resolved rather than reusing the reference from
        # before the call: `InsertModelInPredefinedView` rebuilds the view
        # tree, and this project's convention is not to trust a COM pointer
        # held across a mutating call. One extra `GetCurrentSheet` round trip
        # is cheap next to re-reading every view's `ReferencedDocument`.
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

        # `CreateAuxiliaryViewAt2` places the new view on whatever sheet is
        # active (and the reference-edge selection below only resolves on the
        # active sheet), so a named sheet is activated first -- same reason
        # `insert_model_view`/`insert_projected_view` do it.
        if sheet_name:
            activate_err = self._activate_sheet_or_error(
                doc, sheet_name, "insert_auxiliary_view")
            if activate_err:
                return activate_err

        parent_view, find_err = self._require_view(
            doc, parent_view_name, sheet_name,
            {"parent_view_name": parent_view_name}, label="parent view")
        if find_err:
            return find_err

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
    def _normalize_xy_points(
        raw_points: Any, *, field: str, minimum: int, drop_closing_duplicate: bool = False,
    ) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
        """Validate and normalize a caller-supplied point list into `(x, y)`
        float tuples, in the caller's default unit (not yet converted to
        meters -- that happens per-segment once a parent view is confirmed to
        exist). The one parser behind `_normalize_cut_points` and
        `_normalize_profile_points`, which differ only in `field`, `minimum`,
        and whether a pre-closed polygon is accepted.

        Each point may be `[x, y]`/`(x, y)` or `{"x": ..., "y": ...}`.
        Returns `(points, None)` on success, or `(None, error_message)` for
        anything that isn't a valid `minimum`+-point, `minimum`+-distinct-point
        list -- checked entirely in Python, before any COM call, per those
        issues' shared Acceptance Criteria ("no COM call" for invalid input).

        Args:
            drop_closing_duplicate: True drops a trailing point that
                duplicates the first (an already-closed input, e.g.
                `[A, B, C, A]`) before the distinctness check, so an
                explicitly pre-closed polygon isn't penalized for what the
                caller's own auto-close step would otherwise turn into a
                degenerate zero-length closing segment.
        """
        if not isinstance(raw_points, (list, tuple)) or len(raw_points) < minimum:
            got = len(raw_points) if isinstance(raw_points, (list, tuple)) else raw_points
            return None, f"{field} must have at least {minimum} (x, y) pairs; got {got!r}"

        points: List[Tuple[float, float]] = []
        for i, raw in enumerate(raw_points):
            if isinstance(raw, dict):
                if "x" not in raw or "y" not in raw:
                    return None, f"{field}[{i}] must have 'x' and 'y'; got {raw!r}"
                px, py = raw["x"], raw["y"]
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                px, py = raw[0], raw[1]
            else:
                return None, (
                    f"{field}[{i}] must be [x, y] or {{'x': ..., 'y': ...}}; got {raw!r}"
                )
            try:
                points.append((float(px), float(py)))
            except (TypeError, ValueError):
                return None, f"{field}[{i}] has non-numeric coordinates: {raw!r}"

        if drop_closing_duplicate and len(points) >= 2 and points[-1] == points[0]:
            points = points[:-1]

        if len(set(points)) < minimum:
            return None, f"{field} must contain at least {minimum} distinct points"

        return points, None

    @classmethod
    def _normalize_cut_points(cls, cut_points: Any) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
        """`insert_section_view`'s `cut_points`: at least 2 distinct points,
        with no pre-close handling (a section cut line is an open polyline,
        not a closed profile). See `_normalize_xy_points`."""
        return cls._normalize_xy_points(cut_points, field="cut_points", minimum=2)

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

        parent_view, find_err = self._require_view(
            doc, parent_view_name, None, data, label="parent view")
        if find_err:
            return find_err

        activate_err = self._activate_view(
            doc, parent_view_name, "insert_section_view", data, label="parent view")
        if activate_err:
            return activate_err

        segment_midpoints, sketch_err = self._sketch_segment_loop(
            doc, points, close=False, context="insert_section_view",
            failure_message=(
                "Failed to sketch cut-line segment -- ensure the parent view "
                f"{parent_view_name!r} supports a section line"
            ),
            sketch_error_message="Sketch cut line error", data=data,
        )
        if sketch_err:
            # A partially-sketched cut line is never consumed by anything --
            # only a successful `CreateSectionViewAt5` absorbs the geometry --
            # so it is cleaned up on every pre-creation failure path, the same
            # way `insert_detail_view`/`insert_broken_out_section` clean up
            # theirs. Otherwise a retry re-sketches on top of the leftovers.
            self._delete_sketch_geometry(doc, segment_midpoints)
            return sketch_err

        # Select every cut-line segment atomically before the call, per the
        # dossier's "select the section line or lines" requirement.
        with ExitStack() as stack:
            sel_err = self._select_segments(stack, segment_midpoints)
            if sel_err:
                self._delete_sketch_geometry(doc, segment_midpoints)
                return sel_err

            try:
                args = CREATE_SECTION_VIEW_AT5.bind(
                    units=self._units, x=x, y=y, z=0,
                    label=label or "", options=options,
                    excluded_components=None, section_depth=0,
                )
                view = doc.CreateSectionViewAt5(*args)
            except Exception as e:
                logger.error(f"insert_section_view error: {e}")
                self._delete_sketch_geometry(doc, segment_midpoints)
                return self._result(False, f"Insert section view error: {e}",
                                    SwErrors.swFeatureError, data)

        if view is None:
            self._delete_sketch_geometry(doc, segment_midpoints)
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

    def _sketch_segment_loop(
        self, doc, points: List[Tuple[float, float]], *, close: bool,
        context: str, failure_message: str, sketch_error_message: str,
        data: Dict[str, Any],
    ) -> Tuple[List[Tuple[float, float]], Optional[Dict]]:
        """Sketch `points` as a chain of `ISketchManager::CreateLine`
        segments in the currently-active drawing view, returning one
        representative midpoint per segment -- the shared body of
        `insert_section_view`'s cut line and `insert_broken_out_section`/
        `add_crop_view`'s closed profiles.

        Coordinates arrive in the caller's default unit and are converted
        per-endpoint here. Each segment's midpoint is what the caller later
        hands `SelectByID2`, in the same view-local space `CreateLine` just
        used -- this wrapper's own convention (not sourced in the dossier,
        which doesn't cover `SelectByID2`'s coordinate space for a
        freshly-created drawing-view sketch entity), the same caveat
        `list_view_entities` flags for its own coordinate space.

        `ISketchManager` is fetched once rather than per segment: it is a
        COM property on `IModelDoc2`, so re-reading it inside the loop would
        cost one cross-process round trip per segment for an object that
        does not change.

        Args:
            close: True appends a final segment from the last point back to
                the first, for callers that need a closed profile.

        Returns:
            `(midpoints, None)` on success. On failure, `(midpoints, error)`
            where `midpoints` covers whatever segments were created before
            the failure -- callers that clean up partial geometry pass it
            straight to `_delete_sketch_geometry`.
        """
        loop_points = list(points) + [points[0]] if close else list(points)

        midpoints: List[Tuple[float, float]] = []
        try:
            sketch_mgr = doc.SketchManager
            for (x1, y1), (x2, y2) in zip(loop_points, loop_points[1:]):
                x1_m, y1_m = self._units.to_meters(x1), self._units.to_meters(y1)
                x2_m, y2_m = self._units.to_meters(x2), self._units.to_meters(y2)
                segment = sketch_mgr.CreateLine(x1_m, y1_m, 0.0, x2_m, y2_m, 0.0)
                if segment is None:
                    return midpoints, self._result(
                        False, failure_message, SwErrors.swSketchError, data,
                    )
                midpoints.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
        except Exception as e:
            logger.error(f"{context} sketch error: {e}")
            return midpoints, self._result(
                False, f"{sketch_error_message}: {e}", SwErrors.swSketchError, data,
            )

        return midpoints, None

    def _select_segments(self, stack: ExitStack,
                          midpoints: List[Tuple[float, float]]) -> Optional[Dict]:
        """Select every sketched segment atomically into `stack`, by the
        representative midpoints `_sketch_segment_loop` returned.

        The first `selected()` clears any stale selection (and clears again
        on its own exit); every subsequent one appends and skips clearing on
        both ends (see `SelectionOperations.selected`'s docstring), so the
        `ExitStack`'s LIFO unwind leaves the outermost/first block to do the
        one real clear, after everything inside it -- including the caller's
        create call -- has run. That `append=(i > 0)` invariant is the
        easiest thing here to get wrong, so it is stated once, here.

        Returns `None` once everything is selected, or the failing
        `selected()` result for the caller to propagate.
        """
        for i, (mx, my) in enumerate(midpoints):
            sel = stack.enter_context(
                self.selected("", "SKETCHSEGMENT", mx, my, 0, append=(i > 0), mark=i)
            )
            if not sel["success"]:
                return sel
        return None

    def _delete_sketch_geometry(self, doc, points: List[Tuple[float, float]]) -> None:
        """Best-effort cleanup of construction sketch geometry left behind by a
        failed `insert_section_view`/`insert_detail_view`/
        `insert_broken_out_section`/`add_crop_view` call, via
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

        parent_view, find_err = self._require_view(
            doc, parent_view_name, None, data, label="parent view")
        if find_err:
            return find_err

        activate_err = self._activate_view(
            doc, parent_view_name, "insert_detail_view", data, label="parent view")
        if activate_err:
            return activate_err

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

    @classmethod
    def _normalize_profile_points(
        cls, profile_points: Any,
    ) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
        """`insert_broken_out_section`'s and `add_crop_view`'s
        `profile_points`: at least 3 distinct points, with a trailing
        duplicate of the first dropped so an explicitly pre-closed polygon is
        accepted (both callers auto-close the loop themselves). See
        `_normalize_xy_points`."""
        return cls._normalize_xy_points(
            profile_points, field="profile_points", minimum=3, drop_closing_duplicate=True,
        )

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

        parent_view, find_err = self._require_view(
            doc, parent_view_name, None, data, label="parent view")
        if find_err:
            return find_err

        activate_err = self._activate_view(
            doc, parent_view_name, "insert_broken_out_section", data, label="parent view")
        if activate_err:
            return activate_err

        # Auto-close: an extra segment connects the last point back to the first.
        segment_midpoints, sketch_err = self._sketch_segment_loop(
            doc, points, close=True, context="insert_broken_out_section",
            failure_message=(
                "Failed to sketch profile segment -- ensure the parent view "
                f"{parent_view_name!r} supports a broken-out section"
            ),
            sketch_error_message="Sketch profile error", data=data,
        )
        if sketch_err:
            self._delete_sketch_geometry(doc, segment_midpoints)
            return sketch_err

        with ExitStack() as stack:
            sel_err = self._select_segments(stack, segment_midpoints)
            if sel_err:
                self._delete_sketch_geometry(doc, segment_midpoints)
                return sel_err

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
    # Break and crop views (sw-8ww.5)
    # ========================================================================

    def insert_break_view(
        self, view_name: str, position1: float, position2: float,
        orientation: str = "vertical", gap: Optional[float] = None,
        style: str = "zigzag",
    ) -> Dict:
        """
        Insert a break into an existing drawing view via `IView::InsertBreak3`
        followed by `IDrawingDoc::BreakView` -- requested as `IDrawingDoc::
        InsertBreak`, which does not exist (docs/api/02-views.md's
        `InsertBreak3` record: the parameterized, position-controlling call
        lives on `IView`, not `IDrawingDoc`). `InsertBreak3` only creates the
        break lines; `BreakView` -- called on the selected view, per the
        dossier's `BreakView` record added for this issue -- is what actually
        applies/displays the break.

        Args:
            view_name: Name of the existing drawing view to break
                (`IView::GetName2`, e.g. from `list_views`). Validated
                against the sheet's actual views first (`swInvalidInput`
                listing the real names on a miss), then activated via
                `IDrawingDoc::ActivateView` before the break lines are
                inserted, so `position1`/`position2` land in that view's own
                coordinate space.
            position1, position2: Location of the two break lines, in the
                view's coordinate space, in the caller's default unit
                (`set_units`) -- `InsertBreak3`'s own `Position1`/`Position2`
                (a Y value if `orientation` is horizontal, an X value if
                vertical, per the dossier's axis-convention note).
            orientation: `"vertical"` (default) or `"horizontal"` --
                `InsertBreak3`'s `Orientation` (`swBreakLineOrientation_e`).
                Anything else fails with `swInvalidInput` before any COM
                call.
            gap: Break line gap, in the caller's default unit -- sets
                `IView::BreakLineGap`, a separate get/set property, not an
                `InsertBreak3` parameter (per the dossier's Gotchas). `None`
                (default) leaves the view's existing gap untouched.
            style: Break line cut style -- one of `"straight"`, `"zigzag"`
                (default), `"curve"`, `"small_zigzag"`, `"jagged"`, mapped to
                `swBreakLineStyle_e`. An unrecognized value fails with
                `swInvalidInput` before any COM call, listing the valid
                values.

        Returns:
            Result dict. Fails with `swFeatureError` -- before any COM write
            -- if the view is already broken (`IView::IsBroken`), the
            precondition `InsertBreak3`'s own record states, and again after
            `BreakView` if the view still reports *not* broken (that call is a
            bare `Sub` whose documented failure mode is a silent no-op). On
            success, `data["break_count"]` is the view's resulting break
            count, read back via `IView::GetBreakLineCount2` (best-effort --
            a read failure leaves it `None` rather than failing the whole
            call, since the break itself was already applied by that point).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {
            "view_name": view_name, "position1": position1, "position2": position2,
            "orientation": orientation, "gap": gap, "style": style,
        }

        orientation_key = (orientation or "").strip().lower()
        orientation_int = _BREAK_LINE_ORIENTATION.get(orientation_key)
        if orientation_int is None:
            return self._result(
                False,
                f"Unknown orientation {orientation!r}; expected one of "
                f"{sorted(_BREAK_LINE_ORIENTATION)!r}",
                SwErrors.swInvalidInput, data,
            )

        style_key = (style or "").strip().lower()
        style_int = _BREAK_LINE_STYLE.get(style_key)
        if style_int is None:
            return self._result(
                False,
                f"Unknown style {style!r}; expected one of {sorted(_BREAK_LINE_STYLE)!r}",
                SwErrors.swInvalidInput, data,
            )

        view, find_err = self._require_view(doc, view_name, None, data)
        if find_err:
            return find_err

        # `InsertBreak3`'s own record: "The view must not already be broken."
        # It has no failure code of its own (and no documented behavior for a
        # second break), so the precondition is checked here rather than
        # relying on the COM call to reject it -- the same proactive guard
        # `add_crop_view` applies with `IsCropped`. Only a *definite* True
        # blocks the call (`_com_bool`, since `VARIANT_BOOL` arrives as `bool`
        # through some interop layers and `0`/`-1` through others); an
        # unreadable `IsBroken` leaves the COM call to be the thing that
        # fails.
        if _com_bool(self._read_prop(view, "IsBroken")):
            return self._result(
                False,
                f"View {view_name!r} is already broken -- remove the existing break "
                "first (remove_break_view) rather than stacking a new one",
                SwErrors.swFeatureError, data,
            )

        activate_err = self._activate_view(doc, view_name, "insert_break_view", data)
        if activate_err:
            return activate_err

        pos1_m = self._units.to_meters(position1)
        pos2_m = self._units.to_meters(position2)

        try:
            inserted = view.InsertBreak3(orientation_int, pos1_m, pos2_m, style_int, 1, False)
        except Exception as e:
            logger.error(f"insert_break_view InsertBreak3 error: {e}")
            return self._result(False, f"Insert break error: {e}", SwErrors.swFeatureError, data)
        if inserted is None:
            return self._result(
                False, f"Failed to insert break lines on {view_name!r}",
                SwErrors.swFeatureError, data,
            )

        if gap is not None:
            try:
                view.BreakLineGap = self._units.to_meters(gap)
            except Exception as e:
                logger.error(f"insert_break_view BreakLineGap error: {e}")
                return self._result(
                    False,
                    f"Inserted break lines on {view_name!r} but failed to set gap: {e}",
                    SwErrors.swFeatureError, data,
                )

        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return self._result(
                    False,
                    f"Inserted break lines on {view_name!r} but could not select the "
                    f"view to apply the break: {sel['message']}",
                    SwErrors.swSelectionError, data,
                )
            try:
                doc.BreakView()
            except Exception as e:
                logger.error(f"insert_break_view BreakView error: {e}")
                return self._result(
                    False, f"Inserted break lines on {view_name!r} but BreakView failed: {e}",
                    SwErrors.swFeatureError, data,
                )

        # `BreakView` is a bare `Sub` -- no return value, and its own record
        # warns its failure mode is a silent no-op rather than a raised error.
        # `IView::IsBroken` is the only readable signal that the break was
        # actually applied, so it is checked here the same way
        # `remove_break_view` checks it after `UnBreakView`. Only a definite
        # `False` fails the call; an unreadable state is not evidence of a
        # no-op.
        if _com_bool(self._read_prop(view, "IsBroken")) is False:
            return self._result(
                False,
                f"Inserted break lines on {view_name!r} but BreakView did not apply "
                "the break",
                SwErrors.swFeatureError, data,
            )

        # `Size` is a ByRef out-parameter (a buffer-sizing hint for
        # `GetBreakLineInfo2`, not the count) -- it has to be a real VARIANT
        # box, per this file's `errors`/`warnings` convention, or the call
        # itself fails on a real interop layer. The break count is the
        # function's own return value; anything non-numeric coming back is
        # reported as `None` rather than leaking a raw COM object into `data`.
        try:
            count = view.GetBreakLineCount2(com_backend.byref_int())
        except Exception as e:
            logger.debug(f"insert_break_view GetBreakLineCount2 read failed: {e}")
            count = None
        data["break_count"] = _com_int(count)

        return self._result(True, f"Inserted break on {view_name!r}", SwErrors.swSuccess, data)

    def remove_break_view(self, view_name: str) -> Dict:
        """
        Remove all breaks from a drawing view via select + `IDrawingDoc::
        UnBreakView` -- there is no dedicated "RemoveBreak"/per-break
        removal call; `UnBreakView` acts on whichever view is currently
        selected (docs/api/02-views.md's `UnBreakView` record -- note it
        lives on `IDrawingDoc`, not `IView`, unlike `InsertBreak3`).

        Args:
            view_name: Name of the existing drawing view to unbreak
                (`IView::GetName2`, e.g. from `list_views`). Validated
                against the sheet's actual views first (`swInvalidInput`
                listing the real names on a miss).

        Returns:
            Result dict. `UnBreakView` is a bare `Sub` with no return value,
            so this verifies via `IView::IsBroken()` afterward (per the
            dossier's Gotchas: its thin help page doesn't itself confirm the
            break state actually cleared) and fails with `swFeatureError` if
            the view still reports broken.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {"view_name": view_name}

        view, find_err = self._require_view(doc, view_name, None, data)
        if find_err:
            return find_err

        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                doc.UnBreakView()
            except Exception as e:
                logger.error(f"remove_break_view UnBreakView error: {e}")
                return self._result(False, f"Remove break error: {e}", SwErrors.swFeatureError, data)

        if _com_bool(self._read_prop(view, "IsBroken")):
            return self._result(
                False, f"UnBreakView did not clear the break state on {view_name!r}",
                SwErrors.swFeatureError, data,
            )

        return self._result(True, f"Removed break from {view_name!r}", SwErrors.swSuccess, data)

    def add_crop_view(self, view_name: str, profile_points: List[Any]) -> Dict:
        """
        Crop an existing drawing view to a closed sketch profile via
        `IView::Crop2` -- requested as `IView::CropView`, which does not
        exist (docs/api/02-views.md's `Crop2` record: `Crop2` is the current
        overload, `Crop` its obsolete predecessor). Owns the whole sequence
        -- activate the view, sketch the closed profile as line segments,
        select them, crop -- the same shape `insert_broken_out_section` uses
        for its own prior-selection requirement.

        Args:
            view_name: Name of the existing drawing view to crop
                (`IView::GetName2`, e.g. from `list_views`). Validated
                against the sheet's actual views first (`swInvalidInput`
                listing the real names on a miss). Rejected with
                `swFeatureError` -- before any sketch geometry is created --
                if the view is already cropped (`IView::IsCropped()`), so a
                second crop never stacks on top of the first: `Crop2`'s own
                `swCropViewErrors_e` return code has no "already cropped"
                member, so this is checked proactively rather than relying
                on the COM call to catch it.
            profile_points: 3+ `[x, y]` (or `{"x":.., "y":..}`) pairs, in the
                view's coordinate space, in the caller's default unit
                (`set_units`) -- the closed profile boundary, built from `N`
                `ISketchManager::CreateLine` segments, auto-closed the same
                way `insert_broken_out_section` closes its own loop (an
                extra segment connects the last point back to the first;
                fewer than 3 points, or fewer than 3 distinct points, fails
                with `swInvalidInput` before any COM call).

        Returns:
            Result dict. On success, `data["view_name"]` is `view_name` and
            `data["crop_status"]` is `Crop2`'s own `swCropViewErrors_e`
            return code (always `1`/`swCropViewErrors_NoError` on success --
            see the dossier's return-code trap: `0` is `Unknown`, not
            success). On any failure after the profile was successfully
            sketched (selection failure, `Crop2` itself raising or returning
            a non-success code), whatever segments were sketched are deleted
            via `_delete_sketch_geometry` before the error is returned, so a
            failed call never leaves a stray open sketch on the sheet.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {"view_name": view_name}

        points, point_err = self._normalize_profile_points(profile_points)
        if point_err:
            return self._result(False, point_err, SwErrors.swInvalidInput, data)

        view, find_err = self._require_view(doc, view_name, None, data)
        if find_err:
            return find_err

        if _com_bool(self._read_prop(view, "IsCropped")):
            return self._result(
                False,
                f"View {view_name!r} is already cropped -- remove the existing crop "
                "first (remove_crop_view) rather than stacking a new one",
                SwErrors.swFeatureError, data,
            )

        activate_err = self._activate_view(doc, view_name, "add_crop_view", data)
        if activate_err:
            return activate_err

        # Auto-close: an extra segment connects the last point back to the first.
        segment_midpoints, sketch_err = self._sketch_segment_loop(
            doc, points, close=True, context="add_crop_view",
            failure_message=(
                "Failed to sketch profile segment -- ensure the view "
                f"{view_name!r} supports a crop"
            ),
            sketch_error_message="Sketch profile error", data=data,
        )
        if sketch_err:
            self._delete_sketch_geometry(doc, segment_midpoints)
            return sketch_err

        with ExitStack() as stack:
            sel_err = self._select_segments(stack, segment_midpoints)
            if sel_err:
                self._delete_sketch_geometry(doc, segment_midpoints)
                return sel_err

            try:
                status = view.Crop2(False, False, 1)
            except Exception as e:
                logger.error(f"add_crop_view Crop2 error: {e}")
                self._delete_sketch_geometry(doc, segment_midpoints)
                return self._result(False, f"Crop view error: {e}", SwErrors.swFeatureError, data)

        status_int = _com_int(status)
        if status_int != int(SwCropViewErrors.swCropViewErrors_NoError):
            self._delete_sketch_geometry(doc, segment_midpoints)
            try:
                status_name = SwCropViewErrors(status_int).name
            except ValueError:
                status_name = repr(status)
            return self._result(
                False, f"Failed to crop view {view_name!r} -- Crop2 returned {status_name}",
                SwErrors.swFeatureError, data,
            )

        data["crop_status"] = status_int
        return self._result(True, f"Cropped view {view_name!r}", SwErrors.swSuccess, data)

    def remove_crop_view(self, view_name: str) -> Dict:
        """
        Remove a view's crop via select + `ISldWorks::RunCommand(swCommands_
        Tools_Crop_Delete)` -- requested as `IView::RemoveCropView`, which
        does not exist and has no dedicated API equivalent at all
        (docs/api/02-views.md's `RunCommand` record: crop removal is
        documented only as a right-click UI action; this fires the same
        command ID that action fires -- a workaround, not a purpose-built
        API call).

        Args:
            view_name: Name of the existing, cropped drawing view
                (`IView::GetName2`, e.g. from `list_views`). Validated
                against the sheet's actual views first (`swInvalidInput`
                listing the real names on a miss). Rejected with
                `swFeatureError` -- before the `RunCommand` call -- if the
                view is not currently cropped (`IView::IsCropped()`), the
                precondition `swCommands_Tools_Crop_Delete` itself documents
                ("valid for a selected Crop View in a drawing").

        Returns:
            Result dict. `RunCommand` returns only a bare boolean with no
            structured error info (per the dossier), so this verifies via
            `IView::IsCropped()` afterward and fails with `swFeatureError`
            if the view still reports cropped.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        data = {"view_name": view_name}

        view, find_err = self._require_view(doc, view_name, None, data)
        if find_err:
            return find_err

        if _com_bool(self._read_prop(view, "IsCropped")) is False:
            return self._result(
                False, f"View {view_name!r} is not cropped -- nothing to remove",
                SwErrors.swFeatureError, data,
            )

        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0) as sel:
            if not sel["success"]:
                return sel
            try:
                ran = self.app.RunCommand(int(SwCommands.swCommands_Tools_Crop_Delete), "")
            except Exception as e:
                logger.error(f"remove_crop_view RunCommand error: {e}")
                return self._result(False, f"Remove crop error: {e}", SwErrors.swFeatureError, data)

        if not ran:
            return self._result(
                False, f"RunCommand reported failure removing the crop on {view_name!r}",
                SwErrors.swFeatureError, data,
            )

        if _com_bool(self._read_prop(view, "IsCropped")):
            return self._result(
                False, f"Crop was not removed from {view_name!r}",
                SwErrors.swFeatureError, data,
            )

        return self._result(True, f"Removed crop from {view_name!r}", SwErrors.swSuccess, data)

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

        data = {"view_name": view_name, "x": x, "y": y, "sheet_name": sheet_name}

        view, find_err = self._require_view(doc, view_name, sheet_name, data)
        if find_err:
            return find_err

        if self._is_alignment_locked(view):
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

        # Both views live on the same sheet, so it is resolved once here and
        # reused for the reference-view lookup further down.
        sheet, sheet_err = self._resolve_sheet(doc, sheet_name)
        if sheet_err:
            return sheet_err

        view, find_err = self._require_view(doc, view_name, sheet_name, data, sheet=sheet)
        if find_err:
            return find_err

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

        reference_view, ref_find_err = self._require_view(
            doc, reference_view_name, sheet_name, data,
            label="reference view", sheet=sheet)
        if ref_find_err:
            return ref_find_err

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

        view, find_err = self._require_view(doc, view_name, sheet_name, data)
        if find_err:
            return find_err

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

        view, find_err = self._require_view(doc, view_name, sheet_name, data)
        if find_err:
            return find_err

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
        children: Dict[str, List[str]] = {}
        for view in self._iter_real_views(sheet):
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            parent_name = self._base_view_name(view)
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
                `list_views` does, and activated first: deletion goes through
                `SelectByID2`, which only resolves a view on the *active*
                sheet, so without the activation a named non-active sheet's
                view would validate here and then fail to select.

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

        if sheet_name:
            activate_err = self._activate_sheet_or_error(doc, sheet_name, "delete_view")
            if activate_err:
                return activate_err

        sheet, sheet_err = self._resolve_sheet(doc, sheet_name)
        if sheet_err:
            return sheet_err

        # `sheet` is reused for both the name check and the dependent-view
        # walk below, rather than letting `_require_view` resolve it again.
        _view, find_err = self._require_view(doc, view_name, sheet_name, data, sheet=sheet)
        if find_err:
            return find_err

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

        views_raw, views_err = self._sheet_views_or_error(sheet, "auto_arrange_views")
        if views_err:
            return views_err

        by_name: Dict[str, Dict[str, Any]] = {}
        skipped: List[str] = []
        for view in self._real_views(views_raw):
            name = self._read_prop(view, "GetName2")
            if not name:
                continue
            outline = self._read_prop(view, "GetOutline")
            if not isinstance(outline, (list, tuple)) or len(outline) < 4:
                skipped.append(name)
                continue
            # A non-numeric element counts as an unreadable outline (skipped),
            # not an exception out of the whole tool -- same rule
            # `_describe_view` applies to `IView::Position`.
            try:
                xmin, ymin, xmax, ymax = tuple(float(v) for v in outline[:4])
            except (TypeError, ValueError):
                skipped.append(name)
                continue
            parent_name = self._base_view_name(view)
            locked = self._is_alignment_locked(view)

            by_name[name] = {
                "name": name, "view": view, "parent_name": parent_name, "locked": locked,
                "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            }

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
        for name in by_name:
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
        names = []
        for view in self._iter_real_views(sheet):
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
        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0, doc=doc) as sel:
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
            _target_view, find_err = self._require_view(
                doc, view_name, None, {"view_name": view_name})
            if find_err:
                return find_err
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

        xy_err = self._validate_xy(x, y, {"dimension_type": type_key, "x": x, "y": y})
        if xy_err:
            return xy_err

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        data = {
            "view_name": view_name, "dimension_type": type_key, "x": x, "y": y,
            "entity_count": len(parsed_entities), "dim_type_enum": type_config["dim_type_enum"],
        }

        with ExitStack() as stack:
            for i, (type_str, ex, ey, ez) in enumerate(parsed_entities):
                sel = stack.enter_context(
                    self.selected("", type_str, ex, ey, ez, append=(i > 0), mark=i, doc=doc)
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

        xy_err = self._validate_xy(x, y, {"x": x, "y": y})
        if xy_err:
            return xy_err

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
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
                    self.selected("", type_str, ex, ey, ez, append=(i > 0), mark=i, doc=doc)
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
        with self.selected(dimension_name, "DIMENSION", 0, 0, 0, doc=doc) as sel:
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
        with self.selected(dimension_name, "DIMENSION", 0, 0, 0, doc=doc) as sel:
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

        with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0, doc=doc) as sel:
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

    def _validate_xy(self, x: Any, y: Any, data: Optional[Dict] = None) -> Optional[Dict]:
        """Type-check an annotation placement point.

        Every `Insert*`/`Create*` wrapper in this module takes a sheet-space
        `x`/`y` and must reject a non-number *before* any COM call, per the
        working agreement's "validate before COM calls" rule -- `bool` is
        excluded explicitly because Python makes it an `int` subclass, and a
        `True` that silently means 1 meter is worse than an error.

        Returns an error dict, or `None` if both are numbers.
        """
        if isinstance(x, bool) or isinstance(y, bool) \
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._result(
                False, f"x/y must be numbers, got x={x!r}, y={y!r}",
                SwErrors.swInvalidInput, data,
            )
        return None

    def _validate_note_geometry(self, x: float, y: float, height: Optional[float],
                                 angle: float) -> Optional[Dict]:
        """Type/range-check `add_note`/`add_property_note`'s `x`/`y`/`height`/
        `angle` -- split out from `_create_note_object` so callers can run it
        *before* any COM call (including `select_view_by_name`'s
        `ActivateView`), per the working agreement's "validate before COM
        calls" rule. Returns an error dict, or `None` if everything checks out.
        """
        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err
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

    def _annotation_name_position(self, annotation: Any) -> Tuple[Any, Any, Any]:
        """Read `(name, x, y)` off an `IAnnotation` via `GetName`/`GetPosition`.

        Every annotation family this module creates or lists reports its
        identity the same way, so the read-back is shared: `GetPosition`
        is meters on the wire and comes back in the caller's default unit.
        Best-effort throughout -- a null `annotation`, an unreadable
        property, or a position that isn't a 2+ element sequence yields
        `None` rather than failing the describe.
        """
        if annotation is None:
            return None, None, None

        name = self._read_prop(annotation, "GetName")
        position = self._read_prop(annotation, "GetPosition")
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                return (name,
                        self._units.from_meters(float(position[0])),
                        self._units.from_meters(float(position[1])))
            except (TypeError, ValueError):
                pass
        return name, None, None

    def _place_annotation(self, owner: Any, x: Optional[float], y: Optional[float],
                           noun: str, position_noun: str, context: str,
                           data: Dict) -> Tuple[Any, Optional[Dict]]:
        """Position a freshly-created annotation and record its name.

        Every `Insert*` factory in this module returns a type-specific
        wrapper (`IDatumTag`, `IGtol`, `IWeldSymbol`, ...) that carries no
        placement of its own: the position lives on the `IAnnotation` behind
        `GetAnnotation()`, is set via `SetPosition2` (meters, `z` always
        `0.0` in 2D sheet space), and the annotation is also where the
        SolidWorks-assigned name comes from. This is the shared tail of
        `add_datum_feature`/`add_gtol`/`add_datum_target`/`add_weld_symbol`
        -- `_finalize_note` is the notes-specific equivalent.

        A `GetAnnotation` that throws or returns nothing is only fatal when
        a position was actually requested: `add_gtol`'s freestanding
        (`leader=False`, no `x`/`y`) form legitimately has nothing to place,
        and still succeeds with a `None` name.

        Args:
            owner: The wrapper returned by the `Insert*` call.
            x, y: Placement in the caller's default unit, or `None` to skip
                positioning entirely.
            noun: Sentence-initial name for the "no IAnnotation" message
                (e.g. `"Datum tag"`).
            position_noun: Mid-sentence name for the "could not set …
                position" message (e.g. `"datum tag"`).
            context: Caller identification for the log lines.
            data: The caller's result payload -- `data["name"]` is set here.

        Returns:
            `(annotation, None)` on success, or `(None, error_dict)`.
        """
        try:
            annotation = owner.GetAnnotation()
        except Exception as e:
            logger.warning(f"{context} GetAnnotation error: {e}")
            annotation = None

        if x is not None:
            if annotation is None:
                return None, self._result(
                    False, f"{noun} has no IAnnotation wrapper (GetAnnotation returned nothing) "
                    "-- cannot set position", SwErrors.swFeatureError, data,
                )
            try:
                x_m, y_m = self._units.to_meters(x), self._units.to_meters(y)
                positioned = annotation.SetPosition2(x_m, y_m, 0.0)
            except Exception as e:
                logger.error(f"{context} SetPosition2 error: {e}")
                return None, self._result(
                    False, f"Set position error: {e}", SwErrors.swFeatureError, data,
                )
            if positioned is False:
                return None, self._result(
                    False, f"Could not set {position_noun} position (SetPosition2 returned False)",
                    SwErrors.swFeatureError, data,
                )

        data["name"] = self._read_prop(annotation, "GetName") if annotation is not None else None
        return annotation, None

    def _note_data(self, annotation: Any, view_name: Optional[str],
                    height: Optional[float], angle: float, bold: bool, italic: bool,
                    layer: Optional[str]) -> Dict:
        """Best-effort result payload shared by `add_note`/`add_property_note`
        -- name/position read back from `annotation` (via `IAnnotation::
        GetName`/`GetPosition`, both meters on the wire), everything else
        just the caller's own (already-validated) arguments."""
        name, x, y = self._annotation_name_position(annotation)

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
            activated = self.select_view_by_name(view_name, doc=doc)
            if not activated["success"]:
                return activated

        text_string = self._format_note_text(text, bold, italic)
        note, create_err = self._create_note_object(doc, text_string, x, y, height, angle)
        if create_err:
            return create_err

        annotation, finalize_err = self._finalize_note(note, leader_parsed, layer)
        if finalize_err:
            return finalize_err

        data = self._note_data(annotation, view_name, height, angle, bold, italic, layer)
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
            activated = self.select_view_by_name(view_name, doc=doc)
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

        data = self._note_data(annotation, view_name, height, angle, bold, italic, layer)
        data.update({
            "source": source_key, "property_name": property_name, "linked_text": linked_text,
        })
        return self._result(True, f"Added property note linking {property_name!r} ({source_key})",
                             SwErrors.swSuccess, data)

    # ------------------------------------------------------------------
    # Note discovery / editing
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_com_chain(owner: Any, first_method: str, next_method: str, context: str):
        """Walk a SolidWorks `GetFirstX()` / `X.GetNext()` linked list.

        Every annotation family in this API is enumerated the same way: one
        `GetFirstX` off the owner, then `GetNext` off each element until it
        returns null. A COM failure at either end is logged and ends the
        walk rather than propagating, so one unreadable element can't fail a
        whole listing -- the same best-effort convention
        `list_view_entities`'s `_entity_point` uses.

        Args:
            owner: The object exposing `first_method` (an `IDrawingDoc` for
                views, an `IView` for the annotations attached to it).
            first_method: `"GetFirstNote"`, `"GetFirstDatumTag"`, ...
            next_method: `"GetNext"` for annotations; `IView` spells its own
                `"GetNextView"`.
            context: Caller name, used only in the warning messages.
        """
        head, _head_err = DrawingOperations._com_chain_head(owner, first_method, context)
        return DrawingOperations._iter_com_chain_from(head, next_method, context)

    @staticmethod
    def _com_chain_head(owner: Any, first_method: str, context: str) -> Tuple[Any, Optional[Exception]]:
        """`GetFirstX()` on its own, returning `(head, error)` with the COM
        failure handed back instead of swallowed.

        `_iter_com_chain`'s best-effort walk deliberately conflates "the chain
        is empty" with "that member blew up", which is right for a listing.
        It is wrong for a caller whose answer changes between the two --
        `remove_center_marks`, because `IView::GetFirstCenterMark2` is
        SOLIDWORKS 2025 SP01+ (see `_iter_view_center_marks`), and a swallowed
        "member not found" there reads back to the user as "the view is
        already clean" while every center mark is still on the sheet.
        """
        try:
            return getattr(owner, first_method)(), None
        except Exception as e:
            logger.warning(f"{context}: {first_method} failed: {e}")
            return None, e

    @staticmethod
    def _iter_com_chain_from(head: Any, next_method: str, context: str):
        """Walk on from an already-fetched chain head -- the tail shared by
        `_iter_com_chain` and any caller that probed the head itself via
        `_com_chain_head`."""
        item = head
        while item is not None:
            yield item
            try:
                nxt = getattr(item, next_method)()
            except Exception as e:
                logger.warning(f"{context}: {next_method} failed: {e}")
                nxt = None
            item = nxt if nxt else None

    def _iter_document_views(self, doc):
        """Walk every view in the document via `IDrawingDoc::GetFirstView` /
        `IView::GetNextView` -- per docs/api/03-annotations.md's "Note
        enumeration" record, `GetFirstView` returns the active sheet's own
        pseudo/template view first (where sheet-level/title-block notes
        live), then `GetNextView` walks every real view, then the next
        sheet's own pseudo-view, and so on across the whole document."""
        return self._iter_com_chain(doc, "GetFirstView", "GetNextView",
                                    "_iter_document_views")

    def _iter_view_notes(self, view):
        """Walk every note attached to `view` via `IView::GetFirstNote` /
        `INote::GetNext`."""
        return self._iter_com_chain(view, "GetFirstNote", "GetNext",
                                    "_iter_view_notes")

    def _describe_note(self, note: Any, view_name: Optional[str]) -> Dict:
        """`list_notes`/`edit_note`'s per-note description: text, position,
        layer, and the view it was found on."""
        try:
            annotation = note.GetAnnotation()
        except Exception:
            annotation = None

        name, x, y = self._annotation_name_position(annotation)
        layer = self._read_prop(annotation, "Layer") if annotation is not None else None

        is_compound = bool(self._read_prop(note, "IsCompoundNote"))
        text = self._read_prop(note, "GetText")

        return {
            "name": name, "text": text, "is_compound": is_compound,
            "x": x, "y": y, "layer": layer or None, "view_name": view_name,
        }

    def _scoped_views(self, doc, sheet_name: Optional[str], op: str,
                       label: str) -> Tuple[Optional[List[Tuple[Any, Any]]], Optional[Dict]]:
        """Resolve the `(view, view_name)` pairs a document-wide annotation
        listing should walk, honouring an optional `sheet_name` scope.

        Shared by `list_notes`/`list_datums`, which enumerate different
        annotation families over the identical view set: every view in the
        document when `sheet_name` is omitted, else that sheet's own real
        views plus its sheet-level pseudo-view (where title-block
        annotations live -- see `_iter_document_views`).

        `_is_sheet_pseudo_view` is a COM `Type` read, so it is deliberately
        the right-hand side of the `or`: it only costs a round-trip for the
        one view whose name actually matches `sheet_name`.

        Args:
            op: Calling method name, for the log line only.
            label: Human-facing prefix for the returned error message.

        Returns:
            `(pairs, None)` on success, or `(None, error_dict)`.
        """
        allowed_view_names = None
        if sheet_name:
            sheet, err = self._resolve_sheet(doc, sheet_name)
            if err:
                return None, err
            try:
                views_raw = sheet.GetViews() or []
            except Exception as e:
                logger.error(f"{op}(sheet_name={sheet_name!r}) error: {e}")
                return None, self._result(
                    False, f"{label} error: {e}", SwErrors.swUnknownError,
                )
            allowed_view_names = {
                self._read_prop(v, "GetName2") for v in views_raw
                if self._read_prop(v, "GetName2")
            }

        scoped: List[Tuple[Any, Any]] = []
        for view in self._iter_document_views(doc):
            v_name = self._read_prop(view, "GetName2")
            if allowed_view_names is not None and not (
                v_name in allowed_view_names
                or (v_name == sheet_name and self._is_sheet_pseudo_view(view))
            ):
                continue
            scoped.append((view, v_name))
        return scoped, None

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
            activated = self.select_view_by_name(view_name, doc=doc)
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

        scoped, err = self._scoped_views(doc, sheet_name, "list_notes", "List notes")
        if err:
            return err

        for view, v_name in scoped:
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
                                          label: str, require_datum: bool = True) -> Optional[Dict]:
        """Enforce ASME Y14.5's datum-reference rules for `symbol_key`: form
        tolerances (`_GTOL_FORM_SYMBOLS`) must NOT reference a datum;
        orientation/location/runout tolerances (`_GTOL_DATUM_REQUIRED_SYMBOLS`)
        must reference at least one. `label` names the field in the error
        message (`"symbol"` or `"composite"`).

        `require_datum=False` keeps the form-tolerance prohibition but drops
        the at-least-one requirement -- what a composite frame's *lower*
        segment needs. In a composite FCF the upper segment is the
        pattern-locating control (PLTZF) and carries the datum references;
        the lower feature-relating segment (FRTZF) legally carries fewer, or
        none at all, when it controls only the pattern-internal relationship.
        Applying the upper segment's rule to it rejects a standard composite
        positional callout before any COM call is made.
        """
        if symbol_key in _GTOL_FORM_SYMBOLS and datum_entries:
            return self._result(
                False,
                f"{symbol_key!r} is a form tolerance and cannot reference a datum "
                f"({label})",
                SwErrors.swInvalidInput, {"symbol": symbol_key, "datums": datum_entries},
            )
        if require_datum and symbol_key in _GTOL_DATUM_REQUIRED_SYMBOLS and not datum_entries:
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
        return self._iter_com_chain(view, "GetFirstDatumTag", "GetNext",
                                    "_iter_view_datum_tags")

    def _describe_datum(self, tag: Any, view_name: Optional[str]) -> Dict:
        """`list_datums`'s per-tag description: label, position, and the
        view it was found on -- mirrors `_describe_note`'s shape."""
        try:
            annotation = tag.GetAnnotation()
        except Exception:
            annotation = None

        label = self._read_prop(tag, "GetLabel")
        name, x, y = self._annotation_name_position(annotation)

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

        scoped, err = self._scoped_views(doc, sheet_name, "list_datums", "List datums")
        if err:
            return err

        datums: List[Dict] = []
        for view, v_name in scoped:
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
        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err

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

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "label": label_final, "x": x, "y": y, "style": style_key,
        }

        with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
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

            _, place_err = self._place_annotation(
                tag, x, y, "Datum tag", "datum tag",
                f"add_datum_feature({view_name!r})", data,
            )
            if place_err:
                return place_err

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
            # The lower (feature-relating) segment of a composite frame may
            # legally carry no datum references at all -- see
            # `_validate_gtol_datum_requirement`'s own docstring.
            req_err = self._validate_gtol_datum_requirement(
                symbol_key, composite_entries, "composite", require_datum=False)
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
        if x is not None:
            xy_err = self._validate_xy(x, y)
            if xy_err:
                return xy_err

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

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        # Only walk the document's datum tags if this frame actually
        # references one. The form tolerances (flatness, straightness,
        # circularity, cylindricity) are *forbidden* datums by
        # `_validate_gtol_datum_requirement` above, so for them the walk --
        # every view on every sheet, several COM calls per tag -- would be
        # a full-document enumeration whose result is discarded.
        requested_letters = {letter for letter, _ in datum_entries + composite_entries}
        if requested_letters:
            existing = self.list_datums()
            if not existing["success"]:
                return existing
            existing_letters = set(existing["data"]["letters"])

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
            with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
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

        _, place_err = self._place_annotation(
            gtol_obj, x, y, "GTol", "GTol", f"add_gtol({view_name!r})", data,
        )
        if place_err:
            return place_err

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
        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "label": label, "area_type": area_key, "size": size,
            "x": x, "y": y,
        }

        with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
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

            _, place_err = self._place_annotation(
                created, x, y, "Datum target", "datum target",
                f"add_datum_target({view_name!r})", data,
            )
            if place_err:
                return place_err

        return self._result(True, f"Added datum target {label!r}", SwErrors.swSuccess, data)

    # ------------------------------------------------------------------
    # Surface finish and weld symbols
    # ------------------------------------------------------------------

    def add_surface_finish(self, view_name: str, entity: Dict[str, Any], x: float, y: float,
                            symbol_type: str = "basic", roughness_max: Optional[float] = None,
                            roughness_min: Optional[float] = None,
                            machining_allowance: Optional[str] = None,
                            lay_direction: Optional[str] = None,
                            production_method: Optional[str] = None,
                            all_around: bool = False) -> Dict:
        """
        Add a surface finish symbol via `IModelDocExtension::
        InsertSurfaceFinishSymbol3`.

        Args:
            view_name: Drawing view the entity lives in.
            entity: Entity reference in the shape `list_view_entities`
                returns -- an edge, face, or vertex per the dossier's own
                "Prior selection required" note.
            x, y: Symbol placement, caller's default unit -- converted to
                meters and passed as `InsertSurfaceFinishSymbol3`'s `LocX`/
                `LocY` creation-time parameters. Honored because
                `add_surface_finish` always creates with a straight leader
                (never `swNO_LEADER`) -- see that method's own dossier
                Gotchas ("LocX/LocY/LocZ are silently ignored unless
                LeaderType != swNO_LEADER").
            symbol_type: `"basic"`, `"machining_required"`, or
                `"machining_prohibited"` -- see `_SF_SYMBOL_TYPES`.
            roughness_max, roughness_min: Optional roughness values -- the
                caller's own numbers formatted as COM display-text strings
                via `_format_gtol_number` (NOT converted to meters;
                `MaxRoughness`/`MinRoughness` are `String`-typed COM
                parameters with no documented unit, the same open ambiguity
                `add_gtol`'s `tolerance` flags). If both are given,
                `roughness_min` must be <= `roughness_max`.
            machining_allowance: Optional material-removal-allowance display
                text (`MachAllowance`).
            lay_direction: Optional direction-of-lay symbol -- see
                `_SF_LAY_DIRECTIONS`. Omitted: no lay symbol (`swSFNone`).
            production_method: Optional production-method/treatment display
                text (`ProdMethod`).
            all_around: `True` to enable the all-around leader symbol via
                `IAnnotation::SetLeader3` -- see the sw-1xx.5 dossier
                addendum's "all-around" discrepancy note for why this uses
                `SetLeader3` rather than a dedicated setter (unlike
                `add_weld_symbol`, which has one). Two side effects worth
                knowing: `SetLeader3` rewrites the *whole* leader, so the
                symbol's leader changes from the straight one bound at
                creation to `swBENT`; and it is passed
                `_LEADER_SIDE_DEFAULT`, whose `swLeaderSide_e` mapping this
                module documents as an unverified guess -- a build where `0`
                is not a valid side answers `-2` and fails the call *after*
                the symbol is already committed to the sheet (this module
                does not roll back post-creation setter failures anywhere;
                re-calling stacks a duplicate symbol rather than replacing).

        Returns:
            Result dict. `data["name"]` is `IAnnotation::GetName`'s value,
            read back best-effort.
        """
        symbol_key = (symbol_type or "").strip().lower() if isinstance(symbol_type, str) else ""
        sym_type_enum = _SF_SYMBOL_TYPES.get(symbol_key)
        if sym_type_enum is None:
            return self._result(
                False,
                f"Unknown symbol_type {symbol_type!r}; expected one of {sorted(_SF_SYMBOL_TYPES)!r}",
                SwErrors.swInvalidInput, {"symbol_type": symbol_type},
            )

        if lay_direction is None:
            lay_key = "none"
        elif isinstance(lay_direction, str):
            lay_key = lay_direction.strip().lower()
        else:
            lay_key = ""
        lay_symbol_enum = _SF_LAY_DIRECTIONS.get(lay_key)
        if lay_symbol_enum is None:
            return self._result(
                False,
                f"Unknown lay_direction {lay_direction!r}; expected one of "
                f"{sorted(_SF_LAY_DIRECTIONS)!r}",
                SwErrors.swInvalidInput, {"lay_direction": lay_direction},
            )

        parsed_entity, entity_err = _parse_entity_ref(entity)
        if entity_err:
            return self._result(
                False, f"entity: {entity_err}", SwErrors.swInvalidInput, {"entity": entity},
            )

        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err

        for label, value in (("roughness_max", roughness_max), ("roughness_min", roughness_min)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                return self._result(
                    False, f"{label} must be a number, got {value!r}", SwErrors.swInvalidInput,
                    {label: value},
                )
        if roughness_max is not None and roughness_min is not None and roughness_min > roughness_max:
            return self._result(
                False,
                f"roughness_min ({roughness_min!r}) must be <= roughness_max ({roughness_max!r})",
                SwErrors.swInvalidInput,
                {"roughness_min": roughness_min, "roughness_max": roughness_max},
            )

        for label, value in (("machining_allowance", machining_allowance),
                              ("production_method", production_method)):
            if value is not None and not isinstance(value, str):
                return self._result(
                    False, f"{label} must be a string, got {value!r}", SwErrors.swInvalidInput,
                    {label: value},
                )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        data = {
            "view_name": view_name, "symbol_type": symbol_key, "lay_direction": lay_key,
            "x": x, "y": y, "all_around": bool(all_around),
        }

        with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
            if not sel["success"]:
                return sel

            try:
                args = INSERT_SURFACE_FINISH_SYMBOL3.bind(
                    units=self._units, sym_type=sym_type_enum, loc_x=x, loc_y=y,
                    lay_symbol=lay_symbol_enum,
                    mach_allowance=machining_allowance or "",
                    prod_method=production_method or "",
                    max_roughness=(
                        self._format_gtol_number(roughness_max) if roughness_max is not None else ""
                    ),
                    min_roughness=(
                        self._format_gtol_number(roughness_min) if roughness_min is not None else ""
                    ),
                )
                created = doc.Extension.InsertSurfaceFinishSymbol3(*args)
            except Exception as e:
                logger.error(f"add_surface_finish({view_name!r}) InsertSurfaceFinishSymbol3 error: {e}")
                return self._result(
                    False, f"Insert surface finish symbol error: {e}", SwErrors.swFeatureError, data,
                )
            if created is None:
                return self._result(
                    False,
                    "InsertSurfaceFinishSymbol3 returned nothing -- surface finish symbol not created",
                    SwErrors.swFeatureError, data,
                )

            try:
                annotation = created.GetAnnotation()
            except Exception as e:
                logger.warning(f"add_surface_finish({view_name!r}) GetAnnotation error: {e}")
                annotation = None

            if all_around:
                if annotation is None:
                    return self._result(
                        False,
                        "Surface finish symbol has no IAnnotation wrapper (GetAnnotation "
                        "returned nothing) -- cannot set all-around leader",
                        SwErrors.swFeatureError, data,
                    )
                try:
                    status = annotation.SetLeader3(
                        int(SwLeaderStyle.swBENT), _LEADER_SIDE_DEFAULT, True, False, True, False,
                    )
                except Exception as e:
                    logger.error(f"add_surface_finish({view_name!r}) SetLeader3 error: {e}")
                    return self._result(
                        False, f"Set all-around leader error: {e}", SwErrors.swFeatureError, data,
                    )
                status_code = int(status) if isinstance(status, (int, float)) else None
                if status_code != 0:
                    return self._result(
                        False, f"Could not set all-around leader (SetLeader3 status {status_code})",
                        SwErrors.swFeatureError, {**data, "status_code": status_code},
                    )

            data["name"] = self._read_prop(annotation, "GetName") if annotation is not None else None

        return self._result(
            True,
            f"Added {symbol_key} surface finish symbol" + (f" {data['name']!r}" if data["name"] else ""),
            SwErrors.swSuccess, data,
        )

    def add_weld_symbol(self, view_name: str, entity: Dict[str, Any], x: float, y: float,
                         symbol: str = "fillet", size: Optional[float] = None,
                         length: Optional[float] = None, pitch: Optional[float] = None,
                         contour: Optional[str] = None, field_weld: bool = False,
                         all_around: bool = False, both_sides: bool = False,
                         other_side_symbol: Optional[str] = None,
                         tail_text: Optional[str] = None) -> Dict:
        """
        Add an ISO-style weld symbol via `IModelDoc2::InsertWeldSymbol3` +
        `IWeldSymbol::SetText` (and content setters). `SetText`'s own Remarks
        state its `Symbol` parameter only accepts "currently supported ISO
        weld symbols" -- not AWS/ANSI ones -- see the sw-1xx.5 dossier
        addendum's "Top parameter and drafting-standard dependence" record.

        Args:
            view_name: Drawing view the entity lives in.
            entity: Entity reference in the shape `list_view_entities`
                returns -- an edge or face per the dossier's own official
                worked example's selection precondition.
            x, y: Symbol placement, caller's default unit -- converted to
                meters and applied via `IAnnotation::SetPosition2` after
                creation (`InsertWeldSymbol3` itself takes no position
                parameters, unlike `InsertSurfaceFinishSymbol3`).
            symbol: Arrow-side ("this side") weld symbol -- a friendly alias
                (`_WELD_SYMBOL_ALIASES`) or a raw ISO code
                (`_WELD_SYMBOL_CODES`), case-insensitive. Sent via `SetText`'s
                `Symbol` with `Top=True`; `Top`'s own documented meaning is
                "above the horizontal line", which this project maps to
                "arrow side" per the ISO drafting-standard default
                (`HIDD_WELD.htm`) -- see the sw-1xx.5 dossier addendum for
                the standard-dependence caveat.
            size: Optional weld size, displayed to the left of the symbol
                (`SetText`'s `Left`) -- the caller's own number formatted as
                display text via `_format_gtol_number`, the same
                NOT-converted-to-meters convention as `add_gtol`'s
                `tolerance`.
            length, pitch: Optional intermittent-weld length/pitch,
                displayed to the right of the symbol (`SetText`'s `Right`)
                as `"{length}-{pitch}"` per `HIDD_WELD.htm`'s documented
                "Length-Pitch" format. Both-or-neither.
            contour: Optional `"none"`/`"flat"`/`"convex"`/`"concave"`
                (`SetText`'s `Contour`, `swWeldSymbolContourTypes_e`).
                Omitted: `"none"`.
            field_weld: `True` to add a field/site weld marking via
                `IWeldSymbol::SetFieldWeld` (always `swFieldWeldUp` -- see
                the sw-1xx.5 dossier addendum for why this boolean only
                exposes that one orientation).
            all_around: `True` to enable the all-around (peripheral) weld
                symbol via `IWeldSymbol::SetPeripheral`.
            both_sides: `True` to mirror arrow-side content to the other
                side via `IWeldSymbol::SetSymmetric` (`swWeldSymmetric`).
                `False` skips the call entirely rather than picking a
                default among the two non-symmetric variants.
            other_side_symbol: Optional other-side weld symbol -- same
                accepted shapes as `symbol`. Applied via a second `SetText`
                call with `Top=False`.
            tail_text: Optional tail (specification/process) text via
                `IWeldSymbol::SetProcess`.

        Returns:
            Result dict. `data["name"]` is `IAnnotation::GetName`'s value,
            read back best-effort.
        """
        symbol_code, symbol_err = _resolve_weld_symbol(symbol, "symbol")
        if symbol_err:
            return self._result(False, symbol_err, SwErrors.swInvalidInput, {"symbol": symbol})

        other_code = None
        if other_side_symbol is not None:
            other_code, other_err = _resolve_weld_symbol(other_side_symbol, "other_side_symbol")
            if other_err:
                return self._result(
                    False, other_err, SwErrors.swInvalidInput,
                    {"other_side_symbol": other_side_symbol},
                )

        if contour is None:
            contour_key = "none"
        elif isinstance(contour, str):
            contour_key = contour.strip().lower()
        else:
            contour_key = ""
        contour_enum = _WELD_CONTOURS.get(contour_key)
        if contour_enum is None:
            return self._result(
                False, f"Unknown contour {contour!r}; expected one of {sorted(_WELD_CONTOURS)!r}",
                SwErrors.swInvalidInput, {"contour": contour},
            )

        parsed_entity, entity_err = _parse_entity_ref(entity)
        if entity_err:
            return self._result(
                False, f"entity: {entity_err}", SwErrors.swInvalidInput, {"entity": entity},
            )

        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err

        if size is not None and (
            isinstance(size, bool) or not isinstance(size, (int, float)) or size < 0
        ):
            return self._result(
                False, f"size must be a non-negative number, got {size!r}", SwErrors.swInvalidInput,
                {"size": size},
            )

        if (length is None) != (pitch is None):
            return self._result(
                False, "length and pitch must both be given or both omitted",
                SwErrors.swInvalidInput, {"length": length, "pitch": pitch},
            )
        for label, value in (("length", length), ("pitch", pitch)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
            ):
                return self._result(
                    False, f"{label} must be a non-negative number, got {value!r}",
                    SwErrors.swInvalidInput, {label: value},
                )

        if tail_text is not None and not isinstance(tail_text, str):
            return self._result(
                False, f"tail_text must be a string, got {tail_text!r}", SwErrors.swInvalidInput,
                {"tail_text": tail_text},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        type_str, ex, ey, ez = parsed_entity
        left_text = self._format_gtol_number(size) if size is not None else ""
        right_text = (
            f"{self._format_gtol_number(length)}-{self._format_gtol_number(pitch)}"
            if length is not None else ""
        )
        data = {
            "view_name": view_name, "symbol": symbol_code, "other_side_symbol": other_code,
            "contour": contour_key, "field_weld": bool(field_weld), "all_around": bool(all_around),
            "both_sides": bool(both_sides), "x": x, "y": y,
        }

        with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
            if not sel["success"]:
                return sel

            try:
                weld = doc.InsertWeldSymbol3()
            except Exception as e:
                logger.error(f"add_weld_symbol({view_name!r}) InsertWeldSymbol3 error: {e}")
                return self._result(False, f"Insert weld symbol error: {e}", SwErrors.swFeatureError, data)
            if weld is None:
                return self._result(
                    False, "InsertWeldSymbol3 returned nothing -- weld symbol not created",
                    SwErrors.swFeatureError, data,
                )

            try:
                set_ok = weld.SetText(True, left_text, symbol_code, right_text, "", contour_enum)
            except Exception as e:
                logger.error(f"add_weld_symbol({view_name!r}) SetText error: {e}")
                return self._result(False, f"Set weld text error: {e}", SwErrors.swFeatureError, data)
            if set_ok is False:
                return self._result(
                    False, "Could not set weld symbol text (SetText returned False)",
                    SwErrors.swFeatureError, data,
                )

            if other_code is not None:
                try:
                    other_ok = weld.SetText(False, "", other_code, "", "", contour_enum)
                except Exception as e:
                    logger.error(f"add_weld_symbol({view_name!r}) SetText (other side) error: {e}")
                    return self._result(
                        False, f"Set other-side weld text error: {e}", SwErrors.swFeatureError, data,
                    )
                if other_ok is False:
                    return self._result(
                        False, "Could not set other-side weld symbol text (SetText returned False)",
                        SwErrors.swFeatureError, data,
                    )

            if field_weld:
                try:
                    fw_ok = weld.SetFieldWeld(int(SwWeldSymbolField.swFieldWeldUp))
                except Exception as e:
                    logger.error(f"add_weld_symbol({view_name!r}) SetFieldWeld error: {e}")
                    return self._result(False, f"Set field weld error: {e}", SwErrors.swFeatureError, data)
                if fw_ok is False:
                    return self._result(
                        False, "Could not set field weld (SetFieldWeld returned False)",
                        SwErrors.swFeatureError, data,
                    )

            if all_around:
                try:
                    peripheral_ok = weld.SetPeripheral(True)
                except Exception as e:
                    logger.error(f"add_weld_symbol({view_name!r}) SetPeripheral error: {e}")
                    return self._result(
                        False, f"Set all-around weld error: {e}", SwErrors.swFeatureError, data,
                    )
                if peripheral_ok is False:
                    return self._result(
                        False, "Could not set all-around weld (SetPeripheral returned False)",
                        SwErrors.swFeatureError, data,
                    )

            if both_sides:
                try:
                    sym_ok = weld.SetSymmetric(int(SwWeldSymbolSymmetric.swWeldSymmetric))
                except Exception as e:
                    logger.error(f"add_weld_symbol({view_name!r}) SetSymmetric error: {e}")
                    return self._result(
                        False, f"Set symmetric weld error: {e}", SwErrors.swFeatureError, data,
                    )
                if sym_ok is False:
                    return self._result(
                        False, "Could not set symmetric weld (SetSymmetric returned False)",
                        SwErrors.swFeatureError, data,
                    )

            if tail_text:
                try:
                    proc_ok = weld.SetProcess(True, tail_text, False)
                except Exception as e:
                    logger.error(f"add_weld_symbol({view_name!r}) SetProcess error: {e}")
                    return self._result(False, f"Set tail text error: {e}", SwErrors.swFeatureError, data)
                if proc_ok is False:
                    return self._result(
                        False, "Could not set tail text (SetProcess returned False)",
                        SwErrors.swFeatureError, data,
                    )

            _, place_err = self._place_annotation(
                weld, x, y, "Weld symbol", "weld symbol",
                f"add_weld_symbol({view_name!r})", data,
            )
            if place_err:
                return place_err

        return self._result(
            True, f"Added {symbol_code} weld symbol" + (f" {data['name']!r}" if data["name"] else ""),
            SwErrors.swSuccess, data,
        )

    # ========================================================================
    # Center mark / centerline tools (sw-1xx.6)
    # ========================================================================

    def _view_center_marks(self, view: Any) -> Tuple[Optional[List[Any]], Optional[Exception]]:
        """Every center mark in `view` via `IView::GetFirstCenterMark2` /
        `ICenterMark::GetNext` -- the center-mark analog of `_iter_view_notes`'s
        `GetFirstNote`/`GetNext` walk (sw-1xx.3) and `_iter_view_datum_tags`'s
        `GetFirstDatumTag`/`GetNext` walk (sw-1xx.4), per the sw-1xx.6 dossier
        addendum.

        Unlike those two this is *eager* and returns `(marks, error)` rather
        than a lazy generator, for two reasons its caller
        (`remove_center_marks`) can't do without:

        - The whole chain must be walked before the first `DeleteSelection2`,
          since a deleted COM object's own `GetNext` is not guaranteed to
          still answer (see the `ICenterMark::GetNext` dossier record).
        - `GetFirstCenterMark2` is SOLIDWORKS 2025 SP01+ (see that addendum
          record's Gotchas for the obsolete pre-2025-SP01 predecessor), so a
          failure on that member has to be distinguishable from an empty
          view instead of being swallowed into "0 removed".
        """
        head, head_err = self._com_chain_head(view, "GetFirstCenterMark2", "_view_center_marks")
        if head_err is not None:
            return None, head_err
        return list(self._iter_com_chain_from(head, "GetNext", "_view_center_marks")), None

    def _find_circular_edges(
        self, view: Any,
    ) -> Tuple[Optional[List[Tuple[str, float, float, float]]], Optional[str]]:
        """`add_center_marks`' `target="all_holes"` discovery: every visible
        edge in `view` (`IView::GetVisibleEntities2`, entity type `1` -- edges,
        the same convention `list_view_entities`'s `_VIEW_ENTITY_TYPES` uses)
        whose underlying curve is a circle (`IEdge::GetCurve().IsCircle()`,
        sw-1xx.6 dossier addendum).

        Returns `(edges, None)` where `edges` is a list of `("EDGE", x, y, z)`
        tuples in the caller's default unit -- exactly the shape
        `_parse_entity_ref` produces for an explicit entity reference, so both
        `target` modes feed the same creation loop. An edge whose curve or
        point can't be read is skipped (logged), not fatal to the whole
        enumeration -- same best-effort convention `list_view_entities`'s
        `_entity_point` already uses.

        A failure of the *enumeration itself* returns `(None, message)`
        instead: "this view has no holes" and "this view was never
        successfully read" are opposite answers, and collapsing the second
        into an empty list would report the silent-success the issue's own
        Requirements call out ("a view with no circular geometry returns
        success with count=0" is only true when the view really was read).

        Caveat, inherited from `list_view_entities`: `_entity_point` reports
        the *model's* coordinates, while a drawing's `select_by_id` resolves
        an empty `name` against *sheet* space. On a view whose position/scale
        makes those differ, the points returned here will not select -- see
        `list_view_entities`' own docstring; a model-to-sheet transform
        helper is still missing. `add_center_marks` fails loudly
        (`swFeatureError`, "could not create any") rather than silently when
        that happens.
        """
        try:
            component = view.RootDrawingComponent
            edges = view.GetVisibleEntities2(component, _VIEW_ENTITY_TYPES["edge"]) or []
        except Exception as e:
            logger.warning(f"_find_circular_edges: GetVisibleEntities2 failed: {e}")
            return None, str(e)

        found: List[Tuple[str, float, float, float]] = []
        for edge in edges:
            try:
                curve = edge.GetCurve()
                is_circle = bool(curve.IsCircle()) if curve is not None else False
            except Exception as e:
                logger.warning(f"_find_circular_edges: IsCircle check failed: {e}")
                continue
            if not is_circle:
                continue
            try:
                point = self._entity_point(edge, "edge")
            except Exception as e:
                logger.warning(f"_find_circular_edges: no point for circular edge: {e}")
                continue
            found.append((
                "EDGE",
                self._units.from_meters(point[0]),
                self._units.from_meters(point[1]),
                self._units.from_meters(point[2]),
            ))
        return found, None

    def add_center_marks(self, view_name: str, target: Any = "all_holes",
                          style: str = "single", size: Optional[float] = None,
                          extended_lines: bool = True, slot_center_marks: bool = True,
                          connection_lines: bool = False) -> Dict:
        """
        Batch-apply center marks to circular holes in a drawing view via
        `IDrawingDoc::InsertCenterMark3` -- one COM call per hole (there is
        no array/batch creation call for this per-edge API; `IView::
        AutoInsertCenterMarks2` is a separate, preference-driven UI-automation
        path, not this project's own reproducible batch tool -- see the
        dossier's own `InsertCenterMark3` Gotchas). Selection is atomic per
        hole via `self.selected(...)`.

        Args:
            view_name: Drawing view to mark. Activated via
                `select_view_by_name`.
            target: `"all_holes"` (default) -- every circular edge in the
                view, found via `IView::GetVisibleEntities2` + `IEdge::
                GetCurve().IsCircle()` (`_find_circular_edges`, sw-1xx.6
                dossier addendum). Or an explicit list of entity references
                in the shape `list_view_entities` returns (`{"kind": "edge",
                "x", "y", "z"}`).
            style: `"non_annotation"`, `"single"` (default), `"linear_group"`,
                or `"circular_group"` -- `_CENTER_MARK_STYLES`
                (`swCenterMarkStyle_e`).
            size: Optional line length for every created mark, caller's
                default unit -- converted to meters and assigned to
                `ICenterMark::Size` after creation (dossier: unit unstated on
                that property's own page, treated as meters per this
                project's API-wide convention). Omitted: SolidWorks' own
                default size is left alone.
            extended_lines: `True` (default) to show each mark's extension
                lines (`ICenterMark::ShowLines`).
            slot_center_marks: `InsertCenterMark3`'s own `Slot` parameter,
                applied uniformly to every mark in this batch -- `True`
                (default) per the issue's own default.
            connection_lines: `True` to show a circular connection line
                grouping the marks (`ICenterMark::ConnectionLines`) --
                `False` (default). See `_CENTER_MARK_CONNECTION_LINES`'s own
                comment for this project's bool -> bitmask convention.

        Returns:
            Result dict. `data["count"]` is how many marks were created. A
            view with no circular geometry (or an empty explicit `target`
            list) is a warned success with `count: 0`, not an error -- per
            the issue's own Requirements. `InsertCenterMark3`'s `Propagate`
            argument is always bound `False`: this batch walk already marks
            each hole individually, so pattern propagation would double-mark
            siblings.
        """
        style_key = (style or "").strip().lower() if isinstance(style, str) else ""
        style_enum = _CENTER_MARK_STYLES.get(style_key)
        if style_enum is None:
            return self._result(
                False, f"Unknown style {style!r}; expected one of {sorted(_CENTER_MARK_STYLES)!r}",
                SwErrors.swInvalidInput, {"style": style},
            )

        if size is not None and (
            isinstance(size, bool) or not isinstance(size, (int, float)) or size < 0
        ):
            return self._result(
                False, f"size must be a non-negative number, got {size!r}", SwErrors.swInvalidInput,
                {"size": size},
            )

        connection_key = bool(connection_lines)
        connection_enum = _CENTER_MARK_CONNECTION_LINES[connection_key]

        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        data = {
            "view_name": view_name,
            "target": target if isinstance(target, str) else "explicit",
            "style": style_key, "size": size, "extended_lines": bool(extended_lines),
            "slot_center_marks": bool(slot_center_marks), "connection_lines": connection_key,
        }

        if isinstance(target, str):
            if target.strip().lower() != "all_holes":
                return self._result(
                    False,
                    f"Unknown target {target!r}; expected 'all_holes' or a list of entity references",
                    SwErrors.swInvalidInput, data,
                )
            try:
                view = doc.ActiveDrawingView
            except Exception as e:
                logger.error(f"add_center_marks({view_name!r}) error: {e}")
                return self._result(
                    False, f"Add center marks error: {e}", SwErrors.swSelectionError, data,
                )
            candidates, find_err = self._find_circular_edges(view)
            if find_err is not None:
                # Not an empty view -- the enumeration itself failed, so
                # reporting the "0 circular edges, warned success" below would
                # tell the caller the view has no holes when it was never read.
                return self._result(
                    False,
                    f"Could not enumerate geometry in view {view_name!r}: {find_err}",
                    SwErrors.swSelectionError, data,
                )
        elif isinstance(target, (list, tuple)):
            candidates = []
            for i, entity in enumerate(target):
                parsed, entity_err = _parse_entity_ref(entity)
                if entity_err:
                    return self._result(
                        False, f"target[{i}]: {entity_err}", SwErrors.swInvalidInput, data,
                    )
                candidates.append(parsed)
        else:
            return self._result(
                False,
                f"target must be 'all_holes' or a list of entity references, got {target!r}",
                SwErrors.swInvalidInput, data,
            )

        if not candidates:
            data["count"] = 0
            return self._result(
                True,
                f"No circular geometry found in view {view_name!r} -- 0 center marks created",
                SwErrors.swSuccess, data,
            )

        created_count = 0
        unstyled_count = 0
        for type_str, ex, ey, ez in candidates:
            with self.selected("", type_str, ex, ey, ez, doc=doc) as sel:
                if not sel["success"]:
                    continue
                try:
                    mark = doc.InsertCenterMark3(style_enum, False, bool(slot_center_marks))
                except Exception as e:
                    logger.warning(f"add_center_marks({view_name!r}) InsertCenterMark3 error: {e}")
                    mark = None
                if mark is None:
                    continue
                try:
                    if size is not None:
                        mark.Size = self._units.to_meters(size)
                    mark.ShowLines = bool(extended_lines)
                    mark.ConnectionLines = connection_enum
                except Exception as e:
                    logger.warning(
                        f"add_center_marks({view_name!r}) center mark display-setting error: {e}"
                    )
                    # The mark itself exists, so this is not a creation
                    # failure -- but `data["size"]`/`["extended_lines"]`/
                    # `["connection_lines"]` would otherwise echo settings
                    # that never reached SolidWorks, so it is counted and
                    # surfaced rather than only logged.
                    unstyled_count += 1
                created_count += 1

        data["count"] = created_count
        data["unstyled"] = unstyled_count

        if created_count == 0:
            return self._result(
                False,
                f"Found {len(candidates)} candidate(s) in view {view_name!r} but could not "
                "create any center marks",
                SwErrors.swFeatureError, data,
            )

        skipped = len(candidates) - created_count
        message = f"Created {created_count} center mark(s) in view {view_name!r}"
        if skipped:
            message += f" ({skipped} candidate(s) skipped)"
        if unstyled_count:
            message += (
                f"; {unstyled_count} kept SolidWorks' default size/lines "
                "(display settings were rejected)"
            )
        if style_key in ("linear_group", "circular_group") or connection_key:
            # `InsertCenterMark3` builds a group out of everything selected at
            # the time of the call, and this batch selects exactly one edge per
            # call so each mark is placed atomically. The group styles and the
            # connection line therefore apply per mark, never across the hole
            # pattern -- said plainly here rather than letting an unqualified
            # "Created N center mark(s)" imply a bolt circle got grouped.
            message += (
                "; note: marks are created one edge at a time, so group styles "
                "and connection lines apply per mark, not across the pattern"
            )
        return self._result(True, message, SwErrors.swSuccess, data)

    def add_centerlines(self, view_name: str, target: Any = "all", select_view: bool = True) -> Dict:
        """
        Insert a centerline via `IDrawingDoc::InsertCenterLine2` -- a single
        select-then-act call whose two entities come entirely from the
        current selection (the method itself takes no parameters).

        Args:
            view_name: Drawing view to act in. Activated via
                `select_view_by_name`.
            target: `"all"` (default, requires `select_view=True`) -- select
                nothing but the view itself, letting SolidWorks auto-detect
                and insert centerlines wherever it can in that view. Or an
                explicit list of exactly 2 entity references (the shape
                `list_view_entities` returns) identifying the two parallel
                edges, or two circular/arc edges, to draw one centerline
                between -- requires `select_view=False`.
            select_view: `True` (default) to select the view object itself
                (`self.selected(view_name, "DRAWINGVIEW", ...)`) before
                calling -- requires `target="all"`. `False` to select
                `target`'s two entities instead -- requires an explicit
                2-entity `target`. A mismatched combination fails with
                `swInvalidInput` before any COM call.

        Returns:
            Result dict. `InsertCenterLine2` returns a single `ICenterLine`
            pointer (not an array or count) per its own dossier record, so
            `data["count"]` is `1` if a centerline was created, `0`
            otherwise -- this is not a true batch total, even though
            `select_view=True` may cause SolidWorks to insert more than one
            centerline internally in practice; that multi-insert behavior is
            not confirmed on `InsertCenterLine2`'s own help page (see the
            dossier's own Gotchas), so this wrapper only reports what the API
            itself documents returning. A `0` result is a warned success, not
            an error -- legitimately no eligible geometry in the view is a
            normal outcome for `select_view=True`'s auto-detect path.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        data = {"view_name": view_name, "target": target, "select_view": bool(select_view)}

        if select_view:
            if not (isinstance(target, str) and target.strip().lower() == "all"):
                return self._result(
                    False,
                    "select_view=True requires target='all' (whole-view auto-detect) -- "
                    "pass select_view=False with an explicit 2-entity target instead",
                    SwErrors.swInvalidInput, data,
                )
            with self.selected(view_name, "DRAWINGVIEW", 0, 0, 0, doc=doc) as sel:
                if not sel["success"]:
                    return sel
                try:
                    created = doc.InsertCenterLine2()
                except Exception as e:
                    logger.error(f"add_centerlines({view_name!r}) error: {e}")
                    return self._result(
                        False, f"Add centerline error: {e}", SwErrors.swFeatureError, data,
                    )
        else:
            if not isinstance(target, (list, tuple)) or len(target) != 2:
                return self._result(
                    False,
                    "select_view=False requires target to be a list of exactly 2 entity "
                    f"references, got {target!r}",
                    SwErrors.swInvalidInput, data,
                )
            parsed_entities = []
            for i, entity in enumerate(target):
                parsed, entity_err = _parse_entity_ref(entity)
                if entity_err:
                    return self._result(
                        False, f"target[{i}]: {entity_err}", SwErrors.swInvalidInput, data,
                    )
                parsed_entities.append(parsed)

            with ExitStack() as stack:
                for i, (type_str, ex, ey, ez) in enumerate(parsed_entities):
                    sel = stack.enter_context(
                        self.selected("", type_str, ex, ey, ez, append=(i > 0), mark=i, doc=doc)
                    )
                    if not sel["success"]:
                        return sel
                try:
                    created = doc.InsertCenterLine2()
                except Exception as e:
                    logger.error(f"add_centerlines({view_name!r}) error: {e}")
                    return self._result(
                        False, f"Add centerline error: {e}", SwErrors.swFeatureError, data,
                    )

        if created is None:
            data["count"] = 0
            return self._result(
                True,
                f"No centerline created in view {view_name!r} -- check that eligible "
                "geometry was selected",
                SwErrors.swSuccess, data,
            )

        data["count"] = 1
        return self._result(True, f"Created centerline in view {view_name!r}", SwErrors.swSuccess, data)

    def remove_center_marks(self, view_name: str) -> Dict:
        """
        Remove every center mark in a drawing view via select
        (`ICenterMark::Select` + `ISelectionMgr::CreateSelectData`) +
        `IModelDocExtension::DeleteSelection2` -- the same select-then-delete
        idiom `delete_sheet`/`delete_view` already use, applied one center
        mark at a time while walking `IView::GetFirstCenterMark2`/
        `ICenterMark::GetNext` (`_iter_view_center_marks`). Lets a bad batch
        from `add_center_marks` be redone without restarting the drawing.

        Args:
            view_name: Drawing view to clear. Activated via
                `select_view_by_name`.

        Returns:
            Result dict. `data["count"]` (and `data["removed"]`, an alias)
            is how many center marks were actually deleted -- counted from
            this walk's own successful `DeleteSelection2` calls, NOT from
            `IView::GetCenterMarkCount2` (that method only counts old
            feature-style center marks and can under-report the current
            annotation-style kind this project creates -- see the sw-1xx.6
            dossier addendum's Gotchas). A view with no center marks is a
            warned success with `count: 0`; a view whose center marks could
            not be *enumerated* (`GetFirstCenterMark2` is SOLIDWORKS 2025
            SP01+) is a `swUnknownError` failure instead, so "the view is
            clean" and "this build cannot see center marks" never read alike.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        activated = self.select_view_by_name(view_name, doc=doc)
        if not activated["success"]:
            return activated

        try:
            view = doc.ActiveDrawingView
        except Exception as e:
            logger.error(f"remove_center_marks({view_name!r}) error: {e}")
            return self._result(
                False, f"Remove center marks error: {e}", SwErrors.swSelectionError,
                {"view_name": view_name},
            )

        data = {"view_name": view_name}

        # All three of these are loop invariants and each read is a COM
        # round-trip, so they are fetched once rather than per mark. The
        # `SelectionManager` property access is inside the `try` with the
        # rest: on a dead COM pointer it raises like any other member, and
        # letting that escape would hand the tool layer a bare traceback
        # instead of the result dict every other path here returns.
        try:
            sel_data = doc.SelectionManager.CreateSelectData()
            extension = doc.Extension
        except Exception as e:
            logger.error(f"remove_center_marks({view_name!r}) error: {e}")
            return self._result(
                False, f"Remove center marks error: {e}", SwErrors.swSelectionError, data,
            )

        # `_view_center_marks` is eager: the whole chain is walked to
        # exhaustion *before* the first delete, because per the
        # `ICenterMark::GetNext` record in docs/api/03-annotations.md "a
        # deleted COM object's own `GetNext` is not guaranteed to still
        # answer". A lazy walk would end the batch after the first successful
        # `DeleteSelection2` and still report success, leaving the rest behind.
        marks, walk_err = self._view_center_marks(view)
        if walk_err is not None:
            # `GetFirstCenterMark2` itself failed -- most likely a
            # pre-2025-SP01 SolidWorks that has no such member. Swallowing it
            # would report "no center marks found -- 0 removed", telling the
            # caller the view is clean while every mark is still on it.
            return self._result(
                False,
                f"Could not enumerate center marks in view {view_name!r}: {walk_err} "
                "(IView::GetFirstCenterMark2 requires SOLIDWORKS 2025 SP01 or later)",
                SwErrors.swUnknownError, data,
            )
        candidates = len(marks)

        removed = 0
        for mark in marks:
            try:
                selected_ok = mark.Select(False, sel_data)
            except Exception as e:
                logger.warning(f"remove_center_marks({view_name!r}) Select error: {e}")
                selected_ok = False
            if not selected_ok:
                continue
            try:
                deleted = extension.DeleteSelection2(0)
            except Exception as e:
                logger.warning(f"remove_center_marks({view_name!r}) DeleteSelection2 error: {e}")
                deleted = False
            if deleted:
                removed += 1

        data["count"] = removed
        data["removed"] = removed

        if candidates == 0:
            return self._result(
                True, f"No center marks found in view {view_name!r} -- 0 removed",
                SwErrors.swSuccess, data,
            )

        if removed == 0:
            return self._result(
                False,
                f"Found {candidates} center mark(s) in view {view_name!r} but could not remove any",
                SwErrors.swFeatureError, data,
            )

        return self._result(
            True, f"Removed {removed} center mark(s) from view {view_name!r}",
            SwErrors.swSuccess, data,
        )

    # ========================================================================
    # BOM table tools
    # ========================================================================

    @staticmethod
    def _table_annotation(table: Any) -> Any:
        """`ITableAnnotation::GetAnnotation` -- the base `IAnnotation`
        wrapper every table type inherits, reached the same way `_describe_note`
        reaches an `INote`'s own `IAnnotation`. Never raises; `None` on
        failure."""
        try:
            return table.GetAnnotation()
        except Exception:
            return None

    def _iter_view_tables(self, view: Any):
        """Walk every table annotation attached to `view` via `IView::
        GetFirstTableAnnotation`/`ITableAnnotation::GetNext` -- the
        linked-list enumeration documented in docs/api/04-tables.md's
        "Enumerating and hiding table columns" addendum, the same
        `_iter_com_chain` shape `_iter_view_notes`/`_iter_view_datum_tags`
        already use."""
        return self._iter_com_chain(view, "GetFirstTableAnnotation", "GetNext",
                                    "_iter_view_tables")

    def _describe_table(self, table: Any, view_name: Optional[str]) -> Dict:
        """`list_tables`'s per-table record: type, name, position, and size
        (row/column counts -- tables have no documented overall width/height
        property, per the `ITableAnnotation` member index)."""
        annotation = self._table_annotation(table)
        name, x, y = self._annotation_name_position(annotation)

        type_code = _com_int(self._read_prop(table, "Type"))
        type_name = _enum_name(SwTableAnnotationType, type_code) if type_code is not None else None

        return {
            "name": name, "type": type_name, "type_code": type_code,
            "x": x, "y": y, "view_name": view_name,
            "row_count": _com_int(self._read_prop(table, "RowCount")),
            "column_count": _com_int(self._read_prop(table, "ColumnCount")),
        }

    def list_tables(self, sheet_name: Optional[str] = None) -> Dict:
        """
        Enumerate every table annotation (BOM, hole, revision, weldment cut
        list, general, title block, ...) via `IView::GetFirstTableAnnotation`/
        `ITableAnnotation::GetNext`, walked over every view `_scoped_views`
        resolves -- every real view in the document when `sheet_name` is
        omitted, else that sheet's own real views plus its sheet-level
        pseudo-view (where a title-block table lives).

        Args:
            sheet_name: Restrict to this sheet's tables. Omitted: every
                table in the whole document.

        Returns:
            Result dict. `data["tables"]` is a list of `_describe_table`
            records: `name` (`IAnnotation::GetName`), `type` (readable
            `swTableAnnotationType_e` name), `x`/`y` (caller's default
            unit), `view_name`, and `row_count`/`column_count` -- this
            record's "size", since tables have no overall width/height
            property.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        scoped, err = self._scoped_views(doc, sheet_name, "list_tables", "List tables")
        if err:
            return err

        tables: List[Dict] = []
        for view, v_name in scoped:
            tables.extend(self._describe_table(t, v_name) for t in self._iter_view_tables(view))

        return self._result(
            True, f"{len(tables)} table(s)" + (f" on sheet {sheet_name!r}" if sheet_name else ""),
            SwErrors.swSuccess, {"sheet_name": sheet_name, "tables": tables},
        )

    def _find_table_by_name(self, doc, table_name: str) -> Tuple[Any, Optional[str], Optional[Dict]]:
        """Find the table annotation named `table_name` anywhere in the
        document -- `get_bom_contents`'s lookup, walking every view the same
        way `list_tables` does with no `sheet_name` scope.

        Returns:
            `(table, view_name, None)` on a hit; `(None, None, None)` on a
            clean miss (no table has that name); `(None, None, error_dict)`
            if the walk itself failed.
        """
        scoped, err = self._scoped_views(doc, None, "get_bom_contents", "Get BOM contents")
        if err:
            return None, None, err

        for view, v_name in scoped:
            for table in self._iter_view_tables(view):
                annotation = self._table_annotation(table)
                if self._read_prop(annotation, "GetName") == table_name:
                    return table, v_name, None

        return None, None, None

    def insert_bom_table(
        self, view_name: Optional[str] = None, template_path: Optional[str] = None,
        x: float = 0, y: float = 0, bom_type: str = "top_level",
        configuration: Optional[str] = None, anchor: Optional[str] = None,
        attach_to_anchor: bool = False, detailed_cut_list: bool = False,
        hidden_columns: Optional[List[int]] = None,
    ) -> Dict:
        """
        Insert a BOM table onto a drawing view via `IView::InsertBomTable6`.

        Args:
            view_name: Drawing view to attach the table to (`IView::GetName2`,
                e.g. from `list_views`), on the active sheet. Omitted: the
                first real view on the active sheet -- fails with
                `swInvalidInput` if the sheet has none.
            template_path: Path to a `.sldbomtbt` template. Omitted: falls
                back to `utils.sw_finder.find_template("bom")` (globs the
                SolidWorks install's `lang/<language>/` folders for the
                first `.sldbomtbt` file, per docs/api/04-tables.md's
                Gotchas); if that also finds nothing, fails with
                `swTemplateNotFound` rather than passing an empty string to
                `InsertBomTable6` and getting an opaque COM failure.
            x, y: Table placement, caller's default unit -- converted to
                meters. Used only when `attach_to_anchor` is `False` (the
                default).
            bom_type: `"top_level"` (default), `"parts_only"`, or
                `"indented"` -- `swBomType_e`. `"top_level"` must not be
                combined with `configuration` (`InsertBomTable6`'s own
                Remarks: use `IBomFeature::GetConfigurations`/
                `SetConfigurations` instead); `"parts_only"`/`"indented"`
                require it.
            configuration: Configuration name for the BOM. Required for
                `bom_type in ("parts_only", "indented")`; must be omitted
                for `"top_level"`.
            anchor: `"top_left"`, `"top_right"`, `"bottom_left"`, or
                `"bottom_right"` -- the shared `swBOMConfigurationAnchorType_e`
                every table type uses. Required when `attach_to_anchor=True`;
                must be omitted when `attach_to_anchor=False` (mutually
                exclusive with the `x`/`y` placement mode -- either
                combination of the two fails with `swInvalidInput`).
            attach_to_anchor: `True` to snap to the sheet format's BOM
                anchor point (`UseAnchorPoint`) instead of `x`/`y`. Default
                `False`.
            detailed_cut_list: `True` to show the detailed cut list.
            hidden_columns: Optional list of 0-based column indices to hide
                after creation, via `ITableAnnotation::ColumnHidden` (see
                that record's Gotchas in the dossier for the unverified
                setter call shape used here). A failure hiding any column
                fails the whole call -- the table itself is already created
                by that point and is not rolled back, the same
                already-committed-then-fails convention `add_surface_finish`'s
                `all_around` documents.

        Returns:
            Result dict. `data["name"]` is the table's `IAnnotation::GetName`
            value; `data["row_count"]`/`data["column_count"]` are read back
            via `ITableAnnotation::RowCount`/`ColumnCount`, for balloon/update
            tools elsewhere in this epic to address the table by.
        """
        bom_key = (bom_type or "").strip().lower() if isinstance(bom_type, str) else ""
        bom_type_enum = _BOM_TYPES.get(bom_key)
        if bom_type_enum is None:
            return self._result(
                False, f"Unknown bom_type {bom_type!r}; expected one of {sorted(_BOM_TYPES)!r}",
                SwErrors.swInvalidInput, {"bom_type": bom_type},
            )

        if bom_key == "top_level":
            if configuration:
                return self._result(
                    False,
                    "configuration must not be given when bom_type='top_level' -- "
                    "IBomFeature::GetConfigurations/SetConfigurations controls the "
                    "configuration for a top-level-only BOM instead",
                    SwErrors.swInvalidInput, {"bom_type": bom_type, "configuration": configuration},
                )
            config_value = ""
        else:
            if not configuration:
                return self._result(
                    False, f"configuration is required when bom_type={bom_type!r}",
                    SwErrors.swInvalidInput, {"bom_type": bom_type},
                )
            config_value = configuration

        if attach_to_anchor:
            if not anchor:
                return self._result(
                    False, "anchor is required when attach_to_anchor=True",
                    SwErrors.swInvalidInput, {"attach_to_anchor": attach_to_anchor},
                )
            anchor_key = anchor.strip().lower() if isinstance(anchor, str) else ""
        else:
            if anchor:
                return self._result(
                    False,
                    "anchor is only used when attach_to_anchor=True; omit anchor to "
                    "place by x/y, or pass attach_to_anchor=True to use it",
                    SwErrors.swInvalidInput,
                    {"anchor": anchor, "attach_to_anchor": attach_to_anchor},
                )
            anchor_key = "top_left"

        anchor_enum = _TABLE_ANCHOR_TYPES.get(anchor_key)
        if anchor_enum is None:
            return self._result(
                False, f"Unknown anchor {anchor!r}; expected one of {sorted(_TABLE_ANCHOR_TYPES)!r}",
                SwErrors.swInvalidInput, {"anchor": anchor},
            )

        if hidden_columns is not None and (
            not isinstance(hidden_columns, (list, tuple))
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in hidden_columns)
        ):
            return self._result(
                False,
                f"hidden_columns must be a list of column indices, got {hidden_columns!r}",
                SwErrors.swInvalidInput, {"hidden_columns": hidden_columns},
            )

        xy_err = self._validate_xy(x, y)
        if xy_err:
            return xy_err

        resolved_template = template_path or find_template("bom")
        if not resolved_template:
            return self._result(
                False,
                "No BOM table template found. Pass template_path explicitly, or "
                "install a default .sldbomtbt template.",
                SwErrors.swTemplateNotFound, {"bom_type": bom_type},
            )

        doc, err = self.get_drawing_doc()
        if err:
            return err

        sheet, err = self._resolve_sheet(doc, None)
        if err:
            return err

        if view_name:
            view, err = self._require_view(
                doc, view_name, None, data={"bom_type": bom_type}, sheet=sheet,
            )
            if err:
                return err
        else:
            view = next(self._iter_real_views(sheet), None)
            if view is None:
                return self._result(
                    False,
                    "No views on the active sheet to attach the BOM table to -- "
                    "pass view_name, or insert a view first",
                    SwErrors.swInvalidInput,
                )
            view_name = self._read_prop(view, "GetName2")

        numbering_type = (
            int(SwNumberingType.swNumberingType_Detailed) if bom_key == "indented"
            else int(SwNumberingType.swNumberingType_None)
        )

        data = {
            "view_name": view_name, "bom_type": bom_key, "configuration": config_value or None,
            "template_path": resolved_template, "x": x, "y": y,
            "anchor": anchor_key if attach_to_anchor else None,
            "attach_to_anchor": bool(attach_to_anchor),
            "detailed_cut_list": bool(detailed_cut_list),
        }

        try:
            args = INSERT_BOM_TABLE6.bind(
                units=self._units,
                use_anchor_point=attach_to_anchor, x=x, y=y, anchor_type=anchor_enum,
                bom_type=bom_type_enum, configuration=config_value,
                table_template=resolved_template, hidden=False,
                indented_numbering_type=numbering_type,
                detailed_cut_list=detailed_cut_list,
            )
            table = view.InsertBomTable6(*args)
        except Exception as e:
            logger.error(f"insert_bom_table({view_name!r}) InsertBomTable6 error: {e}")
            return self._result(False, f"Insert BOM table error: {e}", SwErrors.swFeatureError, data)

        if table is None:
            return self._result(
                False,
                "InsertBomTable6 returned nothing -- BOM table not created (an invalid "
                "configuration name for this bom_type is the most likely cause)",
                SwErrors.swFeatureError, data,
            )

        if hidden_columns:
            for idx in hidden_columns:
                try:
                    table.ColumnHidden(idx, True)
                except Exception as e:
                    logger.error(f"insert_bom_table({view_name!r}) ColumnHidden({idx}) error: {e}")
                    return self._result(
                        False, f"Hide column {idx} error: {e}", SwErrors.swFeatureError,
                        {**data, "hidden_columns": hidden_columns},
                    )
            data["hidden_columns"] = list(hidden_columns)

        annotation = self._table_annotation(table)
        name, tx, ty = self._annotation_name_position(annotation)
        data["name"] = name
        data["x"] = tx if tx is not None else x
        data["y"] = ty if ty is not None else y
        data["row_count"] = _com_int(self._read_prop(table, "RowCount"))
        data["column_count"] = _com_int(self._read_prop(table, "ColumnCount"))

        return self._result(
            True,
            "Inserted BOM table" + (f" {name!r}" if name else "") + f" in view {view_name!r}",
            SwErrors.swSuccess, data,
        )

    def get_bom_contents(self, table_name: str) -> Dict:
        """
        Read a BOM table's cell text back via `ITableAnnotation::Text2`, so
        an LLM can verify an assembly drawing's BOM without opening
        SolidWorks.

        Args:
            table_name: `IAnnotation::GetName` value, as returned by
                `insert_bom_table`'s `data["name"]` or `list_tables`'
                `data["tables"][i]["name"]`. Searched across every view in
                the document (not scoped to one sheet).

        Returns:
            Result dict. `data["rows"]` is a list of rows (including the
            header row at index 0), each a list of `TotalRowCount` x
            `TotalColumnCount` cell strings, read via `Text2(row, col,
            IncludeHidden=True)` so hidden columns/rows are still reported.
            Fails with `swInvalidInput` if no table has that name, or if the
            table found is not a BOM table (`swTableAnnotationType_e`'s
            `swTableAnnotation_BillOfMaterials`).
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        table, view_name, err = self._find_table_by_name(doc, table_name)
        if err:
            return err
        if table is None:
            return self._result(
                False, f"Unknown table {table_name!r}", SwErrors.swInvalidInput,
                {"table_name": table_name},
            )

        type_code = _com_int(self._read_prop(table, "Type"))
        if type_code != int(SwTableAnnotationType.swTableAnnotation_BillOfMaterials):
            type_name = (
                _enum_name(SwTableAnnotationType, type_code) if type_code is not None else "unknown"
            )
            return self._result(
                False, f"Table {table_name!r} is not a BOM table (type: {type_name})",
                SwErrors.swInvalidInput, {"table_name": table_name, "type": type_name},
            )

        row_count = _com_int(self._read_prop(table, "TotalRowCount"))
        # `TotalColumnCount` (visible + hidden), not the plain `ColumnCount`
        # (visible only) -- the same visible/total split `RowCount`/
        # `TotalRowCount` documents, per this dossier's `ColumnCount` Gotcha.
        # Falling back to `ColumnCount` only if `TotalColumnCount` itself is
        # unreadable keeps a hidden `insert_bom_table` column from silently
        # truncating out of a `Text2(..., IncludeHidden=True)` read.
        column_count = _com_int(self._read_prop(table, "TotalColumnCount"))
        if column_count is None:
            column_count = _com_int(self._read_prop(table, "ColumnCount"))
        if row_count is None or column_count is None:
            return self._result(
                False, f"Could not read row/column count for table {table_name!r}",
                SwErrors.swFeatureError, {"table_name": table_name},
            )

        rows: List[List[Optional[str]]] = []
        for row_index in range(row_count):
            row: List[Optional[str]] = []
            for col_index in range(column_count):
                try:
                    text = table.Text2(row_index, col_index, True)
                except Exception as e:
                    logger.warning(
                        f"get_bom_contents({table_name!r}) Text2({row_index},{col_index}) error: {e}"
                    )
                    text = None
                row.append(text if isinstance(text, str) else (None if text is None else str(text)))
            rows.append(row)

        return self._result(
            True,
            f"{row_count} row(s) x {column_count} column(s) in table {table_name!r}",
            SwErrors.swSuccess,
            {
                "table_name": table_name, "view_name": view_name,
                "row_count": row_count, "column_count": column_count, "rows": rows,
            },
        )
