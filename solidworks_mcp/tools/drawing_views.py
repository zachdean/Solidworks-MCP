"""
Drawing View Creation & Discovery Tools
-----------------------------------------
insert_model_view, insert_standard_3_view, insert_projected_view,
insert_predefined_views, insert_auxiliary_view, list_views.

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
    name="insert_projected_view",
    description=(
        "Project a new drawing view off an existing one via "
        "IDrawingDoc::CreateUnfoldedViewAt3 -- the API's real name for "
        "the UI's 'Insert Projected View' (no *Project*-named method "
        "exists on IDrawingDoc/IView). Selects parent_view_name first, "
        "then projects in the given direction. Cardinal directions "
        "(up/down/left/right) stay orthographically aligned to the "
        "parent; diagonals break alignment to be freely positioned "
        "off-axis. Inherits the parent's scale -- nothing here changes "
        "it. offset moves the new view to an exact distance from the "
        "parent afterward via the IView::Position setter."
    ),
    schema={
        "type": "object",
        "properties": {
            "parent_view_name": {
                "type": "string",
                "description": "Name of the existing drawing view to project from (see list_views)",
            },
            "direction": {
                "type": "string",
                "description": (
                    "up, down, left, right, upleft, upright, downleft, "
                    "or downright (case-insensitive)"
                ),
            },
            "offset": {
                "type": "number",
                "description": (
                    "Distance from the parent view's center to the new view's "
                    "center, in set_units' unit. Omit to use a small default nudge."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet the parent view lives on; omit to use the active sheet",
            },
        },
        "required": ["parent_view_name", "direction"],
    },
)
def insert_projected_view(arguments: dict) -> Dict:
    return sw_automation.insert_projected_view(
        arguments.get("parent_view_name", ""),
        arguments.get("direction", ""),
        arguments.get("offset"),
        arguments.get("sheet_name"),
    )


@tool(
    name="insert_predefined_views",
    description=(
        "Fill every predefined-view placeholder on a sheet via "
        "IDrawingDoc::InsertModelInPredefinedView. Predefined views are "
        "placeholders pre-positioned/pre-configured on a drawing template "
        "beforehand (Insert > Drawing View > Predefined) -- this only "
        "fills existing placeholders, it does not create them. Returns "
        "which placeholders were filled; errors clearly if the sheet has "
        "no predefined-view placeholders."
    ),
    schema={
        "type": "object",
        "properties": {
            "model_path": {
                "type": "string",
                "description": "Full pathname of the model document (.sldprt/.sldasm)",
            },
            "sheet_name": {
                "type": "string",
                "description": (
                    "Sheet to target, activated first. Omit to use the "
                    "active sheet -- only the last-active sheet's "
                    "placeholders get filled."
                ),
            },
        },
        "required": ["model_path"],
    },
)
def insert_predefined_views(arguments: dict) -> Dict:
    return sw_automation.insert_predefined_views(
        arguments.get("model_path", ""),
        arguments.get("sheet_name"),
    )


@tool(
    name="insert_auxiliary_view",
    description=(
        "Insert an auxiliary view off an edge of an existing view via "
        "IDrawingDoc::CreateAuxiliaryViewAt2 -- unlike 'projected view,' "
        "this UI action's real API name matches. edge_selection is a "
        "sheet-space point on the reference edge (in set_units' unit), "
        "selected before the call since CreateAuxiliaryViewAt2 takes no "
        "edge parameter of its own; parent_view_name is validated against "
        "the sheet's actual views for a clear error, though the call "
        "itself operates purely off the selected edge."
    ),
    schema={
        "type": "object",
        "properties": {
            "parent_view_name": {
                "type": "string",
                "description": "Name of the view the reference edge belongs to (see list_views)",
            },
            "edge_selection": {
                "type": "object",
                "description": "Sheet-space point on the reference edge to select",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number", "default": 0},
                },
                "required": ["x", "y"],
            },
            "x": {"type": "number", "description": "New view center X, in set_units' unit"},
            "y": {"type": "number", "description": "New view center Y, in set_units' unit"},
            "label": {"type": "string", "default": "", "description": "Auxiliary view letter label, e.g. 'A'"},
            "flip": {
                "type": "boolean", "default": False,
                "description": "True flips which side of the reference edge the view projects toward",
            },
            "not_aligned": {
                "type": "boolean", "default": False,
                "description": "True breaks alignment with the parent view",
            },
            "show_arrow": {
                "type": "boolean", "default": True,
                "description": "True shows the projection arrow on the parent view",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet the parent view lives on; omit to use the active sheet",
            },
        },
        "required": ["parent_view_name", "edge_selection", "x", "y"],
    },
)
def insert_auxiliary_view(arguments: dict) -> Dict:
    return sw_automation.insert_auxiliary_view(
        arguments.get("parent_view_name", ""),
        arguments.get("edge_selection", {}),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("label", ""),
        arguments.get("flip", False),
        arguments.get("not_aligned", False),
        arguments.get("show_arrow", True),
        arguments.get("sheet_name"),
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
