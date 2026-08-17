"""
Regression tests for the batch center mark and centerline tools
(solidworks_mcp/tools/drawing_annotations.py's add_center_marks,
add_centerlines, remove_center_marks), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
same convention as test_tools_symbols.py: exercise both the registry wiring
and the `DrawingOperations` automation methods, asserting COM call
names/order/args against the fake's call log.
"""

import pytest

from solidworks_mcp.testing.fake_backend import FakePythonCom
from solidworks_mcp.tools import dispatch, sw_automation


class NullDispatch:
    """Matches the null `VT_DISPATCH` VARIANT `SelectByID2`'s `Callout`
    argument requires -- see test_selection.py's identical helper."""

    def __eq__(self, other) -> bool:
        return (getattr(other, "vt", None) == FakePythonCom.VT_DISPATCH
                and getattr(other, "value", "unset") is None)

    def __repr__(self) -> str:
        return "<null VT_DISPATCH VARIANT>"


def _prep_view(fake_sw):
    """Common setup every happy/near-happy-path test needs: ActivateView and
    SelectByID2 both scripted to succeed."""
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)


def _entity(kind="edge", x=1, y=2, z=0):
    return {"kind": kind, "x": x, "y": y, "z": z}


def _circular_edge(fake_sw, obj_id, is_circle, point=(0.01, 0.02, 0.0)):
    """A fake `IEdge` whose `GetCurve().IsCircle()` answers `is_circle`, and
    whose `GetCurveParams2` supplies `_entity_point`'s representative point
    (meters)."""
    curve = fake_sw.new_object(f"{obj_id}.curve")
    curve.set_return(f"{obj_id}.curve.IsCircle", is_circle)

    edge = fake_sw.new_object(obj_id)
    edge.set_return(f"{obj_id}.GetCurve", curve)
    edge.set_return(f"{obj_id}.GetCurveParams2", [point[0], point[1], point[2], 0, 0, 0, 0])
    return edge


