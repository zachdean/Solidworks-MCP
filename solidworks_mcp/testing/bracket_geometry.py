"""The generated bracket fixture's geometry contract, in one place.

`scripts/make_test_geometry.py` builds the bracket *from* these numbers;
`solidworks_mcp/tests/integration/` and `scripts/validate_on_windows.py`
pick entities *against* them. Before sw-ja4 the contract was restated in
all three files, pre-divided into literal halves (`40.0  # BASE_WIDTH_MM /
2`) and held together only by "must match" comments -- so changing a
dimension left the pickers aiming at coordinates the geometry no longer
had, and the failure surfaced as a dozen unrelated-looking `SelectByID2`
misses rather than as anything naming the constant.

All lengths are in mm -- the unit both the generator and the integration
suite set as default before doing anything else.

Import-safe on any platform: constants and pure functions only, no COM.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

# ============================================================================
# The part, as built
# ============================================================================

# The base sketch is on the Front plane, which *is* the global XY plane
# (`SwPlanes.FRONT`), so the sketch's local x/y are the model's X/Y and the
# extrude runs along the model's Z.
BASE_WIDTH_MM = 80.0   # X extent
BASE_DEPTH_MM = 50.0   # Y extent
BASE_HEIGHT_MM = 20.0  # Z extent -- the extrude depth, along the Front plane's normal

HOLE_RADIUS_MM = 4.0
HOLE_INSET_MM = 12.0   # each mounting hole's center, inset from both edges

FILLET_RADIUS_MM = 3.0      # applied to the (+X, +Z) vertical edge
CHAMFER_DISTANCE_MM = 2.0   # applied to the (-X, -Z) vertical edge
CHAMFER_ANGLE_DEG = 45.0

# The offset between the two assembly instances, along X, in mm.
ASSEMBLY_COMPONENT_SPACING_MM = 120.0

HALF_WIDTH_MM = BASE_WIDTH_MM / 2
HALF_DEPTH_MM = BASE_DEPTH_MM / 2

# ============================================================================
# Sheet-space entity picking (the bracket part's *Front view)
# ============================================================================

PART_VIEW_X, PART_VIEW_Y = 100.0, 100.0
ASSEMBLY_VIEW_X, ASSEMBLY_VIEW_Y = 300.0, 100.0

# Untouched corners -- neither the filleted (+X, +Z) nor the chamfered
# (-X, -Z) one -- so these stay stable vertex targets whatever the fillet
# and chamfer sizes are.
CORNER_BOTTOM_RIGHT: Tuple[float, float] = (HALF_WIDTH_MM, -HALF_DEPTH_MM)
CORNER_TOP_LEFT: Tuple[float, float] = (-HALF_WIDTH_MM, HALF_DEPTH_MM)
BOTTOM_EDGE_MIDPOINT: Tuple[float, float] = (0.0, -HALF_DEPTH_MM)
FACE_CENTER: Tuple[float, float] = (0.0, 0.0)  # clear of all 4 holes


def entity(kind: str, local_x: float, local_y: float) -> Dict[str, Any]:
    """An entity-picking dict for `kind` ("vertex"/"edge"/"face") at the
    part view's local (x, y), translated into the sheet coordinates the
    picking tools take.

    The *Front view looks down the model's Z, so the view's local x/y are
    the model's X/Y -- the same axes `BASE_WIDTH_MM`/`BASE_DEPTH_MM` name."""
    return {"kind": kind, "x": PART_VIEW_X + local_x, "y": PART_VIEW_Y + local_y}
