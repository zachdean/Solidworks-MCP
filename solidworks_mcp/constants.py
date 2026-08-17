"""
SolidWorks MCP Constants
------------------------
All constants, enums, and error codes for SolidWorks automation.
"""

from enum import IntEnum


# ============================================================================
# Error Codes
# ============================================================================

class SwErrors(IntEnum):
    """SolidWorks MCP error codes"""
    swSuccess = 0
    swFileNotFoundError = 2
    swFileLoadError = 3
    swFileSaveError = 4
    swInvalidFileType = 5
    swConnectionError = 100
    swNoActiveDocument = 101
    swSketchError = 102
    swFeatureError = 103
    swSelectionError = 104
    swSolidWorksNotFound = 105
    swTemplateNotFound = 106
    swInvalidInput = 107
    swSimulationError = 108
    swExportError = 109
    swVersionUnsupported = 110
    swUnknownError = 999


# ============================================================================
# Document Types
# ============================================================================

class SwDocumentTypes(IntEnum):
    """SolidWorks document types (swDocumentTypes_e).

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """
    swDocNONE = 0
    swDocPART = 1
    swDocASSEMBLY = 2
    swDocDRAWING = 3
    swDocSDM = 4
    swDocLAYOUT = 5
    swDocIMPORTED_PART = 6
    swDocIMPORTED_ASSEMBLY = 7

    @classmethod
    def name_of(cls, code) -> str:
        """Readable name for a `swDocumentTypes_e` code.

        The single source of truth for turning `IModelDoc2::GetType` into
        something worth showing a caller -- previously open-coded as three
        partial `{0: "None", 1: "Part", ...}` literals that each covered a
        different subset of the enum and drifted as members were added.
        Unknown codes render as `unknown type <code>` rather than a bare
        "Unknown", so a new swconst member is diagnosable from the message.
        """
        try:
            return _DOC_TYPE_NAMES[cls(code)]
        except (ValueError, KeyError):
            return f"unknown type {code!r}"


_DOC_TYPE_NAMES = {
    SwDocumentTypes.swDocNONE: "no document",
    SwDocumentTypes.swDocPART: "Part",
    SwDocumentTypes.swDocASSEMBLY: "Assembly",
    SwDocumentTypes.swDocDRAWING: "Drawing",
    SwDocumentTypes.swDocSDM: "SDM",
    SwDocumentTypes.swDocLAYOUT: "Layout",
    SwDocumentTypes.swDocIMPORTED_PART: "Imported Part",
    SwDocumentTypes.swDocIMPORTED_ASSEMBLY: "Imported Assembly",
}


# ============================================================================
# Plane Names
# ============================================================================

class SwPlanes:
    """Standard SolidWorks plane names"""
    FRONT = "Front Plane"
    TOP = "Top Plane"
    RIGHT = "Right Plane"
    
    @classmethod
    def get(cls, name: str) -> str:
        """Get plane name from short name"""
        plane_map = {
            "front": cls.FRONT,
            "top": cls.TOP,
            "right": cls.RIGHT,
        }
        return plane_map.get(name.lower(), cls.FRONT)
    
    @classmethod
    def all(cls) -> list:
        """Get all plane names"""
        return [cls.FRONT, cls.TOP, cls.RIGHT]


# ============================================================================
# Feature End Conditions
# ============================================================================

class SwEndConditions(IntEnum):
    """Extrusion end conditions"""
    swEndCondBlind = 0
    swEndCondThroughAll = 1
    swEndCondThroughAllBoth = 2
    swEndCondThroughNext = 3
    swEndCondUpToVertex = 4
    swEndCondUpToSurface = 5
    swEndCondMidPlane = 6
    swEndCondOffsetFromSurface = 7


# ============================================================================
# Mate Types
# ============================================================================

class SwMateTypes(IntEnum):
    """Assembly mate types"""
    swMateCOINCIDENT = 0
    swMateCONCENTRIC = 1
    swMatePERPENDICULAR = 2
    swMatePARALLEL = 3
    swMateTANGENT = 4
    swMateDISTANCE = 5
    swMateANGLE = 6
    swMateLOCK = 16
    swMateWIDTH = 18


