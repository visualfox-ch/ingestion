"""
Session Pattern Service - Phase 1.3

Tracks and learns from session patterns:
- Detects current work mode (coding, planning, research, etc.)
- Tracks session transitions and durations
- Predicts next likely tools/needs
- Provides session summaries and insights
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
import json

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)

# Session timeout - if no activity for this long, consider session ended
SESSION_TIMEOUT_MINUTES = 30

# Minimum tools to consider a session "established"
MIN_TOOLS_FOR_SESSION = 2


class SessionPatternService:
    """
    Tracks and analyzes session patterns.

    A "session" is a continuous period of interaction with similar intent/mode.
    Sessions can transition (e.g., from research to coding).
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure session tracking tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS session_history (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(50) NOT NULL,
                        user_id VARCHAR(50) DEFAULT 'default',
                        session_type VARCHAR(50),
                        started_at TIMESTAMP DEFAULT NOW(),
                        ended_at TIMESTAMP,
                        duration_minutes INTEGER,
                        tool_count INTEGER DEFAULT 0,
                        tools_used JSONB DEFAULT '[]'::jsonb,
                        transitions JSONB DEFAULT '[]'::jsonb,
                        summary TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_session_history_user
                        ON session_history(user_id);
                    CREATE INDEX IF NOT EXISTS idx_session_history_type
                        ON session_history(session_type);
                    CREATE INDEX IF NOT EXISTS idx_session_history_started
                        ON session_history(started_at DESC);

                    CREATE TABLE IF NOT EXISTS session_transitions (
                        id SERIAL PRIMARY KEY,
                        from_type VARCHAR(50) NOT NULL,
                        to_type VARCHAR(50) NOT NULL,
                        occurrence_count INTEGER DEFAULT 1,
                        avg_duration_before_minutes FLOAT,
                        common_trigger_tools JSONB DEFAULT '[]'::jsonb,
                        last_seen_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(from_type, to_type)
                    );

                    CREATE INDEX IF NOT EXISTS idx_session_transitions_from
                        ON session_transitions(from_type);

                    CREATE TABLE IF NOT EXISTS active_sessions (
                        user_id VARCHAR(50) PRIMARY KEY,
                        session_id VARCHAR(50) NOT NULL,
                        session_type VARCHAR(50),
                        started_at TIMESTAMP DEFAULT NOW(),
                        last_activity_at TIMESTAMP DEFAULT NOW(),
                        tool_count INTEGER DEFAULT 0,
                        recent_tools JSONB DEFAULT '[]'::jsonb,
                        context_data JSONB DEFAULT '{}'::jsonb
                    );
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def get_or_create_session(
        self,
        user_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Get current active session or create a new one.

        Returns session info with type detection.
        """
        try:
            with get_dict_cursor() as cur:
                # Check for active session
                cur.execute("""
                    SELECT session_id, session_type, started_at, last_activity_at,
                           tool_count, recent_tools, context_data
                    FROM active_sessions
                    WHERE user_id = %s
                """, (user_id,))

                row = cur.fetchone()

                if row:
                    last_activity = row['last_activity_at']
                    # Check if session timed out
                    if datetime.now() - last_activity > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                        # End old session and create new
                        self._end_session(user_id, cur)
                        return self._create_session(user_id, cur)

                    return {
                        "session_id": row['session_id'],
                        "session_type": row['session_type'],
                        "started_at": row['started_at'].isoformat(),
                        "duration_minutes": int((datetime.now() - row['started_at']).total_seconds() / 60),
                        "tool_count": row['tool_count'],
                        "recent_tools": row['recent_tools'] or [],
                        "is_new": False
                    }
                else:
                    return self._create_session(user_id, cur)

        except Exception as e:
            logger.error(f"Get or create session failed: {e}")
            return {"error": str(e)}

    def _create_session(self, user_id: str, cur) -> Dict[str, Any]:
        """Create a new session."""
        import uuid
        session_id = f"sess_{uuid.uuid4().hex[:12]}"

        cur.execute("""
            INSERT INTO active_sessions
            (user_id, session_id, started_at, last_activity_at)
            VALUES (%s, %s, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                session_type = NULL,
                started_at = NOW(),
                last_activity_at = NOW(),
                tool_count = 0,
                recent_tools = '[]'::jsonb,
                context_data = '{}'::jsonb
        """, (user_id, session_id))

        return {
            "session_id": session_id,
            "session_type": None,
            "started_at": datetime.now().isoformat(),
            "duration_minutes": 0,
            "tool_count": 0,
            "recent_tools": [],
            "is_new": True
        }

    def _end_session(self, user_id: str, cur):
        """End current session and archive it."""
        cur.execute("""
            SELECT session_id, session_type, started_at, tool_count, recent_tools
            FROM active_sessions
            WHERE user_id = %s
        """, (user_id,))

        row = cur.fetchone()
        if row and row['tool_count'] >= MIN_TOOLS_FOR_SESSION:
            duration = int((datetime.now() - row['started_at']).total_seconds() / 60)

            cur.execute("""
                INSERT INTO session_history
                (session_id, user_id, session_type, started_at, ended_at,
                 duration_minutes, tool_count, tools_used)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
            """, (
                row['session_id'],
                user_id,
                row['session_type'],
                row['started_at'],
                duration,
                row['tool_count'],
                json.dumps(row['recent_tools'] or [])
            ))

    def record_tool_use(
        self,
        tool_name: str,
        user_id: str = "default",
        query: str = None
    ) -> Dict[str, Any]:
        """
        Record a tool use in the current session.

        Updates session state and detects type transitions.
        """
        try:
            session = self.get_or_create_session(user_id)
            if "error" in session:
                return session

            with get_dict_cursor() as cur:
                # Get current session data
                cur.execute("""
                    SELECT session_type, recent_tools, tool_count
                    FROM active_sessions
                    WHERE user_id = %s
                """, (user_id,))

                row = cur.fetchone()
                if not row:
                    return {"error": "No active session"}

                old_type = row['session_type']
                recent_tools = row['recent_tools'] or []

                # Add new tool to recent list (keep last 10)
                recent_tools.append(tool_name)
                recent_tools = recent_tools[-10:]

                # Detect new session type
                new_type = self._detect_session_type(recent_tools, query)

                # Check for transition
                transition = None
                if old_type and new_type and old_type != new_type:
                    transition = {"from": old_type, "to": new_type}
                    self._record_transition(old_type, new_type, row['tool_count'], cur)

                # Update session
                cur.execute("""
                    UPDATE active_sessions SET
                        session_type = %s,
                        last_activity_at = NOW(),
                        tool_count = tool_count + 1,
                        recent_tools = %s
                    WHERE user_id = %s
                """, (new_type, json.dumps(recent_tools), user_id))

                return {
                    "success": True,
                    "session_id": session['session_id'],
                    "session_type": new_type,
                    "tool_count": row['tool_count'] + 1,
                    "transition": transition
                }

        except Exception as e:
            logger.error(f"Record tool use failed: {e}")
            return {"success": False, "error": str(e)}

    def _detect_session_type(
        self,
        recent_tools: List[str],
        query: str = None
    ) -> Optional[str]:
        """Detect session type from tools and query."""
        try:
            from .context_tool_learner import get_context_tool_learner
            learner = get_context_tool_learner()
            result = learner.detect_session_type(recent_tools, query)
            if result.get("success") and result.get("detected"):
                return result["detected"].get("session_type")
        except Exception as e:
            logger.debug(f"Session type detection failed: {e}")

        # Fallback: simple tool-based detection
        tool_set = set(recent_tools)

        if tool_set & {'read_project_file', 'write_project_file', 'read_my_source_files'}:
            return 'coding'
        elif tool_set & {'search_knowledge', 'web_search', 'run_research'}:
            return 'research'
        elif tool_set & {'get_calendar_events', 'create_calendar_event', 'list_projects'}:
            return 'planning'
        elif tool_set & {'send_email', 'get_gmail_messages'}:
            return 'communication'
        elif tool_set & {'system_health_check', 'self_validation_pulse', 'get_my_tool_usage'}:
            return 'introspection'

        return 'general'

    def _record_transition(
        self,
        from_type: str,
        to_type: str,
        tools_before: int,
        cur
    ):
        """Record a session type transition."""
        cur.execute("""
            INSERT INTO session_transitions
            (from_type, to_type, occurrence_count, avg_duration_before_minutes, last_seen_at)
            VALUES (%s, %s, 1, %s, NOW())
            ON CONFLICT (from_type, to_type) DO UPDATE SET
                occurrence_count = session_transitions.occurrence_count + 1,
                avg_duration_before_minutes = (
                    COALESCE(session_transitions.avg_duration_before_minutes, 0) *
                    session_transitions.occurrence_count + %s
                ) / (session_transitions.occurrence_count + 1),
                last_seen_at = NOW()
        """, (from_type, to_type, tools_before, tools_before))

    def predict_next_tools(
        self,
        user_id: str = "default",
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Predict likely next tools based on session patterns.

        Uses:
        - Current session type and recent tools
        - Historical tool sequences
        - Common transitions
        """
        try:
            session = self.get_or_create_session(user_id)
            if "error" in session:
                return session

            session_type = session.get("session_type")
            recent_tools = session.get("recent_tools", [])

            with get_dict_cursor() as cur:
                predictions = []

                # 1. Get tools commonly used in this session type
                if session_type:
                    cur.execute("""
                        SELECT tool_name, SUM(occurrence_count) as total
                        FROM context_tool_mapping ctm
                        JOIN session_type_patterns stp ON true
                        WHERE stp.session_type = %s
                        AND ctm.tool_name = ANY(
                            SELECT jsonb_array_elements_text(stp.tool_preferences->'preferred')
                        )
                        GROUP BY tool_name
                        ORDER BY total DESC
                        LIMIT %s
                    """, (session_type, limit))

                    for row in cur.fetchall():
                        if row['tool_name'] not in recent_tools[-3:]:
                            predictions.append({
                                "tool": row['tool_name'],
                                "reason": f"common in {session_type} sessions",
                                "confidence": 0.7
                            })

                # 2. Get tools that often follow the last tool used
                if recent_tools:
                    last_tool = recent_tools[-1]
                    cur.execute("""
                        SELECT tool_name, occurrence_count
                        FROM context_tool_mapping
                        WHERE context_keyword = %s
                        AND tool_name != %s
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (last_tool.lower(), last_tool, limit))

                    for row in cur.fetchall():
                        if not any(p['tool'] == row['tool_name'] for p in predictions):
                            predictions.append({
                                "tool": row['tool_name'],
                                "reason": f"often follows {last_tool}",
                                "confidence": 0.6
                            })

                # 3. Check for likely transitions
                if session_type:
                    cur.execute("""
                        SELECT to_type, occurrence_count
                        FROM session_transitions
                        WHERE from_type = %s
                        ORDER BY occurrence_count DESC
                        LIMIT 1
                    """, (session_type,))

                    row = cur.fetchone()
                    if row:
                        next_type = row['to_type']
                        # Get tools for the likely next type
                        cur.execute("""
                            SELECT jsonb_array_elements_text(tool_preferences->'preferred') as tool
                            FROM session_type_patterns
                            WHERE session_type = %s
                        """, (next_type,))

                        for tool_row in cur.fetchall():
                            tool = tool_row['tool']
                            if tool and not any(p['tool'] == tool for p in predictions):
                                predictions.append({
                                    "tool": tool,
                                    "reason": f"transition to {next_type} likely",
                                    "confidence": 0.5
                                })

                return {
                    "success": True,
                    "session_type": session_type,
                    "predictions": predictions[:limit]
                }

        except Exception as e:
            logger.error(f"Predict next tools failed: {e}")
            return {"success": False, "error": str(e)}

    def get_session_summary(
        self,
        user_id: str = "default"
    ) -> Dict[str, Any]:
        """Get summary of current session."""
        try:
            session = self.get_or_create_session(user_id)
            if "error" in session:
                return session

            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT session_type, started_at, tool_count, recent_tools
                    FROM active_sessions
                    WHERE user_id = %s
                """, (user_id,))

                row = cur.fetchone()
                if not row:
                    return {"error": "No active session"}

                duration = int((datetime.now() - row['started_at']).total_seconds() / 60)
                recent_tools = row['recent_tools'] or []

                # Count tool frequencies
                tool_counts = defaultdict(int)
                for tool in recent_tools:
                    tool_counts[tool] += 1

                top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]

                return {
                    "success": True,
                    "session_id": session['session_id'],
                    "session_type": row['session_type'],
                    "duration_minutes": duration,
                    "total_tools_used": row['tool_count'],
                    "top_tools": [{"tool": t, "count": c} for t, c in top_tools],
                    "recent_tools": recent_tools[-5:]
                }

        except Exception as e:
            logger.error(f"Get session summary failed: {e}")
            return {"success": False, "error": str(e)}

    def get_session_history(
        self,
        user_id: str = "default",
        days: int = 7,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get historical sessions for a user."""
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT session_id, session_type, started_at, ended_at,
                           duration_minutes, tool_count
                    FROM session_history
                    WHERE user_id = %s
                    AND started_at > NOW() - make_interval(days => %s)
                    ORDER BY started_at DESC
                    LIMIT %s
                """, (user_id, days, limit))

                sessions = []
                for row in cur.fetchall():
                    sessions.append({
                        "session_id": row['session_id'],
                        "type": row['session_type'],
                        "started": row['started_at'].isoformat() if row['started_at'] else None,
                        "ended": row['ended_at'].isoformat() if row['ended_at'] else None,
                        "duration_minutes": row['duration_minutes'],
                        "tool_count": row['tool_count']
                    })

                # Aggregate by type
                type_counts = defaultdict(int)
                type_durations = defaultdict(int)
                for s in sessions:
                    if s['type']:
                        type_counts[s['type']] += 1
                        type_durations[s['type']] += s['duration_minutes'] or 0

                return {
                    "success": True,
                    "sessions": sessions,
                    "summary": {
                        "total_sessions": len(sessions),
                        "by_type": {t: {"count": c, "total_minutes": type_durations[t]}
                                   for t, c in type_counts.items()}
                    }
                }

        except Exception as e:
            logger.error(f"Get session history failed: {e}")
            return {"success": False, "error": str(e)}

    def get_transition_patterns(self, limit: int = 10) -> Dict[str, Any]:
        """Get common session type transitions."""
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT from_type, to_type, occurrence_count,
                           avg_duration_before_minutes
                    FROM session_transitions
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (limit,))

                transitions = []
                for row in cur.fetchall():
                    transitions.append({
                        "from": row['from_type'],
                        "to": row['to_type'],
                        "occurrences": row['occurrence_count'],
                        "avg_duration_before": round(row['avg_duration_before_minutes'] or 0, 1)
                    })

                return {
                    "success": True,
                    "transitions": transitions
                }

        except Exception as e:
            logger.error(f"Get transition patterns failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[SessionPatternService] = None


def get_session_pattern_service() -> SessionPatternService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = SessionPatternService()
    return _service
