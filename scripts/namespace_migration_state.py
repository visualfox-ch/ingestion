#!/usr/bin/env python3
"""
Manage namespace migration state.
"""
import argparse
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

import os

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "jarvis")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "jarvis")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")


def get_conn():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        cursor_factory=RealDictCursor,
    )


def ensure_row(cur, namespace: str):
    cur.execute(
        """
        INSERT INTO namespace_migration_state (namespace)
        VALUES (%s)
        ON CONFLICT (namespace) DO NOTHING
        """,
        (namespace,),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--labels-applied", action="store_true")
    parser.add_argument("--allow-reindex", action="store_true")
    parser.add_argument("--notes")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_row(cur, args.namespace)

            if args.labels_applied:
                cur.execute(
                    """
                    UPDATE namespace_migration_state
                    SET labels_applied = TRUE,
                        labels_applied_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE namespace = %s
                    """,
                    (args.namespace,),
                )

            if args.allow_reindex:
                cur.execute(
                    """
                    UPDATE namespace_migration_state
                    SET reindex_allowed = TRUE,
                        reindex_allowed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE namespace = %s
                    """,
                    (args.namespace,),
                )

            if args.notes:
                cur.execute(
                    """
                    UPDATE namespace_migration_state
                    SET notes = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE namespace = %s
                    """,
                    (args.notes, args.namespace),
                )

            if args.status or (not args.labels_applied and not args.allow_reindex and not args.notes):
                cur.execute(
                    """
                    SELECT namespace, labels_applied, reindex_allowed, updated_at, notes
                    FROM namespace_migration_state
                    WHERE namespace = %s
                    """,
                    (args.namespace,),
                )
                row = cur.fetchone()
                print(row)


if __name__ == "__main__":
    main()
