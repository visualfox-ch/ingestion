#!/usr/bin/env python3
"""
Normalize legacy work_* origin namespaces into canonical "work" with labels.

Updates payloads in:
- jarvis_work
- jarvis_comms

Sets:
- origin_namespace -> "work"
- legacy_origin_namespace -> previous value
- project/org labels based on legacy origin
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

from app.label_schema import apply_label_defaults
from app.namespace_constants import namespace_org
from app.jarvis_config import should_skip_source_path


def make_filter(field: str, value: str) -> Filter:
    return Filter(must=[FieldCondition(key=field, match=MatchValue(value=value))])


def iter_points(client: QdrantClient, collection: str, origin: str, match_field: str):
    offset = None
    flt = make_filter(match_field, origin)
    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            scroll_filter=flt,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break
        for point in points:
            yield point
        if not next_offset:
            break
        offset = next_offset


def normalize_payload(payload: Dict, collection: str, origin: str) -> Dict | None:
    payload = dict(payload or {})
    source_path = payload.get("source_path", "")
    if should_skip_source_path("work", source_path):
        return None
    payload["legacy_origin_namespace"] = origin
    payload["origin_namespace"] = "work"
    if collection == "jarvis_work":
        payload["namespace"] = "work"
    elif collection == "jarvis_comms":
        payload["namespace"] = "comms"

    org = namespace_org(origin) or payload.get("org") or payload.get("project")
    if org:
        payload["org"] = org
        payload.setdefault("project", org)

    return apply_label_defaults(payload)


def batch(iterable: Iterable, size: int):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collections", default="jarvis_work,jarvis_comms")
    parser.add_argument("--origins", default="work_projektil,work_visualfox")
    parser.add_argument("--apply", action="store_true", help="Apply updates (default: dry-run)")
    parser.add_argument("--match-legacy", action="store_true", help="Match legacy_origin_namespace instead of origin_namespace")
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    collections = [c.strip() for c in args.collections.split(",") if c.strip()]
    origins = [o.strip() for o in args.origins.split(",") if o.strip()]

    client = QdrantClient(host="qdrant", port=6333)

    summary: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    match_field = "legacy_origin_namespace" if args.match_legacy else "origin_namespace"

    for collection in collections:
        for origin in origins:
            points_iter = iter_points(client, collection, origin, match_field)
            for batch_points in batch(points_iter, args.batch_size):
                summary[collection][origin] += len(batch_points)
                if not args.apply:
                    continue
                updated = []
                for p in batch_points:
                    payload = normalize_payload(p.payload, collection, origin)
                    if payload is None:
                        continue
                    updated.append(PointStruct(
                        id=p.id,
                        vector=p.vector,
                        payload=payload,
                    ))
                if updated:
                    client.upsert(collection_name=collection, points=updated)

    print("Migration summary:")
    for collection, origins_map in summary.items():
        for origin, count in origins_map.items():
            print(f"- {collection} {origin}: {count} points {'updated' if args.apply else 'scanned'}")


if __name__ == "__main__":
    main()
