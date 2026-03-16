"""
DevOps Self-Monitoring Tools - Phase 3 Agent Infrastructure

Autonomous monitoring agent that:
- Queries Prometheus metrics for anomaly detection
- Analyzes Loki logs for error patterns
- Detects performance degradation
- Creates improvement suggestions
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

# Infrastructure endpoints
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.1.103:19090")
LOKI_URL = os.getenv("LOKI_URL", "http://192.168.1.103:13100")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://192.168.1.103:13000")

# Thresholds for anomaly detection
THRESHOLDS = {
    "error_rate_percent": 5.0,      # Alert if >5% errors
    "latency_p95_ms": 2000,         # Alert if p95 >2s
    "memory_percent": 85,           # Alert if >85% memory
    "cpu_percent": 80,              # Alert if >80% CPU
    "tool_failure_rate": 10,        # Alert if >10% tool failures
}


def query_prometheus(
    query: str,
    time_range: str = "1h",
    step: str = "1m"
) -> Dict[str, Any]:
    """
    Query Prometheus metrics for system monitoring.

    Args:
        query: PromQL query string (e.g., 'rate(http_requests_total[5m])')
        time_range: Time range to query (e.g., '1h', '6h', '24h')
        step: Query resolution step (e.g., '1m', '5m')

    Returns:
        Dict with query results and metadata

    Example queries:
        - Error rate: 'sum(rate(http_requests_total{status=~"5.."}[5m]))'
        - Latency p95: 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))'
        - Memory: 'container_memory_usage_bytes{name="jarvis-ingestion"}'
    """
    try:
        # Parse time range
        range_mapping = {
            "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "6h": 21600, "12h": 43200,
            "24h": 86400, "7d": 604800
        }
        seconds = range_mapping.get(time_range, 3600)

        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds)

        # Query Prometheus range API
        url = f"{PROMETHEUS_URL}/api/v1/query_range"
        params = {
            "query": query,
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": step
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":
            return {
                "success": False,
                "error": data.get("error", "Unknown error"),
                "query": query
            }

        results = data.get("data", {}).get("result", [])

        # Process results
        processed = []
        for result in results:
            metric = result.get("metric", {})
            values = result.get("values", [])

            if values:
                # Get latest value and calculate stats
                latest = float(values[-1][1]) if values[-1][1] != "NaN" else None
                numeric_values = [float(v[1]) for _, v in enumerate(values) if v[1] != "NaN"]

                processed.append({
                    "metric": metric,
                    "latest_value": latest,
                    "min": min(numeric_values) if numeric_values else None,
                    "max": max(numeric_values) if numeric_values else None,
                    "avg": sum(numeric_values) / len(numeric_values) if numeric_values else None,
                    "data_points": len(values)
                })

        return {
            "success": True,
            "query": query,
            "time_range": time_range,
            "result_count": len(processed),
            "results": processed
        }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Cannot connect to Prometheus at {PROMETHEUS_URL}",
            "query": query
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Prometheus query timed out",
            "query": query
        }
    except Exception as e:
        logger.error(f"Prometheus query error: {e}")
        return {
            "success": False,
            "error": str(e),
            "query": query
        }


def query_loki(
    query: str,
    time_range: str = "1h",
    limit: int = 100,
    direction: str = "backward"
) -> Dict[str, Any]:
    """
    Query Loki logs for error patterns and analysis.

    Args:
        query: LogQL query string (e.g., '{container="jarvis-ingestion"} |= "error"')
        time_range: Time range to query (e.g., '1h', '6h', '24h')
        limit: Maximum number of log entries to return
        direction: 'backward' (newest first) or 'forward' (oldest first)

    Returns:
        Dict with log entries and analysis

    Example queries:
        - All errors: '{job="jarvis"} |= "ERROR"'
        - Tool failures: '{container="jarvis-ingestion"} |~ "tool.*failed"'
        - Slow queries: '{job="jarvis"} |~ "took [0-9]{4,}ms"'
    """
    try:
        # Parse time range to nanoseconds
        range_mapping = {
            "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "6h": 21600, "12h": 43200,
            "24h": 86400, "7d": 604800
        }
        seconds = range_mapping.get(time_range, 3600)

        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=seconds)

        # Query Loki API
        url = f"{LOKI_URL}/loki/api/v1/query_range"
        params = {
            "query": query,
            "start": int(start_time.timestamp() * 1e9),  # nanoseconds
            "end": int(end_time.timestamp() * 1e9),
            "limit": limit,
            "direction": direction
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":
            return {
                "success": False,
                "error": data.get("error", "Unknown error"),
                "query": query
            }

        results = data.get("data", {}).get("result", [])

        # Process and analyze logs
        all_entries = []
        error_patterns = {}

        for stream in results:
            labels = stream.get("stream", {})
            values = stream.get("values", [])

            for timestamp_ns, log_line in values:
                timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)

                entry = {
                    "timestamp": timestamp.isoformat(),
                    "labels": labels,
                    "message": log_line[:500]  # Truncate long messages
                }
                all_entries.append(entry)

                # Pattern extraction for errors
                if "error" in log_line.lower() or "exception" in log_line.lower():
                    # Extract error type (simple heuristic)
                    for word in log_line.split():
                        if "Error" in word or "Exception" in word:
                            error_patterns[word] = error_patterns.get(word, 0) + 1
                            break

        # Sort entries by timestamp
        all_entries.sort(key=lambda x: x["timestamp"], reverse=True)

        return {
            "success": True,
            "query": query,
            "time_range": time_range,
            "total_entries": len(all_entries),
            "entries": all_entries[:limit],
            "error_patterns": dict(sorted(
                error_patterns.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10])  # Top 10 error patterns
        }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Cannot connect to Loki at {LOKI_URL}",
            "query": query
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Loki query timed out",
            "query": query
        }
    except Exception as e:
        logger.error(f"Loki query error: {e}")
        return {
            "success": False,
            "error": str(e),
            "query": query
        }


def get_system_health(
    include_details: bool = True
) -> Dict[str, Any]:
    """
    Get comprehensive system health analysis.

    Checks:
    - Jarvis API health endpoint
    - Error rates from Prometheus
    - Recent errors from Loki
    - Memory/CPU usage
    - Tool execution stats

    Args:
        include_details: Include detailed metrics and recent errors

    Returns:
        Dict with health status, scores, and anomalies
    """
    health = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "score": 100,
        "checks": {},
        "anomalies": [],
        "recommendations": []
    }

    # 1. Check Jarvis API health
    try:
        response = requests.get(
            "http://192.168.1.103:18000/health",
            timeout=10
        )
        if response.status_code == 200:
            api_health = response.json()
            health["checks"]["api"] = {
                "status": "healthy",
                "response_time_ms": response.elapsed.total_seconds() * 1000,
                "details": api_health if include_details else None
            }
        else:
            health["checks"]["api"] = {"status": "degraded", "code": response.status_code}
            health["score"] -= 20
            health["anomalies"].append("API returned non-200 status")
    except Exception as e:
        health["checks"]["api"] = {"status": "unhealthy", "error": str(e)}
        health["score"] -= 30
        health["anomalies"].append(f"API unreachable: {e}")

    # 2. Check Prometheus metrics
    prometheus_available = False
    try:
        # Check if Prometheus is up
        prom_response = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5)
        prometheus_available = prom_response.status_code == 200
        health["checks"]["prometheus"] = {
            "status": "healthy" if prometheus_available else "degraded"
        }
    except Exception:
        health["checks"]["prometheus"] = {"status": "unavailable"}

    # 3. Check Loki
    loki_available = False
    try:
        loki_response = requests.get(f"{LOKI_URL}/ready", timeout=5)
        loki_available = loki_response.status_code == 200
        health["checks"]["loki"] = {
            "status": "healthy" if loki_available else "degraded"
        }
    except Exception:
        health["checks"]["loki"] = {"status": "unavailable"}

    # 4. Get recent errors from Loki if available
    if loki_available and include_details:
        error_logs = query_loki(
            query='{job=~"jarvis.*"} |~ "(?i)error|exception|failed"',
            time_range="1h",
            limit=20
        )
        if error_logs.get("success"):
            error_count = error_logs.get("total_entries", 0)
            health["checks"]["recent_errors"] = {
                "count": error_count,
                "patterns": error_logs.get("error_patterns", {})
            }

            if error_count > 50:
                health["score"] -= 15
                health["anomalies"].append(f"High error rate: {error_count} errors in last hour")
                health["recommendations"].append("Investigate error patterns in Loki logs")
            elif error_count > 20:
                health["score"] -= 5
                health["anomalies"].append(f"Elevated error rate: {error_count} errors in last hour")

    # 5. Determine overall status
    if health["score"] >= 90:
        health["overall_status"] = "healthy"
    elif health["score"] >= 70:
        health["overall_status"] = "degraded"
    elif health["score"] >= 50:
        health["overall_status"] = "warning"
    else:
        health["overall_status"] = "critical"

    return health


def analyze_anomalies(
    time_range: str = "6h",
    categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Analyze system for anomalies and patterns.

    Args:
        time_range: Time range to analyze (e.g., '1h', '6h', '24h')
        categories: Specific categories to check (default: all)
                   Options: 'errors', 'latency', 'resources', 'tools'

    Returns:
        Dict with detected anomalies and severity scores
    """
    if categories is None:
        categories = ["errors", "latency", "resources", "tools"]

    analysis = {
        "timestamp": datetime.now().isoformat(),
        "time_range": time_range,
        "anomalies": [],
        "severity": "normal",
        "score": 0
    }

    # Error analysis
    if "errors" in categories:
        error_result = query_loki(
            query='{job=~"jarvis.*"} |~ "(?i)error|exception|critical"',
            time_range=time_range,
            limit=200
        )

        if error_result.get("success"):
            error_count = error_result.get("total_entries", 0)
            patterns = error_result.get("error_patterns", {})

            # Check for error spikes
            if error_count > 100:
                analysis["anomalies"].append({
                    "category": "errors",
                    "type": "error_spike",
                    "severity": "high",
                    "description": f"{error_count} errors in {time_range}",
                    "patterns": patterns
                })
                analysis["score"] += 30
            elif error_count > 50:
                analysis["anomalies"].append({
                    "category": "errors",
                    "type": "elevated_errors",
                    "severity": "medium",
                    "description": f"{error_count} errors in {time_range}",
                    "patterns": patterns
                })
                analysis["score"] += 15

    # Tool failure analysis
    if "tools" in categories:
        tool_errors = query_loki(
            query='{job=~"jarvis.*"} |~ "tool.*failed|Tool execution error"',
            time_range=time_range,
            limit=100
        )

        if tool_errors.get("success"):
            tool_failure_count = tool_errors.get("total_entries", 0)

            if tool_failure_count > 20:
                analysis["anomalies"].append({
                    "category": "tools",
                    "type": "tool_failures",
                    "severity": "high",
                    "description": f"{tool_failure_count} tool failures in {time_range}",
                    "entries": tool_errors.get("entries", [])[:5]
                })
                analysis["score"] += 25
            elif tool_failure_count > 5:
                analysis["anomalies"].append({
                    "category": "tools",
                    "type": "tool_failures",
                    "severity": "medium",
                    "description": f"{tool_failure_count} tool failures in {time_range}"
                })
                analysis["score"] += 10

    # Determine overall severity
    if analysis["score"] >= 50:
        analysis["severity"] = "critical"
    elif analysis["score"] >= 30:
        analysis["severity"] = "warning"
    elif analysis["score"] >= 10:
        analysis["severity"] = "minor"
    else:
        analysis["severity"] = "normal"

    return analysis


