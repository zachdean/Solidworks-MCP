"""
Fake pywin32 modules for `com_backend.set_backend()`
-----------------------------------------------------
`fake_com` provides the fake COM *object graph* (`FakeSldWorks`); this module
provides the other half -- the fake `win32com.client` / `pythoncom` *modules*
that satisfy `solidworks_mcp.com_backend`'s injection seam, so
`SolidWorksAutomation.connect()` succeeds against that graph with no pywin32
installed.

It lives in the shipped `testing` package rather than in a pytest conftest
because the fake `VARIANT` contract has to track `com_backend`'s real one,
and because a Windows smoke script or a second test root needs the same
wiring.

    from solidworks_mcp.testing import install_fake_backend

    with install_fake_backend("drawing") as app:
        ...  # app is a FakeSldWorks; com_backend is reset on exit
"""

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .. import com_backend
from .fake_com import FakeComObject, FakeSldWorks

__all__ = [
    "FakeVariant",
    "FakeWin32ComClient",
    "FakePythonCom",
    "install_fake_backend",
]


class FakeVariant:
    """Stand-in for `win32com.client.VARIANT`: a mutable `.value` box.

    Production code writes a VARIANT into a COM out-parameter and then reads
    the result back off `.value`, so that attribute is the whole contract.
    """

    def __init__(self, vt: int, value: Any) -> None:
        self.vt = vt
        self.value = value


class _FakeDynamic:
    def __init__(self, app: FakeComObject) -> None:
        self._app = app

    def Dispatch(self, prog_id):
        return self._app


class FakeWin32ComClient:
    """Stand-in for the `win32com.client` module, wired to hand back `app`
    for every connection method `_try_connect_com` tries."""

    def __init__(self, app: FakeComObject) -> None:
        self._app = app
        self.dynamic = _FakeDynamic(app)

    def GetObject(self, Class=None):
        return self._app

    def Dispatch(self, prog_id):
        return self._app

    def GetActiveObject(self, prog_id):
        return self._app

    def VARIANT(self, vt, value):
        return FakeVariant(vt, value)


class FakePythonCom:
    """Stand-in for the `pythoncom` module."""

    VT_BYREF = 0x4000
    VT_I4 = 3
    VT_DISPATCH = 9
    Nothing = None

    def CoInitialize(self):
        pass


@contextmanager
def install_fake_backend(
    doc_type: str = "part",
    *,
    app: Optional[FakeComObject] = None,
    **kwargs: Any,
) -> Iterator[FakeComObject]:
    """Install a fake COM backend around a `FakeSldWorks` graph, yielding the
    app and restoring the real backend on exit.

    Args:
        doc_type: passed to `FakeSldWorks` ("part", "assembly", "drawing")
            when `app` is not supplied.
        app: an already-built graph to install instead of making a new one.
        **kwargs: forwarded to `FakeSldWorks` (e.g. `sheet_names=`).
    """
    if app is None:
        app = FakeSldWorks(doc_type, **kwargs)
    previous = com_backend.set_backend(FakeWin32ComClient(app), FakePythonCom())
    try:
        yield app
    finally:
        com_backend.reset_backend(previous)
