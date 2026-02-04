"""
Memory Service Module

Phase 16.4C: Personal Memory System
Handles timeline events, learned preferences, patterns, and relationship notes.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, date
import json
import uuid

from .observability import get_logger
from .db_safety import safe_list_query, safe_write_query

logger = get_logger("jarvis.memory")


# =============================================================================
# TIMELINE OPERATIONS
# =============================================================================

async def add_timeline_event(
    user_id: str,
    event_type: str,
    title: str,
    description: str = None,
    event_date: date = None,
    event_time: str = None,
    category: str = None,
    importance: int = 3,
    related_entities: List[Dict] = None,
    source_type: str = None,
    source_id: str = None,
    tags: List[str] = None,
    is_private: bool = False
) -> Optional[str]:
    """
    Add an event to the personal timeline.

    Returns the event ID if successful.
    """
    try:
        event_date = event_date or date.today()

        with safe_write_query('personal_timeline') as cur:
            event_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO personal_timeline (
                    id, user_id, event_type, title, description,
                    event_date, event_time, category, importance,
                    related_entities, source_type, source_id,
                    tags, is_private
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
            """, (
                event_id, user_id, event_type, title, description,
                event_date, event_time, category, importance,
                json.dumps(related_entities) if related_entities else None,
                source_type, source_id,
                tags, is_private
            ))
            return event_id

    except Exception as e:
        logger.error(f"Failed to add timeline event: {e}")
        return None


