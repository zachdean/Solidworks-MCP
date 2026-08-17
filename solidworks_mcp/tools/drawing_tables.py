"""
Drawing Table Tools
--------------------
insert_bom_table, list_tables, get_bom_contents, auto_balloon_view,
add_balloon, renumber_balloons, remove_balloons.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/04-tables.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool

# `add_balloon`'s `entity` shape -- the same `list_view_entities` shape every
# other entity-taking tool advertises (see drawing_annotations.py's
# `_ENTITY_REF_SCHEMA`), plus `"component"` for the normal "balloon an
# assembly component instance" case, which `list_view_entities` never emits
# itself. Declared locally rather than imported from drawing_annotations.py:
# that module's shared schema is deliberately scoped to what
# `list_view_entities` returns plus `"dimension"` (its own docstring explains
# why), and `"component"` doesn't belong on that shared copy.
_BALLOON_ENTITY_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": (
                "Entity kind: 'edge', 'vertex', or 'face' (as returned by "
                "list_view_entities), or 'component' -- the normal case for "
                "ballooning an assembly component instance, which "
                "list_view_entities does not itself emit."
            ),
        },
        "x": {"type": "number", "description": "Caller's default unit."},
        "y": {"type": "number", "description": "Caller's default unit."},
        "z": {"type": "number", "description": "Caller's default unit. Defaults to 0."},
    },
    "required": ["kind", "x", "y"],
}

_HIDDEN_COLUMNS_SCHEMA = {
    "type": "array",
    "items": {"type": "integer"},
    "description": (
        "0-based column indices to hide after creation, via "
        "ITableAnnotation::ColumnHidden."
    ),
}


@tool(
    name="insert_bom_table",
    description=(
        "Insert a BOM table onto a drawing view via IView::InsertBomTable6. "
        "bom_type: 'top_level' (default), 'parts_only', or 'indented' -- "
        "'top_level' must not be combined with configuration (use "
        "IBomFeature::GetConfigurations/SetConfigurations instead); the "
        "other two require it. Anchor mode and x/y mode are mutually "
        "exclusive: pass attach_to_anchor=True with anchor set to snap to "
        "the sheet format's BOM anchor point, or leave attach_to_anchor "
        "False (default) and use x/y -- passing anchor without "
        "attach_to_anchor=True, or attach_to_anchor=True without anchor, "
        "both fail. template_path falls back to the SolidWorks default "
        ".sldbomtbt template when omitted, erroring with swTemplateNotFound "
        "if none can be found. view_name defaults to the first view on the "
        "active sheet. Returns the created table's name, row_count, and "
        "column_count for balloon/update tools to address it by."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Drawing view to attach the table to. Omitted: the first view on the active sheet.",
            },
            "template_path": {
                "type": "string",
                "description": "Path to a .sldbomtbt template. Omitted: auto-discovered default.",
            },
            "x": {"type": "number", "default": 0, "description": "Placement, caller's default unit. Used only when attach_to_anchor=False."},
            "y": {"type": "number", "default": 0, "description": "Placement, caller's default unit. Used only when attach_to_anchor=False."},
            "bom_type": {
                "type": "string", "default": "top_level",
                "description": "'top_level', 'parts_only', or 'indented'.",
            },
            "configuration": {
                "type": "string",
                "description": "Configuration name. Required for 'parts_only'/'indented'; must be omitted for 'top_level'.",
            },
            "anchor": {
                "type": "string",
                "description": "'top_left', 'top_right', 'bottom_left', or 'bottom_right'. Required when attach_to_anchor=True; must be omitted otherwise.",
            },
            "attach_to_anchor": {
                "type": "boolean", "default": False,
                "description": "True to snap to the sheet format's BOM anchor point instead of x/y.",
            },
            "detailed_cut_list": {
                "type": "boolean", "default": False,
                "description": "True to show the detailed cut list.",
            },
            "hidden_columns": _HIDDEN_COLUMNS_SCHEMA,
        },
        "required": [],
    },
)
def insert_bom_table(arguments: dict) -> Dict:
    return sw_automation.insert_bom_table(
        arguments.get("view_name"),
        arguments.get("template_path"),
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("bom_type", "top_level"),
        arguments.get("configuration"),
        arguments.get("anchor"),
        arguments.get("attach_to_anchor", False),
        arguments.get("detailed_cut_list", False),
        arguments.get("hidden_columns"),
    )


@tool(
    name="list_tables",
    description=(
        "Enumerate every table annotation (BOM, hole, revision, weldment "
        "cut list, general, title block, ...) via IView::"
        "GetFirstTableAnnotation/ITableAnnotation::GetNext. sheet_name "
        "restricts to one sheet's tables (its real views plus its "
        "sheet-level/title-block table); omitted: every table in the whole "
        "document. Each record has type, name, position (x/y), view_name, "
        "and row_count/column_count (a table's size -- tables have no "
        "overall width/height property)."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {"type": "string", "description": "Restrict to this sheet's tables."},
        },
        "required": [],
    },
)
def list_tables(arguments: dict) -> Dict:
    return sw_automation.list_tables(
        arguments.get("sheet_name"),
    )


@tool(
    name="get_bom_contents",
    description=(
        "Read a BOM table's cell text back via ITableAnnotation::Text2, so "
        "an LLM can verify an assembly drawing's BOM without opening "
        "SolidWorks. table_name is IAnnotation::GetName's value, as "
        "returned by insert_bom_table's data.name or list_tables' "
        "data.tables[i].name. Returns rows (including the header row at "
        "index 0), each row_count x column_count cell strings. Fails if no "
        "table has that name, or if it isn't a BOM table."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the target BOM table.",
            },
        },
        "required": ["table_name"],
    },
)
def get_bom_contents(arguments: dict) -> Dict:
    return sw_automation.get_bom_contents(
        arguments.get("table_name"),
    )


@tool(
    name="auto_balloon_view",
    description=(
        "Auto-balloon an entire drawing view via IDrawingDoc::"
        "CreateAutoBalloonOptions + AutoBalloon5 -- the common case; use "
        "add_balloon for the one-off single-balloon case instead. "
        "layout: 'square' (default), 'circle', 'top', 'bottom', 'right', "
        "or 'left'. style: 'circular' (default), 'triangle', 'hexagon', "
        "'box', 'diamond', 'pentagon', 'split_circle', 'flag_pentagon', "
        "'flag_triangle', 'underline', 'square', 's_circle', 'inspection', "
        "'arc_bracket', 'rect_bracket', 'arc_length_symbol', "
        "'fixed_symbol', 'double_arrow', 'split_square', 'verbose', or "
        "'none'. size: 'tight_fit' (default), '1_char', '2_chars', "
        "'3_chars', '4_chars', or '5_chars'. text_content: 'item_number' "
        "(default), 'custom', 'quantity', 'custom_properties', "
        "'component_reference', 'spool_reference', 'part_number_bom', "
        "'file_name', 'cutlist_properties', 'view_sheet', "
        "'view_sheet_with_label', 'view_zone', or 'view_letter'. "
        "leader_attachment: 'edge' (default) or 'face'. bom_table_name, if "
        "given, requires a BOM table with exactly that name to already "
        "exist on the view's sheet, failing before any COM call otherwise; "
        "omitted, any BOM table on the sheet avoids the missing-BOM "
        "warning, and no BOM table at all still runs (balloons are still "
        "created) but the result message warns that item numbers may be "
        "meaningless. Returns the number of balloons created in "
        "data.count."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to balloon."},
            "layout": {"type": "string", "default": "square", "description": "Balloon layout around the view."},
            "style": {"type": "string", "default": "circular", "description": "Balloon shape."},
            "size": {"type": "string", "default": "tight_fit", "description": "Balloon fit/size."},
            "text_content": {
                "type": "string", "default": "item_number",
                "description": "Upper-text content source.",
            },
            "reverse_direction": {
                "type": "boolean", "default": False,
                "description": "Reverse the balloons' item ordering.",
            },
            "ignore_multiple": {
                "type": "boolean", "default": True,
                "description": "True balloons only one instance of a repeated item.",
            },
            "insert_magnetic_line": {
                "type": "boolean", "default": False,
                "description": "Insert magnetic lines with the balloons.",
            },
            "leader_attachment": {
                "type": "string", "default": "edge",
                "description": "'edge' (default) or 'face'.",
            },
            "bom_table_name": {
                "type": "string",
                "description": "Require this exact BOM table to exist on the sheet.",
            },
        },
        "required": ["view_name"],
    },
)
def auto_balloon_view(arguments: dict) -> Dict:
    return sw_automation.auto_balloon_view(
        arguments.get("view_name"),
        arguments.get("layout", "square"),
        arguments.get("style", "circular"),
        arguments.get("size", "tight_fit"),
        arguments.get("text_content", "item_number"),
        arguments.get("reverse_direction", False),
        arguments.get("ignore_multiple", True),
        arguments.get("insert_magnetic_line", False),
        arguments.get("leader_attachment", "edge"),
        arguments.get("bom_table_name"),
    )


@tool(
    name="add_balloon",
    description=(
        "Add a single BOM balloon via IModelDocExtension::InsertBOMBalloon "
        "-- the one-off case; use auto_balloon_view to balloon a whole "
        "view instead. entity is the item to balloon (typically "
        "kind='component' for an assembly component instance, or an edge/"
        "face/vertex as returned by list_view_entities). x/y place the "
        "balloon, caller's default unit. style/size/text_content use the "
        "same values as auto_balloon_view. lower_text is only valid when "
        "style='split_circle'. upper_text is only used when "
        "text_content='custom'. quantity_display shows the item quantity "
        "on the balloon."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entity lives in."},
            "entity": {**_BALLOON_ENTITY_REF_SCHEMA, "description": "Item to balloon."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "style": {"type": "string", "default": "circular", "description": "Balloon shape."},
            "size": {"type": "string", "default": "tight_fit", "description": "Balloon fit/size."},
            "text_content": {
                "type": "string", "default": "item_number",
                "description": "Upper-text content source.",
            },
            "upper_text": {
                "type": "string",
                "description": "Literal upper text; only used when text_content='custom'.",
            },
            "lower_text": {
                "type": "string",
                "description": "Literal lower text; only valid when style='split_circle'.",
            },
            "quantity_display": {
                "type": "boolean", "default": False,
                "description": "Show the item quantity on the balloon.",
            },
        },
        "required": ["view_name", "entity", "x", "y"],
    },
)
def add_balloon(arguments: dict) -> Dict:
    return sw_automation.add_balloon(
        arguments.get("view_name"),
        arguments.get("entity"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("style", "circular"),
        arguments.get("size", "tight_fit"),
        arguments.get("text_content", "item_number"),
        arguments.get("upper_text"),
        arguments.get("lower_text"),
        arguments.get("quantity_display", False),
    )


@tool(
    name="renumber_balloons",
    description=(
        "Deterministically renumber every BOM balloon via INote::"
        "SetBomBalloonText. view_name restricts to one view's balloons; "
        "omitted, every BOM balloon in the document. start is the first "
        "item number (default 1). order='by_position' (the only "
        "implemented order) sorts top-left first: descending sheet Y "
        "(top first), then ascending sheet X (left first), then balloon "
        "name as a stable tie-break -- so the same balloon positions "
        "always produce the same numbering. Returns the renumbered count "
        "in data.count and each balloon's assigned number in data.balloons."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Restrict to this view's balloons."},
            "start": {"type": "integer", "default": 1, "description": "First item number to assign."},
            "order": {
                "type": "string", "default": "by_position",
                "description": "Only 'by_position' is implemented.",
            },
        },
        "required": [],
    },
)
def renumber_balloons(arguments: dict) -> Dict:
    return sw_automation.renumber_balloons(
        arguments.get("view_name"),
        arguments.get("start", 1),
        arguments.get("order", "by_position"),
    )


@tool(
    name="remove_balloons",
    description=(
        "Clear every BOM balloon note from a drawing view via INote::"
        "IsBomBalloon + IModelDocExtension::DeleteSelection2 -- lets a bad "
        "auto_balloon_view/add_balloon batch be redone without restarting "
        "the drawing. Returns the removed count in data.count; a view "
        "with no balloons is a warned success with count 0."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to clear."},
        },
        "required": ["view_name"],
    },
)
def remove_balloons(arguments: dict) -> Dict:
    return sw_automation.remove_balloons(
        arguments.get("view_name"),
    )
