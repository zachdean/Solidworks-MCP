"""
Regression tests for the surface finish and weld symbol tools
(solidworks_mcp/tools/drawing_annotations.py's add_surface_finish,
add_weld_symbol), dispatched through the real `solidworks_mcp.tools`
registry (`dispatch()`) against the fake COM harness -- same convention as
test_tools_gdt.py: exercise both the registry wiring and the
`DrawingOperations` automation methods, asserting COM call order/args
against the fake's call log.
"""

import pytest

from solidworks_mcp.automation.drawings import _WELD_SYMBOL_ALIASES, _WELD_SYMBOL_CODES
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_gdt.py's `tool_sw`, connecting the
    shared `tools.sw_automation` singleton to a fresh fake
    `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _prep_view(fake_sw):
    """Common setup every happy/near-happy-path test needs: ActivateView and
    SelectByID2 both scripted to succeed."""
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)


def _entity(kind="edge", x=1, y=2, z=0):
    return {"kind": kind, "x": x, "y": y, "z": z}


def _sf_symbol(fake_sw, obj_id, name="SFSymbol1", set_leader3_status=0):
    """A fake `ISFSymbol` -> `GetAnnotation` -> `IAnnotation` chain --
    `SetLeader3` scripted to succeed (status 0)."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.SetLeader3", set_leader3_status)

    sf = fake_sw.new_object(obj_id)
    sf.set_return(f"{obj_id}.GetAnnotation", ann)
    return sf, ann


def _weld_symbol(fake_sw, obj_id, name="WeldSymbol1"):
    """A fake `IWeldSymbol` -> `GetAnnotation` -> `IAnnotation` chain --
    every content setter and `SetPosition2` scripted to succeed."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)

    weld = fake_sw.new_object(obj_id)
    weld.set_return(f"{obj_id}.GetAnnotation", ann)
    weld.set_return(f"{obj_id}.SetText", True)
    weld.set_return(f"{obj_id}.SetFieldWeld", True)
    weld.set_return(f"{obj_id}.SetPeripheral", True)
    weld.set_return(f"{obj_id}.SetSymmetric", True)
    weld.set_return(f"{obj_id}.SetProcess", True)
    return weld, ann


class TestAddSurfaceFinish:
    def test_basic_symbol_defaults(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 10, "y": 20,
        })

        assert result["success"] is True, result
        assert result["data"]["name"] == "SFSymbol1"
        fake_sw.call_log.assert_called_with(
            "InsertSurfaceFinishSymbol3",
            0, 1, pytest.approx(0.01), pytest.approx(0.02), 0.0, 0, 0,
            "", "", "", "", "", "", "",
        )

    @pytest.mark.parametrize("symbol_type,expected", [
        ("basic", 0),
        ("machining_required", 9),
        ("machining_prohibited", 2),
    ])
    def test_symbol_type_maps_to_dossier_enum(self, tool_sw, symbol_type, expected):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol_type": symbol_type,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("InsertSurfaceFinishSymbol3", 0) == expected

    def test_unknown_symbol_type_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol_type": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertSurfaceFinishSymbol3")

    @pytest.mark.parametrize("lay_direction,expected", [
        ("circular", 1),
        ("cross", 2),
        ("multi_directional", 3),
        ("parallel", 4),
        ("perpendicular", 5),
        ("radial", 6),
        ("particulate", 7),
    ])
    def test_lay_direction_maps_to_dossier_enum(self, tool_sw, lay_direction, expected):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "lay_direction": lay_direction,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("InsertSurfaceFinishSymbol3", 5) == expected

    def test_omitted_lay_direction_defaults_to_none(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("InsertSurfaceFinishSymbol3", 5) == 0

    def test_unknown_lay_direction_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "lay_direction": "diagonal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertSurfaceFinishSymbol3")

    def test_roughness_values_reach_com_as_display_strings_not_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "roughness_max": 3.2, "roughness_min": 1.6,
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        # MaxRoughness/MinRoughness are indices 11/12 -- plain display text,
        # NOT converted via self._units.to_meters (would be ~0.0000032).
        assert log.arg_of("InsertSurfaceFinishSymbol3", 11) == "3.2"
        assert log.arg_of("InsertSurfaceFinishSymbol3", 12) == "1.6"

    def test_integral_roughness_formats_without_trailing_zero(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "roughness_max": 5,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("InsertSurfaceFinishSymbol3", 11) == "5"

    def test_inverted_roughness_range_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "roughness_max": 1.0, "roughness_min": 2.0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertSurfaceFinishSymbol3")

    def test_machining_allowance_and_production_method_pass_through(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "machining_allowance": "0.5mm", "production_method": "Grind",
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.arg_of("InsertSurfaceFinishSymbol3", 7) == "0.5mm"
        assert log.arg_of("InsertSurfaceFinishSymbol3", 9) == "Grind"

    def test_all_around_sets_leader3_with_bent_all_around_style(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf, _ann = _sf_symbol(fake_sw, "sf1")
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "all_around": True,
        })

        assert result["success"] is True, result
        # LeaderStyle=swBENT(2), LeaderSide=default(0), SmartArrowHeadStyle=True,
        # Perpendicular=False, AllAround=True, Dashed=False.
        fake_sw.call_log.assert_called_with("SetLeader3", 2, 0, True, False, True, False)

    def test_all_around_without_annotation_wrapper_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        sf = fake_sw.new_object("sf1")
        sf.set_return("sf1.GetAnnotation", None)
        fake_sw.ActiveDoc.Extension.set_return("InsertSurfaceFinishSymbol3", sf)

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "all_around": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("SetLeader3")

    def test_unknown_entity_kind_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_surface_finish", {
            "view_name": "Drawing View1", "entity": _entity(kind="surface"), "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertSurfaceFinishSymbol3")


class TestAddWeldSymbol:
    def test_default_fillet_symbol(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 10, "y": 20,
        })

        assert result["success"] is True, result
        assert result["data"]["name"] == "WeldSymbol1"
        log = fake_sw.call_log
        log.assert_called_with("SetText", True, "", "FILL", "", "", 1)
        log.assert_called_with(
            "SetPosition2", pytest.approx(0.01), pytest.approx(0.02), 0.0,
        )

    def test_expected_alias_table_resolves_to_dossier_codes(self):
        # AC1: every friendly alias this dossier documents maps to a code in
        # the fixed 16-member ISO list -- a regression guard, not a tautology,
        # since a typo'd alias target would fail this without ever reaching a
        # dispatch() call.
        assert set(_WELD_SYMBOL_ALIASES.values()) <= _WELD_SYMBOL_CODES

    @pytest.mark.parametrize("alias,code", sorted(_WELD_SYMBOL_ALIASES.items()))
    def test_alias_maps_to_dossier_code(self, tool_sw, alias, code):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol": alias,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetText", 2) == code

    def test_raw_iso_code_accepted_case_insensitively(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol": "busvbr",
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetText", 2) == "BUSVBR"

    def test_unknown_symbol_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertWeldSymbol3")

    def test_length_without_pitch_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "length": 50,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertWeldSymbol3")

    def test_pitch_without_length_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "pitch": 100,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertWeldSymbol3")

    def test_size_sets_left_text(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "size": 6,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetText", 1) == "6"

    def test_length_and_pitch_set_right_text_as_length_dash_pitch(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "length": 50, "pitch": 100,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetText", 3) == "50-100"

    @pytest.mark.parametrize("contour,expected", [
        ("none", 1), ("flat", 2), ("convex", 3), ("concave", 4),
    ])
    def test_contour_maps_to_dossier_enum(self, tool_sw, contour, expected):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "contour": contour,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetText", 5) == expected

    def test_unknown_contour_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "contour": "wavy",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertWeldSymbol3")

    def test_other_side_symbol_sets_second_settext_call_with_top_false(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "symbol": "fillet", "other_side_symbol": "v_groove",
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        calls = log.calls_to("SetText")
        assert len(calls) == 2
        # Arrow side ("this side"): Top=True, Symbol="FILL".
        assert calls[0].args[0] is True
        assert calls[0].args[2] == "FILL"
        # Other side: Top=False, Symbol="BUSV".
        assert calls[1].args[0] is False
        assert calls[1].args[2] == "BUSV"

    def test_no_other_side_symbol_makes_only_one_settext_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert len(fake_sw.call_log.calls_to("SetText")) == 1

    def test_field_weld_calls_set_field_weld_up(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "field_weld": True,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetFieldWeld", 2)

    def test_field_weld_false_skips_set_field_weld(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("SetFieldWeld")

    def test_all_around_calls_set_peripheral_true(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "all_around": True,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetPeripheral", True)

    def test_both_sides_calls_set_symmetric(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "both_sides": True,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetSymmetric", 1)

    def test_both_sides_false_skips_set_symmetric(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("SetSymmetric")

    def test_tail_text_calls_set_process(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        weld, _ann = _weld_symbol(fake_sw, "w1")
        fake_sw.ActiveDoc.set_return("InsertWeldSymbol3", weld)

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "tail_text": "Per WPS-12",
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetProcess", True, "Per WPS-12", False)

    def test_size_must_be_non_negative(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_weld_symbol", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
            "size": -1,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertWeldSymbol3")
