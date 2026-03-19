"""Health and internal status endpoints."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import requests
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from ..observability import get_logger, log_with_context, get_recent_log_events
from ..ssh_client import get_container_logs
from ..auth import auth_dependency
from ..state import global_state
from .. import knowledge_db, postgres_state, meilisearch_client, config

logger = get_logger("jarvis.health")
router = APIRouter()

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
PARSED_DIR = BRAIN_ROOT / "parsed"

LOG_TAIL_COOLDOWN_SECONDS = int(os.environ.get("JARVIS_LOG_TAIL_COOLDOWN_SECONDS", "5"))
_log_tail_rate_limit: Dict[str, float] = {}
LOG_TAIL_IP_ALLOWLIST = [
    ip.strip() for ip in os.environ.get("JARVIS_LOG_TAIL_IP_ALLOWLIST", "").split(",") if ip.strip()
]
LOG_TAIL_REQUIRE_HTTPS = os.environ.get("JARVIS_LOG_TAIL_REQUIRE_HTTPS", "false").lower() in (
    "1", "true", "yes", "on"
)


def _redact_logs(text: str) -> str:
    """Redact common secrets from log output."""
    patterns = [
        (r"(Authorization:\s*Bearer\s+)([^\s]+)", r"\1<redacted>"),
        (r"(api[_-]?key\s*[:=]\s*)([^\s,]+)", r"\1<redacted>"),
        (r"(token\s*[:=]\s*)([^\s,]+)", r"\1<redacted>"),
        (r"(secret\s*[:=]\s*)([^\s,]+)", r"\1<redacted>"),
        (r"(password\s*[:=]\s*)([^\s,]+)", r"\1<redacted>"),
    ]

    redacted = text
    for pattern, repl in patterns:
        redacted = re.sub(pattern, repl, redacted, flags=re.IGNORECASE)
    return redacted


def _filter_log_lines(text: str, level: str) -> str:
    """Filter log lines by minimum severity level."""
    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    level = level.upper()
    if level not in levels:
        return text

    min_index = levels.index(level)
    allowed = set(levels[min_index:])
    lines = []
    for line in text.splitlines():
        if any(lvl in line for lvl in allowed):
            lines.append(line)
    return "\n".join(lines)


def _check_qdrant_ready() -> tuple[bool, Dict[str, Any]]:
    """Fast Qdrant readiness check."""
    try:
        from qdrant_client import QdrantClient

        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=3)
        collections = client.get_collections()
        return True, {
            "status": "healthy",
            "collections": len(collections.collections),
            "host": f"{qdrant_host}:{qdrant_port}",
        }
    except Exception as e:
        return False, {"status": "unhealthy", "error": str(e)}


def _check_postgres_ready() -> tuple[bool, Dict[str, Any]]:
    """Fast Postgres readiness check."""
    try:
        if knowledge_db.is_available():
            return True, {"status": "healthy", "database": "jarvis"}
        return False, {"status": "unhealthy", "error": "Connection failed"}
    except Exception as e:
        return False, {"status": "unhealthy", "error": str(e)}


def _check_sqlite_ready() -> tuple[bool, Dict[str, Any]]:
    """Fast SQLite readiness check."""
    try:
        from .. import state_db

        state_db.list_sessions(limit=1)
        return True, {"status": "healthy", "database": "jarvis_state.db"}
    except Exception as e:
        return False, {"status": "unhealthy", "error": str(e)}


def _check_meilisearch_ready() -> tuple[bool, Dict[str, Any]]:
    """Fast Meilisearch readiness check (warn-only for overall readiness)."""
    try:
        meili_health = meilisearch_client.health_check()
        status = meili_health.get("status", "unknown")
        is_healthy = status in {"healthy", "available"}
        return is_healthy, meili_health
    except Exception as e:
        return False, {"status": "warning", "error": str(e)}


def _collect_readiness_checks() -> tuple[bool, Dict[str, Any]]:
    """Collect lightweight readiness checks for deploys and health probes."""
    checks: Dict[str, Any] = {}
    overall_ready = True

    startup = global_state.get_startup_state()
    startup_ready = bool(startup.get("ready"))
    checks["startup"] = {
        "status": "healthy" if startup_ready else "starting",
        **startup,
    }
    if not startup_ready:
        overall_ready = False

    draining = global_state.get_pool_draining()
    checks["request_acceptance"] = {
        "status": "draining" if draining else "healthy",
        "draining": draining,
    }
    if draining:
        overall_ready = False

    qdrant_ok, qdrant_payload = _check_qdrant_ready()
    checks["qdrant"] = qdrant_payload
    overall_ready = overall_ready and qdrant_ok

    postgres_ok, postgres_payload = _check_postgres_ready()
    checks["postgres"] = postgres_payload
    overall_ready = overall_ready and postgres_ok

    sqlite_ok, sqlite_payload = _check_sqlite_ready()
    checks["sqlite"] = sqlite_payload
    overall_ready = overall_ready and sqlite_ok

    meili_ok, meili_payload = _check_meilisearch_ready()
    checks["meilisearch"] = meili_payload
    checks["meilisearch"]["blocks_readiness"] = False
    checks["meilisearch"]["healthy"] = meili_ok

    return overall_ready, checks


@router.get("/livez")
def livez():
    """Cheap liveness probe: process is serving HTTP."""
    startup = global_state.get_startup_state()
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "startup": startup,
        "draining": global_state.get_pool_draining(),
    }


@router.get("/readyz")
def readyz():
    """Lightweight readiness probe for deploys and container health checks."""
    overall_ready, checks = _collect_readiness_checks()
    status_code = 200 if overall_ready else 503
    payload = {
        "status": "ready" if overall_ready else "not_ready",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "healthy": len([c for c in checks.values() if c.get("status") == "healthy"]),
            "non_healthy": len([c for c in checks.values() if c.get("status") != "healthy"]),
        },
    }
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/health")
def health_check():
    """
    Comprehensive health check for all Jarvis services.
    Returns status of each component and overall system health.
    """
    from datetime import datetime as dt
    start = time.time()
    checks: Dict[str, Any] = {}
    overall_healthy = True

    # 1. Qdrant check
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=5)
        collections = client.get_collections()
        checks["qdrant"] = {
            "status": "healthy",
            "collections": len(collections.collections),
            "host": f"{qdrant_host}:{qdrant_port}"
        }
    except Exception as e:
        checks["qdrant"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 2. Postgres check (Knowledge Layer)
    try:
        if knowledge_db.is_available():
            checks["postgres"] = {"status": "healthy", "database": "jarvis"}
        else:
            checks["postgres"] = {"status": "unhealthy", "error": "Connection failed"}
            overall_healthy = False
    except Exception as e:
        checks["postgres"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 3. SQLite state database check
    try:
        from .. import state_db
        state_db.list_sessions(limit=1)
        checks["sqlite"] = {"status": "healthy", "database": "jarvis_state.db"}
    except Exception as e:
        checks["sqlite"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 4. Meilisearch check (keyword search)
    try:
        meili_health = meilisearch_client.health_check()
        checks["meilisearch"] = meili_health
    except Exception as e:
        checks["meilisearch"] = {"status": "unavailable", "error": str(e)}

    # 5. LLM Providers check (Anthropic + OpenAI)
    try:
        from ..llm import get_llm_factory
        factory = get_llm_factory()
        provider_stats = factory.get_provider_stats()
        checks["llm_providers"] = provider_stats
    except Exception as e:
        checks["llm_providers"] = {"status": "error", "error": str(e)}

    # 6. Telegram bot check
    try:
        from ..telegram_bot import get_bot_status
        checks["telegram_bot"] = get_bot_status()
    except Exception as e:
        checks["telegram_bot"] = {"status": "unknown", "error": str(e)}

    # 7. Scheduler check
    try:
        from ..scheduler import get_scheduler_status
        checks["scheduler"] = get_scheduler_status()
    except Exception as e:
        checks["scheduler"] = {"status": "unknown", "error": str(e)}

    # 8. n8n Gateway check (Google API)
    try:
        from ..n8n_client import is_n8n_available, N8N_HOST, N8N_PORT
        if is_n8n_available():
            checks["n8n_gateway"] = {
                "status": "healthy",
                "host": f"{N8N_HOST}:{N8N_PORT}",
                "services": ["calendar", "gmail"]
            }
        else:
            checks["n8n_gateway"] = {
                "status": "unavailable",
                "host": f"{N8N_HOST}:{N8N_PORT}"
            }
    except Exception as e:
        checks["n8n_gateway"] = {"status": "unknown", "error": str(e)}

    # 9. Embedding model check
    try:
        from ..embed import get_model, MODEL_NAME
        model = get_model()
        checks["embedding_model"] = {
            "status": "healthy",
            "model": MODEL_NAME,
            "loaded": model is not None
        }
    except Exception as e:
        checks["embedding_model"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 10. Follow-up tracking check
    try:
        from .. import state_db
        stats = state_db.get_followup_stats()
        overdue = stats.get("overdue", 0)
        checks["followups"] = {
            "status": "warning" if overdue > 0 else "healthy",
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "overdue": overdue
        }
    except Exception as e:
        checks["followups"] = {"status": "unknown", "error": str(e)}

    # 11. Resource snapshot (visibility + load shedding decisions; does not fail overall)
    try:
        from ..resource_guards import get_resource_snapshot
        snap = get_resource_snapshot()
        mem_p = float(snap.get("memory_percent", 0))
        disk_p = float(snap.get("disk_percent", 0))
        mem_thr = float(snap.get("thresholds", {}).get("mem_reject_percent", 0))
        disk_thr = float(snap.get("thresholds", {}).get("disk_reject_percent", 0))
        checks["resources"] = {
            "status": "warning" if (mem_p >= mem_thr or disk_p >= disk_thr) else "healthy",
            **snap,
        }
    except Exception as e:
        checks["resources"] = {"status": "unknown", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": dt.now().isoformat(),
        "duration_ms": round(duration_ms, 2),
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "healthy": len([c for c in checks.values() if c.get("status") == "healthy"]),
            "warning": len([c for c in checks.values() if c.get("status") == "warning"]),
            "unhealthy": len([c for c in checks.values() if c.get("status") == "unhealthy"])
        }
    }


@router.get("/health/quick")
def health_quick():
    """Quick health check - just returns OK if API is running"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/health/n8n")
