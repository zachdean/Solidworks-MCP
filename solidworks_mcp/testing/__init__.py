"""
SolidWorks MCP Testing Utilities
---------------------------------
Recording fake-COM harness for exercising tools without a Windows/SolidWorks
install. Shipped with the library so it's importable from the target machine
too.

Two halves: `fake_com` fakes the COM *object graph* (`FakeSldWorks`), and
`fake_backend` fakes the pywin32 *modules* that `com_backend`'s injection
seam wants (`install_fake_backend`). Use the latter -- it wires up both.
"""

from .fake_backend import (
    FakePythonCom,
    FakeVariant,
    FakeWin32ComClient,
    install_fake_backend,
)
from .fake_com import Call, CallLog, FakeComObject, FakeSldWorks

__all__ = [
    "Call",
    "CallLog",
    "FakeComObject",
    "FakePythonCom",
    "FakeSldWorks",
    "FakeVariant",
    "FakeWin32ComClient",
    "install_fake_backend",
]
