"""
Declarative drawing-pack spec + offline validator.

`PackSpec` describes a whole drawing pack (a template, an output path, and a
list of sheets) as plain dataclasses -- JSON in, JSON out, no SolidWorks
required. A separate compiler (sw-wds.2) lowers a validated `PackSpec` into
an ordered sequence of `DrawingOperations`/COM calls; this module never talks
to any COM object or the backend that wraps them, so it is fully testable
without Windows or a SolidWorks install.

`ViewSpec`/`AnnotationSpec`/`TableSpec` are each a single flat dataclass with
a discriminating `kind` field rather than a class hierarchy per kind -- that
keeps `from_dict`/`to_dict`/schema generation generic (one code path for all
kinds) at the cost of most fields being optional and only meaningful for a
subset of `kind` values. `validate()` enforces which fields each `kind`
actually requires.
"""

import dataclasses
import functools
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, get_args, get_origin, get_type_hints

# ---------------------------------------------------------------------------
# Discriminator vocabularies
# ---------------------------------------------------------------------------

# Every view kind from the view epic: model, projected, section, detail,
# broken-out, break, crop.
VIEW_KINDS = frozenset(
    {"model", "projected", "section", "detail", "broken_out", "break", "crop"}
)

# View kinds that create a new, independently addressable view (i.e. they
# populate ViewSpec.name and participate in the sheet's view-name namespace).
VIEW_KINDS_CREATING = frozenset({"model", "projected", "section", "detail", "broken_out"})

# View kinds that reference an existing view via ViewSpec.parent, which must
# already be defined earlier in the same sheet.
VIEW_KINDS_WITH_PARENT = frozenset({"projected", "section", "detail", "broken_out"})

# View kinds that mutate an existing view in place via ViewSpec.target,
# rather than creating a new named view.
VIEW_KINDS_WITH_TARGET = frozenset({"break", "crop"})

ANNOTATION_KINDS = frozenset(
    {"note", "gtol", "datum_feature", "datum_target", "surface_finish", "balloon"}
)

TABLE_KINDS = frozenset({"bom", "hole", "revision", "weldment_cutlist"})

# Required-field lists per `kind`, in addition to the dataclass's own
# unconditionally-required fields (see `_DataclassJSON` / `dataclasses.MISSING`
# handling below). Values are attribute names checked for "empty" (None, "",
# or []) via `_is_missing`.
_VIEW_REQUIRED_BY_KIND = {
    "model": ["name", "model_path"],
    "projected": ["name", "parent", "direction"],
    "section": ["name", "parent", "cut_points"],
    "detail": ["name", "parent", "center_x", "center_y", "radius"],
    "broken_out": ["name", "parent", "profile_points"],
    "break": ["target", "position1", "position2"],
    "crop": ["target", "profile_points"],
}

_ANNOTATION_REQUIRED_BY_KIND = {
    "note": ["view", "text"],
    "gtol": ["view", "entity", "symbol", "tolerance"],
    "datum_feature": ["view", "entity", "label"],
    "datum_target": ["view", "entity", "label", "area_type", "size"],
    "surface_finish": ["view", "entity", "symbol_type"],
    "balloon": ["view", "entity"],
}

_TABLE_REQUIRED_BY_KIND = {
    "bom": ["view"],
    "hole": ["view"],
    "revision": [],
    "weldment_cutlist": ["view"],
}


# ---------------------------------------------------------------------------
# from_dict/to_dict machinery, shared by every pack dataclass
# ---------------------------------------------------------------------------


def _is_optional(tp) -> Optional[Any]:
    """Union[X, None] -> X, else None."""
    if get_origin(tp) is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return None


def _convert_value(tp, value):
    if value is None:
        return None
    inner = _is_optional(tp)
    if inner is not None:
        return _convert_value(inner, value)

    origin = get_origin(tp)
    if origin in (list, List):
        (item_t,) = get_args(tp)
        return [_convert_value(item_t, v) for v in value]
    if origin in (dict, Dict):
        return dict(value)
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        if dataclasses.is_dataclass(value):
            return value
        return tp.from_dict(value)
    return value


