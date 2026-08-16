"""
Feature Tools
-------------
extrude_sketch, cut_extrude, fillet_edges, chamfer_edges, list_features.
"""

import logging
import traceback
from typing import Dict

from . import sw_automation
from .registry import tool

logger = logging.getLogger("SolidWorksMCP")


@tool(
    name="extrude_sketch",
    description="Extrude the active sketch (Boss-Extrude).",
    schema={
        "type": "object",
        "properties": {
            "depth": {"type": "number", "default": 10, "description": "Extrusion depth"},
            "both_directions": {"type": "boolean", "default": False, "description": "Extrude in both directions"},
            "unit": {"type": "string", "description": "Unit"}
        },
        "required": []
    },
)
def extrude_sketch(arguments: dict) -> Dict:
    return sw_automation.extrude_sketch(
        arguments.get("depth", 10),
        arguments.get("both_directions", False),
        arguments.get("unit")
    )


@tool(
    name="cut_extrude",
    description="Cut extrude to remove material.",
    schema={
        "type": "object",
        "properties": {
            "depth": {"type": "number", "default": 10, "description": "Cut depth"},
            "through_all": {"type": "boolean", "default": False, "description": "Cut through all"},
            "both_directions": {"type": "boolean", "default": False, "description": "Cut both directions"},
            "unit": {"type": "string", "description": "Unit"}
        },
        "required": []
    },
)
def cut_extrude(arguments: dict) -> Dict:
    return sw_automation.cut_extrude(
        arguments.get("depth", 10),
        arguments.get("through_all", False),
        arguments.get("both_directions", False),
        arguments.get("unit")
    )


@tool(
    name="fillet_edges",
    description="Add fillet to selected edges.",
    schema={
        "type": "object",
        "properties": {
            "radius": {"type": "number", "default": 2, "description": "Fillet radius"},
            "unit": {"type": "string", "description": "Unit"}
        },
        "required": []
    },
)
def fillet_edges(arguments: dict) -> Dict:
    return sw_automation.fillet_edges(
        arguments.get("radius", 2),
        arguments.get("unit")
    )


@tool(
    name="chamfer_edges",
    description="Add chamfer to selected edges.",
    schema={
        "type": "object",
        "properties": {
            "distance": {"type": "number", "default": 2, "description": "Chamfer distance"},
            "angle": {"type": "number", "default": 45, "description": "Chamfer angle (degrees)"},
            "unit": {"type": "string", "description": "Unit"}
        },
        "required": []
    },
)
def chamfer_edges(arguments: dict) -> Dict:
    return sw_automation.chamfer_edges(
        arguments.get("distance", 2),
        arguments.get("angle", 45),
        arguments.get("unit")
    )


# ============================================================================
# list_features handler
# ============================================================================

def _list_features_fixed() -> Dict:
    """
    List all features in the active document.
    FIXED v4.1: Property access for SW 2025 (FirstFeature, GetNextFeature, GetTypeName2).
    """
    try:
        doc, err = sw_automation.get_active_doc()
        if err:
            return err

        features = []

        # FIXED: FirstFeature is a property in SW 2025 COM, not a method
        try:
            feat = doc.FirstFeature
        except AttributeError:
            feat = doc.FirstFeature()

        while feat is not None:
            try:
                name = ""
                feat_type = ""
                suppressed = False

                try:
                    name = feat.Name
                except:
                    name = "<unknown>"

                # FIXED: GetTypeName2 is a property in SW 2025 COM
                try:
                    feat_type = feat.GetTypeName2
                    if callable(feat_type):
                        feat_type = feat_type()
                except:
                    try:
                        feat_type = feat.GetTypeName()
                    except:
                        feat_type = "<unknown>"

                try:
                    suppressed = feat.IsSuppressed()
                except:
                    suppressed = False

                features.append({
                    "name": name,
                    "type": feat_type,
                    "suppressed": bool(suppressed)
                })

            except Exception as e:
                features.append({
                    "name": "<error>",
                    "type": str(e),
                    "suppressed": False
                })

            # FIXED: GetNextFeature is a property in SW 2025 COM
            try:
                feat = feat.GetNextFeature
                if callable(feat):
                    feat = feat()
            except:
                break

        return {
            "success": True,
            "message": f"{len(features)} features found",
            "error_code": 0,
            "error_name": "swSuccess",
            "data": {"features": features, "count": len(features)}
        }

    except Exception as e:
        logger.error(f"List features error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {}
        }


@tool(
    name="list_features",
    description="List all features in the model.",
    schema={"type": "object", "properties": {}, "required": []},
)
def list_features(arguments: dict) -> Dict:
    return _list_features_fixed()
