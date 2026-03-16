"""
RAG Quality Evaluator - Tier 1 Evolution (#3)

Evaluates RAG quality by analyzing Langfuse traces:
- Faithfulness: Is the answer grounded in retrieved context?
- Relevance: Is retrieved context relevant to the query?
- Context-Utilization: How well was the context used?

Aggregates metrics by domain/collection and exports to Prometheus.
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# Langfuse API Configuration
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

# Quality thresholds
QUALITY_THRESHOLDS = {
    "faithfulness": {"good": 0.8, "acceptable": 0.6},
    "relevance": {"good": 0.7, "acceptable": 0.5},
    "context_utilization": {"good": 0.6, "acceptable": 0.4},
}

# Prometheus metrics storage (in-memory, exported periodically)
_rag_quality_metrics = {
    "evaluations": [],
    "aggregated": {},
    "last_updated": None
}


def _get_langfuse_auth() -> tuple:
    """Get Langfuse API authentication."""
    return (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)


def _fetch_recent_traces(
    hours: int = 24,
    limit: int = 100,
    trace_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch recent traces from Langfuse API."""
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse credentials not configured")
        return []

    try:
        # Langfuse API endpoint for traces
        url = f"{LANGFUSE_HOST}/api/public/traces"

        # Calculate time window
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        params = {
            "limit": limit,
            "orderBy": "timestamp",
            "order": "desc"
        }

        if trace_name:
            params["name"] = trace_name

        response = requests.get(
            url,
            params=params,
            auth=_get_langfuse_auth(),
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            traces = data.get("data", [])

            # Filter by time window
            filtered = []
            for trace in traces:
                trace_time = trace.get("timestamp", "")
                if trace_time:
                    try:
                        dt = datetime.fromisoformat(trace_time.replace("Z", "+00:00"))
                        if dt.replace(tzinfo=None) >= start_time:
                            filtered.append(trace)
                    except Exception:
                        filtered.append(trace)  # Include if can't parse

            return filtered
        else:
            logger.error(f"Langfuse API error: {response.status_code} - {response.text}")
            return []

    except requests.exceptions.ConnectionError:
        logger.warning(f"Cannot connect to Langfuse at {LANGFUSE_HOST}")
        return []
    except Exception as e:
        logger.error(f"Error fetching Langfuse traces: {e}")
        return []


def _extract_rag_data(trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract RAG-relevant data from a trace."""
    try:
        metadata = trace.get("metadata", {}) or {}
        input_data = trace.get("input", {}) or {}
        output = trace.get("output", "")

        # Look for context chunks in metadata
        context_chunks = metadata.get("context_chunks", 0)

        # Look for query
        query = ""
        if isinstance(input_data, dict):
            query = input_data.get("query", input_data.get("prompt", ""))
        elif isinstance(input_data, str):
            query = input_data

        # Skip if no query or no context
        if not query or context_chunks == 0:
            return None

        return {
            "trace_id": trace.get("id"),
            "timestamp": trace.get("timestamp"),
            "query": query[:500],
            "output": str(output)[:1000] if output else "",
            "context_chunks": context_chunks,
            "model": trace.get("model") or metadata.get("model", "unknown"),
            "user_id": trace.get("userId"),
            "tags": trace.get("tags", []),
            "duration_ms": metadata.get("duration_ms"),
            "domain": _extract_domain(metadata, trace.get("tags", []))
        }
    except Exception as e:
        logger.debug(f"Error extracting RAG data: {e}")
        return None


def _extract_domain(metadata: Dict, tags: List[str]) -> str:
    """Extract domain/collection from metadata or tags."""
    # Check metadata
    if "domain" in metadata:
        return metadata["domain"]
    if "collection" in metadata:
        return metadata["collection"]
    if "namespace" in metadata:
        return metadata["namespace"]

    # Check tags for domain hints
    domain_tags = [t for t in tags if t not in ["jarvis", "chat", "production"]]
    if domain_tags:
        return domain_tags[0]

    return "default"


def _calculate_faithfulness(query: str, output: str, context_chunks: int) -> float:
    """
    Estimate faithfulness score (0-1).

    Faithfulness = degree to which answer is grounded in retrieved context.
    This is a heuristic - for full accuracy, would need to compare against actual context.
    """
    if not output or context_chunks == 0:
        return 0.0

    # Heuristics based on response characteristics
    score = 0.5  # Base score

    # Longer responses with context tend to be more faithful
    if len(output) > 100 and context_chunks > 0:
        score += 0.1

    # Multiple context chunks suggest better grounding
    if context_chunks >= 3:
        score += 0.2
    elif context_chunks >= 2:
        score += 0.1

    # Check for hedging language (uncertain responses)
    hedging = ["i'm not sure", "i don't know", "unclear", "can't find"]
    if any(h in output.lower() for h in hedging):
        score -= 0.2

    # Check for citation/reference patterns
    citation = ["according to", "based on", "from the", "the document", "it says"]
    if any(c in output.lower() for c in citation):
        score += 0.15

    return max(0.0, min(1.0, score))


def _calculate_relevance(query: str, output: str, context_chunks: int) -> float:
    """
    Estimate context relevance score (0-1).

    Relevance = how relevant the retrieved context was to the query.
    """
    if not query or context_chunks == 0:
        return 0.0

    score = 0.5

    # More context chunks retrieved = better retrieval (up to a point)
    if context_chunks >= 5:
        score += 0.25
    elif context_chunks >= 3:
        score += 0.15
    elif context_chunks >= 1:
        score += 0.05

    # Check if response addresses the query (simple keyword overlap)
    query_words = set(query.lower().split())
    output_words = set(output.lower().split())
    overlap = len(query_words & output_words) / max(len(query_words), 1)
    score += overlap * 0.2

    # Response length relative to query complexity
    if len(output) > len(query) * 2:
        score += 0.1

    return max(0.0, min(1.0, score))


def _calculate_context_utilization(query: str, output: str, context_chunks: int) -> float:
    """
    Estimate context utilization score (0-1).

    Context-Utilization = how effectively the retrieved context was used.
    """
    if context_chunks == 0:
        return 0.0

    if not output:
        return 0.0

    score = 0.4

    # Response density relative to context
    expected_min_length = context_chunks * 20  # Rough heuristic
    if len(output) >= expected_min_length:
        score += 0.2

    # Check for synthesized response (not just copying)
    synthesis_markers = ["therefore", "this means", "in summary", "zusammenfassend", "overall"]
    if any(m in output.lower() for m in synthesis_markers):
        score += 0.2

    # Good utilization often includes specific details
    if any(char.isdigit() for char in output):  # Contains numbers
        score += 0.1

    # Multiple sentences suggest good context use
    sentences = output.count(". ") + output.count("? ") + output.count("! ")
    if sentences >= 3:
        score += 0.15
    elif sentences >= 2:
        score += 0.05

    return max(0.0, min(1.0, score))


def evaluate_rag_quality(
    hours: int = 24,
    limit: int = 100,
    trace_name: Optional[str] = "jarvis-chat"
) -> Dict[str, Any]:
    """
    Evaluate RAG quality from recent Langfuse traces.

    Args:
        hours: Time window in hours
        limit: Maximum traces to analyze
        trace_name: Filter by trace name

    Returns:
        Dict with evaluation results and metrics
    """
    traces = _fetch_recent_traces(hours=hours, limit=limit, trace_name=trace_name)

    if not traces:
        return {
            "success": True,
            "warning": "No traces found or Langfuse not available",
            "traces_analyzed": 0,
            "time_window_hours": hours
        }

    evaluations = []
    domain_metrics = defaultdict(lambda: {
        "faithfulness": [], "relevance": [], "context_utilization": [],
        "count": 0
    })

    for trace in traces:
        rag_data = _extract_rag_data(trace)
        if not rag_data:
            continue

        # Calculate quality scores
        faithfulness = _calculate_faithfulness(
            rag_data["query"], rag_data["output"], rag_data["context_chunks"]
        )
        relevance = _calculate_relevance(
            rag_data["query"], rag_data["output"], rag_data["context_chunks"]
        )
        context_util = _calculate_context_utilization(
            rag_data["query"], rag_data["output"], rag_data["context_chunks"]
        )

        evaluation = {
            "trace_id": rag_data["trace_id"],
            "timestamp": rag_data["timestamp"],
            "domain": rag_data["domain"],
            "model": rag_data["model"],
            "context_chunks": rag_data["context_chunks"],
            "faithfulness": round(faithfulness, 3),
            "relevance": round(relevance, 3),
            "context_utilization": round(context_util, 3),
            "overall_score": round((faithfulness + relevance + context_util) / 3, 3)
        }

        evaluations.append(evaluation)

        # Aggregate by domain
        domain = rag_data["domain"]
        domain_metrics[domain]["faithfulness"].append(faithfulness)
        domain_metrics[domain]["relevance"].append(relevance)
        domain_metrics[domain]["context_utilization"].append(context_util)
        domain_metrics[domain]["count"] += 1

    # Calculate aggregated metrics
    aggregated = {}
    for domain, metrics in domain_metrics.items():
        aggregated[domain] = {
            "count": metrics["count"],
            "faithfulness_avg": round(
                sum(metrics["faithfulness"]) / len(metrics["faithfulness"]), 3
            ) if metrics["faithfulness"] else 0,
            "relevance_avg": round(
                sum(metrics["relevance"]) / len(metrics["relevance"]), 3
            ) if metrics["relevance"] else 0,
            "context_utilization_avg": round(
                sum(metrics["context_utilization"]) / len(metrics["context_utilization"]), 3
            ) if metrics["context_utilization"] else 0,
        }
        # Calculate overall average
        aggregated[domain]["overall_avg"] = round(
            (aggregated[domain]["faithfulness_avg"] +
             aggregated[domain]["relevance_avg"] +
             aggregated[domain]["context_utilization_avg"]) / 3, 3
        )

        # Quality classification
        overall = aggregated[domain]["overall_avg"]
        if overall >= 0.7:
            aggregated[domain]["quality"] = "good"
        elif overall >= 0.5:
            aggregated[domain]["quality"] = "acceptable"
        else:
            aggregated[domain]["quality"] = "needs_improvement"

    # Store for Prometheus export
    global _rag_quality_metrics
    _rag_quality_metrics = {
        "evaluations": evaluations[-100:],  # Keep last 100
        "aggregated": aggregated,
        "last_updated": datetime.now().isoformat()
    }

    # Calculate global averages
    all_faithfulness = [e["faithfulness"] for e in evaluations]
    all_relevance = [e["relevance"] for e in evaluations]
    all_context_util = [e["context_utilization"] for e in evaluations]

    global_avg = {
        "faithfulness": round(sum(all_faithfulness) / len(all_faithfulness), 3) if all_faithfulness else 0,
        "relevance": round(sum(all_relevance) / len(all_relevance), 3) if all_relevance else 0,
        "context_utilization": round(sum(all_context_util) / len(all_context_util), 3) if all_context_util else 0,
    }
    global_avg["overall"] = round(
        (global_avg["faithfulness"] + global_avg["relevance"] + global_avg["context_utilization"]) / 3, 3
    )

    return {
        "success": True,
        "time_window_hours": hours,
        "traces_analyzed": len(evaluations),
        "global_averages": global_avg,
        "by_domain": aggregated,
        "thresholds": QUALITY_THRESHOLDS,
        "sample_evaluations": evaluations[:5],  # Sample
        "last_updated": _rag_quality_metrics["last_updated"]
    }


def get_rag_quality_metrics() -> Dict[str, Any]:
    """
    Get cached RAG quality metrics (for Prometheus export).

    Returns:
        Dict with current metrics and staleness info
    """
    global _rag_quality_metrics

    last_updated = _rag_quality_metrics.get("last_updated")
    staleness_minutes = None

    if last_updated:
        try:
            last_dt = datetime.fromisoformat(last_updated)
            staleness_minutes = (datetime.now() - last_dt).total_seconds() / 60
        except Exception:
            pass

    return {
        "success": True,
        "aggregated": _rag_quality_metrics.get("aggregated", {}),
        "evaluation_count": len(_rag_quality_metrics.get("evaluations", [])),
        "last_updated": last_updated,
        "staleness_minutes": round(staleness_minutes, 1) if staleness_minutes else None,
        "is_stale": staleness_minutes > 30 if staleness_minutes else True
    }


def get_prometheus_rag_metrics() -> str:
    """
    Export RAG quality metrics in Prometheus format.

    Returns:
        String with Prometheus-compatible metrics
    """
    global _rag_quality_metrics

    lines = [
        "# HELP jarvis_rag_faithfulness RAG faithfulness score (0-1)",
        "# TYPE jarvis_rag_faithfulness gauge",
        "# HELP jarvis_rag_relevance RAG relevance score (0-1)",
        "# TYPE jarvis_rag_relevance gauge",
        "# HELP jarvis_rag_context_utilization RAG context utilization score (0-1)",
        "# TYPE jarvis_rag_context_utilization gauge",
        "# HELP jarvis_rag_overall RAG overall quality score (0-1)",
        "# TYPE jarvis_rag_overall gauge",
        "# HELP jarvis_rag_evaluations_total Total RAG evaluations per domain",
        "# TYPE jarvis_rag_evaluations_total counter",
    ]

    aggregated = _rag_quality_metrics.get("aggregated", {})

    for domain, metrics in aggregated.items():
        domain_label = domain.replace('"', '\\"')
        lines.append(f'jarvis_rag_faithfulness{{domain="{domain_label}"}} {metrics.get("faithfulness_avg", 0)}')
        lines.append(f'jarvis_rag_relevance{{domain="{domain_label}"}} {metrics.get("relevance_avg", 0)}')
        lines.append(f'jarvis_rag_context_utilization{{domain="{domain_label}"}} {metrics.get("context_utilization_avg", 0)}')
        lines.append(f'jarvis_rag_overall{{domain="{domain_label}"}} {metrics.get("overall_avg", 0)}')
        lines.append(f'jarvis_rag_evaluations_total{{domain="{domain_label}"}} {metrics.get("count", 0)}')

    return "\n".join(lines)


def get_quality_issues(
    threshold: float = 0.5
) -> Dict[str, Any]:
    """
    Identify domains/traces with quality issues.

    Args:
        threshold: Quality score below which to flag as issue

    Returns:
        Dict with problematic domains and recent low-quality traces
    """
    global _rag_quality_metrics

    issues = {
        "low_quality_domains": [],
        "recent_low_quality_traces": [],
        "recommendations": []
    }

    # Check domain averages
    for domain, metrics in _rag_quality_metrics.get("aggregated", {}).items():
        overall = metrics.get("overall_avg", 0)
        if overall < threshold:
            issues["low_quality_domains"].append({
                "domain": domain,
                "overall_score": overall,
                "faithfulness": metrics.get("faithfulness_avg"),
                "relevance": metrics.get("relevance_avg"),
                "context_utilization": metrics.get("context_utilization_avg"),
                "count": metrics.get("count")
            })

    # Find recent low-quality traces
    for evaluation in _rag_quality_metrics.get("evaluations", []):
        if evaluation.get("overall_score", 1) < threshold:
            issues["recent_low_quality_traces"].append({
                "trace_id": evaluation.get("trace_id"),
                "domain": evaluation.get("domain"),
                "overall_score": evaluation.get("overall_score"),
                "timestamp": evaluation.get("timestamp")
            })

    # Generate recommendations
    if issues["low_quality_domains"]:
        for domain_issue in issues["low_quality_domains"]:
            if domain_issue.get("relevance", 1) < 0.5:
                issues["recommendations"].append(
                    f"Domain '{domain_issue['domain']}': Low relevance - consider improving retrieval (embeddings, chunking)"
                )
            if domain_issue.get("faithfulness", 1) < 0.5:
                issues["recommendations"].append(
                    f"Domain '{domain_issue['domain']}': Low faithfulness - check for hallucination, add grounding"
                )
            if domain_issue.get("context_utilization", 1) < 0.4:
                issues["recommendations"].append(
                    f"Domain '{domain_issue['domain']}': Low context utilization - review prompt engineering"
                )

    issues["issues_found"] = len(issues["low_quality_domains"]) + len(issues["recent_low_quality_traces"])

    return {
        "success": True,
        "threshold": threshold,
        **issues
    }


# Tool definitions for Claude (JSON-serializable)
RAG_QUALITY_TOOLS = [
    {
        "name": "evaluate_rag_quality",
        "description": "Evaluate RAG quality from recent Langfuse traces. Calculates faithfulness, relevance, and context utilization metrics aggregated by domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "default": 24,
                    "description": "Time window in hours to analyze"
                },
                "limit": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum traces to analyze"
                },
                "trace_name": {
                    "type": "string",
                    "default": "jarvis-chat",
                    "description": "Filter by trace name"
                }
            }
        }
    },
    {
        "name": "get_rag_quality_metrics",
        "description": "Get cached RAG quality metrics (for monitoring dashboards). Returns aggregated scores and staleness info.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_prometheus_rag_metrics",
        "description": "Export RAG quality metrics in Prometheus format for Grafana.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_quality_issues",
        "description": "Identify domains and traces with RAG quality issues below threshold.",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Quality score threshold (0-1)"
                }
            }
        }
    }
]