@functools.lru_cache(maxsize=None)
def _hints(cls) -> Dict[str, Any]:
    """`get_type_hints(cls)` memoized -- class annotations never change at
    runtime, but resolving them is not cheap and both `from_dict` (once per
    object parsed from JSON) and `_dataclass_json_schema` ask repeatedly."""
    return get_type_hints(cls)


class _DataclassJSON:
    """Mixin giving every pack dataclass generic, type-hint-driven
    `from_dict`/`to_dict` -- one implementation instead of one per class."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        hints = _hints(cls)
        kwargs = {}
        for f in dataclasses.fields(cls):
            if f.name not in data:
                continue
            kwargs[f.name] = _convert_value(hints[f.name], data[f.name])
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Pack dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScaleSpec(_DataclassJSON):
    """A drawing-view/sheet scale, num:denom (matches add_sheet's
    scale_num/scale_denom and insert_detail_view's scale_num/scale_denom)."""

    num: float = 1
    denom: float = 1


@dataclass
class ViewSpec(_DataclassJSON):
    """One drawing view. `kind` discriminates which of the fields below
    apply -- see `VIEW_KINDS` and `_VIEW_REQUIRED_BY_KIND`.

    `name` identifies a newly created view (model/projected/section/detail/
    broken_out) for later reference by `parent`, by an AnnotationSpec/
    TableSpec's `view`, or as a break/crop's `target`. break/crop mutate an
    existing view in place and use `target` instead of `name`.
    """

    kind: str = ""
    name: str = ""
    parent: Optional[str] = None
    target: Optional[str] = None

    # Sheet placement, in the pack's declared unit.
    x: float = 0
    y: float = 0

    # kind == "model"
    model_path: Optional[str] = None
    orientation: str = "*Front"

    # kind == "projected"
    direction: Optional[str] = None
    offset: Optional[float] = None

    # kind == "section"
    cut_points: List[List[float]] = field(default_factory=list)
    label: Optional[str] = None
    flip_direction: bool = False
    section_type: str = "full"
    auto_hatch: bool = True
    display_only: bool = False
    use_sheet_scale: bool = True

    # kind == "detail"
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    radius: Optional[float] = None
    scale_num: Optional[float] = None
    scale_denom: Optional[float] = None
    style: str = "circle"
    full_outline: bool = False

    # kind == "broken_out"
    profile_points: List[List[float]] = field(default_factory=list)
    depth: Optional[float] = None
    depth_reference: Optional[Dict[str, Any]] = None

    # kind == "break"
    position1: Optional[float] = None
    position2: Optional[float] = None
    break_orientation: str = "vertical"
    gap: Optional[float] = None
    break_style: str = "zigzag"


@dataclass
class AnnotationSpec(_DataclassJSON):
    """One annotation, attached to a view. `kind` discriminates which of the
    fields below apply -- see `ANNOTATION_KINDS` and
    `_ANNOTATION_REQUIRED_BY_KIND`."""

    kind: str = ""
    view: Optional[str] = None
    x: float = 0
    y: float = 0

    # entity attaches the annotation to something in `view` (edge/face/
    # vertex/component -- same {"kind", "x", "y", "z"} shape the COM tools
    # use). Not needed for kind == "note".
    entity: Optional[Dict[str, Any]] = None

    # kind == "note"
    text: Optional[str] = None

    # kind == "gtol"
    symbol: Optional[str] = None
    tolerance: Optional[float] = None
    datums: List[Any] = field(default_factory=list)
    material_condition: Optional[str] = None

    # kind == "datum_feature" / "datum_target"
    label: Optional[str] = None

    # kind == "datum_target"
    area_type: Optional[str] = None
    size: Optional[float] = None

    # kind == "surface_finish"
    symbol_type: Optional[str] = None

    # kind == "balloon"
    style: str = "circular"
    text_content: str = "item_number"


@dataclass
class TableSpec(_DataclassJSON):
    """One table (BOM, hole, revision, weldment cut list). `kind`
    discriminates which of the fields below apply -- see `TABLE_KINDS` and
    `_TABLE_REQUIRED_BY_KIND`."""

    kind: str = ""
    view: Optional[str] = None
    name: Optional[str] = None
    x: float = 0
    y: float = 0

    # kind == "bom"
    bom_type: str = "top_level"
    configuration: Optional[str] = None
    template_path: Optional[str] = None


@dataclass
class SheetSpec(_DataclassJSON):
    name: str = ""
    model_path: str = ""
    paper_size: str = "A3"
    scale: ScaleSpec = field(default_factory=ScaleSpec)
    views: List[ViewSpec] = field(default_factory=list)
    annotations: List[AnnotationSpec] = field(default_factory=list)
    tables: List[TableSpec] = field(default_factory=list)
    properties: Dict[str, str] = field(default_factory=dict)


@dataclass
class PackSpec(_DataclassJSON):
    drawing_template: str = ""
    output: str = ""
    sheets: List[SheetSpec] = field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str) -> "PackSpec":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # -----------------------------------------------------------------
    # Validation -- no COM calls, purely structural/referential checks.
    # -----------------------------------------------------------------

    def validate(self) -> List[str]:
        errors: List[str] = []

        if _is_missing(self.drawing_template):
            errors.append("PackSpec: missing required field 'drawing_template'")
        if _is_missing(self.output):
            errors.append("PackSpec: missing required field 'output'")

        seen_sheet_names = set()
        for si, sheet in enumerate(self.sheets):
            loc = f"sheets[{si}]"
            if _is_missing(sheet.name):
                errors.append(f"{loc}: missing required field 'name'")
            elif sheet.name in seen_sheet_names:
                errors.append(f"{loc}: duplicate sheet name '{sheet.name}'")
            else:
                seen_sheet_names.add(sheet.name)
            if _is_missing(sheet.model_path):
                errors.append(f"{loc} ('{sheet.name}'): missing required field 'model_path'")

            errors.extend(_validate_sheet(sheet, loc))

        return errors


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_missing(value) -> bool:
    return value is None or value == "" or value == []


