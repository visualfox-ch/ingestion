"""
Phase 1: Auto-Approval Decision Engine

Conditional auto-approval based on:
- Risk level (R0-R3)
- Confidence score (0.0-1.0)
- User role (RBAC tier)
- Time restrictions (business hours)

Decision Tree:
  R0 + confidence >75% + autonomous tier → AUTO-APPROVE ✅
  R0/R1 + confidence >90% + manager+ → NOTIFY + AUTO-APPROVE ✅
  R2/R3 → ALWAYS MANUAL 🔔
  Outside business hours → QUEUE 📅
"""

from typing import Tuple, Dict, Optional, Any
from datetime import datetime, timedelta
from enum import Enum

from .observability import get_logger, log_with_context
from .db_safety import safe_write_query, safe_list_query
from .permission_matrix import PermissionMatrix, UserRole, RiskLevel
from .risk_models import RiskClass
from .confidence_scorer import JarvisConfidenceScorer
from .hot_config import get_hot_config
from . import feature_flags

logger = get_logger("jarvis.approval_auto")


class ApprovalDecision(Enum):
    """Auto-approval decision outcomes."""
    AUTO_APPROVED = "auto_approved"      # Execute immediately
    MANUAL_REQUIRED = "manual_required"  # Request manual approval
    QUEUED = "queued"                    # Queue for business hours
    SKIPPED = "skipped"                  # Feature disabled


