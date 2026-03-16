"""
Anomaly Watcher Tools - Tier 2 #5 Jarvis Evolution

Proactive anomaly detection and alerting:
- Continuous monitoring with deduplication
- Telegram alerts for critical issues
- Auto-ticket creation for recurring problems
- Trend analysis across time windows
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

# Configuration
STATE_PATH = "/brain/system/state/anomaly_watcher_state.json"
JARVIS_API = "http://192.168.1.103:18000"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

# Alert cooldowns (avoid spam)
ALERT_COOLDOWNS = {
    "critical": 300,      # 5 minutes
    "warning": 1800,      # 30 minutes
    "minor": 3600,        # 1 hour
    "info": 7200          # 2 hours
}

# Thresholds for proactive alerts
PROACTIVE_THRESHOLDS = {
    "error_spike_count": 50,         # Errors in time window
    "error_spike_rate": 2.0,         # 2x normal rate
    "tool_failure_count": 10,        # Tool failures
    "response_time_degradation": 1.5, # 1.5x normal latency
    "consecutive_failures": 3,        # Same error 3 times
}


def _load_state() -> Dict[str, Any]:
    """Load watcher state from file."""
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state: {e}")

    return {
        "last_check": None,
        "alert_history": [],
        "anomaly_trends": [],
        "suppressed_alerts": {},
        "statistics": {
            "total_checks": 0,
            "total_alerts_sent": 0,
            "total_anomalies_detected": 0
        }
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Save watcher state to file."""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def _generate_alert_id(anomaly: Dict[str, Any]) -> str:
    """Generate unique ID for anomaly to track duplicates."""
    key_parts = [
        anomaly.get("category", ""),
        anomaly.get("type", ""),
        anomaly.get("severity", "")
    ]
    return hashlib.md5(":".join(key_parts).encode()).hexdigest()[:12]


def _should_alert(alert_id: str, severity: str, state: Dict[str, Any]) -> bool:
    """Check if we should send an alert (cooldown check)."""
    suppressed = state.get("suppressed_alerts", {})

    if alert_id in suppressed:
        last_alert_time = datetime.fromisoformat(suppressed[alert_id])
        cooldown = ALERT_COOLDOWNS.get(severity, 3600)

        if datetime.now() - last_alert_time < timedelta(seconds=cooldown):
            return False

    return True


def _mark_alerted(alert_id: str, state: Dict[str, Any]) -> None:
    """Mark an alert as sent."""
    state["suppressed_alerts"][alert_id] = datetime.now().isoformat()

    # Clean old suppressions (older than 24h)
    cutoff = datetime.now() - timedelta(hours=24)
    state["suppressed_alerts"] = {
        k: v for k, v in state["suppressed_alerts"].items()
        if datetime.fromisoformat(v) > cutoff
    }


