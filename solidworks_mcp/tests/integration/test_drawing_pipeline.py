"""
Windows integration: drawing pipeline (sw-17y.1)
--------------------------------------------------
Exercises the drawing-side tool surface end-to-end against the real
geometry `scripts/make_test_geometry.py` produces (see conftest.py for how
that's located, and how the whole module skips cleanly without it).

Geometry recap -- must match scripts/make_test_geometry.py's constants of
the same name: a bracket with an 80x50mm base (X x Z), 20mm tall, 4
mounting holes inset 12mm from each edge, a 3mm fillet on the (+X, +Z)
corner, and a 2mm 45-degree chamfer on the (-X, -Z) corner. The two
remaining corners, (+X, -Z) and (-X, +Z), are untouched -- tests that need
a stable vertex/edge target use those instead of a modified corner, so a
SelectByID2 proximity pick doesn't land on a fillet arc or a chamfer edge
that wasn't there when the coordinate was chosen.

Coordinate convention: every x/y this module passes to place or pick
something is SHEET-space millimeters -- the same convention
`insert_model_view`'s own x/y use ("sheet-space meters"). A point on the
bracket's *Front view, placed at (_VIEW_X, _VIEW_Y) with the sheet's
default 1:1 scale, appears on the sheet at
`(_VIEW_X + local_x, _VIEW_Y + local_z)`: Front looks straight down at the
sketch plane, so the view's on-sheet layout matches the part's local (X, Z)
directly. `_sheet_point()` below is that mapping; `insert_section_view`/
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
import copy
import json
import sys

import pytest

from solidworks_mcp.tools.registry import dispatch
from solidworks_mcp.utils import find_template

from .conftest import BRACKET_ASSEMBLY, BRACKET_PART, GENERATED_DIR, REPO_ROOT

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(sys.platform != "win32", reason="requires Windows + SolidWorks"),
]

# Must match scripts/make_test_geometry.py.
_HALF_WIDTH_MM = 40.0  # BASE_WIDTH_MM / 2
_HALF_DEPTH_MM = 25.0  # BASE_DEPTH_MM / 2
_HOLE_INSET_MM = 12.0

_VIEW_X, _VIEW_Y = 100.0, 100.0

# Untouched corners (neither the filleted (+X,+Z) nor the chamfered (-X,-Z)
# corner) -- stable vertex targets for entity-picking tests.
_CORNER_BOTTOM_RIGHT = (_HALF_WIDTH_MM, -_HALF_DEPTH_MM)
_CORNER_TOP_LEFT = (-_HALF_WIDTH_MM, _HALF_DEPTH_MM)
_BOTTOM_EDGE_MIDPOINT = (0.0, -_HALF_DEPTH_MM)
_FACE_CENTER = (0.0, 0.0)  # clear of all 4 holes (each inset 12mm from an edge)


def _sheet_point(local_x, local_z):
    return _VIEW_X + local_x, _VIEW_Y + local_z


def _vertex(local_x, local_z):
    x, y = _sheet_point(local_x, local_z)
    return {"kind": "vertex", "x": x, "y": y}


def _edge(local_x, local_z):
    x, y = _sheet_point(local_x, local_z)
    return {"kind": "edge", "x": x, "y": y}


def _face(local_x, local_z):
    x, y = _sheet_point(local_x, local_z)
    return {"kind": "face", "x": x, "y": y}


def _new_drawing():
    result = dispatch("new_drawing_from_template", {})
    assert result["success"], result["message"]
    return result


@pytest.fixture
def part_drawing_view():
    """A fresh drawing with the bracket part's *Front view already
    inserted at (_VIEW_X, _VIEW_Y) -- shared setup for tests whose subject
    is something *on* a view, not view creation itself. Function-scoped
    (recreated per test) so `_close_documents_after_test` can close it
    without disturbing any other test."""
    _new_drawing()
    result = dispatch("insert_model_view", {
        "model_path": str(BRACKET_PART), "view_name": "*Front",
        "x": _VIEW_X, "y": _VIEW_Y,
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
        "x": _VIEW_X, "y": _VIEW_Y,
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
        "x": _VIEW_X, "y": _VIEW_Y,
    })
    assert result["success"], result["message"]
    assert result["data"]["view_name"]


def test_insert_section_view(part_drawing_view):
    # cut_points are in the parent view's own local coordinate space, not
    # sheet space -- a straight cut at local x=0 misses both hole columns
    # (holes sit at local x=+/-28mm).
    result = dispatch("insert_section_view", {
        "parent_view_name": part_drawing_view,
        "cut_points": [{"x": 0, "y": -_HALF_DEPTH_MM}, {"x": 0, "y": _HALF_DEPTH_MM}],
        "x": 250, "y": 100,
    })
    assert result["success"], (result["message"], result.get("data"))


def test_insert_detail_view(part_drawing_view):
    hole_x = _HALF_WIDTH_MM - _HOLE_INSET_MM
    hole_z = _HALF_DEPTH_MM - _HOLE_INSET_MM
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
        "entities": [_vertex(*_CORNER_BOTTOM_RIGHT), _vertex(*_CORNER_TOP_LEFT)],
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
        "entity": _edge(*_BOTTOM_EDGE_MIDPOINT),
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
        "entity": _face(*_FACE_CENTER),
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
        "datum_entity": _vertex(*_CORNER_TOP_LEFT),
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

    The example's balloon annotations target hand-picked coordinates
    calibrated for its own (unrelated) gearbox model, meaningless against
    this fixture's geometry -- this test drops them and keeps the BOM
    table (whose x/y are sheet placement, not an entity pick) to still
    exercise the pack's table machinery without guessing coordinates that
    would never land on real geometry. docs/packs/assembly_with_bom.json
    itself is read-only here, never edited.
    """
    example_path = REPO_ROOT / "docs" / "packs" / "assembly_with_bom.json"
    spec = copy.deepcopy(json.loads(example_path.read_text(encoding="utf-8")))

    drawing_template = find_template("drawing")
    assert drawing_template, "no drawing template found on this SolidWorks install"

    output_path = GENERATED_DIR / "_test_pack_output.slddrw"
    created_files.append(output_path)

    spec["drawing_template"] = drawing_template
    spec["output"] = str(output_path)
    sheet = spec["sheets"][0]
    sheet["model_path"] = str(BRACKET_ASSEMBLY)
    sheet["views"][0]["model_path"] = str(BRACKET_ASSEMBLY)
    sheet["annotations"] = []

    result = dispatch("create_drawing_pack", {"spec": spec})
    assert result["success"], (result["message"], result["data"]["summary"])
    assert result["data"]["summary"]["sheets_created"] >= 1
    assert result["data"]["summary"]["views_inserted"] >= 1
