#!/usr/bin/env python3
"""
Generate a lean feedback-review snapshot from JSONL logs.
Safe to run in repo or ingestion container.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse
import json
import sys


LOG_DIR_CANDIDATES = [
    Path("/brain/system/logs"),
    Path("/volume1/BRAIN/system/logs"),
]


@dataclass(frozen=True)
class LogStats:
    name: str
    count: int
    last_ts: str | None
    path: Path | None


def _find_log(name: str) -> Path | None:
    for base in LOG_DIR_CANDIDATES:
        path = base / name
        if path.exists():
            return path
    return None


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _extract_ts(payload: dict) -> datetime | None:
    for key in ("ts", "timestamp", "created_at", "ingest_ts", "event_ts"):
        if key in payload:
            return _parse_ts(str(payload.get(key)))
    return None


def _log_stats(name: str, since: datetime | None) -> LogStats:
    path = _find_log(name)
    if not path:
        return LogStats(name=name, count=0, last_ts=None, path=None)

    count = 0
    last_ts: datetime | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _extract_ts(payload)
            if since and ts and ts < since:
                continue
            count += 1
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts

    last_ts_str = last_ts.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if last_ts else None
    return LogStats(name=name, count=count, last_ts=last_ts_str, path=path)


def render_markdown(stats: list[LogStats], since_label: str) -> str:
    lines = [
        "# Feedback Review Snapshot",
        "",
        f"**Window:** {since_label}",
        f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')}",
        "",
        "## Signals",
    ]
    for stat in stats:
        path = str(stat.path) if stat.path else "not found"
        last_ts = stat.last_ts or "n/a"
        lines.append(f"- `{stat.name}`: {stat.count} entries | last_ts: {last_ts} | path: {path}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    parser.add_argument("--out", type=Path, default=None, help="Write markdown to file (optional)")
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    since_label = f"last {args.days} days"

    logs = [
        "feedback_protocol.jsonl",
        "tool_tests.jsonl",
        "capability_reports.jsonl",
    ]

    stats = [_log_stats(name, since) for name in logs]
    markdown = render_markdown(stats, since_label)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"✅ Wrote snapshot to {args.out}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
