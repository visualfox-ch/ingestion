#!/usr/bin/env python3
"""
scope_backfill.py – Phase 3 Scope-Migration Backfill

Liest scope_alias_resolution und füllt scope_org/scope_visibility für alle
namespace-tragenden Tabellen. Nur Zeilen mit confidence='high' oder
review_required=FALSE werden automatisch backgefüllt.

Zeilen mit review_required=TRUE werden in scope_backfill_audit eingetragen
und MÜSSEN manuell reviewed werden bevor sie backgefüllt werden.

Usage:
    # Dry-run (kein DB-Write, zeigt nur was passieren würde):
    python3 scripts/scope_backfill.py --dry-run

    # Review-Queue zeigen (ambiguous namespaces):
    python3 scripts/scope_backfill.py --show-review-queue

    # Backfill für high-confidence Zeilen ausführen:
    python3 scripts/scope_backfill.py --execute

    # Backfill für eine einzelne Tabelle:
    python3 scripts/scope_backfill.py --execute --table learned_facts

    # Review-Queue nach manueller Bestätigung backfüllen:
    python3 scripts/scope_backfill.py --execute --include-reviewed

Prerequisites:
    - Migration 115 (scope_alias_resolution) wurde angewendet und reviewed
    - Migration 116 (scope columns) wurde angewendet
    - Migration 117 (scope_backfill_audit) wurde angewendet

Sicherheits-Invarianten:
    - Kein ELSE/Default für unbekannte Namespaces: unbekannte Werte landen
      in scope_backfill_audit mit review_required=TRUE und werden NICHT
      automatisch backgefüllt.
    - Idempotent: kann mehrfach ausgeführt werden. Bereits backgefüllte Zeilen
      (scope_org IS NOT NULL) werden übersprungen.
    - Auditierbar: jede backgefüllte Zeile erscheint in scope_backfill_audit.
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

# Tables that have namespace and scope_org columns after migrations 114+116.
# Tuple: (table_name, pk_column, org_column, visibility_column, domain_column|None)
SCOPE_TABLES = [
    # Migration 114 tables (already have scope columns)
    ("connector_state",      "connector_id", "scope_org", "scope_visibility", None),
    ("ingest_event",         "id",           "scope_org", "scope_visibility", "scope_domain"),
    ("conversation",         "session_id",   "scope_org", "scope_visibility", None),
    ("telegram_user",        "user_id",      "default_org", "default_visibility", None),
    ("decision_log",         "decision_id",  "scope_org", "scope_visibility", None),
    # Migration 116 tables (new scope columns)
    ("decision_logs",        "id",           "scope_org", "scope_visibility", None),
    ("learned_facts",        "id",           "scope_org", "scope_visibility", None),
    ("memory_facts_layered", "id",           "scope_org", "scope_visibility", None),
    ("upload_queue",         "id",           "scope_org", "scope_visibility", "scope_domain"),
    ("interaction_quality",  "id",           "scope_org", "scope_visibility", None),
    ("knowledge_item",       "id",           "scope_org", "scope_visibility", "scope_domain"),
    ("chat_sync_state",      "id",           "scope_org", "scope_visibility", None),
    ("entity_mentions",      "id",           "scope_org", "scope_visibility", None),
    ("pattern_history",      "id",           "scope_org", "scope_visibility", None),
    ("prompt_fragment",      "id",           "scope_org", "scope_visibility", None),
    ("conversation_context", "id",           "scope_org", "scope_visibility", None),
    ("person_channel_preference", "id",      "scope_org", "scope_visibility", None),
    ("person_relationship",  "id",           "scope_org", "scope_visibility", None),
    ("hygiene_baselines",    "id",           "scope_org", "scope_visibility", None),
    ("knowledge_evidence_link", "id",        "scope_org", "scope_visibility", None),
]


def get_db_conn():
    """Get a database connection from environment variables."""
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


def load_alias_map(conn, include_review_required: bool = False) -> dict:
    """Load scope_alias_resolution into a dict keyed by legacy_namespace."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if include_review_required:
            cur.execute(
                "SELECT legacy_namespace, target_org, target_visibility, target_domain, "
                "       confidence, review_required, review_note, reviewed_by "
                "FROM scope_alias_resolution "
                "WHERE reviewed_by IS NOT NULL OR review_required = FALSE"
            )
        else:
            cur.execute(
                "SELECT legacy_namespace, target_org, target_visibility, target_domain, "
                "       confidence, review_required, review_note, reviewed_by "
                "FROM scope_alias_resolution "
                "WHERE review_required = FALSE"
            )
        rows = cur.fetchall()
    return {r["legacy_namespace"]: dict(r) for r in rows}


