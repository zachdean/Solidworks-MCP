"""
Drawing Document & Session Tools
---------------------------------
new_drawing_from_template, get_document_type, open_or_activate_document,
rebuild_document, save_drawing, export_pdf, get_custom_properties,
set_custom_properties.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/01-documents-and-sheets.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="new_drawing_from_template",
    description=(
        "Create a new drawing document from a .drwdot template via "
        "ISldWorks::NewDocument. Falls back to auto-discovering a template "
        "when template_path is omitted."
    ),
    schema={
        "type": "object",
        "properties": {
            "template_path": {
                "type": "string",
                "description": "Path to a .drwdot template; auto-discovered when omitted",
            },
            "paper_size": {
                "type": "string",
                "default": "A3",
                "description": "A, B, C, D, E, or A0-A4",
            },
            "orientation": {
                "type": "string",
                "default": "landscape",
                "enum": ["landscape", "portrait"],
                "description": "Portrait is only meaningful for A/A4 paper sizes",
            },
            "scale_num": {"type": "number", "default": 1, "description": "Sheet scale numerator"},
            "scale_denom": {"type": "number", "default": 1, "description": "Sheet scale denominator"},
        },
        "required": [],
    },
)
def new_drawing_from_template(arguments: dict) -> Dict:
    return sw_automation.new_drawing_from_template(
        arguments.get("template_path"),
        arguments.get("paper_size", "A3"),
        arguments.get("orientation", "landscape"),
        arguments.get("scale_num", 1),
        arguments.get("scale_denom", 1),
    )


@tool(
    name="get_document_type",
    description="Identify the active document's type (Part/Assembly/Drawing/...) via IModelDoc2::GetType.",
    schema={"type": "object", "properties": {}, "required": []},
)
def get_document_type(arguments: dict) -> Dict:
    return sw_automation.get_document_type()


@tool(
    name="open_or_activate_document",
    description=(
        "Open a document via OpenDoc6, or activate it via ActivateDoc3 if "
        "already loaded."
    ),
    schema={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "Path to the file"},
            "read_only": {"type": "boolean", "default": False, "description": "Open read-only"},
            "lightweight": {
                "type": "boolean", "default": False,
                "description": "Open lightweight -- useful for large assemblies",
            },
        },
        "required": ["filepath"],
    },
)
def open_or_activate_document(arguments: dict) -> Dict:
    return sw_automation.open_or_activate_document(
        arguments.get("filepath", ""),
        arguments.get("read_only", False),
        arguments.get("lightweight", False),
    )


@tool(
    name="rebuild_document",
    description="Rebuild the active document via ForceRebuild3 (force) or EditRebuild3 (incremental).",
    schema={
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "default": True, "description": "Force a full rebuild"},
            "top_level_only": {
                "type": "boolean", "default": False,
                "description": "For assemblies: rebuild only the top-level assembly",
            },
        },
        "required": [],
    },
)
def rebuild_document(arguments: dict) -> Dict:
    return sw_automation.rebuild_document(
        arguments.get("force", True),
        arguments.get("top_level_only", False),
    )


@tool(
    name="save_drawing",
    description=(
        "Save the active document via Save3 (in place) or SaveAs3 "
        "(filepath given), decoding swFileSaveError_e in the result message."
    ),
    schema={
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Path to save as; omit to save in place",
            },
        },
        "required": [],
    },
)
def save_drawing(arguments: dict) -> Dict:
    return sw_automation.save_drawing(arguments.get("filepath"))


@tool(
    name="export_pdf",
    description=(
        "Export the active drawing to PDF via IModelDocExtension::SaveAs3 + "
        "IExportPdfData, decoding swFileSaveError_e in the result message. "
        "Verifies the output file actually exists on disk afterward and "
        "reports its size."
    ),
    schema={
        "type": "object",
        "properties": {
            "output_path": {
                "type": "string",
                "description": "Destination .pdf path; parent directory is created if missing",
            },
            "sheets": {
                "default": "all",
                "description": (
                    "'all', 'current', or an explicit list of sheet names "
                    "(validated against GetSheetNames before any COM call)"
                ),
                "oneOf": [
                    {"type": "string", "enum": ["all", "current"]},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "open_after": {
                "type": "boolean", "default": False,
                "description": "Open the PDF after saving (IExportPdfData::ViewPdfAfterSaving)",
            },
            "keep_invisible_layers": {
                "type": "boolean", "default": False,
                "description": (
                    "Temporarily show every hidden layer for the export, "
                    "then restore each to hidden afterward"
                ),
            },
            "high_quality": {
                "type": "boolean", "default": True,
                "description": "swPDFExportHighQuality user preference, saved and restored around the call",
            },
        },
        "required": ["output_path"],
    },
)
def export_pdf(arguments: dict) -> Dict:
    return sw_automation.export_pdf(
        arguments.get("output_path", ""),
        arguments.get("sheets", "all"),
        arguments.get("open_after", False),
        arguments.get("keep_invisible_layers", False),
        arguments.get("high_quality", True),
    )


@tool(
    name="get_custom_properties",
    description="Read all custom properties (document-level or a named configuration).",
    schema={
        "type": "object",
        "properties": {
            "configuration": {
                "type": "string",
                "description": "Configuration name; omit for document-level properties",
            },
        },
        "required": [],
    },
)
def get_custom_properties(arguments: dict) -> Dict:
    return sw_automation.get_custom_properties(arguments.get("configuration"))


@tool(
    name="set_custom_properties",
    description="Add or overwrite custom properties (document-level or a named configuration).",
    schema={
        "type": "object",
        "properties": {
            "properties": {
                "type": "object",
                "default": {},
                "description": "{name: value} custom properties to add or overwrite",
            },
            "configuration": {
                "type": "string",
                "description": "Configuration name; omit for document-level properties",
            },
        },
        "required": [],
    },
)
def set_custom_properties(arguments: dict) -> Dict:
    return sw_automation.set_custom_properties(
        arguments.get("properties", {}),
        arguments.get("configuration"),
    )
