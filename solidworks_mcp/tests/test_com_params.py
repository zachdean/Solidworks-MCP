"""
Regression tests for solidworks_mcp.automation.com_params (ComSignature).
"""

import json

import pytest

from solidworks_mcp.automation.com_params import (
    ComSignature,
    Param,
    enum_to_int,
    to_bool,
    to_meters,
    to_optional_object,
    to_radians,
)
from solidworks_mcp.constants_drawing import SwDwgPaperSizes
from solidworks_mcp.testing.fake_backend import FakePythonCom
from solidworks_mcp.utils import UnitConverter


class TestBindOrdering:
    def test_returns_positional_tuple_in_declaration_order(self):
        sig = ComSignature("Foo", [Param("a"), Param("b"), Param("c")])

        args = sig.bind(c=3, a=1, b=2)

        assert args == (1, 2, 3)

    def test_single_param(self):
        sig = ComSignature("Foo", [Param("name")])

        assert sig.bind(name="Sheet1") == ("Sheet1",)


class TestDefaults:
    def test_omitted_kwarg_uses_default(self):
        sig = ComSignature("Foo", [Param("a"), Param("b", 42)])

        args = sig.bind(a=1)

        assert args == (1, 42)

    def test_explicit_kwarg_overrides_default(self):
        sig = ComSignature("Foo", [Param("a", 1), Param("b", 2)])

        args = sig.bind(a=1, b=99)

        assert args == (1, 99)

    def test_missing_required_param_raises(self):
        sig = ComSignature("Foo", [Param("a"), Param("b", 2)])

        with pytest.raises(TypeError, match="missing required parameter"):
            sig.bind(b=2)

    def test_missing_required_error_names_the_param(self):
        sig = ComSignature("Foo", [Param("name"), Param("scale", 1.0)])

        with pytest.raises(TypeError, match="name"):
            sig.bind()

    def test_all_params_default_binds_with_no_kwargs(self):
        sig = ComSignature("Foo", [Param("a", 1), Param("b", 2)])

        assert sig.bind() == (1, 2)


class TestConverters:
    def test_identity_default_converter_passes_through(self):
        sig = ComSignature("Foo", [Param("name")])

        assert sig.bind(name="Sheet1") == ("Sheet1",)

    def test_to_meters_converts_using_supplied_units(self):
        sig = ComSignature("Foo", [Param("depth", converter=to_meters)])
        units = UnitConverter("mm")

        args = sig.bind(units=units, depth=50)

        assert args == (0.05,)

    def test_to_meters_applies_to_filled_in_default(self):
        sig = ComSignature("Foo", [Param("depth", 25, to_meters)])
        units = UnitConverter("mm")

        args = sig.bind(units=units)

        assert args[0] == pytest.approx(0.025)

    def test_to_meters_respects_inch_units(self):
        sig = ComSignature("Foo", [Param("depth", converter=to_meters)])
        units = UnitConverter("inch")

        args = sig.bind(units=units, depth=1)

        assert args[0] == pytest.approx(0.0254)

    def test_to_meters_without_units_raises_instead_of_guessing(self):
        sig = ComSignature("Foo", [Param("depth", converter=to_meters)])

        with pytest.raises(ValueError, match="UnitConverter"):
            sig.bind(depth=50)

    def test_to_radians_converts_degrees(self):
        sig = ComSignature("Foo", [Param("angle", converter=to_radians)])

        args = sig.bind(angle=180)

        assert args[0] == pytest.approx(3.141592653589793)

    def test_enum_to_int_coerces_intenum_member(self):
        sig = ComSignature("Foo", [Param("paper", converter=enum_to_int)])

        args = sig.bind(paper=SwDwgPaperSizes.swDwgPaperA4size)

        assert args == (6,)
        assert type(args[0]) is int

    def test_enum_to_int_coerces_plain_int(self):
        sig = ComSignature("Foo", [Param("paper", converter=enum_to_int)])

        assert sig.bind(paper=6) == (6,)

    def test_to_bool_coerces_truthy_and_falsy(self):
        sig = ComSignature("Foo", [Param("flag", converter=to_bool)])

        assert sig.bind(flag=1) == (True,)
        assert sig.bind(flag=0) == (False,)
        assert sig.bind(flag="") == (False,)

    def test_to_optional_object_turns_none_into_a_null_vt_dispatch(self, fake_sw):
        """A bare Python `None` in an optional-object COM argument is a type
        mismatch on a real connection (the SW 2025 failure `save_document`
        documents working around); COM wants a null `VT_DISPATCH` VARIANT."""
        sig = ComSignature("SelectByID2", [
            Param("callout", None, to_optional_object)])

        (callout,) = sig.bind()

        assert callout.vt == FakePythonCom.VT_DISPATCH
        assert callout.value is None

    def test_to_optional_object_passes_a_real_pointer_through(self, fake_sw):
        sig = ComSignature("SelectByID2", [
            Param("callout", None, to_optional_object)])
        pointer = fake_sw.new_object("callout")

        assert sig.bind(callout=pointer) == (pointer,)


