"""
Phase 2 Gate Decision Engine

Evaluates Phase 1 monitoring metrics and, when approved,
activates Phase 2 auto-approval thresholds via hot config.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional

from .observability import get_logger, log_with_context
from .prometheus_metrics import get_prometheus_client
from .hot_config import set_hot_config, get_hot_config

logger = get_logger("jarvis.phase_gate")

# Gate thresholds (match monitoring docs/alerts)
FALSE_POSITIVE_BLOCKER = 0.05
FALSE_POSITIVE_CRITICAL = 0.10
SUCCESS_RATE_MIN = 0.95
SUCCESS_RATE_CRITICAL = 0.90
CONFIDENCE_OUTLIERS_WARN = 10
CONFIDENCE_OUTLIERS_CRITICAL = 25


@dataclass
class GateMetric:
    name: str
    value: Optional[float]
    status: str
    threshold: Optional[float] = None
    description: str = ""


def _query_scalar(query: str) -> Optional[float]:
    client = get_prometheus_client()
    if not client.is_available():
        return None

    result = client.query_instant(query)
    if not result or result.get("type") != "vector":
        return None

    values = result.get("result", [])
    if not values:
        return None

    try:
        return float(values[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def evaluate_phase2_gate(window_hours: int = 24) -> Dict[str, Any]:
    """Evaluate Phase 2 gate criteria from Prometheus metrics.

    Returns a dict with decision, metrics, and reasoning.
    """
    fp_query = (
        f"sum(increase(jarvis_auto_approval_false_positives_total[{window_hours}h])) / "
        f"sum(increase(jarvis_auto_approval_decisions_total{{decision=\"auto_approved\"}}[{window_hours}h]))"
    )
    success_query = (
        f"sum(increase(jarvis_auto_approval_decisions_total{{decision=\"auto_approved\",success=\"true\"}}[{window_hours}h])) / "
        f"sum(increase(jarvis_auto_approval_decisions_total{{decision=\"auto_approved\"}}[{window_hours}h]))"
    )
    incident_query = f"sum(increase(jarvis_security_incidents_total{{source=\"auto_approval\"}}[{window_hours}h]))"
    outlier_query = "sum(increase(jarvis_confidence_score_outliers_total[1h]))"

    false_positive_rate = _query_scalar(fp_query)
    success_rate = _query_scalar(success_query)
    security_incidents = _query_scalar(incident_query)
    confidence_outliers = _query_scalar(outlier_query)

    metrics: Dict[str, GateMetric] = {}

    if false_positive_rate is None:
        metrics["false_positive_rate"] = GateMetric(
            name="false_positive_rate",
            value=None,
            status="unknown",
            threshold=FALSE_POSITIVE_BLOCKER,
            description="Missing data for false positive rate"
        )
    elif false_positive_rate > FALSE_POSITIVE_CRITICAL:
        metrics["false_positive_rate"] = GateMetric(
            name="false_positive_rate",
            value=false_positive_rate,
            status="red",
            threshold=FALSE_POSITIVE_CRITICAL,
            description="False positive rate >10% (critical)"
        )
    elif false_positive_rate > FALSE_POSITIVE_BLOCKER:
        metrics["false_positive_rate"] = GateMetric(
            name="false_positive_rate",
            value=false_positive_rate,
            status="yellow",
            threshold=FALSE_POSITIVE_BLOCKER,
            description="False positive rate >5% (gate blocker)"
        )
    else:
        metrics["false_positive_rate"] = GateMetric(
            name="false_positive_rate",
            value=false_positive_rate,
            status="green",
            threshold=FALSE_POSITIVE_BLOCKER,
            description="False positive rate within target"
        )

    if success_rate is None:
        metrics["success_rate"] = GateMetric(
            name="success_rate",
            value=None,
            status="unknown",
            threshold=SUCCESS_RATE_MIN,
            description="Missing data for success rate"
        )
    elif success_rate < SUCCESS_RATE_CRITICAL:
        metrics["success_rate"] = GateMetric(
            name="success_rate",
            value=success_rate,
            status="red",
            threshold=SUCCESS_RATE_MIN,
            description="Success rate below 90%"
        )
    elif success_rate < SUCCESS_RATE_MIN:
        metrics["success_rate"] = GateMetric(
            name="success_rate",
            value=success_rate,
            status="yellow",
            threshold=SUCCESS_RATE_MIN,
            description="Success rate below 95%"
        )
    else:
        metrics["success_rate"] = GateMetric(
            name="success_rate",
            value=success_rate,
            status="green",
            threshold=SUCCESS_RATE_MIN,
            description="Success rate within target"
        )

    if security_incidents is None:
        metrics["security_incidents"] = GateMetric(
            name="security_incidents",
            value=None,
            status="unknown",
            threshold=0,
            description="Missing data for security incidents"
        )
    elif security_incidents > 0:
        metrics["security_incidents"] = GateMetric(
            name="security_incidents",
            value=security_incidents,
            status="red",
            threshold=0,
            description="Security incident detected"
        )
    else:
        metrics["security_incidents"] = GateMetric(
            name="security_incidents",
            value=security_incidents,
            status="green",
            threshold=0,
            description="No security incidents"
        )

    if confidence_outliers is None:
        metrics["confidence_outliers"] = GateMetric(
            name="confidence_outliers",
            value=None,
            status="unknown",
            threshold=CONFIDENCE_OUTLIERS_WARN,
            description="Missing data for confidence outliers"
        )
    elif confidence_outliers > CONFIDENCE_OUTLIERS_CRITICAL:
        metrics["confidence_outliers"] = GateMetric(
            name="confidence_outliers",
            value=confidence_outliers,
            status="red",
            threshold=CONFIDENCE_OUTLIERS_WARN,
            description="Confidence outliers above critical threshold"
        )
    elif confidence_outliers > CONFIDENCE_OUTLIERS_WARN:
        metrics["confidence_outliers"] = GateMetric(
            name="confidence_outliers",
            value=confidence_outliers,
            status="yellow",
            threshold=CONFIDENCE_OUTLIERS_WARN,
            description="Confidence outliers above warning threshold"
        )
    else:
        metrics["confidence_outliers"] = GateMetric(
            name="confidence_outliers",
            value=confidence_outliers,
            status="green",
            threshold=CONFIDENCE_OUTLIERS_WARN,
            description="Confidence distribution within target"
        )

    statuses = [metric.status for metric in metrics.values()]

    if "red" in statuses:
        decision = "rollback"
    elif "unknown" in statuses:
        decision = "insufficient_data"
    elif "yellow" in statuses:
        decision = "hold"
    else:
        decision = "approve"

    summary = {
        "decision": decision,
        "window_hours": window_hours,
        "evaluated_at": datetime.utcnow().isoformat() + "Z",
        "metrics": {name: metric.__dict__ for name, metric in metrics.items()}
    }

    log_with_context(
        logger,
        "info",
        "Phase 2 gate evaluation complete",
        decision=decision,
        window_hours=window_hours
    )

    return summary


def apply_phase2_settings(
    decision_summary: Dict[str, Any],
    changed_by: str = "system",
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Apply Phase 2 thresholds if decision is approved."""
    decision = decision_summary.get("decision")
    if decision != "approve":
        return {
            "status": "skipped",
            "reason": f"Decision is '{decision}', not applying Phase 2 settings",
            "decision": decision
        }

    change_reason = reason or "Phase 2 gate approved"

    set_hot_config("auto_approval_enabled", True, changed_by=changed_by, reason=change_reason)
    set_hot_config("auto_approval_phase", 2, changed_by=changed_by, reason=change_reason)
    set_hot_config("auto_approval_r0_threshold", 0.70, changed_by=changed_by, reason=change_reason)
    set_hot_config("auto_approval_r1_threshold", 0.85, changed_by=changed_by, reason=change_reason)
    set_hot_config("auto_approval_r2_threshold", 0.95, changed_by=changed_by, reason=change_reason)
    set_hot_config("auto_approval_r3_threshold", 0.99, changed_by=changed_by, reason=change_reason)

    return {
        "status": "applied",
        "phase": 2,
        "applied_at": datetime.utcnow().isoformat() + "Z",
        "reason": change_reason,
        "current_phase": get_hot_config("auto_approval_phase", 1)
    }
