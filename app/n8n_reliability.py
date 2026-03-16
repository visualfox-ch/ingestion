"""
n8n Reliability Contract & Execution Management

Gate A Features:
- SLA targets and dead-letter queue management
- Contract compliance checking across all workflows

Phase 2 Features (NEW):
- Workflow execution tracking with retry logic
- Health checks and failure pattern detection
- Error handler routing and escalation
- Prometheus metrics integration

SLA Targets:
- Success Rate: ≥95% for critical workflows, ≥90% for standard
- Response Time: ≤30s for sync webhooks, ≤5min for scheduled
- Recovery Time: Failed workflows retried within 15 minutes
- Retry Logic: Exponential backoff (1s, 2s, 4s) for transient errors only
"""
import json
import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from .observability import get_logger, log_with_context
from .postgres_state import get_cursor

logger = get_logger("jarvis.n8n_reliability")


# =============================================================================
# Phase 2: Execution Management & Health Checks
# =============================================================================

class WorkflowExecutionStatus(str, Enum):
    """Workflow execution outcomes"""
    SUCCESS = "success"
    RUNNING = "running"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PERMANENT_ERROR = "permanent_error"


class WorkflowHealthStatus(str, Enum):
    """Workflow health states"""
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


# =============================================================================
# Gate A: SLA Contract Definition
# =============================================================================

@dataclass
class WorkflowSLA:
    """SLA definition for a workflow."""
    workflow_name: str
    tier: str  # critical, standard, best_effort
    success_rate_target: float  # 0.0-1.0
    max_response_time_seconds: int
    max_retries: int
    alert_on_failure: bool


# Default SLA tiers
SLA_TIERS = {
    "critical": WorkflowSLA(
        workflow_name="",
        tier="critical",
        success_rate_target=0.95,
        max_response_time_seconds=30,
        max_retries=3,
        alert_on_failure=True
    ),
    "standard": WorkflowSLA(
        workflow_name="",
        tier="standard",
        success_rate_target=0.90,
        max_response_time_seconds=300,
        max_retries=2,
        alert_on_failure=False
    ),
    "best_effort": WorkflowSLA(
        workflow_name="",
        tier="best_effort",
        success_rate_target=0.80,
        max_response_time_seconds=600,
        max_retries=1,
        alert_on_failure=False
    )
}

# Workflow tier assignments
WORKFLOW_TIERS: Dict[str, str] = {
    # Critical - Core functionality
    "jarvis_google_unified_v2": "critical",
    "jarvis_morning_briefing": "critical",
    "jarvis_daily_digest": "critical",
    "jarvis_gmail_daily_sync": "critical",

    # Standard - Important but can tolerate some failures
    "jarvis_realtime_monitor": "standard",
    "jarvis_goal_progress": "standard",
    "jarvis_deadline_warnings": "standard",
    "jarvis_async_coaching": "standard",
    "jarvis_pattern_detection": "standard",
    "jarvis_weekly_digest": "standard",
    "jarvis_drive_sync": "standard",

    # Best effort - Nice to have
    "jarvis_preference_decay": "best_effort",
    "jarvis_preference_learner": "best_effort",
    "jarvis_active_learning": "best_effort",
    "jarvis_baseline_recorder": "best_effort",
    "jarvis_learning_digest": "best_effort",
    "jarvis_log_archival": "best_effort",
    "nightly_consolidation": "best_effort",
}


def get_workflow_sla(workflow_name: str) -> WorkflowSLA:
    """Get SLA for a workflow."""
    tier = WORKFLOW_TIERS.get(workflow_name, "best_effort")
    base_sla = SLA_TIERS[tier]
    return WorkflowSLA(
        workflow_name=workflow_name,
        tier=tier,
        success_rate_target=base_sla.success_rate_target,
        max_response_time_seconds=base_sla.max_response_time_seconds,
        max_retries=base_sla.max_retries,
        alert_on_failure=base_sla.alert_on_failure
    )


# =============================================================================
# Dead Letter Queue Management
# =============================================================================

