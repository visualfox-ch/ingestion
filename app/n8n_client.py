"""
n8n API Client - Gateway to Google APIs via n8n webhooks.

n8n handles OAuth authentication for Google services.
This client provides a clean interface for Jarvis to interact with Google APIs.

Architecture (Unified API Gateway):
- GET  /webhook/google?service=calendar&account=...  → Read calendar events
- POST /webhook/google?service=calendar&account=...  → Create calendar event
- GET  /webhook/google?service=gmail                 → Read emails (Projektil only)
- POST /webhook/google?service=gmail                 → Send email (Projektil only)

Accounts:
- projektil: Calendar + Gmail
- visualfox: Calendar only (NO Gmail!)
"""
import os
import time
import asyncio
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.n8n")


def _sleep(seconds: float) -> None:
    """Sleep using asyncio when no running loop; fallback to time.sleep otherwise."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(asyncio.sleep(seconds))
        return
    time.sleep(seconds)

# Rate limiting configuration
RATE_LIMIT_MAX_RETRIES = 4
RATE_LIMIT_INITIAL_BACKOFF = 1.0  # seconds
RATE_LIMIT_PATTERNS = ["rate", "429", "quota", "too many requests", "limit exceeded"]

# n8n configuration
N8N_HOST = os.environ.get("N8N_HOST", "n8n")  # Docker DNS
N8N_PORT = int(os.environ.get("N8N_PORT", "5678"))  # Internal port
N8N_BASE_URL = f"http://{N8N_HOST}:{N8N_PORT}/webhook"
N8N_TIMEOUT = int(os.environ.get("N8N_TIMEOUT", "30"))

# Mock mode for stresstest (disable external API calls)
MOCK_N8N = os.environ.get("MOCK_N8N", "false").lower() == "true"


# ============ Mock Responses ============

MOCK_CALENDAR_EVENTS = [
    {
        "id": "mock_event_1",
        "summary": "Mock Meeting",
        "start": {"dateTime": (datetime.now() + timedelta(hours=2)).isoformat()},
        "end": {"dateTime": (datetime.now() + timedelta(hours=3)).isoformat()},
    },
    {
        "id": "mock_event_2",
        "summary": "Mock Standup",
        "start": {"dateTime": (datetime.now() + timedelta(days=1, hours=9)).isoformat()},
        "end": {"dateTime": (datetime.now() + timedelta(days=1, hours=10)).isoformat()},
    },
]


# ============ Core API Functions ============

def _call_google_api(
    service: str,
    account: str = "projektil",
    params: Dict = None,
    method: str = "GET",
    body: Dict = None
) -> Dict[str, Any]:
    """
    Call the unified Google API gateway (or mock if MOCK_N8N=true).

    Args:
        service: Service name (calendar, gmail, chat)
        account: Account name (projektil, visualfox)
        params: Additional query parameters
        method: HTTP method (GET, POST)
        body: JSON body for POST requests

    Returns:
        Response data or error dict
    """
    # Return mock responses in test mode
    if MOCK_N8N:
        log_with_context(logger, "info", "Using mock n8n (MOCK_N8N=true)",
                        service=service, account=account, method=method)
        
        if service == "calendar" and method == "GET":
            return {"success": True, "events": MOCK_CALENDAR_EVENTS}
        elif service == "calendar" and method == "POST":
            return {
                "success": True,
                "event_id": f"mock_{datetime.now().timestamp()}",
                "message": "Mock event created"
            }
        elif service == "gmail" and method == "POST":
            return {
                "success": True,
                "message_id": f"mock_email_{datetime.now().timestamp()}",
                "message": "Mock email sent"
            }
        else:
            return {"success": True, "message": f"Mock {service} response"}
    
    # Real n8n API call
    url = f"{N8N_BASE_URL}/google"

    query_params = {
        "service": service,
        "account": account,
    }
    if params:
        query_params.update(params)

    try:
        log_with_context(logger, "debug", "Calling n8n Google API",
                        service=service, account=account, method=method)

        if method == "GET":
            resp = requests.get(url, params=query_params, timeout=N8N_TIMEOUT)
        else:
            resp = requests.post(url, params=query_params, json=body, timeout=N8N_TIMEOUT)

        resp.raise_for_status()
        result = resp.json()

        log_with_context(logger, "info", "n8n API call successful",
                        service=service, account=account)

        return result

    except requests.Timeout:
        log_with_context(logger, "error", "n8n API timeout",
                        service=service, account=account)
        return {"success": False, "error": "Timeout"}
    except requests.RequestException as e:
        log_with_context(logger, "error", "n8n API failed",
                        service=service, account=account, error=str(e))
        return {"success": False, "error": str(e)}
    except Exception as e:
        log_with_context(logger, "error", "n8n client error",
                        service=service, account=account, error=str(e))
        return {"success": False, "error": str(e)}


def _is_rate_limit_error(result: Dict[str, Any]) -> bool:
    """Check if the result indicates a rate limit error."""
    if not result.get("error"):
        return False
    error_str = str(result.get("error", "")).lower()
    return any(pattern in error_str for pattern in RATE_LIMIT_PATTERNS)


def _call_google_api_with_retry(
    service: str,
    account: str = "projektil",
    params: Dict = None,
    method: str = "GET",
    body: Dict = None,
    max_retries: int = RATE_LIMIT_MAX_RETRIES,
    initial_backoff: float = RATE_LIMIT_INITIAL_BACKOFF
) -> Dict[str, Any]:
    """
    Call Google API with exponential backoff on rate limits.

    Args:
        service: Service name (calendar, gmail, chat)
        account: Account name (projektil, visualfox)
        params: Additional query parameters
        method: HTTP method (GET, POST)
        body: JSON body for POST requests
        max_retries: Maximum retry attempts (default: 4)
        initial_backoff: Initial backoff in seconds (default: 1.0)

    Returns:
        Response data or error dict
    """
    backoff = initial_backoff
    last_result = None

    for attempt in range(max_retries + 1):
        result = _call_google_api(service, account, params, method, body)
        last_result = result

        # Check for rate limit error
        if _is_rate_limit_error(result):
            if attempt < max_retries:
                log_with_context(logger, "warning", "Rate limit hit, backing off",
                    service=service, account=account, attempt=attempt + 1,
                    backoff_seconds=backoff, max_retries=max_retries)
                _sleep(backoff)
                backoff *= 2  # Exponential: 1s, 2s, 4s, 8s
                continue
            else:
                log_with_context(logger, "error", "Rate limit exceeded after max retries",
                    service=service, account=account, attempts=max_retries + 1)

        # Success or non-rate-limit error
        return result

    return last_result


def _extract_data(response: Dict[str, Any]) -> Any:
    """Extract data from API response, handling various formats."""
    if isinstance(response, dict):
        if "data" in response:
            return response["data"]
        if "success" in response and response.get("success"):
            return response.get("data", response)
    return response


# ============ Calendar Functions ============

def get_calendar_events_projektil() -> List[Dict[str, Any]]:
    """Get calendar events from Projektil account."""
    result = _call_google_api("calendar", "projektil")
    data = _extract_data(result)

    # Handle single event vs list
    if isinstance(data, dict):
        events = [data] if data.get("id") else []
    elif isinstance(data, list):
        events = data
    else:
        events = []

    return _normalize_calendar_events(events, "projektil")


def get_calendar_events_visualfox() -> List[Dict[str, Any]]:
    """Get calendar events from Visualfox account."""
    result = _call_google_api("calendar", "visualfox")
    data = _extract_data(result)

    if isinstance(data, dict):
        events = [data] if data.get("id") else []
    elif isinstance(data, list):
        events = data
    else:
        events = []

    return _normalize_calendar_events(events, "visualfox")


def get_all_calendar_events() -> List[Dict[str, Any]]:
    """
    Get calendar events from all configured accounts.
    Events are sorted by start time.
    """
    all_events = []

    all_events.extend(get_calendar_events_projektil())
    all_events.extend(get_calendar_events_visualfox())

    all_events.sort(key=lambda e: e.get("start", ""))

    log_with_context(logger, "info", "Fetched all calendar events",
                    total=len(all_events))

    return all_events


def _normalize_calendar_events(events: List[Dict], account: str) -> List[Dict[str, Any]]:
    """Normalize Google Calendar events to a consistent format."""
    normalized = []

    for event in events:
        # Skip cancelled events
        if event.get("status") == "cancelled":
            continue

        start = event.get("start", {})
        end = event.get("end", {})

        start_str = start.get("dateTime", start.get("date", "")) if isinstance(start, dict) else str(start)
        end_str = end.get("dateTime", end.get("date", "")) if isinstance(end, dict) else str(end)
        is_all_day = isinstance(start, dict) and "date" in start and "dateTime" not in start

        normalized.append({
            "id": event.get("id", ""),
            "account": account,
            "summary": event.get("summary", "No title"),
            "description": event.get("description", ""),
            "location": event.get("location", ""),
            "start": start_str,
            "end": end_str,
            "all_day": is_all_day,
            "status": event.get("status", "confirmed"),
            "html_link": event.get("htmlLink", ""),
            "attendees": [
                a.get("email") for a in event.get("attendees", [])
                if isinstance(a, dict) and a.get("email")
            ][:5],
        })

    return normalized


def _parse_event_date(event: Dict) -> Optional[datetime]:
    """Parse the start date/datetime from an event."""
    start_str = event.get("start", "")
    if not start_str:
        return None

    try:
        if "T" in start_str:
            return datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        else:
            return datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _filter_events_by_timeframe(
    events: List[Dict[str, Any]],
    timeframe: str = "week"
) -> List[Dict[str, Any]]:
    """Filter events by timeframe."""
    if timeframe == "all":
        return events

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    if timeframe == "today":
        start_filter = today_start
        end_filter = today_end
    elif timeframe == "tomorrow":
        start_filter = today_end
        end_filter = today_end + timedelta(days=1)
    elif timeframe == "week":
        start_filter = today_start
        end_filter = today_start + timedelta(days=7)
    else:
        start_filter = today_start
        end_filter = today_start + timedelta(days=7)

    filtered = []
    for event in events:
        event_date = _parse_event_date(event)
        if event_date and start_filter <= event_date < end_filter:
            filtered.append(event)

    return filtered


def get_calendar_events(
    timeframe: str = "week",
    account: str = "all"
) -> List[Dict[str, Any]]:
    """
    Get calendar events with filtering options.

    Args:
        timeframe: One of "today", "tomorrow", "week", "all"
        account: One of "all", "visualfox", "projektil"

    Returns:
        Filtered and sorted list of events
    """
    events = []

    if account in ("all", "visualfox"):
        events.extend(get_calendar_events_visualfox())
    if account in ("all", "projektil"):
        events.extend(get_calendar_events_projektil())

    events.sort(key=lambda e: e.get("start", ""))
    filtered = _filter_events_by_timeframe(events, timeframe)

    log_with_context(logger, "info", "Fetched calendar events",
                    timeframe=timeframe, account=account,
                    total=len(events), filtered=len(filtered))

    return filtered


def get_today_events() -> List[Dict[str, Any]]:
    """Get today's events from all accounts."""
    return get_calendar_events(timeframe="today", account="all")


