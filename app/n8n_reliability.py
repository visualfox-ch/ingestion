"""
n8n Reliability Contract (Gate A)

Defines SLA targets, dead-letter queue management, and contract compliance checking.

SLA Targets:
- Success Rate: ≥95% for critical workflows, ≥90% for standard
- Response Time: ≤30s for sync webhooks, ≤5min for scheduled
- Recovery Time: Failed workflows retried within 15 minutes
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from .observability import get_logger, log_with_context
from .postgres_state import get_cursor

logger = get_logger("jarvis.n8n_reliability")


# =============================================================================
# SLA Contract Definition
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
