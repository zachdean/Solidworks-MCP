"""
Regression tests for the section view tool
(solidworks_mcp/tools/drawing_views.py's insert_section_view), dispatched
through the real `solidworks_mcp.tools` registry (`dispatch()`) against the
fake COM harness -- so these exercise both the registry wiring and the
`DrawingOperations.insert_section_view` automation method it calls, asserting
COM call order/args against the fake's call log the same way
test_tools_views_projected.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_views_projected.py's `tool_sw`, connecting
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
    under path-scoped keys, per test_tools_views_projected.py's `_view`
    convention (multiple view objects in one test can't share a bare-name
    key for the same method with different values)."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    return view


def _seed_parent_and_selection(fake_sw, parent_name="Drawing View1"):
    """Common setup every happy/near-happy-path test needs: a resolvable
    parent view on the active sheet, plus `ActivateView`/`SelectByID2`
    scripted to succeed."""
    sheet = fake_sw.ActiveDoc.GetCurrentSheet()
    sheet.set_return("GetViews", [_view(fake_sw, "parent_view", parent_name)])
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)


def _seed_created_view(fake_sw, obj_id="section_view", name="Drawing View2", label="A"):
    """A fake created section `IView` wired up with a `GetSection()` ->
    `IDrSection` chain, so `data["label"]` reads back a real string instead
    of an auto-vivified stand-in object (see fake_com.py's module docstring
    Limitations section)."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    section = fake_sw.new_object(f"{obj_id}.section")
    section.set_return(f"{obj_id}.section.GetLabel", label)
    view.set_return(f"{obj_id}.GetSection", section)
    fake_sw.ActiveDoc.set_return("CreateSectionViewAt5", view)
    return view, section


class TestInsertSectionViewHappyPath:
    def test_end_to_end_com_sequence_and_meter_conversion(self, tool_sw):
        """Acceptance criteria: the COM sequence is asserted end to end
        (activate parent, sketch the cut line, select, CreateSectionViewAt5)
        and cut-line coordinates reach COM in meters."""
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [{"x": 10, "y": 20}, {"x": 10, "y": 80}],
            "x": 50, "y": 25, "label": "A",
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        names = log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("CreateLine")
            < names.index("SelectByID2") < names.index("CreateSectionViewAt5")
        ), names

        log.assert_called_with("ActivateView", "Drawing View1")
        log.assert_called_with(
            "CreateLine", pytest.approx(0.010), pytest.approx(0.020), 0.0,
            pytest.approx(0.010), pytest.approx(0.080), 0.0,
        )
        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == ""
        assert select_call.args[1] == "SKETCHSEGMENT"
        assert select_call.args[2] == pytest.approx(0.010)
        assert select_call.args[3] == pytest.approx(0.050)

        create_call = log.calls_to("CreateSectionViewAt5")[0]
        assert create_call.args[0] == pytest.approx(0.05)
        assert create_call.args[1] == pytest.approx(0.025)
        assert create_call.args[2] == pytest.approx(0.0)
        assert create_call.args[3] == "A"
        assert create_call.args[4] == 0  # section_type="full" -> no Options bit
        assert create_call.args[6] == pytest.approx(0.0)  # section_depth

    def test_returns_view_name_and_label(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw, name="Drawing View7", label="B")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View7"
        assert result["data"]["label"] == "B"

    def test_auto_hatch_and_display_only_applied_to_section(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _view_obj, section = _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "auto_hatch": False, "display_only": True,
        })

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("SetAutoHatch", False)
        fake_sw.call_log.assert_called_with("SetDisplayOnlySurfaceCut", True)

    def test_use_sheet_scale_sets_integer_view_property_and_rebuilds(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        view_obj, _section = _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "use_sheet_scale": False,
        })

        assert result["success"] is True
        # UseSheetScale is System.Integer (1/0), not Boolean -- assigning
        # plain `False` would be wrong (VBA's False is 0, but Python's bool
        # is a distinct type COM may not coerce the same way). `False == 0`
        # is True in Python, so `is not True` is what actually pins the type.
        assert view_obj.UseSheetScale == 0
        assert view_obj.UseSheetScale is not False
        assert fake_sw.call_log.calls_to("EditRebuild3")

    def test_use_sheet_scale_true_assigns_the_integer_1_not_bool_true(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        view_obj, _section = _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "use_sheet_scale": True,
        })

        assert result["success"] is True
        assert view_obj.UseSheetScale == 1
        assert view_obj.UseSheetScale is not True

    def test_label_omitted_passes_empty_string_and_reads_back_auto_assigned(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw, label="C")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        assert result["data"]["label"] == "C"
        create_call = fake_sw.call_log.calls_to("CreateSectionViewAt5")[0]
        assert create_call.args[3] == ""

    def test_cut_points_accept_list_pair_form(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[1, 2], [3, 4]],
            "x": 0, "y": 0,
        })

        assert result["success"] is True
        assert fake_sw.call_log.calls_to("CreateLine")