def get_tomorrow_events() -> List[Dict[str, Any]]:
    """Get tomorrow's events from all accounts."""
    return get_calendar_events(timeframe="tomorrow", account="all")


def get_week_events() -> List[Dict[str, Any]]:
    """Get this week's events from all accounts."""
    return get_calendar_events(timeframe="week", account="all")


def create_calendar_event(
    summary: str,
    start: str,
    end: str,
    account: str = "projektil",
    description: str = "",
    location: str = "",
    attendees: List[str] = None
) -> Dict[str, Any]:
    """
    Create a new calendar event via n8n.

    Args:
        summary: Event title
        start: Start time (ISO 8601 format, e.g., "2026-01-30T14:00:00+01:00")
        end: End time (ISO 8601 format)
        account: Calendar account ("projektil" or "visualfox")
        description: Optional event description
        location: Optional location
        attendees: Optional list of email addresses

    Returns:
        Dict with success status and created event data or error
    """
    if account not in ("projektil", "visualfox"):
        return {"success": False, "error": f"Invalid account: {account}"}

    body = {
        "summary": summary,
        "start": start,
        "end": end,
    }

    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = attendees

    result = _call_google_api("calendar", account, method="POST", body=body)

    if result.get("success"):
        log_with_context(logger, "info", "Calendar event created",
                        account=account, summary=summary)
    else:
        log_with_context(logger, "error", "Failed to create calendar event",
                        account=account, error=result.get("error"))

    return result


