"""
Jarvis Feedback Tracker - Coaching Effectiveness Measurement

Tracks:
- Implicit feedback (message patterns, engagement)
- Explicit feedback (ratings, reactions)
- Goal progress over time
- Domain-specific effectiveness
"""
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.feedback")


# ============ Data Classes ============

@dataclass
class FeedbackMetric:
    """A single feedback metric"""
    user_id: int
    domain_id: str
    metric_type: str
    metric_value: float
    context: Dict[str, Any] = None
    created_at: datetime = None


@dataclass
class EffectivenessScore:
    """Aggregated effectiveness score for a domain"""
    domain_id: str
    overall_score: float
    engagement_score: float
    goal_progress_score: float
    satisfaction_score: float
    sample_size: int


# ============ Implicit Feedback ============

def track_message_engagement(
    user_id: int,
    domain_id: str,
    message_length: int,
    response_time_ms: int,
    had_followup: bool,
    tools_used: List[str] = None
) -> bool:
    """
    Track implicit engagement metrics from a conversation turn.

    Higher engagement signals:
    - Longer messages = more invested
    - Quick response = engaged
    - Follow-up questions = finding value
    - Tool usage = complex task
    """
    try:
        # Calculate engagement score (0-1)
        length_score = min(message_length / 500, 1.0)  # Cap at 500 chars
        response_score = max(0, 1 - (response_time_ms / 60000))  # Penalty for slow response
        followup_score = 1.0 if had_followup else 0.5
        tool_score = 0.8 if tools_used else 0.5

        engagement_value = (length_score + response_score + followup_score + tool_score) / 4

        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="engagement",
            metric_value=engagement_value,
            context={
                "message_length": message_length,
                "response_time_ms": response_time_ms,
                "had_followup": had_followup,
                "tools_used": tools_used or []
            }
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to track engagement", error=str(e))
        return False


def track_session_depth(
    user_id: int,
    domain_id: str,
    turns_in_session: int,
    topics_covered: List[str],
    session_duration_minutes: int
) -> bool:
    """
    Track session depth as a proxy for value.

    Deeper sessions = more engagement = more value.
    """
    try:
        # Calculate depth score
        turns_score = min(turns_in_session / 10, 1.0)  # Cap at 10 turns
        topics_score = min(len(topics_covered) / 3, 1.0)  # Cap at 3 topics
        duration_score = min(session_duration_minutes / 30, 1.0)  # Cap at 30 min

        depth_value = (turns_score + topics_score + duration_score) / 3

        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="session_depth",
            metric_value=depth_value,
            context={
                "turns": turns_in_session,
                "topics": topics_covered,
                "duration_minutes": session_duration_minutes
            }
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to track session depth", error=str(e))
        return False


# ============ Explicit Feedback ============

def record_rating(
    user_id: int,
    domain_id: str,
    rating: int,
    context: str = None
) -> bool:
    """
    Record explicit user rating (1-5 scale).
    """
    if rating < 1 or rating > 5:
        return False

    try:
        # Normalize to 0-1
        rating_value = (rating - 1) / 4

        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="explicit_rating",
            metric_value=rating_value,
            context={"raw_rating": rating, "context": context}
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to record rating", error=str(e))
        return False


def record_reaction(
    user_id: int,
    domain_id: str,
    reaction_type: str,
    message_id: str = None
) -> bool:
    """
    Record user reaction (thumbs up, helpful, etc.)
    """
    reaction_values = {
        "thumbs_up": 1.0,
        "helpful": 0.9,
        "interesting": 0.7,
        "neutral": 0.5,
        "thumbs_down": 0.0,
        "not_helpful": 0.1,
        "confusing": 0.2,
    }

    value = reaction_values.get(reaction_type, 0.5)

    try:
        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="reaction",
            metric_value=value,
            context={"reaction_type": reaction_type, "message_id": message_id}
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to record reaction", error=str(e))
        return False


def record_goal_progress(
    user_id: int,
    domain_id: str,
    goal_id: int,
    progress_delta: float,
    notes: str = None
) -> bool:
    """
    Record progress towards a goal.

    progress_delta: Change in progress (e.g., 0.1 = 10% progress made)
    """
    try:
        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="goal_progress",
            metric_value=progress_delta,
            context={"goal_id": goal_id, "notes": notes}
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to record goal progress", error=str(e))
        return False


