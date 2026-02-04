#!/usr/bin/env python3
"""Backfill timestamps to Zurich timezone (CET/CEST) for legacy data.

Default: dry-run. Use --apply to write changes.

Targets:
- Postgres tables (if available via postgres_state.get_conn)
- SQLite memory store facts (JARVIS_MEMORY_DB)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Tuple

import psycopg2

from app.postgres_state import get_conn

DEFAULT_OFFSET_HOURS = 1

POSTGRES_TABLES: List[Tuple[str, List[str]]] = [
    ("decision_log", ["created_at", "updated_at"]),
    ("session_lessons", ["first_seen", "last_seen", "created_at"]),
    ("cross_session_patterns", ["last_detected", "created_at"]),
    ("jarvis_suggestions", ["created_at", "followup_at", "outcome_recorded_at"]),
    ("user_activity_event", ["event_timestamp", "created_at"]),
]

SQLITE_FACTS_COLUMNS = ["created_at", "updated_at", "last_accessed"]


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _shift_iso(ts: str, offset_hours: int) -> str | None:
    parsed = _parse_iso(ts)
    if not parsed:
        return None
    return (parsed + timedelta(hours=offset_hours)).isoformat(timespec="seconds")


def backfill_postgres(offset_hours: int, apply: bool) -> None:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for table, columns in POSTGRES_TABLES:
                    for col in columns:
                        try:
                            if apply:
                                cur.execute(
                                    f"UPDATE {table} SET {col} = {col} + INTERVAL '%s hours' WHERE {col} IS NOT NULL",
                                    (offset_hours,)
                                )
                            else:
                                cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col} IS NOT NULL")
                                row = cur.fetchone() or {}
                                count = row.get("cnt", 0)
                                print(f"[DRY-RUN] {table}.{col}: {count} rows to shift +{offset_hours}h")
                        except psycopg2.Error as exc:
                            conn.rollback()
                            print(f"[SKIP] {table}.{col}: {exc.pgerror or exc}")
    except Exception as exc:
        print(f"[SKIP] Postgres backfill failed: {exc}")


def backfill_sqlite(offset_hours: int, apply: bool) -> None:
    db_path = os.environ.get("JARVIS_MEMORY_DB", "/brain/system/state/jarvis_memory.db")
    if not os.path.exists(db_path):
        print(f"[SKIP] SQLite DB not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT id, created_at, updated_at, last_accessed FROM facts")
        rows = cur.fetchall()
        if not apply:
            print(f"[DRY-RUN] facts: {len(rows)} rows to consider")
            return

        for row in rows:
            updates = {}
            for col in SQLITE_FACTS_COLUMNS:
                value = row[col]
                shifted = _shift_iso(value, offset_hours) if value else None
                if shifted and shifted != value:
                    updates[col] = shifted
            if updates:
                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                params = list(updates.values()) + [row["id"]]
                cur.execute(f"UPDATE facts SET {set_clause} WHERE id = ?", params)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill timestamps to Zurich time")
    parser.add_argument("--offset-hours", type=int, default=DEFAULT_OFFSET_HOURS)
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--skip-postgres", action="store_true", help="Skip Postgres backfill")
    parser.add_argument("--skip-sqlite", action="store_true", help="Skip SQLite backfill")
    args = parser.parse_args()

    print(f"Timezone backfill: offset +{args.offset_hours}h | apply={args.apply}")
    if not args.skip_postgres:
        backfill_postgres(args.offset_hours, args.apply)
    if not args.skip_sqlite:
        backfill_sqlite(args.offset_hours, args.apply)
