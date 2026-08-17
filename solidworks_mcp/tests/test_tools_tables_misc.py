"""
Regression tests for the hole table, revision table, and weldment cut list
tools (solidworks_mcp/tools/drawing_tables.py's insert_hole_table,
insert_revision_table, add_revision, insert_weldment_cutlist), dispatched
through the real `solidworks_mcp.tools` registry (`dispatch()`) against the
fake COM harness -- same convention as test_tools_bom.py/test_tools_balloons.py:
exercise both the registry wiring and the `DrawingOperations` automation
methods, asserting COM call names/order/args against the fake's call log.
"""

import datetime

import pytest

from solidworks_mcp.constants_drawing import (
    SwBOMConfigurationAnchorType,
    SwDrawingViewTypes,
    SwHoleTableTagOrder,
    SwHoleTableTagStyle,
    SwRevisionTableSymbolShape,
    SwTableAnnotationType,
)
from solidworks_mcp.tools import dispatch, sw_automation


def _view(fake_sw, obj_id, name, type_code=None, first_table=None):
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    view.set_return(f"{obj_id}.GetFirstTableAnnotation", first_table)
    view.set_return(f"{obj_id}.GetNextView", None)
    return view


def _hole_table(fake_sw, obj_id, name="HoleTable1", row_count=5, column_count=4,
                 position=(0.05, 0.03, 0.0)):
    """A fake `IHoleTableAnnotation` -> `GetAnnotation` -> `IAnnotation` chain.
    `HoleTable` (the `IHoleTable` feature `CombineSameSize` lives on) is left
    to auto-vivify -- a bare `table.HoleTable` access always returns the same
    cached child object, so a test can grab it after `dispatch()` via the
    same `table.HoleTable` the production code used."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))

    table = fake_sw.new_object(obj_id)
    table.set_return(f"{obj_id}.GetAnnotation", ann)
    table.set_return(f"{obj_id}.RowCount", row_count)
    table.set_return(f"{obj_id}.ColumnCount", column_count)
    return table, ann


def _revision_table(fake_sw, obj_id, name="RevisionTable1", row_count=1, column_count=5,
                     position=(0.0, 0.0, 0.0), current_revision=None):
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))

    table = fake_sw.new_object(obj_id)
    table.set_return(f"{obj_id}.GetAnnotation", ann)
    table.set_return(f"{obj_id}.Type", int(SwTableAnnotationType.swTableAnnotation_RevisionBlock))
    table.set_return(f"{obj_id}.RowCount", row_count)
    table.set_return(f"{obj_id}.ColumnCount", column_count)
    table.set_return(f"{obj_id}.TotalColumnCount", column_count)
    if current_revision is not None:
        table.set_return(f"{obj_id}.CurrentRevision", current_revision)
    table.set_return(f"{obj_id}.GetNext", None)
    return table, ann


def _columns(table, titles):
    """Script `GetColumnTitle2(i, True)` to answer `titles[i]` for
    successive `i` -- `add_revision`'s column-index-by-title lookup."""
    table.set_sequence("GetColumnTitle2", list(titles))


def _weldment_table(fake_sw, obj_id, name="CutList1", row_count=3, column_count=4,
                     position=(0.0, 0.0, 0.0), has_feature=True):
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))

    table = fake_sw.new_object(obj_id)
    table.set_return(f"{obj_id}.GetAnnotation", ann)
    table.set_return(f"{obj_id}.RowCount", row_count)
    table.set_return(f"{obj_id}.ColumnCount", column_count)
    if has_feature:
        feature = fake_sw.new_object(f"{obj_id}.feature")
        table.set_return(f"{obj_id}.WeldmentCutListFeature", feature)
    else:
        table.set_return(f"{obj_id}.WeldmentCutListFeature", None)
    return table, ann


