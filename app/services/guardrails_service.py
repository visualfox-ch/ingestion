"""
Guardrails Service - Phase L0 (Leitplanken-System)

Central safety layer for autonomous actions.
MUST be checked before ANY autonomous action.

Key principle: Check BEFORE acting, not after.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import json

logger = logging.getLogger(__name__)

# Singleton instance
_guardrails_service = None


def get_guardrails_service():
    """Get or create the singleton GuardrailsService instance."""
    global _guardrails_service
    if _guardrails_service is None:
        _guardrails_service = GuardrailsService()
    return _guardrails_service


class GuardrailCheckResult:
    """Result of a guardrail check."""

    def __init__(
        self,
        passed: bool,
        guardrail_id: int = None,
        guardrail_name: str = None,
        guardrail_type: str = None,
        reason: str = None,
        action: str = None,
        override_allowed: bool = False,
        override_requires: str = None
    ):
        self.passed = passed
        self.guardrail_id = guardrail_id
        self.guardrail_name = guardrail_name
        self.guardrail_type = guardrail_type
        self.reason = reason
        self.action = action
        self.override_allowed = override_allowed
        self.override_requires = override_requires

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "guardrail_id": self.guardrail_id,
            "guardrail_name": self.guardrail_name,
            "guardrail_type": self.guardrail_type,
            "reason": self.reason,
            "action": self.action,
            "override_allowed": self.override_allowed,
            "override_requires": self.override_requires
        }


class GuardrailsService:
    """
    Leitplanken-System: Central safety layer for Jarvis autonomy.

    Three types of guardrails:
    - HARD: Never override (e.g., no credential exposure)
    - SOFT: Can be overridden with user confirmation
    - CONTEXT: Apply based on situation (time, domain, etc.)
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _get_cursor(self):
        """Get database cursor."""
        from app.db_client import get_cursor
        return get_cursor()

    def check_before_action(
        self,
        action_type: str,
        action_details: Dict[str, Any],
        tool_name: str = None,
        domain: str = None,
        session_id: str = None,
        user_id: str = None,
        source: str = None,
        context: Dict[str, Any] = None
    ) -> Tuple[bool, List[GuardrailCheckResult], int]:
        """
        Central guardrail check - MUST be called before any autonomous action.

        Returns:
            Tuple of (all_passed, check_results, audit_id)
        """
        start_time = datetime.now()
        results = []

        try:
            # L0.1: Check tool risk tier FIRST (before other guardrails)
            if tool_name and action_type == "tool_call":
                tier_result = self._check_tool_risk_tier(
                    tool_name=tool_name,
                    context=context or {},
                    session_id=session_id
                )
                if tier_result:
                    results.append(tier_result)

            # Get all active guardrails, ordered by priority
            guardrails = self._get_active_guardrails()

            for guardrail in guardrails:
                result = self._check_single_guardrail(
                    guardrail=guardrail,
                    action_type=action_type,
                    action_details=action_details,
                    tool_name=tool_name,
                    domain=domain,
                    context=context or {}
                )
                if result:
                    results.append(result)

            # Check for active overrides
            results = self._apply_overrides(results, session_id)

            # Determine overall result
            all_passed = all(r.passed for r in results)
            blocking_guardrail = next((r for r in results if not r.passed), None)

            # Log to audit
            audit_id = self._log_audit(
                action_type=action_type,
                action_details=action_details,
                results=results,
                all_passed=all_passed,
                blocking_guardrail=blocking_guardrail,
                session_id=session_id,
                user_id=user_id,
                source=source,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )

            return all_passed, results, audit_id

        except Exception as e:
            self.logger.error(f"Guardrail check failed: {e}")
            # Fail closed - if check fails, block the action
            error_result = GuardrailCheckResult(
                passed=False,
                reason=f"Guardrail check error: {str(e)}",
                action="block"
            )
            return False, [error_result], None

    def _get_active_guardrails(self) -> List[Dict]:
        """Get all active guardrails ordered by priority."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT id, name, description, guardrail_type, scope, scope_pattern,
                           condition, action_on_violation, override_allowed,
                           override_requires, context_conditions, priority
                    FROM guardrails
                    WHERE is_active = TRUE
                    ORDER BY priority ASC
                """)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            self.logger.error(f"Failed to get guardrails: {e}")
            return []

    def _check_tool_risk_tier(
        self,
        tool_name: str,
        context: Dict = None,
        session_id: str = None
    ) -> Optional[GuardrailCheckResult]:
        """
        L0.1: Check tool risk tier and return result if blocked.

        Tiers:
        - 0: Always allowed (read-only)
        - 1: Requires confidence >= 80%
        - 2: Requires user confirmation
        - 3: Requires explicit override
        """
        context = context or {}
        try:
            with self._get_cursor() as cur:
                # Get tool's risk tier
                cur.execute("""
                    SELECT t.risk_tier, r.name, r.requirement, r.min_confidence,
                           r.requires_confirmation, r.requires_override, r.auto_approve
                    FROM jarvis_tools t
                    LEFT JOIN tool_risk_tiers r ON t.risk_tier = r.tier
                    WHERE t.name = %s AND t.enabled = TRUE
                """, (tool_name,))
                row = cur.fetchone()

                if not row:
                    # Tool not found or disabled - default to tier 1
                    return None

                risk_tier, tier_name, requirement, min_confidence, requires_confirm, requires_override, auto_approve = row

                # Tier 0: Always allowed
                if risk_tier == 0 or auto_approve:
                    return None  # Pass

                # Tier 1: Check confidence
                if risk_tier == 1:
                    confidence = context.get('confidence', 0.5)
                    min_conf = min_confidence or 0.8
                    if confidence >= min_conf:
                        return None  # Pass
                    return GuardrailCheckResult(
                        passed=False,
                        guardrail_name=f"risk_tier_{risk_tier}",
                        guardrail_type="risk_tier",
                        reason=f"Tool '{tool_name}' requires confidence >= {min_conf:.0%}, got {confidence:.0%}",
                        action="ask_user",
                        override_allowed=True,
                        override_requires="user_confirmation"
                    )

                # Tier 2: Requires user confirmation
                if risk_tier == 2:
                    # Check if already confirmed in this session
                    if self._has_session_confirmation(session_id, tool_name):
                        return None  # Already confirmed
                    return GuardrailCheckResult(
                        passed=False,
                        guardrail_name=f"risk_tier_{risk_tier}",
                        guardrail_type="risk_tier",
                        reason=f"Tool '{tool_name}' (tier 2: sensitive) requires user confirmation",
                        action="ask_user",
                        override_allowed=True,
                        override_requires="user_confirmation"
                    )

                # Tier 3: Requires explicit override
                if risk_tier == 3:
                    # Check for active override
                    if self._has_active_override_for_tool(tool_name, session_id):
                        return None  # Override active
                    return GuardrailCheckResult(
                        passed=False,
                        guardrail_name=f"risk_tier_{risk_tier}",
                        guardrail_type="risk_tier",
                        reason=f"Tool '{tool_name}' (tier 3: critical) requires explicit override",
                        action="block",
                        override_allowed=True,
                        override_requires="explicit_override"
                    )

                return None  # Default pass

        except Exception as e:
            self.logger.warning(f"Risk tier check failed for {tool_name}: {e}")
            return None  # Fail open on error (other guardrails will catch)

    def _has_session_confirmation(self, session_id: str, tool_name: str) -> bool:
        """Check if tool was confirmed in this session."""
        if not session_id:
            return False
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM guardrail_overrides
                    WHERE session_id = %s
                    AND revoked_at IS NULL
                    AND (valid_until IS NULL OR valid_until > NOW())
                    AND reason LIKE %s
                    LIMIT 1
                """, (session_id, f"%{tool_name}%"))
                return cur.fetchone() is not None
        except Exception:
            return False

    def _has_active_override_for_tool(self, tool_name: str, session_id: str = None) -> bool:
        """Check if there's an active override for this specific tool."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM guardrail_overrides o
                    JOIN guardrails g ON o.guardrail_id = g.id
                    WHERE o.revoked_at IS NULL
                    AND (o.valid_until IS NULL OR o.valid_until > NOW())
                    AND (o.session_id = %s OR o.session_id IS NULL)
                    AND g.scope_pattern LIKE %s
                    LIMIT 1
                """, (session_id, f"%{tool_name}%"))
                return cur.fetchone() is not None
        except Exception:
            return False

    def _check_single_guardrail(
        self,
        guardrail: Dict,
        action_type: str,
        action_details: Dict,
        tool_name: str = None,
        domain: str = None,
        context: Dict = None
    ) -> Optional[GuardrailCheckResult]:
        """Check if a single guardrail applies and if it passes."""
        context = context or {}

        # First check if this guardrail applies to this action
        if not self._guardrail_applies(guardrail, action_type, tool_name, domain, context):
            return None  # Doesn't apply, skip

        # Check context conditions for context-type guardrails
        if guardrail['guardrail_type'] == 'context':
            if not self._check_context_conditions(guardrail.get('context_conditions'), context):
                return None  # Context conditions not met, skip

        # Now check the actual condition
        condition = guardrail.get('condition', {})
        if isinstance(condition, str):
            condition = json.loads(condition)

        passed, reason = self._evaluate_condition(
            condition=condition,
            action_type=action_type,
            action_details=action_details,
            tool_name=tool_name,
            context=context
        )

        return GuardrailCheckResult(
            passed=passed,
            guardrail_id=guardrail['id'],
            guardrail_name=guardrail['name'],
            guardrail_type=guardrail['guardrail_type'],
            reason=reason,
            action=guardrail['action_on_violation'] if not passed else None,
            override_allowed=guardrail.get('override_allowed', False),
            override_requires=guardrail.get('override_requires')
        )

    def _guardrail_applies(
        self,
        guardrail: Dict,
        action_type: str,
        tool_name: str = None,
        domain: str = None,
        context: Dict = None
    ) -> bool:
        """Check if a guardrail applies to the given action."""
        scope = guardrail['scope']
        pattern = guardrail.get('scope_pattern')

        if scope == 'global':
            return True

        if scope == 'tool' and tool_name:
            if pattern:
                return bool(re.match(pattern, tool_name))
            return True

        if scope == 'action_type' and action_type:
            if pattern:
                return bool(re.search(pattern, action_type))
            return True

        if scope == 'domain' and domain:
            if pattern:
                return bool(re.match(pattern, domain))
            return True

        return False

    def _check_context_conditions(self, conditions: Dict, context: Dict) -> bool:
        """Check if context conditions are met for context-type guardrails."""
        if not conditions:
            return True

        if isinstance(conditions, str):
            conditions = json.loads(conditions)

        # Time range check
        if 'time_range' in conditions:
            time_range = conditions['time_range']
            tz_name = conditions.get('timezone', 'Europe/Zurich')
            if not self._in_time_range(time_range, tz_name):
                return False

        # Domain check
        if 'domain' in conditions:
            if context.get('domain') != conditions['domain']:
                return False

        return True

    def _in_time_range(self, time_range: str, tz_name: str) -> bool:
        """Check if current time is in the given range (e.g., '23:00-07:00')."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
            now = datetime.now(tz)
            current_time = now.time()

            start_str, end_str = time_range.split('-')
            start = datetime.strptime(start_str, '%H:%M').time()
            end = datetime.strptime(end_str, '%H:%M').time()

            # Handle overnight ranges (e.g., 23:00-07:00)
            if start > end:
                return current_time >= start or current_time <= end
            else:
                return start <= current_time <= end
        except Exception as e:
            self.logger.error(f"Time range check failed: {e}")
            return False

    def _evaluate_condition(
        self,
        condition: Dict,
        action_type: str,
        action_details: Dict,
        tool_name: str = None,
        context: Dict = None
    ) -> Tuple[bool, str]:
        """Evaluate a guardrail condition. Returns (passed, reason)."""
        check_type = condition.get('check', 'unknown')

        if check_type == 'requires_approval':
            # Check if this action type requires approval
            return False, "Action requires user approval"

        elif check_type == 'requires_explicit_confirmation':
            phrase = condition.get('confirmation_phrase', 'bestätigen')
            return False, f"Requires explicit confirmation with phrase: '{phrase}'"

        elif check_type == 'requires_review':
            reviewer = condition.get('reviewer', 'user')
            return False, f"Requires review by {reviewer}"

        elif check_type == 'rate_limit':
            # Would need to check actual usage - simplified for now
            return True, "Rate limit not exceeded"

        elif check_type == 'confidence_threshold':
            min_conf = condition.get('min_confidence', 0.8)
            actual_conf = action_details.get('confidence', 0)
            if actual_conf >= min_conf:
                return True, f"Confidence {actual_conf:.2f} meets threshold {min_conf}"
            return False, f"Confidence {actual_conf:.2f} below threshold {min_conf}"

        elif check_type == 'in_approved_list':
            # Check against autonomous tools list
            approved = self._get_approved_autonomous_tools()
            if tool_name in approved:
                return True, f"Tool {tool_name} is in approved list"
            return False, f"Tool {tool_name} not in approved autonomous list"

        elif check_type == 'chain_depth':
            max_depth = condition.get('max_depth', 3)
            current_depth = context.get('chain_depth', 0)
            if current_depth <= max_depth:
                return True, f"Chain depth {current_depth} within limit {max_depth}"
            return False, f"Chain depth {current_depth} exceeds limit {max_depth}"

        elif check_type == 'no_sensitive_data':
            patterns = condition.get('patterns', [])
            details_str = json.dumps(action_details).lower()
            for pattern in patterns:
                if pattern.lower() in details_str:
                    return False, f"Contains sensitive data pattern: {pattern}"
            return True, "No sensitive data detected"

        elif check_type == 'time_restriction':
            # Already handled in context conditions
            return False, "Time restriction in effect"

        else:
            self.logger.warning(f"Unknown check type: {check_type}")
            return True, f"Unknown check type {check_type} - passing"

    def _get_approved_autonomous_tools(self) -> List[str]:
        """Get list of tools approved for autonomous use."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT name FROM jarvis_tools
                    WHERE enabled = TRUE
                    AND requires_approval = FALSE
                """)
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            self.logger.error(f"Failed to get approved tools: {e}")
            return []

    def _apply_overrides(
        self,
        results: List[GuardrailCheckResult],
        session_id: str = None
    ) -> List[GuardrailCheckResult]:
        """Apply any active overrides to failed guardrails."""
        if not session_id:
            return results

        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT guardrail_id FROM guardrail_overrides
                    WHERE (session_id = %s OR session_id IS NULL)
                    AND revoked_at IS NULL
                    AND (valid_until IS NULL OR valid_until > NOW())
                """, (session_id,))
                active_overrides = {row[0] for row in cur.fetchall()}

            for result in results:
                if not result.passed and result.guardrail_id in active_overrides:
                    result.passed = True
                    result.reason = f"Override active for {result.guardrail_name}"
                    result.action = None

            return results
        except Exception as e:
            self.logger.error(f"Failed to apply overrides: {e}")
            return results

    def _log_audit(
        self,
        action_type: str,
        action_details: Dict,
        results: List[GuardrailCheckResult],
        all_passed: bool,
        blocking_guardrail: Optional[GuardrailCheckResult],
        session_id: str = None,
        user_id: str = None,
        source: str = None,
        duration_ms: int = None
    ) -> Optional[int]:
        """Log the guardrail check to audit table."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO autonomy_audit
                    (action_type, action_details, guardrails_checked, all_passed,
                     blocking_guardrail_id, session_id, user_id, source,
                     was_executed, execution_duration_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    action_type,
                    json.dumps(action_details),
                    json.dumps([r.to_dict() for r in results]),
                    all_passed,
                    blocking_guardrail.guardrail_id if blocking_guardrail else None,
                    session_id,
                    user_id,
                    source,
                    all_passed,  # was_executed = all_passed for now
                    duration_ms
                ))
                result = cur.fetchone()
                if not result:
                    return None

                # Support both tuple cursors and dict-like cursors.
                try:
                    return result[0]
                except Exception:
                    try:
                        return result.get("id")
                    except Exception:
                        return None
        except Exception as e:
            self.logger.error(f"Failed to log audit: {e}")
            return None

    # ============================================
    # Management Methods
    # ============================================

    def add_guardrail(
        self,
        name: str,
        guardrail_type: str,
        scope: str,
        condition: Dict,
        description: str = None,
        scope_pattern: str = None,
        action_on_violation: str = "block",
        override_allowed: bool = False,
        override_requires: str = None,
        context_conditions: Dict = None,
        priority: int = 100
    ) -> Dict[str, Any]:
        """Add a new guardrail."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO guardrails
                    (name, description, guardrail_type, scope, scope_pattern,
                     condition, action_on_violation, override_allowed,
                     override_requires, context_conditions, priority)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    name, description, guardrail_type, scope, scope_pattern,
                    json.dumps(condition), action_on_violation, override_allowed,
                    override_requires,
                    json.dumps(context_conditions) if context_conditions else None,
                    priority
                ))
                result = cur.fetchone()
                return {"success": True, "guardrail_id": result[0]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_guardrail(
        self,
        guardrail_id: int = None,
        name: str = None,
        **updates
    ) -> Dict[str, Any]:
        """Update an existing guardrail."""
        try:
            # Build update query dynamically
            set_clauses = []
            values = []

            for key, value in updates.items():
                if key in ['condition', 'context_conditions'] and isinstance(value, dict):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = %s")
                values.append(value)

            if not set_clauses:
                return {"success": False, "error": "No updates provided"}

            set_clauses.append("updated_at = NOW()")

            # Add identifier
            if guardrail_id:
                where_clause = "id = %s"
                values.append(guardrail_id)
            elif name:
                where_clause = "name = %s"
                values.append(name)
            else:
                return {"success": False, "error": "Must provide guardrail_id or name"}

            query = f"""
                UPDATE guardrails
                SET {', '.join(set_clauses)}
                WHERE {where_clause}
            """

            with self._get_cursor() as cur:
                cur.execute(query, values)
                return {"success": True, "rows_updated": cur.rowcount}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_guardrails(
        self,
        guardrail_type: str = None,
        scope: str = None,
        active_only: bool = True
    ) -> Dict[str, Any]:
        """Get guardrails with optional filtering."""
        try:
            conditions = []
            params = []

            if active_only:
                conditions.append("is_active = TRUE")
            if guardrail_type:
                conditions.append("guardrail_type = %s")
                params.append(guardrail_type)
            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            with self._get_cursor() as cur:
                cur.execute(f"""
                    SELECT id, name, description, guardrail_type, scope, scope_pattern,
                           condition, action_on_violation, override_allowed,
                           override_requires, context_conditions, priority, is_active,
                           created_at, updated_at
                    FROM guardrails
                    {where_clause}
                    ORDER BY priority ASC
                """, params)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]

                guardrails = []
                for row in rows:
                    g = dict(zip(columns, row))
                    # Parse JSON fields
                    if g.get('condition'):
                        g['condition'] = json.loads(g['condition']) if isinstance(g['condition'], str) else g['condition']
                    if g.get('context_conditions'):
                        g['context_conditions'] = json.loads(g['context_conditions']) if isinstance(g['context_conditions'], str) else g['context_conditions']
                    guardrails.append(g)

                return {"success": True, "guardrails": guardrails, "count": len(guardrails)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_override(
        self,
        guardrail_id: int = None,
        guardrail_name: str = None,
        override_type: str = "temporary",
        reason: str = "",
        valid_duration_hours: int = None,
        session_id: str = None,
        authorized_by: str = "user"
    ) -> Dict[str, Any]:
        """Create an override for a soft guardrail."""
        try:
            # Get guardrail ID from name if needed
            if not guardrail_id and guardrail_name:
                with self._get_cursor() as cur:
                    cur.execute("SELECT id, guardrail_type FROM guardrails WHERE name = %s", (guardrail_name,))
                    row = cur.fetchone()
                    if not row:
                        return {"success": False, "error": f"Guardrail '{guardrail_name}' not found"}
                    guardrail_id = row[0]
                    guardrail_type = row[1]
            else:
                with self._get_cursor() as cur:
                    cur.execute("SELECT guardrail_type FROM guardrails WHERE id = %s", (guardrail_id,))
                    row = cur.fetchone()
                    if not row:
                        return {"success": False, "error": f"Guardrail {guardrail_id} not found"}
                    guardrail_type = row[0]

            # Cannot override hard limits
            if guardrail_type == 'hard':
                return {"success": False, "error": "Cannot override hard limits"}

            valid_until = None
            if valid_duration_hours:
                valid_until = datetime.now() + timedelta(hours=valid_duration_hours)

            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO guardrail_overrides
                    (guardrail_id, override_type, reason, valid_until, session_id, authorized_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (guardrail_id, override_type, reason, valid_until, session_id, authorized_by))
                result = cur.fetchone()
                return {"success": True, "override_id": result[0], "valid_until": str(valid_until) if valid_until else "permanent"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def revoke_override(self, override_id: int, revoked_by: str = "user") -> Dict[str, Any]:
        """Revoke an active override."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    UPDATE guardrail_overrides
                    SET revoked_at = NOW(), revoked_by = %s
                    WHERE id = %s AND revoked_at IS NULL
                """, (revoked_by, override_id))
                return {"success": True, "rows_updated": cur.rowcount}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_audit_log(
        self,
        limit: int = 50,
        action_type: str = None,
        passed_only: bool = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """Get audit log entries."""
        try:
            conditions = []
            params = []

            if action_type:
                conditions.append("action_type = %s")
                params.append(action_type)
            if passed_only is not None:
                conditions.append("all_passed = %s")
                params.append(passed_only)
            if session_id:
                conditions.append("session_id = %s")
                params.append(session_id)

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            with self._get_cursor() as cur:
                cur.execute(f"""
                    SELECT id, action_type, action_details, guardrails_checked,
                           all_passed, blocking_guardrail_id, session_id, source,
                           was_executed, was_overridden, override_reason,
                           created_at, execution_duration_ms
                    FROM autonomy_audit
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s
                """, params + [limit])
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]

                entries = []
                for row in rows:
                    e = dict(zip(columns, row))
                    # Parse JSON
                    if e.get('action_details'):
                        e['action_details'] = json.loads(e['action_details']) if isinstance(e['action_details'], str) else e['action_details']
                    if e.get('guardrails_checked'):
                        e['guardrails_checked'] = json.loads(e['guardrails_checked']) if isinstance(e['guardrails_checked'], str) else e['guardrails_checked']
                    entries.append(e)

                return {"success": True, "entries": entries, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_feedback(
        self,
        guardrail_id: int,
        feedback_type: str,
        feedback_details: str = None,
        suggested_change: Dict = None,
        audit_id: int = None,
        created_by: str = "user"
    ) -> Dict[str, Any]:
        """Add feedback for a guardrail (for improving soft limits)."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO guardrail_feedback
                    (guardrail_id, audit_id, feedback_type, feedback_details,
                     suggested_change, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    guardrail_id, audit_id, feedback_type, feedback_details,
                    json.dumps(suggested_change) if suggested_change else None,
                    created_by
                ))
                result = cur.fetchone()
                return {"success": True, "feedback_id": result[0]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_guardrails_summary(self) -> Dict[str, Any]:
        """Get summary of all guardrails and recent activity."""
        try:
            with self._get_cursor() as cur:
                # Count by type
                cur.execute("""
                    SELECT guardrail_type, COUNT(*), SUM(CASE WHEN is_active THEN 1 ELSE 0 END)
                    FROM guardrails
                    GROUP BY guardrail_type
                """)
                by_type = {row[0]: {"total": row[1], "active": row[2]} for row in cur.fetchall()}

                # Recent audit stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN all_passed THEN 1 ELSE 0 END) as passed,
                        SUM(CASE WHEN NOT all_passed THEN 1 ELSE 0 END) as blocked
                    FROM autonomy_audit
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()
                recent_audit = {
                    "total_checks": row[0] or 0,
                    "passed": row[1] or 0,
                    "blocked": row[2] or 0
                }

                # Active overrides
                cur.execute("""
                    SELECT COUNT(*) FROM guardrail_overrides
                    WHERE revoked_at IS NULL
                    AND (valid_until IS NULL OR valid_until > NOW())
                """)
                active_overrides = cur.fetchone()[0]

                return {
                    "success": True,
                    "by_type": by_type,
                    "recent_24h": recent_audit,
                    "active_overrides": active_overrides
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================
    # L0.1: Risk Tier Management
    # ============================================

    def get_tool_risk_tiers(self, tier: int = None) -> Dict[str, Any]:
        """Get tools grouped by risk tier."""
        try:
            with self._get_cursor() as cur:
                if tier is not None:
                    cur.execute("""
                        SELECT t.name as tool_name, t.risk_tier, t.description, t.enabled as is_enabled,
                               r.name as tier_name, r.requirement
                        FROM jarvis_tools t
                        LEFT JOIN tool_risk_tiers r ON t.risk_tier = r.tier
                        WHERE t.risk_tier = %s
                        ORDER BY t.name
                    """, (tier,))
                else:
                    cur.execute("""
                        SELECT t.name as tool_name, t.risk_tier, t.description, t.enabled as is_enabled,
                               r.name as tier_name, r.requirement
                        FROM jarvis_tools t
                        LEFT JOIN tool_risk_tiers r ON t.risk_tier = r.tier
                        ORDER BY t.risk_tier, t.name
                    """)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                tools = [dict(zip(columns, row)) for row in rows]

                # Group by tier
                by_tier = {}
                for tool in tools:
                    t = tool['risk_tier']
                    if t not in by_tier:
                        by_tier[t] = {
                            "tier_name": tool['tier_name'],
                            "requirement": tool['requirement'],
                            "tools": []
                        }
                    by_tier[t]["tools"].append({
                        "name": tool['tool_name'],
                        "description": tool['description'],
                        "enabled": tool['is_enabled']
                    })

                return {
                    "success": True,
                    "by_tier": by_tier,
                    "total_tools": len(tools)
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_tool_risk_tier(
        self,
        tool_name: str,
        tier: int,
        reason: str = None
    ) -> Dict[str, Any]:
        """Set the risk tier for a tool."""
        if tier < 0 or tier > 3:
            return {"success": False, "error": "Tier must be 0-3"}

        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    UPDATE jarvis_tools
                    SET risk_tier = %s
                    WHERE name = %s
                    RETURNING name, risk_tier
                """, (tier, tool_name))
                result = cur.fetchone()

                if not result:
                    return {"success": False, "error": f"Tool '{tool_name}' not found"}

                # Log the change
                self.logger.info(f"Risk tier changed: {tool_name} -> tier {tier} (reason: {reason})")

                return {
                    "success": True,
                    "tool_name": result[0],
                    "new_tier": result[1],
                    "reason": reason
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_tier_definitions(self) -> Dict[str, Any]:
        """Get all tier definitions."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT tier, name, description, requirement,
                           auto_approve, min_confidence, requires_confirmation, requires_override
                    FROM tool_risk_tiers
                    ORDER BY tier
                """)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                tiers = [dict(zip(columns, row)) for row in rows]
                return {"success": True, "tiers": tiers}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_risk_tier_summary(self) -> Dict[str, Any]:
        """Get summary of tools by risk tier."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT
                        t.risk_tier,
                        r.name as tier_name,
                        r.requirement,
                        COUNT(*) as tool_count,
                        SUM(CASE WHEN t.enabled THEN 1 ELSE 0 END) as enabled_count
                    FROM jarvis_tools t
                    LEFT JOIN tool_risk_tiers r ON t.risk_tier = r.tier
                    GROUP BY t.risk_tier, r.name, r.requirement
                    ORDER BY t.risk_tier
                """)
                rows = cur.fetchall()

                summary = []
                for row in rows:
                    summary.append({
                        "tier": row[0],
                        "name": row[1],
                        "requirement": row[2],
                        "total": row[3],
                        "enabled": row[4]
                    })

                return {"success": True, "summary": summary}
        except Exception as e:
            return {"success": False, "error": str(e)}
