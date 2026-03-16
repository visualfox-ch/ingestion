#!/usr/bin/env python3
"""
Refresh CAPABILITIES_STATUS.md with an auto-generated inventory snapshot.

Lean by design:
- Parse repo files (no runtime deps).
- Update only a bounded section with markers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CAP_FILE = ROOT / "CAPABILITIES_STATUS.md"
TOOLS_FILE = ROOT / "app" / "tools.py"
MAIN_FILE = ROOT / "app" / "main.py"
CONFIG_FILE = ROOT / "app" / "jarvis_config.py"
CONNECTORS_DIR = ROOT / "app" / "connectors"

AUTO_START = "<!-- AUTO-INVENTORY START -->"
AUTO_END = "<!-- AUTO-INVENTORY END -->"


@dataclass(frozen=True)
class Inventory:
    tools: int
    endpoints_total: int
    endpoints_by_method: dict[str, int]
    connectors: list[str]
    namespaces: list[str]


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8")


def _count_tools() -> int:
    text = _read_text(TOOLS_FILE)
    return len(re.findall(r"^def tool_", text, flags=re.MULTILINE))


def _endpoint_inventory() -> tuple[int, dict[str, int]]:
    text = _read_text(MAIN_FILE)
    matches = re.findall(
        r"@app\.(get|post|put|delete|patch|options|head)\(\"([^\"]+)\"",
        text,
        flags=re.IGNORECASE,
    )
    endpoints = {(m.lower(), p) for m, p in matches}
    by_method: dict[str, int] = {}
    for method, _path in endpoints:
        by_method[method] = by_method.get(method, 0) + 1
    return len(endpoints), dict(sorted(by_method.items()))


def _list_connectors() -> list[str]:
    if not CONNECTORS_DIR.exists():
        return []
    items = []
    for path in CONNECTORS_DIR.glob("*.py"):
        if path.name in ("__init__.py", "registry.py"):
            continue
        items.append(path.stem)
    return sorted(items)


def _extract_namespaces() -> list[str]:
    text = _read_text(CONFIG_FILE)
    names = []
    for key in ("DEFAULT_NAMESPACE", "WORK_NAMESPACE", "SYSTEM_NAMESPACE", "COMMS_NAMESPACE"):
        match = re.search(rf"^{key}\s*=\s*\"([^\"]+)\"", text, flags=re.MULTILINE)
        if match:
            names.append(match.group(1))
    return names


def build_inventory() -> Inventory:
    tools = _count_tools()
    endpoints_total, endpoints_by_method = _endpoint_inventory()
    connectors = _list_connectors()
    namespaces = _extract_namespaces()
    return Inventory(
        tools=tools,
        endpoints_total=endpoints_total,
        endpoints_by_method=endpoints_by_method,
        connectors=connectors,
        namespaces=namespaces,
    )


def _render_inventory(inv: Inventory, stamp: str) -> str:
    methods = ", ".join(f"{k.upper()}={v}" for k, v in inv.endpoints_by_method.items())
    connectors = ", ".join(inv.connectors) if inv.connectors else "none"
    namespaces = ", ".join(inv.namespaces) if inv.namespaces else "unknown"
    return "\n".join(
        [
            AUTO_START,
            f"### Auto Inventory Snapshot ({stamp} UTC)",
            f"- Tools: {inv.tools}",
            f"- API endpoints: {inv.endpoints_total} ({methods})",
            f"- Connectors: {connectors}",
            f"- Namespaces: {namespaces}",
            AUTO_END,
        ]
    )


def _update_current_capabilities_date(text: str, date_str: str) -> str:
    return re.sub(
        r"^## Current Capabilities \(\d{4}-\d{2}-\d{2}\)",
        f"## Current Capabilities ({date_str})",
        text,
        flags=re.MULTILINE,
    )


def _inject_inventory(text: str, inventory_block: str) -> str:
    if AUTO_START in text and AUTO_END in text:
        pattern = re.compile(
            rf"{re.escape(AUTO_START)}.*?{re.escape(AUTO_END)}",
            flags=re.DOTALL,
        )
        return pattern.sub(inventory_block, text)

    # Insert after "## Current Capabilities (...)" heading
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("## Current Capabilities "):
            insert_at = idx + 1
            lines[insert_at:insert_at] = ["", inventory_block, ""]
            return "\n".join(lines)
    # Fallback: append to end
    return text + "\n\n" + inventory_block + "\n"


def main() -> int:
    if not CAP_FILE.exists():
        print(f"❌ Missing CAPABILITIES_STATUS.md at {CAP_FILE}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d %H:%M")

    inv = build_inventory()
    inventory_block = _render_inventory(inv, stamp)

    text = _read_text(CAP_FILE)
    text = _update_current_capabilities_date(text, date_str)
    text = _inject_inventory(text, inventory_block)

    CAP_FILE.write_text(text, encoding="utf-8")
    print(f"✅ Updated {CAP_FILE.name} with auto-inventory snapshot ({stamp} UTC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