def show_review_queue(conn):
    """Print all review-required entries."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT legacy_namespace, target_org, target_visibility, confidence, "
            "       review_note, production_rows, reviewed_by, reviewed_at "
            "FROM scope_alias_resolution "
            "WHERE review_required = TRUE "
            "ORDER BY production_rows DESC NULLS LAST"
        )
        rows = cur.fetchall()
    if not rows:
        print("✅ Keine Review-Queue Einträge.")
        return
    print(f"\n⚠️  {len(rows)} Namespace-Werte benötigen manuelle Review:\n")
    print(f"{'namespace':<28} {'→ org/vis':<25} {'rows':>6}  {'reviewed_by':<15} note")
    print("-" * 100)
    for r in rows:
        reviewed = r["reviewed_by"] or "—"
        scope_str = f"{r['target_org']}/{r['target_visibility']}"
        rows_count = r["production_rows"] or "?"
        note = (r["review_note"] or "")[:55]
        print(f"{r['legacy_namespace'] or 'NULL':<28} {scope_str:<25} {rows_count:>6}  {reviewed:<15} {note}")
    print()
    print("Zum Markieren als reviewed:")
    print("  UPDATE scope_alias_resolution SET reviewed_by='your_name', reviewed_at=NOW()")
    print("  WHERE legacy_namespace = '<value>';")


def count_pending(conn, table: str, org_col: str) -> int:
    """Count rows needing backfill (scope_org IS NULL)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {org_col} IS NULL")  # noqa: S608
        return cur.fetchone()[0]


