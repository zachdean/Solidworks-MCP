"""
Regression tests for the `export_pdf` tool
(solidworks_mcp/tools/drawing_documents.py -> DrawingOperations.export_pdf in
solidworks_mcp/automation/drawings.py), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
mirroring solidworks_mcp/tests/test_tools_document.py's `TestSaveDrawing`
conventions (fake COM never actually writes a file to disk, so "the file was
really written" is simulated by pre-creating it at `output_path` before the
call and asserting the tool reads it back correctly afterward).
"""

import os

from solidworks_mcp.constants_drawing import SwFileSaveError, SwUserPreferenceToggle
from solidworks_mcp.tools import dispatch


def _wire_export_data(fake_sw, saveas3_return=True):
    """Script `GetExportFileData` to hand back a fresh `IExportPdfData`
    fake, and `SaveAs3` to return `saveas3_return` with no error/warning
    bits set unless the test overrides them with `set_byref`."""
    export_data = fake_sw.new_object("export_data")
    export_data.set_return("SetSheets", True)
    fake_sw.set_return("GetExportFileData", export_data)
    fake_sw.ActiveDoc.Extension.set_return("SaveAs3", saveas3_return)
    return export_data


class TestExportPdfSheetSelection:
    def test_all_sheets_sets_export_data_and_succeeds(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"%PDF-1.4 stub")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is True, result
        assert result["data"]["sheets"] == ["Sheet1", "Sheet2"]
        log = fake_sw.call_log
        assert log.arg_of("SetSheets", 0) == 1  # swExportData_ExportAllSheets
        assert log.arg_of("SetSheets", 1) == ["Sheet1", "Sheet2"]
        assert log.arg_of("SaveAs3", 0) == str(output_path)

    def test_current_sheet_sets_export_data_correctly(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        current = fake_sw.ActiveDoc.GetCurrentSheet()
        current.set_return("Name", "Sheet1")
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "sheets": "current",
        })

        assert result["success"] is True, result
        assert result["data"]["sheets"] == ["Sheet1"]
        log = fake_sw.call_log
        assert log.arg_of("SetSheets", 0) == 2  # swExportData_ExportCurrentSheet
        assert log.arg_of("SetSheets", 1) == ["Sheet1"]

    def test_explicit_sheet_list_preserves_order_in_export_data(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2", "Sheet3"])
        _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "sheets": ["Sheet3", "Sheet1"],
        })

        assert result["success"] is True, result
        assert result["data"]["sheets"] == ["Sheet3", "Sheet1"]
        log = fake_sw.call_log
        assert log.arg_of("SetSheets", 0) == 3  # swExportData_ExportSpecifiedSheets
        assert log.arg_of("SetSheets", 1) == ["Sheet3", "Sheet1"]

    def test_unknown_sheet_name_errors_before_touching_com(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "sheets": ["Sheet1", "Nope"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["unknown_sheets"] == ["Nope"]
        assert result["data"]["available_sheets"] == ["Sheet1", "Sheet2"]
        assert "Sheet1" in result["message"] and "Sheet2" in result["message"]
        log = fake_sw.call_log
        assert not log.calls_to("GetExportFileData")
        assert not log.calls_to("SaveAs3")

    def test_invalid_sheets_type_is_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "sheets": 123,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")


class TestExportPdfSaveErrorDecoding:
    def test_nonzero_save_error_fails_even_if_return_value_is_truthy(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=True)
        fake_sw.ActiveDoc.Extension.set_byref(
            "SaveAs3", {5: int(SwFileSaveError.swReadOnlySaveError), 6: 0})
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
        assert result["data"]["errors"] == int(SwFileSaveError.swReadOnlySaveError)
        assert "swReadOnlySaveError" in result["data"]["decoded_errors"]
        assert "swReadOnlySaveError" in result["message"]

    def test_saveas3_false_return_fails(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=False)
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"


class TestExportPdfFileVerification:
    def test_missing_output_file_after_successful_com_call_fails(self, tool_sw, tmp_path):
        """SaveAs3 can report True/Errors==0 while writing nothing -- the
        fake harness never touches the filesystem, so simply not
        pre-creating `output_path` reproduces exactly this failure mode."""
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=True)
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swExportError"
        assert "no file was written" in result["message"]

    def test_creates_missing_output_directory(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=True)
        nested = tmp_path / "reports" / "2026" / "out.pdf"
        assert not nested.parent.exists()

        dispatch("export_pdf", {"output_path": str(nested)})

        assert nested.parent.is_dir()

    def test_reports_size_of_existing_output_file(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=True)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"0123456789")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is True
        assert result["data"]["size_bytes"] == 10

    def test_locked_or_unwritable_output_path_fails_before_com(
            self, tool_sw, tmp_path, monkeypatch):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw, saveas3_return=True)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"already open in a viewer")

        real_open = open

        def _raise_for_target(path, mode="r", *args, **kwargs):
            if os.path.abspath(str(path)) == os.path.abspath(str(output_path)) and "a" in mode:
                raise PermissionError("file is locked")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(
            "solidworks_mcp.automation.drawings.open", _raise_for_target, raising=False)

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swExportError"
        assert not fake_sw.call_log.calls_to("SaveAs3")


