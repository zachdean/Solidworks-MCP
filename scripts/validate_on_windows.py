#!/usr/bin/env python3
"""End-to-end validation runner for the Windows + SolidWorks machine (sw-17y.2).

The single command that turns "does this actually work against real
SolidWorks" into a triage list instead of an interactive debugging session:
connects to SolidWorks, generates the test geometry (`scripts/
make_test_geometry.py`), then invokes every tool registered in
`solidworks_mcp.tools.registry` at least once with sensible, context-derived
arguments -- recording a pass/fail/skip verdict, the arguments used, the
result message, and the elapsed time for each, regardless of whether earlier
tools failed.

Run on a Windows machine with SolidWorks installed and this project's venv
active:

    .venv\\Scripts\\python.exe scripts\\validate_on_windows.py [--out-dir DIR]
                                                                [--only PATTERN]
                                                                [--skip PATTERN]

Writes `validation_report.md` and `validation_report.json` under `--out-dir`
(default `tests/fixtures/generated/`, gitignored) and exits nonzero if any
tool failed.

Design notes
============
Every registered tool gets exactly one report entry, in registry
(registration/import) order -- new tools picked up automatically via
`registry.describe_tools()`, never a hardcoded list (sw-17y.2 acceptance
criteria). A tool's entry is one of:

  - "pass" / "fail": the tool was actually dispatched; a raised exception
    (including a real COM error) is caught, recorded (message, traceback,
    and the COM HRESULT if one can be found on the exception), and the run
    continues -- one broken tool never hides the other forty.
  - "skipped": the tool is in `EXCLUSIONS` below, with a stated reason, and
    was never dispatched (execute_python -- arbitrary code execution has no
    generically safe args to synthesize).
  - "filtered": excluded by `--only`/`--skip`, never dispatched.

`--only`/`--skip` narrow *which tools are dispatched*, not which tools get a
report entry -- the JSON report always has one entry per registered tool, so
a `--only` re-run of just the previous failures still satisfies "the JSON
report has one entry per registered tool."

`ScriptContext` tracks what's currently open/selected in SolidWorks (the
active drawing's path, its main part/assembly views, a BOM/hole/revision
table, a layer, a note, a dimension, ...) and lazily re-establishes it
before a tool that needs it, since the registry sweep runs in registration
order -- which happens to build up sensibly (documents -> drawing sheets ->
views -> annotations -> tables -> layers -> line format -> pack -> sketch/
feature primitives -> utility) but also contains `close_document`/
`delete_view`/`delete_sheet`/`delete_table`/`remove_*` tools that legitimately
destroy the very state later tools need. Re-establishing context uses
`dispatch()` calls that are *not* separately recorded (they exercise tools
that get their own real entry elsewhere in the sweep already); this mirrors
`solidworks_mcp/tests/integration/conftest.py`'s own setup/teardown fixtures.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import logging
import subprocess
import sys
import time
import traceback
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# Guarded: `solidworks_mcp/tests/test_validation_runner.py` execs this module
# by path, and an unguarded insert would leave a duplicate repo root on
# `sys.path` for the rest of the pytest session.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The bracket fixture's geometry contract -- the dimensions
# scripts/make_test_geometry.py builds from and the sheet-space mapping
# solidworks_mcp/tests/integration/ picks against. Constants and pure
# functions only, no COM.
from solidworks_mcp.testing.bracket_geometry import (  # noqa: E402
    ASSEMBLY_VIEW_X,
    ASSEMBLY_VIEW_Y,
    BOTTOM_EDGE_MIDPOINT,
    CORNER_BOTTOM_RIGHT,
    CORNER_TOP_LEFT,
    FACE_CENTER,
    HALF_DEPTH_MM,
    HALF_WIDTH_MM,
    HOLE_INSET_MM,
    PART_VIEW_X,
    PART_VIEW_Y,
    entity,
)
from solidworks_mcp.testing.pack_examples import load_example_pack  # noqa: E402

# Safe to import unconditionally on any platform: `solidworks_mcp.tools`
# registers every tool as an import-time side effect (schema + handler
# closures only) and instantiates the shared `SolidWorksAutomation` without
# touching COM -- the whole existing fake-COM test suite already relies on
# this. Only `main()`'s actual `dispatch()` calls (gated behind the
# `sys.platform` check below) reach real SolidWorks.
from solidworks_mcp.tools import registry as tool_registry  # noqa: E402
from solidworks_mcp.tools import sw_automation  # noqa: E402

logger = logging.getLogger("validate_on_windows")

DEFAULT_GEOMETRY_DIR = REPO_ROOT / "tests" / "fixtures" / "generated"
DEFAULT_OUTPUT_DIR = DEFAULT_GEOMETRY_DIR
BRACKET_PART_NAME = "bracket.sldprt"
BRACKET_ASSEMBLY_NAME = "bracket_assembly.sldasm"

# Throwaway-part block conventions used by the sketches/features section
# (see `_pre_create_sketch` and friends) -- deliberately the *tools' own*
# schema defaults (draw_rectangle's -50/-25/50/25, extrude_sketch's depth=10)
# rather than new constants, so those tools are exercised with zero-argument
# calls exactly as a caller relying on defaults would use them.
_BLOCK_HALF_WIDTH_MM = 50.0
_BLOCK_HALF_DEPTH_MM = 25.0
_BLOCK_HEIGHT_MM = 10.0


# ============================================================================
# Report data model
# ============================================================================

@dataclass
class ToolRecord:
    name: str
    status: str  # "pass" | "fail" | "skipped" | "filtered"
    arguments: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    com_hresult: Optional[int] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "elapsed_seconds": round(self.elapsed_seconds, 4)}


def _extract_hresult(exc: BaseException) -> Optional[int]:
    """Best-effort HRESULT extraction that never assumes `pywintypes` is
    importable -- this module must import cleanly on macOS for the unit
    tests, so exceptions are duck-typed rather than caught by type. A real
    `pywintypes.com_error`'s `.args` is `(hresult, strerror, excepinfo,
    argerr)`; a plain Python exception has neither shape and both lookups
    just fall through to `None`."""
    hresult = getattr(exc, "hresult", None)
    if isinstance(hresult, int):
        return hresult
    args = getattr(exc, "args", None)
    if isinstance(args, tuple) and args and isinstance(args[0], int):
        return args[0]
    return None


def _describe_exception(exc: BaseException) -> str:
    """The most useful human-readable description of `exc` -- a
    `com_error`'s real message usually lives in `excepinfo[2]`
    (`args[2][2]`), not `str(exc)`/`strerror`, which is often a generic
    'exception occurred' stub."""
    args = getattr(exc, "args", None)
    if isinstance(args, tuple) and len(args) >= 3:
        excepinfo = args[2]
        if isinstance(excepinfo, (tuple, list)) and len(excepinfo) >= 3 and excepinfo[2]:
            return str(excepinfo[2])
    return str(exc)


# ============================================================================
# Exclusions -- tools never dispatched, with a stated reason each. Every
# other registered tool is attempted (best-effort args); "will it work" is
# exactly what this script exists to find out, so a tool that merely *might*
# fail against this fixture (e.g. insert_weldment_cutlist against a
# non-weldment part) belongs in the report as a real failure, not silently
# excluded.
# ============================================================================

EXCLUSIONS: Dict[str, str] = {
    "execute_python": (
        "Runs arbitrary caller-supplied Python against the live SolidWorks "
        "session (solidworks_mcp/tools/utility.py) -- there is no "
        "generically safe code to synthesize for an unattended sweep, and "
        "a wrong guess here has unbounded blast radius unlike every other "
        "tool's COM call."
    ),
}


# ============================================================================
# ScriptContext -- tracks what's currently open/selected in SolidWorks and
# lazily (re-)establishes it. `_try` calls are setup plumbing, not part of
# the report: each of those tool names gets its own real, recorded
# invocation elsewhere in the sweep.
# ============================================================================

# Names that only mean something inside one drawing document -- cleared
# together whenever a fresh drawing is built (see
# `ScriptContext._reset_drawing_scoped_state`).
_DRAWING_SCOPED_ATTRS = (
    "view_name",
    "extra_view_name",
    "assembly_view_name",
    "bom_table_name",
    "hole_table_name",
    "revision_table_name",
    "layer_name",
    "note_name",
    "dimension_name",
    "datum_label",
    "extra_sheet_name",
)


class ScriptContext:
    def __init__(self, dispatch_fn: Callable[[str, dict], Dict[str, Any]],
                 part_path: Path, assembly_path: Path, output_dir: Path):
        self.dispatch = dispatch_fn
        self.part_path = part_path
        self.assembly_path = assembly_path
        self.output_dir = output_dir

        self.drawing_path: Optional[str] = None
        self.sheet_name: Optional[str] = None
        self._reset_drawing_scoped_state()
        self.part_doc_active = False
        self.block_extruded = False
        self.automation = sw_automation
        self.warnings: List[str] = []

    def _reset_drawing_scoped_state(self) -> None:
        """Clear every name that only means something inside one drawing
        document. Called at startup and again whenever `ensure_drawing`
        has to build a fresh drawing, so there is one list of these
        attributes rather than an initialiser and a reset block that have
        to be kept in step."""
        for attr in _DRAWING_SCOPED_ATTRS:
            setattr(self, attr, None)

    def _try(self, name: str, args: dict) -> Dict[str, Any]:
        try:
            result = self.dispatch(name, args)
        except Exception as exc:  # noqa: BLE001 -- setup plumbing must never abort the sweep
            self.warnings.append(f"setup call {name}({args!r}) raised: {exc}")
            return {"success": False, "message": str(exc), "data": {}}
        if not result.get("success"):
            self.warnings.append(f"setup call {name}({args!r}) failed: {result.get('message')}")
        return result

    def _active_doc_type(self) -> str:
        result = self._try("get_document_type", {})
        return str((result.get("data") or {}).get("type") or "").lower()

    def _names(self, list_tool: str, args: dict, collection_key: str) -> set:
        result = self._try(list_tool, args)
        items = (result.get("data") or {}).get(collection_key, [])
        return {item.get("name") for item in items}

    # -- Drawing-level context -------------------------------------------

    def ensure_drawing(self) -> None:
        self.part_doc_active = False
        if self.drawing_path is not None:
            if self._active_doc_type() == "drawing":
                return
            self._try("open_or_activate_document", {"filepath": self.drawing_path})
            if self._active_doc_type() == "drawing":
                return
            # The saved drawing couldn't be reactivated -- fall through and
            # build a fresh one rather than leaving every later tool broken.

        result = self._try("new_drawing_from_template", {})
        if not result.get("success"):
            return
        self._reset_drawing_scoped_state()
        self.sheet_name = (result.get("data") or {}).get("sheet_name")

        save_path = str(self.output_dir / "_validation_drawing.slddrw")
        save_result = self._try("save_drawing", {"filepath": save_path})
        if save_result.get("success"):
            self.drawing_path = save_path

    def ensure_part_view(self) -> None:
        self.ensure_drawing()
        if self.view_name and self.view_name in self._names("list_views", {"sheet_name": self.sheet_name}, "views"):
            return
        self.view_name = None
        result = self._try("insert_model_view", {
            "model_path": str(self.part_path), "view_name": "*Front",
            "x": PART_VIEW_X, "y": PART_VIEW_Y, "sheet_name": self.sheet_name,
        })
        if result.get("success"):
            self.view_name = (result.get("data") or {}).get("view_name")

    def ensure_assembly_view(self) -> None:
        self.ensure_drawing()
        if self.assembly_view_name and self.assembly_view_name in self._names(
                "list_views", {"sheet_name": self.sheet_name}, "views"):
            return
        self.assembly_view_name = None
        result = self._try("insert_model_view", {
            "model_path": str(self.assembly_path), "view_name": "*Isometric",
            "x": ASSEMBLY_VIEW_X, "y": ASSEMBLY_VIEW_Y, "sheet_name": self.sheet_name,
        })
        if result.get("success"):
            self.assembly_view_name = (result.get("data") or {}).get("view_name")

    def ensure_bom_table(self) -> None:
        self.ensure_assembly_view()
        if not self.assembly_view_name:
            return
        if self.bom_table_name and self.bom_table_name in self._names(
                "list_tables", {"sheet_name": self.sheet_name}, "tables"):
            return
        self.bom_table_name = None
        result = self._try("insert_bom_table", {
            "view_name": self.assembly_view_name, "x": 250, "y": 60, "bom_type": "top_level",
        })
        if result.get("success"):
            self.bom_table_name = (result.get("data") or {}).get("name")

    def ensure_hole_table(self) -> None:
        self.ensure_part_view()
        if not self.view_name:
            return
        if self.hole_table_name and self.hole_table_name in self._names(
                "list_tables", {"sheet_name": self.sheet_name}, "tables"):
            return
        self.hole_table_name = None
        result = self._try("insert_hole_table", {
            "view_name": self.view_name, "datum_entity": entity("vertex", *CORNER_TOP_LEFT),
            "x": 250, "y": 60,
        })
        if result.get("success"):
            self.hole_table_name = (result.get("data") or {}).get("name")

    def ensure_revision_table(self) -> None:
        self.ensure_drawing()
        if self.revision_table_name and self.revision_table_name in self._names(
                "list_tables", {"sheet_name": self.sheet_name}, "tables"):
            return
        self.revision_table_name = None
        result = self._try("insert_revision_table", {})
        if result.get("success"):
            self.revision_table_name = (result.get("data") or {}).get("name")

    def ensure_layer(self) -> None:
        self.ensure_drawing()
        if self.layer_name and self.layer_name in self._names("list_layers", {}, "layers"):
            return
        self.layer_name = None
        result = self._try("create_layer", {"name": "ValidationLayer", "color": "#FF0000"})
        if result.get("success"):
            self.layer_name = "ValidationLayer"

    def ensure_note(self) -> None:
        self.ensure_part_view()
        if self.note_name:
            return
        result = self._try("add_note", {"text": "Validation note", "x": 20, "y": 20})
        if result.get("success"):
            self.note_name = (result.get("data") or {}).get("name")

    def ensure_dimension(self) -> None:
        self.ensure_part_view()
        if self.dimension_name:
            return
        result = self._try("add_dimension", {
            "view_name": self.view_name,
            "entities": [entity("vertex", *CORNER_BOTTOM_RIGHT), entity("vertex", *CORNER_TOP_LEFT)],
            "x": 200, "y": 60, "dimension_type": "smart",
        })
        if result.get("success"):
            self.dimension_name = (result.get("data") or {}).get("name")

    def ensure_datum(self) -> None:
        self.ensure_part_view()
        if self.datum_label:
            return
        result = self._try("add_datum_feature", {
            "view_name": self.view_name, "entity": entity("edge", *BOTTOM_EDGE_MIDPOINT),
            "label": "A", "x": 0, "y": 90,
        })
        if result.get("success"):
            self.datum_label = (result.get("data") or {}).get("label") or "A"

    # -- Part-document context (sketches/features section) ----------------

    def ensure_part_document(self) -> None:
        if self.part_doc_active and self._active_doc_type() == "part":
            return
        result = self._try("create_new_part", {})
        self.part_doc_active = bool(result.get("success"))
        if self.part_doc_active:
            self.block_extruded = False

    def ensure_extruded_block(self) -> None:
        """A solid block to fillet/chamfer/cut, idempotent per part
        document -- needed so cut_extrude/fillet_edges/chamfer_edges are
        independently re-runnable via `--only` instead of silently
        depending on create_sketch/draw_rectangle/extrude_sketch having
        already run earlier in the same sweep."""
        self.ensure_part_document()
        if self.block_extruded:
            return
        self._try("create_sketch", {"plane": "Front"})
        self._try("draw_rectangle", {})
        self._try("close_sketch", {})
        result = self._try("extrude_sketch", {})
        self.block_extruded = bool(result.get("success"))

    def select_block_edge(self, x_mm: float, z_mm: float) -> None:
        """Best-effort direct edge selection for fillet_edges/chamfer_edges,
        which take no entity argument of their own -- they act on whatever
        is currently selected (see solidworks_mcp/automation/selection.py).
        No MCP tool exposes selection-by-coordinate, so this reaches the
        automation layer directly, same as scripts/make_test_geometry.py's
        `_select_vertical_edge` (not a dispatch() call, so it isn't part of
        the report; the fillet/chamfer tool call right after it is)."""
        for sign in (1, -1):
            y_mm = sign * _BLOCK_HEIGHT_MM / 2
            try:
                result = self.automation.select_by_id("", "EDGE", x_mm, y_mm, z_mm)
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"select_block_edge raised: {exc}")
                continue
            if result.get("success"):
                return
        self.warnings.append(f"select_block_edge: no edge found near x={x_mm} z={z_mm}")


# ============================================================================
# Per-tool argument builders. Each entry may declare `pre` (context
# setup, run before building args), `build` (arguments dict), and `post`
# (absorb the dispatched result back into context). Tools not listed here
# fall back to `_generic_build` -- required-field synthesis from the
# schema plus whatever context is already available -- so a newly
# registered tool is still exercised (see module docstring / sw-17y.2
# acceptance criteria: "new tools are covered automatically").
# ============================================================================

@dataclass
class ToolSpec:
    pre: Optional[Callable[[ScriptContext], None]] = None
    build: Callable[[ScriptContext], Dict[str, Any]] = lambda ctx: {}
    post: Optional[Callable[[ScriptContext, Dict[str, Any]], None]] = None


def _post_capture(field_name: str, data_key: str = "name"):
    def _post(ctx: ScriptContext, result: Dict[str, Any]) -> None:
        if result.get("success"):
            setattr(ctx, field_name, (result.get("data") or {}).get(data_key))
    return _post


def _post_add_sheet(ctx: ScriptContext, result: Dict[str, Any]) -> None:
    if result.get("success"):
        ctx.extra_sheet_name = "ValidationSheet2"


def _pre_cut_extrude(ctx: ScriptContext) -> None:
    """cut_extrude needs a solid block (see `ensure_extruded_block` --
    called here rather than relied on from an earlier sweep step, so
    `--only cut_extrude` reproduces the same context a full run would
    build) plus a *new* active sketch on its top face. Mirrors scripts/
    make_test_geometry.py's sign-ambiguity workaround: extrude_sketch
    doesn't report which way it extruded."""
    ctx.ensure_extruded_block()
    for sign in (1, -1):
        result = ctx._try("create_sketch_on_face", {
            "x": 0, "y": sign * _BLOCK_HEIGHT_MM / 2, "z": 0, "unit": "mm",
        })
        if result.get("success"):
            break
    ctx._try("draw_circle", {"x": 0, "y": 0, "radius": 5, "unit": "mm"})


def _pre_fillet_edges(ctx: ScriptContext) -> None:
    ctx.ensure_extruded_block()
    ctx.select_block_edge(_BLOCK_HALF_WIDTH_MM, _BLOCK_HALF_DEPTH_MM)


def _pre_chamfer_edges(ctx: ScriptContext) -> None:
    ctx.ensure_extruded_block()
    ctx.select_block_edge(-_BLOCK_HALF_WIDTH_MM, -_BLOCK_HALF_DEPTH_MM)


def _build_delete_table(ctx: ScriptContext) -> Dict[str, Any]:
    return {"table_name": ctx.hole_table_name or ctx.bom_table_name or ""}


def _pre_set_table_position(ctx: ScriptContext) -> None:
    ctx.ensure_bom_table()
    if ctx.bom_table_name:
        ctx._try("set_table_anchor", {"table_name": ctx.bom_table_name, "anchored": False})


def _build_create_drawing_pack(ctx: ScriptContext) -> Dict[str, Any]:
    """The same retargeting `solidworks_mcp/tests/integration/
    test_drawing_pipeline.py` does -- a real docs/packs/ example pointed at
    the generated assembly, with its calibrated (gearbox-specific) balloon
    coordinates dropped."""
    from solidworks_mcp.utils import find_template
    return {"spec": load_example_pack(
        "assembly_with_bom",
        model_path=ctx.assembly_path,
        output_path=ctx.output_dir / "_validation_pack_output.slddrw",
        drawing_template=find_template("drawing"),
    )}


TOOL_SPECS: Dict[str, ToolSpec] = {
    # -- capabilities / connection ---------------------------------------
    "get_capabilities": ToolSpec(),
    "connect_solidworks": ToolSpec(),
    "get_solidworks_info": ToolSpec(),

    # -- documents ---------------------------------------------------------
    "create_new_part": ToolSpec(),
    "create_new_assembly": ToolSpec(),
    "open_document": ToolSpec(build=lambda ctx: {"filepath": str(ctx.part_path)}),
    "save_document": ToolSpec(
        build=lambda ctx: {"filepath": str(ctx.output_dir / "_validation_save_document.sldprt")}),
    "close_document": ToolSpec(build=lambda ctx: {"save": False}),
    "get_document_info": ToolSpec(),
    "list_open_documents": ToolSpec(),

    # -- drawing documents ---------------------------------------------------
    "new_drawing_from_template": ToolSpec(post=_post_capture("sheet_name", "sheet_name")),
    "get_document_type": ToolSpec(),
    "open_or_activate_document": ToolSpec(build=lambda ctx: {"filepath": str(ctx.assembly_path)}),
    "rebuild_document": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "save_drawing": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"filepath": str(ctx.output_dir / "_validation_save_drawing.slddrw")},
    ),
    "export_pdf": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"output_path": str(ctx.output_dir / "_validation_export.pdf")},
    ),
    "export_dxf_dwg": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {
            "output_path": str(ctx.output_dir / "_validation_export.dxf"), "format": "dxf",
        },
    ),
    "export_edrawings": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"output_path": str(ctx.output_dir / "_validation_export.edrw")},
    ),
    "get_custom_properties": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "set_custom_properties": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"properties": {"ValidationRunProperty": "scripts/validate_on_windows.py"}},
    ),
    "batch_export_pack": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {
            "output_dir": str(ctx.output_dir / "_validation_batch_export"),
            "formats": ["pdf"], "overwrite": True,
        },
    ),

    # -- sheets --------------------------------------------------------------
    "add_sheet": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"name": "ValidationSheet2"}, post=_post_add_sheet),
    "activate_sheet": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"name": ctx.extra_sheet_name or ctx.sheet_name or "Sheet1"},
    ),
    "list_sheets": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "get_active_sheet": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "set_sheet_properties": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"sheet_name": ctx.sheet_name, "scale_num": 1, "scale_denom": 2},
    ),
    "set_sheet_scale": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"scale_num": 1, "scale_denom": 1, "sheet_name": ctx.sheet_name},
    ),
    "get_sheet_properties": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"sheet_name": ctx.sheet_name}),
    "copy_sheet": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"source_sheet": ctx.sheet_name, "new_name": "ValidationSheetCopy"},
    ),
    "delete_sheet": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"name": "ValidationSheetCopy"}),
    "rename_sheet": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {
            "old_name": ctx.extra_sheet_name or "ValidationSheet2",
            "new_name": "ValidationSheetRenamed",
        },
    ),

    # -- view creation --------------------------------------------------------
    "insert_model_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "model_path": str(ctx.part_path), "view_name": "*Right",
            "x": PART_VIEW_X + 200, "y": PART_VIEW_Y, "sheet_name": ctx.sheet_name,
        },
        post=_post_capture("extra_view_name", "view_name"),
    ),
    "insert_standard_3_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"model_path": str(ctx.part_path)}),
    "insert_projected_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"parent_view_name": ctx.view_name, "direction": "right"},
    ),
    "insert_predefined_views": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"model_path": str(ctx.part_path)}),
    "insert_auxiliary_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "parent_view_name": ctx.view_name, "edge_selection": entity("edge", *BOTTOM_EDGE_MIDPOINT),
            "x": PART_VIEW_X + 200, "y": PART_VIEW_Y + 150, "label": "B",
        },
    ),
    "insert_section_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "parent_view_name": ctx.view_name,
            "cut_points": [{"x": 0, "y": -HALF_DEPTH_MM}, {"x": 0, "y": HALF_DEPTH_MM}],
            "x": 250, "y": 100,
        },
    ),
    "insert_detail_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "parent_view_name": ctx.view_name,
            "center_x": HALF_WIDTH_MM - HOLE_INSET_MM, "center_y": HALF_DEPTH_MM - HOLE_INSET_MM,
            "radius": 15, "x": 250, "y": 250,
        },
    ),
    "insert_broken_out_section": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "parent_view_name": ctx.view_name,
            "profile_points": [{"x": -5, "y": -5}, {"x": 5, "y": -5}, {"x": 0, "y": 5}],
            "depth": 5,
        },
    ),
    "insert_break_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "position1": -10, "position2": 10, "orientation": "vertical",
        },
    ),
    "remove_break_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(), build=lambda ctx: {"view_name": ctx.view_name}),
    "add_crop_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name,
            "profile_points": [
                {"x": -5, "y": -5}, {"x": 5, "y": -5}, {"x": 5, "y": 5}, {"x": -5, "y": 5},
            ],
        },
    ),
    "remove_crop_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(), build=lambda ctx: {"view_name": ctx.view_name}),
    "list_views": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"sheet_name": ctx.sheet_name}),

    # -- view layout -----------------------------------------------------------
    "move_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "x": PART_VIEW_X + 10, "y": PART_VIEW_Y + 10},
    ),
    "align_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "alignment": "break"},
    ),
    "set_view_scale": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "scale_num": 1, "scale_denom": 2},
    ),
    "set_view_display_mode": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "mode": "hidden-lines-visible"},
    ),
    "delete_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.extra_view_name or ctx.view_name, "cascade": True},
    ),
    "auto_arrange_views": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"sheet_name": ctx.sheet_name}),

    # -- annotations -----------------------------------------------------------
    "insert_model_items": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(), build=lambda ctx: {"view_name": ctx.view_name}),
    "add_dimension": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name,
            "entities": [entity("vertex", *CORNER_BOTTOM_RIGHT), entity("vertex", *CORNER_TOP_LEFT)],
            "x": 200, "y": 60, "dimension_type": "smart",
        },
        post=_post_capture("dimension_name"),
    ),
    "add_ordinate_dimensions": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "origin_entity": entity("vertex", *CORNER_TOP_LEFT),
            "entities": [entity("vertex", *CORNER_BOTTOM_RIGHT)], "x": 50, "y": 140,
        },
    ),
    "set_dimension_value": ToolSpec(
        pre=lambda ctx: ctx.ensure_dimension(),
        build=lambda ctx: {"dimension_name": ctx.dimension_name or "", "value": 85},
    ),
    "set_dimension_text": ToolSpec(
        pre=lambda ctx: ctx.ensure_dimension(),
        build=lambda ctx: {"dimension_name": ctx.dimension_name or "", "prefix": "REF "},
    ),
    "autodimension_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(), build=lambda ctx: {"view_name": ctx.view_name}),
    "add_note": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"text": "Validation note\nline 2", "x": 20, "y": 20},
        post=_post_capture("note_name"),
    ),
    "add_property_note": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "property_name": "PartNo", "x": 20, "y": 40, "source": "sheet", "prefix": "Part No: ",
        },
    ),
    "list_notes": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "edit_note": ToolSpec(
        pre=lambda ctx: ctx.ensure_note(),
        build=lambda ctx: {"note_name": ctx.note_name or "", "text": "Updated validation note"},
    ),
    "list_datums": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "add_datum_feature": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "entity": entity("edge", *BOTTOM_EDGE_MIDPOINT), "label": "A",
            "x": 0, "y": 90,
        },
        post=_post_capture("datum_label", "label"),
    ),
    "add_gtol": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "entity": entity("face", *FACE_CENTER), "symbol": "flatness",
            "tolerance": 0.05, "x": 150, "y": 60,
        },
    ),
    "add_datum_target": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "entity": entity("face", *FACE_CENTER), "label": "a1",
            "area_type": "point", "size": 5, "x": 170, "y": 60,
        },
    ),
    "add_surface_finish": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "entity": entity("edge", *BOTTOM_EDGE_MIDPOINT), "x": 0, "y": 110,
        },
    ),
    "add_weld_symbol": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "entity": entity("edge", *BOTTOM_EDGE_MIDPOINT), "x": 0, "y": 130,
        },
    ),
    "add_center_marks": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "target": "all_holes"},
    ),
    "add_centerlines": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "target": "all", "select_view": True},
    ),
    "remove_center_marks": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(), build=lambda ctx: {"view_name": ctx.view_name}),

    # -- tables ----------------------------------------------------------------
    "insert_bom_table": ToolSpec(
        pre=lambda ctx: ctx.ensure_assembly_view(),
        build=lambda ctx: {
            "view_name": ctx.assembly_view_name, "x": 250, "y": 60, "bom_type": "top_level",
        },
        post=_post_capture("bom_table_name"),
    ),
    "list_tables": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"sheet_name": ctx.sheet_name}),
    "get_bom_contents": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: {"table_name": ctx.bom_table_name or ""},
    ),
    "auto_balloon_view": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: {
            "view_name": ctx.assembly_view_name, "bom_table_name": ctx.bom_table_name,
        },
    ),
    "add_balloon": ToolSpec(
        pre=lambda ctx: ctx.ensure_assembly_view(),
        build=lambda ctx: {
            "view_name": ctx.assembly_view_name,
            "entity": {"kind": "component", "x": ASSEMBLY_VIEW_X, "y": ASSEMBLY_VIEW_Y},
            "x": ASSEMBLY_VIEW_X + 40, "y": ASSEMBLY_VIEW_Y + 40,
        },
    ),
    "renumber_balloons": ToolSpec(
        pre=lambda ctx: ctx.ensure_assembly_view(),
        build=lambda ctx: {"view_name": ctx.assembly_view_name},
    ),
    "remove_balloons": ToolSpec(
        pre=lambda ctx: ctx.ensure_assembly_view(),
        build=lambda ctx: {"view_name": ctx.assembly_view_name},
    ),
    "insert_hole_table": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {
            "view_name": ctx.view_name, "datum_entity": entity("vertex", *CORNER_TOP_LEFT), "x": 250, "y": 60,
        },
        post=_post_capture("hole_table_name"),
    ),
    "insert_revision_table": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), post=_post_capture("revision_table_name"),
    ),
    "add_revision": ToolSpec(
        pre=lambda ctx: ctx.ensure_revision_table(),
        build=lambda ctx: {"description": "Validation run revision"},
    ),
    "insert_weldment_cutlist": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_view(),
        build=lambda ctx: {"view_name": ctx.view_name, "x": 250, "y": 250},
    ),
    "update_table": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: (
            {"table_name": ctx.bom_table_name} if ctx.bom_table_name else {"all_tables": True}
        ),
    ),
    "get_table_contents": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: {"table_name": ctx.bom_table_name or ""},
    ),
    "set_table_cell": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: {"table_name": ctx.bom_table_name or "", "row": 1, "column": 0, "text": "VAL"},
    ),
    "set_table_position": ToolSpec(
        pre=_pre_set_table_position,
        build=lambda ctx: {"table_name": ctx.bom_table_name or "", "x": 260, "y": 70},
    ),
    "set_table_anchor": ToolSpec(
        pre=lambda ctx: ctx.ensure_bom_table(),
        build=lambda ctx: {"table_name": ctx.bom_table_name or "", "anchored": True},
    ),
    "delete_table": ToolSpec(pre=lambda ctx: ctx.ensure_hole_table(), build=_build_delete_table),

    # -- layers ------------------------------------------------------------------
    "create_layer": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"name": "ValidationLayer", "color": "#FF0000"},
        post=lambda ctx, result: ctx.__setattr__("layer_name", "ValidationLayer")
        if result.get("success") else None,
    ),
    "list_layers": ToolSpec(pre=lambda ctx: ctx.ensure_drawing()),
    "set_current_layer": ToolSpec(
        pre=lambda ctx: ctx.ensure_layer(), build=lambda ctx: {"name": ctx.layer_name or ""}),
    "set_layer_properties": ToolSpec(
        pre=lambda ctx: ctx.ensure_layer(),
        build=lambda ctx: {"name": ctx.layer_name or "", "visible": True},
    ),
    "move_annotations_to_layer": ToolSpec(
        pre=lambda ctx: ctx.ensure_layer(), build=lambda ctx: {"layer_name": ctx.layer_name or ""}),

    # -- line format / drafting standard ------------------------------------------
    "set_line_format": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"target": "hidden", "weight": "thick", "style": "phantom"},
    ),
    "get_line_format": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(), build=lambda ctx: {"target": "hidden"}),
    "apply_drafting_standard": ToolSpec(
        pre=lambda ctx: ctx.ensure_drawing(),
        build=lambda ctx: {"standard_file": str(REPO_ROOT / "docs" / "drafting_standard.example.json")},
    ),

    # -- sketches / features (throwaway part document) ----------------------------
    # These 10 need only `ensure_part_document()` -- their own schema
    # defaults are already sensible args (see the generic-fallback builder),
    # they just need *some* part document active, which nothing upstream in
    # the sweep otherwise guarantees when run in isolation via --only.
    **{
        _name: ToolSpec(pre=lambda ctx: ctx.ensure_part_document())
        for _name in (
            "create_sketch_on_face", "draw_line", "draw_circle", "draw_rectangle",
            "draw_arc", "draw_polygon", "close_sketch", "get_sketch_status",
            "extrude_sketch", "list_features",
        )
    },
    "create_sketch": ToolSpec(
        pre=lambda ctx: ctx.ensure_part_document(), build=lambda ctx: {"plane": "Front"}),
    "cut_extrude": ToolSpec(pre=_pre_cut_extrude),
    "fillet_edges": ToolSpec(pre=_pre_fillet_edges),
    "chamfer_edges": ToolSpec(pre=_pre_chamfer_edges),

    # -- utility -------------------------------------------------------------------
    "set_units": ToolSpec(build=lambda ctx: {"unit": "mm"}),

    # -- drawing packs -------------------------------------------------------------
    "create_drawing_pack": ToolSpec(build=_build_create_drawing_pack),
}


# Type-appropriate stand-ins for a required parameter with no default and
# no well-known name. A string is also the fallback for an unknown or
# missing type.
_TYPE_STANDINS: Dict[Any, Any] = {
    "string": "validation",
    "number": 1,
    "integer": 1,
    "boolean": True,
    "array": [],
    "object": {},
}


def _generic_value_for(param_name: str, prop: Dict[str, Any], ctx: ScriptContext) -> Any:
    """Best-effort argument for one required parameter of a tool with no
    `TOOL_SPECS` entry -- context-derived when the parameter name is a
    well-known one, otherwise a type-appropriate stand-in. Exists so a
    newly registered tool is still dispatched (see sw-17y.2's "new tools
    are covered automatically" acceptance criterion), not so its result is
    guaranteed meaningful."""
    if "default" in prop:
        return prop["default"]
    if param_name == "view_name" and ctx.view_name:
        return ctx.view_name
    if param_name == "sheet_name" and ctx.sheet_name:
        return ctx.sheet_name
    if param_name in ("model_path", "filepath"):
        return str(ctx.part_path)
    if param_name == "unit":
        return "mm"

    prop_type = prop.get("type")
    if isinstance(prop_type, list):
        prop_type = prop_type[0] if prop_type else None
    return _TYPE_STANDINS.get(prop_type, "validation")


def _generic_build(schema: Dict[str, Any], ctx: ScriptContext) -> Dict[str, Any]:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    args: Dict[str, Any] = {}
    for param_name in required:
        args[param_name] = _generic_value_for(param_name, properties.get(param_name, {}), ctx)
    return args


def _generic_pre(schema: Dict[str, Any], ctx: ScriptContext) -> None:
    properties = schema.get("properties", {})
    if "view_name" in properties:
        ctx.ensure_part_view()
    elif "sheet_name" in properties:
        ctx.ensure_drawing()


# ============================================================================
# Filtering
# ============================================================================

def _split_patterns(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def matches_any(name: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def filter_status(name: str, only: Optional[str], skip: Optional[str]) -> Optional[str]:
    """Returns "filtered" if `name` is excluded by `--only`/`--skip`,
    otherwise `None` (dispatch it)."""
    only_patterns = _split_patterns(only)
    skip_patterns = _split_patterns(skip)
    if only_patterns and not matches_any(name, only_patterns):
        return "filtered"
    if skip_patterns and matches_any(name, skip_patterns):
        return "filtered"
    return None


# ============================================================================
# Core sweep -- registry-driven, dependency-injectable for testing.
# ============================================================================

def run_validation(
    registry: Any,
    ctx: ScriptContext,
    *,
    only: Optional[str] = None,
    skip: Optional[str] = None,
    exclusions: Optional[Dict[str, str]] = None,
    tool_specs: Optional[Dict[str, ToolSpec]] = None,
    clock: Callable[[], float] = time.perf_counter,
) -> List[ToolRecord]:
    """Dispatch every tool `registry.describe_tools()` reports (in that
    order), recording one `ToolRecord` per tool. `registry` needs only
    `.describe_tools()` (name/description/schema/min_release, no live
    connection required) and `.dispatch(name, arguments)` -- exactly
    `solidworks_mcp.tools.registry`'s surface, or a fake with the same
    shape for testing.
    """
    exclusions = EXCLUSIONS if exclusions is None else exclusions
    tool_specs = TOOL_SPECS if tool_specs is None else tool_specs

    records: List[ToolRecord] = []
    for entry in registry.describe_tools():
        name = entry["name"]

        if name in exclusions:
            records.append(ToolRecord(name=name, status="skipped", reason=exclusions[name]))
            continue

        filtered = filter_status(name, only, skip)
        if filtered is not None:
            records.append(ToolRecord(name=name, status="filtered", reason="excluded by --only/--skip"))
            continue

        spec = tool_specs.get(name)
        try:
            if spec is None:
                _generic_pre(entry["schema"], ctx)
                arguments = _generic_build(entry["schema"], ctx)
            else:
                if spec.pre is not None:
                    spec.pre(ctx)
                arguments = spec.build(ctx)
        except Exception as exc:  # noqa: BLE001 -- a broken arg-builder must not abort the sweep
            records.append(ToolRecord(
                name=name, status="fail", arguments={},
                message=f"Argument setup raised: {exc}",
                error=traceback.format_exc(),
            ))
            continue

        start = clock()
        try:
            result = registry.dispatch(name, arguments)
        except Exception as exc:  # noqa: BLE001 -- the whole point of this sweep
            elapsed = clock() - start
            records.append(ToolRecord(
                name=name, status="fail", arguments=arguments,
                message=_describe_exception(exc), elapsed_seconds=elapsed,
                error=traceback.format_exc(), com_hresult=_extract_hresult(exc),
            ))
            continue
        elapsed = clock() - start

        status = "pass" if result.get("success") else "fail"
        records.append(ToolRecord(
            name=name, status=status, arguments=arguments,
            message=str(result.get("message", "")), elapsed_seconds=elapsed,
        ))

        if spec is not None and spec.post is not None:
            try:
                spec.post(ctx, result)
            except Exception as exc:  # noqa: BLE001 -- context absorption is best-effort
                ctx.warnings.append(f"post-hook for {name} raised: {exc}")

    return records


# ============================================================================
# Report generation
# ============================================================================

def build_report(records: List[ToolRecord], meta: Dict[str, Any]) -> Dict[str, Any]:
    summary = {"total": len(records), "pass": 0, "fail": 0, "skipped": 0, "filtered": 0}
    summary.update(Counter(record.status for record in records))
    return {
        "meta": meta,
        "summary": summary,
        "tools": [r.to_dict() for r in records],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    meta = report["meta"]
    summary = report["summary"]
    lines = [
        "# SolidWorks tool validation report",
        "",
        f"- Generated: {meta.get('generated_at', 'unknown')}",
        f"- Connected SOLIDWORKS release: {meta.get('connected_release', 'unknown')}",
        f"- Configured minimum release: {meta.get('min_release', 'unknown')}",
        "",
        "## Per-tool results",
        "",
        "| Tool | Status | Elapsed (s) | Message |",
        "| --- | --- | --- | --- |",
    ]
    for tool in report["tools"]:
        message = (tool.get("message") or tool.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        if len(message) > 160:
            message = message[:157] + "..."
        lines.append(f"| {tool['name']} | {tool['status']} | {tool['elapsed_seconds']} | {message} |")

    failed = [t for t in report["tools"] if t["status"] == "fail"]
    if failed:
        lines += ["", "## Failures", ""]
        for tool in failed:
            lines.append(f"### {tool['name']}")
            lines.append("")
            lines.append(f"- Arguments: `{json.dumps(tool['arguments'])}`")
            lines.append(f"- Message: {tool['message']}")
            if tool.get("com_hresult") is not None:
                lines.append(f"- COM HRESULT: {tool['com_hresult']}")
            if tool.get("error"):
                lines.append("- Traceback:")
                lines.append("```")
                lines.append(tool["error"].rstrip())
                lines.append("```")
            lines.append("")

    skipped = [t for t in report["tools"] if t["status"] == "skipped"]
    if skipped:
        lines += ["", "## Excluded (never dispatched)", ""]
        for tool in skipped:
            lines.append(f"- **{tool['name']}**: {tool['reason']}")

    lines += [
        "",
        "## Summary",
        "",
        "| Total | Passed | Failed | Skipped (excluded) | Filtered (--only/--skip) |",
        "| --- | --- | --- | --- | --- |",
        f"| {summary['total']} | {summary['pass']} | {summary['fail']} "
        f"| {summary['skipped']} | {summary['filtered']} |",
    ]

    return "\n".join(lines) + "\n"


