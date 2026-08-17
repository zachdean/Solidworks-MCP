"""
SolidWorks MCP Tools
---------------------
Declarative tool registry (`registry.py`) plus one module per tool area:
`connection.py`, `documents.py`, `drawing_documents.py`, `drawing_views.py`,
`drawing_view_layout.py`, `drawing_annotations.py`, `sketches.py`,
`features.py`, `utility.py`. Importing this package registers every tool as
a side effect of importing its submodules.

The shared `sw_automation` instance lives in `_automation.py` and is
re-exported here for `server.py`'s convenience; submodules import it from
there directly, so this package's own import order carries no meaning.
"""

from ._automation import sw_automation
from .registry import (
    UnknownToolError,
    build_tool_list,
    dispatch,
    registered_names,
    schema_from_signature,
    tool,
)

from . import connection  # noqa: F401
from . import documents  # noqa: F401
from . import drawing_documents  # noqa: F401
from . import drawing_views  # noqa: F401
from . import drawing_view_layout  # noqa: F401
from . import drawing_annotations  # noqa: F401
from . import sketches  # noqa: F401
from . import features  # noqa: F401
from . import utility  # noqa: F401

__all__ = [
    "sw_automation",
    "tool",
    "build_tool_list",
    "dispatch",
    "registered_names",
    "schema_from_signature",
    "UnknownToolError",
]
