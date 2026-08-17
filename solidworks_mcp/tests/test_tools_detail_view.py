"""
Regression tests for the detail view and broken-out section tools
(solidworks_mcp/tools/drawing_views.py's insert_detail_view and
insert_broken_out_section), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness
-- so these exercise both the registry wiring and the
`DrawingOperations.insert_detail_view`/`insert_broken_out_section`
automation methods they call, asserting COM call order/args against the
fake's call log the same way test_tools_section_view.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_section_view.py's `tool_sw`, connecting
    the shared `tools.sw_automation` singleton (what `dispatch()` actually
    calls through) to a fresh fake `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _view(fake_sw, obj_id, name, type_code=None, scale=None):
    """Build a fake `IView`-shaped object with `GetName2`/`Type`/`ScaleDecimal`
    scripted under path-scoped keys, per test_tools_section_view.py's `_view`
    convention (multiple view objects in one test can't share a bare-name
    key for the same method with different values)."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    if scale is not None:
        view.set_return(f"{obj_id}.ScaleDecimal", scale)
    return view


def _seed_parent_and_selection(fake_sw, parent_name="Drawing View1", scale=None):
    """Common setup every happy/near-happy-path test needs: a resolvable
    parent view on the active sheet, plus `ActivateView`/`SelectByID2`
    scripted to succeed."""
    sheet = fake_sw.ActiveDoc.GetCurrentSheet()
    parent = _view(fake_sw, "parent_view", parent_name, scale=scale)
    sheet.set_return("GetViews", [parent])
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
    return parent


def _seed_created_detail_view(fake_sw, obj_id="detail_view", name="Drawing View2"):
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    fake_sw.ActiveDoc.set_return("CreateDetailViewAt4", view)
    return view


