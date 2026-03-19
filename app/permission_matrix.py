"""
Permission Matrix (Gate B Hardening)

Advanced permission system with:
- Role-based access control (RBAC)
- Risk scoring & dynamic tier escalation
- Time-based restrictions
- Audit trail integration with approvals
- Rate limiting per user/action

Policy Foundation: jarvis_permissions.yaml + user roles
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from .observability import get_logger, log_with_context
from .db_safety import safe_write_query, safe_list_query
from .permissions import get_permission, check_permission

logger = get_logger("jarvis.permission_matrix")


class UserRole(Enum):
    """User roles for RBAC."""
    ADMIN = "admin"          # Full access
    MANAGER = "manager"      # Most actions
    USER = "user"            # Limited actions
    VIEWER = "viewer"        # Read-only
    SERVICE = "service"      # System integration


class RiskLevel(Enum):
    """Risk assessment for dynamic tier escalation."""
    LOW = "low"              # R0 - Low impact
    MEDIUM = "medium"        # R1 - Medium impact
    HIGH = "high"            # R2 - High impact
    CRITICAL = "critical"    # R3 - Critical impact


class PermissionMatrix:
    """
    Gate B: Hardened permission matrix with role-based access control.
    """

    # Role-to-action-tier mappings
    ROLE_TIER_OVERRIDES = {
        UserRole.ADMIN: {
            # Admin overrides: escalate tiers upward (more permissive)
            "autonomous": "autonomous",
            "notify": "autonomous",
            "approve_standard": "notify",
            "approve_critical": "approve_standard",
            "forbidden": "approve_critical"  # Admin can request override
        },
        UserRole.MANAGER: {
            "autonomous": "autonomous",
            "notify": "notify",
            "approve_standard": "approve_standard",
            "approve_critical": "approve_critical",
            "forbidden": "forbidden"
        },
        UserRole.USER: {
            "autonomous": "autonomous",
            "notify": "notify",
            "approve_standard": "approve_critical",  # Escalate
            "approve_critical": "forbidden",          # Blocked
            "forbidden": "forbidden"
        },
        UserRole.VIEWER: {
            "autonomous": "autonomous",  # Read-only allowed
            "notify": "approve_standard",  # Escalate
            "approve_standard": "forbidden",
            "approve_critical": "forbidden",
            "forbidden": "forbidden"
        },
        UserRole.SERVICE: {
            # Service account: high trust for integration
            "autonomous": "autonomous",
            "notify": "autonomous",
            "approve_standard": "notify",
            "approve_critical": "approve_standard",
            "forbidden": "forbidden"
        }
    }

    # Risk-based tier escalation
    RISK_TIER_ESCALATION = {
        RiskLevel.LOW: {
            "autonomous": "autonomous",
            "notify": "notify",
            "approve_standard": "approve_standard",
            "approve_critical": "approve_critical"
        },
        RiskLevel.MEDIUM: {
            "autonomous": "notify",
            "notify": "approve_standard",
            "approve_standard": "approve_standard",
            "approve_critical": "approve_critical"
        },
        RiskLevel.HIGH: {
            "autonomous": "approve_standard",
            "notify": "approve_standard",
            "approve_standard": "approve_critical",
            "approve_critical": "approve_critical"
        },
        RiskLevel.CRITICAL: {
            # All escalate to critical
            "autonomous": "approve_critical",
            "notify": "approve_critical",
            "approve_standard": "approve_critical",
            "approve_critical": "approve_critical",
            "forbidden": "forbidden"
        }
    }

    # Time-based restrictions (24h format, UTC)
    TIME_RESTRICTIONS = {
        "critical_actions_business_hours_only": {
            "actions": ["code_modify", "delete_permanent", "user_delete"],
            "allowed_hours": (8, 18),  # 08:00-18:00 UTC
            "allowed_days": (0, 1, 2, 3, 4)  # Mon-Fri
        },
        "readonly_during_backup": {
            "actions": ["*"],
            "block_during": "backup_window",  # Sunday 02:00-04:00 UTC
            "fallback": "queue"
        }
    }

    @staticmethod
    def get_user_role(user_id: int) -> Optional[UserRole]:
        """
        Get user's role from database.
        Maps to user_learned_preferences or user table.
        """
        try:
            query = """
            SELECT COALESCE(role, 'user') as role
            FROM users
            WHERE id = %(user_id)s;
            """
            with safe_list_query("users") as cur:
                cur.execute(query, {"user_id": user_id})
                results = cur.fetchall()
            
            if results and len(results) > 0:
                role_str = results[0].get("role", "user").lower()
                try:
                    return UserRole[role_str.upper()]
                except KeyError:
                    return UserRole.USER
            return UserRole.USER
        except Exception as e:
            log_with_context(logger, "warning", "Failed to get user role", error=str(e), user_id=user_id)
            return UserRole.USER

    @staticmethod
    def assess_risk(
        action: str,
        context: Dict[str, Any]
    ) -> RiskLevel:
        """
        Assess risk of an action based on context.
        
        Risk factors:
        - File paths (system files higher risk)
        - Data sensitivity (PII, secrets)
        - Change scope (LOC affected)
        - Rollback capability (reversible vs permanent)
        """
        risk_score = 0.0
        
        # File path risk
        forbidden_patterns = ["/sys", "/etc", "secrets", ".env", "password"]
        if "file_path" in context:
            path = context["file_path"]
            for pattern in forbidden_patterns:
                if pattern in path:
                    risk_score += 0.3
        
        # Data sensitivity
        if context.get("data_type") == "pii":
            risk_score += 0.4
        elif context.get("data_type") == "secrets":
            risk_score += 0.5
        
        # Change scope
        lines_changed = context.get("lines_changed", 0)
        if lines_changed > 500:
            risk_score += 0.2
        
        # Reversibility
        if context.get("reversible") is False:
            risk_score += 0.3
        
        # Determine risk level
        if risk_score >= 0.8:
            return RiskLevel.CRITICAL
        elif risk_score >= 0.5:
            return RiskLevel.HIGH
        elif risk_score >= 0.2:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    @staticmethod
    def check_time_restrictions(action: str) -> Optional[str]:
        """
        Check if action is allowed at current time.
        Returns None if allowed, reason string if blocked.
        """
        now_utc = datetime.utcnow()
        
        for restriction_name, restriction in PermissionMatrix.TIME_RESTRICTIONS.items():
            # Check if action matches restriction
            restricted_actions = restriction.get("actions", [])
            if "*" not in restricted_actions and action not in restricted_actions:
                continue
            
            # Check time window
            if "allowed_hours" in restriction:
                start_hour, end_hour = restriction["allowed_hours"]
                if not (start_hour <= now_utc.hour < end_hour):
                    return f"Action blocked: only allowed during {start_hour:02d}:00-{end_hour:02d}:00 UTC"
            
            # Check allowed days
            if "allowed_days" in restriction:
                if now_utc.weekday() not in restriction["allowed_days"]:
                    return "Action blocked: only allowed on business days (Mon-Fri)"
        
        return None

    @staticmethod
    def check_rate_limit(
        user_id: int,
        action: str,
        window_minutes: int = 60,
        max_count: int = 10
    ) -> bool:
        """
        Check if user has exceeded rate limit for action.
        Returns True if within limits, False if exceeded.
        """
        try:
            query = """
            SELECT COUNT(*) as count
            FROM permission_audit
            WHERE actor = %(actor)s
            AND action = %(action)s
            AND created_at >= NOW() - INTERVAL '%(window)s minutes'
            """
            
            params = {
                "actor": str(user_id),
                "action": action,
                "window": window_minutes
            }
            
            with safe_list_query("permission_audit") as cur:
                cur.execute(query, params)
                results = cur.fetchall()
            
            if results and len(results) > 0:
                count = results[0].get("count", 0)
                return count < max_count
            
            return True
        except Exception as e:
            log_with_context(logger, "warning", "Failed to check rate limit", error=str(e))
            return True  # Allow on error

    @staticmethod
    def check_permission_with_context(
        action: str,
        user_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Check permission with full context: role + risk + time + rate limit.
        
        Returns enhanced permission result with all factors considered.
        """
        context = context or {}
        
        # Step 1: Base permission from policy
        base_perm = check_permission(action, actor="jarvis", context=context)
        
        # Step 2: Apply role-based override
        if user_id:
            user_role = PermissionMatrix.get_user_role(user_id)
            base_tier = base_perm.get("tier", "approve_standard")
            
            if user_role in PermissionMatrix.ROLE_TIER_OVERRIDES:
                overrides = PermissionMatrix.ROLE_TIER_OVERRIDES[user_role]
                escalated_tier = overrides.get(base_tier, base_tier)
                
                base_perm["tier"] = escalated_tier
                base_perm["tier_reason"] = f"Role {user_role.value} applied"
        
        # Step 3: Apply risk-based escalation
        risk = PermissionMatrix.assess_risk(action, context)
        base_tier = base_perm.get("tier", "approve_standard")
        
        escalations = PermissionMatrix.RISK_TIER_ESCALATION[risk]
        escalated_tier = escalations.get(base_tier, base_tier)
        
        if escalated_tier != base_tier:
            base_perm["tier"] = escalated_tier
            base_perm["risk_level"] = risk.value
            base_perm["risk_reason"] = f"Risk level {risk.value} escalated tier"
        
        # Step 4: Check time restrictions
        time_block = PermissionMatrix.check_time_restrictions(action)
        if time_block:
            base_perm["allowed"] = False
            base_perm["time_restriction"] = time_block
            base_perm["requires_approval"] = True
        
        # Step 5: Check rate limits
        if user_id and not base_perm.get("allowed", False):
            if not PermissionMatrix.check_rate_limit(user_id, action):
                base_perm["rate_limited"] = True
                base_perm["reason"] = "Rate limit exceeded"
        
        # Step 6: Update final allowed status based on tier
        final_tier = base_perm.get("tier", "approve_standard")
        if final_tier in ("autonomous", "notify"):
            base_perm["allowed"] = True
        else:
            base_perm["allowed"] = False
            base_perm["requires_approval"] = True
        
        return base_perm

    @staticmethod
    def log_decision_link(
        audit_id: str,
        permission_result: Dict[str, Any],
        decision: str
    ) -> bool:
        """
        Link a permission check to an approval decision.
        Creates audit trail correlation.
        """
        try:
            insert_sql = """
            INSERT INTO permission_decision_log (
                audit_id,
                permission_tier,
                risk_level,
                user_role,
                decision,
                created_at
            ) VALUES (
                %(audit_id)s,
                %(tier)s,
                %(risk_level)s,
                %(user_role)s,
                %(decision)s,
                CURRENT_TIMESTAMP
            );
            """
            
            params = {
                "audit_id": audit_id,
                "tier": permission_result.get("tier"),
                "risk_level": permission_result.get("risk_level"),
                "user_role": permission_result.get("user_role"),
                "decision": decision
            }
            
            with safe_write_query("permission_decision_log") as cur:
                cur.execute(insert_sql, params)
            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to log decision link", error=str(e), audit_id=audit_id)
            return False

    @staticmethod
    def get_permission_stats(user_id: int = None, days_back: int = 7) -> Dict[str, Any]:
        """Get permission check statistics for monitoring."""
        try:
            query = """
            SELECT
                action,
                result,
                COUNT(*) as count,
                COUNT(CASE WHEN result = 'denied_forbidden' THEN 1 END) as denied_count
            FROM permission_audit
            WHERE created_at >= NOW() - INTERVAL '%(days)s days'
            """
            
            params = {"days": days_back}
            
            if user_id:
                query += " AND actor = %(actor)s"
                params["actor"] = str(user_id)
            
            query += " GROUP BY action, result ORDER BY count DESC;"
            
            with safe_list_query("permission_audit") as cur:
                cur.execute(query, params)
                results = cur.fetchall()
            return {
                "summary": [dict(r) for r in results] if results else [],
                "queried_days": days_back,
                "user_id": user_id
            }
        except Exception as e:
            log_with_context(logger, "error", "Failed to get permission stats", error=str(e))
            return {}
