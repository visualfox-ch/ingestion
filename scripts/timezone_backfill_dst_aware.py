#!/usr/bin/env python3
"""DST-aware timezone backfill for Phase 2.

Phase 1 applied fixed +1h offset. This script converts those timestamps
to true Europe/Zurich timezone (CET/CEST) with DST awareness.

Strategy:
- Treat current timestamps as UTC (after removing the +1h offset from Phase 1)
- Reapply as true Zurich timezone (which handles DST)
- Postgres: Use AT TIME ZONE clauses
- SQLite: Use pytz for tz-aware conversion

Default: dry-run. Use --apply to write changes.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple

import psycopg2
import pytz

from app.postgres_state import get_conn

ZURICH_TZ = pytz.timezone("Europe/Zurich")

POSTGRES_TABLES: List[Tuple[str, List[str]]] = [
    ("decision_log", ["created_at", "updated_at"]),
    ("session_lessons", ["first_seen", "last_seen", "created_at"]),
    ("cross_session_patterns", ["last_detected", "created_at"]),
    ("jarvis_suggestions", ["created_at", "followup_at", "outcome_recorded_at"]),
    ("user_activity_event", ["event_timestamp", "created_at"]),
]

SQLITE_FACTS_COLUMNS = ["created_at", "updated_at", "last_accessed"]


def _parse_iso_naive(ts: str) -> datetime | None:
    """Parse ISO timestamp (assumed naive after Phase 1 +1h shift)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _to_zurich_aware(naive_dt: datetime) -> datetime | None:
    """
    Convert a naive datetime (already +1h shifted) to true Zurich timezone.
    
    Logic:
    1. The timestamp is in UTC+1 (CET) after Phase 1
    2. Revert to UTC: subtract 1 hour
    3. Localize as UTC
    4. Convert to Europe/Zurich (handles DST)
    """
    if not naive_dt:
        return None
    try:
        # Assume it's in UTC+1, revert to UTC
        utc_dt = datetime(
            year=naive_dt.year,
            month=naive_dt.month,
            day=naive_dt.day,
            hour=naive_dt.hour - 1,
            minute=naive_dt.minute,
            second=naive_dt.second,
            microsecond=naive_dt.microsecond,
            tzinfo=timezone.utc
        )
        # Convert UTC to Zurich (handles DST)
        zurich_dt = utc_dt.astimezone(ZURICH_TZ)
        return zurich_dt
    except Exception as e:
        print(f"[WARN] Failed to convert {naive_dt}: {e}")
        return None


def _iso_from_aware(aware_dt: datetime) -> str:
    """Convert aware datetime to ISO string with timezone info."""
    return aware_dt.isoformat(timespec="seconds")


def backfill_postgres_dst(apply: bool) -> None:
    """Postgres backfill with DST awareness using AT TIME ZONE."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for table, columns in POSTGRES_TABLES:
                    for col in columns:
                        try:
                            if apply:
                                # SQL: treat as UTC+1, convert to Europe/Zurich
                                # Then cast to timestamp (naive) for storage
                                sql = f"""
                                    UPDATE {table}
                                    SET {col} = (
                                        {col}::text::timestamp AT TIME ZONE 'UTC'
                                        AT TIME ZONE 'Europe/Zurich'
                                    )::timestamp
                                    WHERE {col} IS NOT NULL
                                """
                                cur.execute(sql)
                                affected = cur.rowcount
                                print(f"[APPLY] {table}.{col}: {affected} rows updated with DST-aware conversion")
                            else:
                                # Dry-run: show how many rows would be affected
                                cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col} IS NOT NULL")
                                row = cur.fetchone() or {}
                                count = row.get("cnt", 0) if hasattr(row, "get") else row[0]
                                print(f"[DRY-RUN] {table}.{col}: {count} rows to DST-convert")
                        except psycopg2.Error as exc:
                            conn.rollback()
                            pgerror = exc.pgerror if hasattr(exc, 'pgerror') else str(exc)
                            print(f"[SKIP] {table}.{col}: {pgerror}")
    except Exception as exc:
        print(f"[SKIP] Postgres backfill failed: {exc}")


def backfill_sqlite_dst(apply: bool) -> None:
    """SQLite backfill with DST awareness using pytz."""
    db_path = os.environ.get("JARVIS_MEMORY_DB", "/brain/system/state/jarvis_memory.db")
    if not os.path.exists(db_path):
        print(f"[SKIP] SQLite DB not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id, created_at, updated_at, last_accessed FROM facts")
            rows = cur.fetchall()
            
            if not apply:
                affected_count = 0
                for row in rows:
                    for col in SQLITE_FACTS_COLUMNS:
                        value = row[col]
                        parsed = _parse_iso_naive(value)
                        if parsed and _to_zurich_aware(parsed) is not None:
                            affected_count += 1
                print(f"[DRY-RUN] facts: ~{affected_count} values to DST-convert (from {len(rows)} rows)")
                return

            # Apply phase
            for row in rows:
                updates = {}
                for col in SQLITE_FACTS_COLUMNS:
                    value = row[col]
                    parsed = _parse_iso_naive(value)
                    if parsed:
                        aware = _to_zurich_aware(parsed)
                        if aware:
                            iso_str = _iso_from_aware(aware)
                            if iso_str != value:
                                updates[col] = iso_str
                
                if updates:
                    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                    params = list(updates.values()) + [row["id"]]
                    cur.execute(f"UPDATE facts SET {set_clause} WHERE id = ?", params)
            
            print(f"[APPLY] facts: {len(rows)} rows processed for DST-aware conversion")
    except sqlite3.Error as e:
        print(f"[SKIP] SQLite backfill failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DST-aware timezone backfill (Phase 2)",
        epilog="Default: dry-run. Use --apply to write changes."
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--skip-postgres", action="store_true", help="Skip Postgres backfill")
    parser.add_argument("--skip-sqlite", action="store_true", help="Skip SQLite backfill")
    args = parser.parse_args()

    import sys
    print("=" * 70)
    print(f"Phase 2: DST-aware timezone backfill | apply={args.apply}")
    print("=" * 70)
    
    if not args.skip_postgres:
        print("\n[POSTGRES]")
        backfill_postgres_dst(args.apply)
    
    if not args.skip_sqlite:
        print("\n[SQLITE]")
        backfill_sqlite_dst(args.apply)
    
    print("\n" + "=" * 70)
    if args.apply:
        print("Phase 2 backfill APPLIED. Review logs for details.")
        sys.exit(0)
    else:
        print("Phase 2 dry-run complete. Re-run with --apply to execute.")
        sys.exit(0)
    print("=" * 70)
