"""
Workflow Monitoring Job (Phase 3: n8n Workflow Mastery)

Collects metrics on n8n workflow executions and health.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from prometheus_client import Counter, Histogram, Gauge

from ..observability import get_logger, log_with_context
from ..n8n_workflow_manager import N8NWorkflowManager

logger = get_logger("jarvis.workflow_monitor")

# =============================================================================
# Metrics
# =============================================================================

WORKFLOW_EXECUTIONS_TOTAL = Counter(
    "jarvis_n8n_workflow_executions_total",
    "Total n8n workflow executions",
    ["workflow_id", "status"]
)

WORKFLOW_DURATION_SECONDS = Histogram(
    "jarvis_n8n_workflow_duration_seconds",
    "n8n workflow execution duration in seconds",
    ["workflow_id"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300]
)

WORKFLOW_ERRORS_TOTAL = Counter(
    "jarvis_n8n_workflow_errors_total",
    "Total n8n workflow execution errors",
    ["workflow_id", "error_type"]
)

WORKFLOW_LAST_EXECUTION_TS = Gauge(
    "jarvis_n8n_workflow_last_execution_timestamp",
    "Last execution timestamp for a workflow (unix seconds)",
    ["workflow_id"]
)

WORKFLOW_DATA_QUALITY_SCORE = Gauge(
    "jarvis_n8n_workflow_data_quality_score",
    "Data quality score per workflow (0-1 based on recent success rate)",
    ["workflow_id"]
)


# =============================================================================
# Helpers
# =============================================================================

def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _get_execution_status(execution: Dict[str, Any]) -> str:
    status = execution.get("status")
    if status:
        return status
    if execution.get("error"):
        return "error"
    if execution.get("finished"):
        return "success"
    return "running"


# =============================================================================
# Monitoring Job
# =============================================================================

def run_workflow_monitor(limit: int = 10) -> Dict[str, Any]:
    """Collect metrics for recent n8n workflow executions."""
    manager = N8NWorkflowManager()
    workflows = manager.list_workflows()

    summary = {
        "workflows_total": len(workflows),
        "executions_checked": 0,
        "errors": 0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    for workflow in workflows:
        workflow_id = str(workflow.get("id") or workflow.get("workflowId") or "unknown")
        executions = manager.list_executions(workflow_id=workflow_id, limit=limit)

        if not executions:
            continue

        summary["executions_checked"] += len(executions)

        success_count = 0
        total_count = 0

        for execution in executions:
            total_count += 1
            status = _get_execution_status(execution)
            WORKFLOW_EXECUTIONS_TOTAL.labels(workflow_id=workflow_id, status=status).inc()

            if status == "success":
                success_count += 1

            if status == "error":
                error_type = "unknown"
                if isinstance(execution.get("error"), dict):
                    error_type = execution.get("error", {}).get("name", "unknown")
                WORKFLOW_ERRORS_TOTAL.labels(workflow_id=workflow_id, error_type=error_type).inc()
                summary["errors"] += 1

            started_at = _parse_ts(execution.get("startedAt"))
            stopped_at = _parse_ts(execution.get("stoppedAt"))
            if started_at and stopped_at:
                duration = (stopped_at - started_at).total_seconds()
                if duration >= 0:
                    WORKFLOW_DURATION_SECONDS.labels(workflow_id=workflow_id).observe(duration)

            last_ts = stopped_at or started_at
            if last_ts:
                WORKFLOW_LAST_EXECUTION_TS.labels(workflow_id=workflow_id).set(last_ts.timestamp())

        # Data quality score = recent success rate
        if total_count > 0:
            WORKFLOW_DATA_QUALITY_SCORE.labels(workflow_id=workflow_id).set(success_count / total_count)

    log_with_context(
        logger,
        "info",
        "Workflow monitor run complete",
        workflows_total=summary["workflows_total"],
        executions_checked=summary["executions_checked"],
        errors=summary["errors"]
    )

    return summary