def health_n8n():
    """
    n8n workflow health summary (Tier 1 Quick Win).

    Returns workflow health status, SLA compliance, and dead letter queue status.
    """
    try:
        from ..n8n_reliability import get_n8n_health_summary
        return get_n8n_health_summary()
    except Exception as e:
        logger.error(f"n8n health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/health/detailed")
def health_detailed():
    """
    Enhanced health check with actionable metrics.
    Includes latency measurements, resource usage, and recommendations.
    """
    try:
        from ..health_checks import get_health_status
        return get_health_status()
    except ImportError as e:
        # Fallback to simple version without psutil
        try:
            from ..health_checks_simple import get_simple_health_status
            result = get_simple_health_status()
            result["warning"] = "Using simplified health check (psutil not available)"
            return result
        except Exception as fallback_e:
            return {"error": f"Both health check versions failed: {str(e)} / {str(fallback_e)}", "status": "error"}
    except Exception as e:
        return {"error": f"Health check failed: {str(e)}", "status": "error"}


# /metrics and /metrics/scientific moved to routers/metrics_router.py


@router.post("/internal/pool/drain", response_model=Dict[str, Any])
async def drain_connection_pools(request: Request):
    """Signal graceful connection pool drain."""
    request_id = getattr(request.state, "request_id", "unknown")

    global_state.set_pool_draining(True)

    logger.info(
        "Connection pool drain initiated",
        extra={"request_id": request_id}
    )

    return {
        "status": "draining",
        "active_connections": global_state.get_active_connections(),
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id
    }