def format_events_for_briefing(events: List[Dict[str, Any]], include_date: bool = False) -> str:
    """Format events into a readable summary for briefings."""
    if not events:
        return "Keine Termine."

    lines = []
    current_date = None

    for event in events:
        start_str = event.get("start", "")
        event_date = _parse_event_date(event)

        if include_date and event_date:
            date_str = event_date.strftime("%a %d.%m")
            if date_str != current_date:
                current_date = date_str
                lines.append(f"\n**{date_str}:**")

        if not event.get("all_day", False) and start_str:
            try:
                dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                time_str = start_str
        else:
            time_str = "Ganztägig"

        account = event.get("account", "")
        account_label = f"[{account}] " if account else ""

        line = f"• {time_str}: {account_label}{event.get('summary', 'Kein Titel')}"

        location = event.get("location", "")
        if location:
            loc_short = location.split("\n")[0][:30]
            line += f" @ {loc_short}"

        lines.append(line)

    return "\n".join(lines)


# ============ Gmail Functions ============

def get_gmail_projektil(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent emails from Projektil Gmail account.

    Args:
        limit: Maximum number of emails to fetch

    Returns:
        List of email objects
    """
    result = _call_google_api("gmail", "projektil", params={"limit": limit})
    data = _extract_data(result)

    if isinstance(data, dict):
        emails = [data] if data.get("id") else []
    elif isinstance(data, list):
        emails = data
    else:
        emails = []

    return _normalize_emails(emails, "projektil")


def get_gmail_projektil_with_retry(
    limit: int = 10,
    max_retries: int = RATE_LIMIT_MAX_RETRIES,
    initial_backoff: float = RATE_LIMIT_INITIAL_BACKOFF
) -> Dict[str, Any]:
    """
    Get recent emails from Projektil Gmail with rate limit handling.

    Returns a dict with:
    - emails: List of email objects (on success)
    - rate_limited: True if rate limit was hit (even if recovered)
    - retries: Number of retries needed
    - error: Error message (on failure)

    Args:
        limit: Maximum number of emails to fetch
        max_retries: Maximum retry attempts
        initial_backoff: Initial backoff in seconds

    Returns:
        Dict with emails list and metadata
    """
    backoff = initial_backoff
    retries_used = 0

    for attempt in range(max_retries + 1):
        result = _call_google_api("gmail", "projektil", params={"limit": limit})

        # Check for rate limit
        if _is_rate_limit_error(result):
            retries_used = attempt + 1
            if attempt < max_retries:
                log_with_context(logger, "warning", "Gmail rate limit, backing off",
                    attempt=attempt + 1, backoff_seconds=backoff, limit=limit)
                _sleep(backoff)
                backoff *= 2
                continue
            else:
                log_with_context(logger, "error", "Gmail rate limit exceeded",
                    attempts=max_retries + 1, limit=limit)
                return {
                    "emails": [],
                    "rate_limited": True,
                    "retries": retries_used,
                    "error": str(result.get("error", "Rate limit exceeded")),
                    "exhausted": True
                }

        # Success or other error
        if result.get("success") == False:
            return {
                "emails": [],
                "rate_limited": False,
                "retries": retries_used,
                "error": str(result.get("error", "Unknown error"))
            }

        data = _extract_data(result)
        if isinstance(data, dict):
            emails = [data] if data.get("id") else []
        elif isinstance(data, list):
            emails = data
        else:
            emails = []

        normalized = _normalize_emails(emails, "projektil")

        return {
            "emails": normalized,
            "rate_limited": retries_used > 0,
            "retries": retries_used,
            "count": len(normalized)
        }

    # Should not reach here
    return {
        "emails": [],
        "rate_limited": True,
        "retries": max_retries,
        "error": "Unexpected retry loop exit"
    }


def _normalize_emails(emails: List[Dict], account: str) -> List[Dict[str, Any]]:
    """Normalize Gmail messages to a consistent format."""
    normalized = []

    for email in emails:
        # New unified API format - fields at top level
        normalized.append({
            "id": email.get("id", ""),
            "thread_id": email.get("threadId", ""),
            "account": account,
            "from": email.get("From", ""),
            "to": email.get("To", ""),
            "subject": email.get("Subject", "(Kein Betreff)"),
            "date": email.get("Date", ""),
            "snippet": email.get("snippet", ""),
            "labels": [l.get("name", l) if isinstance(l, dict) else l
                      for l in email.get("labels", email.get("labelIds", []))],
        })

    return normalized


def format_emails_for_briefing(emails: List[Dict[str, Any]], max_items: int = 5) -> str:
    """Format emails into a readable summary for briefings."""
    if not emails:
        return "Keine neuen E-Mails."

    lines = []
    for email in emails[:max_items]:
        sender = email.get("from", "")

        if sender and "<" in sender:
            sender = sender.split("<")[0].strip().strip('"')

        subject = email.get("subject", "")

        if not subject or subject == "(Kein Betreff)":
            snippet = email.get("snippet", "")
            subject = snippet[:50] + "..." if len(snippet) > 50 else snippet

        if len(subject) > 60:
            subject = subject[:57] + "..."

        if sender:
            lines.append(f"• {sender}: {subject}")
        else:
            lines.append(f"• {subject}")

    if len(emails) > max_items:
        lines.append(f"  ... und {len(emails) - max_items} weitere")

    return "\n".join(lines)


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = ""
) -> Dict[str, Any]:
    """
    Send an email via n8n (Projektil Gmail account).

    Note: Only Projektil has Gmail configured. Visualfox has no Gmail.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)

    Returns:
        Dict with success status and sent message data or error
    """
    email_body = {
        "to": to,
        "subject": subject,
        "body": body,
    }

    if cc:
        email_body["cc"] = cc
    if bcc:
        email_body["bcc"] = bcc

    result = _call_google_api("gmail", "projektil", method="POST", body=email_body)

    if result.get("success"):
        log_with_context(logger, "info", "Email sent",
                        to=to, subject=subject[:50])
    else:
        log_with_context(logger, "error", "Failed to send email",
                        to=to, error=result.get("error"))

    return result


# ============ Health Check ============

def is_n8n_available() -> bool:
    """Check if n8n is reachable."""
    try:
        resp = requests.get(f"http://{N8N_HOST}:{N8N_PORT}/healthz", timeout=5)
        return resp.status_code < 500
    except Exception:
        return False


def get_n8n_status() -> Dict[str, Any]:
    """Get n8n connection status."""
    available = is_n8n_available()

    return {
        "available": available,
        "base_url": N8N_BASE_URL,
        "architecture": "unified",
        "endpoint": "/webhook/google",
        "services": {
            "calendar": {
                "GET": "Read events (query: account)",
                "POST": "Create event (body: summary, start, end, ...)",
                "accounts": ["projektil", "visualfox"]
            },
            "gmail": {
                "GET": "Read emails (query: limit)",
                "POST": "Send email (body: to, subject, body, cc, bcc)",
                "accounts": ["projektil"]  # Visualfox has no Gmail!
            },
            "drive": {
                "POST": "Sync files from folder (body: folder_id, limit)",
                "accounts": ["projektil"]
            }
        },
        "accounts": {
            "projektil": ["calendar", "gmail", "drive"],
            "visualfox": ["calendar"]
        }
    }


# ============ Google Drive Functions ============

def trigger_drive_sync(
    folder_id: str = None,
    limit: int = 50,
    namespace: str = "work_projektil"
) -> Dict[str, Any]:
    """
    Trigger Google Drive sync via n8n webhook.

    This calls the jarvis_drive_sync workflow which:
    1. Lists files in the specified folder
    2. Downloads/exports content
    3. POSTs each file to Jarvis /ingest/drive

    Args:
        folder_id: Optional folder ID to sync (None = root/all accessible)
        limit: Maximum files to process
        namespace: Target namespace for ingestion

    Returns:
        Sync result with processed files count
    """
    url = f"{N8N_BASE_URL}/drive-sync"

    body = {
        "folder_id": folder_id,
        "limit": limit,
        "namespace": namespace
    }

    try:
        log_with_context(logger, "info", "Triggering Drive sync via n8n",
                        folder_id=folder_id, limit=limit)

        resp = requests.post(url, json=body, timeout=120)  # Longer timeout for file processing
        resp.raise_for_status()
        result = resp.json()

        log_with_context(logger, "info", "Drive sync completed",
                        total=result.get("total", 0),
                        successful=result.get("successful", 0))

        return result

    except requests.Timeout:
        log_with_context(logger, "error", "Drive sync timeout")
        return {"success": False, "error": "Timeout - sync may still be running"}
    except requests.RequestException as e:
        log_with_context(logger, "error", "Drive sync failed", error=str(e))
        return {"success": False, "error": str(e)}


def list_drive_folders() -> List[Dict[str, Any]]:
    """
    List available Google Drive folders via n8n.

    Returns list of folder metadata for sync configuration.
    """
    # This would need a separate n8n workflow endpoint
    # For now, return a placeholder
    return [
        {"info": "Use Google Drive UI to get folder IDs"},
        {"hint": "Folder ID is in the URL: drive.google.com/drive/folders/FOLDER_ID"}
    ]


def get_drive_sync_status() -> Dict[str, Any]:
    """Get status of Drive sync capability."""
    return {
        "available": is_n8n_available(),
        "endpoint": f"{N8N_BASE_URL}/drive-sync",
        "capabilities": {
            "sync_folder": "POST with folder_id",
            "sync_all": "POST without folder_id",
            "supported_types": ["Google Docs", "Sheets", "Slides", "PDF", "TXT", "MD"]
        },
        "usage": {
            "trigger": "POST /n8n/drive/sync",
            "list_ingested": "GET /drive/documents",
            "search": "GET /drive/search?query=..."
        }
    }
