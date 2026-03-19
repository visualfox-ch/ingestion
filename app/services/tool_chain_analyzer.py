"""
T-21A-01: Smart Tool Chains Service
Analyzes which tools are used together and suggests optimal tool sequences.
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from psycopg2.extras import RealDictCursor

from app.postgres_state import get_conn
from app.observability import get_logger

logger = get_logger("jarvis.tool_chain_analyzer")


class ToolChainAnalyzer:
    """Analyzes tool usage patterns to identify effective chains."""

    def __init__(self):
        self.current_chains: Dict[str, List[str]] = {}  # session_id -> tools used
        self.chain_start_times: Dict[str, datetime] = {}

    def start_chain(self, session_id: str, user_id: str, query_context: str = None) -> None:
        """Start tracking a new tool chain for a session."""
        self.current_chains[session_id] = []
        self.chain_start_times[session_id] = datetime.now()
        logger.debug(f"Started tool chain for session {session_id}")

    def add_tool_to_chain(self, session_id: str, tool_name: str) -> None:
        """Add a tool to the current chain."""
        if session_id not in self.current_chains:
            self.current_chains[session_id] = []
            self.chain_start_times[session_id] = datetime.now()

        self.current_chains[session_id].append(tool_name)
        logger.debug(f"Added {tool_name} to chain {session_id}: {self.current_chains[session_id]}")

    def finish_chain(
        self,
        session_id: str,
        user_id: str,
        success: bool = True,
        query_context: str = None
    ) -> Dict[str, Any]:
        """Finish and save a tool chain."""
        if session_id not in self.current_chains:
            return {"saved": False, "reason": "no_chain"}

        tool_sequence = self.current_chains.pop(session_id)
        start_time = self.chain_start_times.pop(session_id, datetime.now())
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if len(tool_sequence) < 2:
            return {"saved": False, "reason": "single_tool"}

        # Save to database
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO jarvis_tool_chains
                    (session_id, user_id, tool_sequence, query_context, chain_success, total_duration_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (session_id, user_id, json.dumps(tool_sequence), query_context, success, duration_ms))
                conn.commit()

        # Update pattern aggregation
        self._update_pattern(tool_sequence, success, duration_ms)

        logger.info(f"Saved tool chain: {tool_sequence} (success={success})")
        return {
            "saved": True,
            "chain": tool_sequence,
            "duration_ms": duration_ms,
            "success": success
        }

    def _update_pattern(self, tool_sequence: List[str], success: bool, duration_ms: int) -> None:
        """Update or create pattern aggregation."""
        pattern_hash = hashlib.sha256(json.dumps(tool_sequence).encode()).hexdigest()[:16]

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, occurrence_count, avg_success_rate, avg_duration_ms
                    FROM jarvis_tool_chain_patterns
                    WHERE pattern_hash = %s
                """, (pattern_hash,))
                existing = cur.fetchone()

                if existing:
                    # Update existing pattern (RealDictCursor returns dict)
                    new_count = existing['occurrence_count'] + 1
                    new_success_rate = (existing['avg_success_rate'] * existing['occurrence_count'] + (1 if success else 0)) / new_count
                    new_duration = ((existing['avg_duration_ms'] or 0) * existing['occurrence_count'] + duration_ms) / new_count

                    cur.execute("""
                        UPDATE jarvis_tool_chain_patterns
                        SET occurrence_count = %s, avg_success_rate = %s, avg_duration_ms = %s, last_seen_at = NOW()
                        WHERE id = %s
                    """, (new_count, new_success_rate, new_duration, existing['id']))
                else:
                    # Create new pattern
                    cur.execute("""
                        INSERT INTO jarvis_tool_chain_patterns
                        (pattern, pattern_hash, occurrence_count, avg_success_rate, avg_duration_ms)
                        VALUES (%s, %s, 1, %s, %s)
                    """, (json.dumps(tool_sequence), pattern_hash, 1.0 if success else 0.0, float(duration_ms)))
                conn.commit()

    def get_popular_chains(self, min_occurrences: int = 3, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the most popular tool chains."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT pattern, occurrence_count, avg_success_rate, avg_duration_ms, last_seen_at
                    FROM jarvis_tool_chain_patterns
                    WHERE occurrence_count >= %s
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (min_occurrences, limit))
                rows = cur.fetchall()

                return [
                    {
                        "chain": json.loads(row['pattern']),
                        "occurrences": row['occurrence_count'],
                        "success_rate": round(row['avg_success_rate'], 2),
                        "avg_duration_ms": int(row['avg_duration_ms'] or 0),
                        "last_seen": row['last_seen_at'].isoformat() if row['last_seen_at'] else None
                    }
                    for row in rows
                ]

    def suggest_next_tool(self, current_tools: List[str], context: str = None) -> Dict[str, Any]:
        """Suggest the next tool based on patterns."""
        if not current_tools:
            return {"suggestion": None, "reason": "no_current_tools"}

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find patterns that start with current sequence
                cur.execute("""
                    SELECT pattern, occurrence_count, avg_success_rate
                    FROM jarvis_tool_chain_patterns
                    WHERE occurrence_count >= 2
                    ORDER BY occurrence_count DESC
                    LIMIT 100
                """)
                rows = cur.fetchall()

        suggestions = defaultdict(lambda: {"count": 0, "success_rate": 0})

        for row in rows:
            pattern = json.loads(row['pattern'])
            # Check if current tools are a prefix of this pattern
            if len(pattern) > len(current_tools):
                is_prefix = True
                for i, tool in enumerate(current_tools):
                    if i >= len(pattern) or pattern[i] != tool:
                        is_prefix = False
                        break

                if is_prefix:
                    next_tool = pattern[len(current_tools)]
                    suggestions[next_tool]["count"] += row['occurrence_count']
                    suggestions[next_tool]["success_rate"] = max(
                        suggestions[next_tool]["success_rate"],
                        row['avg_success_rate']
                    )

        if not suggestions:
            return {"suggestion": None, "reason": "no_matching_patterns"}

        # Sort by count * success_rate
        best = max(
            suggestions.items(),
            key=lambda x: x[1]["count"] * x[1]["success_rate"]
        )

        return {
            "suggestion": best[0],
            "confidence": round(best[1]["success_rate"], 2),
            "based_on_occurrences": best[1]["count"],
            "alternatives": [
                {"tool": k, "score": round(v["count"] * v["success_rate"], 2)}
                for k, v in sorted(suggestions.items(), key=lambda x: x[1]["count"] * x[1]["success_rate"], reverse=True)[:3]
            ]
        }

    def get_chain_stats(self, user_id: str = None, days: int = 30) -> Dict[str, Any]:
        """Get statistics about tool chains."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where_clause = f"WHERE created_at > NOW() - INTERVAL '{days} days'"
                params = []

                if user_id:
                    where_clause += " AND user_id = %s"
                    params.append(user_id)

                cur.execute(f"""
                    SELECT COUNT(*) as total FROM jarvis_tool_chains {where_clause}
                """, params or None)
                total = cur.fetchone()['total']

                cur.execute(f"""
                    SELECT AVG(jsonb_array_length(tool_sequence)) as avg_len
                    FROM jarvis_tool_chains {where_clause}
                """, params or None)
                avg_length = cur.fetchone()['avg_len']

                cur.execute(f"""
                    SELECT AVG(CASE WHEN chain_success THEN 1.0 ELSE 0.0 END) as rate
                    FROM jarvis_tool_chains {where_clause}
                """, params or None)
                success_rate = cur.fetchone()['rate']

                # Most used tools
                cur.execute(f"""
                    SELECT tool, COUNT(*) as cnt
                    FROM jarvis_tool_chains, jsonb_array_elements_text(tool_sequence) as tool
                    {where_clause}
                    GROUP BY tool
                    ORDER BY cnt DESC
                    LIMIT 10
                """, params or None)
                top_tools = cur.fetchall()

                return {
                    "total_chains": total or 0,
                    "avg_chain_length": round(avg_length or 0, 1),
                    "success_rate": round(success_rate or 0, 2),
                    "top_tools": [{"tool": r['tool'], "count": r['cnt']} for r in top_tools],
                    "period_days": days
                }


# Singleton instance
_analyzer: Optional[ToolChainAnalyzer] = None


def get_tool_chain_analyzer() -> ToolChainAnalyzer:
    """Get the singleton analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ToolChainAnalyzer()
    return _analyzer