def _datum_letter(ref) -> Optional[str]:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        return ref.get("letter")
    return None


def _validate_sheet(sheet: SheetSpec, loc: str) -> List[str]:
    errors: List[str] = []
    defined_views: set = set()
    defined_datums: set = set()
    has_bom = any(t.kind == "bom" for t in sheet.tables)

    for vi, view in enumerate(sheet.views):
        vloc = f"{loc}.views[{vi}]"

        if view.kind not in VIEW_KINDS:
            errors.append(f"{vloc}: unknown view kind '{view.kind}'")
            continue

        for field_name in _VIEW_REQUIRED_BY_KIND[view.kind]:
            if _is_missing(getattr(view, field_name)):
                errors.append(f"{vloc} (kind='{view.kind}'): missing required field '{field_name}'")

        if view.kind == "broken_out" and view.depth is not None and view.depth_reference is not None:
            errors.append(f"{vloc}: broken_out view must give exactly one of 'depth'/'depth_reference', not both")

        if view.kind in VIEW_KINDS_WITH_TARGET:
            if view.target and view.target not in defined_views:
                errors.append(f"{vloc}: target view '{view.target}' is not defined earlier in this sheet")
            continue

        if view.kind in VIEW_KINDS_WITH_PARENT:
            if view.parent and view.parent not in defined_views:
                errors.append(
                    f"{vloc} (kind='{view.kind}'): parent view '{view.parent}' is not defined earlier in this sheet"
                )

        if view.kind in VIEW_KINDS_CREATING and view.name:
            if view.name in defined_views:
                errors.append(f"{vloc}: duplicate view name '{view.name}'")
            else:
                defined_views.add(view.name)

    for ai, ann in enumerate(sheet.annotations):
        aloc = f"{loc}.annotations[{ai}]"

        if ann.kind not in ANNOTATION_KINDS:
            errors.append(f"{aloc}: unknown annotation kind '{ann.kind}'")
            continue

        for field_name in _ANNOTATION_REQUIRED_BY_KIND[ann.kind]:
            if _is_missing(getattr(ann, field_name)):
                errors.append(f"{aloc} (kind='{ann.kind}'): missing required field '{field_name}'")

        if ann.view and ann.view not in defined_views:
            errors.append(f"{aloc}: targets undefined view '{ann.view}'")

        if ann.kind == "datum_feature" and ann.label:
            defined_datums.add(ann.label)

        if ann.kind == "gtol":
            for datum_ref in ann.datums:
                letter = _datum_letter(datum_ref)
                if letter and letter not in defined_datums:
                    errors.append(f"{aloc}: GTOL references undefined datum '{letter}'")

        if ann.kind == "balloon" and not has_bom:
            errors.append(f"{aloc}: balloon has no BOM table defined on sheet '{sheet.name}'")

    for ti, table in enumerate(sheet.tables):
        tloc = f"{loc}.tables[{ti}]"

        if table.kind not in TABLE_KINDS:
            errors.append(f"{tloc}: unknown table kind '{table.kind}'")
            continue

        for field_name in _TABLE_REQUIRED_BY_KIND[table.kind]:
            if _is_missing(getattr(table, field_name)):
                errors.append(f"{tloc} (kind='{table.kind}'): missing required field '{field_name}'")

        if table.view and table.view not in defined_views:
            errors.append(f"{tloc}: targets undefined view '{table.view}'")

    return errors


