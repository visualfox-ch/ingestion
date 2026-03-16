#!/usr/bin/env python3
"""
Backfill specific missing source_path points from legacy work collection into jarvis_work,
then optionally purge legacy collection.

Usage:
  python scripts/fix_work_migration_missing.py --purge-all
"""
from __future__ import annotations

import argparse
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

from app.label_schema import apply_label_defaults
from app.namespace_constants import namespace_org
from app.jarvis_config import should_skip_source_path


QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333

# Keep empty by default to avoid accidental backfill of non-work sources.
DEFAULT_PATHS: List[str] = []


def make_filter(field: str, value: str) -> Filter:
    return Filter(must=[FieldCondition(key=field, match=MatchValue(value=value))])


def scroll_by_source_path(client: QdrantClient, collection: str, source_path: str):
    points = []
    offset = None
    flt = make_filter("source_path", source_path)
    while True:
        res = client.scroll(
            collection_name=collection,
            scroll_filter=flt,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        batch, next_offset = res
        points.extend(batch)
        if not next_offset or len(batch) == 0:
            break
        offset = next_offset
    return points


def upsert_points(client: QdrantClient, collection: str, points: List[PointStruct]):
    if points:
        client.upsert(collection_name=collection, points=points)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default=",".join(DEFAULT_PATHS))
    parser.add_argument("--source", default="jarvis_work_projektil")
    parser.add_argument("--target", default="jarvis_work")
    parser.add_argument("--origin", default="work_projektil")
    parser.add_argument("--purge-all", action="store_true", help="Delete entire legacy collection after backfill")
    args = parser.parse_args()

    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    total_copied = 0
    for path in paths:
        if should_skip_source_path("work", path):
            print(f"⏭️  Skipping blocked path: {path}")
            continue
        src_points = scroll_by_source_path(client, args.source, path)
        if not src_points:
            print(f"⚠️  No points for {path}")
            continue

        new_points = []
        org = namespace_org(args.origin) or args.origin
        project = org
        for p in src_points:
            payload = dict(p.payload or {})
            payload["namespace"] = "work"
            payload["origin_namespace"] = "work"
            payload.setdefault("org", org)
            payload.setdefault("project", project)

            payload = apply_label_defaults(payload)

            new_points.append(PointStruct(
                id=p.id,
                vector=p.vector,
                payload=payload
            ))

        upsert_points(client, args.target, new_points)
        total_copied += len(new_points)
        print(f"✅ Copied {len(new_points)} points for {path}")

    print(f"✅ Backfill complete. Total points copied: {total_copied}")

    if args.purge_all:
        print(f"🧹 Purging legacy collection: {args.source}")
        client.delete_collection(collection_name=args.source)
        print("✅ Legacy collection deleted")


if __name__ == "__main__":
    main()
