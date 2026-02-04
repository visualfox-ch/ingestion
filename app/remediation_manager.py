"""
Remediation Management Module

Phase 16.3: Automated Remediation Infrastructure
Using db_safety wrappers for safe database access with timeouts and metrics.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from .observability import get_logger
from .db_safety import safe_list_query, safe_write_query, safe_aggregate_query
from .remediation_metrics import (
    track_approval_metrics,
    track_db_query,
    update_pending_approvals_gauge,
    record_approval_decision,
    APPROVAL_COUNTER,
    PENDING_APPROVALS_GAUGE
)

logger = get_logger("jarvis.remediation")


# =============================================================================
# PENDING APPROVALS
# =============================================================================

@track_db_query('select', 'remediation_audit_log')
def get_pending_approvals() -> List[Dict[str, Any]]:
    """
    Get all pending approvals requiring human decision.

    Uses safe_list_query with 10s timeout.
    Updates Prometheus gauge with tier counts.
    """
    try:
        with safe_list_query('remediation_audit_log') as cur:
            cur.execute("""
                SELECT
                    remediation_id,
                    playbook,
                    tier,
                    trigger_condition,
                    trigger_timestamp,
                    metrics_before,
                    EXTRACT(EPOCH FROM (NOW() - trigger_timestamp)) / 3600 AS hours_pending
                FROM remediation_audit_log
                WHERE approval_required = TRUE
                  AND approved_at IS NULL
                  AND rejected_at IS NULL
                ORDER BY trigger_timestamp ASC
            """)
            rows = cur.fetchall()

            # Update gauge metrics by tier
            tier_counts = {}
            for row in rows:
                tier = row.get("tier", 0)
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            # Update gauges for tiers 1, 2, 3
            for tier in [1, 2, 3]:
                update_pending_approvals_gauge(tier, tier_counts.get(tier, 0))

            return [
                {
                    "remediation_id": row["remediation_id"],
                    "playbook": row["playbook"],
                    "tier": row["tier"],
                    "trigger_condition": row["trigger_condition"],
                    "trigger_timestamp": row["trigger_timestamp"].isoformat() if row["trigger_timestamp"] else None,
                    "metrics_before": row["metrics_before"] if row["metrics_before"] else {},
                    "hours_pending": round(row["hours_pending"], 2) if row["hours_pending"] else 0.0
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to get pending approvals: {e}")
        return []


# =============================================================================
# RECENT REMEDIATIONS
# =============================================================================

@track_db_query('select', 'remediation_audit_log')
def get_recent_remediations(days: int = 7) -> List[Dict[str, Any]]:
    """
    Get recent remediation history.

    Uses safe_list_query with 10s timeout.

    Args:
        days: Number of days to look back (default: 7)
    """
    try:
        with safe_list_query('remediation_audit_log') as cur:
            cur.execute("""
                SELECT
                    remediation_id,
                    playbook,
                    tier,
                    execution_status,
                    execution_started_at,
                    execution_duration_seconds,
                    improvement_percentage,
                    rollback_attempted,
                    escalated,
                    created_at
                FROM remediation_audit_log
                WHERE created_at >= NOW() - INTERVAL '%s days'
                ORDER BY created_at DESC
                LIMIT 50
            """, (days,))
            rows = cur.fetchall()

            return [
                {
                    "remediation_id": row["remediation_id"],
                    "playbook": row["playbook"],
                    "tier": row["tier"],
                    "status": row["execution_status"],
                    "started_at": row["execution_started_at"].isoformat() if row["execution_started_at"] else None,
                    "duration_seconds": float(row["execution_duration_seconds"]) if row["execution_duration_seconds"] else None,
                    "improvement_pct": float(row["improvement_percentage"]) if row["improvement_percentage"] else None,
                    "rolled_back": row["rollback_attempted"],
                    "escalated": row["escalated"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to get recent remediations: {e}")
        return []


# =============================================================================
# SUCCESS RATES
# =============================================================================

@track_db_query('aggregate', 'remediation_audit_log')
def get_success_rates() -> List[Dict[str, Any]]:
    """
    Get success rates by playbook.

    Uses safe_aggregate_query with 20s timeout for GROUP BY.
    """
    try:
        with safe_aggregate_query('remediation_audit_log') as cur:
            cur.execute("""
                SELECT
                    playbook,
                    COUNT(*) AS total_attempts,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) AS successful,
                    SUM(CASE WHEN execution_status = 'rolled_back' THEN 1 ELSE 0 END) AS rolled_back,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    ROUND(
                        100.0 * SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                        2
                    ) AS success_rate_pct,
                    AVG(execution_duration_seconds) AS avg_duration_seconds,
                    AVG(improvement_percentage) AS avg_improvement_pct
                FROM remediation_audit_log
                WHERE execution_status IS NOT NULL
                GROUP BY playbook
                ORDER BY total_attempts DESC
            """)
            rows = cur.fetchall()

            return [
                {
                    "playbook": row["playbook"],
                    "total_attempts": row["total_attempts"],
                    "successful": row["successful"] or 0,
                    "rolled_back": row["rolled_back"] or 0,
                    "failed": row["failed"] or 0,
                    "success_rate_pct": float(row["success_rate_pct"]) if row["success_rate_pct"] else 0.0,
                    "avg_duration_seconds": float(row["avg_duration_seconds"]) if row["avg_duration_seconds"] else None,
                    "avg_improvement_pct": float(row["avg_improvement_pct"]) if row["avg_improvement_pct"] else None
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to get success rates: {e}")
        return []


# =============================================================================
# APPROVAL ACTIONS
# =============================================================================

def approve_remediation(
    remediation_id: str,
    approved_by: str,
    reason: Optional[str] = None
) -> bool:
    """
    Approve a pending remediation.

    Uses safe_write_query with 15s timeout.
    Records approval metrics.

    Args:
        remediation_id: Unique ID of the remediation
        approved_by: User ID of approver
        reason: Optional approval reason

    Returns:
        True if approval succeeded, False if remediation not found/already processed
    """
    start_time = datetime.now()
    playbook_type = "unknown"

    try:
        with safe_write_query('remediation_audit_log') as cur:
            # First get the playbook type for metrics
            cur.execute("""
                SELECT playbook FROM remediation_audit_log
                WHERE remediation_id = %s
            """, (remediation_id,))
            row = cur.fetchone()
            if row:
                playbook_type = row.get("playbook", "unknown")

            # Perform the approval
            cur.execute("""
                UPDATE remediation_audit_log
                SET approved_by = %s,
                    approved_at = NOW(),
                    approval_reason = %s,
                    execution_status = 'approved',
                    updated_at = NOW()
                WHERE remediation_id = %s
                  AND approval_required = TRUE
                  AND approved_at IS NULL
                  AND rejected_at IS NULL
                RETURNING remediation_id
            """, (approved_by, reason, remediation_id))
            result = cur.fetchone()

            if result:
                # Record success metrics
                latency = (datetime.now() - start_time).total_seconds()
                record_approval_decision(playbook_type, 'approved', latency)

                logger.info(
                    f"Remediation approved",
                    extra={
                        "remediation_id": remediation_id,
                        "approved_by": approved_by,
                        "playbook": playbook_type,
                        "reason_length": len(reason) if reason else 0
                    }
                )
                return True

            logger.warning(
                f"Remediation not found or already processed",
                extra={"remediation_id": remediation_id}
            )
            return False

    except Exception as e:
        # Record error metric
        record_approval_decision(playbook_type, 'error')
        logger.error(
            f"Failed to approve remediation: {e}",
            extra={
                "remediation_id": remediation_id,
                "approved_by": approved_by,
                "error": str(e)
            }
        )
        raise


def reject_remediation(
    remediation_id: str,
    rejected_by: str,
    reason: str
) -> bool:
    """
    Reject a pending remediation.

    Uses safe_write_query with 15s timeout.
    Records rejection metrics.

    Args:
        remediation_id: Unique ID of the remediation
        rejected_by: User ID of person rejecting
        reason: Reason for rejection (required)

    Returns:
        True if rejection succeeded, False if remediation not found/already processed
    """
    start_time = datetime.now()
    playbook_type = "unknown"

    try:
        with safe_write_query('remediation_audit_log') as cur:
            # First get the playbook type for metrics
            cur.execute("""
                SELECT playbook FROM remediation_audit_log
                WHERE remediation_id = %s
            """, (remediation_id,))
            row = cur.fetchone()
            if row:
                playbook_type = row.get("playbook", "unknown")

            # Perform the rejection
            cur.execute("""
                UPDATE remediation_audit_log
                SET rejected_by = %s,
                    rejected_at = NOW(),
                    rejection_reason = %s,
                    execution_status = 'rejected',
                    updated_at = NOW()
                WHERE remediation_id = %s
                  AND approval_required = TRUE
                  AND approved_at IS NULL
                  AND rejected_at IS NULL
                RETURNING remediation_id
            """, (rejected_by, reason, remediation_id))
            result = cur.fetchone()

            if result:
                # Record rejection metrics
                latency = (datetime.now() - start_time).total_seconds()
                record_approval_decision(playbook_type, 'rejected', latency)

                logger.info(
                    f"Remediation rejected",
                    extra={
                        "remediation_id": remediation_id,
                        "rejected_by": rejected_by,
                        "playbook": playbook_type,
                        "reason": reason[:100] if reason else None  # Truncate for logging
                    }
                )
                return True

            logger.warning(
                f"Remediation not found or already processed",
                extra={"remediation_id": remediation_id}
            )
            return False

    except Exception as e:
        # Record error metric
        record_approval_decision(playbook_type, 'error')
        logger.error(
            f"Failed to reject remediation: {e}",
            extra={
                "remediation_id": remediation_id,
                "rejected_by": rejected_by,
                "error": str(e)
            }
        )
        raise


# =============================================================================
# STATS & SUMMARY
# =============================================================================

def get_remediation_summary() -> Dict[str, Any]:
    """
    Get a summary of remediation statistics.

    Returns dict with:
    - pending counts by tier
    - recent activity counts
    - success rates
    """
    try:
        pending = get_pending_approvals()
        recent = get_recent_remediations(days=7)
        stats = get_success_rates()

        # Count by tier
        by_tier = {}
        for item in pending:
            tier = item.get("tier", 0)
            by_tier[tier] = by_tier.get(tier, 0) + 1

        # Count by status in recent
        by_status = {}
        for item in recent:
            status = item.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

        # Overall success rate
        total_attempts = sum(s.get("total_attempts", 0) for s in stats)
        total_successful = sum(s.get("successful", 0) for s in stats)
        overall_rate = (total_successful / total_attempts * 100) if total_attempts > 0 else 0.0

        return {
            "pending_count": len(pending),
            "pending_by_tier": by_tier,
            "recent_count": len(recent),
            "recent_by_status": by_status,
            "playbook_stats": stats,
            "overall_success_rate": round(overall_rate, 2),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get remediation summary: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# =============================================================================
# PHASE 16.3C: EXECUTION MANAGEMENT
# =============================================================================

@track_db_query('select', 'remediation_audit_log')
def get_remediation(remediation_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single remediation by ID.

    Phase 16.3C: Used by execute endpoint.

    Args:
        remediation_id: Unique remediation ID

    Returns:
        Dict with remediation details or None if not found
    """
    try:
        with safe_list_query('remediation_audit_log') as cur:
            cur.execute("""
                SELECT
                    remediation_id,
                    playbook,
                    tier,
                    trigger_condition,
                    trigger_timestamp,
                    metrics_before,
                    approval_required,
                    approved_at,
                    approved_by,
                    rejected_at,
                    rejected_by,
                    executed_at,
                    execution_status,
                    execution_result
                FROM remediation_audit_log
                WHERE remediation_id = %s
            """, (remediation_id,))
            row = cur.fetchone()

            if not row:
                return None

            # Determine status
            status = "pending"
            if row.get("rejected_at"):
                status = "rejected"
            elif row.get("executed_at"):
                status = row.get("execution_status", "executed")
            elif row.get("approved_at"):
                status = "approved"
            elif not row.get("approval_required"):
                status = "auto_approved"

            return {
                "remediation_id": row["remediation_id"],
                "playbook_type": row["playbook"],
                "tier": row["tier"],
                "trigger_condition": row["trigger_condition"],
                "trigger_reason": row["trigger_condition"],  # Alias for clarity
                "trigger_timestamp": row["trigger_timestamp"].isoformat() if row["trigger_timestamp"] else None,
                "metrics_before": row["metrics_before"] if row["metrics_before"] else {},
                "params": row["metrics_before"] if row["metrics_before"] else {},  # Use metrics_before as params
                "status": status,
                "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
                "approved_by": row.get("approved_by"),
                "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else None,
                "execution_result": row.get("execution_result")
            }
    except Exception as e:
        logger.error(f"Failed to get remediation {remediation_id}: {e}")
        return None


