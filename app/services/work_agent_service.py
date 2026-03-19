"""
Work Agent Service (WorkJarvis) - Phase 22A-05

Domain-specific service for productivity and work management:
- Task prioritization (Eisenhower matrix + custom scoring)
- Effort estimation with learning
- Focus time tracking (Pomodoro-style)
- Break suggestions based on patterns
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.work_agent")


class WorkAgentService:
    """
    WorkJarvis - Productivity and Work Management Specialist.

    Provides:
    - Smart task prioritization
    - Effort estimation with calibration
    - Focus session tracking
    - Break suggestions based on energy and patterns
    """

    def __init__(self):
        self._patterns_cache: Dict[str, Any] = {}

    # =========================================================================
    # Task Prioritization
    # =========================================================================

    def prioritize_tasks(
        self,
        tasks: List[Dict[str, Any]] = None,
        context: str = None,
        available_minutes: int = None,
        energy_level: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Prioritize tasks using Eisenhower matrix + custom scoring.

        Args:
            tasks: Optional list of tasks to add/update first
            context: Current context (home, office, calls, etc.)
            available_minutes: Time available for work
            energy_level: Current energy (1-10)
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Add/update tasks if provided
                    if tasks:
                        for task in tasks:
                            self._upsert_task(cur, task, user_id)
                        conn.commit()

                    # Build priority query
                    query = """
                        SELECT id, title, project, priority, importance, urgency,
                               estimated_minutes, due_date, energy_required, context_tags, status
                        FROM jarvis_work_tasks
                        WHERE user_id = %s AND status IN ('todo', 'in_progress')
                    """
                    params = [user_id]

                    # Filter by context
                    if context:
                        query += " AND (context_tags = '[]' OR context_tags ? %s)"
                        params.append(context)

                    # Filter by energy requirement
                    if energy_level and energy_level <= 4:
                        query += " AND energy_required IN ('low', 'medium')"
                    elif energy_level and energy_level <= 6:
                        query += " AND energy_required != 'high'"

                    # Order by priority score
                    query += """
                        ORDER BY
                            CASE WHEN due_date = CURRENT_DATE THEN 0
                                 WHEN due_date < CURRENT_DATE THEN -1
                                 ELSE 1 END,
                            (importance * 0.4 + urgency * 0.4 + priority * 0.2) DESC
                        LIMIT 10
                    """

                    cur.execute(query, tuple(params))

                    prioritized = []
                    total_minutes = 0

                    for row in cur.fetchall():
                        task = {
                            "id": row[0],
                            "title": row[1],
                            "project": row[2],
                            "priority_score": round(row[3] * 0.2 + row[4] * 0.4 + row[5] * 0.4),
                            "estimated_minutes": row[6],
                            "due_date": row[7].isoformat() if row[7] else None,
                            "energy_required": row[8],
                            "status": row[10]
                        }

                        # Eisenhower quadrant
                        if row[4] >= 70 and row[5] >= 70:
                            task["quadrant"] = "DO"
                        elif row[4] >= 70:
                            task["quadrant"] = "SCHEDULE"
                        elif row[5] >= 70:
                            task["quadrant"] = "DELEGATE"
                        else:
                            task["quadrant"] = "ELIMINATE"

                        # Check if fits in available time
                        if available_minutes and row[6]:
                            if total_minutes + row[6] <= available_minutes:
                                task["fits_today"] = True
                                total_minutes += row[6]
                            else:
                                task["fits_today"] = False

                        prioritized.append(task)

                    # Categorize
                    do_first = [t for t in prioritized if t.get("quadrant") == "DO"]
                    schedule = [t for t in prioritized if t.get("quadrant") == "SCHEDULE"]

                    return {
                        "success": True,
                        "prioritized": prioritized,
                        "do_first": do_first[:3],
                        "schedule_later": schedule[:3],
                        "total_estimated_minutes": total_minutes,
                        "context": context,
                        "energy_level": energy_level,
                        "message": f"{len(do_first)} urgent+important tasks, {len(schedule)} to schedule"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Prioritization failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _upsert_task(self, cur, task: Dict[str, Any], user_id: str):
        """Insert or update a task."""
        cur.execute("""
            INSERT INTO jarvis_work_tasks
            (user_id, title, description, project, priority, importance, urgency,
             estimated_minutes, due_date, energy_required, context_tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                priority = EXCLUDED.priority,
                importance = EXCLUDED.importance,
                urgency = EXCLUDED.urgency,
                updated_at = NOW()
        """, (
            user_id,
            task.get("title"),
            task.get("description"),
            task.get("project"),
            task.get("priority", 50),
            task.get("importance", 50),
            task.get("urgency", 50),
            task.get("estimated_minutes"),
            task.get("due_date"),
            task.get("energy_required", "medium"),
            json.dumps(task.get("context_tags", []))
        ))

    # =========================================================================
    # Effort Estimation
    # =========================================================================

    def estimate_effort(
        self,
        task_description: str,
        task_type: str = "general",
        complexity: str = "moderate",
        similar_tasks: bool = True,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Estimate effort for a task, learning from past estimates.

        Args:
            task_description: What needs to be done
            task_type: coding, writing, review, meeting, admin
            complexity: simple, moderate, complex, unknown
        """
        # Base estimates by type and complexity
        base_estimates = {
            "coding": {"simple": 30, "moderate": 90, "complex": 240},
            "writing": {"simple": 20, "moderate": 60, "complex": 180},
            "review": {"simple": 15, "moderate": 45, "complex": 120},
            "meeting": {"simple": 30, "moderate": 60, "complex": 120},
            "admin": {"simple": 10, "moderate": 30, "complex": 60},
            "general": {"simple": 20, "moderate": 60, "complex": 120}
        }

        base = base_estimates.get(task_type, base_estimates["general"])
        estimate = base.get(complexity, base["moderate"])

        # Learn from historical accuracy
        calibration = 1.0
        confidence = 0.5
        similar_count = 0

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if similar_tasks:
                        # Get historical accuracy for this task type
                        cur.execute("""
                            SELECT AVG(actual_minutes::float / estimated_minutes),
                                   COUNT(*), AVG(accuracy_pct)
                            FROM jarvis_effort_estimates
                            WHERE user_id = %s AND task_type = %s
                              AND actual_minutes IS NOT NULL
                              AND completed_at > NOW() - INTERVAL '90 days'
                        """, (user_id, task_type))
                        row = cur.fetchone()

                        if row and row[0] and row[1] >= 3:
                            calibration = row[0]
                            similar_count = row[1]
                            confidence = min(0.9, 0.5 + (row[1] * 0.05))

                    # Apply calibration
                    calibrated_estimate = int(estimate * calibration)

                    # Calculate range
                    if confidence >= 0.7:
                        range_pct = 0.2
                    elif confidence >= 0.5:
                        range_pct = 0.4
                    else:
                        range_pct = 0.6

                    low = int(calibrated_estimate * (1 - range_pct))
                    high = int(calibrated_estimate * (1 + range_pct))

                    return {
                        "success": True,
                        "estimate_minutes": calibrated_estimate,
                        "range": {"low": low, "high": high},
                        "confidence": round(confidence, 2),
                        "task_type": task_type,
                        "complexity": complexity,
                        "calibration": round(calibration, 2),
                        "based_on": similar_count,
                        "formatted": self._format_duration(calibrated_estimate),
                        "message": f"Estimated {self._format_duration(calibrated_estimate)} ({low}-{high} min range)"
                    }

        except Exception as e:
            return {
                "success": True,
                "estimate_minutes": estimate,
                "range": {"low": int(estimate * 0.5), "high": int(estimate * 1.5)},
                "confidence": 0.3,
                "message": f"Base estimate: {estimate} minutes (no historical data)"
            }

    def _format_duration(self, minutes: int) -> str:
        """Format minutes as human-readable duration."""
        if minutes < 60:
            return f"{minutes}min"
        hours = minutes // 60
        mins = minutes % 60
        if mins == 0:
            return f"{hours}h"
        return f"{hours}h {mins}min"

    # =========================================================================
    # Focus Time Tracking
    # =========================================================================

    def track_focus_time(
        self,
        action: str = "status",
        task_title: str = None,
        project: str = None,
        planned_minutes: int = 25,
        category: str = "deep_work",
        notes: str = None,
        session_id: int = None,
        focus_quality: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Track focus sessions (Pomodoro-style).

        Args:
            action: "start", "end", "pause", "status"
            task_title: What you're working on
            project: Project name
            planned_minutes: How long you plan to focus
            category: deep_work, meetings, admin, creative, learning
            session_id: For ending a specific session
            focus_quality: 1-10 self-assessment (for end)
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if action == "start":
                        # Check for active session
                        cur.execute("""
                            SELECT id, task_title, started_at
                            FROM jarvis_focus_sessions
                            WHERE user_id = %s AND ended_at IS NULL
                            LIMIT 1
                        """, (user_id,))
                        active = cur.fetchone()

                        if active:
                            return {
                                "success": False,
                                "error": f"Session already active: '{active[1]}' since {active[2].strftime('%H:%M')}"
                            }

                        # Start new session
                        cur.execute("""
                            INSERT INTO jarvis_focus_sessions
                            (user_id, task_title, project, category, planned_minutes)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                        """, (user_id, task_title, project, category, planned_minutes))
                        new_id = cur.fetchone()[0]
                        conn.commit()

                        return {
                            "success": True,
                            "session_id": new_id,
                            "task": task_title,
                            "planned_minutes": planned_minutes,
                            "started_at": datetime.now().strftime("%H:%M"),
                            "message": f"Focus session started: {task_title} ({planned_minutes}min)"
                        }

                    elif action == "end":
                        # Find active session
                        if session_id:
                            cur.execute("""
                                SELECT id, task_title, started_at, planned_minutes
                                FROM jarvis_focus_sessions
                                WHERE id = %s AND user_id = %s
                            """, (session_id, user_id))
                        else:
                            cur.execute("""
                                SELECT id, task_title, started_at, planned_minutes
                                FROM jarvis_focus_sessions
                                WHERE user_id = %s AND ended_at IS NULL
                                ORDER BY started_at DESC LIMIT 1
                            """, (user_id,))

                        session = cur.fetchone()
                        if not session:
                            return {"success": False, "error": "No active session found"}

                        actual_minutes = int((datetime.now() - session[2]).total_seconds() / 60)

                        cur.execute("""
                            UPDATE jarvis_focus_sessions
                            SET ended_at = NOW(),
                                actual_minutes = %s,
                                focus_quality = %s,
                                completed = TRUE,
                                notes = %s
                            WHERE id = %s
                        """, (actual_minutes, focus_quality, notes, session[0]))

                        # Update daily summary
                        self._update_daily_summary(cur, user_id, actual_minutes, focus_quality)
                        conn.commit()

                        return {
                            "success": True,
                            "session_id": session[0],
                            "task": session[1],
                            "planned_minutes": session[3],
                            "actual_minutes": actual_minutes,
                            "focus_quality": focus_quality,
                            "message": f"Session complete: {actual_minutes}min focused on '{session[1]}'"
                        }

                    elif action == "status":
                        # Get current/recent sessions
                        cur.execute("""
                            SELECT id, task_title, project, started_at, planned_minutes, ended_at
                            FROM jarvis_focus_sessions
                            WHERE user_id = %s AND started_at > NOW() - INTERVAL '24 hours'
                            ORDER BY started_at DESC
                            LIMIT 5
                        """, (user_id,))

                        sessions = []
                        active_session = None

                        for row in cur.fetchall():
                            s = {
                                "id": row[0],
                                "task": row[1],
                                "project": row[2],
                                "started": row[3].strftime("%H:%M"),
                                "planned": row[4],
                                "active": row[5] is None
                            }
                            if row[5] is None:
                                active_session = s
                            sessions.append(s)

                        # Today's stats
                        cur.execute("""
                            SELECT COALESCE(SUM(actual_minutes), 0),
                                   COUNT(*) FILTER (WHERE completed),
                                   AVG(focus_quality)
                            FROM jarvis_focus_sessions
                            WHERE user_id = %s AND DATE(started_at) = CURRENT_DATE
                        """, (user_id,))
                        today = cur.fetchone()

                        return {
                            "success": True,
                            "active_session": active_session,
                            "recent_sessions": sessions,
                            "today": {
                                "total_focus_minutes": today[0],
                                "sessions_completed": today[1],
                                "avg_focus_quality": round(today[2], 1) if today[2] else None
                            }
                        }

        except Exception as e:
            log_with_context(logger, "error", "Focus tracking failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _update_daily_summary(self, cur, user_id: str, minutes: int, quality: int):
        """Update or create daily summary."""
        cur.execute("""
            INSERT INTO jarvis_work_daily_summary
            (user_id, summary_date, total_focus_minutes, avg_focus_quality)
            VALUES (%s, CURRENT_DATE, %s, %s)
            ON CONFLICT (user_id, summary_date)
            DO UPDATE SET
                total_focus_minutes = jarvis_work_daily_summary.total_focus_minutes + EXCLUDED.total_focus_minutes,
                avg_focus_quality = (jarvis_work_daily_summary.avg_focus_quality + EXCLUDED.avg_focus_quality) / 2
        """, (user_id, minutes, quality or 5))

    # =========================================================================
    # Break Suggestions
    # =========================================================================

    def suggest_breaks(
        self,
        current_focus_minutes: int = None,
        energy_level: int = None,
        last_break_minutes_ago: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Suggest breaks based on focus time and energy patterns.

        Returns break recommendations based on:
        - Time since last break
        - Current energy level
        - Learned patterns (52/17 rule, etc.)
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get user's break pattern
                    cur.execute("""
                        SELECT pattern_data FROM jarvis_work_patterns
                        WHERE user_id = %s AND pattern_type = 'break_frequency'
                    """, (user_id,))
                    row = cur.fetchone()

                    ideal_interval = 52
                    ideal_break = 17
                    if row and row[0]:
                        ideal_interval = row[0].get("ideal_interval_minutes", 52)
                        ideal_break = row[0].get("ideal_break_minutes", 17)

                    # Calculate recommendation
                    needs_break = False
                    urgency = "low"
                    break_type = "micro"
                    suggested_duration = 5
                    activities = ["stretch", "walk", "hydrate"]

                    # Check focus time
                    if current_focus_minutes:
                        if current_focus_minutes >= ideal_interval * 2:
                            needs_break = True
                            urgency = "high"
                            break_type = "long"
                            suggested_duration = 20
                            activities = ["walk outside", "meal", "change environment"]
                        elif current_focus_minutes >= ideal_interval:
                            needs_break = True
                            urgency = "medium"
                            break_type = "short"
                            suggested_duration = ideal_break
                            activities = ["stretch", "walk", "coffee", "fresh air"]

                    # Check energy
                    if energy_level and energy_level <= 4:
                        needs_break = True
                        if urgency != "high":
                            urgency = "medium"
                        suggested_duration = max(suggested_duration, 15)
                        activities = ["power nap", "walk outside", "snack", "fresh air"]

                    # Check time since last break
                    if last_break_minutes_ago and last_break_minutes_ago > ideal_interval:
                        needs_break = True

                    # Get recent break history
                    cur.execute("""
                        SELECT break_type, duration_minutes, activity, taken_at
                        FROM jarvis_breaks
                        WHERE user_id = %s AND taken_at > NOW() - INTERVAL '8 hours'
                        ORDER BY taken_at DESC
                        LIMIT 5
                    """, (user_id,))
                    recent_breaks = [
                        {"type": r[0], "duration": r[1], "activity": r[2], "time": r[3].strftime("%H:%M")}
                        for r in cur.fetchall()
                    ]

                    return {
                        "success": True,
                        "needs_break": needs_break,
                        "urgency": urgency,
                        "suggestion": {
                            "type": break_type,
                            "duration_minutes": suggested_duration,
                            "activities": activities
                        },
                        "pattern": {
                            "ideal_focus_minutes": ideal_interval,
                            "ideal_break_minutes": ideal_break
                        },
                        "recent_breaks": recent_breaks,
                        "message": f"{'Take a break!' if needs_break else 'Good focus rhythm.'} Suggested: {suggested_duration}min {break_type} break"
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def log_break(
        self,
        break_type: str = "short",
        duration_minutes: int = None,
        activity: str = None,
        energy_before: int = None,
        energy_after: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """Log a break taken."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get active focus session if any
                    cur.execute("""
                        SELECT id FROM jarvis_focus_sessions
                        WHERE user_id = %s AND ended_at IS NULL
                        LIMIT 1
                    """, (user_id,))
                    session = cur.fetchone()
                    session_id = session[0] if session else None

                    cur.execute("""
                        INSERT INTO jarvis_breaks
                        (user_id, break_type, duration_minutes, activity,
                         focus_session_id, energy_before, energy_after)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        user_id, break_type, duration_minutes, activity,
                        session_id, energy_before, energy_after
                    ))
                    break_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "success": True,
                        "break_id": break_id,
                        "type": break_type,
                        "duration": duration_minutes,
                        "energy_change": (energy_after - energy_before) if energy_before and energy_after else None,
                        "message": f"{break_type.capitalize()} break logged: {duration_minutes}min"
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_work_stats(self, period: str = "today", user_id: str = "1") -> Dict[str, Any]:
        """Get work/productivity statistics."""
        try:
            days = {"today": 0, "week": 7, "month": 30}.get(period, 0)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    if period == "today":
                        date_filter = "DATE(started_at) = CURRENT_DATE"
                    else:
                        date_filter = f"started_at > NOW() - INTERVAL '{days} days'"

                    # Focus stats
                    cur.execute(f"""
                        SELECT COUNT(*), COALESCE(SUM(actual_minutes), 0),
                               AVG(focus_quality), COUNT(*) FILTER (WHERE completed)
                        FROM jarvis_focus_sessions
                        WHERE user_id = %s AND {date_filter}
                    """, (user_id,))
                    focus = cur.fetchone()

                    # Task stats
                    cur.execute(f"""
                        SELECT COUNT(*) FILTER (WHERE status = 'done'),
                               COUNT(*) FILTER (WHERE status = 'in_progress'),
                               COUNT(*) FILTER (WHERE status = 'todo')
                        FROM jarvis_work_tasks
                        WHERE user_id = %s
                    """, (user_id,))
                    tasks = cur.fetchone()

                    # Break stats
                    cur.execute(f"""
                        SELECT COUNT(*), COALESCE(SUM(duration_minutes), 0)
                        FROM jarvis_breaks
                        WHERE user_id = %s AND {date_filter.replace('started_at', 'taken_at')}
                    """, (user_id,))
                    breaks = cur.fetchone()

                    return {
                        "success": True,
                        "period": period,
                        "focus": {
                            "sessions": focus[0],
                            "total_minutes": focus[1],
                            "avg_quality": round(focus[2], 1) if focus[2] else None,
                            "completed": focus[3]
                        },
                        "tasks": {
                            "done": tasks[0],
                            "in_progress": tasks[1],
                            "todo": tasks[2]
                        },
                        "breaks": {
                            "count": breaks[0],
                            "total_minutes": breaks[1]
                        },
                        "focus_to_break_ratio": round(focus[1] / max(breaks[1], 1), 1)
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[WorkAgentService] = None


def get_work_agent_service() -> WorkAgentService:
    """Get or create work agent service singleton."""
    global _service
    if _service is None:
        _service = WorkAgentService()
    return _service
