# Windows Setup

This project's COM automation only runs on Windows against a real SOLIDWORKS
install. Everything else (tests, linting, doc generation) runs fine on macOS/Linux
too -- see ["Development without SOLIDWORKS"](../README.md#development-without-solidworks)
in the README if that's what you're here for instead.

## Prerequisites

- **SOLIDWORKS 2025 or later**, installed and licensed on the machine you'll run
  the server from. The `docs/api/` dossier is researched against the 2025 COM
  API, and the project's default version gate (`SolidWorksConfig.min_release`,
  `solidworks_mcp/config.py`) refuses to dispatch a tool call against anything
  older unless you deliberately lower it. See
  [`docs/api/06-versioning.md`](api/06-versioning.md) and `get_capabilities` for
  how the gate reports what's usable against your install.
- **Python 3.13** (matches this repo's `pyproject.toml` `target-version`; 3.10+
  will likely also work, but 3.13 is what's actually tested here).
- **pywin32** -- you do not install this separately. `requirements.txt` pulls it
  in automatically on Windows via a `sys_platform == "win32"` marker, so the
  normal `pip install -r requirements.txt` step below covers it. It is never
  installed (or required) on macOS/Linux dev machines.

## Set up the dev environment

From a PowerShell prompt, in the repo root:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_dev.ps1
```

`setup_dev.ps1` is the Windows equivalent of `scripts/setup_dev.sh`: it creates
`.venv`, upgrades `pip`, and installs `requirements.txt` +
`requirements-dev.txt` into it (pulling in `pywin32` per the prerequisite
above). Activate the venv afterward with:

```powershell
.venv\Scripts\Activate.ps1
```

`scripts\check.sh` and `scripts\validate_on_windows.py` both auto-detect
`.venv\Scripts\python.exe` when `.venv/bin/python` doesn't exist, so you don't
need the venv activated to run either -- activation is only for convenience
in an interactive shell.

## Running the end-to-end validation runner

Once SOLIDWORKS is installed and the dev environment above is set up, open
SOLIDWORKS (or let the runner launch it -- `connect_solidworks` will start it
if it isn't already running) and run:

```powershell
.venv\Scripts\python.exe scripts\validate_on_windows.py
```

This connects to SOLIDWORKS, generates throwaway test geometry
(`scripts/make_test_geometry.py`), and dispatches every tool registered in
`solidworks_mcp/tools/registry.py` at least once with realistic arguments,
recording a pass/fail/skip verdict for each into
`tests/fixtures/generated/validation_report.md` and `.json` (gitignored). It
exits nonzero if any tool failed, so it's suitable as a CI-style gate on a
Windows runner, not just interactive triage.

Useful flags:

- `--out-dir DIR` -- write the reports somewhere other than
  `tests/fixtures/generated/`.
- `--only PATTERN` / `--skip PATTERN` -- narrow which tools are actually
  dispatched (fnmatch-style), e.g. `--only "insert_*"` to re-run just the view
  tools after fixing one. The report still has one entry per registered tool
  either way -- narrowed-out tools show up as `"filtered"`, not omitted.
- `--force-geometry` -- regenerate the test part/assembly even if they already
  exist under `--geometry-dir`.
- `-v` / `--verbose` -- debug-level logging.

Run `.venv\Scripts\python.exe scripts\validate_on_windows.py --help` for the
full list.

## Troubleshooting

### COM connection failures

`connect_solidworks` (`SolidWorksAutomation.connect()`, `solidworks_mcp/automation/base.py`)
tries to attach to an already-running SOLIDWORKS instance first, and only
launches a new one (via `os.startfile`) if that fails. If it times out waiting
for a freshly-launched instance, the result message says exactly this:

> Timeout after `startup_timeout` seconds. Close any dialogs and try again.

That timeout is almost always a startup dialog stealing focus (see the next
section), not SOLIDWORKS actually failing to start. If it keeps happening:

- Increase `startup_timeout` in `solidworks_mcp/config.json` -- SOLIDWORKS'
  first cold start after a reboot or update can genuinely take longer than the
  120s default.
- Confirm `exe_path` in `config.json` is either `"auto"` (registry-based
  auto-detect via `solidworks_mcp/utils/sw_finder.py`) or an actual, correct
  path to `SLDWORKS.exe` -- a stale hardcoded path from a prior SOLIDWORKS
  version upgrade is a common cause of "not found" rather than "timeout".
- If SOLIDWORKS is already running under a different Windows user session or
  elevation level than the Python process, COM activation can silently fail --
  run both as the same user.

### Template discovery

`new_drawing_from_template` and the `part_template`/`assembly_template`/
`drawing_template` config settings resolve `"auto"` by searching
`SolidWorksFinder.TEMPLATE_SUBDIRS` (`solidworks_mcp/utils/sw_finder.py`)
relative to the detected SOLIDWORKS install directory. This fails (reported as
`SwErrors.swTemplateNotFound`) when:

- Templates were customized or moved outside the default `data/templates`
  layout (common in a managed corporate SOLIDWORKS deployment) -- point the
  relevant `*_template` config setting at the real `.drwdot`/`.prtdot`/
  `.asmdot` path instead of `"auto"`.
- A `PackSpec`'s `drawing_template` field is set to a path that doesn't exist
  on this machine -- pack specs are meant to be portable between machines
  only if the template path is too; see
  [`docs/DRAWING_PACKS.md`](DRAWING_PACKS.md).

### Dialogs blocking automation

SOLIDWORKS' COM API is largely modal-dialog-driven for anything it considers
an interactive decision (Save As format prompts, "document has been modified"
prompts, rebuild-required prompts, feature errors). A blocking dialog freezes
every COM call this project makes -- including the connection retry loop
above -- until a human dismisses it, which is why `validate_on_windows.py` and
any unattended run should start from a clean SOLIDWORKS session with no
document open and no prior crash/recovery dialog pending. If a run hangs
rather than failing outright, switch to the SOLIDWORKS window and look for a
dialog before assuming the process is stuck.

### Read-only save errors

`save_document`/`save_drawing` fail with `SwErrors.swFileSaveError` when the
target file is read-only on disk, checked out to someone else in PDM, or the
output directory doesn't exist. `open_document`'s `read_only` argument opens a
document read-only *on purpose* (e.g. to inspect it without risking an
accidental save) -- a save failure right after opening with `read_only=True`
is expected, not a bug; reopen without it if you intend to save.

### Stale rebuild state

SOLIDWORKS does not recompute dimension values, BOM quantities, or balloon
numbers until something forces a rebuild. `rebuild_document` exposes both
`IModelDoc2::ForceRebuild3` (`force=True`, the default -- rebuilds everything)
and the cheaper incremental `IModelDoc2::EditRebuild3` (`force=False`).
`create_drawing_pack`'s compiler (`solidworks_mcp/pack/compiler.py`) already
places a forced rebuild between the view-insertion phase and the annotation
phase, and again between the table phase and the table-update/balloon phase,
specifically because those values would otherwise be read stale. If you're
calling the individual primitives yourself instead of `create_drawing_pack`
(see [`docs/DRAWING_PACKS.md`](DRAWING_PACKS.md) for when to prefer one over
the other) and a dimension, BOM quantity, or balloon number looks wrong right
after you set it up, call `rebuild_document` before reading it back rather
than assuming the tool is broken.

## Tools referenced in this document

<!-- registered-tools:start -->
`get_capabilities`, `connect_solidworks`, `new_drawing_from_template`,
`open_document`, `save_document`, `save_drawing`, `rebuild_document`,
`create_drawing_pack`.
<!-- registered-tools:end -->