class TestInsertSectionViewCutPointsValidation:
    def test_fewer_than_2_points_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateLine")
        assert not log.calls_to("CreateSectionViewAt5")

    def test_two_identical_points_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[5, 5], [5, 5]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateSectionViewAt5")

    def test_empty_cut_points_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1", "cut_points": [],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestInsertSectionViewOffsetSections:
    def test_offset_section_with_3_points_produces_2_sketch_segments(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10], [10, 10]],
            "x": 0, "y": 0, "section_type": "aligned",
        })

        assert result["success"] is True
        assert len(fake_sw.call_log.calls_to("CreateLine")) == 2
        assert len(fake_sw.call_log.calls_to("SelectByID2")) == 2

    def test_offset_section_with_4_points_produces_3_sketch_segments(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10], [10, 10], [10, 20]],
            "x": 0, "y": 0, "section_type": "full",
        })

        assert result["success"] is True
        assert len(fake_sw.call_log.calls_to("CreateLine")) == 3


class TestInsertSectionViewSectionType:
    def test_aligned_maps_to_offset_section_bit(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "section_type": "aligned",
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateSectionViewAt5")[0]
        assert create_call.args[4] == 2  # swCreateSectionView_OffsetSection

    def test_half_maps_to_partial_bit(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "section_type": "half",
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateSectionViewAt5")[0]
        assert create_call.args[4] == 16  # swCreateSectionView_Partial

    def test_flip_direction_ors_in_change_direction_bit(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _seed_created_view(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "section_type": "aligned", "flip_direction": True,
        })

        assert result["success"] is True
        create_call = fake_sw.call_log.calls_to("CreateSectionViewAt5")[0]
        # OffsetSection (2) | ChangeDirection (4) = 6
        assert create_call.args[4] == 6

    def test_half_section_with_more_than_2_points_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10], [10, 10]],
            "x": 0, "y": 0, "section_type": "half",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("CreateSectionViewAt5")

    def test_unknown_section_type_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0, "section_type": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "bogus" in result["message"]


class TestInsertSectionViewErrorPaths:
    def test_unknown_parent_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_section_view", {
            "parent_view_name": "Bogus View",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("CreateSectionViewAt5")

    def test_selection_failure_propagates_without_calling_create(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("CreateSectionViewAt5")
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_activate_view_failure_fails_without_sketching(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("CreateLine")

    def test_none_return_from_com_fails_naming_parent_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        fake_sw.ActiveDoc.set_return("CreateSectionViewAt5", None)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]
        # Only a successful create consumes the cut line, so a failed call
        # cleans up its own sketch geometry instead of leaving a stray open
        # sketch that a retry would re-sketch on top of.
        assert fake_sw.call_log.calls_to("DeleteSelection2")

    def test_get_section_returning_none_fails_naming_the_created_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        view = fake_sw.new_object("section_view")
        view.set_return("section_view.GetName2", "Drawing View9")
        view.set_return("section_view.GetSection", None)
        fake_sw.ActiveDoc.set_return("CreateSectionViewAt5", view)

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View9" in result["message"]

    def test_section_configuration_failure_fails_the_result_not_silently(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _seed_parent_and_selection(fake_sw)
        _view_obj, section = _seed_created_view(fake_sw, name="Drawing View9")
        section.set_raises("SetAutoHatch", RuntimeError("boom"))

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View9" in result["message"]

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_section_view", {
            "parent_view_name": "Drawing View1",
            "cut_points": [[0, 0], [0, 10]],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert "Part" in result["message"]
