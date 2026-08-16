"""
Connection Tools
----------------
connect_solidworks, get_solidworks_info.
"""

from typing import Dict

from ..utils import get_solidworks_info as _get_solidworks_info
from . import sw_automation
from .registry import tool


@tool(
    name="connect_solidworks",
    description="Connect to SolidWorks. Launches if not running.",
    schema={"type": "object", "properties": {}, "required": []},
)
def connect_solidworks(arguments: dict) -> Dict:
    return sw_automation.connect()


@tool(
    name="get_solidworks_info",
    description="Get SolidWorks installation information.",
    schema={"type": "object", "properties": {}, "required": []},
)
def get_solidworks_info(arguments: dict) -> Dict:
    info = _get_solidworks_info()
    return {
        "success": info["found"],
        "message": f"SolidWorks {'found' if info['found'] else 'not found'}",
        "error_code": 0 if info["found"] else 105,
        "error_name": "swSuccess" if info["found"] else "swSolidWorksNotFound",
        "data": info
    }
