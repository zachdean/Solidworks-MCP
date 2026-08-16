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
from .constants_drawing import (
    SwAddOrdinateDims,
    SwAlignViewTypes,
    SwAnnotationType,
    SwAutodimEntities,
    SwAutodimScheme,
    SwBOMConfigurationAnchorType,
    SwBalloonFit,
    SwBalloonLayoutType,
    SwBalloonStyle,
    SwBalloonTextContent,
    SwBomType,
    SwBreakLineOrientation,
    SwBreakLineStyle,
    SwCenterMarkStyle,
    SwCreateSectionViewAtOptions,
    SwCustomInfoType,
    SwCustomPropertyAddOption,
    SwDatumDisplayType,
    SwDetCircleShowType,
    SwDimensionType,
    SwDisplayStateOpts,
    SwDrawingProjectionType,
    SwDrawingViewTypes,
    SwDwgPaperSizes,
    SwDwgTemplates,
    SwDxfFormat,
    SwDxfMultisheet,
    SwExportDataFileType,
    SwExportDataSheetsToExport,
    SwFileSaveError,
    SwFileSaveWarning,
    SwImportModelItemsSource,
    SwInsertAnnotation,
    SwLeaderStyle,
    SwLineStyles,
    SwLineWeights,
    SwNumberingType,
    SwRebuildOptions,
    SwSFSymType,
    SwSaveAsOptions,
    SwSaveAsVersion,
    SwTableAnnotationType,
    SwTextJustification,
    SwViewDisplayMode,
    SwWeldSymbolContourTypes,
    decode_save_error,
)
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

    # Drawing constants
    "SwAddOrdinateDims",
    "SwAlignViewTypes",
    "SwAnnotationType",
    "SwAutodimEntities",
    "SwAutodimScheme",
    "SwBOMConfigurationAnchorType",
    "SwBalloonFit",
    "SwBalloonLayoutType",
    "SwBalloonStyle",
    "SwBalloonTextContent",
    "SwBomType",
    "SwBreakLineOrientation",
    "SwBreakLineStyle",
    "SwCenterMarkStyle",
    "SwCreateSectionViewAtOptions",
    "SwCustomInfoType",
    "SwCustomPropertyAddOption",
    "SwDatumDisplayType",
    "SwDetCircleShowType",
    "SwDimensionType",
    "SwDisplayStateOpts",
    "SwDrawingProjectionType",
    "SwDrawingViewTypes",
    "SwDwgPaperSizes",
    "SwDwgTemplates",
    "SwDxfFormat",
    "SwDxfMultisheet",
    "SwExportDataFileType",
    "SwExportDataSheetsToExport",
    "SwFileSaveError",
    "SwFileSaveWarning",
    "SwImportModelItemsSource",
    "SwInsertAnnotation",
    "SwLeaderStyle",
    "SwLineStyles",
    "SwLineWeights",
    "SwNumberingType",
    "SwRebuildOptions",
    "SwSFSymType",
    "SwSaveAsOptions",
    "SwSaveAsVersion",
    "SwTableAnnotationType",
    "SwTextJustification",
    "SwViewDisplayMode",
    "SwWeldSymbolContourTypes",
    "decode_save_error",

    # Utils
    "UnitConverter",
    "mm", "cm", "inch", "ft",
    "find_solidworks",
    "find_template",
    "get_solidworks_info",
]