class AutoApprovalEngine:
    """
    Phase 1 conditional auto-approval logic.
    
    Safety First: Conservative thresholds, comprehensive logging,
    easy rollback to Phase 0 (all manual).
    """

    # Decision thresholds by phase
    THRESHOLDS = {
        "phase_1": {
            "r0_confidence": 0.75,
            "r1_confidence": 0.90,
            "r2_confidence": 0.99,  # Very high bar for high-risk
            "r3_confidence": 1.0,   # Not allowed even with 100% confidence
        },
        "phase_2": {
            "r0_confidence": 0.70,
            "r1_confidence": 0.85,
            "r2_confidence": 0.95,
            "r3_confidence": 0.99,  # Allowed but very high bar
        }
    }

    # Role-based approval escalation
    ROLE_AUTO_APPROVAL = {
        UserRole.ADMIN: {"r0": True, "r1": True, "r2": False, "r3": False},
        UserRole.MANAGER: {"r0": True, "r1": True, "r2": False, "r3": False},
        UserRole.USER: {"r0": True, "r1": False, "r2": False, "r3": False},
        UserRole.VIEWER: {"r0": False, "r1": False, "r2": False, "r3": False},
        UserRole.SERVICE: {"r0": True, "r1": True, "r2": False, "r3": False},  # High trust
    }

    ROLE_AUTO_APPROVAL_PHASE2 = {
        UserRole.ADMIN: {"r2": True},
        UserRole.MANAGER: {"r2": True},
        UserRole.USER: {"r2": False},
        UserRole.VIEWER: {"r2": False},
        UserRole.SERVICE: {"r2": True},
    }

    @staticmethod
    def _is_feature_enabled() -> bool:
        hot_enabled = get_hot_config("auto_approval_enabled", True)
        flag_enabled = feature_flags.is_enabled("auto_approval", default=True)
        return bool(hot_enabled) and bool(flag_enabled)

    @staticmethod
    def _get_runtime_phase(default_phase: int = 1) -> int:
        try:
            phase = int(get_hot_config("auto_approval_phase", default_phase))
        except (TypeError, ValueError):
            phase = default_phase
        return max(0, min(2, phase))

    @staticmethod
    def _get_thresholds(phase: int) -> Dict[str, float]:
        thresholds = dict(AutoApprovalEngine.THRESHOLDS.get(f"phase_{phase}", AutoApprovalEngine.THRESHOLDS["phase_1"]))
        overrides = {
            "r0_confidence": get_hot_config("auto_approval_r0_threshold", -1.0),
            "r1_confidence": get_hot_config("auto_approval_r1_threshold", -1.0),
            "r2_confidence": get_hot_config("auto_approval_r2_threshold", -1.0),
            "r3_confidence": get_hot_config("auto_approval_r3_threshold", -1.0),
        }
        for key, value in overrides.items():
            if isinstance(value, (int, float)) and value >= 0:
                thresholds[key] = float(value)
        return thresholds

    @staticmethod
    def should_auto_approve(
        change_id: str,
        audit_id: str,
        risk_level: RiskLevel,
        confidence_score: float,
        user_id: Optional[int] = None,
        phase: int = 1,
        enable_feature: bool = True
    ) -> Tuple[ApprovalDecision, str]:
        """
        Determine if change should be auto-approved based on decision tree.

        Args:
            change_id: Change identifier
            audit_id: Audit trail ID
            risk_level: Risk classification (R0-R3)
            confidence_score: Confidence score (0.0-1.0)
            user_id: ID of user who proposed change
            phase: Current autonomy phase (1 or 2)
            enable_feature: Feature flag to disable auto-approval

        Returns:
            (ApprovalDecision, reason_string)
        """

        # Feature flag check
        if enable_feature:
            enable_feature = AutoApprovalEngine._is_feature_enabled()
        if not enable_feature:
            return ApprovalDecision.SKIPPED, "Auto-approval disabled (Phase 0 fallback)"

        # Resolve runtime phase if not explicitly set
        if phase is None:
            phase = AutoApprovalEngine._get_runtime_phase()

        # Get threshold for this phase
        thresholds = AutoApprovalEngine._get_thresholds(phase)

        # Map RiskLevel to string
        risk_str = risk_level.value.lower()  # "R0", "R1", "R2", "R3"
        risk_short = risk_str.replace("r", "")  # "0", "1", "2", "3"

        # Time check: outside business hours?
        if not AutoApprovalEngine._is_business_hours():
            return ApprovalDecision.QUEUED, "Outside business hours - queued for next day"

        # R3 (Critical) - never auto-approve
        if risk_short == "3":
            return ApprovalDecision.MANUAL_REQUIRED, "R3 (critical) requires manual approval"

        # Get user role for escalation decision
        user_role = None
        if user_id:
            user_role = PermissionMatrix.get_user_role(user_id)

        # Decision tree: Risk Level + Confidence + Role
        if risk_short == "0":  # R0 (Low)
            threshold = thresholds.get("r0_confidence", 0.75)
            if confidence_score >= threshold:
                reason = f"R0 + {confidence_score:.1%} confidence ≥ {threshold:.1%} threshold"

                # Role check: can this user auto-approve R0?
                if user_role and user_role not in AutoApprovalEngine.ROLE_AUTO_APPROVAL:
                    user_role = UserRole.USER  # Default fallback

                if user_role and AutoApprovalEngine.ROLE_AUTO_APPROVAL[user_role].get("r0", False):
                    return ApprovalDecision.AUTO_APPROVED, reason
                elif user_role is None:
                    # No user context (system change) - auto-approve
                    return ApprovalDecision.AUTO_APPROVED, reason + " (system change)"
                else:
                    return ApprovalDecision.MANUAL_REQUIRED, f"User role {user_role.value} cannot auto-approve R0"
            else:
                return ApprovalDecision.MANUAL_REQUIRED, f"R0 confidence {confidence_score:.1%} < {threshold:.1%} threshold"

        elif risk_short == "1":  # R1 (Medium)
            threshold = thresholds.get("r1_confidence", 0.90)
            if confidence_score >= threshold:
                reason = f"R1 + {confidence_score:.1%} confidence ≥ {threshold:.1%} threshold"

                # Role check: can this user auto-approve R1?
                if user_role and user_role not in AutoApprovalEngine.ROLE_AUTO_APPROVAL:
                    user_role = UserRole.USER

                if user_role and AutoApprovalEngine.ROLE_AUTO_APPROVAL[user_role].get("r1", False):
                    return ApprovalDecision.AUTO_APPROVED, reason
                elif user_role is None:
                    return ApprovalDecision.AUTO_APPROVED, reason + " (system change)"
                else:
                    return ApprovalDecision.MANUAL_REQUIRED, f"User role {user_role.value} cannot auto-approve R1"
            else:
                return ApprovalDecision.MANUAL_REQUIRED, f"R1 confidence {confidence_score:.1%} < {threshold:.1%} threshold"

        elif risk_short == "2":  # R2 (High)
            threshold = thresholds.get("r2_confidence", 0.99)
            if phase >= 2 and confidence_score >= threshold:
                reason = f"R2 + {confidence_score:.1%} confidence ≥ {threshold:.1%} threshold (Phase 2)"

                if user_role and user_role not in AutoApprovalEngine.ROLE_AUTO_APPROVAL_PHASE2:
                    user_role = UserRole.USER

                if user_role and AutoApprovalEngine.ROLE_AUTO_APPROVAL_PHASE2[user_role].get("r2", False):
                    return ApprovalDecision.AUTO_APPROVED, reason
                elif user_role is None:
                    return ApprovalDecision.AUTO_APPROVED, reason + " (system change)"
                else:
                    return ApprovalDecision.MANUAL_REQUIRED, f"User role {user_role.value} cannot auto-approve R2"

            return ApprovalDecision.MANUAL_REQUIRED, "R2 (high) requires manual approval"

        # Fallback
        return ApprovalDecision.MANUAL_REQUIRED, "Unknown risk level"

    @staticmethod
    def _is_business_hours() -> bool:
        """Check if current time is during business hours (Mon-Fri 08:00-18:00 UTC)."""
        now_utc = datetime.utcnow()
        weekday = now_utc.weekday()  # 0=Mon, 4=Fri
        hour = now_utc.hour

        # Business hours: Monday-Friday, 08:00-18:00
        return weekday < 5 and 8 <= hour < 18

    @staticmethod
    def record_decision(
        change_id: str,
        audit_id: str,
        risk_level: RiskLevel,
        confidence_score: float,
        decision: ApprovalDecision,
        reason: str,
        user_id: Optional[int] = None,
        user_role: Optional[str] = None
    ) -> bool:
        """
        Record auto-approval decision in database.
        
        Returns: True if recorded successfully, False on error
        """
        try:
            query = """
            INSERT INTO auto_approval_decisions (
                change_id,
                audit_id,
                risk_level,
                confidence_score,
                user_role,
                decision,
                decision_reason,
                created_at
            ) VALUES (
                %(change_id)s,
                %(audit_id)s,
                %(risk_level)s,
                %(confidence)s,
                %(user_role)s,
                %(decision)s,
                %(reason)s,
                CURRENT_TIMESTAMP
            );
            """

            params = {
                "change_id": change_id,
                "audit_id": audit_id,
                "risk_level": risk_level.value,
                "confidence": confidence_score,
                "user_role": user_role or "unknown",
                "decision": decision.value,
                "reason": reason,
            }

            safe_write_query(query, params, context="record_auto_approval_decision")

            log_with_context(
                logger, "info",
                "Auto-approval decision recorded",
                change_id=change_id,
                audit_id=audit_id,
                decision=decision.value,
                confidence=f"{confidence_score:.1%}",
                risk=risk_level.value
            )

            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to record auto-approval decision", error=str(e))
            return False

    @staticmethod
    def report_false_positive(
        auto_approval_id: int,
        change_id: str,
        audit_id: str,
        expected_behavior: str,
        actual_behavior: str,
        impact: str = "minor",
        reported_by: Optional[int] = None
    ) -> bool:
        """
        Report a false positive (auto-approval that led to bad outcome).
        
        Used to tune confidence model over time.
        """
        try:
            query = """
            INSERT INTO confidence_false_positives (
                auto_approval_id,
                change_id,
                audit_id,
                expected_behavior,
                actual_behavior,
                impact,
                reported_by,
                created_at
            ) VALUES (
                %(auto_approval_id)s,
                %(change_id)s,
                %(audit_id)s,
                %(expected)s,
                %(actual)s,
                %(impact)s,
                %(reported_by)s,
                CURRENT_TIMESTAMP
            );
            """

            params = {
                "auto_approval_id": auto_approval_id,
                "change_id": change_id,
                "audit_id": audit_id,
                "expected": expected_behavior,
                "actual": actual_behavior,
                "impact": impact,
                "reported_by": reported_by,
            }

            safe_write_query(query, params, context="report_false_positive")

            log_with_context(
                logger, "warning",
                "False positive reported",
                change_id=change_id,
                impact=impact
            )

            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to report false positive", error=str(e))
            return False

    @staticmethod
    def get_false_positive_rate(days_back: int = 7) -> Dict[str, Any]:
        """
        Get false positive rate statistics for confidence model tuning.
        """
        try:
            query = """
            SELECT
                DATE(aad.created_at) as date,
                COUNT(*) as total_auto_approvals,
                COUNT(CASE WHEN cfp.id IS NOT NULL THEN 1 END) as false_positives,
                ROUND(
                    100.0 * COUNT(CASE WHEN cfp.id IS NOT NULL THEN 1 END) /
                    NULLIF(COUNT(*), 0),
                    2
                ) as false_positive_rate,
                STRING_AGG(DISTINCT cfp.impact, ',') as impact_types
            FROM auto_approval_decisions aad
            LEFT JOIN confidence_false_positives cfp ON aad.id = cfp.auto_approval_id
            WHERE aad.created_at >= NOW() - INTERVAL '%(days)s days'
            GROUP BY DATE(aad.created_at)
            ORDER BY DATE(aad.created_at) DESC;
            """

            results = safe_list_query(
                query,
                {"days": days_back},
                context="get_false_positive_rate"
            )

            return {
                "days_analyzed": days_back,
                "data": [dict(r) for r in results] if results else [],
                "summary": {
                    "total": sum(r.get("total_auto_approvals", 0) for r in (results or [])),
                    "false_positives": sum(r.get("false_positives", 0) for r in (results or []))
                }
            }
        except Exception as e:
            log_with_context(logger, "error", "Failed to get false positive rate", error=str(e))
            return {}
