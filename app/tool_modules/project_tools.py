"""
Project Tools.

Project management, thread management.
Extracted from tools.py (Phase S4).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode, internal_error

logger = get_logger("jarvis.tools.project")


def tool_add_project(name: str, description: str = "", priority: int = 2, **kwargs) -> Dict[str, Any]:
    """Add a new project"""
    log_with_context(logger, "info", "Tool: add_project", name=name, priority=priority)
    metrics.inc("tool_add_project")

    if not _current_user_id:
        return {"error": "No user context available"}

    try:
        from . import projects
        return projects.tool_add_project(_current_user_id, name, description, priority)
    except Exception as e:
        log_with_context(logger, "error", "Add project failed", error=str(e))
        return {"error": str(e)}


def tool_list_projects(**kwargs) -> Dict[str, Any]:
    """List all projects"""
    log_with_context(logger, "info", "Tool: list_projects")
    metrics.inc("tool_list_projects")

    if not _current_user_id:
        return {"error": "No user context available"}

    try:
        from . import projects
        return projects.tool_list_projects(_current_user_id)
    except Exception as e:
        log_with_context(logger, "error", "List projects failed", error=str(e))
        return {"error": str(e)}


def tool_update_project_status(project_id: str, status: str, **kwargs) -> Dict[str, Any]:
    """Update project status"""
    log_with_context(logger, "info", "Tool: update_project_status", project_id=project_id, status=status)
    metrics.inc("tool_update_project_status")

    try:
        from . import projects
        return projects.tool_update_project_status(project_id, status)
    except Exception as e:
        log_with_context(logger, "error", "Update project failed", error=str(e))
        return {"error": str(e)}


def tool_manage_thread(action: str, topic: str = None, notes: str = None, **kwargs) -> Dict[str, Any]:
    """
    Manage conversation threads for ADHD support.

    Actions:
    - open: Start or resume a topic
    - close: Mark topic as completed
    - pause: Temporarily set aside
    - list: Show all threads with status
    """
    log_with_context(logger, "info", "Tool: manage_thread", action=action, topic=topic)
    metrics.inc("tool_manage_thread")

    try:
        from . import session_manager

        user_id = _current_user_id
        if not user_id:
            return {"error": "No user context available"}

        if action == "list":
            # Get all threads grouped by status
            open_threads = session_manager.get_thread_states(user_id, status="open")
            paused_threads = session_manager.get_thread_states(user_id, status="paused")

            return {
                "success": True,
                "open_threads": [{"topic": t["topic"], "since": t["opened_at"]} for t in open_threads],
                "paused_threads": [{"topic": t["topic"], "paused_at": t["paused_at"]} for t in paused_threads],
                "summary": f"{len(open_threads)} offen, {len(paused_threads)} pausiert"
            }

        if not topic:
            return {"error": "Topic required for open/close/pause actions"}

        topic = topic.lower().strip()

        if action == "open":
            result = session_manager.open_thread(user_id, topic)
            return {
                "success": True,
                "action": "opened" if result["action"] == "opened" else "reopened",
                "topic": topic,
                "message": f"Thread '{topic}' ist jetzt aktiv."
            }

        elif action == "close":
            result = session_manager.close_thread(user_id, topic, notes)
            if result["success"]:
                return {
                    "success": True,
                    "action": "closed",
                    "topic": topic,
                    "message": f"Thread '{topic}' wurde abgeschlossen."
                }
            else:
                return {"success": False, "error": f"Thread '{topic}' nicht gefunden oder bereits geschlossen."}

        elif action == "pause":
            result = session_manager.pause_thread(user_id, topic)
            if result["success"]:
                return {
                    "success": True,
                    "action": "paused",
                    "topic": topic,
                    "message": f"Thread '{topic}' wurde pausiert."
                }
            else:
                return {"success": False, "error": f"Thread '{topic}' nicht gefunden oder nicht offen."}

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as e:
        log_with_context(logger, "error", "Thread management failed", error=str(e))
        return {"error": str(e)}


# ============ Proactive Initiative Tools ============

# Phase 15.5: Hint tuning configuration (now driven by config)
HINT_CONFIDENCE_THRESHOLD = 0.65  # fallback if config missing
HINT_WORKING_HOURS_START = 9      # legacy working hours
HINT_WORKING_HOURS_END = 18

# Proactivity dial runtime state (simple in-memory counters)
_proactive_daily_count = 0
_proactive_daily_date = None
_proactive_last_hint_ts = None


