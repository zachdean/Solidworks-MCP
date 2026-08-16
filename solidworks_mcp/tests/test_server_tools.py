"""
list_tools() / call_tool() name-parity regression test.
---------------------------------------------------------
`server.py` declares every tool twice: once as a `Tool` in `list_tools()`
(name, description, schema) and once as a branch of the `if name == "..."`
chain in `call_tool()`. Nothing enforces the two stay in sync -- it is easy
to add/rename a tool in one and forget the other. This test catches that
drift both statically (parsing `call_tool`'s source for the exact set of
names it branches on) and dynamically (actually invoking every listed tool
name and checking the dispatcher didn't fall through to its "Unknown tool"
branch).
"""

import ast
import asyncio
import inspect

import pytest

from solidworks_mcp import com_backend, server
from solidworks_mcp.testing import install_fake_backend
from solidworks_mcp.utils import units as units_module


def _dispatched_names() -> set:
    """Statically extract every string literal `call_tool` compares `name`
    against (`if name == "foo"` / `elif name == "bar"`), by parsing the
    function's own source with `ast` -- decorator-proof and independent of
    whatever the dispatcher's actual runtime behavior turns out to be."""
    source = inspect.getsource(server.call_tool)
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)

    names = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                if isinstance(comparator.value, str):
                    names.add(comparator.value)
    return names


@pytest.fixture(scope="module")
def listed_tools():
    return asyncio.run(server.list_tools())


@pytest.fixture(scope="module")
def dispatched_names():
    return _dispatched_names()


class TestListToolsCallToolParity:
    def test_every_listed_tool_is_dispatched(self, listed_tools, dispatched_names):
        listed_names = {tool.name for tool in listed_tools}
        missing = listed_names - dispatched_names
        assert not missing, (
            f"Tool(s) declared in list_tools() but not handled by call_tool(): {sorted(missing)}"
        )

    def test_every_dispatched_name_is_listed(self, listed_tools, dispatched_names):
        listed_names = {tool.name for tool in listed_tools}
        orphaned = dispatched_names - listed_names
        assert not orphaned, (
            f"Name(s) handled by call_tool() but never declared in list_tools(): {sorted(orphaned)}"
        )

    def test_list_tools_has_no_duplicate_names(self, listed_tools):
        names = [tool.name for tool in listed_tools]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_every_listed_tool_actually_dispatches_at_runtime(self, listed_tools):
        """Complements the static AST check: actually calls every tool name
        with empty arguments and confirms the dispatcher's fallback ("Unknown
        tool: ...") branch was never hit. All tool handlers pull arguments
        via `arguments.get(key, default)`, so `{}` is always a valid (if
        sometimes business-logic-failing) call.

        Runs against an installed fake backend rather than whatever COM the
        host happens to have, so the result is identical on macOS/Linux and
        on the Windows machines this product actually ships to. None of the
        handlers' zero-argument defaults touch the filesystem or a real
        SolidWorks: `open_document("")` fails its `os.path.exists` check and
        `save_document(None)` takes the save-in-place branch onto the fake.

        `server.py` keeps a module-level `sw_automation` singleton shared by
        every test in the process, so the connection it makes to this
        (torn-down) fake has to be dropped afterwards; likewise `set_units`
        mutates process-global `utils.units._default_converter` state.
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
