"""
Auto Context Summarizer Service
Phase 19.2: Automatically generates conversation_contexts from session_messages

Runs periodically to:
1. Find sessions with messages but no/outdated conversation_contexts
2. Generate summaries, extract topics and pending actions
3. Insert/update conversation_contexts table

This fixes the gap where Jarvis doesn't always call remember_conversation_context.
"""

import sqlite3
import threading
import time
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.auto_context_summarizer")

STATE_DB_PATH = "/brain/system/state/jarvis_state.db"

# Simple keyword extraction for topics (no LLM needed)
TOPIC_KEYWORDS = {
    "project": ["projekt", "project", "aufgabe", "task"],
    "meeting": ["meeting", "termin", "call", "besprechung"],
    "deadline": ["deadline", "frist", "bis", "until"],
    "bug": ["bug", "fehler", "error", "problem", "issue"],
    "feature": ["feature", "funktion", "neu", "new"],
    "review": ["review", "check", "prüfen", "testen"],
    "deploy": ["deploy", "release", "live", "production"],
    "memory": ["memory", "gedächtnis", "erinnern", "recall"],
    "email": ["email", "mail", "nachricht"],
    "calendar": ["kalender", "calendar", "termin", "event"],
    "personal": ["adhd", "persönlich", "personal", "privat"],
    "work": ["arbeit", "work", "projektil", "visualfox", "job"],
}

# Action indicators
ACTION_PATTERNS = [
    r"(?:ich (?:werde|muss|sollte)|todo|task|aktion|action|machen|erledigen|checken)\s*[:\-]?\s*(.{10,100})",
    r"(?:bitte|please)\s+(.{10,80})",
    r"(?:vergiss nicht|don't forget|reminder)\s*[:\-]?\s*(.{10,80})",
]


