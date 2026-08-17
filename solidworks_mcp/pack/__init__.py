"""
Declarative drawing-pack spec + compiler
-------------------------------------------
`spec.py` defines the pack dataclasses (`PackSpec`, `SheetSpec`, `ViewSpec`,
`AnnotationSpec`, `TableSpec`) plus JSON round-tripping and offline
validation. `schema.json` is generated from those dataclasses via
`spec.generate_schema()` -- see `scripts/generate_pack_schema.py`.

`compiler.py` lowers a validated `PackSpec` into an ordered list of `Step`s
(registered tool name + arguments) -- still no COM calls anywhere in this
package. `solidworks_mcp/tools/drawing_pack.py`'s `create_drawing_pack` tool
is what actually runs a compiled step list against the tool registry.
"""

from .compiler import Ref, Step, compile
from .spec import (
    AnnotationSpec,
    PackSpec,
    ScaleSpec,
    SheetSpec,
    TableSpec,
    ViewSpec,
    generate_schema,
)

__all__ = [
    "PackSpec",
    "SheetSpec",
    "ViewSpec",
    "AnnotationSpec",
    "TableSpec",
    "ScaleSpec",
    "generate_schema",
    "Ref",
    "Step",
    "compile",
]
