"""
Calendar Tools.

Google Calendar integration and git events.
Extracted from tools.py (Phase S2).
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import requests

from ..observability import get_logger, log_with_context, metrics
from ..errors import (
    JarvisException, ErrorCode, wrap_external_error,
    internal_error
)

logger = get_logger("jarvis.tools.calendar")

import os
N8N_BASE = os.getenv("N8N_BASE", "http://n8n:5678")
N8N_TIMEOUT = int(os.getenv("N8N_TIMEOUT", "60"))


def tool_get_calendar_events(
    timeframe: str = "week",
    account: str = "all",
    **kwargs
) -> Dict[str, Any]:
    """
    Get calendar events via n8n (Google Calendar API gateway).

    Raises:
        JarvisException: On API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: get_calendar_events",
                    timeframe=timeframe, account=account)
    metrics.inc("tool_get_calendar_events")

    try:
        from . import n8n_client

        # Use filtered calendar function
        events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)

        # Check for API-level errors
        if isinstance(events, dict) and events.get("error"):
            error_msg = events.get("error", "Unknown calendar error")
            raise JarvisException(
                code=ErrorCode.CALENDAR_API_ERROR,
                message=f"Failed to fetch calendar: {error_msg}",
                status_code=502,
                details={"timeframe": timeframe, "account": account},
                recoverable="timeout" in str(error_msg).lower(),
                retry_after=15,
                hint="Check n8n Calendar configuration or try again"
            )

        # Include date headers for multi-day views
        include_date = timeframe in ("week", "all")
        formatted = n8n_client.format_events_for_briefing(events, include_date=include_date)

        return {
            "timeframe": timeframe,
            "account": account,
            "events": events,
            "count": len(events),
            "formatted": formatted,
            "source": "n8n"
        }
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Calendar fetch timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Calendar fetch timed out",
            status_code=504,
            details={"timeframe": timeframe, "account": account},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Calendar fetch failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="calendar")


def tool_create_calendar_event(
    summary: str,
    start: str,
    end: str,
    account: str = "projektil",
    description: str = "",
    location: str = "",
    attendees: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a calendar event via n8n.

    Args:
        summary: Event title
        start: Start time in ISO 8601 format (e.g., "2026-01-30T14:00:00+01:00")
        end: End time in ISO 8601 format
        account: "projektil" or "visualfox"
        description: Optional event description
        location: Optional location
        attendees: Optional list of email addresses to invite

    Raises:
        JarvisException: On API errors or invalid datetime formats
    """
    log_with_context(logger, "info", "Tool: create_calendar_event",
                    summary=summary, account=account)
    metrics.inc("tool_create_calendar_event")

    # Validate datetime formats early
    try:
        from datetime import datetime as dt
        dt.fromisoformat(start.replace('Z', '+00:00'))
        dt.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError as e:
        raise JarvisException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Invalid datetime format: {str(e)}",
            status_code=400,
            details={"start": start, "end": end},
            recoverable=False,
            hint="Use ISO 8601 format: YYYY-MM-DDTHH:MM:SS+HH:MM"
        )

    try:
        from . import n8n_client

        result = n8n_client.create_calendar_event(
            summary=summary,
            start=start,
            end=end,
            account=account,
            description=description,
            location=location,
            attendees=attendees
        )

        # Check for API-level errors
        if not result.get("success") and result.get("error"):
            error_msg = result.get("error", "Unknown calendar error")
            raise JarvisException(
                code=ErrorCode.CALENDAR_API_ERROR,
                message=f"Failed to create calendar event: {error_msg}",
                status_code=502,
                details={"summary": summary, "account": account},
                recoverable="timeout" in str(error_msg).lower() or "rate" in str(error_msg).lower(),
                retry_after=30 if "rate" in str(error_msg).lower() else 10,
                hint="Check n8n Calendar configuration or try again"
            )

        return result
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Create calendar event timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Calendar event creation timed out",
            status_code=504,
            details={"summary": summary, "account": account},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Create calendar event failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="calendar")

def tool_get_git_events(**kwargs) -> Dict[str, Any]:
    """Return git commits in a time range (optional keywords)."""
    try:
        from .git_history import get_git_events

        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        keywords = kwargs.get("keywords")
        limit = kwargs.get("limit", 100)

        keyword_list = None
        if isinstance(keywords, str) and keywords.strip():
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
        elif isinstance(keywords, list):
            keyword_list = [str(k).strip() for k in keywords if str(k).strip()]

        result = get_git_events(
            start_time=start_time,
            end_time=end_time,
            keywords=keyword_list,
            limit=limit,
        )
        metrics.inc("tool_get_git_events")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool get_git_events failed", error=str(e))
        return {"error": str(e)}

