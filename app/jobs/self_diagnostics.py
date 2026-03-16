"""
Scheduled Self-Diagnostics Job
Phase 19: Runs every 6 hours to check system health, tools, memory, and pipelines.

Features:
1. System health check (all 11 services)
2. Tool performance test (critical tools)
3. Memory integrity scan (SQLite, Qdrant consistency)
4. Pipeline status check (email, calendar, knowledge)
5. Telegram alert on critical issues
"""

import time
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.self_diagnostics")

# Configuration
CRITICAL_TOOLS = ["search_knowledge", "recall_facts", "search_emails", "get_calendar_events"]
TOOL_TIMEOUT_MS = 5000  # 5 second timeout for tool tests
LATENCY_WARNING_MS = 500  # Warn if tool takes > 500ms
# Use 127.0.0.1 instead of localhost (some systems resolve localhost to IPv6)
HEALTH_ENDPOINT = "http://127.0.0.1:18000/health"


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check."""
    category: str
    status: str  # healthy, warning, critical
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class SelfDiagnosticsRunner:
    """Runs comprehensive self-diagnostics."""

    def __init__(self):
        self.results: List[DiagnosticResult] = []
        self.start_time: Optional[datetime] = None

    def run_all(self) -> Dict[str, Any]:
        """Run all diagnostic checks and return summary."""
        self.start_time = datetime.utcnow()
        self.results = []

        # 1. System Health Check
        self._check_system_health()

        # 2. Tool Performance Test
        self._check_tool_performance()

        # 3. Memory Integrity Scan
        self._check_memory_integrity()

        # 4. Pipeline Status Check
        self._check_pipeline_status()

        # Build summary
        summary = self._build_summary()

        # Log results
        log_with_context(logger, "info", "Self-diagnostics completed",
                        duration_ms=(datetime.utcnow() - self.start_time).total_seconds() * 1000,
                        status=summary["overall_status"],
                        critical_count=summary["critical_count"],
                        warning_count=summary["warning_count"])

        return summary

    def _add_result(self, category: str, status: str, message: str, details: Dict = None):
        """Add a diagnostic result."""
        self.results.append(DiagnosticResult(
            category=category,
            status=status,
            message=message,
            details=details or {}
        ))

    def _check_system_health(self):
        """Check health of all system components."""
        try:
            # Use internal health check function instead of HTTP
            from ..routers.health_router import health_check

            data = health_check()
            checks = data.get("checks", {})

            unhealthy = []
            warnings = []

            for name, check in checks.items():
                check_status = check.get("status", "unknown")
                if check_status == "unhealthy":
                    unhealthy.append(name)
                elif check_status == "warning":
                    warnings.append(name)

            if unhealthy:
                self._add_result("system_health", "critical",
                                f"Unhealthy services: {', '.join(unhealthy)}",
                                {"unhealthy": unhealthy, "warnings": warnings})
            elif warnings:
                self._add_result("system_health", "warning",
                                f"Services with warnings: {', '.join(warnings)}",
                                {"warnings": warnings})
            else:
                self._add_result("system_health", "healthy",
                                f"All {len(checks)} services healthy",
                                {"service_count": len(checks)})
        except Exception as e:
            self._add_result("system_health", "critical",
                            f"Health check failed: {str(e)[:100]}",
                            {"error": str(e)})

    def _check_tool_performance(self):
        """Test critical tools for performance regression."""
        try:
            from ..tools import TOOL_REGISTRY

            slow_tools = []
            failed_tools = []
            tool_times = {}

            for tool_name in CRITICAL_TOOLS:
                if tool_name not in TOOL_REGISTRY:
                    continue

                # Test with minimal input
                start = time.time()
                try:
                    # TOOL_REGISTRY values are functions directly
                    tool_func = TOOL_REGISTRY[tool_name]

                    # Use test query with minimal params
                    if "search" in tool_name or "recall" in tool_name:
                        result = tool_func(query="test diagnostic", limit=1)
                    elif "calendar" in tool_name:
                        result = tool_func(days=1)
                    else:
                        result = {"skipped": True}

                    latency_ms = (time.time() - start) * 1000
                    tool_times[tool_name] = latency_ms

                    if latency_ms > TOOL_TIMEOUT_MS:
                        failed_tools.append(f"{tool_name} (timeout)")
                    elif latency_ms > LATENCY_WARNING_MS:
                        slow_tools.append(f"{tool_name} ({int(latency_ms)}ms)")

                except Exception as e:
                    latency_ms = (time.time() - start) * 1000
                    failed_tools.append(f"{tool_name} (error: {str(e)[:50]})")
                    tool_times[tool_name] = latency_ms if latency_ms < TOOL_TIMEOUT_MS else -1

            if failed_tools:
                self._add_result("tool_performance", "critical",
                                f"Tools failed: {', '.join(failed_tools)}",
                                {"failed": failed_tools, "times": tool_times})
            elif slow_tools:
                self._add_result("tool_performance", "warning",
                                f"Slow tools: {', '.join(slow_tools)}",
                                {"slow": slow_tools, "times": tool_times})
            else:
                valid_times = [t for t in tool_times.values() if t > 0]
                avg_latency = sum(valid_times) / max(len(valid_times), 1)
                self._add_result("tool_performance", "healthy",
                                f"All tools OK (avg {int(avg_latency)}ms)",
                                {"times": tool_times, "avg_latency_ms": avg_latency})

        except Exception as e:
            self._add_result("tool_performance", "warning",
                            f"Tool test skipped: {str(e)[:100]}",
                            {"error": str(e)})

    def _check_memory_integrity(self):
        """Check memory/database integrity."""
        issues = []
        details = {}

        # 1. SQLite integrity check
        try:
            db_path = "/brain/system/state/jarvis_state.db"
            conn = sqlite3.connect(db_path, timeout=10)
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            conn.close()

            if result != "ok":
                issues.append(f"SQLite integrity: {result}")
            details["sqlite_integrity"] = result
        except Exception as e:
            issues.append(f"SQLite check failed: {str(e)[:50]}")
            details["sqlite_error"] = str(e)

        # 2. Check for orphaned session data
        try:
            conn = sqlite3.connect(db_path, timeout=10)

            # Check message count
            cursor = conn.execute("SELECT COUNT(*) FROM session_messages")
            msg_count = cursor.fetchone()[0]
            details["session_messages"] = msg_count

            # Check context count
            cursor = conn.execute("SELECT COUNT(*) FROM conversation_contexts")
            ctx_count = cursor.fetchone()[0]
            details["conversation_contexts"] = ctx_count

            # Check for very old uncompleted actions
            cursor = conn.execute("""
                SELECT COUNT(*) FROM pending_actions
                WHERE completed = 0 AND created_at < datetime('now', '-30 days')
            """)
            old_actions = cursor.fetchone()[0]
            if old_actions > 10:
                issues.append(f"{old_actions} stale pending_actions (>30 days)")
            details["stale_pending_actions"] = old_actions

            conn.close()
        except Exception as e:
            details["session_check_error"] = str(e)

        # 3. Check Qdrant connectivity
        try:
            qdrant_url = "http://qdrant:6333/collections"
            resp = requests.get(qdrant_url, timeout=5)
            if resp.status_code == 200:
                collections = resp.json().get("result", {}).get("collections", [])
                details["qdrant_collections"] = len(collections)
            else:
                issues.append(f"Qdrant returned {resp.status_code}")
        except Exception as e:
            issues.append(f"Qdrant unreachable: {str(e)[:50]}")
            details["qdrant_error"] = str(e)

        if issues:
            self._add_result("memory_integrity", "warning",
                            f"Issues: {'; '.join(issues)}",
                            details)
        else:
            self._add_result("memory_integrity", "healthy",
                            "All memory systems OK",
                            details)

    def _check_pipeline_status(self):
        """Check status of data pipelines (email, calendar, etc.)."""
        pipelines = {}
        issues = []

        # Check n8n workflows via API
        try:
            from ..n8n_client import get_workflow_status

            # Key workflows to check
            workflow_names = ["gmail_sync", "calendar_sync", "daily_briefing"]

            for wf_name in workflow_names:
                try:
                    status = get_workflow_status(wf_name)
                    pipelines[wf_name] = status
                    if status.get("status") == "error":
                        issues.append(f"{wf_name}: {status.get('error', 'unknown error')}")
                except Exception:
                    pipelines[wf_name] = {"status": "unknown"}
        except ImportError:
            pipelines["n8n"] = {"status": "module_not_available"}
        except Exception as e:
            pipelines["n8n_check"] = {"error": str(e)}

        # Check last successful email sync (from PostgreSQL)
        try:
            from ..postgres_state import get_cursor
            with get_cursor() as cur:
                cur.execute("""
                    SELECT MAX(created_at) as last_email
                    FROM message
                    WHERE source = 'gmail'
                """)
                row = cur.fetchone()
                if row and row[0]:
                    last_email = row[0]
                    pipelines["email_last_sync"] = str(last_email)

                    # Warn if no email in 24h
                    if isinstance(last_email, datetime):
                        if datetime.utcnow() - last_email > timedelta(hours=24):
                            issues.append("No email sync in 24h")
                else:
                    pipelines["email_last_sync"] = "never"
                    issues.append("No emails synced yet")
        except Exception as e:
            pipelines["email_check_error"] = str(e)

        if issues:
            self._add_result("pipeline_status", "warning",
                            f"Pipeline issues: {'; '.join(issues)}",
                            pipelines)
        else:
            self._add_result("pipeline_status", "healthy",
                            "All pipelines operational",
                            pipelines)

    def _build_summary(self) -> Dict[str, Any]:
        """Build summary from all results."""
        critical_count = sum(1 for r in self.results if r.status == "critical")
        warning_count = sum(1 for r in self.results if r.status == "warning")

        if critical_count > 0:
            overall_status = "critical"
        elif warning_count > 0:
            overall_status = "warning"
        else:
            overall_status = "healthy"

        return {
            "overall_status": overall_status,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "healthy_count": sum(1 for r in self.results if r.status == "healthy"),
            "total_checks": len(self.results),
            "results": [
                {
                    "category": r.category,
                    "status": r.status,
                    "message": r.message,
                    "details": r.details
                }
                for r in self.results
            ],
            "duration_ms": (datetime.utcnow() - self.start_time).total_seconds() * 1000,
            "timestamp": datetime.utcnow().isoformat()
        }


def run_self_diagnostics() -> Dict[str, Any]:
    """Run self-diagnostics and send alerts if needed."""
    log_with_context(logger, "info", "Starting scheduled self-diagnostics")

    runner = SelfDiagnosticsRunner()
    summary = runner.run_all()

    # Send Telegram alert if critical or multiple warnings
    if summary["overall_status"] == "critical" or summary["warning_count"] >= 2:
        _send_diagnostic_alert(summary)

    return summary


def _send_diagnostic_alert(summary: Dict[str, Any]):
    """Send diagnostic alert via Telegram."""
    try:
        from ..telegram_bot import TELEGRAM_TOKEN
        import os

        if not TELEGRAM_TOKEN:
            log_with_context(logger, "warning", "Cannot send alert: no Telegram token")
            return

        # Get allowed users
        allowed_users = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
        if not allowed_users:
            return

        user_ids = [int(u.strip()) for u in allowed_users.split(",") if u.strip()]

        # Build alert message
        status_emoji = "🔴" if summary["overall_status"] == "critical" else "🟡"

        message = f"{status_emoji} **Jarvis Self-Diagnostics Alert**\n\n"
        message += f"Status: {summary['overall_status'].upper()}\n"
        message += f"Critical: {summary['critical_count']} | Warnings: {summary['warning_count']}\n\n"

        # Add critical/warning details
        for result in summary["results"]:
            if result["status"] in ("critical", "warning"):
                emoji = "🔴" if result["status"] == "critical" else "🟡"
                message += f"{emoji} **{result['category']}**: {result['message']}\n"

        message += f"\n_Checked at {summary['timestamp'][:16]}_"

        # Send to all users
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        for user_id in user_ids:
            try:
                requests.post(url, json={
                    "chat_id": user_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }, timeout=10)
            except Exception as e:
                log_with_context(logger, "error", "Failed to send alert",
                               user_id=user_id, error=str(e))

        log_with_context(logger, "info", "Diagnostic alert sent",
                        status=summary["overall_status"],
                        recipients=len(user_ids))

    except Exception as e:
        log_with_context(logger, "error", "Failed to send diagnostic alert",
                        error=str(e))


# Singleton for manual access
_diagnostics_runner: Optional[SelfDiagnosticsRunner] = None


def get_last_diagnostics() -> Optional[Dict[str, Any]]:
    """Get results from last diagnostic run."""
    global _diagnostics_runner
    if _diagnostics_runner and _diagnostics_runner.results:
        return _diagnostics_runner._build_summary()
    return None
