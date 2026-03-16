"""
Verify-Before-Act Service (Phase S2).

Disciplined flow: Plan → Execute → Verify → Handoff

This service ensures:
1. Every important action has an explicit plan
2. Expected outcomes are defined BEFORE execution
3. Actual outcomes are compared against expectations
4. Discrepancies trigger alerts or rollback
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class VerifyBeforeActService:
    """Service for Plan → Execute → Verify → Handoff flow."""

    def __init__(self):
        """Initialize the service."""
        from app.services.postgres_state import get_cursor
        self.get_cursor = get_cursor

    # =========================================================================
    # Plan Phase
    # =========================================================================

    def create_plan(
        self,
        action_type: str,
        action_name: str,
        action_params: Dict[str, Any],
        expected_outcome: str,
        expected_state: Optional[Dict[str, Any]] = None,
        success_criteria: Optional[List[Dict[str, Any]]] = None,
        rollback_plan: Optional[Dict[str, Any]] = None,
        risk_tier: int = 1,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create an action plan before execution."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT create_action_plan(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    action_type,
                    action_name,
                    json.dumps(action_params) if action_params else None,
                    expected_outcome,
                    json.dumps(expected_state) if expected_state else None,
                    json.dumps(success_criteria) if success_criteria else None,
                    json.dumps(rollback_plan) if rollback_plan else None,
                    risk_tier,
                    json.dumps(context) if context else None
                ))
                plan_id = cur.fetchone()[0]

                return {
                    "plan_id": plan_id,
                    "action_type": action_type,
                    "action_name": action_name,
                    "expected_outcome": expected_outcome,
                    "risk_tier": risk_tier,
                    "status": "planned"
                }
        except Exception as e:
            logger.error(f"Failed to create plan: {e}")
            raise

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get a plan by ID."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT plan_id, action_type, action_name, action_params,
                           expected_outcome, expected_state, success_criteria,
                           rollback_plan, risk_tier, requires_verification,
                           auto_rollback_on_failure, status, created_at
                    FROM action_plans
                    WHERE plan_id = %s
                """, (plan_id,))
                row = cur.fetchone()
                if not row:
                    return None

                return {
                    "plan_id": row[0],
                    "action_type": row[1],
                    "action_name": row[2],
                    "action_params": row[3],
                    "expected_outcome": row[4],
                    "expected_state": row[5],
                    "success_criteria": row[6],
                    "rollback_plan": row[7],
                    "risk_tier": row[8],
                    "requires_verification": row[9],
                    "auto_rollback_on_failure": row[10],
                    "status": row[11],
                    "created_at": row[12].isoformat() if row[12] else None
                }
        except Exception as e:
            logger.error(f"Failed to get plan: {e}")
            return None

    # =========================================================================
    # Execute Phase
    # =========================================================================

    def start_execution(self, plan_id: str) -> int:
        """Mark execution as started, return execution ID."""
        try:
            with self.get_cursor() as cur:
                # Update plan status
                cur.execute("""
                    UPDATE action_plans SET status = 'executing'
                    WHERE plan_id = %s
                """, (plan_id,))

                # Create execution record
                cur.execute("""
                    INSERT INTO action_executions (plan_id, execution_status)
                    VALUES (%s, 'running')
                    RETURNING id
                """, (plan_id,))
                return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to start execution: {e}")
            raise

    def record_execution(
        self,
        plan_id: str,
        actual_outcome: str,
        actual_state: Optional[Dict[str, Any]],
        raw_result: Any,
        status: str = "success",
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record execution result."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT record_execution(%s, %s, %s, %s, %s, %s)
                """, (
                    plan_id,
                    actual_outcome,
                    json.dumps(actual_state) if actual_state else None,
                    json.dumps(raw_result) if raw_result else None,
                    status,
                    error_message
                ))
                execution_id = cur.fetchone()[0]

                return {
                    "execution_id": execution_id,
                    "plan_id": plan_id,
                    "status": status,
                    "actual_outcome": actual_outcome
                }
        except Exception as e:
            logger.error(f"Failed to record execution: {e}")
            raise

    # =========================================================================
    # Verify Phase
    # =========================================================================

    def verify_execution(
        self,
        plan_id: str,
        execution_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Verify execution against plan."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT verify_execution(%s, %s)
                """, (plan_id, execution_id))
                result = cur.fetchone()[0]
                return result if isinstance(result, dict) else json.loads(result)
        except Exception as e:
            logger.error(f"Failed to verify execution: {e}")
            raise

    def get_verification(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get verification result for a plan."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT v.id, v.verification_passed, v.criteria_results,
                           v.discrepancies, v.confidence_score, v.action_taken,
                           v.human_reviewed, v.verified_at
                    FROM verification_results v
                    WHERE v.plan_id = %s
                    ORDER BY v.verified_at DESC
                    LIMIT 1
                """, (plan_id,))
                row = cur.fetchone()
                if not row:
                    return None

                return {
                    "verification_id": row[0],
                    "passed": row[1],
                    "criteria_results": row[2],
                    "discrepancies": row[3],
                    "confidence_score": row[4],
                    "action_taken": row[5],
                    "human_reviewed": row[6],
                    "verified_at": row[7].isoformat() if row[7] else None
                }
        except Exception as e:
            logger.error(f"Failed to get verification: {e}")
            return None

    # =========================================================================
    # Rollback Phase
    # =========================================================================

    def trigger_rollback(
        self,
        plan_id: str,
        reason: str,
        verification_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Trigger rollback for a failed plan."""
        try:
            with self.get_cursor() as cur:
                # Get the rollback plan
                cur.execute("""
                    SELECT rollback_plan FROM action_plans WHERE plan_id = %s
                """, (plan_id,))
                row = cur.fetchone()
                rollback_plan = row[0] if row else None

                # Create rollback log entry
                cur.execute("""
                    INSERT INTO rollback_log (
                        plan_id, verification_id, trigger_reason,
                        rollback_steps, rollback_status
                    ) VALUES (%s, %s, %s, %s, 'pending')
                    RETURNING id
                """, (
                    plan_id,
                    verification_id,
                    reason,
                    json.dumps(rollback_plan) if rollback_plan else None
                ))
                rollback_id = cur.fetchone()[0]

                # Update plan status
                cur.execute("""
                    UPDATE action_plans SET status = 'rolled_back'
                    WHERE plan_id = %s
                """, (plan_id,))

                return {
                    "rollback_id": rollback_id,
                    "plan_id": plan_id,
                    "reason": reason,
                    "rollback_plan": rollback_plan,
                    "status": "pending"
                }
        except Exception as e:
            logger.error(f"Failed to trigger rollback: {e}")
            raise

    def complete_rollback(
        self,
        rollback_id: int,
        status: str,
        post_state: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark rollback as complete."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    UPDATE rollback_log
                    SET rollback_status = %s,
                        completed_at = NOW(),
                        post_rollback_state = %s,
                        state_recovered = %s,
                        notes = %s
                    WHERE id = %s
                    RETURNING plan_id
                """, (
                    status,
                    json.dumps(post_state) if post_state else None,
                    status == "success",
                    notes,
                    rollback_id
                ))
                plan_id = cur.fetchone()[0]

                return {
                    "rollback_id": rollback_id,
                    "plan_id": plan_id,
                    "status": status,
                    "state_recovered": status == "success"
                }
        except Exception as e:
            logger.error(f"Failed to complete rollback: {e}")
            raise

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_active_plans(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get plans that need attention."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT plan_id, action_type, action_name, expected_outcome,
                           status, risk_tier, created_at, execution_status,
                           executed_at, verification_passed, action_taken
                    FROM v_active_plans
                    LIMIT %s
                """, (limit,))

                return [
                    {
                        "plan_id": row[0],
                        "action_type": row[1],
                        "action_name": row[2],
                        "expected_outcome": row[3],
                        "status": row[4],
                        "risk_tier": row[5],
                        "created_at": row[6].isoformat() if row[6] else None,
                        "execution_status": row[7],
                        "executed_at": row[8].isoformat() if row[8] else None,
                        "verification_passed": row[9],
                        "action_taken": row[10]
                    }
                    for row in cur.fetchall()
                ]
        except Exception as e:
            logger.error(f"Failed to get active plans: {e}")
            return []

    def get_failed_verifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get failed verifications needing review."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT plan_id, action_name, expected_outcome,
                           actual_outcome, discrepancies, action_taken,
                           verified_at, human_reviewed
                    FROM v_failed_verifications
                    LIMIT %s
                """, (limit,))

                return [
                    {
                        "plan_id": row[0],
                        "action_name": row[1],
                        "expected_outcome": row[2],
                        "actual_outcome": row[3],
                        "discrepancies": row[4],
                        "action_taken": row[5],
                        "verified_at": row[6].isoformat() if row[6] else None,
                        "human_reviewed": row[7]
                    }
                    for row in cur.fetchall()
                ]
        except Exception as e:
            logger.error(f"Failed to get failed verifications: {e}")
            return []

    def get_verification_stats(self) -> Dict[str, Any]:
        """Get verification statistics."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    SELECT action_type, total_plans, verified_count,
                           failed_count, rolled_back_count, success_rate_pct
                    FROM v_verification_stats
                """)

                stats_by_type = {
                    row[0]: {
                        "total": row[1],
                        "verified": row[2],
                        "failed": row[3],
                        "rolled_back": row[4],
                        "success_rate": float(row[5]) if row[5] else 0
                    }
                    for row in cur.fetchall()
                }

                # Get overall stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'verified') as verified,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        COUNT(*) FILTER (WHERE status = 'rolled_back') as rolled_back
                    FROM action_plans
                """)
                row = cur.fetchone()

                return {
                    "overall": {
                        "total_plans": row[0],
                        "verified": row[1],
                        "failed": row[2],
                        "rolled_back": row[3],
                        "success_rate": round(100 * row[1] / row[0], 2) if row[0] > 0 else 0
                    },
                    "by_action_type": stats_by_type
                }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}

    def mark_reviewed(
        self,
        plan_id: str,
        reviewer: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark a failed verification as human-reviewed."""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    UPDATE verification_results
                    SET human_reviewed = TRUE,
                        reviewer = %s,
                        review_notes = %s,
                        reviewed_at = NOW()
                    WHERE plan_id = %s
                    RETURNING id
                """, (reviewer, notes, plan_id))
                row = cur.fetchone()

                if not row:
                    return {"success": False, "error": "Verification not found"}

                return {
                    "success": True,
                    "verification_id": row[0],
                    "reviewer": reviewer
                }
        except Exception as e:
            logger.error(f"Failed to mark reviewed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service_instance: Optional[VerifyBeforeActService] = None


def get_verify_service() -> VerifyBeforeActService:
    """Get the singleton service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = VerifyBeforeActService()
    return _service_instance