@track_db_query('update', 'remediation_audit_log')
def update_status(remediation_id: str, status: str) -> bool:
    """
    Update remediation execution status.

    Phase 16.3C: Used to track playbook execution state.

    Args:
        remediation_id: Unique remediation ID
        status: New status (executing, completed, failed, rolled_back)

    Returns:
        True if updated, False otherwise
    """
    try:
        with safe_write_query('remediation_audit_log') as cur:
            if status == "executing":
                cur.execute("""
                    UPDATE remediation_audit_log
                    SET
                        executed_at = NOW(),
                        execution_status = %s
                    WHERE remediation_id = %s
                """, (status, remediation_id))
            else:
                cur.execute("""
                    UPDATE remediation_audit_log
                    SET execution_status = %s
                    WHERE remediation_id = %s
                """, (status, remediation_id))

            updated = cur.rowcount > 0

            if updated:
                logger.info(f"Remediation {remediation_id} status updated to {status}")

            return updated
    except Exception as e:
        logger.error(f"Failed to update remediation status: {e}")
        return False


@track_db_query('update', 'remediation_audit_log')
def update_execution_result(
    remediation_id: str,
    status: str,
    execution_result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    duration_seconds: Optional[float] = None
) -> bool:
    """
    Update remediation with execution result.

    Phase 16.3C: Called by n8n status callback.

    Args:
        remediation_id: Unique remediation ID
        status: Final status (completed, failed, rolled_back)
        execution_result: Dict with pre/post checks, improvement metrics
        error: Error message if failed
        duration_seconds: Total execution time

    Returns:
        True if updated, False otherwise
    """
    try:
        result_json = None
        if execution_result:
            result_json = json.dumps(execution_result)
        elif error:
            result_json = json.dumps({"error": error})

        with safe_write_query('remediation_audit_log') as cur:
            cur.execute("""
                UPDATE remediation_audit_log
                SET
                    execution_status = %s,
                    execution_result = %s,
                    completed_at = NOW()
                WHERE remediation_id = %s
            """, (status, result_json, remediation_id))

            updated = cur.rowcount > 0

            if updated:
                logger.info(
                    f"Remediation {remediation_id} completed with status {status}",
                    extra={
                        "duration_seconds": duration_seconds,
                        "has_error": error is not None
                    }
                )

                # Update metrics
                if status == "completed":
                    record_approval_decision(
                        playbook_type="unknown",  # Could be retrieved from DB
                        decision="executed",
                        latency_seconds=duration_seconds or 0.0
                    )

            return updated
    except Exception as e:
        logger.error(f"Failed to update execution result: {e}")
        return False
