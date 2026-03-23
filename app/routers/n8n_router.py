"""
n8n Integration Router

Extracted from main.py - All n8n-related endpoints for:
- Google Calendar integration
- Gmail integration
- Drive sync
- Workflow management
- Reliability contracts
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
Any = Any  # Re-export for Depends type hint
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse
from ..rate_limiter import rate_limit_dependency
from ..observability import get_logger
from ..metrics import CALENDAR_EVENTS_ALIAS_REQUESTS_TOTAL
from ..jobs.alias_sunset_job import is_sunsetted, record_alias_call

logger = get_logger("jarvis.n8n")
router = APIRouter(prefix="/n8n", tags=["n8n"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class CalendarEventRequest(BaseModel):
    summary: str
    start: str  # ISO 8601 format
    end: str    # ISO 8601 format
    account: str = "projektil"
    description: str = ""
    location: str = ""
    attendees: List[str] = []


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""


class CreateWorkflowRequest(BaseModel):
    workflow_data: Dict[str, Any]


class UpdateWorkflowRequest(BaseModel):
    workflow_data: Dict[str, Any]


class ExecuteWorkflowRequest(BaseModel):
    data: Dict[str, Any] = None


class CreateFromTemplateRequest(BaseModel):
    template_name: str
    params: Dict[str, Any]


# =============================================================================
# STATUS & CALENDAR ENDPOINTS
# =============================================================================

@router.get("/status")
def n8n_status():
    """Get n8n connection status"""
    from .. import n8n_client
    return n8n_client.get_n8n_status()


@router.get("/calendar")
def n8n_calendar(timeframe: str = "week", account: str = "all"):
    """
    Get calendar events with filtering.

    Args:
        timeframe: today, tomorrow, week, all (default: week)
        account: all, visualfox, projektil (default: all)
    """
    from .. import n8n_client
    events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)
    include_date = timeframe in ("week", "all")
    return {
        "events": events,
        "count": len(events),
        "timeframe": timeframe,
        "account": account,
        "formatted": n8n_client.format_events_for_briefing(events, include_date=include_date)
    }


@router.get("/calendar/today")
def n8n_calendar_today():
    """Get today's calendar events from all accounts"""
    from .. import n8n_client
    events = n8n_client.get_today_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "today",
        "formatted": n8n_client.format_events_for_briefing(events)
    }


@router.get("/calendar/tomorrow")
def n8n_calendar_tomorrow():
    """Get tomorrow's calendar events from all accounts"""
    from .. import n8n_client
    events = n8n_client.get_tomorrow_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "tomorrow",
        "formatted": n8n_client.format_events_for_briefing(events)
    }


@router.get("/calendar/week")
def n8n_calendar_week():
    """Get this week's calendar events from all accounts"""
    from .. import n8n_client
    events = n8n_client.get_week_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "week",
        "formatted": n8n_client.format_events_for_briefing(events, include_date=True)
    }


def _parse_event_dt(raw_value: Optional[str]) -> Optional[datetime]:
    """Parse event date/datetime into UTC datetime for lightweight window filtering."""
    if not raw_value:
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    try:
        if len(value) == 10:
            # Date-only events use YYYY-MM-DD; treat as UTC midnight.
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


@router.get("/calendar/events")
def n8n_calendar_events(hours: int = 24, account: str = "all"):
    """Backward-compatible calendar events endpoint (legacy callers use hours window)."""
    if is_sunsetted():
        return JSONResponse(
            status_code=410,
            content={
                "error": "endpoint_removed",
                "message": "This endpoint was auto-retired after 30 days of zero usage. Use /n8n/calendar instead.",
                "replacement": "/n8n/calendar",
            },
        )

    from .. import n8n_client

    safe_hours = max(1, min(int(hours), 168))
    safe_account = str(account or "all").strip() or "all"
    CALENDAR_EVENTS_ALIAS_REQUESTS_TOTAL.labels(account=safe_account).inc()
    record_alias_call()
    window_start = datetime.now(timezone.utc)
    window_end = window_start + timedelta(hours=safe_hours)

    events = n8n_client.get_calendar_events(timeframe="all", account=safe_account)
    filtered: List[Dict[str, Any]] = []

    for event in events:
        start_dt = _parse_event_dt(event.get("start"))
        end_dt = _parse_event_dt(event.get("end")) or start_dt

        if start_dt is None or end_dt is None:
            continue

        # Include events overlapping the [now, now+hours] window.
        if start_dt <= window_end and end_dt >= window_start:
            filtered.append(event)

    return {
        "events": filtered,
        "count": len(filtered),
        "hours": safe_hours,
        "account": safe_account,
        "formatted": n8n_client.format_events_for_briefing(filtered, include_date=True),
    }


