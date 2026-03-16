"""
Auto Session Persist Service
Phase 19.1: Automatic message tracking without explicit tool calls

Tracks messages automatically after each Telegram interaction.
Generates simple summaries (no LLM call).
Persists to SQLite jarvis_state.db.
Background cleanup every 10 minutes.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.auto_session_persist")

# State DB path (inside container)
STATE_DB_PATH = "/brain/system/state/jarvis_state.db"


class AutoSessionPersist:
    """Automatic session message persistence service."""

    _instance: Optional["AutoSessionPersist"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = STATE_DB_PATH):
        self.db_path = db_path
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._ensure_table()

    @classmethod
    def get_instance(cls) -> "AutoSessionPersist":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(STATE_DB_PATH)
        return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Ensure session_messages table exists."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS session_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        user_id INTEGER,
                        timestamp TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        message_index INTEGER,
                        tool_calls TEXT,
                        token_count INTEGER,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session_messages_user ON session_messages(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session_messages_timestamp ON session_messages(timestamp DESC)")
                conn.commit()
                log_with_context(logger, "debug", "session_messages table ensured")
        except Exception as e:
            log_with_context(logger, "error", "Failed to ensure session_messages table", error=str(e))

    def track_message(
        self,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
        message_index: int = 0,
        tool_calls: Optional[List[str]] = None,
        token_count: Optional[int] = None
    ) -> bool:
        """
        Track a single message in the session.

        Args:
            session_id: Current session identifier
            user_id: Telegram user ID
            role: 'user' or 'assistant'
            content: Message content (truncated to 10KB)
            message_index: Position in conversation
            tool_calls: List of tool names used (for assistant messages)
            token_count: Estimated token count

        Returns:
            True if successfully tracked, False otherwise
        """
        try:
            # Truncate content to prevent DB bloat
            content_truncated = content[:10000] if content else ""
            tool_calls_json = str(tool_calls) if tool_calls else None
            timestamp = datetime.utcnow().isoformat()

            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO session_messages
                    (session_id, user_id, timestamp, role, content, message_index, tool_calls, token_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    user_id,
                    timestamp,
                    role,
                    content_truncated,
                    message_index,
                    tool_calls_json,
                    token_count,
                    timestamp
                ))
                conn.commit()

            log_with_context(
                logger, "debug", "Message tracked",
                session_id=session_id, role=role, user_id=user_id
            )
            return True

        except Exception as e:
            log_with_context(
                logger, "error", "Failed to track message",
                session_id=session_id, error=str(e)
            )
            return False

    def get_recent_messages(
        self,
        user_id: Optional[int] = None,
        limit: int = 20,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get recent messages for a user (or all users if user_id is None).

        Args:
            user_id: Telegram user ID (optional - if None, returns all users)
            limit: Max messages to return
            hours: Look back period

        Returns:
            List of message dicts
        """
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

            with self._get_connection() as conn:
                if user_id:
                    cursor = conn.execute("""
                        SELECT session_id, timestamp, role, content, tool_calls
                        FROM session_messages
                        WHERE user_id = ? AND timestamp > ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (user_id, cutoff, limit))
                else:
                    # No user filter - return all recent messages
                    cursor = conn.execute("""
                        SELECT session_id, timestamp, role, content, tool_calls
                        FROM session_messages
                        WHERE timestamp > ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (cutoff, limit))

                rows = cursor.fetchall()
                return [dict(row) for row in rows]

        except Exception as e:
            log_with_context(logger, "error", "Failed to get recent messages", error=str(e))
            return []

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Generate a simple summary for a session (no LLM call).

        Returns:
            Dict with message_count, roles, first/last timestamp, topics (keywords)
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT role, content, timestamp, tool_calls
                    FROM session_messages
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                """, (session_id,))

                rows = cursor.fetchall()

                if not rows:
                    return {"message_count": 0, "summary": "No messages"}

                user_count = sum(1 for r in rows if r["role"] == "user")
                assistant_count = sum(1 for r in rows if r["role"] == "assistant")

                # Extract simple keywords from user messages
                all_user_content = " ".join(r["content"] for r in rows if r["role"] == "user")
                # Simple keyword extraction: words > 5 chars, lowercase
                words = [w.lower() for w in all_user_content.split() if len(w) > 5]
                # Count frequency
                word_freq = {}
                for w in words:
                    word_freq[w] = word_freq.get(w, 0) + 1
                top_keywords = sorted(word_freq.items(), key=lambda x: -x[1])[:5]

                # Collect tool calls
                all_tools = []
                for r in rows:
                    if r["tool_calls"]:
                        try:
                            tools = eval(r["tool_calls"]) if isinstance(r["tool_calls"], str) else r["tool_calls"]
                            if isinstance(tools, list):
                                all_tools.extend(tools)
                        except:
                            pass

                return {
                    "message_count": len(rows),
                    "user_messages": user_count,
                    "assistant_messages": assistant_count,
                    "first_message": rows[0]["timestamp"],
                    "last_message": rows[-1]["timestamp"],
                    "top_keywords": [k for k, _ in top_keywords],
                    "tools_used": list(set(all_tools))
                }

        except Exception as e:
            log_with_context(logger, "error", "Failed to get session summary", error=str(e))
            return {"error": str(e)}

    def cleanup_old_messages(self, days: int = 30) -> int:
        """
        Delete messages older than specified days.

        Returns:
            Number of messages deleted
        """
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            with self._get_connection() as conn:
                cursor = conn.execute("""
                    DELETE FROM session_messages
                    WHERE created_at < ?
                """, (cutoff,))
                deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                log_with_context(logger, "info", "Cleaned up old messages", deleted=deleted, days=days)
            return deleted

        except Exception as e:
            log_with_context(logger, "error", "Failed to cleanup messages", error=str(e))
            return 0

    def start_background_cleanup(self, interval_minutes: int = 10) -> None:
        """Start background cleanup thread."""
        if self._running:
            return

        self._running = True

        def cleanup_loop():
            while self._running:
                time.sleep(interval_minutes * 60)
                if self._running:
                    self.cleanup_old_messages(days=30)

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        log_with_context(logger, "info", "Background cleanup started", interval_minutes=interval_minutes)

    def stop_background_cleanup(self) -> None:
        """Stop background cleanup thread."""
        self._running = False
        log_with_context(logger, "info", "Background cleanup stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get session message statistics."""
        try:
            with self._get_connection() as conn:
                # Total messages
                total = conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0]

                # Messages by role
                by_role = conn.execute("""
                    SELECT role, COUNT(*) as count
                    FROM session_messages
                    GROUP BY role
                """).fetchall()

                # Unique users
                users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM session_messages").fetchone()[0]

                # Unique sessions
                sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM session_messages").fetchone()[0]

                # Recent activity
                recent_24h = conn.execute("""
                    SELECT COUNT(*) FROM session_messages
                    WHERE timestamp > datetime('now', '-1 day')
                """).fetchone()[0]

                return {
                    "total_messages": total,
                    "by_role": {r["role"]: r["count"] for r in by_role},
                    "unique_users": users,
                    "unique_sessions": sessions,
                    "messages_last_24h": recent_24h,
                    "cleanup_running": self._running
                }

        except Exception as e:
            log_with_context(logger, "error", "Failed to get stats", error=str(e))
            return {"error": str(e)}


# Singleton accessor
def get_auto_session_persist() -> AutoSessionPersist:
    """Get the auto session persist service instance."""
    return AutoSessionPersist.get_instance()
