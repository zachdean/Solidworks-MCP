"""
Shared SolidWorks automation instance
--------------------------------------
The single `SolidWorksAutomation` every tool handler and `server.py` drives.

It lives in this leaf module -- rather than in the `solidworks_mcp.tools`
package `__init__` -- precisely so nothing depends on import *order*: a
submodule doing `from ._automation import sw_automation` triggers a normal,
fully-executed module import, instead of reading an attribute off a
half-initialized parent package.
"""

from ..automation import SolidWorksAutomation

__all__ = ["sw_automation"]

sw_automation = SolidWorksAutomation()
