"""
Drawing Annotation Tools
--------------------------
insert_model_items, add_dimension, add_ordinate_dimensions,
set_dimension_value, set_dimension_text, autodimension_view, add_note,
add_property_note, list_notes, edit_note, list_datums, add_datum_feature,
add_gtol, add_datum_target.

Backed by `DrawingOperations` (solidworks_mcp/automation/drawings.py), per
docs/api/03-annotations.md.
"""

from typing import Dict

from ._automation import sw_automation
from .registry import tool

_ENTITY_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "Entity kind: 'edge', 'vertex', or 'face' (as returned by list_view_entities).",
        },
        "x": {"type": "number", "description": "Caller's default unit."},
        "y": {"type": "number", "description": "Caller's default unit."},
        "z": {"type": "number", "description": "Caller's default unit. Defaults to 0."},
    },
    "required": ["kind", "x", "y"],
}


@tool(
    name="insert_model_items",
    description=(
        "Import model annotations (dimensions, datums, GTols, surface "
        "finishes, weld symbols, notes, hole callouts, ...) onto a drawing "
        "view via IDrawingDoc::InsertModelAnnotations4 -- the fastest route "
        "to a fully dimensioned view for a part modeled with driving "
        "dimensions or DimXpert. Pass exactly one of view_name (a specific "
        "view) or all_views=True (every view on the active sheet, with "
        "per-view counts reported). Reports how many annotations were "
        "actually imported per view -- a zero-import result is still a "
        "warned success, not a bare 'success' with nothing to show for it. "
        "Note: center marks/centerlines are NOT importable through this "
        "tool (swInsertAnnotation_e has no bit for them) -- use the "
        "dedicated center mark/centerline tools instead."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": (
                    "Name of the drawing view to import into (see "
                    "list_views). Mutually exclusive with all_views -- "
                    "exactly one of the two is required."
                ),
            },
            "sources": {
                "type": "string",
                "default": "model",
                "description": (
                    "Where the annotations come from: 'model' (default, "
                    "all dimensions in the view), 'selected_feature', "
                    "'selected_component' (assembly drawings), or "
                    "'assembly_only'."
                ),
            },
            "types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Annotation types to import: 'dimensions', 'datums', "
                    "'datum_targets', 'gtols', 'surface_finishes', 'welds', "
                    "'notes', 'hole_callouts', 'cosmetic_threads', "
                    "'instance_counts'. Omit for the default: dimensions "
                    "+ hole_callouts."
                ),
            },
            "all_views": {
                "type": "boolean", "default": False,
                "description": (
                    "True to import into every view on the active sheet "
                    "(one call per view, per-view counts reported). "
                    "Mutually exclusive with view_name."
                ),
            },
            "eliminate_duplicates": {
                "type": "boolean", "default": True,
                "description": "True (default) to eliminate duplicate dimensions",
            },
            "hidden_features": {
                "type": "boolean", "default": False,
                "description": "True to also insert dimensions from hidden features",
            },
        },
        "required": [],
    },
)
def insert_model_items(arguments: dict) -> Dict:
    return sw_automation.insert_model_items(
        arguments.get("view_name"),
        arguments.get("sources"),
        arguments.get("types"),
        arguments.get("all_views", False),
        arguments.get("eliminate_duplicates", True),
        arguments.get("hidden_features", False),
    )