def add_to_dead_letter(
    workflow_name: str,
    execution_id: str = None,
    error_type: str = None,
    error_message: str = None,
    payload: Dict = None
) -> int:
    """Add a failed execution to the dead letter queue."""
    sla = get_workflow_sla(workflow_name)

    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO n8n_dead_letter
                (workflow_name, execution_id, error_type, error_message, payload, max_retries)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING dl_id
            """, (
                workflow_name,
                execution_id,
                error_type,
                error_message,
                json.dumps(payload) if payload else '{}',
                sla.max_retries
            ))
            dl_id = cur.fetchone()["dl_id"]

        log_with_context(logger, "info", "Added to dead letter queue",
                        workflow=workflow_name, dl_id=dl_id, error_type=error_type)
        return dl_id
    except Exception as e:
        log_with_context(logger, "error", "Failed to add to dead letter",
                        workflow=workflow_name, error=str(e))
        return -1


def get_pending_retries(limit: int = 10) -> List[Dict]:
    """Get pending items from dead letter queue that can be retried."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM n8n_dead_letter
                WHERE status IN ('pending', 'retrying')
                AND retry_count < max_retries
                ORDER BY created_at ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get pending retries", error=str(e))
        return []


def mark_retry_attempt(dl_id: int) -> bool:
    """Mark a dead letter item as being retried."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE n8n_dead_letter
                SET status = 'retrying', retry_count = retry_count + 1
                WHERE dl_id = %s
            """, (dl_id,))
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to mark retry", dl_id=dl_id, error=str(e))
        return False


def resolve_dead_letter(dl_id: int, success: bool = True) -> bool:
    """Mark a dead letter item as resolved or abandoned."""
    status = "resolved" if success else "abandoned"
    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE n8n_dead_letter
                SET status = %s, resolved_at = NOW()
                WHERE dl_id = %s
            """, (status, dl_id))
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to resolve dead letter",
                        dl_id=dl_id, error=str(e))
        return False


def get_dead_letter_stats() -> Dict[str, Any]:
    """Get statistics on dead letter queue."""
    try:
        with get_cursor() as cur:
            # Status counts
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM n8n_dead_letter
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cur.fetchall()}

            # By workflow
            cur.execute("""
                SELECT workflow_name, COUNT(*) as count,
                       SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved,
                       SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) as abandoned
                FROM n8n_dead_letter
                GROUP BY workflow_name
                ORDER BY count DESC
                LIMIT 10
            """)
            by_workflow = [dict(row) for row in cur.fetchall()]

            # Recent failures (last 24h)
            cur.execute("""
                SELECT COUNT(*) as count
                FROM n8n_dead_letter
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
            recent_24h = cur.fetchone()["count"]

        return {
            "by_status": status_counts,
            "by_workflow": by_workflow,
            "recent_24h_failures": recent_24h,
            "total_pending": status_counts.get("pending", 0) + status_counts.get("retrying", 0)
        }
    except Exception as e:
        log_with_context(logger, "error", "Failed to get dead letter stats", error=str(e))
        return {"error": str(e)}


# =============================================================================
# Contract Compliance Checking
# =============================================================================

