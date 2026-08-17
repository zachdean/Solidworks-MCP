"""
Sketch Tools
------------
create_sketch, create_sketch_on_face, draw_line, draw_circle,
draw_rectangle, draw_arc, draw_polygon, close_sketch, get_sketch_status.
"""

import logging
import traceback
from typing import Dict

from ._automation import sw_automation
from .registry import tool

logger = logging.getLogger("SolidWorksMCP")


@tool(
    name="create_sketch",
    description="Create a new sketch on a plane.",
    schema={
        "type": "object",
        "properties": {
            "plane": {
                "type": "string",
                "enum": ["Front", "Top", "Right"],
                "default": "Front",
                "description": "Plane to sketch on"
            }
        },
        "required": []
    },
)
def create_sketch(arguments: dict) -> Dict:
    return sw_automation.create_sketch(arguments.get("plane", "Front"))


@tool(
    name="create_sketch_on_face",
    description="Create a new sketch on an existing body face (by 3D coordinates). Use for cut-extrude on faces instead of reference planes.",
    schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "default": 0, "description": "X coordinate on the face"},
            "y": {"type": "number", "default": 0, "description": "Y coordinate on the face"},
            "z": {"type": "number", "default": 0, "description": "Z coordinate on the face"},
            "unit": {"type": "string", "description": "Unit (mm, inch, m)"}
        },
        "required": []
    },
)
def create_sketch_on_face(arguments: dict) -> Dict:
    return sw_automation.create_sketch_on_face(
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("z", 0),
        arguments.get("unit")
    )


@tool(
    name="draw_line",
    description="Draw a line in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x1": {"type": "number", "default": 0, "description": "Start X"},
            "y1": {"type": "number", "default": 0, "description": "Start Y"},
            "x2": {"type": "number", "default": 100, "description": "End X"},
            "y2": {"type": "number", "default": 0, "description": "End Y"},
            "unit": {"type": "string", "description": "Unit (mm, inch, m)"}
        },
        "required": []
    },
)
def draw_line(arguments: dict) -> Dict:
    return sw_automation.draw_line(
        arguments.get("x1", 0),
        arguments.get("y1", 0),
        arguments.get("x2", 100),
        arguments.get("y2", 0),
        arguments.get("unit")
    )


@tool(
    name="draw_circle",
    description="Draw a circle in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "default": 0, "description": "Center X"},
            "y": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "unit": {"type": "string", "description": "Unit (mm, inch, m)"}
        },
        "required": []
    },
)
def draw_circle(arguments: dict) -> Dict:
    return sw_automation.draw_circle(
        arguments.get("x", 0),
        arguments.get("y", 0),
        arguments.get("radius", 25),
        arguments.get("unit")
    )


@tool(
    name="draw_rectangle",
    description="Draw a rectangle in the active sketch.",
    schema={
        "type": "object",
        "properties": {
            "x1": {"type": "number", "default": -50, "description": "First corner X"},
            "y1": {"type": "number", "default": -25, "description": "First corner Y"},
            "x2": {"type": "number", "default": 50, "description": "Second corner X"},
            "y2": {"type": "number", "default": 25, "description": "Second corner Y"},
            "unit": {"type": "string", "description": "Unit (mm, inch, m)"}
        },
        "required": []
    },
)
def draw_rectangle(arguments: dict) -> Dict:
    return sw_automation.draw_rectangle(
        arguments.get("x1", -50),
        arguments.get("y1", -25),
        arguments.get("x2", 50),
        arguments.get("y2", 25),
        arguments.get("unit")
    )


@tool(
    name="draw_arc",
    description="Draw an arc by center and angles.",
    schema={
        "type": "object",
        "properties": {
            "cx": {"type": "number", "default": 0, "description": "Center X"},
            "cy": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "start_angle": {"type": "number", "default": 0, "description": "Start angle (degrees)"},
            "end_angle": {"type": "number", "default": 90, "description": "End angle (degrees)"},
            "unit": {"type": "string", "description": "Unit for radius"}
        },
        "required": []
    },
)
def draw_arc(arguments: dict) -> Dict:
    return sw_automation.draw_arc_center(
        arguments.get("cx", 0),
        arguments.get("cy", 0),
        arguments.get("radius", 25),
        arguments.get("start_angle", 0),
        arguments.get("end_angle", 90),
        arguments.get("unit")
    )


