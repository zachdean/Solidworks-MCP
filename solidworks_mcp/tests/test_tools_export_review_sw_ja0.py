"""
Regression tests for the `/review` findings on the sw-jcq drawing-export epic
(sw-ja0).
-----------------------------------------------------------------------------
Each class below pins one defect that the export tools shipped with and that a
green suite did not catch, so the fix can't silently regress. Same conventions
as solidworks_mcp/tests/test_tools_export_pdf.py: dispatched through the real
`solidworks_mcp.tools` registry against the fake COM harness, with "the file
was really written" simulated by pre-creating it at the expected path.

The through-line is that a COM call's *reported* failure has to become a failed
result: a refused preference write, a refused `SetSheets`, or a `VARIANT_BOOL`
that arrives as `0` instead of `False` all used to be discarded, leaving an
export that ran under the wrong settings and still reported success.
"""

import json

from solidworks_mcp.automation.drawings import _com_bool, _looks_like_missing_addin
from solidworks_mcp.constants_drawing import SwUserPreferenceIntegerValue
from solidworks_mcp.tools import dispatch


def _wire_export_data(fake_sw):
    """`GetExportFileData` -> a fresh `IExportPdfData` whose `SetSheets`
    succeeds, plus a succeeding `SaveAs3` (test_tools_export_pdf.py's helper,
    duplicated here so this module reads standalone)."""
    export_data = fake_sw.new_object("export_data")
    export_data.set_return("SetSheets", True)
    fake_sw.set_return("GetExportFileData", export_data)
    fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
    return export_data


class TestComBool:
    """`_com_bool` -- the `VARIANT_BOOL`-as-`int` normalizer the layer pass
    needs. An `is False` identity test misses the `0` form entirely."""

    def test_zero_and_minus_one_read_as_booleans(self):
        assert _com_bool(0) is False
        assert _com_bool(-1) is True
        assert _com_bool(1) is True

    def test_real_booleans_pass_through(self):
        assert _com_bool(False) is False
        assert _com_bool(True) is True

    def test_non_boolean_values_are_inconclusive(self):
        """`None` (a failed `_read_prop`) and an opaque object are "no answer",
        not `False` -- callers must be able to skip rather than guess."""
        assert _com_bool(None) is None
        assert _com_bool("False") is None
        assert _com_bool(object()) is None


class TestKeepInvisibleLayersWithIntegerVariantBool:
    def test_layer_hidden_as_int_zero_is_still_shown_and_restored(
            self, tool_sw, tmp_path):
        """The bug: `Visible` arriving as `0` rather than `False` made
        `keep_invisible_layers=True` a silent no-op, producing the same PDF as
        `False` while still reporting success."""
        fake_sw = tool_sw("drawing")
        _wire_export_data(fake_sw)
        layer_mgr = fake_sw.new_object("layer_mgr")
        fake_sw.ActiveDoc.set_return("GetLayerManager", layer_mgr)
        layer_mgr.set_return("GetLayerList", ["Hidden1"])
        hidden_layer = fake_sw.new_object("hidden_layer")
        # The `int` form of VARIANT_BOOL, as some interop layers hand it back.
        hidden_layer.set_return("hidden_layer.Visible", 0)
        hidden_layer.set_return("hidden_layer.Printable", 1)
        layer_mgr.set_return("GetLayer", hidden_layer)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {
            "output_path": str(output_path), "keep_invisible_layers": True,
        })

        assert result["success"] is True, result
        # Shown for the export, then put back -- both assignments happened, so
        # the layer is no longer backed only by its scripted `0`.
        assert hidden_layer.Visible is False
        # `Printable` came back as `1`; it is re-asserted as a real `True`
        # rather than skipped for not being a `bool`.
        assert hidden_layer.Printable is True


