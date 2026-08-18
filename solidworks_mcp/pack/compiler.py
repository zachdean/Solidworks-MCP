"""
Pack compiler -- lowers a validated `PackSpec` into an ordered list of `Step`s
naming a registered MCP tool and its arguments. Pure Python: no COM, no
`sw_automation`, no `dispatch()` -- `compile()` never imports
`solidworks_mcp.tools`, so it is importable and fully testable without a
`com_backend` in play at all. The `create_drawing_pack` tool
(`solidworks_mcp/tools/drawing_pack.py`) is what actually runs a compiled
step list against the tool registry.

Ref resolution
==============
`compile()` cannot know, ahead of time, what name SolidWorks will actually
assign a newly created sheet or view -- `new_drawing_from_template`'s first
sheet and every `insert_*_view` call hand back their *own* name
(`IView::GetName2`/`GetSheetNames()[0]`), which is not guaranteed to match
the pack spec's `name`/`sheet.name`. So a step that needs to address a
sheet/view created by an earlier step doesn't get a literal string -- it
gets a `Ref`, a placeholder keyed by the spec-level name. `create_drawing_pack`
resolves each `Ref` at execution time, once the step that creates it has
actually run and reported the real name back.

Every sheet's own name is *also* addressed via `Ref`, even though
`add_sheet` (sheets after the first) honors the requested name exactly --
this keeps the executor's resolution logic uniform (one mechanism, not one
for "the first sheet" and a separate literal-string path for the rest).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .spec import (
    AnnotationSpec,
    PackSpec,
    SheetSpec,
    TableSpec,
    ViewSpec,
    VIEW_KINDS_CREATING,
    VIEW_KINDS_WITH_PARENT,
    VIEW_KINDS_WITH_TARGET,
)

__all__ = ["Ref", "Step", "compile"]


@dataclass(frozen=True)
class Ref:
    """A placeholder for a sheet/view name not known until execution time --
    see the module docstring. `key` is an opaque string minted by the
    compiler (`_sheet_key`/`_view_key`); callers never construct one
    directly."""

    key: str

    def to_dict(self) -> Dict[str, str]:
        return {"$ref": self.key}


@dataclass
class Step:
    """One compiled tool call. `args` values are plain JSON-safe data,
    except any `Ref` placeholders needing execution-time resolution.

    `binds`/`bind_field`, when set, tell the executor: after this step
    succeeds, read `result["data"][bind_field]` and record it as the actual
    name for `binds` -- so a later step's `Ref(binds)` resolves to it.
    `category` groups steps for the pack summary (sheets/views/annotations/
    tables/balloons/other); rebuild/export steps use "rebuild"/"export" so
    they're excluded from those counts.
    """

    tool: str
    args: Dict[str, Any]
    binds: Optional[str] = None
    bind_field: Optional[str] = None
    category: str = "other"
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "args": {k: _serialize_arg(v) for k, v in self.args.items()},
            "binds": self.binds,
            "bind_field": self.bind_field,
            "category": self.category,
            "label": self.label,
        }


def _serialize_arg(value: Any) -> Any:
    if isinstance(value, Ref):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize_arg(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_arg(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Key helpers -- namespaced so a view name reused across sheets, or a view
# name that happens to collide with a sheet name, can't cross-bind.
# ---------------------------------------------------------------------------


def _sheet_key(sheet_name: str) -> str:
    return f"sheet::{sheet_name}"


def _view_key(sheet_name: str, view_name: str) -> str:
    return f"view::{sheet_name}::{view_name}"


# ---------------------------------------------------------------------------
# View ordering -- parents (and break/crop targets) before the views that
# reference them, regardless of the order the spec lists them in. A stable
# "wave" topological sort: every view whose dependency is already placed (or
# has none) is placed in original relative order, repeated until nothing
# changes.
# ---------------------------------------------------------------------------


def _view_dependency(view: ViewSpec) -> Optional[str]:
    if view.kind in VIEW_KINDS_WITH_PARENT:
        return view.parent
    if view.kind in VIEW_KINDS_WITH_TARGET:
        return view.target
    return None


def _order_views(views: List[ViewSpec]) -> List[ViewSpec]:
    ordered: List[ViewSpec] = []
    placed: set = set()
    remaining = list(views)

    progressed = True
    while remaining and progressed:
        progressed = False
        still_remaining = []
        for view in remaining:
            dep = _view_dependency(view)
            if dep is None or dep in placed:
                ordered.append(view)
                if view.kind in VIEW_KINDS_CREATING and view.name:
                    placed.add(view.name)
                progressed = True
            else:
                still_remaining.append(view)
        remaining = still_remaining

    # A dependency that's never satisfied (a spec that skipped validate())
    # falls through here rather than being dropped -- compiled in original
    # order so `compile()` never silently loses a view.
    ordered.extend(remaining)
    return ordered


# ---------------------------------------------------------------------------
# Per-view-kind compilation
# ---------------------------------------------------------------------------


def _compile_view(view: ViewSpec, sheet_name: str, sheet_model_path: str = "") -> Step:
    label = f"view:{view.name}" if view.name else f"view:{view.target}"

    if view.kind == "model":
        return Step(
            tool="insert_model_view",
            args={
                # `SheetSpec.model_path` is the sheet-wide default: it is a
                # required field, and setting it there (the obvious place)
                # while omitting it on the view used to discard it silently
                # and fail validation naming the *view* field instead.
                "model_path": view.model_path or sheet_model_path,
                "view_name": view.orientation,
                "x": view.x,
                "y": view.y,
                "sheet_name": Ref(_sheet_key(sheet_name)),
            },
            binds=_view_key(sheet_name, view.name or ""),
            bind_field="view_name",
            category="view",
            label=label,
        )

    if view.kind == "projected":
        return Step(
            tool="insert_projected_view",
            args={
                "parent_view_name": Ref(_view_key(sheet_name, view.parent or "")),
                "direction": view.direction,
                "offset": view.offset,
                "sheet_name": Ref(_sheet_key(sheet_name)),
            },
            binds=_view_key(sheet_name, view.name or ""),
            bind_field="view_name",
            category="view",
            label=label,
        )

    if view.kind == "section":
        return Step(
            tool="insert_section_view",
            args={
                "parent_view_name": Ref(_view_key(sheet_name, view.parent or "")),
                "cut_points": view.cut_points,
                "x": view.x,
                "y": view.y,
                "label": view.label,
                "flip_direction": view.flip_direction,
                "section_type": view.section_type,
                "auto_hatch": view.auto_hatch,
                "display_only": view.display_only,
                "use_sheet_scale": view.use_sheet_scale,
            },
            binds=_view_key(sheet_name, view.name or ""),
            bind_field="view_name",
            category="view",
            label=label,
        )

    if view.kind == "detail":
        return Step(
            tool="insert_detail_view",
            args={
                "parent_view_name": Ref(_view_key(sheet_name, view.parent or "")),
                "center_x": view.center_x,
                "center_y": view.center_y,
                "radius": view.radius,
                "x": view.x,
                "y": view.y,
                "label": view.label,
                "scale_num": view.scale_num,
                "scale_denom": view.scale_denom,
                "style": view.style,
                "full_outline": view.full_outline,
            },
            binds=_view_key(sheet_name, view.name or ""),
            bind_field="view_name",
            category="view",
            label=label,
        )

    if view.kind == "broken_out":
        # Mutates the parent view in place -- SolidWorks never assigns it a
        # separate view name (see `insert_broken_out_section`'s
        # `data["view_name"] = parent_view_name`). Binding the pack's `name`
        # to that same key means a later annotation/table addressing this
        # broken-out view by name resolves to the (already-resolved) parent.
        return Step(
            tool="insert_broken_out_section",
            args={
                "parent_view_name": Ref(_view_key(sheet_name, view.parent or "")),
                "profile_points": view.profile_points,
                "depth": view.depth,
                "depth_reference": view.depth_reference,
            },
            binds=_view_key(sheet_name, view.name or ""),
            bind_field="view_name",
            category="view",
            label=label,
        )

    if view.kind == "break":
        return Step(
            tool="insert_break_view",
            args={
                "view_name": Ref(_view_key(sheet_name, view.target or "")),
                "position1": view.position1,
                "position2": view.position2,
                "orientation": view.break_orientation,
                "gap": view.gap,
                "style": view.break_style,
            },
            # "other", not "view" -- this mutates an existing view rather
            # than inserting a new one, so it isn't a `views_inserted` event.
            category="other",
            label=label,
        )

    if view.kind == "crop":
        return Step(
            tool="add_crop_view",
            args={
                "view_name": Ref(_view_key(sheet_name, view.target or "")),
                "profile_points": view.profile_points,
            },
            category="other",  # mutates an existing view; see "break" above.
            label=label,
        )

    raise ValueError(f"compile(): unknown view kind {view.kind!r}")


# ---------------------------------------------------------------------------
# Per-annotation-kind compilation
# ---------------------------------------------------------------------------


def _compile_annotation(ann: AnnotationSpec, sheet_name: str) -> Step:
    view_ref = Ref(_view_key(sheet_name, ann.view)) if ann.view else None
    label = f"annotation:{ann.kind}"

    if ann.kind == "note":
        return Step(
            tool="add_note",
            args={"text": ann.text, "x": ann.x, "y": ann.y, "view_name": view_ref},
            category="annotation", label=label,
        )

    if ann.kind == "gtol":
        return Step(
            tool="add_gtol",
            args={
                "view_name": view_ref, "entity": ann.entity, "symbol": ann.symbol,
                "tolerance": ann.tolerance, "datums": ann.datums, "x": ann.x, "y": ann.y,
                "material_condition": ann.material_condition,
            },
            category="annotation", label=label,
        )

    if ann.kind == "datum_feature":
        return Step(
            tool="add_datum_feature",
            args={
                "view_name": view_ref, "entity": ann.entity, "label": ann.label,
                "x": ann.x, "y": ann.y,
            },
            category="annotation", label=label,
        )

    if ann.kind == "datum_target":
        return Step(
            tool="add_datum_target",
            args={
                "view_name": view_ref, "entity": ann.entity, "label": ann.label,
                "area_type": ann.area_type, "size": ann.size, "x": ann.x, "y": ann.y,
            },
            category="annotation", label=label,
        )

    if ann.kind == "surface_finish":
        return Step(
            tool="add_surface_finish",
            args={
                "view_name": view_ref, "entity": ann.entity, "x": ann.x, "y": ann.y,
                "symbol_type": ann.symbol_type,
            },
            category="annotation", label=label,
        )

    if ann.kind == "balloon":
        return Step(
            tool="add_balloon",
            args={
                "view_name": view_ref, "entity": ann.entity, "x": ann.x, "y": ann.y,
                "style": ann.style, "text_content": ann.text_content,
            },
            category="balloon", label="balloon",
        )

    raise ValueError(f"compile(): unknown annotation kind {ann.kind!r}")


# ---------------------------------------------------------------------------
# Per-table-kind compilation
# ---------------------------------------------------------------------------

# `insert_hole_table` requires a datum_entity the pack spec has no field
# for (docs/api/04-tables.md's hole-table record; `TableSpec` only carries
# `view`/`x`/`y`/bom-only fields for the "hole" kind per
# `_TABLE_REQUIRED_BY_KIND`). Anchoring at the view origin is the only
# spec-free default that's always valid -- a real per-hole-table datum
# still needs a follow-up `set_table_*`-style pack field if one is ever
# wanted.
_DEFAULT_HOLE_TABLE_DATUM = {"kind": "vertex", "x": 0, "y": 0}


def _compile_table(table: TableSpec, sheet_name: str) -> Step:
    view_ref = Ref(_view_key(sheet_name, table.view)) if table.view else None
    label = f"table:{table.kind}"

    if table.kind == "bom":
        return Step(
            tool="insert_bom_table",
            args={
                "view_name": view_ref, "x": table.x, "y": table.y,
                "bom_type": table.bom_type, "configuration": table.configuration,
                "template_path": table.template_path,
            },
            category="table", label=label,
        )

    if table.kind == "hole":
        return Step(
            tool="insert_hole_table",
            args={
                "view_name": view_ref, "datum_entity": dict(_DEFAULT_HOLE_TABLE_DATUM),
                "x": table.x, "y": table.y, "template_path": table.template_path,
            },
            category="table", label=label,
        )

    if table.kind == "revision":
        return Step(
            tool="insert_revision_table",
            args={"template_path": table.template_path},
            category="table", label=label,
        )

    if table.kind == "weldment_cutlist":
        return Step(
            tool="insert_weldment_cutlist",
            args={
                "view_name": view_ref, "x": table.x, "y": table.y,
                "template_path": table.template_path,
            },
            category="table", label=label,
        )

    raise ValueError(f"compile(): unknown table kind {table.kind!r}")


# ---------------------------------------------------------------------------
# Per-sheet compilation
# ---------------------------------------------------------------------------


def _compile_sheet(sheet: SheetSpec, index: int, drawing_template: str) -> List[Step]:
    sheet_key = _sheet_key(sheet.name)
    steps: List[Step] = []

    # 1. create sheet
    if index == 0:
        steps.append(Step(
            tool="new_drawing_from_template",
            args={
                "template_path": drawing_template,
                "paper_size": sheet.paper_size,
                "scale_num": sheet.scale.num,
                "scale_denom": sheet.scale.denom,
            },
            binds=sheet_key, bind_field="sheet_name",
            category="sheet", label=f"sheet:{sheet.name}",
        ))
        # `new_drawing_from_template` creates its own first sheet, named
        # whatever the .drwdot template says -- not necessarily `sheet.name`.
        # Rename it to the declared name so the pack's own sheet-name
        # namespace is actually honored for sheet 0, the same as `add_sheet`
        # already honors it exactly for every later sheet. `rename_sheet`
        # itself fails if `old_name == new_name` (a same-name collision) --
        # the executor treats that case as a no-op instead of dispatching it
        # (see `create_drawing_pack`'s `_execute_steps`), since a spec whose
        # first sheet happens to already be named what the template's
        # default sheet is named is a normal, not exceptional, case.
        steps.append(Step(
            tool="rename_sheet",
            args={"old_name": Ref(sheet_key), "new_name": sheet.name},
            binds=sheet_key, bind_field="new_name",
            category="other", label=f"rename_first_sheet:{sheet.name}",
        ))
    else:
        steps.append(Step(
            tool="add_sheet",
            args={
                "name": sheet.name, "paper_size": sheet.paper_size,
                "scale_num": sheet.scale.num, "scale_denom": sheet.scale.denom,
            },
            binds=sheet_key, bind_field="name",
            category="sheet", label=f"sheet:{sheet.name}",
        ))

    # 2. set sheet properties
    steps.append(Step(
        tool="set_sheet_properties",
        args={
            "sheet_name": Ref(sheet_key), "paper_size": sheet.paper_size,
            "scale_num": sheet.scale.num, "scale_denom": sheet.scale.denom,
        },
        # "other", not "sheet" -- the sheet itself was already counted by
        # its creation step above; this only configures it.
        category="other", label=f"sheet_properties:{sheet.name}",
    ))

    # 3. insert views (parents before children)
    for view in _order_views(sheet.views):
        steps.append(_compile_view(view, sheet.name, sheet.model_path))

    # 4. auto-arrange -- skipped when the sheet opts out, since this repacks
    # every root view into a grid via `IView::Position` and would otherwise
    # discard the `x`/`y` each ViewSpec declared (see `SheetSpec.auto_arrange`).
    if sheet.auto_arrange:
        steps.append(Step(
            tool="auto_arrange_views",
            args={"sheet_name": Ref(sheet_key)},
            category="other", label=f"auto_arrange:{sheet.name}",
        ))

    # 5. REBUILD -- dimension/BOM values are stale until this runs, and the
    # next phase (model items + annotations) reads them.
    steps.append(Step(
        tool="rebuild_document", args={"force": True},
        category="rebuild", label=f"rebuild:{sheet.name}:pre-annotate",
    ))

    # 6. insert annotations (balloons are their own later phase -- they
    # need this sheet's BOM table, inserted next, to already exist for a
    # meaningful item number).
    for ann in sheet.annotations:
        if ann.kind != "balloon":
            steps.append(_compile_annotation(ann, sheet.name))

    # 7. insert tables
    for table in sheet.tables:
        steps.append(_compile_table(table, sheet.name))

    # 8. REBUILD -- table contents (BOM quantities, balloon numbering) are
    # stale until this runs.
    steps.append(Step(
        tool="rebuild_document", args={"force": True},
        category="rebuild", label=f"rebuild:{sheet.name}:pre-table-update",
    ))

    # 9. update tables ("other", not "table" -- these tables were already
    # counted by their own insert_*_table step above; this only refreshes
    # them)
    steps.append(Step(
        tool="update_table", args={"all_tables": True},
        category="other", label=f"update_tables:{sheet.name}",
    ))

    # 10. balloons
    for ann in sheet.annotations:
        if ann.kind == "balloon":
            steps.append(_compile_annotation(ann, sheet.name))

    # 11. set custom properties (only if the sheet actually declares any --
    # an empty call would be a pointless COM round trip every sheet)
    if sheet.properties:
        steps.append(Step(
            tool="set_custom_properties",
            args={"properties": dict(sheet.properties)},
            category="other", label=f"custom_properties:{sheet.name}",
        ))

    return steps


def compile(spec: PackSpec) -> List[Step]:
    """Lower a `PackSpec` into an ordered list of `Step`s. Pure: makes no
    COM calls and never touches `sw_automation`/`dispatch()`. Does not
    itself call `spec.validate()` -- callers (e.g. `create_drawing_pack`)
    are expected to validate first; `compile()` trusts its input."""

    steps: List[Step] = []
    for index, sheet in enumerate(spec.sheets):
        steps.extend(_compile_sheet(sheet, index, spec.drawing_template))

    # 12. export -- once per pack, not per sheet: `PackSpec.output` is a
    # single `.slddrw` destination for the whole (possibly multi-sheet)
    # document, saved via `save_drawing`.
    steps.append(Step(
        tool="save_drawing",
        args={"filepath": spec.output},
        category="export", label="export",
    ))

    return steps
