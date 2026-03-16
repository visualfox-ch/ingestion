"""
Memory Lifecycle Service
Phase 19.4: Automatic learning, pattern detection, and memory consolidation.

Features:
1. Auto-detect and log Jarvis suggestions/recommendations
2. Detect positive/negative outcomes from user responses
3. Cross-session pattern detection (weekly job)
4. Memory consolidation and cleanup (daily job)
"""

import re
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.memory_lifecycle")

# Patterns indicating Jarvis gave advice/suggestion
SUGGESTION_PATTERNS = [
    r"(?:ich (?:empfehle|schlage vor|rate)|du (?:solltest|könntest)|versuch(?:e|s)? (?:mal)?|mein (?:vorschlag|rat|tipp))",
    r"(?:i (?:suggest|recommend)|you (?:should|could|might)|try|my (?:suggestion|advice|tip))",
    r"(?:hier (?:ist|sind)|so (?:geht|funktioniert)|das (?:hilft|funktioniert))",
]

# Patterns indicating positive outcome
POSITIVE_OUTCOME_PATTERNS = [
    r"(?:danke|thanks|thx|super|perfekt|toll|great|awesome|genial|funktioniert|hat geklappt|worked)",
    r"(?:ja,? das|yes,? that|genau|exactly|richtig|correct|stimmt)",
    r"(?:👍|✅|🎉|❤️|😊|🙏)",
]

# Patterns indicating negative outcome
NEGATIVE_OUTCOME_PATTERNS = [
    r"(?:funktioniert nicht|doesn't work|didn't work|hat nicht|klappt nicht|geht nicht)",
    r"(?:nein|no|falsch|wrong|incorrect|fehler|error|problem)",
    r"(?:👎|❌|😕|😞|🙁)",
]

# Topics to track for patterns (German + English keywords)
PATTERN_TOPICS = {
    "memory": ["gedächnis", "gedächtnis", "memory", "erinnern", "recall", "vergessen", "forget"],
    "productivity": ["produktiv", "focus", "konzentration", "ablenkung", "todo", "aufgabe", "task"],
    "stress": ["stress", "überwältigt", "overwhelm", "müde", "erschöpft", "exhausted", "dringend"],
    "projects": ["projekt", "project", "visualfox", "projektil", "deadline", "arbeit", "work"],
    "technical": ["code", "bug", "deploy", "api", "docker", "python", "tool", "system", "fehler"],
    "personal": ["adhd", "energie", "energy", "schlaf", "sleep", "motivation", "persönlich"],
    "planning": ["plan", "ziel", "goal", "strategie", "strategy", "priorität", "priority"],
    "health": ["gesundheit", "health", "problem", "hürden", "blocker", "funktioniert"],
}