# ============================================================================
# View Types
# ============================================================================

class SwViews:
    """Standard view orientations"""
    FRONT = ("*Front", 1)
    BACK = ("*Back", 2)
    LEFT = ("*Left", 3)
    RIGHT = ("*Right", 4)
    TOP = ("*Top", 5)
    BOTTOM = ("*Bottom", 6)
    ISOMETRIC = ("*Isometric", 7)
    TRIMETRIC = ("*Trimetric", 8)
    DIMETRIC = ("*Dimetric", 9)
    
    @classmethod
    def get(cls, name: str):
        """Get view tuple from name"""
        view_map = {
            "front": cls.FRONT,
            "back": cls.BACK,
            "left": cls.LEFT,
            "right": cls.RIGHT,
            "top": cls.TOP,
            "bottom": cls.BOTTOM,
            "isometric": cls.ISOMETRIC,
            "trimetric": cls.TRIMETRIC,
            "dimetric": cls.DIMETRIC,
        }
        return view_map.get(name.lower(), cls.ISOMETRIC)


# ============================================================================
# File Extensions
# ============================================================================

class SwFileTypes:
    """SolidWorks file extensions"""
    PART = ".sldprt"
    ASSEMBLY = ".sldasm"
    DRAWING = ".slddrw"
    PART_TEMPLATE = ".prtdot"
    ASSEMBLY_TEMPLATE = ".asmdot"
    DRAWING_TEMPLATE = ".drwdot"
    
    # Export formats
    STEP = ".step"
    STEP_ALT = ".stp"
    STL = ".stl"
    IGES = ".igs"
    PARASOLID = ".x_t"
    DXF = ".dxf"
    DWG = ".dwg"
    PDF = ".pdf"
    
    @classmethod
    def is_valid_part(cls, ext: str) -> bool:
        return ext.lower() == cls.PART

    @classmethod
    def doc_type_for(cls, ext: str) -> "SwDocumentTypes":
        """`swDocumentTypes_e` for a file extension -- `OpenDoc6`'s `Type`
        argument. Defaults to `swDocPART` for an unrecognized extension, the
        behaviour both former copies of this map already had."""
        return _DOC_TYPE_BY_EXT.get(ext.lower(), SwDocumentTypes.swDocPART)

    @classmethod
    def is_valid_export(cls, ext: str) -> bool:
        valid = [cls.STEP, cls.STEP_ALT, cls.STL, cls.IGES, cls.PARASOLID, cls.DXF, cls.DWG, cls.PDF]
        return ext.lower() in valid


_DOC_TYPE_BY_EXT = {
    SwFileTypes.PART: SwDocumentTypes.swDocPART,
    SwFileTypes.ASSEMBLY: SwDocumentTypes.swDocASSEMBLY,
    SwFileTypes.DRAWING: SwDocumentTypes.swDocDRAWING,
}


# ============================================================================
# Selection Types
# ============================================================================

class SwSelectType:
    """Entity selection types for SelectByID2"""
    FACE = "FACE"
    EDGE = "EDGE"
    VERTEX = "VERTEX"
    PLANE = "PLANE"
    AXIS = "AXIS"
    SKETCH = "SKETCH"
    SKETCHSEGMENT = "SKETCHSEGMENT"
    SKETCHPOINT = "SKETCHPOINT"
    BODYFEATURE = "BODYFEATURE"
    COMPONENT = "COMPONENT"
    EXTSKETCHSEGMENT = "EXTSKETCHSEGMENT"


# ============================================================================
# Default Values
# ============================================================================

class Defaults:
    """Default values for operations"""
    EXTRUDE_DEPTH_MM = 10.0
    FILLET_RADIUS_MM = 2.0
    CHAMFER_DISTANCE_MM = 2.0
    CIRCLE_RADIUS_MM = 25.0
    RECTANGLE_WIDTH_MM = 100.0
    RECTANGLE_HEIGHT_MM = 50.0
    
    CONNECTION_TIMEOUT = 120  # seconds
    RETRY_INTERVAL = 5  # seconds
    MAX_RETRIES = 3
