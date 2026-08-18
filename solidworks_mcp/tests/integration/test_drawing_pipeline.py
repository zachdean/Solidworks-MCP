"""
Windows integration: drawing pipeline (sw-17y.1)
--------------------------------------------------
Exercises the drawing-side tool surface end-to-end against the real
geometry `scripts/make_test_geometry.py` produces (see conftest.py for how
that's located, and how the whole module skips cleanly without it).

Geometry recap -- every number below comes from
`solidworks_mcp.testing.bracket_geometry`, the shared contract
scripts/make_test_geometry.py builds from: a bracket with an 80x50mm base
(X x Z), 20mm tall, 4 mounting holes inset 12mm from each edge, a 3mm
fillet on the (+X, +Z) corner, and a 2mm 45-degree chamfer on the
(-X, -Z) corner. The two
remaining corners, (+X, -Z) and (-X, +Z), are untouched -- tests that need
a stable vertex/edge target use those instead of a modified corner, so a
SelectByID2 proximity pick doesn't land on a fillet arc or a chamfer edge
that wasn't there when the coordinate was chosen.

Coordinate convention: every x/y this module passes to place or pick
something is SHEET-space millimeters -- the same convention
`insert_model_view`'s own x/y use ("sheet-space meters"). A point on the
bracket's *Front view, placed at (PART_VIEW_X, PART_VIEW_Y) with the sheet's
default 1:1 scale, appears on the sheet at
`(PART_VIEW_X + local_x, PART_VIEW_Y + local_z)`: Front looks straight down at the
sketch plane, so the view's on-sheet layout matches the part's local (X, Z)
directly. `bracket_geometry.entity()` is that mapping; `insert_section_view`/
`insert_detail_view`'s `cut_points`/`center_x`/`center_y` are the one
exception -- their own docstrings say those are in the parent view's local
coordinate space, not sheet space, so those two tests pass local
coordinates unconverted.

These coordinates are a best-effort geometric approximation, not a
verified transform (no model-to-sheet transform helper exists in this
project -- see `list_view_entities`' docstring). A failure here should read
as "the approximation was off, adjust the coordinates" -- every assertion
below includes the result message and, where useful, the full data payload,
so that diagnosis doesn't require re-running interactively.
"""
import sys

import pytest

# The bracket's dimensions and this sheet-space mapping are the shared
# contract scripts/make_test_geometry.py builds the fixture from, so a
# dimension change can't leave these picks aiming at coordinates the
# geometry no longer has.
from solidworks_mcp.testing.bracket_geometry import (
    BOTTOM_EDGE_MIDPOINT,
    CORNER_BOTTOM_RIGHT,
    CORNER_TOP_LEFT,
    FACE_CENTER,
    HALF_DEPTH_MM,
    HALF_WIDTH_MM,
    HOLE_INSET_MM,
    PART_VIEW_X,
    PART_VIEW_Y,
    entity,
)
from solidworks_mcp.testing.pack_examples import load_example_pack
from solidworks_mcp.tools.registry import dispatch
from solidworks_mcp.utils import find_template

from .conftest import BRACKET_ASSEMBLY, BRACKET_PART, GENERATED_DIR

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(sys.platform != "win32", reason="requires Windows + SolidWorks"),
]


def _new_drawing():
    result = dispatch("new_drawing_from_template", {})
    assert result["success"], result["message"]
    return result


@pytest.fixture
def part_drawing_view():
    """A fresh drawing with the bracket part's *Front view already
    inserted at (PART_VIEW_X, PART_VIEW_Y) -- shared setup for tests whose subject
    is something *on* a view, not view creation itself. Function-scoped
    (recreated per test) so `_close_documents_after_test` can close it
    without disturbing any other test."""
    _new_drawing()
    result = dispatch("insert_model_view", {
        "model_path": str(BRACKET_PART), "view_name": "*Front",
        "x": PART_VIEW_X, "y": PART_VIEW_Y,
    })
    assert result["success"], result["message"]
    return result["data"]["view_name"]