class TestAddCenterMarksAllHoles:
    def test_one_com_call_per_circular_edge(self, tool_sw):
        """5 circular + 2 non-circular edges -> exactly 5 InsertCenterMark3
        calls, one per hole."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        view = fake_sw.ActiveDoc.ActiveDrawingView

        # Distinct points per circular edge, and points well outside that set
        # for the non-circular ones -- so the test can confirm the marks
        # landed on the *hole* edges, not merely that 5 calls happened.
        circular = [
            _circular_edge(fake_sw, f"hole{i}", True, point=(0.001 * (i + 1), 0.002, 0.0))
            for i in range(5)
        ]
        straight = [
            _circular_edge(fake_sw, f"edge{i}", False, point=(0.999, 0.999, 0.0))
            for i in range(2)
        ]
        view.set_return("GetVisibleEntities2", circular + straight)

        result = dispatch("add_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 5
        assert len(fake_sw.call_log.calls_to("InsertCenterMark3")) == 5

        selected_x = {round(c.args[2], 6) for c in fake_sw.call_log.calls_to("SelectByID2")}
        expected_x = {round(0.001 * (i + 1), 6) for i in range(5)}
        assert selected_x == expected_x
        assert round(0.999, 6) not in selected_x

    def test_zero_circular_edges_is_a_success_not_an_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetVisibleEntities2", [])

        result = dispatch("add_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("InsertCenterMark3")

    def test_view_with_only_non_circular_edges_is_zero_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetVisibleEntities2", [_circular_edge(fake_sw, "e1", False)])

        result = dispatch("add_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("InsertCenterMark3")


class TestAddCenterMarksExplicitTarget:
    def test_explicit_entity_list_skips_all_holes_discovery(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", fake_sw.new_object("mark1"))

        result = dispatch("add_center_marks", {
            "view_name": "Drawing View1",
            "target": [_entity("edge", 5, 6), _entity("edge", 7, 8)],
        })

        assert result["success"] is True, result
        assert result["data"]["count"] == 2
        assert len(fake_sw.call_log.calls_to("InsertCenterMark3")) == 2
        assert not fake_sw.call_log.calls_to("GetVisibleEntities2")

    def test_invalid_entity_reference_fails_before_any_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)

        result = dispatch("add_center_marks", {
            "view_name": "Drawing View1",
            "target": [{"kind": "bogus", "x": 1, "y": 2}],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertCenterMark3")

    def test_unknown_string_target_is_invalid_input(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)

        result = dispatch("add_center_marks", {"view_name": "Drawing View1", "target": "everything"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestAddCenterMarksStyleAndParams:
    @pytest.mark.parametrize("style,expected", [
        ("non_annotation", 1),
        ("single", 2),
        ("linear_group", 3),
        ("circular_group", 4),
    ])
    def test_style_maps_to_dossier_enum(self, tool_sw, style, expected):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", fake_sw.new_object("mark1"))

        result = dispatch("add_center_marks", {
            "view_name": "Drawing View1", "target": [_entity()], "style": style,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("InsertCenterMark3", expected, False, True)

    def test_unknown_style_is_invalid_input(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)

        result = dispatch("add_center_marks", {
            "view_name": "Drawing View1", "target": [_entity()], "style": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertCenterMark3")

    def test_propagate_is_always_false(self, tool_sw):
        """`InsertCenterMark3`'s `Propagate` (2nd positional arg) is always
        bound False -- each hole is marked individually by this batch walk."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", fake_sw.new_object("mark1"))

        dispatch("add_center_marks", {"view_name": "Drawing View1", "target": [_entity()]})

        call = fake_sw.call_log.calls_to("InsertCenterMark3")[0]
        assert call.args[1] is False

    def test_slot_center_marks_passed_as_third_positional_arg(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", fake_sw.new_object("mark1"))

        dispatch("add_center_marks", {
            "view_name": "Drawing View1", "target": [_entity()], "slot_center_marks": False,
        })

        call = fake_sw.call_log.calls_to("InsertCenterMark3")[0]
        assert call.args == (2, False, False)

    def test_size_extended_lines_connection_lines_applied_to_created_mark(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "inch"
        _prep_view(fake_sw)
        mark = fake_sw.new_object("mark1")
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", mark)

        result = dispatch("add_center_marks", {
            "view_name": "Drawing View1", "target": [_entity()],
            "size": 1.0, "extended_lines": False, "connection_lines": True,
        })

        assert result["success"] is True, result
        # 1 inch -> 0.0254 m, per self._units.to_meters (not a hardcoded mm factor).
        assert mark.Size == pytest.approx(0.0254)
        assert mark.ShowLines is False
        assert mark.ConnectionLines == 2  # swCenterMark_ShowCircularConnectLines

    def test_connection_lines_default_false_maps_to_no_connect_lines(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        mark = fake_sw.new_object("mark1")
        fake_sw.ActiveDoc.set_return("InsertCenterMark3", mark)

        result = dispatch("add_center_marks", {"view_name": "Drawing View1", "target": [_entity()]})

        assert result["success"] is True, result
        assert mark.ConnectionLines == 0  # swCenterMark_ShowNoConnectLines
        assert mark.ShowLines is True  # extended_lines default True


class TestAddCenterlines:
    def test_select_view_true_selects_view_before_insert(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterLine2", fake_sw.new_object("cl1"))

        result = dispatch("add_centerlines", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 1
        fake_sw.call_log.assert_called_with(
            "SelectByID2", "Drawing View1", "DRAWINGVIEW", 0.0, 0.0, 0.0,
            False, 0, NullDispatch(), 0,
        )
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("InsertCenterLine2")

    def test_select_view_true_requires_target_all(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)

        result = dispatch("add_centerlines", {
            "view_name": "Drawing View1", "target": [_entity(), _entity()], "select_view": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertCenterLine2")

    def test_select_view_false_selects_both_entities_then_inserts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterLine2", fake_sw.new_object("cl1"))

        result = dispatch("add_centerlines", {
            "view_name": "Drawing View1",
            "target": [_entity("edge", 1, 2), _entity("edge", 3, 4)],
            "select_view": False,
        })

        assert result["success"] is True, result
        selects = fake_sw.call_log.calls_to("SelectByID2")
        assert len(selects) == 2
        assert selects[0].args[5] is False  # append=False for the first entity
        assert selects[1].args[5] is True   # append=True for the second
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("InsertCenterLine2")

    def test_select_view_false_requires_exactly_two_entities(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)

        result = dispatch("add_centerlines", {
            "view_name": "Drawing View1", "target": [_entity()], "select_view": False,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertCenterLine2")

    def test_no_centerline_created_is_a_warned_success_with_zero_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertCenterLine2", None)

        result = dispatch("add_centerlines", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0


class TestRemoveCenterMarks:
    def _chain(self, fake_sw, view, ids):
        """Wire `view.GetFirstCenterMark2` / `ICenterMark::GetNext` to walk
        `ids` in order, then `None`. Each mark's `Select` defaults to
        succeeding (`True`); a test overrides `marks[i].set_return(f"{id}.Select",
        False)` to force one to fail."""
        marks = [fake_sw.new_object(i) for i in ids]
        for mark, obj_id in zip(marks, ids):
            mark.set_return(f"{obj_id}.Select", True)
        for i, obj_id in enumerate(ids):
            nxt = marks[i + 1] if i + 1 < len(marks) else None
            marks[i].set_return(f"{obj_id}.GetNext", nxt)
        if marks:
            view.set_return("GetFirstCenterMark2", marks[0])
        else:
            view.set_return("GetFirstCenterMark2", None)
        return marks

    def test_removes_every_mark_in_the_walk(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        self._chain(fake_sw, view, ["mark1", "mark2", "mark3"])
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("remove_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 3
        assert result["data"]["removed"] == 3
        assert len(fake_sw.call_log.calls_to("DeleteSelection2")) == 3

    def test_no_center_marks_is_a_success_with_zero_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetFirstCenterMark2", None)

        result = dispatch("remove_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("DeleteSelection2")

    def test_selection_failures_are_skipped_but_do_not_fail_the_batch(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        marks = self._chain(fake_sw, view, ["mark1", "mark2"])
        marks[0].set_return("mark1.Select", False)  # this one can't be selected
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("remove_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 1
        assert len(fake_sw.call_log.calls_to("DeleteSelection2")) == 1

    def test_all_selection_failures_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        marks = self._chain(fake_sw, view, ["mark1"])
        marks[0].set_return("mark1.Select", False)

        result = dispatch("remove_center_marks", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["count"] == 0
