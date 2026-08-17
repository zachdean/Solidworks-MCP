"""
Drawing Annotation Tools
--------------------------
insert_model_items.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/03-annotations.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="insert_model_items",
    description=(
        "Import model annotations (dimensions, datums, GTols, surface "
        "finishes, weld symbols, notes, hole callouts, ...) onto a drawing "
        "view via IDrawingDoc::InsertModelAnnotations4 -- the fastest route "
        "to a fully dimensioned view for a part modeled with driving "
        "dimensions or DimXpert. Pass exactly one of view_name (a specific "
        "view) or all_views=True (every view on the active sheet, with "
        "per-view counts reported). Reports how many annotations were "
        "actually imported per view -- a zero-import result is still a "
        "warned success, not a bare 'success' with nothing to show for it. "
        "Note: center marks/centerlines are NOT importable through this "
        "tool (swInsertAnnotation_e has no bit for them) -- use the "
        "dedicated center mark/centerline tools instead."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": (
                    "Name of the drawing view to import into (see "
                    "list_views). Mutually exclusive with all_views -- "
                    "exactly one of the two is required."
                ),
            },
            "sources": {
                "type": "string",
                "default": "model",
                "description": (
                    "Where the annotations come from: 'model' (default, "
                    "all dimensions in the view), 'selected_feature', "
                    "'selected_component' (assembly drawings), or "
                    "'assembly_only'."
                ),
            },
            "types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Annotation types to import: 'dimensions', 'datums', "
                    "'datum_targets', 'gtols', 'surface_finishes', 'welds', "
                    "'notes', 'hole_callouts', 'cosmetic_threads', "
                    "'instance_counts'. Omit for the default: dimensions "
                    "+ hole_callouts."
                ),
            },
            "all_views": {
                "type": "boolean", "default": False,
                "description": (
                    "True to import into every view on the active sheet "
                    "(one call per view, per-view counts reported). "
                    "Mutually exclusive with view_name."
                ),
            },
            "eliminate_duplicates": {
                "type": "boolean", "default": True,
                "description": "True (default) to eliminate duplicate dimensions",
            },
            "hidden_features": {
                "type": "boolean", "default": False,
                "description": "True to also insert dimensions from hidden features",
            },
        },
        "required": [],
    },
)
def insert_model_items(arguments: dict) -> Dict:
    return sw_automation.insert_model_items(
        arguments.get("view_name"),
        arguments.get("sources"),
        arguments.get("types"),
        arguments.get("all_views", False),
        arguments.get("eliminate_duplicates", True),
        arguments.get("hidden_features", False),
    )
