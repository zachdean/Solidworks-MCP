"""
SolidWorks Drawing Operations
------------------------------
Access and operate on drawing (.slddrw) documents.
"""

import os
import logging
from contextlib import ExitStack
from math import ceil, sqrt
from typing import Any, Dict, List, Optional, Tuple

from .. import com_backend
from .com_params import (
    ComSignature, Param, REQUIRED, enum_to_int, to_bool, to_meters, to_optional_object,
)
from ..constants import SwErrors, SwDocumentTypes, SwFileTypes
from ..constants_drawing import (
    SwAlignViewTypes,
    SwCreateSectionViewAtOptions,
    SwCustomInfoType,
    SwCustomPropertyAddOption,
    SwDetCircleShowType,
    SwDetViewStyle,
    SwDisplayMode,
    SwDrawingViewTypes,
    SwDwgPaperSizes,
    SwImportModelItemsSource,
    SwInsertAnnotation,
    SwSaveAsOptions,
    SwSaveAsVersion,
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

                export_data = com_backend.null_dispatch()
                advanced_options = com_backend.null_dispatch()
                saved = doc.Extension.SaveAs3(
                    filepath, int(SwSaveAsVersion.swSaveAsCurrentVersion),
                    int(SwSaveAsOptions.swSaveAsOptions_Silent),
                    export_data, advanced_options, errors, warnings,
                )
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
