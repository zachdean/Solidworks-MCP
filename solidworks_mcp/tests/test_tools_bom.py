"""
Regression tests for the BOM table tools (solidworks_mcp/tools/
drawing_tables.py's insert_bom_table, list_tables, get_bom_contents),
dispatched through the real `solidworks_mcp.tools` registry (`dispatch()`)
against the fake COM harness -- same convention as test_tools_notes.py:
exercise both the registry wiring and the `DrawingOperations` automation
methods, asserting COM call order/args against the fake's call log.
"""

import pytest

from solidworks_mcp.constants_drawing import (
    SwBOMConfigurationAnchorType,
    SwBomType,
    SwDrawingViewTypes,
    SwNumberingType,
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


def _chain_views(*views):
    for a, b in zip(views, views[1:]):
        a.set_return(f"{a._path}.GetNextView", b)


def _table(fake_sw, obj_id, name="BomTable1", type_code=SwTableAnnotationType.swTableAnnotation_BillOfMaterials,
           row_count=None, total_row_count=None, column_count=None, total_column_count=None,
           position=(0.1, 0.2, 0.0)):
    """A fake `IBomTableAnnotation` -> `GetAnnotation` -> `IAnnotation` chain,
    with `GetNext` pre-terminated at `None` (chain terminator, matching
    test_tools_notes.py's `_note` convention)."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    if position is not None:
        ann.set_return(f"{obj_id}.ann.GetPosition", list(position))

    table = fake_sw.new_object(obj_id)
    table.set_return(f"{obj_id}.GetAnnotation", ann)
    table.set_return(f"{obj_id}.Type", int(type_code))
    if row_count is not None:
        table.set_return(f"{obj_id}.RowCount", row_count)
    if total_row_count is not None:
        table.set_return(f"{obj_id}.TotalRowCount", total_row_count)
    if column_count is not None:
        table.set_return(f"{obj_id}.ColumnCount", column_count)
    if total_column_count is not None:
        table.set_return(f"{obj_id}.TotalColumnCount", total_column_count)
    table.set_return(f"{obj_id}.GetNext", None)
    return table, ann


class TestInsertBomTable:
    def test_xy_mode_positional_tuple_matches_dossier_order(self, tool_sw):
        """Default (x/y placement, top_level, no configuration): the exact
        12-positional-arg tuple InsertBomTable6 must receive, in
        docs/api/04-tables.md's declared order."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1", name="BomTable1", row_count=5, column_count=4)
        view.set_return("v1.InsertBomTable6", table)

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
            "x": 50, "y": 25,
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBomTable6")[0].args
        assert args == (
            False, pytest.approx(0.05), pytest.approx(0.025),
            int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft),
            int(SwBomType.swBomType_TopLevelOnly),
            "", "/tpl/bom-standard.sldbomtbt", False,
            int(SwNumberingType.swNumberingType_None),
            False, False, False,
        )
        assert result["data"]["name"] == "BomTable1"
        assert result["data"]["row_count"] == 5
        assert result["data"]["column_count"] == 4

    def test_anchor_mode_positional_tuple(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1")
        view.set_return("v1.InsertBomTable6", table)

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
            "bom_type": "parts_only", "configuration": "Default",
            "attach_to_anchor": True, "anchor": "bottom_right",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBomTable6")[0].args
        assert args[0] is True  # UseAnchorPoint
        assert args[3] == int(SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_BottomRight)
        assert args[4] == int(SwBomType.swBomType_PartsOnly)
        assert args[5] == "Default"

    def test_indented_bom_type_uses_detailed_numbering(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1")
        view.set_return("v1.InsertBomTable6", table)

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
            "bom_type": "indented", "configuration": "Default", "detailed_cut_list": True,
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBomTable6")[0].args
        assert args[4] == int(SwBomType.swBomType_Indented)
        assert args[8] == int(SwNumberingType.swNumberingType_Detailed)
        assert args[9] is True  # DetailedCutList

    def test_unknown_bom_type_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt", "bom_type": "nonsense",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_configuration_with_top_level_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt",
            "bom_type": "top_level", "configuration": "Default",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_missing_configuration_for_parts_only_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt", "bom_type": "parts_only",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_attach_to_anchor_without_anchor_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt", "attach_to_anchor": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_anchor_without_attach_to_anchor_rejected(self, tool_sw):
        """Anchor mode and x/y mode are mutually exclusive: giving `anchor`
        while `attach_to_anchor` stays False (the x/y default) is rejected
        rather than silently ignored."""
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt", "anchor": "top_left",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_unknown_anchor_value_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_bom_table", {
            "template_path": "/tpl/bom-standard.sldbomtbt",
            "attach_to_anchor": True, "anchor": "middle",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_missing_template_with_no_discoverable_default_errors(self, tool_sw, monkeypatch):
        fake_sw = tool_sw("drawing")
        monkeypatch.setattr("solidworks_mcp.automation.drawings.find_template", lambda t: None)

        result = dispatch("insert_bom_table", {})

        assert result["success"] is False
        assert result["error_name"] == "swTemplateNotFound"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_template_path_omitted_falls_back_to_find_template(self, tool_sw, monkeypatch):
        fake_sw = tool_sw("drawing")
        monkeypatch.setattr(
            "solidworks_mcp.automation.drawings.find_template",
            lambda t: "/discovered/bom-standard.sldbomtbt" if t == "bom" else None,
        )
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1")
        view.set_return("v1.InsertBomTable6", table)

        result = dispatch("insert_bom_table", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBomTable6")[0].args
        assert args[6] == "/discovered/bom-standard.sldbomtbt"

    def test_view_name_omitted_uses_first_view_on_active_sheet(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1")
        view.set_return("v1.InsertBomTable6", table)

        result = dispatch("insert_bom_table", {"template_path": "/tpl/bom-standard.sldbomtbt"})

        assert result["success"] is True, result
        assert result["data"]["view_name"] == "Drawing View1"
        assert fake_sw.call_log.calls_to("InsertBomTable6")

    def test_no_views_on_sheet_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [])

        result = dispatch("insert_bom_table", {"template_path": "/tpl/bom-standard.sldbomtbt"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBomTable6")

    def test_insert_returning_nothing_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        view.set_return("v1.InsertBomTable6", None)

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_hidden_columns_hides_each_index_after_creation(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1")
        view.set_return("v1.InsertBomTable6", table)
        table.set_return("t1.ColumnHidden", True)

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
            "hidden_columns": [0, 2],
        })

        assert result["success"] is True, result
        calls = fake_sw.call_log.calls_to("ColumnHidden")
        assert [c.args for c in calls] == [(0, True), (2, True)]

    def test_failed_column_hide_still_reports_the_created_tables_name(self, tool_sw):
        """`ColumnHidden` runs *after* `InsertBomTable6` already put a table
        on the sheet, and nothing rolls it back. If hiding fails the caller
        still needs `data["name"]` to reach that stray table with
        `delete_table` -- reporting the failure without a name would strand
        it."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])
        table, _ann = _table(fake_sw, "t1", name="BomTable1")
        view.set_return("v1.InsertBomTable6", table)
        table.set_raises("t1.ColumnHidden", RuntimeError("not an indexed property setter"))

        result = dispatch("insert_bom_table", {
            "view_name": "Drawing View1", "template_path": "/tpl/bom-standard.sldbomtbt",
            "hidden_columns": [1],
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["name"] == "BomTable1"
        assert "still on the sheet" in result["message"]


class TestListTables:
    def test_lists_tables_across_every_view_in_document(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        table1, _a1 = _table(
            fake_sw, "t1", name="BomTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_BillOfMaterials,
            row_count=5, column_count=4, position=(0.01, 0.02, 0.0),
        )
        table2, _a2 = _table(
            fake_sw, "t2", name="HoleTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_HoleChart,
            row_count=3, column_count=4, position=(0.03, 0.04, 0.0),
        )
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_table=table1)
        view2 = _view(fake_sw, "v2", "Drawing View1", first_table=table2)
        _chain_views(view1, view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("list_tables", {})

        assert result["success"] is True, result
        by_name = {t["name"]: t for t in result["data"]["tables"]}
        assert set(by_name) == {"BomTable1", "HoleTable1"}
        assert by_name["BomTable1"]["type"] == "swTableAnnotation_BillOfMaterials"
        assert by_name["BomTable1"]["row_count"] == 5
        assert by_name["BomTable1"]["column_count"] == 4
        assert by_name["BomTable1"]["x"] == pytest.approx(10.0)  # meters -> mm default unit
        assert by_name["BomTable1"]["view_name"] == "Sheet1"
        assert by_name["HoleTable1"]["type"] == "swTableAnnotation_HoleChart"
        assert by_name["HoleTable1"]["view_name"] == "Drawing View1"

    def test_sheet_name_scopes_to_that_sheets_tables(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table1, _a1 = _table(fake_sw, "t1", name="Table1")
        table2, _a2 = _table(fake_sw, "t2", name="Table2")
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table1)
        view2 = _view(fake_sw, "v2", "Drawing View2", first_table=table2)
        _chain_views(view1, view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        sheet1 = fake_sw.new_object("sheet1")
        sheet1.set_return("sheet1.GetViews", [view1])
        fake_sw.ActiveDoc.set_return("Sheet", sheet1)

        result = dispatch("list_tables", {"sheet_name": "Sheet1"})

        assert result["success"] is True, result
        names = {t["name"] for t in result["data"]["tables"]}
        assert names == {"Table1"}

    def test_empty_document_is_a_success_with_no_tables(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("list_tables", {})

        assert result["success"] is True, result
        assert result["data"]["tables"] == []


class TestGetBomContents:
    def test_returns_rows_including_header_row(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="BomTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_BillOfMaterials,
            total_row_count=3, column_count=2,
        )
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        # Row-major order: (0,0) (0,1) (1,0) (1,1) (2,0) (2,1) -- row 0 is the
        # header row.
        table.set_sequence("Text2", [
            "ITEM NO.", "PART NUMBER",
            "1", "Bracket-001",
            "2", "Bolt-002",
        ])

        result = dispatch("get_bom_contents", {"table_name": "BomTable1"})

        assert result["success"] is True, result
        assert result["data"]["rows"] == [
            ["ITEM NO.", "PART NUMBER"],
            ["1", "Bracket-001"],
            ["2", "Bolt-002"],
        ]
        assert result["data"]["row_count"] == 3
        assert result["data"]["column_count"] == 2
        call = fake_sw.call_log.calls_to("Text2")[0]
        assert call.args == (0, 0, True)

    def test_hidden_column_still_reported_via_total_column_count(self, tool_sw):
        """`ColumnCount` is visible-only; a column hidden by `insert_bom_table`'s
        `hidden_columns` must still show up, via `TotalColumnCount`
        (visible + hidden) -- bounding the read loop with the plain
        `ColumnCount` would silently truncate it out."""
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="BomTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_BillOfMaterials,
            total_row_count=1, column_count=2, total_column_count=3,
        )
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        table.set_sequence("Text2", ["ITEM NO.", "PART NUMBER", "QTY."])

        result = dispatch("get_bom_contents", {"table_name": "BomTable1"})

        assert result["success"] is True, result
        assert result["data"]["column_count"] == 3
        assert result["data"]["rows"] == [["ITEM NO.", "PART NUMBER", "QTY."]]

    def test_unknown_table_name_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("get_bom_contents", {"table_name": "NoSuchTable"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_non_bom_table_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="HoleTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_HoleChart,
        )
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("get_bom_contents", {"table_name": "HoleTable1"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("Text2")
