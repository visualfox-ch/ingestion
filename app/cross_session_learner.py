"""
Cross-Session Learning for Jarvis
Persistent learning across multiple sessions.
Tracks patterns, decisions, feedback, and generates lessons.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import json
import hashlib
import os
import uuid
from .postgres_state import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.cross_session_learner")


@dataclass
class SessionLesson:
    """A lesson learned from repeated patterns across sessions"""
    lesson_id: str
    user_id: int
    lesson_key: str  # e.g., "topic_recurrence:productivity"
    lesson_text: str
    confidence: float  # 0.0-1.0
    occurrence_count: int
    first_seen: str
    last_seen: str
    affected_decisions: List[str] = None  # IDs of decisions this lesson affected
    effectiveness: float = 0.5  # 0.0-1.0, how often did this lesson help?

    def __post_init__(self):
        if self.affected_decisions is None:
            self.affected_decisions = []


@dataclass
class DecisionLog:
    """A decision Jarvis made with context"""
    decision_id: str
    user_id: int
    session_id: str
    decision_text: str
    context: str
    confidence: float  # 0.0-1.0
    outcome_known: bool = False
    outcome: Optional[str] = None
    feedback_score: Optional[float] = None  # 1-5 after outcome known
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class CrossSessionLearner:
    """
    Learns patterns and insights across user sessions.
    
    Main mechanisms:
    1. Topic Recurrence - if topic appears in 3+ sessions, create lesson
    2. Decision Outcomes - track how well decisions worked
    3. Contextual Patterns - "always happens in context X" rules
    4. Effectiveness Feedback - lessons rated by user on whether they helped
    """

    def __init__(self):
        self._init_tables()

    def _init_tables(self):
        """Initialize cross-session learning tables"""
        with get_conn() as conn:
            cursor = conn.cursor()

            # Drop existing tables only when explicitly requested (development/testing).
            # In production, this would wipe the persistent learning we are trying to build.
            reset_tables = os.getenv("JARVIS_CROSS_SESSION_RESET_TABLES", "false").lower() in ("1", "true", "yes", "on")
            if reset_tables:
                log_with_context(logger, "warning", "Cross-session learning tables reset requested (DANGEROUS)")
                cursor.execute("DROP TABLE IF EXISTS cross_session_patterns CASCADE")
                cursor.execute("DROP TABLE IF EXISTS decision_log CASCADE")
                cursor.execute("DROP TABLE IF EXISTS session_lessons CASCADE")

            # Table 1: Session Lessons (insights from recurring patterns)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_lessons (
                lesson_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                lesson_key TEXT NOT NULL,
                lesson_text TEXT NOT NULL,
                category TEXT DEFAULT 'topic_recurrence',
                confidence REAL DEFAULT 0.5,
                occurrence_count INTEGER DEFAULT 1,
                affected_decisions JSONB DEFAULT '[]',
                effectiveness REAL DEFAULT 0.5,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_lessons_user_key
            ON session_lessons(user_id, lesson_key)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_lessons_active
            ON session_lessons(active)
            """)

            # Table 2: Decision Log (Jarvis decisions with outcomes)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS decision_log (
                decision_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                decision_text TEXT NOT NULL,
                context TEXT,
                decision_category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.5,
                outcome_known INTEGER DEFAULT 0,
                outcome TEXT,
                feedback_score REAL,
                lessons_applied JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_user
            ON decision_log(user_id, outcome_known)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_session
            ON decision_log(session_id)
            """)

            # Table 3: Cross-Session Patterns (recurring themes)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS cross_session_patterns (
                pattern_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                pattern_name TEXT NOT NULL,
                pattern_description TEXT,
                detection_rule TEXT,
                session_count INTEGER DEFAULT 1,
                occurrence_dates JSONB DEFAULT '[]',
                context_samples JSONB DEFAULT '[]',
                confidence REAL DEFAULT 0.3,
                last_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_patterns_user
            ON cross_session_patterns(user_id, pattern_name)
            """)

            # Table 4: Jarvis Suggestions with Outcome Tracking (Phase 18 - Outcome Tracking System)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_suggestions (
                suggestion_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                suggestion_text TEXT NOT NULL,
                suggestion_type TEXT DEFAULT 'advice',  -- advice, task, insight, recommendation
                context TEXT,
                confidence REAL DEFAULT 0.5,
                followup_at TIMESTAMP,  -- When to check back (default 24h later)
                followup_sent INTEGER DEFAULT 0,
                outcome TEXT,  -- worked, partially, didnt_work, not_tried, null if unknown
                outcome_notes TEXT,
                outcome_recorded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suggestions_user
            ON jarvis_suggestions(user_id, created_at DESC)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suggestions_followup
            ON jarvis_suggestions(followup_at, followup_sent)
            WHERE followup_at IS NOT NULL AND followup_sent = 0
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suggestions_outcome
            ON jarvis_suggestions(outcome)
            WHERE outcome IS NOT NULL
            """)

            log_with_context(logger, "info", "Cross-session learning tables initialized")

    def log_decision(
        self,
        user_id: int,
        session_id: str,
        decision_text: str,
        context: str,
        decision_category: str = "general",
        confidence: float = 0.5,
    ) -> str:
        """
        Log a decision Jarvis made.
        Returns decision_id for later outcome tracking.
        """
        # Use a non-deterministic ID to avoid duplicate-key failures when the same
        # decision is logged multiple times (retries, repeated prompts, etc.).
        decision_id = uuid.uuid4().hex

        try:
            user_id_int = int(user_id)
        except Exception:
            user_id_int = 0

        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO decision_log
            (decision_id, user_id, session_id, decision_text, context, 
             decision_category, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (decision_id, user_id_int, session_id, decision_text, context,
             decision_category, confidence))

            log_with_context(
                logger, "info",
                f"Decision logged for user {user_id_int}",
                decision_id=decision_id,
                category=decision_category
            )

            return decision_id

    def record_decision_outcome(
        self,
        decision_id: str,
        outcome: str,
        feedback_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Record the outcome of a decision and optional feedback (1-5 scale).
        Automatically updates lesson effectiveness if this decision applied lessons.
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            # Get decision details
            cursor.execute("""
            SELECT user_id, decision_text, lessons_applied
            FROM decision_log
            WHERE decision_id = %s
            """, (decision_id,))

            result = cursor.fetchone()
            if not result:
                return {"status": "error", "reason": "Decision not found"}

            user_id, decision_text, lessons_applied = result
            lessons_applied = json.loads(lessons_applied) if isinstance(lessons_applied, str) else lessons_applied

            # Update decision
            cursor.execute("""
            UPDATE decision_log
            SET outcome_known = 1,
                outcome = %s,
                feedback_score = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE decision_id = %s
            """, (outcome, feedback_score, decision_id))

            # Update lesson effectiveness if lessons were applied
            if feedback_score and lessons_applied:
                for lesson_id in lessons_applied:
                    cursor.execute("""
                    SELECT effectiveness
                    FROM session_lessons
                    WHERE lesson_id = %s
                    """, (lesson_id,))
                    
                    lesson_result = cursor.fetchone()
                    if lesson_result:
                        current_eff = lesson_result[0]
                        # Weighted average: shift effectiveness toward feedback score (0-1 scale)
                        normalized_feedback = (feedback_score - 1) / 4  # Convert 1-5 to 0-1
                        new_eff = (current_eff * 0.8) + (normalized_feedback * 0.2)
                        
                        cursor.execute("""
                        UPDATE session_lessons
                        SET effectiveness = %s,
                            last_seen = CURRENT_TIMESTAMP
                        WHERE lesson_id = %s
                        """, (new_eff, lesson_id))

            return {
                "status": "recorded",
                "decision_id": decision_id,
                "feedback_applied": feedback_score is not None,
                "lessons_updated": len(lessons_applied)
            }

    def detect_recurring_topic(
        self,
        user_id: int,
        topic: str,
        session_id: str,
        context: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if topic recurs across sessions.
        Creates lesson if topic appears in 3+ sessions within 30 days.
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            # Get all occurrences of this topic in last 30 days
            cursor.execute("""
            SELECT COUNT(DISTINCT session_id) as session_count
            FROM decision_log
            WHERE user_id = %s
              AND decision_text LIKE %s
              AND created_at > NOW() - INTERVAL '30 days'
            """, (user_id, f"%{topic}%"))

            result = cursor.fetchone()
            session_count = result[0] if result else 0

            if session_count >= 3:
                # Create or update lesson
                lesson_key = f"topic_recurrence:{topic.lower().replace(' ', '_')}"
                lesson_id = self._generate_id(f"{user_id}_{lesson_key}")

                # Check if lesson exists
                cursor.execute("""
                SELECT lesson_id, occurrence_count FROM session_lessons
                WHERE user_id = %s AND lesson_key = %s
                """, (user_id, lesson_key))

                lesson_result = cursor.fetchone()

                if lesson_result:
                    # Update existing
                    new_count = lesson_result[1] + 1
                    cursor.execute("""
                    UPDATE session_lessons
                    SET occurrence_count = %s,
                        confidence = LEAST(confidence + 0.1, 1.0),
                        last_seen = CURRENT_TIMESTAMP
                    WHERE lesson_id = %s
                    """, (new_count, lesson_id))
                else:
                    # Create new
                    lesson_text = f"Topic '{topic}' recurs regularly across sessions. " \
                                 f"Consider proactive suggestions or dedicated time."
                    
                    cursor.execute("""
                    INSERT INTO session_lessons
                    (lesson_id, user_id, lesson_key, lesson_text, category, 
                     confidence, occurrence_count)
                    VALUES (%s, %s, %s, %s, 'topic_recurrence', 0.6, 1)
                    """, (lesson_id, user_id, lesson_key, lesson_text))

                return {
                    "status": "lesson_created",
                    "lesson_key": lesson_key,
                    "topic": topic,
                    "session_count": session_count,
                    "confidence": 0.6 if not lesson_result else min(lesson_result[1] * 0.1 + 0.6, 1.0)
                }
            
            return None

    def get_active_lessons(
        self,
        user_id: int,
        min_confidence: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Get all active lessons for a user.
        Sorted by effectiveness (how helpful they've been).
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            SELECT lesson_id, lesson_key, lesson_text, confidence, 
                   occurrence_count, effectiveness
            FROM session_lessons
            WHERE user_id = %s
              AND active = 1
              AND confidence >= %s
            ORDER BY effectiveness DESC, occurrence_count DESC
            """, (user_id, min_confidence))

            rows = cursor.fetchall()

            return [
                {
                    "lesson_id": row['lesson_id'],
                    "lesson_key": row['lesson_key'],
                    "lesson_text": row['lesson_text'],
                    "confidence": row['confidence'],
                    "occurrence_count": row['occurrence_count'],
                    "effectiveness": row['effectiveness']
                }
                for row in rows
            ]

    def get_decision_insights(
        self,
        user_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze decision quality over time.
        Returns stats on decision outcomes and feedback.
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            SELECT 
                COUNT(*) as total_decisions,
                COUNT(CASE WHEN outcome_known THEN 1 END) as outcomes_recorded,
                AVG(feedback_score) as avg_feedback,
                AVG(confidence) as avg_confidence
            FROM decision_log
            WHERE user_id = %s
              AND created_at > NOW() - INTERVAL '%s days'
            """, (user_id, days))

            row = cursor.fetchone()
            
            # Handle empty result
            if not row:
                return {
                    "total_decisions": 0,
                    "outcomes_recorded": 0,
                    "avg_feedback": 0.0,
                    "avg_confidence": 0.0,
                    "period_days": days
                }

            return {
                "total_decisions": int(row['total_decisions']) if row['total_decisions'] is not None else 0,
                "outcomes_recorded": int(row['outcomes_recorded']) if row['outcomes_recorded'] is not None else 0,
                "avg_feedback": round(float(row['avg_feedback']), 2) if row['avg_feedback'] is not None else 0.0,
                "avg_confidence": round(float(row['avg_confidence']), 2) if row['avg_confidence'] is not None else 0.0,
                "period_days": days
            }

    # ============ Suggestion Outcome Tracking (Phase 18) ============

    def log_suggestion(
        self,
        user_id: int,
        session_id: str,
        suggestion_text: str,
        suggestion_type: str = "advice",
        context: str = "",
        confidence: float = 0.5,
        followup_hours: int = 24
    ) -> str:
        """
        Log a suggestion Jarvis made for later outcome tracking.

        Args:
            user_id: The user receiving the suggestion
            session_id: Current session ID
            suggestion_text: The actual suggestion text
            suggestion_type: One of: advice, task, insight, recommendation
            context: Additional context about the suggestion
            confidence: Jarvis' confidence in this suggestion (0.0-1.0)
            followup_hours: Hours until follow-up should be sent (default 24)

        Returns:
            suggestion_id for tracking
        """
        suggestion_id = self._generate_id(f"sugg_{user_id}_{session_id}_{suggestion_text[:50]}_{datetime.now().isoformat()}")

        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO jarvis_suggestions
            (suggestion_id, user_id, session_id, suggestion_text, suggestion_type,
             context, confidence, followup_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW() + INTERVAL '%s hours')
            """,
            (suggestion_id, user_id, session_id, suggestion_text, suggestion_type,
             context, confidence, followup_hours))

            log_with_context(
                logger, "info",
                f"Suggestion logged for user {user_id}",
                suggestion_id=suggestion_id,
                suggestion_type=suggestion_type
            )

            return suggestion_id

    def record_suggestion_outcome(
        self,
        suggestion_id: str,
        outcome: str,
        outcome_notes: str = ""
    ) -> Dict[str, Any]:
        """
        Record the outcome of a suggestion.

        Args:
            suggestion_id: The suggestion to update
            outcome: One of: worked, partially, didnt_work, not_tried
            outcome_notes: Optional notes about the outcome

        Returns:
            Status dict with updated suggestion info
        """
        valid_outcomes = {"worked", "partially", "didnt_work", "not_tried"}
        if outcome not in valid_outcomes:
            return {"status": "error", "reason": f"Invalid outcome. Must be one of: {valid_outcomes}"}

        with get_conn() as conn:
            cursor = conn.cursor()

            # Update suggestion with outcome
            cursor.execute("""
            UPDATE jarvis_suggestions
            SET outcome = %s,
                outcome_notes = %s,
                outcome_recorded_at = NOW()
            WHERE suggestion_id = %s
            RETURNING user_id, suggestion_text, suggestion_type, confidence
            """, (outcome, outcome_notes, suggestion_id))

            result = cursor.fetchone()
            if not result:
                return {"status": "error", "reason": "Suggestion not found"}

            user_id, suggestion_text, suggestion_type, confidence = result

            log_with_context(
                logger, "info",
                f"Suggestion outcome recorded",
                suggestion_id=suggestion_id,
                outcome=outcome
            )

            return {
                "status": "recorded",
                "suggestion_id": suggestion_id,
                "outcome": outcome,
                "suggestion_type": suggestion_type,
                "confidence": confidence
            }

    def get_pending_followups(
        self,
        user_id: int = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get suggestions that are due for follow-up (outcome not yet recorded).

        Returns suggestions where followup_at has passed but no outcome yet.
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            if user_id:
                cursor.execute("""
                SELECT suggestion_id, user_id, session_id, suggestion_text,
                       suggestion_type, context, confidence, followup_at, created_at
                FROM jarvis_suggestions
                WHERE user_id = %s
                  AND outcome IS NULL
                  AND followup_at <= NOW()
                  AND followup_sent = 0
                ORDER BY followup_at ASC
                LIMIT %s
                """, (user_id, limit))
            else:
                cursor.execute("""
                SELECT suggestion_id, user_id, session_id, suggestion_text,
                       suggestion_type, context, confidence, followup_at, created_at
                FROM jarvis_suggestions
                WHERE outcome IS NULL
                  AND followup_at <= NOW()
                  AND followup_sent = 0
                ORDER BY followup_at ASC
                LIMIT %s
                """, (limit,))

            rows = cursor.fetchall()

            return [
                {
                    "suggestion_id": row['suggestion_id'],
                    "user_id": row['user_id'],
                    "session_id": row['session_id'],
                    "suggestion_text": row['suggestion_text'],
                    "suggestion_type": row['suggestion_type'],
                    "context": row['context'],
                    "confidence": float(row['confidence']) if row['confidence'] else 0.5,
                    "followup_at": row['followup_at'].isoformat() if row['followup_at'] else None,
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None
                }
                for row in rows
            ]

    def mark_followup_sent(self, suggestion_id: str) -> bool:
        """Mark a suggestion as having its follow-up sent."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            UPDATE jarvis_suggestions
            SET followup_sent = 1
            WHERE suggestion_id = %s
            """, (suggestion_id,))
            return cursor.rowcount > 0

    def get_suggestion_stats(
        self,
        user_id: int = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get statistics about suggestion outcomes.

        Returns counts by outcome type and effectiveness metrics.
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            user_filter = "AND user_id = %s" if user_id else ""
            params = (days, user_id) if user_id else (days,)

            cursor.execute(f"""
            SELECT
                COUNT(*) as total_suggestions,
                COUNT(CASE WHEN outcome IS NOT NULL THEN 1 END) as outcomes_recorded,
                COUNT(CASE WHEN outcome = 'worked' THEN 1 END) as worked,
                COUNT(CASE WHEN outcome = 'partially' THEN 1 END) as partially,
                COUNT(CASE WHEN outcome = 'didnt_work' THEN 1 END) as didnt_work,
                COUNT(CASE WHEN outcome = 'not_tried' THEN 1 END) as not_tried,
                AVG(confidence) as avg_confidence
            FROM jarvis_suggestions
            WHERE created_at > NOW() - INTERVAL '%s days'
            {user_filter}
            """, params)

            row = cursor.fetchone()

            if not row or row['total_suggestions'] == 0:
                return {
                    "total_suggestions": 0,
                    "outcomes_recorded": 0,
                    "by_outcome": {},
                    "effectiveness_rate": 0.0,
                    "avg_confidence": 0.0,
                    "period_days": days
                }

            total = int(row['total_suggestions'])
            outcomes_recorded = int(row['outcomes_recorded']) if row['outcomes_recorded'] else 0
            worked = int(row['worked']) if row['worked'] else 0
            partially = int(row['partially']) if row['partially'] else 0
            didnt_work = int(row['didnt_work']) if row['didnt_work'] else 0
            not_tried = int(row['not_tried']) if row['not_tried'] else 0

            # Effectiveness = (worked + 0.5*partially) / outcomes_recorded
            effective_count = worked + (partially * 0.5)
            effectiveness_rate = (effective_count / outcomes_recorded * 100) if outcomes_recorded > 0 else 0

            return {
                "total_suggestions": total,
                "outcomes_recorded": outcomes_recorded,
                "by_outcome": {
                    "worked": worked,
                    "partially": partially,
                    "didnt_work": didnt_work,
                    "not_tried": not_tried
                },
                "effectiveness_rate": round(effectiveness_rate, 1),
                "avg_confidence": round(float(row['avg_confidence']), 2) if row['avg_confidence'] else 0.0,
                "period_days": days
            }

    def get_top_working_suggestions(
        self,
        user_id: int = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get the suggestions that worked best (for weekly report).
        """
        with get_conn() as conn:
            cursor = conn.cursor()

            user_filter = "AND user_id = %s" if user_id else ""
            params = (limit, user_id) if user_id else (limit,)

            cursor.execute(f"""
            SELECT suggestion_id, user_id, suggestion_text, suggestion_type,
                   outcome, outcome_notes, confidence, created_at
            FROM jarvis_suggestions
            WHERE outcome = 'worked'
            {user_filter}
            ORDER BY outcome_recorded_at DESC
            LIMIT %s
            """, params[::-1] if user_id else params)  # Reverse params order for LIMIT

            rows = cursor.fetchall()

            return [
                {
                    "suggestion_id": row['suggestion_id'],
                    "user_id": row['user_id'],
                    "suggestion_text": row['suggestion_text'][:200] + "..." if len(row['suggestion_text']) > 200 else row['suggestion_text'],
                    "suggestion_type": row['suggestion_type'],
                    "outcome": row['outcome'],
                    "outcome_notes": row['outcome_notes'],
                    "confidence": float(row['confidence']) if row['confidence'] else 0.5,
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None
                }
                for row in rows
            ]

    def _generate_id(self, base_string: str) -> str:
        """Generate deterministic ID from string"""
        return hashlib.sha256(base_string.encode()).hexdigest()[:16]


# Singleton instance
cross_session_learner = CrossSessionLearner()

# Initialize database tables on import
try:
    cross_session_learner._init_tables()
except Exception as e:
    logger.warning(f"Failed to initialize cross-session learning tables: {e}")
