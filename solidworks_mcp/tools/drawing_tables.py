"""
Drawing Table Tools
--------------------
insert_bom_table, list_tables, get_bom_contents, auto_balloon_view,
add_balloon, renumber_balloons, remove_balloons, insert_hole_table,
insert_revision_table, add_revision, insert_weldment_cutlist,
update_table, get_table_contents, set_table_cell, set_table_position,
set_table_anchor, delete_table.

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

_DATUM_ENTITY_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "Entity kind: 'vertex' or 'edge' (as returned by list_view_entities). No other kind is a valid hole-table datum origin.",
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


@tool(
    name="insert_hole_table",
    description=(
        "Insert a hole table onto a drawing view via IView::"
        "InsertHoleTable3, after atomically selecting datum_entity "
        "(Mark=1) -- a hole table's X/Y columns are relative to a "
        "pre-selected datum origin vertex or edge. tag_style: "
        "'alphanumeric' (default) or 'numeric'. combine_same_size: True "
        "(default) merges cells of same-size holes via IHoleTable::"
        "CombineSameSize. template_path falls back to the SolidWorks "
        "default .sldholtbt template when omitted, erroring with "
        "swTemplateNotFound if none can be found. Returns the created "
        "table's name, row_count, and column_count."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to attach the table to and select the datum entity in."},
            "datum_entity": {**_DATUM_ENTITY_REF_SCHEMA, "description": "Origin/datum vertex or edge, selected with Mark=1 before insertion."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "template_path": {
                "type": "string",
                "description": "Path to a .sldholtbt template. Omitted: auto-discovered default.",
            },
            "tag_style": {
                "type": "string", "default": "alphanumeric",
                "description": "'alphanumeric' (default) or 'numeric'.",
            },
            "combine_same_size": {
                "type": "boolean", "default": True,
                "description": "True to merge cells of the same-size holes.",
            },
        },
        "required": ["view_name", "datum_entity", "x", "y"],
    },
)
def insert_hole_table(arguments: dict) -> Dict:
    return sw_automation.insert_hole_table(
        arguments.get("view_name"),
        arguments.get("datum_entity"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("template_path"),
        arguments.get("tag_style"),
        arguments.get("combine_same_size", True),
    )


@tool(
    name="insert_revision_table",
    description=(
        "Insert a revision table onto the active sheet via ISheet::"
        "InsertRevisionTable2 (requested as IDrawingDoc::"
        "InsertRevisionTable2, which does not exist). anchor=True "
        "(default) inserts at the sheet's existing revision-table anchor "
        "point and x/y must be omitted; anchor=False requires x/y. "
        "alpha_numeric is accepted and echoed for forward compatibility -- "
        "SolidWorks has no per-table alpha/numeric COM property; "
        "add_revision infers the numbering scheme from the table's "
        "existing rows instead. symbol_shape: 'circle' (default), "
        "'square', 'triangle', or 'hexagon'. template_path falls back to "
        "the SolidWorks default .sldrevtbt template when omitted, "
        "erroring with swTemplateNotFound if none can be found, and with "
        "swFeatureError if the sheet already has a revision table (only "
        "one is allowed per sheet). Returns the created table's name, "
        "row_count, and column_count."
    ),
    schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "Placement, caller's default unit. Must be omitted when anchor=True; required when anchor=False."},
            "y": {"type": "number", "description": "Placement, caller's default unit. Must be omitted when anchor=True; required when anchor=False."},
            "template_path": {
                "type": "string",
                "description": "Path to a .sldrevtbt template. Omitted: auto-discovered default.",
            },
            "anchor": {
                "type": "boolean", "default": True,
                "description": "True to insert at the sheet's existing revision-table anchor point instead of x/y.",
            },
            "alpha_numeric": {
                "type": "boolean", "default": True,
                "description": "Echoed in the result; see description for why this isn't a real COM setting.",
            },
            "symbol_shape": {
                "type": "string", "default": "circle",
                "description": "'circle' (default), 'square', 'triangle', or 'hexagon'.",
            },
        },
        "required": [],
    },
)
def insert_revision_table(arguments: dict) -> Dict:
    return sw_automation.insert_revision_table(
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("template_path"),
        arguments.get("anchor", True),
        arguments.get("alpha_numeric", True),
        arguments.get("symbol_shape", "circle"),
    )


@tool(
    name="add_revision",
    description=(
        "Append a row to the document's revision table via "
        "IRevisionTableAnnotation::AddRevision. revision omitted: "
        "auto-incremented from the table's last row (A -> B, 1 -> 2; a "
        "brand-new table with no rows starts at 'A'). date omitted: "
        "defaults to today, formatted MM/DD/YY. approved_by/zone are "
        "written only if the table's template has a matching column "
        "(silently skipped otherwise, reported in data.skipped_fields). "
        "Fails with swInvalidInput if no revision table exists yet -- call "
        "insert_revision_table first."
    ),
    schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "The \"what changed\" text for this revision."},
            "revision": {"type": "string", "description": "Explicit revision designation, e.g. 'B'. Omitted: auto-incremented."},
            "date": {"type": "string", "description": "Omitted: defaults to today (MM/DD/YY)."},
            "approved_by": {"type": "string", "description": "Optional approver name/initials."},
            "zone": {"type": "string", "description": "Optional drawing zone reference."},
        },
        "required": ["description"],
    },
)
def add_revision(arguments: dict) -> Dict:
    return sw_automation.add_revision(
        arguments.get("description"),
        arguments.get("revision"),
        arguments.get("date"),
        arguments.get("approved_by"),
        arguments.get("zone"),
    )


@tool(
    name="insert_weldment_cutlist",
    description=(
        "Insert a weldment cut list table onto a drawing view via IView::"
        "InsertWeldmentTable (requested as IModelDocExtension::"
        "InsertWeldmentCutlist, which does not exist under that name or "
        "any variant spelling). template_path falls back to the "
        "SolidWorks default .sldwldtbt template when omitted, erroring "
        "with swTemplateNotFound if none can be found. Fails with "
        "swFeatureError, distinctly from an empty table, when the view's "
        "referenced model has no weldment cut list feature (detected via "
        "IWeldmentCutListAnnotation::WeldmentCutListFeature reading back "
        "empty). Returns the created table's name, row_count, and "
        "column_count."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to attach the table to."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "template_path": {
                "type": "string",
                "description": "Path to a .sldwldtbt template. Omitted: auto-discovered default.",
            },
        },
        "required": ["view_name", "x", "y"],
    },
)
def insert_weldment_cutlist(arguments: dict) -> Dict:
    return sw_automation.insert_weldment_cutlist(
        arguments.get("view_name"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("template_path"),
    )


@tool(
    name="update_table",
    description=(
        "Force a table (or every table on the active sheet) to reflect the "
        "document's current state -- via IModelDoc2::ForceRebuild3 plus a "
        "per-table IAnnotation::Visible toggle; there is no "
        "ITableAnnotation::Update (see docs/api/04-tables.md's intro). Pass "
        "exactly one of table_name or all_tables=True. table_name updates "
        "one table, searched across the whole document. all_tables=True "
        "updates every table on the active sheet and reports each one in "
        "data.tables, each with its own refreshed flag (True only if that "
        "table's Visible toggle actually ran; an already-hidden table is "
        "left alone and reported as not refreshed rather than counted as "
        "updated) -- data.refreshed_count totals it. An empty sheet is a "
        "warned success with count 0."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Update exactly this table. Mutually exclusive with all_tables.",
            },
            "all_tables": {
                "type": "boolean", "default": False,
                "description": "True to update every table on the active sheet. Mutually exclusive with table_name.",
            },
        },
        "required": [],
    },
)
def update_table(arguments: dict) -> Dict:
    return sw_automation.update_table(
        arguments.get("table_name"),
        arguments.get("all_tables", False),
    )


@tool(
    name="get_table_contents",
    description=(
        "Read any table's cell text back via ITableAnnotation::Text2 -- the "
        "generic counterpart of get_bom_contents, working for BOM, hole, "
        "revision, weldment cut list, general, and title block tables "
        "alike (no table-type restriction). table_name is "
        "IAnnotation::GetName's value, as returned by any insert_*_table "
        "tool's data.name or list_tables' data.tables[i].name. Returns "
        "rows (including the header row at index 0), each row_count x "
        "column_count cell strings, plus the table's type. Fails if no "
        "table has that name."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the target table.",
            },
        },
        "required": ["table_name"],
    },
)
def get_table_contents(arguments: dict) -> Dict:
    return sw_automation.get_table_contents(
        arguments.get("table_name"),
    )


@tool(
    name="set_table_cell",
    description=(
        "Overwrite one table cell's driving text via ITableAnnotation::"
        "Text, refusing the write with swInvalidInput if "
        "IsCellTextEditable reports the cell read-only (e.g. an "
        "auto-generated hole table column) rather than silently no-oping. "
        "row/column are 0-based, matching Text2/IsCellTextEditable's own "
        "indexing -- out-of-range indices are rejected with swInvalidInput "
        "before any write. After writing, the cell is read back via Text2 "
        "into data.verified: a read-back that disagrees fails with "
        "swFeatureError instead of a false success, while a read-back that "
        "itself errors is not treated as a failed write -- it succeeds with "
        "data.verified=False and the read-back error named in the message."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the target table.",
            },
            "row": {"type": "integer", "description": "0-based row index."},
            "column": {"type": "integer", "description": "0-based column index."},
            "text": {"type": "string", "description": "New driving text for the cell."},
        },
        "required": ["table_name", "row", "column", "text"],
    },
)
def set_table_cell(arguments: dict) -> Dict:
    return sw_automation.set_table_cell(
        arguments.get("table_name"),
        arguments.get("row"),
        arguments.get("column"),
        arguments.get("text"),
    )


@tool(
    name="set_table_position",
    description=(
        "Move a table to an explicit sheet-space position via the base "
        "IAnnotation::SetPosition (ITableAnnotation has no SetPosition of "
        "its own). Fails with swInvalidInput if the table is currently "
        "anchored (ITableAnnotation::Anchored=True) -- an anchored table's "
        "origin snaps back to the sheet anchor point and would immediately "
        "override an explicit position -- call set_table_anchor with "
        "anchored=False first."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the target table.",
            },
            "x": {"type": "number", "description": "New position, caller's default unit."},
            "y": {"type": "number", "description": "New position, caller's default unit."},
        },
        "required": ["table_name", "x", "y"],
    },
)
def set_table_position(arguments: dict) -> Dict:
    return sw_automation.set_table_position(
        arguments.get("table_name"),
        arguments.get("x"),
        arguments.get("y"),
    )


@tool(
    name="set_table_anchor",
    description=(
        "Set a table's anchored state via ITableAnnotation::Anchored. "
        "anchored=True (default) snaps the table to its type's sheet "
        "anchor point; anchored=False releases it for explicit "
        "set_table_position control. Setting anchored=True when the sheet "
        "format has no anchor point for this table's type has no effect at "
        "the COM layer -- this reads Anchored back afterward and fails "
        "with swFeatureError on a mismatch rather than a false success."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the target table.",
            },
            "anchored": {
                "type": "boolean", "default": True,
                "description": "True to anchor to the sheet anchor point, False to release.",
            },
        },
        "required": ["table_name"],
    },
)
def set_table_anchor(arguments: dict) -> Dict:
    return sw_automation.set_table_anchor(
        arguments.get("table_name"),
        arguments.get("anchored", True),
    )


@tool(
    name="delete_table",
    description=(
        "Delete a table annotation via select (Type='ANNOTATIONTABLES') + "
        "IModelDocExtension::DeleteSelection2 -- there is no "
        "ITableAnnotation::DeleteTable, so this uses the same "
        "select-then-delete idiom remove_center_marks/remove_balloons use "
        "for annotation types with no dedicated per-object delete method. "
        "table_name is IAnnotation::GetName's value, searched across the "
        "whole document before any selection is attempted -- an unknown "
        "name fails with swInvalidInput and no COM call."
    ),
    schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "IAnnotation::GetName's value for the table to delete.",
            },
        },
        "required": ["table_name"],
    },
)
def delete_table(arguments: dict) -> Dict:
    return sw_automation.delete_table(
        arguments.get("table_name"),
    )
