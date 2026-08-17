"""
Document Tools
--------------
create_new_part, create_new_assembly, open_document, save_document,
close_document, get_document_info, list_open_documents.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool


@tool(
    name="create_new_part",
    description="Create a new part document.",
    schema={"type": "object", "properties": {}, "required": []},
)
def create_new_part(arguments: dict) -> Dict:
    return sw_automation.create_new_part()


@tool(
    name="create_new_assembly",
    description="Create a new assembly document.",
    schema={"type": "object", "properties": {}, "required": []},
)
def create_new_assembly(arguments: dict) -> Dict:
    return sw_automation.create_new_assembly()


@tool(
    name="open_document",
    description="Open an existing SolidWorks document.",
    schema={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "Path to file"}
        },
        "required": ["filepath"]
    },
)
def open_document(arguments: dict) -> Dict:
    return sw_automation.open_document(arguments.get("filepath", ""))


@tool(
    name="save_document",
    description="Save the active document.",
    schema={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "Path to save (optional for Save As)"}
        },
        "required": []
    },
)
def save_document(arguments: dict) -> Dict:
    return sw_automation.save_document(arguments.get("filepath"))


@tool(
    name="close_document",
    description="Close the active document.",
    schema={
        "type": "object",
        "properties": {
            "save": {"type": "boolean", "default": False, "description": "Save before closing"}
        },
        "required": []
    },
)
def close_document(arguments: dict) -> Dict:
    return sw_automation.close_document(arguments.get("save", False))


@tool(
    name="get_document_info",
    description="Get information about the active document.",
    schema={"type": "object", "properties": {}, "required": []},
)
def get_document_info(arguments: dict) -> Dict:
    return sw_automation.get_document_info()


@tool(
    name="list_open_documents",
    description="List all open documents.",
    schema={"type": "object", "properties": {}, "required": []},
)
def list_open_documents(arguments: dict) -> Dict:
    return sw_automation.list_open_documents()
