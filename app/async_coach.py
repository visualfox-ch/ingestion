"""
Jarvis Async Coach - Scheduled Coaching Interactions

Manages:
- Scheduled check-ins
- Goal reminders
- Progress prompts
- Learning nudges
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.async")


# ============ Interaction Types ============

INTERACTION_TYPES = {
    "goal_checkin": {
        "name": "Goal Check-in",
        "description": "Check progress on active goals",
        "default_interval_hours": 24,
        "template": "Wie läuft es mit deinem Ziel: {goal_title}? Fortschritt diese Woche?",
    },
    "domain_reminder": {
        "name": "Domain Reminder",
        "description": "Remind to engage with a domain",
        "default_interval_hours": 48,
        "template": "Schon länger nicht in {domain_name} aktiv. Was steht an?",
    },
    "reflection_prompt": {
        "name": "Reflection Prompt",
        "description": "Weekly reflection questions",
        "default_interval_hours": 168,  # Weekly
        "template": "Zeit für Reflexion: Was hat diese Woche gut funktioniert? Was nicht?",
    },
    "skill_practice": {
        "name": "Skill Practice",
        "description": "Prompt to practice a skill",
        "default_interval_hours": 72,
        "template": "Übung macht den Meister: Probier heute {skill_name} aus.",
    },
    "habit_check": {
        "name": "Habit Check",
        "description": "Check on habit consistency",
        "default_interval_hours": 24,
        "template": "Habit-Check: Hast du heute {habit_name} gemacht?",
    },
    "learning_nudge": {
        "name": "Learning Nudge",
        "description": "Encourage continued learning",
        "default_interval_hours": 72,
        "template": "Quick Learning: Was hast du heute Neues gelernt oder ausprobiert?",
    },
}


# ============ Data Classes ============

@dataclass
class ScheduledInteraction:
    """A scheduled coaching interaction"""
    id: Optional[int]
    user_id: int
    domain_id: Optional[str]
    interaction_type: str
    scheduled_for: datetime
    content: Dict[str, Any]
    status: str = "pending"
    executed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None


# ============ Scheduling ============

def schedule_interaction(
    user_id: int,
    interaction_type: str,
    scheduled_for: datetime,
    domain_id: str = None,
    content: Dict[str, Any] = None
) -> Optional[int]:
    """Schedule a new coaching interaction."""
    if interaction_type not in INTERACTION_TYPES:
        log_with_context(logger, "warning", "Unknown interaction type", type=interaction_type)
        return None

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO scheduled_interaction
                (user_id, domain_id, interaction_type, scheduled_for, content, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                RETURNING id
            """, (
                user_id,
                domain_id,
                interaction_type,
                scheduled_for,
                json.dumps(content or {}),
                datetime.utcnow()
            ))
            row = cur.fetchone()
            interaction_id = row["id"] if row else None

            log_with_context(logger, "info", "Interaction scheduled",
                           id=interaction_id, type=interaction_type,
                           scheduled=scheduled_for.isoformat())
            return interaction_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to schedule", error=str(e))
        return None


def schedule_goal_checkin(
    user_id: int,
    goal_id: int,
    goal_title: str,
    domain_id: str,
    hours_from_now: int = 24
) -> Optional[int]:
    """Schedule a goal check-in."""
    scheduled_for = datetime.utcnow() + timedelta(hours=hours_from_now)

    return schedule_interaction(
        user_id=user_id,
        interaction_type="goal_checkin",
        scheduled_for=scheduled_for,
        domain_id=domain_id,
        content={"goal_id": goal_id, "goal_title": goal_title}
    )


def schedule_domain_reminder(
    user_id: int,
    domain_id: str,
    domain_name: str,
    hours_from_now: int = 48
) -> Optional[int]:
    """Schedule a domain reminder."""
    scheduled_for = datetime.utcnow() + timedelta(hours=hours_from_now)

    return schedule_interaction(
        user_id=user_id,
        interaction_type="domain_reminder",
        scheduled_for=scheduled_for,
        domain_id=domain_id,
        content={"domain_name": domain_name}
    )


def schedule_weekly_reflection(user_id: int) -> Optional[int]:
    """Schedule weekly reflection for next Sunday."""
    now = datetime.utcnow()
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7

    scheduled_for = now + timedelta(days=days_until_sunday)
    scheduled_for = scheduled_for.replace(hour=18, minute=0, second=0, microsecond=0)

    return schedule_interaction(
        user_id=user_id,
        interaction_type="reflection_prompt",
        scheduled_for=scheduled_for,
        content={"week_number": scheduled_for.isocalendar()[1]}
    )


# ============ Retrieval ============

