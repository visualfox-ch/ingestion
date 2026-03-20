"""Metrics endpoints for observability and scientific health."""
from __future__ import annotations

import time
import os
import re
import requests
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from ..observability import get_logger
from .. import knowledge_db

logger = get_logger("jarvis.metrics")
router = APIRouter()

# =============================================================================
# DASHBOARD CACHE (30s TTL)
# =============================================================================
_dashboard_cache: Dict[str, Any] = {}
_dashboard_cache_time: float = 0
DASHBOARD_CACHE_TTL = 30  # seconds


@router.get("/metrics")
def get_metrics():
    """Get runtime metrics for observability including connection pools, LLM, RAG, and proactive stats"""
    from ..observability import metrics, embedding_cache, query_cache, llm_metrics, rag_metrics

    # Get base metrics
    base_metrics = {
        "metrics": metrics.get_stats(),
        "caches": {
            "embedding": embedding_cache.stats(),
            "query_rewrite": query_cache.stats()
        }
    }

    # Feature flags status (read-only snapshot)
    try:
        from .. import config
        base_metrics["feature_flags"] = {
            "enabled": config.FEATURE_FLAGS_ENABLED,
            "source": config.FEATURE_FLAGS_SOURCE,
            "defaults": config.FEATURE_FLAGS_DEFAULTS,
        }
    except Exception as e:
        logger.warning("Could not load feature flag config", extra={"error": str(e)})

    # Add connection pool stats
    try:
        pool_stats = knowledge_db.get_pool_stats()
        base_metrics["connection_pools"] = {
            "knowledge_db": pool_stats
        }
    except Exception as e:
        logger.warning("Could not get pool stats", extra={"error": str(e)})
        base_metrics["connection_pools"] = {"error": str(e)}

    # Add detailed LLM metrics (new LLMMetrics class)
    base_metrics["llm"] = llm_metrics.get_stats()

    # Add RAG quality metrics
    base_metrics["rag"] = rag_metrics.get_stats()

    # Add proactive intervention metrics
    try:
        from ..proactive_service import get_proactive_stats
        base_metrics["proactive"] = get_proactive_stats()
    except Exception as e:
        logger.warning("Could not get proactive stats", extra={"error": str(e)})

    return base_metrics