class TestRefusedPreferenceWriteFailsTheExport:
    def test_integer_setter_returning_false_fails_dxf_export(
            self, tool_sw, tmp_path):
        """`SetUserPreferenceIntegerValue` returns False when the value was not
        set. Discarding that meant the export ran under whatever multi-sheet
        setting the session happened to hold and reported success."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        fake_sw.set_return("SetUserPreferenceIntegerValue", False)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"
        assert "SetUserPreferenceIntegerValue" in result["message"]
        assert not fake_sw.call_log.calls_to("SaveAs3")

    def test_toggle_setter_has_no_return_to_check(self, tool_sw, tmp_path):
        """`SetUserPreferenceToggle` is a `Sub`. Truth-testing its (absent)
        return would fail every PDF export, so it must stay unchecked."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_export_data(fake_sw)
        fake_sw.set_return("SetUserPreferenceToggle", None)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is True, result


class TestRefusedSetSheetsFailsThePdfExport:
    def test_set_sheets_returning_false_fails_before_saving(
            self, tool_sw, tmp_path):
        """`IExportPdfData::SetSheets` returns False when the selection was not
        applied. Unchecked, the export produced a PDF of whatever sheets the
        export-data object defaulted to and `_save_as3` still called it a
        success, since the file existed with `Errors == 0`."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        export_data = fake_sw.new_object("export_data")
        export_data.set_return("SetSheets", False)
        fake_sw.set_return("GetExportFileData", export_data)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.pdf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_pdf", {"output_path": str(output_path)})

        assert result["success"] is False
        assert result["error_name"] == "swExportError"
        assert "SetSheets" in result["message"]
        assert not fake_sw.call_log.calls_to("SaveAs3")


class TestPerSheetDxfPathSanitizing:
    def test_sheet_name_with_path_characters_stays_inside_output_dir(
            self, tool_sw, tmp_path):
        """A sheet name is free text in the drawing tree, not a filename:
        `1/2 SCALE` used to be interpolated straight into the path, aiming the
        export at a subdirectory nobody created."""
        fake_sw = tool_sw("drawing", sheet_names=["1/2 SCALE", "REV:A"])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        (tmp_path / "out_1_2 SCALE.dxf").write_bytes(b"one")
        (tmp_path / "out_REV_A.dxf").write_bytes(b"two")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(tmp_path / "out.dxf"),
            "multisheet": "separate_files",
        })

        assert result["success"] is True, result
        paths = [f["path"] for f in result["data"]["files"]]
        assert paths == [
            str(tmp_path / "out_1_2 SCALE.dxf"), str(tmp_path / "out_REV_A.dxf"),
        ]
        # The un-sanitized `sheet` name is still what the manifest reports --
        # sanitizing is about the path, not about renaming the caller's sheet.
        assert [f["sheet"] for f in result["data"]["files"]] == ["1/2 SCALE", "REV:A"]

    def test_two_sheets_sanitizing_onto_one_name_get_distinct_files(
            self, tool_sw, tmp_path):
        """`1/2` and `1_2` both sanitize to `1_2`; without dedup the second
        export would overwrite the first and the tool would report two files
        where one exists."""
        fake_sw = tool_sw("drawing", sheet_names=["1/2", "1_2"])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        (tmp_path / "out_1_2.dxf").write_bytes(b"one")
        (tmp_path / "out_1_2_2.dxf").write_bytes(b"two")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(tmp_path / "out.dxf"),
            "multisheet": "separate_files",
        })

        assert result["success"] is True, result
        paths = [f["path"] for f in result["data"]["files"]]
        assert paths == [
            str(tmp_path / "out_1_2.dxf"), str(tmp_path / "out_1_2_2.dxf"),
        ]
        assert len(set(paths)) == 2


class TestActiveSheetRestoredAfterPerSheetLoop:
    def test_dxf_per_sheet_export_puts_the_original_sheet_back(
            self, tool_sw, tmp_path):
        """The loop leaves the *last* sheet active. Every other session
        mutation here is snapshot-and-restored, and the active sheet is what a
        following `export_pdf(sheets="current")` reads."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        current = fake_sw.new_object("current_sheet")
        current.set_return("current_sheet.Name", "Sheet1")
        fake_sw.ActiveDoc.set_return("GetCurrentSheet", current)
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        (tmp_path / "out_Sheet1.dxf").write_bytes(b"one")
        (tmp_path / "out_Sheet2.dxf").write_bytes(b"two")

        result = dispatch("export_dxf_dwg", {
            "output_path": str(tmp_path / "out.dxf"),
            "multisheet": "separate_files",
        })

        assert result["success"] is True, result
        activated = [c.args[0] for c in fake_sw.call_log.calls_to("ActivateSheet")]
        assert activated == ["Sheet1", "Sheet2", "Sheet1"]

    def test_combined_export_never_touches_the_active_sheet(
            self, tool_sw, tmp_path):
        """Nothing to restore when nothing was switched -- the restore must not
        introduce an `ActivateSheet` call of its own."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        output_path = tmp_path / "out.dxf"
        output_path.write_bytes(b"stub")

        result = dispatch("export_dxf_dwg", {"output_path": str(output_path)})

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("ActivateSheet")

    def test_batch_export_per_sheet_pdf_only_never_switches_sheets(
            self, tool_sw, tmp_path):
        """PDF drives `SetSheets`, so the per-sheet batch loop has no sheet to
        switch -- and therefore none to put back."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        (tmp_path / "Draw1_Sheet1.pdf").write_bytes(b"one")
        (tmp_path / "Draw1_Sheet2.pdf").write_bytes(b"two")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "per_sheet": True,
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        assert result["data"]["total"] == 2
        assert not fake_sw.call_log.calls_to("ActivateSheet")

    def test_batch_export_per_sheet_dxf_puts_the_original_sheet_back(
            self, tool_sw, tmp_path):
        """DXF has no "these specific sheets" mode, so this loop *does* switch
        sheets -- and must restore the one it found."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        current = fake_sw.new_object("current_sheet")
        current.set_return("current_sheet.Name", "Sheet2")
        fake_sw.ActiveDoc.set_return("GetCurrentSheet", current)
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        (tmp_path / "Draw1_Sheet1.dxf").write_bytes(b"one")
        (tmp_path / "Draw1_Sheet2.dxf").write_bytes(b"two")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "per_sheet": True, "formats": ["dxf"],
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        activated = [c.args[0] for c in fake_sw.call_log.calls_to("ActivateSheet")]
        assert activated[-1] == "Sheet2"


class TestBatchExportFilenamePattern:
    def test_index_with_a_format_spec_is_accepted(self, tool_sw, tmp_path):
        """`{index:02d}` discriminates between sheets just as well as
        `{index}`; a substring test for the bare token rejected it."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)
        (tmp_path / "Draw1_01.pdf").write_bytes(b"one")
        (tmp_path / "Draw1_02.pdf").write_bytes(b"two")

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path), "per_sheet": True,
            "filename_pattern": "{drawing}_{index:02d}",
            "include_native": False, "overwrite": True,
        })

        assert result["success"] is True, result
        assert [f["path"] for f in result["data"]["files"]] == [
            str(tmp_path / "Draw1_01.pdf"), str(tmp_path / "Draw1_02.pdf"),
        ]

    def test_pattern_with_no_sheet_discriminator_is_still_rejected(
            self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        _wire_export_data(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path / "pack"), "per_sheet": True,
            "filename_pattern": "{drawing}_{date}",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_value_dependent_pattern_failure_returns_a_result_not_an_exception(
            self, tool_sw, tmp_path):
        """`{rev[0]}` formats fine against the placeholder pre-flight and then
        raises on the real, empty `rev` -- which must not escape the tool."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_export_data(fake_sw)

        result = dispatch("batch_export_pack", {
            "output_dir": str(tmp_path / "pack"),
            "filename_pattern": "{drawing}_{rev[0]}",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "filename_pattern" in result["message"]


class TestBatchExportManifestRespectsOverwrite:
    def test_existing_manifest_is_not_truncated_when_overwrite_is_false(
            self, tool_sw, tmp_path):
        """`overwrite=False` refuses to touch any existing output path; the
        manifest is an output too, and the one most likely to already be there
        from a prior export into the same folder."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_export_data(fake_sw)
        output_dir = tmp_path / "pack"
        output_dir.mkdir()
        manifest = output_dir / "manifest.json"
        manifest.write_text(json.dumps({"previous": "run"}))

        result = dispatch("batch_export_pack", {
            "output_dir": str(output_dir), "overwrite": False,
        })

        assert result["data"]["manifest_path"] is None, result
        assert json.loads(manifest.read_text()) == {"previous": "run"}

    def test_manifest_is_written_when_overwrite_is_true(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        _wire_export_data(fake_sw)
        output_dir = tmp_path / "pack"
        output_dir.mkdir()
        manifest = output_dir / "manifest.json"
        manifest.write_text(json.dumps({"previous": "run"}))

        result = dispatch("batch_export_pack", {
            "output_dir": str(output_dir), "overwrite": True,
        })

        assert result["data"]["manifest_path"] == str(manifest), result
        assert "files" in json.loads(manifest.read_text())


class TestLooksLikeMissingAddin:
    def test_addin_wording_still_matches(self):
        assert _looks_like_missing_addin("The eDrawings add-in is not loaded")
        assert _looks_like_missing_addin("addin unavailable")

    def test_a_quoted_edrawings_path_is_not_an_addin_diagnosis(self):
        r"""Every target of this export ends in `.edrw` and operators export
        into directories like `C:\Exports\eDrawings\`, so keying on the bare
        word sent them to load an add-in that was already there."""
        assert not _looks_like_missing_addin(
            r"Access is denied: C:\Exports\eDrawings\pack.edrw")
        assert not _looks_like_missing_addin("could not write out.edrw")


class TestExportEdrawingsFailurePathsCarryAddinAvailable:
    def test_refused_preference_write_reports_addin_available(
            self, tool_sw, tmp_path):
        """`addin_available` is documented as present on *every* failure, and
        `_result` drops a falsy `data` entirely -- so a caller reading
        `data["addin_available"]` used to get a `KeyError` here."""
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1"])
        fake_sw.set_return("SetUserPreferenceIntegerValue", False)

        result = dispatch("export_edrawings", {
            "output_path": str(tmp_path / "out.edrw"),
        })

        assert result["success"] is False
        assert result["data"]["addin_available"] is True
        pref = int(SwUserPreferenceIntegerValue.swEdrawingsSaveAsSelectionOption)
        assert pref in [
            c.args[0] for c in fake_sw.call_log.calls_to("SetUserPreferenceIntegerValue")
        ]

    def test_bad_sheets_value_reports_addin_available(self, tool_sw, tmp_path):
        tool_sw("drawing", sheet_names=["Sheet1"])

        result = dispatch("export_edrawings", {
            "output_path": str(tmp_path / "out.edrw"), "sheets": ["Sheet1"],
        })

        assert result["success"] is False
        assert result["data"]["addin_available"] is True

    def test_bad_extension_reports_addin_available(self, tool_sw, tmp_path):
        tool_sw("drawing", sheet_names=["Sheet1"])

        result = dispatch("export_edrawings", {
            "output_path": str(tmp_path / "out.pdf"),
        })

        assert result["success"] is False
        assert result["data"]["addin_available"] is True


class TestSaveDrawingBindsThroughTheSignature:
    def test_saveas3_argument_order_matches_the_com_signature(
            self, tool_sw, tmp_path):
        """`save_drawing` hand-transcribed the same 7-positional call the
        `SAVE_AS3` `ComSignature` exists to make un-transposable."""
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SaveAs3", True)
        filepath = tmp_path / "saved.slddrw"

        result = dispatch("save_drawing", {"filepath": str(filepath)})

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("SaveAs3")[0].args
        assert len(args) == 7
        assert args[0] == str(filepath)
        assert args[1] == 0   # swSaveAsCurrentVersion
        assert args[2] == 1   # swSaveAsOptions_Silent
