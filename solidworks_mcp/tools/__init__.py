"""
SolidWorks MCP Tools
---------------------
Declarative tool registry (`registry.py`) plus one module per tool area:
`connection.py`, `documents.py`, `sketches.py`, `features.py`, `utility.py`.
Importing this package registers every tool as a side effect of importing
its submodules.

`sw_automation` lives here (rather than in `server.py`) so both `server.py`
and every tools submodule can import the *same* instance without a
package-crossing circular import: this module builds it before importing
the submodules below, so by the time e.g. `connection.py` does
`from . import sw_automation`, the attribute already exists on this
(mid-initialization) package.
"""

from ..automation import SolidWorksAutomation

sw_automation = SolidWorksAutomation()

from .registry import (  # noqa: E402
    UnknownToolError,
    build_tool_list,
    dispatch,
    registered_names,
    schema_from_signature,
    tool,
)

from . import connection  # noqa: E402,F401
from . import documents  # noqa: E402,F401
from . import sketches  # noqa: E402,F401
from . import features  # noqa: E402,F401
from . import utility  # noqa: E402,F401

__all__ = [
    "sw_automation",
    "tool",
    "build_tool_list",
    "dispatch",
    "registered_names",
    "schema_from_signature",
    "UnknownToolError",
]
