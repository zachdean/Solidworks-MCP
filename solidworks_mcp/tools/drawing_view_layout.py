"""
Drawing View Placement, Alignment, Display, and Deletion Tools
------------------------------------------------------------------
move_view, align_view, set_view_scale, set_view_display_mode, delete_view,
auto_arrange_views.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/02-views.md's "View properties" and "View naming, type, alignment,
and lifecycle" sections, plus that dossier's sw-8ww.6 addendum (GetOutline,
RemoveAlignment/UseDefaultAlignment, swViewAlignment_e, swDisplayMode_e).
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="move_view",
    description=(
        "Move a drawing view to an exact sheet-space position via "
        "IView::Position. If the view is aligned to a parent view (can "
        "only move along its alignment vector, per docs/api/02-views.md), "
        "this reports the lock with swFeatureError instead of silently "
        "moving it somewhere else or no-op'ing -- call align_view with "
        "alignment='break' first to free it."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the view to move (see list_views)",
            },
            "x": {"type": "number", "description": "New view center X, in set_units' unit"},
            "y": {"type": "number", "description": "New view center Y, in set_units' unit"},
            "sheet_name": {
                "type": "string",
                "description": "Sheet the view lives on; omit to use the active sheet",
            },
        },
        "required": ["view_name", "x", "y"],
    },
)
def move_view(arguments: dict) -> Dict:
    return sw_automation.move_view(
        arguments.get("view_name", ""),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("sheet_name"),
    )


@tool(
    name="align_view",
    description=(
        "Align a drawing view to a reference view via IView::AlignWithView, "
        "or break/reset its alignment via IView::RemoveAlignment/"
        "UseDefaultAlignment. alignment='none'/'break' is the escape hatch "
        "for move_view's alignment-lock refusal -- removes the alignment "
        "restriction so the view can be moved to an arbitrary position."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the view to align/un-align (see list_views)",
            },
            "reference_view_name": {
                "type": "string",
                "description": (
                    "Name of the view to align with. Required for horizontal/"
                    "vertical/horizontal_origin/vertical_origin; ignored for "
                    "default/none/break."
                ),
            },
            "alignment": {
                "type": "string", "default": "horizontal",
                "description": (
                    "horizontal, vertical, horizontal_origin, vertical_origin, "
                    "default, none, or break (case-insensitive) -- see tool description"
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet both views live on; omit to use the active sheet",
            },
        },
        "required": ["view_name"],
    },
)
def align_view(arguments: dict) -> Dict:
    return sw_automation.align_view(
        arguments.get("view_name", ""),
        arguments.get("reference_view_name"),
        arguments.get("alignment", "horizontal"),
        arguments.get("sheet_name"),
    )


@tool(
    name="set_view_scale",
    description=(
        "Set a drawing view's scale independently of the sheet scale, via "
        "IView::ScaleRatio + IView::UseSheetScale. scale_num/scale_denom "
        "must be given together (and are mutually exclusive with "
        "use_sheet_scale=True); use_sheet_scale=True links the view's "
        "scale back to the sheet's own scale instead."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the view to rescale (see list_views)",
            },
            "scale_num": {
                "type": "number",
                "description": "View scale numerator -- must be given with scale_denom",
            },
            "scale_denom": {
                "type": "number",
                "description": "View scale denominator -- must be given with scale_num",
            },
            "use_sheet_scale": {
                "type": "boolean", "default": False,
                "description": "True links this view's scale to the sheet scale, ignoring scale_num/scale_denom",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet the view lives on; omit to use the active sheet",
            },
        },
        "required": ["view_name"],
    },
)
def set_view_scale(arguments: dict) -> Dict:
    return sw_automation.set_view_scale(
        arguments.get("view_name", ""),
        arguments.get("scale_num"),
        arguments.get("scale_denom"),
        arguments.get("use_sheet_scale", False),
        arguments.get("sheet_name"),
    )


@tool(
    name="set_view_display_mode",
    description=(
        "Set a drawing view's display mode via IView::SetDisplayMode3. "
        "mode is wireframe, hidden-lines-visible, hidden-lines-removed, "
        "shaded, or shaded-with-edges. shadows maps to SetDisplayMode3's "
        "Edges parameter (edges shown when shaded); high_quality maps to "
        "the inverse of its Facetted parameter."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the view to update (see list_views)",
            },
            "mode": {
                "type": "string",
                "description": (
                    "wireframe, hidden-lines-visible, hidden-lines-removed, "
                    "shaded, or shaded-with-edges (case-insensitive)"
                ),
            },
            "shadows": {
                "type": "boolean", "default": False,
                "description": "SetDisplayMode3's Edges flag -- edges shown when in shaded mode",
            },
            "high_quality": {
                "type": "boolean", "default": True,
                "description": "True (default) requests precision-quality geometry; False requests draft-quality/faceted",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet the view lives on; omit to use the active sheet",
            },
        },
        "required": ["view_name", "mode"],
    },
)
def set_view_display_mode(arguments: dict) -> Dict:
    return sw_automation.set_view_display_mode(
        arguments.get("view_name", ""),
        arguments.get("mode", ""),
        arguments.get("shadows", False),
        arguments.get("high_quality", True),
        arguments.get("sheet_name"),
    )


@tool(
    name="delete_view",
    description=(
        "Delete a drawing view via select-then-IModelDocExtension::"
        "DeleteSelection2 (no dedicated DeleteView2 call exists). Refuses "
        "to delete a view with dependent child views (section/detail/"
        "projected/auxiliary views derived from it) unless cascade=True, "
        "in which case every descendant is deleted first (deepest first), "
        "then the named view -- data.removed lists every view actually "
        "removed, in deletion order."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the view to delete (see list_views)",
            },
            "cascade": {
                "type": "boolean", "default": False,
                "description": "True deletes dependent child views first instead of refusing",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet the view lives on; omit to use the active sheet",
            },
        },
        "required": ["view_name"],
    },
)
def delete_view(arguments: dict) -> Dict:
    return sw_automation.delete_view(
        arguments.get("view_name", ""),
        arguments.get("cascade", False),
        arguments.get("sheet_name"),
    )


@tool(
    name="auto_arrange_views",
    description=(
        "Lay out every view on a sheet with no overlapping bounding boxes, "
        "via IView::GetOutline + IView::Position -- deterministic grid/row "
        "packing (same input outlines always yield the same positions). "
        "Views are grouped by alignment root (IView::GetBaseView); only "
        "each group's root is repositioned directly, since an aligned "
        "child view can only move along its alignment vector -- SolidWorks "
        "carries aligned children along when their root moves, the same "
        "way dragging a base view in the UI drags its projected views. A "
        "view that is itself alignment-locked (IView::GetAlignment) with "
        "no GetBaseView parent -- e.g. explicitly aligned via align_view -- "
        "is left untouched and reported in data.locked rather than moved. "
        "The tool that makes a batch-generated view pack presentable."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": "Sheet to arrange; omit to use the active sheet",
            },
            "margin": {
                "type": "number",
                "description": "Spacing between packed view groups, in set_units' unit. Omit for a 10mm default.",
            },
        },
        "required": [],
    },
)
def auto_arrange_views(arguments: dict) -> Dict:
    return sw_automation.auto_arrange_views(
        arguments.get("sheet_name"),
        arguments.get("margin"),
    )
