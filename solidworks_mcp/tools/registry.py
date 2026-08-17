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

from .. import version_gate
from ..automation.com_params import ComSignature
from ._automation import sw_automation

__all__ = [
    "tool",
    "build_tool_list",
    "dispatch",
    "registered_names",
    "describe_tools",
    "schema_from_signature",
    "UnknownToolError",
]


class UnknownToolError(KeyError):
    """Raised by `dispatch()` when `name` has no registered handler."""


class _RegisteredTool:
    __slots__ = ("name", "description", "schema", "handler", "min_release")

    def __init__(self, name: str, description: str, schema: Dict[str, Any],
                 handler: Callable[[dict], Dict[str, Any]],
                 min_release: Optional[int] = None):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.min_release = min_release


# Order matters for `build_tool_list()` -- tools are listed in the order
# they were registered (i.e. import order of the `solidworks_mcp.tools`
# submodules), matching the deterministic order the old hand-written list
# had. A dict preserves insertion order, so it is both the lookup index and
# the ordering; no parallel list to keep in sync.
_TOOLS: Dict[str, _RegisteredTool] = {}


def tool(name: str, description: str, schema: Dict[str, Any], *,
         min_release: Optional[int] = None) -> Callable:
    """Decorator: register `handler` as the MCP tool `name`.

    Args:
        min_release: the SOLIDWORKS release year (e.g. `2025`) this tool's
            COM calls require, if higher than the project-wide floor
            (`config.min_release`). `dispatch()` checks this -- via
            `version_gate.require_version` -- before invoking `handler`, so
            a handler never runs against a release too old for the overload
            it calls. Omit for tools that need nothing beyond the project
            floor, which is nearly all of them. Pass `0` (not `None`) to
            exempt a tool from the gate entirely -- see
            `version_gate.effective_min_release`; reserved for discovery
            tools like `get_capabilities` that must stay callable on an
            unsupported release precisely to report that fact.

    Raises:
        ValueError: if `name` is already registered -- at import time, since
            every tools submodule registers its tools at module scope.
    """
    def decorator(handler: Callable[[dict], Dict[str, Any]]) -> Callable[[dict], Dict[str, Any]]:
        if name in _TOOLS:
            raise ValueError(f"Tool '{name}' is already registered")
        _TOOLS[name] = _RegisteredTool(name, description, schema, handler, min_release)
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


def describe_tools() -> List[Dict[str, Any]]:
    """Every registered tool's static metadata, in registration order: name,
    description, schema, declared `min_release`, and the *effective*
    `min_release` (`version_gate.effective_min_release`, folding in the
    project-wide floor). Used by the `get_capabilities` tool and
    `scripts/gen_tools_doc.py` -- neither invokes a handler, so this is safe
    to call with nothing connected."""
    return [
        {
            "name": entry.name,
            "description": entry.description,
            "schema": entry.schema,
            "min_release": entry.min_release,
            "effective_min_release": version_gate.effective_min_release(entry.min_release),
        }
        for entry in _TOOLS.values()
    ]


def dispatch(name: str, arguments: dict) -> Dict[str, Any]:
    """Invoke the registered handler for `name` with `arguments`.

    Checks `version_gate.require_version` first -- if the connected
    SOLIDWORKS release is older than the tool's effective `min_release`, the
    handler never runs and the gate's error result (naming the tool, the
    connected version, and the required version) is returned instead. A
    handler that has never called `automation.connect()` is not gated (see
    `version_gate.require_version`); the handler's own connection attempt
    surfaces its own error in that case.

    Returns:
        The handler's standard result dict, or the gate's error result.

    Raises:
        UnknownToolError: if no tool named `name` is registered.
    """
    entry = _TOOLS.get(name)
    if entry is None:
        raise UnknownToolError(name)
    gate_error = version_gate.require_version(sw_automation, name, entry.min_release)
    if gate_error is not None:
        return gate_error
    return entry.handler(arguments)
