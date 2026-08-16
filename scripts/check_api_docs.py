#!/usr/bin/env python3
"""Validate docs/api/*.md dossiers against the format in docs/api/README.md.

Fails (exit 1) if a dossier is missing required front matter, a method record
(H3 heading) is missing its Signature / Parameter table / Source URL(s) /
status line, or a file documents fewer method records than the `min_methods`
count declared in its own front matter.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "api"
EXCLUDED_FILES = {"README.md", "_TEMPLATE.md"}

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
RECORD_HEADING_RE = re.compile(r"^### +(.+?)\s*$", re.M)
SIGNATURE_RE = re.compile(r"\*\*Signature:?\*\*\s*\n```")
PARAM_TABLE_RE = re.compile(r"^\|.*\|\s*\n\|[ \t]*:?-{2,}.*\|\s*$", re.M)
SOURCE_URL_RE = re.compile(r"\*\*Source URL\(s\):?\*\*(.*?)(?=\n\*\*|\Z)", re.S)
URL_RE = re.compile(r"https?://\S+")
STATUS_RE = re.compile(r"\*\*status:?\*\*\s*(verified|unverified)\b")


def parse_front_matter(text: str) -> dict[str, str] | None:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def split_records(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) for each H3 method record in document order."""
    headings = list(RECORD_HEADING_RE.finditer(text))
    records = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        records.append((m.group(1), text[start:end]))
    return records


def check_record(heading: str, body: str) -> list[str]:
    errors = []
    if not SIGNATURE_RE.search(body):
        errors.append(f"record '{heading}': missing **Signature:** fenced code block")
    if not PARAM_TABLE_RE.search(body):
        errors.append(f"record '{heading}': missing Parameter table (markdown table with header separator)")
    source_match = SOURCE_URL_RE.search(body)
    if not source_match or not URL_RE.search(source_match.group(1)):
        errors.append(f"record '{heading}': missing **Source URL(s):** with at least one http(s) URL")
    if not STATUS_RE.search(body):
        errors.append(f"record '{heading}': missing **status:** verified|unverified line")
    return errors


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors = []

    front_matter = parse_front_matter(text)
    if front_matter is None:
        return [f"{path}: missing required YAML front matter (--- ... ---) with 'min_methods'"]
    if "min_methods" not in front_matter:
        errors.append(f"{path}: front matter missing required 'min_methods' key")

    records = split_records(text)
    for heading, body in records:
        errors.extend(f"{path}: {e}" for e in check_record(heading, body))

    if "min_methods" in front_matter:
        try:
            min_methods = int(front_matter["min_methods"])
        except ValueError:
            errors.append(f"{path}: front matter 'min_methods' is not an integer: {front_matter['min_methods']!r}")
        else:
            if len(records) < min_methods:
                errors.append(
                    f"{path}: has {len(records)} method record(s), fewer than declared min_methods={min_methods}"
                )

    return errors


def main() -> int:
    if not DOCS_DIR.is_dir():
        print(f"error: {DOCS_DIR} does not exist", file=sys.stderr)
        return 1

    doc_files = sorted(
        p for p in DOCS_DIR.glob("*.md") if p.name not in EXCLUDED_FILES
    )

    all_errors: list[str] = []
    for path in doc_files:
        all_errors.extend(check_file(path))

    if all_errors:
        for error in all_errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"\n{len(all_errors)} error(s) across {len(doc_files)} dossier file(s)", file=sys.stderr)
        return 1

    print(f"ok: {len(doc_files)} dossier file(s) validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