@router.post("/calendar")
def n8n_create_calendar_event(req: CalendarEventRequest):
    """
    Create a calendar event via n8n.

    Body:
    - summary: Event title (required)
    - start: ISO 8601 datetime (required)
    - end: ISO 8601 datetime (required)
    - account: "projektil" or "visualfox" (default: projektil)
    - description: Event description
    - location: Event location
    - attendees: List of email addresses
    """
    from .. import n8n_client
    result = n8n_client.create_calendar_event(
        summary=req.summary,
        start=req.start,
        end=req.end,
        account=req.account,
        description=req.description,
        location=req.location,
        attendees=req.attendees if req.attendees else None
    )
    return result


# =============================================================================
# GMAIL ENDPOINTS
# =============================================================================

@router.get("/gmail/projektil")
def n8n_gmail_projektil(limit: int = 10):
    """Get recent emails from Projektil Gmail account via n8n"""
    from .. import n8n_client
    emails = n8n_client.get_gmail_projektil(limit=limit)
    return {
        "emails": emails,
        "count": len(emails),
        "account": "projektil",
        "formatted": n8n_client.format_emails_for_briefing(emails)
    }


@router.post("/gmail")
def n8n_send_email(req: SendEmailRequest):
    """
    Send an email via n8n (Projektil Gmail account).

    Note: Only Projektil has Gmail. Visualfox has no Gmail.

    Body:
    - to: Recipient email (required)
    - subject: Email subject (required)
    - body: Email body - plain text or HTML (required)
    - cc: CC recipients (comma-separated)
    - bcc: BCC recipients (comma-separated)
    """
    from .. import n8n_client
    result = n8n_client.send_email(
        to=req.to,
        subject=req.subject,
        body=req.body,
        cc=req.cc,
        bcc=req.bcc
    )
    return result


# NOTE: /gmail/sync and /drive/* endpoints remain in main.py
# They have complex request models (GmailSyncRequest, DriveSyncRequest)
# that should be migrated in a future iteration


# =============================================================================
# WORKFLOW MANAGEMENT
# =============================================================================

