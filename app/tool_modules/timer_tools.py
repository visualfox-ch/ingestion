"""
Timer Tools - Reminder/Timer Management

Extracted from tools.py as part of T006 Main/Tools Split.
"""

from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

TIMER_TOOLS = [
    {
        "name": "set_timer",
        "description": "Create a reminder timer scheduled via n8n and stored in Redis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Reminder text to send"
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay in seconds"
                },
                "delay_minutes": {
                    "type": "number",
                    "description": "Delay in minutes"
                },
                "due_at": {
                    "type": "string",
                    "description": "ISO timestamp for when to fire"
                },
                "user_id": {
                    "type": "string",
                    "description": "Telegram user id (defaults to current user)"
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Ask user for confirmation before firing",
                    "default": False
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "cancel_timer",
        "description": "Cancel an existing timer by timer_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timer_id": {
                    "type": "string",
                    "description": "Timer ID to cancel"
                },
                "user_id": {
                    "type": "string",
                    "description": "User id (optional)"
                }
            },
            "required": ["timer_id"]
        }
    },
    {
        "name": "list_timers",
        "description": "List timers for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User id (optional)"
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (pending, fired, canceled)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max timers to return",
                    "default": 50
                }
            }
        }
    },
]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

def tool_set_timer(**kwargs) -> Dict[str, Any]:
    """
    Create a reminder timer (scheduled via n8n, stored in Redis).
    """
    try:
        from ..timer_service import create_timer
        from ..tracing import get_current_user_id
        from .. import metrics

        message = kwargs.get("message")
        delay_seconds = kwargs.get("delay_seconds")
        delay_minutes = kwargs.get("delay_minutes")
        due_at = kwargs.get("due_at")
        confirm = bool(kwargs.get("confirm", False))

        if message is None or not str(message).strip():
            return {"error": "message is required"}

        if delay_seconds is None and delay_minutes is not None:
            delay_seconds = int(float(delay_minutes) * 60)

        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")

        result = create_timer(
            user_id=user_id,
            message=str(message),
            due_at=due_at,
            delay_seconds=delay_seconds,
            channel="telegram",
            source="tool",
            confirm=confirm,
        )

        metrics.inc("tool_set_timer")
        return result

    except Exception as e:
        logger.warning(f"Set timer failed: {e}")
        return {"error": str(e)}


def tool_cancel_timer(**kwargs) -> Dict[str, Any]:
    """
    Cancel an existing timer by timer_id.
    """
    try:
        from ..timer_service import cancel_timer
        from ..tracing import get_current_user_id
        from .. import metrics

        timer_id = kwargs.get("timer_id")
        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")

        if not timer_id:
            return {"error": "timer_id is required"}

        result = cancel_timer(str(timer_id), user_id=user_id)
        metrics.inc("tool_cancel_timer")
        return result

    except Exception as e:
        logger.warning(f"Cancel timer failed: {e}")
        return {"error": str(e)}


def tool_list_timers(**kwargs) -> Dict[str, Any]:
    """
    List timers for a user.
    """
    try:
        from ..timer_service import list_timers
        from ..tracing import get_current_user_id
        from .. import metrics

        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")
        status = kwargs.get("status")
        limit = kwargs.get("limit", 50)

        result = list_timers(str(user_id), status=status, limit=int(limit))
        metrics.inc("tool_list_timers")
        return result

    except Exception as e:
        logger.warning(f"List timers failed: {e}")
        return {"error": str(e)}