@router.post("/internal/pool/reset", response_model=Dict[str, Any])
async def reset_connection_pools(request: Request):
    """Reset all database connection pools."""
    request_id = getattr(request.state, "request_id", "unknown")

    pools_reset = []

    try:
        if hasattr(postgres_state, "reset_pool"):
            postgres_state.reset_pool()
            pools_reset.append("postgres")

        if hasattr(knowledge_db, "reset_client"):
            knowledge_db.reset_client()
            pools_reset.append("qdrant")

        if hasattr(meilisearch_client, "reset_client"):
            meilisearch_client.reset_client()
            pools_reset.append("meilisearch")

        global_state.set_pool_draining(False)
        while global_state.get_active_connections() > 0:
            global_state.decrement_active_connections()

        logger.info(
            "Connection pools reset",
            extra={"request_id": request_id, "pools_reset": pools_reset}
        )

        return {
            "status": "reset",
            "pools": pools_reset,
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(
            "Failed to reset connection pools",
            extra={"request_id": request_id, "error": str(e)}
        )
        return {
            "status": "error",
            "error": str(e),
            "pools_attempted": pools_reset,
            "request_id": request_id
        }


@router.get("/stats")
def stats():
    def count_files(p: Path, pattern: str):
        if not p.exists():
            return 0
        return len(list(p.glob(pattern)))

    return {
        "work_projektil": {
            "emails_inbox": count_files(PARSED_DIR / "work_projektil" / "email" / "inbox", "*.txt"),
            "emails_sent": count_files(PARSED_DIR / "work_projektil" / "email" / "sent", "*.txt"),
            "whatsapp_jsonl": count_files(PARSED_DIR / "work_projektil" / "comms", "*.jsonl"),
            "gchat_jsonl": count_files(PARSED_DIR / "work_projektil" / "comms_gchat", "*.jsonl"),
        },
        "private": {
            "whatsapp_jsonl": count_files(PARSED_DIR / "private" / "comms", "*.jsonl"),
            "gchat_jsonl": count_files(PARSED_DIR / "private" / "comms_gchat", "*.jsonl"),
        }
    }


@router.get("/telegram/status")
def get_telegram_status_detailed():
    """Get detailed Telegram bot status including configuration and statistics."""
    from ..telegram_bot import get_bot_status, TELEGRAM_TOKEN, ALLOWED_USER_IDS

    try:
        basic_status = get_bot_status()

        bot_info = None
        if TELEGRAM_TOKEN:
            try:
                response = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
                    timeout=5
                )
                if response.status_code == 200:
                    bot_info = response.json().get("result", {})
            except (requests.RequestException, ValueError) as e:
                logger.debug("Failed to fetch Telegram bot info", extra={"error": str(e)})

        return {
            "status": basic_status.get("status", "unknown"),
            "bot_running": basic_status.get("running", False),
            "thread_alive": basic_status.get("thread_alive", False),
            "token_configured": basic_status.get("token_configured", False),
            "allowed_users": {
                "count": len(ALLOWED_USER_IDS) if ALLOWED_USER_IDS else 0,
                "ids": ALLOWED_USER_IDS if ALLOWED_USER_IDS else []
            },
            "bot_info": bot_info,
            "endpoints": {
                "send": "/telegram/send",
                "send_alert": "/telegram/send_alert",
                "vip_email_alert": "/telegram/vip_email_alert",
                "followup_reminder": "/telegram/followup_reminder",
                "status": "/telegram/status"
            },
            "features": {
                "broadcast": True,
                "targeted_messages": True,
                "inline_buttons": True,
                "markdown_support": True,
                "silent_mode": True
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to get Telegram status"
        }


@router.get("/worker/status")
def get_worker_status():
    """Get the current status of the queue worker."""
    return {
        "running": global_state.get_worker_running(),
        "stats": global_state.get_worker_stats()
    }


@router.get("/insights")
def get_health_insights_report():
    """
    Get comprehensive health insights with proactive hints.
    
    Includes:
    - Real-time metrics (API response time, memory, CPU, disk)
    - 24-hour trends analysis
    - Proactive alerts and recommendations
    - System and container health
    - Performance anomaly detection
    
    Example response:
    {
        "overall_status": "🟢 OPTIMAL",
        "metrics": {
            "api_response_time_ms": 145.2,
            "memory_usage_percent": 42.1,
            "cpu_usage_percent": 38.5,
            "error_rate_percent": 0.08,
            "requests_per_minute": 127.4
        },
        "trends": [
            {
                "metric_name": "api_response_time_ms",
                "current": 145.2,
                "avg_24h": 138.5,
                "trend": "↑",
                "change_percent": 4.8
            }
        ],
        "proactive_hints": [
            {
                "severity": "info",
                "category": "trends",
                "title": "🚀 System Optimal",
                "message": "All metrics within optimal ranges",
                "recommendation": "Monitor continues. Good time for testing."
            }
        ]
    }
    """
    try:
        from ..health_insights import get_health_insights
        
        insights = get_health_insights()
        
        # Collect additional metrics from the request context if available
        additional_metrics = {}
        
        # Try to get error rate and request metrics from observability
        try:
            from ..metrics import get_error_rate, get_request_rate
            additional_metrics["error_rate_percent"] = get_error_rate()
            additional_metrics["requests_per_minute"] = get_request_rate()
        except Exception:
            pass
        
        # Generate full report
        report = insights.get_full_health_report(additional_metrics)
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating health insights: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to generate health insights",
            "timestamp": datetime.now().isoformat()
        }


