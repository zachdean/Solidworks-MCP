"""
Drawing Annotation Tools
--------------------------
insert_model_items, add_dimension, add_ordinate_dimensions,
set_dimension_value, set_dimension_text, autodimension_view.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/03-annotations.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool

_ENTITY_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "Entity kind: 'edge', 'vertex', or 'face' (as returned by list_view_entities).",
        },
        "x": {"type": "number", "description": "Caller's default unit."},
        "y": {"type": "number", "description": "Caller's default unit."},
        "z": {"type": "number", "description": "Caller's default unit. Defaults to 0."},
    },
    "required": ["kind", "x", "y"],
}


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


@tool(
    name="add_dimension",
    description=(
        "Add a drawing-only reference dimension between picked entities in a "
        "view -- the fallback for anything DimXpert/insert_model_items didn't "
        "already carry over. dimension_type: 'smart' (default, SolidWorks "
        "infers the result from what's selected), 'horizontal', 'vertical', "
        "'radial', 'diameter', 'angular'. entities is a list of entity "
        "references in the shape list_view_entities returns. Fewer entities "
        "than the type needs (2 for horizontal/vertical/angular, 1 otherwise) "
        "fails before any SolidWorks call is made. Returns the created "
        "dimension's name (IDimension::FullName, usable as dimension_name in "
        "set_dimension_value/set_dimension_text) and its value in the current "
        "default unit."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entities live in."},
            "entities": {
                "type": "array", "items": _ENTITY_REF_SCHEMA,
                "description": "Entities to dimension between, as returned by list_view_entities.",
            },
            "x": {"type": "number", "description": "Dimension text/line placement, default unit."},
            "y": {"type": "number", "description": "Dimension text/line placement, default unit."},
            "dimension_type": {
                "type": "string", "default": "smart",
                "description": "'smart', 'horizontal', 'vertical', 'radial', 'diameter', or 'angular'.",
            },
        },
        "required": ["view_name", "entities", "x", "y"],
    },
)
def add_dimension(arguments: dict) -> Dict:
    return sw_automation.add_dimension(
        arguments.get("view_name"),
        arguments.get("entities"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("dimension_type", "smart"),
    )


@tool(
    name="add_ordinate_dimensions",
    description=(
        "Start a baseline/ordinate dimension chain off a datum origin via "
        "IModelDocExtension::AddOrdinateDimension. origin_entity is the datum "
        "point/edge; entities are the additional members of the group -- both "
        "in the entity-reference shape list_view_entities returns. direction: "
        "'horizontal' (default), 'vertical', 'angular', or 'auto' (orientation "
        "inferred from the selected points)."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entities live in."},
            "origin_entity": {
                **_ENTITY_REF_SCHEMA,
                "description": "Datum/origin entity the ordinate group is measured from.",
            },
            "entities": {
                "type": "array", "items": _ENTITY_REF_SCHEMA,
                "description": "Additional entities to include in the ordinate group.",
            },
            "x": {"type": "number", "description": "Dimension placement, default unit."},
            "y": {"type": "number", "description": "Dimension placement, default unit."},
            "direction": {
                "type": "string", "default": "horizontal",
                "description": "'horizontal' (default), 'vertical', 'angular', or 'auto'.",
            },
        },
        "required": ["view_name", "origin_entity", "entities", "x", "y"],
    },
)
def add_ordinate_dimensions(arguments: dict) -> Dict:
    return sw_automation.add_ordinate_dimensions(
        arguments.get("view_name"),
        arguments.get("origin_entity"),
        arguments.get("entities"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("direction", "horizontal"),
    )


@tool(
    name="set_dimension_value",
    description=(
        "Set a dimension's driving value via IDimension::SetSystemValue3 "
        "(meters at the COM boundary, converted from the caller's default "
        "unit). dimension_name is IDimension::FullName, e.g. as returned by "
        "add_dimension's data.name. Fails clearly (naming the reason -- e.g. "
        "dimension driven by geometry) rather than silently no-op-ing."
    ),
    schema={
        "type": "object",
        "properties": {
            "dimension_name": {
                "type": "string",
                "description": "IDimension::FullName, e.g. 'D1@Sketch1@Part1.SLDPRT'.",
            },
            "value": {"type": "number", "description": "New value, caller's default unit."},
        },
        "required": ["dimension_name", "value"],
    },
)
def set_dimension_value(arguments: dict) -> Dict:
    return sw_automation.set_dimension_value(
        arguments.get("dimension_name"),
        arguments.get("value"),
    )


@tool(
    name="set_dimension_text",
    description=(
        "Set a dimension's prefix/suffix/full-override text via "
        "IDisplayDimension::SetText -- for tolerance callouts and 'TYP'/'REF' "
        "annotations. At least one of prefix/suffix/override is required. "
        "override replaces the entire text and clears the suffix/live value "
        "display (a SolidWorks behavior, not a bug here) -- combining it with "
        "suffix in the same call is not a meaningful combination."
    ),
    schema={
        "type": "object",
        "properties": {
            "dimension_name": {
                "type": "string",
                "description": "IDimension::FullName, e.g. 'D1@Sketch1@Part1.SLDPRT'.",
            },
            "prefix": {"type": "string", "description": "Text before the dimension value."},
            "suffix": {"type": "string", "description": "Text after the dimension value."},
            "override": {"type": "string", "description": "Full replacement text."},
        },
        "required": ["dimension_name"],
    },
)
def set_dimension_text(arguments: dict) -> Dict:
    return sw_automation.set_dimension_text(
        arguments.get("dimension_name"),
        arguments.get("prefix"),
        arguments.get("suffix"),
        arguments.get("override"),
    )


@tool(
    name="autodimension_view",
    description=(
        "Bulk-dimension a drawing view via IDrawingDoc::AutoDimension -- a "
        "'just add reasonable baseline dimensions' fallback for a view with "
        "no usable DimXpert data. scheme: 'baseline' (default), 'ordinate', "
        "'chain'. entities: 'all' (default), 'based_on_preselect', 'selected'. "
        "horizontal_placement: 'above' (default) or 'below'. "
        "vertical_placement: 'left' (default) or 'right'. Fails clearly "
        "(naming the reason, e.g. no dimensionable entities) rather than a "
        "silent no-op."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to autodimension."},
            "scheme": {
                "type": "string", "default": "baseline",
                "description": "'baseline' (default), 'ordinate', or 'chain'.",
            },
            "entities": {
                "type": "string", "default": "all",
                "description": "'all' (default), 'based_on_preselect', or 'selected'.",
            },
            "horizontal_placement": {
                "type": "string", "default": "above",
                "description": "'above' (default) or 'below'.",
            },
            "vertical_placement": {
                "type": "string", "default": "left",
                "description": "'left' (default) or 'right'.",
            },
        },
        "required": ["view_name"],
    },
)
def autodimension_view(arguments: dict) -> Dict:
    return sw_automation.autodimension_view(
        arguments.get("view_name"),
        arguments.get("scheme", "baseline"),
        arguments.get("entities", "all"),
        arguments.get("horizontal_placement", "above"),
        arguments.get("vertical_placement", "left"),
    )
