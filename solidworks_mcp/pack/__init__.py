"""
Declarative drawing-pack spec
-------------------------------
`spec.py` defines the pack dataclasses (`PackSpec`, `SheetSpec`, `ViewSpec`,
`AnnotationSpec`, `TableSpec`) plus JSON round-tripping and offline
validation. `schema.json` is generated from those dataclasses via
`spec.generate_schema()` -- see `scripts/generate_pack_schema.py`.

No COM calls happen anywhere in this package; the compiler that lowers a
validated `PackSpec` into ordered SolidWorks calls is a separate concern
(sw-wds.2).
"""

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
]
