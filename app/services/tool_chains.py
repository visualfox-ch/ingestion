"""
Smart Tool Chains - Phase 21A

Automatic follow-up tools that run after primary tools complete.
Enables multi-step workflows without explicit LLM orchestration.

Example chains:
- remember_fact -> verify_fact_novelty
- search_knowledge -> summarize_results (if many results)
- create_action_plan -> estimate_complexity
"""
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_chains")


@dataclass
class ChainRule:
    """Definition of a tool chain rule."""
    trigger_tool: str
    follow_up_tool: str
    condition: str  # "always", "on_success", "on_error", or a lambda expression
    priority: int = 50
    enabled: bool = True
    description: str = ""


# Default tool chain rules
DEFAULT_CHAINS: List[ChainRule] = [
    # Memory chains
    ChainRule(
        trigger_tool="remember_fact",
        follow_up_tool="check_fact_duplicates",
        condition="on_success",
        description="Check for duplicate facts after storing"
    ),

    # Search chains
    ChainRule(
        trigger_tool="search_knowledge",
        follow_up_tool="rank_search_results",
        condition="result_count > 5",
        description="Rank results when too many returned"
    ),

    # Planning chains
    ChainRule(
        trigger_tool="create_action_plan",
        follow_up_tool="estimate_plan_complexity",
        condition="on_success",
        description="Estimate complexity after creating plan"
    ),

    # Playbook chains
    ChainRule(
        trigger_tool="run_safe_playbook",
        follow_up_tool="verify_playbook_success",
        condition="on_success",
        description="Verify playbook completed successfully"
    ),

    # Learning chains
    ChainRule(
        trigger_tool="record_learning",
        follow_up_tool="check_learning_conflicts",
        condition="on_success",
        description="Check for conflicting learnings"
    ),

    # Context chains
    ChainRule(
        trigger_tool="store_context",
        follow_up_tool="summarize_context_delta",
        condition="context_size > 1000",
        description="Summarize large context additions"
    ),
]


