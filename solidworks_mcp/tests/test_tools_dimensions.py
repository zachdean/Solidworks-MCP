"""
Regression tests for the dimension tools (solidworks_mcp/tools/
drawing_annotations.py's add_dimension, add_ordinate_dimensions,
set_dimension_value, set_dimension_text, autodimension_view), dispatched
through the real `solidworks_mcp.tools` registry (`dispatch()`) against the
fake COM harness -- same convention as test_tools_model_items.py and
test_tools_section_view.py: exercise both the registry wiring and the
`DrawingOperations` automation methods, asserting COM call order/args
against the fake's call log.
"""

import pytest

from solidworks_mcp.tools import dispatch, sw_automation


def _prep_view(fake_sw):
    """Common setup every happy/near-happy-path test needs: ActivateView and
    SelectByID2 both scripted to succeed."""
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)


def _entity(kind, x, y, z=0):
    return {"kind": kind, "x": x, "y": y, "z": z}


def _dimension(fake_sw, obj_id, full_name="D1@Sketch1@Part1.SLDPRT", value_m=0.05):
    """A fake `IDisplayDimension` -> `GetDimension2` -> `IDimension` chain,
    with `FullName`/`GetSystemValue3` scripted so `add_dimension`'s
    name/value read-back gets real Python values back (per fake_com.py's own
    module docstring: a bare property read needs an explicit script to
    survive as more than a dual-purpose wrapper; `FullName` is read via
    `_read_prop`, which resolves it either way by calling it if callable)."""
    idim = fake_sw.new_object(f"{obj_id}.idim")
    idim.set_return(f"{obj_id}.idim.FullName", full_name)
    idim.set_return(f"{obj_id}.idim.GetSystemValue3", value_m)
    display_dim = fake_sw.new_object(obj_id)
    display_dim.set_return(f"{obj_id}.GetDimension2", idim)
    return display_dim, idim


class TestAddDimensionEntityValidation:
    """Acceptance criteria: fewer entities than the type requires errors
    before touching COM."""

    def test_unknown_dimension_type_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "bogus" in result["message"]
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("SelectByID2")

    def test_horizontal_with_one_entity_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("vertex", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "horizontal",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        log = fake_sw.call_log
        assert not log.calls_to("ActivateView")
        assert not log.calls_to("SelectByID2")
        assert not log.calls_to("AddHorizontalDimension2")

    def test_angular_with_one_entity_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "angular",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_empty_entities_rejects(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1", "entities": [], "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_non_list_entities_rejects_instead_of_raising(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1", "entities": "not-a-list", "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_entity_with_unknown_kind_rejects(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [{"kind": "surface", "x": 1, "y": 2}],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_entity_missing_numeric_coordinates_rejects(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [{"kind": "edge", "x": "bad", "y": 2}],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_non_numeric_x_rejects_without_com_call(self, tool_sw):
        """A non-numeric placement x/y must not reach `self._units.to_meters`
        inside the tool -- that would raise (ValueError/TypeError) straight
        out of the tool boundary, violating "never raise out of a tool"."""
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": "fifty", "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_non_numeric_y_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": None, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")


class TestAddDimensionTypeMapping:
    """All 6 dimension types map to the dossier-documented enum values and
    dispatch to the correct COM creation call."""

    def test_smart_uses_add_dimension2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2), _entity("edge", 3, 4)],
            "x": 0, "y": 0, "dimension_type": "smart",
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("AddDimension2")
        assert not fake_sw.call_log.calls_to("AddHorizontalDimension2")
        assert not fake_sw.call_log.calls_to("AddVerticalDimension2")

    def test_horizontal_uses_add_horizontal_dimension2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddHorizontalDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("vertex", 1, 2), _entity("vertex", 3, 2)],
            "x": 0, "y": 0, "dimension_type": "horizontal",
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("AddHorizontalDimension2")
        assert not fake_sw.call_log.calls_to("AddDimension2")

    def test_vertical_uses_add_vertical_dimension2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddVerticalDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("vertex", 1, 2), _entity("vertex", 1, 5)],
            "x": 0, "y": 0, "dimension_type": "vertical",
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.calls_to("AddVerticalDimension2")
        assert not fake_sw.call_log.calls_to("AddDimension2")

    @pytest.mark.parametrize("dimension_type,expected_enum", [
        ("smart", 0), ("horizontal", 11), ("vertical", 12),
        ("radial", 5), ("diameter", 6), ("angular", 3),
    ])
    def test_dim_type_enum_matches_dossier_swdimensiontype(
        self, tool_sw, dimension_type, expected_enum,
    ):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)
        fake_sw.ActiveDoc.set_return("AddHorizontalDimension2", display_dim)
        fake_sw.ActiveDoc.set_return("AddVerticalDimension2", display_dim)

        min_entities = 2 if dimension_type in ("horizontal", "vertical", "angular") else 1
        entities = [_entity("edge", i, i) for i in range(min_entities)]

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1", "entities": entities,
            "x": 0, "y": 0, "dimension_type": dimension_type,
        })

        assert result["success"] is True, result
        assert result["data"]["dim_type_enum"] == expected_enum

    def test_radial_forces_diametric_false(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is True, result
        assert display_dim.Diametric is False

    def test_diameter_forces_diametric_true_and_redraws(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "diameter",
        })

        assert result["success"] is True, result
        assert display_dim.Diametric is True
        assert fake_sw.call_log.calls_to("GraphicsRedraw2")

    def test_smart_and_angular_do_not_touch_diametric(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2), _entity("edge", 3, 4)],
            "x": 0, "y": 0, "dimension_type": "angular",
        })

        assert not fake_sw.call_log.calls_to("GraphicsRedraw2")

    def test_type_code_read_back_via_type2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        display_dim.set_return("d1.Type2", 6)  # swDiameterDimension
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "diameter",
        })

        assert result["success"] is True, result
        assert result["data"]["type_code"] == 6


