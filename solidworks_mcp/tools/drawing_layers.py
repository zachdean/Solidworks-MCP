"""
Drawing Layer Tools
--------------------
create_layer, list_layers, set_current_layer, set_layer_properties,
move_annotations_to_layer.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/05-export-and-layers.md's Layers section (`ILayerMgr`/`ILayer`).
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool

_COLOR_SCHEMA = {
    "description": (
        "Layer line color: a '#RRGGBB'/'RRGGBB' hex string, or an [r, g, b] "
        "0-255 triple. Converted to the Win32 COLORREF integer SolidWorks "
        "expects (0x00BBGGRR -- blue in the high byte, red in the low byte, "
        "the reverse of the 0xRRGGBB order this argument itself uses). "
        "Omitted: black."
    ),
    "oneOf": [
        {"type": "string"},
        {
            "type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
            "minItems": 3, "maxItems": 3,
        },
    ],
}

_STYLE_SCHEMA = {
    "type": "string",
    "enum": ["continuous", "hidden", "phantom", "chain", "center", "stitch",
             "chain_thick", "default"],
    "description": "Line style (swLineStyles_e).",
}

_WIDTH_SCHEMA = {
    "type": "string",
    "enum": ["none", "thin", "normal", "thick", "thick2", "thick3", "thick4",
             "thick5", "thick6", "number", "layer", "custom"],
    "description": "Line width/weight (swLineWeights_e).",
}


@tool(
    name="create_layer",
    description=(
        "Create a new drawing layer via ILayerMgr::AddLayer, so generated "
        "dimensions/notes/reference geometry can be put on a named layer a "
        "drafting-standard or certification review can toggle "
        "independently. Fails with a clear error if name already exists "
        "(checked before any mutating call). visible/printable are applied "
        "after creation, visible first (setting Visible can change "
        "Printable as a side effect, so printable is re-applied second)."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "New layer's name. Must not already exist."},
            "description": {"type": "string", "default": "", "description": "Free-text layer description."},
            "color": _COLOR_SCHEMA,
            "style": _STYLE_SCHEMA,
            "width": _WIDTH_SCHEMA,
            "visible": {"type": "boolean", "default": True, "description": "ILayer::Visible."},
            "printable": {"type": "boolean", "default": True, "description": "ILayer::Printable."},
        },
        "required": ["name"],
    },
)
def create_layer(arguments: dict) -> Dict:
    return sw_automation.create_layer(
        arguments["name"],
        arguments.get("description", ""),
        arguments.get("color"),
        arguments.get("style"),
        arguments.get("width"),
        arguments.get("visible", True),
        arguments.get("printable", True),
    )


@tool(
    name="list_layers",
    description=(
        "Enumerate every layer in the active drawing via ILayerMgr::"
        "GetLayerList/GetLayer. Each record has name, description, "
        "visible, printable, color ('#RRGGBB'), style, and width."
    ),
    schema={"type": "object", "properties": {}, "required": []},
)
def list_layers(arguments: dict) -> Dict:
    return sw_automation.list_layers()


@tool(
    name="set_current_layer",
    description=(
        "Make an existing layer the active one via ILayerMgr::"
        "SetCurrentLayer, so subsequently created annotations land on it. "
        "Fails with swInvalidInput listing every existing layer if name "
        "does not match one."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Existing layer's name."},
        },
        "required": ["name"],
    },
)
def set_current_layer(arguments: dict) -> Dict:
    return sw_automation.set_current_layer(arguments["name"])


@tool(
    name="set_layer_properties",
    description=(
        "Partially update an existing layer's ILayer properties -- every "
        "argument left unset keeps that field exactly as it already was. "
        "printable is applied after visible (setting Visible can change "
        "Printable as a side effect, so an explicit printable always "
        "wins). Fails with swInvalidInput listing every existing layer if "
        "name does not match one. Returns the layer's full state after "
        "every requested change."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Existing layer's name."},
            "visible": {"type": "boolean", "description": "New ILayer::Visible. Omitted: unchanged."},
            "printable": {"type": "boolean", "description": "New ILayer::Printable. Omitted: unchanged."},
            "color": _COLOR_SCHEMA,
            "style": _STYLE_SCHEMA,
            "width": _WIDTH_SCHEMA,
        },
        "required": ["name"],
    },
)
def set_layer_properties(arguments: dict) -> Dict:
    return sw_automation.set_layer_properties(
        arguments["name"],
        arguments.get("visible"),
        arguments.get("printable"),
        arguments.get("color"),
        arguments.get("style"),
        arguments.get("width"),
    )


@tool(
    name="move_annotations_to_layer",
    description=(
        "Bulk-assign existing annotations to a layer via IAnnotation::"
        "Layer -- what makes a generated dimension/note/GD&T pack "
        "reviewable by a drafting-standard pass that toggles layers. "
        "view_name restricts to one view (omitted: every view in the "
        "document). annotation_types restricts to a subset of 'note', "
        "'datum_tag', 'table', 'dimension' (omitted: all four) -- GTols "
        "and weld symbols have no per-view enumeration in this tool layer "
        "yet, so are not movable by this tool. Fails with swInvalidInput "
        "listing every existing layer if layer_name does not match one. "
        "Reports how many annotations were moved, per type."
    ),
    schema={
        "type": "object",
        "properties": {
            "layer_name": {"type": "string", "description": "Existing layer's name."},
            "view_name": {
                "type": "string",
                "description": "Restrict to annotations attached to this one view. Omitted: every view.",
            },
            "annotation_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["note", "datum_tag", "table", "dimension"]},
                "description": "Subset of annotation families to move. Omitted: all four.",
            },
        },
        "required": ["layer_name"],
    },
)
def move_annotations_to_layer(arguments: dict) -> Dict:
    return sw_automation.move_annotations_to_layer(
        arguments["layer_name"],
        arguments.get("view_name"),
        arguments.get("annotation_types"),
    )
