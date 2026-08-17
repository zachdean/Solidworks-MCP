"""
Utility Tools
-------------
set_units, execute_python.
"""

import io
import json
import sys
import traceback
from typing import Dict

from .. import com_backend
from ..constants import SwErrors
from ..utils import set_default_unit
from ._automation import sw_automation
from .registry import tool


@tool(
    name="set_units",
    description="Set default unit for dimensions.",
    schema={
        "type": "object",
        "properties": {
            "unit": {
                "type": "string",
                "enum": ["mm", "inch", "m", "cm"],
                "description": "Default unit"
            }
        },
        "required": ["unit"]
    },
)
def set_units(arguments: dict) -> Dict:
    unit = arguments.get("unit", "mm")
    set_default_unit(unit)
    sw_automation._units.default_unit = unit
    return {
        "success": True,
        "message": f"Default unit set to: {unit}",
        "error_code": 0,
        "error_name": "swSuccess",
        "data": {"unit": unit}
    }


# ============================================================================
# execute_python handler
# ============================================================================

def _execute_python_fixed(code: str) -> Dict:
    """
    Execute custom Python code with access to SolidWorks.
    FIXED: Now captures stdout, stderr, and 'result' variable.
    """
    try:
        if not sw_automation.is_connected:
            r = sw_automation.connect()
            if not r["success"]:
                return r

        import math
        import os as os_module
        from types import SimpleNamespace

        # Go through the same seam as the automation layer, so this tool
        # honours an injected test backend and raises ComUnavailableError
        # (not ModuleNotFoundError) off Windows. Executed snippets reach COM
        # as `win32com.client.<...>`, so keep that shape.
        #
        # NARROWING: the exposed `win32com` is a stand-in exposing `.client`
        # only, not the real package -- a snippet reaching for another
        # submodule (`win32com.storagecon`, `win32com.server.util`) now gets
        # an AttributeError and must `import` it itself. Widening this would
        # mean importing pywin32 directly here and losing the seam.
        win32com_client = com_backend.get_win32com()
        pythoncom = com_backend.get_pythoncom()

        # Prepare execution context with many useful objects
        exec_globals = {
            # SolidWorks objects
            'sw': sw_automation.app,
            'doc': sw_automation.app.ActiveDoc if sw_automation.app else None,
            'automation': sw_automation,

            # COM libraries
            'win32com': SimpleNamespace(client=win32com_client),
            'pythoncom': pythoncom,

            # Standard libraries
            'math': math,
            'os': os_module,
            'json': json,

            # Result placeholder
            'result': None,
        }

        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()

        try:
            sys.stdout = captured_stdout
            sys.stderr = captured_stderr

            # Execute the code
            exec(code, exec_globals)

        finally:
            # Always restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        # Get captured output
        stdout_text = captured_stdout.getvalue()
        stderr_text = captured_stderr.getvalue()
        result_val = exec_globals.get('result')

        # Build response message
        message_parts = []

        if stdout_text:
            message_parts.append(f"=== Output ===\n{stdout_text.rstrip()}")

        if stderr_text:
            message_parts.append(f"=== Stderr ===\n{stderr_text.rstrip()}")

        if result_val is not None:
            message_parts.append(f"=== Result ===\n{result_val}")

        if not message_parts:
            message_parts.append("Code executed successfully (no output)")

        return {
            "success": True,
            "message": "\n\n".join(message_parts),
            "error_code": 0,
            "error_name": "swSuccess",
            "data": {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "result": str(result_val) if result_val is not None else None
            }
        }

    except SyntaxError as e:
        return {
            "success": False,
            "message": f"Syntax error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"error_type": "SyntaxError", "details": str(e)}
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {
            "success": False,
            "message": f"Execution error: {e}\n\nTraceback:\n{tb}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": tb
            }
        }


@tool(
    name="execute_python",
    description="Execute custom Python code with stdout capture. Access 'sw' (app), 'doc' (active document). Use print() for debug output.",
    schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"}
        },
        "required": ["code"]
    },
)
def execute_python(arguments: dict) -> Dict:
    code = arguments.get("code", "")
    if not code:
        return sw_automation._result(False, "Code is required", SwErrors.swInvalidInput)
    return _execute_python_fixed(code)