def _send_telegram_alert(
    title: str,
    message: str,
    severity: str = "warning"
) -> bool:
    """Send alert via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured for alerts")
        return False

    # Severity emoji
    emoji_map = {
        "critical": "🚨",
        "warning": "⚠️",
        "minor": "📢",
        "info": "ℹ️"
    }
    emoji = emoji_map.get(severity, "📢")

    text = f"{emoji} *Anomaly Detected*\n\n"
    text += f"*{title}*\n"
    text += f"Severity: `{severity}`\n\n"
    text += message
    text += f"\n\n_Detected at {datetime.now().strftime('%H:%M:%S')}_"

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)

        return response.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


def watch_anomalies(
    time_range: str = "15m",
    auto_alert: bool = True,
    auto_ticket: bool = True,
    categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Proactive anomaly watcher - monitors system and sends alerts.

    Args:
        time_range: Time window to analyze (5m, 15m, 30m, 1h)
        auto_alert: Automatically send Telegram alerts for critical issues
        auto_ticket: Automatically create tickets for recurring problems
        categories: Categories to watch (errors, tools, latency, resources)

    Returns:
        Dict with detected anomalies, alerts sent, and recommendations
    """
    from .monitoring_tools import analyze_anomalies, get_system_health

    state = _load_state()
    state["statistics"]["total_checks"] += 1

    result = {
        "timestamp": datetime.now().isoformat(),
        "time_range": time_range,
        "anomalies_detected": [],
        "alerts_sent": [],
        "tickets_created": [],
        "trend_analysis": {},
        "recommendations": []
    }

    # Run anomaly analysis
    analysis = analyze_anomalies(time_range=time_range, categories=categories)

    if not analysis.get("anomalies"):
        # No anomalies - update trend
        result["status"] = "healthy"
        state["anomaly_trends"].append({
            "timestamp": datetime.now().isoformat(),
            "severity": "normal",
            "count": 0
        })
        _save_state(state)
        return result

    # Process each anomaly
    for anomaly in analysis["anomalies"]:
        alert_id = _generate_alert_id(anomaly)
        severity = anomaly.get("severity", "minor")

        result["anomalies_detected"].append({
            "id": alert_id,
            "category": anomaly.get("category"),
            "type": anomaly.get("type"),
            "severity": severity,
            "description": anomaly.get("description")
        })

        state["statistics"]["total_anomalies_detected"] += 1

        # Send alert if appropriate
        if auto_alert and severity in ["critical", "high", "warning"]:
            if _should_alert(alert_id, severity, state):
                title = f"{anomaly.get('category', 'System').title()} Anomaly"
                message = anomaly.get("description", "Unknown issue detected")

                # Add patterns if available
                if "patterns" in anomaly:
                    patterns = anomaly["patterns"]
                    if patterns:
                        top_patterns = list(patterns.items())[:3]
                        message += "\n\nTop patterns:\n"
                        message += "\n".join([f"• {k}: {v}x" for k, v in top_patterns])

                if _send_telegram_alert(title, message, severity):
                    _mark_alerted(alert_id, state)
                    result["alerts_sent"].append({
                        "id": alert_id,
                        "title": title,
                        "severity": severity
                    })
                    state["statistics"]["total_alerts_sent"] += 1

    # Check for recurring patterns (auto-ticket)
    if auto_ticket:
        recurring = _check_recurring_patterns(analysis["anomalies"], state)
        for pattern in recurring:
            ticket = _create_auto_ticket(pattern)
            if ticket.get("success"):
                result["tickets_created"].append(ticket)

    # Trend analysis
    result["trend_analysis"] = _analyze_trends(state)

    # Generate recommendations
    result["recommendations"] = _generate_recommendations(
        analysis["anomalies"],
        result["trend_analysis"]
    )

    # Update trends
    state["anomaly_trends"].append({
        "timestamp": datetime.now().isoformat(),
        "severity": analysis.get("severity", "normal"),
        "count": len(analysis["anomalies"])
    })

    # Keep only last 100 trend entries
    state["anomaly_trends"] = state["anomaly_trends"][-100:]

    # Record in alert history
    state["alert_history"].append({
        "timestamp": datetime.now().isoformat(),
        "anomaly_count": len(result["anomalies_detected"]),
        "alerts_sent": len(result["alerts_sent"]),
        "severity": analysis.get("severity")
    })
    state["alert_history"] = state["alert_history"][-500:]

    state["last_check"] = datetime.now().isoformat()
    _save_state(state)

    result["status"] = analysis.get("severity", "normal")
    return result