class TestUnknownKwarg:
    def test_unknown_kwarg_raises_type_error(self):
        sig = ComSignature("SetupSheet5", [Param("name"), Param("scale", 1.0)])

        with pytest.raises(TypeError, match="unknown parameter"):
            sig.bind(name="Sheet1", scael=2.0)

    def test_unknown_kwarg_error_names_the_typo(self):
        sig = ComSignature("SetupSheet5", [Param("name")])

        with pytest.raises(TypeError, match="scael"):
            sig.bind(name="Sheet1", scael=2.0)

    def test_unknown_kwarg_checked_before_missing_required(self):
        sig = ComSignature("Foo", [Param("a")])

        with pytest.raises(TypeError, match="unknown parameter"):
            sig.bind(b=1)


class TestConstruction:
    def test_duplicate_param_names_raise_on_construction(self):
        with pytest.raises(ValueError, match="duplicate"):
            ComSignature("Foo", [Param("a"), Param("a")])


class TestDescribe:
    def test_describe_is_keyed_by_param_name(self):
        sig = ComSignature("Foo", [Param("name"), Param("depth", 10, to_meters)])

        schema = sig.describe()

        assert set(schema.keys()) == {"name", "depth"}

    def test_describe_infers_type_from_converter(self):
        sig = ComSignature(
            "Foo",
            [
                Param("depth", 10, to_meters),
                Param("angle", 0, to_radians),
                Param("paper", 6, enum_to_int),
                Param("flag", True, to_bool),
            ],
        )

        schema = sig.describe()

        assert schema["depth"]["type"] == "number"
        assert schema["angle"]["type"] == "number"
        assert schema["paper"]["type"] == "integer"
        assert schema["flag"]["type"] == "boolean"

    def test_describe_infers_type_from_default_for_identity_converter(self):
        sig = ComSignature("Foo", [Param("name", "Sheet1"), Param("count", 3)])

        schema = sig.describe()

        assert schema["name"]["type"] == "string"
        assert schema["count"]["type"] == "integer"

    def test_describe_includes_default_when_present(self):
        sig = ComSignature("Foo", [Param("scale", 1.0), Param("name")])

        schema = sig.describe()

        assert schema["scale"]["default"] == 1.0
        assert "default" not in schema["name"]

    def test_describe_output_is_valid_mcp_properties_block(self):
        sig = ComSignature(
            "SetupSheet5",
            [
                Param("name"),
                Param("template", SwDwgPaperSizes.swDwgPaperA4size, enum_to_int),
                Param("width", 0.2794, to_meters),
                Param("first_angle", True, to_bool),
            ],
        )

        schema = sig.describe()

        # Round-trips through JSON exactly as an MCP inputSchema properties
        # block would -- including the IntEnum default "template" declares
        # (SwDwgPaperSizes members compare equal to their int value, so the
        # round-tripped plain int still matches).
        assert json.loads(json.dumps(schema)) == schema

        assert set(schema.keys()) == {"name", "template", "width", "first_angle"}
        for prop in schema.values():
            assert isinstance(prop, dict)
            if "type" in prop:
                assert prop["type"] in {
                    "string", "number", "integer", "boolean", "array", "object",
                }