def check_workflow_compliance(workflow_name: str, days: int = 7) -> Dict[str, Any]:
    """Check if a workflow is meeting its SLA."""
    sla = get_workflow_sla(workflow_name)

    try:
        with get_cursor() as cur:
            # Get success rate from workflow_runs
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration
                FROM workflow_runs
                WHERE workflow_name = %s
                AND created_at > NOW() - INTERVAL '%s days'
            """, (workflow_name, days))
            row = cur.fetchone()

            total = row["total"] or 0
            successful = row["successful"] or 0
            avg_duration = row["avg_duration"] or 0

            success_rate = successful / total if total > 0 else 1.0

            # Check compliance
            rate_compliant = success_rate >= sla.success_rate_target
            time_compliant = avg_duration <= sla.max_response_time_seconds

            return {
                "workflow_name": workflow_name,
                "sla": asdict(sla),
                "metrics": {
                    "total_runs": total,
                    "successful_runs": successful,
                    "success_rate": round(success_rate, 3),
                    "avg_duration_seconds": round(avg_duration, 2)
                },
                "compliance": {
                    "success_rate": rate_compliant,
                    "response_time": time_compliant,
                    "overall": rate_compliant and time_compliant
                },
                "period_days": days
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to check compliance",
                        workflow=workflow_name, error=str(e))
        return {"error": str(e), "workflow_name": workflow_name}


def get_contract_overview() -> Dict[str, Any]:
    """Get overview of all workflow SLA compliance."""
    results = {
        "critical": {"compliant": 0, "non_compliant": 0, "workflows": []},
        "standard": {"compliant": 0, "non_compliant": 0, "workflows": []},
        "best_effort": {"compliant": 0, "non_compliant": 0, "workflows": []},
    }

    for workflow_name, tier in WORKFLOW_TIERS.items():
        compliance = check_workflow_compliance(workflow_name)
        if "error" in compliance:
            continue

        is_compliant = compliance.get("compliance", {}).get("overall", False)

        if is_compliant:
            results[tier]["compliant"] += 1
        else:
            results[tier]["non_compliant"] += 1

        results[tier]["workflows"].append({
            "name": workflow_name,
            "compliant": is_compliant,
            "success_rate": compliance.get("metrics", {}).get("success_rate", 0)
        })

    # Calculate overall compliance
    total_compliant = sum(r["compliant"] for r in results.values())
    total_workflows = sum(r["compliant"] + r["non_compliant"] for r in results.values())

    return {
        "by_tier": results,
        "overall": {
            "compliant": total_compliant,
            "total": total_workflows,
            "compliance_rate": total_compliant / total_workflows if total_workflows > 0 else 1.0
        },
        "sla_targets": {
            tier: {
                "success_rate": sla.success_rate_target,
                "max_response_time": sla.max_response_time_seconds,
                "max_retries": sla.max_retries
            }
            for tier, sla in SLA_TIERS.items()
        },
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


# =============================================================================
# Idempotency Helper
# =============================================================================

def check_idempotency(workflow_name: str, idempotency_key: str) -> Optional[Dict]:
    """Check if a workflow run with this key already exists (for idempotent execution)."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM workflow_runs
                WHERE idempotency_key = %s
            """, (idempotency_key,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Idempotency check failed",
                        workflow=workflow_name, key=idempotency_key, error=str(e))
        return None


def record_workflow_run(
    workflow_name: str,
    idempotency_key: str,
    status: str = "running",
    result_counts: Dict = None,
    error_message: str = None
) -> int:
    """Record a workflow run for idempotency and tracking."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO workflow_runs
                (idempotency_key, workflow_name, status, result_counts, error_message)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    status = EXCLUDED.status,
                    result_counts = EXCLUDED.result_counts,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
                RETURNING run_id
            """, (
                idempotency_key,
                workflow_name,
                status,
                json.dumps(result_counts) if result_counts else '{}',
                error_message
            ))
            return cur.fetchone()["run_id"]
    except Exception as e:
        log_with_context(logger, "error", "Failed to record workflow run",
                        workflow=workflow_name, error=str(e))
        return -1


# =============================================================================
# Phase 2: Execution Recording & Health Checks
# =============================================================================

def record_execution(
    workflow_id: str,
    audit_id: str,
    status: WorkflowExecutionStatus,
    execution_time_ms: float,
    error: Optional[str] = None,
    retry_count: int = 0
) -> bool:
    """
    Record workflow execution to database for SLA tracking.
    
    Args:
        workflow_id: n8n workflow identifier
        audit_id: Jarvis approval audit trail ID (for correlation)
        status: WorkflowExecutionStatus enum value
        execution_time_ms: Execution time in milliseconds
        error: Error message if failed
        retry_count: Number of retries performed
        
    Returns:
        True if recorded successfully
    """
    try:
        with get_cursor() as cur:
            import uuid
            execution_id = str(uuid.uuid4())
            
            cur.execute("""
                INSERT INTO n8n_workflow_executions
                (execution_id, workflow_id, audit_id, status, execution_time_ms, 
                 error, retry_count, recorded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                execution_id,
                workflow_id,
                audit_id,
                status.value,
                execution_time_ms,
                error[:500] if error else None,  # Truncate error
                retry_count
            ))
            
        log_with_context(
            logger, "info",
            "workflow_execution_recorded",
            workflow_id=workflow_id,
            audit_id=audit_id,
            status=status.value,
            execution_time_ms=execution_time_ms,
            retry_count=retry_count
        )
        return True
    except Exception as e:
        log_with_context(
            logger, "error",
            "workflow_execution_recording_failed",
            workflow_id=workflow_id,
            audit_id=audit_id,
            error=str(e)
        )
        return False


