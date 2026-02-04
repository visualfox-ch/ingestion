"""Phase 2 Gate Evaluation Scheduled Job

Runs daily during Phase 1 validation window (Feb 4-6) to check if
Phase 1 metrics meet Phase 2 gate criteria.

If decision is "approve", sends Telegram notification to admin for manual activation.
"""
from typing import Dict, Any
from ..observability import get_logger, log_with_context
from .. import phase_gate

logger = get_logger("jarvis.phase2_gate_job")


def run_phase2_gate_evaluation() -> Dict[str, Any]:
    """
    Evaluate Phase 2 gate criteria from Prometheus metrics.
    
    Returns:
        Gate evaluation result with decision and metrics
    """
    log_with_context(logger, "info", "Starting scheduled Phase 2 gate evaluation")
    
    try:
        # Evaluate Phase 1 metrics (24h window)
        result = phase_gate.evaluate_phase2_gate(window_hours=24)
        
        decision = result["decision"]
        log_with_context(
            logger,
            "info",
            "Phase 2 gate evaluation complete",
            decision=decision,
            metrics_count=len(result.get("metrics", {}))
        )
        
        # Send Telegram notification if decision is actionable
        if decision == "approve":
            _send_approval_notification(result)
        elif decision == "hold":
            _send_hold_notification(result)
        elif decision == "rollback":
            _send_rollback_notification(result)
        else:
            log_with_context(logger, "info", "Phase 2 gate: insufficient data, will retry tomorrow")
        
        return result
    
    except Exception as e:
        log_with_context(logger, "error", "Phase 2 gate evaluation failed", error=str(e), exc_info=True)
        return {
            "decision": "error",
            "error": str(e),
            "evaluated_at": None
        }


def _send_approval_notification(result: Dict[str, Any]):
    """Send Telegram notification when Phase 2 is approved."""
    from ..scheduler import _send_telegram_message
    from ..config import TELEGRAM_ADMIN_CHAT_ID
    
    if not TELEGRAM_ADMIN_CHAT_ID:
        log_with_context(logger, "warning", "Cannot send approval notification: no admin chat ID")
        return
    
    metrics = result.get("metrics", {})
    fp_rate = metrics.get("false_positive_rate", {}).get("value")
    success_rate = metrics.get("success_rate", {}).get("value")
    incidents = metrics.get("security_incidents", {}).get("value")
    
    message = (
        "🎯 **Phase 2 Gate: APPROVED** ✅\n\n"
        "Phase 1 validation complete. All metrics green:\n"
        f"• False Positive Rate: {fp_rate*100:.1f}% (<5% ✓)\n"
        f"• Success Rate: {success_rate*100:.1f}% (>95% ✓)\n"
        f"• Security Incidents: {int(incidents or 0)} (0 ✓)\n\n"
        "**Action Required**:\n"
        "Activate Phase 2 via:\n"
        "`curl -X POST http://192.168.1.103:18000/api/gate/phase2/activate "
        "-H 'Content-Type: application/json' "
        "-d '{\"decision_summary\": \"Phase 1 validated\", \"changed_by\": \"admin\", \"confirm\": true}'`\n\n"
        f"Evaluated at: {result.get('evaluated_at')}"
    )
    
    try:
        _send_telegram_message(TELEGRAM_ADMIN_CHAT_ID, message)
        log_with_context(logger, "info", "Phase 2 approval notification sent to admin")
    except Exception as e:
        log_with_context(logger, "error", "Failed to send approval notification", error=str(e))


def _send_hold_notification(result: Dict[str, Any]):
    """Send Telegram notification when Phase 2 gate is on hold."""
    from ..scheduler import _send_telegram_message
    from ..config import TELEGRAM_ADMIN_CHAT_ID
    
    if not TELEGRAM_ADMIN_CHAT_ID:
        return
    
    metrics = result.get("metrics", {})
    yellow_metrics = [
        name for name, metric in metrics.items()
        if metric.get("status") == "yellow"
    ]
    
    message = (
        "⏸️ **Phase 2 Gate: HOLD** ⚠️\n\n"
        "Some Phase 1 metrics are yellow:\n"
        f"• {', '.join(yellow_metrics)}\n\n"
        "**Recommendation**: Tune Phase 1, retry in 24h\n\n"
        f"Evaluated at: {result.get('evaluated_at')}"
    )
    
    try:
        _send_telegram_message(TELEGRAM_ADMIN_CHAT_ID, message)
        log_with_context(logger, "info", "Phase 2 hold notification sent to admin")
    except Exception as e:
        log_with_context(logger, "warning", "Failed to send hold notification", error=str(e))


def _send_rollback_notification(result: Dict[str, Any]):
    """Send Telegram notification when Phase 2 gate requires rollback."""
    from ..scheduler import _send_telegram_message
    from ..config import TELEGRAM_ADMIN_CHAT_ID
    
    if not TELEGRAM_ADMIN_CHAT_ID:
        return
    
    metrics = result.get("metrics", {})
    red_metrics = [
        (name, metric.get("description"))
        for name, metric in metrics.items()
        if metric.get("status") == "red"
    ]
    
    message = (
        "🚨 **Phase 2 Gate: ROLLBACK** 🔴\n\n"
        "Critical issues detected in Phase 1:\n\n"
    )
    
    for name, description in red_metrics:
        message += f"• **{name}**: {description}\n"
    
    message += (
        "\n**Recommendation**: Investigate issues, consider reverting to Phase 0\n\n"
        f"Evaluated at: {result.get('evaluated_at')}"
    )
    
    try:
        _send_telegram_message(TELEGRAM_ADMIN_CHAT_ID, message)
        log_with_context(logger, "warning", "Phase 2 rollback notification sent to admin")
    except Exception as e:
        log_with_context(logger, "error", "Failed to send rollback notification", error=str(e))
