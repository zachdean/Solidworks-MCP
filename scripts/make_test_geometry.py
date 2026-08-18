#!/usr/bin/env python3
"""Generate the part/assembly fixtures the Windows integration tests need.

Everything up to sw-17y was written and unit-tested against the fake-COM
harness, with no real SolidWorks involved. The Windows integration suite
(`solidworks_mcp/tests/integration/`) needs real geometry to open, add views
of, and dimension -- and that geometry has to be built by script, not shipped
as binary fixtures in git, so the first real hardware run is one command
instead of an interactive modeling session.

Run on a Windows machine with SolidWorks installed and this project's venv
active:

    .venv\\Scripts\\python.exe scripts\\make_test_geometry.py [--out-dir DIR]

Produces, under `--out-dir` (default `tests/fixtures/generated/`, gitignored):
  - bracket.sldprt: a rectangular-base bracket with 4 mounting holes, a
    fillet, and a chamfer, with PartNo/Description/Material/Revision custom
    properties set.
  - bracket_assembly.sldasm: two instances of bracket.sldprt, with its own
    PartNo/Description/Revision custom properties set.

Every step is built entirely from the automation methods already exposed by
`solidworks_mcp.automation.SolidWorksAutomation` (`create_new_part`,
`create_sketch`, `draw_rectangle`, `draw_circle`, `extrude_sketch`,
`cut_extrude`, `fillet_edges`, `chamfer_edges`, `set_custom_properties`,
`save_document`), with one exception: inserting components into the
assembly. No `AddComponent` tool or automation method exists anywhere in
this project (it is out of scope for `DrawingOperations`, the only mixin
that talks to assemblies), so this script calls `IAssemblyDoc::
AddComponent5` directly via the raw COM document object. That signature is
public SOLIDWORKS API knowledge, not sourced from this project's
`docs/api/` dossier -- the dossier only covers the drawing-side API surface
this project's tools expose, and this generator script sits outside that
tool surface entirely.

Edge selection for the fillet/chamfer (`fillet_edges`/`chamfer_edges` act on
whatever is currently selected, taking no entity argument themselves) is a
best-effort coordinate guess from the block's known, parametric dimensions:
`extrude_sketch` doesn't report which way along the sketch-plane normal
`FeatureExtrusion2` actually extruded, so `_select_vertical_edge` tries both
signs. If SolidWorks resolves the sketch/extrude geometry differently than
assumed here, this script fails loudly (a `GeometryBuildError` naming the
step and the coordinates tried) rather than silently producing broken
geometry -- fix the assumption and rerun.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The bracket's dimensions live in the shared contract module rather than
# here, so the integration suite and scripts/validate_on_windows.py pick
# entities against the same numbers this script builds from.
from solidworks_mcp.testing.bracket_geometry import (  # noqa: E402
    ASSEMBLY_COMPONENT_SPACING_MM,
    BASE_HEIGHT_MM,
    CHAMFER_ANGLE_DEG,
    CHAMFER_DISTANCE_MM,
    FILLET_RADIUS_MM,
    HALF_DEPTH_MM,
    HALF_WIDTH_MM,
    HOLE_INSET_MM,
    HOLE_RADIUS_MM,
)

DEFAULT_OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "generated"

logger = logging.getLogger("make_test_geometry")

PART_PROPERTIES = {
    "PartNo": "BR-1001",
    "Description": "Mounting Bracket",
    "Material": "6061-T6 Aluminum",
    "Revision": "A",
}

ASSEMBLY_PROPERTIES = {
    "PartNo": "ASM-2001",
    "Description": "Bracket Sub-Assembly",
    "Revision": "A",
}


class GeometryBuildError(RuntimeError):
    """Raised when a build step's standard result dict reports failure."""


def _check(step: str, result: dict) -> dict:
    """Raise `GeometryBuildError` if `result` (a standard tool/automation
    result dict) is not a success; otherwise log and pass it through."""
    if not result.get("success"):
        raise GeometryBuildError(f"{step} failed: {result.get('message')}")
    logger.info("%s: %s", step, result.get("message"))
    return result


def _select_vertical_edge(sw, x_mm: float, y_mm: float, height_mm: float, label: str) -> None:
    """Select the extrude-direction edge at model (x, y, ?), trying both
    signs of the extrude direction -- see the module docstring for why the
    sign is ambiguous from here.

    The base sketch is on the Front plane (= the global XY plane, see
    `SwPlanes.FRONT`), so the sketch's local x/y are the model's X/Y and
    `extrude_sketch` runs along **Z**. The edge to pick is therefore the
    one at the (x, y) corner, probed at half the extrude depth along Z."""
    for sign in (1, -1):
        z_mm = sign * height_mm / 2
        result = sw.select_by_id("", "EDGE", x_mm, y_mm, z_mm)
        if result.get("success"):
            logger.info("%s: selected edge near (%.1f, %.1f, %.1f)mm", label, x_mm, y_mm, z_mm)
            return
    raise GeometryBuildError(
        f"{label}: could not select an edge near x={x_mm}mm y={y_mm}mm "
        "(tried both extrude directions)"
    )


