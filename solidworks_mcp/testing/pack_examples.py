"""Load a shipped `docs/packs/` example and repoint it at generated test
geometry.

`solidworks_mcp/tests/integration/test_drawing_pipeline.py` and
`scripts/validate_on_windows.py` both exercise `create_drawing_pack`
against a real example spec, and both need the same four substitutions to
do it -- the examples ship with placeholder Windows paths and, in
`assembly_with_bom.json`'s case, balloon coordinates hand-calibrated for an
unrelated gearbox model that would never land on the bracket fixture's
geometry. That munging lived in both callers before sw-ja4.

The example file itself is only ever read, never written.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

PACKS_DIR = Path(__file__).resolve().parents[2] / "docs" / "packs"


def load_example_pack(
    name: str,
    model_path: Union[str, Path],
    output_path: Union[str, Path],
    drawing_template: Optional[str] = None,
) -> Dict[str, Any]:
    """Return `docs/packs/<name>.json` parsed and retargeted: first sheet
    and its first view pointed at `model_path`, `output` at `output_path`,
    `drawing_template` replaced when one is given (the examples' own path
    is a placeholder), and annotations dropped.

    Annotations go because the examples' coordinates are entity picks
    calibrated for their own model; the sheet's tables stay, since their
    x/y are sheet placement rather than picks. Each call re-parses, so
    callers get a spec they can mutate freely.
    """
    spec = json.loads((PACKS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    if drawing_template:
        spec["drawing_template"] = drawing_template
    spec["output"] = str(output_path)
    sheet = spec["sheets"][0]
    sheet["model_path"] = str(model_path)
    sheet["views"][0]["model_path"] = str(model_path)
    sheet["annotations"] = []
    return spec
