#!/usr/bin/env python3
"""
Backfill labels for existing Qdrant points.

Uses apply_label_defaults() to compute labels and writes them back to payload.
"""
import argparse
import json
import os
from typing import Dict, Any, List, Tuple

from qdrant_client import QdrantClient

from app.label_schema import apply_label_defaults


QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))


def _group_updates(updates: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for point_id, labels in updates:
        key = json.dumps(labels, sort_keys=True)
        group = grouped.setdefault(key, {"labels": labels, "ids": []})
        group["ids"].append(point_id)
    return grouped


def backfill_collection(client: QdrantClient, collection: str, batch_size: int, dry_run: bool) -> Dict[str, int]:
    offset = None
    scanned = 0
    updated = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break

        updates: List[Tuple[str, Dict[str, Any]]] = []
        for p in points:
            scanned += 1
            payload = p.payload or {}
            meta = apply_label_defaults(payload)
            new_labels = meta.get("labels", {})
            if new_labels != payload.get("labels"):
                updates.append((p.id, new_labels))

        if updates and not dry_run:
            grouped = _group_updates(updates)
            for group in grouped.values():
                client.set_payload(
                    collection_name=collection,
                    payload={"labels": group["labels"]},
                    points=group["ids"],
                )
                updated += len(group["ids"])
        else:
            updated += len(updates) if dry_run else 0

        offset = next_offset
        if offset is None:
            break

    return {"scanned": scanned, "updated": updated}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--collections",
        default="jarvis_work,jarvis_private,jarvis_comms",
        help="Comma-separated Qdrant collections to backfill",
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    collections = [c.strip() for c in args.collections.split(",") if c.strip()]
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    for collection in collections:
        stats = backfill_collection(client, collection, args.batch_size, args.dry_run)
        print(f"{collection}: scanned={stats['scanned']} updated={stats['updated']}")


if __name__ == "__main__":
    main()
