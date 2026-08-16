"""
Shared pytest fixtures for the automation tool tests.
---------------------------------------------------------
Wires the `FakeSldWorks` recording harness (`solidworks_mcp.testing.fake_com`)
into `com_backend`'s test-injection seam so `SolidWorksAutomation.connect()`
succeeds against a fake COM object graph instead of real pywin32.
"""

import pytest

from solidworks_mcp import com_backend
from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.testing.fake_com import FakeSldWorks


class _FakeVariant:
    """Stand-in for `win32com.client.VARIANT`: a mutable `.value` box."""

    def __init__(self, vt, value):
        self.vt = vt
        self.value = value


class _FakeDynamic:
    def __init__(self, app):
        self._app = app

    def Dispatch(self, prog_id):
        return self._app


class _FakeWin32ComClient:
    """Stand-in for the `win32com.client` module, wired to hand back `app`
    for every connection method `_try_connect_com` tries."""

    def __init__(self, app):
        self._app = app
        self.dynamic = _FakeDynamic(app)

    def GetObject(self, Class=None):
        return self._app

    def Dispatch(self, prog_id):
        return self._app

    def GetActiveObject(self, prog_id):
        return self._app

    def VARIANT(self, vt, value):
        return _FakeVariant(vt, value)


class _FakePythonCom:
    """Stand-in for the `pythoncom` module."""

    VT_BYREF = 0x4000
    VT_I4 = 3
    VT_DISPATCH = 9
    Nothing = None

    def CoInitialize(self):
        pass


@pytest.fixture
def fake_sw():
    """A `FakeSldWorks("part")` app installed as the active com_backend,
    torn down after the test."""
    app = FakeSldWorks("part")
    com_backend.set_backend(_FakeWin32ComClient(app), _FakePythonCom())
    yield app
    com_backend.reset_backend()


@pytest.fixture
def automation(fake_sw):
    """A `SolidWorksAutomation` already connected to `fake_sw`."""
    auto = SolidWorksAutomation()
    result = auto.connect()
    assert result["success"], result
    return auto


@pytest.fixture
def call_log(fake_sw):
    """The `CallLog` recording every interaction with `fake_sw`."""
    return fake_sw.call_log