@pytest.fixture
def assembly_drawing_view():
    """A fresh drawing with the two-component assembly's *Isometric view
    inserted -- setup for the BOM/balloon test."""
    _new_drawing()
    result = dispatch("insert_model_view", {
        "model_path": str(BRACKET_ASSEMBLY), "view_name": "*Isometric",
        "x": PART_VIEW_X, "y": PART_VIEW_Y,
    })
    assert result["success"], result["message"]
    return result["data"]["view_name"]


# ============================================================================
# Document / sheet creation
# ============================================================================

def test_create_drawing_from_template():
    result = _new_drawing()
    assert result["data"]["sheet_name"], result["message"]


def test_add_sheet():
    _new_drawing()
    result = dispatch("add_sheet", {"name": "Sheet2"})
    assert result["success"], result["message"]


# ============================================================================
# Views
# ============================================================================

def test_insert_model_view():
    _new_drawing()
    result = dispatch("insert_model_view", {
        "model_path": str(BRACKET_PART), "view_name": "*Front",
        "x": PART_VIEW_X, "y": PART_VIEW_Y,
    })
    assert result["success"], result["message"]
    assert result["data"]["view_name"]


def test_insert_section_view(part_drawing_view):
    # cut_points are in the parent view's own local coordinate space, not
    # sheet space -- a straight cut at local x=0 misses both hole columns
    # (holes sit at local x=+/-28mm).
    result = dispatch("insert_section_view", {
        "parent_view_name": part_drawing_view,
        "cut_points": [{"x": 0, "y": -HALF_DEPTH_MM}, {"x": 0, "y": HALF_DEPTH_MM}],
        "x": 250, "y": 100,
    })
    assert result["success"], (result["message"], result.get("data"))


def test_insert_detail_view(part_drawing_view):
    hole_x = HALF_WIDTH_MM - HOLE_INSET_MM
    hole_z = HALF_DEPTH_MM - HOLE_INSET_MM
    result = dispatch("insert_detail_view", {
        "parent_view_name": part_drawing_view,
        "center_x": hole_x, "center_y": hole_z, "radius": 15,
        "x": 250, "y": 250,
    })
    assert result["success"], (result["message"], result.get("data"))


def test_insert_model_items(part_drawing_view):
    result = dispatch("insert_model_items", {"view_name": part_drawing_view})
    # A zero-import result is still a documented success (see the tool's
    # own docstring) -- only an actual failure result is a real signal here.
    assert result["success"], result["message"]


# ============================================================================
# Annotations
# ============================================================================

def test_add_dimension(part_drawing_view):
    result = dispatch("add_dimension", {
        "view_name": part_drawing_view,
        "entities": [entity("vertex", *CORNER_BOTTOM_RIGHT), entity("vertex", *CORNER_TOP_LEFT)],
        "x": 200, "y": 60,
        "dimension_type": "smart",
    })
    assert result["success"], (result["message"], result.get("data"))
    assert result["data"]["name"]


def test_add_note(part_drawing_view):
    result = dispatch("add_note", {
        "text": "ALL DIMENSIONS IN MM\nUNLESS OTHERWISE SPECIFIED",
        "x": 20, "y": 20,
    })
    assert result["success"], result["message"]
    assert result["data"]["name"]


def test_add_property_note(part_drawing_view):
    result = dispatch("add_property_note", {
        "property_name": "PartNo", "x": 20, "y": 40,
        "source": "sheet", "prefix": "Part No: ",
    })
    assert result["success"], result["message"]


def test_add_datum_feature(part_drawing_view):
    result = dispatch("add_datum_feature", {
        "view_name": part_drawing_view,
        "entity": entity("edge", *BOTTOM_EDGE_MIDPOINT),
        "label": "A", "x": 0, "y": 90,
    })
    assert result["success"], (result["message"], result.get("data"))
    assert result["data"]["label"] == "A"


