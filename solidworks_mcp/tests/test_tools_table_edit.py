"""
Regression tests for the generic table update/read/edit tools
(solidworks_mcp/tools/drawing_tables.py's update_table, get_table_contents,
set_table_cell, set_table_position, set_table_anchor, delete_table),
dispatched through the real `solidworks_mcp.tools` registry (`dispatch()`)
against the fake COM harness -- same convention as test_tools_bom.py/
test_tools_tables_misc.py: exercise both the registry wiring and the
`DrawingOperations` automation methods, asserting COM call names/order/args
against the fake's call log.
"""

import pytest

from solidworks_mcp.constants_drawing import (
    SwAnnotationVisibilityState,
    SwDrawingViewTypes,
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


def _table(fake_sw, obj_id, name="Table1", type_code=SwTableAnnotationType.swTableAnnotation_General,
           row_count=None, total_row_count=None, column_count=None, total_column_count=None,
           position=(0.0, 0.0, 0.0), visible=None, anchored=None):
    """A fake `ITableAnnotation` -> `GetAnnotation` -> `IAnnotation` chain,
    with `GetNext` pre-terminated at `None` -- same shape as
    test_tools_bom.py's `_table`, generalized with optional `visible`
    (`IAnnotation::Visible`, an `swAnnotationVisibilityState_e` int) and
    `anchored` (`ITableAnnotation::Anchored`, a bool) presets."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    if position is not None:
        ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    if visible is not None:
        ann.set_return(f"{obj_id}.ann.Visible", int(visible))

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
    if anchored is not None:
        table.set_return(f"{obj_id}.Anchored", anchored)
    table.set_return(f"{obj_id}.GetNext", None)
    return table, ann


def _chain_tables(*tables):
    for (table, _ann), (nxt, _nxt_ann) in zip(tables, tables[1:]):
        table.set_return(f"{table._path}.GetNext", nxt)


class TestUpdateTable:
    def test_neither_table_name_nor_all_tables_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("update_table", {})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ForceRebuild3")

    def test_both_table_name_and_all_tables_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("update_table", {"table_name": "Table1", "all_tables": True})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ForceRebuild3")

    def test_unknown_table_name_errors_before_rebuild(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("update_table", {"table_name": "NoSuchTable"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ForceRebuild3")

    def test_single_table_calls_force_rebuild_and_reports_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="BomTable1", row_count=5, column_count=4)
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        result = dispatch("update_table", {"table_name": "BomTable1"})

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("ForceRebuild3")[0].args == (False,)
        assert result["data"]["count"] == 1
        # `refreshed` is False here: `Visible` was never scripted, so the
        # read-back is unreadable and the toggle is correctly skipped rather
        # than assumed -- see test_visible_table_is_toggled_hidden_then_visible
        # for the case where it actually runs.
        assert result["data"]["tables"] == [
            {"name": "BomTable1", "view_name": "Drawing View1", "row_count": 5,
             "column_count": 4, "refreshed": False},
        ]
        assert result["data"]["refreshed_count"] == 0

    def test_all_tables_updates_every_table_on_active_sheet_and_reports_each(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table1, _a1 = _table(fake_sw, "t1", name="Table1", row_count=2, column_count=3)
        table2, _a2 = _table(fake_sw, "t2", name="Table2", row_count=4, column_count=1)
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table1)
        view2 = _view(fake_sw, "v2", "Drawing View2", first_table=table2)
        _chain_views(view1, view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        # `_scoped_views(doc, "Sheet1", ...)` resolves the sheet a second,
        # independent way (`ISheet::Sheet` by name) from `GetCurrentSheet`
        # (already pre-scripted by `FakeSldWorks("drawing")` to the default
        # "Sheet1") -- same two-call scripting `list_tables`' own
        # sheet_name test requires.
        sheet1 = fake_sw.new_object("sheet1")
        sheet1.set_return("sheet1.GetViews", [view1, view2])
        fake_sw.ActiveDoc.set_return("Sheet", sheet1)

        result = dispatch("update_table", {"all_tables": True})

        assert result["success"] is True, result
        assert len(fake_sw.call_log.calls_to("ForceRebuild3")) == 1
        assert result["data"]["count"] == 2
        names = {t["name"] for t in result["data"]["tables"]}
        assert names == {"Table1", "Table2"}

    def test_all_tables_scoping_excludes_other_sheets_tables(self, tool_sw):
        """`GetViews` returning only `view1` (view2's sheet is different)
        must exclude `Table2` even though the document-wide `GetFirstView`/
        `GetNextView` walk `_iter_document_views` uses would otherwise
        reach it -- proves `all_tables=True` is actually sheet-scoped, not
        a document-wide walk in disguise."""
        fake_sw = tool_sw("drawing")
        table1, _a1 = _table(fake_sw, "t1", name="Table1", row_count=2, column_count=3)
        table2, _a2 = _table(fake_sw, "t2", name="Table2", row_count=4, column_count=1)
        view1 = _view(fake_sw, "v1", "Drawing View1", first_table=table1)
        view2 = _view(fake_sw, "v2", "Drawing View2", first_table=table2)
        _chain_views(view1, view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        sheet1 = fake_sw.new_object("sheet1")
        sheet1.set_return("sheet1.GetViews", [view1])  # view2 excluded
        fake_sw.ActiveDoc.set_return("Sheet", sheet1)

        result = dispatch("update_table", {"all_tables": True})

        assert result["success"] is True, result
        assert result["data"]["count"] == 1
        assert result["data"]["tables"][0]["name"] == "Table1"

    def test_all_tables_with_no_tables_is_a_warned_success_and_skips_rebuild(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Drawing View1")
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        sheet1 = fake_sw.new_object("sheet1")
        sheet1.set_return("sheet1.GetViews", [view])
        fake_sw.ActiveDoc.set_return("Sheet", sheet1)

        result = dispatch("update_table", {"all_tables": True})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("ForceRebuild3")

    def test_visible_table_is_toggled_hidden_then_visible(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, ann = _table(
            fake_sw, "t1", name="Table1", row_count=1, column_count=1,
            visible=SwAnnotationVisibilityState.swAnnotationVisible,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        result = dispatch("update_table", {"table_name": "Table1"})

        assert result["success"] is True, result
        # A real assignment happened (raw int stored directly on the fake),
        # not just a scripted-return comparison -- see the module docstring
        # in drawings.py's update_table for why this is the only way the
        # fake harness can distinguish "toggled back to visible" from
        # "never touched" when both end at the same value.
        assert isinstance(ann.Visible, int)
        assert ann.Visible == int(SwAnnotationVisibilityState.swAnnotationVisible)
        assert result["data"]["tables"][0]["refreshed"] is True
        assert result["data"]["refreshed_count"] == 1

    def test_already_hidden_table_is_left_alone(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, ann = _table(
            fake_sw, "t1", name="Table1", row_count=1, column_count=1,
            visible=SwAnnotationVisibilityState.swAnnotationHidden,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        result = dispatch("update_table", {"table_name": "Table1"})

        assert result["success"] is True, result
        # No assignment happened -- `Visible` was never written into
        # `ann`'s children, so it still resolves through the scripted
        # return rather than a raw stored int.
        assert ann.Visible == int(SwAnnotationVisibilityState.swAnnotationHidden)
        assert result["data"]["tables"][0]["refreshed"] is False
        assert result["data"]["refreshed_count"] == 0


class TestGetTableContents:
    def test_returns_rectangular_grid_matching_row_column_counts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="GeneralTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_General,
            total_row_count=2, column_count=3,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_sequence("Text2", ["A", "B", "C", "1", "2", "3"])

        result = dispatch("get_table_contents", {"table_name": "GeneralTable1"})

        assert result["success"] is True, result
        assert result["data"]["row_count"] == 2
        assert result["data"]["column_count"] == 3
        rows = result["data"]["rows"]
        assert len(rows) == 2
        assert all(len(row) == 3 for row in rows)
        assert rows == [["A", "B", "C"], ["1", "2", "3"]]
        assert result["data"]["type"] == "swTableAnnotation_General"

    def test_works_for_non_bom_table_types(self, tool_sw):
        """Unlike get_bom_contents, get_table_contents has no Type restriction."""
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="HoleTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_HoleChart,
            total_row_count=1, column_count=1,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_sequence("Text2", ["HOLE TABLE"])

        result = dispatch("get_table_contents", {"table_name": "HoleTable1"})

        assert result["success"] is True, result
        assert result["data"]["type"] == "swTableAnnotation_HoleChart"

    def test_unknown_table_name_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("get_table_contents", {"table_name": "NoSuchTable"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestSetTableCell:
    def test_writes_and_verifies_via_read_back(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=2, column_count=2,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_return("IsCellTextEditable", True)
        table.set_return("Text", True)
        table.set_return("Text2", "Bracket-002")

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 1, "column": 0, "text": "Bracket-002",
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("Text")[0].args == (1, 0, "Bracket-002")
        assert result["data"]["verified"] is True

    def test_read_back_raising_is_an_unverified_success_not_a_failure(self, tool_sw):
        """A `Text2` read-back that raises is not evidence the write itself
        failed -- only a read-back that succeeds and disagrees is (see
        test_write_mismatch_on_read_back_is_a_feature_error_not_false_success).
        Conflating the two would report swFeatureError on every successful
        write against an interop layer where Text2 is flaky/unavailable."""
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=1, column_count=1,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_return("IsCellTextEditable", True)
        table.set_return("Text", True)
        table.set_raises("Text2", RuntimeError("interop layer does not support Text2"))

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 0, "column": 0, "text": "New Value",
        })

        assert result["success"] is True, result
        assert result["data"]["verified"] is False
        assert fake_sw.call_log.calls_to("Text")

    def test_index_base_is_0_based_with_no_conversion(self, tool_sw):
        """Requirement: row/column are documented 0-based and are not
        shifted at the public/COM boundary -- pin row=0, column=0 reaching
        Text/IsCellTextEditable as literal 0, 0."""
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=1, column_count=1,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_return("IsCellTextEditable", True)
        table.set_return("Text", True)
        table.set_return("Text2", "ITEM NO.")

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 0, "column": 0, "text": "ITEM NO.",
        })

        assert result["success"] is True, result
        editable_call = fake_sw.call_log.calls_to("IsCellTextEditable")[0]
        assert editable_call.args == (0, 0)
        text_call = fake_sw.call_log.calls_to("Text")[0]
        assert text_call.args == (0, 0, "ITEM NO.")

    def test_read_only_cell_is_refused_without_writing(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="HoleTable1",
            type_code=SwTableAnnotationType.swTableAnnotation_HoleChart,
            total_row_count=2, column_count=2,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_return("IsCellTextEditable", False)

        result = dispatch("set_table_cell", {
            "table_name": "HoleTable1", "row": 0, "column": 0, "text": "X",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("Text")

    def test_out_of_range_row_is_rejected_before_any_write(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=2, column_count=2,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 2, "column": 0, "text": "X",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("IsCellTextEditable")
        assert not fake_sw.call_log.calls_to("Text")

    def test_out_of_range_column_is_rejected_before_any_write(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=2, column_count=2,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 0, "column": 5, "text": "X",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("Text")

    def test_write_mismatch_on_read_back_is_a_feature_error_not_false_success(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(
            fake_sw, "t1", name="Table1", total_row_count=1, column_count=1,
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        table.set_return("IsCellTextEditable", True)
        table.set_return("Text", True)
        table.set_return("Text2", "SOMETHING ELSE")

        result = dispatch("set_table_cell", {
            "table_name": "Table1", "row": 0, "column": 0, "text": "New Value",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert fake_sw.call_log.calls_to("Text")

    def test_unknown_table_name_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_cell", {
            "table_name": "NoSuchTable", "row": 0, "column": 0, "text": "X",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestSetTablePosition:
    def test_sets_position_via_base_annotation_set_position(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        table, ann = _table(fake_sw, "t1", name="Table1", anchored=False)
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        ann.set_return("t1.ann.SetPosition", True)

        result = dispatch("set_table_position", {"table_name": "Table1", "x": 50, "y": 25})

        assert result["success"] is True, result
        call = fake_sw.call_log.calls_to("SetPosition")[0]
        assert call.args == (pytest.approx(0.05), pytest.approx(0.025), pytest.approx(0.0))

    def test_anchored_table_is_rejected_without_calling_set_position(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="Table1", anchored=True)
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_position", {"table_name": "Table1", "x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetPosition")

    def test_set_position_returning_false_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, ann = _table(fake_sw, "t1", name="Table1", anchored=False)
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        ann.set_return("t1.ann.SetPosition", False)

        result = dispatch("set_table_position", {"table_name": "Table1", "x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_non_numeric_xy_is_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_table_position", {"table_name": "Table1", "x": "far", "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestSetTableAnchor:
    def test_anchors_and_reads_back(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="Table1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_anchor", {"table_name": "Table1", "anchored": True})

        assert result["success"] is True, result
        assert table.Anchored is True
        assert result["data"]["anchored"] is True

    def test_releases_anchor_with_anchored_false(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="Table1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_anchor", {"table_name": "Table1", "anchored": False})

        assert result["success"] is True, result
        assert table.Anchored is False
        assert result["data"]["anchored"] is False

    def test_unknown_table_name_is_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("set_table_anchor", {"table_name": "NoSuchTable", "anchored": True})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_non_boolean_anchored_is_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_table_anchor", {"table_name": "Table1", "anchored": "yes"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestDeleteTable:
    def test_selects_by_annotation_tables_type_and_deletes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="Table1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_table", {"table_name": "Table1"})

        assert result["success"] is True, result
        select_call = fake_sw.call_log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Table1"
        assert select_call.args[1] == "ANNOTATIONTABLES"
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_unknown_table_name_is_rejected_before_any_select(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("delete_table", {"table_name": "NoSuchTable"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_delete_selection_returning_false_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        table, _ann = _table(fake_sw, "t1", name="Table1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=table)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", False)

        result = dispatch("delete_table", {"table_name": "Table1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