@router.get("/insights/summary")
def get_health_insights_summary():
    """
    Get brief health summary suitable for Telegram/dashboards.
    
    Example:
    {
        "status": "🟢 OPTIMAL",
        "uptime": "47h 23m",
        "api_response": "145ms ↓12%",
        "memory": "42.1%",
        "cpu": "38.5%",
        "errors": "0/1000",
        "alerts": []
    }
    """
    try:
        from ..health_insights import get_health_insights
        
        insights = get_health_insights()
        report = insights.get_full_health_report()
        
        metrics = report["metrics"]
        status = report["overall_status"]
        hints = report["proactive_hints"]
        
        # Filter only critical/warning hints
        active_alerts = [h for h in hints if h["severity"] in ["critical", "warning"]]
        
        # Calculate uptime
        import os
        try:
            uptime_seconds = time.time() - max(os.stat("/").st_mtime for _ in [1])
            uptime_hours = int(uptime_seconds / 3600)
            uptime_days = int(uptime_hours / 24)
            uptime_str = f"{uptime_days}d {uptime_hours % 24}h" if uptime_days > 0 else f"{uptime_hours}h"
        except (OSError, ValueError) as e:
            logger.warning(f"Failed to calculate system uptime: {e}")
            uptime_str = "unknown"
        
        # Get trend indicators
        trends = report.get("trends", [])
        api_trend = next((t for t in trends if t["metric_name"] == "api_response_time_ms"), None)
        api_trend_str = f'{metrics["api_response_time_ms"]:.0f}ms {api_trend["trend"]}{api_trend["change_percent"]:.0f}%' if api_trend else f'{metrics["api_response_time_ms"]:.0f}ms'
        
        return {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "uptime": uptime_str,
            "api_response": api_trend_str,
            "memory": f'{metrics["memory_usage_percent"]:.1f}%',
            "cpu": f'{metrics["cpu_usage_percent"]:.1f}%',
            "disk": f'{metrics["disk_usage_percent"]:.1f}%',
            "errors": f'{int(metrics["error_rate_percent"] * metrics["requests_per_minute"] / 100)}/min' if metrics["requests_per_minute"] > 0 else "0/min",
            "containers": f'{metrics["containers_healthy"]}/{metrics["containers_total"]} healthy',
            "alerts": [{"title": h["title"], "message": h["message"]} for h in active_alerts],
            "alert_count": len(active_alerts)
        }
        
    except Exception as e:
        logger.error(f"Error generating health summary: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/monitoring/system")
