"""
Scheduled Maintenance Jobs

Phase: Tool Activation Strategy
Jobs for tools that should run automatically but were previously forgotten.
"""
import logging
from datetime import datetime
from typing import Dict, Any

from app.observability import get_logger, log_with_context

logger = get_logger("jarvis.jobs.maintenance")


def run_memory_decay_job() -> Dict[str, Any]:
    """
    Daily job: Decay memory recency scores.

    Ensures old memories naturally fade unless reinforced.
    Schedule: Daily at 03:00
    """
    log_with_context(logger, "info", "Starting memory decay job")

    try:
        from app.tool_modules.importance_scoring_tools import decay_memory_recency

        result = decay_memory_recency()

        if result.get("success"):
            log_with_context(
                logger, "info",
                "Memory decay completed",
                updated=result.get("updated_count", 0)
            )
        else:
            log_with_context(
                logger, "warning",
                "Memory decay returned error",
                error=result.get("error")
            )

        return result

    except Exception as e:
        log_with_context(logger, "error", "Memory decay job failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_duplicate_cleanup_job() -> Dict[str, Any]:
    """
    Weekly job: Find and clean up duplicate entries in Qdrant.

    Two-phase approach:
    1. Find duplicates across collections
    2. Clean up with dry_run=False if duplicates found

    Schedule: Sunday at 04:00
    """
    log_with_context(logger, "info", "Starting duplicate cleanup job")

    try:
        from app.tool_modules.rag_maintenance_tools import find_duplicates, cleanup_duplicates

        # Collections to check for duplicates
        collections = ["jarvis_facts", "jarvis_corrections", "jarvis_research"]

        total_found = 0
        total_cleaned = 0
        results = []

        for collection in collections:
            try:
                # Phase 1: Find duplicates
                find_result = find_duplicates(
                    collection_name=collection,
                    similarity_threshold=0.95,  # Very similar = duplicate
                    sample_size=500
                )

                if not find_result.get("success", True):
                    log_with_context(
                        logger, "warning",
                        f"Find duplicates failed for {collection}",
                        error=find_result.get("error")
                    )
                    continue

                duplicates = find_result.get("duplicates_found", [])
                if not duplicates:
                    continue

                total_found += len(duplicates)

                # Extract IDs to delete (keep first, delete duplicates)
                ids_to_delete = []
                for dup in duplicates:
                    # Delete the second point (point_b) to keep the original
                    point_b_id = dup.get("point_b", {}).get("id")
                    if point_b_id:
                        ids_to_delete.append(point_b_id)

                if not ids_to_delete:
                    continue

                # Phase 2: Clean up (NOT dry run)
                cleanup_result = cleanup_duplicates(
                    collection_name=collection,
                    duplicate_ids=ids_to_delete,
                    dry_run=False
                )

                cleaned = cleanup_result.get("deleted_count", 0)
                total_cleaned += cleaned

                results.append({
                    "collection": collection,
                    "found": len(duplicates),
                    "cleaned": cleaned
                })

                log_with_context(
                    logger, "info",
                    f"Cleaned duplicates in {collection}",
                    found=len(duplicates),
                    cleaned=cleaned
                )

            except Exception as e:
                log_with_context(
                    logger, "warning",
                    f"Duplicate cleanup failed for {collection}",
                    error=str(e)
                )

        log_with_context(
            logger, "info",
            "Duplicate cleanup job completed",
            total_found=total_found,
            total_cleaned=total_cleaned
        )

        return {
            "success": True,
            "total_found": total_found,
            "total_cleaned": total_cleaned,
            "details": results
        }

    except Exception as e:
        log_with_context(logger, "error", "Duplicate cleanup job failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_anomaly_analysis_job() -> Dict[str, Any]:
    """
    Periodic job: Analyze system for anomalies.

    Checks errors, latency, resources, and tool usage patterns.
    Sends Telegram alert if critical anomalies detected.

    Schedule: Every 2 hours
    """
    log_with_context(logger, "info", "Starting anomaly analysis job")

    try:
        from app.tool_modules.monitoring_tools import analyze_anomalies

        result = analyze_anomalies(
            time_range="2h",
            categories=["errors", "latency", "resources", "tools"]
        )

        anomalies = result.get("anomalies", [])
        severity = result.get("severity", "normal")
        score = result.get("score", 0)

        log_with_context(
            logger, "info",
            "Anomaly analysis completed",
            anomaly_count=len(anomalies),
            severity=severity,
            score=score
        )

        # Alert on high severity
        if severity in ["high", "critical"] or score >= 50:
            _send_anomaly_alert(result)

        return result

    except Exception as e:
        log_with_context(logger, "error", "Anomaly analysis job failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_usage_anomaly_detection_job() -> Dict[str, Any]:
    """
    Daily job: Detect usage pattern anomalies.

    Identifies unusual patterns like activity spikes,
    high failure rates, or unexpected tool usage.

    Schedule: Daily at 06:00
    """
    log_with_context(logger, "info", "Starting usage anomaly detection job")

    try:
        from app.tool_modules.pattern_recognition_tools import detect_usage_anomalies

        result = detect_usage_anomalies(days=7)

        if result.get("success"):
            anomalies = result.get("anomalies", [])
            log_with_context(
                logger, "info",
                "Usage anomaly detection completed",
                anomaly_count=len(anomalies)
            )

            # Alert on significant anomalies
            high_severity = [a for a in anomalies if a.get("severity") in ["high", "critical"]]
            if high_severity:
                _send_usage_anomaly_alert(result)
        else:
            log_with_context(
                logger, "warning",
                "Usage anomaly detection returned error",
                error=result.get("error")
            )

        return result

    except Exception as e:
        log_with_context(logger, "error", "Usage anomaly detection job failed", error=str(e))
        return {"success": False, "error": str(e)}


def _send_anomaly_alert(analysis: Dict[str, Any]):
    """Send Telegram alert for detected anomalies."""
    try:
        from app.telegram_bot import TELEGRAM_TOKEN
        from app.state_db import get_all_telegram_users
        import requests

        if not TELEGRAM_TOKEN:
            return

        anomalies = analysis.get("anomalies", [])
        severity = analysis.get("severity", "unknown")
        score = analysis.get("score", 0)

        message = f"⚠️ **System Anomaly Alert**\n\n"
        message += f"Severity: {severity.upper()} (Score: {score})\n"
        message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        for anomaly in anomalies[:5]:  # Top 5
            cat = anomaly.get("category", "unknown")
            desc = anomaly.get("description", "No description")
            message += f"• [{cat}] {desc}\n"

        if len(anomalies) > 5:
            message += f"\n... and {len(anomalies) - 5} more"

        # Send to all registered users
        users = get_all_telegram_users()
        for user in users:
            _send_telegram(TELEGRAM_TOKEN, user["user_id"], message)

    except Exception as e:
        log_with_context(logger, "warning", "Failed to send anomaly alert", error=str(e))


def _send_usage_anomaly_alert(analysis: Dict[str, Any]):
    """Send Telegram alert for usage anomalies."""
    try:
        from app.telegram_bot import TELEGRAM_TOKEN
        from app.state_db import get_all_telegram_users
        import requests

        if not TELEGRAM_TOKEN:
            return

        anomalies = analysis.get("anomalies", [])
        high_severity = [a for a in anomalies if a.get("severity") in ["high", "critical"]]

        message = f"📊 **Usage Anomaly Alert**\n\n"
        message += f"Detected: {len(high_severity)} high-severity pattern(s)\n"
        message += f"Analysis period: 7 days\n\n"

        for anomaly in high_severity[:5]:
            atype = anomaly.get("type", "unknown")
            desc = _describe_usage_anomaly(anomaly)
            message += f"• [{atype}] {desc}\n"

        users = get_all_telegram_users()
        for user in users:
            _send_telegram(TELEGRAM_TOKEN, user["user_id"], message)

    except Exception as e:
        log_with_context(logger, "warning", "Failed to send usage anomaly alert", error=str(e))


def _describe_usage_anomaly(anomaly: Dict[str, Any]) -> str:
    """Return a readable one-line description for usage anomaly alerts."""
    atype = str(anomaly.get("type", "unknown"))

    if atype == "high_failure_rate":
        tool = str(anomaly.get("tool", "unknown_tool"))
        try:
            rate = float(anomaly.get("rate", 0.0))
        except (TypeError, ValueError):
            rate = 0.0
        try:
            total = int(anomaly.get("total", 0))
        except (TypeError, ValueError):
            total = 0
        severity = str(anomaly.get("severity", "unknown"))
        return f"{tool}: failure rate {rate:.1f}% over {total} calls (severity: {severity})"

    if atype == "activity_spike":
        try:
            count = int(anomaly.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        try:
            expected = int(anomaly.get("expected", 0))
        except (TypeError, ValueError):
            expected = 0
        return f"activity spike: {count} calls ({expected} expected)"

    if atype == "activity_drop":
        try:
            count = int(anomaly.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        try:
            expected = int(anomaly.get("expected", 0))
        except (TypeError, ValueError):
            expected = 0
        return f"activity drop: {count} calls ({expected} expected)"

    description = anomaly.get("description")
    if description:
        return str(description)

    return f"anomaly detected: {atype}"


def _send_telegram(token: str, chat_id: int, text: str):
    """Send a Telegram message."""
    import requests

    if len(text) > 4000:
        text = text[:3997] + "..."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        requests.post(url, json=payload, timeout=30)
    except Exception:
        pass  # Silent fail for alerts


def run_weekly_tool_report_job() -> Dict[str, Any]:
    """
    Weekly job: Generate and send tool usage report.

    Provides insights on:
    - Most used tools
    - Never used tools
    - Performance issues
    - Recommendations

    Schedule: Sunday at 10:00
    """
    log_with_context(logger, "info", "Starting weekly tool report job")

    try:
        from app.postgres_state import get_conn
        from app.telegram_bot import TELEGRAM_TOKEN
        from app.state_db import get_all_telegram_users

        report = {"generated_at": datetime.now().isoformat()}

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Top 10 most used tools (last 7 days)
                cur.execute("""
                    SELECT tool_name, COUNT(*) as calls,
                           COUNT(CASE WHEN success THEN 1 END) as successful,
                           ROUND(AVG(latency_ms)::numeric, 0) as avg_latency
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name
                    ORDER BY calls DESC
                    LIMIT 10
                """)
                top_tools = []
                for row in cur.fetchall():
                    top_tools.append({
                        "name": row[0],
                        "calls": row[1],
                        "success_rate": round(row[2] / row[1] * 100, 1) if row[1] > 0 else 0,
                        "avg_latency_ms": int(row[3]) if row[3] else 0
                    })
                report["top_tools"] = top_tools

                # Tools with issues (low success rate)
                cur.execute("""
                    SELECT tool_name, COUNT(*) as calls,
                           ROUND(COUNT(CASE WHEN success THEN 1 END)::float / COUNT(*) * 100, 1) as success_rate
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name
                    HAVING COUNT(*) >= 5
                       AND COUNT(CASE WHEN success THEN 1 END)::float / COUNT(*) < 0.9
                    ORDER BY success_rate ASC
                    LIMIT 5
                """)
                problem_tools = [{"name": row[0], "calls": row[1], "success_rate": float(row[2])} for row in cur.fetchall()]
                report["problem_tools"] = problem_tools

                # Slowest tools (p95 > 2s)
                cur.execute("""
                    SELECT tool_name, ROUND(AVG(latency_ms)::numeric, 0) as avg_latency
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name
                    HAVING COUNT(*) >= 5 AND AVG(latency_ms) > 2000
                    ORDER BY avg_latency DESC
                    LIMIT 5
                """)
                slow_tools = [{"name": row[0], "avg_latency_ms": int(row[1])} for row in cur.fetchall()]
                report["slow_tools"] = slow_tools

                # Never used tools count
                cur.execute("""
                    SELECT COUNT(*) FROM jarvis_tools
                    WHERE enabled = true AND use_count = 0
                """)
                never_used_count = cur.fetchone()[0]
                report["never_used_count"] = never_used_count

                # Total tools and usage stats
                cur.execute("""
                    SELECT COUNT(*), SUM(use_count) FROM jarvis_tools WHERE enabled = true
                """)
                row = cur.fetchone()
                report["total_tools"] = row[0]
                report["total_usage"] = row[1] or 0

        # Build Telegram message
        message = "📊 **Weekly Tool Report**\n\n"
        message += f"📅 Week ending {datetime.now().strftime('%Y-%m-%d')}\n\n"

        message += "**Top 5 Tools:**\n"
        for i, t in enumerate(report.get("top_tools", [])[:5], 1):
            message += f"{i}. `{t['name']}`: {t['calls']} calls ({t['success_rate']}%)\n"

        if report.get("problem_tools"):
            message += "\n⚠️ **Tools with Issues:**\n"
            for t in report["problem_tools"][:3]:
                message += f"• `{t['name']}`: {t['success_rate']}% success\n"

        if report.get("slow_tools"):
            message += "\n🐢 **Slow Tools:**\n"
            for t in report["slow_tools"][:3]:
                message += f"• `{t['name']}`: {t['avg_latency_ms']}ms avg\n"

        message += f"\n📈 **Summary:**\n"
        message += f"• Total tools: {report['total_tools']}\n"
        message += f"• Never used: {report['never_used_count']}\n"

        # Send report
        if TELEGRAM_TOKEN:
            users = get_all_telegram_users()
            for user in users:
                _send_telegram(TELEGRAM_TOKEN, user["user_id"], message)

        log_with_context(logger, "info", "Weekly tool report sent",
                        top_tools=len(report.get("top_tools", [])),
                        problem_tools=len(report.get("problem_tools", [])))

        return {"success": True, "report": report}

    except Exception as e:
        log_with_context(logger, "error", "Weekly tool report job failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_self_optimization_job() -> Dict[str, Any]:
    """
    Weekly job: Run self-optimization analysis.

    Analyzes system performance, quality, and cost to generate
    improvement proposals. Sends summary via Telegram.

    Schedule: Monday at 09:00
    """
    log_with_context(logger, "info", "Starting self-optimization job")

    try:
        from app.services.self_optimization import get_self_optimization_service
        from app.telegram_bot import TELEGRAM_TOKEN
        from app.state_db import get_all_telegram_users

        service = get_self_optimization_service()

        # Run analysis for last 7 days
        result = service.run_optimization_analysis(days=7)

        if not result.get("success"):
            log_with_context(logger, "warning", "Self-optimization analysis failed",
                           error=result.get("error"))
            return result

        proposals = result.get("proposals", [])

        # Build Telegram message
        if proposals:
            message = "🔧 **Weekly Self-Optimization Report**\n\n"
            message += f"Gefunden: {result['total_proposals']} Verbesserungsvorschläge\n\n"

            # Top 5 proposals
            for i, p in enumerate(proposals[:5], 1):
                impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p["impact"], "⚪")
                message += f"{i}. {impact_emoji} **{p['title']}**\n"
                message += f"   {p['description'][:100]}...\n"
                message += f"   → {p['proposed_action'][:80]}...\n\n"

            message += "_Nutze `run_self_optimization_analysis()` für Details._"

            # Send to all registered users
            if TELEGRAM_TOKEN:
                users = get_all_telegram_users()
                for user in users:
                    _send_telegram(TELEGRAM_TOKEN, user["user_id"], message)

        log_with_context(logger, "info", "Self-optimization job completed",
                        proposals=len(proposals))

        return result

    except Exception as e:
        log_with_context(logger, "error", "Self-optimization job failed", error=str(e))
        return {"success": False, "error": str(e)}
