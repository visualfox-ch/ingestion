"""API endpoints for deploy history and dashboard (ingestion mirror)"""

# This file is kept in sync with docker/app/routers/deploy_status_router.py
# Mirror copy for ingestion app

from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any

from ..observability import get_logger
from ..tool_modules.deploy_notifier_tools import get_deploy_notifier

logger = get_logger("jarvis.routers.deploy_status")
router = APIRouter(prefix="/deploy", tags=["Deploy"])


@router.get("/status", response_model=Dict[str, Any])
def get_deploy_status():
    """
    Get current deploy status and history.
    
    Returns recent deploys with success rate and trends.
    """
    notifier = get_deploy_notifier()
    
    # Get history
    history = notifier.db.get_recent_deploys(limit=10)
    
    # Calculate stats
    total = len(history)
    successful = sum(1 for r in history if r.status == "success")
    failed = sum(1 for r in history if r.status == "failed")
    success_rate = (successful / total * 100) if total > 0 else 0
    
    # Calculate average duration
    durations = [r.duration_seconds for r in history if r.duration_seconds]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    # Find rollback stats
    rollbacks = sum(1 for r in history if r.rollback_tag)
    
    return {
        "status": "ok",
        "history_count": total,
        "success": successful,
        "failed": failed,
        "success_rate_percent": round(success_rate, 1),
        "avg_duration_seconds": round(avg_duration, 1),
        "rollbacks_in_history": rollbacks,
        "recent_deploys": [
            {
                "id": r.deploy_id,
                "commit": r.commit_sha[:8] if r.commit_sha else "unknown",
                "message": r.commit_message[:50] if r.commit_message else "auto",
                "status": r.status,
                "phase": r.phase,
                "duration": r.duration_seconds,
                "started": r.started_at,
                "failed_health_checks": len(r.health_check_failures),
                "rollback": r.rollback_tag or None,
            }
            for r in history
        ]
    }


@router.get("/history", response_model=Dict[str, Any])
def get_deploy_history(limit: int = 20):
    """
    Get deploy history with detailed information.
    
    Query params:
    - limit: Number of recent deploys to return (default: 20, max: 100)
    """
    if limit > 100:
        limit = 100
    
    notifier = get_deploy_notifier()
    history = notifier.db.get_recent_deploys(limit)
    
    deploys = []
    for r in history:
        deploy_info = {
            "deploy_id": r.deploy_id,
            "commit": {
                "sha": r.commit_sha,
                "message": r.commit_message,
            },
            "timing": {
                "started": r.started_at,
                "ended": r.ended_at,
                "duration_seconds": r.duration_seconds,
            },
            "status": r.status,
            "phase": r.phase,
            "deployed_by": r.deployed_by,
            "hostname": r.hostname,
        }
        
        if r.health_check_failures:
            deploy_info["failures"] = [
                {
                    "endpoint": f["endpoint"],
                    "expected": f["expected_status"],
                    "actual": f["actual_status"],
                    "error": f["error_message"],
                }
                for f in r.health_check_failures
            ]
        
        if r.rollback_tag:
            deploy_info["rollback"] = {
                "tag": r.rollback_tag,
                "reason": r.rollback_reason,
            }
        
        deploys.append(deploy_info)
    
    return {
        "status": "ok",
        "count": len(deploys),
        "deploys": deploys,
    }


@router.get("/dashboard/summary", response_model=Dict[str, Any])
def get_deploy_dashboard_summary():
    """
    Get deploy dashboard summary (emoji timeline, stats).
    
    Used by n8n workflows and web dashboards.
    """
    notifier = get_deploy_notifier()
    history = notifier.db.get_recent_deploys(limit=10)
    
    # Build emoji timeline
    timeline = []
    for r in history:
        if r.status == "success":
            status_emoji = "✅"
        elif r.status == "failed":
            status_emoji = "❌"
        elif r.rollback_tag:
            status_emoji = "🔄"
        else:
            status_emoji = "⏳"
        
        timeline.append({
            "emoji": status_emoji,
            "commit": r.commit_message[:30] if r.commit_message else "auto",
            "duration": f"{r.duration_seconds:.0f}s" if r.duration_seconds else "?",
            "time": r.started_at[-8:] if r.started_at else "?",
        })
    
    # Stats
    recent_24h_count = len([r for r in history if r.status in ["success", "failed"]])
    failures = len([r for r in history if r.status == "failed"])
    
    return {
        "status": "ok",
        "last_10_deploys_timeline": timeline,
        "stats": {
            "total_in_history": len(history),
            "failures_last_10": failures,
            "success_rate": round((1 - failures/len(history)) * 100, 1) if history else 100,
        },
        "message": f"Last 10 deploys: {failures} failures, trend {'⬆️ improving' if failures <= 2 else '⬇️ needs attention'}",
    }


@router.get("/dashboard/alerts", response_model=Dict[str, Any])
def get_deploy_alerts():
    """
    Get deploy alerts (failures, rollbacks, patterns).
    
    Returns issues that need attention.
    """
    notifier = get_deploy_notifier()
    history = notifier.db.get_recent_deploys(limit=50)
    
    alerts = []
    
    # Check for repeated failures
    recent_statuses = [r.status for r in history[:10]]
    failure_streak = 0
    for status in recent_statuses:
        if status == "failed":
            failure_streak += 1
        else:
            break
    
    if failure_streak >= 2:
        alerts.append({
            "level": "critical",
            "message": f"⚠️ {failure_streak} consecutive deploy failures - investigate immediately",
        })
    
    # Check for pattern: rollbacks increasing
    rollback_recent = sum(1 for r in history[:10] if r.rollback_tag)
    if rollback_recent >= 3:
        alerts.append({
            "level": "warning",
            "message": f"🔄 {rollback_recent} rollbacks in last 10 deploys - code quality issue?",
        })
    
    # Check for health check failures
    health_failures = [r for r in history[:5] if r.health_check_failures]
    if health_failures:
        endpoints = set(
            f["endpoint"] 
            for r in health_failures 
            for f in r.health_check_failures
        )
        alerts.append({
            "level": "info",
            "message": f"📋 Recent health check failures on: {', '.join(endpoints)}",
        })
    
    return {
        "status": "ok",
        "alerts": alerts if alerts else [{"level": "info", "message": "✅ All systems nominal"}],
    }
