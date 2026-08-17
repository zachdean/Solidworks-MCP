"""
Drawing View Creation & Discovery Tools
-----------------------------------------
insert_model_view, insert_standard_3_view, insert_projected_view,
insert_predefined_views, insert_auxiliary_view, insert_section_view,
insert_detail_view, insert_broken_out_section, list_views.

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
    name="insert_section_view",
    description=(
        "Insert a section view off an existing drawing view via "
        "IDrawingDoc::CreateSectionViewAt5. Owns the whole sequence: "
        "activates parent_view_name, sketches cut_points as line segments "
        "(N-1 segments for N points -- 2 points is a straight cut, 3+ is "
        "offset/stepped) via the sketch manager in the parent view's own "
        "coordinate space, selects them, creates the view, then configures "
        "it. section_type is full (default), aligned "
        "(swCreateSectionView_OffsetSection), or half "
        "(swCreateSectionView_Partial -- SolidWorks has no true half-section "
        "flag under any name; this is the closest documented behavior, and "
        "is only valid with a straight 2-point cut). auto_hatch and "
        "display_only are applied post-creation via IDrSection::SetAutoHatch "
        "/SetDisplayOnlySurfaceCut -- display_only is NOT a true 'no "
        "material cut' toggle (none exists in this API), only the closest "
        "named setting (surface-body cut display). use_sheet_scale sets "
        "IView::UseSheetScale afterward. Section scope (excluding "
        "components/ribs from an assembly's cut) is out of scope for this "
        "tool -- SolidWorks does not pop a dialog for it during API-driven "
        "creation, since IDrSection exposes that state programmatically, so "
        "no user-preference toggle is touched. Fewer than 2 cut_points, or "
        "fewer than 2 distinct points, fails before any COM call."
    ),
    schema={
        "type": "object",
        "properties": {
            "parent_view_name": {
                "type": "string",
                "description": "Name of the existing drawing view to cut (see list_views)",
            },
            "cut_points": {
                "type": "array",
                "description": (
                    "2+ points [x, y] (or {'x':.., 'y':..}) in the parent view's "
                    "coordinate space, in set_units' unit. 2 points = straight cut; "
                    "3+ = offset/stepped cut."
                ),
                "items": {"type": "object"},
                "minItems": 2,
            },
            "x": {"type": "number", "description": "Section view placement X on the sheet, in set_units' unit"},
            "y": {"type": "number", "description": "Section view placement Y on the sheet, in set_units' unit"},
            "label": {
                "type": "string",
                "description": "Section label letter, e.g. 'A'. Omit to let SolidWorks auto-assign one.",
            },
            "flip_direction": {
                "type": "boolean", "default": False,
                "description": "True switches which side of the cut line the section looks toward",
            },
            "section_type": {
                "type": "string", "default": "full",
                "description": "full, aligned, or half (case-insensitive) -- see tool description",
            },
            "auto_hatch": {
                "type": "boolean", "default": True,
                "description": "IDrSection::SetAutoHatch after creation (assembly section views only)",
            },
            "display_only": {
                "type": "boolean", "default": False,
                "description": "IDrSection::SetDisplayOnlySurfaceCut after creation (surface bodies only)",
            },
            "use_sheet_scale": {
                "type": "boolean", "default": True,
                "description": "IView::UseSheetScale after creation",
            },
        },
        "required": ["parent_view_name", "cut_points", "x", "y"],
    },
)
def insert_section_view(arguments: dict) -> Dict:
    return sw_automation.insert_section_view(
        arguments.get("parent_view_name", ""),
        arguments.get("cut_points", []),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("label"),
        arguments.get("flip_direction", False),
        arguments.get("section_type", "full"),
        arguments.get("auto_hatch", True),
        arguments.get("display_only", False),
        arguments.get("use_sheet_scale", True),
    )


@tool(
    name="insert_detail_view",
    description=(
        "Insert a detail view off a circular region of an existing drawing "
        "view via IDrawingDoc::CreateDetailViewAt4 (requested as "
        "CreateDetailViewAt5, which does not exist -- At4 is the current "
        "highest overload). Owns the whole sequence: activates "
        "parent_view_name, sketches the detail circle at "
        "center_x/center_y/radius via ISketchManager::CreateCircleByRadius, "
        "selects it, creates the view. style is circle (default), profile, "
        "or none -- despite the name this binds to CreateDetailViewAt4's "
        "Showtype parameter (swDetCircleShowType_e), not its separate "
        "border/leader-look Style parameter (always swDetViewSTANDARD, not "
        "exposed). scale_num/scale_denom must be given together or both "
        "omitted; omitted defaults to the parent view's own scale. A "
        "non-positive radius fails before any COM call. On any failure "
        "after the circle is sketched, it is deleted so no stray "
        "construction sketch is left on the sheet."
    ),
    schema={
        "type": "object",
        "properties": {
            "parent_view_name": {
                "type": "string",
                "description": "Name of the existing drawing view to detail (see list_views)",
            },
            "center_x": {"type": "number", "description": "Detail circle center X, in the parent view's space, in set_units' unit"},
            "center_y": {"type": "number", "description": "Detail circle center Y, in the parent view's space, in set_units' unit"},
            "radius": {"type": "number", "description": "Detail circle radius, in set_units' unit (must be positive)"},
            "x": {"type": "number", "description": "Detail view placement X on the sheet, in set_units' unit"},
            "y": {"type": "number", "description": "Detail view placement Y on the sheet, in set_units' unit"},
            "label": {
                "type": "string",
                "description": "Detail view label letter, e.g. 'A'. Omit for an empty label.",
            },
            "scale_num": {
                "type": "number",
                "description": "Detail view scale numerator -- must be given with scale_denom, or both omitted",
            },
            "scale_denom": {
                "type": "number",
                "description": "Detail view scale denominator -- must be given with scale_num, or both omitted",
            },
            "style": {
                "type": "string", "default": "circle",
                "description": "circle, profile, or none (case-insensitive) -- see tool description",
            },
            "full_outline": {
                "type": "boolean", "default": False,
                "description": "CreateDetailViewAt4's FullOutline flag",
            },
        },
        "required": ["parent_view_name", "center_x", "center_y", "radius", "x", "y"],
    },
)
def insert_detail_view(arguments: dict) -> Dict:
    return sw_automation.insert_detail_view(
        arguments.get("parent_view_name", ""),
        arguments.get("center_x", 0),
        arguments.get("center_y", 0),
        arguments.get("radius", 0),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("label"),
        arguments.get("scale_num"),
        arguments.get("scale_denom"),
        arguments.get("style", "circle"),
        arguments.get("full_outline", False),
    )


@tool(
    name="insert_broken_out_section",
    description=(
        "Insert a broken-out section on an existing drawing view via "
        "IDrawingDoc::CreateBreakOutSection (requested as IView::"
        "InsertBrokenOutSection, which does not exist). Owns the whole "
        "sequence: activates parent_view_name, sketches profile_points as a "
        "closed loop of line segments (auto-closed -- the last point "
        "connects back to the first), selects them, creates the section. "
        "Exactly one of depth or depth_reference is required: depth is a "
        "plain numeric depth; depth_reference selects a geometry reference "
        "(default type 'FACE') and applies it afterward via "
        "IBrokenOutSectionFeatureData::DepthReference (CreateBreakOutSection "
        "itself has no reference-depth parameter). preview=True sketches "
        "and validates the profile then deletes it without ever calling "
        "CreateBreakOutSection -- a dry run, not backed by a real COM "
        "'preview' concept. Fewer than 3 profile_points, or fewer than 3 "
        "distinct points, fails before any COM call. On any failure after "
        "the profile is sketched, it is deleted so no stray construction "
        "sketch is left on the sheet."
    ),
    schema={
        "type": "object",
        "properties": {
            "parent_view_name": {
                "type": "string",
                "description": "Name of the existing drawing view to break open (see list_views)",
            },
            "profile_points": {
                "type": "array",
                "description": (
                    "3+ points [x, y] (or {'x':.., 'y':..}) in the parent view's "
                    "coordinate space, in set_units' unit -- the closed profile "
                    "boundary (auto-closed; a pre-closed chain is also accepted)."
                ),
                "items": {"type": "object"},
                "minItems": 3,
            },
            "depth": {
                "type": "number",
                "description": "Material-removal depth, in set_units' unit. Exactly one of depth/depth_reference is required.",
            },
            "depth_reference": {
                "type": "object",
                "description": "Sheet-space point selecting the depth-reference geometry. Exactly one of depth/depth_reference is required.",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number", "default": 0},
                    "type": {"type": "string", "default": "FACE"},
                },
                "required": ["x", "y"],
            },
            "preview": {
                "type": "boolean", "default": False,
                "description": "True validates and sketches the profile but never calls CreateBreakOutSection (dry run)",
            },
        },
        "required": ["parent_view_name", "profile_points"],
    },
)
def insert_broken_out_section(arguments: dict) -> Dict:
    return sw_automation.insert_broken_out_section(
        arguments.get("parent_view_name", ""),
        arguments.get("profile_points", []),
        arguments.get("depth"),
        arguments.get("depth_reference"),
        arguments.get("preview", False),
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