def build_bracket_part(sw, out_dir: Path) -> Path:
    """Build the bracket part and save it under `out_dir`. Returns the
    saved part's path."""
    _check("create_new_part", sw.create_new_part())
    _check("create_sketch(base)", sw.create_sketch("Front"))
    _check("draw_rectangle(base)",
           sw.draw_rectangle(-HALF_WIDTH_MM, -HALF_DEPTH_MM, HALF_WIDTH_MM, HALF_DEPTH_MM))
    _check("extrude_sketch(base)", sw.extrude_sketch(BASE_HEIGHT_MM))

    # Same both-signs extrude-direction probe as `_select_vertical_edge`:
    # the block was extruded along Z, so its top face is the z = +/-
    # BASE_HEIGHT_MM plane, probed at the face's center (x=y=0).
    for sign in (1, -1):
        result = sw.create_sketch_on_face(0, 0, sign * BASE_HEIGHT_MM)
        if result.get("success"):
            logger.info("create_sketch_on_face(top): %s", result.get("message"))
            break
    else:
        raise GeometryBuildError(
            "Could not find the extruded block's top face for the hole sketch"
        )

    hole_x = HALF_WIDTH_MM - HOLE_INSET_MM
    hole_y = HALF_DEPTH_MM - HOLE_INSET_MM
    hole_centers = [(hole_x, hole_y), (-hole_x, hole_y), (-hole_x, -hole_y), (hole_x, -hole_y)]
    for cx, cy in hole_centers:
        _check("draw_circle(hole)", sw.draw_circle(cx, cy, HOLE_RADIUS_MM))

    _check("cut_extrude(holes)", sw.cut_extrude(through_all=True))

    _select_vertical_edge(sw, HALF_WIDTH_MM, HALF_DEPTH_MM, BASE_HEIGHT_MM, "fillet edge")
    _check("fillet_edges", sw.fillet_edges(FILLET_RADIUS_MM))

    _select_vertical_edge(sw, -HALF_WIDTH_MM, -HALF_DEPTH_MM, BASE_HEIGHT_MM, "chamfer edge")
    _check("chamfer_edges", sw.chamfer_edges(CHAMFER_DISTANCE_MM, CHAMFER_ANGLE_DEG))

    _check("set_custom_properties(part)", sw.set_custom_properties(dict(PART_PROPERTIES)))

    part_path = out_dir / "bracket.sldprt"
    _check("save_document(part)", sw.save_document(str(part_path)))
    _check("close_document(part)", sw.close_document(save=False))
    return part_path


def build_assembly(sw, part_path: Path, out_dir: Path) -> Path:
    """Build a two-component assembly from `part_path` and save it under
    `out_dir`. Returns the saved assembly's path."""
    _check("create_new_assembly", sw.create_new_assembly())

    doc, err = sw.get_active_doc()
    if err:
        raise GeometryBuildError(f"No active assembly document: {err.get('message')}")

    part_path_str = str(part_path)
    spacing_m = sw.units.to_meters(ASSEMBLY_COMPONENT_SPACING_MM, "mm")
    positions = (0.0, spacing_m)
    for index, x_m in enumerate(positions):
        # IAssemblyDoc::AddComponent5(ComponentName, Options, ConfigName,
        # UseLightWeightDefault, ReferencedConfigName, X, Y, Z) -> IComponent2.
        # See the module docstring: public SOLIDWORKS API knowledge, not
        # this project's docs/api/ dossier.
        component = doc.AddComponent5(part_path_str, 0, "", False, "", x_m, 0.0, 0.0)
        if component is None:
            raise GeometryBuildError(
                f"AddComponent5 failed to insert component #{index + 1} from {part_path_str!r}"
            )
    logger.info("Inserted %d component(s) into the assembly", len(positions))

    _check("rebuild_document(assembly)", sw.rebuild_document())
    _check("set_custom_properties(assembly)", sw.set_custom_properties(dict(ASSEMBLY_PROPERTIES)))

    asm_path = out_dir / "bracket_assembly.sldasm"
    _check("save_document(assembly)", sw.save_document(str(asm_path)))
    _check("close_document(assembly)", sw.close_document(save=False))
    return asm_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR),
        help="Directory to write generated fixtures into (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if sys.platform != "win32":
        logger.error(
            "make_test_geometry.py requires Windows + SolidWorks; got platform %r. "
            "This is a fixture generator for the Windows integration suite, not "
            "something to run in CI/off-Windows.",
            sys.platform,
        )
        return 1

    from solidworks_mcp.automation import SolidWorksAutomation

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sw = SolidWorksAutomation()
    _check("connect", sw.connect())
    sw.units.default_unit = "mm"

    try:
        part_path = build_bracket_part(sw, out_dir)
        asm_path = build_assembly(sw, part_path, out_dir)
    except GeometryBuildError as e:
        logger.error("Geometry generation failed: %s", e)
        return 1

    logger.info("Generated part: %s", part_path)
    logger.info("Generated assembly: %s", asm_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