def get_pending_interactions(
    user_id: int = None,
    before: datetime = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get pending interactions that are due."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            before = before or datetime.utcnow()
            filters = ["status = 'pending'", "scheduled_for <= %s"]
            params = [before]

            if user_id:
                filters.append("user_id = %s")
                params.append(user_id)

            params.append(limit)

            cur.execute(f"""
                SELECT * FROM scheduled_interaction
                WHERE {' AND '.join(filters)}
                ORDER BY scheduled_for ASC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get pending", error=str(e))
        return []


def get_upcoming_interactions(
    user_id: int,
    hours: int = 24,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Get upcoming interactions for a user."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cutoff = datetime.utcnow() + timedelta(hours=hours)

            cur.execute("""
                SELECT * FROM scheduled_interaction
                WHERE user_id = %s
                  AND status = 'pending'
                  AND scheduled_for <= %s
                ORDER BY scheduled_for ASC
                LIMIT %s
            """, (user_id, cutoff, limit))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get upcoming", error=str(e))
        return []


# ============ Execution ============

def mark_executed(
    interaction_id: int,
    result: Dict[str, Any] = None
) -> bool:
    """Mark an interaction as executed."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE scheduled_interaction
                SET status = 'executed',
                    executed_at = %s,
                    result = %s
                WHERE id = %s
            """, (datetime.utcnow(), json.dumps(result or {}), interaction_id))

            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to mark executed", error=str(e))
        return False


def mark_skipped(
    interaction_id: int,
    reason: str = None
) -> bool:
    """Mark an interaction as skipped."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE scheduled_interaction
                SET status = 'skipped',
                    executed_at = %s,
                    result = %s
                WHERE id = %s
            """, (datetime.utcnow(), json.dumps({"reason": reason}), interaction_id))

            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to mark skipped", error=str(e))
        return False


def reschedule(
    interaction_id: int,
    new_time: datetime
) -> bool:
    """Reschedule an interaction."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE scheduled_interaction
                SET scheduled_for = %s,
                    status = 'pending'
                WHERE id = %s AND status = 'pending'
            """, (new_time, interaction_id))

            return cur.rowcount > 0
    except Exception as e:
        log_with_context(logger, "error", "Failed to reschedule", error=str(e))
        return False


# ============ Message Generation ============

def generate_interaction_message(interaction: Dict[str, Any]) -> str:
    """Generate the message text for an interaction."""
    interaction_type = interaction.get("interaction_type", "")
    content = interaction.get("content", {})

    if isinstance(content, str):
        content = json.loads(content)

    type_def = INTERACTION_TYPES.get(interaction_type, {})
    template = type_def.get("template", "Check-in time!")

    # Simple template substitution
    message = template
    for key, value in content.items():
        message = message.replace(f"{{{key}}}", str(value))

    return message


def build_interaction_context(interaction: Dict[str, Any]) -> str:
    """Build context for the interaction to include in system prompt."""
    interaction_type = interaction.get("interaction_type", "")
    domain_id = interaction.get("domain_id", "")

    type_def = INTERACTION_TYPES.get(interaction_type, {})

    context_parts = [
        "=== SCHEDULED INTERACTION ===",
        f"Type: {type_def.get('name', interaction_type)}",
        f"Purpose: {type_def.get('description', '')}",
    ]

    if domain_id:
        context_parts.append(f"Domain: {domain_id}")

    context_parts.extend([
        "",
        "Keep the response focused and actionable.",
        "End with a clear next step or question.",
    ])

    return "\n".join(context_parts)


# ============ Auto-Scheduling ============

def auto_schedule_for_user(
    user_id: int,
    domains: List[str] = None
) -> Dict[str, Any]:
    """
    Automatically schedule interactions based on user activity.

    Called periodically to ensure user has relevant check-ins scheduled.
    """
    result = {
        "scheduled": [],
        "skipped": [],
    }

    try:
        # Check for inactive domains
        if domains:
            from . import coaching_domains

            for domain_id in domains:
                domain = coaching_domains.get_domain(domain_id)
                if not domain:
                    continue

                # Check if domain has recent activity
                from . import feedback_tracker
                metrics = feedback_tracker.get_recent_metrics(
                    user_id=user_id,
                    domain_id=domain_id,
                    limit=1
                )

                if not metrics:
                    # No recent activity - schedule reminder
                    existing = get_upcoming_interactions(user_id, hours=48)
                    has_reminder = any(
                        i.get("domain_id") == domain_id and
                        i.get("interaction_type") == "domain_reminder"
                        for i in existing
                    )

                    if not has_reminder:
                        interaction_id = schedule_domain_reminder(
                            user_id=user_id,
                            domain_id=domain_id,
                            domain_name=domain.name
                        )
                        if interaction_id:
                            result["scheduled"].append({
                                "type": "domain_reminder",
                                "domain": domain_id,
                                "id": interaction_id
                            })

        # Ensure weekly reflection is scheduled
        existing = get_upcoming_interactions(user_id, hours=168)
        has_reflection = any(
            i.get("interaction_type") == "reflection_prompt"
            for i in existing
        )

        if not has_reflection:
            interaction_id = schedule_weekly_reflection(user_id)
            if interaction_id:
                result["scheduled"].append({
                    "type": "reflection_prompt",
                    "id": interaction_id
                })

    except Exception as e:
        log_with_context(logger, "error", "Auto-scheduling failed", error=str(e))
        result["error"] = str(e)

    return result


# ============ Statistics ============

def get_interaction_stats(
    user_id: int,
    days: int = 30
) -> Dict[str, Any]:
    """Get interaction statistics for a user."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cutoff = datetime.utcnow() - timedelta(days=days)

            cur.execute("""
                SELECT
                    interaction_type,
                    status,
                    COUNT(*) as count
                FROM scheduled_interaction
                WHERE user_id = %s AND created_at > %s
                GROUP BY interaction_type, status
            """, (user_id, cutoff))

            stats = {"by_type": {}, "by_status": {}}

            for row in cur.fetchall():
                int_type = row["interaction_type"]
                status = row["status"]
                count = row["count"]

                if int_type not in stats["by_type"]:
                    stats["by_type"][int_type] = {}
                stats["by_type"][int_type][status] = count

                if status not in stats["by_status"]:
                    stats["by_status"][status] = 0
                stats["by_status"][status] += count

            # Calculate engagement rate
            total_executed = stats["by_status"].get("executed", 0)
            total_skipped = stats["by_status"].get("skipped", 0)
            total_pending = stats["by_status"].get("pending", 0)
            total = total_executed + total_skipped

            stats["engagement_rate"] = total_executed / total if total > 0 else 0
            stats["total_interactions"] = total + total_pending

            return stats

    except Exception as e:
        log_with_context(logger, "error", "Failed to get stats", error=str(e))
        return {}
