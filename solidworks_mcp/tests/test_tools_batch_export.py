"""
Regression tests for the `batch_export_pack` composite tool
(solidworks_mcp/tools/drawing_documents.py ->
DrawingOperations.batch_export_pack in solidworks_mcp/automation/drawings.py),
dispatched through the real `solidworks_mcp.tools` registry (`dispatch()`)
against the fake COM harness.

Mirrors solidworks_mcp/tests/test_tools_export_pdf.py's/test_tools_export_cad.py's
conventions: the fake COM harness never actually writes a file to disk, so
"the file was really written" is simulated by pre-creating it at the *exact*
path this tool computes (`output_dir` + sanitized filename_pattern + format
extension) before the call, then asserting the tool reads it back correctly.

Because of that pre-creation trick, every happy-path test below passes
`overwrite=True` -- the pre-created file would otherwise trip
`batch_export_pack`'s own overwrite guard, which has its own dedicated tests.
"""

import datetime
import json

import pytest

from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_export_pdf.py's `tool_sw`, connecting the
    shared `tools.sw_automation` singleton (what `dispatch()` actually calls
    through) to a fresh fake `SldWorks.Application`, defaulting to a drawing
    document since `batch_export_pack` requires one."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _wire_saveas3_ok(fake_sw):
    """Script every `SaveAs3` call (export_pdf/export_dxf_dwg/
    export_edrawings/the native-archive copy all funnel through the same
    `IModelDocExtension::SaveAs3` entry point) to succeed, plus
    `GetExportFileData` for the PDF path specifically."""
    export_data = fake_sw.new_object("export_data")
    export_data.set_return("SetSheets", True)
    fake_sw.set_return("GetExportFileData", export_data)
    fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)


