"""
Jarvis Person Intelligence Engine - Phase 17

Learns and tracks user behavioral patterns, preferences, and anomalies
to provide personalized, context-aware responses.

Components:
- BaselineTracker: Tracks statistical baselines for user behavior
- PreferenceEngine: Manages learned user preferences
- ActiveLearner: Generates targeted learning questions
- AnomalyDetector: Detects deviations from normal patterns
- ProfileAssembler: Assembles profile context for prompts
"""
import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from psycopg2.extras import Json
from .postgres_state import get_cursor
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.person_intelligence")

# Configuration
WARMUP_DAYS = 14  # Days before anomaly alerts are sent
MIN_SAMPLES_FOR_CONFIDENCE = 5  # Minimum samples before baseline is trusted
ANOMALY_THRESHOLD_ALERT = 2.0  # Z-score for proactive alerts
ANOMALY_THRESHOLD_CRITICAL = 3.0  # Z-score for critical alerts
PREFERENCE_DECAY_HALF_LIFE_DAYS = 90  # Days for preference confidence decay
MAX_QUESTIONS_PER_DAY = 2  # Maximum learning questions per day


# ============ Data Classes ============

@dataclass
class Baseline:
    """A single behavioral baseline metric"""
    metric_category: str
    metric_name: str
    expected_value: float
    std_dev: float
    confidence: float
    sample_count: int
    context_filter: Dict = field(default_factory=dict)


@dataclass
class Preference:
    """A learned user preference"""
    category: str
    key: str
    value: Any
    confidence: float
    context_type: Optional[str] = None
    context_id: Optional[str] = None
    learned_from: str = "inferred"


@dataclass
class Anomaly:
    """A detected behavioral anomaly"""
    id: int
    metric_category: str
    metric_name: str
    observed_value: float
    expected_value: float
    deviation_score: float
    severity: str
    context: Dict
    detected_at: datetime


@dataclass
class LearningQuestion:
    """A question for active learning"""
    id: int
    question_type: str
    question_text: str
    options: List[Dict]
    priority: float
    uncertainty_reason: str


# ============ Baseline Tracker ============

class BaselineTracker:
    """Tracks and updates behavioral baselines for users"""

    @staticmethod
    def record_observation(
        user_id: int,
        category: str,
        metric: str,
        value: float,
        context: Optional[Dict] = None
    ) -> Dict:
        """
        Record a new observation and update the baseline.
        Uses Welford's online algorithm for incremental mean/variance.
        """
        context = context or {}
        now = datetime.now()

        with get_cursor() as cur:
            # Get existing baseline
            cur.execute("""
                SELECT id, expected_value, std_dev, sample_count, min_observed, max_observed
                FROM user_behavioral_baseline
                WHERE user_id = %s AND metric_category = %s AND metric_name = %s
                  AND context_filter = %s
            """, (user_id, category, metric, Json(context)))
            row = cur.fetchone()

            if row:
                # Update existing baseline using Welford's algorithm
                n = row['sample_count'] + 1
                old_mean = row['expected_value']
                old_std = row['std_dev']

                # Welford's online algorithm
                delta = value - old_mean
                new_mean = old_mean + delta / n

                if n > 1:
                    # Update variance incrementally
                    old_variance = old_std ** 2 if old_std else 0
                    new_variance = ((n - 2) * old_variance + (value - old_mean) * (value - new_mean)) / (n - 1)
                    new_std = math.sqrt(max(0, new_variance))
                else:
                    new_std = 0.0

                # Update min/max
                new_min = min(row['min_observed'] or value, value)
                new_max = max(row['max_observed'] or value, value)

                # Calculate confidence (asymptotic to 1.0)
                confidence = 1 - (1 / (1 + n / MIN_SAMPLES_FOR_CONFIDENCE))

                cur.execute("""
                    UPDATE user_behavioral_baseline SET
                        expected_value = %s,
                        std_dev = %s,
                        sample_count = %s,
                        min_observed = %s,
                        max_observed = %s,
                        confidence = %s,
                        last_updated = %s
                    WHERE id = %s
                """, (new_mean, new_std, n, new_min, new_max, confidence, now, row['id']))

                # Check for anomaly
                is_anomaly = False
                deviation_score = 0.0
                if old_std > 0 and n >= MIN_SAMPLES_FOR_CONFIDENCE:
                    deviation_score = abs(value - old_mean) / old_std
                    is_anomaly = deviation_score >= ANOMALY_THRESHOLD_ALERT

                return {
                    "recorded": True,
                    "new_baseline": {
                        "expected_value": round(new_mean, 2),
                        "std_dev": round(new_std, 2),
                        "confidence": round(confidence, 2)
                    },
                    "is_anomaly": is_anomaly,
                    "deviation_score": round(deviation_score, 2)
                }
            else:
                # Create new baseline
                cur.execute("""
                    INSERT INTO user_behavioral_baseline
                    (user_id, metric_category, metric_name, expected_value, std_dev,
                     sample_count, min_observed, max_observed, confidence, context_filter)
                    VALUES (%s, %s, %s, %s, 0, 1, %s, %s, 0.1, %s)
                """, (user_id, category, metric, value, value, value, Json(context)))

                return {
                    "recorded": True,
                    "new_baseline": {
                        "expected_value": value,
                        "std_dev": 0.0,
                        "confidence": 0.1
                    },
                    "is_anomaly": False,
                    "deviation_score": 0.0
                }

    @staticmethod
    def get_baseline(
        user_id: int,
        category: str,
        metric: str,
        context: Optional[Dict] = None
    ) -> Optional[Baseline]:
        """Get a specific baseline for a user"""
        context = context or {}

        with get_cursor() as cur:
            cur.execute("""
                SELECT metric_category, metric_name, expected_value, std_dev,
                       confidence, sample_count, context_filter
                FROM user_behavioral_baseline
                WHERE user_id = %s AND metric_category = %s AND metric_name = %s
                  AND context_filter = %s
            """, (user_id, category, metric, Json(context)))
            row = cur.fetchone()

            if row:
                return Baseline(
                    metric_category=row['metric_category'],
                    metric_name=row['metric_name'],
                    expected_value=row['expected_value'],
                    std_dev=row['std_dev'],
                    confidence=row['confidence'],
                    sample_count=row['sample_count'],
                    context_filter=row['context_filter'] or {}
                )
            return None

    @staticmethod
    def get_all_baselines(user_id: int, category: Optional[str] = None) -> List[Baseline]:
        """Get all baselines for a user, optionally filtered by category"""
        with get_cursor() as cur:
            if category:
                cur.execute("""
                    SELECT metric_category, metric_name, expected_value, std_dev,
                           confidence, sample_count, context_filter
                    FROM user_behavioral_baseline
                    WHERE user_id = %s AND metric_category = %s
                    ORDER BY metric_category, metric_name
                """, (user_id, category))
            else:
                cur.execute("""
                    SELECT metric_category, metric_name, expected_value, std_dev,
                           confidence, sample_count, context_filter
                    FROM user_behavioral_baseline
                    WHERE user_id = %s
                    ORDER BY metric_category, metric_name
                """, (user_id,))

            return [
                Baseline(
                    metric_category=row['metric_category'],
                    metric_name=row['metric_name'],
                    expected_value=row['expected_value'],
                    std_dev=row['std_dev'],
                    confidence=row['confidence'],
                    sample_count=row['sample_count'],
                    context_filter=row['context_filter'] or {}
                )
                for row in cur.fetchall()
            ]

    @staticmethod
    def calculate_deviation(
        user_id: int,
        category: str,
        metric: str,
        value: float
    ) -> Tuple[float, str]:
        """
        Calculate Z-score deviation for a value.
        Returns (z_score, severity)
        """
        baseline = BaselineTracker.get_baseline(user_id, category, metric)

        if not baseline or baseline.std_dev == 0 or baseline.sample_count < MIN_SAMPLES_FOR_CONFIDENCE:
            return 0.0, "unknown"

        z_score = abs(value - baseline.expected_value) / baseline.std_dev

        if z_score >= ANOMALY_THRESHOLD_CRITICAL:
            severity = "critical"
        elif z_score >= ANOMALY_THRESHOLD_ALERT:
            severity = "elevated"
        else:
            severity = "normal"

        return round(z_score, 2), severity