class TestAddDimensionSelectionOrdering:
    def test_selects_view_then_entities_then_creates(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2), _entity("edge", 3, 4)],
            "x": 0, "y": 0, "dimension_type": "smart",
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("SelectByID2")
            < names.index("AddDimension2")
        ), names

    def test_first_entity_clears_selection_rest_append(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2), _entity("edge", 3, 4), _entity("vertex", 5, 6)],
            "x": 0, "y": 0, "dimension_type": "angular",
        })

        select_calls = fake_sw.call_log.calls_to("SelectByID2")
        assert len(select_calls) == 3
        # append=False, mark=0 for the first entity; append=True after.
        assert select_calls[0].args[5] is False
        assert select_calls[0].args[6] == 0
        assert select_calls[1].args[5] is True
        assert select_calls[1].args[6] == 1
        assert select_calls[2].args[5] is True
        assert select_calls[2].args[6] == 2
        assert select_calls[0].args[1] == "EDGE"
        assert select_calls[2].args[1] == "VERTEX"

    def test_clear_select_act_clear_ordering(self, tool_sw):
        """Acceptance criteria: entities are selected via the `selected(...)`
        context manager, asserted by clear-select-act-clear ordering in the
        call log. The first (non-appending) `selected()` clears on entry, the
        appending ones suppress both clears, and the outer block's exit
        performs the one closing clear -- exactly two `ClearSelection2` calls
        bracketing the three `SelectByID2` calls and the create call."""
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2), _entity("edge", 3, 4), _entity("vertex", 5, 6)],
            "x": 0, "y": 0, "dimension_type": "angular",
        })

        names = fake_sw.call_log.ordered_names()
        relevant = [n for n in names if n in ("ClearSelection2", "SelectByID2", "AddDimension2")]
        assert relevant == [
            "ClearSelection2", "SelectByID2", "SelectByID2", "SelectByID2",
            "AddDimension2", "ClearSelection2",
        ], names
        assert len(fake_sw.call_log.calls_to("ClearSelection2")) == 2

    def test_entity_selection_failure_fails_without_creating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("AddDimension2")

    def test_activate_view_failure_fails_without_selecting_entities(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert not fake_sw.call_log.calls_to("SelectByID2")
        assert not fake_sw.call_log.calls_to("AddDimension2")


class TestAddDimensionUnitConversion:
    def test_placement_xy_converted_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 50, "y": 25, "dimension_type": "radial",
        })

        call = fake_sw.call_log.calls_to("AddDimension2")[0]
        assert call.args[0] == pytest.approx(0.05)
        assert call.args[1] == pytest.approx(0.025)
        assert call.args[2] == pytest.approx(0.0)

    def test_entity_coordinates_converted_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        display_dim, _idim = _dimension(fake_sw, "d1")
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 10, 20, 0)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        select_call = fake_sw.call_log.calls_to("SelectByID2")[0]
        assert select_call.args[2] == pytest.approx(0.010)
        assert select_call.args[3] == pytest.approx(0.020)

    def test_returned_value_converted_back_to_user_units(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        _prep_view(fake_sw)
        # 0.05 m -> 50 mm
        display_dim, _idim = _dimension(fake_sw, "d1", value_m=0.05)
        fake_sw.ActiveDoc.set_return("AddDimension2", display_dim)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is True, result
        assert result["data"]["value"] == pytest.approx(50.0)
        assert result["data"]["name"] == "D1@Sketch1@Part1.SLDPRT"


class TestAddDimensionErrorPaths:
    def test_com_exception_fails_the_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_raises("AddDimension2", RuntimeError("boom"))

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_none_returned_fails_the_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.set_return("AddDimension2", None)

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("add_dimension", {
            "view_name": "Drawing View1",
            "entities": [_entity("edge", 1, 2)],
            "x": 0, "y": 0, "dimension_type": "radial",
        })

        assert result["success"] is False
        assert "Part" in result["message"]


class TestAddOrdinateDimensions:
    def test_happy_path_selects_origin_then_entities_then_creates(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 0)  # Success

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0), _entity("vertex", 20, 0)],
            "x": 0, "y": -5, "direction": "horizontal",
        })

        assert result["success"] is True, result
        assert result["data"]["status"] == "swCreateOrdDimErr_Success"
        select_calls = fake_sw.call_log.calls_to("SelectByID2")
        assert len(select_calls) == 3
        assert select_calls[0].args[5] is False  # origin: append=False
        assert select_calls[1].args[5] is True
        assert select_calls[2].args[5] is True
        names = fake_sw.call_log.ordered_names()
        assert (
            names.index("ActivateView") < names.index("SelectByID2")
            < names.index("AddOrdinateDimension")
        ), names

    def test_clear_select_act_clear_ordering(self, tool_sw):
        """Same clear-select-act-clear shape as add_dimension's own test,
        for the origin + 2 member entities (3 selections total)."""
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 0)

        dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0), _entity("vertex", 20, 0)],
            "x": 0, "y": 0,
        })

        names = fake_sw.call_log.ordered_names()
        relevant = [
            n for n in names if n in ("ClearSelection2", "SelectByID2", "AddOrdinateDimension")
        ]
        assert relevant == [
            "ClearSelection2", "SelectByID2", "SelectByID2", "SelectByID2",
            "AddOrdinateDimension", "ClearSelection2",
        ], names
        assert len(fake_sw.call_log.calls_to("ClearSelection2")) == 2

    def test_setpickmode_called_on_success(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 0)

        dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert fake_sw.call_log.calls_to("SetPickMode")

    def test_setpickmode_called_on_com_status_failure(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 3)  # GenBadSel

        dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert fake_sw.call_log.calls_to("SetPickMode")

    def test_setpickmode_called_even_when_com_call_raises(self, tool_sw):
        """The bug this regression-tests: SetPickMode used to live after the
        `with ExitStack()` block, so an exception from AddOrdinateDimension
        returned early and skipped it, leaving the document in
        ordinate-group-building mode."""
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_raises("AddOrdinateDimension", RuntimeError("boom"))

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert fake_sw.call_log.calls_to("SetPickMode")

    @pytest.mark.parametrize("direction,expected", [
        ("auto", 1), ("vertical", 2), ("horizontal", 3), ("angular", 4),
    ])
    def test_direction_maps_to_swaddordinatedims_e(self, tool_sw, direction, expected):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 0)

        dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0, "direction": direction,
        })

        call = fake_sw.call_log.calls_to("AddOrdinateDimension")[0]
        assert call.args[0] == expected

    def test_unknown_direction_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0, "direction": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_empty_entities_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [], "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_invalid_origin_entity_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": {"kind": "bogus", "x": 0, "y": 0},
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_non_numeric_xy_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": "zero", "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("ActivateView")

    def test_com_status_failure_fails_the_result_naming_status(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_return("AddOrdinateDimension", 3)  # GenBadSel

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "swCreateOrdDimErr_GenBadSel" in result["message"]

    def test_com_exception_fails_the_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        fake_sw.ActiveDoc.Extension.set_raises("AddOrdinateDimension", RuntimeError("boom"))

        result = dispatch("add_ordinate_dimensions", {
            "view_name": "Drawing View1",
            "origin_entity": _entity("vertex", 0, 0),
            "entities": [_entity("vertex", 10, 0)],
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestSetDimensionValue:
    def test_happy_path_converts_to_meters_and_reads_back_user_units(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        idim = fake_sw.new_object("idim")
        idim.set_return("idim.SetSystemValue3", 0)  # swSetValue_Successful
        idim.set_return("idim.GetSystemValue3", 0.075)  # 75mm read back
        display_dim = fake_sw.new_object("display_dim")
        display_dim.set_return("display_dim.GetDimension2", idim)
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        result = dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": 75,
        })

        assert result["success"] is True, result
        assert result["data"]["value"] == pytest.approx(75.0)
        set_call = fake_sw.call_log.calls_to("SetSystemValue3")[0]
        assert set_call.args[0] == pytest.approx(0.075)

    def test_selects_dimension_by_name_and_type(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        idim = fake_sw.new_object("idim")
        idim.set_return("idim.SetSystemValue3", 0)
        idim.set_return("idim.GetSystemValue3", 0.01)
        display_dim = fake_sw.new_object("display_dim")
        display_dim.set_return("display_dim.GetDimension2", idim)
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": 10,
        })

        select_call = fake_sw.call_log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "D1@Sketch1@Part1.SLDPRT"
        assert select_call.args[1] == "DIMENSION"

    def test_non_numeric_value_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": "ten",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_selection_failure_fails_without_setting(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("SetSystemValue3")

    def test_com_status_failure_names_the_reason(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        idim = fake_sw.new_object("idim")
        idim.set_return("idim.SetSystemValue3", 3)  # swSetValue_DrivenDimension
        display_dim = fake_sw.new_object("display_dim")
        display_dim.set_return("display_dim.GetDimension2", idim)
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        result = dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "swSetValue_DrivenDimension" in result["message"]

    def test_no_selected_object_fails_cleanly(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", None)

        result = dispatch("set_dimension_value", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "value": 10,
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"


class TestSetDimensionText:
    def test_prefix_and_suffix_use_the_correct_whichtext_codes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        display_dim = fake_sw.new_object("display_dim")
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        result = dispatch("set_dimension_text", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT",
            "prefix": "QTY: ", "suffix": " TYP",
        })

        assert result["success"] is True, result
        set_text_calls = fake_sw.call_log.calls_to("SetText")
        assert (1, "QTY: ") in [(c.args[0], c.args[1]) for c in set_text_calls]
        assert (2, " TYP") in [(c.args[0], c.args[1]) for c in set_text_calls]

    def test_override_uses_whichtext_all(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        display_dim = fake_sw.new_object("display_dim")
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        dispatch("set_dimension_text", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "override": "REF",
        })

        call = fake_sw.call_log.calls_to("SetText")[0]
        assert call.args == (0, "REF")

    def test_no_fields_given_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_dimension_text", {"dimension_name": "D1@Sketch1@Part1.SLDPRT"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_calls_graphics_redraw_after_updating(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        display_dim = fake_sw.new_object("display_dim")
        fake_sw.ActiveDoc.SelectionManager.set_return("GetSelectedObject6", display_dim)

        dispatch("set_dimension_text", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "prefix": "X",
        })

        assert fake_sw.call_log.calls_to("GraphicsRedraw2")

    def test_selection_failure_fails_without_setting_text(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("set_dimension_text", {
            "dimension_name": "D1@Sketch1@Part1.SLDPRT", "prefix": "X",
        })

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("SetText")


class TestAutodimensionView:
    def test_happy_path_selects_view_then_calls_autodimension(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("AutoDimension", 0)  # swAutodimStatusSuccess

        result = dispatch("autodimension_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("AutoDimension")
        select_call = fake_sw.call_log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

    def test_default_args_map_to_baseline_all_above_left(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("AutoDimension", 0)

        dispatch("autodimension_view", {"view_name": "Drawing View1"})

        call = fake_sw.call_log.calls_to("AutoDimension")[0]
        # EntitiesToDimension=swAutodimEntitiesAll(1), HorizontalScheme=
        # swAutodimSchemeBaseline(1), HorizontalPlacement=Above(1),
        # VerticalScheme=Baseline(1), VerticalPlacement=Left(-1).
        assert call.args == (1, 1, 1, 1, -1)

    def test_scheme_and_placement_overrides(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("AutoDimension", 0)

        dispatch("autodimension_view", {
            "view_name": "Drawing View1", "scheme": "chain",
            "horizontal_placement": "below", "vertical_placement": "right",
        })

        call = fake_sw.call_log.calls_to("AutoDimension")[0]
        # chain=3, below=-1, right=1
        assert call.args == (1, 3, -1, 3, 1)

    def test_unknown_scheme_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("autodimension_view", {
            "view_name": "Drawing View1", "scheme": "centerline",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_unknown_entities_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("autodimension_view", {
            "view_name": "Drawing View1", "entities": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_unknown_horizontal_placement_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("autodimension_view", {
            "view_name": "Drawing View1", "horizontal_placement": "center",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_unknown_vertical_placement_rejects(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("autodimension_view", {
            "view_name": "Drawing View1", "vertical_placement": "center",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_com_status_failure_names_the_reason(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("AutoDimension", 8)  # swAutodimStatusNoEntities

        result = dispatch("autodimension_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "swAutodimStatusNoEntities" in result["message"]

    def test_view_selection_failure_fails_without_calling_autodimension(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("autodimension_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swSelectionError"
        assert not fake_sw.call_log.calls_to("AutoDimension")

    def test_com_exception_fails_the_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_raises("AutoDimension", RuntimeError("boom"))

        result = dispatch("autodimension_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
