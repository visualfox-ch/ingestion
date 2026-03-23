"""
Agent Hooks Service - Automatic Pre/Post Processing

Tool Activation Strategy Phase A: Auto-Hooks
These hooks run automatically to activate "forgotten" tools:

1. Pre-Query Hooks:
   - check_corrections: Avoid repeating past mistakes

2. Pre-Tool Hooks:
   - check_guardrails: Security check before autonomous actions

3. Post-Response Hooks:
   - assess_my_confidence: Quality control (async, non-blocking)

Usage in agent.py:
    from .services.agent_hooks import AgentHooks

    hooks = AgentHooks(user_id=user_id, session_id=session_id)

    # Before processing query
    corrections = await hooks.pre_query(query)
    if corrections:
        # Apply corrections to system prompt or context

    # Before tool execution (in tool_executor.py)
    allowed, reason = await hooks.pre_tool(tool_name, tool_input)
    if not allowed:
        return {"blocked": True, "reason": reason}

    # After response (non-blocking)
    asyncio.create_task(hooks.post_response(query, response, tool_calls))

Phase C: DB-Driven Tool Risk Classification
Tool categories are now loaded from jarvis_tools.risk_tier:
- Tier 0: SAFE_TOOLS (read-only, always allowed)
- Tier 1: Standard (default, no special handling)
- Tier 2-3: AUTONOMOUS_TOOLS (sensitive/critical, guardrails check)
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, FrozenSet
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.agent_hooks")

# ========== DB-DRIVEN TOOL RISK CLASSIFICATION ==========

# Cache for tool risk classifications
_tool_risk_cache: Dict[str, FrozenSet[str]] = {}
_cache_timestamp: float = 0
_CACHE_TTL_SECONDS = 60  # Refresh every 60 seconds


def _load_tools_by_risk_tier() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """
    Load tool classifications from database.

    Returns:
        Tuple of (safe_tools, autonomous_tools) frozensets
    """
    global _tool_risk_cache, _cache_timestamp

    # Check cache validity
    now = time.time()
    if _tool_risk_cache and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        return _tool_risk_cache.get("safe", frozenset()), _tool_risk_cache.get("autonomous", frozenset())

    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Tier 0 = safe (read-only, always allowed)
                cur.execute("""
                    SELECT name FROM jarvis_tools
                    WHERE enabled = true AND risk_tier = 0
                """)
                # Handle both dict-style and tuple-style cursor results
                rows = cur.fetchall()
                safe_tools = frozenset(
                    row["name"] if isinstance(row, dict) else row[0]
                    for row in rows
                )

                # Tier 2-3 = autonomous (sensitive/critical, need guardrails)
                cur.execute("""
                    SELECT name FROM jarvis_tools
                    WHERE enabled = true AND risk_tier >= 2
                """)
                rows = cur.fetchall()
                autonomous_tools = frozenset(
                    row["name"] if isinstance(row, dict) else row[0]
                    for row in rows
                )

        # Update cache
        _tool_risk_cache = {
            "safe": safe_tools,
            "autonomous": autonomous_tools
        }
        _cache_timestamp = now

        logger.debug(f"Loaded tool risk tiers from DB: {len(safe_tools)} safe, {len(autonomous_tools)} autonomous")
        return safe_tools, autonomous_tools

    except Exception as e:
        logger.warning(f"Failed to load tool risk tiers from DB, using fallback: {e}")
        return _get_fallback_tools()


def _get_fallback_tools() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """Fallback hardcoded tools if DB is unavailable."""
    safe = frozenset([
        "search_knowledge", "search_emails", "search_chats", "get_recent_activity",
        "get_calendar_events", "get_gmail_messages",
        "recall_facts", "recall_conversation_history", "list_available_tools",
        "get_self_model", "system_health_check", "self_validation_pulse", "analyze_tool_usage",
        "introspect_capabilities", "get_execution_stats", "check_guardrails",
        "get_guardrails", "get_config", "get_system_status"
    ])
    autonomous = frozenset([
        "write_project_file", "send_email", "create_calendar_event",
        "remember_fact", "store_context", "archive_memory",
        "evolve_identity", "update_relationship", "control_smart_home",
        "send_telegram_message", "broadcast_message", "write_dynamic_tool",
        "enable_experimental_feature", "add_guardrail", "add_decision_rule"
    ])
    return safe, autonomous


def get_safe_tools() -> FrozenSet[str]:
    """Get current safe tools (Tier 0)."""
    safe, _ = _load_tools_by_risk_tier()
    return safe


def get_autonomous_tools() -> FrozenSet[str]:
    """Get current autonomous tools (Tier 2-3)."""
    _, autonomous = _load_tools_by_risk_tier()
    return autonomous


def invalidate_tool_risk_cache():
    """Force cache refresh on next access."""
    global _cache_timestamp
    _cache_timestamp = 0


# For backward compatibility - use get_safe_tools() and get_autonomous_tools() instead
# These will be populated on first access (lazy loading)
def _create_lazy_frozenset(getter):
    """Create a lazy-loading frozenset wrapper."""
    class LazyFrozenSet:
        _cache = None
        def __contains__(self, item):
            if self._cache is None:
                self._cache = getter()
            return item in self._cache
        def __iter__(self):
            if self._cache is None:
                self._cache = getter()
            return iter(self._cache)
        def __len__(self):
            if self._cache is None:
                self._cache = getter()
            return len(self._cache)
    return LazyFrozenSet()

# Legacy module-level constants (deprecated, use functions instead)
SAFE_TOOLS = _create_lazy_frozenset(get_safe_tools)
AUTONOMOUS_TOOLS = _create_lazy_frozenset(get_autonomous_tools)


@dataclass
class HookResult:
    """Result of a hook execution."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None