@tool(
    name="add_dimension",
    description=(
        "Add a drawing-only reference dimension between picked entities in a "
        "view -- the fallback for anything DimXpert/insert_model_items didn't "
        "already carry over. dimension_type: 'smart' (default, SolidWorks "
        "infers the result from what's selected), 'horizontal', 'vertical', "
        "'radial', 'diameter', 'angular'. entities is a list of entity "
        "references in the shape list_view_entities returns. Fewer entities "
        "than the type needs (2 for horizontal/vertical/angular, 1 otherwise) "
        "fails before any SolidWorks call is made. Returns the created "
        "dimension's name (IDimension::FullName, usable as dimension_name in "
        "set_dimension_value/set_dimension_text) and its value in the current "
        "default unit."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entities live in."},
            "entities": {
                "type": "array", "items": _ENTITY_REF_SCHEMA,
                "description": "Entities to dimension between, as returned by list_view_entities.",
            },
            "x": {"type": "number", "description": "Dimension text/line placement, default unit."},
            "y": {"type": "number", "description": "Dimension text/line placement, default unit."},
            "dimension_type": {
                "type": "string", "default": "smart",
                "description": "'smart', 'horizontal', 'vertical', 'radial', 'diameter', or 'angular'.",
            },
        },
        "required": ["view_name", "entities", "x", "y"],
    },
)
def add_dimension(arguments: dict) -> Dict:
    return sw_automation.add_dimension(
        arguments.get("view_name"),
        arguments.get("entities"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("dimension_type", "smart"),
    )


@tool(
    name="add_ordinate_dimensions",
    description=(
        "Start a baseline/ordinate dimension chain off a datum origin via "
        "IModelDocExtension::AddOrdinateDimension. origin_entity is the datum "
        "point/edge; entities are the additional members of the group -- both "
        "in the entity-reference shape list_view_entities returns. direction: "
        "'horizontal' (default), 'vertical', 'angular', or 'auto' (orientation "
        "inferred from the selected points)."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entities live in."},
            "origin_entity": {
                **_ENTITY_REF_SCHEMA,
                "description": "Datum/origin entity the ordinate group is measured from.",
            },
            "entities": {
                "type": "array", "items": _ENTITY_REF_SCHEMA,
                "description": "Additional entities to include in the ordinate group.",
            },
            "x": {"type": "number", "description": "Dimension placement, default unit."},
            "y": {"type": "number", "description": "Dimension placement, default unit."},
            "direction": {
                "type": "string", "default": "horizontal",
                "description": "'horizontal' (default), 'vertical', 'angular', or 'auto'.",
            },
        },
        "required": ["view_name", "origin_entity", "entities", "x", "y"],
    },
)
def add_ordinate_dimensions(arguments: dict) -> Dict:
    return sw_automation.add_ordinate_dimensions(
        arguments.get("view_name"),
        arguments.get("origin_entity"),
        arguments.get("entities"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("direction", "horizontal"),
    )


@tool(
    name="set_dimension_value",
    description=(
        "Set a dimension's driving value via IDimension::SetSystemValue3 "
        "(meters at the COM boundary, converted from the caller's default "
        "unit). dimension_name is IDimension::FullName, e.g. as returned by "
        "add_dimension's data.name. Fails clearly (naming the reason -- e.g. "
        "dimension driven by geometry) rather than silently no-op-ing."
    ),
    schema={
        "type": "object",
        "properties": {
            "dimension_name": {
                "type": "string",
                "description": "IDimension::FullName, e.g. 'D1@Sketch1@Part1.SLDPRT'.",
            },
            "value": {"type": "number", "description": "New value, caller's default unit."},
        },
        "required": ["dimension_name", "value"],
    },
)
def set_dimension_value(arguments: dict) -> Dict:
    return sw_automation.set_dimension_value(
        arguments.get("dimension_name"),
        arguments.get("value"),
    )


@tool(
    name="set_dimension_text",
    description=(
        "Set a dimension's prefix/suffix/full-override text via "
        "IDisplayDimension::SetText -- for tolerance callouts and 'TYP'/'REF' "
        "annotations. At least one of prefix/suffix/override is required. "
        "override replaces the entire text and clears the suffix/live value "
        "display (a SolidWorks behavior, not a bug here) -- combining it with "
        "suffix in the same call is not a meaningful combination."
    ),
    schema={
        "type": "object",
        "properties": {
            "dimension_name": {
                "type": "string",
                "description": "IDimension::FullName, e.g. 'D1@Sketch1@Part1.SLDPRT'.",
            },
            "prefix": {"type": "string", "description": "Text before the dimension value."},
            "suffix": {"type": "string", "description": "Text after the dimension value."},
            "override": {"type": "string", "description": "Full replacement text."},
        },
        "required": ["dimension_name"],
    },
)
def set_dimension_text(arguments: dict) -> Dict:
    return sw_automation.set_dimension_text(
        arguments.get("dimension_name"),
        arguments.get("prefix"),
        arguments.get("suffix"),
        arguments.get("override"),
    )


@tool(
    name="autodimension_view",
    description=(
        "Bulk-dimension a drawing view via IDrawingDoc::AutoDimension -- a "
        "'just add reasonable baseline dimensions' fallback for a view with "
        "no usable DimXpert data. scheme: 'baseline' (default), 'ordinate', "
        "'chain'. entities: 'all' (default), 'based_on_preselect', 'selected'. "
        "horizontal_placement: 'above' (default) or 'below'. "
        "vertical_placement: 'left' (default) or 'right'. Fails clearly "
        "(naming the reason, e.g. no dimensionable entities) rather than a "
        "silent no-op."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view to autodimension."},
            "scheme": {
                "type": "string", "default": "baseline",
                "description": "'baseline' (default), 'ordinate', or 'chain'.",
            },
            "entities": {
                "type": "string", "default": "all",
                "description": "'all' (default), 'based_on_preselect', or 'selected'.",
            },
            "horizontal_placement": {
                "type": "string", "default": "above",
                "description": "'above' (default) or 'below'.",
            },
            "vertical_placement": {
                "type": "string", "default": "left",
                "description": "'left' (default) or 'right'.",
            },
        },
        "required": ["view_name"],
    },
)
def autodimension_view(arguments: dict) -> Dict:
    return sw_automation.autodimension_view(
        arguments.get("view_name"),
        arguments.get("scheme", "baseline"),
        arguments.get("entities", "all"),
        arguments.get("horizontal_placement", "above"),
        arguments.get("vertical_placement", "left"),
    )


_LEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {
            "type": "string", "default": "none",
            "description": "'none' (default), 'straight', 'bent', or 'underline'.",
        },
        "x": {"type": "number", "description": "Leader attachment point, caller's default unit. Requires y too."},
        "y": {"type": "number", "description": "Leader attachment point, caller's default unit. Requires x too."},
        "z": {"type": "number", "description": "Leader attachment point, caller's default unit. Defaults to 0."},
        "smart_arrow": {
            "type": "boolean", "default": True,
            "description": "True (default) for SolidWorks' smart arrowhead style.",
        },
        "dashed": {"type": "boolean", "default": False, "description": "True for a dashed leader line."},
        "perpendicular": {
            "type": "boolean", "default": False,
            "description": "True for a perpendicular bent leader (rarely meaningful on notes).",
        },
        "all_around": {
            "type": "boolean", "default": False,
            "description": "True for an all-around leader symbol (rarely meaningful on notes).",
        },
    },
}


@tool(
    name="add_note",
    description=(
        "Add a general or flag note to a drawing sheet via IDrawingDoc::"
        "CreateText2. x/y place the note relative to the sheet's lower-left "
        "corner, caller's default unit. leader (optional) attaches a leader "
        "with a style ('none'/'straight'/'bent'/'underline') and an "
        "optional attachment point + arrow style -- see the leader schema. "
        "text accepts '\\n' for multi-line notes (SolidWorks' own line-feed "
        "convention -- passed straight through, no translation needed). "
        "bold/italic wrap the text in SolidWorks' '<FONT style=B/I>' inline "
        "formatting instruction. Returns the note's SolidWorks-assigned "
        "name (data.name, e.g. 'Note1') -- pass that to edit_note to update "
        "it later."
    ),
    schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Note text. '\\n' starts a new line."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "view_name": {
                "type": "string",
                "description": "Drawing view to activate first, so the note is authored in its context. Omit for whatever's already active.",
            },
            "leader": _LEADER_SCHEMA,
            "height": {
                "type": "number",
                "description": "Text height, caller's default unit. Omit for the document's default note height.",
            },
            "angle": {"type": "number", "default": 0, "description": "Text angle, degrees."},
            "bold": {"type": "boolean", "default": False},
            "italic": {"type": "boolean", "default": False},
            "layer": {"type": "string", "description": "Layer name (IAnnotation::Layer) to file the note under."},
        },
        "required": ["text", "x", "y"],
    },
)
def add_note(arguments: dict) -> Dict:
    return sw_automation.add_note(
        arguments.get("text"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("view_name"),
        arguments.get("leader"),
        arguments.get("height"),
        arguments.get("angle", 0),
        arguments.get("bold", False),
        arguments.get("italic", False),
        arguments.get("layer"),
    )


@tool(
    name="add_property_note",
    description=(
        "Add a note whose text is entirely a linked custom-property "
        "reference -- the mechanism that keeps a title block's 'Weight'/"
        "'Material'/etc. fields live against the model, via INote::"
        "PropertyLinkedText. source='sheet' (default) emits "
        "$PRPSHEET:\"property_name\" (the model shown in the sheet's "
        "'model shown in' setting -- what title blocks use for part "
        "properties); source='model' emits $PRP:\"property_name\" (the "
        "drawing document's own properties). prefix/suffix add literal "
        "text around the link, e.g. prefix='Weight: '. Accepts the same "
        "view_name/leader/height/angle/bold/italic/layer options as "
        "add_note."
    ),
    schema={
        "type": "object",
        "properties": {
            "property_name": {"type": "string", "description": "Custom property name to link, e.g. 'SW-Mass'."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "source": {
                "type": "string", "default": "sheet",
                "description": "'sheet' (default, emits $PRPSHEET:...) or 'model' (emits $PRP:...).",
            },
            "prefix": {"type": "string", "default": "", "description": "Literal text before the link."},
            "suffix": {"type": "string", "default": "", "description": "Literal text after the link."},
            "view_name": {"type": "string", "description": "Same as add_note's view_name."},
            "leader": _LEADER_SCHEMA,
            "height": {"type": "number", "description": "Same as add_note's height."},
            "angle": {"type": "number", "default": 0, "description": "Same as add_note's angle."},
            "bold": {"type": "boolean", "default": False},
            "italic": {"type": "boolean", "default": False},
            "layer": {"type": "string", "description": "Same as add_note's layer."},
        },
        "required": ["property_name", "x", "y"],
    },
)
def add_property_note(arguments: dict) -> Dict:
    note_opts = {}
    for key in ("view_name", "leader", "height", "angle", "bold", "italic", "layer"):
        if key in arguments:
            note_opts[key] = arguments[key]
    return sw_automation.add_property_note(
        arguments.get("property_name"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("source", "sheet"),
        arguments.get("prefix", ""),
        arguments.get("suffix", ""),
        **note_opts,
    )


@tool(
    name="list_notes",
    description=(
        "Enumerate existing notes -- text, position, layer -- via IView::"
        "GetFirstNote/INote::GetNext, so an LLM can find (and then "
        "edit_note) a template's placeholder notes without a mouse. "
        "view_name restricts to one view's notes; sheet_name restricts to "
        "one sheet's real views plus its sheet-level/title-block notes. "
        "Omit both for every note in the whole document."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Restrict to this view's notes."},
            "sheet_name": {"type": "string", "description": "Restrict to this sheet's notes. Ignored if view_name is also given."},
        },
        "required": [],
    },
)
def list_notes(arguments: dict) -> Dict:
    return sw_automation.list_notes(
        arguments.get("view_name"),
        arguments.get("sheet_name"),
    )


@tool(
    name="edit_note",
    description=(
        "Update an existing note's text and/or position -- how a caller "
        "fills in a template's placeholder notes without recreating them. "
        "note_name is IAnnotation::GetName's value (e.g. 'Note1'), as "
        "returned by add_note/add_property_note's data.name or list_notes' "
        "data.notes[i].name. Unrecognized: fails listing every note name "
        "found in the document. text accepts '\\n' for multi-line, same as "
        "add_note. x/y may be given alone -- the other axis is read back "
        "from the note's current position and left unchanged."
    ),
    schema={
        "type": "object",
        "properties": {
            "note_name": {"type": "string", "description": "IAnnotation::GetName's value for the target note."},
            "text": {"type": "string", "description": "New text. '\\n' starts a new line."},
            "x": {"type": "number", "description": "New position, caller's default unit."},
            "y": {"type": "number", "description": "New position, caller's default unit."},
        },
        "required": ["note_name"],
    },
)
def edit_note(arguments: dict) -> Dict:
    return sw_automation.edit_note(
        arguments.get("note_name"),
        arguments.get("text"),
        arguments.get("x"),
        arguments.get("y"),
    )


_GTOL_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "Entity kind: 'edge', 'face', 'dimension', or 'vertex'.",
        },
        "x": {"type": "number", "description": "Caller's default unit."},
        "y": {"type": "number", "description": "Caller's default unit."},
        "z": {"type": "number", "description": "Caller's default unit. Defaults to 0."},
    },
    "required": ["kind", "x", "y"],
}

