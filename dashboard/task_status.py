# Task/Alert status integration for dashboard backend
from app.agent_state import AgentState
from app.agent_metrics import get_deployment_metrics
from typing import List, Dict, Any

def get_all_task_status() -> List[Dict[str, Any]]:
    # Example: Use deployment metrics as a source for demo
    metrics = get_deployment_metrics().get_recent_deployments(limit=20)
    # Map to dashboard task format
    tasks = []
    for m in metrics:
        tasks.append({
            "id": m.get("agent", "unknown"),
            "status": "success" if m.get("success") else "failed",
            "type": m.get("mode", "-"),
            "owner": m.get("agent", "-"),
            "start": m.get("timestamp", "-")
        })
    return tasks

def get_alerts() -> List[Dict[str, Any]]:
    # Example: Show failed deployments as alerts
    metrics = get_deployment_metrics().get_recent_deployments(limit=20)
    alerts = []
    for m in metrics:
        if not m.get("success"):
            alerts.append({
                "message": f"Deployment failed for {m.get('agent')} at {m.get('timestamp')}: {m.get('error','unknown error')}"
            })
    return alerts