class AgentHooks:
    """
    Automatic hooks that call "forgotten" tools.

    These hooks ensure that important meta-tools are called
    without Jarvis (LLM) having to remember them.
    """

    def __init__(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        enabled: bool = True
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.enabled = enabled
        self._corrections_cache: Dict[str, List[Dict]] = {}

    # ========== PRE-QUERY HOOKS ==========

    def pre_query(self, query: str) -> HookResult:
        """
        Run before processing a query.

        Calls: check_corrections
        Returns: Relevant corrections to apply
        """
        if not self.enabled:
            return HookResult(success=True, skipped=True, skip_reason="hooks_disabled")

        try:
            from ..tool_modules.correction_tools import check_corrections

            result = check_corrections(query=query, min_confidence=0.5)

            corrections = result.get("corrections", [])
            if corrections:
                logger.info(f"Pre-query hook found {len(corrections)} corrections for query")
                return HookResult(
                    success=True,
                    data={
                        "corrections": corrections,
                        "count": len(corrections),
                        "apply_hint": self._format_corrections_hint(corrections)
                    }
                )

            return HookResult(success=True, data={"corrections": [], "count": 0})

        except ImportError as e:
            logger.debug(f"Correction tools not available: {e}")
            return HookResult(success=True, skipped=True, skip_reason="module_not_available")
        except Exception as e:
            logger.warning(f"Pre-query hook failed: {e}")
            return HookResult(success=False, error=str(e))

    def _format_corrections_hint(self, corrections: List[Dict]) -> str:
        """Format corrections as a hint for the system prompt."""
        if not corrections:
            return ""

        hints = []
        for c in corrections[:3]:  # Max 3 corrections
            error_type = c.get("error_type", "general")
            pattern = c.get("error_pattern", "")
            correct = c.get("correct_response", "")
            hints.append(f"- {error_type}: Nicht '{pattern}', sondern '{correct}'")

        return "\n".join(hints)

    # ========== PRE-TOOL HOOKS ==========

    def pre_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> HookResult:
        """
        Run before executing a tool.

        Calls: check_guardrails (for autonomous tools)
        Returns: Whether tool execution is allowed
        """
        if not self.enabled:
            return HookResult(success=True, data={"allowed": True}, skipped=True)

        # Skip guardrails for safe read-only tools (Tier 0)
        safe_tools = get_safe_tools()
        if tool_name in safe_tools:
            return HookResult(
                success=True,
                data={"allowed": True},
                skipped=True,
                skip_reason="safe_tool_tier_0"
            )

        # Only check guardrails for autonomous tools (Tier 2-3)
        autonomous_tools = get_autonomous_tools()
        if tool_name not in autonomous_tools:
            return HookResult(
                success=True,
                data={"allowed": True},
                skipped=True,
                skip_reason="not_autonomous"
            )

        try:
            from ..tool_modules.guardrails_tools import check_guardrails

            result = check_guardrails(
                action_type="tool_call",
                tool_name=tool_name,
                action_details=tool_input,
                context=context or {}
            )

            allowed = result.get("allowed", True)
            reason = result.get("reason", "")
            violations = result.get("violations", [])

            if not allowed:
                logger.warning(f"Guardrails blocked tool {tool_name}: {reason}")

                # Record metric
                try:
                    from ..metrics import TOOL_BLOCKED
                    guardrail_type = result.get("guardrail_type", "unknown")
                    # Get risk tier for this tool
                    risk_tier = self._get_tool_risk_tier(tool_name)
                    TOOL_BLOCKED.labels(
                        tool_name=tool_name,
                        guardrail_type=guardrail_type,
                        risk_tier=str(risk_tier)
                    ).inc()
                except Exception:
                    pass  # Don't fail on metric recording

                # Send Telegram alert for blocked tool
                self._send_tool_blocked_alert(
                    tool_name=tool_name,
                    reason=reason,
                    violations=violations,
                    guardrail_type=result.get("guardrail_type"),
                    context=context
                )

            return HookResult(
                success=True,
                data={
                    "allowed": allowed,
                    "reason": reason,
                    "violations": violations,
                    "guardrail_type": result.get("guardrail_type")
                }
            )

        except ImportError as e:
            logger.debug(f"Guardrails tools not available: {e}")
            return HookResult(success=True, data={"allowed": True}, skipped=True)
        except Exception as e:
            logger.warning(f"Pre-tool hook failed: {e}")
            # Fail open - allow tool if hook fails
            return HookResult(success=False, error=str(e), data={"allowed": True})

    # ========== HELPERS ==========

    def _get_tool_risk_tier(self, tool_name: str) -> int:
        """Get risk tier for a tool from DB."""
        try:
            from ..postgres_state import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT risk_tier FROM jarvis_tools WHERE name = %s",
                        (tool_name,)
                    )
                    row = cur.fetchone()
                    if row:
                        return row[0] if isinstance(row, tuple) else row.get("risk_tier", 1)
        except Exception:
            pass
        return 1  # Default to standard

    # ========== ALERTS ==========

    def _send_tool_blocked_alert(
        self,
        tool_name: str,
        reason: str,
        violations: List[Dict],
        guardrail_type: Optional[str] = None,
        context: Optional[Dict] = None
    ):
        """Send Telegram alert when a tool is blocked by guardrails."""
        try:
            from ..telegram_bot import TELEGRAM_TOKEN
            from ..state_db import get_all_telegram_users
            import requests

            if not TELEGRAM_TOKEN:
                return

            # Build alert message
            message = f"⚠️ **Tool Blocked**\n\n"
            message += f"**Tool:** `{tool_name}`\n"
            message += f"**Reason:** {reason}\n"

            if guardrail_type:
                message += f"**Guardrail:** {guardrail_type}\n"

            if violations:
                message += f"\n**Violations:**\n"
                for v in violations[:3]:  # Max 3
                    v_type = v.get("type", "unknown")
                    v_msg = v.get("message", str(v))
                    message += f"• {v_type}: {v_msg}\n"

            if context:
                query = context.get("query", "")[:100]
                if query:
                    message += f"\n**Context:** {query}..."

            message += f"\n\n_Session: {self.session_id or 'unknown'}_"

            # Send to all registered users
            users = get_all_telegram_users()
            for user in users:
                self._send_telegram(TELEGRAM_TOKEN, user["user_id"], message)

            logger.info(f"Sent tool-blocked alert for {tool_name}")

        except Exception as e:
            logger.debug(f"Failed to send tool-blocked alert: {e}")

    def _send_telegram(self, token: str, chat_id: int, text: str):
        """Send a Telegram message."""
        import requests

        if len(text) > 4000:
            text = text[:3997] + "..."

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        try:
            requests.post(url, json=payload, timeout=10)
        except Exception:
            pass  # Silent fail for alerts

    # ========== POST-RESPONSE HOOKS ==========

    def post_response(
        self,
        query: str,
        response: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> HookResult:
        """
        Run after generating a response (async-safe, non-blocking).

        Calls:
        - assess_my_confidence: Quality control
        - suggest_tools: Recommend unused but relevant tools (Phase 21 2B)

        Returns: Confidence assessment and tool suggestions
        """
        if not self.enabled:
            return HookResult(success=True, skipped=True, skip_reason="hooks_disabled")

        result_data = {}

        # 1. Confidence assessment
        try:
            from ..tool_modules.uncertainty_tools import assess_my_confidence

            conf_result = assess_my_confidence(
                query=query,
                response=response,
                tool_calls=tool_calls or [],
                session_id=self.session_id
            )

            confidence = conf_result.get("confidence", 0.0)
            signals = conf_result.get("uncertainty_signals", [])

            if confidence < 0.5:
                logger.info(f"Low confidence response ({confidence:.2f}): {signals}")

            result_data["confidence"] = confidence
            result_data["uncertainty_signals"] = signals
            result_data["calibration_note"] = conf_result.get("calibration_note")

        except ImportError as e:
            logger.debug(f"Uncertainty tools not available: {e}")
        except Exception as e:
            logger.warning(f"Confidence assessment failed: {e}")

        # 2. Smart Tool Suggestions (Phase 21 2B)
        try:
            from .tool_suggestions import get_tool_suggestion_service

            # Extract tool names that were used
            used_tools = set()
            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc.get("name") or tc.get("tool_name") or tc.get("function", {}).get("name")
                    if tool_name:
                        used_tools.add(tool_name)

            # Get suggestions
            service = get_tool_suggestion_service()
            suggestions = service.get_suggestions(
                query=query,
                used_tools=used_tools,
                response_text=response
            )

            if suggestions:
                result_data["tool_suggestions"] = [
                    {
                        "tool_name": s.tool_name,
                        "description": s.description,
                        "usage_hint": s.usage_hint,
                        "similarity": round(s.similarity, 3),
                        "category": s.category
                    }
                    for s in suggestions
                ]
                result_data["suggestions_formatted"] = service.format_suggestions(suggestions)

                logger.debug(f"Generated {len(suggestions)} tool suggestions for query")

        except ImportError as e:
            logger.debug(f"Tool suggestions not available: {e}")
        except Exception as e:
            logger.warning(f"Tool suggestions failed: {e}")

        return HookResult(success=True, data=result_data)


# ========== ASYNC WRAPPERS ==========

async def run_pre_query_hook_async(
    query: str,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None
) -> HookResult:
    """Async wrapper for pre-query hook."""
    hooks = AgentHooks(user_id=user_id, session_id=session_id)
    return await asyncio.get_event_loop().run_in_executor(
        None, hooks.pre_query, query
    )


async def run_post_response_hook_async(
    query: str,
    response: str,
    tool_calls: Optional[List[Dict]] = None,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None
) -> HookResult:
    """Async wrapper for post-response hook (fire-and-forget safe)."""
    hooks = AgentHooks(user_id=user_id, session_id=session_id)
    return await asyncio.get_event_loop().run_in_executor(
        None, hooks.post_response, query, response, tool_calls
    )


# ========== SINGLETON ACCESS ==========

_hooks_instance: Optional[AgentHooks] = None


def get_agent_hooks(
    user_id: Optional[int] = None,
    session_id: Optional[str] = None
) -> AgentHooks:
    """Get or create AgentHooks instance."""
    global _hooks_instance
    if _hooks_instance is None or user_id or session_id:
        _hooks_instance = AgentHooks(user_id=user_id, session_id=session_id)
    return _hooks_instance
