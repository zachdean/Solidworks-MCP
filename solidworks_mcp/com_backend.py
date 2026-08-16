"""
COM Backend Accessor
---------------------
Lazy, injectable access to the `win32com.client` and `pythoncom` modules.

`solidworks_mcp.automation` needs COM to actually talk to SolidWorks, but
pywin32 only exists on Windows. Importing `win32com.client` / `pythoncom` at
module load time makes the whole package unimportable on macOS/Linux, which
blocks any off-Windows development or testing.

This module defers those imports until a caller actually asks for the real
objects (`get_win32com()` / `get_pythoncom()`), and raises a clear
`ComUnavailableError` instead of `ModuleNotFoundError` when pywin32 isn't
installed. Tests can also install fake modules via `set_backend()` /
`reset_backend()` without touching `sys.modules`.
"""

import importlib.util


class ComUnavailableError(RuntimeError):
    """Raised when COM automation is attempted without pywin32 available."""


_win32com_override = None
_pythoncom_override = None


def _find_spec_safe(name: str):
    try:
        return importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None


def is_com_available() -> bool:
    """Whether real pywin32-backed COM access is currently usable."""
    if _win32com_override is not None and _pythoncom_override is not None:
        return True
    return (
        _find_spec_safe("win32com.client") is not None
        and _find_spec_safe("pythoncom") is not None
    )


def __getattr__(name: str):
    # Computed on each access (not cached at import time) so tests that
    # monkeypatch availability, or call set_backend()/reset_backend(), see
    # up-to-date results.
    if name == "COM_AVAILABLE":
        return is_com_available()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_win32com():
    """Return the win32com.client module (real or injected test stub)."""
    if _win32com_override is not None:
        return _win32com_override
    if _find_spec_safe("win32com.client") is None:
        raise ComUnavailableError(
            "pywin32 is required; this operation only runs on Windows with SolidWorks installed"
        )
    import win32com.client
    return win32com.client


def get_pythoncom():
    """Return the pythoncom module (real or injected test stub)."""
    if _pythoncom_override is not None:
        return _pythoncom_override
    if _find_spec_safe("pythoncom") is None:
        raise ComUnavailableError(
            "pywin32 is required; this operation only runs on Windows with SolidWorks installed"
        )
    import pythoncom
    return pythoncom


def set_backend(win32com_stub, pythoncom_stub) -> None:
    """Inject fake win32com.client / pythoncom modules for testing."""
    global _win32com_override, _pythoncom_override
    _win32com_override = win32com_stub
    _pythoncom_override = pythoncom_stub


def reset_backend() -> None:
    """Remove any injected test backend, reverting to real pywin32 imports."""
    global _win32com_override, _pythoncom_override
    _win32com_override = None
    _pythoncom_override = None
