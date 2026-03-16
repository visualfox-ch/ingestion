"""
Session Pattern Tools - Phase 1.3

Tools for Jarvis to understand and leverage session patterns:
- Get current session state and type
- Predict next likely tools
- View session history and transitions
- Get session summaries
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_current_session(
    user_id: str = "default",
    **kwargs
) -> Dict[str, Any]:
    """
    Get current session info including type and duration.

    Returns session state, type (coding/research/planning/etc.),
    and recent activity.

    Args:
        user_id: User identifier (default: "default")

    Returns:
        Dict with session info
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.get_or_create_session(user_id=user_id)

    except Exception as e:
        logger.error(f"Get current session failed: {e}")
        return {"success": False, "error": str(e)}


def get_session_summary(
    user_id: str = "default",
    **kwargs
) -> Dict[str, Any]:
    """
    Get detailed summary of current session.

    Shows session type, duration, top tools used, and recent activity.

    Args:
        user_id: User identifier (default: "default")

    Returns:
        Dict with session summary
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.get_session_summary(user_id=user_id)

    except Exception as e:
        logger.error(f"Get session summary failed: {e}")
        return {"success": False, "error": str(e)}


def predict_next_tools(
    user_id: str = "default",
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Predict likely next tools based on session patterns.

    Uses current session type, recent tools, and historical patterns
    to suggest what tools might be needed next.

    Args:
        user_id: User identifier (default: "default")
        limit: Max predictions to return (default: 5)

    Returns:
        Dict with tool predictions and reasoning
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.predict_next_tools(user_id=user_id, limit=limit)

    except Exception as e:
        logger.error(f"Predict next tools failed: {e}")
        return {"success": False, "error": str(e)}


def get_session_history(
    user_id: str = "default",
    days: int = 7,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get historical session data.

    Shows past sessions, their types, durations, and aggregated stats.

    Args:
        user_id: User identifier (default: "default")
        days: Number of days to look back (default: 7)
        limit: Max sessions to return (default: 20)

    Returns:
        Dict with session history and summary
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.get_session_history(user_id=user_id, days=days, limit=limit)

    except Exception as e:
        logger.error(f"Get session history failed: {e}")
        return {"success": False, "error": str(e)}


def get_session_transitions(
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Get common session type transitions.

    Shows patterns like "research -> coding" or "planning -> communication"
    with frequencies and typical durations.

    Args:
        limit: Max transitions to return (default: 10)

    Returns:
        Dict with transition patterns
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.get_transition_patterns(limit=limit)

    except Exception as e:
        logger.error(f"Get session transitions failed: {e}")
        return {"success": False, "error": str(e)}


def record_session_activity(
    tool_name: str,
    user_id: str = "default",
    query: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record tool activity in current session.

    Updates session state and detects type transitions.
    Called automatically by the agent, but can also be called manually.

    Args:
        tool_name: Name of tool that was used
        user_id: User identifier (default: "default")
        query: The query that triggered the tool (optional)

    Returns:
        Dict with updated session state
    """
    try:
        from app.services.session_pattern_service import get_session_pattern_service

        service = get_session_pattern_service()
        return service.record_tool_use(
            tool_name=tool_name,
            user_id=user_id,
            query=query
        )

    except Exception as e:
        logger.error(f"Record session activity failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
SESSION_PATTERN_TOOLS = [
    {
        "name": "get_current_session",
        "description": "Get current session info including type (coding/research/planning/communication/introspection) and duration. Use this to understand the current work context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                }
            }
        }
    },
    {
        "name": "get_session_summary",
        "description": "Get detailed summary of current session including top tools used, duration, and recent activity pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                }
            }
        }
    },
    {
        "name": "predict_next_tools",
        "description": "Predict likely next tools based on session patterns. Uses current context and historical patterns to suggest what tools might be needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max predictions to return (default: 5)"
                }
            }
        }
    },
    {
        "name": "get_session_history",
        "description": "Get historical session data showing past sessions, their types, durations, and aggregated stats by session type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default: 7)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max sessions to return (default: 20)"
                }
            }
        }
    },
    {
        "name": "get_session_transitions",
        "description": "Get common session type transitions like 'research -> coding'. Shows frequencies and typical durations before transition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max transitions to return (default: 10)"
                }
            }
        }
    },
    {
        "name": "record_session_activity",
        "description": "Manually record tool activity in current session. Usually called automatically, but can be used to manually update session state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of tool that was used"
                },
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                },
                "query": {
                    "type": "string",
                    "description": "The query that triggered the tool"
                }
            },
            "required": ["tool_name"]
        }
    }
]