class AutoContextSummarizer:
    """Automatic context summarization service."""

    _instance: Optional["AutoContextSummarizer"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = STATE_DB_PATH):
        self.db_path = db_path
        self._summarize_thread: Optional[threading.Thread] = None
        self._running = False

    @classmethod
    def get_instance(cls) -> "AutoContextSummarizer":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(STATE_DB_PATH)
        return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _extract_topics(self, messages: List[Dict]) -> List[str]:
        """Extract topics from messages using keyword matching."""
        all_text = " ".join(m.get("content", "").lower() for m in messages)
        found_topics = []

        for topic, keywords in TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in all_text:
                    found_topics.append(topic)
                    break

        return list(set(found_topics))[:5]  # Max 5 topics

    def _extract_actions(self, messages: List[Dict]) -> List[str]:
        """Extract potential action items from messages."""
        actions = []

        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")

            for pattern in ACTION_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    clean = match.strip()
                    if len(clean) > 10 and clean not in actions:
                        actions.append(clean[:100])

        return actions[:5]  # Max 5 actions

    def _generate_summary(self, messages: List[Dict]) -> str:
        """Generate a simple summary without LLM."""
        if not messages:
            return "Empty session"

        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        # Get first user message as context
        first_query = user_msgs[0].get("content", "")[:200] if user_msgs else ""

        # Count tool calls
        tool_calls = []
        for m in assistant_msgs:
            tc = m.get("tool_calls")
            if tc:
                try:
                    tools = eval(tc) if isinstance(tc, str) else tc
                    if isinstance(tools, list):
                        tool_calls.extend(tools)
                except:
                    pass

        summary = f"Session with {len(user_msgs)} queries"
        if tool_calls:
            unique_tools = list(set(tool_calls))[:3]
            summary += f", used tools: {', '.join(unique_tools)}"
        if first_query:
            summary += f". Started with: '{first_query[:100]}...'"

        return summary

    def _detect_emotional_indicators(self, messages: List[Dict]) -> Dict[str, Any]:
        """Simple emotional indicator detection."""
        all_text = " ".join(m.get("content", "").lower() for m in messages if m.get("role") == "user")

        indicators = {
            "dominant": "neutral",
            "frustration": 0.0,
            "urgency": 0.0,
            "satisfaction": 0.0,
        }

        # Frustration indicators
        if any(w in all_text for w in ["funktioniert nicht", "broken", "kaputt", "fehler", "bug", "problem"]):
            indicators["frustration"] = 0.3
            indicators["dominant"] = "frustrated"

        # Urgency indicators
        if any(w in all_text for w in ["dringend", "urgent", "schnell", "asap", "sofort", "jetzt"]):
            indicators["urgency"] = 0.5
            if indicators["dominant"] == "neutral":
                indicators["dominant"] = "urgent"

        # Satisfaction indicators
        if any(w in all_text for w in ["danke", "thanks", "super", "perfekt", "toll", "great", "gut"]):
            indicators["satisfaction"] = 0.4
            indicators["dominant"] = "satisfied"

        return indicators

    def summarize_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Generate a context summary for a specific session.

        Returns the generated context dict or None if failed.
        """
        try:
            with self._get_connection() as conn:
                # Get all messages for this session
                cursor = conn.execute("""
                    SELECT session_id, user_id, timestamp, role, content, tool_calls
                    FROM session_messages
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                """, (session_id,))

                messages = [dict(row) for row in cursor.fetchall()]

                if not messages:
                    return None

                # Extract metadata
                user_id = messages[0].get("user_id")
                first_ts = messages[0].get("timestamp", "")
                last_ts = messages[-1].get("timestamp", "")

                # Generate summary components
                summary = self._generate_summary(messages)
                topics = self._extract_topics(messages)
                actions = self._extract_actions(messages)
                emotions = self._detect_emotional_indicators(messages)

                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "namespace": "general",
                    "start_time": first_ts,
                    "end_time": last_ts,
                    "conversation_summary": summary,
                    "key_topics": topics,
                    "pending_actions": actions,
                    "emotional_indicators": emotions,
                    "message_count": len(messages),
                    "source": "auto_summarizer"
                }

                return context

        except Exception as e:
            log_with_context(logger, "error", "Failed to summarize session",
                           session_id=session_id, error=str(e))
            return None

    def update_conversation_context(self, context: Dict[str, Any]) -> bool:
        """Insert or update a conversation context in the database."""
        import json

        try:
            with self._get_connection() as conn:
                now = datetime.utcnow().isoformat()

                conn.execute("""
                    INSERT INTO conversation_contexts (
                        session_id, user_id, namespace, start_time, end_time,
                        conversation_summary, key_topics, pending_actions,
                        emotional_indicators, message_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        end_time = excluded.end_time,
                        conversation_summary = excluded.conversation_summary,
                        key_topics = excluded.key_topics,
                        pending_actions = excluded.pending_actions,
                        emotional_indicators = excluded.emotional_indicators,
                        message_count = excluded.message_count
                """, (
                    context["session_id"],
                    context.get("user_id"),
                    context.get("namespace", "general"),
                    context["start_time"],
                    context["end_time"],
                    context["conversation_summary"],
                    json.dumps(context.get("key_topics", [])),
                    json.dumps(context.get("pending_actions", [])),
                    json.dumps(context.get("emotional_indicators", {})),
                    context.get("message_count", 0),
                    now
                ))

                # Phase 19.3: Also update topic_mentions table for cross-session tracking
                session_id = context["session_id"]
                user_id = context.get("user_id")
                if user_id:
                    for topic in context.get("key_topics", []):
                        topic_lower = topic.lower()
                        # Check if exists
                        cursor = conn.execute(
                            "SELECT id, mention_count FROM topic_mentions WHERE user_id = ? AND topic = ?",
                            (user_id, topic_lower)
                        )
                        existing = cursor.fetchone()
                        if existing:
                            conn.execute("""
                                UPDATE topic_mentions
                                SET mention_count = mention_count + 1, last_mentioned = ?, session_id = ?
                                WHERE id = ?
                            """, (now, session_id, existing[0]))
                        else:
                            conn.execute("""
                                INSERT INTO topic_mentions (session_id, user_id, topic, first_mentioned, last_mentioned)
                                VALUES (?, ?, ?, ?, ?)
                            """, (session_id, user_id, topic_lower, now, now))

                conn.commit()

            log_with_context(logger, "info", "Updated conversation context",
                           session_id=context["session_id"],
                           message_count=context.get("message_count", 0),
                           topics_updated=len(context.get("key_topics", [])))
            return True

        except Exception as e:
            log_with_context(logger, "error", "Failed to update conversation context",
                           session_id=context.get("session_id"), error=str(e))
            return False

    def sync_all_sessions(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Sync all sessions from session_messages to conversation_contexts.

        Args:
            hours_back: How many hours to look back

        Returns:
            Stats dict with synced/failed counts
        """
        stats = {"synced": 0, "failed": 0, "skipped": 0}

        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours_back)).isoformat()

            with self._get_connection() as conn:
                # Find sessions with recent messages
                cursor = conn.execute("""
                    SELECT DISTINCT session_id, MAX(timestamp) as last_msg
                    FROM session_messages
                    WHERE timestamp > ?
                    GROUP BY session_id
                    ORDER BY last_msg DESC
                """, (cutoff,))

                sessions = cursor.fetchall()

            log_with_context(logger, "info", "Starting session sync",
                           sessions_found=len(sessions), hours_back=hours_back)

            for row in sessions:
                session_id = row[0]

                # Generate and save context
                context = self.summarize_session(session_id)
                if context:
                    if self.update_conversation_context(context):
                        stats["synced"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    stats["skipped"] += 1

            log_with_context(logger, "info", "Session sync completed", **stats)

        except Exception as e:
            log_with_context(logger, "error", "Session sync failed", error=str(e))

        return stats

    def start_background_sync(self, interval_minutes: int = 30) -> None:
        """Start background sync thread."""
        if self._running:
            return

        self._running = True

        def sync_loop():
            # Initial sync on startup
            time.sleep(10)  # Wait for other services to initialize
            self.sync_all_sessions(hours_back=24 * 7)  # Sync last 7 days on startup

            while self._running:
                time.sleep(interval_minutes * 60)
                if self._running:
                    self.sync_all_sessions(hours_back=2)  # Sync last 2 hours periodically

        self._summarize_thread = threading.Thread(target=sync_loop, daemon=True)
        self._summarize_thread.start()
        log_with_context(logger, "info", "Background sync started",
                        interval_minutes=interval_minutes)

    def stop_background_sync(self) -> None:
        """Stop background sync thread."""
        self._running = False
        log_with_context(logger, "info", "Background sync stopped")


# Singleton accessor
def get_auto_context_summarizer() -> AutoContextSummarizer:
    """Get the auto context summarizer service instance."""
    return AutoContextSummarizer.get_instance()
