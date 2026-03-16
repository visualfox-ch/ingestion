"""
Decision Tracking Tools - Phase 3.2

Tools for tracking and analyzing decisions:
- Record decisions with reasoning
- Track outcomes
- Get decision history and stats
- Get decision suggestions based on patterns
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def record_decision(
    category: str,
    decision_point: str,
    decision_made: str,
    options_considered: List[str] = None,
    reasoning: str = None,
    confidence: float = 0.5,
    context: Dict[str, Any] = None,
    query: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record a decision made during processing.

    Tracks what decision was made, why, and with what confidence.

    Args:
        category: Decision category (tool_selection, response_style,
                 context_inclusion, clarification, delegation, autonomy, safety)
        decision_point: What decision was being made
        decision_made: The actual decision taken
        options_considered: Other options that were considered
        reasoning: Why this decision was made
        confidence: Confidence level 0-1 (default: 0.5)
        context: Context at time of decision
        query: Original query if applicable

    Returns:
        Dict with decision_id for later outcome tracking
    """
    try:
        from app.services.decision_tracker import get_decision_tracker

        service = get_decision_tracker()
        return service.record_decision(
            category=category,
            decision_point=decision_point,
            decision_made=decision_made,
            options_considered=options_considered,
            reasoning=reasoning,
            confidence=confidence,
            context=context,
            query=query
        )

    except Exception as e:
        logger.error(f"Record decision failed: {e}")
        return {"success": False, "error": str(e)}


def record_decision_outcome(
    decision_id: str,
    outcome: str,
    outcome_score: float = None,
    notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record the outcome of a decision.

    Updates the decision record and learns from the outcome.

    Args:
        decision_id: ID from record_decision
        outcome: Outcome status (success, partial, failure, unknown)
        outcome_score: Numeric score 0-1 (optional)
        notes: Additional notes about outcome

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.decision_tracker import get_decision_tracker

        service = get_decision_tracker()
        return service.record_outcome(
            decision_id=decision_id,
            outcome=outcome,
            outcome_score=outcome_score,
            notes=notes
        )

    except Exception as e:
        logger.error(f"Record decision outcome failed: {e}")
        return {"success": False, "error": str(e)}


def get_decision_history(
    category: str = None,
    days: int = 7,
    limit: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """
    Get recent decision history.

    Shows decisions made with their outcomes.

    Args:
        category: Filter by category (optional)
        days: Number of days to look back (default: 7)
        limit: Max decisions to return (default: 50)

    Returns:
        Dict with list of decisions
    """
    try:
        from app.services.decision_tracker import get_decision_tracker

        service = get_decision_tracker()
        return service.get_decision_history(
            category=category,
            days=days,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get decision history failed: {e}")
        return {"success": False, "error": str(e)}


def get_decision_stats(
    category: str = None,
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Get decision statistics and patterns.

    Shows success rates, scores, and learned patterns.

    Args:
        category: Filter by category (optional)
        days: Number of days to analyze (default: 30)

    Returns:
        Dict with statistics and top patterns
    """
    try:
        from app.services.decision_tracker import get_decision_tracker

        service = get_decision_tracker()
        return service.get_decision_stats(
            category=category,
            days=days
        )

    except Exception as e:
        logger.error(f"Get decision stats failed: {e}")
        return {"success": False, "error": str(e)}


def suggest_decision(
    category: str,
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Suggest a decision based on learned patterns.

    Uses historical patterns to recommend decisions.

    Args:
        category: Decision category
        context: Current context (session_type, query_type, etc.)

    Returns:
        Dict with suggested decision and confidence
    """
    try:
        from app.services.decision_tracker import get_decision_tracker

        service = get_decision_tracker()
        return service.suggest_decision(
            category=category,
            context=context
        )

    except Exception as e:
        logger.error(f"Suggest decision failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
DECISION_TRACKING_TOOLS = [
    {
        "name": "record_decision",
        "description": "Record a decision made during processing. Tracks what, why, and confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["tool_selection", "response_style", "context_inclusion",
                            "clarification", "delegation", "autonomy", "safety"],
                    "description": "Decision category"
                },
                "decision_point": {
                    "type": "string",
                    "description": "What decision was being made"
                },
                "decision_made": {
                    "type": "string",
                    "description": "The actual decision taken"
                },
                "options_considered": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Other options considered"
                },
                "reasoning": {
                    "type": "string",
                    "description": "Why this decision was made"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level 0-1 (default: 0.5)"
                },
                "context": {
                    "type": "object",
                    "description": "Context at time of decision"
                },
                "query": {
                    "type": "string",
                    "description": "Original query if applicable"
                }
            },
            "required": ["category", "decision_point", "decision_made"]
        }
    },
    {
        "name": "record_decision_outcome",
        "description": "Record the outcome of a decision. Updates patterns for future learning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision_id": {
                    "type": "string",
                    "description": "Decision ID from record_decision"
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failure", "unknown"],
                    "description": "Outcome status"
                },
                "outcome_score": {
                    "type": "number",
                    "description": "Numeric score 0-1"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes"
                }
            },
            "required": ["decision_id", "outcome"]
        }
    },
    {
        "name": "get_decision_history",
        "description": "Get recent decision history with outcomes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category"
                },
                "days": {
                    "type": "integer",
                    "description": "Days to look back (default: 7)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max decisions (default: 50)"
                }
            }
        }
    },
    {
        "name": "get_decision_stats",
        "description": "Get decision statistics and learned patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category"
                },
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 30)"
                }
            }
        }
    },
    {
        "name": "suggest_decision",
        "description": "Suggest a decision based on learned patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Decision category"
                },
                "context": {
                    "type": "object",
                    "description": "Current context"
                }
            },
            "required": ["category"]
        }
    }
]
