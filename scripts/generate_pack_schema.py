#!/usr/bin/env python3
"""
Regenerate solidworks_mcp/pack/schema.json from the pack dataclasses
(solidworks_mcp/pack/spec.py). Run this after changing any field on
PackSpec/SheetSpec/ViewSpec/AnnotationSpec/TableSpec/ScaleSpec --
test_pack_spec.py fails if the checked-in file drifts from the generator.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from solidworks_mcp.pack.spec import generate_schema  # noqa: E402

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "solidworks_mcp" / "pack" / "schema.json"


def main() -> None:
    schema = generate_schema()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
