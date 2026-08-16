"""
SolidWorks MCP Testing Utilities
---------------------------------
Recording fake-COM harness (see `fake_com`) for exercising tools without a
Windows/SolidWorks install. Shipped with the library so it's importable
from the target machine too.
"""

from .fake_com import Call, CallLog, FakeComObject, FakeSldWorks

__all__ = [
    "Call",
    "CallLog",
    "FakeComObject",
    "FakeSldWorks",
]
