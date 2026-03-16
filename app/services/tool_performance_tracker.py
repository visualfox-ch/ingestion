"""
T-21A-04: Tool Performance Learning Service
Tracks success/failure per tool with context for adaptive tool selection.
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

from app.postgres_state import get_conn
from app.observability import get_logger

logger = get_logger("jarvis.tool_performance_tracker")


def _get_time_of_day() -> str:
    """Get current time of day category."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def _get_context_type(query: str = None) -> str:
    """Infer context type from query."""
    if not query:
        return "unknown"

    query_lower = query.lower()

    # Work-related keywords
    work_keywords = ["project", "task", "meeting", "deadline", "deploy", "code", "bug", "feature"]
    if any(kw in query_lower for kw in work_keywords):
        return "work"

    # Personal keywords
    personal_keywords = ["reminder", "birthday", "family", "health", "fitness", "hobby"]
    if any(kw in query_lower for kw in personal_keywords):
        return "personal"

    # Technical keywords
    tech_keywords = ["api", "database", "server", "docker", "git", "python", "javascript"]
    if any(kw in query_lower for kw in tech_keywords):
        return "technical"

    return "general"


class ToolPerformanceTracker:
    """Tracks and analyzes tool performance for adaptive selection."""

    def record_execution(
        self,
        tool_name: str,
        user_id: str,
        success: bool,
        session_id: str = None,
        error_type: str = None,
        error_message: str = None,
        duration_ms: int = None,
        input_tokens: int = None,
        query_context: str = None
    ) -> Dict[str, Any]:
        """Record a tool execution result."""
        time_of_day = _get_time_of_day()
        context_type = _get_context_type(query_context)
        day_of_week = datetime.now().weekday()

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jarvis_tool_performance
                    (tool_name, user_id, session_id, success, error_type, error_message,
                     duration_ms, input_tokens, context_type, time_of_day, day_of_week)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (tool_name, user_id, session_id, success, error_type, error_message,
                    duration_ms, input_tokens, context_type, time_of_day, day_of_week))
                conn.commit()

        # Update aggregated stats
        self._update_stats(tool_name, user_id, success, duration_ms, time_of_day, context_type)

        logger.debug(f"Recorded {tool_name} execution: success={success}, duration={duration_ms}ms")
        return {"recorded": True, "tool": tool_name, "success": success}

    def _update_stats(
        self,
        tool_name: str,
        user_id: str,
        success: bool,
        duration_ms: int = None,
        time_of_day: str = None,
        context_type: str = None
    ) -> None:
        """Update aggregated stats for a tool."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Update user-specific stats
                for uid in [user_id, "global"]:
                    cur.execute("""
                        SELECT total_calls, success_count, failure_count, avg_duration_ms
                        FROM jarvis_tool_performance_stats
                        WHERE tool_name = %s AND user_id = %s
                    """, (tool_name, uid))
                    existing = cur.fetchone()

                    if existing:
                        new_total = existing['total_calls'] + 1
                        new_success = existing['success_count'] + (1 if success else 0)
                        new_failure = existing['failure_count'] + (0 if success else 1)
                        new_rate = new_success / new_total if new_total > 0 else 1.0

                        # Update average duration
                        new_avg_duration = existing['avg_duration_ms']
                        if duration_ms is not None:
                            if existing['avg_duration_ms']:
                                new_avg_duration = (existing['avg_duration_ms'] * existing['total_calls'] + duration_ms) / new_total
                            else:
                                new_avg_duration = float(duration_ms)

                        cur.execute("""
                            UPDATE jarvis_tool_performance_stats
                            SET total_calls = %s, success_count = %s, failure_count = %s,
                                success_rate = %s, avg_duration_ms = %s, updated_at = NOW(),
                                last_success_at = CASE WHEN %s THEN NOW() ELSE last_success_at END,
                                last_failure_at = CASE WHEN NOT %s THEN NOW() ELSE last_failure_at END
                            WHERE tool_name = %s AND user_id = %s
                        """, (new_total, new_success, new_failure, new_rate, new_avg_duration,
                            success, success, tool_name, uid))
                    else:
                        cur.execute("""
                            INSERT INTO jarvis_tool_performance_stats
                            (tool_name, user_id, total_calls, success_count, failure_count,
                             success_rate, avg_duration_ms, last_success_at, last_failure_at)
                            VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)
                        """, (tool_name, uid, 1 if success else 0, 0 if success else 1,
                            1.0 if success else 0.0, float(duration_ms) if duration_ms else None,
                            datetime.now() if success else None,
                            None if success else datetime.now()))
                conn.commit()

    def get_tool_stats(self, tool_name: str = None, user_id: str = None) -> List[Dict[str, Any]]:
        """Get performance stats for tools."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                where_clauses = []
                params = []

                if tool_name:
                    where_clauses.append("tool_name = %s")
                    params.append(tool_name)

                if user_id:
                    where_clauses.append("user_id = %s")
                    params.append(user_id)
                else:
                    where_clauses.append("user_id = 'global'")

                where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

                cur.execute(f"""
                    SELECT tool_name, total_calls, success_rate, avg_duration_ms,
                           last_success_at, last_failure_at, best_time_of_day, best_context_type
                    FROM jarvis_tool_performance_stats
                    {where_clause}
                    ORDER BY total_calls DESC
                """, params or None)
                rows = cur.fetchall()

                return [
                    {
                        "tool_name": r['tool_name'],
                        "total_calls": r['total_calls'],
                        "success_rate": round(r['success_rate'], 3) if r['success_rate'] else 0,
                        "avg_duration_ms": int(r['avg_duration_ms'] or 0),
                        "last_success": r['last_success_at'].isoformat() if r['last_success_at'] else None,
                        "last_failure": r['last_failure_at'].isoformat() if r['last_failure_at'] else None,
                        "best_time_of_day": r['best_time_of_day'],
                        "best_context": r['best_context_type']
                    }
                    for r in rows
                ]

    def get_tool_recommendations(
        self,
        query_context: str = None,
        available_tools: List[str] = None
    ) -> Dict[str, Any]:
        """Get tool recommendations based on current context."""
        time_of_day = _get_time_of_day()
        context_type = _get_context_type(query_context)

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get tools that perform well in current context
                cur.execute("""
                    SELECT tool_name, success_rate, avg_duration_ms, total_calls
                    FROM jarvis_tool_performance_stats
                    WHERE user_id = 'global' AND success_rate >= 0.7 AND total_calls >= 5
                    ORDER BY success_rate DESC, total_calls DESC
                """)
                rows = cur.fetchall()

                # Filter to available tools if specified
                if available_tools:
                    rows = [r for r in rows if r['tool_name'] in available_tools]

                recommended = [
                    {
                        "tool": r['tool_name'],
                        "success_rate": round(r['success_rate'], 2),
                        "reliability_score": round(r['success_rate'] * min(r['total_calls'] / 10, 1.0), 2)
                    }
                    for r in rows[:10]
                ]

                # Get tools to avoid (low success rate)
                cur.execute("""
                    SELECT tool_name, success_rate, total_calls
                    FROM jarvis_tool_performance_stats
                    WHERE user_id = 'global' AND success_rate < 0.5 AND total_calls >= 3
                    ORDER BY success_rate ASC
                    LIMIT 5
                """)
                avoid_rows = cur.fetchall()

                avoid = [
                    {"tool": r['tool_name'], "success_rate": round(r['success_rate'], 2)}
                    for r in avoid_rows
                ]

                return {
                    "context": {
                        "time_of_day": time_of_day,
                        "context_type": context_type
                    },
                    "recommended": recommended,
                    "avoid": avoid
                }

    def get_failure_analysis(self, tool_name: str = None, days: int = 7) -> Dict[str, Any]:
        """Analyze recent failures for a tool."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                where_clause = f"WHERE NOT success AND created_at > NOW() - INTERVAL '{days} days'"
                params = []

                if tool_name:
                    where_clause += " AND tool_name = %s"
                    params.append(tool_name)

                cur.execute(f"""
                    SELECT tool_name, error_type, error_message, time_of_day, context_type, created_at
                    FROM jarvis_tool_performance
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT 50
                """, params or None)
                rows = cur.fetchall()

                # Group by error type
                error_types = defaultdict(int)
                for r in rows:
                    error_types[r['error_type'] or 'unknown'] += 1

                # Group by time of day
                time_distribution = defaultdict(int)
                for r in rows:
                    time_distribution[r['time_of_day']] += 1

                return {
                    "total_failures": len(rows),
                    "period_days": days,
                    "error_types": dict(error_types),
                    "time_distribution": dict(time_distribution),
                    "recent_failures": [
                        {
                            "tool": r['tool_name'],
                            "error_type": r['error_type'],
                            "time": r['created_at'].isoformat() if r['created_at'] else None,
                            "context": r['context_type']
                        }
                        for r in rows[:10]
                    ]
                }


# Singleton instance
_tracker: Optional[ToolPerformanceTracker] = None


def get_tool_performance_tracker() -> ToolPerformanceTracker:
    """Get the singleton tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = ToolPerformanceTracker()
    return _tracker
