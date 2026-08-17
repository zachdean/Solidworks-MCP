"""
Regression tests for the break and crop view tools
(solidworks_mcp/tools/drawing_views.py's insert_break_view,
remove_break_view, add_crop_view, remove_crop_view), dispatched through the
real `solidworks_mcp.tools` registry (`dispatch()`) against the fake COM
harness -- so these exercise both the registry wiring and the
`DrawingOperations` automation methods they call, asserting COM call
order/args against the fake's call log the same way
test_tools_detail_view.py does for insert_detail_view/
insert_broken_out_section.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_detail_view.py's `tool_sw`, connecting
    the shared `tools.sw_automation` singleton (what `dispatch()` actually
    calls through) to a fresh fake `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _view(fake_sw, obj_id, name, type_code=None):
    """Build a fake `IView`-shaped object with `GetName2`/`Type` scripted
    under path-scoped keys, per test_tools_detail_view.py's `_view`
    convention."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    return view


def _seed_view_and_selection(fake_sw, view_name="Drawing View1"):
    """Common setup every happy/near-happy-path test needs: a resolvable
    view on the active sheet, plus `ActivateView`/`SelectByID2` scripted to
    succeed."""
    sheet = fake_sw.ActiveDoc.GetCurrentSheet()
    view = _view(fake_sw, "target_view", view_name)
    sheet.set_return("GetViews", [view])
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
    return view


# ============================================================================
# insert_break_view
# ============================================================================

