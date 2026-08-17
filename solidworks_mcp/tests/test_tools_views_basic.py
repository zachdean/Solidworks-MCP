"""
Regression tests for the model-view / standard-3-view / view-discovery tools
(solidworks_mcp/tools/drawing_views.py), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
so these exercise both the registry wiring and the `DrawingOperations`
automation methods it calls, asserting COM call order/args against the
fake's call log the same way solidworks_mcp/tests/test_tools_document.py does.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes, SwUserPreferenceToggle
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_document.py's `tool_sw`, connecting the
    shared `tools.sw_automation` singleton (what `dispatch()` actually calls
    through) to a fresh fake `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


class TestInsertModelView:
    def test_happy_path_maps_friendly_name_and_converts_units_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        view = fake_sw.new_object("view1")
        view.set_return("GetName2", "Drawing View1")
        fake_sw.ActiveDoc.set_return("CreateDrawViewFromModelView3", view)

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt",
            "view_name": "top",
            "x": 50, "y": 25,
        })

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View1"
        assert result["data"]["requested_view_name"] == "*Top"
        fake_sw.call_log.assert_called_with(
            "CreateDrawViewFromModelView3",
            "/models/Bracket.sldprt", "*Top", 0.05, 0.025, 0.0,
        )

    def test_view_name_is_case_insensitive_and_star_prefix_tolerant(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = fake_sw.new_object("view1")
        view.set_return("GetName2", "Drawing View1")
        fake_sw.ActiveDoc.set_return("CreateDrawViewFromModelView3", view)

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt", "view_name": "*ISOMETRIC",
        })

        assert result["success"] is True
        assert result["data"]["requested_view_name"] == "*Isometric"

    def test_unknown_view_name_errors_listing_valid_names(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt", "view_name": "Bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus" in result["message"]
        assert "*Front" in result["message"]

    def test_none_return_from_com_fails_naming_model_and_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("CreateDrawViewFromModelView3", None)

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt", "view_name": "Front",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "/models/Bracket.sldprt" in result["message"]
        assert "*Front" in result["message"]

    def test_sheet_name_activates_sheet_before_creating_the_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", True)
        view = fake_sw.new_object("view1")
        view.set_return("GetName2", "Drawing View1")
        fake_sw.ActiveDoc.set_return("CreateDrawViewFromModelView3", view)

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt", "sheet_name": "Sheet2",
        })

        assert result["success"] is True
        log = fake_sw.call_log
        names = log.ordered_names()
        assert names.index("ActivateSheet") < names.index("CreateDrawViewFromModelView3")
        log.assert_called_with("ActivateSheet", "Sheet2")

    def test_unknown_sheet_name_fails_without_creating_a_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateSheet", False)

        result = dispatch("insert_model_view", {
            "model_path": "/models/Bracket.sldprt", "sheet_name": "NoSuchSheet",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateDrawViewFromModelView3")

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("insert_model_view", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestInsertStandard3View:
    def test_third_angle_happy_path_restores_preference_on_success(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceToggle", False)
        fake_sw.ActiveDoc.set_return("Create3rdAngleViews2", True)

        result = dispatch("insert_standard_3_view", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is True
        toggle = int(SwUserPreferenceToggle.swAutomaticScaling3ViewDrawings)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, True), (toggle, False)]
        assert not fake_sw.call_log.calls_to("Create1stAngleViews2")

    def test_first_angle_calls_create1stangleviews2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceToggle", True)
        fake_sw.ActiveDoc.set_return("Create1stAngleViews2", True)

        result = dispatch("insert_standard_3_view", {
            "model_path": "/models/Bracket.sldprt", "first_angle": True,
        })

        assert result["success"] is True
        assert fake_sw.call_log.calls_to("Create1stAngleViews2")
        assert not fake_sw.call_log.calls_to("Create3rdAngleViews2")

    def test_restores_preference_when_creation_returns_false(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceToggle", True)
        fake_sw.ActiveDoc.set_return("Create3rdAngleViews2", False)

        result = dispatch("insert_standard_3_view", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        toggle = int(SwUserPreferenceToggle.swAutomaticScaling3ViewDrawings)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, True), (toggle, True)]

    def test_restores_preference_when_creation_raises(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.set_return("GetUserPreferenceToggle", False)
        fake_sw.ActiveDoc.set_raises("Create3rdAngleViews2", RuntimeError("boom"))

        result = dispatch("insert_standard_3_view", {"model_path": "/models/Bracket.sldprt"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        toggle = int(SwUserPreferenceToggle.swAutomaticScaling3ViewDrawings)
        calls = fake_sw.call_log.calls_to("SetUserPreferenceToggle")
        assert [c.args for c in calls] == [(toggle, True), (toggle, False)]


class TestListViews:
    def test_zero_views_does_not_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [])

        result = dispatch("list_views", {})

        assert result["success"] is True
        assert result["data"]["views"] == []

    def test_happy_path_reports_name_type_scale_and_position(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        view = fake_sw.new_object("view1")
        view.set_return("GetName2", "Drawing View1")
        view.set_return("Type", int(SwDrawingViewTypes.swDrawingStandardView))
        view.set_return("ScaleDecimal", 0.5)
        view.set_return("Position", [0.1, 0.2])
        view.set_return("GetBaseView", None)
        view.set_return("ReferencedDocument", None)
        sheet.set_return("GetViews", [view])

        result = dispatch("list_views", {})

        assert result["success"] is True
        [described] = result["data"]["views"]
        assert described["name"] == "Drawing View1"
        assert described["type"] == "swDrawingStandardView"
        assert described["scale"] == 0.5
        assert described["x"] == 100.0
        assert described["y"] == 200.0
        assert described["parent_view"] is None

    def test_filters_out_a_sheet_pseudo_view_entry_if_one_is_present(self, tool_sw):
        """`ISheet::GetViews` is documented as *not* heading its array with
        the sheet's own pseudo-view (unlike `IDrawingDoc::GetViews`), but
        that's an inference from one working macro, flagged unverified in
        docs/api/02-views.md. `list_views` filters defensively rather than
        trusting it -- this pins that filter."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()

        sheet_pseudo_view = fake_sw.new_object("sheet_pseudo_view")
        sheet_pseudo_view.set_return(
            "sheet_pseudo_view.Type", int(SwDrawingViewTypes.swDrawingSheet))
        sheet_pseudo_view.set_return("sheet_pseudo_view.GetName2", "Sheet1")

        real_view = fake_sw.new_object("real_view")
        real_view.set_return(
            "real_view.Type", int(SwDrawingViewTypes.swDrawingStandardView))
        real_view.set_return("real_view.GetName2", "Drawing View1")

        sheet.set_return("GetViews", [sheet_pseudo_view, real_view])

        result = dispatch("list_views", {})

        assert result["success"] is True
        [described] = result["data"]["views"]
        assert described["name"] == "Drawing View1"

    def test_explicit_sheet_name_resolves_via_sheet_accessor(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet2 = fake_sw.new_object("sheet2")
        sheet2.set_return("GetViews", [])
        fake_sw.ActiveDoc.set_return("Sheet", sheet2)

        result = dispatch("list_views", {"sheet_name": "Sheet2"})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("Sheet", "Sheet2")

    def test_unknown_sheet_name_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("Sheet", None)

        result = dispatch("list_views", {"sheet_name": "NoSuchSheet"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_section_view_falls_back_to_base_view_for_referenced_model_and_parent(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()

        ref_doc = fake_sw.new_object("ref_doc")
        ref_doc.set_return("GetPathName", "/models/Bracket.sldprt")
        ref_doc.set_return("GetTitle", "Bracket.SLDPRT")

        base_view = fake_sw.new_object("base_view")
        # Exact-path keys, not the bare method name: `section_view` also
        # scripts `GetName2` below, and the fake harness's bare-name
        # scripting is shared process-wide across every object, so two
        # different objects can't both use the bare-name key for the same
        # method with different values (see testing/fake_com.py's module
        # docstring on `set_return` key precedence).
        base_view.set_return("base_view.GetName2", "Drawing View1")
        base_view.set_return("base_view.ReferencedDocument", ref_doc)

        section_view = fake_sw.new_object("section_view")
        section_view.set_return("section_view.GetName2", "Section View A-A")
        section_view.set_return("section_view.ReferencedDocument", None)
        section_view.set_return("GetBaseView", base_view)
        sheet.set_return("GetViews", [section_view])

        result = dispatch("list_views", {})

        assert result["success"] is True
        [described] = result["data"]["views"]
        assert described["parent_view"] == "Drawing View1"
        assert described["referenced_model"] == "/models/Bracket.sldprt"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("list_views", {})

        assert result["success"] is False
        assert "Part" in result["message"]