class TestInsertDetailViewHappyPath:
    def test_end_to_end_com_sequence_and_meter_conversion(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _seed_parent_and_selection(fake_sw)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 10, "center_y": 20, "radius": 5,
            "x": 50, "y": 25, "label": "A",
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        names = log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("CreateCircleByRadius")
            < names.index("SelectByID2") < names.index("CreateDetailViewAt4")
        ), names

        log.assert_called_with("ActivateView", "Drawing View1")
        log.assert_called_with(
            "CreateCircleByRadius",
            pytest.approx(0.010), pytest.approx(0.020), 0.0, pytest.approx(0.005),
        )

        # Selected at a point on the circle's *boundary* (center + radius),
        # not the center -- docs/api/02-views.md's CreateCircleByRadius Gotchas.
        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == ""
        assert select_call.args[1] == "SKETCHSEGMENT"
        assert select_call.args[2] == pytest.approx(0.015)
        assert select_call.args[3] == pytest.approx(0.020)

        create_call = log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[0] == pytest.approx(0.05)   # x
        assert create_call.args[1] == pytest.approx(0.025)  # y
        assert create_call.args[2] == pytest.approx(0.0)    # z
        assert create_call.args[3] == 0                     # swDetViewSTANDARD
        assert create_call.args[6] == "A"                   # label
        assert create_call.args[7] == 1                      # swDetCircleCIRCLE

    def test_returns_view_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_detail_view(fake_sw, name="Drawing View7")

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View7"

    def test_full_outline_passed_through(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "full_outline": True,
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[8] is True    # FullOutline
        assert create_call.args[9] is False   # JaggedOutline
        assert create_call.args[10] is False  # NoOutline

    def test_style_profile_maps_to_showtype_profile(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "style": "profile",
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[7] == 0  # swDetCirclePROFILE

    def test_style_none_maps_to_showtype_dontshow(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "style": "none",
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[7] == 2  # swDetCircleDONTSHOW

    def test_unknown_style_rejects_without_com_call(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "style": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "bogus" in result["message"]

    def test_explicit_scale_used_over_parent_scale(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw, scale=2.0)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "scale_num": 4, "scale_denom": 1,
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[4] == 4
        assert create_call.args[5] == 1

    def test_omitted_scale_defaults_to_parent_view_scale(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw, scale=2.5)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[4] == 2.5
        assert create_call.args[5] == 1.0

    def test_omitted_scale_falls_back_to_1_1_when_parent_scale_unreadable(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw, scale=None)
        _seed_created_detail_view(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateDetailViewAt4")[0]
        assert create_call.args[4] == 1.0
        assert create_call.args[5] == 1.0

    def test_half_specified_scale_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0, "scale_num": 2,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateDetailViewAt4")


class TestInsertDetailViewValidation:
    def test_non_positive_radius_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 0,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateCircleByRadius")
        assert not log.calls_to("CreateDetailViewAt4")

    def test_negative_radius_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": -5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_unknown_parent_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Bogus View",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("CreateDetailViewAt4")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert "Part" in result["message"]


class TestInsertDetailViewCleanup:
    def test_activate_view_failure_fails_without_sketching(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("CreateCircleByRadius")

    def test_selection_failure_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("CreateDetailViewAt4")
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_create_call_raising_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        fake_sw.ActiveDoc.set_raises("CreateDetailViewAt4", RuntimeError("boom"))

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_none_return_from_com_triggers_cleanup_and_names_parent_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        fake_sw.ActiveDoc.set_return("CreateDetailViewAt4", None)

        result = dispatch("insert_detail_view", {
            "parent_view_name": "Drawing View1",
            "center_x": 0, "center_y": 0, "radius": 5,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]
        assert fake_sw.call_log.calls_to("DeleteSelection2")


# ============================================================================
# insert_broken_out_section
# ============================================================================

def _seed_broken_out_success(fake_sw):
    fake_sw.ActiveDoc.set_return("CreateBreakOutSection", True)


class TestInsertBrokenOutSectionHappyPath:
    def test_end_to_end_com_sequence_and_meter_conversion(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _seed_parent_and_selection(fake_sw)
        _seed_broken_out_success(fake_sw)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        names = log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("CreateLine")
            < names.index("SelectByID2") < names.index("CreateBreakOutSection")
        ), names

        # 3 points -> auto-closed loop of 4 vertices -> 3 segments.
        assert len(log.calls_to("CreateLine")) == 3
        assert len(log.calls_to("SelectByID2")) == 3

        # Auto-close: the last segment connects the last point back to the first.
        closing_call = log.calls_to("CreateLine")[2]
        assert closing_call.args[0] == pytest.approx(0.010)  # x1 (10mm)
        assert closing_call.args[1] == pytest.approx(0.010)  # y1
        assert closing_call.args[3] == pytest.approx(0.0)    # x2 (back to first point)
        assert closing_call.args[4] == pytest.approx(0.0)    # y2

        depth_call = log.calls_to("CreateBreakOutSection")[0]
        assert depth_call.args[0] == pytest.approx(0.005)  # 5mm -> meters

    def test_returns_parent_view_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw, parent_name="Drawing View9")
        _seed_broken_out_success(fake_sw)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View9",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View9"

    def test_pre_closed_profile_drops_duplicate_and_still_creates_3_segments(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_broken_out_success(fake_sw)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10], [0, 0]],
            "depth": 5,
        })

        assert result["success"] is True
        assert len(fake_sw.call_log.calls_to("CreateLine")) == 3

    def test_preview_sketches_and_deletes_without_creating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_broken_out_success(fake_sw)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5, "preview": True,
        })

        assert result["success"] is True
        assert result["data"]["preview"] is True
        log = fake_sw.call_log
        assert len(log.calls_to("CreateLine")) == 3
        assert not log.calls_to("CreateBreakOutSection")
        assert log.calls_to("DeleteSelection2")

    def test_depth_reference_chain_is_invoked(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_broken_out_success(fake_sw)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth_reference": {"x": 5, "y": 5, "type": "FACE"},
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.calls_to("CreateBreakOutSection")
        assert log.calls_to("GetSelectedObject6")
        assert log.calls_to("FeatureByPositionReverse")
        assert log.calls_to("GetDefinition")
        assert log.calls_to("ModifyDefinition")
        assert result["data"]["depth_reference_applied"] is True

        # depth omitted -> CreateBreakOutSection gets the 0.0 placeholder,
        # since the real depth is driven by DepthReference afterward.
        depth_call = log.calls_to("CreateBreakOutSection")[0]
        assert depth_call.args[0] == pytest.approx(0.0)


class TestInsertBrokenOutSectionValidation:
    def test_fewer_than_3_points_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateLine")
        assert not log.calls_to("CreateBreakOutSection")

    def test_fewer_than_3_distinct_points_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [0, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_both_depth_and_depth_reference_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5, "depth_reference": {"x": 1, "y": 1},
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_neither_depth_nor_depth_reference_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_unknown_parent_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Bogus View",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("CreateBreakOutSection")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert "Part" in result["message"]


class TestInsertBrokenOutSectionCleanup:
    def test_selection_failure_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("CreateBreakOutSection")
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_create_call_raising_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        fake_sw.ActiveDoc.set_raises("CreateBreakOutSection", RuntimeError("boom"))

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_false_return_from_com_triggers_cleanup_and_names_parent_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        fake_sw.ActiveDoc.set_return("CreateBreakOutSection", False)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_activate_view_failure_fails_without_sketching(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("insert_broken_out_section", {
            "parent_view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
            "depth": 5,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("CreateLine")