def get_system_metrics(auth: bool = Depends(auth_dependency)):
    """Read-only system metrics for monitoring access."""
    try:
        from ..health_insights import get_health_insights

        insights = get_health_insights()
        return {
            "timestamp": datetime.now().isoformat(),
            "system": insights.get_system_metrics(),
            "process": insights.get_process_metrics(),
            "containers": insights.get_container_health(),
        }
    except Exception as e:
        logger.error(f"Error collecting system metrics: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/monitoring/services")
def get_service_health(auth: bool = Depends(auth_dependency)):
    """Read-only service health snapshot."""
    try:
        return health_check()
    except Exception as e:
        logger.error(f"Error collecting service health: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/monitoring/performance")
def get_performance_metrics(auth: bool = Depends(auth_dependency)):
    """Read-only API performance metrics from Prometheus."""
    try:
        from ..prometheus_metrics import get_prometheus_client

        client = get_prometheus_client()
        summary = client.get_health_summary()
        anomalies = client.detect_anomalies()
        summary["anomalies"] = anomalies
        return summary
    except Exception as e:
        logger.error(f"Error collecting performance metrics: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/monitoring/errors")
def get_recent_errors(
    min_level: str = "WARNING",
    limit: int = 50,
    auth: bool = Depends(auth_dependency)
):
    """Read-only recent error snapshot from in-memory sources."""
    try:
        errors = []

        try:
            worker_stats = global_state.get_worker_stats()
            if worker_stats.get("last_error"):
                errors.append({
                    "source": "worker",
                    "message": worker_stats.get("last_error"),
                    "last_processed_at": worker_stats.get("last_processed_at")
                })
        except Exception:
            pass

        try:
            from ..telegram_bot import get_bot_status
            bot_status = get_bot_status()
            if bot_status.get("last_error"):
                errors.append({
                    "source": "telegram_bot",
                    "message": bot_status.get("last_error"),
                    "last_crash_at": bot_status.get("last_crash_at")
                })
        except Exception:
            pass

        try:
            from ..prometheus_metrics import get_prometheus_client
            anomalies = get_prometheus_client().detect_anomalies()
            for anomaly in anomalies:
                errors.append({
                    "source": "prometheus_anomaly",
                    "message": anomaly.get("message"),
                    "severity": anomaly.get("severity"),
                    "metric": anomaly.get("metric"),
                    "value": anomaly.get("value"),
                    "threshold": anomaly.get("threshold")
                })
        except Exception:
            pass

        if limit < 1 or limit > 200:
            return {
                "status": "error",
                "error": "limit must be between 1 and 200",
                "timestamp": datetime.now().isoformat()
            }

        try:
            log_events = get_recent_log_events(limit=limit, min_level=min_level)
            for event in log_events:
                errors.append({
                    "source": "log_buffer",
                    "level": event.get("level"),
                    "logger": event.get("logger"),
                    "message": event.get("msg"),
                    "timestamp": event.get("ts"),
                    "exception": event.get("exception")
                })
        except Exception:
            pass

        return {
            "timestamp": datetime.now().isoformat(),
            "count": len(errors),
            "errors": errors,
            "note": "Recent errors are derived from in-memory service status, Prometheus anomalies, and in-process log buffer. Container logs are not included."
        }
    except Exception as e:
        logger.error(f"Error collecting recent errors: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/monitoring/logs")
