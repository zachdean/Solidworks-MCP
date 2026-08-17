"""
Drawing Sheet Management Tools
--------------------------------
add_sheet, activate_sheet, list_sheets, get_active_sheet, set_sheet_properties,
set_sheet_scale, get_sheet_properties.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/01-documents-and-sheets.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="add_sheet",
    description=(
        "Create a new drawing sheet via IDrawingDoc::NewSheet4. paper_size "
        "selects a swDwgPaperSizes_e landscape size (A/B/C/D/E/A0-A4), or "
        "'custom' to size the sheet from width/height instead."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name for the new sheet"},
            "template_path": {
                "type": "string",
                "description": "Full path to a custom .slddrt sheet-format template",
            },
            "paper_size": {
                "type": "string", "default": "A3",
                "description": "A, B, C, D, E, A0-A4, or 'custom' (requires width/height)",
            },
            "scale_num": {"type": "number", "default": 1, "description": "Scale numerator"},
            "scale_denom": {"type": "number", "default": 1, "description": "Scale denominator"},
            "first_angle": {
                "type": "boolean", "default": False,
                "description": "True for first-angle projection, false for third-angle",
            },
            "width": {
                "type": "number",
                "description": "Sheet width; only valid when paper_size='custom'",
            },
            "height": {
                "type": "number",
                "description": "Sheet height; only valid when paper_size='custom'",
            },
        },
        "required": ["name"],
    },
)
def add_sheet(arguments: dict) -> Dict:
    return sw_automation.add_sheet(
        arguments.get("name", ""),
        arguments.get("template_path"),
        arguments.get("paper_size", "A3"),
        arguments.get("scale_num", 1),
        arguments.get("scale_denom", 1),
        arguments.get("first_angle", False),
        arguments.get("width"),
        arguments.get("height"),
    )


@tool(
    name="activate_sheet",
    description=(
        "Make a sheet active via IDrawingDoc::ActivateSheet. Fails with the "
        "available sheet names if the given name doesn't exist."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Sheet name to activate"},
        },
        "required": ["name"],
    },
)
def activate_sheet(arguments: dict) -> Dict:
    return sw_automation.activate_sheet(arguments.get("name", ""))


@tool(
    name="list_sheets",
    description=(
        "Enumerate every sheet in the active drawing via "
        "IDrawingDoc::GetSheetNames, plus each sheet's scale, paper size, "
        "projection type, dimensions, and view count via "
        "ISheet::GetProperties2/GetViews."
    ),
    schema={"type": "object", "properties": {}, "required": []},
)
def list_sheets(arguments: dict) -> Dict:
    return sw_automation.list_sheets()


@tool(
    name="get_active_sheet",
    description=(
        "Report the currently active sheet's name, scale, paper size, "
        "projection type, and dimensions via IDrawingDoc::GetCurrentSheet."
    ),
    schema={"type": "object", "properties": {}, "required": []},
)
def get_active_sheet(arguments: dict) -> Dict:
    return sw_automation.get_active_sheet()


@tool(
    name="set_sheet_properties",
    description=(
        "Update a sheet's setup (paper size, template, scale, projection, "
        "custom dimensions) via IDrawingDoc::SetupSheet5. Reads the sheet's "
        "current setup first and only overrides the fields supplied here -- "
        "any field left out keeps its current value rather than being reset."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": "Sheet to update. Omitted: the current active sheet.",
            },
            "paper_size": {
                "type": "string",
                "description": (
                    "A, B, C, D, E, A0-A4, or 'custom' (requires width/height). "
                    "Omitted: keeps the sheet's current paper size."
                ),
            },
            "template_path": {
                "type": "string",
                "description": (
                    "Full path to a custom .slddrt sheet-format template. "
                    "Omitted: keeps the sheet's current template."
                ),
            },
            "scale_num": {"type": "number", "description": "Scale numerator"},
            "scale_denom": {
                "type": "number",
                "description": "Scale denominator; must be nonzero",
            },
            "first_angle": {
                "type": "boolean",
                "description": "True for first-angle projection, false for third-angle",
            },
            "width": {
                "type": "number",
                "description": "Sheet width; only valid when the effective paper_size is 'custom'",
            },
            "height": {
                "type": "number",
                "description": "Sheet height; only valid when the effective paper_size is 'custom'",
            },
        },
        "required": [],
    },
)
def set_sheet_properties(arguments: dict) -> Dict:
    return sw_automation.set_sheet_properties(
        arguments.get("sheet_name"),
        arguments.get("paper_size"),
        arguments.get("template_path"),
        arguments.get("scale_num"),
        arguments.get("scale_denom"),
        arguments.get("first_angle"),
        arguments.get("width"),
        arguments.get("height"),
    )


@tool(
    name="set_sheet_scale",
    description=(
        "Convenience wrapper over set_sheet_properties that updates only a "
        "sheet's scale via IDrawingDoc::SetupSheet5, leaving every other "
        "field (paper size, template, projection, dimensions) untouched."
    ),
    schema={
        "type": "object",
        "properties": {
            "scale_num": {"type": "number", "description": "Scale numerator"},
            "scale_denom": {
                "type": "number",
                "description": "Scale denominator; must be nonzero",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet to update. Omitted: the current active sheet.",
            },
        },
        "required": ["scale_num", "scale_denom"],
    },
)
def set_sheet_scale(arguments: dict) -> Dict:
    return sw_automation.set_sheet_scale(
        arguments.get("scale_num"),
        arguments.get("scale_denom"),
        arguments.get("sheet_name"),
    )


@tool(
    name="get_sheet_properties",
    description=(
        "Read back a sheet's name, paper size, scale (numeric pair and a "
        "readable ratio string), projection angle, dimensions, and template "
        "info via ISheet::GetProperties2."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": "Sheet to read. Omitted: the current active sheet.",
            },
        },
        "required": [],
    },
)
def get_sheet_properties(arguments: dict) -> Dict:
    return sw_automation.get_sheet_properties(arguments.get("sheet_name"))
