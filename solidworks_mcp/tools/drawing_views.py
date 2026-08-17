"""
Drawing View Creation & Discovery Tools
-----------------------------------------
insert_model_view, insert_standard_3_view, list_views.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/02-views.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="insert_model_view",
    description=(
        "Place a model view on a drawing sheet via "
        "IDrawingDoc::CreateDrawViewFromModelView3. view_name accepts "
        "Front/Top/Right/Left/Bottom/Back/Isometric/Dimetric/Trimetric/"
        "Current (case-insensitive), mapped to the *Name form SolidWorks "
        "expects. Returns the created view's name for later view/"
        "annotation tools to target."
    ),
    schema={
        "type": "object",
        "properties": {
            "model_path": {
                "type": "string",
                "description": "Full pathname of the model document (.sldprt/.sldasm)",
            },
            "view_name": {
                "type": "string",
                "default": "*Front",
                "description": (
                    "Front, Top, Right, Left, Bottom, Back, Isometric, "
                    "Dimetric, Trimetric, or Current (case-insensitive, "
                    "with or without a leading *)"
                ),
            },
            "x": {"type": "number", "default": 0, "description": "View center X, in set_units' unit"},
            "y": {"type": "number", "default": 0, "description": "View center Y, in set_units' unit"},
            "sheet_name": {
                "type": "string",
                "description": "Sheet to place the view on; omit to use the active sheet",
            },
        },
        "required": ["model_path"],
    },
)
def insert_model_view(arguments: dict) -> Dict:
    return sw_automation.insert_model_view(
        arguments.get("model_path", ""),
        arguments.get("view_name", "*Front"),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("sheet_name"),
    )


@tool(
    name="insert_standard_3_view",
    description=(
        "Insert the standard three-view set via IDrawingDoc::"
        "Create3rdAngleViews2 (ANSI, default) or Create1stAngleViews2 "
        "(ISO, first_angle=True). Snapshots and restores the "
        "swAutomaticScaling3ViewDrawings user preference around the call."
    ),
    schema={
        "type": "object",
        "properties": {
            "model_path": {
                "type": "string",
                "description": "Full pathname of the model document (.sldprt/.sldasm)",
            },
            "first_angle": {
                "type": "boolean", "default": False,
                "description": "True for ISO/first-angle projection; False (default) for ANSI/third-angle",
            },
            "auto_scale": {
                "type": "boolean", "default": True,
                "description": "Value to write to swAutomaticScaling3ViewDrawings for the duration of this call",
            },
        },
        "required": ["model_path"],
    },
)
def insert_standard_3_view(arguments: dict) -> Dict:
    return sw_automation.insert_standard_3_view(
        arguments.get("model_path", ""),
        arguments.get("first_angle", False),
        arguments.get("auto_scale", True),
    )


@tool(
    name="list_views",
    description=(
        "Enumerate views on a drawing sheet via ISheet::GetViews -- name, "
        "type, scale, position, referenced model, and parent view. The "
        "discovery tool for addressing views by name in later view/"
        "annotation tools."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": "Sheet to enumerate; omit to use the active sheet",
            },
        },
        "required": [],
    },
)
def list_views(arguments: dict) -> Dict:
    return sw_automation.list_views(arguments.get("sheet_name"))