def get_container_log_tail(
    service: str = "ingestion",
    lines: int = 200,
    level: str = "ERROR",
    filter: Optional[str] = None,
    format: str = "text",
    request: Request = None,
    auth: bool = Depends(auth_dependency)
):
    """Read-only container log tail (NAS via SSH)."""
    if os.environ.get("JARVIS_ENABLE_REMOTE_LOGS", "false").lower() not in ("1", "true", "yes", "on"):
        return {
            "status": "disabled",
            "message": "Remote log access disabled. Set JARVIS_ENABLE_REMOTE_LOGS=true to enable.",
            "timestamp": datetime.now().isoformat()
        }

    allowed_containers = {
        "ingestion": "jarvis-ingestion",
        "qdrant": "jarvis-qdrant",
        "postgres": "jarvis-postgres",
        "meilisearch": "jarvis-meilisearch",
        "redis": "jarvis-redis",
        "n8n": "jarvis-n8n",
        "prometheus": "jarvis-prometheus",
        "grafana": "jarvis-grafana",
        "loki": "jarvis-loki",
        "promtail": "jarvis-promtail",
        "alertmanager": "jarvis-alertmanager",
        "cadvisor": "jarvis-cadvisor",
        "node_exporter": "jarvis-node-exporter",
        "portainer": "jarvis-portainer",
        "langfuse": "jarvis-langfuse",
        "langfuse_worker": "jarvis-langfuse-worker",
        "langfuse_clickhouse": "jarvis-langfuse-clickhouse",
        "langfuse_redis": "jarvis-langfuse-redis",
        "langfuse_minio": "jarvis-langfuse-minio",
        "jaeger": "jarvis-jaeger",
        "docs": "jarvis-docs",
        "postgres_exporter": "jarvis-postgres-exporter",
    }

    if service not in allowed_containers:
        return {
            "status": "error",
            "error": f"Service '{service}' not allowed",
            "allowed": sorted(list(allowed_containers.keys())),
            "timestamp": datetime.now().isoformat()
        }

    if lines < 1 or lines > 500:
        return {
            "status": "error",
            "error": "lines must be between 1 and 500",
            "timestamp": datetime.now().isoformat()
        }

    client_ip = request.client.host if request and request.client else "unknown"
    if LOG_TAIL_IP_ALLOWLIST and client_ip not in LOG_TAIL_IP_ALLOWLIST:
        logger.warning("Log tail blocked by IP allowlist", extra={"client_ip": client_ip})
        return {
            "status": "error",
            "error": "forbidden",
            "message": "client_ip not in allowlist",
            "timestamp": datetime.now().isoformat()
        }

    if LOG_TAIL_REQUIRE_HTTPS:
        scheme = request.headers.get("x-forwarded-proto") if request else None
        scheme = scheme or (request.url.scheme if request else "")
        if scheme != "https":
            logger.warning("Log tail blocked (HTTPS required)", extra={"client_ip": client_ip})
            return {
                "status": "error",
                "error": "https_required",
                "timestamp": datetime.now().isoformat()
            }
    rate_key = f"{client_ip}:{service}"
    last_seen = _log_tail_rate_limit.get(rate_key)
    now = time.time()
    if last_seen and now - last_seen < LOG_TAIL_COOLDOWN_SECONDS:
        return {
            "status": "error",
            "error": "rate_limited",
            "retry_after_seconds": LOG_TAIL_COOLDOWN_SECONDS,
            "timestamp": datetime.now().isoformat()
        }
    _log_tail_rate_limit[rate_key] = now

    container_name = allowed_containers[service]
    result = get_container_logs(container_name, lines)

    if not result.get("success"):
        logger.warning(
            "Log tail failed",
            extra={"client_ip": client_ip, "service": service, "container": container_name}
        )
        return {
            "status": "error",
            "error": result.get("error") or result.get("stderr") or "Failed to fetch logs",
            "exit_code": result.get("exit_code"),
            "timestamp": datetime.now().isoformat()
        }

    raw_logs = result.get("stdout", "")
    filtered_logs = _filter_log_lines(raw_logs, level)
    if filter:
        try:
            regex = re.compile(filter, re.IGNORECASE)
            filtered_logs = "\n".join(
                [line for line in filtered_logs.splitlines() if regex.search(line)]
            )
        except re.error:
            return {
                "status": "error",
                "error": "invalid_filter_regex",
                "timestamp": datetime.now().isoformat()
            }
    redacted_logs = _redact_logs(filtered_logs)

    logger.info(
        "Log tail served",
        extra={
            "client_ip": client_ip,
            "service": service,
            "container": container_name,
            "lines": lines,
            "level": level.upper(),
            "filter": filter or ""
        }
    )

    payload = {
        "timestamp": datetime.now().isoformat(),
        "service": service,
        "container": container_name,
        "lines": lines,
        "level": level.upper(),
        "filter": filter,
        "logs": redacted_logs
    }

    if format.lower() == "lines":
        payload["logs"] = [line for line in redacted_logs.splitlines() if line]
        payload["format"] = "lines"
    else:
        payload["format"] = "text"

    return payload


