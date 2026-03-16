"""
Cross-Session Continuity Service - Tier 3 #11

Enables agents to remember context from previous sessions:
- Session summaries for "where did we leave off?"
- Conversation threads that span multiple sessions
- Handoffs between sessions (reminders, follow-ups)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json

from app.observability import get_logger, log_with_context
from app.postgres_state import get_conn

logger = get_logger("jarvis.cross_session")


def _log(level: str, msg: str, **kwargs):
    """Helper to log with context."""
    log_with_context(logger, level, msg, **kwargs)


@dataclass
class SessionContext:
    """Context restored at session start."""
    user_id: str
    session_id: str

    # Previous session info
    last_session_summary: Optional[str] = None
    last_session_topics: List[str] = field(default_factory=list)
    last_session_ended: Optional[datetime] = None

    # Active threads
    active_threads: List[Dict[str, Any]] = field(default_factory=list)

    # Pending handoffs
    pending_handoffs: List[Dict[str, Any]] = field(default_factory=list)

    # User preferences
    show_recap: bool = True
    recap_verbosity: str = "brief"
    auto_resume: bool = True

    # Specialist context
    specialist_memories: Dict[str, List[Dict]] = field(default_factory=dict)


class CrossSessionService:
    """Service for managing cross-session continuity."""

    def __init__(self):
        self._initialized = False

    def _ensure_init(self):
        """Lazy initialization."""
        if not self._initialized:
            self._initialized = True
            _log("info", "CrossSessionService initialized")

    def restore_session_context(
        self,
        user_id: str,
        session_id: str,
        specialist: Optional[str] = None
    ) -> SessionContext:
        """
        Restore context when a new session starts.

        Returns everything the agent needs to continue naturally.
        """
        self._ensure_init()

        context = SessionContext(
            user_id=user_id,
            session_id=session_id
        )

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get user preferences
                    cur.execute("""
                        SELECT auto_resume_threads, show_session_recap,
                               recap_verbosity, specialist_memory_days
                        FROM jarvis_user_session_prefs
                        WHERE user_id = %s
                    """, (user_id,))

                    prefs = cur.fetchone()
                    if prefs:
                        context.auto_resume = prefs["auto_resume_threads"]
                        context.show_recap = prefs["show_session_recap"]
                        context.recap_verbosity = prefs["recap_verbosity"]
                        memory_days = prefs["specialist_memory_days"]
                    else:
                        memory_days = 30

                    # Get last session summary
                    cur.execute("""
                        SELECT session_id, summary, key_topics, ended_at,
                               primary_specialist, open_threads
                        FROM jarvis_session_summaries
                        WHERE user_id = %s AND ended_at IS NOT NULL
                        ORDER BY ended_at DESC
                        LIMIT 1
                    """, (user_id,))

                    last_session = cur.fetchone()
                    if last_session:
                        context.last_session_summary = last_session["summary"]
                        context.last_session_topics = last_session["key_topics"] or []
                        context.last_session_ended = last_session["ended_at"]

                    # Get active conversation threads
                    cur.execute("""
                        SELECT thread_id, topic, category, specialist,
                               context_summary, last_message_preview,
                               priority, last_active_at
                        FROM jarvis_conversation_threads
                        WHERE user_id = %s AND status = 'active'
                        ORDER BY priority DESC, last_active_at DESC
                        LIMIT 10
                    """, (user_id,))

                    context.active_threads = [
                        {
                            "thread_id": row["thread_id"],
                            "topic": row["topic"],
                            "category": row["category"],
                            "specialist": row["specialist"],
                            "summary": row["context_summary"],
                            "last_preview": row["last_message_preview"],
                            "priority": row["priority"],
                            "last_active": row["last_active_at"].isoformat() if row["last_active_at"] else None
                        }
                        for row in cur.fetchall()
                    ]

                    # Get pending handoffs
                    cur.execute("""
                        SELECT id, handoff_type, title, content,
                               from_specialist, for_specialist, priority
                        FROM jarvis_session_handoffs
                        WHERE user_id = %s
                          AND status = 'pending'
                          AND (expires_at IS NULL OR expires_at > NOW())
                          AND (for_specialist IS NULL OR for_specialist = %s)
                        ORDER BY priority DESC
                        LIMIT 5
                    """, (user_id, specialist))

                    context.pending_handoffs = [
                        {
                            "id": row["id"],
                            "type": row["handoff_type"],
                            "title": row["title"],
                            "content": row["content"],
                            "from_specialist": row["from_specialist"],
                            "for_specialist": row["for_specialist"],
                            "priority": row["priority"]
                        }
                        for row in cur.fetchall()
                    ]

                    # Mark handoffs as delivered
                    if context.pending_handoffs:
                        handoff_ids = [h["id"] for h in context.pending_handoffs]
                        cur.execute("""
                            UPDATE jarvis_session_handoffs
                            SET status = 'delivered',
                                to_session_id = %s,
                                delivered_at = NOW()
                            WHERE id = ANY(%s)
                        """, (session_id, handoff_ids))

                    # Get specialist memories if specialist specified
                    if specialist:
                        cutoff = datetime.now() - timedelta(days=memory_days)
                        cur.execute("""
                            SELECT memory_type, key, value, confidence
                            FROM jarvis_specialist_memory
                            WHERE specialist_name = %s
                              AND (expires_at IS NULL OR expires_at > NOW())
                              AND created_at > %s
                            ORDER BY use_count DESC, updated_at DESC
                            LIMIT 20
                        """, (specialist, cutoff))

                        memories = []
                        for row in cur.fetchall():
                            memories.append({
                                "type": row["memory_type"],
                                "key": row["key"],
                                "value": row["value"],
                                "confidence": row["confidence"]
                            })

                        if memories:
                            context.specialist_memories[specialist] = memories

                    conn.commit()

            _log("info", "Session context restored",
                user_id=user_id,
                session_id=session_id,
                threads=len(context.active_threads),
                handoffs=len(context.pending_handoffs),
                has_last_session=context.last_session_summary is not None)

        except Exception as e:
            _log("error", f"Failed to restore session context: {e}")

        return context

    def build_session_recap(self, context: SessionContext) -> Optional[str]:
        """
        Build a natural language recap for the user.

        Returns None if no recap is needed/wanted.
        """
        if not context.show_recap:
            return None

        parts = []

        # Time since last session
        if context.last_session_ended:
            delta = datetime.now() - context.last_session_ended
            if delta.days > 0:
                time_str = f"vor {delta.days} Tag{'en' if delta.days > 1 else ''}"
            elif delta.seconds > 3600:
                hours = delta.seconds // 3600
                time_str = f"vor {hours} Stunde{'n' if hours > 1 else ''}"
            else:
                time_str = "vor kurzem"

            if context.recap_verbosity == "detailed" and context.last_session_summary:
                parts.append(f"Letzte Session ({time_str}): {context.last_session_summary}")
            elif context.last_session_topics:
                topics = ", ".join(context.last_session_topics[:3])
                parts.append(f"Zuletzt ({time_str}): {topics}")

        # Active threads
        if context.active_threads and context.auto_resume:
            high_priority = [t for t in context.active_threads if t.get("priority", 50) > 70]
            if high_priority:
                thread_topics = [t["topic"] for t in high_priority[:2]]
                parts.append(f"Offene Themen: {', '.join(thread_topics)}")

        # Pending handoffs
        if context.pending_handoffs:
            for handoff in context.pending_handoffs[:2]:
                if handoff["type"] == "reminder":
                    parts.append(f"Erinnerung: {handoff['title']}")
                elif handoff["type"] == "follow_up":
                    parts.append(f"Follow-up: {handoff['title']}")

        if not parts:
            return None

        return "\n".join(parts)

    def save_session_summary(
        self,
        session_id: str,
        user_id: str,
        summary: str,
        topics: List[str],
        specialists_used: List[str],
        message_count: int = 0,
        tool_calls_count: int = 0,
        open_threads: Optional[List[Dict]] = None,
        user_state: Optional[Dict] = None
    ) -> bool:
        """Save a session summary when session ends."""
        self._ensure_init()

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if session already exists
                    cur.execute("""
                        SELECT id, started_at FROM jarvis_session_summaries
                        WHERE session_id = %s
                    """, (session_id,))

                    existing = cur.fetchone()

                    if existing:
                        # Update existing
                        cur.execute("""
                            UPDATE jarvis_session_summaries
                            SET ended_at = NOW(),
                                duration_minutes = EXTRACT(EPOCH FROM (NOW() - started_at)) / 60,
                                summary = %s,
                                key_topics = %s,
                                specialists_used = %s,
                                primary_specialist = %s,
                                message_count = %s,
                                tool_calls_count = %s,
                                open_threads = %s,
                                user_state_snapshot = %s
                            WHERE session_id = %s
                        """, (
                            summary,
                            json.dumps(topics),
                            json.dumps(specialists_used),
                            specialists_used[0] if specialists_used else None,
                            message_count,
                            tool_calls_count,
                            json.dumps(open_threads) if open_threads else None,
                            json.dumps(user_state) if user_state else None,
                            session_id
                        ))
                    else:
                        # Insert new (with immediate end)
                        cur.execute("""
                            INSERT INTO jarvis_session_summaries
                            (session_id, user_id, started_at, ended_at,
                             summary, key_topics, specialists_used, primary_specialist,
                             message_count, tool_calls_count, open_threads, user_state_snapshot)
                            VALUES (%s, %s, NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            session_id,
                            user_id,
                            summary,
                            json.dumps(topics),
                            json.dumps(specialists_used),
                            specialists_used[0] if specialists_used else None,
                            message_count,
                            tool_calls_count,
                            json.dumps(open_threads) if open_threads else None,
                            json.dumps(user_state) if user_state else None
                        ))

                    conn.commit()

            _log("info", "Session summary saved",
                session_id=session_id,
                topics=topics,
                specialists=specialists_used)
            return True

        except Exception as e:
            _log("error", f"Failed to save session summary: {e}")
            return False

    def start_session(self, session_id: str, user_id: str) -> bool:
        """Mark a session as started (for duration tracking)."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_session_summaries
                        (session_id, user_id, started_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (session_id) DO NOTHING
                    """, (session_id, user_id))
                    conn.commit()
            return True
        except Exception as e:
            _log("error", f"Failed to start session: {e}")
            return False

    def create_thread(
        self,
        user_id: str,
        topic: str,
        category: str,
        session_id: str,
        specialist: Optional[str] = None,
        priority: int = 50
    ) -> Optional[str]:
        """Create a new conversation thread."""
        self._ensure_init()

        import uuid
        thread_id = f"thread_{uuid.uuid4().hex[:12]}"

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_conversation_threads
                        (thread_id, user_id, topic, category, specialist,
                         first_session_id, last_session_id, priority)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING thread_id
                    """, (
                        thread_id, user_id, topic, category, specialist,
                        session_id, session_id, priority
                    ))
                    conn.commit()

            _log("info", "Thread created", thread_id=thread_id, topic=topic)
            return thread_id

        except Exception as e:
            _log("error", f"Failed to create thread: {e}")
            return None

    def update_thread(
        self,
        thread_id: str,
        session_id: str,
        context_summary: Optional[str] = None,
        last_message_preview: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None
    ) -> bool:
        """Update a conversation thread."""
        try:
            updates = ["last_session_id = %s", "last_active_at = NOW()",
                      "session_count = session_count + 1", "updated_at = NOW()"]
            values = [session_id]

            if context_summary:
                updates.append("context_summary = %s")
                values.append(context_summary)

            if last_message_preview:
                updates.append("last_message_preview = %s")
                values.append(last_message_preview)

            if status:
                updates.append("status = %s")
                values.append(status)

            if priority is not None:
                updates.append("priority = %s")
                values.append(priority)

            values.append(thread_id)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE jarvis_conversation_threads
                        SET {', '.join(updates)}
                        WHERE thread_id = %s
                    """, values)
                    conn.commit()

            return True

        except Exception as e:
            _log("error", f"Failed to update thread: {e}")
            return False

    def resolve_thread(self, thread_id: str) -> bool:
        """Mark a thread as resolved."""
        return self.update_thread(thread_id, "", status="resolved")

    def create_handoff(
        self,
        user_id: str,
        session_id: str,
        title: str,
        content: str,
        handoff_type: str = "context",
        priority: int = 50,
        from_specialist: Optional[str] = None,
        for_specialist: Optional[str] = None,
        expires_hours: Optional[int] = None
    ) -> Optional[int]:
        """Create a handoff for the next session."""
        self._ensure_init()

        try:
            expires_at = None
            if expires_hours:
                expires_at = datetime.now() + timedelta(hours=expires_hours)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_session_handoffs
                        (from_session_id, user_id, handoff_type, priority,
                         title, content, from_specialist, for_specialist, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        session_id, user_id, handoff_type, priority,
                        title, content, from_specialist, for_specialist, expires_at
                    ))

                    result = cur.fetchone()
                    handoff_id = result["id"] if result else None
                    conn.commit()

            _log("info", "Handoff created",
                handoff_id=handoff_id,
                handoff_type=handoff_type,
                title=title)
            return handoff_id

        except Exception as e:
            _log("error", f"Failed to create handoff: {e}")
            return None

    def get_session_stats(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Get session statistics for a user."""
        try:
            cutoff = datetime.now() - timedelta(days=days)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Session counts
                    cur.execute("""
                        SELECT COUNT(*) as total_sessions,
                               AVG(duration_minutes) as avg_duration,
                               SUM(message_count) as total_messages,
                               SUM(tool_calls_count) as total_tool_calls
                        FROM jarvis_session_summaries
                        WHERE user_id = %s AND started_at > %s
                    """, (user_id, cutoff))

                    stats = cur.fetchone()

                    # Active threads
                    cur.execute("""
                        SELECT COUNT(*) as active_threads
                        FROM jarvis_conversation_threads
                        WHERE user_id = %s AND status = 'active'
                    """, (user_id,))

                    threads = cur.fetchone()

                    # Top specialists
                    cur.execute("""
                        SELECT primary_specialist, COUNT(*) as count
                        FROM jarvis_session_summaries
                        WHERE user_id = %s AND started_at > %s
                          AND primary_specialist IS NOT NULL
                        GROUP BY primary_specialist
                        ORDER BY count DESC
                        LIMIT 3
                    """, (user_id, cutoff))

                    top_specialists = [
                        {"specialist": row["primary_specialist"], "sessions": row["count"]}
                        for row in cur.fetchall()
                    ]

                    return {
                        "period_days": days,
                        "total_sessions": stats["total_sessions"] or 0,
                        "avg_duration_minutes": round(stats["avg_duration"] or 0, 1),
                        "total_messages": stats["total_messages"] or 0,
                        "total_tool_calls": stats["total_tool_calls"] or 0,
                        "active_threads": threads["active_threads"] or 0,
                        "top_specialists": top_specialists
                    }

        except Exception as e:
            _log("error", f"Failed to get session stats: {e}")
            return {"error": str(e)}


# Singleton instance
_service: Optional[CrossSessionService] = None


def get_cross_session_service() -> CrossSessionService:
    """Get the singleton CrossSessionService instance."""
    global _service
    if _service is None:
        _service = CrossSessionService()
    return _service
