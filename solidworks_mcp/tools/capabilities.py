"""
Capabilities Tool
------------------
get_capabilities -- how an LLM discovers what it can currently do before it
tries: the connected SOLIDWORKS release, the project's minimum required
release, and every registered tool with its own `min_release` and whether
it's usable right now. Registered with `min_release=0` -- `version_gate`'s
"exempt from the gate entirely" sentinel, not the default `None` -- so it
must stay callable even against an unsupported release, since that's exactly
when a caller most needs to see why every other tool reports `usable: False`.
"""

from typing import Dict

from .. import version_gate
from ..config import get_config
from ._automation import sw_automation
from .registry import describe_tools, tool


@tool(
    name="get_capabilities",
    description=(
        "Report the connected SOLIDWORKS version, the project's minimum "
        "required version, and every registered tool with its required "
        "version and whether it is usable right now. Call this before "
        "calling an unfamiliar tool to check it will actually work against "
        "the connected SOLIDWORKS install."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    min_release=0,
)
def get_capabilities(arguments: dict) -> Dict:
    min_required = get_config().min_release
    connected = bool(sw_automation.is_connected)

    connected_release_year = None
    revision_number = None
    if connected:
        try:
            release = version_gate.get_connected_release(sw_automation)
        except version_gate.VersionGateError:
            connected = False
        else:
            connected_release_year = release.year
            revision_number = release.raw

    tools = []
    for entry in describe_tools():
        required = entry["effective_min_release"]
        usable = True if required is None else (connected and connected_release_year >= required)
        tools.append({
            "name": entry["name"],
            "description": entry["description"],
            "min_release": required,
            "usable": usable,
        })

    return {
        "success": True,
        "message": (
            f"Connected to SOLIDWORKS {connected_release_year}" if connected
            else "Not connected to SOLIDWORKS"
        ) + f"; project minimum is SOLIDWORKS {min_required}.",
        "error_code": 0,
        "error_name": "swSuccess",
        "data": {
            "connected": connected,
            "connected_release": connected_release_year,
            "revision_number": revision_number,
            "min_required_release": min_required,
            "tools": tools,
        },
    }
