"""
Nightly RAG Regression Runner

Lightweight MVP to track RAG stability using a fixed query set.
Stores latest run results to a JSON file for review and alerting.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .observability import get_logger, log_with_context
from .embed import embed_texts
from .hybrid_search import hybrid_search

logger = get_logger("jarvis.rag_regression")

# Config via env
RAG_REGRESSION_ENABLED = os.getenv("JARVIS_RAG_REGRESSION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
RAG_REGRESSION_PATH = os.getenv("JARVIS_RAG_REGRESSION_PATH", "/brain/system/logs/rag_regression.json")
RAG_REGRESSION_MAX_RESULTS = int(os.getenv("JARVIS_RAG_REGRESSION_MAX_RESULTS", "20"))

_DEFAULT_QUERIES = [
    {"query": "Jarvis health check status", "namespace": "work_projektil"},
    {"query": "meeting notes"},
    {"query": "project timeline"},
    {"query": "deployment status"},
    {"query": "support hotline update"},
]


def _load_query_set() -> List[Dict[str, Any]]:
    raw = os.getenv("JARVIS_RAG_REGRESSION_QUERIES")
    if not raw:
        return _DEFAULT_QUERIES
    try:
        queries = json.loads(raw)
        if isinstance(queries, list):
            return queries
    except json.JSONDecodeError:
        pass
    return _DEFAULT_QUERIES


def _ensure_output_dir(path: str) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)


def run_rag_regression() -> Dict[str, Any]:
    """Run a lightweight RAG regression check and persist results."""
    if not RAG_REGRESSION_ENABLED:
        return {"status": "disabled", "timestamp": datetime.utcnow().isoformat()}

    queries = _load_query_set()
    results: List[Dict[str, Any]] = []
    empty_count = 0
    fusion_scores: List[float] = []
    total_results = 0

    for item in queries:
        query = (item.get("query") or "").strip()
        if not query:
            continue
        namespace = item.get("namespace")
        item_type = item.get("item_type")
        limit = int(item.get("limit") or RAG_REGRESSION_MAX_RESULTS)

        embedding = embed_texts([query])[0] or []
        namespace = str(namespace) if namespace else None
        item_type = str(item_type) if item_type else None
        hits = hybrid_search(
            query=query,
            query_embedding=embedding,
            namespace=namespace,
            item_type=item_type,
            limit=limit,
        )

        count = len(hits)
        total_results += count
        if count == 0:
            empty_count += 1

        top_score = hits[0].fusion_score if hits else None
        avg_score = None
        if hits:
            scores = [h.fusion_score for h in hits]
            avg_score = sum(scores) / len(scores)
            fusion_scores.append(avg_score)

        results.append({
            "query": query,
            "namespace": namespace,
            "item_type": item_type,
            "results_count": count,
            "top_fusion_score": round(top_score, 6) if top_score is not None else None,
            "avg_fusion_score": round(avg_score, 6) if avg_score is not None else None,
        })

    summary = {
        "queries_total": len(results),
        "empty_rate": empty_count / max(len(results), 1),
        "avg_results_per_query": total_results / max(len(results), 1),
        "avg_fusion_score": round(sum(fusion_scores) / len(fusion_scores), 6) if fusion_scores else None,
    }

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "ok",
        "summary": summary,
        "results": results,
    }

    try:
        _ensure_output_dir(RAG_REGRESSION_PATH)
        with open(RAG_REGRESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_with_context(logger, "warning", "Failed to write RAG regression report", error=str(e))

    log_with_context(logger, "info", "RAG regression run complete", **summary)
    return report


def get_latest_rag_regression() -> Optional[Dict[str, Any]]:
    """Load the latest RAG regression report from disk."""
    path = Path(RAG_REGRESSION_PATH)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_with_context(logger, "warning", "Failed to read RAG regression report", error=str(e))
        return None