def record_action_taken(
    user_id: int,
    domain_id: str,
    action_type: str,
    action_details: Dict[str, Any] = None
) -> bool:
    """
    Record when user takes action based on coaching.

    High-value signal that coaching led to action.
    """
    action_values = {
        "implemented_suggestion": 1.0,
        "scheduled_task": 0.9,
        "created_document": 0.8,
        "sent_message": 0.8,
        "started_workout": 0.9,
        "completed_goal": 1.0,
        "set_reminder": 0.6,
    }

    value = action_values.get(action_type, 0.7)

    try:
        return _store_metric(
            user_id=user_id,
            domain_id=domain_id,
            metric_type="action_taken",
            metric_value=value,
            context={"action_type": action_type, "details": action_details or {}}
        )
    except Exception as e:
        log_with_context(logger, "error", "Failed to record action", error=str(e))
        return False


# ============ Effectiveness Calculation ============

def calculate_domain_effectiveness(
    user_id: int,
    domain_id: str,
    days: int = 30
) -> Optional[EffectivenessScore]:
    """
    Calculate overall effectiveness score for a domain.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get metrics by type
            cur.execute("""
                SELECT metric_type, AVG(metric_value) as avg_value, COUNT(*) as count
                FROM coaching_effectiveness
                WHERE user_id = %s AND domain_id = %s AND created_at > %s
                GROUP BY metric_type
            """, (user_id, domain_id, cutoff))

            metrics = {row["metric_type"]: {"avg": row["avg_value"], "count": row["count"]}
                      for row in cur.fetchall()}

            if not metrics:
                return None

            # Calculate component scores
            engagement = metrics.get("engagement", {}).get("avg", 0.5)
            session_depth = metrics.get("session_depth", {}).get("avg", 0.5)
            ratings = metrics.get("explicit_rating", {}).get("avg", 0.5)
            reactions = metrics.get("reaction", {}).get("avg", 0.5)
            goal_progress = metrics.get("goal_progress", {}).get("avg", 0.5)
            actions = metrics.get("action_taken", {}).get("avg", 0.5)

            # Weighted overall score
            engagement_score = (engagement + session_depth) / 2
            satisfaction_score = (ratings + reactions) / 2
            goal_progress_score = (goal_progress + actions) / 2

            overall = (
                engagement_score * 0.3 +
                satisfaction_score * 0.3 +
                goal_progress_score * 0.4
            )

            total_samples = sum(m.get("count", 0) for m in metrics.values())

            return EffectivenessScore(
                domain_id=domain_id,
                overall_score=overall,
                engagement_score=engagement_score,
                goal_progress_score=goal_progress_score,
                satisfaction_score=satisfaction_score,
                sample_size=total_samples
            )

    except Exception as e:
        log_with_context(logger, "error", "Failed to calculate effectiveness", error=str(e))
        return None


def get_effectiveness_trends(
    user_id: int,
    domain_id: str = None,
    weeks: int = 4
) -> List[Dict[str, Any]]:
    """
    Get effectiveness trends over time.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cutoff = datetime.utcnow() - timedelta(weeks=weeks)

            domain_filter = "AND domain_id = %s" if domain_id else ""
            params = [user_id, cutoff]
            if domain_id:
                params.insert(1, domain_id)

            cur.execute(f"""
                SELECT
                    domain_id,
                    DATE_TRUNC('week', created_at) as week,
                    AVG(metric_value) as avg_value,
                    COUNT(*) as sample_count
                FROM coaching_effectiveness
                WHERE user_id = %s {domain_filter} AND created_at > %s
                GROUP BY domain_id, DATE_TRUNC('week', created_at)
                ORDER BY week DESC
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get trends", error=str(e))
        return []


def get_domain_comparison(user_id: int, days: int = 30) -> List[Dict[str, Any]]:
    """
    Compare effectiveness across domains.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cutoff = datetime.utcnow() - timedelta(days=days)

            cur.execute("""
                SELECT
                    domain_id,
                    AVG(metric_value) as avg_effectiveness,
                    COUNT(*) as interaction_count,
                    COUNT(DISTINCT DATE(created_at)) as active_days
                FROM coaching_effectiveness
                WHERE user_id = %s AND created_at > %s
                GROUP BY domain_id
                ORDER BY avg_effectiveness DESC
            """, (user_id, cutoff))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to compare domains", error=str(e))
        return []


# ============ Insights Generation ============

def generate_effectiveness_insights(
    user_id: int,
    days: int = 30
) -> Dict[str, Any]:
    """
    Generate insights about coaching effectiveness.
    """
    insights = {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": days,
        "domains": {},
        "recommendations": [],
        "highlights": [],
    }

    try:
        comparison = get_domain_comparison(user_id, days)

        for domain_data in comparison:
            domain_id = domain_data["domain_id"]
            score = calculate_domain_effectiveness(user_id, domain_id, days)

            if score:
                insights["domains"][domain_id] = {
                    "overall_score": score.overall_score,
                    "engagement": score.engagement_score,
                    "satisfaction": score.satisfaction_score,
                    "goal_progress": score.goal_progress_score,
                    "interactions": domain_data["interaction_count"],
                    "active_days": domain_data["active_days"],
                }

                # Generate highlights
                if score.overall_score >= 0.8:
                    insights["highlights"].append(
                        f"{domain_id}: Hohe Effektivität ({score.overall_score:.0%})"
                    )
                elif score.overall_score <= 0.4:
                    insights["recommendations"].append(
                        f"{domain_id}: Coaching-Ansatz überprüfen (nur {score.overall_score:.0%})"
                    )

                # Specific recommendations
                if score.engagement_score < 0.5:
                    insights["recommendations"].append(
                        f"{domain_id}: Mehr interaktive Elemente einbauen"
                    )
                if score.goal_progress_score < 0.5:
                    insights["recommendations"].append(
                        f"{domain_id}: Kleinere, erreichbare Ziele setzen"
                    )

        # Overall recommendation
        if not insights["domains"]:
            insights["recommendations"].append(
                "Keine Daten vorhanden. Mehr Domains aktiv nutzen."
            )

    except Exception as e:
        log_with_context(logger, "error", "Failed to generate insights", error=str(e))
        insights["error"] = str(e)

    return insights


# ============ Storage ============

def _store_metric(
    user_id: int,
    domain_id: str,
    metric_type: str,
    metric_value: float,
    context: Dict[str, Any] = None
) -> bool:
    """Store a metric in the database."""
    try:
        import json
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO coaching_effectiveness
                (user_id, domain_id, metric_type, metric_value, context, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                user_id,
                domain_id,
                metric_type,
                metric_value,
                json.dumps(context) if context else None,
                datetime.utcnow()
            ))
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to store metric", error=str(e))
        return False