class ToolChainService:
    """
    Service for managing and executing tool chains.

    Tool chains allow automatic follow-up actions after primary tools complete.
    This reduces the cognitive load on the LLM and ensures consistency.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._chains = {}
            cls._instance._load_default_chains()
        return cls._instance

    def _load_default_chains(self):
        """Load default chain rules."""
        for rule in DEFAULT_CHAINS:
            self._chains[rule.trigger_tool] = self._chains.get(rule.trigger_tool, [])
            self._chains[rule.trigger_tool].append(rule)

        # Also load from database if available
        self._load_db_chains()

    def _load_db_chains(self):
        """Load chain rules from database."""
        try:
            from ..postgres_state import get_conn

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trigger_tool, follow_up_tool, condition, priority, description
                        FROM jarvis_tool_chain_rules
                        WHERE enabled = true
                        ORDER BY priority DESC
                    """)

                    for row in cur.fetchall():
                        rule = ChainRule(
                            trigger_tool=row[0],
                            follow_up_tool=row[1],
                            condition=row[2],
                            priority=row[3],
                            description=row[4] or ""
                        )
                        self._chains[rule.trigger_tool] = self._chains.get(rule.trigger_tool, [])
                        self._chains[rule.trigger_tool].append(rule)

        except Exception as e:
            # Table might not exist yet
            logger.debug(f"Could not load DB chains: {e}")

    def get_follow_up_tools(
        self,
        trigger_tool: str,
        result: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get follow-up tools for a completed tool execution.

        Args:
            trigger_tool: Name of the tool that just completed
            result: Result from the trigger tool
            context: Additional context

        Returns:
            List of follow-up tool calls to execute
        """
        chains = self._chains.get(trigger_tool, [])
        if not chains:
            return []

        follow_ups = []

        for rule in sorted(chains, key=lambda r: -r.priority):
            if not rule.enabled:
                continue

            if self._evaluate_condition(rule.condition, result, context):
                follow_ups.append({
                    "tool_name": rule.follow_up_tool,
                    "reason": rule.description,
                    "priority": rule.priority,
                    "input": self._build_follow_up_input(rule, result, context)
                })

                log_with_context(
                    logger, "info", "Tool chain triggered",
                    trigger=trigger_tool,
                    follow_up=rule.follow_up_tool,
                    condition=rule.condition
                )

        return follow_ups

    def _evaluate_condition(
        self,
        condition: str,
        result: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Evaluate a chain condition."""
        if condition == "always":
            return True

        if condition == "on_success":
            return result.get("success", True) and "error" not in result

        if condition == "on_error":
            return not result.get("success", True) or "error" in result

        # Evaluate simple expressions like "result_count > 5"
        try:
            # Create safe evaluation context
            eval_context = {
                "result_count": len(result.get("results", result.get("items", []))),
                "success": result.get("success", True),
                "context_size": len(str(context)) if context else 0,
                "has_error": "error" in result,
            }

            # Only allow simple comparisons
            if " > " in condition or " < " in condition or " == " in condition:
                return eval(condition, {"__builtins__": {}}, eval_context)
        except Exception:
            pass

        return False

    def _build_follow_up_input(
        self,
        rule: ChainRule,
        result: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build input for the follow-up tool based on trigger result."""
        # Default: pass relevant data from trigger result
        follow_up_input = {}

        # Tool-specific input mapping
        if rule.follow_up_tool == "check_fact_duplicates":
            follow_up_input = {
                "fact_content": result.get("fact", result.get("content", "")),
                "threshold": 0.85
            }

        elif rule.follow_up_tool == "rank_search_results":
            follow_up_input = {
                "results": result.get("results", []),
                "query": context.get("query", "") if context else ""
            }

        elif rule.follow_up_tool == "verify_playbook_success":
            follow_up_input = {
                "playbook_name": result.get("playbook_name", ""),
                "execution_id": result.get("execution_id", "")
            }

        elif rule.follow_up_tool == "estimate_plan_complexity":
            follow_up_input = {
                "plan": result.get("plan", result)
            }

        else:
            # Generic: pass the trigger result as context
            follow_up_input = {
                "trigger_result": result,
                "trigger_tool": rule.trigger_tool
            }

        return follow_up_input

    def add_chain(
        self,
        trigger_tool: str,
        follow_up_tool: str,
        condition: str = "on_success",
        priority: int = 50,
        description: str = "",
        persist: bool = True
    ) -> Dict[str, Any]:
        """
        Add a new tool chain rule.

        Args:
            trigger_tool: Tool that triggers the chain
            follow_up_tool: Tool to run after trigger
            condition: When to run ("always", "on_success", "on_error", or expression)
            priority: Higher = runs first
            description: Why this chain exists
            persist: Save to database

        Returns:
            Status dict
        """
        rule = ChainRule(
            trigger_tool=trigger_tool,
            follow_up_tool=follow_up_tool,
            condition=condition,
            priority=priority,
            description=description
        )

        self._chains[trigger_tool] = self._chains.get(trigger_tool, [])
        self._chains[trigger_tool].append(rule)

        if persist:
            try:
                from ..postgres_state import get_conn

                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO jarvis_tool_chain_rules
                            (trigger_tool, follow_up_tool, condition, priority, description, enabled)
                            VALUES (%s, %s, %s, %s, %s, true)
                            ON CONFLICT (trigger_tool, follow_up_tool) DO UPDATE SET
                                condition = EXCLUDED.condition,
                                priority = EXCLUDED.priority,
                                description = EXCLUDED.description
                        """, (trigger_tool, follow_up_tool, condition, priority, description))
                        conn.commit()
            except Exception as e:
                logger.warning(f"Could not persist chain rule: {e}")

        return {
            "success": True,
            "trigger": trigger_tool,
            "follow_up": follow_up_tool,
            "condition": condition
        }

    def get_all_chains(self) -> Dict[str, List[Dict]]:
        """Get all registered chain rules."""
        result = {}
        for trigger, rules in self._chains.items():
            result[trigger] = [
                {
                    "follow_up": r.follow_up_tool,
                    "condition": r.condition,
                    "priority": r.priority,
                    "description": r.description,
                    "enabled": r.enabled
                }
                for r in rules
            ]
        return result


# Singleton accessor
_service = None

def get_tool_chain_service() -> ToolChainService:
    """Get the singleton ToolChainService instance."""
    global _service
    if _service is None:
        _service = ToolChainService()
    return _service
