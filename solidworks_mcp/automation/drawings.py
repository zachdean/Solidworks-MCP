"""
SolidWorks Drawing Operations
------------------------------
Access and operate on drawing (.slddrw) documents.
"""

import os
import logging
from typing import Any, Dict, Optional, Tuple

from .. import com_backend
from ..constants import SwErrors, SwDocumentTypes, SwFileTypes
from ..constants_drawing import (
    SwCustomInfoType,
    SwCustomPropertyAddOption,
    SwDrawingViewTypes,
    SwDwgPaperSizes,
    SwSaveAsOptions,
    SwSaveAsVersion,
    SwUserPreferenceToggle,
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