@router.get("/metrics/system")
def get_system_metrics():
    """
    System resource metrics for Jarvis components.

    Returns RAM, CPU, Disk usage for quick health checks.
    Detailed metrics available via Prometheus/Grafana (cAdvisor, Node Exporter).
    """
    import subprocess
    import resource
    from ..postgres_state import get_cursor

    result = {
        "process": {},
        "containers": [],
        "disk": {},
        "source_tracking": {}
    }

    # Process memory (this container)
    try:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        result["process"] = {
            "memory_mb": round(rusage.ru_maxrss / 1024, 2),
            "user_time_s": round(rusage.ru_utime, 2),
            "system_time_s": round(rusage.ru_stime, 2)
        }
    except Exception as e:
        result["process"] = {"error": str(e)}

    # Docker stats via docker CLI (if available)
    try:
        docker_cmd = "docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' 2>/dev/null || true"
        proc = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=10)
        if proc.stdout.strip():
            containers = []
            for line in proc.stdout.strip().split('\n'):
                parts = line.split(',')
                if len(parts) >= 4:
                    containers.append({
                        "name": parts[0],
                        "cpu": parts[1],
                        "memory": parts[2],
                        "memory_percent": parts[3]
                    })
            result["containers"] = containers
    except Exception as e:
        result["containers"] = {"error": str(e)}

    # Disk usage for BRAIN volume
    try:
        brain_root = os.environ.get("BRAIN_ROOT", "/brain")
        if os.path.exists(brain_root):
            stat = os.statvfs(brain_root)
            total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            used_gb = total_gb - free_gb
            result["disk"] = {
                "path": brain_root,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "used_percent": round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            }
    except Exception as e:
        result["disk"] = {"error": str(e)}

    # Source tracking stats (messages by source)
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT source, COUNT(*) as count
                FROM message
                WHERE source IS NOT NULL
                GROUP BY source
                ORDER BY count DESC
            """)
            rows = cur.fetchall()
            result["source_tracking"] = {row["source"]: row["count"] for row in rows}

            cur.execute("SELECT COUNT(*) as total FROM message")
            result["source_tracking"]["_total_messages"] = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) as legacy FROM message WHERE source IS NULL")
            result["source_tracking"]["_legacy_no_source"] = cur.fetchone()["legacy"]
    except Exception as e:
        result["source_tracking"] = {"error": str(e)}

    return result


@router.get("/metrics/dashboard")
def get_metrics_dashboard():
    """
    Get aggregated metrics dashboard for UI/Grafana.

    Returns a simplified view of key metrics with 30s caching.
    Designed for quick polling without overwhelming the system.

    Categories:
    - agent: Request counts, latency, error rates
    - llm: Token usage, costs, performance
    - system: Memory, disk, uptime
    - hot_config: Current runtime config values
    """
    global _dashboard_cache, _dashboard_cache_time

    # Return cached if fresh
    now = time.time()
    if _dashboard_cache and (now - _dashboard_cache_time) < DASHBOARD_CACHE_TTL:
        return _dashboard_cache

    from ..observability import llm_metrics, rag_metrics, metrics as obs_metrics

    dashboard: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cache_ttl_seconds": DASHBOARD_CACHE_TTL,
    }

    # ===== AGENT METRICS =====
    try:
        base_stats = obs_metrics.get_stats()
        llm_stats = llm_metrics.get_stats()
        llm_totals = llm_stats.get("totals", {})

        requests_total = llm_totals.get("requests", 0)
        errors_total = llm_totals.get("errors", 0)

        # Calculate average latency from LLM stats
        avg_latency_ms = None
        by_model = llm_stats.get("by_model", {})
        latencies = []
        for model_stats in by_model.values():
            if "latency" in model_stats and model_stats["latency"].get("avg_s"):
                latencies.append(model_stats["latency"]["avg_s"] * 1000)
        if latencies:
            avg_latency_ms = round(sum(latencies) / len(latencies), 1)

        # Tool success rate from RAG metrics
        rag_stats = rag_metrics.get_stats()
        tool_success_rate = 1.0 - rag_stats.get("empty_rate", 0)

        dashboard["agent"] = {
            "requests_total": requests_total,
            "avg_latency_ms": avg_latency_ms,
            "error_rate": round(errors_total / max(requests_total, 1), 4),
            "tool_success_rate": round(tool_success_rate, 4),
        }
    except Exception as e:
        logger.warning("Dashboard: Could not get agent metrics", extra={"error": str(e)})
        dashboard["agent"] = {"error": str(e)}

    # ===== LLM METRICS =====
    try:
        llm_stats = llm_metrics.get_stats()
        llm_totals = llm_stats.get("totals", {})

        total_tokens = llm_totals.get("input_tokens", 0) + llm_totals.get("output_tokens", 0)
        requests = llm_totals.get("requests", 1)

        dashboard["llm"] = {
            "tokens_total": total_tokens,
            "tokens_input": llm_totals.get("input_tokens", 0),
            "tokens_output": llm_totals.get("output_tokens", 0),
            "avg_tokens_per_request": round(total_tokens / max(requests, 1), 1),
            "cost_usd_total": round(llm_totals.get("cost_usd", 0), 4),
            "models_active": list(llm_stats.get("by_model", {}).keys()),
        }
    except Exception as e:
        logger.warning("Dashboard: Could not get LLM metrics", extra={"error": str(e)})
        dashboard["llm"] = {"error": str(e)}

    # ===== SYSTEM METRICS =====
    try:
        import psutil

        # Memory
        mem = psutil.virtual_memory()

        # Disk (check /brain mount if available, else /)
        disk_path = "/brain" if psutil.disk_usage("/brain") else "/"
        try:
            disk = psutil.disk_usage(disk_path)
        except Exception:
            disk = psutil.disk_usage("/")
            disk_path = "/"

        # Uptime (process start time)
        import os
        process = psutil.Process(os.getpid())
        uptime_seconds = time.time() - process.create_time()

        dashboard["system"] = {
            "memory_percent": round(mem.percent, 1),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": round(disk.percent, 1),
            "disk_path": disk_path,
            "uptime_seconds": round(uptime_seconds, 0),
            "uptime_hours": round(uptime_seconds / 3600, 2),
        }
    except Exception as e:
        logger.warning("Dashboard: Could not get system metrics", extra={"error": str(e)})
        dashboard["system"] = {"error": str(e)}

    # ===== HOT CONFIG =====
    try:
        from .. import hot_config

        dashboard["hot_config"] = {
            "proactive_level": hot_config.get_proactive_level(),
            "proactive_max_per_day": hot_config.get_proactive_max_per_day(),
            "confidence_cap": hot_config.get_confidence_cap(),
            "confidence_threshold": hot_config.get_confidence_threshold(),
            "agent_max_rounds": hot_config.get_agent_max_rounds(),
            "agent_timeout_seconds": hot_config.get_agent_timeout_seconds(),
            "log_level": hot_config.get_log_level(),
        }
    except Exception as e:
        logger.warning("Dashboard: Could not get hot config", extra={"error": str(e)})
        dashboard["hot_config"] = {"error": str(e)}

    # ===== PROACTIVE STATS =====
    try:
        from ..proactive_service import get_proactive_stats
        proactive = get_proactive_stats()
        dashboard["proactive"] = {
            "interventions_total": proactive.get("totals", {}).get("interventions", 0),
            "acceptance_rate": proactive.get("totals", {}).get("acceptance_rate"),
            "pending_count": proactive.get("pending_count", 0),
        }
    except Exception as e:
        dashboard["proactive"] = {"status": "not_available"}

    # Cache the result
    _dashboard_cache = dashboard
    _dashboard_cache_time = now

    return dashboard


@router.get("/metrics/prometheus")
def get_prometheus_metrics():
    """Export metrics in Prometheus format including LLM, RAG, proactive, and connection pools"""
    from ..connection_pool_metrics import export_all_pool_metrics
    from ..observability import llm_metrics, rag_metrics
    from prometheus_client import generate_latest, REGISTRY

    lines = []

    # Connection pool metrics
    try:
        pool_metrics_text = export_all_pool_metrics()
        lines.append(pool_metrics_text)
    except Exception as e:
        logger.warning("Could not export pool metrics", extra={"error": str(e)})

    # LLM performance metrics (TTFT, tokens/sec, costs, histograms)
    try:
        llm_prometheus = llm_metrics.get_prometheus_metrics()
        lines.append(llm_prometheus)
    except Exception as e:
        logger.warning("Could not export LLM metrics", extra={"error": str(e)})

    # RAG quality metrics
    try:
        rag_prometheus = rag_metrics.get_prometheus_metrics()
        lines.append(rag_prometheus)
    except Exception as e:
        logger.warning("Could not export RAG metrics", extra={"error": str(e)})

    # Proactive intervention metrics
    try:
        from ..proactive_service import get_proactive_prometheus
        proactive_prometheus = get_proactive_prometheus()
        lines.append(proactive_prometheus)
    except Exception as e:
        logger.warning("Could not export proactive metrics", extra={"error": str(e)})

    # Tool loop detection metrics (Phase 18.1)
    try:
        from ..observability import tool_loop_detector
        tool_loop_prometheus = tool_loop_detector.get_prometheus_metrics()
        lines.append(tool_loop_prometheus)
    except Exception as e:
        logger.warning("Could not export tool loop metrics", extra={"error": str(e)})

    # RAG Quality metrics from Langfuse traces (Tier 1 Evolution)
    try:
        from ..tool_modules.rag_quality_tools import get_prometheus_rag_metrics
        rag_quality_prometheus = get_prometheus_rag_metrics()
        lines.append(rag_quality_prometheus)
    except Exception as e:
        logger.warning("Could not export RAG quality metrics", extra={"error": str(e)})

    # Core Prometheus metrics registry (RED, fast-path, facette, etc.)
    try:
        registry_metrics = generate_latest(REGISTRY).decode("utf-8")
        lines.append(registry_metrics)
    except Exception as e:
        logger.warning("Could not export core Prometheus registry metrics", extra={"error": str(e)})

    from fastapi.responses import PlainTextResponse
    from prometheus_client import CONTENT_TYPE_LATEST
    return PlainTextResponse("\n".join(lines), media_type=CONTENT_TYPE_LATEST)


@router.get("/metrics/llm")
def get_llm_metrics():
    """Get detailed LLM performance metrics"""
    from ..observability import llm_metrics
    return llm_metrics.get_stats()


@router.get("/metrics/llm/summary")
def get_llm_summary():
    """Get a quick summary of LLM costs and performance for the current session"""
    from ..observability import llm_metrics

    stats = llm_metrics.get_stats()
    totals = stats.get("totals", {})
    by_model = stats.get("by_model", {})

    # Calculate averages across all models
    all_ttft = []
    all_latency = []
    all_tps = []

    for model_stats in by_model.values():
        if "ttft" in model_stats:
            all_ttft.append(model_stats["ttft"]["avg_s"])
        if "latency" in model_stats:
            all_latency.append(model_stats["latency"]["avg_s"])
        if "tokens_per_second" in model_stats:
            all_tps.append(model_stats["tokens_per_second"]["avg"])

    return {
        "session_uptime_seconds": stats.get("uptime_seconds", 0),
        "total_requests": totals.get("requests", 0),
        "total_errors": totals.get("errors", 0),
        "error_rate": totals.get("errors", 0) / max(totals.get("requests", 1), 1),
        "total_tokens": {
            "input": totals.get("input_tokens", 0),
            "output": totals.get("output_tokens", 0),
        },
        "total_cost_usd": totals.get("cost_usd", 0),
        "avg_ttft_seconds": sum(all_ttft) / len(all_ttft) if all_ttft else None,
        "avg_latency_seconds": sum(all_latency) / len(all_latency) if all_latency else None,
        "avg_tokens_per_second": sum(all_tps) / len(all_tps) if all_tps else None,
        "models_used": list(by_model.keys()),
    }


@router.get("/metrics/rag")
def get_rag_metrics():
    """Get RAG (Retrieval-Augmented Generation) quality metrics"""
    from ..observability import rag_metrics
    return rag_metrics.get_stats()


@router.get("/metrics/rag/quality")
def get_rag_quality_evaluation():
    """
    Get RAG quality evaluation from Langfuse traces.

    Evaluates faithfulness, relevance, and context utilization.
    """
    try:
        from ..tool_modules.rag_quality_tools import evaluate_rag_quality
        return evaluate_rag_quality(hours=24, limit=100)
    except Exception as e:
        logger.warning("Could not get RAG quality evaluation", extra={"error": str(e)})
        return {"error": str(e)}


@router.get("/metrics/rag/quality/issues")
def get_rag_quality_issues():
    """Get RAG quality issues and recommendations."""
    try:
        from ..tool_modules.rag_quality_tools import get_quality_issues
        return get_quality_issues(threshold=0.5)
    except Exception as e:
        logger.warning("Could not get RAG quality issues", extra={"error": str(e)})
        return {"error": str(e)}


@router.get("/metrics/rag/quality/prometheus")
def get_rag_quality_prometheus():
    """Export RAG quality metrics in Prometheus format."""
    from fastapi.responses import PlainTextResponse
    try:
        from ..tool_modules.rag_quality_tools import get_prometheus_rag_metrics
        return PlainTextResponse(get_prometheus_rag_metrics(), media_type="text/plain")
    except Exception as e:
        logger.warning("Could not get RAG quality prometheus metrics", extra={"error": str(e)})
        return PlainTextResponse(f"# Error: {e}", media_type="text/plain")


@router.get("/metrics/proactive")
def get_proactive_metrics():
    """Get proactive intervention metrics"""
    try:
        from ..proactive_service import get_proactive_stats
        return get_proactive_stats()
    except Exception as e:
        logger.warning("Could not get proactive stats", extra={"error": str(e)})
        return {"error": str(e)}


@router.get("/metrics/observability-summary")
def get_observability_summary():
    """Get a unified summary of all observability metrics for quick health check"""
    from ..observability import llm_metrics, rag_metrics

    llm_stats = llm_metrics.get_stats()
    rag_stats = rag_metrics.get_stats()
    llm_totals = llm_stats.get("totals", {})

    summary = {
        "llm": {
            "requests_total": llm_totals.get("requests", 0),
            "error_rate": llm_totals.get("errors", 0) / max(llm_totals.get("requests", 1), 1),
            "cost_usd_total": llm_totals.get("cost_usd", 0),
            "models_active": len(llm_stats.get("by_model", {})),
        },
        "rag": {
            "searches_total": rag_stats.get("searches_total", 0),
            "empty_rate": rag_stats.get("empty_rate", 0),
            "avg_relevance": rag_stats.get("relevance", {}).get("avg") if "relevance" in rag_stats else None,
        },
        "proactive": {"status": "not_loaded"},
    }

    # Add proactive stats if available
    try:
        from ..proactive_service import get_proactive_stats
        proactive_stats = get_proactive_stats()
        summary["proactive"] = {
            "interventions_total": proactive_stats.get("totals", {}).get("interventions", 0),
            "acceptance_rate": proactive_stats.get("totals", {}).get("acceptance_rate"),
            "pending_count": proactive_stats.get("pending_count", 0),
        }
    except Exception:
        pass

    return summary


@router.get("/metrics/scientific")
def get_scientific_metrics():
    """Comprehensive scientific metrics for Jarvis system health."""
    from .. import memory_store

    now = datetime.now()
    result = {
        "generated_at": now.isoformat(),
        "categories": {},
        "overall_health": 0.0,
        "recommendations": []
    }

    # ===== MEMORY HEALTH METRICS =====
    try:
        memory_stats = memory_store.get_memory_stats()
        trust_dist = memory_store.get_trust_distribution()

        total_facts = memory_stats.get("facts_total", 0)
        high_trust = trust_dist.get("high", 0)
        medium_trust = trust_dist.get("medium", 0)
        low_trust = trust_dist.get("low", 0)
        minimal_trust = trust_dist.get("minimal", 0)

        high_ratio = high_trust / total_facts if total_facts > 0 else 0
        medium_ratio = medium_trust / total_facts if total_facts > 0 else 0
        low_ratio = low_trust / total_facts if total_facts > 0 else 0

        result["categories"]["memory"] = {
            "health_score": 1.0,
            "metrics": {
                "facts_total": total_facts,
                "trust_distribution": {
                    "high": high_trust,
                    "medium": medium_trust,
                    "low": low_trust,
                    "minimal": minimal_trust
                },
                "ratios": {
                    "high": round(high_ratio, 3),
                    "medium": round(medium_ratio, 3),
                    "low": round(low_ratio, 3)
                }
            }
        }
    except Exception as e:
        result["categories"]["memory"] = {"error": str(e), "health_score": 0}

    # ===== KNOWLEDGE HEALTH METRICS =====
    try:
        profiles = knowledge_db.get_all_person_profiles(status="active")
        pending_reviews = 0
        total_versions = 0

        for p in profiles[:100]:
            versions = knowledge_db.get_profile_versions(p["person_id"], status="proposed")
            pending_reviews += len(versions)
            total_versions += 1

        fresh_profiles = 0
        for p in profiles:
            full = knowledge_db.get_person_profile(p["person_id"])
            if full:
                updated = full.get("updated_at", "")
                if updated:
                    try:
                        update_date = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        if (now - update_date.replace(tzinfo=None)).days < 30:
                            fresh_profiles += 1
                    except (ValueError, TypeError) as e:
                        logger.debug("Failed to parse profile updated_at", extra={"error": str(e)})

        profile_count = len(profiles)
        freshness_ratio = fresh_profiles / profile_count if profile_count > 0 else 0

        knowledge_health = 1.0
        if pending_reviews > 10:
            knowledge_health -= 0.2
            result["recommendations"].append(f"Process {pending_reviews} pending profile reviews")
        if freshness_ratio < 0.3:
            knowledge_health -= 0.2
            result["recommendations"].append("Knowledge becoming stale - update person profiles")

        result["categories"]["knowledge"] = {
            "health_score": max(0, min(1, knowledge_health)),
            "metrics": {
                "active_profiles": profile_count,
                "pending_reviews": pending_reviews,
                "fresh_profiles_30d": fresh_profiles,
                "freshness_ratio": round(freshness_ratio, 3)
            },
            "thresholds": {
                "max_pending_reviews": 10,
                "min_freshness_ratio": 0.30,
                "review_sla_days": 7
            }
        }
    except Exception as e:
        result["categories"]["knowledge"] = {"error": str(e), "health_score": 0}

    return result


# =============================================================================
# Prometheus allowlisted query endpoints (read-only)
# =============================================================================
PROMETHEUS_DEFAULT_URL = "http://prometheus:9090"
PROMETHEUS_TIMEOUT_SECONDS = float(os.getenv("JARVIS_PROMETHEUS_TIMEOUT", "3"))

PROMETHEUS_ALLOWLIST = {
    "up_jarvis": {
        "query": 'up{job="jarvis-api"}',
        "description": "Jarvis ingestion up"
    },
    "up_prometheus": {
        "query": 'up{job="prometheus"}',
        "description": "Prometheus up"
    },
    "up_n8n": {
        "query": 'up{job="n8n"}',
        "description": "n8n up"
    },
    "up_postgres": {
        "query": 'up{job="postgres"}',
        "description": "Postgres exporter up"
    },
    "up_qdrant": {
        "query": 'up{job="qdrant"}',
        "description": "Qdrant up"
    },
    "up_meilisearch": {
        "query": 'up{job="meilisearch"}',
        "description": "Meilisearch up"
    },
    "db_pool_in_use": {
        "query": 'jarvis_db_pool_in_use',
        "description": "DB pool connections in use"
    },
    "db_pool_wait_p95_seconds": {
        "query": 'jarvis_db_pool_wait_time_p95_seconds',
        "description": "DB pool wait time p95 (seconds)"
    },
    "tool_loops_total": {
        "query": 'jarvis_tool_loops_total',
        "description": "Tool loop detections (total)"
    },
    "tool_loops_rate": {
        "query": 'rate(jarvis_tool_loops_total[{window}])',
        "description": "Tool loop detection rate"
    },
    "agent_requests_total": {
        "query": 'red_agent_requests_total',
        "description": "Agent requests total"
    },
    "agent_request_rate": {
        "query": 'rate(red_agent_requests_total[{window}])',
        "description": "Agent request rate"
    },
    "agent_p95_seconds": {
        "query": 'histogram_quantile(0.95, sum(rate(red_agent_duration_seconds_bucket[{window}])) by (le))',
        "description": "Agent duration p95 (seconds)"
    },
    "agent_p99_seconds": {
        "query": 'histogram_quantile(0.99, sum(rate(red_agent_duration_seconds_bucket[{window}])) by (le))',
        "description": "Agent duration p99 (seconds)"
    },
    "db_query_p95_seconds": {
        "query": 'histogram_quantile(0.95, sum(rate(remediation_database_query_seconds_bucket[{window}])) by (le))',
        "description": "DB query p95 (seconds)"
    },
    "llm_requests_total": {
        "query": 'sum(jarvis_llm_requests_total)',
        "description": "LLM requests total"
    },
    "llm_errors_total": {
        "query": 'sum(jarvis_llm_errors_total)',
        "description": "LLM errors total"
    },
    "llm_cost_usd_total": {
        "query": 'sum(jarvis_llm_cost_usd_total)',
        "description": "LLM cost total (USD)"
    },
    "autonomous_actions_total": {
        "query": 'sum(jarvis_autonomous_actions_total)',
        "description": "Autonomy actions total"
    },
    "autonomous_actions_rate": {
        "query": 'rate(jarvis_autonomous_actions_total[{window}])',
        "description": "Autonomy actions rate"
    },
    "autonomous_approvals_total": {
        "query": 'sum(jarvis_autonomous_approval_decisions_total)',
        "description": "Autonomy approval decisions total"
    },
    "autonomous_approval_latency_p95_seconds": {
        "query": 'histogram_quantile(0.95, sum(rate(jarvis_autonomous_approval_latency_seconds_bucket[{window}])) by (le))',
        "description": "Autonomy approval latency p95 (seconds)"
    },
    "autonomous_errors_total": {
        "query": 'sum(jarvis_autonomous_errors_total)',
        "description": "Autonomy processing errors total"
    },
    "autonomous_rollbacks_total": {
        "query": 'sum(jarvis_autonomous_rollbacks_total)',
        "description": "Autonomy rollbacks total"
    },
}


def _resolve_prometheus_url() -> str:
    env_url = os.getenv("JARVIS_PROMETHEUS_URL")
    if env_url:
        return env_url.rstrip("/")
    return PROMETHEUS_DEFAULT_URL


def _parse_duration_to_seconds(value: str) -> int:
    if not value:
        return 0
    match = re.match(r"^(\d+)([smhd])$", value.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Invalid duration. Use 30s/5m/1h/1d format.")
    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return amount * multipliers[unit]


def _build_promql(key: str, window: str | None) -> str:
    if key not in PROMETHEUS_ALLOWLIST:
        raise HTTPException(status_code=400, detail="Unknown key. Use /monitoring/prometheus/keys for allowlist.")
    template = PROMETHEUS_ALLOWLIST[key]["query"]
    if "{window}" in template:
        win = window or "5m"
        _parse_duration_to_seconds(win)
        return template.format(window=win)
    return template


@router.get("/monitoring/prometheus/keys")
def get_prometheus_allowlist_keys():
    return {
        "base_url": _resolve_prometheus_url(),
        "timeout_seconds": PROMETHEUS_TIMEOUT_SECONDS,
        "keys": {
            k: {
                "description": v.get("description"),
                "query_template": v.get("query"),
                "requires_window": "{window}" in v.get("query", "")
            }
            for k, v in sorted(PROMETHEUS_ALLOWLIST.items())
        }
    }


@router.get("/monitoring/prometheus/query")
def query_prometheus(
    key: str,
    window: str | None = None,
    range: str | None = None,
    step: str | None = None,
):
    promql = _build_promql(key, window)
    base_url = _resolve_prometheus_url()

    if range:
        seconds = _parse_duration_to_seconds(range)
        end_time = time.time()
        start_time = end_time - seconds
        url = f"{base_url}/api/v1/query_range"
        params = {
            "query": promql,
            "start": start_time,
            "end": end_time,
            "step": step or "30s",
        }
    else:
        url = f"{base_url}/api/v1/query"
        params = {"query": promql}

    try:
        response = requests.get(url, params=params, timeout=PROMETHEUS_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Prometheus query timeout")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Prometheus query failed: {exc}")

    data = response.json()
    if data.get("status") != "success":
        raise HTTPException(status_code=502, detail="Prometheus returned non-success response")

    result = data.get("data", {}).get("result", [])
    return {
        "key": key,
        "query": promql,
        "range": range,
        "step": params.get("step"),
        "resultType": data.get("data", {}).get("resultType"),
        "result": result,
    }


# =============================================================================
# LANGFUSE SESSION COSTS (AI Dev Ops Integration)
# =============================================================================

@router.get("/langfuse/session-costs")
def get_langfuse_session_costs(session_id: str, limit: int = 100):
    """
    Get LLM costs for a specific session from Langfuse.

    Used by VS Code AI Dev Ops to track costs per Claude Code session.
    """
    from ..langfuse_integration import get_session_costs
    return get_session_costs(session_id, limit)


@router.get("/langfuse/recent-sessions")
def get_langfuse_recent_sessions(hours: int = 24, limit: int = 20):
    """
    Get costs for recent sessions from Langfuse.

    Returns sessions sorted by cost (highest first).
    """
    from ..langfuse_integration import get_recent_sessions_costs
    return get_recent_sessions_costs(hours, limit)


@router.get("/langfuse/status")
def get_langfuse_integration_status():
    """Get Langfuse integration status."""
    from ..langfuse_integration import get_langfuse_status
    return get_langfuse_status()
