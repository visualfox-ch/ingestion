"""
Jarvis Self-Validation Service.

Uses the data sources that actually exist in this codebase:
- PostgreSQL: message, tool_audit, user_feedback, interaction_quality
- SQLite state DB: conversation_contexts, topic_mentions, facts
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from prometheus_client import generate_latest

try:
    import psutil
except ImportError:  # pragma: no cover - depends on runtime image
    psutil = None

from ..db_safety import safe_aggregate_query, safe_list_query, safe_dict_aggregate_query, safe_dict_list_query
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

    def _action_queue_candidates(self) -> List[Path]:
        candidates: List[Path] = []
        env_path = os.environ.get("ACTION_QUEUE_PATH")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path("/brain/system/data/action_queue"),
                Path("/Volumes/BRAIN/system/data/action_queue"),
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

    def _resolve_action_queue_path(self) -> Optional[Path]:
        for candidate in self._action_queue_candidates():
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _read_action_queue_records(self) -> List[Dict[str, Any]]:
        base = self._resolve_action_queue_path()
        if base is None:
            return []

        records: List[Dict[str, Any]] = []
        for status_dir in ("approved", "rejected", "expired", "completed"):
            current = base / status_dir
            if not current.exists() or not current.is_dir():
                continue
            for file_path in current.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as handle:
                        records.append(json.load(handle))
                except Exception as exc:
                    logger.warning(f"Failed to parse action queue file {file_path}: {exc}")
        return records

    def _percentile(self, values: Sequence[float], q: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        idx = int((len(ordered) - 1) * q)
        idx = max(0, min(idx, len(ordered) - 1))
        return ordered[idx]

    def _agency_metrics_snapshot(self, hours: int) -> Dict[str, Optional[float]]:
        cutoff = datetime.now() - timedelta(hours=hours)

        latencies: List[float] = []
        for action in self._read_action_queue_records():
            created = self._parse_timestamp(action.get("created_at"))
            if created is None:
                continue
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            if created < cutoff:
                continue

            decision = (
                self._parse_timestamp(action.get("approved_at"))
                or self._parse_timestamp(action.get("rejected_at"))
                or self._parse_timestamp(action.get("expired_at"))
            )
            if decision is None:
                continue
            if decision.tzinfo is not None:
                decision = decision.replace(tzinfo=None)
            latency = (decision - created).total_seconds()
            if latency >= 0:
                latencies.append(latency)

        approval_p95 = self._percentile(latencies, 0.95)

        rollback_total = 0.0
        applied_total = 0.0
        try:
            metrics_text = generate_latest().decode("utf-8", errors="replace")
            for line in metrics_text.splitlines():
                if line.startswith("jarvis_autonomous_rollbacks_total"):
                    parts = line.rsplit(" ", 1)
                    if len(parts) == 2:
                        rollback_total += float(parts[1])
                elif line.startswith("jarvis_autonomous_actions_total"):
                    if 'status="completed"' in line or 'status="auto_approved"' in line or 'status="auto_approved_notify"' in line:
                        parts = line.rsplit(" ", 1)
                        if len(parts) == 2:
                            applied_total += float(parts[1])
        except Exception as exc:
            logger.warning(f"Failed to read autonomy metrics from prometheus registry: {exc}")

        rollback_rate = None
        if applied_total > 0:
            rollback_rate = rollback_total / applied_total

        return {
            "autonomy_rollback_rate": rollback_rate,
            "approval_p95_seconds": approval_p95,
        }

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

    def _get_or_create_state_conn(self) -> Optional[sqlite3.Connection]:
        """Like _get_state_conn but creates the DB file when JARVIS_STATE_DB env is set."""
        env_path = os.environ.get("JARVIS_STATE_DB")
        if env_path:
            p = Path(env_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            return conn
        return self._get_state_conn()

    def _sqlite_table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _ensure_proactive_snapshots_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER,
                acceptance_rate REAL,
                proactivity_score REAL
            )
            """
        )
        conn.commit()

    def _save_proactive_snapshot(
        self,
        acceptance_rate: Optional[float],
        score: Optional[float],
        user_id: Optional[int],
    ) -> None:
        if score is None and acceptance_rate is None:
            return
        try:
            conn = self._get_or_create_state_conn()
            if conn is None:
                return
            with conn:
                self._ensure_proactive_snapshots_table(conn)
                conn.execute(
                    "INSERT INTO proactive_snapshots (timestamp, user_id, acceptance_rate, proactivity_score) VALUES (?, ?, ?, ?)",
                    (datetime.now().isoformat(), user_id, acceptance_rate, score),
                )
        except Exception as exc:
            logger.warning(f"Failed to save proactive snapshot: {exc}")

    def _ensure_calibration_feedback_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                confidence REAL NOT NULL,
                actual_correct INTEGER NOT NULL,
                category TEXT
            )
            """
        )
        conn.commit()

    def save_calibration_feedback(
        self,
        confidence: float,
        actual_correct: bool,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a calibration data point (confidence vs actual outcome) to SQLite."""
        try:
            conn = self._get_or_create_state_conn()
            if conn is None:
                return {"status": "error", "error": "state_db unavailable"}
            with conn:
                self._ensure_calibration_feedback_table(conn)
                conn.execute(
                    "INSERT INTO calibration_feedback (timestamp, confidence, actual_correct, category) VALUES (?, ?, ?, ?)",
                    (datetime.now().isoformat(), float(confidence), int(actual_correct), category),
                )
            return {"status": "success", "timestamp": datetime.now().isoformat()}
        except Exception as exc:
            logger.error(f"Failed to save calibration feedback: {exc}")
            return {"status": "error", "error": str(exc)}

    def _pg_table_exists(self, table_name: str) -> bool:
        try:
            with safe_dict_list_query("pg_catalog", timeout=5) as cur:
                cur.execute("SELECT to_regclass(%s) AS regclass", (f"public.{table_name}",))
                row = cur.fetchone()
                if not row:
                    return False
                # Handle both dict-like (RealDictRow/DictCursor) and plain tuple rows
                try:
                    val = row["regclass"]
                except (TypeError, KeyError):
                    val = row[0]
                return bool(val)
        except Exception as exc:
            logger.warning(f"Failed to inspect PostgreSQL table {table_name}: {exc}")
            return False

    def _most_recent_context_user_id(self) -> Optional[int]:
        """Return the user_id with the most recent activity in conversation_contexts, or None."""
        conn = self._get_state_conn()
        if conn is None:
            return None
        try:
            if not self._sqlite_table_exists(conn, "conversation_contexts"):
                return None
            row = conn.execute(
                "SELECT user_id FROM conversation_contexts "
                "WHERE user_id IS NOT NULL "
                "ORDER BY COALESCE(end_time, created_at) DESC LIMIT 1"
            ).fetchone()
            if row:
                return int(row["user_id"])
        except Exception as exc:
            logger.warning(f"_most_recent_context_user_id failed: {exc}")
        finally:
            conn.close()
        return None

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

    def _combine_statuses(self, statuses: Sequence[str]) -> str:
        normalized = [status for status in statuses if status]
        if not normalized:
            return "no_data"
        if any(status == "fail" for status in normalized):
            return "fail"
        if any(status == "warn" for status in normalized):
            return "warn"
        if any(status == "no_data" for status in normalized):
            return "warn"
        return "pass"

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
                with safe_dict_aggregate_query("message") as cur:
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

                with safe_dict_aggregate_query("message") as cur:
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
                with safe_dict_aggregate_query("jarvis_interactions") as cur:
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
                with safe_dict_aggregate_query("interaction_quality") as cur:
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
                with safe_dict_aggregate_query("tool_audit") as cur:
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

                with safe_dict_aggregate_query("message") as cur:
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
                with safe_dict_aggregate_query("jarvis_interactions") as cur:
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

            with safe_dict_aggregate_query("tool_audit") as cur:
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

            # No activity in the analysis window should be treated as no_data,
            # not as a hard continuity failure.
            if not daily_sessions:
                return {
                    "status": "no_data",
                    "timestamp": datetime.now().isoformat(),
                    "user_id": user_id,
                    "period_days": 30,
                    "active_days": 0,
                    "continuity_score_percent": None,
                    "stored_contexts": context_count,
                    "tracked_topics": topic_count,
                    "session_gaps": None,
                    "daily_breakdown": [],
                    "message": "No conversation activity found in the last 30 days.",
                }

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
                with safe_dict_aggregate_query("user_feedback") as cur:
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
                with safe_dict_aggregate_query("tool_audit") as cur:
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
                with safe_dict_aggregate_query("message") as cur:
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
                with safe_dict_aggregate_query("interaction_quality") as cur:
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
        feedback_grace_cutoff = datetime.now() - timedelta(hours=24)
        min_completed_outcomes = 3

        try:
            if not self._pg_table_exists("proactive_hints"):
                try:
                    from ..proactive_service import get_proactive_stats

                    stats = get_proactive_stats()
                    totals = stats.get("totals") or {}

                    accepted = int(totals.get("accepted") or 0)
                    ignored = int(totals.get("ignored") or 0)
                    explicitly_rejected = int(totals.get("rejected") or 0)
                    expired_count = int(totals.get("expired") or 0)
                    pending = int(stats.get("pending_count") or 0)
                    shown = int(totals.get("interventions") or 0)
                    # completed_outcomes = only user-decided signals (accepted or explicit rejection)
                    # system-expired hints do not count as user feedback
                    completed_outcomes = accepted + explicitly_rejected

                    acceptance_rate = (
                        round((accepted / completed_outcomes) * 100.0, 1)
                        if completed_outcomes > 0
                        else None
                    )

                    if completed_outcomes > 0:
                        confidence = 50.0
                        score = round((acceptance_rate * 0.7) + (confidence * 0.3), 1)
                    else:
                        score = None

                    if shown == 0:
                        assessment = "No proactive activity to assess."
                    elif completed_outcomes == 0:
                        assessment = "Awaiting feedback; hints were shown but no completed outcomes yet."
                    elif completed_outcomes < min_completed_outcomes:
                        assessment = (
                            f"Early signal only ({completed_outcomes} completed outcomes); "
                            "collect more feedback before hard conclusions."
                        )
                    else:
                        assessment = self._assess_proactivity(score)

                    result_proactive = {
                        "status": "success",
                        "timestamp": datetime.now().isoformat(),
                        "user_id": user_id,
                        "period_hours": hours,
                        "hint_stats": {
                            "total_hints": shown,
                            "shown": shown,
                            "accepted": accepted,
                            "explicitly_rejected": explicitly_rejected,
                            "rejected": explicitly_rejected,
                            "expired": expired_count,
                            "ignored_or_expired": ignored + expired_count,
                            "no_feedback_yet": pending,
                            "completed_outcomes": completed_outcomes,
                            "acceptance_rate": acceptance_rate,
                            "avg_confidence": None,
                        },
                        "type_distribution": {
                            key: int((value or {}).get("interventions") or 0)
                            for key, value in (stats.get("by_type") or {}).items()
                        },
                        "proactivity_score": score,
                        "assessment": assessment,
                        "sample_quality": {
                            "completed_outcomes": completed_outcomes,
                            "min_completed_outcomes_for_judgement": min_completed_outcomes,
                            "is_small_sample": shown > 0 and completed_outcomes < min_completed_outcomes,
                        },
                        "data_source": "proactive_service_memory",
                    }
                    self._save_proactive_snapshot(acceptance_rate, score, user_id)
                    return result_proactive
                except Exception as exc:
                    logger.warning(f"Proactive fallback metrics unavailable: {exc}")
                    return {
                        "status": "no_data",
                        "timestamp": datetime.now().isoformat(),
                        "user_id": user_id,
                        "period_hours": hours,
                        "message": "proactive_hints table not found and in-memory fallback unavailable.",
                    }

            params: List[Any] = [cutoff]
            user_filter = ""
            if user_id is not None:
                # proactive_hints.user_id is character varying
                user_filter = " AND user_id = %s"
                params.append(str(user_id))

            with safe_dict_aggregate_query("proactive_hints") as cur:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_hints,
                        COUNT(*) FILTER (WHERE was_shown = TRUE) AS shown,
                        COUNT(*) FILTER (WHERE was_accepted = TRUE) AS accepted,
                        COUNT(*) FILTER (
                            WHERE was_accepted = FALSE
                              AND NULLIF(TRIM(COALESCE(user_feedback, '')), '') IS NOT NULL
                        ) AS explicitly_rejected,
                        COUNT(*) FILTER (
                            WHERE was_accepted = FALSE
                              AND feedback_at IS NOT NULL
                              AND NULLIF(TRIM(COALESCE(user_feedback, '')), '') IS NULL
                        ) AS expired,
                        COUNT(*) FILTER (
                            WHERE was_accepted = FALSE
                              AND feedback_at IS NULL
                              AND NULLIF(TRIM(COALESCE(user_feedback, '')), '') IS NULL
                        ) AS ambiguous_negative,
                        COUNT(*) FILTER (
                            WHERE was_shown = TRUE
                              AND was_accepted IS NULL
                              AND created_at >= %s
                        ) AS no_feedback_yet,
                        COUNT(*) FILTER (
                            WHERE was_shown = TRUE
                              AND was_accepted IS NULL
                              AND created_at < %s
                        ) AS ignored_or_expired,
                        AVG(confidence) AS avg_confidence
                    FROM proactive_hints
                    WHERE created_at > %s
                    {user_filter}
                    """,
                    [feedback_grace_cutoff, feedback_grace_cutoff, *params],
                )
                row = cur.fetchone()

                completed_outcomes = int(row["accepted"] or 0) + int(row["explicitly_rejected"] or 0)
                acceptance_rate = (
                    round((float(row["accepted"] or 0) / float(completed_outcomes)) * 100.0, 1)
                    if completed_outcomes > 0
                    else None
                )

                _expired_by_system = int(row["expired"] or 0)
                hint_stats = {
                    "total_hints": int(row["total_hints"] or 0),
                    "shown": int(row["shown"] or 0),
                    "accepted": int(row["accepted"] or 0),
                    "explicitly_rejected": int(row["explicitly_rejected"] or 0),
                    "rejected": int(row["explicitly_rejected"] or 0),
                    # expired: system-closed hints without explicit user signal (not counted in completed_outcomes)
                    "expired": _expired_by_system,
                    "ambiguous_negative": int(row["ambiguous_negative"] or 0),
                    "no_feedback_yet": int(row["no_feedback_yet"] or 0),
                    "ignored_or_expired": int(row["ignored_or_expired"] or 0) + _expired_by_system,
                    "completed_outcomes": completed_outcomes,
                    "acceptance_rate": acceptance_rate,
                    "avg_confidence": round(float(row["avg_confidence"]), 2)
                    if row["avg_confidence"] is not None
                    else None,
                }

            with safe_dict_aggregate_query("proactive_hints") as cur:
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

            if hint_stats["completed_outcomes"] > 0:
                acceptance = hint_stats["acceptance_rate"] or 0.0
                confidence = (hint_stats["avg_confidence"] or 0.5) * 100.0
                score = round((acceptance * 0.7) + (confidence * 0.3), 1)
            else:
                score = None

            shown = int(hint_stats.get("shown") or 0)
            completed_outcomes = int(hint_stats.get("completed_outcomes") or 0)
            if shown == 0:
                assessment = "No proactive activity to assess."
            elif completed_outcomes == 0:
                assessment = "Awaiting feedback; hints were shown but no completed outcomes yet."
            elif completed_outcomes < min_completed_outcomes:
                assessment = (
                    f"Early signal only ({completed_outcomes} completed outcomes); "
                    "collect more feedback before hard conclusions."
                )
            else:
                assessment = self._assess_proactivity(score)

            self._save_proactive_snapshot(hint_stats.get("acceptance_rate"), score, user_id)
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "period_hours": hours,
                "hint_stats": hint_stats,
                "type_distribution": type_distribution,
                "proactivity_score": score,
                "assessment": assessment,
                "sample_quality": {
                    "completed_outcomes": completed_outcomes,
                    "min_completed_outcomes_for_judgement": min_completed_outcomes,
                    "is_small_sample": shown > 0 and completed_outcomes < min_completed_outcomes,
                },
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

    def reality_check_snapshot(
        self,
        hours: int = 168,
        days: int = 7,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return deploy-time KPI snapshot for agency/memory/proactive/calibration."""
        try:
            continuity_score: Optional[float] = None
            continuity_status = "no_data"
            continuity_payload: Dict[str, Any] = {
                "status": "no_data",
                "value": None,
                "thresholds": {"pass": ">=60", "warn": ">=40", "fail": "<40"},
            }

            # Auto-detect most recent user if none given (fixes RC1 no_data when user_id=None)
            effective_user_id = user_id if user_id is not None else self._most_recent_context_user_id()

            if effective_user_id is not None:
                continuity = self.conversation_continuity_test(effective_user_id)
                if continuity.get("status") == "success":
                    raw_value = continuity.get("continuity_score_percent")
                    continuity_score = float(raw_value) if raw_value is not None else None
                    if continuity_score is not None:
                        if continuity_score >= 60:
                            continuity_status = "pass"
                        elif continuity_score >= 40:
                            continuity_status = "warn"
                        else:
                            continuity_status = "fail"
                    continuity_payload = {
                        "status": continuity_status,
                        "value": continuity_score,
                        "thresholds": {"pass": ">=60", "warn": ">=40", "fail": "<40"},
                    }

            diagnostics = self.memory_diagnostics()
            memory_health_value = 1.0 if diagnostics.get("status") == "success" else 0.0
            memory_health_status = "pass" if memory_health_value == 1.0 else "fail"

            proactive = self.proactivity_score(user_id=user_id, hours=hours)
            proactive_acceptance: Optional[float] = None
            proactive_score_value: Optional[float] = None
            proactive_acceptance_status = "no_data"
            proactive_score_status = "no_data"
            proactive_shown = 0
            proactive_completed_outcomes = 0
            proactive_is_small_sample = False
            if proactive.get("status") == "success":
                hint_stats = proactive.get("hint_stats") or {}
                raw_acceptance = hint_stats.get("acceptance_rate")
                raw_score = proactive.get("proactivity_score")
                proactive_acceptance = float(raw_acceptance) if raw_acceptance is not None else None
                proactive_score_value = float(raw_score) if raw_score is not None else None
                proactive_shown = int(hint_stats.get("shown") or 0)

                sample_quality = proactive.get("sample_quality") or {}
                proactive_completed_outcomes = int(sample_quality.get("completed_outcomes") or 0)
                proactive_is_small_sample = bool(sample_quality.get("is_small_sample"))

                if proactive_shown == 0:
                    proactive_acceptance_status = "no_data"
                    proactive_score_status = "no_data"
                elif proactive_is_small_sample:
                    # Avoid hard fail on thin samples; this is a quality warning, not no_data.
                    proactive_acceptance_status = "warn"
                    proactive_score_status = "warn"
                else:
                    if proactive_acceptance is not None:
                        if proactive_acceptance >= 35:
                            proactive_acceptance_status = "pass"
                        elif proactive_acceptance >= 20:
                            proactive_acceptance_status = "warn"
                        else:
                            proactive_acceptance_status = "fail"

                    if proactive_score_value is not None:
                        if proactive_score_value >= 55:
                            proactive_score_status = "pass"
                        elif proactive_score_value >= 35:
                            proactive_score_status = "warn"
                        else:
                            proactive_score_status = "fail"

            if proactive.get("status") != "success" and proactive_acceptance is None and proactive_score_value is None:
                # SQLite fallback: read latest persisted proactive snapshot
                try:
                    _conn = self._get_state_conn()
                    if _conn is not None and self._sqlite_table_exists(_conn, "proactive_snapshots"):
                        _cutoff = (datetime.now() - timedelta(days=7)).isoformat()
                        _row = _conn.execute(
                            "SELECT acceptance_rate, proactivity_score FROM proactive_snapshots "
                            "WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
                            (_cutoff,),
                        ).fetchone()
                        if _row:
                            proactive_acceptance = _row["acceptance_rate"]
                            proactive_score_value = _row["proactivity_score"]
                            if proactive_acceptance is not None:
                                if proactive_acceptance >= 35:
                                    proactive_acceptance_status = "pass"
                                elif proactive_acceptance >= 20:
                                    proactive_acceptance_status = "warn"
                                else:
                                    proactive_acceptance_status = "fail"
                            if proactive_score_value is not None:
                                if proactive_score_value >= 55:
                                    proactive_score_status = "pass"
                                elif proactive_score_value >= 35:
                                    proactive_score_status = "warn"
                                else:
                                    proactive_score_status = "fail"
                except Exception as _exc:
                    logger.warning(f"Proactive SQLite fallback failed: {_exc}")

            agency_snapshot = self._agency_metrics_snapshot(hours=hours)
            rollback_rate = agency_snapshot.get("autonomy_rollback_rate")
            rollback_status = "no_data"
            if rollback_rate is not None:
                if rollback_rate <= 0.05:
                    rollback_status = "pass"
                elif rollback_rate <= 0.10:
                    rollback_status = "warn"
                else:
                    rollback_status = "fail"

            approval_p95 = agency_snapshot.get("approval_p95_seconds")
            approval_status = "no_data"
            if approval_p95 is not None:
                if approval_p95 <= 3600:
                    approval_status = "pass"
                elif approval_p95 <= 14400:
                    approval_status = "warn"
                else:
                    approval_status = "fail"

            from ..uncertainty_quantifier import get_uncertainty_quantifier

            quantifier = get_uncertainty_quantifier()
            calibration_report = quantifier.get_calibration_report()
            ece_value = calibration_report.get("overall_ece")
            if ece_value is not None:
                ece_value = float(ece_value)

            calibration_source = "quantifier_history"
            calibration_samples = 0
            min_calibration_samples = 20

            seven_day_cutoff = datetime.now() - timedelta(days=days)
            for entry in quantifier.history:
                ts = self._parse_timestamp(entry.get("timestamp"))
                if ts is None:
                    continue
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                if ts >= seven_day_cutoff:
                    calibration_samples += 1

            if ece_value is None:
                # SQLite calibration_feedback fallback: compute ECE from stored observations
                try:
                    _conn = self._get_state_conn()
                    if _conn is not None and self._sqlite_table_exists(_conn, "calibration_feedback"):
                        _cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                        _fb_rows = _conn.execute(
                            "SELECT confidence, actual_correct FROM calibration_feedback WHERE timestamp >= ?",
                            (_cutoff,),
                        ).fetchall()
                        if _fb_rows:
                            _n = len(_fb_rows)
                            calibration_source = "sqlite_calibration_feedback"
                            calibration_samples = _n
                            if _n >= min_calibration_samples:
                                _buckets: Dict[int, Dict[str, float]] = {}
                                for _r in _fb_rows:
                                    _b = min(int(float(_r["confidence"]) * 10), 9)
                                    if _b not in _buckets:
                                        _buckets[_b] = {"count": 0.0, "correct": 0.0}
                                    _buckets[_b]["count"] += 1
                                    _buckets[_b]["correct"] += int(_r["actual_correct"])
                                _ece = 0.0
                                for _b_idx, _bdata in _buckets.items():
                                    _mid = (_b_idx + 0.5) / 10.0
                                    _frac = _bdata["correct"] / _bdata["count"]
                                    _ece += (_bdata["count"] / _n) * abs(_frac - _mid)
                                ece_value = round(_ece, 4)
                except Exception as _exc:
                    logger.warning(f"Calibration SQLite fallback failed: {_exc}")

            calibration_ece_status = "no_data"
            if ece_value is not None:
                if ece_value <= 0.15:
                    calibration_ece_status = "pass"
                elif ece_value <= 0.20:
                    calibration_ece_status = "warn"
                else:
                    calibration_ece_status = "fail"

            total_assessments = 0
            try:
                if self._pg_table_exists("message"):
                    with safe_dict_aggregate_query("message") as cur:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS total
                            FROM message
                            WHERE created_at > %s
                              AND role = 'assistant'
                            """,
                            (seven_day_cutoff,),
                        )
                        row = cur.fetchone()
                        total_assessments = int(row["total"] or 0)
            except Exception as exc:
                logger.warning(f"Failed to calculate confidence feedback denominator: {exc}")

            coverage_value = None
            coverage_status = "no_data"
            if total_assessments > 0:
                coverage_value = round((calibration_samples / total_assessments) * 100.0, 1)
                if coverage_value >= 30:
                    coverage_status = "pass"
                elif coverage_value >= 15:
                    coverage_status = "warn"
                else:
                    coverage_status = "fail"

            agency_metrics = {
                "autonomy_rollback_rate": {
                    "status": rollback_status,
                    "value": rollback_rate,
                    "thresholds": {"pass": "<=0.05", "warn": "<=0.10", "fail": ">0.10"},
                },
                "approval_p95_seconds": {
                    "status": approval_status,
                    "value": approval_p95,
                    "thresholds": {"pass": "<=3600", "warn": "<=14400", "fail": ">14400"},
                },
            }

            memory_metrics = {
                "continuity_score_percent": continuity_payload,
                "memory_health": {
                    "status": memory_health_status,
                    "value": int(memory_health_value),
                    "thresholds": {"pass": "1", "fail": "0"},
                },
            }

            proactive_metrics = {
                "proactivity_acceptance_rate": {
                    "status": proactive_acceptance_status,
                    "value": proactive_acceptance,
                    "thresholds": {"pass": ">=35", "warn": ">=20", "fail": "<20"},
                },
                "proactivity_score": {
                    "status": proactive_score_status,
                    "value": proactive_score_value,
                    "thresholds": {"pass": ">=55", "warn": ">=35", "fail": "<35"},
                },
            }

            calibration_metrics = {
                "calibration_ece": {
                    "status": calibration_ece_status,
                    "value": ece_value,
                    "thresholds": {"pass": "<=0.15", "warn": "<=0.20", "fail": ">0.20"},
                },
                "confidence_feedback_coverage": {
                    "status": coverage_status,
                    "value": coverage_value,
                    "thresholds": {"pass": ">=30", "warn": ">=15", "fail": "<15"},
                },
                "calibration_samples": {
                    "status": "pass" if calibration_samples >= min_calibration_samples else ("warn" if calibration_samples > 0 else "no_data"),
                    "value": calibration_samples,
                    "source": calibration_source,
                    "thresholds": {
                        "pass": f">={min_calibration_samples}",
                        "warn": f"1..{min_calibration_samples - 1}",
                        "fail": "n/a",
                    },
                },
            }

            dimensions = {
                "agency": {
                    "status": self._combine_statuses([metric["status"] for metric in agency_metrics.values()]),
                    "metrics": agency_metrics,
                },
                "memory": {
                    "status": self._combine_statuses([metric["status"] for metric in memory_metrics.values()]),
                    "metrics": memory_metrics,
                },
                "proactive": {
                    "status": self._combine_statuses([metric["status"] for metric in proactive_metrics.values()]),
                    "metrics": proactive_metrics,
                },
                "calibration": {
                    "status": self._combine_statuses([metric["status"] for metric in calibration_metrics.values()]),
                    "metrics": calibration_metrics,
                },
            }

            overall = self._combine_statuses([payload["status"] for payload in dimensions.values()])

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "period_hours": hours,
                "period_days": days,
                "user_id": user_id,
                "overall": overall,
                "dimensions": dimensions,
            }
        except Exception as exc:
            logger.error(f"Reality check snapshot failed: {exc}")
            return {
                "status": "error",
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
                "overall": "fail",
                "dimensions": {
                    "agency": {"status": "fail", "metrics": {}},
                    "memory": {"status": "fail", "metrics": {}},
                    "proactive": {"status": "fail", "metrics": {}},
                    "calibration": {"status": "fail", "metrics": {}},
                },
            }


_service_instance: Optional[SelfValidationService] = None


def get_self_validation_service() -> SelfValidationService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SelfValidationService()
    return _service_instance
