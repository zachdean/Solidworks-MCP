"""
Tool registry unit tests.
--------------------------
Exercises `solidworks_mcp.tools.registry` in isolation -- duplicate-name
registration, `dispatch()`/`build_tool_list()` plumbing, and the
`schema_from_signature()` adapter for `ComSignature.describe()`. Tests that
register tools do so against a monkeypatched, empty `_TOOLS`/`_ORDER` so
they don't pollute the real (process-global, import-time-populated) tool
registry that `solidworks_mcp.tools` and `server.py` share.
"""

import pytest

from solidworks_mcp.automation.com_params import ComSignature, Param, to_bool, to_meters
from solidworks_mcp.tools import registry as registry_module


@pytest.fixture
def empty_registry(monkeypatch):
    """Swap in a fresh, empty registry for the duration of the test."""
    monkeypatch.setattr(registry_module, "_TOOLS", {})
    monkeypatch.setattr(registry_module, "_ORDER", [])


def _dummy_schema():
    return {"type": "object", "properties": {}, "required": []}


class TestDuplicateRegistration:
    def test_registering_two_tools_with_the_same_name_raises_value_error(self, empty_registry):
        @registry_module.tool("dup_tool", "first registration", _dummy_schema())
        def handler_one(arguments):
            return {"success": True, "message": "one", "error_code": 0, "error_name": "swSuccess"}

        with pytest.raises(ValueError):
            @registry_module.tool("dup_tool", "second registration", _dummy_schema())
            def handler_two(arguments):
                return {"success": True, "message": "two", "error_code": 0, "error_name": "swSuccess"}

    def test_distinct_names_register_independently(self, empty_registry):
        @registry_module.tool("tool_a", "a", _dummy_schema())
        def handler_a(arguments):
            return {"success": True, "message": "a", "error_code": 0, "error_name": "swSuccess"}

        @registry_module.tool("tool_b", "b", _dummy_schema())
        def handler_b(arguments):
            return {"success": True, "message": "b", "error_code": 0, "error_name": "swSuccess"}

        names = {t.name for t in registry_module.build_tool_list()}
        assert names == {"tool_a", "tool_b"}


class TestDispatchAndBuildToolList:
    def test_dispatch_calls_the_registered_handler_with_arguments(self, empty_registry):
        seen = {}

        @registry_module.tool("echo_tool", "echoes its arguments", _dummy_schema())
        def echo(arguments):
            seen["arguments"] = arguments
            return {"success": True, "message": "ok", "error_code": 0, "error_name": "swSuccess"}

        result = registry_module.dispatch("echo_tool", {"x": 1})
        assert result["success"] is True
        assert seen["arguments"] == {"x": 1}

    def test_dispatch_unknown_name_raises_unknown_tool_error(self, empty_registry):
        with pytest.raises(registry_module.UnknownToolError):
            registry_module.dispatch("does_not_exist", {})

    def test_build_tool_list_preserves_registration_order(self, empty_registry):
        for name in ("first", "second", "third"):
            registry_module.tool(name, name, _dummy_schema())(lambda arguments: {})
        assert [t.name for t in registry_module.build_tool_list()] == ["first", "second", "third"]


class TestSchemaFromSignature:
    def test_wraps_describe_output_into_a_full_input_schema(self):
        sig = ComSignature("SetupSheet5", [
            Param("name"),
            Param("first_angle", True, to_bool),
            Param("depth", 10, to_meters),
        ])

        schema = registry_module.schema_from_signature(sig)

        assert schema["type"] == "object"
        assert set(schema["properties"]) == {"name", "first_angle", "depth"}
        assert schema["properties"]["first_angle"]["type"] == "boolean"
        assert schema["properties"]["first_angle"]["default"] is True
        assert schema["properties"]["depth"]["type"] == "number"
        # `name` has no default (REQUIRED sentinel) -> inferred as required.
        assert schema["required"] == ["name"]

    def test_required_can_be_overridden_explicitly(self):
        sig = ComSignature("Foo", [Param("a", 1), Param("b", 2)])
        schema = registry_module.schema_from_signature(sig, required=["b"])
        assert schema["required"] == ["b"]
