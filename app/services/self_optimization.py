"""
Self-Optimization Service - Phase 21 Option 3C

Proactive self-monitoring and automatic optimization suggestions.
Jarvis monitors his own performance and proposes improvements.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.self_optimization")


@dataclass
class OptimizationProposal:
    """A proposed optimization."""
    category: str  # performance, quality, cost, reliability
    title: str
    description: str
    impact: str  # high, medium, low
    effort: str  # high, medium, low
    metrics_affected: List[str]
    proposed_action: str
    confidence: float


class SelfOptimizationService:
    """
    Service for self-monitoring and optimization.

    Analyzes system metrics and proposes improvements.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _table_exists(cur, table_name: str) -> bool:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f"public.{table_name}",))
        row = cur.fetchone()
        return bool(row and row.get("present"))

    def run_optimization_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Run comprehensive optimization analysis.

        Checks:
        1. Tool performance (latency, errors)
        2. Query patterns (repetitive questions)
        3. Memory efficiency (unused facts)
        4. Cost optimization (token usage)

        Args:
            days: Number of days to analyze

        Returns:
            Dict with analysis results and proposals
        """
        proposals = []

        # 1. Analyze tool performance
        tool_proposals = self._analyze_tool_performance(days)
        proposals.extend(tool_proposals)

        # 2. Analyze query patterns
        query_proposals = self._analyze_query_patterns(days)
        proposals.extend(query_proposals)

        # 3. Analyze memory efficiency
        memory_proposals = self._analyze_memory_efficiency(days)
        proposals.extend(memory_proposals)

        # 4. Analyze cost optimization
        cost_proposals = self._analyze_cost_optimization(days)
        proposals.extend(cost_proposals)

        # 5. Analyze response quality
        quality_proposals = self._analyze_response_quality(days)
        proposals.extend(quality_proposals)

        # Sort by impact and confidence
        proposals.sort(key=lambda p: (
            {"high": 3, "medium": 2, "low": 1}.get(p.impact, 0),
            p.confidence
        ), reverse=True)

        return {
            "success": True,
            "analysis_period_days": days,
            "timestamp": datetime.now().isoformat(),
            "proposals": [
                {
                    "category": p.category,
                    "title": p.title,
                    "description": p.description,
                    "impact": p.impact,
                    "effort": p.effort,
                    "metrics_affected": p.metrics_affected,
                    "proposed_action": p.proposed_action,
                    "confidence": round(p.confidence, 2)
                }
                for p in proposals[:10]  # Top 10 proposals
            ],
            "total_proposals": len(proposals)
        }

    def _analyze_tool_performance(self, days: int) -> List[OptimizationProposal]:
        """Analyze tool performance and identify optimization opportunities."""
        proposals = []

        try:
            from ..postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                    if not self._table_exists(cur, "jarvis_tool_executions"):
                        return proposals

                    # Find slow tools (avg > 2s)
                    cur.execute("""
                        SELECT tool_name,
                               COUNT(*) as calls,
                               ROUND(AVG(latency_ms)::numeric, 0) as avg_latency,
                               ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 0) as p95_latency
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days'
                        GROUP BY tool_name
                        HAVING COUNT(*) >= 10 AND AVG(latency_ms) > 2000
                        ORDER BY avg_latency DESC
                        LIMIT 5
                    """, (days,))

                    for row in cur.fetchall():
                        tool_name = row.get("tool_name")
                        calls = row.get("calls", 0)
                        avg_latency = row.get("avg_latency", 0)
                        p95_latency = row.get("p95_latency", 0)
                        proposals.append(OptimizationProposal(
                            category="performance",
                            title=f"Slow Tool: {tool_name}",
                            description=f"Tool '{tool_name}' has avg latency of {avg_latency}ms (p95: {p95_latency}ms) over {calls} calls",
                            impact="medium",
                            effort="medium",
                            metrics_affected=["tool_latency", "response_time"],
                            proposed_action=f"Investigate caching opportunities or async execution for {tool_name}",
                            confidence=0.8
                        ))

                    # Find high-failure tools
                    cur.execute("""
                        SELECT tool_name,
                               COUNT(*) as calls,
                               COUNT(CASE WHEN NOT success THEN 1 END) as failures,
                               ROUND((COUNT(CASE WHEN NOT success THEN 1 END)::numeric / COUNT(*)::numeric) * 100, 1) as failure_rate
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days'
                        GROUP BY tool_name
                        HAVING COUNT(*) >= 10
                           AND COUNT(CASE WHEN NOT success THEN 1 END)::float / COUNT(*) > 0.1
                        ORDER BY failure_rate DESC
                        LIMIT 5
                    """, (days,))

                    for row in cur.fetchall():
                        tool_name = row.get("tool_name")
                        calls = row.get("calls", 0)
                        failures = row.get("failures", 0)
                        failure_rate = row.get("failure_rate", 0)
                        proposals.append(OptimizationProposal(
                            category="reliability",
                            title=f"High Failure Rate: {tool_name}",
                            description=f"Tool '{tool_name}' has {failure_rate}% failure rate ({failures}/{calls} calls)",
                            impact="high",
                            effort="medium",
                            metrics_affected=["error_rate", "reliability"],
                            proposed_action=f"Review error logs for {tool_name} and improve error handling",
                            confidence=0.9
                        ))

        except Exception as e:
            logger.warning(f"Tool performance analysis failed: {e}")

        return proposals

    def _analyze_query_patterns(self, days: int) -> List[OptimizationProposal]:
        """Analyze query patterns for optimization opportunities."""
        proposals = []

        try:
            from ..postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                    if not self._table_exists(cur, "jarvis_sessions"):
                        return proposals

                    # Find repetitive queries (similar questions asked multiple times)
                    cur.execute("""
                        SELECT COUNT(*) as session_count
                        FROM jarvis_sessions
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    row = cur.fetchone()
                    session_count = row.get("session_count", 0) if row else 0

                    if session_count > 50:
                        # Check for query clustering opportunities
                        proposals.append(OptimizationProposal(
                            category="quality",
                            title="Consider Query Templates",
                            description=f"High session volume ({session_count} sessions in {days} days). Consider creating templates for common queries.",
                            impact="low",
                            effort="low",
                            metrics_affected=["user_experience"],
                            proposed_action="Analyze common query patterns and create shortcuts or playbooks",
                            confidence=0.6
                        ))

        except Exception as e:
            logger.warning(f"Query pattern analysis failed: {e}")

        return proposals

    def _analyze_memory_efficiency(self, days: int) -> List[OptimizationProposal]:
        """Analyze memory/fact storage efficiency."""
        proposals = []

        try:
            from ..postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                    if not self._table_exists(cur, "jarvis_facts"):
                        return proposals

                    # Check for stale facts
                    cur.execute("""
                        SELECT COUNT(*) as stale_count
                        FROM jarvis_facts
                        WHERE last_accessed < NOW() - INTERVAL '90 days'
                          AND recency_score < 0.3
                    """)
                    row = cur.fetchone()
                    stale_count = row.get("stale_count", 0) if row else 0

                    if stale_count > 100:
                        proposals.append(OptimizationProposal(
                            category="performance",
                            title="Memory Cleanup Needed",
                            description=f"{stale_count} facts haven't been accessed in 90+ days with low recency scores",
                            impact="medium",
                            effort="low",
                            metrics_affected=["memory_usage", "search_performance"],
                            proposed_action="Run archive_memory to move stale facts to cold storage",
                            confidence=0.85
                        ))

                    # Check for potential duplicates
                    cur.execute("""
                        SELECT COUNT(*) FROM (
                            SELECT content, COUNT(*) as cnt
                            FROM jarvis_facts
                            GROUP BY content
                            HAVING COUNT(*) > 1
                        ) duplicates
                    """)
                    row = cur.fetchone()
                    dup_count = row.get("count", 0) if row else 0

                    if dup_count > 10:
                        proposals.append(OptimizationProposal(
                            category="quality",
                            title="Duplicate Facts Detected",
                            description=f"{dup_count} potential duplicate facts found",
                            impact="medium",
                            effort="low",
                            metrics_affected=["data_quality", "search_relevance"],
                            proposed_action="Run duplicate cleanup job to merge or remove duplicates",
                            confidence=0.8
                        ))

        except Exception as e:
            logger.warning(f"Memory efficiency analysis failed: {e}")

        return proposals

    def _analyze_cost_optimization(self, days: int) -> List[OptimizationProposal]:
        """Analyze LLM cost optimization opportunities."""
        proposals = []

        try:
            from ..postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                    if not self._table_exists(cur, "jarvis_llm_calls"):
                        return proposals

                    # Check token usage patterns
                    cur.execute("""
                        SELECT
                            AVG(input_tokens) as avg_input,
                            AVG(output_tokens) as avg_output,
                            SUM(input_tokens + output_tokens) as total_tokens
                        FROM jarvis_llm_calls
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    row = cur.fetchone()

                    if row and row.get("avg_input") is not None:
                        avg_input = row.get("avg_input", 0)
                        avg_output = row.get("avg_output", 0)
                        total_tokens = row.get("total_tokens", 0)

                        if avg_input > 3000:
                            proposals.append(OptimizationProposal(
                                category="cost",
                                title="High Average Input Tokens",
                                description=f"Average input tokens ({avg_input:.0f}) is high. Consider prompt compression.",
                                impact="medium",
                                effort="medium",
                                metrics_affected=["llm_cost", "latency"],
                                proposed_action="Review prompt assembly and reduce context where possible",
                                confidence=0.7
                            ))

                        # Check cache hit rate
                        cur.execute("""
                            SELECT
                                COUNT(*) as total,
                                COUNT(CASE WHEN cache_hit THEN 1 END) as hits
                            FROM jarvis_llm_calls
                            WHERE created_at > NOW() - INTERVAL '%s days'
                        """, (days,))
                        cache_row = cur.fetchone()

                        if cache_row and cache_row.get("total", 0) > 100:
                            hit_rate = cache_row.get("hits", 0) / cache_row.get("total", 1) * 100
                            if hit_rate < 20:
                                proposals.append(OptimizationProposal(
                                    category="cost",
                                    title="Low Cache Hit Rate",
                                    description=f"LLM cache hit rate is only {hit_rate:.1f}%. Potential for cost savings.",
                                    impact="high",
                                    effort="medium",
                                    metrics_affected=["llm_cost", "latency"],
                                    proposed_action="Improve semantic caching configuration and cache TTL",
                                    confidence=0.75
                                ))

        except Exception as e:
            logger.warning(f"Cost optimization analysis failed: {e}")

        return proposals

    def _analyze_response_quality(self, days: int) -> List[OptimizationProposal]:
        """Analyze response quality metrics."""
        proposals = []

        try:
            from ..postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                    has_corrections = self._table_exists(cur, "jarvis_corrections")
                    has_sessions = self._table_exists(cur, "jarvis_sessions")
                    has_conf_logs = self._table_exists(cur, "jarvis_confidence_logs")

                    # Check correction rate (how often user corrects Jarvis)
                    correction_count = 0
                    if has_corrections:
                        cur.execute("""
                            SELECT COUNT(*) as correction_count
                            FROM jarvis_corrections
                            WHERE created_at > NOW() - INTERVAL '%s days'
                        """, (days,))
                        row = cur.fetchone()
                        correction_count = row.get("correction_count", 0) if row else 0

                    session_count = 1
                    if has_sessions:
                        cur.execute("""
                            SELECT COUNT(*) as session_count
                            FROM jarvis_sessions
                            WHERE created_at > NOW() - INTERVAL '%s days'
                        """, (days,))
                        row = cur.fetchone()
                        session_count = row.get("session_count", 1) if row else 1

                    if session_count > 0:
                        correction_rate = correction_count / session_count * 100
                        if correction_rate > 10:
                            proposals.append(OptimizationProposal(
                                category="quality",
                                title="High Correction Rate",
                                description=f"User corrections at {correction_rate:.1f}% of sessions. Review common correction patterns.",
                                impact="high",
                                effort="medium",
                                metrics_affected=["user_satisfaction", "accuracy"],
                                proposed_action="Analyze correction patterns and update behavior rules",
                                confidence=0.85
                            ))

                    # Check for low-confidence responses
                    low_conf_count = 0
                    if has_conf_logs:
                        cur.execute("""
                            SELECT COUNT(*) as low_conf_count
                            FROM jarvis_confidence_logs
                            WHERE created_at > NOW() - INTERVAL '%s days'
                              AND confidence < 0.5
                        """, (days,))
                        row = cur.fetchone()
                        low_conf_count = row.get("low_conf_count", 0) if row else 0

                    if low_conf_count > 20:
                        proposals.append(OptimizationProposal(
                            category="quality",
                            title="Many Low-Confidence Responses",
                            description=f"{low_conf_count} responses with confidence < 50% in {days} days",
                            impact="medium",
                            effort="high",
                            metrics_affected=["accuracy", "reliability"],
                            proposed_action="Review knowledge gaps and improve RAG retrieval",
                            confidence=0.7
                        ))

        except Exception as e:
            logger.warning(f"Response quality analysis failed: {e}")

        return proposals

    def get_health_summary(self) -> Dict[str, Any]:
        """Get a quick health summary for Jarvis."""
        try:
            from ..postgres_state import get_dict_cursor

            summary = {
                "timestamp": datetime.now().isoformat(),
                "status": "healthy",
                "metrics": {}
            }

            with get_dict_cursor() as cur:
                if not self._table_exists(cur, "jarvis_tool_executions"):
                    summary["metrics"]["tool_success_rate_24h"] = 100.0
                    summary["metrics"]["active_tools_7d"] = 0
                else:
                    # Tool success rate (24h)
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(CASE WHEN success THEN 1 END) as successful
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '24 hours'
                    """)
                    row = cur.fetchone()
                    total = row.get("total", 0) if row else 0
                    successful = row.get("successful", 0) if row else 0
                    if total > 0:
                        summary["metrics"]["tool_success_rate_24h"] = round(successful / total * 100, 1)
                    else:
                        summary["metrics"]["tool_success_rate_24h"] = 100.0

                    # Active tools (used in last 7 days)
                    cur.execute("""
                        SELECT COUNT(DISTINCT tool_name) as active_tools
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '7 days'
                    """)
                    row = cur.fetchone()
                    summary["metrics"]["active_tools_7d"] = row.get("active_tools", 0) if row else 0

                    # Total enabled tools
                    if self._table_exists(cur, "jarvis_tools"):
                        cur.execute("""
                            SELECT COUNT(*) as total_enabled FROM jarvis_tools WHERE enabled = true
                        """)
                        row = cur.fetchone()
                        summary["metrics"]["total_enabled_tools"] = row.get("total_enabled", 0) if row else 0
                    else:
                        summary["metrics"]["total_enabled_tools"] = 0

                    # Avg response latency (24h)
                    if self._table_exists(cur, "jarvis_tool_executions"):
                        cur.execute("""
                            SELECT ROUND(AVG(latency_ms)::numeric, 0) as avg_latency
                            FROM jarvis_tool_executions
                            WHERE executed_at > NOW() - INTERVAL '24 hours'
                        """)
                        row = cur.fetchone()
                        summary["metrics"]["avg_tool_latency_ms_24h"] = int(row.get("avg_latency")) if row and row.get("avg_latency") else 0
                    else:
                        summary["metrics"]["avg_tool_latency_ms_24h"] = 0

                    # Determine overall status
                    if summary["metrics"]["tool_success_rate_24h"] < 90:
                        summary["status"] = "degraded"
                    if summary["metrics"]["tool_success_rate_24h"] < 80:
                        summary["status"] = "unhealthy"

            return summary

        except Exception as e:
            logger.error(f"Failed to get health summary: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "unknown",
                "error": str(e)
            }

    def apply_optimization(self, proposal_title: str, confirm: bool = False) -> Dict[str, Any]:
        """
        Apply an optimization proposal.

        Args:
            proposal_title: Title of the proposal to apply
            confirm: Must be True to actually apply

        Returns:
            Dict with result
        """
        if not confirm:
            return {
                "success": False,
                "error": "Confirmation required. Set confirm=True to apply.",
                "proposal_title": proposal_title
            }

        # Log the application
        try:
            from ..postgres_state import get_conn

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_self_modifications
                        (modification_type, target, changes, created_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (
                        "optimization_applied",
                        proposal_title,
                        json.dumps({"applied_at": datetime.now().isoformat()})
                    ))
                    conn.commit()

            return {
                "success": True,
                "message": f"Optimization '{proposal_title}' logged for application",
                "note": "Manual implementation may be required for some optimizations"
            }

        except Exception as e:
            logger.error(f"Failed to apply optimization: {e}")
            return {"success": False, "error": str(e)}


# Singleton accessor
_service = None


def get_self_optimization_service() -> SelfOptimizationService:
    """Get the singleton SelfOptimizationService instance."""
    global _service
    if _service is None:
        _service = SelfOptimizationService()
    return _service
