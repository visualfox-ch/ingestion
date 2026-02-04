#!/usr/bin/env python3
"""Update CAPABILITIES_STATUS.md with latest date and monitoring endpoints.

Idempotent: updates date header, ensures monitoring bullets exist, and
adds a recent change note if missing.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

STATUS_PATH = Path("/Volumes/BRAIN/system/docker/CAPABILITIES_STATUS.md")

NEW_MONITORING_BULLETS = [
    "- **Monitoring (System):** ✅ `/monitoring/system`",
    "- **Monitoring (Services):** ✅ `/monitoring/services`",
    "- **Monitoring (Performance):** ✅ `/monitoring/performance`",
    "- **Monitoring (Errors):** ✅ `/monitoring/errors` (min_level, limit)",
    "- **Monitoring (Logs):** ✅ `/monitoring/logs` (allowlisted, redacted, rate‑limited, format=lines)",
]

RECENT_CHANGE_LINE = "- Monitoring Access endpoints + secure log tail (redaction, rate‑limit, filters)."


def update_date(lines: list[str]) -> list[str]:
    updated = []
    today = datetime.utcnow().strftime("%Y‑%m‑%d")
    for line in lines:
        if line.startswith("## Current Capabilities ("):
            updated.append(f"## Current Capabilities ({today})\n")
        else:
            updated.append(line)
    return updated


def ensure_monitoring_bullets(lines: list[str]) -> list[str]:
    out = []
    in_observability = False
    inserted = False
    existing = set(line.strip() for line in lines)

    for idx, line in enumerate(lines):
        out.append(line)
        if line.strip() == "### 4) Observability & Reporting":
            in_observability = True
            continue

        if in_observability and line.startswith("---"):
            if not inserted:
                for bullet in NEW_MONITORING_BULLETS:
                    if bullet not in existing:
                        out.insert(len(out) - 1, bullet + "\n")
                inserted = True
            in_observability = False

    if not inserted and in_observability:
        for bullet in NEW_MONITORING_BULLETS:
            if bullet not in existing:
                out.append(bullet + "\n")

    return out


def ensure_recent_change(lines: list[str]) -> list[str]:
    out = []
    in_recent = False
    added = False

    for line in lines:
        out.append(line)
        if line.strip() == "## Recent Changes (Last 7 days)":
            in_recent = True
            continue

        if in_recent and line.strip() == "":
            if RECENT_CHANGE_LINE not in "".join(lines):
                out.insert(len(out) - 1, RECENT_CHANGE_LINE + "\n")
            in_recent = False
            added = True

    if not added and RECENT_CHANGE_LINE not in "".join(lines):
        out.append("\n" + RECENT_CHANGE_LINE + "\n")

    return out


def main() -> int:
    if not STATUS_PATH.exists():
        return 1

    lines = STATUS_PATH.read_text().splitlines(keepends=True)
    lines = update_date(lines)
    lines = ensure_monitoring_bullets(lines)
    lines = ensure_recent_change(lines)

    STATUS_PATH.write_text("".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