# ============ Preference Engine ============

class PreferenceEngine:
    """Manages learned user preferences"""

    @staticmethod
    def get_preference(
        user_id: int,
        category: str,
        key: str,
        context_type: Optional[str] = None,
        context_id: Optional[str] = None
    ) -> Optional[Preference]:
        """Get a specific preference, with fallback to general preference"""
        with get_cursor() as cur:
            # Try context-specific first
            if context_type and context_id:
                cur.execute("""
                    SELECT preference_category, preference_key, preference_value,
                           confidence, context_type, context_id, learned_from
                    FROM user_preferences
                    WHERE user_id = %s AND preference_category = %s AND preference_key = %s
                      AND context_type = %s AND context_id = %s
                """, (user_id, category, key, context_type, context_id))
                row = cur.fetchone()
                if row:
                    return Preference(
                        category=row['preference_category'],
                        key=row['preference_key'],
                        value=row['preference_value'],
                        confidence=row['confidence'],
                        context_type=row['context_type'],
                        context_id=row['context_id'],
                        learned_from=row['learned_from']
                    )

            # Fallback to general preference
            cur.execute("""
                SELECT preference_category, preference_key, preference_value,
                       confidence, context_type, context_id, learned_from
                FROM user_preferences
                WHERE user_id = %s AND preference_category = %s AND preference_key = %s
                  AND context_type IS NULL AND context_id IS NULL
            """, (user_id, category, key))
            row = cur.fetchone()

            if row:
                return Preference(
                    category=row['preference_category'],
                    key=row['preference_key'],
                    value=row['preference_value'],
                    confidence=row['confidence'],
                    context_type=row['context_type'],
                    context_id=row['context_id'],
                    learned_from=row['learned_from']
                )
            return None

    @staticmethod
    def get_preferences(
        user_id: int,
        category: Optional[str] = None,
        context_type: Optional[str] = None,
        context_id: Optional[str] = None
    ) -> List[Preference]:
        """Get all preferences for a user with optional filters"""
        with get_cursor() as cur:
            conditions = ["user_id = %s"]
            params = [user_id]

            if category:
                conditions.append("preference_category = %s")
                params.append(category)

            if context_type:
                conditions.append("context_type = %s")
                params.append(context_type)
                if context_id:
                    conditions.append("context_id = %s")
                    params.append(context_id)

            cur.execute(f"""
                SELECT preference_category, preference_key, preference_value,
                       confidence, context_type, context_id, learned_from
                FROM user_preferences
                WHERE {' AND '.join(conditions)}
                ORDER BY preference_category, preference_key
            """, params)

            return [
                Preference(
                    category=row['preference_category'],
                    key=row['preference_key'],
                    value=row['preference_value'],
                    confidence=row['confidence'],
                    context_type=row['context_type'],
                    context_id=row['context_id'],
                    learned_from=row['learned_from']
                )
                for row in cur.fetchall()
            ]

    @staticmethod
    def set_preference(
        user_id: int,
        category: str,
        key: str,
        value: Any,
        learned_from: str = "inferred",
        context_type: Optional[str] = None,
        context_id: Optional[str] = None,
        confidence: float = 0.5
    ) -> bool:
        """Set or update a preference"""
        now = datetime.now()

        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO user_preferences
                (user_id, preference_category, preference_key, preference_value,
                 confidence, learned_from, context_type, context_id, last_used, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, preference_category, preference_key, context_type, context_id)
                DO UPDATE SET
                    preference_value = EXCLUDED.preference_value,
                    confidence = GREATEST(user_preferences.confidence, EXCLUDED.confidence),
                    learned_from = EXCLUDED.learned_from,
                    last_used = EXCLUDED.last_used,
                    updated_at = EXCLUDED.updated_at
            """, (user_id, category, key, Json(value), confidence, learned_from,
                  context_type, context_id, now, now))

            log_with_context(logger, "info", "Preference set",
                           user_id=user_id, category=category, key=key)
            return True

    @staticmethod
    def record_feedback(
        user_id: int,
        category: str,
        key: str,
        positive: bool,
        context_type: Optional[str] = None,
        context_id: Optional[str] = None
    ) -> bool:
        """Record positive or negative feedback for a preference"""
        with get_cursor() as cur:
            if positive:
                cur.execute("""
                    UPDATE user_preferences SET
                        positive_signals = positive_signals + 1,
                        confidence = LEAST(1.0, confidence + 0.05),
                        last_used = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s AND preference_category = %s AND preference_key = %s
                      AND (context_type = %s OR (context_type IS NULL AND %s IS NULL))
                      AND (context_id = %s OR (context_id IS NULL AND %s IS NULL))
                """, (user_id, category, key, context_type, context_type, context_id, context_id))
            else:
                cur.execute("""
                    UPDATE user_preferences SET
                        negative_signals = negative_signals + 1,
                        confidence = GREATEST(0.1, confidence - 0.1),
                        updated_at = NOW()
                    WHERE user_id = %s AND preference_category = %s AND preference_key = %s
                      AND (context_type = %s OR (context_type IS NULL AND %s IS NULL))
                      AND (context_id = %s OR (context_id IS NULL AND %s IS NULL))
                """, (user_id, category, key, context_type, context_type, context_id, context_id))

            return cur.rowcount > 0

    @staticmethod
    def infer_from_edit_distance(
        user_id: int,
        original: str,
        edited: str,
        context: Dict
    ) -> Optional[Dict]:
        """
        Infer preferences from edit distance between original and edited text.
        Returns learned preferences if significant edits detected.
        """
        if not original or not edited:
            return None

        # Calculate simple edit distance ratio
        original_len = len(original)
        edited_len = len(edited)

        # Length-based inference
        length_ratio = edited_len / original_len if original_len > 0 else 1.0

        learned = []

        # Infer detail level preference
        if length_ratio < 0.5:
            # User significantly shortened - prefers summary
            PreferenceEngine.set_preference(
                user_id=user_id,
                category="detail_level",
                key="default",
                value={"level": "summary"},
                learned_from="inferred",
                context_type=context.get("context_type"),
                context_id=context.get("context_id")
            )
            learned.append({"key": "detail_level", "value": "summary"})
        elif length_ratio > 2.0:
            # User significantly expanded - prefers detail
            PreferenceEngine.set_preference(
                user_id=user_id,
                category="detail_level",
                key="default",
                value={"level": "detailed"},
                learned_from="inferred",
                context_type=context.get("context_type"),
                context_id=context.get("context_id")
            )
            learned.append({"key": "detail_level", "value": "detailed"})

        # Check for emoji removal
        import re
        emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]')
        original_emojis = len(emoji_pattern.findall(original))
        edited_emojis = len(emoji_pattern.findall(edited))

        if original_emojis > 0 and edited_emojis == 0:
            PreferenceEngine.set_preference(
                user_id=user_id,
                category="negative",
                key="no_emojis",
                value={"active": True},
                learned_from="inferred"
            )
            learned.append({"key": "no_emojis", "value": True})

        return {"learned": learned} if learned else None


# ============ Active Learner ============

class ActiveLearner:
    """Generates and manages learning questions"""

    @staticmethod
    def generate_question(user_id: int) -> Optional[LearningQuestion]:
        """Generate a high-value learning question based on uncertainty"""
        with get_cursor() as cur:
            # Find low-confidence preferences that would benefit from clarification
            cur.execute("""
                SELECT preference_category, preference_key, confidence
                FROM user_preferences
                WHERE user_id = %s AND confidence < 0.5
                ORDER BY confidence ASC
                LIMIT 5
            """, (user_id,))
            low_confidence = cur.fetchall()

            if low_confidence:
                pref = low_confidence[0]
                question_text = ActiveLearner._generate_question_text(
                    pref['preference_category'],
                    pref['preference_key']
                )
                options = ActiveLearner._generate_options(
                    pref['preference_category'],
                    pref['preference_key']
                )

                if question_text and options:
                    # Insert into queue
                    expires_at = datetime.now() + timedelta(days=7)
                    cur.execute("""
                        INSERT INTO active_learning_queue
                        (user_id, question_type, question_text, options, priority,
                         target_preference_key, uncertainty_reason, expires_at)
                        VALUES (%s, 'preference', %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        user_id,
                        question_text,
                        Json(options),
                        1 - pref['confidence'],  # Higher priority for lower confidence
                        f"{pref['preference_category']}:{pref['preference_key']}",
                        f"Low confidence ({pref['confidence']:.2f})",
                        expires_at
                    ))
                    row = cur.fetchone()

                    return LearningQuestion(
                        id=row['id'],
                        question_type='preference',
                        question_text=question_text,
                        options=options,
                        priority=1 - pref['confidence'],
                        uncertainty_reason=f"Low confidence ({pref['confidence']:.2f})"
                    )

            return None

    @staticmethod
    def _generate_question_text(category: str, key: str) -> Optional[str]:
        """Generate natural language question for a preference"""
        questions = {
            ("communication_style", "formality"): "Wie soll ich normalerweise antworten - eher formell oder locker?",
            ("detail_level", "default"): "Bei Analysen: Lieber kurze Zusammenfassung oder ausführliche Details?",
            ("detail_level", "budget_topics"): "Bei Budget-Themen: Zahlen-Deep-Dive oder Executive Summary?",
            ("channel", "email"): "Email-Entwürfe: Kurz und knapp oder mit mehr Kontext?",
            ("negative", "no_emojis"): "Soll ich Emojis in Antworten verwenden?",
        }
        return questions.get((category, key))

    @staticmethod
    def _generate_options(category: str, key: str) -> List[Dict]:
        """Generate options for a preference question"""
        options_map = {
            ("communication_style", "formality"): [
                {"label": "Locker", "value": "casual"},
                {"label": "Formell", "value": "formal"},
                {"label": "Kommt drauf an", "value": "context_dependent"}
            ],
            ("detail_level", "default"): [
                {"label": "Zusammenfassung", "value": "summary"},
                {"label": "Ausführlich", "value": "detailed"},
                {"label": "Frag mich jeweils", "value": "ask"}
            ],
            ("detail_level", "budget_topics"): [
                {"label": "Zahlen-Details", "value": "detailed"},
                {"label": "Executive Summary", "value": "summary"},
                {"label": "Beides", "value": "both"}
            ],
            ("channel", "email"): [
                {"label": "Kurz & knapp", "value": "brief"},
                {"label": "Mit Kontext", "value": "detailed"},
                {"label": "Je nach Empfänger", "value": "context_dependent"}
            ],
            ("negative", "no_emojis"): [
                {"label": "Ja, gerne", "value": False},
                {"label": "Lieber nicht", "value": True},
                {"label": "Egal", "value": None}
            ],
        }
        return options_map.get((category, key), [])

    @staticmethod
    def get_pending_questions(user_id: int, limit: int = 2) -> List[LearningQuestion]:
        """Get pending questions for a user"""
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, question_type, question_text, options, priority, uncertainty_reason
                FROM active_learning_queue
                WHERE user_id = %s AND status = 'pending' AND expires_at > NOW()
                ORDER BY priority DESC
                LIMIT %s
            """, (user_id, limit))

            return [
                LearningQuestion(
                    id=row['id'],
                    question_type=row['question_type'],
                    question_text=row['question_text'],
                    options=row['options'] or [],
                    priority=row['priority'],
                    uncertainty_reason=row['uncertainty_reason']
                )
                for row in cur.fetchall()
            ]

    @staticmethod
    def record_answer(question_id: int, answer_value: Any) -> bool:
        """Record an answer to a learning question"""
        with get_cursor() as cur:
            # Get the question details
            cur.execute("""
                SELECT user_id, target_preference_key
                FROM active_learning_queue
                WHERE id = %s
            """, (question_id,))
            row = cur.fetchone()

            if not row:
                return False

            # Update the question
            cur.execute("""
                UPDATE active_learning_queue SET
                    status = 'answered',
                    answer_value = %s,
                    answered_at = NOW()
                WHERE id = %s
            """, (Json(answer_value), question_id))

            # Update the preference if we have a target
            if row['target_preference_key']:
                parts = row['target_preference_key'].split(':')
                if len(parts) == 2:
                    category, key = parts
                    PreferenceEngine.set_preference(
                        user_id=row['user_id'],
                        category=category,
                        key=key,
                        value=answer_value,
                        learned_from='explicit',
                        confidence=0.9  # High confidence for explicit answers
                    )

            return True

    @staticmethod
    def get_daily_question_count(user_id: int) -> int:
        """Get number of questions asked today"""
        with get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count
                FROM active_learning_queue
                WHERE user_id = %s AND asked_at >= CURRENT_DATE
            """, (user_id,))
            row = cur.fetchone()
            return row['count'] if row else 0

    @staticmethod
    def can_ask_question(user_id: int) -> bool:
        """Check if we can ask another question today"""
        return ActiveLearner.get_daily_question_count(user_id) < MAX_QUESTIONS_PER_DAY


