# SolidWorks MCP Server 🔧

> Automate SolidWorks using natural language through Claude AI and the Model Context Protocol (MCP)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks 2025+](https://img.shields.io/badge/SolidWorks-2025%2B-red.svg)](https://www.solidworks.com/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

---

## 🎯 What is This?

**SolidWorks MCP Server** is a [Model Context Protocol](https://modelcontextprotocol.io/)
server that lets Claude control SolidWorks through natural language: parts and
assemblies, sketches and features, and a full drawing pipeline (sheets, views,
dimensions, GD&T, tables, balloons, layers, and export) driven directly through
the COM API. Instead of clicking through menus, you describe what you want and
the server does it.

**Example prompts you can use:**
- *"Create a new part, draw a circle with radius 30mm and extrude it 15mm"*
- *"Add a fillet of 2mm to all edges"*
- *"Create a drawing of this part with front/top/right views and a GD&T flatness callout"*
- *"Insert a BOM table on this assembly drawing and balloon every component"*
- *"Export the current drawing to PDF"*

---

## ✨ Features

- ✅ **111 tools** across connection, documents, sketching, features, and a full
  drawing pipeline (sheets, views, annotations, tables, layers, packs) — see
  [Tool Categories](#tool-categories) below and the generated
  [`docs/TOOLS.md`](docs/TOOLS.md) for the complete per-tool reference.
- ✅ **SOLIDWORKS 2025+** with a runtime version gate (`get_capabilities`) that
  reports which tools are usable against the connected install.
- ✅ **Declarative drawing packs** — describe a whole drawing (sheets, views,
  annotations, tables, balloons, export) as one JSON spec and let
  `create_drawing_pack` build it, instead of hand-sequencing 15-20 raw calls.
  See [`docs/DRAWING_PACKS.md`](docs/DRAWING_PACKS.md).
- ✅ **Auto-detects SolidWorks** installation via the Windows registry.
- ✅ **Multi-unit support** — the public tool API takes lengths in whatever unit
  `set_units` is set to (mm/cm/inch/meter/foot) and angles in degrees; the COM
  boundary converts to meters/radians.
- ✅ **Testable without a SolidWorks install** — a recording fake-COM harness
  backs the whole test suite. See
  [Development without SolidWorks](#development-without-solidworks).
- ✅ **Hand-researched API dossier** (`docs/api/`) backing every drawing-tool
  signature, instead of guessing COM parameter order.
- ✅ **JSON configuration** — easy to customize without touching code.
- ✅ **Comprehensive logging** — full debug output for troubleshooting.

---

## Tool Categories

<!-- registered-tools:start -->
| Category | Tools | Count |
| --- | --- | --- |
| Connection & Session | `connect_solidworks`, `get_solidworks_info` | 2 |
| Documents | `create_new_part`, `create_new_assembly`, `open_document`, `save_document`, `close_document`, `get_document_info`, `list_open_documents` | 7 |
| Sketches | `create_sketch`, `create_sketch_on_face`, `draw_line`, `draw_circle`, `draw_rectangle`, `draw_arc`, `draw_polygon`, `close_sketch`, `get_sketch_status` | 9 |
| Features | `extrude_sketch`, `cut_extrude`, `fillet_edges`, `chamfer_edges`, `list_features` | 5 |
| Utilities | `set_units`, `execute_python` | 2 |
| Capabilities | `get_capabilities` | 1 |
| Drawing Documents & Export | `new_drawing_from_template`, `get_document_type`, `open_or_activate_document`, `rebuild_document`, `save_drawing`, `export_pdf`, `export_dxf_dwg`, `export_edrawings`, `get_custom_properties`, `set_custom_properties`, `batch_export_pack` | 11 |
| Drawing Sheets | `add_sheet`, `activate_sheet`, `list_sheets`, `get_active_sheet`, `set_sheet_properties`, `set_sheet_scale`, `get_sheet_properties`, `copy_sheet`, `delete_sheet`, `rename_sheet` | 10 |
| Drawing Views | `insert_model_view`, `insert_standard_3_view`, `insert_projected_view`, `insert_predefined_views`, `insert_auxiliary_view`, `insert_section_view`, `insert_detail_view`, `insert_broken_out_section`, `insert_break_view`, `remove_break_view`, `add_crop_view`, `remove_crop_view`, `list_views` | 13 |
| View Layout | `move_view`, `align_view`, `set_view_scale`, `set_view_display_mode`, `delete_view`, `auto_arrange_views` | 6 |
| Annotations & GD&T | `insert_model_items`, `add_dimension`, `add_ordinate_dimensions`, `set_dimension_value`, `set_dimension_text`, `autodimension_view`, `add_note`, `add_property_note`, `list_notes`, `edit_note`, `list_datums`, `add_datum_feature`, `add_gtol`, `add_datum_target`, `add_surface_finish`, `add_weld_symbol`, `add_center_marks`, `add_centerlines`, `remove_center_marks` | 19 |
| Tables & Balloons | `insert_bom_table`, `list_tables`, `get_bom_contents`, `auto_balloon_view`, `add_balloon`, `renumber_balloons`, `remove_balloons`, `insert_hole_table`, `insert_revision_table`, `add_revision`, `insert_weldment_cutlist`, `update_table`, `get_table_contents`, `set_table_cell`, `set_table_position`, `set_table_anchor`, `delete_table` | 17 |
| Layers | `create_layer`, `list_layers`, `set_current_layer`, `set_layer_properties`, `move_annotations_to_layer` | 5 |
| Line Format & Drafting Standards | `set_line_format`, `get_line_format`, `apply_drafting_standard` | 3 |
| Drawing Packs | `create_drawing_pack` | 1 |
| **Total** | | **111** |
<!-- registered-tools:end -->

The table above is a category summary; [`docs/TOOLS.md`](docs/TOOLS.md) is the
generated, always-up-to-date reference with every tool's full description,
parameters, and minimum SOLIDWORKS release (`scripts/gen_tools_doc.py --check`
fails the build if it ever drifts from the registry). Call the
`get_capabilities` tool at runtime to see which tools are usable against your
specific connected SOLIDWORKS install.

---

## 📋 Requirements

- **OS:** Windows 10 or Windows 11 (SolidWorks itself is Windows-only; see
  [Development without SolidWorks](#development-without-solidworks) if
  you're contributing from macOS/Linux)
- **SolidWorks:** 2025 or later, installed and licensed
- **Python:** 3.13 (see `pyproject.toml`)
- **Claude:** Claude Desktop app or Claude Code

---

## ⚡ Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/alisamsam/solidworks-mcp.git
cd solidworks-mcp
```

### 2. Set Up the Dev Environment

On Windows (PowerShell):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_dev.ps1
```

On macOS/Linux (bash):

```bash
./scripts/setup_dev.sh
```

Either script creates `.venv` and installs `requirements.txt` +
`requirements-dev.txt` into it (`pywin32` is pulled in automatically on
Windows only, via a platform marker — nothing extra to install). See
[`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md) for prerequisites and
troubleshooting specific to running against a real SolidWorks install.

### 3. Configure Claude Desktop

Add the following to your `claude_desktop_config.json`:

**Location:** `C:\Users\YOUR_NAME\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "C:\\path\\to\\solidworks-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\solidworks-mcp\\solidworks_mcp_server.py"]
    }
  }
}
```

Point `command` at the venv's own interpreter (not a bare `python`) so the
server always runs with the dependencies `setup_dev.ps1` installed, regardless
of what's on the system `PATH`.

### 4. Configure Claude Code

Claude Code reads the same kind of MCP server config via `claude mcp add`, or
by adding an entry to its own `mcpServers` config:

```powershell
claude mcp add solidworks -- C:\path\to\solidworks-mcp\.venv\Scripts\python.exe C:\path\to\solidworks-mcp\solidworks_mcp_server.py
```

### 5. Launch

1. Open **SolidWorks** first (or let `connect_solidworks` launch it for you).
2. Restart **Claude Desktop** / start a **Claude Code** session.
3. Ask Claude to *"Connect to SolidWorks"*.
4. Start designing! 🎉

---

## 📐 Walkthrough: Create and Annotate a Drawing Pack

Two ways to produce a finished drawing, using the actual registered tool
names:

**The declarative way** — describe the whole drawing as one spec and let the
composite tool sequence everything (including rebuild timing) for you:

<!-- registered-tools:start -->
1. `connect_solidworks`
2. `create_drawing_pack` with a `PackSpec` (see
   [`docs/DRAWING_PACKS.md`](docs/DRAWING_PACKS.md) and the three worked
   examples under [`docs/packs/`](docs/packs/)) — this single call creates the
   sheet, inserts views, adds annotations and tables, rebuilds at the right
   points, and saves the output.
<!-- registered-tools:end -->

**The manual way** — the same result, one primitive at a time:

<!-- registered-tools:start -->
1. `connect_solidworks` — attach to (or launch) SolidWorks.
2. `new_drawing_from_template` — create the drawing document.
3. `add_sheet`, `set_sheet_properties`, `set_sheet_scale` — set up the sheet.
4. `insert_model_view` for the main view, then `insert_projected_view` for
   each additional orthographic view.
5. `rebuild_document` (forced) — view geometry and dimensions are stale until
   this runs.
6. `add_dimension`, `add_note`, `add_gtol`, `add_datum_feature` — annotate.
7. `insert_bom_table` (assemblies) and `auto_balloon_view` — table + balloons.
8. `rebuild_document` again — BOM quantities and balloon numbers need a second
   rebuild once the table exists.
9. `save_drawing`, then `export_pdf` or `export_dxf_dwg` to hand off the sheet.
<!-- registered-tools:end -->

The manual sequence is exactly what `create_drawing_pack` runs internally
(see [`docs/DRAWING_PACKS.md`](docs/DRAWING_PACKS.md#execution-order)) — reach
for it directly when you're editing one existing drawing rather than building
a whole one from scratch.

---

## Development without SolidWorks

SolidWorks' COM API only exists on Windows with a licensed install, but the
whole test suite (and most of day-to-day development) runs on any platform,
because every tool talks to SolidWorks through one seam
(`solidworks_mcp/com_backend.py`) that tests swap for a **recording fake-COM
harness** (`solidworks_mcp/testing/fake_com.py`) instead of real `win32com`.

`FakeComObject` auto-vivifies any COM member access (so `doc.SketchManager
.InsertSketch(True)` "just works" without pre-declaring every interface it
might touch), records every method call with its exact positional arguments
(so a test can assert a length was passed as `0.05` meters, not `50`), and can
be scripted ahead of time to return specific values, raise, or return a
different value on each successive call — enough to exercise both the happy
path and the error-handling path of a tool. `FakeSldWorks` wires up a
plausible `SldWorks.Application` → `ActiveDoc` object graph so most tools work
against it with no further setup; see `solidworks_mcp/tests/conftest.py`'s
`fake_sw`/`automation`/`tool_sw` fixtures for how tests get one.

In practice this means:

- You can write and test a new tool entirely on macOS/Linux, and the same test
  gives real confidence about COM method names and argument order — the
  fake-COM tests are what `scripts/validate_on_windows.py` (Windows-only,
  against a real install) exists to *additionally* confirm at the integration
  level, not to replace.
- `bash scripts/check.sh` — compiles the package, lints it, validates the
  `docs/api/` dossier format, checks `docs/TOOLS.md` is up to date, and runs
  the full pytest suite — passes on any platform and is the gate to run before
  committing.
- Tests marked `@pytest.mark.windows` or `@pytest.mark.integration`
  (`pyproject.toml`) are the exception: those need a real SolidWorks install
  and are skipped elsewhere.

---

## 📁 Project Structure

```
solidworks-mcp/
├── solidworks_mcp_server.py      # Entry point
├── solidworks_mcp/               # Main package
│   ├── server.py                 # MCP server wiring
│   ├── config.py / config.json   # Configuration management
│   ├── constants.py / constants_drawing.py  # SolidWorks enums & error codes
│   ├── version_gate.py           # Per-tool minimum-SOLIDWORKS-release enforcement
│   ├── automation/                # SolidWorksAutomation + DrawingOperations mixins
│   ├── tools/                     # @tool-registered MCP tools (registry.py + one module per category)
│   ├── pack/                      # Declarative drawing-pack spec + compiler
│   ├── testing/                   # Fake-COM harness used by the whole test suite
│   └── tests/                     # pytest suite (fake-COM; integration/ needs Windows)
├── docs/
│   ├── TOOLS.md                  # GENERATED tool index (scripts/gen_tools_doc.py)
│   ├── api/                       # Hand-researched COM API dossier
│   ├── WINDOWS_SETUP.md          # Windows prerequisites, setup, troubleshooting
│   ├── DRAWING_PACKS.md          # Pack spec format + worked examples
│   └── packs/                     # The worked example PackSpec JSON files
├── scripts/
│   ├── setup_dev.sh / setup_dev.ps1   # Dev environment bootstrap
│   ├── check.sh                       # Build gate: lint, docs, tests
│   ├── validate_on_windows.py         # End-to-end runner against real SolidWorks
│   └── gen_tools_doc.py               # Regenerates docs/TOOLS.md
├── requirements.txt / requirements-dev.txt
└── DEVELOPMENT_ROADMAP.md        # Historical planning doc (see its own notice)
```

---

## ⚙️ Configuration

Edit `solidworks_mcp/config.json` to customize behavior:

```json
{
  "exe_path": "auto",
  "default_unit": "mm",
  "startup_timeout": 120,
  "log_level": "INFO",
  "default_extrude_depth": 10.0,
  "default_fillet_radius": 2.0
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `exe_path` | `"auto"` | Path to SLDWORKS.exe or auto-detect |
| `part_template` / `assembly_template` / `drawing_template` | `"auto"` | Template paths, or auto-detect (see [`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md#template-discovery)) |
| `default_unit` | `"mm"` | Default unit for all dimensions |
| `startup_timeout` | `120` | Seconds to wait for SW startup |
| `min_release` | `2025` | SOLIDWORKS release year every tool call is gated against (`version_gate.py`) |
| `log_level` | `"INFO"` | Logging verbosity |

---

## 🔧 SOLIDWORKS Version Gating

Every tool that requires a specific COM signature declares a minimum
SOLIDWORKS release; `dispatch()` checks the connected version against it
before running the handler (`solidworks_mcp/version_gate.py`). Call
`get_capabilities` to see the connected version, the project's floor
(`min_release`), and which of the 111 registered tools are actually usable
right now. Lower `min_release` in `config.json` deliberately if you need to
test against an older install — see [`docs/api/06-versioning.md`](docs/api/06-versioning.md).

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run `bash scripts/check.sh` before committing — it must exit 0
4. Commit your changes: `git commit -m "Add my feature"`
5. Push to the branch: `git push origin feature/my-feature`
6. Open a Pull Request

New drawing-tool work should follow the working agreement in the drawing-tool
epic: signatures come from `docs/api/` (research and add to the dossier rather
than guessing), automation methods live on the `DrawingOperations` mixin,
lengths are user-unit at the tool boundary and meters at the COM boundary, and
every tool is exercised against the fake-COM harness — see
[Development without SolidWorks](#development-without-solidworks).

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Samsaam Ali Baig**
- GitHub: [@alisamsam](https://github.com/alisamsam)

---

## 🙏 Acknowledgements

- [Anthropic](https://anthropic.com) for Claude AI and the MCP framework
- [SolidWorks](https://www.solidworks.com) COM API documentation
- Inspired by [ros2-claude-code-template](https://github.com/harunkurt/ros2-claude-code-template) by Harun KURT

---

⭐ **If this project helps you, please give it a star!**
