"""
COM Backend Accessor
---------------------
Lazy, injectable access to the `win32com.client` and `pythoncom` modules,
plus the handful of COM operations the automation layer actually performs
with them.

`solidworks_mcp.automation` needs COM to actually talk to SolidWorks, but
pywin32 only exists on Windows. Importing `win32com.client` / `pythoncom` at
module load time makes the whole package unimportable on macOS/Linux, which
blocks any off-Windows development or testing.

This module defers those imports until a caller actually asks for the real
objects (`get_win32com()` / `get_pythoncom()`), and raises a clear
`ComUnavailableError` instead of `ModuleNotFoundError` when pywin32 isn't
installed. Tests can also install fake modules via `set_backend()` /
`reset_backend()` without touching `sys.modules`.

Prefer the operation-level helpers (`null_dispatch()`, `byref_int()`) over
fetching the raw modules: between them they cover every VARIANT the
automation layer builds, so the `VT_BYREF | VT_I4` bit-fiddling lives in
exactly one place.
"""

import importlib
from typing import Any, Dict, Optional

_WIN32COM = "win32com.client"
_PYTHONCOM = "pythoncom"

_UNAVAILABLE_MSG = (
    "pywin32 is required; this operation only runs on Windows with SolidWorks installed"
)


class ComUnavailableError(RuntimeError):
    """Raised when COM automation is attempted without pywin32 available."""


# Test-injected stand-ins (see `set_backend`), checked ahead of the real
# modules, and the memoized real imports.
_overrides: Dict[str, Any] = {}
_loaded: Dict[str, Any] = {}


def _load(name: str) -> Any:
    if name in _overrides:
        return _overrides[name]
    module = _loaded.get(name)
    if module is None:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            raise ComUnavailableError(_UNAVAILABLE_MSG) from exc
        _loaded[name] = module
    return module


def is_com_available() -> bool:
    """Whether COM access is currently usable (real pywin32 or an injected
    test backend). Computed on each call, so it tracks
    `set_backend()`/`reset_backend()`."""
    try:
        _load(_WIN32COM)
        _load(_PYTHONCOM)
    except ComUnavailableError:
        return False
    return True


def get_win32com() -> Any:
    """Return the win32com.client module (real or injected test stub)."""
    return _load(_WIN32COM)


def get_pythoncom() -> Any:
    """Return the pythoncom module (real or injected test stub)."""
    return _load(_PYTHONCOM)


def null_dispatch() -> Any:
    """A null `VT_DISPATCH` VARIANT -- what SolidWorks' `SelectByID2` and
    `Extension.SaveAs` want for their optional callout/export arguments."""
    return get_win32com().VARIANT(get_pythoncom().VT_DISPATCH, None)


def byref_int(initial: int = 0) -> Any:
    """A by-reference 32-bit int VARIANT, for SolidWorks' `errors`/`warnings`
    out-parameters. Read the result back off `.value` after the call."""
    pythoncom = get_pythoncom()
    return get_win32com().VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, initial)


def byref_str(initial: str = "") -> Any:
    """A by-reference string VARIANT, for out-parameters like
    `ICustomPropertyManager::Get6`'s `ValOut`/`ResolvedValOut`. Read the
    result back off `.value` after the call."""
    pythoncom = get_pythoncom()
    return get_win32com().VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, initial)


def byref_bool(initial: bool = False) -> Any:
    """A by-reference boolean VARIANT, for out-parameters like
    `ICustomPropertyManager::Get6`'s `WasResolved`/`LinkToProperty`. Read the
    result back off `.value` after the call."""
    pythoncom = get_pythoncom()
    return get_win32com().VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, initial)


def set_backend(win32com_stub: Any, pythoncom_stub: Any) -> Dict[str, Any]:
    """Inject fake win32com.client / pythoncom modules for testing.

    Returns the overrides that were in effect beforehand; hand that token to
    `reset_backend()` to restore them, so installs can nest.
    """
    previous = dict(_overrides)
    _overrides[_WIN32COM] = win32com_stub
    _overrides[_PYTHONCOM] = pythoncom_stub
    return previous


def reset_backend(previous: Optional[Dict[str, Any]] = None) -> None:
    """Remove the injected test backend, reverting to real pywin32 imports.

    Pass the token `set_backend()` returned to restore the backend that was
    installed before it instead of clearing outright -- otherwise unwinding
    an inner install silently kills the outer one too.
    """
    _overrides.clear()
    if previous:
        _overrides.update(previous)
