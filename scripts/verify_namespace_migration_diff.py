#!/usr/bin/env python3
"""
Verify namespace migration coverage.

Legacy mode:
- Compare old collections against new targets using origin_namespace counts.

Filesystem mode (preferred when legacy collections are gone):
- Build expected source_path sets from /brain/raw + /brain/parsed for legacy origins
- Compare against jarvis_work / jarvis_comms filtered by project/org labels
- Report missing/extra source_paths for a smooth, reliable diff
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Set


QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
RAW_DIR = Path(os.environ.get("RAW_DIR", "/brain/raw"))
PARSED_DIR = Path(os.environ.get("PARSED_DIR", "/brain/parsed"))

PROJECT_ORIGINS = {
    "projektil": "work_projektil",
    "visualfox": "work_visualfox",
}


def qdrant_url(path: str) -> str:
    return f"http://{QDRANT_HOST}:{QDRANT_PORT}{path}"


def http_get(path: str) -> Dict[str, Any]:
    req = urllib.request.Request(qdrant_url(path))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def http_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        qdrant_url(path),
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def make_filter(field: str, value: str) -> Dict[str, Any]:
    return {"must": [{"key": field, "match": {"value": value}}]}


@dataclass
class CheckResult:
    name: str
    source_collection: str
    target_collection: str
    origin_namespace: Optional[str]
    source_count: Optional[int]
    target_count: Optional[int]
    coverage: Optional[float]
    status: str
    notes: str


@dataclass
class FsCheckResult:
    name: str
    collection: str
    namespace: str
    project: str
    expected_count: int
    actual_count: int
    missing_count: int
    extra_count: int
    missing_sample: List[str]
    extra_sample: List[str]
    status: str
    notes: str


def count_points(collection: str, filters: Optional[Dict[str, Any]]) -> Optional[int]:
    try:
        payload = {"exact": True}
        if filters:
            payload["filter"] = filters
        result = http_post(f"/collections/{collection}/points/count", payload)
        return int(result.get("result", {}).get("count", 0))
    except Exception:
        return None


def collection_exists(name: str) -> bool:
    try:
        cols = http_get("/collections").get("result", {}).get("collections", [])
        return any(c.get("name") == name for c in cols)
    except Exception:
        return False


def evaluate_pair(
    name: str,
    source_collection: str,
    target_collection: str,
    origin_namespace: Optional[str]
) -> CheckResult:
    source_exists = collection_exists(source_collection)
    target_exists = collection_exists(target_collection)

    if not source_exists:
        return CheckResult(
            name=name,
            source_collection=source_collection,
            target_collection=target_collection,
            origin_namespace=origin_namespace,
            source_count=None,
            target_count=None,
            coverage=None,
            status="source_missing",
            notes="Source collection not found."
        )

    if not target_exists:
        return CheckResult(
            name=name,
            source_collection=source_collection,
            target_collection=target_collection,
            origin_namespace=origin_namespace,
            source_count=None,
            target_count=None,
            coverage=None,
            status="target_missing",
            notes="Target collection not found."
        )

    source_count = count_points(source_collection, filters=None)
    target_filters = make_filter("origin_namespace", origin_namespace) if origin_namespace else None
    target_count = count_points(target_collection, filters=target_filters)

    # Fallback if counts failed
    if source_count is None or target_count is None:
        return CheckResult(
            name=name,
            source_collection=source_collection,
            target_collection=target_collection,
            origin_namespace=origin_namespace,
            source_count=source_count,
            target_count=target_count,
            coverage=None,
            status="error",
            notes="Failed to count one or more collections."
        )

    if source_count == 0:
        return CheckResult(
            name=name,
            source_collection=source_collection,
            target_collection=target_collection,
            origin_namespace=origin_namespace,
            source_count=source_count,
            target_count=target_count,
            coverage=1.0,
            status="ok_empty_source",
            notes="Source collection empty."
        )

    coverage = target_count / max(source_count, 1)

    if target_count == 0:
        status = "critical_missing_all"
        notes = "Target has 0 points while source has data."
    elif target_count < source_count:
        status = "warn_partial"
        notes = "Target has fewer points than source (possible dedupe or missing parsed data)."
    elif target_count == source_count:
        status = "ok"
        notes = "Counts match."
    else:
        status = "ok_extra"
        notes = "Target has more points than source (new data or different indexing scope)."

    return CheckResult(
        name=name,
        source_collection=source_collection,
        target_collection=target_collection,
        origin_namespace=origin_namespace,
        source_count=source_count,
        target_count=target_count,
        coverage=coverage,
        status=status,
        notes=notes
    )


def iter_raw_docs(raw_base: Path) -> Set[str]:
    docs: Set[str] = set()
    if not raw_base.exists():
        return docs
    for item in raw_base.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix not in (".txt", ".md"):
            continue
        rel = item.relative_to(RAW_DIR)
        # Exclude comms raw sources (handled separately)
        if len(rel.parts) >= 3 and rel.parts[1] == "inbox" and rel.parts[2] in ("chats", "gchat"):
            continue
        docs.add(str(rel))
    return docs


def iter_raw_comms(raw_base: Path) -> Set[str]:
    comms: Set[str] = set()
    chats = raw_base / "inbox" / "chats"
    gchat = raw_base / "inbox" / "gchat"
    if chats.exists():
        for p in chats.glob("*.txt"):
            comms.add(str(p.relative_to(RAW_DIR)))
        # Include processed files but map to original source_path
        processed = chats / "_processed"
        if processed.exists():
            for p in processed.glob("*.txt"):
                rel = p.relative_to(RAW_DIR)
                rel_parts = list(rel.parts)
                if "_processed" in rel_parts:
                    rel_parts.remove("_processed")
                comms.add(str(Path(*rel_parts)))
    if gchat.exists():
        for p in gchat.glob("*.json"):
            comms.add(str(p.relative_to(RAW_DIR)))
        processed = gchat / "_processed"
        if processed.exists():
            for p in processed.glob("*.json"):
                rel = p.relative_to(RAW_DIR)
                rel_parts = list(rel.parts)
                if "_processed" in rel_parts:
                    rel_parts.remove("_processed")
                comms.add(str(Path(*rel_parts)))
    return comms


def iter_parsed_emails(parsed_base: Path) -> Set[str]:
    emails: Set[str] = set()
    email_dir = parsed_base / "email"
    if not email_dir.exists():
        return emails
    for label in ("inbox", "sent"):
        label_dir = email_dir / label
        if not label_dir.exists():
            continue
        for p in label_dir.glob("*.txt"):
            rel_parts = p.relative_to(PARSED_DIR).parts
            source_path = str(Path(*rel_parts[:-1]) / f"{p.stem}.json")
            emails.add(source_path)
    return emails


def iter_parsed_comms(parsed_base: Path) -> Set[str]:
    comms: Set[str] = set()
    for subdir in ("comms", "comms_gchat"):
        path = parsed_base / subdir
        if not path.exists():
            continue
        for p in path.glob("*.jsonl"):
            comms.add(str(p.relative_to(PARSED_DIR)))
    return comms


def expected_source_paths(origin: str) -> Dict[str, Set[str]]:
    raw_base = RAW_DIR / origin
    parsed_base = PARSED_DIR / origin
    return {
        # Comms can originate from raw inbox or legacy parsed jsonl files.
        "comms": iter_raw_comms(raw_base) | iter_parsed_comms(parsed_base),
        "docs": iter_raw_docs(raw_base),
        "email": iter_parsed_emails(parsed_base),
    }


def scroll_source_paths(
    collection: str,
    namespace: str,
    project: Optional[str],
) -> Set[str]:
    source_paths: Set[str] = set()
    offset = None

    must = [{"key": "namespace", "match": {"value": namespace}}]
    should = []
    if project:
        should.append({"key": "project", "match": {"value": project}})
        should.append({"key": "org", "match": {"value": project}})
    filters = {"must": must}
    if should:
        filters["should"] = should

    while True:
        payload = {
            "limit": 512,
            "with_payload": True,
            "with_vector": False,
            "filter": filters,
        }
        if offset is not None:
            payload["offset"] = offset
        result = http_post(f"/collections/{collection}/points/scroll", payload).get("result", {})
        points = result.get("points", [])
        if not points:
            break
        for p in points:
            sp = (p.get("payload") or {}).get("source_path")
            if sp:
                source_paths.add(sp)
        offset = result.get("next_page_offset")
        if offset is None:
            break

    return source_paths


def fs_check(
    name: str,
    collection: str,
    namespace: str,
    project: str,
    expected: Set[str],
) -> FsCheckResult:
    actual = scroll_source_paths(collection, namespace, project)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)

    if not expected:
        status = "ok_empty_source"
        notes = "No filesystem sources found for this project."
    elif not actual:
        status = "critical_missing_all"
        notes = "No Qdrant points found for this project."
    elif missing:
        status = "warn_partial"
        notes = "Some expected source_paths are missing."
    else:
        status = "ok"
        notes = "All expected source_paths found."

    return FsCheckResult(
        name=name,
        collection=collection,
        namespace=namespace,
        project=project,
        expected_count=len(expected),
        actual_count=len(actual),
        missing_count=len(missing),
        extra_count=len(extra),
        missing_sample=missing[:20],
        extra_sample=extra[:20],
        status=status,
        notes=notes,
    )


def main() -> None:
    legacy_sources = [
        "jarvis_work_projektil",
        "jarvis_work_visualfox",
        "jarvis_work_projektil_comms",
        "jarvis_work_visualfox_comms",
        "jarvis_private_comms",
    ]
    legacy_mode = any(collection_exists(name) for name in legacy_sources)

    results: Dict[str, Any] = {}

    if legacy_mode:
        checks = [
            ("work_projektil → work (emails/docs)", "jarvis_work_projektil", "jarvis_work", "work_projektil"),
            ("work_visualfox → work (emails/docs)", "jarvis_work_visualfox", "jarvis_work", "work_visualfox"),
            ("work_projektil_comms → comms", "jarvis_work_projektil_comms", "jarvis_comms", "work_projektil"),
            ("work_visualfox_comms → comms", "jarvis_work_visualfox_comms", "jarvis_comms", "work_visualfox"),
            ("private_comms → comms", "jarvis_private_comms", "jarvis_comms", "private"),
        ]
        results["legacy_checks"] = [asdict(evaluate_pair(name, src, tgt, origin)) for name, src, tgt, origin in checks]
    else:
        fs_results: List[FsCheckResult] = []
        for project, origin in PROJECT_ORIGINS.items():
            expected = expected_source_paths(origin)
            fs_results.append(
                fs_check(
                    name=f"{origin} → work (emails/docs)",
                    collection="jarvis_work",
                    namespace="work",
                    project=project,
                    expected=expected["docs"] | expected["email"],
                )
            )
            fs_results.append(
                fs_check(
                    name=f"{origin} → comms (chats)",
                    collection="jarvis_comms",
                    namespace="comms",
                    project=project,
                    expected=expected["comms"],
                )
            )
        results["filesystem_checks"] = [asdict(r) for r in fs_results]

    summary = {
        "qdrant_host": QDRANT_HOST,
        "qdrant_port": QDRANT_PORT,
        "raw_dir": str(RAW_DIR),
        "parsed_dir": str(PARSED_DIR),
        **results,
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