class TestBatchExportPackCombined:
    def test_combined_pdf_happy_path(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_saveas3_ok(fake_sw)
        expected = tmp_path / "Draw1_all.pdf"
        expected.write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"],
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["total"] == 1
        assert result["data"]["succeeded"] == 1
        assert result["data"]["failed"] == 0
        entry = result["data"]["files"][0]
        assert entry["path"] == str(expected)
        assert entry["format"] == "pdf"
        assert entry["sheet"] is None
        assert entry["success"] is True
        assert entry["size_bytes"] == 4

    def test_writes_valid_manifest_json_with_one_entry_per_file(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")
        (tmp_path / "Draw1_all.dxf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf", "dxf"],
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        manifest_path = result["data"]["manifest_path"]
        assert manifest_path == str(tmp_path / "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert len(manifest["files"]) == 2
        assert {f["format"] for f in manifest["files"]} == {"pdf", "dxf"}

    def test_drawing_token_strips_extension_from_saved_document_title(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        fake_sw.ActiveDoc.set_return("GetTitle", "MyDrawing.SLDDRW")
        expected = tmp_path / "MyDrawing_all.pdf"
        expected.write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["files"][0]["path"] == str(expected)

    def test_default_invocation_exports_pdf_and_native_copy(self, tool_sw, tmp_path):
        """The defaults (`formats=["pdf"]`, `include_native=True`) are the
        call an LLM is most likely to make with no extra arguments."""
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")
        (tmp_path / "Draw1_all.slddrw").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["total"] == 2
        formats = {f["format"] for f in result["data"]["files"]}
        assert formats == {"pdf", "native"}

    def test_multiple_formats_produce_one_file_each(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"a")
        (tmp_path / "Draw1_all.dxf").write_bytes(b"bb")
        (tmp_path / "Draw1_all.dwg").write_bytes(b"ccc")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf", "dxf", "dwg"],
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        by_format = {f["format"]: f for f in result["data"]["files"]}
        assert set(by_format) == {"pdf", "dxf", "dwg"}
        assert all(f["success"] for f in by_format.values())
        assert by_format["pdf"]["path"].endswith("Draw1_all.pdf")
        assert by_format["dxf"]["path"].endswith("Draw1_all.dxf")
        assert by_format["dwg"]["path"].endswith("Draw1_all.dwg")


class TestBatchExportPackPerSheet:
    def test_one_file_per_sheet(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_Sheet1.pdf").write_bytes(b"a")
        (tmp_path / "Draw1_Sheet2.pdf").write_bytes(b"bb")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "per_sheet": True,
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        paths = {f["sheet"]: f["path"] for f in result["data"]["files"]}
        assert paths == {
            "Sheet1": str(tmp_path / "Draw1_Sheet1.pdf"),
            "Sheet2": str(tmp_path / "Draw1_Sheet2.pdf"),
        }
        # Per-sheet PDF export uses the explicit-list ("specified sheets")
        # mode -- SetSheets(3, [name]) -- not a bare `sheets="all"` combine.
        log = fake_sw.call_log
        set_sheets_calls = [c.args for c in log.calls_to("SetSheets")]
        assert set_sheets_calls == [(3, ["Sheet1"]), (3, ["Sheet2"])]

    def test_per_sheet_dxf_activates_sheet_then_exports_current(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_saveas3_ok(fake_sw)
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        (tmp_path / "Draw1_Sheet1.dxf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["dxf"], "per_sheet": True,
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.arg_of("ActivateSheet", 0) == "Sheet1"
        names = log.ordered_names()
        assert names.index("ActivateSheet") < names.index("SaveAs3")

    def test_per_sheet_requires_sheet_or_index_token(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "per_sheet": True,
            "filename_pattern": "{drawing}",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_per_sheet_activation_failure_skips_current_mode_formats_only(
            self, tool_sw, tmp_path):
        """pdf's per-sheet export uses an explicit sheet-name list (no
        activation needed), but dxf/edrawings need `sheets="current"` after
        `ActivateSheet` -- if activation fails, those formats fail without a
        COM call while pdf is still attempted."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_saveas3_ok(fake_sw)
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)
        (tmp_path / "Draw1_Sheet1.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf", "dxf"], "per_sheet": True,
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is False
        by_format = {f["format"]: f for f in result["data"]["files"]}
        assert by_format["pdf"]["success"] is True
        assert by_format["dxf"]["success"] is False
        assert "activate" in by_format["dxf"]["error"].lower()
        dxf_path = str(tmp_path / "Draw1_Sheet1.dxf")
        saveas3_paths = [c.args[0] for c in fake_sw.call_log.calls_to("SaveAs3")]
        assert dxf_path not in saveas3_paths


class TestBatchExportPackFilenameTokens:
    def test_all_five_tokens_resolve(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_saveas3_ok(fake_sw)
        mgr = fake_sw.new_object("cpm")
        fake_sw.ActiveDoc.Extension.set_return("CustomPropertyManager", mgr)
        mgr.set_return("GetNames", ["Revision"])
        mgr.set_byref("Get6", {2: "raw", 3: "B"})
        today = datetime.date.today().strftime("%Y-%m-%d")
        expected = tmp_path / f"Draw1_Sheet1_1_{today}_B.pdf"
        expected.write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "per_sheet": True,
            "filename_pattern": "{drawing}_{sheet}_{index}_{date}_{rev}",
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["files"][0]["path"] == str(expected)

    def test_unknown_token_rejected_before_com(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "filename_pattern": "{bogus}",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_rev_defaults_to_empty_string_when_no_custom_property(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_saveas3_ok(fake_sw)
        expected = tmp_path / "Sheet1_.pdf"
        expected.write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "per_sheet": True,
            "filename_pattern": "{sheet}_{rev}", "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["files"][0]["path"] == str(expected)


class TestBatchExportPackSanitization:
    def test_sheet_name_with_slash_and_colon_is_sanitized(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["A/B:C"])
        _wire_saveas3_ok(fake_sw)
        expected = tmp_path / "A_B_C.pdf"
        expected.write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "per_sheet": True,
            "filename_pattern": "{sheet}", "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        entry = result["data"]["files"][0]
        assert entry["path"] == str(expected)
        assert entry["sheet"] == "A/B:C"


class TestBatchExportPackOverwrite:
    def test_overwrite_false_refuses_existing_file(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        existing = tmp_path / "Draw1_all.pdf"
        existing.write_bytes(b"already here")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
        })

        assert result["success"] is False
        entry = result["data"]["files"][0]
        assert entry["success"] is False
        assert "already exists" in entry["error"]
        assert not fake_sw.call_log.calls_to("SaveAs3")
        # The pre-existing file must not have been touched.
        assert existing.read_bytes() == b"already here"

    def test_overwrite_true_clobbers_existing_file(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        existing = tmp_path / "Draw1_all.pdf"
        existing.write_bytes(b"old content")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("SaveAs3")


class TestBatchExportPackPartialFailure:
    def test_mid_batch_failure_continues_and_reports_overall_false(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        # Only the PDF output is pre-created -- the harness never writes a
        # real file, so DXF's export "succeeds" at the COM layer but fails
        # batch_export_pack's own on-disk verification.
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf", "dxf"],
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is False
        by_format = {f["format"]: f for f in result["data"]["files"]}
        assert by_format["pdf"]["success"] is True
        assert by_format["dxf"]["success"] is False
        assert result["data"]["succeeded"] == 1
        assert result["data"]["failed"] == 1
        assert result["data"]["failures"][0]["format"] == "dxf"

        with open(result["data"]["manifest_path"]) as f:
            manifest = json.load(f)
        statuses = {f["format"]: f["success"] for f in manifest["files"]}
        assert statuses == {"pdf": True, "dxf": False}


class TestBatchExportPackRebuild:
    def test_rebuild_first_issues_rebuild_before_first_export(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True, "rebuild_first": True,
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("ForceRebuild3") < names.index("SaveAs3")
        assert result["data"]["rebuild"] == {
            "attempted": True, "success": True, "message": "Rebuild successful",
        }

    def test_rebuild_first_false_skips_rebuild(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True, "rebuild_first": False,
        })

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("ForceRebuild3")
        assert result["data"]["rebuild"] == {
            "attempted": False, "success": None, "message": None,
        }

    def test_rebuild_failure_is_non_fatal_and_exports_still_attempted(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", False)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["rebuild"]["success"] is False


class TestBatchExportPackNative:
    def test_include_native_writes_slddrw_copy(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.slddrw").write_bytes(b"native stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": [], "include_native": True,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["total"] == 1
        entry = result["data"]["files"][0]
        assert entry["format"] == "native"
        assert entry["sheet"] is None
        assert entry["path"] == str(tmp_path / "Draw1_all.slddrw")
        # swSaveAsOptions_Silent (1) | swSaveAsOptions_Copy (2) -- a side
        # copy for archive, not a re-point of the open document.
        assert fake_sw.call_log.arg_of("SaveAs3", 2) == 3

    def test_include_native_false_omits_native_entry(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        (tmp_path / "Draw1_all.pdf").write_bytes(b"stub")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["pdf"], "include_native": False,
            "overwrite": True,
        })

        assert result["success"] is True, result
        assert all(f["format"] != "native" for f in result["data"]["files"])


class TestBatchExportPackValidation:
    def test_unknown_format_rejected_before_com(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": ["png"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ForceRebuild3")
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_no_formats_and_no_native_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "formats": [], "include_native": False,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_empty_filename_pattern_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "filename_pattern": "   ",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_no_sheets_fails(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", [])
        _wire_saveas3_ok(fake_sw)

        result = dispatch("batch_export_pack", {"output_dir": str(tmp_path)})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw, tmp_path):
        tool_sw("part")

        result = dispatch("batch_export_pack", {"output_dir": str(tmp_path)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_creates_missing_output_directory(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        _wire_saveas3_ok(fake_sw)
        nested = tmp_path / "packs" / "2026"
        assert not nested.exists()

        result = dispatch("batch_export_pack", {
            "output_dir": str(nested), "formats": ["pdf"], "include_native": False,
        })

        # The directory is created even though the export itself then fails
        # (fake COM writes nothing, so the file-existence check fails) --
        # this only asserts the directory-creation side effect.
        assert nested.is_dir()
        assert result["success"] is False
