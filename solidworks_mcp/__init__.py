"""
SolidWorks MCP Package
----------------------
Model Context Protocol server for SolidWorks automation.

Version: 3.0.0
Author: Samsaam Ali Baig
"""

__version__ = "3.0.0"
__author__ = "Samsaam Ali Baig"

from .automation import SolidWorksAutomation
from .config import get_config, reload_config, save_config, SolidWorksConfig
from .constants import SwErrors, SwPlanes, SwDocumentTypes, SwViews
from . import constants_drawing
from .constants_drawing import *  # noqa: F403  (re-export; see its __all__)
from .utils import (
    UnitConverter, 
    mm, cm, inch, ft,
    find_solidworks,
    find_template,
    get_solidworks_info
)

__all__ = [
    # Version
    "__version__",
    "__author__",
    
    # Main class
    "SolidWorksAutomation",
    
    # Config
    "get_config",
    "reload_config", 
    "save_config",
    "SolidWorksConfig",
    
    # Constants
    "SwErrors",
    "SwPlanes",
    "SwDocumentTypes",
    "SwViews",

    # Utils
    "UnitConverter",
    "mm", "cm", "inch", "ft",
    "find_solidworks",
    "find_template",
    "get_solidworks_info",
]

# Every drawing constant, straight from the module that defines them -- so a
# new enum in constants_drawing.py is exported here without touching this file.
__all__ += constants_drawing.__all__