def write_reports(report: Dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_dir / "validation_report.md").write_text(render_markdown(report), encoding="utf-8")


# ============================================================================
# Dialog suppression -- best-effort, restored on exit even on exception.
# Only touches user preferences this project already knows the numeric ID
# for (SwUserPreferenceToggle.swDXFDontShowMap -- see constants_drawing.py's
# own docstring on why the rest of that enum's values are not guessed at)
# plus swInputDimValOnCreate, resolved from the installed type library at
# runtime rather than hardcoded (docs/api/03-annotations.md documents the
# *need* to set it, not a numeric value). If either can't be established,
# suppression for that one dialog is skipped and logged -- "where possible"
# per this issue's requirements, not a hard dependency.
# ============================================================================

@contextmanager
def _suppress_dimension_value_dialog(app: Any):
    pref_id = None
    if app is not None:
        try:
            from solidworks_mcp import com_backend
            win32com_client = com_backend.get_win32com()
            pref_id = int(win32com_client.constants.swInputDimValOnCreate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dimension-value dialog suppression unavailable: %s", exc)

    if pref_id is None or app is None:
        yield
        return

    try:
        original = app.GetUserPreferenceToggle(pref_id)
        app.SetUserPreferenceToggle(pref_id, True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dimension-value dialog suppression unavailable: %s", exc)
        yield
        return

    try:
        yield
    finally:
        try:
            app.SetUserPreferenceToggle(pref_id, original)
        except Exception:  # noqa: BLE001 -- best-effort restore
            logger.warning("could not restore swInputDimValOnCreate to its original value")


@contextmanager
def _suppress_dialogs(automation: Any):
    from solidworks_mcp.constants_drawing import SwUserPreferenceToggle

    with ExitStack() as stack:
        try:
            stack.enter_context(automation._user_preference(SwUserPreferenceToggle.swDXFDontShowMap, True))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DXF layer-mapping dialog suppression unavailable: %s", exc)
        stack.enter_context(_suppress_dimension_value_dialog(automation.app))
        yield


# ============================================================================
# Cleanup -- close every document SolidWorks has open, without saving, even
# on exception. Same bounded-loop idiom as solidworks_mcp/tests/integration/
# conftest.py's `_close_documents_after_test` fixture.
# ============================================================================

def _close_all_documents(automation: Any) -> None:
    """Closes directly through the automation instance, not `dispatch()` --
    `list_open_documents`/`close_document` are version-gated tools
    (solidworks_mcp/version_gate.py), and cleanup must still run against an
    unsupported/older SOLIDWORKS release the gate would otherwise refuse
    every call against."""
    for _ in range(50):
        info = automation.list_open_documents()
        documents = (info.get("data") or {}).get("documents", [])
        if not documents:
            return
        automation.close_document(False)
    logger.warning("_close_all_documents: still open after 50 iterations, giving up")


# ============================================================================
# Geometry generation
# ============================================================================

def ensure_geometry(geometry_dir: Path, force: bool) -> bool:
    part_path = geometry_dir / BRACKET_PART_NAME
    assembly_path = geometry_dir / BRACKET_ASSEMBLY_NAME
    if not force and part_path.exists() and assembly_path.exists():
        logger.info("Reusing existing generated geometry in %s (pass --force-geometry to rebuild)",
                    geometry_dir)
        return True

    logger.info("Generating test geometry via scripts/make_test_geometry.py ...")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_test_geometry.py"),
         "--out-dir", str(geometry_dir)],
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        logger.error("make_test_geometry.py failed with exit code %s", result.returncode)
        return False
    return part_path.exists() and assembly_path.exists()


# ============================================================================
# main
# ============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR),
                         help="Directory for validation_report.{md,json} (default: %(default)s)")
    parser.add_argument("--geometry-dir", default=str(DEFAULT_GEOMETRY_DIR),
                         help="Directory for the generated test geometry (default: %(default)s)")
    parser.add_argument("--force-geometry", action="store_true",
                         help="Regenerate test geometry even if it already exists")
    parser.add_argument("--only", default=None,
                         help="Comma-separated glob pattern(s); only matching tools are dispatched")
    parser.add_argument("--skip", default=None,
                         help="Comma-separated glob pattern(s); matching tools are never dispatched")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    if sys.platform != "win32":
        logger.error(
            "validate_on_windows.py requires Windows + SolidWorks; got platform %r. "
            "This validates the live tool registry against a real SolidWorks install, "
            "not something to run in CI/off-Windows.",
            sys.platform,
        )
        return 1

    geometry_dir = Path(args.geometry_dir).resolve()
    output_dir = Path(args.out_dir).resolve()

    if not ensure_geometry(geometry_dir, args.force_geometry):
        return 1

    part_path = geometry_dir / BRACKET_PART_NAME
    assembly_path = geometry_dir / BRACKET_ASSEMBLY_NAME

    connect_result = tool_registry.dispatch("connect_solidworks", {})
    if not connect_result.get("success"):
        logger.error("Could not connect to SolidWorks: %s", connect_result.get("message"))
        return 1

    from solidworks_mcp import version_gate
    from solidworks_mcp.config import get_config

    min_release = get_config().min_release
    connected_release = None
    try:
        release = version_gate.get_connected_release(sw_automation)
        connected_release = release.year
        logger.info("Connected to SOLIDWORKS %s (minimum configured: %s)", release.year, min_release)
    except version_gate.VersionGateError as exc:
        logger.warning("Could not determine connected SOLIDWORKS version: %s", exc)

    dispatch_fn = tool_registry.dispatch
    ctx = ScriptContext(dispatch_fn, part_path, assembly_path, output_dir)

    try:
        with _suppress_dialogs(sw_automation):
            records = run_validation(tool_registry, ctx, only=args.only, skip=args.skip)
    finally:
        try:
            _close_all_documents(sw_automation)
        except Exception:  # noqa: BLE001 -- cleanup must not mask the real result
            logger.exception("Error while closing documents during cleanup")
        try:
            sw_automation.disconnect()
        except Exception:  # noqa: BLE001
            pass

    for warning in ctx.warnings:
        logger.debug("context: %s", warning)

    meta = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "connected_release": connected_release,
        "min_release": min_release,
        "geometry_dir": str(geometry_dir),
        "only": args.only,
        "skip": args.skip,
    }
    report = build_report(records, meta)
    write_reports(report, output_dir)

    logger.info(
        "Validation complete: %s pass, %s fail, %s skipped, %s filtered (report: %s)",
        report["summary"]["pass"], report["summary"]["fail"],
        report["summary"]["skipped"], report["summary"]["filtered"], output_dir,
    )

    return 1 if report["summary"]["fail"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