class TestInsertHoleTable:
    def test_selects_datum_before_insert_hole_table3(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        table, _ann = _hole_table(fake_sw, "t1")
        view.set_return("v1.InsertHoleTable3", table)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 10, "y": 20, "template_path": "/tpl/hole-standard.sldholtbt",
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("InsertHoleTable3")
        select_args = fake_sw.call_log.calls_to("SelectByID2")[0].args
        assert select_args[6] == 1  # Mark=1

    def test_positional_args_match_dossier_order(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        table, _ann = _hole_table(fake_sw, "t1", name="HoleTable1", row_count=6, column_count=4)
        view.set_return("v1.InsertHoleTable3", table)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0, "z": 0},
            "x": 50, "y": 25, "template_path": "/tpl/hole-standard.sldholtbt",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertHoleTable3")[0].args
        assert args[:8] == (
            False, pytest.approx(0.05), pytest.approx(0.025),
            int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft),
            "A", "/tpl/hole-standard.sldholtbt",
            int(SwHoleTableTagOrder.swHoleTableTagOrder_XY),
            int(SwHoleTableTagStyle.swHoleTable_AlphaNumericTags),
        )
        assert args[8].value is None  # ManualTags: null VT_DISPATCH
        assert result["data"]["name"] == "HoleTable1"
        assert result["data"]["row_count"] == 6
        assert result["data"]["column_count"] == 4

    def test_numeric_tag_style_uses_start_value_1(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        table, _ann = _hole_table(fake_sw, "t1")
        view.set_return("v1.InsertHoleTable3", table)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "edge", "x": 1, "y": 2},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
            "tag_style": "numeric",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertHoleTable3")[0].args
        assert args[4] == "1"
        assert args[7] == int(SwHoleTableTagStyle.swHoleTable_NumericTags)

    def test_combine_same_size_defaults_true(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        table, _ann = _hole_table(fake_sw, "t1")
        view.set_return("v1.InsertHoleTable3", table)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
        })

        assert result["success"] is True, result
        assert table.HoleTable.CombineSameSize is True

    def test_combine_same_size_false_is_respected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        table, _ann = _hole_table(fake_sw, "t1")
        view.set_return("v1.InsertHoleTable3", table)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
            "combine_same_size": False,
        })

        assert result["success"] is True, result
        assert table.HoleTable.CombineSameSize is False

    def test_datum_entity_must_be_vertex_or_edge(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "face", "x": 0, "y": 0},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertHoleTable3")
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_unknown_tag_style_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
            "tag_style": "manual",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertHoleTable3")

    def test_insert_returning_nothing_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        view.set_return("v1.InsertHoleTable3", None)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 0, "y": 0, "template_path": "/tpl/hole-standard.sldholtbt",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_missing_template_with_no_discoverable_default_errors(self, tool_sw, monkeypatch):
        fake_sw = tool_sw("drawing")
        monkeypatch.setattr("solidworks_mcp.automation.drawings.find_template", lambda t: None)

        result = dispatch("insert_hole_table", {
            "view_name": "Drawing View1",
            "datum_entity": {"kind": "vertex", "x": 0, "y": 0},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swTemplateNotFound"
        assert not fake_sw.call_log.calls_to("InsertHoleTable3")


class TestInsertRevisionTable:
    def test_anchor_mode_positional_args(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        table, _ann = _revision_table(fake_sw, "rt1")
        sheet.set_return("InsertRevisionTable2", table)

        result = dispatch("insert_revision_table", {"template_path": "/tpl/rev.sldrevtbt"})

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertRevisionTable2")[0].args
        assert args == (
            True, pytest.approx(0.0), pytest.approx(0.0),
            int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft),
            "/tpl/rev.sldrevtbt",
            int(SwRevisionTableSymbolShape.swRevisionTable_CircleSymbol),
            True,
        )
        assert result["data"]["name"] == "RevisionTable1"

    def test_xy_mode_positional_args(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        table, _ann = _revision_table(fake_sw, "rt1")
        sheet.set_return("InsertRevisionTable2", table)

        result = dispatch("insert_revision_table", {
            "template_path": "/tpl/rev.sldrevtbt", "anchor": False, "x": 100, "y": 50,
            "symbol_shape": "hexagon",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertRevisionTable2")[0].args
        assert args[0] is False
        assert args[1] == pytest.approx(0.1)
        assert args[2] == pytest.approx(0.05)
        assert args[5] == int(SwRevisionTableSymbolShape.swRevisionTable_HexagonSymbol)

    def test_anchor_true_with_xy_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_revision_table", {"x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertRevisionTable2")

    def test_anchor_false_without_xy_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_revision_table", {"anchor": False})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertRevisionTable2")

    def test_unknown_symbol_shape_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_revision_table", {"symbol_shape": "star"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertRevisionTable2")

    def test_returning_none_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("InsertRevisionTable2", None)

        result = dispatch("insert_revision_table", {"template_path": "/tpl/rev.sldrevtbt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_missing_template_with_no_discoverable_default_errors(self, tool_sw, monkeypatch):
        fake_sw = tool_sw("drawing")
        monkeypatch.setattr("solidworks_mcp.automation.drawings.find_template", lambda t: None)

        result = dispatch("insert_revision_table", {})

        assert result["success"] is False
        assert result["error_name"] == "swTemplateNotFound"
        assert not fake_sw.call_log.calls_to("InsertRevisionTable2")


class TestAddRevision:
    def test_auto_increment_a_to_b(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A")
        _columns(table, ["ZONE", "REV", "DESCRIPTION", "DATE", "APPROVED BY"])
        table.set_return("AddRevision", 1)
        table.set_return("GetRowNumberForId", 1)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "Updated bracket thickness"})

        assert result["success"] is True, result
        assert result["data"]["revision"] == "B"
        call = fake_sw.call_log.calls_to("AddRevision")[0]
        assert call.args == ("B",)

    def test_auto_increment_1_to_2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="1", column_count=3)
        _columns(table, ["REV", "DESCRIPTION", "DATE"])
        table.set_return("AddRevision", 2)
        table.set_return("GetRowNumberForId", 2)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "Fixed hole callout"})

        assert result["success"] is True, result
        assert result["data"]["revision"] == "2"
        call = fake_sw.call_log.calls_to("AddRevision")[0]
        assert call.args == ("2",)

    def test_first_revision_defaults_to_a_when_table_empty(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="", column_count=3)
        _columns(table, ["REV", "DESCRIPTION", "DATE"])
        table.set_return("AddRevision", 0)
        table.set_return("GetRowNumberForId", 0)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "Initial release"})

        assert result["success"] is True, result
        assert result["data"]["revision"] == "A"

    def test_date_defaults_to_today_mm_dd_yy(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A", column_count=3)
        _columns(table, ["REV", "DESCRIPTION", "DATE"])
        table.set_return("AddRevision", 1)
        table.set_return("GetRowNumberForId", 1)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "test"})

        assert result["success"] is True, result
        expected_date = datetime.date.today().strftime("%m/%d/%y")
        assert result["data"]["date"] == expected_date
        date_calls = [c for c in fake_sw.call_log.calls_to("Text") if c.args[1] == 2]
        assert date_calls[0].args[2] == expected_date

    def test_explicit_revision_bypasses_auto_increment(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A", column_count=3)
        _columns(table, ["REV", "DESCRIPTION", "DATE"])
        table.set_return("AddRevision", 5)
        table.set_return("GetRowNumberForId", 5)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "Redline", "revision": "X"})

        assert result["success"] is True, result
        assert result["data"]["revision"] == "X"
        assert fake_sw.call_log.calls_to("AddRevision")[0].args == ("X",)

    def test_no_revision_table_found_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "test"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_approved_by_and_zone_written_when_columns_exist(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A", column_count=5)
        _columns(table, ["ZONE", "REV", "DESCRIPTION", "DATE", "APPROVED BY"])
        table.set_return("AddRevision", 1)
        table.set_return("GetRowNumberForId", 1)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {
            "description": "Updated tolerance", "approved_by": "J. Smith", "zone": "B3",
        })

        assert result["success"] is True, result
        assert "skipped_fields" not in result["data"]
        text_by_col = {c.args[1]: c.args[2] for c in fake_sw.call_log.calls_to("Text")}
        assert text_by_col[2] == "Updated tolerance"  # DESCRIPTION column
        assert text_by_col[4] == "J. Smith"  # APPROVED BY column
        assert text_by_col[0] == "B3"  # ZONE column

    def test_skips_missing_optional_columns(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A", column_count=3)
        _columns(table, ["REV", "DESCRIPTION", "DATE"])
        table.set_return("AddRevision", 1)
        table.set_return("GetRowNumberForId", 1)
        table.set_return("Text", True)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {
            "description": "Updated tolerance", "approved_by": "J. Smith", "zone": "B3",
        })

        assert result["success"] is True, result
        assert set(result["data"]["skipped_fields"]) == {"approved_by", "zone"}

    def test_missing_description_column_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _revision_table(fake_sw, "rt1", current_revision="A", column_count=1)
        _columns(table, ["REV"])
        table.set_return("AddRevision", 1)
        table.set_return("GetRowNumberForId", 1)
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("add_revision", {"description": "test"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestInsertWeldmentCutlist:
    def test_positional_args_match_dossier_order(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _weldment_table(fake_sw, "t1")
        view.set_return("v1.InsertWeldmentTable", table)

        result = dispatch("insert_weldment_cutlist", {
            "view_name": "Drawing View1", "x": 50, "y": 25,
            "template_path": "/tpl/cut list.sldwldtbt",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertWeldmentTable")[0].args
        assert args == (
            False, pytest.approx(0.05), pytest.approx(0.025),
            int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft),
            "", "/tpl/cut list.sldwldtbt",
        )

    def test_no_weldment_cutlist_feature_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _weldment_table(fake_sw, "t1", has_feature=False)
        view.set_return("v1.InsertWeldmentTable", table)

        result = dispatch("insert_weldment_cutlist", {
            "view_name": "Drawing View1", "x": 10, "y": 10,
            "template_path": "/tpl/cut list.sldwldtbt",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_success_reads_row_column_counts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _weldment_table(fake_sw, "t1", name="CutList1", row_count=6, column_count=5)
        view.set_return("v1.InsertWeldmentTable", table)

        result = dispatch("insert_weldment_cutlist", {
            "view_name": "Drawing View1", "x": 10, "y": 10,
            "template_path": "/tpl/cut list.sldwldtbt",
        })

        assert result["success"] is True, result
        assert result["data"]["name"] == "CutList1"
        assert result["data"]["row_count"] == 6
        assert result["data"]["column_count"] == 5

    def test_insert_returning_nothing_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        view.set_return("v1.InsertWeldmentTable", None)

        result = dispatch("insert_weldment_cutlist", {
            "view_name": "Drawing View1", "x": 10, "y": 10,
            "template_path": "/tpl/cut list.sldwldtbt",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_missing_template_with_no_discoverable_default_errors(self, tool_sw, monkeypatch):
        fake_sw = tool_sw("drawing")
        monkeypatch.setattr("solidworks_mcp.automation.drawings.find_template", lambda t: None)

        result = dispatch("insert_weldment_cutlist", {
            "view_name": "Drawing View1", "x": 10, "y": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swTemplateNotFound"
        assert not fake_sw.call_log.calls_to("InsertWeldmentTable")
