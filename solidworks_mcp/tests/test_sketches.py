"""
Regression tests for solidworks_mcp.automation.sketches (SketchOperations),
exercised through `SolidWorksAutomation` bound to the fake COM harness.
"""

import pytest


class TestCreateSketch:
    def test_happy_path(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.Extension.set_return("SelectByID2", True)

        result = automation.create_sketch("Front")

        assert result["success"] is True
        assert result["data"]["plane"] == "Front Plane"
        assert fake_sw.call_log.arg_of("SelectByID2", 0) == "Front Plane"
        assert fake_sw.call_log.arg_of("SelectByID2", 1) == "PLANE"
        assert fake_sw.call_log.ordered_names() == ["SelectByID2", "InsertSketch2"]

    def test_select_by_id_fails(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.Extension.set_return("SelectByID2", False)

        result = automation.create_sketch("Top")

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"


class TestDrawCircle:
    def test_happy_path_converts_mm_to_meters(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.SketchManager.set_return("CreateCircle", object())

        result = automation.draw_circle(0, 0, 25, unit="mm")

        assert result["success"] is True
        # Center point (0, 0) and the edge point x = center_x + radius, in meters.
        assert fake_sw.call_log.arg_of("CreateCircle", 0) == pytest.approx(0.0)
        assert fake_sw.call_log.arg_of("CreateCircle", 3) == pytest.approx(0.025)
        assert result["data"] == {
            "radius": 25, "unit": "mm", "center_x": 0, "center_y": 0
        }

    def test_com_returns_none(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.SketchManager.set_return("CreateCircle", None)

        result = automation.draw_circle(0, 0, 25, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swSketchError"


class TestDrawRectangle:
    def test_happy_path_converts_mm_to_meters(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.SketchManager.set_return("CreateCornerRectangle", object())

        result = automation.draw_rectangle(-50, -25, 50, 25, unit="mm")

        assert result["success"] is True
        assert fake_sw.call_log.arg_of("CreateCornerRectangle", 0) == pytest.approx(-0.05)
        assert fake_sw.call_log.arg_of("CreateCornerRectangle", 1) == pytest.approx(-0.025)
        assert fake_sw.call_log.arg_of("CreateCornerRectangle", 3) == pytest.approx(0.05)
        assert fake_sw.call_log.arg_of("CreateCornerRectangle", 4) == pytest.approx(0.025)
        assert result["data"] == {"width": 100, "height": 50, "unit": "mm"}

    def test_com_returns_none(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.SketchManager.set_return("CreateCornerRectangle", None)

        result = automation.draw_rectangle(-50, -25, 50, 25, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swSketchError"