def test_add_gtol(part_drawing_view):
    # flatness is a form tolerance -- datums must be omitted for it (see
    # add_gtol's docstring), which sidesteps needing a datum feature to
    # already exist on the drawing.
    result = dispatch("add_gtol", {
        "view_name": part_drawing_view,
        "entity": entity("face", *FACE_CENTER),
        "symbol": "flatness", "tolerance": 0.05,
        "x": 150, "y": 60,
    })
    assert result["success"], (result["message"], result.get("data"))


# ============================================================================
# Tables
# ============================================================================

def test_insert_bom_table_with_balloons(assembly_drawing_view):
    bom_result = dispatch("insert_bom_table", {
        "view_name": assembly_drawing_view, "x": 250, "y": 60,
        "bom_type": "top_level",
    })
    assert bom_result["success"], (bom_result["message"], bom_result.get("data"))
    assert bom_result["data"]["row_count"] >= 2  # header + at least 1 item row

    balloon_result = dispatch("auto_balloon_view", {
        "view_name": assembly_drawing_view,
        "bom_table_name": bom_result["data"]["name"],
    })
    assert balloon_result["success"], (balloon_result["message"], balloon_result.get("data"))
    assert balloon_result["data"]["count"] >= 1


def test_insert_hole_table(part_drawing_view):
    result = dispatch("insert_hole_table", {
        "view_name": part_drawing_view,
        "datum_entity": entity("vertex", *CORNER_TOP_LEFT),
        "x": 250, "y": 60,
    })
    assert result["success"], (result["message"], result.get("data"))
    assert result["data"]["row_count"] >= 2  # header + at least 1 hole row


# ============================================================================
# Export
# ============================================================================

def test_export_pdf(part_drawing_view, created_files):
    output_path = GENERATED_DIR / "_test_export.pdf"
    created_files.append(output_path)
    output_path.unlink(missing_ok=True)  # a stale file from an interrupted prior run would
    # otherwise make the exists()/size assertions below pass against old, not fresh, output.
    result = dispatch("export_pdf", {"output_path": str(output_path)})
    assert result["success"], result["message"]
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_export_dxf(part_drawing_view, created_files):
    output_path = GENERATED_DIR / "_test_export.dxf"
    created_files.append(output_path)
    output_path.unlink(missing_ok=True)  # see test_export_pdf's comment
    result = dispatch("export_dxf_dwg", {"output_path": str(output_path), "format": "dxf"})
    assert result["success"], result["message"]
    assert output_path.exists()
    assert output_path.stat().st_size > 0


# ============================================================================
# Full pack
# ============================================================================

def test_create_drawing_pack_from_example(created_files):
    """Run one full create_drawing_pack from a docs/packs/ example, pointed
    at the generated assembly instead of the example's own placeholder
    Windows paths.

    The retargeting itself is `load_example_pack` (shared with
    scripts/validate_on_windows.py, which runs the same pack): the
    example's balloon annotations target hand-picked coordinates
    calibrated for its own (unrelated) gearbox model, meaningless against
    this fixture's geometry, so they are dropped while the BOM table
    (whose x/y are sheet placement, not an entity pick) stays and still
    exercises the pack's table machinery. docs/packs/assembly_with_bom.json
    itself is read-only here, never edited.
    """
    drawing_template = find_template("drawing")
    assert drawing_template, "no drawing template found on this SolidWorks install"

    output_path = GENERATED_DIR / "_test_pack_output.slddrw"
    created_files.append(output_path)

    spec = load_example_pack(
        "assembly_with_bom",
        model_path=BRACKET_ASSEMBLY,
        output_path=output_path,
        drawing_template=drawing_template,
    )

    result = dispatch("create_drawing_pack", {"spec": spec})
    assert result["success"], (result["message"], result["data"]["summary"])
    assert result["data"]["summary"]["sheets_created"] >= 1
    assert result["data"]["summary"]["views_inserted"] >= 1
