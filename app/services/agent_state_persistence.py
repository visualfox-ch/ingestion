"""
T-21C-01: Agent State Persistence Service
Persistent state for AI agents (Claude Code, Copilot, Codex) across sessions.
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from psycopg2.extras import RealDictCursor

from app.postgres_state import get_conn
from app.observability import get_logger

logger = get_logger("jarvis.agent_state_persistence")


class AgentStatePersistence:
    """Manages persistent state for AI coding agents."""

    # Known agents
    KNOWN_AGENTS = ["claude_code", "copilot", "codex", "cursor", "aider", "jarvis"]

    # State key categories
    STATE_CATEGORIES = [
        "preferences",  # User preferences learned by agent
        "context",      # Current working context
        "history",      # Recent actions/decisions
        "memory",       # Long-term memories
        "goals",        # Current goals/tasks
        "handoff"       # Handoff information for other agents
    ]

    def set_state(
        self,
        agent_id: str,
        user_id: str,
        state_key: str,
        state_value: Any,
        expires_in_hours: int = None
    ) -> Dict[str, Any]:
        """Set or update agent state."""
        if agent_id not in self.KNOWN_AGENTS:
            logger.warning(f"Unknown agent: {agent_id}")

        expires_at = None
        if expires_in_hours:
            expires_at = datetime.now() + timedelta(hours=expires_in_hours)

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO jarvis_agent_state (agent_id, user_id, state_key, state_value, expires_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (agent_id, user_id, state_key)
                    DO UPDATE SET state_value = EXCLUDED.state_value, expires_at = EXCLUDED.expires_at, updated_at = NOW()
                """, (agent_id, user_id, state_key, json.dumps(state_value), expires_at))
                conn.commit()

        logger.debug(f"Set state {agent_id}/{state_key} for user {user_id}")
        return {"success": True, "agent": agent_id, "key": state_key}

    def get_state(
        self,
        agent_id: str,
        user_id: str,
        state_key: str = None
    ) -> Optional[Dict[str, Any]]:
        """Get agent state."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if state_key:
                    cur.execute("""
                        SELECT state_value, updated_at, expires_at
                        FROM jarvis_agent_state
                        WHERE agent_id = %s AND user_id = %s AND state_key = %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                    """, (agent_id, user_id, state_key))
                    row = cur.fetchone()

                    if row:
                        # RealDictCursor returns dict-like rows
                        return {
                            "value": row['state_value'],
                            "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
                            "expires_at": row['expires_at'].isoformat() if row['expires_at'] else None
                        }
                    return None
                else:
                    # Get all state for agent/user
                    cur.execute("""
                        SELECT state_key, state_value, updated_at, expires_at
                        FROM jarvis_agent_state
                        WHERE agent_id = %s AND user_id = %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                    """, (agent_id, user_id))
                    rows = cur.fetchall()

                    return {
                        r['state_key']: {
                            "value": r['state_value'],
                            "updated_at": r['updated_at'].isoformat() if r['updated_at'] else None,
                            "expires_at": r['expires_at'].isoformat() if r['expires_at'] else None
                        }
                        for r in rows
                    }

    def delete_state(self, agent_id: str, user_id: str, state_key: str = None) -> bool:
        """Delete agent state."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if state_key:
                    cur.execute("""
                        DELETE FROM jarvis_agent_state
                        WHERE agent_id = %s AND user_id = %s AND state_key = %s
                    """, (agent_id, user_id, state_key))
                else:
                    cur.execute("""
                        DELETE FROM jarvis_agent_state
                        WHERE agent_id = %s AND user_id = %s
                    """, (agent_id, user_id))
                conn.commit()
                return True

    def start_session(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        working_directory: str = None
    ) -> Dict[str, Any]:
        """Start a new agent session."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO jarvis_agent_sessions
                    (agent_id, user_id, session_id, working_directory, started_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING id
                """, (agent_id, user_id, session_id, working_directory))
                session_db_id = cur.fetchone()["id"]
                conn.commit()

        logger.info(f"Started session {session_id} for {agent_id}")
        return {"session_db_id": session_db_id, "session_id": session_id}

    def end_session(
        self,
        session_id: str,
        files_modified: List[str] = None,
        tasks_completed: List[str] = None,
        tools_used: List[str] = None,
        summary: str = None,
        success: bool = True
    ) -> Dict[str, Any]:
        """End an agent session with results."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, started_at FROM jarvis_agent_sessions
                    WHERE session_id = %s AND ended_at IS NULL
                """, (session_id,))
                row = cur.fetchone()

                if not row:
                    return {"success": False, "reason": "session_not_found"}

                duration = int((datetime.now() - row['started_at']).total_seconds() / 60)

                cur.execute("""
                    UPDATE jarvis_agent_sessions
                    SET ended_at = NOW(), duration_minutes = %s, files_modified = %s,
                        tasks_completed = %s, tools_used = %s, summary = %s, success = %s
                    WHERE id = %s
                """, (duration, json.dumps(files_modified or []), json.dumps(tasks_completed or []),
                    json.dumps(tools_used or []), summary, success, row['id']))
                conn.commit()

        logger.info(f"Ended session {session_id}: {len(files_modified or [])} files, {duration}min")
        return {
            "success": True,
            "duration_minutes": duration,
            "files_modified": len(files_modified or []),
            "tasks_completed": len(tasks_completed or [])
        }

    def get_recent_sessions(
        self,
        agent_id: str = None,
        user_id: str = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent agent sessions."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where_clauses = []
                params = []

                if agent_id:
                    where_clauses.append("agent_id = %s")
                    params.append(agent_id)

                if user_id:
                    where_clauses.append("user_id = %s")
                    params.append(user_id)

                where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

                params.append(limit)
                cur.execute(f"""
                    SELECT agent_id, session_id, working_directory, files_modified,
                           tasks_completed, tools_used, summary, success,
                           started_at, ended_at, duration_minutes
                    FROM jarvis_agent_sessions
                    {where_clause}
                    ORDER BY started_at DESC
                    LIMIT %s
                """, params)
                rows = cur.fetchall()

                return [
                    {
                        "agent_id": r['agent_id'],
                        "session_id": r['session_id'],
                        "working_directory": r['working_directory'],
                        "files_modified": r['files_modified'] if r['files_modified'] else [],
                        "tasks_completed": r['tasks_completed'] if r['tasks_completed'] else [],
                        "tools_used": r['tools_used'] if r['tools_used'] else [],
                        "summary": r['summary'],
                        "success": r['success'],
                        "started_at": r['started_at'].isoformat() if r['started_at'] else None,
                        "ended_at": r['ended_at'].isoformat() if r['ended_at'] else None,
                        "duration_minutes": r['duration_minutes']
                    }
                    for r in rows
                ]

    def create_handoff(
        self,
        from_agent: str,
        to_agent: str,
        user_id: str,
        context: Dict[str, Any],
        files_involved: List[str] = None,
        reason: str = None
    ) -> Dict[str, Any]:
        """Create a handoff from one agent to another."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO jarvis_agent_handoffs
                    (from_agent, to_agent, user_id, context, files_involved, reason, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                    RETURNING id
                """, (from_agent, to_agent, user_id, json.dumps(context),
                    json.dumps(files_involved or []), reason))
                handoff_id = cur.fetchone()["id"]
                conn.commit()

        logger.info(f"Created handoff {handoff_id}: {from_agent} -> {to_agent}")
        return {
            "handoff_id": handoff_id,
            "from": from_agent,
            "to": to_agent,
            "status": "pending"
        }

    def get_pending_handoffs(self, agent_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Get pending handoffs for an agent."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, from_agent, context, files_involved, reason, created_at
                    FROM jarvis_agent_handoffs
                    WHERE to_agent = %s AND user_id = %s AND status = 'pending'
                    ORDER BY created_at DESC
                """, (agent_id, user_id))
                rows = cur.fetchall()

                return [
                    {
                        "handoff_id": r['id'],
                        "from_agent": r['from_agent'],
                        "context": r['context'],  # JSONB auto-deserialized
                        "files_involved": r['files_involved'] if r['files_involved'] else [],
                        "reason": r['reason'],
                        "created_at": r['created_at'].isoformat() if r['created_at'] else None
                    }
                    for r in rows
                ]

    def complete_handoff(self, handoff_id: int, status: str = "completed") -> bool:
        """Mark a handoff as completed."""
        if status not in ["completed", "rejected"]:
            status = "completed"

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE jarvis_agent_handoffs
                    SET status = %s, completed_at = NOW()
                    WHERE id = %s
                """, (status, handoff_id))
                conn.commit()
                return True

    def cleanup_expired(self) -> Dict[str, int]:
        """Clean up expired state entries."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    DELETE FROM jarvis_agent_state
                    WHERE expires_at IS NOT NULL AND expires_at < NOW()
                """)
                deleted = cur.rowcount
                conn.commit()
                logger.info(f"Cleaned up {deleted} expired state entries")
                return {"deleted_entries": deleted}

    def get_agent_stats(self, agent_id: str = None, days: int = 30) -> Dict[str, Any]:
        """Get statistics about agent usage."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where_clause = f"WHERE started_at > NOW() - INTERVAL '{days} days'"
                if agent_id:
                    where_clause += f" AND agent_id = '{agent_id}'"

                # Session stats
                cur.execute(f"""
                    SELECT
                        COUNT(*) as total_sessions,
                        AVG(duration_minutes) as avg_duration,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                        SUM(jsonb_array_length(files_modified)) as total_files_modified
                    FROM jarvis_agent_sessions
                    {where_clause}
                """)
                stats = cur.fetchone()

                # Per-agent breakdown
                cur.execute(f"""
                    SELECT agent_id, COUNT(*) as sessions,
                           AVG(duration_minutes) as avg_duration,
                           SUM(jsonb_array_length(files_modified)) as files_modified
                    FROM jarvis_agent_sessions
                    {where_clause}
                    GROUP BY agent_id
                    ORDER BY sessions DESC
                """)
                per_agent = cur.fetchall()

                # Handoff stats
                cur.execute(f"""
                    SELECT COUNT(*) as handoff_count FROM jarvis_agent_handoffs
                    WHERE created_at > NOW() - INTERVAL '{days} days'
                """)
                handoffs = cur.fetchone()["handoff_count"]

                return {
                    "period_days": days,
                    "total_sessions": stats['total_sessions'] or 0,
                    "avg_session_duration_min": round(stats['avg_duration'] or 0, 1),
                    "success_rate": round((stats['successful'] or 0) / max(stats['total_sessions'] or 1, 1), 2),
                    "total_files_modified": stats['total_files_modified'] or 0,
                    "total_handoffs": handoffs or 0,
                    "per_agent": [
                        {
                            "agent": r['agent_id'],
                            "sessions": r['sessions'],
                            "avg_duration": round(r['avg_duration'] or 0, 1),
                            "files_modified": r['files_modified'] or 0
                        }
                        for r in per_agent
                    ]
                }


# Singleton instance
_persistence: Optional[AgentStatePersistence] = None


def get_agent_state_persistence() -> AgentStatePersistence:
    """Get the singleton persistence instance."""
    global _persistence
    if _persistence is None:
        _persistence = AgentStatePersistence()
    return _persistence
