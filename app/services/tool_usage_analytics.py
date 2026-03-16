"""
Tool Usage Analytics Service

Aggregates tool_audit data into meaningful patterns:
- Which tools are used most
- Context → Tool mapping (what queries trigger which tools)
- Session patterns (tool chains)
- Success/failure rates by context
- Time-based patterns (when tools work best)
"""

import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import json
import re

from app.db_client import get_db_client

logger = logging.getLogger(__name__)


class ToolUsageAnalytics:
    """
    Analytics engine for tool usage patterns.

    Reads from tool_audit, writes to:
    - jarvis_tool_performance_stats (aggregated stats)
    - jarvis_tool_chains (session tool sequences)
    - jarvis_tool_chain_patterns (common patterns)
    - context_tool_mapping (new: which queries → which tools)
    """

    def __init__(self):
        self.db = get_db_client()

    def get_tool_stats(
        self,
        days: int = 30,
        tool_name: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get aggregated tool usage statistics.

        Returns:
            - Total calls, success rate, avg duration per tool
            - Time-based patterns (best hours/days)
            - Recent trend (increasing/decreasing usage)
        """
        try:
            with self.db.get_cursor() as cur:
                # Base query for tool stats
                if tool_name:
                    cur.execute("""
                        SELECT
                            tool_name,
                            COUNT(*) as total_calls,
                            SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                            AVG(duration_ms) as avg_duration_ms,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms,
                            MIN(created_at) as first_seen,
                            MAX(created_at) as last_seen
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        AND tool_name = %s
                        GROUP BY tool_name
                    """, (days, tool_name))
                else:
                    cur.execute("""
                        SELECT
                            tool_name,
                            COUNT(*) as total_calls,
                            SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                            AVG(duration_ms) as avg_duration_ms,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms,
                            MIN(created_at) as first_seen,
                            MAX(created_at) as last_seen
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY tool_name
                        ORDER BY COUNT(*) DESC
                        LIMIT %s
                    """, (days, limit))

                rows = cur.fetchall()

                stats = []
                for row in rows:
                    total = row[1]
                    success = row[2] or 0
                    stats.append({
                        "tool_name": row[0],
                        "total_calls": total,
                        "success_count": success,
                        "failure_count": total - success,
                        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
                        "avg_duration_ms": round(row[3], 1) if row[3] else 0,
                        "p95_duration_ms": round(row[4], 1) if row[4] else 0,
                        "first_seen": row[5].isoformat() if row[5] else None,
                        "last_seen": row[6].isoformat() if row[6] else None
                    })

                # Get total stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(DISTINCT tool_name) as unique_tools,
                        AVG(duration_ms) as avg_duration
                    FROM tool_audit
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))
                totals = cur.fetchone()

                return {
                    "success": True,
                    "period_days": days,
                    "total_calls": totals[0] or 0,
                    "unique_tools_used": totals[1] or 0,
                    "avg_duration_ms": round(totals[2], 1) if totals[2] else 0,
                    "tools": stats
                }

        except Exception as e:
            logger.error(f"Get tool stats failed: {e}")
            return {"success": False, "error": str(e)}

    def get_time_patterns(
        self,
        tool_name: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze time-based usage patterns.

        Returns:
            - Usage by hour of day
            - Usage by day of week
            - Peak usage times
        """
        try:
            with self.db.get_cursor() as cur:
                # Usage by hour
                if tool_name:
                    cur.execute("""
                        SELECT
                            EXTRACT(HOUR FROM created_at) as hour,
                            COUNT(*) as calls,
                            AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        AND tool_name = %s
                        GROUP BY EXTRACT(HOUR FROM created_at)
                        ORDER BY hour
                    """, (days, tool_name))
                else:
                    cur.execute("""
                        SELECT
                            EXTRACT(HOUR FROM created_at) as hour,
                            COUNT(*) as calls,
                            AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY EXTRACT(HOUR FROM created_at)
                        ORDER BY hour
                    """, (days,))

                hourly = {int(row[0]): {"calls": row[1], "success_rate": round(row[2] * 100, 1)}
                         for row in cur.fetchall()}

                # Usage by day of week
                if tool_name:
                    cur.execute("""
                        SELECT
                            EXTRACT(DOW FROM created_at) as dow,
                            COUNT(*) as calls
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        AND tool_name = %s
                        GROUP BY EXTRACT(DOW FROM created_at)
                        ORDER BY dow
                    """, (days, tool_name))
                else:
                    cur.execute("""
                        SELECT
                            EXTRACT(DOW FROM created_at) as dow,
                            COUNT(*) as calls
                        FROM tool_audit
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY EXTRACT(DOW FROM created_at)
                        ORDER BY dow
                    """, (days,))

                days_map = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
                           4: "Thursday", 5: "Friday", 6: "Saturday"}
                daily = {days_map[int(row[0])]: row[1] for row in cur.fetchall()}

                # Find peak hour
                peak_hour = max(hourly.items(), key=lambda x: x[1]["calls"])[0] if hourly else None
                peak_day = max(daily.items(), key=lambda x: x[1])[0] if daily else None

                return {
                    "success": True,
                    "tool_name": tool_name or "all_tools",
                    "period_days": days,
                    "hourly_distribution": hourly,
                    "daily_distribution": daily,
                    "peak_hour": peak_hour,
                    "peak_day": peak_day,
                    "insights": self._generate_time_insights(hourly, daily, peak_hour, peak_day)
                }

        except Exception as e:
            logger.error(f"Get time patterns failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_time_insights(self, hourly: Dict, daily: Dict, peak_hour: int, peak_day: str) -> List[str]:
        """Generate human-readable insights from time patterns."""
        insights = []

        if peak_hour is not None:
            if 6 <= peak_hour < 12:
                insights.append(f"Du bist am produktivsten morgens (Peak: {peak_hour}:00)")
            elif 12 <= peak_hour < 18:
                insights.append(f"Du bist am produktivsten nachmittags (Peak: {peak_hour}:00)")
            elif 18 <= peak_hour < 22:
                insights.append(f"Du bist am produktivsten abends (Peak: {peak_hour}:00)")
            else:
                insights.append(f"Du arbeitest oft nachts (Peak: {peak_hour}:00)")

        if peak_day:
            insights.append(f"Aktivster Tag: {peak_day}")

        # Check for late night work
        late_night = sum(hourly.get(h, {}).get("calls", 0) for h in [22, 23, 0, 1, 2])
        total = sum(h.get("calls", 0) for h in hourly.values())
        if total > 0 and late_night / total > 0.2:
            insights.append("Signifikante Nachtarbeit erkannt (>20% der Calls nach 22 Uhr)")

        return insights

    def get_context_tool_mapping(
        self,
        min_occurrences: int = 3,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze which query patterns lead to which tools.

        Returns:
            - Common query keywords → tool mappings
            - Query type classifications
        """
        try:
            with self.db.get_cursor() as cur:
                # Get recent tool inputs
                cur.execute("""
                    SELECT tool_name, tool_input, COUNT(*) as count
                    FROM tool_audit
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    AND tool_input IS NOT NULL
                    AND tool_input != '{}'::jsonb
                    GROUP BY tool_name, tool_input
                    HAVING COUNT(*) >= %s
                    ORDER BY COUNT(*) DESC
                    LIMIT 100
                """, (days, min_occurrences))

                rows = cur.fetchall()

                # Analyze patterns
                patterns = defaultdict(lambda: {"tools": defaultdict(int), "count": 0})

                for tool_name, tool_input, count in rows:
                    # Extract keywords from input
                    keywords = self._extract_keywords(tool_input)
                    for kw in keywords:
                        patterns[kw]["tools"][tool_name] += count
                        patterns[kw]["count"] += count

                # Convert to list and sort
                pattern_list = []
                for keyword, data in patterns.items():
                    if data["count"] >= min_occurrences:
                        top_tools = sorted(data["tools"].items(), key=lambda x: -x[1])[:3]
                        pattern_list.append({
                            "keyword": keyword,
                            "total_occurrences": data["count"],
                            "primary_tool": top_tools[0][0] if top_tools else None,
                            "tools": dict(top_tools)
                        })

                pattern_list.sort(key=lambda x: -x["total_occurrences"])

                return {
                    "success": True,
                    "period_days": days,
                    "min_occurrences": min_occurrences,
                    "patterns_found": len(pattern_list),
                    "patterns": pattern_list[:30]
                }

        except Exception as e:
            logger.error(f"Get context mapping failed: {e}")
            return {"success": False, "error": str(e)}

    def _extract_keywords(self, tool_input: Dict) -> List[str]:
        """Extract meaningful keywords from tool input."""
        keywords = []

        if not tool_input:
            return keywords

        # Common query fields
        for field in ["query", "search_query", "question", "topic", "keyword"]:
            if field in tool_input and tool_input[field]:
                text = str(tool_input[field]).lower()
                # Extract individual words (3+ chars)
                words = re.findall(r'\b[a-zäöüß]{3,}\b', text)
                keywords.extend(words[:5])  # Max 5 keywords per input

        return list(set(keywords))

    def get_tool_chains(
        self,
        days: int = 7,
        min_chain_length: int = 2
    ) -> Dict[str, Any]:
        """
        Analyze tool usage chains within sessions.

        Returns:
            - Common tool sequences
            - Successful vs failed chains
        """
        try:
            with self.db.get_cursor() as cur:
                # Get tools grouped by trace_id (session)
                cur.execute("""
                    SELECT trace_id,
                           ARRAY_AGG(tool_name ORDER BY created_at) as tools,
                           BOOL_AND(success) as all_success
                    FROM tool_audit
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    AND trace_id IS NOT NULL
                    GROUP BY trace_id
                    HAVING COUNT(*) >= %s
                    ORDER BY MIN(created_at) DESC
                    LIMIT 200
                """, (days, min_chain_length))

                rows = cur.fetchall()

                # Count chain patterns
                chain_counts = defaultdict(lambda: {"count": 0, "success": 0})

                for trace_id, tools, success in rows:
                    # Create chain signature (first 4 tools)
                    chain_key = " → ".join(tools[:4])
                    chain_counts[chain_key]["count"] += 1
                    if success:
                        chain_counts[chain_key]["success"] += 1

                # Convert to list
                chains = []
                for chain, data in chain_counts.items():
                    chains.append({
                        "chain": chain,
                        "count": data["count"],
                        "success_rate": round(data["success"] / data["count"] * 100, 1) if data["count"] > 0 else 0
                    })

                chains.sort(key=lambda x: -x["count"])

                return {
                    "success": True,
                    "period_days": days,
                    "total_sessions": len(rows),
                    "unique_patterns": len(chains),
                    "common_chains": chains[:20]
                }

        except Exception as e:
            logger.error(f"Get tool chains failed: {e}")
            return {"success": False, "error": str(e)}

    def get_failure_analysis(
        self,
        days: int = 30,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Analyze tool failures for improvement opportunities.

        Returns:
            - Tools with highest failure rates
            - Common error patterns
            - Suggestions for improvement
        """
        try:
            with self.db.get_cursor() as cur:
                # Tools with failures
                cur.execute("""
                    SELECT
                        tool_name,
                        COUNT(*) as total,
                        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failures,
                        ARRAY_AGG(DISTINCT error_message) FILTER (WHERE error_message IS NOT NULL) as error_messages
                    FROM tool_audit
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY tool_name
                    HAVING SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) > 0
                    ORDER BY SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) DESC
                    LIMIT %s
                """, (days, limit))

                rows = cur.fetchall()

                failures = []
                for row in rows:
                    total = row[1]
                    fails = row[2]
                    failures.append({
                        "tool_name": row[0],
                        "total_calls": total,
                        "failures": fails,
                        "failure_rate": round(fails / total * 100, 1) if total > 0 else 0,
                        "error_samples": row[3][:3] if row[3] else []
                    })

                return {
                    "success": True,
                    "period_days": days,
                    "tools_with_failures": len(failures),
                    "failures": failures
                }

        except Exception as e:
            logger.error(f"Get failure analysis failed: {e}")
            return {"success": False, "error": str(e)}

    def aggregate_stats(self) -> Dict[str, Any]:
        """
        Run full aggregation and update jarvis_tool_performance_stats.
        Called periodically to keep stats current.
        """
        try:
            with self.db.get_cursor() as cur:
                # Aggregate last 30 days into stats table
                cur.execute("""
                    INSERT INTO jarvis_tool_performance_stats
                    (tool_name, user_id, total_calls, success_count, failure_count,
                     success_rate, avg_duration_ms, p95_duration_ms, updated_at)
                    SELECT
                        tool_name,
                        'global',
                        COUNT(*),
                        SUM(CASE WHEN success THEN 1 ELSE 0 END),
                        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END),
                        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END),
                        AVG(duration_ms),
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms),
                        NOW()
                    FROM tool_audit
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    GROUP BY tool_name
                    ON CONFLICT (tool_name, user_id) DO UPDATE SET
                        total_calls = EXCLUDED.total_calls,
                        success_count = EXCLUDED.success_count,
                        failure_count = EXCLUDED.failure_count,
                        success_rate = EXCLUDED.success_rate,
                        avg_duration_ms = EXCLUDED.avg_duration_ms,
                        p95_duration_ms = EXCLUDED.p95_duration_ms,
                        updated_at = NOW()
                """)

                rows_affected = cur.rowcount

                return {
                    "success": True,
                    "tools_aggregated": rows_affected,
                    "timestamp": datetime.utcnow().isoformat()
                }

        except Exception as e:
            logger.error(f"Aggregate stats failed: {e}")
            return {"success": False, "error": str(e)}

    def get_recommendations(self) -> Dict[str, Any]:
        """
        Generate recommendations based on usage patterns.

        Returns:
            - Underutilized tools
            - Tools to optimize
            - Usage pattern suggestions
        """
        try:
            stats = self.get_tool_stats(days=30)
            failures = self.get_failure_analysis(days=30)
            time_patterns = self.get_time_patterns(days=30)

            recommendations = []

            # Find underutilized tools (registered but rarely used)
            if stats.get("success"):
                used_tools = {t["tool_name"] for t in stats.get("tools", [])}
                # This would need the full registry - skip for now

            # Find tools to optimize (high failure rate)
            if failures.get("success"):
                for fail in failures.get("failures", []):
                    if fail["failure_rate"] > 10:
                        recommendations.append({
                            "type": "optimize",
                            "priority": "high" if fail["failure_rate"] > 30 else "medium",
                            "tool": fail["tool_name"],
                            "reason": f"Failure rate: {fail['failure_rate']}%",
                            "action": "Review error patterns and improve error handling"
                        })

            # Time-based recommendations
            if time_patterns.get("success"):
                insights = time_patterns.get("insights", [])
                for insight in insights:
                    if "Nachtarbeit" in insight:
                        recommendations.append({
                            "type": "behavior",
                            "priority": "info",
                            "reason": insight,
                            "action": "Consider scheduling complex tasks during peak productivity hours"
                        })

            return {
                "success": True,
                "recommendations": recommendations,
                "generated_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Get recommendations failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_analytics: Optional[ToolUsageAnalytics] = None


def get_tool_usage_analytics() -> ToolUsageAnalytics:
    """Get or create analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = ToolUsageAnalytics()
    return _analytics
