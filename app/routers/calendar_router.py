"""
Calendar Router

Extracted from main.py - Calendar Management endpoints:
- Conflict detection
- Suggest event (HITL)
- Suggest reschedule (HITL)
- Execute approved actions
- Pending suggestions
- Suggestion history
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json

from ..observability import get_logger

logger = get_logger("jarvis.calendar")
router = APIRouter(prefix="/calendar", tags=["calendar"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class CalendarSuggestionRequest(BaseModel):
    """Request model for calendar event suggestions."""
    summary: str
    start: str  # ISO 8601 format
    end: str    # ISO 8601 format
    account: str = "projektil"  # projektil or visualfox
    description: str = ""
    location: str = ""
    reason: str = ""  # Why this event is being suggested


class CalendarRescheduleRequest(BaseModel):
    """Request model for rescheduling suggestions."""
    event_id: str  # ID of the event to reschedule
    account: str = "projektil"
    new_start: str  # ISO 8601 format
    new_end: str    # ISO 8601 format
    reason: str = ""  # Why rescheduling is suggested


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _calculate_overlap(e1_start: str, e1_end: str, e2_start: str, e2_end: str) -> int:
    """Calculate overlap duration in minutes."""
    from datetime import datetime
    try:
        # Parse ISO 8601
        e1_end_dt = datetime.fromisoformat(e1_end.replace("Z", "+00:00"))
        e2_start_dt = datetime.fromisoformat(e2_start.replace("Z", "+00:00"))
        e2_end_dt = datetime.fromisoformat(e2_end.replace("Z", "+00:00"))

        overlap_start = max(datetime.fromisoformat(e1_start.replace("Z", "+00:00")), e2_start_dt)
        overlap_end = min(e1_end_dt, e2_end_dt)

        if overlap_end > overlap_start:
            return int((overlap_end - overlap_start).total_seconds() / 60)
    except Exception:
        pass
    return 0


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/conflicts")
def get_calendar_conflicts(
    timeframe: str = "week",
    account: str = "all"
):
    """
    Detect calendar conflicts (overlapping events).

    Args:
        timeframe: today, tomorrow, week (default: week)
        account: all, visualfox, projektil (default: all)

    Returns:
        List of conflict pairs with event details
    """
    from .. import n8n_client

    events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)

    # Sort events by start time
    def parse_time(event):
        start = event.get("start", {})
        if isinstance(start, str):
            return start
        return start.get("dateTime") or start.get("date") or ""

    events_sorted = sorted(events, key=parse_time)

    conflicts = []
    for i, event1 in enumerate(events_sorted):
        for event2 in events_sorted[i+1:]:
            # Get start/end times
            e1_start = parse_time(event1)
            e1_end = event1.get("end", {})
            if isinstance(e1_end, dict):
                e1_end = e1_end.get("dateTime") or e1_end.get("date") or ""

            e2_start = parse_time(event2)
            e2_end = event2.get("end", {})
            if isinstance(e2_end, dict):
                e2_end = e2_end.get("dateTime") or e2_end.get("date") or ""

            # Check for overlap
            if e1_end > e2_start:
                conflicts.append({
                    "event1": {
                        "id": event1.get("id"),
                        "summary": event1.get("summary"),
                        "start": e1_start,
                        "end": e1_end,
                        "account": event1.get("account")
                    },
                    "event2": {
                        "id": event2.get("id"),
                        "summary": event2.get("summary"),
                        "start": e2_start,
                        "end": e2_end,
                        "account": event2.get("account")
                    },
                    "overlap_minutes": _calculate_overlap(e1_start, e1_end, e2_start, e2_end)
                })

    return {
        "conflicts": conflicts,
        "count": len(conflicts),
        "timeframe": timeframe,
        "account": account
    }


@router.post("/suggest-event")
def suggest_calendar_event(req: CalendarSuggestionRequest):
    """
    Suggest creating a new calendar event (HITL - requires approval).

    This endpoint:
    1. Validates the suggestion
    2. Creates an action request for approval
    3. Sends Telegram notification with approve/reject buttons
    4. Returns action_id for tracking

    Does NOT create the event directly!
    Event creation only happens after explicit user approval.
    """
    from ..telegram_bot import request_action_approval
    from datetime import datetime

    # Validate times
    try:
        start_dt = datetime.fromisoformat(req.start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(req.end.replace("Z", "+00:00"))
        if end_dt <= start_dt:
            raise HTTPException(status_code=400, detail="End time must be after start time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")

    # Format for human-readable display
    start_fmt = start_dt.strftime("%d.%m.%Y %H:%M")
    end_fmt = end_dt.strftime("%H:%M")
    duration = int((end_dt - start_dt).total_seconds() / 60)

    # Create approval request
    description = f"Neuen Termin erstellen:\n\n"
    description += f"**{req.summary}**\n"
    description += f"{start_fmt} - {end_fmt} ({duration} Min)\n"
    description += f"Kalender: {req.account}\n"
    if req.location:
        description += f"{req.location}\n"
    if req.reason:
        description += f"\nGrund: {req.reason}"

    result = request_action_approval(
        action_name="calendar_suggest_event",
        description=description,
        target=f"calendar:{req.account}",
        context={
            "type": "calendar_create",
            "summary": req.summary,
            "start": req.start,
            "end": req.end,
            "account": req.account,
            "description": req.description,
            "location": req.location,
            "reason": req.reason
        },
        urgent=False
    )

    return {
        "status": "pending_approval" if result.get("status") == "pending" else result.get("status"),
        "action_id": result.get("id"),
        "message": "Suggestion sent to Telegram for approval" if result.get("status") == "pending" else result.get("result", {}).get("error", "Unknown status"),
        "expires_at": result.get("expires_at"),
        "suggestion": {
            "summary": req.summary,
            "start": req.start,
            "end": req.end,
            "account": req.account
        }
    }


@router.post("/suggest-reschedule")
def suggest_calendar_reschedule(req: CalendarRescheduleRequest):
    """
    Suggest rescheduling an existing calendar event (HITL - requires approval).

    This endpoint:
    1. Fetches the original event
    2. Validates the new times
    3. Creates an action request for approval
    4. Sends Telegram notification with approve/reject buttons
    5. Returns action_id for tracking

    Does NOT modify the event directly!
    Modification only happens after explicit user approval.
    """
    from ..telegram_bot import request_action_approval
    from .. import n8n_client
    from datetime import datetime

    # Validate times
    try:
        new_start_dt = datetime.fromisoformat(req.new_start.replace("Z", "+00:00"))
        new_end_dt = datetime.fromisoformat(req.new_end.replace("Z", "+00:00"))
        if new_end_dt <= new_start_dt:
            raise HTTPException(status_code=400, detail="End time must be after start time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")

    # Try to find the original event
    events = n8n_client.get_calendar_events(timeframe="all", account=req.account)
    original_event = None
    for event in events:
        if event.get("id") == req.event_id:
            original_event = event
            break

    event_summary = original_event.get("summary", "Unbekannter Termin") if original_event else f"Event {req.event_id}"

    # Format for human-readable display
    new_start_fmt = new_start_dt.strftime("%d.%m.%Y %H:%M")
    new_end_fmt = new_end_dt.strftime("%H:%M")
    duration = int((new_end_dt - new_start_dt).total_seconds() / 60)

    # Get original times for comparison
    original_start = ""
    if original_event:
        orig_start = original_event.get("start", {})
        if isinstance(orig_start, dict):
            original_start = orig_start.get("dateTime", orig_start.get("date", ""))
        else:
            original_start = orig_start
        try:
            orig_dt = datetime.fromisoformat(original_start.replace("Z", "+00:00"))
            original_start = orig_dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass

    # Create approval request
    description = f"Termin verschieben:\n\n"
    description += f"**{event_summary}**\n"
    if original_start:
        description += f"Alt: {original_start}\n"
    description += f"Neu: {new_start_fmt} - {new_end_fmt} ({duration} Min)\n"
    description += f"Kalender: {req.account}\n"
    if req.reason:
        description += f"\nGrund: {req.reason}"

    result = request_action_approval(
        action_name="calendar_suggest_reschedule",
        description=description,
        target=f"calendar:{req.account}:{req.event_id}",
        context={
            "type": "calendar_reschedule",
            "event_id": req.event_id,
            "account": req.account,
            "new_start": req.new_start,
            "new_end": req.new_end,
            "original_summary": event_summary,
            "original_start": original_start,
            "reason": req.reason
        },
        urgent=False
    )

    return {
        "status": "pending_approval" if result.get("status") == "pending" else result.get("status"),
        "action_id": result.get("id"),
        "message": "Reschedule suggestion sent to Telegram for approval" if result.get("status") == "pending" else result.get("result", {}).get("error", "Unknown status"),
        "expires_at": result.get("expires_at"),
        "suggestion": {
            "event_id": req.event_id,
            "original_summary": event_summary,
            "new_start": req.new_start,
            "new_end": req.new_end,
            "account": req.account
        }
    }


@router.post("/execute-approved/{action_id}")
def execute_approved_calendar_action(action_id: str):
    """
    Execute an approved calendar action.

    This endpoint is called after an action is approved (via Telegram or API).
    It performs the actual calendar modification.

    Only works for approved actions!
    """
    from .. import action_queue, n8n_client

    action = action_queue.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.get("status") != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Action is not approved (status: {action.get('status')})"
        )

    context = action.get("context", {})
    action_type = context.get("type")

    if action_type == "calendar_create":
        # Create new event
        result = n8n_client.create_calendar_event(
            summary=context.get("summary"),
            start=context.get("start"),
            end=context.get("end"),
            account=context.get("account", "projektil"),
            description=context.get("description", ""),
            location=context.get("location", "")
        )

        # Mark action as completed
        action_queue.mark_action_completed(action_id, result=result)

        return {
            "status": "executed",
            "action_type": "calendar_create",
            "result": result
        }

    elif action_type == "calendar_reschedule":
        # Note: Rescheduling requires updating an existing event
        # This would need n8n to support event updates
        # For now, we return a message that manual action is needed

        action_queue.mark_action_completed(action_id, result={
            "status": "manual_action_required",
            "message": "Event rescheduling requires manual update via Google Calendar",
            "event_id": context.get("event_id"),
            "new_start": context.get("new_start"),
            "new_end": context.get("new_end")
        })

        return {
            "status": "manual_action_required",
            "action_type": "calendar_reschedule",
            "message": "Please update the event manually in Google Calendar",
            "details": {
                "event_id": context.get("event_id"),
                "new_start": context.get("new_start"),
                "new_end": context.get("new_end")
            }
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")


@router.get("/suggestions/pending")
def get_pending_calendar_suggestions():
    """
    Get all pending calendar suggestions waiting for approval.
    """
    from .. import action_queue

    all_pending = action_queue.get_pending_actions()
    calendar_pending = [
        a for a in all_pending
        if a.get("action") in ["calendar_suggest_event", "calendar_suggest_reschedule"]
    ]

    return {
        "count": len(calendar_pending),
        "suggestions": calendar_pending
    }


@router.get("/suggestions/history")
def get_calendar_suggestion_history(limit: int = 20):
    """
    Get history of calendar suggestions (approved, rejected, expired).
    """
    from .. import action_queue

    history = []
    queue_base = Path(action_queue.ACTION_QUEUE_BASE)

    for status_dir in ["approved", "rejected", "expired", "completed"]:
        dir_path = queue_base / status_dir
        if not dir_path.exists():
            continue

        for file_path in dir_path.glob("*.json"):
            try:
                with open(file_path) as f:
                    action = json.load(f)
                    if action.get("action") in ["calendar_suggest_event", "calendar_suggest_reschedule"]:
                        history.append(action)
            except Exception:
                continue

    # Sort by created_at descending
    history.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "count": len(history[:limit]),
        "total": len(history),
        "history": history[:limit]
    }
