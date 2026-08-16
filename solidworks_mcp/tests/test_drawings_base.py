"""
Regression tests for solidworks_mcp.automation.drawings (DrawingOperations),
exercised through `SolidWorksAutomation` bound to the fake COM harness.
"""

from solidworks_mcp.automation import DrawingOperations, SolidWorksAutomation


class TestMixinWiring:
    def test_drawing_operations_is_in_mro(self):
        assert DrawingOperations in SolidWorksAutomation.__mro__


class TestGetDrawingDoc:
    def test_happy_path_on_drawing(self, make_sw):
        fake_sw = make_sw("drawing")
        auto = SolidWorksAutomation()
        connected = auto.connect()
        assert connected["success"], connected

        doc, err = auto.get_drawing_doc()

        assert err is None
        assert doc is fake_sw.ActiveDoc

    def test_error_result_when_active_doc_is_a_part(self, automation):
        doc, err = automation.get_drawing_doc()

        assert doc is None
        assert err is not None
        assert err["success"] is False
        assert "Part" in err["message"]

    def test_error_result_when_active_doc_is_an_assembly(self, make_sw):
        make_sw("assembly")
        auto = SolidWorksAutomation()
        connected = auto.connect()
        assert connected["success"], connected

        doc, err = auto.get_drawing_doc()

        assert doc is None
        assert err["success"] is False
        assert "Assembly" in err["message"]

    def test_error_result_when_no_active_doc(self, make_sw):
        fake_sw = make_sw("drawing")
        # Assigning the literal value (rather than scripting it) is how the
        # fake harness represents "no active document" -- see
        # testing/fake_com.py's module docstring, Limitations section.
        fake_sw.ActiveDoc = None

        auto = SolidWorksAutomation()
        connected = auto.connect()
        assert connected["success"], connected

        doc, err = auto.get_drawing_doc()

        assert doc is None
        assert err["error_name"] == "swNoActiveDocument"
