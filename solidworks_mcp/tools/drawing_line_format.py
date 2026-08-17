"""
Drawing Line Format / Drafting Standard Tools
-----------------------------------------------
set_line_format, get_line_format, apply_drafting_standard.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/05-export-and-layers.md's "Document line-format defaults" and
"Line format (per-entity, on a drawing)" sections.
"""

from typing import Dict

from ._automation import sw_automation
from .drawing_annotations import entity_ref_schema
from .registry import tool

_ENTITY_CLASSES = ["visible", "hidden", "section", "detail_circle", "dimension", "construction"]

_WEIGHT_SCHEMA = {
    "type": "string",
    "enum": ["none", "thin", "normal", "thick", "thick2", "thick3", "thick4",
             "thick5", "thick6", "number", "layer", "custom"],
    "description": "Line weight (swLineWeights_e). Omitted: unchanged.",
}

_STYLE_SCHEMA = {
    "type": "string",
    "enum": ["continuous", "hidden", "phantom", "chain", "center", "stitch",
             "chain_thick", "default"],
    "description": (
        "Line style (swLineStyles_e). Omitted: unchanged. 'default' is only valid "
        "when target is an explicit entity list, not a named entity class. For an "
        "explicit entity list, style is sent to SolidWorks as a Title-Cased display "
        "name (e.g. 'hidden' -> 'Hidden') -- confirmed correct for 'hidden' against "
        "official docs, but unverified for the others (status: unverified in "
        "docs/api/05-export-and-layers.md's IDrawingDoc::SetLineStyle record)."
    ),
}

_COLOR_SCHEMA = {
    "description": (
        "Line color: a '#RRGGBB'/'RRGGBB' hex string, or an [r, g, b] 0-255 "
        "triple. Only valid when target is an explicit entity list -- no "
        "per-category document color property exists for a named entity "
        "class. Omitted: unchanged."
    ),
    "oneOf": [
        {"type": "string"},
        {
            "type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
            "minItems": 3, "maxItems": 3,
        },
    ],
}

_TARGET_ENTITY_SCHEMA = entity_ref_schema("Entity kind: 'edge' (as returned by list_view_entities).")

_TARGET_SCHEMA = {
    "oneOf": [
        {
            "type": "string", "enum": _ENTITY_CLASSES,
            "description": "A named drafting-standard entity class -- sets/reads its document default.",
        },
        {
            "type": "array", "items": _TARGET_ENTITY_SCHEMA,
            "description": "Explicit entities to apply a per-entity override to.",
        },
    ],
    "description": (
        "Either a named entity class (" + ", ".join(_ENTITY_CLASSES) + "), or a "
        "non-empty list of entity references."
    ),
}


@tool(
    name="set_line_format",
    description=(
        "Set line weight/style/color, either as a document-wide drafting-"
        "standard default for a named entity class (visible/hidden/section/"
        "detail_circle/dimension/construction, via IModelDocExtension::"
        "SetUserPreferenceInteger -- weight/style only, color is rejected) "
        "or as a per-entity override on an explicit list of entity "
        "references (via IDrawingDoc::SetLineWidth/SetLineStyle/"
        "SetLineColor -- all three supported). view_name only applies to "
        "the entity-list form: it activates that view first. At least one "
        "of weight/style/color must be given."
    ),
    schema={
        "type": "object",
        "properties": {
            "target": _TARGET_SCHEMA,
            "weight": _WEIGHT_SCHEMA,
            "style": _STYLE_SCHEMA,
            "color": _COLOR_SCHEMA,
            "view_name": {
                "type": "string",
                "description": "Entity-list target only: view to activate first.",
            },
        },
        "required": ["target"],
    },
)
def set_line_format(arguments: dict) -> Dict:
    return sw_automation.set_line_format(
        arguments["target"],
        arguments.get("weight"),
        arguments.get("style"),
        arguments.get("color"),
        arguments.get("view_name"),
    )


@tool(
    name="get_line_format",
    description=(
        "Read back the current weight/style for a named drafting-standard "
        "entity class's document default (IModelDocExtension::"
        "GetUserPreferenceInteger). color is always null -- no such "
        "document property exists. Only a named entity class is accepted, "
        "not an explicit entity list -- SolidWorks has no documented "
        "per-entity line-format read-back API."
    ),
    schema={
        "type": "object",
        "properties": {
            "target": {
                "type": "string", "enum": _ENTITY_CLASSES,
                "description": "A named drafting-standard entity class.",
            },
            "view_name": {
                "type": "string",
                "description": "Accepted for symmetry with set_line_format; currently unused.",
            },
        },
        "required": ["target"],
    },
)
def get_line_format(arguments: dict) -> Dict:
    return sw_automation.get_line_format(arguments["target"], arguments.get("view_name"))


@tool(
    name="apply_drafting_standard",
    description=(
        "Read a JSON file mapping entity classes (visible/hidden/section/"
        "detail_circle/dimension/construction) to {weight, style} and apply "
        "every entry via set_line_format in one call -- see "
        "docs/drafting_standard.example.json for the expected shape. Fails "
        "with swInvalidInput (before any COM call) naming the bad key if "
        "the file isn't valid JSON, isn't a non-empty object, or contains "
        "an unrecognized entity class or property. data.results reports "
        "each entity class's own set_line_format outcome."
    ),
    schema={
        "type": "object",
        "properties": {
            "standard_file": {
                "type": "string",
                "description": "Path to a JSON drafting-standard file.",
            },
        },
        "required": ["standard_file"],
    },
)
def apply_drafting_standard(arguments: dict) -> Dict:
    return sw_automation.apply_drafting_standard(arguments["standard_file"])
