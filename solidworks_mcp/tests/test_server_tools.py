"""
list_tools() / dispatch() parity + registry completeness regression test.
---------------------------------------------------------------------------
`server.py` used to declare every tool twice: once as a `Tool` in
`list_tools()` (name, description, schema) and once as a branch of an
`if/elif` chain in `call_tool()`. Nothing enforced the two stayed in sync --
it was easy to add/rename a tool in one and forget the other.

Since sw-a59.4, both `list_tools()` and `call_tool()` are driven by the same
`solidworks_mcp.tools` registry (`tools/registry.py`), so that particular
drift is no longer structurally possible -- there is exactly one place a
tool is declared. This test keeps a belt-and-suspenders parity check (in
case a future change reintroduces two sources of truth) and adds the
registry-completeness checks a single declarative source makes easy to
enforce: every registered tool must have a real description and a valid
`inputSchema`, and `call_tool()` must not regress back to a hand-written
dispatch chain.
"""

import ast
import asyncio
import inspect

import pytest

from solidworks_mcp import com_backend, server
from solidworks_mcp.testing import install_fake_backend
from solidworks_mcp.tools import dispatch, registered_names
from solidworks_mcp.tools.registry import UnknownToolError
from solidworks_mcp.utils import units as units_module

EXPECTED_TOOL_NAMES = {
    # Connection Tools
    "connect_solidworks",
    "get_solidworks_info",
    # Document Tools
    "create_new_part",
    "create_new_assembly",
    "open_document",
    "save_document",
    "close_document",
    "get_document_info",
    "list_open_documents",
    # Drawing Document & Session Tools
    "new_drawing_from_template",
    "get_document_type",
    "open_or_activate_document",
    "rebuild_document",
    "save_drawing",
    "get_custom_properties",
    "set_custom_properties",
    # Drawing View Creation & Discovery Tools
    "insert_model_view",
    "insert_standard_3_view",
    "insert_projected_view",
    "insert_predefined_views",
    "insert_auxiliary_view",
    "insert_section_view",
    "insert_detail_view",
    "insert_broken_out_section",
    "list_views",
    # Drawing View Placement, Alignment, Display, and Deletion Tools
    "move_view",
    "align_view",
    "set_view_scale",
    "set_view_display_mode",
    "delete_view",
    "auto_arrange_views",
    # Sketch Tools
    "create_sketch",
    "create_sketch_on_face",
    "draw_line",
    "draw_circle",
    "draw_rectangle",
    "draw_arc",
    "draw_polygon",
    # Sketch Management Tools
    "close_sketch",
    "get_sketch_status",
    # Feature Tools
    "extrude_sketch",
    "cut_extrude",
    "fillet_edges",
    "chamfer_edges",
    "list_features",
    # Utility Tools
    "set_units",
    "execute_python",
}


@pytest.fixture(scope="module")
def listed_tools():
    return asyncio.run(server.list_tools())


