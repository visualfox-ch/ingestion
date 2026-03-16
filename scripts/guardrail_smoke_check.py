#!/usr/bin/env python3
"""
Guardrail smoke check for namespace hygiene.

Scans a bounded number of points and flags any source_path that should be blocked
by should_skip_source_path() (e.g., _processed copies or /brain/system/docker docs).
"""
from __future__ import annotations

import argparse
from typing import List, Tuple

from qdrant_client import QdrantClient

from app.jarvis_config import should_skip_source_path


def scan_collection(
    client: QdrantClient,
    collection: str,
    namespace: str,
    max_points: int,
    fail_fast: bool,
) -> Tuple[int, List[str]]:
    offset = None
    scanned = 0
    violations: List[str] = []

    while scanned < max_points:
        res = client.scroll(
            collection_name=collection,
            scroll_filter=None,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points, next_offset = res
        if not points:
            break
        for p in points:
            payload = p.payload or {}
            source_path = payload.get("source_path", "") or ""
            scanned += 1
            if source_path and should_skip_source_path(namespace, source_path):
                violations.append(source_path)
                if fail_fast:
                    return scanned, violations
            if scanned >= max_points:
                break
        if not next_offset:
            break
        offset = next_offset

    return scanned, violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-points", type=int, default=20000)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    client = QdrantClient(host="qdrant", port=6333)

    checks = [
        ("jarvis_work", "work"),
        ("jarvis_comms", "comms"),
    ]

    overall_violations = 0
    for collection, namespace in checks:
        scanned, violations = scan_collection(
            client=client,
            collection=collection,
            namespace=namespace,
            max_points=args.max_points,
            fail_fast=args.fail_fast,
        )
        print(f"{collection} ({namespace}) scanned: {scanned}")
        if violations:
            overall_violations += len(violations)
            print(f"  violations: {len(violations)}")
            print(f"  sample: {violations[:10]}")
        else:
            print("  violations: 0")

    if overall_violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
