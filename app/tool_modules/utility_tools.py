"""
Utility Tools.

Basic utility functions: no_tool, out_of_scope, pending actions, hints.
Extracted from tools.py (Phase S6).
"""
from typing import Dict, Any
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.utility")


def tool_no_tool_needed(reason: str = "", **kwargs) -> Dict[str, Any]:
    """Placeholder for when no tool is needed"""
    log_with_context(logger, "info", "Tool: no_tool_needed", reason=reason)
    metrics.inc("tool_no_tool_needed")
    return {"status": "ok", "reason": reason}


def tool_request_out_of_scope(reason: str = "Unspecified", suggestion: str = "Nutze ein anderes Tool", **kwargs) -> Dict[str, Any]:
    """Signal that a request is outside Jarvis's capabilities"""
    log_with_context(logger, "info", "Tool: request_out_of_scope", reason=reason)
    metrics.inc("tool_request_out_of_scope")
    return {"status": "out_of_scope", "reason": reason, "suggestion": suggestion}


def tool_complete_pending_action(
    action_id: int = None,
    action_text: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Mark a pending action as completed"""
    log_with_context(logger, "info", "Tool: complete_pending_action",
                    action_id=action_id, action_text=action_text)
    metrics.inc("tool_complete_pending_action")

    from . import session_manager

    if action_id:
        success = session_manager.complete_action(action_id)
        if success:
            return {
                "status": "completed",
                "action_id": action_id,
                "message": "Action marked as completed"
            }
        else:
            return {
                "status": "not_found",
                "action_id": action_id,
                "message": "Action not found"
            }

    elif action_text:
        # Find matching action by text
        pending = session_manager.get_pending_actions(user_id=user_id, limit=50)
        for action in pending:
            if action_text.lower() in action["action_text"].lower():
                success = session_manager.complete_action(action["id"])
                if success:
                    return {
                        "status": "completed",
                        "action_id": action["id"],
                        "matched_text": action["action_text"],
                        "message": "Action matched and marked as completed"
                    }

        return {
            "status": "not_found",
            "search_text": action_text,
            "message": "No matching pending action found"
        }

    return {
        "status": "error",
        "message": "Please provide either action_id or action_text"
    }


# ============ Knowledge Layer Tools ============


def tool_proactive_hint(
    observation: str,
    context: str,
    suggested_action: str = None,
    confidence: str = "medium",
    force: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Share a proactive observation or pattern.
    This is a Tier 2 (Notify) action - Jarvis can do this autonomously.

    Phase 15.5 enhancements:
    - Filters low-confidence hints (< 0.65)
    - Only sends during working hours (9-18 Zurich, weekdays)
    - Set force=True to bypass filters (for critical hints)

    Args:
        observation: The observation to share
        context: Context around the observation
        suggested_action: Optional suggested action
        confidence: "low", "medium", or "high"
        force: Bypass confidence and time filters

    Returns:
        Status dict with hint info or filter reason
    """
    from . import config

    conf_score = _get_confidence_score(confidence)
    level_threshold = _proactive_level_threshold(config.PROACTIVE_LEVEL, config.PROACTIVE_CONFIDENCE_THRESHOLD)

    log_with_context(logger, "info", "Tool: proactive_hint",
                    confidence=confidence, confidence_score=conf_score,
                    observation_preview=observation[:50], force=force,
                    proactive_level=config.PROACTIVE_LEVEL)
    metrics.inc("tool_proactive_hint")

    # Level gate (unless forced)
    if not force and config.PROACTIVE_LEVEL <= 1:
        metrics.inc("tool_proactive_hint_filtered_level")
        return {
            "status": "filtered",
            "reason": "proactive_level",
            "level": config.PROACTIVE_LEVEL,
            "message": "Proactivity disabled by level."
        }

    # Check confidence threshold (unless forced)
    if not force and conf_score < level_threshold:
        log_with_context(logger, "info", "Hint filtered: low confidence",
                        confidence_score=conf_score, threshold=level_threshold)
        metrics.inc("tool_proactive_hint_filtered_confidence")
        return {
            "status": "filtered",
            "reason": "low_confidence",
            "confidence_score": conf_score,
            "threshold": level_threshold,
            "message": f"Hint filtered: confidence {conf_score:.2f} < threshold {level_threshold}"
        }

    # Quiet hours gate (unless forced)
    if not force and _is_quiet_hours():
        log_with_context(logger, "info", "Hint deferred: quiet hours")
        metrics.inc("tool_proactive_hint_deferred_quiet_hours")
        return {
            "status": "deferred",
            "reason": "quiet_hours",
            "quiet_hours": f"{config.PROACTIVE_QUIET_HOURS_START}-{config.PROACTIVE_QUIET_HOURS_END}",
            "message": "Hint deferred: quiet hours. Will not disturb user."
        }

    # Rate limits (unless forced)
    if not force:
        now = datetime.utcnow()
        rate_check = _check_proactive_rate_limits(
            now,
            config.PROACTIVE_MAX_PER_DAY,
            config.PROACTIVE_COOLDOWN_MINUTES
        )
        if not rate_check.get("allowed", False):
            metrics.inc("tool_proactive_hint_rate_limited")
            return {
                "status": "deferred",
                "reason": rate_check.get("reason", "rate_limited"),
                "message": rate_check.get("message", "Proactive hint deferred by rate limits")
            }

    # Store the hint as a fact for future reference (SQLite)
    from . import memory_store
    hint_fact = f"[Proactive Hint] {observation}"
    memory_store.add_fact(hint_fact, category="insight", confidence=conf_score)

    # Also store in proactive_hints PostgreSQL table for metrics (Phase 19.2)
    user_id = kwargs.get("user_id", "unknown")
    session_id = kwargs.get("session_id", "unknown")
    try:
        from .db_safety import safe_write_query
        with safe_write_query("proactive_hints") as cur:
            cur.execute("""
                INSERT INTO proactive_hints (user_id, session_id, hint_type, category, content, context, confidence, was_shown, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(user_id),
                str(session_id),
                "observation",
                "insight",
                observation,
                context,
                conf_score,
                True,  # was_shown = True since we're delivering it
                json.dumps({"suggested_action": suggested_action}) if suggested_action else None
            ))
    except Exception as e:
        log_with_context(logger, "warning", "Failed to store proactive hint in PostgreSQL", error=str(e))

    # Update counters
    global _proactive_daily_count, _proactive_daily_date, _proactive_last_hint_ts
    _proactive_daily_date = datetime.utcnow().date().isoformat()
    _proactive_daily_count += 1
    _proactive_last_hint_ts = datetime.utcnow().timestamp()

    return {
        "status": "hint_shared",
        "observation": observation,
        "context": context,
        "suggested_action": suggested_action,
        "confidence": confidence,
        "confidence_score": conf_score,
        "proactive_level": config.PROACTIVE_LEVEL,
        "message": f"Proaktiver Hinweis geteilt: {observation[:100]}..."
    }


# ============ Direct File Access ============

# Whitelisted directories for file access
ALLOWED_FILE_PATHS = [
    # macOS paths (for local testing)
    "/Volumes/BRAIN/system/",      # Main system folder
    "/Volumes/BRAIN/system/data/", # Canonical data folder
    "/Volumes/BRAIN/data/",        # Data folder (linkedin/visualfox updates)
    "/Volumes/BRAIN/projects/",    # Project files
    "/Volumes/BRAIN/notes/",       # Notes
    # Docker paths (inside container)
    "/brain/system/",              # Main system folder
    "/brain/system/data/",         # Canonical data folder
    "/brain/data/",                # Data folder (when mounted under /brain)
    "/brain/projects/",            # Project files
    "/brain/notes/",               # Notes
    "/data/",                      # Docker mounted data
]

# Blocked file patterns (security)
BLOCKED_PATTERNS = [
    ".env",
    "credentials",
    "secret",
    "password",
    ".key",
    ".pem",
    "id_rsa",
    ".ssh",
]

AUDIT_DIR_DOCKER = "/brain/system/ingestion/audit"
AUDIT_DIR_MAC = "/Volumes/BRAIN/system/ingestion/audit"


