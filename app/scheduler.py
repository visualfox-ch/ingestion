"""
Jarvis Scheduler
Handles scheduled tasks like daily briefings.
"""
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any

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

# Phase 2 gate evaluation schedule (hour/minute)
PHASE2_GATE_ENABLED = os.environ.get("JARVIS_PHASE2_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PHASE2_GATE_HOUR = int(os.environ.get("JARVIS_PHASE2_GATE_HOUR", "6"))  # 06:00 UTC daily
PHASE2_GATE_MINUTE = int(os.environ.get("JARVIS_PHASE2_GATE_MINUTE", "0"))

# Self-diagnostics schedule (Phase 19 - every 6 hours)
SELF_DIAGNOSTICS_ENABLED = os.environ.get("JARVIS_SELF_DIAGNOSTICS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SELF_DIAGNOSTICS_INTERVAL_HOURS = int(os.environ.get("JARVIS_SELF_DIAGNOSTICS_INTERVAL_HOURS", "6"))

# Autonomous research schedule (Phase 2B - daily)
AUTO_RESEARCH_ENABLED = os.environ.get("JARVIS_AUTO_RESEARCH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AUTO_RESEARCH_HOUR = int(os.environ.get("JARVIS_AUTO_RESEARCH_HOUR", "18"))
AUTO_RESEARCH_MINUTE = int(os.environ.get("JARVIS_AUTO_RESEARCH_MINUTE", "0"))
AUTO_RESEARCH_MAX_TOPICS = int(os.environ.get("JARVIS_AUTO_RESEARCH_MAX_TOPICS", "3"))

# Batch API queue processing (Tier 4 #13 - 50% cost savings)
BATCH_QUEUE_ENABLED = os.environ.get("JARVIS_BATCH_QUEUE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
BATCH_QUEUE_INTERVAL_MINUTES = int(os.environ.get("JARVIS_BATCH_QUEUE_INTERVAL_MINUTES", "30"))
BATCH_QUEUE_MIN_TASKS = int(os.environ.get("JARVIS_BATCH_QUEUE_MIN_TASKS", "5"))

# ML Pattern Analysis (Tier 4 #14 - Predictive Intelligence)
ML_PATTERN_ENABLED = os.environ.get("JARVIS_ML_PATTERN_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ML_PATTERN_INTERVAL_HOURS = int(os.environ.get("JARVIS_ML_PATTERN_INTERVAL_HOURS", "6"))

# Auto-Refactoring Analysis (Tier 4 #15 - Code Quality)
AUTO_REFACTOR_ENABLED = os.environ.get("JARVIS_AUTO_REFACTOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AUTO_REFACTOR_HOUR = int(os.environ.get("JARVIS_AUTO_REFACTOR_HOUR", "3"))  # 03:00 daily

# Maintenance Jobs (Tool Activation Strategy)
MEMORY_DECAY_ENABLED = os.environ.get("JARVIS_MEMORY_DECAY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MEMORY_DECAY_HOUR = int(os.environ.get("JARVIS_MEMORY_DECAY_HOUR", "3"))  # 03:00 daily

DUPLICATE_CLEANUP_ENABLED = os.environ.get("JARVIS_DUPLICATE_CLEANUP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DUPLICATE_CLEANUP_DAY = os.environ.get("JARVIS_DUPLICATE_CLEANUP_DAY", "sun")  # Sunday
DUPLICATE_CLEANUP_HOUR = int(os.environ.get("JARVIS_DUPLICATE_CLEANUP_HOUR", "4"))  # 04:00

ANOMALY_ANALYSIS_ENABLED = os.environ.get("JARVIS_ANOMALY_ANALYSIS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ANOMALY_ANALYSIS_INTERVAL_HOURS = int(os.environ.get("JARVIS_ANOMALY_ANALYSIS_INTERVAL_HOURS", "2"))  # Every 2h

USAGE_ANOMALY_ENABLED = os.environ.get("JARVIS_USAGE_ANOMALY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
USAGE_ANOMALY_HOUR = int(os.environ.get("JARVIS_USAGE_ANOMALY_HOUR", "6"))  # 06:00 daily

WEEKLY_TOOL_REPORT_ENABLED = os.environ.get("JARVIS_WEEKLY_TOOL_REPORT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
WEEKLY_TOOL_REPORT_DAY = os.environ.get("JARVIS_WEEKLY_TOOL_REPORT_DAY", "sun")  # Sunday
WEEKLY_TOOL_REPORT_HOUR = int(os.environ.get("JARVIS_WEEKLY_TOOL_REPORT_HOUR", "10"))  # 10:00

SELF_OPTIMIZATION_ENABLED = os.environ.get("JARVIS_SELF_OPTIMIZATION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SELF_OPTIMIZATION_DAY = os.environ.get("JARVIS_SELF_OPTIMIZATION_DAY", "mon")  # Monday
SELF_OPTIMIZATION_HOUR = int(os.environ.get("JARVIS_SELF_OPTIMIZATION_HOUR", "9"))  # 09:00

# Alias auto-sunset check (weekly Sunday, 30-day idle window)
ALIAS_SUNSET_CHECK_ENABLED = os.environ.get("JARVIS_ALIAS_SUNSET_CHECK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ALIAS_SUNSET_CHECK_HOUR = int(os.environ.get("JARVIS_ALIAS_SUNSET_CHECK_HOUR", "5"))  # 05:00 Sunday

# Phase 22E PoC: pre-meeting proactive suggestions (parallel-safe with T-22A)
PRE_MEETING_PUSH_ENABLED = os.environ.get("JARVIS_PRE_MEETING_PUSH_ENABLED", "false").lower() in ("1", "true", "yes", "on")
PRE_MEETING_LOOKAHEAD_MINUTES = int(os.environ.get("JARVIS_PRE_MEETING_LOOKAHEAD_MINUTES", "30"))
PRE_MEETING_CHECK_INTERVAL_MINUTES = int(os.environ.get("JARVIS_PRE_MEETING_CHECK_INTERVAL_MINUTES", "5"))
PRE_MEETING_CONTEXT_LIMIT = int(os.environ.get("JARVIS_PRE_MEETING_CONTEXT_LIMIT", "2"))
PRE_MEETING_STATE_PATH = os.environ.get(
    "JARVIS_PRE_MEETING_STATE_PATH",
    "/brain/system/data/scheduler/pre_meeting_sent.json",
)

# Timezone (from environment or default)
TIMEZONE = os.environ.get("TZ", "Europe/Zurich")


def _parse_event_start(start_raw: str) -> Optional[datetime]:
    """Parse ISO datetime/date from normalized calendar event start field."""
    if not start_raw:
        return None

    try:
        if "T" in start_raw:
            dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(start_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _load_pre_meeting_state() -> Dict[str, float]:
    """Load dedup state map for already sent pre-meeting notifications."""
    path = Path(PRE_MEETING_STATE_PATH)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sent = payload.get("sent", {}) if isinstance(payload, dict) else {}
        if isinstance(sent, dict):
            return {str(k): float(v) for k, v in sent.items()}
    except Exception as e:
        log_with_context(logger, "warning", "Failed to load pre-meeting state", error=str(e))
    return {}


def _save_pre_meeting_state(sent: Dict[str, float]) -> None:
    """Persist dedup state for pre-meeting notifications."""
    path = Path(PRE_MEETING_STATE_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sent": sent}, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    except Exception as e:
        log_with_context(logger, "warning", "Failed to persist pre-meeting state", error=str(e))


def _prune_pre_meeting_state(sent: Dict[str, float], now_ts: float) -> Dict[str, float]:
    """Drop old dedup entries to keep state compact."""
    keep_after = now_ts - (2 * 24 * 60 * 60)
    return {k: ts for k, ts in sent.items() if ts >= keep_after}


def _build_pre_meeting_key(user_id: int, event: Dict[str, Any], start_dt: datetime) -> str:
    """Stable dedup key for one user + one calendar event start."""
    event_id = event.get("id") or ""
    summary = (event.get("summary") or "").strip()
    account = event.get("account") or "unknown"
    return f"{user_id}:{account}:{event_id}:{summary}:{start_dt.isoformat()}"


def _fetch_pre_meeting_context_lines(event: Dict[str, Any], namespace: str) -> list[str]:
    """Fetch concise context snippets from Qdrant-backed search for the upcoming meeting."""
    query_parts = [event.get("summary", "")]
    if event.get("location"):
        query_parts.append(event.get("location", ""))
    attendees = event.get("attendees") or []
    if attendees:
        query_parts.append(" ".join(attendees[:2]))
    query = " ".join(p for p in query_parts if p).strip()
    if not query:
        return []

    try:
        from .tools import tool_search_knowledge

        result = tool_search_knowledge(
            query=query,
            namespace=namespace,
            limit=max(1, PRE_MEETING_CONTEXT_LIMIT),
            recency_days=60,
        )
        lines = []
        for item in result.get("results", [])[:PRE_MEETING_CONTEXT_LIMIT]:
            text = (item.get("text") or "").replace("\n", " ").strip()
            source = item.get("source_path") or item.get("label") or "context"
            if text:
                lines.append(f"- {source}: {text[:140]}")
        return lines
    except Exception as e:
        log_with_context(logger, "warning", "Pre-meeting context lookup failed", error=str(e))
        return []


def _format_pre_meeting_message(event: Dict[str, Any], start_dt: datetime, minutes_left: int, context_lines: list[str]) -> str:
    """Render Telegram-friendly pre-meeting suggestion text."""
    def _escape_md(text: str) -> str:
        # Telegram Markdown mode is sensitive to a small set of characters
        # that frequently appear in file paths and context snippets.
        return (
            text.replace("\\", "\\\\")
            .replace("_", "\\_")
            .replace("*", "\\*")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )

    account = _escape_md(event.get("account", ""))
    account_prefix = f"[{account}] " if account else ""
    summary = _escape_md(event.get("summary", "Termin"))
    location = _escape_md(event.get("location", ""))
    location_line = f"\nOrt: {location}" if location else ""
    start_local = start_dt.astimezone()
    when_line = start_local.strftime("%d.%m.%Y %H:%M")

    message = (
        f"📌 *Meeting-Hinweis* ({minutes_left} min)\n"
        f"{account_prefix}*{summary}*\n"
        f"Start: {when_line}{location_line}"
    )
    if context_lines:
        escaped_context = [_escape_md(line) for line in context_lines]
        message += "\n\n*Relevanter Kontext:*\n" + "\n".join(escaped_context)
    message += "\n\nVorschlag: Soll ich dir eine kurze Vorbereitung oder Follow-up-Notiz erstellen?"
    return message


def _get_pre_meeting_dependencies():
    """Import dependencies in one place so tests can stub them cleanly."""
    from . import state_db
    from . import n8n_client

    return state_db, n8n_client


def send_pre_meeting_suggestions() -> None:
    """Phase 22E PoC: proactively notify users about meetings starting soon."""
    if not PRE_MEETING_PUSH_ENABLED:
        return

    try:
        state_db, n8n_client = _get_pre_meeting_dependencies()
        users = state_db.get_all_telegram_users()
        if not users:
            return

        events = n8n_client.get_calendar_events(timeframe="today", account="all")
        now_utc = datetime.now(timezone.utc)
        state = _prune_pre_meeting_state(_load_pre_meeting_state(), now_utc.timestamp())
        sent_count = 0

        for user in users:
            user_id = user.get("user_id")
            if user_id is None:
                continue
            namespace = user.get("namespace") or "work_projektil"

            for event in events:
                if event.get("all_day"):
                    continue
                start_dt = _parse_event_start(event.get("start", ""))
                if not start_dt:
                    continue

                minutes_left = int((start_dt - now_utc).total_seconds() // 60)
                if minutes_left < 0 or minutes_left > PRE_MEETING_LOOKAHEAD_MINUTES:
                    continue

                dedup_key = _build_pre_meeting_key(user_id, event, start_dt)
                if dedup_key in state:
                    continue

                context_lines = _fetch_pre_meeting_context_lines(event, namespace)
                message = _format_pre_meeting_message(event, start_dt, minutes_left, context_lines)
                _send_telegram_message(user_id, message)
                state[dedup_key] = now_utc.timestamp()
                sent_count += 1

        if sent_count:
            _save_pre_meeting_state(state)
            log_with_context(
                logger,
                "info",
                "Pre-meeting suggestions sent",
                count=sent_count,
                lookahead_minutes=PRE_MEETING_LOOKAHEAD_MINUTES,
            )
    except Exception as e:
        log_with_context(logger, "error", "Pre-meeting suggestion job failed", error=str(e))


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


def run_learning_decay():
    """
    Phase 19.5: Run learning decay and migration.
    Called daily to decay old facts and migrate mature ones.
    """
    log_with_context(logger, "info", "Starting learning decay job")
    try:
        from .services.auto_learner import decay_old_facts, migrate_to_main_facts

        # Decay old facts
        decay_result = decay_old_facts(days_threshold=14, decay_rate=0.05)
        log_with_context(logger, "info", "Learning decay completed",
                        decayed=decay_result.get("decayed", 0),
                        deleted=decay_result.get("deleted", 0))

        # Migrate high-confidence facts
        migrate_result = migrate_to_main_facts(min_confidence=0.8)
        log_with_context(logger, "info", "Learning migration completed",
                        migrated=migrate_result.get("migrated", 0),
                        skipped=migrate_result.get("skipped", 0))

    except Exception as e:
        log_with_context(logger, "error", "Learning decay job failed", error=str(e))


def run_batch_queue_processing():
    """
    Tier 4 #13: Process batch queues for 50% cost savings.
    Called periodically to batch queued tasks together.
    """
    log_with_context(logger, "info", "Starting batch queue processing")
    try:
        from .services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        # Get queue status
        queue_status = processor.get_queue_status()
        if not queue_status.get("success"):
            log_with_context(logger, "warning", "Failed to get queue status")
            return

        queue_summary = queue_status.get("queue_summary", {})
        total_processed = 0

        # Process each task type that has enough queued items
        for task_type, statuses in queue_summary.items():
            queued_info = statuses.get("queued", {})
            count = queued_info.get("count", 0)

            if count >= BATCH_QUEUE_MIN_TASKS:
                log_with_context(logger, "info", f"Processing batch queue",
                               task_type=task_type, count=count)

                result = processor.process_queue(task_type)
                if result.get("success"):
                    total_processed += result.get("task_count", 0)
                    log_with_context(logger, "info", "Batch submitted",
                                   task_type=task_type,
                                   job_id=result.get("job_id"),
                                   count=result.get("task_count"))
                else:
                    log_with_context(logger, "warning", "Batch processing failed",
                                   task_type=task_type, error=result.get("error"))

        if total_processed > 0:
            log_with_context(logger, "info", "Batch queue processing completed",
                           total_processed=total_processed,
                           estimated_savings="50% vs sync")

    except Exception as e:
        log_with_context(logger, "error", "Batch queue processing failed", error=str(e))


def run_ml_pattern_analysis():
    """
    Tier 4 #14: Run ML pattern analysis for predictive alerts.
    Called periodically to analyze metrics and generate alerts.
    """
    log_with_context(logger, "info", "Starting ML pattern analysis")
    try:
        from .services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        # Generate predictive alerts for standard metrics
        alerts_result = service.generate_predictive_alerts()
        if alerts_result.get("success"):
            alert_count = alerts_result.get("alerts_generated", 0)
            if alert_count > 0:
                log_with_context(logger, "info", "ML pattern alerts generated",
                               alert_count=alert_count)

        # Run seasonal decomposition on key metrics
        key_metrics = ["queries_per_hour", "tool_calls_per_hour", "response_latency_p95"]
        patterns_detected = 0

        for metric in key_metrics:
            result = service.decompose_seasonal(metric)
            if result.get("success"):
                patterns = result.get("patterns_detected", [])
                patterns_detected += len(patterns)

        log_with_context(logger, "info", "ML pattern analysis completed",
                        alerts=alerts_result.get("alerts_generated", 0),
                        patterns=patterns_detected)

    except Exception as e:
        log_with_context(logger, "error", "ML pattern analysis failed", error=str(e))


def run_auto_refactor_analysis():
    """
    Tier 4 #15: Run automated code quality analysis.
    Called daily to analyze codebase and generate refactoring suggestions.
    """
    log_with_context(logger, "info", "Starting auto-refactor analysis")
    try:
        from .services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        # Analyze codebase
        result = service.analyze_codebase()
        if result.get("success"):
            log_with_context(logger, "info", "Code analysis completed",
                           files=result.get("files_analyzed", 0),
                           issues=result.get("issues_found", 0))

            # Generate suggestions
            suggestions = service.generate_suggestions(max_suggestions=10)
            if suggestions.get("success"):
                log_with_context(logger, "info", "Refactoring suggestions generated",
                               count=suggestions.get("suggestions_generated", 0))
        else:
            log_with_context(logger, "warning", "Code analysis failed",
                           error=result.get("error"))

    except Exception as e:
        log_with_context(logger, "error", "Auto-refactor analysis failed", error=str(e))


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

        # Schedule Phase 2 gate evaluation (daily during validation window)
        if PHASE2_GATE_ENABLED:
            from .jobs.phase2_gate_job import run_phase2_gate_evaluation
            _scheduler.add_job(
                run_phase2_gate_evaluation,
                CronTrigger(hour=PHASE2_GATE_HOUR, minute=PHASE2_GATE_MINUTE),
                id="phase2_gate_evaluation",
                name="Phase 2 Gate Evaluation",
                replace_existing=True
            )

        # Schedule self-diagnostics (every 6 hours)
        if SELF_DIAGNOSTICS_ENABLED:
            from .jobs.self_diagnostics import run_self_diagnostics
            _scheduler.add_job(
                run_self_diagnostics,
                IntervalTrigger(hours=SELF_DIAGNOSTICS_INTERVAL_HOURS),
                id="self_diagnostics",
                name="Self-Diagnostics",
                replace_existing=True
            )

        # Schedule learning decay (daily at 04:00)
        _scheduler.add_job(
            run_learning_decay,
            CronTrigger(hour=4, minute=0),
            id="learning_decay",
            name="Learning Decay",
            replace_existing=True
        )

        # Phase 22E PoC: pre-meeting proactive suggestions
        if PRE_MEETING_PUSH_ENABLED:
            _scheduler.add_job(
                send_pre_meeting_suggestions,
                IntervalTrigger(minutes=PRE_MEETING_CHECK_INTERVAL_MINUTES),
                id="pre_meeting_suggestions",
                name="Pre-Meeting Suggestions",
                replace_existing=True,
            )

        # Schedule autonomous research (daily)
        if AUTO_RESEARCH_ENABLED:
            from .jobs.autonomous_research_job import run_autonomous_research_job
            _scheduler.add_job(
                run_autonomous_research_job,
                CronTrigger(hour=AUTO_RESEARCH_HOUR, minute=AUTO_RESEARCH_MINUTE),
                id="autonomous_research",
                name="Autonomous Research",
                replace_existing=True
            )

        # Schedule batch queue processing (Tier 4 #13 - 50% cost savings)
        if BATCH_QUEUE_ENABLED:
            _scheduler.add_job(
                run_batch_queue_processing,
                IntervalTrigger(minutes=BATCH_QUEUE_INTERVAL_MINUTES),
                id="batch_queue_processing",
                name="Batch Queue Processing",
                replace_existing=True
            )

        # Schedule ML pattern analysis (Tier 4 #14 - Predictive Intelligence)
        if ML_PATTERN_ENABLED:
            _scheduler.add_job(
                run_ml_pattern_analysis,
                IntervalTrigger(hours=ML_PATTERN_INTERVAL_HOURS),
                id="ml_pattern_analysis",
                name="ML Pattern Analysis",
                replace_existing=True
            )

        # Schedule auto-refactor analysis (Tier 4 #15 - Code Quality)
        if AUTO_REFACTOR_ENABLED:
            _scheduler.add_job(
                run_auto_refactor_analysis,
                CronTrigger(hour=AUTO_REFACTOR_HOUR, minute=0),
                id="auto_refactor_analysis",
                name="Auto-Refactor Analysis",
                replace_existing=True
            )

        # ===== Maintenance Jobs (Tool Activation Strategy) =====

        # Schedule memory decay (daily at 03:00)
        if MEMORY_DECAY_ENABLED:
            from .jobs.maintenance_jobs import run_memory_decay_job
            _scheduler.add_job(
                run_memory_decay_job,
                CronTrigger(hour=MEMORY_DECAY_HOUR, minute=0),
                id="memory_decay",
                name="Memory Decay",
                replace_existing=True
            )

        # Schedule duplicate cleanup (weekly Sunday at 04:00)
        if DUPLICATE_CLEANUP_ENABLED:
            from .jobs.maintenance_jobs import run_duplicate_cleanup_job
            _scheduler.add_job(
                run_duplicate_cleanup_job,
                CronTrigger(day_of_week=DUPLICATE_CLEANUP_DAY, hour=DUPLICATE_CLEANUP_HOUR, minute=0),
                id="duplicate_cleanup",
                name="Duplicate Cleanup",
                replace_existing=True
            )

        # Schedule anomaly analysis (every 2 hours)
        if ANOMALY_ANALYSIS_ENABLED:
            from .jobs.maintenance_jobs import run_anomaly_analysis_job
            _scheduler.add_job(
                run_anomaly_analysis_job,
                IntervalTrigger(hours=ANOMALY_ANALYSIS_INTERVAL_HOURS),
                id="anomaly_analysis",
                name="Anomaly Analysis",
                replace_existing=True
            )

        # Schedule usage anomaly detection (daily at 06:00)
        if USAGE_ANOMALY_ENABLED:
            from .jobs.maintenance_jobs import run_usage_anomaly_detection_job
            _scheduler.add_job(
                run_usage_anomaly_detection_job,
                CronTrigger(hour=USAGE_ANOMALY_HOUR, minute=0),
                id="usage_anomaly_detection",
                name="Usage Anomaly Detection",
                replace_existing=True
            )

        # Schedule weekly tool report (Sunday at 10:00)
        if WEEKLY_TOOL_REPORT_ENABLED:
            from .jobs.maintenance_jobs import run_weekly_tool_report_job
            _scheduler.add_job(
                run_weekly_tool_report_job,
                CronTrigger(day_of_week=WEEKLY_TOOL_REPORT_DAY, hour=WEEKLY_TOOL_REPORT_HOUR, minute=0),
                id="weekly_tool_report",
                name="Weekly Tool Report",
                replace_existing=True
            )

        # Schedule self-optimization analysis (Monday at 09:00)
        if SELF_OPTIMIZATION_ENABLED:
            from .jobs.maintenance_jobs import run_self_optimization_job
            _scheduler.add_job(
                run_self_optimization_job,
                CronTrigger(day_of_week=SELF_OPTIMIZATION_DAY, hour=SELF_OPTIMIZATION_HOUR, minute=0),
                id="self_optimization",
                name="Self-Optimization Analysis",
                replace_existing=True
            )

        # Schedule alias auto-sunset check (weekly Sunday at 05:00)
        if ALIAS_SUNSET_CHECK_ENABLED:
            from .jobs.alias_sunset_job import run_alias_sunset_check
            _scheduler.add_job(
                run_alias_sunset_check,
                CronTrigger(day_of_week="sun", hour=ALIAS_SUNSET_CHECK_HOUR, minute=0),
                id="alias_sunset_check",
                name="Alias Auto-Sunset Check",
                replace_existing=True
            )

        _scheduler.start()
        log_with_context(logger, "info", "Scheduler started",
                briefing_time=f"{BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d}",
                workflow_monitor_interval_seconds=WORKFLOW_MONITOR_INTERVAL_SECONDS,
                rag_regression_time=f"{RAG_REGRESSION_HOUR:02d}:{RAG_REGRESSION_MINUTE:02d}",
                monthly_review_schedule="Day 31 at 03:00 UTC",
                phase2_gate_time=f"{PHASE2_GATE_HOUR:02d}:{PHASE2_GATE_MINUTE:02d}" if PHASE2_GATE_ENABLED else "disabled",
                self_diagnostics_interval=f"every {SELF_DIAGNOSTICS_INTERVAL_HOURS}h" if SELF_DIAGNOSTICS_ENABLED else "disabled",
                auto_research_time=f"{AUTO_RESEARCH_HOUR:02d}:{AUTO_RESEARCH_MINUTE:02d}" if AUTO_RESEARCH_ENABLED else "disabled",
                batch_queue_interval=f"every {BATCH_QUEUE_INTERVAL_MINUTES}m" if BATCH_QUEUE_ENABLED else "disabled",
                pre_meeting_interval=f"every {PRE_MEETING_CHECK_INTERVAL_MINUTES}m" if PRE_MEETING_PUSH_ENABLED else "disabled",
                ml_pattern_interval=f"every {ML_PATTERN_INTERVAL_HOURS}h" if ML_PATTERN_ENABLED else "disabled",
                auto_refactor_time=f"{AUTO_REFACTOR_HOUR:02d}:00" if AUTO_REFACTOR_ENABLED else "disabled",
                memory_decay_time=f"{MEMORY_DECAY_HOUR:02d}:00" if MEMORY_DECAY_ENABLED else "disabled",
                duplicate_cleanup=f"{DUPLICATE_CLEANUP_DAY} {DUPLICATE_CLEANUP_HOUR:02d}:00" if DUPLICATE_CLEANUP_ENABLED else "disabled",
                anomaly_analysis_interval=f"every {ANOMALY_ANALYSIS_INTERVAL_HOURS}h" if ANOMALY_ANALYSIS_ENABLED else "disabled",
                usage_anomaly_time=f"{USAGE_ANOMALY_HOUR:02d}:00" if USAGE_ANOMALY_ENABLED else "disabled",
                weekly_tool_report=f"{WEEKLY_TOOL_REPORT_DAY} {WEEKLY_TOOL_REPORT_HOUR:02d}:00" if WEEKLY_TOOL_REPORT_ENABLED else "disabled",
                self_optimization=f"{SELF_OPTIMIZATION_DAY} {SELF_OPTIMIZATION_HOUR:02d}:00" if SELF_OPTIMIZATION_ENABLED else "disabled",
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
