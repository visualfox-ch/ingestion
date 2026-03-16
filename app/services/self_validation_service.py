"""
Jarvis Self-Validation Service.

Uses the data sources that actually exist in this codebase:
- PostgreSQL: message, tool_audit, user_feedback, interaction_quality
- SQLite state DB: conversation_contexts, topic_mentions, facts
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import psutil
except ImportError:  # pragma: no cover - depends on runtime image
    psutil = None

from ..db_safety import safe_aggregate_query, safe_list_query
from ..observability import get_logger

logger = get_logger("jarvis.self_validation")

# Simple in-memory cache with TTL
_cache: Dict[str, Any] = {}
_cache_timestamps: Dict[str, datetime] = {}
CACHE_TTL_SECONDS = 60  # 1 minute cache


def _get_cached(key: str) -> Optional[Any]:
    """Get cached value if not expired."""
    if key in _cache and key in _cache_timestamps:
        if datetime.now() - _cache_timestamps[key] < timedelta(seconds=CACHE_TTL_SECONDS):
            return _cache[key]
    return None


def _set_cached(key: str, value: Any) -> None:
    """Set cached value with timestamp."""
    _cache[key] = value
    _cache_timestamps[key] = datetime.now()


class SelfValidationService:
    """Service for Jarvis self-monitoring and validation."""

    def __init__(self) -> None:
        self.start_time = datetime.now()
        self._last_health: Optional[Dict[str, Any]] = None
        self._last_health_time: Optional[datetime] = None

    # =========================================================================
    # Helpers
    # =========================================================================

    def _state_db_candidates(self) -> List[Path]:
        candidates: List[Path] = []
        env_path = os.environ.get("JARVIS_STATE_DB")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path("/brain/system/state/jarvis_state.db"),
                Path("/Volumes/BRAIN/system/state/jarvis_state.db"),
            ]
        )

        unique: List[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    def _resolve_state_db_path(self) -> Optional[Path]:
        for candidate in self._state_db_candidates():
            if candidate.exists():
                return candidate
        return None

    def _get_state_conn(self) -> Optional[sqlite3.Connection]:
        db_path = self._resolve_state_db_path()
        if db_path is None:
            return None

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _sqlite_table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _pg_table_exists(self, table_name: str) -> bool:
        try:
            with safe_list_query("pg_catalog", timeout=5) as cur:
                cur.execute("SELECT to_regclass(%s) AS regclass", (f"public.{table_name}",))
                row = cur.fetchone()
                return bool(row and row["regclass"])
        except Exception as exc:
            logger.warning(f"Failed to inspect PostgreSQL table {table_name}: {exc}")
            return False

    def _format_timestamp(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
        return str(value)

    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _session_ids_for_user(
        self,
        conn: Optional[sqlite3.Connection],
        user_id: Optional[int],
        cutoff: Optional[datetime] = None,
    ) -> List[str]:
        if conn is None or user_id is None or not self._sqlite_table_exists(conn, "conversation_contexts"):
            return []

        query = "SELECT session_id FROM conversation_contexts WHERE user_id = ?"
        params: List[Any] = [user_id]
        if cutoff is not None:
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
        rows = conn.execute(query, params).fetchall()
        return [row["session_id"] for row in rows if row["session_id"]]

    def _context_recommendations(self, stats: Dict[str, Any]) -> List[str]:
        recs: List[str] = []

        avg_tokens = stats.get("avg_total_tokens") or stats.get("avg_input_tokens") or 0
        max_tokens = stats.get("max_total_tokens") or stats.get("max_input_tokens") or 0

        if avg_tokens and avg_tokens > 50000:
            recs.append("High average context usage; summarize history more aggressively.")
        if max_tokens and max_tokens > 150000:
            recs.append("Some requests are close to the context ceiling; add chunking or pruning.")
        if avg_tokens and avg_tokens < 5000:
            recs.append("Low context usage; more relevant history could be injected.")
        if not recs:
            recs.append("Context usage looks balanced.")

        return recs

    def _diagnose_memory_issues(
        self,
        context_stats: Dict[str, Any],
        facts_stats: Dict[str, Any],
        auto_persist_status: Dict[str, Any],
    ) -> List[str]:
        issues: List[str] = []

        if context_stats.get("total_contexts", 0) == 0:
            issues.append("No conversation contexts stored; session persistence may not be working.")

        last_context = self._parse_timestamp(context_stats.get("last_context"))
        if last_context and datetime.now() - last_context > timedelta(hours=24):
            issues.append(
                f"No contexts stored in the last 24h; latest entry is {context_stats['last_context']}."
            )

        if facts_stats.get("total_facts", 0) < 10:
            issues.append("Very few facts stored; fact capture may be underused.")

        if not auto_persist_status.get("enabled", False):
            issues.append(auto_persist_status.get("reason", "Session persistence metadata is unavailable."))

        if not issues:
            issues.append("Memory systems appear healthy.")

        return issues

    def _assess_continuity(self, score: float, contexts: int, gaps: Sequence[Dict[str, Any]]) -> str:
        if score > 70 and contexts > 10:
            return "Excellent continuity with consistent context persistence."
        if score > 50:
            return "Good continuity with regular engagement."
        if score > 20:
            return "Moderate continuity with noticeable gaps between sessions."
        return "Low continuity; cross-session context is sparse."

    def _calculate_quality_score(
        self,
        feedback: Dict[str, Any],
        tool_success: Optional[float],
        consistency: Dict[str, Any],
    ) -> Optional[float]:
        scores: List[float] = []
        weights: List[float] = []

        if feedback.get("avg_rating") is not None:
            scores.append(float(feedback["avg_rating"]) * 20)
            weights.append(0.4)

        if tool_success is not None:
            scores.append(float(tool_success))
            weights.append(0.4)

        avg_output = consistency.get("avg_output_tokens")
        stddev_output = consistency.get("stddev_output_tokens")
        if avg_output and stddev_output is not None:
            cv = float(stddev_output) / float(avg_output)
            consistency_score = max(0.0, 100.0 - (cv * 100.0))
            scores.append(consistency_score)
            weights.append(0.2)

        if not scores:
            return None

        total_weight = sum(weights)
        weighted_sum = sum(score * weight for score, weight in zip(scores, weights))
        return round(weighted_sum / total_weight, 1)

    def _interpret_quality(self, score: Optional[float]) -> str:
        if score is None:
            return "Insufficient data for quality assessment."
        if score >= 90:
            return "Excellent; responses are high quality and consistent."
        if score >= 75:
            return "Good; generally effective with room for improvement."
        if score >= 60:
            return "Moderate; some quality issues should be addressed."
        return "Needs improvement; review feedback and error patterns."

    def _assess_proactivity(self, score: Optional[float]) -> str:
        if score is None:
            return "No proactive activity to assess."
        if score >= 75:
            return "Highly effective; proactive hints are well received."
        if score >= 50:
            return "Moderately effective; some hints resonate."
        if score >= 25:
            return "Low effectiveness; timing or relevance should be tuned."
        return "Needs review; hints may be intrusive or irrelevant."

    # =========================================================================
    # Phase 1
    # =========================================================================

    def get_system_health(self) -> Dict[str, Any]:
        # Check cache first (saves ~200ms from psutil interval calls)
        cached = _get_cached("system_health")
        if cached:
            return cached

        try:
            if psutil is None:
                return {
                    "status": "unavailable",
                    "timestamp": datetime.now().isoformat(),
                    "error": "psutil is not installed.",
                }

            process = psutil.Process()
            mem = process.memory_info()
            system_mem = psutil.virtual_memory()
            cpu_percent = process.cpu_percent(interval=0.1)
            system_cpu = psutil.cpu_percent(interval=0.1)

            brain_path = "/brain" if os.path.exists("/brain") else "/Volumes/BRAIN"
            try:
                disk = psutil.disk_usage(brain_path)
                disk_info = {
                    "path": brain_path,
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent_used": disk.percent,
                }
            except Exception:
                disk_info = {"error": "Could not read disk info"}

            create_time = datetime.fromtimestamp(process.create_time())
            uptime = datetime.now() - create_time

            try:
                open_files = len(process.open_files())
            except Exception:
                open_files = -1

            result = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "process": {
                    "pid": process.pid,
                    "uptime_seconds": int(uptime.total_seconds()),
                    "uptime_human": str(uptime).split(".")[0],
                    "threads": process.num_threads(),
                    "open_files": open_files,
                    "memory_rss_mb": round(mem.rss / (1024**2), 2),
                    "memory_vms_mb": round(mem.vms / (1024**2), 2),
                    "cpu_percent": cpu_percent,
                },
                "system": {
                    "cpu_percent": system_cpu,
                    "cpu_count": psutil.cpu_count(),
                    "memory_total_gb": round(system_mem.total / (1024**3), 2),
                    "memory_available_gb": round(system_mem.available / (1024**3), 2),
                    "memory_percent_used": system_mem.percent,
                },
                "disk": disk_info,
            }
            _set_cached("system_health", result)
            return result
        except Exception as exc:
            logger.error(f"System health check failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def validate_tool_registry(self) -> Dict[str, Any]:
        try:
            from ..tools import TOOL_REGISTRY, get_tool_definitions

            tool_names = sorted(TOOL_REGISTRY.keys())
            tool_definitions = get_tool_definitions()
            defined_tools = {tool["name"] for tool in tool_definitions}
            missing_definitions = [tool for tool in tool_names if tool not in defined_tools]
            extra_definitions = [tool["name"] for tool in tool_definitions if tool["name"] not in tool_names]

            categories: Dict[str, List[str]] = {
                "search": [],
                "memory": [],
                "communication": [],
                "project": [],
                "file": [],
                "self_awareness": [],
                "other": [],
            }

            for tool in tool_names:
                if "search" in tool or "recent" in tool:
                    categories["search"].append(tool)
                elif "remember" in tool or "recall" in tool or "context" in tool:
                    categories["memory"].append(tool)
                elif "email" in tool or "calendar" in tool or "gmail" in tool:
                    categories["communication"].append(tool)
                elif "project" in tool or "thread" in tool:
                    categories["project"].append(tool)
                elif "file" in tool or "read" in tool or "write" in tool:
                    categories["file"].append(tool)
                elif any(
                    keyword in tool
                    for keyword in (
                        "introspect",
                        "health",
                        "system",
                        "validate",
                        "metrics",
                        "benchmark",
                        "quality",
                        "proactivity",
                        "dashboard",
                    )
                ):
                    categories["self_awareness"].append(tool)
                else:
                    categories["other"].append(tool)

            issues: List[str] = []
            if missing_definitions:
                issues.append(f"Tools without JSON definitions: {missing_definitions}")
            if extra_definitions:
                issues.append(f"Definitions without implementations: {extra_definitions}")

            return {
                "status": "valid" if not issues else "has_issues",
                "timestamp": datetime.now().isoformat(),
                "total_tools": len(tool_names),
                "tools": tool_names,
                "categories": {
                    key: {"count": len(values), "tools": values}
                    for key, values in categories.items()
                    if values
                },
                "issues": issues or None,
                "validation_passed": not issues,
            }
        except Exception as exc:
            logger.error(f"Tool registry validation failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def get_response_metrics(self, hours: int = 24) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(hours=hours)
        data_sources: List[str] = []
        stats: Dict[str, Any] = {
            "total_interactions": 0,
            "latency": {"avg_ms": None, "min_ms": None, "max_ms": None},
            "tokens": {
                "avg_input": None,
                "avg_output": None,
                "total_input": 0,
                "total_output": 0,
            },
        }
        tool_usage: Dict[str, int] = {}
        hourly_distribution: Dict[int, int] = {}

        try:
            if self._pg_table_exists("message"):
                with safe_aggregate_query("message") as cur:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE role = 'assistant') AS total_interactions,
                            AVG(tokens_in) FILTER (WHERE role = 'assistant') AS avg_input,
                            AVG(tokens_out) FILTER (WHERE role = 'assistant') AS avg_output,
                            COALESCE(SUM(tokens_in) FILTER (WHERE role = 'assistant'), 0) AS total_input,
                            COALESCE(SUM(tokens_out) FILTER (WHERE role = 'assistant'), 0) AS total_output
                        FROM message
                        WHERE created_at > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    stats["total_interactions"] = int(row["total_interactions"] or 0)
                    stats["tokens"] = {
                        "avg_input": round(float(row["avg_input"]), 0) if row["avg_input"] is not None else None,
                        "avg_output": round(float(row["avg_output"]), 0) if row["avg_output"] is not None else None,
                        "total_input": int(row["total_input"] or 0),
                        "total_output": int(row["total_output"] or 0),
                    }

                with safe_aggregate_query("message") as cur:
                    cur.execute(
                        """
                        SELECT
                            EXTRACT(HOUR FROM created_at) AS hour,
                            COUNT(*) AS count
                        FROM message
                        WHERE created_at > %s
                          AND role = 'assistant'
                        GROUP BY hour
                        ORDER BY hour
                        """,
                        (cutoff,),
                    )
                    hourly_distribution = {
                        int(row["hour"]): int(row["count"])
                        for row in cur.fetchall()
                    }
                data_sources.append("message")

            if self._pg_table_exists("jarvis_interactions"):
                with safe_aggregate_query("jarvis_interactions") as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(duration_seconds * 1000.0) AS avg_ms,
                            MIN(duration_seconds * 1000.0) AS min_ms,
                            MAX(duration_seconds * 1000.0) AS max_ms
                        FROM jarvis_interactions
                        WHERE created_at > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    stats["latency"] = {
                        "avg_ms": round(float(row["avg_ms"]), 2) if row["avg_ms"] is not None else None,
                        "min_ms": round(float(row["min_ms"]), 2) if row["min_ms"] is not None else None,
                        "max_ms": round(float(row["max_ms"]), 2) if row["max_ms"] is not None else None,
                    }
                data_sources.append("jarvis_interactions")
            elif self._pg_table_exists("interaction_quality"):
                with safe_aggregate_query("interaction_quality") as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(response_time_seconds * 1000.0) AS avg_ms,
                            MIN(response_time_seconds * 1000.0) AS min_ms,
                            MAX(response_time_seconds * 1000.0) AS max_ms
                        FROM interaction_quality
                        WHERE timestamp > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    stats["latency"] = {
                        "avg_ms": round(float(row["avg_ms"]), 2) if row["avg_ms"] is not None else None,
                        "min_ms": round(float(row["min_ms"]), 2) if row["min_ms"] is not None else None,
                        "max_ms": round(float(row["max_ms"]), 2) if row["max_ms"] is not None else None,
                    }
                data_sources.append("interaction_quality")

            if self._pg_table_exists("tool_audit"):
                with safe_aggregate_query("tool_audit") as cur:
                    cur.execute(
                        """
                        SELECT tool_name, COUNT(*) AS count
                        FROM tool_audit
                        WHERE created_at > %s
                        GROUP BY tool_name
                        ORDER BY count DESC
                        LIMIT 20
                        """,
                        (cutoff,),
                    )
                    tool_usage = {row["tool_name"]: int(row["count"]) for row in cur.fetchall()}
                data_sources.append("tool_audit")

            status = "success" if data_sources else "no_data"
            response: Dict[str, Any] = {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "period_hours": hours,
                "stats": stats,
                "tool_usage": tool_usage,
                "hourly_distribution": hourly_distribution,
                "data_sources": data_sources,
            }
            if not data_sources:
                response["message"] = "No compatible response-metrics data sources are available."
            return response
        except Exception as exc:
            logger.error(f"Response metrics query failed: {exc}")
            return {"status": "error", "error": str(exc)}

    # =========================================================================
    # Phase 2
    # =========================================================================

    def memory_diagnostics(self) -> Dict[str, Any]:
        conn = self._get_state_conn()
        if conn is None:
            return {
                "status": "no_data",
                "message": "State DB not found.",
                "searched_paths": [str(path) for path in self._state_db_candidates()],
            }

        try:
            state_db_path = self._resolve_state_db_path()

            context_stats: Dict[str, Any] = {
                "total_contexts": 0,
                "unique_users": 0,
                "last_context": None,
                "first_context": None,
            }
            recent_contexts: List[Dict[str, Any]] = []
            if self._sqlite_table_exists(conn, "conversation_contexts"):
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_contexts,
                        COUNT(DISTINCT user_id) AS unique_users,
                        MAX(COALESCE(end_time, created_at)) AS last_context,
                        MIN(created_at) AS first_context
                    FROM conversation_contexts
                    """
                ).fetchone()
                context_stats = {
                    "total_contexts": int(row["total_contexts"] or 0),
                    "unique_users": int(row["unique_users"] or 0),
                    "last_context": self._format_timestamp(row["last_context"]),
                    "first_context": self._format_timestamp(row["first_context"]),
                }

                recent_rows = conn.execute(
                    """
                    SELECT user_id, session_id, namespace,
                           COALESCE(end_time, created_at) as last_activity,
                           message_count
                    FROM conversation_contexts
                    ORDER BY COALESCE(end_time, created_at) DESC
                    LIMIT 5
                    """
                ).fetchall()
                recent_contexts = [
                    {
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "namespace": row["namespace"],
                        "last_activity": self._format_timestamp(row["last_activity"]),
                        "message_count": int(row["message_count"] or 0),
                    }
                    for row in recent_rows
                ]

            facts_stats: Dict[str, Any] = {
                "total_facts": 0,
                "categories": 0,
                "last_fact": None,
            }
            # Facts are stored in jarvis_memory.db, not jarvis_state.db
            memory_db_candidates = [
                Path("/brain/system/state/jarvis_memory.db"),
                Path("/Volumes/BRAIN/system/state/jarvis_memory.db"),
            ]
            for memory_path in memory_db_candidates:
                if memory_path.exists():
                    try:
                        memory_conn = sqlite3.connect(str(memory_path), timeout=5.0)
                        memory_conn.row_factory = sqlite3.Row
                        # Check if facts table exists
                        table_check = memory_conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
                        ).fetchone()
                        if table_check:
                            row = memory_conn.execute(
                                """
                                SELECT
                                    COUNT(*) AS total_facts,
                                    COUNT(DISTINCT category) AS categories,
                                    MAX(created_at) AS last_fact
                                FROM facts
                                WHERE active = 1
                                """
                            ).fetchone()
                            facts_stats = {
                                "total_facts": int(row["total_facts"] or 0),
                                "categories": int(row["categories"] or 0),
                                "last_fact": self._format_timestamp(row["last_fact"]),
                            }
                        memory_conn.close()
                    except Exception as e:
                        log_with_context(logger, "warning", "Failed to read memory DB", error=str(e))
                    break

            auto_persist_status: Dict[str, Any]
            if self._sqlite_table_exists(conn, "session_messages"):
                row = conn.execute("SELECT COUNT(*) AS count FROM session_messages").fetchone()
                auto_persist_status = {
                    "enabled": True,
                    "session_messages": int(row["count"] or 0),
                }
            else:
                auto_persist_status = {
                    "enabled": False,
                    "reason": "session_messages table not found in state DB.",
                }

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "state_db_path": str(state_db_path) if state_db_path else None,
                "conversation_contexts": context_stats,
                "facts": facts_stats,
                "recent_contexts": recent_contexts,
                "auto_session_persist": auto_persist_status,
                "diagnosis": self._diagnose_memory_issues(
                    context_stats,
                    facts_stats,
                    auto_persist_status,
                ),
            }
        except Exception as exc:
            logger.error(f"Memory diagnostics failed: {exc}")
            return {"status": "error", "error": str(exc)}
        finally:
            conn.close()

    def context_window_analysis(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(days=7)
        data_source: Optional[str] = None

        try:
            if self._pg_table_exists("message"):
                state_conn = self._get_state_conn()
                session_ids = self._session_ids_for_user(state_conn, user_id, cutoff)
                if state_conn is not None:
                    state_conn.close()

                params: List[Any] = [cutoff]
                session_filter = ""
                if user_id is not None:
                    if not session_ids:
                        return {
                            "status": "no_data",
                            "timestamp": datetime.now().isoformat(),
                            "user_id": user_id,
                            "message": "No sessions found for this user in the state DB.",
                        }
                    placeholders = ", ".join(["%s"] * len(session_ids))
                    session_filter = f" AND session_id IN ({placeholders})"
                    params.extend(session_ids)

                with safe_aggregate_query("message") as cur:
                    cur.execute(
                        f"""
                        SELECT
                            AVG(tokens_in) AS avg_input,
                            AVG(tokens_out) AS avg_output,
                            MAX(tokens_in) AS max_input,
                            MAX(tokens_out) AS max_output,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tokens_in) AS p95_input,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tokens_out) AS p95_output,
                            COUNT(*) AS total_messages
                        FROM message
                        WHERE created_at > %s
                          AND role = 'assistant'
                          {session_filter}
                        """,
                        params,
                    )
                    row = cur.fetchone()
                    token_stats = {
                        "avg_input_tokens": round(float(row["avg_input"]), 0) if row["avg_input"] is not None else None,
                        "avg_output_tokens": round(float(row["avg_output"]), 0) if row["avg_output"] is not None else None,
                        "max_input_tokens": int(row["max_input"]) if row["max_input"] is not None else None,
                        "max_output_tokens": int(row["max_output"]) if row["max_output"] is not None else None,
                        "p95_input_tokens": round(float(row["p95_input"]), 0) if row["p95_input"] is not None else None,
                        "p95_output_tokens": round(float(row["p95_output"]), 0) if row["p95_output"] is not None else None,
                        "sampled_messages": int(row["total_messages"] or 0),
                    }
                    data_source = "message"
            elif self._pg_table_exists("jarvis_interactions"):
                with safe_aggregate_query("jarvis_interactions") as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(tokens_used) AS avg_total,
                            MAX(tokens_used) AS max_total,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tokens_used) AS p95_total,
                            COUNT(*) AS total_interactions
                        FROM jarvis_interactions
                        WHERE created_at > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    token_stats = {
                        "avg_total_tokens": round(float(row["avg_total"]), 0) if row["avg_total"] is not None else None,
                        "max_total_tokens": int(row["max_total"]) if row["max_total"] is not None else None,
                        "p95_total_tokens": round(float(row["p95_total"]), 0) if row["p95_total"] is not None else None,
                        "sampled_interactions": int(row["total_interactions"] or 0),
                    }
                    data_source = "jarvis_interactions"
            else:
                return {
                    "status": "no_data",
                    "timestamp": datetime.now().isoformat(),
                    "user_id": user_id,
                    "message": "No compatible token-tracking source is available.",
                }

            context_limits = {
                "claude_3_5_sonnet": 200000,
                "claude_3_opus": 200000,
                "recommended_max": 150000,
            }
            avg_total = (
                token_stats.get("avg_total_tokens")
                or (token_stats.get("avg_input_tokens") or 0) + (token_stats.get("avg_output_tokens") or 0)
            )
            efficiency = round((avg_total / context_limits["recommended_max"]) * 100, 2) if avg_total else None

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "token_stats": token_stats,
                "context_limits": context_limits,
                "context_utilization_percent": efficiency,
                "recommendations": self._context_recommendations(token_stats),
                "data_source": data_source,
            }
        except Exception as exc:
            logger.error(f"Context window analysis failed: {exc}")
            return {"status": "error", "error": str(exc)}

    # =========================================================================
    # Phase 3
    # =========================================================================

    def benchmark_tool_calls(self, hours: int = 24) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(hours=hours)

        try:
            if not self._pg_table_exists("tool_audit"):
                return {
                    "status": "no_data",
                    "timestamp": datetime.now().isoformat(),
                    "message": "tool_audit table not found.",
                }

            with safe_aggregate_query("tool_audit") as cur:
                cur.execute(
                    """
                    SELECT
                        tool_name,
                        COUNT(*) AS calls,
                        AVG(duration_ms) AS avg_ms,
                        MIN(duration_ms) AS min_ms,
                        MAX(duration_ms) AS max_ms,
                        AVG(CASE WHEN success THEN 100.0 ELSE 0.0 END) AS success_rate
                    FROM tool_audit
                    WHERE created_at > %s
                    GROUP BY tool_name
                    ORDER BY calls DESC
                    """,
                    (cutoff,),
                )
                rows = cur.fetchall()

            tool_benchmarks: Dict[str, Any] = {}
            for row in rows:
                tool_benchmarks[row["tool_name"]] = {
                    "calls": int(row["calls"] or 0),
                    "avg_ms": round(float(row["avg_ms"]), 2) if row["avg_ms"] is not None else None,
                    "min_ms": round(float(row["min_ms"]), 2) if row["min_ms"] is not None else None,
                    "max_ms": round(float(row["max_ms"]), 2) if row["max_ms"] is not None else None,
                    "success_rate_percent": round(float(row["success_rate"]), 1)
                    if row["success_rate"] is not None
                    else None,
                }

            slowest = sorted(
                ((tool, data["avg_ms"]) for tool, data in tool_benchmarks.items() if data["avg_ms"] is not None),
                key=lambda item: item[1],
                reverse=True,
            )[:5]
            failing = sorted(
                (
                    (tool, data["success_rate_percent"])
                    for tool, data in tool_benchmarks.items()
                    if data["success_rate_percent"] is not None and data["success_rate_percent"] < 95
                ),
                key=lambda item: item[1],
            )[:5]

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "period_hours": hours,
                "total_tools_used": len(tool_benchmarks),
                "benchmarks": tool_benchmarks,
                "insights": {
                    "slowest_tools": [{"tool": tool, "avg_ms": avg_ms} for tool, avg_ms in slowest],
                    "unreliable_tools": [
                        {"tool": tool, "success_rate": success_rate}
                        for tool, success_rate in failing
                    ],
                },
                "data_source": "tool_audit",
            }
        except Exception as exc:
            logger.error(f"Tool benchmark failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def compare_code_versions(self, module: str = "main") -> Dict[str, Any]:
        try:
            base_path = "/brain/system/ingestion/app"
            if not os.path.exists(base_path):
                base_path = "/Volumes/BRAIN/system/ingestion/app"

            file_map = {
                "main": "main.py",
                "agent": "agent.py",
                "tools": "tools.py",
                "config": "config.py",
                "router": "routers/self_validation_router.py",
            }

            filename = file_map.get(module, f"{module}.py")
            filepath = os.path.join(base_path, filename)
            if not os.path.exists(filepath):
                return {"status": "error", "error": f"File not found: {filepath}"}

            git_dir = os.path.dirname(base_path)
            log_result = subprocess.run(
                ["git", "-C", git_dir, "log", "--oneline", "-10", "--", f"app/{filename}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            recent_commits = log_result.stdout.strip().splitlines() if log_result.stdout.strip() else []

            diff_result = subprocess.run(
                ["git", "-C", git_dir, "diff", "HEAD~1", "--stat", "--", f"app/{filename}"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            stat = os.stat(filepath)
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "module": module,
                "file": filepath,
                "file_size_kb": round(stat.st_size / 1024, 2),
                "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "recent_commits": recent_commits[:5],
                "last_commit_diff": diff_result.stdout.strip() or "No recent changes",
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Git command timed out"}
        except Exception as exc:
            logger.error(f"Code version compare failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def conversation_continuity_test(self, user_id: int) -> Dict[str, Any]:
        conn = self._get_state_conn()
        if conn is None:
            return {"status": "no_data", "message": "State DB not found."}

        try:
            if not self._sqlite_table_exists(conn, "conversation_contexts"):
                return {
                    "status": "no_data",
                    "message": "conversation_contexts table not found in state DB.",
                }

            cutoff = datetime.now() - timedelta(days=30)
            rows = conn.execute(
                """
                SELECT
                    DATE(created_at) AS date,
                    COUNT(*) AS sessions,
                    COALESCE(SUM(message_count), 0) AS interactions,
                    MIN(start_time) AS first_msg,
                    MAX(COALESCE(end_time, created_at)) AS last_msg
                FROM conversation_contexts
                WHERE user_id = ?
                  AND created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                """,
                (user_id, cutoff.isoformat()),
            ).fetchall()

            daily_sessions = [
                {
                    "date": row["date"],
                    "sessions": int(row["sessions"] or 0),
                    "interactions": int(row["interactions"] or 0),
                    "first": self._format_timestamp(row["first_msg"]),
                    "last": self._format_timestamp(row["last_msg"]),
                }
                for row in rows
            ]

            context_row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversation_contexts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            context_count = int(context_row["count"] or 0)

            topic_count = 0
            if self._sqlite_table_exists(conn, "topic_mentions"):
                topic_row = conn.execute(
                    "SELECT COUNT(DISTINCT topic) AS count FROM topic_mentions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                topic_count = int(topic_row["count"] or 0)

            gaps: List[Dict[str, Any]] = []
            for index in range(len(daily_sessions) - 1):
                newer = self._parse_timestamp(daily_sessions[index]["date"])
                older = self._parse_timestamp(daily_sessions[index + 1]["date"])
                if newer is None or older is None:
                    continue
                gap_days = (newer - older).days
                if gap_days > 1:
                    gaps.append(
                        {
                            "from": daily_sessions[index + 1]["date"],
                            "to": daily_sessions[index]["date"],
                            "days": gap_days,
                        }
                    )

            active_days = len(daily_sessions)
            continuity_score = round((active_days / 30.0) * 100.0, 1)

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "period_days": 30,
                "active_days": active_days,
                "continuity_score_percent": continuity_score,
                "stored_contexts": context_count,
                "tracked_topics": topic_count,
                "session_gaps": gaps[:5] or None,
                "daily_breakdown": daily_sessions[:7],
                "assessment": self._assess_continuity(continuity_score, context_count, gaps),
            }
        except Exception as exc:
            logger.error(f"Continuity test failed: {exc}")
            return {"status": "error", "error": str(exc)}
        finally:
            conn.close()

    # =========================================================================
    # Phase 4
    # =========================================================================

    def response_quality_metrics(self, hours: int = 168) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(hours=hours)
        data_sources: List[str] = []

        try:
            feedback_stats: Dict[str, Any] = {
                "total_feedback": 0,
                "avg_rating": None,
                "positive_rate_percent": None,
            }
            if self._pg_table_exists("user_feedback"):
                with safe_aggregate_query("user_feedback") as cur:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) AS total_feedback,
                            AVG(rating) AS avg_rating,
                            AVG(CASE WHEN rating >= 4 THEN 100.0 ELSE 0.0 END) AS positive_rate
                        FROM user_feedback
                        WHERE created_at > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    feedback_stats = {
                        "total_feedback": int(row["total_feedback"] or 0),
                        "avg_rating": round(float(row["avg_rating"]), 2) if row["avg_rating"] is not None else None,
                        "positive_rate_percent": round(float(row["positive_rate"]), 1)
                        if row["positive_rate"] is not None
                        else None,
                    }
                data_sources.append("user_feedback")

            tool_success: Optional[float] = None
            if self._pg_table_exists("tool_audit"):
                with safe_aggregate_query("tool_audit") as cur:
                    cur.execute(
                        """
                        SELECT AVG(CASE WHEN success THEN 100.0 ELSE 0.0 END) AS success_rate
                        FROM tool_audit
                        WHERE created_at > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    tool_success = round(float(row["success_rate"]), 1) if row["success_rate"] is not None else None
                data_sources.append("tool_audit")

            response_consistency: Dict[str, Any] = {
                "avg_output_tokens": None,
                "stddev_output_tokens": None,
            }
            if self._pg_table_exists("message"):
                with safe_aggregate_query("message") as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(tokens_out) AS avg_tokens,
                            STDDEV(tokens_out) AS stddev_tokens
                        FROM message
                        WHERE created_at > %s
                          AND role = 'assistant'
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    response_consistency = {
                        "avg_output_tokens": round(float(row["avg_tokens"]), 0)
                        if row["avg_tokens"] is not None
                        else None,
                        "stddev_output_tokens": round(float(row["stddev_tokens"]), 0)
                        if row["stddev_tokens"] is not None
                        else None,
                    }
                data_sources.append("message")
            elif self._pg_table_exists("interaction_quality"):
                with safe_aggregate_query("interaction_quality") as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(response_length) AS avg_tokens,
                            STDDEV(response_length) AS stddev_tokens
                        FROM interaction_quality
                        WHERE timestamp > %s
                        """,
                        (cutoff,),
                    )
                    row = cur.fetchone()
                    response_consistency = {
                        "avg_output_tokens": round(float(row["avg_tokens"]), 0)
                        if row["avg_tokens"] is not None
                        else None,
                        "stddev_output_tokens": round(float(row["stddev_tokens"]), 0)
                        if row["stddev_tokens"] is not None
                        else None,
                    }
                data_sources.append("interaction_quality")

            quality_score = self._calculate_quality_score(feedback_stats, tool_success, response_consistency)
            status = "success" if data_sources else "no_data"
            response: Dict[str, Any] = {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "period_hours": hours,
                "feedback": feedback_stats,
                "tool_success_rate": tool_success,
                "response_consistency": response_consistency,
                "composite_quality_score": quality_score,
                "interpretation": self._interpret_quality(quality_score),
                "data_sources": data_sources,
            }
            if not data_sources:
                response["message"] = "No compatible quality metrics data sources are available."
            return response
        except Exception as exc:
            logger.error(f"Quality metrics failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def proactivity_score(self, user_id: Optional[int] = None, hours: int = 168) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(hours=hours)

        try:
            if not self._pg_table_exists("proactive_hints"):
                return {
                    "status": "no_data",
                    "timestamp": datetime.now().isoformat(),
                    "user_id": user_id,
                    "period_hours": hours,
                    "message": "proactive_hints table not found; this metric has no persisted source yet.",
                }

            params: List[Any] = [cutoff]
            user_filter = ""
            if user_id is not None:
                user_filter = " AND user_id = %s"
                params.append(user_id)

            with safe_aggregate_query("proactive_hints") as cur:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_hints,
                        COUNT(*) FILTER (WHERE was_shown = TRUE) AS shown,
                        COUNT(*) FILTER (WHERE was_accepted = TRUE) AS accepted,
                        COUNT(*) FILTER (WHERE was_accepted = FALSE) AS rejected,
                        AVG(confidence) AS avg_confidence
                    FROM proactive_hints
                    WHERE created_at > %s
                    {user_filter}
                    """,
                    params,
                )
                row = cur.fetchone()

                hint_stats = {
                    "total_hints": int(row["total_hints"] or 0),
                    "shown": int(row["shown"] or 0),
                    "accepted": int(row["accepted"] or 0),
                    "rejected": int(row["rejected"] or 0),
                    "acceptance_rate": round(
                        (float(row["accepted"] or 0) / float(row["shown"] or 1)) * 100.0,
                        1,
                    )
                    if row["shown"]
                    else None,
                    "avg_confidence": round(float(row["avg_confidence"]), 2)
                    if row["avg_confidence"] is not None
                    else None,
                }

            with safe_aggregate_query("proactive_hints") as cur:
                cur.execute(
                    f"""
                    SELECT hint_type, COUNT(*) AS count
                    FROM proactive_hints
                    WHERE created_at > %s
                    {user_filter}
                    GROUP BY hint_type
                    ORDER BY count DESC
                    """,
                    params,
                )
                type_distribution = {
                    row["hint_type"]: int(row["count"])
                    for row in cur.fetchall()
                }

            if hint_stats["total_hints"] > 0:
                acceptance = hint_stats["acceptance_rate"] or 0.0
                confidence = (hint_stats["avg_confidence"] or 0.5) * 100.0
                score = round((acceptance * 0.7) + (confidence * 0.3), 1)
            else:
                score = None

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "period_hours": hours,
                "hint_stats": hint_stats,
                "type_distribution": type_distribution,
                "proactivity_score": score,
                "assessment": self._assess_proactivity(score),
                "data_source": "proactive_hints",
            }
        except Exception as exc:
            logger.error(f"Proactivity score failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def quick_pulse(self) -> Dict[str, Any]:
        """
        Lightweight health check for real-time monitoring.
        Target: <50ms response time.

        Returns essential metrics only, uses caching where possible.
        """
        start = datetime.now()

        # Use cached health if available (saves ~100ms)
        cached_health = _get_cached("system_health")
        if cached_health:
            health_status = cached_health.get("status", "unknown")
            cpu_percent = cached_health.get("system", {}).get("cpu_percent", 0)
            memory_percent = cached_health.get("system", {}).get("memory_percent_used", 0)
        else:
            # Quick health check without full psutil scan
            health_status = "healthy"
            cpu_percent = 0
            memory_percent = 0
            if psutil:
                try:
                    cpu_percent = psutil.cpu_percent(interval=0)  # Non-blocking
                    memory_percent = psutil.virtual_memory().percent
                except Exception:
                    pass

        # Use cached tool count
        cached_tools = _get_cached("tool_count")
        if cached_tools:
            tool_count = cached_tools
        else:
            try:
                from ..tools import TOOL_REGISTRY
                tool_count = len(TOOL_REGISTRY)
                _set_cached("tool_count", tool_count)
            except Exception:
                tool_count = 0

        # Use cached quality score
        cached_quality = _get_cached("quality_score")
        quality_score = cached_quality if cached_quality else None

        elapsed_ms = (datetime.now() - start).total_seconds() * 1000

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "latency_ms": round(elapsed_ms, 1),
            "health": health_status,
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory_percent, 1),
            "tool_count": tool_count,
            "quality_score": quality_score,
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "cache_status": "hit" if cached_health else "miss",
        }

    def dashboard_snapshot(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "system_health": self.get_system_health(),
            "tool_registry": self.validate_tool_registry(),
            "response_metrics": self.get_response_metrics(hours=24),
            "memory_diagnostics": self.memory_diagnostics(),
            "context_window_analysis": self.context_window_analysis(user_id=None),
            "tool_benchmarks": self.benchmark_tool_calls(hours=24),
            "code_versions": {
                "main": self.compare_code_versions(module="main"),
                "tools": self.compare_code_versions(module="tools"),
            },
            "quality_metrics": self.response_quality_metrics(hours=168),
            "proactivity": self.proactivity_score(user_id=None, hours=168),
            "continuity_test_hint": "Use /self/continuity/{user_id} for user-specific continuity checks.",
        }


_service_instance: Optional[SelfValidationService] = None


def get_self_validation_service() -> SelfValidationService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SelfValidationService()
    return _service_instance
