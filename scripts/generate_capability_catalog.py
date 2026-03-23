#!/usr/bin/env python3
"""Generate docs/CAPABILITY_CATALOG.md from docs/CAPABILITIES.json.

This script keeps the catalog aligned with runtime-exported capabilities,
with a compact structure to avoid manual doc drift.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _resolve_existing_path(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    names = "\n- ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"No candidate file found. Tried:\n- {names}")


def _category_for_tool(name: str) -> str:
    lname = name.lower()

    if any(k in lname for k in ["search", "knowledge", "gmail", "calendar", "web"]):
        return "Knowledge and Retrieval"
    if any(k in lname for k in ["remember", "recall", "memory", "person_context"]):
        return "Memory and Context"
    if any(k in lname for k in ["project", "task", "thread", "followup", "prioritize"]):
        return "Projects and Tasks"
    if any(k in lname for k in ["agent", "delegation", "coordination", "handoff", "context_pool"]):
        return "Agent Coordination"
    if any(k in lname for k in ["tool_", "tool_chain", "routing", "autonomy", "registry"]):
        return "Tooling and Autonomy"
    if any(k in lname for k in ["health", "metrics", "prometheus", "dashboard", "diagnostics", "validation"]):
        return "Health and Observability"
    if any(k in lname for k in ["read_project_file", "write_project_file", "read_own_code", "source_files"]):
        return "File and Source Access"
    return "Other"


def _render(caps: dict) -> str:
    tools = [t for t in caps.get("tools", []) if isinstance(t, dict)]
    tools_sorted = sorted(tools, key=lambda t: str(t.get("name", "")))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for tool in tools_sorted:
        name = str(tool.get("name", "unknown"))
        grouped[_category_for_tool(name)].append(tool)

    active_count = sum(1 for t in tools_sorted if str(t.get("status", "")).lower() == "active")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines: list[str] = []
    lines.append("# CAPABILITY CATALOG")
    lines.append("")
    lines.append("Generated file. Do not edit manually.")
    lines.append("")
    lines.append("Canonical Source: docs/CAPABILITIES.json")
    lines.append("")
    lines.append(f"Version: {caps.get('version', 'unknown')}")
    lines.append(f"Build timestamp: {caps.get('build_timestamp', 'unknown')}")
    lines.append(f"Generated at: {generated_at}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"Total: {len(tools_sorted)} active tools")
    lines.append(f"Active status entries: {active_count}")
    lines.append("")

    lines.append("## Categories")
    lines.append("")
    for category in sorted(grouped.keys()):
        entries = grouped[category]
        lines.append(f"### {category} ({len(entries)})")
        lines.append("")
        for tool in entries:
            name = str(tool.get("name", "unknown"))
            description = str(tool.get("description", "")).strip()
            if not description:
                description = "No description provided."
            lines.append(f"- {name}: {description}")
        lines.append("")

    lines.append("## Hard Limits")
    lines.append("")
    lines.append("- This catalog reflects declared capabilities, not runtime permissions.")
    lines.append("- Safety, approval, and deployment constraints are defined in policies and runbooks.")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    docker_root = Path(__file__).resolve().parents[1]
    system_root = docker_root.parent

    capabilities_path = _resolve_existing_path(
        [
            docker_root / "docs" / "CAPABILITIES.json",
            system_root / "docs" / "CAPABILITIES.json",
        ]
    )
    catalog_candidates = [
        docker_root / "docs" / "CAPABILITY_CATALOG.md",
        system_root / "docs" / "CAPABILITY_CATALOG.md",
    ]
    catalog_path = next((path for path in catalog_candidates if path.exists()), catalog_candidates[0])
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    with capabilities_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    rendered = _render(payload)
    catalog_path.write_text(rendered, encoding="utf-8")

    print(f"Generated {catalog_path} from {capabilities_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