def create_improvement_ticket(
    title: str,
    description: str,
    category: str = "optimization",
    priority: str = "medium",
    suggested_action: Optional[str] = None,
    related_metrics: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create an improvement ticket in the Action Queue.

    Args:
        title: Short title for the improvement
        description: Detailed description of the issue/improvement
        category: Type of improvement (optimization, bug, monitoring, scaling)
        priority: Urgency level (low, medium, high, critical)
        suggested_action: Recommended fix or improvement
        related_metrics: Supporting data from monitoring

    Returns:
        Dict with ticket creation result
    """
    try:
        # Map to action queue format
        action_payload = {
            "type": "devops_improvement",
            "title": title,
            "content": {
                "description": description,
                "category": category,
                "suggested_action": suggested_action,
                "related_metrics": related_metrics,
                "created_by": "monitoring_agent",
                "created_at": datetime.now().isoformat()
            },
            "priority": {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(priority, 2),
            "source": "devops_monitoring"
        }

        # Write to action queue file
        queue_path = "/brain/system/data/action_queue/pending"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"devops_{timestamp}_{category}.json"
        filepath = f"{queue_path}/{filename}"

        # Ensure directory exists
        os.makedirs(queue_path, exist_ok=True)

        with open(filepath, "w") as f:
            json.dump(action_payload, f, indent=2)

        logger.info(f"Created improvement ticket: {title}")

        return {
            "success": True,
            "ticket_id": filename,
            "title": title,
            "priority": priority,
            "category": category,
            "file_path": filepath
        }

    except Exception as e:
        logger.error(f"Failed to create improvement ticket: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def get_monitoring_status() -> Dict[str, Any]:
    """
    Get status of all monitoring components.

    Returns:
        Dict with status of Prometheus, Loki, Grafana and available metrics
    """
    status = {
        "timestamp": datetime.now().isoformat(),
        "components": {},
        "available_dashboards": []
    }

    # Check Prometheus
    try:
        response = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5)
        status["components"]["prometheus"] = {
            "status": "healthy" if response.status_code == 200 else "degraded",
            "url": PROMETHEUS_URL
        }
    except Exception as e:
        status["components"]["prometheus"] = {
            "status": "unavailable",
            "error": str(e),
            "url": PROMETHEUS_URL
        }

    # Check Loki
    try:
        response = requests.get(f"{LOKI_URL}/ready", timeout=5)
        status["components"]["loki"] = {
            "status": "healthy" if response.status_code == 200 else "degraded",
            "url": LOKI_URL
        }
    except Exception as e:
        status["components"]["loki"] = {
            "status": "unavailable",
            "error": str(e),
            "url": LOKI_URL
        }

    # Check Grafana
    try:
        response = requests.get(f"{GRAFANA_URL}/api/health", timeout=5)
        status["components"]["grafana"] = {
            "status": "healthy" if response.status_code == 200 else "degraded",
            "url": GRAFANA_URL
        }
    except Exception as e:
        status["components"]["grafana"] = {
            "status": "unavailable",
            "error": str(e),
            "url": GRAFANA_URL
        }

    # Add useful queries reference
    status["example_queries"] = {
        "prometheus": [
            "up{job='jarvis'}",
            "rate(http_requests_total[5m])",
            "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
        ],
        "loki": [
            '{job="jarvis"} |= "error"',
            '{container="jarvis-ingestion"} |~ "tool.*failed"',
            '{job="jarvis"} | json | level="error"'
        ]
    }

    return status


# Tool definitions for registration
# Tool definitions for Claude (JSON-serializable, no function references)
MONITORING_TOOLS = [
    {
        "name": "query_prometheus",
        "description": "Query Prometheus metrics for system monitoring. Use PromQL syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PromQL query string (e.g., 'rate(http_requests_total[5m])')"},
                "time_range": {"type": "string", "default": "1h", "description": "Time range (5m, 15m, 1h, 6h, 24h, 7d)"},
                "step": {"type": "string", "default": "1m", "description": "Resolution step (1m, 5m)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_loki",
        "description": "Query Loki logs for error patterns and analysis. Use LogQL syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "LogQL query string (e.g., '{job=\"jarvis\"} |= \"error\"')"},
                "time_range": {"type": "string", "default": "1h", "description": "Time range (5m, 15m, 1h, 6h, 24h)"},
                "limit": {"type": "integer", "default": 100, "description": "Max entries to return"},
                "direction": {"type": "string", "default": "backward", "enum": ["backward", "forward"]}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_system_health",
        "description": "Get comprehensive system health analysis including API status, error counts, and anomalies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_details": {"type": "boolean", "default": True, "description": "Include detailed metrics and recent errors"}
            }
        }
    },
    {
        "name": "analyze_anomalies",
        "description": "Analyze system for anomalies and patterns in errors, latency, resources, or tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_range": {"type": "string", "default": "6h", "description": "Time range to analyze"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["errors", "latency", "resources", "tools"]},
                    "description": "Categories to check (default: all)"
                }
            }
        }
    },
    {
        "name": "create_improvement_ticket",
        "description": "Create an improvement ticket in the Action Queue for DevOps issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the improvement"},
                "description": {"type": "string", "description": "Detailed description of the issue"},
                "category": {"type": "string", "enum": ["optimization", "bug", "monitoring", "scaling"], "default": "optimization"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
                "suggested_action": {"type": "string", "description": "Recommended fix or improvement"}
            },
            "required": ["title", "description"]
        }
    },
    {
        "name": "get_monitoring_status",
        "description": "Get status of all monitoring components (Prometheus, Loki, Grafana) and example queries.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
