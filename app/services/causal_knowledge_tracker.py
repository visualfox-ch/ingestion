"""
T-21B-01: CK-Track (Causal Knowledge) Service
Tracks "Wenn X, dann Y" patterns for predictive intelligence.
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from app.postgres_state import get_conn
from app.observability import get_logger

logger = get_logger("jarvis.causal_knowledge_tracker")


class CausalKnowledgeTracker:
    """Tracks and learns causal patterns for predictive recommendations."""

    # Minimum confidence for predictions
    MIN_PREDICTION_CONFIDENCE = 0.6

    # Cause and effect types
    CAUSE_TYPES = ["behavior", "event", "state", "action", "time", "external"]
    EFFECT_TYPES = ["need", "outcome", "state", "recommendation", "warning", "opportunity"]

    def record_observation(
        self,
        user_id: str,
        cause_event: str,
        effect_event: str,
        cause_type: str = "event",
        effect_type: str = "outcome",
        time_delta_minutes: int = None,
        session_id: str = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Record a cause-effect observation."""
        # Normalize inputs
        cause_event = cause_event.lower().strip()
        effect_event = effect_event.lower().strip()
        cause_type = cause_type if cause_type in self.CAUSE_TYPES else "event"
        effect_type = effect_type if effect_type in self.EFFECT_TYPES else "outcome"

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check if pattern exists
                cur.execute("""
                    SELECT id, confidence, evidence_count
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND cause = %s AND effect = %s AND active = TRUE
                """, (user_id, cause_event, effect_event))
                existing = cur.fetchone()

                if existing:
                    # Update existing pattern with new evidence (RealDictCursor returns dict)
                    new_count = existing['evidence_count'] + 1
                    # Confidence increases with more evidence, max 0.95
                    new_confidence = min(0.95, existing['confidence'] + 0.05)

                    cur.execute("""
                        UPDATE jarvis_causal_patterns
                        SET evidence_count = %s, confidence = %s, last_observed_at = NOW()
                        WHERE id = %s
                    """, (new_count, new_confidence, existing['id']))

                    pattern_id = existing['id']
                    logger.info(f"Updated causal pattern {pattern_id}: {cause_event} -> {effect_event} (confidence={new_confidence})")
                else:
                    # Create new pattern
                    cur.execute("""
                        INSERT INTO jarvis_causal_patterns
                        (user_id, cause, effect, cause_type, effect_type, confidence, evidence_count)
                        VALUES (%s, %s, %s, %s, %s, 0.5, 1)
                        RETURNING id
                    """, (user_id, cause_event, effect_event, cause_type, effect_type))
                    pattern_id = cur.fetchone()['id']

                    logger.info(f"Created new causal pattern {pattern_id}: {cause_event} -> {effect_event}")

                # Record observation
                cur.execute("""
                    INSERT INTO jarvis_causal_observations
                    (user_id, pattern_id, cause_event, effect_event, time_delta_minutes, session_id, context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (user_id, pattern_id, cause_event, effect_event, time_delta_minutes, session_id,
                    json.dumps(context) if context else '{}'))
                conn.commit()

                return {
                    "recorded": True,
                    "pattern_id": pattern_id,
                    "cause": cause_event,
                    "effect": effect_event,
                    "is_new": existing is None
                }

    def predict_effects(
        self,
        user_id: str,
        current_cause: str,
        min_confidence: float = None
    ) -> List[Dict[str, Any]]:
        """Predict likely effects given a cause."""
        min_conf = min_confidence or self.MIN_PREDICTION_CONFIDENCE
        current_cause = current_cause.lower().strip()

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT effect, effect_type, confidence, evidence_count, last_observed_at
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND cause = %s AND confidence >= %s AND active = TRUE
                    ORDER BY confidence DESC, evidence_count DESC
                """, (user_id, current_cause, min_conf))
                rows = cur.fetchall()

                return [
                    {
                        "effect": r['effect'],
                        "type": r['effect_type'],
                        "confidence": round(r['confidence'], 2),
                        "evidence_count": r['evidence_count'],
                        "last_seen": r['last_observed_at'].isoformat() if r['last_observed_at'] else None
                    }
                    for r in rows
                ]

    def predict_causes(
        self,
        user_id: str,
        observed_effect: str,
        min_confidence: float = None
    ) -> List[Dict[str, Any]]:
        """Predict likely causes given an observed effect (reverse inference)."""
        min_conf = min_confidence or self.MIN_PREDICTION_CONFIDENCE
        observed_effect = observed_effect.lower().strip()

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cause, cause_type, confidence, evidence_count, last_observed_at
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND effect = %s AND confidence >= %s AND active = TRUE
                    ORDER BY confidence DESC, evidence_count DESC
                """, (user_id, observed_effect, min_conf))
                rows = cur.fetchall()

                return [
                    {
                        "cause": r['cause'],
                        "type": r['cause_type'],
                        "confidence": round(r['confidence'], 2),
                        "evidence_count": r['evidence_count'],
                        "last_seen": r['last_observed_at'].isoformat() if r['last_observed_at'] else None
                    }
                    for r in rows
                ]

    def get_all_patterns(
        self,
        user_id: str,
        min_confidence: float = 0.0,
        min_evidence: int = 1,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all causal patterns for a user."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cause, effect, cause_type, effect_type, confidence, evidence_count,
                           first_observed_at, last_observed_at, metadata
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND confidence >= %s AND evidence_count >= %s AND active = TRUE
                    ORDER BY confidence DESC, evidence_count DESC
                    LIMIT %s
                """, (user_id, min_confidence, min_evidence, limit))
                rows = cur.fetchall()

                return [
                    {
                        "cause": r['cause'],
                        "effect": r['effect'],
                        "cause_type": r['cause_type'],
                        "effect_type": r['effect_type'],
                        "confidence": round(r['confidence'], 2),
                        "evidence_count": r['evidence_count'],
                        "first_seen": r['first_observed_at'].isoformat() if r['first_observed_at'] else None,
                        "last_seen": r['last_observed_at'].isoformat() if r['last_observed_at'] else None,
                        "metadata": r['metadata'] if r['metadata'] else {}
                    }
                    for r in rows
                ]

    def decay_confidence(self, days_inactive: int = 30, decay_rate: float = 0.1) -> Dict[str, Any]:
        """Decay confidence of patterns not observed recently."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE jarvis_causal_patterns
                    SET confidence = GREATEST(0.1, confidence - %s)
                    WHERE last_observed_at < NOW() - INTERVAL '{days_inactive} days' AND active = TRUE
                """, (decay_rate,))
                affected = cur.rowcount
                conn.commit()
                logger.info(f"Decayed confidence for {affected} inactive patterns")
                return {"decayed_patterns": affected, "decay_rate": decay_rate}

    def deactivate_pattern(self, pattern_id: int, reason: str = None) -> bool:
        """Deactivate a pattern (soft delete)."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                metadata = json.dumps({"deactivation_reason": reason}) if reason else '{}'
                cur.execute("""
                    UPDATE jarvis_causal_patterns
                    SET active = FALSE, metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                    WHERE id = %s
                """, (metadata, pattern_id))
                conn.commit()
                return True

    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """Get causal knowledge statistics for a user."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                """, (user_id,))
                total = cur.fetchone()['cnt']

                cur.execute("""
                    SELECT COUNT(*) as cnt FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE AND confidence >= 0.7
                """, (user_id,))
                high_conf = cur.fetchone()['cnt']

                cur.execute("""
                    SELECT COUNT(*) as cnt FROM jarvis_causal_observations
                    WHERE user_id = %s
                """, (user_id,))
                observations = cur.fetchone()['cnt']

                # Top causes
                cur.execute("""
                    SELECT cause, COUNT(*) as cnt
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                    GROUP BY cause
                    ORDER BY cnt DESC
                    LIMIT 5
                """, (user_id,))
                top_causes = cur.fetchall()

                # Top effects
                cur.execute("""
                    SELECT effect, COUNT(*) as cnt
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                    GROUP BY effect
                    ORDER BY cnt DESC
                    LIMIT 5
                """, (user_id,))
                top_effects = cur.fetchall()

                return {
                    "total_patterns": total or 0,
                    "high_confidence_patterns": high_conf or 0,
                    "total_observations": observations or 0,
                    "top_causes": [{"cause": r['cause'], "count": r['cnt']} for r in top_causes],
                    "top_effects": [{"effect": r['effect'], "count": r['cnt']} for r in top_effects]
                }

    def suggest_patterns_to_observe(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Suggest patterns that need more evidence."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cause, effect, confidence, evidence_count
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                      AND confidence BETWEEN 0.4 AND 0.7
                      AND evidence_count < 5
                    ORDER BY confidence DESC
                    LIMIT %s
                """, (user_id, limit))
                rows = cur.fetchall()

                return [
                    {
                        "cause": r['cause'],
                        "effect": r['effect'],
                        "current_confidence": round(r['confidence'], 2),
                        "evidence_needed": 5 - r['evidence_count'],
                        "suggestion": f"Beobachte ob '{r['cause']}' zu '{r['effect']}' führt"
                    }
                    for r in rows
                ]


# Singleton instance
_tracker: Optional[CausalKnowledgeTracker] = None


def get_causal_knowledge_tracker() -> CausalKnowledgeTracker:
    """Get the singleton tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = CausalKnowledgeTracker()
    return _tracker