async def get_timeline(
    user_id: str,
    start_date: date = None,
    end_date: date = None,
    event_type: str = None,
    category: str = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get timeline events with optional filters.
    """
    try:
        with safe_list_query('personal_timeline') as cur:
            query = """
                SELECT id, event_type, title, description, context,
                       event_date, event_time, category, importance,
                       related_entities, source_type, tags, created_at
                FROM personal_timeline
                WHERE user_id = %s
            """
            params = [user_id]

            if start_date:
                query += " AND event_date >= %s"
                params.append(start_date)

            if end_date:
                query += " AND event_date <= %s"
                params.append(end_date)

            if event_type:
                query += " AND event_type = %s"
                params.append(event_type)

            if category:
                query += " AND category = %s"
                params.append(category)

            query += " ORDER BY event_date DESC, event_time DESC NULLS LAST LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                {
                    "id": str(row["id"]),
                    "event_type": row["event_type"],
                    "title": row["title"],
                    "description": row["description"],
                    "context": row["context"],
                    "event_date": row["event_date"].isoformat() if row["event_date"] else None,
                    "event_time": str(row["event_time"]) if row["event_time"] else None,
                    "category": row["category"],
                    "importance": row["importance"],
                    "related_entities": row["related_entities"],
                    "source_type": row["source_type"],
                    "tags": row["tags"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Failed to get timeline: {e}")
        return []


# =============================================================================
# PREFERENCE OPERATIONS
# =============================================================================

async def learn_preference(
    user_id: str,
    key: str,
    value: str,
    category: str = None,
    source: str = None
) -> bool:
    """
    Learn or update a user preference.

    Uses the database function to handle confidence updates.
    """
    try:
        with safe_write_query('user_learned_preferences') as cur:
            cur.execute("""
                SELECT update_preference_confidence(%s, %s, %s, %s)
            """, (user_id, key, value, source))

            # Update category if provided
            if category:
                cur.execute("""
                    UPDATE user_learned_preferences
                    SET preference_category = %s, updated_at = NOW()
                    WHERE user_id = %s AND preference_key = %s
                """, (category, user_id, key))

            return True

    except Exception as e:
        logger.error(f"Failed to learn preference: {e}")
        return False


async def get_preference(user_id: str, key: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific learned preference.
    """
    try:
        with safe_list_query('user_learned_preferences') as cur:
            cur.execute("""
                SELECT preference_key, preference_value, preference_category,
                       confidence, observation_count, last_confirmed_at
                FROM user_learned_preferences
                WHERE user_id = %s AND preference_key = %s AND is_active = true
            """, (user_id, key))

            row = cur.fetchone()
            if row:
                return {
                    "key": row["preference_key"],
                    "value": row["preference_value"],
                    "category": row["preference_category"],
                    "confidence": float(row["confidence"]),
                    "observation_count": row["observation_count"],
                    "last_confirmed": row["last_confirmed_at"].isoformat() if row["last_confirmed_at"] else None
                }
            return None

    except Exception as e:
        logger.error(f"Failed to get preference: {e}")
        return None


async def get_all_preferences(
    user_id: str,
    category: str = None,
    min_confidence: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Get all learned preferences for a user.
    """
    try:
        with safe_list_query('user_learned_preferences') as cur:
            query = """
                SELECT preference_key, preference_value, preference_category,
                       confidence, observation_count, last_confirmed_at
                FROM user_learned_preferences
                WHERE user_id = %s AND is_active = true AND confidence >= %s
            """
            params = [user_id, min_confidence]

            if category:
                query += " AND preference_category = %s"
                params.append(category)

            query += " ORDER BY confidence DESC, observation_count DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                {
                    "key": row["preference_key"],
                    "value": row["preference_value"],
                    "category": row["preference_category"],
                    "confidence": float(row["confidence"]),
                    "observation_count": row["observation_count"],
                    "last_confirmed": row["last_confirmed_at"].isoformat() if row["last_confirmed_at"] else None
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Failed to get preferences: {e}")
        return []


async def confirm_preference(user_id: str, key: str, source: str = "user_confirmation") -> bool:
    """
    Explicitly confirm a preference (increases confidence).

    Phase 16.4D: Preference Calibration
    """
    try:
        pref = await get_preference(user_id, key)
        if pref:
            # Re-learn with same value to increase confidence
            return await learn_preference(
                user_id=user_id,
                key=key,
                value=pref["value"],
                source=source
            )
        return False
    except Exception as e:
        logger.error(f"Failed to confirm preference: {e}")
        return False


async def contradict_preference(
    user_id: str,
    key: str,
    new_value: str = None,
    source: str = "user_contradiction"
) -> bool:
    """
    Explicitly contradict a preference (decreases confidence or replaces value).

    Phase 16.4D: Preference Calibration
    """
    try:
        if new_value:
            # Learn new value (DB function handles confidence adjustment)
            return await learn_preference(
                user_id=user_id,
                key=key,
                value=new_value,
                source=source
            )
        else:
            # Just decrease confidence without new value
            with safe_write_query('user_learned_preferences') as cur:
                cur.execute("""
                    UPDATE user_learned_preferences
                    SET confidence = GREATEST(confidence - 0.15, 0.2),
                        updated_at = NOW()
                    WHERE user_id = %s AND preference_key = %s
                """, (user_id, key))
                return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to contradict preference: {e}")
        return False


async def decay_stale_preferences(user_id: str, days_threshold: int = 60) -> int:
    """
    Decrease confidence for preferences not confirmed recently.

    Phase 16.4D: Preference Calibration - time-based decay
    Returns number of preferences decayed.
    """
    try:
        with safe_write_query('user_learned_preferences') as cur:
            cur.execute("""
                UPDATE user_learned_preferences
                SET confidence = GREATEST(confidence - 0.05, 0.3),
                    updated_at = NOW()
                WHERE user_id = %s
                  AND is_active = true
                  AND confidence > 0.3
                  AND (last_confirmed_at IS NULL OR last_confirmed_at < NOW() - INTERVAL '%s days')
                RETURNING preference_key
            """, (user_id, days_threshold))
            rows = cur.fetchall()

            if rows:
                logger.info(f"Decayed {len(rows)} stale preferences for {user_id}")

            return len(rows)
    except Exception as e:
        logger.error(f"Failed to decay preferences: {e}")
        return 0


# =============================================================================
# PATTERN OPERATIONS
# =============================================================================

async def record_pattern(
    user_id: str,
    pattern_type: str,
    pattern_name: str,
    pattern_data: Dict[str, Any],
    description: str = None,
    time_scope: str = None,
    confidence: float = 0.5
) -> Optional[str]:
    """
    Record a detected pattern.
    """
    try:
        with safe_write_query('detected_patterns') as cur:
            pattern_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO detected_patterns (
                    id, user_id, pattern_type, pattern_name, description,
                    pattern_data, confidence, time_scope
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                pattern_id, user_id, pattern_type, pattern_name, description,
                json.dumps(pattern_data), confidence, time_scope
            ))
            return pattern_id

    except Exception as e:
        logger.error(f"Failed to record pattern: {e}")
        return None


async def get_active_patterns(
    user_id: str,
    pattern_type: str = None,
    min_confidence: float = 0.4
) -> List[Dict[str, Any]]:
    """
    Get active patterns for a user.
    """
    try:
        with safe_list_query('detected_patterns') as cur:
            query = """
                SELECT id, pattern_type, pattern_name, description,
                       pattern_data, confidence, time_scope,
                       observation_count, last_matched_at, is_confirmed
                FROM detected_patterns
                WHERE user_id = %s AND is_active = true AND confidence >= %s
            """
            params = [user_id, min_confidence]

            if pattern_type:
                query += " AND pattern_type = %s"
                params.append(pattern_type)

            query += " ORDER BY confidence DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                {
                    "id": str(row["id"]),
                    "type": row["pattern_type"],
                    "name": row["pattern_name"],
                    "description": row["description"],
                    "data": row["pattern_data"],
                    "confidence": float(row["confidence"]),
                    "time_scope": row["time_scope"],
                    "observation_count": row["observation_count"],
                    "last_matched": row["last_matched_at"].isoformat() if row["last_matched_at"] else None,
                    "confirmed": row["is_confirmed"]
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Failed to get patterns: {e}")
        return []


# =============================================================================
# INTERACTION QUALITY
# =============================================================================

async def record_interaction_quality(
    session_id: str = None,
    message_id: str = None,
    response_helpful: bool = None,
    task_completed: bool = None,
    follow_up_needed: bool = None,
    response_length: int = None,
    response_time_seconds: int = None,
    rating: int = None,
    feedback_text: str = None,
    query_type: str = None,
    namespace: str = None
) -> bool:
    """
    Record interaction quality signals.
    """
    try:
        # Compute inferred satisfaction
        satisfaction = 0.5  # Neutral default

        if response_helpful is not None:
            satisfaction += 0.2 if response_helpful else -0.2

        if task_completed is not None:
            satisfaction += 0.15 if task_completed else -0.1

        if follow_up_needed is not None:
            satisfaction += -0.1 if follow_up_needed else 0.05

        if rating is not None:
            satisfaction = (satisfaction + (rating - 3) * 0.2) / 2

        satisfaction = max(0.0, min(1.0, satisfaction))

        with safe_write_query('interaction_quality') as cur:
            cur.execute("""
                INSERT INTO interaction_quality (
                    session_id, message_id, response_helpful, task_completed,
                    follow_up_needed, response_length, response_time_seconds,
                    rating, feedback_text, query_type, namespace,
                    inferred_satisfaction
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                session_id, message_id, response_helpful, task_completed,
                follow_up_needed, response_length, response_time_seconds,
                rating, feedback_text, query_type, namespace,
                satisfaction
            ))
            return True

    except Exception as e:
        logger.error(f"Failed to record interaction quality: {e}")
        return False


async def get_quality_summary(days: int = 30) -> Dict[str, Any]:
    """
    Get interaction quality summary.
    """
    try:
        with safe_list_query('interaction_quality') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_interactions,
                    AVG(inferred_satisfaction) as avg_satisfaction,
                    COUNT(*) FILTER (WHERE response_helpful = true) as helpful_count,
                    COUNT(*) FILTER (WHERE response_helpful = false) as unhelpful_count,
                    COUNT(*) FILTER (WHERE task_completed = true) as completed_count,
                    AVG(rating) FILTER (WHERE rating IS NOT NULL) as avg_rating
                FROM interaction_quality
                WHERE timestamp > NOW() - INTERVAL '%s days'
            """, (days,))

            row = cur.fetchone()

            return {
                "total_interactions": row["total_interactions"] or 0,
                "avg_satisfaction": round(float(row["avg_satisfaction"] or 0.5), 2),
                "helpful_count": row["helpful_count"] or 0,
                "unhelpful_count": row["unhelpful_count"] or 0,
                "completed_count": row["completed_count"] or 0,
                "avg_rating": round(float(row["avg_rating"]), 1) if row["avg_rating"] else None,
                "period_days": days
            }

    except Exception as e:
        logger.error(f"Failed to get quality summary: {e}")
        return {}


# =============================================================================
# RELATIONSHIP NOTES
# =============================================================================

async def update_relationship_note(
    user_id: str,
    person_name: str,
    person_email: str = None,
    person_company: str = None,
    relationship_type: str = None,
    notes: str = None,
    learned_facts: List[Dict] = None,
    vip_status: bool = None,
    interaction_frequency: str = None
) -> bool:
    """
    Update or create a relationship note.
    """
    try:
        with safe_write_query('relationship_notes') as cur:
            cur.execute("""
                INSERT INTO relationship_notes (
                    user_id, person_name, person_email, person_company,
                    relationship_type, notes, learned_facts, vip_status,
                    interaction_frequency
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, person_name) DO UPDATE SET
                    person_email = COALESCE(EXCLUDED.person_email, relationship_notes.person_email),
                    person_company = COALESCE(EXCLUDED.person_company, relationship_notes.person_company),
                    relationship_type = COALESCE(EXCLUDED.relationship_type, relationship_notes.relationship_type),
                    notes = COALESCE(EXCLUDED.notes, relationship_notes.notes),
                    learned_facts = COALESCE(EXCLUDED.learned_facts, relationship_notes.learned_facts),
                    vip_status = COALESCE(EXCLUDED.vip_status, relationship_notes.vip_status),
                    interaction_frequency = COALESCE(EXCLUDED.interaction_frequency, relationship_notes.interaction_frequency),
                    updated_at = NOW()
            """, (
                user_id, person_name, person_email, person_company,
                relationship_type, notes,
                json.dumps(learned_facts) if learned_facts else None,
                vip_status, interaction_frequency
            ))
            return True

    except Exception as e:
        logger.error(f"Failed to update relationship note: {e}")
        return False


async def get_relationship_note(user_id: str, person_name: str) -> Optional[Dict[str, Any]]:
    """
    Get notes about a specific person.
    """
    try:
        with safe_list_query('relationship_notes') as cur:
            cur.execute("""
                SELECT person_name, person_email, person_company,
                       relationship_type, notes, learned_facts,
                       communication_preferences, vip_status,
                       interaction_frequency, last_interaction_date,
                       last_interaction_summary
                FROM relationship_notes
                WHERE user_id = %s AND person_name ILIKE %s
                LIMIT 1
            """, (user_id, f"%{person_name}%"))

            row = cur.fetchone()
            if row:
                return {
                    "name": row["person_name"],
                    "email": row["person_email"],
                    "company": row["person_company"],
                    "relationship_type": row["relationship_type"],
                    "notes": row["notes"],
                    "learned_facts": row["learned_facts"],
                    "communication_preferences": row["communication_preferences"],
                    "vip": row["vip_status"],
                    "interaction_frequency": row["interaction_frequency"],
                    "last_interaction_date": row["last_interaction_date"].isoformat() if row["last_interaction_date"] else None,
                    "last_interaction_summary": row["last_interaction_summary"]
                }
            return None

    except Exception as e:
        logger.error(f"Failed to get relationship note: {e}")
        return None


async def get_vip_contacts(user_id: str) -> List[Dict[str, Any]]:
    """
    Get all VIP contacts.
    """
    try:
        with safe_list_query('relationship_notes') as cur:
            cur.execute("""
                SELECT person_name, person_email, person_company,
                       relationship_type, vip_status, last_interaction_date
                FROM relationship_notes
                WHERE user_id = %s AND vip_status = true
                ORDER BY last_interaction_date DESC NULLS LAST
            """, (user_id,))

            return [
                {
                    "name": row["person_name"],
                    "email": row["person_email"],
                    "company": row["person_company"],
                    "relationship_type": row["relationship_type"],
                    "last_interaction": row["last_interaction_date"].isoformat() if row["last_interaction_date"] else None
                }
                for row in cur.fetchall()
            ]

    except Exception as e:
        logger.error(f"Failed to get VIP contacts: {e}")
        return []
