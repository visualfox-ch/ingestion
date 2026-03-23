"""
Decision Tools.

Decision rules, outcomes, autonomy status.
Extracted from tools.py (Phase S5).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode, internal_error

logger = get_logger("jarvis.tools.decision")


def tool_record_decision_outcome(**kwargs) -> Dict[str, Any]:
    """Record feedback/outcome for a prior decision_id."""
    try:
        from ..cross_session_learner import cross_session_learner

        decision_id = kwargs.get("decision_id")
        outcome = kwargs.get("outcome")
        feedback_score = kwargs.get("feedback_score")
        source_channel = kwargs.get("source_channel", "user")
        strategy_id = kwargs.get("strategy_id")
        tool_name = kwargs.get("tool_name")
        details = kwargs.get("details") or {}

        result = cross_session_learner.record_decision_outcome(
            decision_id=decision_id,
            outcome=outcome,
            feedback_score=feedback_score,
            source_channel=source_channel,
            strategy_id=strategy_id,
            tool_name=tool_name,
            details=details,
        )
        metrics.inc("tool_record_decision_outcome")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool record_decision_outcome failed", error=str(e))
        return {"error": str(e)}



# Ollama tools MOVED to tool_modules/ollama_tools.py (T006 refactor)
# Implementations: tool_delegate_ollama_task, tool_get_ollama_task_status, tool_get_ollama_queue_status,
#                  tool_cancel_ollama_task, tool_get_ollama_callback_result, tool_ask_ollama, tool_ollama_python

def tool_add_decision_rule(
    name: str = None,
    condition_type: str = None,
    condition_value: Any = None,
    action_type: str = None,
    action_value: Any = None,
    description: str = None,
    priority: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """
    Add a decision rule for tool selection.

    Jarvis learns when to use which tools and creates rules to optimize.

    Args:
        name: Unique name for this rule
        condition_type: "keyword", "intent", "context", "pattern"
        condition_value: The condition (keywords list, intent name, context dict, regex pattern)
        action_type: "include_tools", "exclude_tools", "set_priority", "require_approval"
        action_value: The action to take (tool names list, priority value, etc.)
        description: Human-readable description of what this rule does
        priority: Higher priority rules are checked first

    Returns:
        Created rule info
    """
    log_with_context(logger, "info", "Tool: add_decision_rule", name=name, condition_type=condition_type)
    metrics.inc("tool_add_decision_rule")

    if not all([name, condition_type, condition_value, action_type, action_value]):
        return {"error": "name, condition_type, condition_value, action_type, action_value are required"}

    try:
        from ..services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        return service.add_decision_rule(
            name=name,
            condition_type=condition_type,
            condition_value=condition_value,
            action_type=action_type,
            action_value=action_value,
            description=description,
            priority=priority
        )

    except Exception as e:
        log_with_context(logger, "error", "add_decision_rule failed", error=str(e))
        return {"error": str(e)}


def tool_get_autonomy_status(**kwargs) -> Dict[str, Any]:
    """
    Get Jarvis's autonomy status - what tools, categories, and rules are configured.

    Use this to understand your current capabilities and recent changes.

    Returns:
        Autonomy dashboard with tools, categories, rules, and modifications
    """
    log_with_context(logger, "info", "Tool: get_autonomy_status")
    metrics.inc("tool_get_autonomy_status")

    try:
        from ..services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        tools = service.get_enabled_tools()
        categories = service.get_categories()
        modifications = service.get_recent_modifications(limit=10)
        style = service.get_response_style()

        return {
            "status": "autonomous",
            "tools": {
                "total_enabled": len(tools),
                "by_category": {},  # Would need aggregation
                "recently_modified": [m for m in modifications if m["table"] == "jarvis_tools"][:3]
            },
            "categories": {
                "count": len(categories),
                "names": [c["name"] for c in categories]
            },
            "response_style": style["name"] if style else "default",
            "recent_self_modifications": modifications[:5],
            "hint": "Use manage_tool_registry to modify tools, add_decision_rule to add rules"
        }

    except Exception as e:
        log_with_context(logger, "error", "get_autonomy_status failed", error=str(e))
        # Return basic info even if DB fails
        from .. import tools as core_tools
        return {
            "status": "code_fallback",
            "tools": {"total_enabled": len(core_tools.TOOL_REGISTRY)},
            "error": str(e),
            "hint": "Database not available, using code-defined tools"
        }

