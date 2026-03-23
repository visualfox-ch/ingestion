#!/usr/bin/env python3
"""Validate mandatory Subagent & Docs evidence fields in task files.

Rules:
- Only checks task files matching tasks/T-*.md.
- Only enforces files that contain the section
  '## Subagent & Docs Evidence (Mandatory)'.
- For enforced files, required fields must be present and non-empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

SECTION_HEADER = "## Subagent & Docs Evidence (Mandatory)"

# Top-level fields in mandatory section
TOP_LEVEL_FIELDS = [
    "- Subagent pattern used (fan-out/fan-in | single-agent | n/a)",
    "- Assumptions (needs runtime verification)",
]

# Nested fields under "Verified by docs"
VERIFIED_DOCS_FIELDS = [
    "- Source(s)",
    "- Claim(s) verified",
]

# Nested fields under KPI snapshot
KPI_FIELDS = [
    "- Rework rate",
    "- Deploy failure/retry rate",
    "- Time-to-root-cause",
    "- Regression count",
]


def find_section_lines(lines: list[str]) -> tuple[int, int] | None:
    start_idx = -1
    for idx, line in enumerate(lines):
        if line.strip() == SECTION_HEADER:
            start_idx = idx
            break
    if start_idx < 0:
        return None

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break

    return start_idx, end_idx


def field_value(section_lines: list[str], field_prefix: str) -> tuple[str | None, int | None]:
    """Return (value, line_offset_in_section).

    Accepts either:
    - an inline value on the same line, or
    - one or more indented follow-up lines beneath the field.
    """
    pattern = re.compile(rf"^\s*{re.escape(field_prefix)}\s*:\s*(.*)$")
    for offset, line in enumerate(section_lines):
        match = pattern.match(line)
        if match:
            inline_value = match.group(1).strip()
            if inline_value:
                return inline_value, offset

            base_indent = len(line) - len(line.lstrip(" "))
            nested_values: list[str] = []
            for nested_line in section_lines[offset + 1 :]:
                if not nested_line.strip():
                    continue
                if nested_line.startswith("## "):
                    break
                nested_indent = len(nested_line) - len(nested_line.lstrip(" "))
                if nested_indent <= base_indent and re.match(r"^\s*-\s", nested_line):
                    break
                if nested_indent <= base_indent:
                    break
                nested_values.append(nested_line.strip())

            if nested_values:
                return " ".join(nested_values), offset

            return "", offset
    return None, None


def lint_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    section_bounds = find_section_lines(lines)
    if section_bounds is None:
        return []

    start_idx, end_idx = section_bounds
    section_lines = lines[start_idx:end_idx]
    issues: list[str] = []

    def add_missing_or_empty(field_name: str, line_no: int | None) -> None:
        if line_no is None:
            issues.append(f"missing field: {field_name}")
        else:
            issues.append(f"empty field: {field_name} (line {start_idx + line_no + 1})")

    for field in TOP_LEVEL_FIELDS:
        value, line_no = field_value(section_lines, field)
        if value is None:
            add_missing_or_empty(field, None)
        elif value == "":
            add_missing_or_empty(field, line_no)

    for field in VERIFIED_DOCS_FIELDS:
        value, line_no = field_value(section_lines, field)
        if value is None:
            add_missing_or_empty(field, None)
        elif value == "":
            add_missing_or_empty(field, line_no)

    for field in KPI_FIELDS:
        value, line_no = field_value(section_lines, field)
        if value is None:
            add_missing_or_empty(field, None)
        elif value == "":
            add_missing_or_empty(field, line_no)

    return issues


def iter_task_files(root: Path, include: Iterable[str]) -> list[Path]:
    if include:
        return [root / rel for rel in include]
    return sorted((root / "tasks").glob("T-*.md"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint mandatory Subagent & Docs evidence fields in task files.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Optional task file paths relative to repo root (for focused checks).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    task_files = iter_task_files(repo_root, args.files)

    enforced_count = 0
    failed = False

    for file_path in task_files:
        if not file_path.exists() or not file_path.is_file():
            continue

        text = file_path.read_text(encoding="utf-8")
        if SECTION_HEADER not in text:
            continue

        enforced_count += 1
        issues = lint_file(file_path)
        if issues:
            failed = True
            rel = file_path.relative_to(repo_root)
            print(f"ERROR: {rel}")
            for issue in issues:
                print(f"  - {issue}")

    if failed:
        print()
        print("Task evidence lint failed.")
        print("Fill mandatory fields in '## Subagent & Docs Evidence (Mandatory)'.")
        return 1

    print(f"OK: task evidence lint passed (checked {enforced_count} task file(s) with mandatory section)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
