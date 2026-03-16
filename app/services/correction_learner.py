"""
Correction Learner Service

Learns from user corrections to avoid repeating mistakes:
1. Detects when user corrects Jarvis (using trigger phrases)
2. Extracts the correction pattern
3. Stores patterns for future reference
4. Applies learned corrections to prevent repeated mistakes
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)

# Singleton
_correction_learner = None


def get_correction_learner() -> "CorrectionLearner":
    """Get singleton instance."""
    global _correction_learner
    if _correction_learner is None:
        _correction_learner = CorrectionLearner()
    return _correction_learner


class CorrectionLearner:
    """
    Learns from user corrections to improve future responses.
    """

    def __init__(self):
        self._trigger_cache: Optional[List[Dict]] = None
        self._trigger_cache_time: Optional[datetime] = None
        self._pattern_cache: Dict[str, List[Dict]] = {}

    # ==================== DETECTION ====================

    def _get_triggers(self) -> List[Dict]:
        """Get correction trigger phrases from DB with caching."""
        if (self._trigger_cache is not None and
            self._trigger_cache_time and
            datetime.now() - self._trigger_cache_time < timedelta(minutes=30)):
            return self._trigger_cache

        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT trigger_phrase, trigger_type, language
                    FROM correction_triggers
                    WHERE is_active = TRUE
                    ORDER BY LENGTH(trigger_phrase) DESC
                """)
                self._trigger_cache = [dict(r) for r in cur.fetchall()]
                self._trigger_cache_time = datetime.now()
                return self._trigger_cache
        except Exception as e:
            logger.warning(f"Failed to get correction triggers: {e}")
            # Fallback triggers
            return [
                {"trigger_phrase": "nein", "trigger_type": "explicit", "language": "de"},
                {"trigger_phrase": "falsch", "trigger_type": "explicit", "language": "de"},
                {"trigger_phrase": "nicht so", "trigger_type": "explicit", "language": "de"},
                {"trigger_phrase": "no", "trigger_type": "explicit", "language": "en"},
                {"trigger_phrase": "wrong", "trigger_type": "explicit", "language": "en"},
            ]

    def detect_correction(
        self,
        user_message: str,
        previous_response: str = None
    ) -> Dict[str, Any]:
        """
        Detect if user message is a correction.

        Returns:
            Dict with:
                - is_correction: bool
                - trigger_type: 'explicit', 'implicit', 'follow_up'
                - trigger_phrase: the phrase that triggered detection
                - confidence: 0.0-1.0
        """
        if not user_message:
            return {"is_correction": False}

        message_lower = user_message.lower()
        triggers = self._get_triggers()

        for trigger in triggers:
            phrase = trigger["trigger_phrase"].lower()
            if phrase in message_lower:
                # Check position - corrections at start are more confident
                position = message_lower.find(phrase)
                at_start = position < 10

                confidence = 0.9 if trigger["trigger_type"] == "explicit" else 0.6
                if at_start:
                    confidence += 0.1

                return {
                    "is_correction": True,
                    "trigger_type": trigger["trigger_type"],
                    "trigger_phrase": trigger["trigger_phrase"],
                    "confidence": min(confidence, 1.0),
                    "language": trigger.get("language", "de")
                }

        return {"is_correction": False}

    # ==================== PATTERN EXTRACTION ====================

    def extract_correction_pattern(
        self,
        user_message: str,
        previous_response: str,
        error_type: str = "general"
    ) -> Dict[str, Any]:
        """
        Extract a learnable pattern from a correction.

        Args:
            user_message: What user said (the correction)
            previous_response: What Jarvis said (the error)
            error_type: Category of error

        Returns:
            Extracted pattern with error_pattern, correct_response
        """
        # Try to extract "not X but Y" pattern
        patterns = [
            r"nicht\s+(.+?)\s+sondern\s+(.+)",  # nicht X sondern Y
            r"not\s+(.+?)\s+but\s+(.+)",         # not X but Y
            r"(.+?)\s+sondern\s+(.+)",           # X sondern Y
            r"(.+?),?\s+stattdessen\s+(.+)",     # X, stattdessen Y
            r"(.+?),?\s+instead\s+(.+)",         # X, instead Y
        ]

        for pattern in patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                return {
                    "error_pattern": match.group(1).strip(),
                    "correct_response": match.group(2).strip(),
                    "extraction_method": "pattern_match",
                    "confidence": 0.8
                }

        # Try to extract correction after trigger phrase
        triggers = ["nein,", "falsch,", "no,", "wrong,", "eigentlich", "actually"]
        for trigger in triggers:
            if trigger in user_message.lower():
                idx = user_message.lower().find(trigger)
                after_trigger = user_message[idx + len(trigger):].strip()
                if len(after_trigger) > 5:
                    return {
                        "error_pattern": self._extract_key_phrase(previous_response),
                        "correct_response": after_trigger,
                        "extraction_method": "after_trigger",
                        "confidence": 0.6
                    }

        # Fallback - use whole message as correction
        return {
            "error_pattern": self._extract_key_phrase(previous_response),
            "correct_response": user_message,
            "extraction_method": "fallback",
            "confidence": 0.4
        }

    def _extract_key_phrase(self, text: str, max_words: int = 5) -> str:
        """Extract key phrase from text for pattern matching."""
        if not text:
            return ""
        # Get first meaningful sentence
        sentences = re.split(r'[.!?]', text)
        first = sentences[0] if sentences else text
        words = first.split()[:max_words]
        return " ".join(words)

    # ==================== STORAGE ====================

    def store_correction(
        self,
        error_type: str,
        error_pattern: str,
        correction_text: str,
        correct_response: str = None,
        original_response: str = None,
        error_context: str = None,
        confidence: float = 0.5,
        session_id: str = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """
        Store a correction pattern in the database.
        """
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO correction_patterns
                        (error_type, error_pattern, correction_text, correct_response,
                         original_response, error_context, confidence, session_id, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (error_type, error_pattern) DO UPDATE SET
                        occurrence_count = correction_patterns.occurrence_count + 1,
                        confidence = GREATEST(correction_patterns.confidence, EXCLUDED.confidence),
                        correct_response = COALESCE(EXCLUDED.correct_response, correction_patterns.correct_response),
                        last_triggered = NOW(),
                        updated_at = NOW()
                    RETURNING id, occurrence_count
                """, (
                    error_type, error_pattern, correction_text, correct_response,
                    original_response, error_context, confidence, session_id, user_id
                ))
                result = cur.fetchone()

            logger.info(f"Stored correction pattern: {error_type}/{error_pattern[:30]}...")
            return {
                "success": True,
                "correction_id": result[0],
                "occurrence_count": result[1],
                "is_new": result[1] == 1
            }

        except Exception as e:
            logger.error(f"Failed to store correction: {e}")
            return {"success": False, "error": str(e)}

    # ==================== LOOKUP ====================

    def get_relevant_corrections(
        self,
        query: str,
        error_types: List[str] = None,
        min_confidence: float = 0.5,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get corrections relevant to a query.

        Args:
            query: The current query to check against
            error_types: Filter by error types (optional)
            min_confidence: Minimum confidence threshold
            limit: Max corrections to return

        Returns:
            List of relevant correction patterns
        """
        try:
            with get_dict_cursor() as cur:
                # Build query dynamically
                sql = """
                    SELECT error_type, error_pattern, correct_response,
                           confidence, occurrence_count, correction_text
                    FROM correction_patterns
                    WHERE is_active = TRUE
                      AND confidence >= %s
                """
                params = [min_confidence]

                if error_types:
                    sql += " AND error_type = ANY(%s)"
                    params.append(error_types)

                # Check if any pattern matches the query
                sql += """
                    ORDER BY
                        CASE WHEN %s ILIKE '%%' || error_pattern || '%%' THEN 1 ELSE 2 END,
                        confidence DESC,
                        occurrence_count DESC
                    LIMIT %s
                """
                params.extend([query, limit])

                cur.execute(sql, params)
                rows = cur.fetchall()

            # Filter to only matching patterns
            corrections = []
            query_lower = query.lower()
            for row in rows:
                pattern = row["error_pattern"].lower()
                if pattern in query_lower or self._fuzzy_match(pattern, query_lower):
                    corrections.append(dict(row))

            return corrections

        except Exception as e:
            logger.error(f"Failed to get corrections: {e}")
            return []

    def _fuzzy_match(self, pattern: str, text: str, threshold: float = 0.7) -> bool:
        """Simple fuzzy matching - checks if enough words from pattern appear in text."""
        pattern_words = set(pattern.split())
        text_words = set(text.split())
        if not pattern_words:
            return False
        match_count = len(pattern_words & text_words)
        return match_count / len(pattern_words) >= threshold

    # ==================== PROCESS CORRECTION ====================

    def process_correction(
        self,
        user_message: str,
        previous_response: str,
        session_id: str = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """
        Full correction processing pipeline:
        1. Detect if message is a correction
        2. Extract pattern
        3. Store for future reference

        Returns:
            Processing result with detection info and storage result
        """
        # Step 1: Detect
        detection = self.detect_correction(user_message, previous_response)
        if not detection.get("is_correction"):
            return {
                "processed": False,
                "reason": "not_a_correction"
            }

        # Step 2: Determine error type
        error_type = self._infer_error_type(user_message, previous_response)

        # Step 3: Extract pattern
        extraction = self.extract_correction_pattern(
            user_message, previous_response, error_type
        )

        # Step 4: Store
        storage = self.store_correction(
            error_type=error_type,
            error_pattern=extraction["error_pattern"],
            correction_text=user_message,
            correct_response=extraction.get("correct_response"),
            original_response=previous_response,
            confidence=min(detection["confidence"], extraction["confidence"]),
            session_id=session_id,
            user_id=user_id
        )

        # Step 5: Log audit
        self._log_audit(
            correction_id=storage.get("correction_id"),
            action="detected",
            query_text=user_message,
            session_id=session_id,
            user_id=user_id
        )

        return {
            "processed": True,
            "detection": detection,
            "extraction": extraction,
            "storage": storage,
            "error_type": error_type
        }

    def _infer_error_type(self, correction: str, original: str) -> str:
        """Infer the type of error from the correction context."""
        correction_lower = correction.lower()

        # Check for name corrections
        name_patterns = ["heisst", "heißt", "name ist", "called", "named"]
        if any(p in correction_lower for p in name_patterns):
            return "name"

        # Check for preference corrections
        pref_patterns = ["ich möchte", "ich will", "lieber", "prefer", "rather"]
        if any(p in correction_lower for p in pref_patterns):
            return "preference"

        # Check for factual corrections
        fact_patterns = ["das stimmt nicht", "thats not true", "actually its", "in wirklichkeit"]
        if any(p in correction_lower for p in fact_patterns):
            return "factual"

        # Check for tone corrections
        tone_patterns = ["zu formal", "too formal", "zu locker", "too casual"]
        if any(p in correction_lower for p in tone_patterns):
            return "tone"

        return "general"

    def _log_audit(
        self,
        correction_id: int,
        action: str,
        query_text: str = None,
        response_modified: bool = False,
        session_id: str = None,
        user_id: int = None
    ):
        """Log correction audit entry."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO correction_audit
                        (correction_id, action, query_text, response_modified, session_id, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (correction_id, action, query_text, response_modified, session_id, user_id))
        except Exception as e:
            logger.warning(f"Failed to log correction audit: {e}")

    # ==================== STATS ====================

    def get_correction_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get correction statistics."""
        try:
            with get_dict_cursor() as cur:
                # Total corrections
                cur.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(CASE WHEN is_verified THEN 1 END) as verified,
                           AVG(confidence) as avg_confidence,
                           AVG(occurrence_count) as avg_occurrences
                    FROM correction_patterns
                    WHERE is_active = TRUE
                """)
                totals = dict(cur.fetchone())

                # By type
                cur.execute("""
                    SELECT error_type, COUNT(*) as count, AVG(confidence) as avg_conf
                    FROM correction_patterns
                    WHERE is_active = TRUE
                    GROUP BY error_type
                    ORDER BY count DESC
                """)
                by_type = [dict(r) for r in cur.fetchall()]

                # Recent detections
                cur.execute("""
                    SELECT action, COUNT(*) as count
                    FROM correction_audit
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY action
                """, (days,))
                recent_actions = {r["action"]: r["count"] for r in cur.fetchall()}

            return {
                "success": True,
                "total_patterns": totals["total"],
                "verified_patterns": totals["verified"],
                "avg_confidence": round(totals["avg_confidence"] or 0, 3),
                "avg_occurrences": round(totals["avg_occurrences"] or 0, 1),
                "by_type": by_type,
                "recent_actions": recent_actions,
                "period_days": days
            }

        except Exception as e:
            logger.error(f"Failed to get correction stats: {e}")
            return {"success": False, "error": str(e)}