class TestInsertBreakViewHappyPath:
    def test_end_to_end_com_sequence_and_meter_conversion(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", True)
        view.set_return("target_view.GetBreakLineCount2", 1)
        # Not broken before the call, broken after -- `insert_break_view`
        # checks `IsBroken` as a precondition and again to confirm
        # `BreakView` (a void Sub) actually applied the break.
        view.set_sequence("target_view.IsBroken", [False, True])

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1",
            "position1": 10, "position2": 50,
            "orientation": "horizontal", "gap": 2, "style": "jagged",
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        names = log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("InsertBreak3")
            < names.index("BreakView")
        ), names

        log.assert_called_with("ActivateView", "Drawing View1")

        insert_call = log.calls_to("InsertBreak3")[0]
        assert insert_call.args[0] == 1  # swBreakLineHorizontal
        assert insert_call.args[1] == pytest.approx(0.010)  # position1, 10mm
        assert insert_call.args[2] == pytest.approx(0.050)  # position2, 50mm
        assert insert_call.args[3] == 5  # swBreakLine_Jagged
        assert insert_call.args[4] == 1  # ShapeIntensity
        assert insert_call.args[5] is False  # BreakSketchBlocks

        assert view.BreakLineGap == pytest.approx(0.002)  # 2mm -> meters

        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

        assert result["data"]["break_count"] == 1

    def test_default_orientation_and_style(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", True)
        view.set_sequence("target_view.IsBroken", [False, True])

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is True, result
        insert_call = fake_sw.call_log.calls_to("InsertBreak3")[0]
        assert insert_call.args[0] == 2  # swBreakLineVertical (default)
        assert insert_call.args[3] == 2  # swBreakLine_ZigZag (default)

    def test_gap_omitted_does_not_set_breaklinegap(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", True)
        view.set_sequence("target_view.IsBroken", [False, True])

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is True, result
        # Never set -> bare attribute access hands back the dual-purpose
        # auto-vivified wrapper, not a real float.
        assert not isinstance(view.BreakLineGap, float)


class TestInsertBreakViewValidation:
    def test_unknown_orientation_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
            "orientation": "diagonal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "diagonal" in result["message"]
        assert not fake_sw.call_log.calls_to("ActivateView")
        assert not fake_sw.call_log.calls_to("InsertBreak3")

    def test_unknown_style_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
            "style": "wavy",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "wavy" in result["message"]
        assert not fake_sw.call_log.calls_to("ActivateView")
        assert not fake_sw.call_log.calls_to("InsertBreak3")

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_break_view", {
            "view_name": "Bogus View", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("InsertBreak3")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert "Part" in result["message"]


class TestInsertBreakViewFailurePaths:
    def test_already_broken_view_rejected_without_com_write(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsBroken", True)

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "already broken" in result["message"]
        assert not fake_sw.call_log.calls_to("ActivateView")
        assert not fake_sw.call_log.calls_to("InsertBreak3")

    def test_breakview_silent_noop_reported(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", True)
        # Still not broken after BreakView -- its documented failure mode.
        view.set_return("target_view.IsBroken", False)

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "did not apply the break" in result["message"]
        assert fake_sw.call_log.calls_to("BreakView")

    def test_activate_view_failure_fails_before_insert_break3(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "target_view", "Drawing View1")
        view.set_return("target_view.IsBroken", False)
        sheet.set_return("GetViews", [view])
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("InsertBreak3")

    def test_insert_break3_none_return_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", None)
        view.set_return("target_view.IsBroken", False)

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("BreakView")

    def test_selection_failure_fails_before_breakview(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.InsertBreak3", True)
        view.set_return("target_view.IsBroken", False)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_break_view", {
            "view_name": "Drawing View1", "position1": 0, "position2": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert "Inserted break lines" in result["message"]
        assert not fake_sw.call_log.calls_to("BreakView")


# ============================================================================
# remove_break_view
# ============================================================================

class TestRemoveBreakView:
    def test_happy_path_calls_unbreakview_and_verifies_not_broken(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsBroken", False)

        result = dispatch("remove_break_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.calls_to("UnBreakView")
        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

    def test_still_broken_after_unbreakview_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsBroken", True)

        result = dispatch("remove_break_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert fake_sw.call_log.calls_to("UnBreakView")

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("remove_break_view", {"view_name": "Bogus View"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert not fake_sw.call_log.calls_to("UnBreakView")

    def test_selection_failure_triggers_no_unbreakview_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "target_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("remove_break_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("UnBreakView")


# ============================================================================
# add_crop_view
# ============================================================================

def _seed_uncropped_view_and_selection(fake_sw, view_name="Drawing View1"):
    view = _seed_view_and_selection(fake_sw, view_name)
    view.set_return("target_view.IsCropped", False)
    return view


class TestAddCropViewHappyPath:
    def test_end_to_end_com_sequence_and_meter_conversion(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        view = _seed_uncropped_view_and_selection(fake_sw)
        view.set_return("target_view.Crop2", 1)  # swCropViewErrors_NoError

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        names = log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("CreateLine")
            < names.index("SelectByID2") < names.index("Crop2")
        ), names

        # 3 points -> auto-closed loop of 4 vertices -> 3 segments.
        assert len(log.calls_to("CreateLine")) == 3
        assert len(log.calls_to("SelectByID2")) == 3

        closing_call = log.calls_to("CreateLine")[2]
        assert closing_call.args[0] == pytest.approx(0.010)  # x1 (10mm)
        assert closing_call.args[1] == pytest.approx(0.010)  # y1
        assert closing_call.args[3] == pytest.approx(0.0)    # x2 (back to first point)
        assert closing_call.args[4] == pytest.approx(0.0)    # y2

        crop_call = log.calls_to("Crop2")[0]
        assert crop_call.args == (False, False, 1)

        assert result["data"]["view_name"] == "Drawing View1"
        assert result["data"]["crop_status"] == 1

    def test_pre_closed_profile_drops_duplicate_and_still_creates_3_segments(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_uncropped_view_and_selection(fake_sw)
        view.set_return("target_view.Crop2", 1)

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10], [0, 0]],
        })

        assert result["success"] is True, result
        assert len(fake_sw.call_log.calls_to("CreateLine")) == 3


class TestAddCropViewValidation:
    def test_fewer_than_3_points_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1", "profile_points": [[0, 0], [10, 0]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateLine")
        assert not log.calls_to("Crop2")

    def test_already_cropped_rejects_without_sketching(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsCropped", True)

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "already cropped" in result["message"]
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateLine")

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("add_crop_view", {
            "view_name": "Bogus View",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("Crop2")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert "Part" in result["message"]


class TestAddCropViewCleanup:
    def test_crop2_non_success_status_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_uncropped_view_and_selection(fake_sw)
        view.set_return("target_view.Crop2", 4)  # swCropViewErrors_IncorrectProfile

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "IncorrectProfile" in result["message"]
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_selection_failure_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_uncropped_view_and_selection(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("Crop2")
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_crop2_raising_triggers_cleanup(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_uncropped_view_and_selection(fake_sw)
        view.set_raises("target_view.Crop2", RuntimeError("boom"))

        result = dispatch("add_crop_view", {
            "view_name": "Drawing View1",
            "profile_points": [[0, 0], [10, 0], [10, 10]],
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert fake_sw.call_log.calls_to("DeleteSelection2")


# ============================================================================
# remove_crop_view
# ============================================================================

class TestRemoveCropView:
    def test_happy_path_calls_runcommand_and_verifies_not_cropped(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_sequence("target_view.IsCropped", [True, False])
        fake_sw.set_return("RunCommand", True)

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        log = fake_sw.call_log
        run_call = log.calls_to("RunCommand")[0]
        assert run_call.args[0] == 1389  # swCommands_Tools_Crop_Delete
        assert run_call.args[1] == ""

        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

    def test_not_cropped_rejects_without_runcommand_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsCropped", False)

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "not cropped" in result["message"]
        assert not fake_sw.call_log.calls_to("RunCommand")

    def test_runcommand_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsCropped", True)
        fake_sw.set_return("RunCommand", False)

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_still_cropped_after_runcommand_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsCropped", True)
        fake_sw.set_return("RunCommand", True)

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "not removed" in result["message"] or "Crop was not removed" in result["message"]

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("remove_crop_view", {"view_name": "Bogus View"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert not fake_sw.call_log.calls_to("RunCommand")

    def test_selection_failure_triggers_no_runcommand_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _seed_view_and_selection(fake_sw)
        view.set_return("target_view.IsCropped", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("RunCommand")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("remove_crop_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert "Part" in result["message"]
