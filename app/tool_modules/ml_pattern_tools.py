"""
ML Pattern Recognition Tools (Tier 4 #14).

Time-Series Analysis and Predictive Intelligence:
- Seasonal decomposition (hourly, daily, weekly patterns)
- Forecasting with confidence intervals
- Anomaly detection with seasonal adjustment
- Cross-metric correlation analysis
- Predictive alerting

Tools:
- record_metric: Record time series data point
- analyze_seasonality: Decompose metric into seasonal patterns
- forecast_metric: Generate forecasts with confidence intervals
- detect_anomalies: Find anomalies with ML-based detection
- correlate_metrics: Analyze correlation between metrics
- get_pattern_alerts: Get predictive alerts
- get_pattern_summary: Overview of all detected patterns
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

ML_PATTERN_TOOLS = [
    {
        "name": "record_metric",
        "description": "Record a time series data point for ML analysis. Use for tracking metrics like queries_per_hour, response_latency, error_count over time.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric (e.g., 'queries_per_hour', 'tool_failure_rate')"
                },
                "value": {
                    "type": "number",
                    "description": "Numeric value to record"
                },
                "dimensions": {
                    "type": "object",
                    "description": "Optional dimensions for segmentation (e.g., {'source': 'telegram'})"
                }
            },
            "required": ["metric_name", "value"]
        },
        "category": "ml_patterns"
    },
    {
        "name": "analyze_seasonality",
        "description": "Decompose a metric into trend, seasonal, and residual components. Detects hourly and weekly patterns (e.g., 'activity peaks at 14:00' or 'lowest on Sunday').",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric to analyze"
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours of historical data to analyze (default: 336 = 2 weeks)"
                }
            },
            "required": ["metric_name"]
        },
        "category": "ml_patterns"
    },
    {
        "name": "forecast_metric",
        "description": "Generate time series forecast with confidence intervals. Uses exponential smoothing with seasonal adjustment.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric to forecast"
                },
                "horizon_hours": {
                    "type": "integer",
                    "description": "How many hours ahead to forecast (default: 24)"
                },
                "confidence_level": {
                    "type": "number",
                    "description": "Confidence level for intervals (default: 0.9)"
                }
            },
            "required": ["metric_name"]
        },
        "category": "ml_patterns"
    },
    {
        "name": "detect_anomalies_ml",
        "description": "Detect anomalies using seasonally-adjusted statistical analysis. More accurate than simple threshold-based detection.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric to analyze"
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours of data to analyze (default: 168 = 1 week)"
                },
                "sensitivity": {
                    "type": "number",
                    "description": "Z-score threshold for anomalies (default: 2.5, lower = more sensitive)"
                }
            },
            "required": ["metric_name"]
        },
        "category": "ml_patterns"
    },
    {
        "name": "correlate_metrics",
        "description": "Analyze correlation between two metrics with lag analysis. Identifies if one metric leads/follows another.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric1": {
                    "type": "string",
                    "description": "First metric name"
                },
                "metric2": {
                    "type": "string",
                    "description": "Second metric name"
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours of data to analyze (default: 168)"
                }
            },
            "required": ["metric1", "metric2"]
        },
        "category": "ml_patterns"
    },
    {
        "name": "generate_predictive_alerts",
        "description": "Analyze metrics and generate predictive alerts for potential issues before they occur.",
        "parameters": {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of metrics to analyze (default: standard system metrics)"
                }
            },
            "required": []
        },
        "category": "ml_patterns"
    },
    {
        "name": "get_pattern_alerts",
        "description": "Get active predictive alerts that haven't been acknowledged.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Filter by severity level"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max alerts to return (default: 20)"
                }
            },
            "required": []
        },
        "category": "ml_patterns"
    },
    {
        "name": "get_pattern_summary",
        "description": "Get overview of all detected patterns, active forecasts, and alert counts.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "ml_patterns"
    },
    {
        "name": "get_time_series",
        "description": "Retrieve raw time series data for a metric.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric"
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours of history to retrieve (default: 168)"
                },
                "dimensions": {
                    "type": "object",
                    "description": "Filter by dimensions"
                }
            },
            "required": ["metric_name"]
        },
        "category": "ml_patterns"
    }
]


# =============================================================================
# Tool Handlers
# =============================================================================

def record_metric(
    metric_name: str,
    value: float,
    dimensions: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """Record a time series data point."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        success = service.record_metric(
            metric_name=metric_name,
            value=value,
            dimensions=dimensions
        )

        return {
            "success": success,
            "metric": metric_name,
            "value": value,
            "message": f"Recorded {metric_name}={value}" if success else "Recording failed"
        }
    except Exception as e:
        logger.error(f"record_metric failed: {e}")
        return {"success": False, "error": str(e)}