_DATUM_REF_SCHEMA = {
    "oneOf": [
        {"type": "string", "description": "Bare datum letter, e.g. 'A'."},
        {
            "type": "object",
            "properties": {
                "letter": {"type": "string", "description": "Datum letter, e.g. 'A'."},
                "modifier": {"type": "string", "description": "'MMC', 'LMC', or 'RFS'."},
            },
            "required": ["letter"],
        },
    ],
}


@tool(
    name="list_datums",
    description=(
        "Enumerate existing datum feature tags -- label, position, view -- "
        "via IView::GetFirstDatumTag/IDatumTag::GetNext, so add_gtol's "
        "datum-letter validation and add_datum_feature's auto-lettering "
        "have something to read. sheet_name restricts to one sheet; omit "
        "for every datum tag in the document. data.letters is the sorted, "
        "deduplicated set of labels found."
    ),
    schema={
        "type": "object",
        "properties": {
            "sheet_name": {"type": "string", "description": "Restrict to this sheet's datum tags."},
        },
        "required": [],
    },
)
def list_datums(arguments: dict) -> Dict:
    return sw_automation.list_datums(arguments.get("sheet_name"))


@tool(
    name="add_datum_feature",
    description=(
        "Place a datum feature symbol (A, B, C...) on a selected edge/face/"
        "dimension via IModelDoc2::InsertDatumTag2. label is the datum "
        "letter (up to 2 characters) -- omit to auto-assign the next unused "
        "letter A-Z, skipping the reserved letters I, O, Q (reading "
        "existing tags via list_datums). Explicitly passing I/O/Q fails. "
        "style: 'default', 'square', or 'round' (IDatumTag::SetDisplayStyle)."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entity lives in."},
            "entity": {**_GTOL_ENTITY_SCHEMA, "description": "Entity to attach the datum feature to."},
            "label": {"type": "string", "description": "Datum letter. Omit to auto-assign."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "style": {"type": "string", "description": "'default', 'square', or 'round'."},
        },
        "required": ["view_name", "entity", "x", "y"],
    },
)
def add_datum_feature(arguments: dict) -> Dict:
    return sw_automation.add_datum_feature(
        arguments.get("view_name"),
        arguments.get("entity"),
        arguments.get("label"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("style"),
    )


@tool(
    name="add_gtol",
    description=(
        "Add a geometric tolerance feature control frame via IModelDoc2::"
        "InsertGtol + IGtol::SetFrameSymbols2/SetFrameValues2. symbol is one "
        "of the 14 geometric characteristics: 'position', 'flatness', "
        "'perpendicularity', 'parallelism', 'concentricity', 'straightness', "
        "'circularity', 'cylindricity', 'profile_of_a_line', "
        "'profile_of_a_surface', 'angularity', 'symmetry', "
        "'circular_runout', 'total_runout'. datums is an ordered list of up "
        "to 3 references (primary/secondary/tertiary), each a bare letter "
        "string or {letter, modifier: 'MMC'|'LMC'|'RFS'} -- every letter "
        "must already exist on the drawing (see list_datums/"
        "add_datum_feature), and form tolerances (flatness, straightness, "
        "circularity, cylindricity) must omit datums while orientation/"
        "location/runout characteristics require at least one. "
        "material_condition modifies the tolerance value itself. "
        "projected_zone (IGtol::SetPTZHeight2) adds a projected-tolerance-"
        "zone height. leader=False creates a freestanding GTol with no "
        "selection. composite adds a second stacked frame row: "
        "{tolerance, datums, material_condition}."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entity lives in."},
            "entity": {**_GTOL_ENTITY_SCHEMA, "description": "Entity to attach the GTol to."},
            "symbol": {"type": "string", "description": "One of the 14 geometric characteristics."},
            "tolerance": {"type": "number", "description": "Tolerance zone value, caller's default unit."},
            "datums": {
                "type": "array", "items": _DATUM_REF_SCHEMA,
                "description": "Up to 3 ordered datum references.",
            },
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
            "material_condition": {"type": "string", "description": "'MMC', 'LMC', or 'RFS'."},
            "projected_zone": {"type": "number", "description": "Projected tolerance zone height."},
            "leader": {"type": "boolean", "default": True, "description": "False for a freestanding GTol."},
            "composite": {
                "type": "object",
                "properties": {
                    "tolerance": {"type": "number"},
                    "datums": {"type": "array", "items": _DATUM_REF_SCHEMA},
                    "material_condition": {"type": "string"},
                },
                "description": "Optional second stacked frame row (composite feature control frame).",
            },
        },
        "required": ["view_name", "entity", "symbol", "tolerance"],
    },
)
def add_gtol(arguments: dict) -> Dict:
    return sw_automation.add_gtol(
        arguments.get("view_name"),
        arguments.get("entity"),
        arguments.get("symbol"),
        arguments.get("tolerance"),
        arguments.get("datums"),
        arguments.get("x"),
        arguments.get("y"),
        arguments.get("material_condition"),
        arguments.get("projected_zone"),
        arguments.get("leader", True),
        arguments.get("composite"),
    )


