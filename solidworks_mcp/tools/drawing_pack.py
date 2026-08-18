"""
Drawing Pack Composite Tool
-----------------------------
create_drawing_pack -- validates a declarative `PackSpec` (see
`solidworks_mcp/pack/spec.py`), lowers it to an ordered step list via
`solidworks_mcp.pack.compiler.compile`, then executes those steps through
this same tool registry (`dispatch()`) rather than reaching into
`DrawingOperations` directly -- the whole point of a *composite* tool here
is running the already-registered primitives (`add_sheet`,
`insert_model_view`, `add_note`, ...) in the right order and rebuild
phasing, not reimplementing them.

Per docs/api and the pack epic (sw-wds): rebuild timing is a correctness
requirement, not a nicety -- dimension values, BOM quantities, and balloon
numbers stay stale until a rebuild, so `compile()` places a rebuild both
between the view phase and the annotation phase, and again between the
table phase and the table-update/balloon phase (see `pack/compiler.py`).
"""

from typing import Any, Dict, List

from ..constants import SwErrors
from ..pack import PackSpec, Ref
from ..pack import compile as pack_compile
from ..pack.spec import generate_schema
from ._automation import sw_automation
from .registry import UnknownToolError, dispatch, tool

# The `spec` property's schema is generated from the same dataclasses
# `PackSpec.validate()`/`compile()` use (`pack.spec.generate_schema()`),
# rather than hand-duplicated here, so the tool's advertised schema can't
# drift from what `PackSpec.from_dict` actually accepts. JSON Schema `$ref`s
# are resolved against the *document root*, so `$defs` has to be hoisted to
# this tool's own top-level schema -- nesting `generate_schema()`'s output
# unchanged under `properties.spec` would leave every `#/$defs/...` ref
# inside it pointing at the wrong root.
_PACK_JSON_SCHEMA = generate_schema()
_PACK_SPEC_DEFS = _PACK_JSON_SCHEMA.get("$defs", {})
_PACK_SPEC_PROPERTY_SCHEMA = {
    key: _PACK_JSON_SCHEMA[key]
    for key in ("type", "properties", "required", "additionalProperties")
    if key in _PACK_JSON_SCHEMA
}

# Step categories tallied into the pack summary; "rebuild"/"other" are
# intentionally absent -- rebuilds aren't a pack deliverable, and
# set_custom_properties isn't counted against any of these either.
_SUMMARY_COUNTERS = {
    "sheet": "sheets_created",
    "view": "views_inserted",
    "annotation": "annotations_added",
    "balloon": "balloons_added",
    "table": "tables_added",
    "export": "files_exported",
}


def _resolve_refs(value: Any, bound: Dict[str, str], missing: List[str]) -> Any:
    """Walk a step's argument value, substituting each `Ref` for its
    execution-time-bound name. Any `Ref` not yet in `bound` (its creating
    step never ran, or failed) is recorded in `missing` and left as `None`
    -- the caller checks `missing` before dispatching so an unresolved
    reference never reaches a real tool call."""
    if isinstance(value, Ref):
        if value.key in bound:
            return bound[value.key]
        missing.append(value.key)
        return None
    if isinstance(value, list):
        return [_resolve_refs(item, bound, missing) for item in value]
    if isinstance(value, dict):
        return {k: _resolve_refs(v, bound, missing) for k, v in value.items()}
    return value


def _execute_steps(steps, on_error: str) -> Dict:
    bound: Dict[str, str] = {}
    step_log: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {name: 0 for name in _SUMMARY_COUNTERS.values()}
    summary["failures"] = []

    aborted = False
    for step in steps:
        if aborted:
            step_log.append({
                "tool": step.tool, "label": step.label, "success": None,
                "skipped": True,
                "message": "Skipped -- an earlier step aborted the pack (on_error='abort')",
            })
            continue

        missing: List[str] = []
        args = {key: _resolve_refs(value, bound, missing) for key, value in step.args.items()}

        if missing:
            result = {
                "success": False,
                "message": (
                    f"Skipped -- dependency {sorted(set(missing))!r} was never created "
                    "(an earlier step it depends on did not succeed)"
                ),
                "error_code": int(SwErrors.swFeatureError),
                "error_name": SwErrors.swFeatureError.name,
            }
        elif step.tool == "rename_sheet" and args.get("old_name") == args.get("new_name"):
            # `rename_sheet` itself refuses `old_name == new_name` as a name
            # collision (it can't tell "already correctly named" apart from
            # "colliding with a different sheet") -- the compiler emits this
            # step unconditionally for every pack's first sheet (see
            # compiler.py), so this is the expected, common case whenever the
            # template's default sheet name already matches the spec.
            result = {
                "success": True,
                "message": f"Sheet already named {args.get('new_name')!r}; no rename needed",
                "data": {"name": args.get("old_name"), "new_name": args.get("new_name")},
            }
        else:
            try:
                result = dispatch(step.tool, args)
            except UnknownToolError as e:
                result = {
                    "success": False,
                    "message": f"Unknown tool {step.tool!r}: {e}",
                    "error_code": int(SwErrors.swUnknownError),
                    "error_name": SwErrors.swUnknownError.name,
                }

        success = bool(result.get("success"))
        step_log.append({
            "tool": step.tool, "label": step.label, "success": success,
            "skipped": False,
            "message": result.get("message", ""),
            "data": result.get("data"),
        })

        if success:
            counter = _SUMMARY_COUNTERS.get(step.category)
            if counter:
                summary[counter] += 1
            if step.binds and step.bind_field:
                actual = (result.get("data") or {}).get(step.bind_field)
                if actual:
                    bound[step.binds] = actual
        else:
            summary["failures"].append({
                "tool": step.tool, "label": step.label, "message": result.get("message", ""),
            })
            if on_error == "abort":
                aborted = True

    overall_success = not summary["failures"]
    message = (
        f"Pack completed: {len(step_log)} step(s), no failures" if overall_success else
        f"Pack completed with {len(summary['failures'])} failure(s) out of {len(step_log)} step(s)"
    )
    return sw_automation._result(
        overall_success, message,
        SwErrors.swSuccess if overall_success else SwErrors.swFeatureError,
        {"steps": step_log, "summary": summary},
    )


