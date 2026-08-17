"""
Regression tests for the sheet-management tools
(solidworks_mcp/tools/drawing_sheets.py: add_sheet, activate_sheet,
list_sheets, get_active_sheet), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
so these exercise both the registry wiring and the `DrawingOperations`
automation methods it calls, asserting COM call order/args against the
fake's call log the same way solidworks_mcp/tests/test_tools_document.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDwgPaperSizes, SwDwgTemplates
from solidworks_mcp.tools import dispatch, sw_automation

# `tool_sw` (the drawing-mode factory connecting the shared
# `tools.sw_automation` singleton that `dispatch()` calls through) comes from
# conftest.py.


class TestAddSheet:
    def test_happy_path_passes_new_sheet4_args_in_dossier_order(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("NewSheet4", True)

        result = dispatch("add_sheet", {"name": "Sheet2"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with(
            "NewSheet4",
            "Sheet2",
            int(SwDwgPaperSizes.swDwgPaperA3size),
            int(SwDwgTemplates.swDwgTemplateNone),
            1, 1, False, "",
            0.0, 0.0, "",
            0.0, 0.0, 0.0, 0.0, 0, 0,
        )

    def test_custom_paper_size_converts_width_height_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("NewSheet4", True)

        result = dispatch("add_sheet", {
            "name": "Sheet2", "paper_size": "custom", "width": 100, "height": 200,
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("NewSheet4")[0].args
        assert args[1] == int(SwDwgPaperSizes.swDwgPapersUserDefined)
        assert args[7] == pytest.approx(0.1)
        assert args[8] == pytest.approx(0.2)

    def test_custom_paper_size_without_width_and_height_errors(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("add_sheet", {"name": "Sheet2", "paper_size": "custom"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "width" in result["message"]

    def test_width_without_custom_paper_size_errors(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("add_sheet", {"name": "Sheet2", "width": 100})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_unknown_paper_size_errors_listing_valid_names(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("add_sheet", {"name": "Sheet2", "paper_size": "Q5"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Q5" in result["message"]
        assert "custom" in result["message"]
        assert "A3" in result["message"]

    def test_template_path_binds_template_in_custom_and_template_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("NewSheet4", True)

        result = dispatch("add_sheet", {
            "name": "Sheet2", "template_path": "/templates/custom.slddrt",
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("NewSheet4")[0].args
        assert args[2] == int(SwDwgTemplates.swDwgTemplateCustom)
        assert args[6] == "/templates/custom.slddrt"

    def test_first_angle_and_scale_are_passed_through(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("NewSheet4", True)

        result = dispatch("add_sheet", {
            "name": "Sheet2", "first_angle": True, "scale_num": 1, "scale_denom": 2,
        })

        assert result["success"] is True
        args = fake_sw.call_log.calls_to("NewSheet4")[0].args
        assert args[3] == 1
        assert args[4] == 2
        assert args[5] is True

    def test_new_sheet4_returning_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("NewSheet4", False)

        result = dispatch("add_sheet", {"name": "Sheet2"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("add_sheet", {"name": "Sheet2"})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestActivateSheet:
    def test_happy_path(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)

        result = dispatch("activate_sheet", {"name": "Sheet2"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("ActivateSheet", "Sheet2")

    def test_unknown_sheet_errors_listing_available_sheets(self, tool_sw):
        fake_sw = tool_sw("drawing", sheet_names=["Sheet1", "Sheet2"])
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)

        result = dispatch("activate_sheet", {"name": "NoSuchSheet"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Sheet1" in result["message"]
        assert "Sheet2" in result["message"]
        assert result["data"]["available_sheets"] == ["Sheet1", "Sheet2"]

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("assembly")

        result = dispatch("activate_sheet", {"name": "Sheet2"})

        assert result["success"] is False
        assert "Assembly" in result["message"]


class TestListSheets:
    def test_get_sheet_names_returns_a_tuple_and_resolves_each_sheet_independently(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))
        sheet1 = fake_sw.new_object("sheet1")
        sheet1.set_return("sheet1.GetProperties2", [
            int(SwDwgPaperSizes.swDwgPaperA3size), int(SwDwgTemplates.swDwgTemplateNone),
            1, 1, False, 0.42, 0.297, False,
        ])
        sheet2 = fake_sw.new_object("sheet2")
        sheet2.set_return("sheet2.GetProperties2", [
            int(SwDwgPaperSizes.swDwgPaperA4size), int(SwDwgTemplates.swDwgTemplateNone),
            1, 2, True, 0.297, 0.21, False,
        ])
        fake_sw.ActiveDoc.set_sequence("Sheet", [sheet1, sheet2])

        result = dispatch("list_sheets", {})

        assert result["success"] is True
        sheet_calls = fake_sw.call_log.calls_to("Sheet")
        assert [c.args for c in sheet_calls] == [("Sheet1",), ("Sheet2",)]
        [first, second] = result["data"]["sheets"]
        assert first["name"] == "Sheet1"
        assert first["paper_size"] == "A3"
        assert first["scale_denom"] == 1
        assert second["name"] == "Sheet2"
        assert second["paper_size"] == "A4"
        assert second["scale_denom"] == 2
        assert second["projection"] == "swDrawing1stAngleProjection"

    def test_sheet_accessor_returning_none_reports_null_fields_instead_of_failing(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))
        fake_sw.ActiveDoc.set_return("Sheet", None)

        result = dispatch("list_sheets", {})

        assert result["success"] is True
        [described] = result["data"]["sheets"]
        assert described == {
            "name": "Sheet1", "scale_num": None, "scale_denom": None,
            "paper_size_code": None, "paper_size": None, "projection": None,
            "width": None, "height": None, "view_count": 0,
        }

    def test_get_sheet_names_returns_a_single_bare_string(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", "Sheet1")

        result = dispatch("list_sheets", {})

        assert result["success"] is True
        names = [s["name"] for s in result["data"]["sheets"]]
        assert names == ["Sheet1"]

    def test_get_sheet_names_returns_none(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", None)

        result = dispatch("list_sheets", {})

        assert result["success"] is True
        assert result["data"]["sheets"] == []

    def test_happy_path_reports_scale_size_projection_and_view_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("GetSheetNames", ["Sheet1"])
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetProperties2", [
            int(SwDwgPaperSizes.swDwgPaperA3size), int(SwDwgTemplates.swDwgTemplateNone),
            1, 2, True, 0.42, 0.297, False,
        ])
        view = fake_sw.new_object("view1")
        view.set_return("Type", 0)
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("Sheet", sheet)

        result = dispatch("list_sheets", {})

        assert result["success"] is True
        [described] = result["data"]["sheets"]
        assert described["name"] == "Sheet1"
        assert described["scale_num"] == 1
        assert described["scale_denom"] == 2
        assert described["paper_size"] == "A3"
        assert described["projection"] == "swDrawing1stAngleProjection"
        assert described["width"] == pytest.approx(420.0)
        assert described["height"] == pytest.approx(297.0)
        assert described["view_count"] == 1

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("list_sheets", {})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestGetActiveSheet:
    def test_happy_path_reports_name_scale_and_size(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("Name", "Sheet1")
        sheet.set_return("GetProperties2", [
            int(SwDwgPaperSizes.swDwgPaperA4size), int(SwDwgTemplates.swDwgTemplateNone),
            1, 1, False, 0.297, 0.21, False,
        ])

        result = dispatch("get_active_sheet", {})

        assert result["success"] is True
        assert result["data"]["name"] == "Sheet1"
        assert result["data"]["scale_num"] == 1
        assert result["data"]["scale_denom"] == 1
        assert result["data"]["paper_size"] == "A4"
        assert result["data"]["projection"] == "swDrawing3rdAngleProjection"
        assert result["data"]["width"] == pytest.approx(297.0)
        assert result["data"]["height"] == pytest.approx(210.0)

    def test_name_comes_from_isheet_getname_when_no_name_property_exists(self, tool_sw):
        # A real ISheet exposes GetName, not a `Name` property (see
        # docs/api/01-documents-and-sheets.md's ISheet::SetName record), so
        # get_active_sheet must still report a name when only GetName answers.
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("ISheet.GetName", "Sheet1")
        sheet.set_return("Name", None)

        result = dispatch("get_active_sheet", {})

        assert result["success"] is True, result
        assert result["data"]["name"] == "Sheet1"

    def test_no_active_sheet_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetCurrentSheet", None)

        result = dispatch("get_active_sheet", {})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("assembly")

        result = dispatch("get_active_sheet", {})

        assert result["success"] is False
        assert "Assembly" in result["message"]