class TestListToolsRegistry:
    def test_list_tools_returns_the_expected_tool_names(self, listed_tools):
        names = {tool.name for tool in listed_tools}
        assert names == EXPECTED_TOOL_NAMES
        assert len(listed_tools) == len(EXPECTED_TOOL_NAMES)

    def test_list_tools_has_no_duplicate_names(self, listed_tools):
        names = [tool.name for tool in listed_tools]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_list_tools_order_is_deterministic(self, listed_tools):
        again = asyncio.run(server.list_tools())
        assert [t.name for t in listed_tools] == [t.name for t in again]

    def test_every_registered_tool_has_a_description(self, listed_tools):
        for tool in listed_tools:
            assert isinstance(tool.description, str) and tool.description.strip(), (
                f"{tool.name!r} has an empty description"
            )

    def test_every_registered_tool_has_a_valid_input_schema(self, listed_tools):
        for tool in listed_tools:
            schema = tool.inputSchema
            assert isinstance(schema, dict), f"{tool.name!r} inputSchema is not a dict"
            assert schema.get("type") == "object", f"{tool.name!r} inputSchema.type must be 'object'"
            assert isinstance(schema.get("properties"), dict), f"{tool.name!r} inputSchema.properties must be a dict"
            required = schema.get("required", [])
            assert isinstance(required, list), f"{tool.name!r} inputSchema.required must be a list"
            for req_name in required:
                assert req_name in schema["properties"], (
                    f"{tool.name!r} requires {req_name!r} but it is not in its schema properties"
                )

    def test_every_listed_tool_is_dispatchable(self, listed_tools):
        """Every name `list_tools()` declares must resolve to a registered
        handler. Checked via `registered_names()` (a pure lookup) rather
        than by actually calling `dispatch()` here -- most handlers reach
        for a live SolidWorks connection, and running that unguarded would
        launch/drive the real app on a Windows host. The fake-backed
        `test_every_listed_tool_actually_dispatches_at_runtime` below is
        where dispatch is actually invoked."""
        dispatchable = set(registered_names())
        for tool in listed_tools:
            assert tool.name in dispatchable, (
                f"{tool.name!r} is listed but has no registered handler"
            )

    def test_dispatch_raises_unknown_tool_error_for_unregistered_name(self, listed_tools):
        bogus = "definitely_not_a_registered_tool"
        assert bogus not in {t.name for t in listed_tools}
        with pytest.raises(UnknownToolError):
            dispatch(bogus, {})

    def test_call_tool_has_no_hand_written_elif_dispatch_chain(self):
        """Regression guard: `call_tool()` must dispatch entirely through the
        registry, not via a reintroduced `if/elif name == "..."` chain."""
        source = inspect.getsource(server.call_tool)
        tree = ast.parse(source)
        func = tree.body[0]
        assert isinstance(func, ast.AsyncFunctionDef)

        offending = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "name"):
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                    if isinstance(comparator.value, str):
                        offending.append(comparator.value)
        assert not offending, (
            f"call_tool() still branches on `name ==` literals: {offending} -- "
            "dispatch through the tools registry instead"
        )

    def test_every_listed_tool_actually_dispatches_at_runtime(self, listed_tools):
        """Complements the static checks above: actually calls every tool
        name (through the real MCP `call_tool` entry point) with empty
        arguments and confirms the dispatcher's fallback ("Unknown tool: ...")
        branch was never hit. All tool handlers pull arguments via
        `arguments.get(key, default)`, so `{}` is always a valid (if
        sometimes business-logic-failing) call.

        Runs against an installed fake backend rather than whatever COM the
        host happens to have, so the result is identical on macOS/Linux and
        on the Windows machines this product actually ships to. None of the
        handlers' zero-argument defaults touch the filesystem or a real
        SolidWorks: `open_document("")` fails its `os.path.exists` check and
        `save_document(None)` takes the save-in-place branch onto the fake.

        `solidworks_mcp.tools` keeps a module-level `sw_automation` singleton
        shared by every test in the process, so the connection it makes to
        this (torn-down) fake has to be dropped afterwards; likewise
        `set_units` mutates process-global `utils.units._default_converter`
        state.
        """
        original_default_unit = units_module.get_converter().default_unit
        original_sw_units_default = server.sw_automation._units.default_unit
        try:
            with install_fake_backend("part"):
                assert com_backend.is_com_available()
                for tool in listed_tools:
                    contents = asyncio.run(server.call_tool(tool.name, {}))
                    text = contents[0].text
                    assert f"Unknown tool: {tool.name}" not in text, (
                        f"{tool.name!r} is listed but call_tool() dispatched it to the fallback branch: {text}"
                    )
        finally:
            server.sw_automation.disconnect()
            units_module.set_default_unit(original_default_unit)
            server.sw_automation._units.default_unit = original_sw_units_default
