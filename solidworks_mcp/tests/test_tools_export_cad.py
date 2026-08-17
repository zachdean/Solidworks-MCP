"""
Regression tests for the `export_dxf_dwg` and `export_edrawings` tools
(solidworks_mcp/tools/drawing_documents.py ->
DrawingOperations.export_dxf_dwg/export_edrawings in
solidworks_mcp/automation/drawings.py), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
mirroring solidworks_mcp/tests/test_tools_export_pdf.py's conventions (fake
COM never actually writes a file to disk, so "the file was really written" is
simulated by pre-creating it at the expected path before the call and
asserting the tool reads it back correctly afterward).
"""

import os

import pytest

from solidworks_mcp.constants_drawing import SwFileSaveError
from solidworks_mcp.tools import dispatch


class TestExportDxfDwgValidation:
    @pytest.mark.parametrize("filename, extra", [
        ("out.dxf", {"format": "step"}),          # unknown format
        ("out.pdf", {"format": "dxf"}),           # extension doesn't match format
        ("out.dxf", {"export_fonts_as": "bitmap"}),
        ("out.dxf", {"version": "R1985"}),
    ], ids=["format", "extension_mismatch", "export_fonts_as", "version"])
    def test_bad_argument_rejected_before_com(self, tool_sw, tmp_path, filename, extra):
        """Every fail-fast input check rejects with `swInvalidInput` and
        without reaching `SaveAs3` -- one body, since the whole point of each
        is that it happens before any COM call."""
        fake_sw = tool_sw("drawing")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(tmp_path / filename), **extra,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_missing_map_file_errors_before_touching_com(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path),
            "map_file": str(tmp_path / "nope.xml"),
        })

        assert result["success"] is False
        assert result["error_name"] == "swFileNotFoundError"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert not fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_unknown_sheet_name_errors_before_touching_com(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "sheets": ["Sheet1", "Nope"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["unknown_sheets"] == ["Nope"]
        assert not fake_sw.call_log.calls_to("SaveAs3")


class TestExportDxfDwgSheetSelection:
    def test_all_sheets_single_file_combines_into_one_call(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is True, result
        assert result["data"]["export_mode"] == "combined"
        assert result["data"]["files"] == [{
            "path": str(output_path), "sheet": None, "size_bytes": 4,
        }]
        log = fake_sw.call_log
        assert log.calls_to("SaveAs3")[0].args[0] == str(output_path)
        # swDxfMultiSheetOption = swDxfMultiSheet (2) -- combine all sheets.
        multisheet_calls = log.calls_to("SetUserPreferenceIntegerValue")
        assert (253, 2) in [c.args for c in multisheet_calls]  # swDxfMultiSheetOption
        assert not log.calls_to("ActivateSheet")

    def test_all_sheets_separate_files_loops_and_activates_each_sheet(
            self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        (tmp_path / "out_Sheet1.dxf").write_bytes(b"one")
        (tmp_path / "out_Sheet2.dxf").write_bytes(b"twotwo")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "multisheet": "separate_files",
        })

        assert result["success"] is True, result
        assert result["data"]["export_mode"] == "per_sheet"
        files = result["data"]["files"]
        assert [f["sheet"] for f in files] == ["Sheet1", "Sheet2"]
        assert files[0]["path"] == str(tmp_path / "out_Sheet1.dxf")
        assert files[0]["size_bytes"] == 3
        assert files[1]["size_bytes"] == 6
        log = fake_sw.call_log
        assert [c.args[0] for c in log.calls_to("ActivateSheet")] == ["Sheet1", "Sheet2"]
        assert [c.args[0] for c in log.calls_to("SaveAs3")] == [
            str(tmp_path / "out_Sheet1.dxf"), str(tmp_path / "out_Sheet2.dxf"),
        ]
        # swDxfMultiSheetOption = swDxfActiveSheetOnly (0), set once before
        # the loop -- each SaveAs3 call only wants its own activated sheet,
        # not SolidWorks' own (undocumented-filename) swDxfSeparateSheets (1)
        # multi-file mode.
        multisheet_calls = [
            c.args for c in log.calls_to("SetUserPreferenceIntegerValue") if c.args[0] == 253
        ]
        assert 0 in [v for _, v in multisheet_calls]

    def test_current_sheet_single_call_at_output_path(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        current = fake_sw.ActiveDoc.GetCurrentSheet()
        current.set_return("Name", "Sheet1")
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "sheets": "current",
        })

        assert result["success"] is True, result
        assert result["data"]["export_mode"] == "current"
        assert result["data"]["files"] == [{
            "path": str(output_path), "sheet": "Sheet1", "size_bytes": 4,
        }]
        assert not fake_sw.call_log.calls_to("ActivateSheet")

    def test_explicit_sheet_list_loops_even_with_multisheet_single_file(
            self, tool_sw, tmp_path):
        """An explicit sheet list has no native "combine only these N sheets"
        equivalent, so it always loops per-sheet regardless of `multisheet`
        (docs/api/05-export-and-layers.md has no such mode)."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2", "Sheet3"])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        (tmp_path / "out_Sheet3.dxf").write_bytes(b"x")
        (tmp_path / "out_Sheet1.dxf").write_bytes(b"y")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "sheets": ["Sheet3", "Sheet1"],
            "multisheet": "single_file",
        })

        assert result["success"] is True, result
        assert result["data"]["export_mode"] == "per_sheet"
        assert [f["sheet"] for f in result["data"]["files"]] == ["Sheet3", "Sheet1"]


class TestExportDxfDwgPreferenceRestore:
    def test_font_and_multisheet_preferences_set_and_restored(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 77)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is True, result
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        # forward: fonts (swDxfOutputFonts=1) -> geometry (0), multisheet
        # (swDxfMultiSheetOption=253) -> combined (2); restore in reverse.
        assert [c.args for c in calls] == [
            (1, 0), (253, 2), (253, 77), (1, 77),
        ]

    def test_version_preference_set_only_when_provided(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 5)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        without_version = dispatch("export_dxf_dwg", {"output_path": str(output_path)})
        assert without_version["success"] is True
        assert (0, 5) not in [
            c.args for c in fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        ]

        with_version = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "version": "R2018",
        })
        assert with_version["success"] is True
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        # swDxfVersion=0, swDxfFormat_R2018=8
        assert (0, 8) in [c.args for c in calls]
        assert (0, 5) in [c.args for c in calls]  # restored back to original

    def test_map_file_configures_and_restores_mapping_preferences(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceToggle", False)
        fake_sw.set_return("GetUserPreferenceIntegerValue", -1)
        fake_sw.set_return("GetUserPreferenceStringListValue", [])
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        map_file = tmp_path / "layers.xml"
        map_file.write_text("<map/>")
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(output_path), "map_file": str(map_file),
        })

        assert result["success"] is True, result
        toggle_calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        # swDxfMapping=8 -> True, swDXFDontShowMap=21 -> True, then restored
        assert (8, True) in [c.args for c in toggle_calls]
        assert (21, True) in [c.args for c in toggle_calls]
        assert (8, False) in [c.args for c in toggle_calls]
        assert (21, False) in [c.args for c in toggle_calls]
        string_list_calls = fake_sw.call_log.calls_to("SetUserPreferenceStringListValue")
        assert string_list_calls[0].args == (0, [str(map_file)])
        assert string_list_calls[-1].args == (0, [])  # restored to the original (empty) list
        int_calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        assert (2, 0) in [c.args for c in int_calls]  # swDxfMappingFileIndex -> 0
        assert (2, -1) in [c.args for c in int_calls]  # restored

    def test_restores_preferences_when_saveas3_raises(self, tool_sw, tmp_path):
        """Mirrors export_pdf's test_restores_preference_and_layer_visibility
        _when_saveas3_raises -- the exception path is exactly where the
        `finally`-block restores matter most."""
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 42)
        fake_sw.ActiveDoc.Extension.set_raises("SaveAs3", RuntimeError("boom"))
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        assert [c.args for c in calls] == [
            (1, 0), (253, 2), (253, 42), (1, 42),
        ]


class TestExportDxfDwgFileVerification:
    def test_missing_output_file_after_success_fails(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swExportError"
        # Verified per file by the shared `_save_as3` primitive, so the
        # failure names the one path that wasn't written rather than
        # collecting a `missing` list in a second pass afterward.
        assert result["data"]["path"] == str(output_path)

    def test_nonzero_save_error_fails_even_if_return_value_is_truthy(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        fake_sw.ActiveDoc.Extension.set_byref(
            "SaveAs3", {5: int(SwFileSaveError.swReadOnlySaveError), 6: 0})
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
        assert "swReadOnlySaveError" in result["data"]["decoded_errors"]


class TestExportDxfDwgRequiresDrawing:
    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw, tmp_path):
        tool_sw("part")
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestExportEdrawings:
    def test_export_all_sets_selection_preference_and_succeeds(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.edrw"
        output_path.write_bytes(b"stub")

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is True, result
        assert result["data"]["addin_available"] is True
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        # swEdrawingsSaveAsSelectionOption=237, swEdrawingSaveAll=2, restored to 0
        assert [c.args for c in calls] == [(237, 2), (237, 0)]
        assert fake_sw.call_log.calls_to("SaveAs3")[0].args[0] == str(output_path)

    def test_export_current_sets_selection_preference(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.edrw"
        output_path.write_bytes(b"stub")

        result = dispatch("export_edrawings", {
            "output_path": str(output_path), "sheets": "current",
        })

        assert result["success"] is True, result
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        # swEdrawingSaveActive=1
        assert (237, 1) in [c.args for c in calls]

    def test_invalid_sheets_value_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {
            "output_path": str(output_path), "sheets": ["Sheet1"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_wrong_extension_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        output_path = tmp_path / "out.dxf"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_addin_unavailable_error_bit_reported(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        fake_sw.ActiveDoc.Extension.set_byref(
            "SaveAs3", {5: int(SwFileSaveError.swFileSaveFormatNotAvailable), 6: 0})
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["data"]["addin_available"] is False
        assert "add-in" in result["message"]

    def test_addin_unavailable_exception_message_reported(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_raises(
            "SaveAs3", RuntimeError("eDrawings add-in is not registered"))
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["data"]["addin_available"] is False
        # preference is still restored even though SaveAs3 raised
        calls = fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        assert calls[-1].args == (237, 0)

    def test_ordinary_failure_does_not_report_addin_unavailable(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        fake_sw.ActiveDoc.Extension.set_byref(
            "SaveAs3", {5: int(SwFileSaveError.swReadOnlySaveError), 6: 0})
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["data"]["addin_available"] is True

    def test_missing_output_file_after_success_fails(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceIntegerValue", 0)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swExportError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw, tmp_path):
        tool_sw("part")
        output_path = tmp_path / "out.edrw"

        result = dispatch("export_edrawings", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
