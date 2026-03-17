#!/usr/bin/env python3
"""Scope alias review utility.

Helps review and approve pending scope alias mappings safely.

Commands:
  report
  approve --namespace <value> --reviewer <name> --reason <text>
  approve-null --reviewer <name> --reason <text>
    approve-empty --reviewer <name> --reason <text>

This script never alters legacy namespace data in source tables.
It only updates scope_alias_resolution review metadata.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras


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


def cmd_report(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT legacy_namespace, target_org, target_visibility, target_domain, "
            "       confidence, review_required, reviewed_by, reviewed_at, production_rows "
            "FROM scope_alias_resolution "
            "WHERE review_required = TRUE "
            "ORDER BY production_rows DESC NULLS LAST"
        )
        alias_rows = cur.fetchall()

        cur.execute(
            "SELECT table_name, legacy_namespace, COUNT(*) AS cnt "
            "FROM scope_backfill_audit "
            "WHERE review_required = TRUE "
            "GROUP BY table_name, legacy_namespace "
            "ORDER BY table_name, cnt DESC"
        )
        backlog_rows = cur.fetchall()

    print("PENDING_ALIAS_REVIEW")
    print("namespace,target_org,target_visibility,target_domain,confidence,reviewed_by,production_rows")
    for r in alias_rows:
        ns = r["legacy_namespace"] if r["legacy_namespace"] is not None else "<NULL>"
        domain = r["target_domain"] or ""
        reviewed_by = r["reviewed_by"] or ""
        print(
            f"{ns},{r['target_org']},{r['target_visibility']},{domain},"
            f"{r['confidence']},{reviewed_by},{r['production_rows'] or ''}"
        )

    print("\nPENDING_BACKFILL_BY_TABLE")
    print("table,namespace,count")
    for r in backlog_rows:
        ns = r["legacy_namespace"] if r["legacy_namespace"] not in (None, "") else "<NULL_OR_EMPTY>"
        print(f"{r['table_name']},{ns},{r['cnt']}")


def approve_alias(conn, namespace_value, reviewer: str, reason: str, is_null: bool = False):
    with conn.cursor() as cur:
        if is_null:
            cur.execute(
                "UPDATE scope_alias_resolution "
                "SET reviewed_by = %s, reviewed_at = NOW(), review_note = COALESCE(review_note, '') || E'\\nREVIEW_APPROVED: ' || %s "
                "WHERE legacy_namespace IS NULL"
                "RETURNING id",
                (reviewer, reason),
            )
        else:
            cur.execute(
                "UPDATE scope_alias_resolution "
                "SET reviewed_by = %s, reviewed_at = NOW(), review_note = COALESCE(review_note, '') || E'\\nREVIEW_APPROVED: ' || %s "
                "WHERE legacy_namespace = %s "
                "RETURNING id",
                (reviewer, reason, namespace_value),
            )
        rows = cur.fetchall()

    if not rows:
        ns_label = "<NULL>" if is_null else namespace_value
        print(f"ERROR: no alias row found for namespace {ns_label}", file=sys.stderr)
        return 1

    conn.commit()
    ns_label = "<NULL>" if is_null else namespace_value
    print(f"OK: approved alias {ns_label} by {reviewer}")
    return 0


def approve_empty_alias(conn, reviewer: str, reason: str):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scope_alias_resolution "
            "SET reviewed_by = %s, reviewed_at = NOW(), review_note = COALESCE(review_note, '') || E'\\nREVIEW_APPROVED: ' || %s "
            "WHERE legacy_namespace = '' "
            "RETURNING id",
            (reviewer, reason),
        )
        rows = cur.fetchall()

    if not rows:
        print("ERROR: no alias row found for empty namespace", file=sys.stderr)
        return 1

    conn.commit()
    print(f"OK: approved alias <EMPTY> by {reviewer}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Scope alias review utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("report", help="Show pending aliases and pending backfill distribution")

    p_approve = sub.add_parser("approve", help="Approve one alias by namespace value")
    p_approve.add_argument("--namespace", required=True)
    p_approve.add_argument("--reviewer", required=True)
    p_approve.add_argument("--reason", required=True)

    p_approve_null = sub.add_parser("approve-null", help="Approve the NULL namespace alias row")
    p_approve_null.add_argument("--reviewer", required=True)
    p_approve_null.add_argument("--reason", required=True)

    p_approve_empty = sub.add_parser("approve-empty", help="Approve the empty-string namespace alias row")
    p_approve_empty.add_argument("--reviewer", required=True)
    p_approve_empty.add_argument("--reason", required=True)

    args = parser.parse_args()

    conn = get_db_conn()
    try:
        if args.cmd == "report":
            cmd_report(conn)
            return 0
        if args.cmd == "approve":
            return approve_alias(conn, args.namespace, args.reviewer, args.reason, is_null=False)
        if args.cmd == "approve-null":
            return approve_alias(conn, None, args.reviewer, args.reason, is_null=True)
        if args.cmd == "approve-empty":
            return approve_empty_alias(conn, args.reviewer, args.reason)
        print("Unknown command", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
