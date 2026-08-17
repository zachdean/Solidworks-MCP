"""
Regression tests for the view placement/alignment/display/deletion tools
(solidworks_mcp/tools/drawing_view_layout.py: move_view, align_view,
set_view_scale, set_view_display_mode, delete_view, auto_arrange_views),
dispatched through the real `solidworks_mcp.tools` registry (`dispatch()`)
against the fake COM harness -- so these exercise both the registry wiring
and the `DrawingOperations` automation methods it calls, asserting COM call
order/args against the fake's call log the same way
test_tools_views_basic.py/test_tools_views_projected.py do.
"""

import pytest

from solidworks_mcp.constants_drawing import (
    SwAlignViewTypes,
    SwDisplayMode,
    SwDrawingViewTypes,
    SwViewAlignment,
)
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_views_basic.py's `tool_sw`, connecting the
    shared `tools.sw_automation` singleton (what `dispatch()` actually calls
    through) to a fresh fake `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _view(fake_sw, obj_id, name, type_code=None, position=None, alignment=None,
          base_view=None, outline=None):
    """Build a fake `IView`-shaped object with path-scoped keys, per
    test_tools_views_projected.py's own `_view` helper convention -- multiple
    view objects in one test can't share the bare-name key for the same
    method with different values."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    if position is not None:
        view.set_return(f"{obj_id}.Position", list(position))
    if alignment is not None:
        view.set_return(f"{obj_id}.GetAlignment", int(alignment))
    if base_view is not None:
        view.set_return(f"{obj_id}.GetBaseView", base_view)
    if outline is not None:
        view.set_return(f"{obj_id}.GetOutline", list(outline))
    return view


def _boxes_overlap(a, b):
    """True if two (xmin, ymin, xmax, ymax) boxes overlap (touching edges
    are not an overlap)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class TestMoveView:
    def test_happy_path_sets_position_in_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])

        result = dispatch("move_view", {"view_name": "Drawing View1", "x": 50, "y": 25})

        assert result["success"] is True
        # `Position` is a COM property *set*, not a method call -- the fake
        # harness's call log only records invocations/reads, not writes
        # (testing/fake_com.py's `__setattr__`), so the write is verified by
        # reading the attribute back, same as
        # test_tools_views_projected.py's own Position-setter assertions.
        assert view.Position == pytest.approx([0.05, 0.025])
        assert fake_sw.call_log.calls_to("EditRebuild3")

    def test_alignment_locked_view_reports_lock_instead_of_moving(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View2",
                  alignment=int(SwViewAlignment.swViewAligned)),
        ])

        result = dispatch("move_view", {"view_name": "Drawing View2", "x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "align" in result["message"].lower()
        assert not fake_sw.call_log.calls_to("Position")

    def test_align_both_bit_also_reports_lock(self, tool_sw):
        """swViewAlignBoth (3) has both the AlignedChildren (1) and Aligned
        (2) bits set -- move_view must still detect the lock via the shared
        bit rather than an exact-value match against swViewAligned alone."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View3",
                  alignment=int(SwViewAlignment.swViewAlignBoth)),
        ])

        result = dispatch("move_view", {"view_name": "Drawing View3", "x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_projected_view_alignment_locked_to_its_parent_reports_lock(self, tool_sw):
        """Pins the acceptance criterion's literally-named case: a projected
        view (swDrawingProjectedView) locked to its parent must report the
        lock rather than moving or silently no-op'ing."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View2",
                  type_code=SwDrawingViewTypes.swDrawingProjectedView,
                  alignment=int(SwViewAlignment.swViewAligned)),
        ])

        result = dispatch("move_view", {"view_name": "Drawing View2", "x": 10, "y": 10})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("EditRebuild3")

    def test_children_aligned_bit_alone_does_not_block_the_move(self, tool_sw):
        """swViewAlignedChildren (1) means other views are aligned *to* this
        one -- this view itself is still free to move."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1",
                  alignment=int(SwViewAlignment.swViewAlignedChildren)),
        ])

        result = dispatch("move_view", {"view_name": "Drawing View1", "x": 10, "y": 10})

        assert result["success"] is True

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("move_view", {"view_name": "Bogus", "x": 0, "y": 0})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Drawing View1" in result["message"]


class TestAlignView:
    def test_horizontal_alignment_calls_align_with_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        ref_view = _view(fake_sw, "ref", "Drawing View1")
        moving_view = _view(fake_sw, "v2", "Drawing View2")
        moving_view.set_return("v2.AlignWithView", True)
        sheet.set_return("GetViews", [ref_view, moving_view])

        result = dispatch("align_view", {
            "view_name": "Drawing View2", "reference_view_name": "Drawing View1",
            "alignment": "horizontal",
        })

        assert result["success"] is True
        call = fake_sw.call_log.calls_to("AlignWithView")[0]
        assert call.args[0] == int(SwAlignViewTypes.swAlignViewHorizontalCenter)
        assert call.args[1] is ref_view

    def test_vertical_origin_alignment_maps_to_correct_enum(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        ref_view = _view(fake_sw, "ref", "Drawing View1")
        moving_view = _view(fake_sw, "v2", "Drawing View2")
        moving_view.set_return("v2.AlignWithView", True)
        sheet.set_return("GetViews", [ref_view, moving_view])

        result = dispatch("align_view", {
            "view_name": "Drawing View2", "reference_view_name": "Drawing View1",
            "alignment": "vertical_origin",
        })

        assert result["success"] is True
        call = fake_sw.call_log.calls_to("AlignWithView")[0]
        assert call.args[0] == int(SwAlignViewTypes.swAlignViewVerticalOrigin)

    def test_center_alignment_without_reference_view_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("align_view", {
            "view_name": "Drawing View1", "alignment": "horizontal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("AlignWithView")

    def test_break_alignment_calls_remove_alignment(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1",
                  alignment=int(SwViewAlignment.swViewAligned)),
        ])

        result = dispatch("align_view", {"view_name": "Drawing View1", "alignment": "break"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("RemoveAlignment")
        assert not fake_sw.call_log.calls_to("AlignWithView")

    def test_none_alignment_is_an_alias_for_break(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("align_view", {"view_name": "Drawing View1", "alignment": "none"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("RemoveAlignment")

    def test_default_alignment_calls_use_default_alignment(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("align_view", {"view_name": "Drawing View1", "alignment": "default"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("UseDefaultAlignment")

    def test_unknown_alignment_value_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("align_view", {
            "view_name": "Drawing View1", "reference_view_name": "Drawing View1",
            "alignment": "diagonal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_unknown_reference_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("align_view", {
            "view_name": "Drawing View1", "reference_view_name": "Bogus",
            "alignment": "horizontal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Drawing View1" in result["message"]


class TestSetViewScale:
    def test_explicit_scale_sets_ratio_and_clears_use_sheet_scale(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])

        result = dispatch("set_view_scale", {
            "view_name": "Drawing View1", "scale_num": 1, "scale_denom": 2,
        })

        assert result["success"] is True
        # Property sets, not method calls -- verified by reading the
        # attribute back (see move_view's own happy-path test for why).
        assert view.ScaleRatio == [1.0, 2.0]
        assert view.UseSheetScale == 0

    def test_use_sheet_scale_sets_flag_only(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet.set_return("GetViews", [view])

        result = dispatch("set_view_scale", {
            "view_name": "Drawing View1", "use_sheet_scale": True,
        })

        assert result["success"] is True
        assert view.UseSheetScale == 1

    def test_use_sheet_scale_with_explicit_scale_is_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_view_scale", {
            "view_name": "Drawing View1", "scale_num": 1, "scale_denom": 2,
            "use_sheet_scale": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_missing_scale_denom_fails(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_view_scale", {"view_name": "Drawing View1", "scale_num": 1})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_non_positive_scale_fails(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_view_scale", {
            "view_name": "Drawing View1", "scale_num": 0, "scale_denom": 2,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestSetViewDisplayMode:
    @pytest.mark.parametrize("mode_name,expected_enum", [
        ("wireframe", SwDisplayMode.swWIREFRAME),
        ("hidden-lines-visible", SwDisplayMode.swHIDDEN_GREYED),
        ("hidden-lines-removed", SwDisplayMode.swHIDDEN),
        ("shaded", SwDisplayMode.swSHADED),
        ("shaded-with-edges", SwDisplayMode.swSHADED_EDGES),
    ])
    def test_maps_all_five_mode_names_to_the_dossier_enum(self, tool_sw, mode_name, expected_enum):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        view.set_return("v1.SetDisplayMode3", True)
        sheet.set_return("GetViews", [view])

        result = dispatch("set_view_display_mode", {
            "view_name": "Drawing View1", "mode": mode_name,
        })

        assert result["success"] is True
        call = fake_sw.call_log.calls_to("SetDisplayMode3")[0]
        assert call.args[1] == int(expected_enum)

    def test_use_parent_is_always_false_for_an_explicit_mode_set(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        view.set_return("v1.SetDisplayMode3", True)
        sheet.set_return("GetViews", [view])

        dispatch("set_view_display_mode", {"view_name": "Drawing View1", "mode": "shaded"})

        call = fake_sw.call_log.calls_to("SetDisplayMode3")[0]
        assert call.args[0] is False

    def test_shadows_and_high_quality_map_to_edges_and_facetted(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = _view(fake_sw, "v1", "Drawing View1")
        view.set_return("v1.SetDisplayMode3", True)
        sheet.set_return("GetViews", [view])

        dispatch("set_view_display_mode", {
            "view_name": "Drawing View1", "mode": "shaded",
            "shadows": True, "high_quality": False,
        })

        call = fake_sw.call_log.calls_to("SetDisplayMode3")[0]
        # (UseParent, Mode, Facetted, Edges) -- Facetted is the inverse of
        # high_quality, Edges is this tool's `shadows` parameter.
        assert call.args[2] is True   # high_quality=False -> Facetted=True
        assert call.args[3] is True   # shadows=True -> Edges=True

    def test_unknown_mode_fails_before_any_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_view_display_mode", {
            "view_name": "Drawing View1", "mode": "cartoon",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetDisplayMode3")


class TestDeleteView:
    def test_deletes_a_leaf_view_with_no_children(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_view", {"view_name": "Drawing View1"})

        assert result["success"] is True
        assert result["data"]["removed"] == ["Drawing View1"]

    def test_refuses_a_parent_with_children_without_cascade(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        parent = _view(fake_sw, "parent", "Drawing View1")
        child = _view(fake_sw, "child", "Section View A-A", base_view=parent)
        sheet.set_return("GetViews", [parent, child])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["children"] == ["Section View A-A"]
        assert not fake_sw.call_log.calls_to("DeleteSelection2")

    def test_cascade_deletes_children_before_the_parent_and_reports_removed(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        parent = _view(fake_sw, "parent", "Drawing View1")
        child = _view(fake_sw, "child", "Section View A-A", base_view=parent)
        sheet.set_return("GetViews", [parent, child])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_view", {"view_name": "Drawing View1", "cascade": True})

        assert result["success"] is True
        assert result["data"]["removed"] == ["Section View A-A", "Drawing View1"]
        select_calls = fake_sw.call_log.calls_to("SelectByID2")
        assert [c.args[0] for c in select_calls] == ["Section View A-A", "Drawing View1"]

    def test_cascade_deletes_grandchildren_before_children(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        grandparent = _view(fake_sw, "gp", "Drawing View1")
        parent = _view(fake_sw, "parent", "Detail View A", base_view=grandparent)
        child = _view(fake_sw, "child", "Detail View B", base_view=parent)
        sheet.set_return("GetViews", [grandparent, parent, child])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_view", {"view_name": "Drawing View1", "cascade": True})

        assert result["success"] is True
        assert result["data"]["removed"] == ["Detail View B", "Detail View A", "Drawing View1"]

    def test_unknown_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("delete_view", {"view_name": "Bogus"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Drawing View1" in result["message"]

    def test_partial_cascade_failure_reports_what_was_already_removed(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        parent = _view(fake_sw, "parent", "Drawing View1")
        child = _view(fake_sw, "child", "Section View A-A", base_view=parent)
        sheet.set_return("GetViews", [parent, child])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        # Child deletes fine; the parent's own DeleteSelection2 fails.
        fake_sw.ActiveDoc.Extension.set_sequence("DeleteSelection2", [True, False])

        result = dispatch("delete_view", {"view_name": "Drawing View1", "cascade": True})

        assert result["success"] is False
        assert result["data"]["removed"] == ["Section View A-A"]


class TestAutoArrangeViews:
    def test_no_views_returns_success_with_empty_arranged(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [])

        result = dispatch("auto_arrange_views", {})

        assert result["success"] is True
        assert result["data"]["arranged"] == []

    def test_view_with_unreadable_outline_is_skipped_not_failed(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        good = _view(fake_sw, "v1", "Drawing View1", position=[0, 0],
                      outline=[0.0, 0.0, 0.1, 0.05])
        bad = _view(fake_sw, "v2", "Drawing View2")  # no outline scripted
        sheet.set_return("GetViews", [good, bad])

        result = dispatch("auto_arrange_views", {})

        assert result["success"] is True
        assert result["data"]["skipped"] == ["Drawing View2"]
        assert [a["view_name"] for a in result["data"]["arranged"]] == ["Drawing View1"]

    def test_view_locked_to_an_external_alignment_is_not_placed(self, tool_sw):
        """A view aligned via align_view (no GetBaseView parent, but
        GetAlignment's swViewAligned bit set) would otherwise look like a
        free-standing root -- writing its Position would be silently
        clamped/ignored by SolidWorks the same way move_view refuses it
        outright, so it must be excluded from placement and reported."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        movable = _view(fake_sw, "v1", "Drawing View1", position=[0.0, 0.0],
                         outline=[0.0, 0.0, 0.10, 0.05])
        locked = _view(fake_sw, "v2", "Drawing View2", position=[5.0, 5.0],
                        outline=[5.0, 5.0, 5.10, 5.05],
                        alignment=int(SwViewAlignment.swViewAligned))
        sheet.set_return("GetViews", [movable, locked])

        result = dispatch("auto_arrange_views", {})

        assert result["success"] is True
        assert result["data"]["locked"] == ["Drawing View2"]
        assert [a["view_name"] for a in result["data"]["arranged"]] == ["Drawing View1"]
        # Never touched -- still at its original scripted position.
        assert locked.Position() == [5.0, 5.0]

    def test_all_views_locked_or_skipped_returns_empty_arranged(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1", position=[0.0, 0.0],
                  outline=[0.0, 0.0, 0.10, 0.05],
                  alignment=int(SwViewAlignment.swViewAligned)),
        ])

        result = dispatch("auto_arrange_views", {})

        assert result["success"] is True
        assert result["data"]["locked"] == ["Drawing View1"]
        assert result["data"]["arranged"] == []

    def test_deterministic_positions_across_identical_fixtures(self, tool_sw):
        """Same input view outlines always yield the same positions --
        asserted twice, once per independently-built fixture (each
        `tool_sw("drawing")` call installs and connects to a fresh fake COM
        graph, per testing/fake_backend.py's nested-install support)."""
        def _run():
            fake_sw = tool_sw("drawing")
            sw_automation._units.default_unit = "m"
            sheet = fake_sw.ActiveDoc.GetCurrentSheet()
            sheet.set_return("GetViews", [
                _view(fake_sw, "v1", "Drawing View1", position=[0.0, 0.0],
                      outline=[0.0, 0.0, 0.10, 0.05]),
                _view(fake_sw, "v2", "Drawing View2", position=[1.0, 0.0],
                      outline=[1.0, 0.0, 1.20, 0.08]),
                _view(fake_sw, "v3", "Drawing View3", position=[0.0, 1.0],
                      outline=[0.0, 1.0, 0.05, 1.05]),
            ])
            result = dispatch("auto_arrange_views", {})
            assert result["success"] is True
            return result["data"]["arranged"]

        first = _run()
        second = _run()

        assert first == second
        assert len(first) == 3

    def test_no_overlapping_bounding_boxes_for_a_six_view_fixture(self, tool_sw):
        """4 alignment groups / 6 total views (2 standalone + 2 root+child
        pairs), each group's box 0.10 x 0.05 m, default 0.01 m margin --
        verifies both the exact deterministic grid placement and that no
        two groups' new bounding boxes overlap."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "m"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()

        root_a = _view(fake_sw, "root_a", "Root A", position=[0.0, 0.0],
                        outline=[0.0, 0.0, 0.10, 0.05])
        root_b = _view(fake_sw, "root_b", "Root B", position=[1.0, 0.0],
                        outline=[1.0, 0.0, 1.10, 0.05])
        root_c = _view(fake_sw, "root_c", "Root C", position=[2.0, 0.0],
                        outline=[2.0, 0.0, 2.10, 0.05])
        child_c = _view(fake_sw, "child_c", "Detail C-C", base_view=root_c,
                         position=[999.0, 999.0],  # sentinel: must stay untouched
                         outline=[2.02, 0.005, 2.08, 0.045])  # inside root_c's box
        root_d = _view(fake_sw, "root_d", "Root D", position=[3.0, 0.0],
                        outline=[3.0, 0.0, 3.10, 0.05])
        child_d = _view(fake_sw, "child_d", "Detail D-D", base_view=root_d,
                         position=[999.0, 999.0],
                         outline=[3.02, 0.005, 3.08, 0.045])  # inside root_d's box

        sheet.set_return("GetViews", [root_a, root_b, root_c, child_c, root_d, child_d])

        result = dispatch("auto_arrange_views", {})

        assert result["success"] is True
        arranged = {a["view_name"]: a for a in result["data"]["arranged"]}
        assert set(arranged) == {"Root A", "Root B", "Root C", "Root D"}
        assert arranged["Root C"]["members"] == ["Root C", "Detail C-C"]

        # Hand-computed expected grid: 4 groups, 0.10x0.05m boxes, 2 columns
        # (ceil(sqrt(4))), 0.01m default margin.
        assert arranged["Root A"]["x"] == pytest.approx(0.01)
        assert arranged["Root A"]["y"] == pytest.approx(0.01)
        assert arranged["Root B"]["x"] == pytest.approx(0.12)
        assert arranged["Root B"]["y"] == pytest.approx(0.01)
        assert arranged["Root C"]["x"] == pytest.approx(0.01)
        assert arranged["Root C"]["y"] == pytest.approx(0.07)
        assert arranged["Root D"]["x"] == pytest.approx(0.12)
        assert arranged["Root D"]["y"] == pytest.approx(0.07)

        boxes = []
        for name, w, h in [("Root A", 0.10, 0.05), ("Root B", 0.10, 0.05),
                            ("Root C", 0.10, 0.05), ("Root D", 0.10, 0.05)]:
            x, y = arranged[name]["x"], arranged[name]["y"]
            boxes.append((x, y, x + w, y + h))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                assert not _boxes_overlap(boxes[i], boxes[j]), (boxes[i], boxes[j])

        # Aligned children are never repositioned directly -- only their
        # group's root view's Position is touched.
        assert child_c.GetOutline() == [2.02, 0.005, 2.08, 0.045]
        assert child_c.Position() == [999.0, 999.0]
        assert child_d.Position() == [999.0, 999.0]

    def test_custom_margin_is_converted_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1", position=[0.0, 0.0],
                  outline=[0.0, 0.0, 0.10, 0.05]),
        ])

        result = dispatch("auto_arrange_views", {"margin": 20})

        assert result["success"] is True
        # 1 group, 20mm margin -> placed at (0.02, 0.02) m.
        assert result["data"]["arranged"][0]["x"] == pytest.approx(20.0)
        assert result["data"]["arranged"][0]["y"] == pytest.approx(20.0)

    def test_negative_margin_fails(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("auto_arrange_views", {"margin": -5})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