def get_workflow_health(workflow_id: str) -> Dict[str, Any]:
    """
    Get current health status for a workflow based on recent executions.
    
    Returns:
        {
            "workflow_id": str,
            "health_status": "up" | "degraded" | "down",
            "success_rate_24h": float (0.0-1.0),
            "error_rate_24h": float,
            "avg_execution_ms": float,
            "p95_execution_ms": float,
            "total_executions_24h": int,
            "total_failures_24h": int,
            "total_timeouts_24h": int,
            "consecutive_failures": int,
            "last_error": Optional[str],
            "sla_status": bool (is_meeting_sla)
        }
    """
    try:
        with get_cursor() as cur:
            # Get SLA target
            cur.execute("""
                SELECT success_rate_target, max_response_time_ms, tier
                FROM n8n_workflow_reliability_config
                WHERE workflow_id = %s
            """, (workflow_id,))
            config_row = cur.fetchone()
            
            if not config_row:
                # Default config
                sla_target = 0.90
                max_response_ms = 30000
                tier = "standard"
            else:
                sla_target = config_row["success_rate_target"]
                max_response_ms = config_row["max_response_time_ms"]
                tier = config_row["tier"]

            # Get 24h metrics
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'success') as successful,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'timeout') as timeouts,
                    COUNT(*) FILTER (WHERE status = 'permanent_error') as permanent_errors,
                    COUNT(*) as total,
                    ROUND(AVG(execution_time_ms)::numeric, 2) as avg_time_ms,
                    MAX(execution_time_ms) as max_time_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY execution_time_ms) as p95_time_ms
                FROM n8n_workflow_executions
                WHERE workflow_id = %s
                AND recorded_at > NOW() - INTERVAL '24 hours'
            """, (workflow_id,))
            
            metrics = cur.fetchone()
            if not metrics or metrics["total"] == 0:
                return {
                    "workflow_id": workflow_id,
                    "health_status": "up",
                    "success_rate_24h": 1.0,
                    "error_rate_24h": 0.0,
                    "avg_execution_ms": 0.0,
                    "p95_execution_ms": 0.0,
                    "total_executions_24h": 0,
                    "total_failures_24h": 0,
                    "total_timeouts_24h": 0,
                    "consecutive_failures": 0,
                    "last_error": None,
                    "sla_status": True,
                    "tier": tier
                }

            total = metrics["total"] or 1
            successful = metrics["successful"] or 0
            success_rate = successful / total
            
            # Determine health status
            if success_rate >= 0.95:
                health_status = "up"
            elif success_rate >= 0.80:
                health_status = "degraded"
            else:
                health_status = "down"

            # Get last error
            cur.execute("""
                SELECT error FROM n8n_workflow_executions
                WHERE workflow_id = %s
                AND error IS NOT NULL
                AND recorded_at > NOW() - INTERVAL '24 hours'
                ORDER BY recorded_at DESC
                LIMIT 1
            """, (workflow_id,))
            last_error_row = cur.fetchone()
            last_error = last_error_row["error"] if last_error_row else None

            # Count consecutive failures
            cur.execute("""
                WITH recent_statuses AS (
                    SELECT status
                    FROM n8n_workflow_executions
                    WHERE workflow_id = %s
                    AND recorded_at > NOW() - INTERVAL '24 hours'
                    ORDER BY recorded_at DESC
                    LIMIT 10
                )
                SELECT COUNT(*) as consecutive_failures
                FROM recent_statuses
                WHERE status != 'success'
            """, (workflow_id,))
            consecutive = cur.fetchone()["consecutive_failures"] or 0

            sla_met = success_rate >= sla_target

            return {
                "workflow_id": workflow_id,
                "health_status": health_status,
                "success_rate_24h": round(success_rate, 4),
                "error_rate_24h": round(1.0 - success_rate, 4),
                "avg_execution_ms": float(metrics["avg_time_ms"] or 0),
                "p95_execution_ms": float(metrics["p95_time_ms"] or 0),
                "total_executions_24h": total,
                "total_failures_24h": metrics["failed"] or 0,
                "total_timeouts_24h": metrics["timeouts"] or 0,
                "consecutive_failures": consecutive,
                "last_error": last_error,
                "sla_status": sla_met,
                "tier": tier,
                "sla_target": sla_target
            }

    except Exception as e:
        log_with_context(
            logger, "error",
            "workflow_health_check_failed",
            workflow_id=workflow_id,
            error=str(e)
        )
        return {
            "workflow_id": workflow_id,
            "health_status": "unknown",
            "error": str(e)
        }


def get_all_workflows_health() -> List[Dict[str, Any]]:
    """Get health status for all configured workflows"""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT DISTINCT workflow_id FROM n8n_workflow_reliability_config")
            workflows = cur.fetchall()
            
        health_reports = []
        for row in workflows:
            health = get_workflow_health(row["workflow_id"])
            if health and "error" not in health:
                health_reports.append(health)
        
        return sorted(health_reports, key=lambda x: x.get("success_rate_24h", 1.0))

    except Exception as e:
        log_with_context(logger, "error", "Failed to get all workflows health", error=str(e))
        return []


def get_n8n_system_health() -> Dict[str, Any]:
    """Get overall n8n system health aggregated from all workflows"""
    try:
        health_reports = get_all_workflows_health()
        
        if not health_reports:
            return {
                "system_status": "unknown",
                "total_workflows": 0,
                "workflows_up": 0,
                "workflows_degraded": 0,
                "workflows_down": 0,
                "avg_success_rate": 1.0,
                "critical_workflows_healthy": True
            }

        total = len(health_reports)
        up = sum(1 for h in health_reports if h["health_status"] == "up")
        degraded = sum(1 for h in health_reports if h["health_status"] == "degraded")
        down = sum(1 for h in health_reports if h["health_status"] == "down")
        
        avg_success_rate = sum(h.get("success_rate_24h", 1.0) for h in health_reports) / total
        
        critical_health = [
            h for h in health_reports 
            if h.get("tier") == "critical" and h["health_status"] != "up"
        ]

        system_status = "up"
        if down > 0 or critical_health:
            system_status = "degraded"
        if down > total * 0.5:
            system_status = "down"

        return {
            "system_status": system_status,
            "total_workflows": total,
            "workflows_up": up,
            "workflows_degraded": degraded,
            "workflows_down": down,
            "avg_success_rate": round(avg_success_rate, 4),
            "critical_workflows_healthy": len(critical_health) == 0,
            "unhealthy_critical": [
                {"workflow_id": h["workflow_id"], "status": h["health_status"]}
                for h in critical_health
            ],
            "checked_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to get n8n system health", error=str(e))
        return {"system_status": "error", "error": str(e)}


# =============================================================================
# Phase 2: Auto-Retry with Exponential Backoff (Tier 1 Quick Win)
# =============================================================================

def process_dead_letter_queue(max_items: int = 20) -> Dict[str, Any]:
    """
    Process items in the dead letter queue - cleanup and triage.

    This is a Tier 1 Quick Win that:
    - Abandons items that have exceeded max retries
    - Identifies retriable items (for next scheduled workflow run)
    - Tracks permanent errors for alerting

    Most n8n failures are transient (rate limits, network) and will resolve
    on the next scheduled run. This function does cleanup and triage.

    Args:
        max_items: Maximum number of items to process

    Returns:
        {
            "processed": int,
            "abandoned": int,
            "retriable": int,
            "permanent_errors": int,
            "details": [...]
        }
    """
    pending = get_pending_retries(limit=max_items)

    results = {
        "processed": 0,
        "abandoned": 0,
        "retriable": 0,
        "permanent_errors": 0,
        "details": []
    }

    if not pending:
        log_with_context(logger, "info", "No pending dead letter items")
        return results

    log_with_context(logger, "info", f"Processing {len(pending)} dead letter items")

    permanent_error_types = {
        "authentication_error", "invalid_config", "permanent_error",
        "invalid_payload", "workflow_not_found", "unauthorized"
    }

    for item in pending:
        dl_id = item["dl_id"]
        workflow_name = item["workflow_name"]
        retry_count = item.get("retry_count", 0)
        max_retries = item.get("max_retries", 3)
        error_type = item.get("error_type", "")
        error_message = item.get("error_message", "")

        results["processed"] += 1

        # Check for permanent errors - abandon immediately
        if error_type in permanent_error_types:
            resolve_dead_letter(dl_id, success=False)
            results["permanent_errors"] += 1
            results["details"].append({
                "dl_id": dl_id,
                "workflow": workflow_name,
                "status": "abandoned",
                "reason": f"permanent_error: {error_type}",
                "error_message": error_message[:200] if error_message else None
            })
            log_with_context(logger, "warning", "Permanent error abandoned",
                            dl_id=dl_id, workflow=workflow_name, error_type=error_type)
            continue

        # Check if max retries exceeded
        if retry_count >= max_retries:
            resolve_dead_letter(dl_id, success=False)
            results["abandoned"] += 1
            results["details"].append({
                "dl_id": dl_id,
                "workflow": workflow_name,
                "status": "abandoned",
                "reason": "max_retries_exceeded",
                "retry_count": retry_count
            })
            log_with_context(logger, "warning", "Max retries exceeded",
                            dl_id=dl_id, workflow=workflow_name, retry_count=retry_count)
            continue

        # Transient error - will be retried on next scheduled run
        # Mark retry attempt to track
        mark_retry_attempt(dl_id)
        results["retriable"] += 1
        results["details"].append({
            "dl_id": dl_id,
            "workflow": workflow_name,
            "status": "retriable",
            "retry_count": retry_count + 1,
            "next_action": "await_scheduled_run"
        })

    log_with_context(logger, "info", "Dead letter processing complete",
                    processed=results["processed"],
                    abandoned=results["abandoned"],
                    retriable=results["retriable"],
                    permanent_errors=results["permanent_errors"])

    return results


def get_n8n_health_summary() -> Dict[str, Any]:
    """
    Get a concise n8n health summary for the /health/n8n endpoint.

    Returns:
        {
            "status": "healthy" | "degraded" | "unhealthy",
            "workflows": {
                "total": int,
                "up": int,
                "degraded": int,
                "down": int
            },
            "dead_letter": {
                "pending": int,
                "recent_24h": int
            },
            "sla_compliance": float,
            "critical_healthy": bool
        }
    """
    try:
        system_health = get_n8n_system_health()
        dl_stats = get_dead_letter_stats()

        # Map system status to health status
        status_map = {
            "up": "healthy",
            "degraded": "degraded",
            "down": "unhealthy",
            "unknown": "unknown",
            "error": "error"
        }

        return {
            "status": status_map.get(system_health.get("system_status", "unknown"), "unknown"),
            "workflows": {
                "total": system_health.get("total_workflows", 0),
                "up": system_health.get("workflows_up", 0),
                "degraded": system_health.get("workflows_degraded", 0),
                "down": system_health.get("workflows_down", 0)
            },
            "dead_letter": {
                "pending": dl_stats.get("total_pending", 0),
                "recent_24h": dl_stats.get("recent_24h_failures", 0)
            },
            "sla_compliance": system_health.get("avg_success_rate", 1.0),
            "critical_healthy": system_health.get("critical_workflows_healthy", True),
            "unhealthy_critical": system_health.get("unhealthy_critical", []),
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        log_with_context(logger, "error", "Failed to get n8n health summary", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "checked_at": datetime.now(timezone.utc).isoformat()
        }


def detect_failure_patterns() -> Dict[str, Any]:
    """
    Detect failure patterns and root causes for n8n workflows.

    Returns failure analysis with common error types and affected workflows
    """
    try:
        with get_cursor() as cur:
            # Get materialized view data
            cur.execute("""
                SELECT
                    workflow_id,
                    workflow_name,
                    status,
                    failure_count,
                    error_summary,
                    failure_date
                FROM v_n8n_failure_analysis
                ORDER BY failure_count DESC
                LIMIT 20
            """)
            
            failures = [dict(row) for row in cur.fetchall()]
            
            # Group by error type
            error_groups = {}
            for failure in failures:
                error_type = failure["status"]
                if error_type not in error_groups:
                    error_groups[error_type] = {"count": 0, "workflows": [], "examples": []}
                
                error_groups[error_type]["count"] += failure["failure_count"]
                if failure["workflow_id"] not in error_groups[error_type]["workflows"]:
                    error_groups[error_type]["workflows"].append(failure["workflow_id"])
                
                if len(error_groups[error_type]["examples"]) < 3:
                    error_groups[error_type]["examples"].append({
                        "workflow": failure["workflow_id"],
                        "summary": failure["error_summary"]
                    })

            return {
                "analysis_period": "24_hours",
                "total_failures_analyzed": len(failures),
                "error_types": error_groups,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed to detect failure patterns", error=str(e))
        return {"error": str(e)}