# ============ Anomaly Detector ============

class AnomalyDetector:
    """Detects and logs behavioral anomalies"""

    @staticmethod
    def check_for_anomalies(user_id: int) -> List[Anomaly]:
        """Check all baselines for anomalies (should be called periodically)"""
        # This would typically be called by n8n workflow
        # For now, return empty list - anomalies are detected during record_observation
        return []

    @staticmethod
    def log_anomaly(
        user_id: int,
        baseline_id: int,
        observed_value: float,
        expected_value: float,
        std_dev: float,
        deviation_score: float,
        context: Optional[Dict] = None
    ) -> int:
        """Log a detected anomaly"""
        severity = "critical" if deviation_score >= ANOMALY_THRESHOLD_CRITICAL else "elevated"
        context = context or {}

        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO user_anomaly_log
                (user_id, baseline_id, observed_value, expected_value, std_dev,
                 deviation_score, severity, context_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, baseline_id, observed_value, expected_value,
                  std_dev, deviation_score, severity, Json(context)))
            row = cur.fetchone()
            return row['id']

    @staticmethod
    def get_open_anomalies(user_id: int, severity: Optional[str] = None) -> List[Anomaly]:
        """Get open anomalies for a user"""
        with get_cursor() as cur:
            if severity:
                cur.execute("""
                    SELECT a.id, a.observed_value, a.expected_value, a.deviation_score,
                           a.severity, a.context_snapshot, a.detected_at,
                           b.metric_category, b.metric_name
                    FROM user_anomaly_log a
                    JOIN user_behavioral_baseline b ON a.baseline_id = b.id
                    WHERE a.user_id = %s AND a.status = 'open' AND a.severity = %s
                    ORDER BY a.detected_at DESC
                """, (user_id, severity))
            else:
                cur.execute("""
                    SELECT a.id, a.observed_value, a.expected_value, a.deviation_score,
                           a.severity, a.context_snapshot, a.detected_at,
                           b.metric_category, b.metric_name
                    FROM user_anomaly_log a
                    JOIN user_behavioral_baseline b ON a.baseline_id = b.id
                    WHERE a.user_id = %s AND a.status = 'open'
                    ORDER BY a.detected_at DESC
                """, (user_id,))

            return [
                Anomaly(
                    id=row['id'],
                    metric_category=row['metric_category'],
                    metric_name=row['metric_name'],
                    observed_value=row['observed_value'],
                    expected_value=row['expected_value'],
                    deviation_score=row['deviation_score'],
                    severity=row['severity'],
                    context=row['context_snapshot'] or {},
                    detected_at=row['detected_at']
                )
                for row in cur.fetchall()
            ]

    @staticmethod
    def resolve_anomaly(anomaly_id: int, status: str, explanation: Optional[str] = None) -> bool:
        """Resolve an anomaly"""
        valid_statuses = ['explained', 'false_positive', 'new_normal']
        if status not in valid_statuses:
            return False

        with get_cursor() as cur:
            cur.execute("""
                UPDATE user_anomaly_log SET
                    status = %s,
                    explanation = %s,
                    resolved_at = NOW()
                WHERE id = %s
            """, (status, explanation, anomaly_id))
            return cur.rowcount > 0

    @staticmethod
    def should_notify(anomaly: Anomaly) -> bool:
        """Check if an anomaly should trigger a notification"""
        return anomaly.severity == 'critical' or anomaly.deviation_score >= ANOMALY_THRESHOLD_ALERT


