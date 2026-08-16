#!/usr/bin/env python3
"""Validate docs/api/*.md dossiers against the format in docs/api/README.md.

Fails (exit 1) if a dossier is missing required front matter, a method record
(H3 heading) is missing one of the RECORD_CHECKS fields below, or a file
documents fewer method records than the `min_methods` count declared in its own
front matter.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "api"

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
RECORD_HEADING_RE = re.compile(r"^### +(.+?)\s*$", re.M)

# Every per-record rule lives here as data, so adding or relaxing a required
# field is a row edit rather than a new regex + branch + message string. Order
# is the order the fields appear in a record (see docs/api/_TEMPLATE.md).
# **Gotchas:** is deliberately absent: the format asks for it, but a record with
# genuinely nothing to warn about is legitimate, so it stays reviewer-enforced.
RECORD_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\*\*Signature:?\*\*\s*\n```"),
        "missing **Signature:** fenced code block",
    ),
    (
        re.compile(r"^\|.*\|\s*\n\|[ \t]*:?-{2,}.*\|\s*$", re.M),
        "missing Parameter table (markdown table with header separator)",
    ),
    (
        re.compile(r"^\*\*Returns:?\*\*", re.M),
        "missing **Returns:** line",
    ),
    (
        re.compile(r"^\*\*Prior selection required:?\*\*", re.M),
        "missing **Prior selection required:** line",
    ),
    (
        # The URL has to sit inside the Source URL(s) section, i.e. before the
        # next bold field label.
        re.compile(r"\*\*Source URL\(s\):?\*\*(?:(?!\n\*\*).)*?https?://\S+", re.S),
        "missing **Source URL(s):** with at least one http(s) URL",
    ),
    (
        re.compile(r"\*\*status:?\*\*\s*(verified|unverified)\b"),
        "missing **status:** verified|unverified line",
    ),
]


def is_dossier(path: Path) -> bool:
    """True for files the validator should check.

    `README.md` is prose about the format and `_`-prefixed files are scaffolding
    (`_TEMPLATE.md` today) — the underscore prefix is the general opt-out, so a
    second scaffold file needs no change here. Keep in sync with the prose in
    docs/api/README.md.
    """
    return path.name != "README.md" and not path.name.startswith("_")


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


def check_record(body: str) -> list[str]:
    return [message for pattern, message in RECORD_CHECKS if not pattern.search(body)]


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")

    front_matter = parse_front_matter(text)
    if front_matter is None:
        return [f"{path}: missing required YAML front matter (--- ... ---) with 'min_methods'"]

    errors = []
    records = split_records(text)
    for heading, body in records:
        errors.extend(f"{path}: record '{heading}': {e}" for e in check_record(body))

    min_methods = front_matter.get("min_methods")
    if min_methods is None:
        errors.append(f"{path}: front matter missing required 'min_methods' key")
    elif not min_methods.isdigit():
        errors.append(f"{path}: front matter 'min_methods' is not an integer: {min_methods!r}")
    elif len(records) < int(min_methods):
        errors.append(
            f"{path}: has {len(records)} method record(s), fewer than declared min_methods={min_methods}"
        )

    return errors


def main(docs_dir: Path = DOCS_DIR) -> int:
    if not docs_dir.is_dir():
        print(f"error: {docs_dir} does not exist", file=sys.stderr)
        return 1

    doc_files = sorted(p for p in docs_dir.glob("*.md") if is_dossier(p))

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
