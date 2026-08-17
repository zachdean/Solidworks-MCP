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
    SwDwgPaperSizes,
    SwSaveAsOptions,
    SwSaveAsVersion,
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