# ============ Profile Assembler ============

class ProfileAssembler:
    """Assembles user profile for prompt injection"""

    @staticmethod
    def get_full_profile(user_id: int) -> Dict:
        """Get complete user profile"""
        baselines = BaselineTracker.get_all_baselines(user_id)
        preferences = PreferenceEngine.get_preferences(user_id)
        anomalies = AnomalyDetector.get_open_anomalies(user_id)

        # Group baselines by category
        baseline_dict = {}
        for b in baselines:
            if b.metric_category not in baseline_dict:
                baseline_dict[b.metric_category] = {}
            baseline_dict[b.metric_category][b.metric_name] = {
                "expected": round(b.expected_value, 2),
                "std_dev": round(b.std_dev, 2),
                "confidence": round(b.confidence, 2)
            }

        # Group preferences by category
        pref_dict = {}
        for p in preferences:
            if p.category not in pref_dict:
                pref_dict[p.category] = {}
            key = f"{p.key}:{p.context_type}:{p.context_id}" if p.context_type else p.key
            pref_dict[p.category][key] = {
                "value": p.value,
                "confidence": round(p.confidence, 2),
                "context": f"{p.context_type}:{p.context_id}" if p.context_type else None
            }

        # Calculate completeness
        total_possible = 10  # arbitrary baseline
        total_filled = len(baselines) + len(preferences)
        completeness = min(1.0, total_filled / total_possible)

        return {
            "user_id": user_id,
            "baselines": baseline_dict,
            "preferences": pref_dict,
            "open_anomalies": len(anomalies),
            "profile_completeness": round(completeness, 2),
            "last_updated": datetime.now().isoformat()
        }

    @staticmethod
    def get_prompt_context(user_id: int) -> str:
        """Generate profile context string for system prompt injection"""
        preferences = PreferenceEngine.get_preferences(user_id)
        baselines = BaselineTracker.get_all_baselines(user_id)

        if not preferences and not baselines:
            return "No profile data available yet."

        lines = []

        # Communication preferences
        style_prefs = [p for p in preferences if p.category == 'communication_style']
        if style_prefs:
            lines.append("### Communication Preferences")
            for p in style_prefs:
                value = p.value.get('level', p.value) if isinstance(p.value, dict) else p.value
                context = f" (with {p.context_id})" if p.context_id else ""
                lines.append(f"- {p.key}: {value}{context}")

        # Detail level
        detail_prefs = [p for p in preferences if p.category == 'detail_level']
        if detail_prefs:
            lines.append("\n### Detail Level")
            for p in detail_prefs:
                value = p.value.get('level', p.value) if isinstance(p.value, dict) else p.value
                lines.append(f"- {p.key}: {value}")

        # Negative preferences
        negative_prefs = [p for p in preferences if p.category == 'negative']
        if negative_prefs:
            lines.append("\n### Negative Preferences (DO NOT)")
            for p in negative_prefs:
                if p.value and (isinstance(p.value, bool) or p.value.get('active')):
                    lines.append(f"- {p.key.replace('no_', 'No ')}")

        # Behavioral patterns (if confident)
        confident_baselines = [b for b in baselines if b.confidence >= 0.6]
        if confident_baselines:
            lines.append("\n### Known Patterns")
            for b in confident_baselines:
                lines.append(f"- {b.metric_category}/{b.metric_name}: ~{b.expected_value:.1f} (±{b.std_dev:.1f})")

        return "\n".join(lines) if lines else "Profile data is still being collected."

    @staticmethod
    def get_profile_summary(user_id: int) -> str:
        """Get a short one-line profile summary"""
        preferences = PreferenceEngine.get_preferences(user_id)

        if not preferences:
            return "New user - preferences not yet learned"

        style = next((p.value for p in preferences
                     if p.category == 'communication_style' and p.key == 'formality'), None)
        detail = next((p.value for p in preferences
                      if p.category == 'detail_level' and p.key == 'default'), None)

        parts = []
        if style:
            val = style.get('level', style) if isinstance(style, dict) else style
            parts.append(f"style={val}")
        if detail:
            val = detail.get('level', detail) if isinstance(detail, dict) else detail
            parts.append(f"detail={val}")

        return f"Profile: {', '.join(parts)}" if parts else "Profile: learning..."


