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
from ..constants import SwErrors
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
    version_error = None
    if connected:
        try:
            release = version_gate.get_connected_release(sw_automation)
        except version_gate.VersionGateError as exc:
            # Connected, but the version could not be read/parsed. Keep
            # `connected` True -- reporting "not connected" here sends the
            # caller off to reconnect when the actual fault is an
            # unreadable RevisionNumber, and this tool exists precisely to
            # explain why the rest of the toolset is unusable.
            version_error = str(exc)
        else:
            connected_release_year = release.year
            revision_number = release.raw

    tools = []
    for entry in describe_tools():
        required = entry["effective_min_release"]
        # Mirror `version_gate.require_version`, which is what `dispatch`
        # actually enforces: an exempt tool always passes, and so does
        # every tool while nothing is connected (the gate has no version to
        # judge, and the handler's own lazy connect reports its own error).
        # Reporting `usable: False` for the whole toolset in a fresh,
        # not-yet-connected session -- the exact moment this tool is meant
        # to be called -- was wrong in the one direction that matters.
        if required is None or not connected:
            usable = True
        elif connected_release_year is None:
            usable = False  # connected, but the gate can't read the version
        else:
            usable = connected_release_year >= required
        tools.append({
            "name": entry["name"],
            "description": entry["description"],
            "min_release": required,
            "usable": usable,
        })

    if not connected:
        message = "Not connected to SOLIDWORKS"
    elif version_error is not None:
        message = f"Connected to SOLIDWORKS, but its version could not be read ({version_error})"
    else:
        message = f"Connected to SOLIDWORKS {connected_release_year}"
    message += f"; project minimum is SOLIDWORKS {min_required}."

    return sw_automation._result(True, message, SwErrors.swSuccess, {
        "connected": connected,
        "connected_release": connected_release_year,
        "revision_number": revision_number,
        "version_error": version_error,
        "min_required_release": min_required,
        "tools": tools,
    })
