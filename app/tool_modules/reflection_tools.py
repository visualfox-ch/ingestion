"""
Self-Reflection Tools - Phase A1 (AGI Evolution)

Tools for Jarvis to use the Self-Reflection Engine:
- Run reflection on past responses
- Get improvement suggestions
- Track improvement progress
- Manage critique rules
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def evaluate_my_response(
    query: str,
    response: str,
    tool_calls: List[Dict] = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluate a response against self-critique rules.

    Scores the response on accuracy, helpfulness, efficiency, style, and safety.

    Args:
        query: The original query
        response: The response to evaluate
        tool_calls: List of tools that were used
        session_id: Session identifier

    Returns:
        Dict with quality scores and areas needing improvement
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.evaluate_response(
            query=query,
            response=response,
            tool_calls=tool_calls,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Evaluate my response failed: {e}")
        return {"success": False, "error": str(e)}


def reflect_on_response(
    reflection_id: int,
    query: str,
    response: str,
    critique_scores: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    Generate reflection and improvements for a response.

    Asks "What could have been better?" and suggests improvements.

    Args:
        reflection_id: ID from evaluate_my_response
        query: Original query
        response: The response
        critique_scores: Scores from evaluation

    Returns:
        Dict with reflection text and improvement suggestions
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.generate_reflection(
            reflection_id=reflection_id,
            query=query,
            response=response,
            critique_scores=critique_scores
        )

    except Exception as e:
        logger.error(f"Reflect on response failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_learnings(
    days: int = 7,
    min_occurrences: int = 2,
    **kwargs
) -> Dict[str, Any]:
    """
    Extract learnings from accumulated reflections.

    Finds recurring patterns that should become permanent improvements.

    Args:
        days: Days to look back (default: 7)
        min_occurrences: Minimum times a pattern must occur (default: 2)

    Returns:
        Dict with extracted learnings by category
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.extract_learnings(
            days=days,
            min_occurrences=min_occurrences
        )

    except Exception as e:
        logger.error(f"Get my learnings failed: {e}")
        return {"success": False, "error": str(e)}