# ============ Phase 17.2: Preference Learner ============

@dataclass
class StyleProfile:
    """User communication style profile"""
    formality_score: float = 0.5
    avg_message_length: float = 0.0
    emoji_ratio: float = 0.0
    abbreviation_ratio: float = 0.0
    exclamation_frequency: float = 0.0
    punctuation_precision: float = 0.5
    greeting_formality: float = 0.5
    uses_sie_form: bool = False
    confidence: float = 0.0
    sample_count: int = 0


@dataclass
class ContextPreference:
    """Context-specific communication preferences"""
    context_type: str
    formality_modifier: float = 0.0
    length_modifier: float = 0.0
    urgency_threshold: float = 0.5
    is_internal_domain: bool = False
    reply_thread_threshold: int = 3
    confidence: float = 0.0


@dataclass
class PersonPattern:
    """Communication pattern with a specific person"""
    person_email: str
    person_name: Optional[str] = None
    person_domain: Optional[str] = None
    formality_score: float = 0.5
    avg_response_time_hours: Optional[float] = None
    typical_message_length: Optional[float] = None
    is_internal: bool = False
    interaction_count: int = 0
    confidence: float = 0.0


class PreferenceLearner:
    """
    Phase 17.2: Learns communication preferences from message history.

    Features:
    - Style extraction (formality, tone, length)
    - Context detection (email, meeting, async, urgent)
    - Person-specific patterns
    - Confidence scoring with Jarvis-refined heuristics
    """

    # Common abbreviations (Jarvis-suggested)
    ABBREVIATIONS = {'btw', 'asap', 'fyi', 'imho', 'imo', 'afaik', 'lmk', 'thx', 'pls', 'np', 'ty'}

    # Formal greeting patterns (German/English)
    FORMAL_GREETINGS = {'liebe grüsse', 'freundliche grüsse', 'mit freundlichen grüssen',
                        'beste grüsse', 'kind regards', 'best regards', 'sincerely'}
    CASUAL_GREETINGS = {'ciao', 'lg', 'vg', 'cheers', 'gruss', 'bis dann', 'bye'}

    # Urgency keywords
    URGENT_KEYWORDS = {'asap', 'urgent', 'dringend', 'sofort', 'critical', 'wichtig', 'help', 'hilfe'}

    @classmethod
    def extract_style_from_message(cls, text: str) -> Dict[str, float]:
        """
        Extract style metrics from a single message.

        Returns dict with formality indicators based on Jarvis-refined heuristics.
        """
        if not text:
            return {}

        text_lower = text.lower()
        words = text.split()
        word_count = len(words)

        if word_count == 0:
            return {}

        # Character analysis
        char_count = len(text)
        uppercase_chars = sum(1 for c in text if c.isupper())
        punctuation_count = sum(1 for c in text if c in '.,;:!?')
        emoji_count = sum(1 for c in text if ord(c) > 0x1F300)
        exclamation_count = text.count('!')
        question_count = text.count('?')

        # Word-level analysis
        avg_word_length = sum(len(w) for w in words) / word_count if word_count > 0 else 0
        abbreviation_count = sum(1 for w in words if w.lower().strip('.,!?') in cls.ABBREVIATIONS)

        # Greeting analysis
        has_formal_greeting = any(g in text_lower for g in cls.FORMAL_GREETINGS)
        has_casual_greeting = any(g in text_lower for g in cls.CASUAL_GREETINGS)

        # Sie/Du detection (German formality)
        uses_sie = bool(any(w.lower() in ('sie', 'ihnen', 'ihr', 'ihre') for w in words))
        uses_du = bool(any(w.lower() in ('du', 'dir', 'dich', 'dein', 'deine') for w in words))

        # Calculate ratios
        emoji_ratio = emoji_count / word_count if word_count > 0 else 0
        abbreviation_ratio = abbreviation_count / word_count if word_count > 0 else 0
        exclamation_frequency = exclamation_count / max(1, punctuation_count) if punctuation_count > 0 else 0

        # Punctuation precision (correct usage pattern)
        expected_punctuation = char_count / 50  # Expect ~1 punctuation per 50 chars
        punctuation_precision = min(1.0, punctuation_count / max(1, expected_punctuation))

        # Formality score (0.0 = casual, 1.0 = formal)
        formality_score = 0.5

        # Adjust based on Jarvis-refined heuristics
        if avg_word_length > 5.5:
            formality_score += 0.1
        if punctuation_precision > 0.6:
            formality_score += 0.1
        if has_formal_greeting:
            formality_score += 0.15
        if uses_sie and not uses_du:
            formality_score += 0.15

        # Casual indicators
        if emoji_ratio > 0.1:
            formality_score -= 0.15
        if abbreviation_ratio > 0.05:
            formality_score -= 0.1
        if has_casual_greeting:
            formality_score -= 0.15
        if exclamation_frequency > 0.3:
            formality_score -= 0.05
        if uses_du and not uses_sie:
            formality_score -= 0.1

        # Clamp to [0, 1]
        formality_score = max(0.0, min(1.0, formality_score))

        # Greeting formality (separate metric)
        greeting_formality = 0.5
        if has_formal_greeting:
            greeting_formality = 0.8
        elif has_casual_greeting:
            greeting_formality = 0.2

        return {
            'formality_score': formality_score,
            'avg_word_length': avg_word_length,
            'message_length': word_count,
            'emoji_ratio': emoji_ratio,
            'abbreviation_ratio': abbreviation_ratio,
            'exclamation_frequency': exclamation_frequency,
            'punctuation_precision': punctuation_precision,
            'greeting_formality': greeting_formality,
            'uses_sie_form': uses_sie and not uses_du,
        }

    @classmethod
    def detect_context(cls, message: Dict) -> str:
        """
        Detect the context type for a message.

        Contexts (Jarvis-refined):
        - email_formal: External email, formal default
        - email_internal: Internal domain email, semi-formal
        - email_thread: Reply thread > 3, casual drift
        - meeting: Meeting-related
        - async: No immediate response expected
        - urgent: Contains urgency keywords
        """
        text = message.get('body', message.get('text', ''))
        text_lower = text.lower()
        subject = message.get('subject', '').lower()
        sender = message.get('from', '')
        channel = message.get('channel', 'email')

        # Urgency check (highest priority)
        if any(kw in text_lower or kw in subject for kw in cls.URGENT_KEYWORDS):
            return 'urgent'

        # Meeting context
        if message.get('event_type') == 'meeting':
            return 'meeting'
        if 'meeting' in subject or 'einladung' in subject:
            return 'meeting'

        # Email context detection
        if channel == 'email':
            # Check if internal domain (Jarvis-refined)
            sender_domain = sender.split('@')[-1] if '@' in sender else ''
            if 'projektil.ch' in sender_domain:
                return 'email_internal'

            # Check reply thread depth
            re_count = subject.count('re:') + subject.count('aw:')
            if re_count >= 3:
                return 'email_thread'

            return 'email_formal'

        # Slack = async casual
        if channel == 'slack':
            return 'async'

        return 'email_formal'

    @classmethod
    def update_style_profile(cls, user_id: int, messages: List[Dict]) -> StyleProfile:
        """
        Update user's style profile from message history.

        Uses incremental averaging (like Welford's algorithm) for stability.
        """
        if not messages:
            return cls.get_style_profile(user_id)

        with get_cursor() as cur:
            # Get existing profile
            cur.execute("""
                SELECT formality_score, avg_message_length, emoji_ratio,
                       abbreviation_ratio, exclamation_frequency, punctuation_precision,
                       greeting_formality, uses_sie_form, sample_count, confidence
                FROM user_communication_profiles WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()

            if row:
                old_count = row['sample_count']
                old_formality = row['formality_score']
                old_length = row['avg_message_length']
                old_emoji = row['emoji_ratio']
                old_abbrev = row['abbreviation_ratio']
                old_exclam = row['exclamation_frequency']
                old_punct = row['punctuation_precision']
                old_greeting = row['greeting_formality']
                old_sie = row['uses_sie_form']
            else:
                old_count = 0
                old_formality = 0.5
                old_length = 0.0
                old_emoji = 0.0
                old_abbrev = 0.0
                old_exclam = 0.0
                old_punct = 0.5
                old_greeting = 0.5
                old_sie = False

            # Process new messages
            sie_count = 0
            for msg in messages:
                text = msg.get('body', msg.get('text', ''))
                style = cls.extract_style_from_message(text)
                if not style:
                    continue

                # Incremental update (running average)
                new_count = old_count + 1

                old_formality = old_formality + (style['formality_score'] - old_formality) / new_count
                old_length = old_length + (style['message_length'] - old_length) / new_count
                old_emoji = old_emoji + (style['emoji_ratio'] - old_emoji) / new_count
                old_abbrev = old_abbrev + (style['abbreviation_ratio'] - old_abbrev) / new_count
                old_exclam = old_exclam + (style['exclamation_frequency'] - old_exclam) / new_count
                old_punct = old_punct + (style['punctuation_precision'] - old_punct) / new_count
                old_greeting = old_greeting + (style['greeting_formality'] - old_greeting) / new_count

                if style.get('uses_sie_form'):
                    sie_count += 1

                old_count = new_count

            # Update Sie-form (majority vote)
            uses_sie = sie_count > len(messages) / 2

            # Calculate confidence
            confidence = cls.calculate_confidence(old_count)

            # Upsert profile
            cur.execute("""
                INSERT INTO user_communication_profiles
                (user_id, formality_score, avg_message_length, emoji_ratio,
                 abbreviation_ratio, exclamation_frequency, punctuation_precision,
                 greeting_formality, uses_sie_form, sample_count, confidence, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    formality_score = EXCLUDED.formality_score,
                    avg_message_length = EXCLUDED.avg_message_length,
                    emoji_ratio = EXCLUDED.emoji_ratio,
                    abbreviation_ratio = EXCLUDED.abbreviation_ratio,
                    exclamation_frequency = EXCLUDED.exclamation_frequency,
                    punctuation_precision = EXCLUDED.punctuation_precision,
                    greeting_formality = EXCLUDED.greeting_formality,
                    uses_sie_form = EXCLUDED.uses_sie_form,
                    sample_count = EXCLUDED.sample_count,
                    confidence = EXCLUDED.confidence,
                    last_updated = NOW()
            """, (user_id, old_formality, old_length, old_emoji, old_abbrev,
                  old_exclam, old_punct, old_greeting, uses_sie, old_count, confidence))

            log_with_context(logger, "info", "Style profile updated",
                           user_id=user_id, sample_count=old_count, confidence=confidence)

            return StyleProfile(
                formality_score=old_formality,
                avg_message_length=old_length,
                emoji_ratio=old_emoji,
                abbreviation_ratio=old_abbrev,
                exclamation_frequency=old_exclam,
                punctuation_precision=old_punct,
                greeting_formality=old_greeting,
                uses_sie_form=uses_sie,
                confidence=confidence,
                sample_count=old_count
            )

    @classmethod
    def get_style_profile(cls, user_id: int) -> Optional[StyleProfile]:
        """Get the current style profile for a user"""
        with get_cursor() as cur:
            cur.execute("""
                SELECT formality_score, avg_message_length, emoji_ratio,
                       abbreviation_ratio, exclamation_frequency, punctuation_precision,
                       greeting_formality, uses_sie_form, sample_count, confidence
                FROM user_communication_profiles WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()

            if not row:
                return None

            return StyleProfile(
                formality_score=row['formality_score'],
                avg_message_length=row['avg_message_length'],
                emoji_ratio=row['emoji_ratio'],
                abbreviation_ratio=row['abbreviation_ratio'],
                exclamation_frequency=row['exclamation_frequency'],
                punctuation_precision=row['punctuation_precision'],
                greeting_formality=row['greeting_formality'],
                uses_sie_form=row['uses_sie_form'],
                confidence=row['confidence'],
                sample_count=row['sample_count']
            )

    @classmethod
    def learn_context_rules(cls, user_id: int, messages: List[Dict]) -> List[ContextPreference]:
        """
        Learn context-specific style rules from message patterns.

        Compares formality across contexts to learn modifiers.
        """
        if not messages:
            return []

        # Group messages by context
        context_styles: Dict[str, List[Dict]] = {}
        for msg in messages:
            context = cls.detect_context(msg)
            if context not in context_styles:
                context_styles[context] = []

            text = msg.get('body', msg.get('text', ''))
            style = cls.extract_style_from_message(text)
            if style:
                context_styles[context].append(style)

        # Get base formality (overall average)
        all_formality = []
        for styles in context_styles.values():
            all_formality.extend(s['formality_score'] for s in styles)
        base_formality = sum(all_formality) / len(all_formality) if all_formality else 0.5

        results = []
        with get_cursor() as cur:
            for context_type, styles in context_styles.items():
                if not styles:
                    continue

                # Calculate averages for this context
                avg_formality = sum(s['formality_score'] for s in styles) / len(styles)
                avg_length = sum(s['message_length'] for s in styles) / len(styles)

                # Calculate modifiers (deviation from base)
                formality_modifier = avg_formality - base_formality

                # Urgency detection
                urgency_threshold = 0.3 if context_type == 'urgent' else 0.5

                # Internal domain flag
                is_internal = context_type == 'email_internal'

                # Confidence
                confidence = cls.calculate_confidence(len(styles))

                # Upsert
                cur.execute("""
                    INSERT INTO user_context_preferences
                    (user_id, context_type, formality_modifier, length_modifier,
                     urgency_threshold, is_internal_domain, sample_count, confidence, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, context_type) DO UPDATE SET
                        formality_modifier = EXCLUDED.formality_modifier,
                        length_modifier = EXCLUDED.length_modifier,
                        urgency_threshold = EXCLUDED.urgency_threshold,
                        is_internal_domain = EXCLUDED.is_internal_domain,
                        sample_count = user_context_preferences.sample_count + EXCLUDED.sample_count,
                        confidence = EXCLUDED.confidence,
                        updated_at = NOW()
                """, (user_id, context_type, formality_modifier, avg_length,
                      urgency_threshold, is_internal, len(styles), confidence))

                results.append(ContextPreference(
                    context_type=context_type,
                    formality_modifier=formality_modifier,
                    length_modifier=avg_length,
                    urgency_threshold=urgency_threshold,
                    is_internal_domain=is_internal,
                    confidence=confidence
                ))

        log_with_context(logger, "info", "Context rules learned",
                        user_id=user_id, contexts=len(results))
        return results

    @classmethod
    def build_person_model(cls, user_id: int, interactions: List[Dict]) -> List[PersonPattern]:
        """
        Build person-specific communication patterns.

        Tracks formality, response time, and message length per person.
        """
        if not interactions:
            return []

        # Group by person email
        person_data: Dict[str, List[Dict]] = {}
        for interaction in interactions:
            email = interaction.get('person_email', interaction.get('from', ''))
            if not email or '@' not in email:
                continue

            if email not in person_data:
                person_data[email] = []
            person_data[email].append(interaction)

        results = []
        with get_cursor() as cur:
            for email, data in person_data.items():
                if not data:
                    continue

                # Extract domain and name
                domain = email.split('@')[-1] if '@' in email else ''
                name = data[0].get('person_name', email.split('@')[0])

                # Calculate style metrics
                formalities = []
                lengths = []
                response_times = []

                for d in data:
                    text = d.get('body', d.get('text', ''))
                    style = cls.extract_style_from_message(text)
                    if style:
                        formalities.append(style['formality_score'])
                        lengths.append(style['message_length'])

                    if d.get('response_time_hours'):
                        response_times.append(d['response_time_hours'])

                avg_formality = sum(formalities) / len(formalities) if formalities else 0.5
                avg_length = sum(lengths) / len(lengths) if lengths else 0.0
                avg_response = sum(response_times) / len(response_times) if response_times else None

                # Internal flag
                is_internal = 'projektil.ch' in domain

                # Confidence
                confidence = cls.calculate_confidence(len(data))

                # Upsert
                cur.execute("""
                    INSERT INTO interaction_patterns
                    (user_id, person_email, person_name, person_domain,
                     formality_score, avg_response_time_hours, typical_message_length,
                     is_internal, interaction_count, confidence, updated_at, last_interaction)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (user_id, person_email) DO UPDATE SET
                        person_name = COALESCE(EXCLUDED.person_name, interaction_patterns.person_name),
                        formality_score = EXCLUDED.formality_score,
                        avg_response_time_hours = EXCLUDED.avg_response_time_hours,
                        typical_message_length = EXCLUDED.typical_message_length,
                        interaction_count = interaction_patterns.interaction_count + EXCLUDED.interaction_count,
                        confidence = EXCLUDED.confidence,
                        updated_at = NOW(),
                        last_interaction = NOW()
                """, (user_id, email, name, domain, avg_formality, avg_response,
                      avg_length, is_internal, len(data), confidence))

                results.append(PersonPattern(
                    person_email=email,
                    person_name=name,
                    person_domain=domain,
                    formality_score=avg_formality,
                    avg_response_time_hours=avg_response,
                    typical_message_length=avg_length,
                    is_internal=is_internal,
                    interaction_count=len(data),
                    confidence=confidence
                ))

        log_with_context(logger, "info", "Person models built",
                        user_id=user_id, persons=len(results))
        return results

    @classmethod
    def get_person_pattern(cls, user_id: int, person_email: str) -> Optional[PersonPattern]:
        """Get communication pattern for a specific person"""
        with get_cursor() as cur:
            cur.execute("""
                SELECT person_email, person_name, person_domain,
                       formality_score, avg_response_time_hours, typical_message_length,
                       is_internal, interaction_count, confidence
                FROM interaction_patterns
                WHERE user_id = %s AND person_email = %s
            """, (user_id, person_email))
            row = cur.fetchone()

            if not row:
                return None

            return PersonPattern(
                person_email=row['person_email'],
                person_name=row['person_name'],
                person_domain=row['person_domain'],
                formality_score=row['formality_score'],
                avg_response_time_hours=row['avg_response_time_hours'],
                typical_message_length=row['typical_message_length'],
                is_internal=row['is_internal'],
                interaction_count=row['interaction_count'],
                confidence=row['confidence']
            )

    @classmethod
    def get_context_preference(cls, user_id: int, context_type: str) -> Optional[ContextPreference]:
        """Get preference for a specific context"""
        with get_cursor() as cur:
            cur.execute("""
                SELECT context_type, formality_modifier, length_modifier,
                       urgency_threshold, is_internal_domain, reply_thread_threshold, confidence
                FROM user_context_preferences
                WHERE user_id = %s AND context_type = %s
            """, (user_id, context_type))
            row = cur.fetchone()

            if not row:
                return None

            return ContextPreference(
                context_type=row['context_type'],
                formality_modifier=row['formality_modifier'],
                length_modifier=row['length_modifier'],
                urgency_threshold=row['urgency_threshold'],
                is_internal_domain=row['is_internal_domain'],
                reply_thread_threshold=row['reply_thread_threshold'],
                confidence=row['confidence']
            )

    @staticmethod
    def calculate_confidence(sample_count: int, min_samples: int = 50) -> float:
        """
        Calculate confidence score based on sample count.

        Formula: min(sample_count / min_samples, 1.0)
        Reaches 1.0 at 50 samples by default.
        """
        return min(sample_count / min_samples, 1.0)