class TestExportPdfOptions:
    def test_open_after_sets_view_pdf_after_saving(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        export_data = _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "open_after": True,
        })

        assert result["success"] is True
        assert export_data.ViewPdfAfterSaving is True

    def test_high_quality_default_sets_and_restores_preference(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        fake_sw.set_return("GetUserPreferenceToggle", False)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is True
        toggle = int(SwUserPreferenceToggle.swPDFExportHighQuality)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, True), (toggle, False)]

    def test_high_quality_false_is_written_and_restored(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        fake_sw.set_return("GetUserPreferenceToggle", True)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "high_quality": False,
        })

        assert result["success"] is True
        toggle = int(SwUserPreferenceToggle.swPDFExportHighQuality)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, False), (toggle, True)]

    def test_keep_invisible_layers_shows_hidden_layers_and_restores_them(
            self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        doc = fake_sw.ActiveDoc
        layer_mgr = fake_sw.new_object("layer_mgr")
        doc.set_return("GetLayerManager", layer_mgr)
        layer_mgr.set_return("GetLayerList", ["Hidden1", "Visible1"])
        # Path-qualified keys (not the bare "Visible" method name) -- both
        # layers share that bare name in the harness's global script
        # registry, so scripting them with the bare key would have the
        # second `set_return` silently clobber the first.
        hidden_layer = fake_sw.new_object("hidden_layer")
        hidden_layer.set_return("hidden_layer.Visible", False)
        hidden_layer.set_return("hidden_layer.Printable", True)
        visible_layer = fake_sw.new_object("visible_layer")
        visible_layer.set_return("visible_layer.Visible", True)
        layer_mgr.set_sequence("GetLayer", [hidden_layer, visible_layer])
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "keep_invisible_layers": True,
        })

        assert result["success"] is True, result
        # Restored to hidden afterward -- a raw `False` was assigned directly
        # (not merely re-read as the original scripted value).
        assert hidden_layer.Visible is False
        # `ILayer::Visible`'s Gotchas: flipping Visible can change Printable
        # as a side effect, so its prior value must be re-asserted too.
        assert hidden_layer.Printable is True
        # The already-visible layer was never assigned to, so it's still
        # backed only by its original `set_return` scripting.
        assert visible_layer.Visible == True  # noqa: E712

    def test_keep_invisible_layers_false_never_touches_layer_manager(
            self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is True
        assert not fake_sw.call_log.calls_to("GetLayerManager")

    def test_restores_preference_and_layer_visibility_when_saveas3_raises(
            self, tool_sw, tmp_path):
        """Mirrors insert_standard_3_view's
        test_restores_preference_when_creation_raises -- the exception path
        is exactly where the `finally`-block restores matter most, and this
        exercises both the quality-preference and the layer-visibility
        restore at once."""
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        fake_sw.set_return("GetUserPreferenceToggle", False)
        fake_sw.ActiveDoc.Extension.set_raises("SaveAs3", RuntimeError("boom"))
        doc = fake_sw.ActiveDoc
        layer_mgr = fake_sw.new_object("layer_mgr")
        doc.set_return("GetLayerManager", layer_mgr)
        layer_mgr.set_return("GetLayerList", ["Hidden1"])
        hidden_layer = fake_sw.new_object("hidden_layer")
        hidden_layer.set_return("hidden_layer.Visible", False)
        layer_mgr.set_return("GetLayer", hidden_layer)
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "keep_invisible_layers": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
        toggle = int(SwUserPreferenceToggle.swPDFExportHighQuality)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, True), (toggle, False)]
        assert hidden_layer.Visible is False


class TestExportPdfRequiresDrawing:
    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw, tmp_path):
        tool_sw("part")
        output_path = tmp_path / "out.pdf"

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