def get_improvement_progress(
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Get metrics on self-improvement over time.

    Shows quality trends, improvement rates, and category breakdown.

    Args:
        days: Days to analyze (default: 30)

    Returns:
        Dict with improvement metrics and trends
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.get_improvement_metrics(days=days)

    except Exception as e:
        logger.error(f"Get improvement progress failed: {e}")
        return {"success": False, "error": str(e)}


def get_pending_improvements(
    priority: str = None,
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Get pending improvements waiting to be applied.

    Shows what can be improved based on past reflections.

    Args:
        priority: Filter by priority (critical, high, medium, low)
        limit: Max improvements to return (default: 10)

    Returns:
        Dict with pending improvements
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.get_pending_improvements(
            priority=priority,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get pending improvements failed: {e}")
        return {"success": False, "error": str(e)}


def apply_improvement(
    improvement_id: int,
    outcome_score: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Mark an improvement as applied.

    Records that an improvement has been implemented.

    Args:
        improvement_id: ID of the improvement
        outcome_score: Optional score for the outcome (0-1)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.apply_improvement(
            improvement_id=improvement_id,
            outcome_score=outcome_score
        )

    except Exception as e:
        logger.error(f"Apply improvement failed: {e}")
        return {"success": False, "error": str(e)}


def run_self_reflection(
    query: str,
    response: str,
    tool_calls: List[Dict] = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Run the full self-reflection loop.

    Complete Reflexion pattern: Evaluate -> Reflect -> Extract Learnings

    Args:
        query: Original query
        response: Generated response
        tool_calls: Tools that were used
        session_id: Session identifier

    Returns:
        Dict with evaluation, reflection, and any extracted learnings
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.run_reflection_loop(
            query=query,
            response=response,
            tool_calls=tool_calls,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Run self reflection failed: {e}")
        return {"success": False, "error": str(e)}


def add_critique_rule(
    rule_name: str,
    rule_category: str,
    critique_prompt: str,
    rule_condition: str = "all",
    weight: float = 1.0,
    min_score_threshold: float = 0.5,
    **kwargs
) -> Dict[str, Any]:
    """
    Add or update a self-critique rule.

    Rules define how responses are evaluated.

    Args:
        rule_name: Unique name for the rule
        rule_category: Category (accuracy, helpfulness, efficiency, style, safety)
        critique_prompt: Prompt describing how to evaluate
        rule_condition: When to apply (all, tool_call, or keyword)
        weight: Weight of this rule (default: 1.0)
        min_score_threshold: Score below which triggers reflection (default: 0.5)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.add_critique_rule(
            rule_name=rule_name,
            rule_category=rule_category,
            critique_prompt=critique_prompt,
            rule_condition=rule_condition,
            weight=weight,
            min_score_threshold=min_score_threshold
        )

    except Exception as e:
        logger.error(f"Add critique rule failed: {e}")
        return {"success": False, "error": str(e)}


def get_critique_rules(
    category: str = None,
    active_only: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Get all self-critique rules.

    Shows how responses are being evaluated.

    Args:
        category: Filter by category
        active_only: Only show active rules (default: True)

    Returns:
        Dict with critique rules
    """
    try:
        from app.services.reflection_service import get_reflection_service

        service = get_reflection_service()
        return service.get_critique_rules(
            category=category,
            active_only=active_only
        )

    except Exception as e:
        logger.error(f"Get critique rules failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
REFLECTION_TOOLS = [
    {
        "name": "evaluate_my_response",
        "description": "Evaluate a response against self-critique rules. Scores on accuracy, helpfulness, efficiency, style, safety.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original query"
                },
                "response": {
                    "type": "string",
                    "description": "The response to evaluate"
                },
                "tool_calls": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of tools that were used"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session identifier"
                }
            },
            "required": ["query", "response"]
        }
    },
    {
        "name": "reflect_on_response",
        "description": "Generate reflection and improvements for a response. Asks 'What could have been better?'",
        "input_schema": {
            "type": "object",
            "properties": {
                "reflection_id": {
                    "type": "integer",
                    "description": "ID from evaluate_my_response"
                },
                "query": {
                    "type": "string",
                    "description": "Original query"
                },
                "response": {
                    "type": "string",
                    "description": "The response"
                },
                "critique_scores": {
                    "type": "object",
                    "description": "Scores from evaluation"
                }
            },
            "required": ["reflection_id", "query", "response", "critique_scores"]
        }
    },
    {
        "name": "get_my_learnings",
        "description": "Extract learnings from accumulated reflections. Finds recurring improvement patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to look back (default: 7)"
                },
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum times pattern must occur (default: 2)"
                }
            }
        }
    },
    {
        "name": "get_improvement_progress",
        "description": "Get metrics on self-improvement over time. Shows quality trends and improvement rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 30)"
                }
            }
        }
    },
    {
        "name": "get_pending_improvements",
        "description": "Get pending improvements waiting to be applied.",
        "input_schema": {
            "type": "object",
            "properties": {
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Filter by priority"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max improvements (default: 10)"
                }
            }
        }
    },
    {
        "name": "apply_improvement",
        "description": "Mark an improvement as applied with optional outcome score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "improvement_id": {
                    "type": "integer",
                    "description": "ID of the improvement"
                },
                "outcome_score": {
                    "type": "number",
                    "description": "Outcome score 0-1 (optional)"
                }
            },
            "required": ["improvement_id"]
        }
    },
    {
        "name": "run_self_reflection",
        "description": "Run the full self-reflection loop: Evaluate -> Reflect -> Extract Learnings",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Original query"
                },
                "response": {
                    "type": "string",
                    "description": "Generated response"
                },
                "tool_calls": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Tools that were used"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session identifier"
                }
            },
            "required": ["query", "response"]
        }
    },
    {
        "name": "add_critique_rule",
        "description": "Add or update a self-critique rule. Defines how responses are evaluated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_name": {
                    "type": "string",
                    "description": "Unique name for the rule"
                },
                "rule_category": {
                    "type": "string",
                    "enum": ["accuracy", "helpfulness", "efficiency", "style", "safety"],
                    "description": "Category of the rule"
                },
                "critique_prompt": {
                    "type": "string",
                    "description": "Prompt describing how to evaluate"
                },
                "rule_condition": {
                    "type": "string",
                    "description": "When to apply (all, tool_call, or keyword)"
                },
                "weight": {
                    "type": "number",
                    "description": "Weight of this rule (default: 1.0)"
                },
                "min_score_threshold": {
                    "type": "number",
                    "description": "Score below which triggers reflection (default: 0.5)"
                }
            },
            "required": ["rule_name", "rule_category", "critique_prompt"]
        }
    },
    {
        "name": "get_critique_rules",
        "description": "Get all self-critique rules. Shows how responses are evaluated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["accuracy", "helpfulness", "efficiency", "style", "safety"],
                    "description": "Filter by category"
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only show active rules (default: True)"
                }
            }
        }
    }
]
