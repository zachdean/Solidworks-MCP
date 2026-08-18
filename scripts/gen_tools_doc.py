#!/usr/bin/env python3
"""Generate docs/TOOLS.md from the tool registry (`solidworks_mcp/tools/registry.py`).

Run with no arguments to (re)write `docs/TOOLS.md`. Run with `--check` to verify the
committed file matches what the registry would generate right now, without writing
anything -- this is what `scripts/check.sh` runs, so a stale `docs/TOOLS.md` fails the
build instead of silently drifting from the code.
"""
from __future__ import annotations

import argparse
import functools
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_API_DIR = REPO_ROOT / "docs" / "api"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "TOOLS.md"

sys.path.insert(0, str(REPO_ROOT))

# An `Interface::Method` (or `Interface::Method2`-style overload) token, as used
# both by tool descriptions (free text) and dossier H3 headings (`### Interface::Method`).
_DOSSIER_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*::[A-Za-z0-9]+\b")


def _slugify(heading: str) -> str:
    """GitHub-flavored-markdown-style anchor slug: lowercase, drop anything that
    isn't a word character/space/hyphen, then turn runs of whitespace into `-`."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def build_dossier_index(docs_api_dir: Path = DOCS_API_DIR) -> Dict[str, Tuple[str, str]]:
    """Map every `Interface::Method` token mentioned in a dossier H3 heading to
    `(relative_path_from_docs, anchor_slug)`, so a tool description mentioning the
    same token can be linked back to where it's actually documented."""
    index: Dict[str, Tuple[str, str]] = {}
    if not docs_api_dir.is_dir():
        return index
    for path in sorted(docs_api_dir.glob("*.md")):
        if path.name == "README.md" or path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^### +(.+?)\s*$", text, re.M):
            heading = match.group(1)
            anchor = _slugify(heading)
            for token in _DOSSIER_TOKEN_RE.findall(heading):
                # First dossier to mention a token wins -- files are walked in a
                # fixed (sorted) order, so this is deterministic across runs.
                index.setdefault(token, (f"api/{path.name}", anchor))
    return index


def find_dossier_refs(description: str, index: Dict[str, Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    """`(token, relative_path, anchor)` for every dossier-indexed token mentioned in
    `description`, in first-seen order with duplicates removed."""
    seen: Dict[str, Tuple[str, str, str]] = {}
    for token in _DOSSIER_TOKEN_RE.findall(description):
        if token in index and token not in seen:
            path, anchor = index[token]
            seen[token] = (token, path, anchor)
    return list(seen.values())


@functools.lru_cache(maxsize=1)
def _default_min_release() -> int:
    """The project-wide version floor as *committed* -- `SolidWorksConfig`'s
    dataclass default, read without consulting the config.json a developer
    may have edited locally. See `render_tool`."""
    from solidworks_mcp.config import SolidWorksConfig
    return SolidWorksConfig.__dataclass_fields__["min_release"].default


def _load_registry():
    """Import the tool registry -- a real package import (not exec-by-path, unlike
    `check_api_docs.py`'s test double), since registering every tool requires the
    whole `solidworks_mcp.tools` package's import machinery."""
    from solidworks_mcp.tools import describe_tools
    return describe_tools()


def render_tool(entry: Dict[str, Any], dossier_index: Dict[str, Tuple[str, str]]) -> str:
    lines = [f"## `{entry['name']}`", "", entry["description"].strip(), ""]
    # Folded against `_default_min_release()` -- the committed dataclass
    # default -- rather than `entry["effective_min_release"]`, which uses
    # the *loaded* `get_config().min_release`. `config.py` reads
    # `solidworks_mcp/config.json` at import, so a developer who lowers the
    # floor locally (the documented way to test against an older install)
    # would otherwise rewrite all 111 of these lines and fail
    # `gen_tools_doc.py --check` for a reason unrelated to their change.
    # A committed, checked-in doc has to depend on committed code only.
    declared = entry["min_release"]
    if declared == 0:
        lines.append("- **Minimum release:** none -- exempt from the version gate")
    else:
        floor = _default_min_release() if declared is None else max(_default_min_release(), declared)
        lines.append(f"- **Minimum release:** SOLIDWORKS {floor}")

    properties = entry["schema"].get("properties") or {}
    required = set(entry["schema"].get("required") or [])
    if not properties:
        lines.append("- **Parameters:** none")
    else:
        lines.append("- **Parameters:**")
        lines.append("")
        lines.append("  | Name | Type | Required | Default |")
        lines.append("  | --- | --- | --- | --- |")
        for pname, prop in properties.items():
            ptype = prop.get("type", "any")
            preq = "yes" if pname in required else "no"
            default = prop.get("default", "")
            lines.append(f"  | `{pname}` | {ptype} | {preq} | {default} |")
        lines.append("")

    refs = find_dossier_refs(entry["description"], dossier_index)
    if refs:
        lines.append("- **Dossier reference:** " + ", ".join(
            f"[`{token}`]({path}#{anchor})" for token, path, anchor in refs
        ))
    else:
        lines.append("- **Dossier reference:** none found in `docs/api/`")

    lines.append("")
    return "\n".join(lines)


def render_doc(tools: List[Dict[str, Any]], dossier_index: Dict[str, Tuple[str, str]]) -> str:
    header = [
        "# SolidWorks MCP Tool Index",
        "",
        "GENERATED by `scripts/gen_tools_doc.py` from the tool registry "
        "(`solidworks_mcp/tools/registry.py`) -- do not hand-edit. Regenerate with "
        "`.venv/bin/python scripts/gen_tools_doc.py` and commit the result; "
        "`scripts/check.sh` runs `gen_tools_doc.py --check` and fails the build if "
        "this file is out of date.",
        "",
        f"{len(tools)} tool(s) registered. Call `get_capabilities` at runtime for "
        "which of these are usable against the currently connected SOLIDWORKS "
        "install.",
        "",
    ]
    body = [render_tool(entry, dossier_index) for entry in tools]
    return "\n".join(header + body).rstrip() + "\n"


def generate() -> str:
    tools = _load_registry()
    dossier_index = build_dossier_index()
    return render_doc(tools, dossier_index)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                         help="verify the output file is up to date; exit 1 if not, without writing")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                         help="path to read/write (default: docs/TOOLS.md)")
    args = parser.parse_args(argv)

    content = generate()

    if args.check:
        if not args.output.exists():
            print(f"error: {args.output} does not exist -- run scripts/gen_tools_doc.py to generate it",
                  file=sys.stderr)
            return 1
        current = args.output.read_text(encoding="utf-8")
        if current != content:
            print(f"error: {args.output} is stale -- run scripts/gen_tools_doc.py and commit the result",
                  file=sys.stderr)
            return 1
        print(f"ok: {args.output} is up to date")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
