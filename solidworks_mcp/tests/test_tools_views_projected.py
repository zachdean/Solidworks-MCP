"""
Regression tests for the projected/predefined/auxiliary view tools
(solidworks_mcp/tools/drawing_views.py's insert_projected_view,
insert_predefined_views, insert_auxiliary_view), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
so these exercise both the registry wiring and the `DrawingOperations`
automation methods it calls, asserting COM call order/args against the
fake's call log the same way test_tools_views_basic.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes
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


def _view(fake_sw, obj_id, name, type_code=None, position=None):
    """Build a fake `IView`-shaped object with `GetName2`/`Type` (and
    optionally `Position`) scripted under path-scoped keys -- multiple view
    objects in one test can't share the bare-name key for the same method
    with different values, per test_tools_views_basic.py's own convention
    (see its `test_section_view_falls_back_to_base_view...` comment)."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    if position is not None:
        view.set_return(f"{obj_id}.Position", position)
    return view


class TestInsertProjectedView:
    def test_happy_path_selects_parent_view_before_projecting(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.1, 0.2])])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right",
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View2"
        log = fake_sw.call_log
        names = log.ordered_names()
        assert names.index("SelectByID2") < names.index("CreateUnfoldedViewAt3")
        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

    def test_unknown_parent_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Bogus View", "direction": "right",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("CreateUnfoldedViewAt3")

    def test_unknown_direction_errors(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "sideways",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "sideways" in result["message"]

    def test_offset_moves_the_view_via_position_setter_afterward(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.0, 0.0])])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right", "offset": 100,
        })

        assert result["success"] is True
        assert new_view.Position == pytest.approx([0.1, 0.0])
        assert fake_sw.call_log.calls_to("EditRebuild3")

    def test_no_offset_leaves_position_untouched(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.0, 0.0])])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right",
        })

        assert result["success"] is True
        assert not fake_sw.call_log.calls_to("EditRebuild3")

    def test_none_return_from_com_fails_naming_parent_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", None)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "up",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]

    def test_offset_reposition_failure_fails_the_result_not_silently(self, tool_sw):
        """The view was created, but if the Position setter itself raises,
        the view sits somewhere other than the requested offset -- reporting
        plain success there would silently hand back a wrong-position view
        while `data["offset"]` claims the request was honored."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.0, 0.0])])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)
        fake_sw.ActiveDoc.set_raises("EditRebuild3", RuntimeError("rebuild boom"))

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right", "offset": 100,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View2" in result["message"]

    def test_selection_failure_propagates_without_calling_create(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "up",
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("CreateUnfoldedViewAt3")

    def test_sheet_name_activates_sheet_before_creating(self, tool_sw):
        """`CreateUnfoldedViewAt3` places the projection on whichever sheet is
        active, so a named sheet has to be activated before the parent view is
        selected -- otherwise the new view lands on the wrong sheet."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.1, 0.2])])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right",
            "sheet_name": "Sheet2",
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("ActivateSheet") < names.index("SelectByID2")
        assert names.index("ActivateSheet") < names.index("CreateUnfoldedViewAt3")
        fake_sw.call_log.assert_called_with("ActivateSheet", "Sheet2")

    def test_unknown_sheet_name_fails_without_creating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "right",
            "sheet_name": "NoSuchSheet",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateUnfoldedViewAt3")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": "up",
        })

        assert result["success"] is False
        assert "Part" in result["message"]


_DIRECTIONS = [
    ("right", 1, 0, False),
    ("left", -1, 0, False),
    ("up", 0, 1, False),
    ("down", 0, -1, False),
    ("upright", 1, 1, True),
    ("upleft", -1, 1, True),
    ("downright", 1, -1, True),
    ("downleft", -1, -1, True),
]


class TestInsertProjectedViewDirections:
    """Pins the acceptance criteria that all 8 direction values are accepted
    and map to distinct CreateUnfoldedViewAt3 arguments: the 4 cardinal
    directions stay aligned (NotAligned=False), the 4 diagonals break
    alignment (NotAligned=True), and every direction's (X, Y, NotAligned)
    tuple is unique."""

    @pytest.mark.parametrize("direction,dx,dy,not_aligned", _DIRECTIONS)
    def test_direction_maps_to_expected_position_and_alignment_flag(
        self, tool_sw, direction, dx, dy, not_aligned,
    ):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                             position=[0.0, 0.0])])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("proj_view")
        new_view.set_return("proj_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

        result = dispatch("insert_projected_view", {
            "parent_view_name": "Drawing View1", "direction": direction,
        })

        assert result["success"] is True
        step = 0.05
        fake_sw.call_log.assert_called_with(
            "CreateUnfoldedViewAt3",
            pytest.approx(dx * step), pytest.approx(dy * step), 0.0, not_aligned,
        )

    def test_all_8_directions_produce_distinct_com_argument_tuples(self, tool_sw):
        seen = set()
        for direction, *_ in _DIRECTIONS:
            fake_sw = tool_sw("drawing")
            sheet = fake_sw.ActiveDoc.GetCurrentSheet()
            sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1",
                                                 position=[0.0, 0.0])])
            fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
            new_view = fake_sw.new_object("proj_view")
            new_view.set_return("proj_view.GetName2", "Drawing View2")
            fake_sw.ActiveDoc.set_return("CreateUnfoldedViewAt3", new_view)

            result = dispatch("insert_projected_view", {
                "parent_view_name": "Drawing View1", "direction": direction,
            })

            assert result["success"] is True, (direction, result)
            call = fake_sw.call_log.calls_to("CreateUnfoldedViewAt3")[0]
            seen.add(call.args)

        assert len(seen) == len(_DIRECTIONS)