# ---------------------------------------------------------------------------
# JSON Schema generation -- derived from the dataclasses above, not
# hand-written. Keeps solidworks_mcp/pack/schema.json (and hence the MCP
# tool schema / docs built from it) in sync with the code by construction.
# ---------------------------------------------------------------------------

_PRIMITIVE_JSON_TYPES = {str: "string", float: "number", int: "number", bool: "boolean"}


def _json_schema_for_type(tp, defs: Dict[str, Any]) -> Dict[str, Any]:
    inner = _is_optional(tp)
    if inner is not None:
        return _json_schema_for_type(inner, defs)

    if tp is Any:
        return {}
    if tp is dict:
        return {"type": "object"}
    if tp is list:
        return {"type": "array"}

    origin = get_origin(tp)
    if origin in (list, List):
        (item_t,) = get_args(tp)
        return {"type": "array", "items": _json_schema_for_type(item_t, defs)}
    if origin in (dict, Dict):
        _, val_t = get_args(tp)
        return {"type": "object", "additionalProperties": _json_schema_for_type(val_t, defs)}
    if origin is Union:
        return {"anyOf": [_json_schema_for_type(a, defs) for a in get_args(tp)]}

    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        _ensure_def(tp, defs)
        return {"$ref": f"#/$defs/{tp.__name__}"}

    return {"type": _PRIMITIVE_JSON_TYPES.get(tp, "string")}


def _dataclass_json_schema(cls, defs: Dict[str, Any]) -> Dict[str, Any]:
    hints = _hints(cls)
    properties = {}
    required = []
    for f in dataclasses.fields(cls):
        properties[f.name] = _json_schema_for_type(hints[f.name], defs)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            required.append(f.name)
    schema: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _ensure_def(cls, defs: Dict[str, Any]) -> None:
    if cls.__name__ in defs:
        return
    defs[cls.__name__] = {}  # placeholder breaks cycles; none expected here
    defs[cls.__name__] = _dataclass_json_schema(cls, defs)


def generate_schema() -> Dict[str, Any]:
    """Build a JSON Schema (draft-07) for `PackSpec` by introspecting the
    dataclasses above. Regenerate `schema.json` with
    `scripts/generate_pack_schema.py` after changing any pack dataclass."""

    # `_ensure_def` recurses through PackSpec's own field types, so every
    # nested dataclass (SheetSpec -> ScaleSpec/ViewSpec/AnnotationSpec/
    # TableSpec) lands in `$defs` without being listed here.
    defs: Dict[str, Any] = {}
    top = _dataclass_json_schema(PackSpec, defs)

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://solidworks-mcp/pack/schema.json",
        "title": "PackSpec",
        **top,
        "$defs": defs,
    }
