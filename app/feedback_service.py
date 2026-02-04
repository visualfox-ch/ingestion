"""
Feedback Service Module

Phase 16.4A: Feedback Loop System
Handles user feedback collection, decision tracking, and self-improvement.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import uuid

from .observability import get_logger
from .db_safety import safe_list_query, safe_write_query

logger = get_logger("jarvis.feedback")


# =============================================================================
# FEEDBACK COLLECTION
# =============================================================================

async def submit_feedback(
    user_id: str,
    feedback_type: str,
    rating: int = None,
    thumbs_up: bool = None,
    feedback_text: str = None,
    feedback_tags: List[str] = None,
    session_id: str = None,
    context_type: str = None,
    original_query: str = None,
    original_response: str = None
) -> Optional[str]:
    """
    Submit user feedback.

    Returns feedback ID if successful.
    Phase 16.4: Also checks for negative feedback patterns and triggers improvement logging.
    """
    try:
        with safe_write_query('user_feedback') as cur:
            feedback_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO user_feedback (
                    feedback_type, rating, thumbs_up, feedback_text,
                    feedback_tags, session_id, context_type,
                    original_query, original_response
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                feedback_type, rating, thumbs_up, feedback_text,
                feedback_tags, session_id, context_type,
                original_query, original_response
            ))
            result = cur.fetchone()
            feedback_id = str(result['id']) if result else None

        # Phase 16.4: Quality → Improvement Bridge (Pattern-based)
        if feedback_id:
            is_negative = (rating is not None and rating < 3) or (thumbs_up is False)
            if is_negative:
                await _check_and_trigger_improvement(
                    user_id=user_id,
                    current_feedback={
                        "id": feedback_id,
                        "rating": rating,
                        "thumbs_up": thumbs_up,
                        "text": feedback_text,
                        "tags": feedback_tags,
                        "session_id": session_id,
                        "context_type": context_type
                    }
                )

        return feedback_id

    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        return None


async def _check_and_trigger_improvement(
    user_id: str,
    current_feedback: Dict[str, Any],
    threshold: int = 3,
    hours: int = 24
) -> bool:
    """
    Check for negative feedback pattern and trigger improvement log if threshold met.

    Jarvis Best Practice: Only surface patterns (3+ in 24h), not single incidents.
    """
    try:
        # Count recent negative feedback
        with safe_list_query('user_feedback') as cur:
            cur.execute("""
                SELECT COUNT(*) as neg_count,
                       array_agg(feedback_text) FILTER (WHERE feedback_text IS NOT NULL) as texts,
                       array_agg(feedback_tags) FILTER (WHERE feedback_tags IS NOT NULL) as all_tags
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s hours'
                  AND (rating < 3 OR thumbs_up = false)
            """, (hours,))
            row = cur.fetchone()

            neg_count = row['neg_count'] or 0
            texts = row['texts'] or []
            all_tags = row['all_tags'] or []

        # Pattern detected?
        if neg_count >= threshold:
            # Build evidence summary
            evidence = f"Pattern detected: {neg_count} negative feedback in {hours}h. "
            if texts:
                evidence += f"Comments: {'; '.join([t for t in texts if t][:3])}. "
            if all_tags:
                flat_tags = [tag for sublist in all_tags if sublist for tag in sublist]
                if flat_tags:
                    unique_tags = list(set(flat_tags))[:5]
                    evidence += f"Tags: {', '.join(unique_tags)}"

            # Trigger improvement log
            await log_improvement(
                improvement_type="feedback_pattern",
                description=f"Negative feedback pattern detected ({neg_count} in {hours}h)",
                evidence_summary=evidence,
                expected_impact="Review and address recurring issues",
                status="proposed"
            )

            logger.info(f"Improvement logged: {neg_count} negative feedback pattern detected")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to check improvement trigger: {e}")
        return False


async def submit_quick_feedback(
    user_id: str,
    feedback_type: str,
    thumbs_up: bool,
    session_id: str = None,
    tags: List[str] = None
) -> Optional[str]:
    """
    Submit quick thumbs up/down feedback.
    """
    return await submit_feedback(
        user_id=user_id,
        feedback_type=feedback_type,
        thumbs_up=thumbs_up,
        session_id=session_id,
        feedback_tags=tags
    )


async def get_feedback_summary(user_id: str = "micha", days: int = 30) -> Dict[str, Any]:
    """
    Get feedback summary statistics.
    """
    try:
        requested_user_id = user_id if user_id else None

        with safe_list_query("user_feedback") as cur:
            # NOTE:
            # Some installations have `user_feedback.user_id` as INTEGER while the runtime `user_id`
            # can be a string (e.g. "system" or a Telegram ID). Use a safe cast to avoid
            # "operator does not exist: integer = character varying" errors.
            cur.execute(
                """
                SELECT
                    COUNT(*)::BIGINT AS total_feedback,
                    ROUND(AVG(rating)::NUMERIC, 2) AS avg_rating,
                    COUNT(*) FILTER (WHERE thumbs_up = true OR rating >= 4)::BIGINT AS positive_count,
                    COUNT(*) FILTER (WHERE thumbs_up = false OR rating <= 2)::BIGINT AS negative_count,
                    (
                        SELECT COALESCE(ARRAY_AGG(tag), ARRAY[]::TEXT[])
                        FROM (
                            SELECT UNNEST(feedback_tags) AS tag
                            FROM user_feedback
                            WHERE created_at > NOW() - make_interval(days => %s)
                              AND (%s IS NULL OR user_id::TEXT = %s)
                              AND feedback_tags IS NOT NULL
                            GROUP BY tag
                            ORDER BY COUNT(*) DESC
                            LIMIT 5
                        ) t
                    ) AS top_tags
                FROM user_feedback
                WHERE created_at > NOW() - make_interval(days => %s)
                  AND (%s IS NULL OR user_id::TEXT = %s)
                """,
                (days, requested_user_id, requested_user_id, days, requested_user_id, requested_user_id),
            )
            row = cur.fetchone() or {}

        return {
            "total_feedback": row.get("total_feedback") or 0,
            "avg_rating": float(row["avg_rating"]) if row.get("avg_rating") is not None else None,
            "positive_count": row.get("positive_count") or 0,
            "negative_count": row.get("negative_count") or 0,
            "top_tags": row.get("top_tags") or [],
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Failed to get feedback summary: {e}")
        return {}


async def get_recent_feedback(
    user_id: str = "micha",
    feedback_type: str = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get recent feedback entries.
    """
    try:
        with safe_list_query('user_feedback') as cur:
            query = """
                SELECT id, feedback_type, rating, thumbs_up, feedback_text,
                       feedback_tags, context_type, created_at
                FROM user_feedback
                WHERE 1=1
            """
            params = []

            if feedback_type:
                query += " AND feedback_type = %s"
                params.append(feedback_type)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)

            return [
                {
                    "id": str(row["id"]),
                    "type": row["feedback_type"],
                    "rating": row["rating"],
                    "thumbs_up": row["thumbs_up"],
                    "text": row["feedback_text"],
                    "tags": row["feedback_tags"],
                    "context_type": row["context_type"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in cur.fetchall()
            ]

    except Exception as e:
        logger.error(f"Failed to get recent feedback: {e}")
        return []


# =============================================================================
# DECISION TRACKING
# =============================================================================

async def record_decision(
    user_id: str,
    decision_type: str,
    decision_description: str,
    chosen_option: str = None,
    options_considered: List[Dict] = None,
    key_factors: List[str] = None,
    time_pressure: str = None,
    confidence_level: int = None,
    context_notes: str = None,
    related_entities: List[Dict] = None
) -> Optional[str]:
    """
    Record a decision for future learning.
    """
    try:
        with safe_write_query('decision_history') as cur:
            decision_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO decision_history (
                    id, user_id, decision_type, decision_description,
                    chosen_option, options_considered, key_factors,
                    time_pressure, confidence_level, context_notes,
                    related_entities
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                decision_id, user_id, decision_type, decision_description,
                chosen_option,
                json.dumps(options_considered) if options_considered else None,
                key_factors, time_pressure, confidence_level, context_notes,
                json.dumps(related_entities) if related_entities else None
            ))
            return decision_id

    except Exception as e:
        logger.error(f"Failed to record decision: {e}")
        return None


async def update_decision_outcome(
    decision_id: str,
    outcome_status: str,
    outcome_notes: str = None
) -> bool:
    """
    Update the outcome of a recorded decision.
    """
    try:
        with safe_write_query('decision_history') as cur:
            cur.execute("""
                UPDATE decision_history
                SET outcome_status = %s,
                    outcome_notes = %s,
                    outcome_recorded_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
            """, (outcome_status, outcome_notes, decision_id))
            return cur.rowcount > 0

    except Exception as e:
        logger.error(f"Failed to update decision outcome: {e}")
        return False


async def get_decision_history(
    user_id: str = "micha",
    decision_type: str = None,
    outcome_status: str = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get decision history.
    """
    try:
        with safe_list_query('decision_history') as cur:
            query = """
                SELECT id, decision_type, decision_description,
                       chosen_option, key_factors, time_pressure,
                       confidence_level, outcome_status, outcome_notes,
                       created_at, outcome_recorded_at
                FROM decision_history
                WHERE user_id = %s
            """
            params = [user_id]

            if decision_type:
                query += " AND decision_type = %s"
                params.append(decision_type)

            if outcome_status:
                query += " AND outcome_status = %s"
                params.append(outcome_status)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)

            return [
                {
                    "id": str(row["id"]),
                    "type": row["decision_type"],
                    "description": row["decision_description"],
                    "chosen_option": row["chosen_option"],
                    "key_factors": row["key_factors"],
                    "time_pressure": row["time_pressure"],
                    "confidence": row["confidence_level"],
                    "outcome_status": row["outcome_status"],
                    "outcome_notes": row["outcome_notes"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "outcome_at": row["outcome_recorded_at"].isoformat() if row["outcome_recorded_at"] else None
                }
                for row in cur.fetchall()
            ]

    except Exception as e:
        logger.error(f"Failed to get decision history: {e}")
        return []


# =============================================================================
# OUTCOME TRACKING
# =============================================================================

async def track_outcome(
    user_id: str,
    source_type: str,
    source_id: str = None,
    prediction: str = None,
    predicted_confidence: float = None,
    actual_outcome: str = None,
    outcome_quality: str = None,
    success_score: float = None,
    lessons_learned: str = None,
    should_repeat: bool = None,
    adjustment_needed: str = None
) -> Optional[str]:
    """
    Track an outcome for learning.
    """
    try:
        with safe_write_query('outcome_tracking') as cur:
            outcome_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO outcome_tracking (
                    id, user_id, source_type, source_id,
                    prediction, predicted_confidence, actual_outcome,
                    outcome_quality, success_score,
                    lessons_learned, should_repeat, adjustment_needed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                outcome_id, user_id, source_type, source_id,
                prediction, predicted_confidence, actual_outcome,
                outcome_quality, success_score,
                lessons_learned, should_repeat, adjustment_needed
            ))
            return outcome_id

    except Exception as e:
        logger.error(f"Failed to track outcome: {e}")
        return None


async def get_outcome_statistics(
    user_id: str = "micha",
    source_type: str = None,
    days: int = 30
) -> Dict[str, Any]:
    """
    Get outcome statistics for learning.
    """
    try:
        with safe_list_query('outcome_tracking') as cur:
            query = """
                SELECT
                    COUNT(*) as total_outcomes,
                    AVG(success_score) as avg_success_score,
                    COUNT(*) FILTER (WHERE outcome_quality = 'better_than_expected') as better_count,
                    COUNT(*) FILTER (WHERE outcome_quality = 'as_expected') as expected_count,
                    COUNT(*) FILTER (WHERE outcome_quality = 'worse_than_expected') as worse_count,
                    COUNT(*) FILTER (WHERE should_repeat = true) as repeat_count,
                    COUNT(*) FILTER (WHERE should_repeat = false) as dont_repeat_count
                FROM outcome_tracking
                WHERE user_id = %s
                  AND tracked_at > NOW() - INTERVAL '%s days'
            """
            params = [user_id, days]

            if source_type:
                query = query.replace("WHERE user_id", "WHERE source_type = %s AND user_id")
                params = [source_type, user_id, days]

            cur.execute(query, params)
            row = cur.fetchone()

            if row:
                return {
                    "total_outcomes": row["total_outcomes"] or 0,
                    "avg_success_score": round(float(row["avg_success_score"]), 2) if row["avg_success_score"] else None,
                    "better_than_expected": row["better_count"] or 0,
                    "as_expected": row["expected_count"] or 0,
                    "worse_than_expected": row["worse_count"] or 0,
                    "should_repeat": row["repeat_count"] or 0,
                    "should_not_repeat": row["dont_repeat_count"] or 0,
                    "period_days": days
                }

            return {}

    except Exception as e:
        logger.error(f"Failed to get outcome statistics: {e}")
        return {}


# =============================================================================
# SELF-IMPROVEMENT TRACKING
# =============================================================================

async def log_improvement(
    improvement_type: str,
    description: str,
    trigger_feedback_ids: List[str] = None,
    evidence_summary: str = None,
    expected_impact: str = None,
    status: str = "proposed"
) -> Optional[str]:
    """
    Log a self-improvement action.
    """
    try:
        with safe_write_query('self_improvement_log') as cur:
            improvement_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO self_improvement_log (
                    id, improvement_type, description,
                    trigger_feedback_ids, evidence_summary,
                    expected_impact, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                improvement_id, improvement_type, description,
                trigger_feedback_ids, evidence_summary,
                expected_impact, status
            ))
            return improvement_id

    except Exception as e:
        logger.error(f"Failed to log improvement: {e}")
        return None


async def get_improvement_log(
    improvement_type: str = None,
    status: str = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get self-improvement log entries.
    """
    try:
        with safe_list_query('self_improvement_log') as cur:
            query = """
                SELECT id, improvement_type, description, evidence_summary,
                       expected_impact, actual_impact, status, created_at
                FROM self_improvement_log
                WHERE 1=1
            """
            params = []

            if improvement_type:
                query += " AND improvement_type = %s"
                params.append(improvement_type)

            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)

            return [
                {
                    "id": str(row["id"]),
                    "type": row["improvement_type"],
                    "description": row["description"],
                    "evidence": row["evidence_summary"],
                    "expected_impact": row["expected_impact"],
                    "actual_impact": row["actual_impact"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in cur.fetchall()
            ]

    except Exception as e:
        logger.error(f"Failed to get improvement log: {e}")
        return []