@router.get("/workflows")
def list_n8n_workflows(
    active_only: bool = False,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """List all n8n workflows."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    workflows = manager.list_workflows(active_only)
    return {"workflows": workflows}


@router.get("/workflows/{workflow_id}")
def get_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get a specific n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.get_workflow(workflow_id)


@router.post("/workflows")
def create_n8n_workflow(
    req: CreateWorkflowRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Create a new n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.create_workflow(req.workflow_data)


@router.patch("/workflows/{workflow_id}")
def update_n8n_workflow(
    workflow_id: str,
    req: UpdateWorkflowRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Update an n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.update_workflow(workflow_id, req.workflow_data)


@router.post("/workflows/{workflow_id}/activate")
def activate_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Activate an n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.activate_workflow(workflow_id)


@router.post("/workflows/{workflow_id}/deactivate")
def deactivate_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Deactivate an n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.deactivate_workflow(workflow_id)


@router.delete("/workflows/{workflow_id}")
def delete_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Delete an n8n workflow."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.delete_workflow(workflow_id)


@router.post("/workflows/{workflow_id}/execute")
def execute_n8n_workflow(
    workflow_id: str,
    req: ExecuteWorkflowRequest = None,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute an n8n workflow manually."""
    from .. import n8n_workflow_manager
    manager = n8n_workflow_manager.N8NWorkflowManager()
    data = req.data if req else None
    return manager.execute_workflow(workflow_id, data)


@router.get("/templates")
def get_workflow_templates(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get available workflow templates."""
    from .. import n8n_workflow_manager
    return n8n_workflow_manager.get_workflow_templates()


@router.post("/templates/create")
def create_from_template(
    req: CreateFromTemplateRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Create a workflow from a template."""
    from .. import n8n_workflow_manager
    return n8n_workflow_manager.create_workflow_from_template(
        req.template_name,
        req.params
    )


@router.get("/workflow/status")
def get_n8n_workflow_status(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get n8n workflow management status."""
    from .. import n8n_workflow_manager
    return n8n_workflow_manager.get_n8n_workflow_status()


# =============================================================================
# RELIABILITY CONTRACT & DEAD LETTER
# =============================================================================

@router.get("/contract")
def get_n8n_contract():
    """
    Get n8n Reliability Contract overview.

    Shows SLA compliance for all tracked workflows by tier.
    """
    from .. import n8n_reliability as n8n_rel
    return n8n_rel.get_contract_overview()


@router.get("/contract/workflow/{workflow_name}")
def get_workflow_contract(workflow_name: str, days: int = 7):
    """
    Check SLA compliance for a specific workflow.

    Args:
        workflow_name: Name of the workflow
        days: Number of days to check (default 7)
    """
    from .. import n8n_reliability as n8n_rel
    return n8n_rel.check_workflow_compliance(workflow_name, days)


@router.get("/dead-letter")
def get_dead_letter_queue(status: str = None, limit: int = 50):
    """
    Get dead letter queue items.

    Args:
        status: Filter by status (pending, retrying, resolved, abandoned)
        limit: Max items to return
    """
    from ..postgres_state import get_cursor

    try:
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with get_cursor() as cur:
            cur.execute(f"""
                SELECT * FROM n8n_dead_letter
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)
            rows = cur.fetchall()

        return {
            "items": [
                {
                    **dict(row),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None
                }
                for row in rows
            ],
            "count": len(rows),
            "filter": {"status": status}
        }
    except Exception as e:
        logger.error(f"Failed to get dead letter queue: {e}")
        return {"error": str(e), "items": []}


@router.get("/dead-letter/stats")
def get_dead_letter_stats():
    """Get dead letter queue statistics."""
    from .. import n8n_reliability as n8n_rel
    return n8n_rel.get_dead_letter_stats()


@router.post("/dead-letter/resolve/{dl_id}")
def resolve_dead_letter_item(dl_id: int, success: bool = True):
    """
    Mark a dead letter item as resolved or abandoned.

    Args:
        dl_id: Dead letter item ID
        success: True for resolved, False for abandoned
    """
    from .. import n8n_reliability as n8n_rel

    result = n8n_rel.resolve_dead_letter(dl_id, success)
    return {
        "dl_id": dl_id,
        "resolved": result,
        "status": "resolved" if success else "abandoned"
    }


@router.get("/sla-tiers")
def get_sla_tiers():
    """Get SLA tier definitions."""
    from .. import n8n_reliability as n8n_rel
    from dataclasses import asdict

    return {
        "tiers": {
            tier: asdict(sla)
            for tier, sla in n8n_rel.SLA_TIERS.items()
        },
        "workflow_assignments": n8n_rel.WORKFLOW_TIERS,
        "description": "n8n Reliability Contract SLA definitions"
    }


# =============================================================================
# N8N MONITORING & AUTO-HEALING
# =============================================================================

@router.get("/monitor")
def get_n8n_monitor_status():
    """
    Get real-time n8n workflow monitoring dashboard data.

    Returns comprehensive status including:
    - Total/active/inactive workflow counts
    - Critical workflows that are down
    - Error rates and recent failures
    - Health assessment
    """
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.get_dashboard_data()


@router.get("/monitor/status")
def get_workflow_status_summary():
    """Get workflow status summary."""
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.get_workflow_status()


@router.get("/monitor/errors")
def get_workflow_errors(hours: int = 24):
    """Get workflow error summary for the last N hours."""
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.get_error_summary()


@router.get("/monitor/executions")
def get_recent_executions(hours: int = 24, limit: int = 50):
    """Get recent workflow executions."""
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.get_recent_executions(hours=hours, limit=limit)


@router.post("/monitor/heal")
def trigger_auto_heal():
    """
    Trigger auto-healing for n8n workflows.

    This will:
    - Reactivate stopped critical workflows
    - Ensure error handlers are attached
    """
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.auto_heal()


@router.post("/monitor/sync")
def sync_workflows_from_files():
    """
    Sync workflows from JSON files to n8n.

    Creates missing workflows from /brain/system/n8n/workflows/*.json
    """
    from ..services.n8n_monitoring_service import get_n8n_monitoring_service
    service = get_n8n_monitoring_service()
    return service.sync_from_files()