def analyze_seasonality(
    metric_name: str,
    hours: int = 336,
    **kwargs
) -> Dict[str, Any]:
    """Analyze seasonal patterns in a metric."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.decompose_seasonal(metric_name, hours)
    except Exception as e:
        logger.error(f"analyze_seasonality failed: {e}")
        return {"success": False, "error": str(e)}


def forecast_metric(
    metric_name: str,
    horizon_hours: int = 24,
    confidence_level: float = 0.9,
    **kwargs
) -> Dict[str, Any]:
    """Generate forecast for a metric."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.forecast(metric_name, horizon_hours, confidence_level)
    except Exception as e:
        logger.error(f"forecast_metric failed: {e}")
        return {"success": False, "error": str(e)}


def detect_anomalies_ml(
    metric_name: str,
    hours: int = 168,
    sensitivity: float = 2.5,
    **kwargs
) -> Dict[str, Any]:
    """Detect anomalies with ML-based analysis."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.detect_anomalies_ml(metric_name, hours, sensitivity)
    except Exception as e:
        logger.error(f"detect_anomalies_ml failed: {e}")
        return {"success": False, "error": str(e)}


def correlate_metrics(
    metric1: str,
    metric2: str,
    hours: int = 168,
    **kwargs
) -> Dict[str, Any]:
    """Analyze correlation between two metrics."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.correlate_metrics(metric1, metric2, hours)
    except Exception as e:
        logger.error(f"correlate_metrics failed: {e}")
        return {"success": False, "error": str(e)}


def generate_predictive_alerts(
    metrics: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Generate predictive alerts for metrics."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.generate_predictive_alerts(metrics)
    except Exception as e:
        logger.error(f"generate_predictive_alerts failed: {e}")
        return {"success": False, "error": str(e)}


def get_pattern_alerts(
    severity: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """Get active predictive alerts."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.get_active_alerts(severity, limit)
    except Exception as e:
        logger.error(f"get_pattern_alerts failed: {e}")
        return {"success": False, "error": str(e)}


def get_pattern_summary(**kwargs) -> Dict[str, Any]:
    """Get summary of all detected patterns."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        return service.get_pattern_summary()
    except Exception as e:
        logger.error(f"get_pattern_summary failed: {e}")
        return {"success": False, "error": str(e)}


def get_time_series(
    metric_name: str,
    hours: int = 168,
    dimensions: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """Get raw time series data."""
    try:
        from app.services.ml_pattern_service import get_ml_pattern_service
        service = get_ml_pattern_service()

        series = service.get_time_series(metric_name, hours, dimensions)

        return {
            "success": True,
            "metric": metric_name,
            "data_points": len(series),
            "hours": hours,
            "data": [
                {
                    "timestamp": p.timestamp.isoformat(),
                    "value": p.value,
                    "dimensions": p.metadata
                }
                for p in series[:100]  # Limit output
            ],
            "truncated": len(series) > 100
        }
    except Exception as e:
        logger.error(f"get_time_series failed: {e}")
        return {"success": False, "error": str(e)}


def get_ml_pattern_tools() -> List[Dict]:
    """Get all ML pattern tool definitions."""
    return ML_PATTERN_TOOLS
