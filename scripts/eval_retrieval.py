#!/usr/bin/env python3
"""
Simple Retrieval Evaluation Harness

Runs search_knowledge on a fixed query set and computes basic hit-rate
against expected source_path substrings.
"""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.tools import tool_search_knowledge


EVAL_PATH = os.getenv("JARVIS_RETRIEVAL_EVAL_PATH", "/brain/system/logs/retrieval_eval.json")

_DEFAULT_QUERIES = [
    {"query": "Jarvis health check status", "namespace": "work", "expect": ["RUNBOOK_OBSERVABILITY_CHECKS.md"]},
    {"query": "deploy lock rules", "namespace": "work", "expect": ["DEPLOY_LOCK.md"]},
    {"query": "projektil", "namespace": "work", "expect": ["work_projektil/"]},
]


def _load_queries() -> List[Dict[str, Any]]:
    raw = os.getenv("JARVIS_RETRIEVAL_EVAL_QUERIES")
    if not raw:
        return _DEFAULT_QUERIES
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return _DEFAULT_QUERIES


def _ensure_output_dir(path: str) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)


def _hit(results: List[Dict[str, Any]], expect: List[str]) -> bool:
    if not expect:
        return True
    for r in results:
        src = (r.get("source_path") or "").lower()
        for e in expect:
            if e.lower() in src:
                return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Also print the full evaluation report as JSON to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queries = _load_queries()
    results = []
    hits = 0
    total = 0

    for item in queries:
        query = (item.get("query") or "").strip()
        if not query:
            continue
        namespace = item.get("namespace") or "work"
        expect = item.get("expect") or []
        limit = int(item.get("limit") or 5)

        res = tool_search_knowledge(query=query, namespace=namespace, limit=limit)
        total += 1
        ok = _hit(res.get("results", []), expect)
        hits += 1 if ok else 0

        results.append({
            "query": query,
            "namespace": namespace,
            "expected": expect,
            "hit": ok,
            "results_count": res.get("count", 0),
        })

    summary = {
        "queries_total": total,
        "hit_rate": hits / max(total, 1),
    }

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "summary": summary,
        "results": results,
    }

    try:
        _ensure_output_dir(EVAL_PATH)
        with open(EVAL_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print("Retrieval eval complete")
    print(f"  output: {EVAL_PATH}")
    print(f"  queries: {summary['queries_total']}")
    print(f"  hit_rate: {summary['hit_rate']:.3f}")

    if args.print_json:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