def get_recent_metrics(
    user_id: int,
    domain_id: str = None,
    metric_type: str = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get recent metrics for debugging/analysis."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            filters = ["user_id = %s"]
            params = [user_id]

            if domain_id:
                filters.append("domain_id = %s")
                params.append(domain_id)
            if metric_type:
                filters.append("metric_type = %s")
                params.append(metric_type)

            params.append(limit)

            cur.execute(f"""
                SELECT * FROM coaching_effectiveness
                WHERE {' AND '.join(filters)}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get metrics", error=str(e))
        return []


# ============ Person Intelligence Integration (Phase 17) ============

def track_draft_usage(
    user_id: int,
    original_draft: str,
    final_text: str,
    context: Dict[str, Any] = None,
    action_type: str = "email_draft"
) -> Dict[str, Any]:
    """
    Track how a user modifies a draft to learn preferences.

    This integrates with Person Intelligence to:
    1. Calculate edit distance and infer style preferences
    2. Record whether the draft was accepted or heavily modified
    3. Update user preferences based on modifications

    Returns learned preferences and metrics.
    """
    try:
        from . import person_intelligence

        context = context or {}
        result = {
            "tracked": True,
            "learned": [],
            "metrics": {}
        }

        # Calculate basic metrics
        if not original_draft or not final_text:
            result["tracked"] = False
            result["reason"] = "missing_text"
            return result

        original_len = len(original_draft)
        final_len = len(final_text)

        # Length ratio
        length_ratio = final_len / original_len if original_len > 0 else 1.0
        result["metrics"]["length_ratio"] = round(length_ratio, 2)

        # Simple word-level similarity (Jaccard)
        original_words = set(original_draft.lower().split())
        final_words = set(final_text.lower().split())
        if original_words or final_words:
            jaccard = len(original_words & final_words) / len(original_words | final_words)
        else:
            jaccard = 1.0
        result["metrics"]["word_similarity"] = round(jaccard, 2)

        # Acceptance threshold: high similarity means accepted
        accepted = jaccard >= 0.7
        result["metrics"]["accepted"] = accepted

        # Learn from the edit using Person Intelligence
        learned = person_intelligence.PreferenceEngine.infer_from_edit_distance(
            user_id=user_id,
            original=original_draft,
            edited=final_text,
            context={
                "action_type": action_type,
                "context_type": context.get("context_type"),
                "context_id": context.get("context_id"),
                "person": context.get("person"),
                "domain": context.get("domain")
            }
        )

        if learned and learned.get("learned"):
            result["learned"].extend(learned["learned"])

        # Track engagement for coaching effectiveness
        track_message_engagement(
            user_id=user_id,
            domain_id=context.get("domain", "general"),
            message_length=final_len,
            response_time_ms=context.get("response_time_ms", 30000),
            had_followup=False,
            tools_used=[action_type]
        )

        # Record action if accepted
        if accepted:
            record_action_taken(
                user_id=user_id,
                domain_id=context.get("domain", "general"),
                action_type="sent_message" if action_type == "email_draft" else "implemented_suggestion",
                action_details={"length_ratio": length_ratio, "similarity": jaccard}
            )

        log_with_context(logger, "info", "Draft usage tracked",
                        user_id=user_id, accepted=accepted, learned_count=len(result["learned"]))

        return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to track draft usage", error=str(e))
        return {"tracked": False, "error": str(e)}


def record_telegram_reaction(
    user_id: int,
    message_id: str,
    reaction: str,
    context: Dict[str, Any] = None
) -> bool:
    """
    Record a Telegram reaction (thumbs up/down) and update preferences.

    Reactions:
    - 👍 / thumbs_up: Positive signal
    - 👎 / thumbs_down: Negative signal
    - "too_long": Prefer shorter responses
    - "too_short": Prefer longer responses
    """
    try:
        from . import person_intelligence

        context = context or {}

        # Map reaction to preference updates
        if reaction in ["thumbs_up", "👍", "helpful"]:
            # Positive feedback - boost confidence of current preferences
            if context.get("preference_key"):
                parts = context["preference_key"].split(":")
                if len(parts) >= 2:
                    person_intelligence.PreferenceEngine.record_feedback(
                        user_id=user_id,
                        category=parts[0],
                        key=parts[1],
                        positive=True,
                        context_type=context.get("context_type"),
                        context_id=context.get("context_id")
                    )

        elif reaction in ["thumbs_down", "👎", "not_helpful"]:
            # Negative feedback - reduce confidence
            if context.get("preference_key"):
                parts = context["preference_key"].split(":")
                if len(parts) >= 2:
                    person_intelligence.PreferenceEngine.record_feedback(
                        user_id=user_id,
                        category=parts[0],
                        key=parts[1],
                        positive=False,
                        context_type=context.get("context_type"),
                        context_id=context.get("context_id")
                    )

        elif reaction == "too_long":
            # User wants shorter responses
            person_intelligence.PreferenceEngine.set_preference(
                user_id=user_id,
                category="detail_level",
                key="default",
                value={"level": "summary"},
                learned_from="inferred",
                context_type=context.get("context_type"),
                context_id=context.get("context_id")
            )

        elif reaction == "too_short":
            # User wants more detail
            person_intelligence.PreferenceEngine.set_preference(
                user_id=user_id,
                category="detail_level",
                key="default",
                value={"level": "detailed"},
                learned_from="inferred",
                context_type=context.get("context_type"),
                context_id=context.get("context_id")
            )

        # Also record for coaching effectiveness
        record_reaction(
            user_id=user_id,
            domain_id=context.get("domain", "general"),
            reaction_type=reaction,
            message_id=message_id
        )

        log_with_context(logger, "info", "Telegram reaction recorded",
                        user_id=user_id, reaction=reaction)
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to record reaction", error=str(e))
        return False
