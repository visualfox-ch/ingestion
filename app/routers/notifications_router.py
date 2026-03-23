"""Notification and scheduler endpoints (Telegram + briefing)."""
from __future__ import annotations

from typing import List, Dict, Any

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..observability import get_logger

logger = get_logger("jarvis.notifications")
router = APIRouter()


@router.post("/scheduler/briefing")
def trigger_briefing():
    """Manually trigger a briefing (for testing)"""
    from ..scheduler import trigger_briefing_now
    trigger_briefing_now()
    return {"status": "triggered"}


@router.get("/scheduler/status")
def scheduler_status():
    """Get scheduler status including next briefing time"""
    from ..scheduler import get_scheduler_status
    return get_scheduler_status()


class TelegramAlertRequest(BaseModel):
    message: str
    level: str = "info"
    buttons: list | None = None  # Optional inline keyboard buttons
    chat_id: str | int | None = None
    thread_id: str | int | None = None


@router.post("/telegram/send_alert")
def send_telegram_alert(req: TelegramAlertRequest):
    """
    Send an alert message to Telegram.
    Used by n8n workflows for proactive notifications.
    """
    from ..telegram_bot import send_alert
    success = send_alert(
        req.message,
        level=req.level,
        buttons=req.buttons,
        chat_id=req.chat_id,
        thread_id=req.thread_id,
    )
    return {"success": success, "level": req.level}


class VipEmailAlertRequest(BaseModel):
    sender: str
    subject: str
    snippet: str
    email_id: str
    person_context: str | None = None


@router.post("/telegram/vip_email_alert")
def send_vip_email_telegram_alert(req: VipEmailAlertRequest):
    """
    Send a VIP email alert with quick-action buttons.
    Used by realtime monitor for VIP email detection.
    """
    from ..telegram_bot import send_vip_email_alert
    success = send_vip_email_alert(
        sender=req.sender,
        subject=req.subject,
        snippet=req.snippet,
        email_id=req.email_id,
        person_context=req.person_context
    )
    return {"success": success, "type": "vip_email"}


class FollowupReminderRequest(BaseModel):
    followup_id: str
    subject: str
    source_from: str | None = None
    priority: str = "normal"
    is_overdue: bool = False


@router.post("/telegram/followup_reminder")
def send_followup_telegram_reminder(req: FollowupReminderRequest):
    """
    Send a follow-up reminder with action buttons.
    Used by proactive layer for follow-up reminders.
    """
    from ..telegram_bot import send_followup_reminder
    success = send_followup_reminder(
        followup_id=req.followup_id,
        subject=req.subject,
        source_from=req.source_from,
        priority=req.priority,
        is_overdue=req.is_overdue
    )
    return {"success": success, "type": "followup_reminder"}


class TelegramSendRequest(BaseModel):
    message: str
    user_id: int | None = None  # None = broadcast to all
    chat_id: str | int | None = None
    thread_id: str | int | None = None
    parse_mode: str = "Markdown"
    buttons: list[list[dict]] | None = None
    silent: bool = False


@router.post("/telegram/send")
def send_telegram_message(req: TelegramSendRequest):
    """
    Send a message via Telegram to specific user or all users.
    """
    from ..telegram_bot import TELEGRAM_TOKEN, ALLOWED_USER_IDS

    if not TELEGRAM_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    if not ALLOWED_USER_IDS and not req.user_id and not req.chat_id:
        raise HTTPException(status_code=400, detail="No recipients configured")

    if req.thread_id is not None and req.chat_id is None:
        raise HTTPException(status_code=400, detail="thread_id requires explicit chat_id")

    recipients = [str(req.chat_id)] if req.chat_id is not None else [str(req.user_id)] if req.user_id else ALLOWED_USER_IDS

    if req.user_id and req.chat_id is None and str(req.user_id) not in ALLOWED_USER_IDS:
        raise HTTPException(status_code=403, detail="User not in allowed list")

    results = []
    for recipient in recipients:
        try:
            payload = {
                "chat_id": recipient,
                "text": req.message,
                "parse_mode": req.parse_mode,
                "disable_notification": req.silent
            }

            if req.thread_id is not None:
                payload["message_thread_id"] = int(req.thread_id)

            if req.buttons:
                payload["reply_markup"] = {"inline_keyboard": req.buttons}

            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json=payload,
                timeout=10
            )

            success = response.status_code == 200
            message_id = None
            if success:
                result_data = response.json().get("result", {})
                message_id = result_data.get("message_id")

            results.append({
                "user_id": recipient,
                "success": success,
                "message_id": message_id,
                "error": None if success else response.text[:100]
            })
        except Exception as e:
            results.append({
                "user_id": recipient,
                "success": False,
                "message_id": None,
                "error": str(e)[:100]
            })

    success_count = len([r for r in results if r["success"]])

    return {
        "sent_to": success_count,
        "failed": len(results) - success_count,
        "total_recipients": len(recipients),
        "broadcast": req.user_id is None and req.chat_id is None,
        "details": results
    }
