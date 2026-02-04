"""
Jarvis Scheduler
Handles scheduled tasks like daily briefings.
"""
import os
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.scheduler")

# Global scheduler instance
_scheduler: Optional[BackgroundScheduler] = None

# Default briefing time (8:00 AM)
BRIEFING_HOUR = int(os.environ.get("JARVIS_BRIEFING_HOUR", "8"))
BRIEFING_MINUTE = int(os.environ.get("JARVIS_BRIEFING_MINUTE", "0"))

# Workflow monitor interval (seconds)
WORKFLOW_MONITOR_INTERVAL_SECONDS = int(
    os.environ.get("JARVIS_WORKFLOW_MONITOR_INTERVAL_SECONDS", "300")
)

# Nightly RAG regression schedule (hour/minute)
RAG_REGRESSION_ENABLED = os.environ.get("JARVIS_RAG_REGRESSION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
RAG_REGRESSION_HOUR = int(os.environ.get("JARVIS_RAG_REGRESSION_HOUR", "2"))
RAG_REGRESSION_MINUTE = int(os.environ.get("JARVIS_RAG_REGRESSION_MINUTE", "30"))

# Timezone (from environment or default)
TIMEZONE = os.environ.get("TZ", "Europe/Zurich")


def send_telegram_briefing():
    """Send daily briefing to all registered Telegram users"""
    from . import state_db
    from . import agent
    from . import n8n_client

    log_with_context(logger, "info", "Starting scheduled daily briefing")

    try:
        import requests

        # Get all telegram users
        users = state_db.get_all_telegram_users()

        if not users:
            log_with_context(logger, "info", "No Telegram users registered for briefing")
            return

        for user in users:
            user_id = user["user_id"]
            namespace = user["namespace"] or "work_projektil"

            log_with_context(logger, "info", "Sending briefing to user",
                           user_id=user_id, namespace=namespace)

            try:
                # Get calendar events via n8n
                calendar_context = ""
                email_context = ""

                try:
                    events = n8n_client.get_today_events()
                    if events:
                        calendar_context = f"\n\n**Termine heute:**\n{n8n_client.format_events_for_briefing(events)}"
                except Exception as e:
                    log_with_context(logger, "warning", "Calendar fetch failed", error=str(e))

                # Get recent emails via n8n
                try:
                    emails = n8n_client.get_gmail_projektil(limit=5)
                    if emails:
                        email_context = f"\n\n**Neue E-Mails:**\n{n8n_client.format_emails_for_briefing(emails)}"
                except Exception as e:
                    log_with_context(logger, "warning", "Email fetch failed", error=str(e))

                # Generate briefing
                result = agent.get_daily_briefing(namespace=namespace, days=1)

                if "error" in result:
                    log_with_context(logger, "error", "Briefing generation failed",
                                   user_id=user_id, error=result["error"])
                    continue

                answer = result.get("answer", "No briefing available")

                # Build full briefing
                full_briefing = f"📅 **Daily Briefing**\n\n{answer}"
                if calendar_context:
                    full_briefing += calendar_context
                if email_context:
                    full_briefing += email_context

                # Send via Telegram
                _send_telegram_message(user_id, full_briefing)

                log_with_context(logger, "info", "Briefing sent successfully",
                               user_id=user_id)

            except Exception as e:
                log_with_context(logger, "error", "Failed to send briefing to user",
                               user_id=user_id, error=str(e))

    except Exception as e:
        log_with_context(logger, "error", "Scheduled briefing failed", error=str(e))


def run_rag_regression_job():
    """Run nightly RAG regression check."""
    if not RAG_REGRESSION_ENABLED:
        log_with_context(logger, "info", "RAG regression disabled")
        return
    try:
        from .rag_regression import run_rag_regression
        run_rag_regression()
    except Exception as e:
        log_with_context(logger, "error", "RAG regression failed", error=str(e))


def _send_telegram_message(chat_id: int, text: str):
    """Send a message via Telegram Bot API"""
    from .telegram_bot import TELEGRAM_TOKEN

    if not TELEGRAM_TOKEN:
        log_with_context(logger, "warning", "Cannot send Telegram message: no token")
        return

    import requests

    # Telegram message limit
    if len(text) > 4000:
        text = text[:3997] + "..."

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log_with_context(logger, "error", "Telegram send failed",
                        chat_id=chat_id, error=str(e))
        raise


def start_scheduler() -> bool:
    """Start the background scheduler"""
    global _scheduler

    if _scheduler and _scheduler.running:
        log_with_context(logger, "info", "Scheduler already running")
        return True

    try:
        _scheduler = BackgroundScheduler(timezone=TIMEZONE)

        # Schedule daily briefing
        _scheduler.add_job(
            send_telegram_briefing,
            CronTrigger(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE),
            id="daily_briefing",
            name="Daily Briefing",
            replace_existing=True
        )

        # Schedule workflow monitoring
        from .jobs.workflow_monitor import run_workflow_monitor
        _scheduler.add_job(
            run_workflow_monitor,
            IntervalTrigger(seconds=WORKFLOW_MONITOR_INTERVAL_SECONDS),
            id="workflow_monitor",
            name="Workflow Monitor",
            replace_existing=True
        )

        # Schedule nightly RAG regression
        _scheduler.add_job(
            run_rag_regression_job,
            CronTrigger(hour=RAG_REGRESSION_HOUR, minute=RAG_REGRESSION_MINUTE),
            id="rag_regression",
            name="RAG Regression",
            replace_existing=True
        )

        # Schedule monthly review (day 31 at 03:00 UTC)
        from .jobs.monthly_review_job import run_monthly_review_job
        _scheduler.add_job(
            run_monthly_review_job,
            CronTrigger(day=31, hour=3, minute=0),  # Day 31 of month at 03:00 UTC
            id="monthly_review",
            name="Monthly Review (Self-Optimization)",
            replace_existing=True
        )

        _scheduler.start()
        log_with_context(logger, "info", "Scheduler started",
                briefing_time=f"{BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d}",
                workflow_monitor_interval_seconds=WORKFLOW_MONITOR_INTERVAL_SECONDS,
                rag_regression_time=f"{RAG_REGRESSION_HOUR:02d}:{RAG_REGRESSION_MINUTE:02d}",
                monthly_review_schedule="Day 31 at 03:00 UTC",
                timezone=TIMEZONE)
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to start scheduler", error=str(e))
        return False


def stop_scheduler():
    """Stop the scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        log_with_context(logger, "info", "Scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if scheduler is running"""
    return _scheduler is not None and _scheduler.running


def get_next_briefing_time() -> Optional[str]:
    """Get next scheduled briefing time"""
    if not _scheduler:
        return None

    job = _scheduler.get_job("daily_briefing")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def get_scheduler_status() -> dict:
    """Get comprehensive scheduler status for health checks"""
    running = is_scheduler_running()
    next_briefing = get_next_briefing_time()
    workflow_job = _scheduler.get_job("workflow_monitor") if _scheduler else None
    next_workflow_monitor = workflow_job.next_run_time.isoformat() if workflow_job and workflow_job.next_run_time else None

    status = {
        "status": "healthy" if running else "stopped",
        "running": running,
        "briefing_time": f"{BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d}",
        "next_briefing": next_briefing,
        "workflow_monitor_interval_seconds": WORKFLOW_MONITOR_INTERVAL_SECONDS,
        "next_workflow_monitor": next_workflow_monitor,
        "timezone": str(TIMEZONE)
    }

    if _scheduler:
        jobs = _scheduler.get_jobs()
        status["job_count"] = len(jobs)

    return status


def trigger_briefing_now():
    """Manually trigger a briefing (for testing)"""
    log_with_context(logger, "info", "Manual briefing trigger")
    send_telegram_briefing()