def _check_recurring_patterns(
    anomalies: List[Dict[str, Any]],
    state: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Check for patterns that recur frequently."""
    recurring = []

    # Get recent history
    recent_history = state.get("alert_history", [])[-20:]

    # Count category occurrences
    category_counts = {}
    for entry in recent_history:
        # Simple heuristic: if we've had multiple alerts recently
        if entry.get("alerts_sent", 0) > 0:
            category_counts["recent_alerts"] = category_counts.get("recent_alerts", 0) + 1

    # Check current anomalies against threshold
    for anomaly in anomalies:
        category = anomaly.get("category", "unknown")
        if anomaly.get("severity") in ["critical", "high"]:
            # Check if we've seen this pattern 3+ times recently
            pattern_key = f"{category}:{anomaly.get('type')}"
            occurrences = sum(
                1 for h in recent_history
                if h.get("severity") in ["critical", "warning"]
            )

            if occurrences >= PROACTIVE_THRESHOLDS["consecutive_failures"]:
                recurring.append({
                    "pattern": pattern_key,
                    "occurrences": occurrences,
                    "anomaly": anomaly
                })

    return recurring


def _create_auto_ticket(pattern: Dict[str, Any]) -> Dict[str, Any]:
    """Create automatic improvement ticket for recurring pattern."""
    from .monitoring_tools import create_improvement_ticket

    anomaly = pattern.get("anomaly", {})

    return create_improvement_ticket(
        title=f"Recurring {anomaly.get('category', 'System')} Issue",
        description=f"Auto-detected recurring pattern: {pattern.get('pattern')}\n"
                   f"Occurred {pattern.get('occurrences')} times recently.\n"
                   f"Last occurrence: {anomaly.get('description')}",
        category="monitoring",
        priority="high" if anomaly.get("severity") == "critical" else "medium",
        suggested_action="Investigate root cause and implement permanent fix"
    )


def _analyze_trends(state: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze anomaly trends over time."""
    trends = state.get("anomaly_trends", [])

    if not trends:
        return {"status": "no_data", "message": "No trend data available"}

    # Get recent trends (last 24h worth)
    recent = trends[-96:]  # Assuming 15min intervals

    total_anomalies = sum(t.get("count", 0) for t in recent)
    critical_count = sum(1 for t in recent if t.get("severity") == "critical")
    warning_count = sum(1 for t in recent if t.get("severity") == "warning")

    # Calculate trend direction
    if len(recent) >= 4:
        first_half = sum(t.get("count", 0) for t in recent[:len(recent)//2])
        second_half = sum(t.get("count", 0) for t in recent[len(recent)//2:])

        if second_half > first_half * 1.5:
            direction = "increasing"
        elif second_half < first_half * 0.5:
            direction = "decreasing"
        else:
            direction = "stable"
    else:
        direction = "insufficient_data"

    return {
        "total_anomalies_24h": total_anomalies,
        "critical_incidents": critical_count,
        "warning_incidents": warning_count,
        "trend_direction": direction,
        "health_score": max(0, 100 - (critical_count * 20) - (warning_count * 5) - (total_anomalies * 2))
    }


def _generate_recommendations(
    anomalies: List[Dict[str, Any]],
    trends: Dict[str, Any]
) -> List[str]:
    """Generate actionable recommendations based on anomalies and trends."""
    recommendations = []

    # Category-specific recommendations
    for anomaly in anomalies:
        category = anomaly.get("category")
        severity = anomaly.get("severity")

        if category == "errors" and severity in ["critical", "high"]:
            recommendations.append("Check Loki logs for detailed error traces")
            recommendations.append("Review recent deployments for breaking changes")

        if category == "tools":
            recommendations.append("Review tool registry for configuration issues")
            recommendations.append("Check external service connectivity (APIs, DBs)")

        if category == "latency":
            recommendations.append("Check Prometheus for resource bottlenecks")
            recommendations.append("Review database query performance")

        if category == "resources":
            recommendations.append("Consider scaling resources or optimizing memory usage")

    # Trend-based recommendations
    if trends.get("trend_direction") == "increasing":
        recommendations.append("Anomalies are increasing - prioritize investigation")

    if trends.get("health_score", 100) < 50:
        recommendations.append("System health is degraded - immediate attention needed")

    # Deduplicate
    return list(dict.fromkeys(recommendations))[:5]


def get_watcher_status() -> Dict[str, Any]:
    """
    Get current status of the Anomaly Watcher.

    Returns:
        Dict with watcher statistics and configuration
    """
    state = _load_state()

    return {
        "timestamp": datetime.now().isoformat(),
        "last_check": state.get("last_check"),
        "statistics": state.get("statistics", {}),
        "recent_alerts": state.get("alert_history", [])[-10:],
        "suppressed_count": len(state.get("suppressed_alerts", {})),
        "trend_summary": _analyze_trends(state),
        "configuration": {
            "alert_cooldowns": ALERT_COOLDOWNS,
            "thresholds": PROACTIVE_THRESHOLDS,
            "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        }
    }


def reset_alert_cooldowns(
    alert_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Reset alert cooldowns to allow immediate re-alerting.

    Args:
        alert_ids: Specific alert IDs to reset, or None for all

    Returns:
        Dict with reset confirmation
    """
    state = _load_state()

    if alert_ids:
        for alert_id in alert_ids:
            state["suppressed_alerts"].pop(alert_id, None)
        cleared = len(alert_ids)
    else:
        cleared = len(state.get("suppressed_alerts", {}))
        state["suppressed_alerts"] = {}

    _save_state(state)

    return {
        "success": True,
        "cleared_count": cleared,
        "message": f"Cleared {cleared} alert cooldowns"
    }


def configure_watcher(
    thresholds: Optional[Dict[str, Any]] = None,
    cooldowns: Optional[Dict[str, int]] = None
) -> Dict[str, Any]:
    """
    Configure watcher thresholds and cooldowns.

    Args:
        thresholds: New threshold values to set
        cooldowns: New cooldown values (seconds) by severity

    Returns:
        Dict with updated configuration
    """
    global PROACTIVE_THRESHOLDS, ALERT_COOLDOWNS

    if thresholds:
        PROACTIVE_THRESHOLDS.update(thresholds)

    if cooldowns:
        ALERT_COOLDOWNS.update(cooldowns)

    return {
        "success": True,
        "thresholds": PROACTIVE_THRESHOLDS,
        "cooldowns": ALERT_COOLDOWNS
    }


def get_anomaly_history(
    limit: int = 50,
    severity_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get anomaly detection history.

    Args:
        limit: Maximum entries to return
        severity_filter: Filter by severity (critical, warning, minor)

    Returns:
        Dict with historical anomaly data
    """
    state = _load_state()

    history = state.get("alert_history", [])

    if severity_filter:
        history = [h for h in history if h.get("severity") == severity_filter]

    return {
        "total_entries": len(state.get("alert_history", [])),
        "filtered_entries": len(history),
        "history": history[-limit:],
        "statistics": state.get("statistics", {})
    }


# Tool definitions for registration
ANOMALY_WATCHER_TOOLS = [
    {
        "name": "watch_anomalies",
        "description": "Proactive anomaly watcher - monitors system and sends Telegram alerts for critical issues. Use this for continuous monitoring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_range": {
                    "type": "string",
                    "default": "15m",
                    "description": "Time window to analyze (5m, 15m, 30m, 1h)"
                },
                "auto_alert": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically send Telegram alerts"
                },
                "auto_ticket": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically create tickets for recurring issues"
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories to watch (errors, tools, latency, resources)"
                }
            }
        }
    },
    {
        "name": "get_watcher_status",
        "description": "Get current status of the Anomaly Watcher including statistics and configuration.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "reset_alert_cooldowns",
        "description": "Reset alert cooldowns to allow immediate re-alerting for specific or all alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific alert IDs to reset, or omit for all"
                }
            }
        }
    },
    {
        "name": "configure_watcher",
        "description": "Configure watcher thresholds and alert cooldowns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thresholds": {
                    "type": "object",
                    "description": "New threshold values (error_spike_count, tool_failure_count, etc.)"
                },
                "cooldowns": {
                    "type": "object",
                    "description": "New cooldown values in seconds by severity (critical, warning, minor, info)"
                }
            }
        }
    },
    {
        "name": "get_anomaly_history",
        "description": "Get historical anomaly detection data for analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum entries to return"
                },
                "severity_filter": {
                    "type": "string",
                    "enum": ["critical", "warning", "minor"],
                    "description": "Filter by severity level"
                }
            }
        }
    }
]
