"""
Regression tests for solidworks_mcp.automation.selection (SelectionOperations),
exercised through `SolidWorksAutomation` bound to the fake COM harness.
"""

import pytest

from solidworks_mcp.automation import SelectionOperations, SolidWorksAutomation


class TestMixinWiring:
    def test_selection_operations_is_in_mro(self):
        assert SelectionOperations in SolidWorksAutomation.__mro__


class TestSelectById:
    def test_passes_args_to_select_by_id2_in_exact_order(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        result = automation.select_by_id(
            "D1@Sketch2@Part1.SLDPRT", "DIMENSION", 50, 25, 0,
            append=True, mark=4, callout=None, sel_option=1,
        )

        assert result["success"] is True
        log = fake_sw.call_log
        log.assert_called_with(
            "SelectByID2",
            "D1@Sketch2@Part1.SLDPRT", "DIMENSION", 0.05, 0.025, 0.0,
            True, 4, None, 1,
        )
        # Pinned to IModelDocExtension -- 03-annotations.md documents several
        # methods that look plausible on the wrong interface and don't exist.
        assert log.calls_to("SelectByID2")[0].path.endswith(".Extension")

    def test_coordinates_convert_using_the_configured_unit(self, automation, fake_sw):
        # Non-default unit (config default is "mm"), so this fails if the
        # conversion is a hardcoded /1000 instead of a real unit lookup.
        automation._units.default_unit = "inch"
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        automation.select_by_id("", "EDGE", 1, 2, 3)

        fake_sw.call_log.assert_called_with(
            "SelectByID2", "", "EDGE",
            pytest.approx(0.0254), pytest.approx(0.0508), pytest.approx(0.0762),
            False, 0, None, 0,
        )

    def test_default_args_produce_select_exactly_this_one_behavior(self, automation, fake_sw):
        """append=False, mark=0, callout=None, sel_option=0 are the documented
        defaults for "select exactly this one thing"."""
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        automation.select_by_id("", "EDGE", 1, 2, 3)

        log = fake_sw.call_log
        log.assert_called_with("SelectByID2", "", "EDGE", 0.001, 0.002, 0.003, False, 0, None, 0)

    def test_records_what_was_selected_in_result_data(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        result = automation.select_by_id("", "FACE", 1, 2, 3)

        assert result["data"]["type"] == "FACE"
        assert result["data"]["x"] == 1
        assert result["data"]["y"] == 2
        assert result["data"]["z"] == 3

    def test_returns_structured_error_when_selectbyid2_returns_false(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = automation.select_by_id("", "EDGE", 0, 0, 0)

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"

    def test_com_exception_is_caught_not_raised(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_raises("SelectByID2", RuntimeError("boom"))

        result = automation.select_by_id("", "EDGE", 0, 0, 0)

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"


class TestClearSelection:
    def test_calls_clear_selection2_with_all_true(self, automation, fake_sw):
        result = automation.clear_selection()

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("ClearSelection2", True)


class TestGetSelectionInfo:
    def test_reports_count_and_object_types(self, automation, fake_sw):
        sel_mgr = fake_sw.ActiveDoc.SelectionManager
        sel_mgr.set_return("GetSelectedObjectCount2", 2)
        sel_mgr.set_sequence("GetSelectedObjectType3", [3, 4])  # e.g. VERTEX, EDGE codes

        result = automation.get_selection_info()

        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert result["data"]["objects"] == [
            {"index": 1, "type_code": 3},
            {"index": 2, "type_code": 4},
        ]

    def test_zero_selected_reports_empty(self, automation, fake_sw):
        sel_mgr = fake_sw.ActiveDoc.SelectionManager
        sel_mgr.set_return("GetSelectedObjectCount2", 0)

        result = automation.get_selection_info()

        assert result["success"] is True
        assert result["data"]["count"] == 0
        assert result["data"]["objects"] == []


class TestSelectedContextManager:
    def test_clears_selection_before_and_after_success(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        with automation.selected("", "EDGE", 1, 2, 3) as result:
            assert result["success"] is True

        names = fake_sw.call_log.ordered_names()
        assert names.count("ClearSelection2") == 2
        select_index = names.index("SelectByID2")
        assert "ClearSelection2" in names[:select_index]
        assert "ClearSelection2" in names[select_index + 1:]

    def test_clears_selection_on_exception_from_body(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        with pytest.raises(ValueError, match="body blew up"):
            with automation.selected("", "EDGE", 1, 2, 3):
                raise ValueError("body blew up")

        names = fake_sw.call_log.ordered_names()
        assert names.count("ClearSelection2") == 2
        select_index = names.index("SelectByID2")
        assert "ClearSelection2" in names[:select_index]
        assert "ClearSelection2" in names[select_index + 1:]

    def test_selection_failure_yields_structured_error_without_raising(self, automation, fake_sw):
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        with automation.selected("", "EDGE", 1, 2, 3) as result:
            assert result["success"] is False
            assert result["error_name"] == "swSelectionError"

        clears = fake_sw.call_log.calls_to("ClearSelection2")
        assert len(clears) == 2


class TestSelectViewByName:
    def test_selects_a_known_view(self, make_sw):
        fake_sw = make_sw("drawing")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]
        fake_sw.ActiveDoc.set_return("ActivateView", True)

        result = auto.select_view_by_name("Drawing View1")

        assert result["success"] is True
        assert result["data"]["view_name"] == "Drawing View1"
        fake_sw.call_log.assert_called_with("ActivateView", "Drawing View1")

    def test_unknown_view_name_returns_clear_error(self, make_sw):
        fake_sw = make_sw("drawing")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = auto.select_view_by_name("Nonexistent View")

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert "Nonexistent View" in result["message"]

    def test_requires_a_drawing_document(self, automation):
        result = automation.select_view_by_name("Drawing View1")

        assert result["success"] is False
        assert "Part" in result["message"]


class TestListViewEntities:
    def test_returns_coordinates_in_the_configured_unit(self, make_sw):
        # Deliberately a non-default unit (config default is "mm") -- a
        # hardcoded *1000 would pass a mm-only test but fail this one, so
        # this actually exercises set_units' effect on the conversion.
        fake_sw = make_sw("drawing")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]
        auto._units.default_unit = "inch"
        fake_sw.ActiveDoc.set_return("ActivateView", True)

        view = fake_sw.ActiveDoc.ActiveDrawingView
        vertex = fake_sw.new_object("vertex1")
        vertex.set_return("GetPoint", [0.0254, 0.0508, 0.0])  # meters
        edge = fake_sw.new_object("edge1")
        edge.set_return("GetStartPoint", [0.0254, 0.0254, 0.0])
        face = fake_sw.new_object("face1")
        face.set_return("GetBox", [0.0, 0.0, 0.0, 0.0508, 0.1016, 0.0])

        view.set_sequence("GetVisibleEntities2", [[edge], [face], [vertex]])

        result = auto.list_view_entities("Drawing View1")

        assert result["success"] is True
        entities = {e["kind"]: e for e in result["data"]["entities"]}
        assert entities["vertex"]["x"] == pytest.approx(1.0)
        assert entities["vertex"]["y"] == pytest.approx(2.0)
        assert entities["edge"]["x"] == pytest.approx(1.0)
        assert entities["edge"]["y"] == pytest.approx(1.0)
        assert entities["face"]["x"] == pytest.approx(1.0)
        assert entities["face"]["y"] == pytest.approx(2.0)

    def test_unknown_view_name_returns_clear_error(self, make_sw):
        fake_sw = make_sw("drawing")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = auto.list_view_entities("Nonexistent View")

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