class MemoryLifecycleService:
    """Manages the full lifecycle of Jarvis memory and learning."""

    _instance: Optional["MemoryLifecycleService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._consolidation_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_consolidation: Optional[datetime] = None
        self._last_pattern_detection: Optional[datetime] = None

    @classmethod
    def get_instance(cls) -> "MemoryLifecycleService":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def detect_suggestion_in_response(self, response: str) -> Optional[str]:
        """
        Detect if Jarvis response contains a suggestion/recommendation.
        Returns the suggestion text if found, None otherwise.
        """
        response_lower = response.lower()
        for pattern in SUGGESTION_PATTERNS:
            if re.search(pattern, response_lower, re.IGNORECASE):
                # Extract first 200 chars as suggestion summary
                return response[:200].strip()
        return None

    def detect_outcome_in_message(self, message: str) -> Optional[Tuple[str, float]]:
        """
        Detect if user message indicates outcome of previous suggestion.
        Returns (outcome_type, confidence) or None.
        outcome_type: 'positive', 'negative', 'neutral'
        """
        message_lower = message.lower()

        # Check positive patterns
        for pattern in POSITIVE_OUTCOME_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return ("positive", 0.8)

        # Check negative patterns
        for pattern in NEGATIVE_OUTCOME_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return ("negative", 0.8)

        return None

    def auto_log_suggestion(
        self,
        user_id: int,
        session_id: str,
        suggestion_text: str,
        context: str = "",
        confidence: float = 0.7
    ) -> Optional[str]:
        """
        Automatically log a detected suggestion for later outcome tracking.
        Returns suggestion_id or None on failure.
        """
        try:
            from ..cross_session_learner import CrossSessionLearner
            learner = CrossSessionLearner()

            suggestion_id = learner.log_suggestion(
                user_id=user_id,
                session_id=session_id,
                suggestion_text=suggestion_text,
                suggestion_type="auto_detected",
                context=context,
                confidence=confidence,
                followup_hours=24  # Check back in 24 hours
            )

            log_with_context(logger, "info", "Auto-logged suggestion",
                           suggestion_id=suggestion_id, user_id=user_id)
            return suggestion_id

        except Exception as e:
            log_with_context(logger, "error", "Failed to auto-log suggestion",
                           error=str(e))
            return None

    def auto_record_outcome(
        self,
        user_id: int,
        outcome_type: str,
        confidence: float = 0.8
    ) -> int:
        """
        Automatically record outcome for the most recent pending suggestion.
        Returns number of suggestions updated.
        """
        try:
            from ..cross_session_learner import CrossSessionLearner
            learner = CrossSessionLearner()

            # Get pending followups for this user
            pending = learner.get_pending_followups(user_id=user_id)
            if not pending:
                return 0

            # Update the most recent one
            outcome_map = {
                "positive": "worked",
                "negative": "didnt_work",
                "neutral": "partially"
            }
            outcome = outcome_map.get(outcome_type, "partially")

            # Record outcome for most recent
            most_recent = pending[0]
            learner.record_suggestion_outcome(
                suggestion_id=most_recent["suggestion_id"],
                outcome=outcome,
                notes=f"Auto-detected {outcome_type} outcome"
            )

            log_with_context(logger, "info", "Auto-recorded outcome",
                           suggestion_id=most_recent["suggestion_id"],
                           outcome=outcome)
            return 1

        except Exception as e:
            log_with_context(logger, "error", "Failed to auto-record outcome",
                           error=str(e))
            return 0

    def detect_cross_session_patterns(self, user_id: int, days_back: int = 30) -> List[Dict[str, Any]]:
        """
        Analyze session messages for recurring patterns.
        Returns list of detected patterns with confidence scores.
        """
        try:
            from .auto_session_persist import get_auto_session_persist
            persist = get_auto_session_persist()

            # Get all messages for analysis
            messages = persist.get_recent_messages(
                user_id=user_id,
                limit=500,
                hours=days_back * 24
            )

            if not messages:
                return []

            # Combine all user messages
            user_text = " ".join(
                m.get("content", "").lower()
                for m in messages
                if m.get("role") == "user"
            )

            detected_patterns = []

            # Check each topic category
            for category, keywords in PATTERN_TOPICS.items():
                mentions = sum(user_text.count(kw) for kw in keywords)
                if mentions >= 3:  # Minimum threshold
                    # Calculate frequency
                    total_words = len(user_text.split())
                    frequency = mentions / max(total_words, 1) * 1000  # per 1000 words

                    detected_patterns.append({
                        "category": category,
                        "keywords_found": [kw for kw in keywords if kw in user_text],
                        "mention_count": mentions,
                        "frequency_per_1k": round(frequency, 2),
                        "confidence": min(0.9, 0.3 + (mentions * 0.1)),
                        "detected_at": datetime.utcnow().isoformat()
                    })

            # Sort by mention count
            detected_patterns.sort(key=lambda x: x["mention_count"], reverse=True)

            log_with_context(logger, "info", "Pattern detection completed",
                           user_id=user_id, patterns_found=len(detected_patterns))

            return detected_patterns

        except Exception as e:
            log_with_context(logger, "error", "Pattern detection failed",
                           user_id=user_id, error=str(e))
            return []

    def consolidate_memory(self, days_to_keep: int = 30) -> Dict[str, Any]:
        """
        Consolidate and clean up memory:
        1. Archive old session_messages (keep summary in conversation_contexts)
        2. Merge duplicate topic_mentions
        3. Clean up completed pending_actions
        4. Update topic mention counts
        """
        stats = {
            "messages_archived": 0,
            "topics_merged": 0,
            "actions_cleaned": 0,
            "errors": []
        }

        try:
            import sqlite3
            db_path = "/brain/system/state/jarvis_state.db"
            conn = sqlite3.connect(db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            now = datetime.utcnow().isoformat()
            cutoff = (datetime.utcnow() - timedelta(days=days_to_keep)).isoformat()

            # 1. Archive old messages (keep last N per session)
            cursor = conn.execute("""
                DELETE FROM session_messages
                WHERE id NOT IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY session_id
                            ORDER BY timestamp DESC
                        ) as rn
                        FROM session_messages
                    ) WHERE rn <= 50
                )
                AND timestamp < ?
            """, (cutoff,))
            stats["messages_archived"] = cursor.rowcount

            # 2. Merge duplicate topic_mentions (same user, same topic)
            cursor = conn.execute("""
                SELECT user_id, topic, COUNT(*) as cnt
                FROM topic_mentions
                GROUP BY user_id, topic
                HAVING COUNT(*) > 1
            """)
            duplicates = cursor.fetchall()

            for dup in duplicates:
                # Keep the one with highest mention_count, sum them
                conn.execute("""
                    UPDATE topic_mentions
                    SET mention_count = (
                        SELECT SUM(mention_count)
                        FROM topic_mentions
                        WHERE user_id = ? AND topic = ?
                    ),
                    last_mentioned = (
                        SELECT MAX(last_mentioned)
                        FROM topic_mentions
                        WHERE user_id = ? AND topic = ?
                    )
                    WHERE id = (
                        SELECT id FROM topic_mentions
                        WHERE user_id = ? AND topic = ?
                        ORDER BY mention_count DESC
                        LIMIT 1
                    )
                """, (dup["user_id"], dup["topic"]) * 3)

                # Delete the duplicates
                conn.execute("""
                    DELETE FROM topic_mentions
                    WHERE user_id = ? AND topic = ?
                    AND id NOT IN (
                        SELECT id FROM topic_mentions
                        WHERE user_id = ? AND topic = ?
                        ORDER BY mention_count DESC
                        LIMIT 1
                    )
                """, (dup["user_id"], dup["topic"]) * 2)
                stats["topics_merged"] += 1

            # 3. Clean up old completed pending_actions
            old_completed_cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
            cursor = conn.execute("""
                DELETE FROM pending_actions
                WHERE completed = 1 AND completed_at < ?
            """, (old_completed_cutoff,))
            stats["actions_cleaned"] = cursor.rowcount

            conn.commit()
            conn.close()

            self._last_consolidation = datetime.utcnow()
            log_with_context(logger, "info", "Memory consolidation completed", **stats)

        except Exception as e:
            stats["errors"].append(str(e))
            log_with_context(logger, "error", "Memory consolidation failed", error=str(e))

        return stats

    def start_background_jobs(self, consolidation_interval_hours: int = 24) -> None:
        """Start background consolidation and pattern detection jobs."""
        if self._running:
            return

        self._running = True

        def job_loop():
            # Initial delay
            time.sleep(60)

            while self._running:
                try:
                    # Run consolidation if due
                    if (self._last_consolidation is None or
                        datetime.utcnow() - self._last_consolidation > timedelta(hours=consolidation_interval_hours)):
                        self.consolidate_memory(days_to_keep=30)

                except Exception as e:
                    log_with_context(logger, "error", "Background job failed", error=str(e))

                # Sleep for 1 hour between checks
                time.sleep(3600)

        self._consolidation_thread = threading.Thread(target=job_loop, daemon=True)
        self._consolidation_thread.start()
        log_with_context(logger, "info", "Memory lifecycle background jobs started")

    def stop_background_jobs(self) -> None:
        """Stop background jobs."""
        self._running = False
        log_with_context(logger, "info", "Memory lifecycle background jobs stopped")

    def get_memory_health_report(self, user_id: int = None) -> Dict[str, Any]:
        """Generate a comprehensive memory health report."""
        try:
            import sqlite3
            db_path = "/brain/system/state/jarvis_state.db"
            conn = sqlite3.connect(db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row

            # Session messages stats
            cursor = conn.execute("""
                SELECT COUNT(*) as total,
                       COUNT(DISTINCT session_id) as sessions,
                       MIN(timestamp) as oldest,
                       MAX(timestamp) as newest
                FROM session_messages
            """)
            msg_stats = dict(cursor.fetchone())

            # Topic mentions stats
            cursor = conn.execute("""
                SELECT COUNT(*) as total_topics,
                       SUM(mention_count) as total_mentions,
                       MAX(last_mentioned) as most_recent
                FROM topic_mentions
            """)
            topic_stats = dict(cursor.fetchone())

            # Pending actions stats
            cursor = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN completed = 0 THEN 1 ELSE 0 END) as pending
                FROM pending_actions
            """)
            action_stats = dict(cursor.fetchone())

            conn.close()

            # Get learning stats
            try:
                from ..cross_session_learner import CrossSessionLearner
                learner = CrossSessionLearner()
                learning_stats = learner.get_suggestion_stats(days=30)
            except Exception:
                learning_stats = {"error": "Could not fetch learning stats"}

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "session_messages": msg_stats,
                "topic_mentions": topic_stats,
                "pending_actions": action_stats,
                "learning": learning_stats,
                "last_consolidation": self._last_consolidation.isoformat() if self._last_consolidation else None,
                "background_jobs_running": self._running
            }

        except Exception as e:
            return {"error": str(e)}


# Singleton accessor
def get_memory_lifecycle_service() -> MemoryLifecycleService:
    """Get the memory lifecycle service instance."""
    return MemoryLifecycleService.get_instance()
