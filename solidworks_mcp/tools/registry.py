"""
Tool Registry
-------------
Declarative registry for MCP tools. A `@tool(name, description, schema)`
decorator registers a handler function into an ordered registry; `server.py`
pulls the whole registry via `build_tool_list()` / `dispatch()` instead of
listing every tool twice (once in `list_tools()`, once as an `if/elif`
branch in `call_tool()`) -- the two lists could never drift because there is
only one list.

Handlers take the raw `arguments` dict passed by the MCP client and return
the project's standard result dict (`{"success", "message", "error_code",
"error_name", ...}`) -- exactly what every `SolidWorksAutomation` method and
`sw_automation._result()` already produce, so `server.py::format_result` is
unchanged.

`schema` may be supplied two ways:
  - literally, as a complete JSON-schema `inputSchema` dict; or
  - via `schema_from_signature()`, which adapts a `ComSignature.describe()`
    properties map (from `solidworks_mcp.automation.com_params`) into one.
"""

from typing import Any, Callable, Dict, List, Optional

from mcp.types import Tool

from ..automation.com_params import ComSignature

__all__ = [
    "tool",
    "build_tool_list",
    "dispatch",
    "registered_names",
    "schema_from_signature",
    "UnknownToolError",
]


class UnknownToolError(KeyError):
    """Raised by `dispatch()` when `name` has no registered handler."""


class _RegisteredTool:
    __slots__ = ("name", "description", "schema", "handler")

    def __init__(self, name: str, description: str, schema: Dict[str, Any],
                 handler: Callable[[dict], Dict[str, Any]]):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler


# Order matters for `build_tool_list()` -- tools are listed in the order
# they were registered (i.e. import order of the `solidworks_mcp.tools`
# submodules), matching the deterministic order the old hand-written list
# had. A dict preserves insertion order, so it is both the lookup index and
# the ordering; no parallel list to keep in sync.
_TOOLS: Dict[str, _RegisteredTool] = {}


def tool(name: str, description: str, schema: Dict[str, Any]) -> Callable:
    """Decorator: register `handler` as the MCP tool `name`.

    Raises:
        ValueError: if `name` is already registered -- at import time, since
            every tools submodule registers its tools at module scope.
    """
    def decorator(handler: Callable[[dict], Dict[str, Any]]) -> Callable[[dict], Dict[str, Any]]:
        if name in _TOOLS:
            raise ValueError(f"Tool '{name}' is already registered")
        _TOOLS[name] = _RegisteredTool(name, description, schema, handler)
        return handler
    return decorator


def schema_from_signature(signature: ComSignature, *,
                           required: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build a full MCP `inputSchema` dict from a `ComSignature`.

    `ComSignature.describe()` only returns the `properties` map (each
    param's inferred `type`/`default`), so this wraps it into
    `{"type": "object", "properties": ..., "required": ...}`.

    Args:
        signature: the `ComSignature` to describe.
        required: param names that must be supplied. Defaults to every
            param whose `describe()` entry has no `"default"` key, i.e.
            every `Param` declared without a default value.
    """
    properties = signature.describe()
    if required is None:
        required = [name for name, prop in properties.items() if "default" not in prop]
    return {"type": "object", "properties": properties, "required": required}


def build_tool_list() -> List[Tool]:
    """Every registered tool as an `mcp.types.Tool`, in registration order."""
    return [
        Tool(
            name=entry.name,
            description=entry.description,
            inputSchema=entry.schema,
        )
        for entry in _TOOLS.values()
    ]


def registered_names() -> List[str]:
    """Every registered tool name, in registration order. Lets callers check
    "is this name dispatchable" without actually invoking a handler (most
    handlers reach for a live SolidWorks connection)."""
    return list(_TOOLS)


def dispatch(name: str, arguments: dict) -> Dict[str, Any]:
    """Invoke the registered handler for `name` with `arguments`.

    Returns:
        The handler's standard result dict.

    Raises:
        UnknownToolError: if no tool named `name` is registered.
    """
    entry = _TOOLS.get(name)
    if entry is None:
        raise UnknownToolError(name)
    return entry.handler(arguments)