@tool(
    name="draw_polygon",
    description="Draw a regular polygon.",
    schema={
        "type": "object",
        "properties": {
            "cx": {"type": "number", "default": 0, "description": "Center X"},
            "cy": {"type": "number", "default": 0, "description": "Center Y"},
            "radius": {"type": "number", "default": 25, "description": "Radius"},
            "sides": {"type": "integer", "default": 6, "description": "Number of sides (3-100)"},
            "unit": {"type": "string", "description": "Unit"}
        },
        "required": []
    },
)
def draw_polygon(arguments: dict) -> Dict:
    return sw_automation.draw_polygon(
        arguments.get("cx", 0),
        arguments.get("cy", 0),
        arguments.get("radius", 25),
        arguments.get("sides", 6),
        arguments.get("unit")
    )


# ============================================================================
# close_sketch handler
# ============================================================================

def _close_sketch_handler() -> Dict:
    """
    Close the active sketch if one is open.
    Returns sketch status info.
    """
    try:
        doc, err = sw_automation.get_active_doc()
        if err:
            return err

        # Check if sketch is active
        had_active = False
        try:
            active_sketch = doc.SketchManager.ActiveSketch
            had_active = active_sketch is not None
        except:
            pass

        if had_active:
            try:
                doc.SketchManager.InsertSketch(True)
            except:
                try:
                    doc.InsertSketch2(True)
                except:
                    pass

            return {
                "success": True,
                "message": "Sketch closed successfully",
                "error_code": 0,
                "error_name": "swSuccess",
                "data": {"had_active_sketch": True, "action": "closed"}
            }
        else:
            return {
                "success": True,
                "message": "No active sketch to close",
                "error_code": 0,
                "error_name": "swSuccess",
                "data": {"had_active_sketch": False, "action": "none"}
            }

    except Exception as e:
        logger.error(f"Close sketch error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"traceback": traceback.format_exc()}
        }


@tool(
    name="close_sketch",
    description="Close/exit the active sketch. Call this before extrude if sketch is still open.",
    schema={"type": "object", "properties": {}, "required": []},
)
def close_sketch(arguments: dict) -> Dict:
    return _close_sketch_handler()


# ============================================================================
# get_sketch_status handler
# ============================================================================

def _get_sketch_status_handler() -> Dict:
    """
    Get diagnostic info about the current sketch state.
    Useful for debugging sketch/extrude issues.
    """
    try:
        doc, err = sw_automation.get_active_doc()
        if err:
            return err

        info = {
            "has_active_sketch": False,
            "active_sketch_name": None,
            "sketch_count": 0,
            "sketch_names": [],
            "feature_count": 0,
            "extrusion_count": 0,
        }

        # Check active sketch
        try:
            active_sketch = doc.SketchManager.ActiveSketch
            if active_sketch is not None:
                info["has_active_sketch"] = True
                try:
                    info["active_sketch_name"] = active_sketch.Name
                except:
                    info["active_sketch_name"] = "<unknown>"
        except:
            pass

        # Walk feature tree (using PROPERTIES not methods)
        try:
            feat = doc.FirstFeature
            while feat is not None:
                try:
                    feat_type = feat.GetTypeName2
                    info["feature_count"] += 1

                    if feat_type == "ProfileFeature":
                        info["sketch_count"] += 1
                        info["sketch_names"].append(feat.Name)
                    elif feat_type == "Extrusion":
                        info["extrusion_count"] += 1
                except:
                    pass
                try:
                    feat = feat.GetNextFeature
                except:
                    break
        except:
            pass

        # Build readable message
        status = "OPEN" if info["has_active_sketch"] else "CLOSED"
        msg = (f"Sketch status: {status}. "
               f"Sketches: {info['sketch_count']} {info['sketch_names']}. "
               f"Extrusions: {info['extrusion_count']}. "
               f"Total features: {info['feature_count']}")

        return {
            "success": True,
            "message": msg,
            "error_code": 0,
            "error_name": "swSuccess",
            "data": info
        }

    except Exception as e:
        logger.error(f"Sketch status error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"traceback": traceback.format_exc()}
        }


@tool(
    name="get_sketch_status",
    description="Get diagnostic info: active sketch state, sketch count, sketch names in feature tree.",
    schema={"type": "object", "properties": {}, "required": []},
)
def get_sketch_status(arguments: dict) -> Dict:
    return _get_sketch_status_handler()
