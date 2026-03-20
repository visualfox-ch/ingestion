"""
Causal Tools.

Predictive context, causal observations and patterns.
Extracted from tools.py (Phase S6).
"""
from typing import Dict, Any
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.causal")


def tool_get_predictive_context(
    context_type: str = "day_ahead",
    **kwargs
) -> Dict[str, Any]:
    """
    Get predictive insights based on patterns and upcoming events.

    Jarvis can anticipate needs based on:
    - Calendar events and their typical preparation needs
    - Historical patterns (e.g., "Mondays are usually busy")
    - Recent emotional/energy trends

    Args:
        context_type: Type of prediction (day_ahead, week_ahead, meeting_prep)

    Returns:
        Predictions, recommendations, and proactive suggestions
    """
    log_with_context(logger, "info", "Tool: get_predictive_context", context_type=context_type)
    metrics.inc("tool_get_predictive_context")

    try:
        from datetime import datetime, timedelta

        now = datetime.now()
        result = {
            "context_type": context_type,
            "generated_at": now.isoformat(),
            "predictions": [],
            "recommendations": [],
            "energy_forecast": None
        }

        # Get today's calendar
        from .postgres_state import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check for patterns about this weekday
                weekday = now.strftime("%A").lower()
                cur.execute("""
                    SELECT value, confidence
                    FROM jarvis_context
                    WHERE key LIKE %s
                    AND category = 'pattern'
                    ORDER BY confidence DESC
                    LIMIT 3
                """, (f"%{weekday}%",))
                weekday_patterns = cur.fetchall()

                for p in weekday_patterns:
                    result["predictions"].append({
                        "type": "weekday_pattern",
                        "prediction": p["value"],
                        "confidence": p["confidence"] or 0.5
                    })

                # Check recent energy/mood trends
                cur.execute("""
                    SELECT value, updated_at
                    FROM jarvis_context
                    WHERE category IN ('energy', 'mood', 'stress')
                    AND updated_at >= NOW() - INTERVAL '3 days'
                    ORDER BY updated_at DESC
                    LIMIT 5
                """)
                energy_rows = cur.fetchall()

                if energy_rows:
                    recent_states = [r["value"] for r in energy_rows]
                    # Simple trend analysis
                    if any("tired" in s.lower() or "müde" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "niedrig"
                        result["recommendations"].append("Plane Pausen ein - letzte Tage waren anstrengend")
                    elif any("stress" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "angespannt"
                        result["recommendations"].append("Fokus auf wichtigste Task, Rest delegieren oder verschieben")
                    else:
                        result["energy_forecast"] = "normal"

        # Default recommendations based on context_type
        if context_type == "day_ahead":
            result["recommendations"].extend([
                "Morgens Deep Work, nachmittags Meetings",
                "Prüfe offene Follow-ups vor erstem Meeting"
            ])
        elif context_type == "meeting_prep":
            result["recommendations"].append("Hole Person-Context für Meeting-Teilnehmer")

        return result

    except Exception as e:
        log_with_context(logger, "error", "get_predictive_context failed", error=str(e))
        return {"error": str(e)}


# Phase 20: Identity Evolution Tools MOVED to tool_modules/identity_tools.py (T006 refactor)
# Implementations: tool_get_self_model, tool_evolve_identity, tool_log_experience,
#                  tool_get_relationship, tool_update_relationship, tool_get_learning_patterns,
#                  tool_record_session_learning


def tool_record_causal_observation(
    cause_event: str,
    effect_event: str,
    cause_type: str = "event",
    effect_type: str = "outcome",
    **kwargs
) -> Dict[str, Any]:
    """Record a cause-effect observation."""
    user_id = str(kwargs.get("user_id", "1"))
    session_id = kwargs.get("session_id")

    log_with_context(logger, "info", "Tool: record_causal_observation",
                    cause=cause_event, effect=effect_event)
    metrics.inc("tool_record_causal_observation")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        return tracker.record_observation(
            user_id=user_id,
            cause_event=cause_event,
            effect_event=effect_event,
            cause_type=cause_type,
            effect_type=effect_type,
            session_id=session_id
        )
    except Exception as e:
        log_with_context(logger, "error", "record_causal_observation failed", error=str(e))
        return {"error": str(e)}


def tool_predict_from_cause(
    cause: str,
    min_confidence: float = 0.6,
    **kwargs
) -> Dict[str, Any]:
    """Predict effects from a cause."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: predict_from_cause", cause=cause)
    metrics.inc("tool_predict_from_cause")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        predictions = tracker.predict_effects(user_id, cause, min_confidence)
        return {"cause": cause, "predicted_effects": predictions, "count": len(predictions)}
    except Exception as e:
        log_with_context(logger, "error", "predict_from_cause failed", error=str(e))
        return {"error": str(e)}


def tool_get_causal_patterns(
    min_confidence: float = 0.5,
    limit: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """Get all causal patterns."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: get_causal_patterns")
    metrics.inc("tool_get_causal_patterns")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        patterns = tracker.get_all_patterns(user_id, min_confidence, 1, limit)
        return {"patterns": patterns, "count": len(patterns)}
    except Exception as e:
        log_with_context(logger, "error", "get_causal_patterns failed", error=str(e))
        return {"error": str(e)}

