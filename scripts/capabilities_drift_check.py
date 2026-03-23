#!/usr/bin/env python3
"""Minimal drift check between CAPABILITIES.json and CAPABILITY_CATALOG.md.

Default mode is warn-only (exit 0 on drift). Use --strict to fail on drift.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CATALOG_TOTAL_RE = re.compile(r"Total:\s*(\d+)\s+active tools", re.IGNORECASE)


def _normalize_tool_name(name: str) -> str:
    normalized = str(name).strip()
    if normalized.startswith("tool_"):
        return normalized[5:]
    return normalized


def _resolve_existing_path(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    names = "\n- ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"No candidate file found. Tried:\n- {names}")


def _load_capabilities_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise ValueError(f"Invalid schema in {path}: expected 'tools' list")

    return len(tools)


def _load_capability_tool_names(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise ValueError(f"Invalid schema in {path}: expected 'tools' list")

    return {
        str(tool.get("name"))
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    }


def _load_runtime_tool_names(repo_root: Path) -> tuple[set[str] | None, str | None]:
    try:
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from app.tools import get_tool_definitions  # pylint: disable=import-error

        names = {
            str(tool.get("name"))
            for tool in get_tool_definitions()
            if isinstance(tool, dict) and tool.get("name")
        }
        return names, None
    except Exception as exc:
        return None, str(exc)


def _load_catalog_claimed_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    match = CATALOG_TOTAL_RE.search(text)
    if not match:
        raise ValueError(
            f"Could not find catalog total in {path}. Expected line like: 'Total: <N> active tools'"
        )
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check capabilities/catalog tool-count drift.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when drift is found")
    args = parser.parse_args()

    docker_root = Path(__file__).resolve().parents[1]
    system_root = docker_root.parent

    capabilities_path = _resolve_existing_path(
        [
            docker_root / "docs" / "CAPABILITIES.json",
            system_root / "docs" / "CAPABILITIES.json",
        ]
    )
    catalog_path = _resolve_existing_path(
        [
            docker_root / "docs" / "CAPABILITY_CATALOG.md",
            system_root / "docs" / "CAPABILITY_CATALOG.md",
        ]
    )

    capabilities_count = _load_capabilities_count(capabilities_path)
    capability_tool_names = _load_capability_tool_names(capabilities_path)
    catalog_count = _load_catalog_claimed_count(catalog_path)
    runtime_tool_names, runtime_error = _load_runtime_tool_names(docker_root)

    print("== Capabilities drift check ==")
    print(f"CAPABILITIES count: {capabilities_count} ({capabilities_path})")
    print(f"Catalog claimed count: {catalog_count} ({catalog_path})")

    has_count_drift = capabilities_count != catalog_count
    if has_count_drift:
        print("DRIFT: CAPABILITIES.json and CAPABILITY_CATALOG.md disagree on active tool count")
    else:
        print("OK: no count drift detected")

    if runtime_tool_names is None:
        print(f"WARN: runtime tool-name drift check skipped: {runtime_error}")
        return 1 if args.strict and has_count_drift else 0

    normalized_runtime_names = {_normalize_tool_name(name) for name in runtime_tool_names}
    normalized_capability_names = {_normalize_tool_name(name) for name in capability_tool_names}

    missing_in_runtime = sorted(normalized_capability_names - normalized_runtime_names)
    runtime_extras = sorted(normalized_runtime_names - normalized_capability_names)

    print(f"Runtime tool names (raw): {len(runtime_tool_names)}")
    print(f"Capabilities tool names (raw): {len(capability_tool_names)}")
    print(f"Runtime tool names (normalized): {len(normalized_runtime_names)}")
    print(f"Capabilities tool names (normalized): {len(normalized_capability_names)}")

    has_name_drift = bool(missing_in_runtime)
    if has_name_drift:
        print("DRIFT: CAPABILITIES contract names are missing in runtime")
        print(f"missing_in_runtime_registry: {len(missing_in_runtime)}")
        if missing_in_runtime:
            print("sample_missing_in_runtime_registry:", ", ".join(missing_in_runtime[:10]))
    else:
        print("OK: all CAPABILITIES contract names exist in runtime")

    if runtime_extras:
        print(
            "INFO: runtime has additional tools not listed in CAPABILITIES contract:",
            len(runtime_extras),
        )
        print("sample_runtime_extras:", ", ".join(runtime_extras[:10]))

    if args.strict and (has_count_drift or has_name_drift):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
