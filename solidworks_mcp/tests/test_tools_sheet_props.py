"""
Regression tests for the sheet-setup tools
(solidworks_mcp/tools/drawing_sheets.py: set_sheet_properties, set_sheet_scale,
get_sheet_properties), dispatched through the real `solidworks_mcp.tools`
registry (`dispatch()`) against the fake COM harness -- so these exercise
both the registry wiring and the `DrawingOperations` automation methods it
calls, asserting COM call order/args against the fake's call log the same
way solidworks_mcp/tests/test_tools_sheets.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDwgPaperSizes, SwDwgTemplates
from solidworks_mcp.tools import dispatch, sw_automation


def _script_current_sheet(sheet, paper_size=SwDwgPaperSizes.swDwgPaperA3size,
                           template_in=SwDwgTemplates.swDwgTemplateNone,
                           scale_num=1, scale_denom=1, first_angle=False,
                           width=0.42, height=0.297, name="Sheet1",
                           template_path=None):
    """Script `sheet` to answer `ISheet::GetProperties2`/`GetTemplateName`/
    `Name` the way a real sheet would, matching the 8-element
    `GetProperties2` array order documented in
    docs/api/01-documents-and-sheets.md. `template_path=None` (default)
    scripts `GetTemplateName`'s documented `"*.drt"` "no real template"
    sentinel; pass a real path for a sheet that uses a custom template."""
    sheet.set_return("Name", name)
    sheet.set_return("GetProperties2", [
        int(paper_size), int(template_in), scale_num, scale_denom,
        first_angle, width, height, False,
    ])
    sheet.set_return("GetTemplateName", template_path if template_path is not None else "*.drt")
    return sheet


class TestSetSheetProperties:
    def test_scale_only_update_preserves_paper_size_template_and_dimensions(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet(), width=0.42, height=0.297)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[:7] == (
            "Sheet1",
            int(SwDwgPaperSizes.swDwgPaperA3size),
            int(SwDwgTemplates.swDwgTemplateNone),
            1, 2, False, "",
        )
        assert args[7] == pytest.approx(0.42)
        assert args[8] == pytest.approx(0.297)
        assert args[9:] == ("", False)

    def test_named_paper_size_override_does_not_zero_current_dimensions(self, tool_sw):
        """A sheet with `TemplateIn=swDwgTemplateNone` has Width/Height "live"
        per the dossier's SetupSheet5 table (valid whenever `TemplateIn` is
        `swDwgTemplateNone`, *not* only when `PaperSize` is user-defined) --
        switching its named paper_size must not send `0, 0` for those two."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet(), width=0.42, height=0.297)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {
            "paper_size": "A4",
            "template_path": "/templates/custom.slddrt",
            "scale_num": 1, "scale_denom": 2,
            "first_angle": True,
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[:7] == (
            "Sheet1",
            int(SwDwgPaperSizes.swDwgPaperA4size),
            int(SwDwgTemplates.swDwgTemplateCustom),
            1, 2, True, "/templates/custom.slddrt",
        )
        assert args[7] == pytest.approx(0.42)
        assert args[8] == pytest.approx(0.297)
        assert args[9:] == ("", False)

    def test_custom_paper_size_converts_width_height_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {
            "paper_size": "custom", "width": 100, "height": 200,
            "scale_num": 1, "scale_denom": 1,
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[1] == int(SwDwgPaperSizes.swDwgPapersUserDefined)
        assert args[7] == pytest.approx(0.1)
        assert args[8] == pytest.approx(0.2)

    def test_custom_paper_size_preserves_current_dimensions_when_omitted(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(
            fake_sw.ActiveDoc.GetCurrentSheet(),
            paper_size=SwDwgPaperSizes.swDwgPapersUserDefined,
            width=0.3, height=0.2,
        )
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 4})

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[1] == int(SwDwgPaperSizes.swDwgPapersUserDefined)
        assert args[7] == pytest.approx(0.3)
        assert args[8] == pytest.approx(0.2)

    def test_zero_scale_denom_errors_without_touching_com(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 0})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert fake_sw.call_log.calls_to("SetupSheet5") == []
        assert fake_sw.call_log.calls_to("GetProperties2") == []

    def test_negative_width_errors_without_touching_com(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_sheet_properties", {
            "paper_size": "custom", "width": -10, "height": 100,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert fake_sw.call_log.calls_to("SetupSheet5") == []
        assert fake_sw.call_log.calls_to("GetProperties2") == []

    def test_negative_height_errors_without_touching_com(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_sheet_properties", {
            "paper_size": "custom", "width": 100, "height": -10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert fake_sw.call_log.calls_to("SetupSheet5") == []
        assert fake_sw.call_log.calls_to("GetProperties2") == []

    def test_width_without_custom_paper_size_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())

        result = dispatch("set_sheet_properties", {"width": 100})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert fake_sw.call_log.calls_to("SetupSheet5") == []

    def test_unknown_paper_size_errors_listing_valid_names(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())

        result = dispatch("set_sheet_properties", {"paper_size": "Q5"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Q5" in result["message"]
        assert "custom" in result["message"]

    def test_template_path_override_binds_custom_template(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {
            "template_path": "/templates/custom.slddrt",
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[2] == int(SwDwgTemplates.swDwgTemplateCustom)
        assert args[6] == "/templates/custom.slddrt"

    def test_current_custom_template_is_preserved_when_omitted(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(
            fake_sw.ActiveDoc.GetCurrentSheet(),
            template_in=SwDwgTemplates.swDwgTemplateCustom,
            template_path="/existing/current.slddrt",
        )
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[2] == int(SwDwgTemplates.swDwgTemplateCustom)
        assert args[6] == "/existing/current.slddrt"
        assert result["data"]["template_path"] == "/existing/current.slddrt"

    def test_current_custom_template_unreadable_errors_without_touching_setup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(
            fake_sw.ActiveDoc.GetCurrentSheet(),
            template_in=SwDwgTemplates.swDwgTemplateCustom,
            template_path=None,  # GetTemplateName reports the "*.drt" sentinel
        )

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert fake_sw.call_log.calls_to("SetupSheet5") == []

    def test_missing_sheet_name_errors_without_calling_setup_sheet5(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())
        # Both spellings `_sheet_name` tries: `ISheet::GetName` (the real
        # member, pre-scripted by the harness) and the `Name` property it
        # falls back to.
        sheet.set_return("ISheet.GetName", "")
        sheet.set_return("Name", "")

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is False
        assert fake_sw.call_log.calls_to("SetupSheet5") == []

    def test_first_angle_change_triggers_rebuild(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet(), first_angle=False)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {"first_angle": True})

        assert result["success"] is True
        assert len(fake_sw.call_log.calls_to("ForceRebuild3")) == 1
        assert fake_sw.call_log.calls_to("ForceRebuild3")[0].args == (False,)

    def test_first_angle_unchanged_does_not_trigger_rebuild(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet(), first_angle=False)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is True
        assert fake_sw.call_log.calls_to("ForceRebuild3") == []

    def test_unknown_sheet_name_errors_listing_available_sheets(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("Sheet", None)
        fake_sw.ActiveDoc.set_return("GetSheetNames", ["Sheet1", "Sheet2"])

        result = dispatch("set_sheet_properties", {
            "sheet_name": "Missing", "scale_num": 1, "scale_denom": 2,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Sheet1" in result["message"]
        assert "Sheet2" in result["message"]

    def test_setup_sheet5_returning_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())
        fake_sw.ActiveDoc.set_return("SetupSheet5", False)

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("set_sheet_properties", {"scale_num": 1, "scale_denom": 2})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestSetSheetScale:
    def test_delegates_to_set_sheet_properties_with_only_scale(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet(), width=0.42, height=0.297)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_scale", {"scale_num": 1, "scale_denom": 4})

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("SetupSheet5")[0].args
        assert args[:7] == (
            "Sheet1",
            int(SwDwgPaperSizes.swDwgPaperA3size),
            int(SwDwgTemplates.swDwgTemplateNone),
            1, 4, False, "",
        )
        assert args[7] == pytest.approx(0.42)
        assert args[8] == pytest.approx(0.297)
        assert args[9:] == ("", False)

    def test_zero_scale_denom_errors(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_sheet_scale", {"scale_num": 1, "scale_denom": 0})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_zero_scale_num_errors_without_touching_com(self, tool_sw):
        # A 0 numerator is as degenerate a sheet scale as a 0 denominator,
        # and SetupSheet5 reports neither -- so it's rejected pre-COM the
        # same way rather than sent through as a "successful" update.
        fake_sw = tool_sw("drawing")

        result = dispatch("set_sheet_scale", {"scale_num": 0, "scale_denom": 1})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetupSheet5")

    def test_resolves_the_active_sheet_name_via_isheet_getname(self, tool_sw):
        # The real ISheet member index has GetName/SetName and no bare `Name`
        # property (docs/api/01-documents-and-sheets.md's ISheet::SetName
        # record), so the no-sheet_name default mode has to work with only
        # GetName answering -- reading `Name` alone made it fail outright
        # against a real interop layer.
        fake_sw = tool_sw("drawing")
        sheet = _script_current_sheet(fake_sw.ActiveDoc.GetCurrentSheet())
        sheet.set_return("ISheet.GetName", "Sheet1")
        sheet.set_return("Name", None)
        fake_sw.ActiveDoc.set_return("SetupSheet5", True)

        result = dispatch("set_sheet_scale", {"scale_num": 1, "scale_denom": 4})

        assert result["success"] is True, result
        assert result["data"]["name"] == "Sheet1"
        assert fake_sw.call_log.calls_to("SetupSheet5")[0].args[0] == "Sheet1"


class TestGetSheetProperties:
    def test_happy_path_reports_scale_ratio_and_fields(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _script_current_sheet(
            fake_sw.ActiveDoc.GetCurrentSheet(),
            paper_size=SwDwgPaperSizes.swDwgPaperA4size,
            scale_num=1, scale_denom=2, first_angle=True,
            width=0.297, height=0.21,
        )

        result = dispatch("get_sheet_properties", {})

        assert result["success"] is True
        data = result["data"]
        assert data["name"] == "Sheet1"
        assert data["paper_size"] == "A4"
        assert data["scale_num"] == 1
        assert data["scale_denom"] == 2
        assert data["scale_ratio"] == "1:2"
        assert data["projection"] == "swDrawing1stAngleProjection"
        assert data["width"] == pytest.approx(297.0)
        assert data["height"] == pytest.approx(210.0)
        assert data["template_in"] == "swDwgTemplateNone"
        assert data["template_path"] is None

    def test_reports_real_template_path_when_sheet_uses_a_custom_template(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _script_current_sheet(
            fake_sw.ActiveDoc.GetCurrentSheet(),
            template_in=SwDwgTemplates.swDwgTemplateCustom,
            template_path="/templates/custom.slddrt",
        )

        result = dispatch("get_sheet_properties", {})

        assert result["success"] is True
        assert result["data"]["template_in"] == "swDwgTemplateCustom"
        assert result["data"]["template_path"] == "/templates/custom.slddrt"

    def test_unknown_sheet_name_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("Sheet", None)
        fake_sw.ActiveDoc.set_return("GetSheetNames", ["Sheet1"])

        result = dispatch("get_sheet_properties", {"sheet_name": "Missing"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_no_active_sheet_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetCurrentSheet", None)

        result = dispatch("get_sheet_properties", {})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("assembly")

        result = dispatch("get_sheet_properties", {})

        assert result["success"] is False
        assert "Assembly" in result["message"]