class TestInsertPredefinedViews:
    def test_happy_path_returns_filled_view_names(self, tool_sw):
        # A predefined-view placeholder is already a named view object on
        # the sheet *before* it's filled (docs/api/02-views.md: the method
        # only fills existing placeholders, it doesn't create them) -- so
        # the fill signal has to be whether the view starts referencing a
        # model, not whether a new view name appears. `ReferencedDocument`
        # is scripted to flip from unset to `ref_doc` across the two
        # `GetViews` reads the tool makes (before/after the call).
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        placeholder = _view(fake_sw, "placeholder_view", "Drawing View1")
        ref_doc = fake_sw.new_object("ref_doc")
        placeholder.set_sequence("placeholder_view.ReferencedDocument", [None, ref_doc])
        sheet.set_return("GetViews", [placeholder])
        fake_sw.ActiveDoc.set_return("InsertModelInPredefinedView", True)

        result = dispatch("insert_predefined_views", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is True
        assert result["data"]["filled_views"] == ["Drawing View1"]
        fake_sw.call_log.assert_called_with(
            "InsertModelInPredefinedView", "/models/Bracket.sldprt",
        )

    def test_no_placeholders_errors_descriptively_without_calling_com(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [])

        result = dispatch("insert_predefined_views", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "predefined" in result["message"].lower()
        assert not fake_sw.call_log.calls_to("InsertModelInPredefinedView")

    def test_com_returns_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        placeholder = _view(fake_sw, "placeholder_view", "Drawing View1")
        placeholder.set_return("placeholder_view.ReferencedDocument", None)
        sheet.set_return("GetViews", [placeholder])
        fake_sw.ActiveDoc.set_return("InsertModelInPredefinedView", False)

        result = dispatch("insert_predefined_views", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Failed to insert model" in result["message"]

    def test_true_return_but_nothing_referenced_fails(self, tool_sw):
        """`InsertModelInPredefinedView` returning `True` isn't itself proof
        of a fill -- if no previously-unfilled placeholder ends up
        referencing the model, that's still a failure, not a silent
        success with an empty `filled_views`."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        placeholder = _view(fake_sw, "placeholder_view", "Drawing View1")
        placeholder.set_return("placeholder_view.ReferencedDocument", None)
        sheet.set_return("GetViews", [placeholder])
        fake_sw.ActiveDoc.set_return("InsertModelInPredefinedView", True)

        result = dispatch("insert_predefined_views", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "reference" in result["message"].lower()

    def test_sheet_name_activates_sheet_before_inserting(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        placeholder = _view(fake_sw, "placeholder_view", "Drawing View1")
        ref_doc = fake_sw.new_object("ref_doc2")
        placeholder.set_sequence("placeholder_view.ReferencedDocument", [None, ref_doc])
        sheet.set_return("GetViews", [placeholder])
        fake_sw.ActiveDoc.set_return("InsertModelInPredefinedView", True)

        result = dispatch("insert_predefined_views", {
            "model_path": "/models/Bracket.sldprt", "sheet_name": "Sheet2",
        })

        assert result["success"] is True
        names = fake_sw.call_log.ordered_names()
        assert names.index("ActivateSheet") < names.index("InsertModelInPredefinedView")
        fake_sw.call_log.assert_called_with("ActivateSheet", "Sheet2")

    def test_unknown_sheet_name_fails_without_inserting(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)

        result = dispatch("insert_predefined_views", {
            "model_path": "/models/Bracket.sldprt", "sheet_name": "NoSuchSheet",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertModelInPredefinedView")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_predefined_views", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestInsertAuxiliaryView:
    def test_happy_path_selects_edge_before_creating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("aux_view")
        new_view.set_return("aux_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateAuxiliaryViewAt2", new_view)

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1",
            "edge_selection": {"x": 10, "y": 20},
            "x": 50, "y": 25, "label": "A",
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View2"
        log = fake_sw.call_log
        names = log.ordered_names()
        assert names.index("SelectByID2") < names.index("CreateAuxiliaryViewAt2")

        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == ""
        assert select_call.args[1] == "EDGE"
        assert select_call.args[2] == pytest.approx(0.01)
        assert select_call.args[3] == pytest.approx(0.02)
        assert select_call.args[4] == pytest.approx(0.0)

        log.assert_called_with(
            "CreateAuxiliaryViewAt2", 0.05, 0.025, 0.0, False, "A", True, False,
        )

    def test_sheet_name_activates_sheet_before_creating(self, tool_sw):
        """`CreateAuxiliaryViewAt2` also places its view on the active sheet,
        so a named sheet is activated before the reference edge is selected."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        new_view = fake_sw.new_object("aux_view")
        new_view.set_return("aux_view.GetName2", "Drawing View2")
        fake_sw.ActiveDoc.set_return("CreateAuxiliaryViewAt2", new_view)

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1",
            "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0, "sheet_name": "Sheet2",
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("ActivateSheet") < names.index("CreateAuxiliaryViewAt2")
        fake_sw.call_log.assert_called_with("ActivateSheet", "Sheet2")

    def test_unknown_sheet_name_fails_without_creating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1",
            "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0, "sheet_name": "NoSuchSheet",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateAuxiliaryViewAt2")

    def test_unknown_parent_view_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "known_view", "Drawing View1")])

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Bogus", "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("CreateAuxiliaryViewAt2")

    def test_missing_edge_selection_keys_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1", "edge_selection": {"x": 1},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_none_return_from_com_fails_naming_parent_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("CreateAuxiliaryViewAt2", None)

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1", "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]

    def test_selection_failure_propagates_without_calling_create(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "parent_view", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1", "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("CreateAuxiliaryViewAt2")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_auxiliary_view", {
            "parent_view_name": "Drawing View1", "edge_selection": {"x": 1, "y": 1},
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert "Part" in result["message"]