@tool(
    name="create_drawing_pack",
    description=(
        "Build a whole drawing (sheets, views, annotations, tables, "
        "balloons, custom properties, export) from one declarative "
        "PackSpec, instead of an LLM orchestrating 15-20 raw tool calls "
        "per part. Validates the spec (solidworks_mcp/pack/spec.py's "
        "PackSpec.validate() -- structural/referential checks only, no "
        "COM), compiles it to an ordered step list "
        "(solidworks_mcp.pack.compiler.compile), then runs each step "
        "through this same tool registry. Enforces per-sheet phase order: "
        "create sheet -> set sheet properties -> insert views (parents "
        "before children) -> auto-arrange -> REBUILD -> annotations -> "
        "insert tables -> REBUILD -> update tables -> balloons -> set "
        "custom properties; export (save_drawing to PackSpec.output) runs "
        "once at the end. The two rebuilds matter: dimension values, BOM "
        "quantities, and balloon numbers are stale until a rebuild runs. "
        "on_error='abort' (default) stops at the first failed step; "
        "'continue' runs every remaining step and reports every failure. "
        "Either way, the full per-step log is returned so a partial pack "
        "is diagnosable. dry_run=True compiles and returns the step list "
        "(data.steps) without executing anything. Two known limitations, "
        "both from what PackSpec (solidworks_mcp/pack/spec.py) can "
        "express: the first sheet's declared name is applied via a rename "
        "right after creation, since the template's own first sheet is "
        "rarely already named that -- this is automatic and needs no "
        "action from the caller. A 'hole' table has no spec field for its "
        "required datum origin, so one is always inserted anchored at the "
        "view origin (0, 0); a real per-hole-table datum still requires "
        "editing the table afterward. Note that the auto-arrange step "
        "repositions every view and so overwrites the x/y each view "
        "declares; set a sheet's auto_arrange to false to keep the "
        "declared placement (and to keep sheet-space annotation "
        "coordinates aligned with the views they point at)."
    ),
    schema={
        "type": "object",
        "properties": {
            "spec": {
                **_PACK_SPEC_PROPERTY_SCHEMA,
                "description": "A PackSpec -- see solidworks_mcp/pack/spec.py / docs/packs/*.json for examples.",
            },
            "on_error": {
                "type": "string", "default": "abort", "enum": ["abort", "continue"],
                "description": (
                    "'abort' (default): stop at the first failed step. "
                    "'continue': run every remaining step regardless."
                ),
            },
            "dry_run": {
                "type": "boolean", "default": False,
                "description": "True: compile and return the step list (data.steps) without executing anything.",
            },
        },
        "required": ["spec"],
        "$defs": _PACK_SPEC_DEFS,
    },
)
def create_drawing_pack(arguments: dict) -> Dict:
    spec_data = arguments.get("spec")
    on_error = arguments.get("on_error", "abort")
    dry_run = arguments.get("dry_run", False)

    if not isinstance(spec_data, dict):
        return sw_automation._result(
            False, "'spec' is required and must be an object", SwErrors.swInvalidInput,
        )

    if on_error not in ("abort", "continue"):
        return sw_automation._result(
            False, f"Unknown on_error {on_error!r}; expected 'abort' or 'continue'",
            SwErrors.swInvalidInput, {"on_error": on_error},
        )

    try:
        spec = PackSpec.from_dict(spec_data)
    except Exception as e:
        return sw_automation._result(
            False, f"Could not parse pack spec: {e}", SwErrors.swInvalidInput,
        )

    errors = spec.validate()
    if errors:
        return sw_automation._result(
            False, f"Pack spec failed validation ({len(errors)} error(s))",
            SwErrors.swInvalidInput, {"validation_errors": errors},
        )

    steps = pack_compile(spec)

    if dry_run:
        return sw_automation._result(
            True, f"Compiled {len(steps)} step(s) (dry_run -- nothing executed)",
            SwErrors.swSuccess, {"dry_run": True, "steps": [s.to_dict() for s in steps]},
        )

    return _execute_steps(steps, on_error)