@tool(
    name="add_datum_target",
    description=(
        "Add a datum target symbol via IModelDocExtension::"
        "InsertDatumTargetSymbol3. label is the target's datum reference "
        "text (e.g. 'a1'). area_type: 'point', 'circle', or 'rectangle'. "
        "size is the target area diameter/width, caller's default unit."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {"type": "string", "description": "Drawing view the entity lives in."},
            "entity": {**_GTOL_ENTITY_SCHEMA, "description": "Entity (typically a face) to attach the target to."},
            "label": {"type": "string", "description": "Datum target label, e.g. 'a1'."},
            "area_type": {"type": "string", "description": "'point', 'circle', or 'rectangle'."},
            "size": {"type": "number", "description": "Target area diameter/width, caller's default unit."},
            "x": {"type": "number", "description": "Placement, caller's default unit."},
            "y": {"type": "number", "description": "Placement, caller's default unit."},
        },
        "required": ["view_name", "entity", "label", "area_type", "size", "x", "y"],
    },
)
def add_datum_target(arguments: dict) -> Dict:
    return sw_automation.add_datum_target(
        arguments.get("view_name"),
        arguments.get("entity"),
        arguments.get("label"),
        arguments.get("area_type"),
        arguments.get("size"),
        arguments.get("x"),
        arguments.get("y"),
    )