def backfill_table(
    conn,
    table: str,
    pk_col: str,
    org_col: str,
    vis_col: str,
    domain_col: Optional[str],
    alias_map: dict,
    run_id: str,
    dry_run: bool,
    batch_size: int = 500,
) -> dict:
    """Backfill a single table. Returns stats dict."""
    stats = {"table": table, "backfilled": 0, "review_queued": 0, "skipped": 0, "errors": 0}

    if table == "decision_log":
        select_sql = (
            f"SELECT {pk_col}, "
            "COALESCE(context_snapshot::jsonb ->> 'namespace', '') AS namespace "
            f"FROM {table} WHERE {org_col} IS NULL"
        )
    else:
        select_sql = f"SELECT {pk_col}, namespace FROM {table} WHERE {org_col} IS NULL"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(select_sql)  # noqa: S608
        rows = cur.fetchall()

    rows_to_fill = []
    rows_to_review = []

    for row in rows:
        ns = row["namespace"] or ""  # "" is sentinel for NULL
        resolution = alias_map.get(ns)

        if resolution is None:
            # Unknown namespace not in alias_resolution table → must review
            rows_to_review.append({
                "backfill_run_id": run_id,
                "table_name": table,
                "record_id": str(row[pk_col]),
                "legacy_namespace": row["namespace"],
                "resolved_org": "UNKNOWN",
                "resolved_visibility": "UNKNOWN",
                "resolved_domain": None,
                "confidence": "none",
                "review_required": True,
                "review_note": f"Namespace '{row['namespace']}' nicht in scope_alias_resolution",
            })
            stats["review_queued"] += 1
        elif resolution["review_required"] and not resolution.get("reviewed_by"):
            # Known but flagged for review  
            rows_to_review.append({
                "backfill_run_id": run_id,
                "table_name": table,
                "record_id": str(row[pk_col]),
                "legacy_namespace": row["namespace"],
                "resolved_org": resolution["target_org"],
                "resolved_visibility": resolution["target_visibility"],
                "resolved_domain": resolution.get("target_domain"),
                "confidence": resolution["confidence"],
                "review_required": True,
                "review_note": resolution.get("review_note"),
            })
            stats["review_queued"] += 1
        else:
            rows_to_fill.append({
                "pk": row[pk_col],
                "org": resolution["target_org"],
                "vis": resolution["target_visibility"],
                "domain": resolution.get("target_domain"),
                "confidence": resolution["confidence"],
                "ns": row["namespace"],
            })

    if dry_run:
        print(f"  [DRY-RUN] {table}: würde {len(rows_to_fill)} Zeilen backfüllen, "
              f"{len(rows_to_review)} in Review-Queue")
        stats["backfilled"] = len(rows_to_fill)
        stats["review_queued"] = len(rows_to_review)
        return stats

    # Write backfill in batches
    for i in range(0, len(rows_to_fill), batch_size):
        batch = rows_to_fill[i : i + batch_size]
        with conn.cursor() as cur:
            for item in batch:
                try:
                    if domain_col:
                        cur.execute(
                            f"UPDATE {table} SET {org_col}=%s, {vis_col}=%s, {domain_col}=%s "  # noqa: S608
                            f"WHERE {pk_col}=%s AND {org_col} IS NULL",
                            (item["org"], item["vis"], item["domain"], item["pk"]),
                        )
                    else:
                        cur.execute(
                            f"UPDATE {table} SET {org_col}=%s, {vis_col}=%s "  # noqa: S608
                            f"WHERE {pk_col}=%s AND {org_col} IS NULL",
                            (item["org"], item["vis"], item["pk"]),
                        )
                    # Write to audit
                    cur.execute(
                        "INSERT INTO scope_backfill_audit "
                        "(backfill_run_id, table_name, record_id, legacy_namespace, "
                        " resolved_org, resolved_visibility, resolved_domain, confidence, review_required) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (table_name, record_id, backfill_run_id) DO NOTHING",
                        (run_id, table, str(item["pk"]), item["ns"],
                         item["org"], item["vis"], item["domain"],
                         item["confidence"], False),
                    )
                    stats["backfilled"] += 1
                except Exception as e:
                    conn.rollback()
                    stats["errors"] += 1
                    print(f"    ERROR in {table} pk={item['pk']}: {e}", file=sys.stderr)
                    continue
        conn.commit()

    # Write review-required entries to audit (no DB update for these)
    if rows_to_review:
        with conn.cursor() as cur:
            for item in rows_to_review:
                try:
                    cur.execute(
                        "INSERT INTO scope_backfill_audit "
                        "(backfill_run_id, table_name, record_id, legacy_namespace, "
                        " resolved_org, resolved_visibility, resolved_domain, confidence, "
                        " review_required, review_note) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (table_name, record_id, backfill_run_id) DO NOTHING",
                        (run_id, item["table_name"], item["record_id"], item["legacy_namespace"],
                         item["resolved_org"], item["resolved_visibility"], item["resolved_domain"],
                         item["confidence"], True, item["review_note"]),
                    )
                except Exception as e:
                    print(f"    AUDIT ERROR {table}: {e}", file=sys.stderr)
        conn.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Scope backfill script for Jarvis namespace migration")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, no DB writes")
    parser.add_argument("--show-review-queue", action="store_true", help="Show ambiguous namespace entries needing review")
    parser.add_argument("--execute", action="store_true", help="Execute the backfill")
    parser.add_argument("--include-reviewed", action="store_true", help="Also backfill entries marked reviewed_by in alias table")
    parser.add_argument("--table", help="Only backfill this table")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size per table (default: 500)")
    args = parser.parse_args()

    if not args.dry_run and not args.show_review_queue and not args.execute:
        parser.print_help()
        sys.exit(1)

    conn = get_db_conn()
    conn.autocommit = False

    if args.show_review_queue:
        show_review_queue(conn)
        conn.close()
        return

    alias_map = load_alias_map(conn, include_review_required=args.include_reviewed)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    tables = SCOPE_TABLES
    if args.table:
        tables = [t for t in SCOPE_TABLES if t[0] == args.table]
        if not tables:
            print(f"ERROR: Tabelle '{args.table}' nicht in SCOPE_TABLES", file=sys.stderr)
            sys.exit(1)

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Scope Backfill – run_id: {run_id}")
    print(f"Alias-Map geladen: {len(alias_map)} Einträge (include_reviewed={args.include_reviewed})\n")

    total_stats = {"backfilled": 0, "review_queued": 0, "errors": 0}

    for table_name, pk_col, org_col, vis_col, domain_col in tables:
        pending = count_pending(conn, table_name, org_col)
        if pending == 0:
            print(f"  ✓ {table_name}: bereits vollständig (0 pending)")
            continue

        print(f"  → {table_name}: {pending} Zeilen pending…")
        stats = backfill_table(
            conn, table_name, pk_col, org_col, vis_col, domain_col,
            alias_map, run_id, args.dry_run, args.batch_size,
        )
        marker = "✓" if stats["errors"] == 0 else "✗"
        print(f"    {marker} backfilled={stats['backfilled']}, "
              f"review_queued={stats['review_queued']}, "
              f"errors={stats['errors']}")
        total_stats["backfilled"] += stats["backfilled"]
        total_stats["review_queued"] += stats["review_queued"]
        total_stats["errors"] += stats["errors"]

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Fertig in {elapsed:.1f}s")
    print(f"  Total backfilled:    {total_stats['backfilled']}")
    print(f"  Review-Queue:        {total_stats['review_queued']}  ← prüfen: --show-review-queue")
    print(f"  Errors:              {total_stats['errors']}")

    if total_stats["review_queued"] > 0:
        print("\n  ⚠️  Review-Einträge vorhanden. Vor dem Lese-Cutover bereinigen.")
    if total_stats["errors"] > 0:
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