@router.get("/capabilities")
def get_capabilities(request: Request, _=Depends(auth_dependency)) -> Dict[str, Any]:
    """
    Get current Jarvis capabilities by directly reading canonical source files.
    This bypasses knowledge search for reliable, always-current status.
    
    Returns structured JSON with version, features, domains, tools, monitoring endpoints.
    """
    try:
        # Read canonical sources directly from filesystem
        capabilities_status_path = Path("/brain/system/docker/CAPABILITIES_STATUS.md")
        capabilities_json_path = Path("/brain/system/docs/CAPABILITIES.json")
        jarvis_self_path = Path("/brain/system/policies/JARVIS_SELF.md")
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "status": "success",
            "sources": {},
            "data": {}
        }
        
        # 1. Read CAPABILITIES_STATUS.md (canonical snapshot)
        if capabilities_status_path.exists():
            status_content = capabilities_status_path.read_text()
            result["sources"]["capabilities_status"] = {
                "path": str(capabilities_status_path),
                "exists": True,
                "size_bytes": len(status_content),
                "content": status_content
            }
            
            # Extract date from content
            import re
            date_match = re.search(r'Current Capabilities \((\d{4}-\d{2}-\d{2})\)', status_content)
            if date_match:
                result["data"]["snapshot_date"] = date_match.group(1)
        else:
            result["sources"]["capabilities_status"] = {
                "path": str(capabilities_status_path),
                "exists": False,
                "error": "file_not_found"
            }
        
        # 2. Read CAPABILITIES.json (generated at deploy)
        if capabilities_json_path.exists():
            import json
            try:
                with open(capabilities_json_path, 'r') as f:
                    capabilities_json = json.load(f)
                result["sources"]["capabilities_json"] = {
                    "path": str(capabilities_json_path),
                    "exists": True,
                    "version": capabilities_json.get("version"),
                    "build_timestamp": capabilities_json.get("build_timestamp")
                }
                result["data"]["version"] = capabilities_json.get("version")
                result["data"]["build_timestamp"] = capabilities_json.get("build_timestamp")
                result["data"]["tools_count"] = len(capabilities_json.get("tools", []))
                result["data"]["tools"] = capabilities_json.get("tools", [])
            except json.JSONDecodeError as e:
                result["sources"]["capabilities_json"] = {
                    "path": str(capabilities_json_path),
                    "exists": True,
                    "error": f"json_decode_error: {str(e)}"
                }
        else:
            result["sources"]["capabilities_json"] = {
                "path": str(capabilities_json_path),
                "exists": False,
                "error": "file_not_found"
            }
        
        # 3. Read JARVIS_SELF.md (for version fallback)
        if jarvis_self_path.exists():
            self_content = jarvis_self_path.read_text()
            result["sources"]["jarvis_self"] = {
                "path": str(jarvis_self_path),
                "exists": True,
                "size_bytes": len(self_content)
            }
            
            # Extract version if not found in capabilities.json
            if not result["data"].get("version"):
                import re
                version_match = re.search(r'\*\*Version\s+([\d.]+)\*\*', self_content)
                if version_match:
                    result["data"]["version_fallback"] = version_match.group(1)
        else:
            result["sources"]["jarvis_self"] = {
                "path": str(jarvis_self_path),
                "exists": False,
                "error": "file_not_found"
            }
        
        # 4. Extract monitoring endpoints from CAPABILITIES_STATUS.md
        if "capabilities_status" in result["sources"] and result["sources"]["capabilities_status"].get("exists"):
            content = result["sources"]["capabilities_status"]["content"]
            monitoring_section = re.search(
                r'### 4\) Observability.*?(?=###|\Z)', 
                content, 
                re.DOTALL
            )
            if monitoring_section:
                endpoints = re.findall(r'\*\*Monitoring \((\w+)\):\*\* ✅ `/monitoring/(\w+)`', monitoring_section.group(0))
                result["data"]["monitoring_endpoints"] = [
                    {"name": name, "path": f"/monitoring/{path}"} 
                    for name, path in endpoints
                ]
        
        log_with_context(
            logger, "info", "Capabilities retrieved",
            extra={"client_ip": request.client.host, "sources_found": len([s for s in result["sources"].values() if s.get("exists")])}
        )
        
        return result
        
    except Exception as e:
        log_with_context(logger, "error", "Capabilities retrieval failed", error=str(e))
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "error": str(e)
        }
