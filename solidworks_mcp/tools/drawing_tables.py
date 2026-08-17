"""
Drawing Table Tools
--------------------
insert_bom_table, list_tables, get_bom_contents.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/04-tables.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool

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
