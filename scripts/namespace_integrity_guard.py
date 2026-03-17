#!/usr/bin/env python3
"""Namespace integrity guard for scope migration.

Purpose:
- Prevent silent namespace data loss during namespace->scope migration.
- Snapshot namespace non-null counts per table.
- Verify that namespace counts did not decrease unexpectedly.

Usage:
  python3 scripts/namespace_integrity_guard.py snapshot
  python3 scripts/namespace_integrity_guard.py verify
  python3 scripts/namespace_integrity_guard.py verify --snapshot-file /path/to/file.json

Exit codes:
  0 = OK
  1 = Verification failed (potential data loss)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2

TABLES: List[str] = [
    "conversation",
    "decision_logs",
    "learned_facts",
    "memory_facts_layered",
    "upload_queue",
    "interaction_quality",
    "prompt_fragment",
    "hygiene_baselines",
]

DEFAULT_SNAPSHOT_FILE = "data/namespace_integrity_snapshot.json"


@dataclass
class TableCounts:
    table: str
    total_rows: int
    namespace_nonnull_rows: int
    namespace_null_rows: int


def get_db_conn():
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ.get("POSTGRES_DB", "jarvis"),
        user=os.environ.get("POSTGRES_USER", "jarvis"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


def collect_counts(conn) -> Dict[str, TableCounts]:
    out: Dict[str, TableCounts] = {}
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(
                f"SELECT COUNT(*), COUNT(namespace) FROM {table}"  # noqa: S608
            )
            total, ns_nonnull = cur.fetchone()
            out[table] = TableCounts(
                table=table,
                total_rows=int(total),
                namespace_nonnull_rows=int(ns_nonnull),
                namespace_null_rows=int(total - ns_nonnull),
            )
    return out


def load_snapshot(path: Path) -> Dict[str, TableCounts]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("tables", [])
    return {
        row["table"]: TableCounts(
            table=row["table"],
            total_rows=int(row["total_rows"]),
            namespace_nonnull_rows=int(row["namespace_nonnull_rows"]),
            namespace_null_rows=int(row["namespace_null_rows"]),
        )
        for row in rows
    }


def write_snapshot(path: Path, counts: Dict[str, TableCounts]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": [asdict(counts[t]) for t in TABLES],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def verify_counts(
    baseline: Dict[str, TableCounts],
    current: Dict[str, TableCounts],
) -> Tuple[bool, List[str]]:
    problems: List[str] = []
    for table in TABLES:
        b = baseline.get(table)
        c = current.get(table)
        if b is None or c is None:
            problems.append(f"{table}: missing from snapshot/current data")
            continue

        # Hard invariant: namespace non-null rows must not decrease.
        if c.namespace_nonnull_rows < b.namespace_nonnull_rows:
            problems.append(
                f"{table}: namespace_nonnull decreased "
                f"{b.namespace_nonnull_rows} -> {c.namespace_nonnull_rows}"
            )

        # Soft signal: total row count decrease can also indicate unexpected deletion.
        if c.total_rows < b.total_rows:
            problems.append(
                f"{table}: total_rows decreased {b.total_rows} -> {c.total_rows}"
            )

    return (len(problems) == 0, problems)


def print_table(title: str, counts: Dict[str, TableCounts]) -> None:
    print(title)
    print("table,total,namespace_nonnull,namespace_null")
    for table in TABLES:
        c = counts[table]
        print(f"{c.table},{c.total_rows},{c.namespace_nonnull_rows},{c.namespace_null_rows}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Namespace integrity guard")
    parser.add_argument("command", choices=["snapshot", "verify"])
    parser.add_argument("--snapshot-file", default=DEFAULT_SNAPSHOT_FILE)
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot_file)

    conn = get_db_conn()
    try:
        current = collect_counts(conn)
    finally:
        conn.close()

    if args.command == "snapshot":
        write_snapshot(snapshot_path, current)
        print_table("SNAPSHOT_WRITTEN", current)
        print(f"snapshot_file={snapshot_path}")
        return 0

    if not snapshot_path.exists():
        print(
            f"ERROR: snapshot file not found: {snapshot_path}. Run 'snapshot' first.",
            file=sys.stderr,
        )
        return 1

    baseline = load_snapshot(snapshot_path)
    ok, problems = verify_counts(baseline, current)

    print_table("VERIFY_CURRENT", current)
    if ok:
        print("VERIFY_OK: namespace integrity preserved")
        return 0

    print("VERIFY_FAILED: potential namespace data loss detected", file=sys.stderr)
    for p in problems:
        print(f" - {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
