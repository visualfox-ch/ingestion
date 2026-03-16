"""
Pattern Learning Job - Phase 4.4

Background job that runs periodically to:
- Analyze temporal patterns
- Update tool co-occurrence data
- Cluster queries
- Detect anomalies
- Learn tool chains from audit history

Designed to run via APScheduler or cron.
"""

import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


def run_pattern_learning(
    days: int = 7,
    notify: bool = False
) -> Dict[str, Any]:
    """
    Run all pattern learning tasks.

    Args:
        days: Number of days to analyze
        notify: Whether to send notification on completion

    Returns:
        Dict with results from all learning tasks
    """
    results = {
        "started_at": datetime.now().isoformat(),
        "tasks": {}
    }

    # 1. Learn tool chains from audit history
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service
        chain_service = get_smart_tool_chain_service()
        chain_result = chain_service.learn_chains_from_audit(days=days, min_occurrences=2)
        results["tasks"]["tool_chains"] = {
            "success": chain_result.get("success", False),
            "chains_found": chain_result.get("chains_found", 0),
            "chains_saved": chain_result.get("chains_saved", 0)
        }
        logger.info(f"Tool chain learning: {chain_result.get('chains_saved', 0)} chains saved")
    except Exception as e:
        results["tasks"]["tool_chains"] = {"success": False, "error": str(e)}
        logger.warning(f"Tool chain learning failed: {e}")

    # 2. Analyze temporal patterns
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service
        pattern_service = get_pattern_recognition_service()
        temporal_result = pattern_service.analyze_temporal_patterns(days=days)
        results["tasks"]["temporal_patterns"] = {
            "success": temporal_result.get("success", False),
            "peak_hour": temporal_result.get("patterns", {}).get("peak_hour"),
            "most_active_day": temporal_result.get("patterns", {}).get("most_active_day")
        }
        logger.info(f"Temporal patterns analyzed: peak hour {temporal_result.get('patterns', {}).get('peak_hour')}")
    except Exception as e:
        results["tasks"]["temporal_patterns"] = {"success": False, "error": str(e)}
        logger.warning(f"Temporal pattern analysis failed: {e}")

    # 3. Analyze tool co-occurrence
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service
        pattern_service = get_pattern_recognition_service()
        cooccur_result = pattern_service.analyze_tool_cooccurrence(days=days)
        results["tasks"]["tool_cooccurrence"] = {
            "success": cooccur_result.get("success", False),
            "top_pairs_count": len(cooccur_result.get("top_pairs", []))
        }
        logger.info(f"Tool co-occurrence: {len(cooccur_result.get('top_pairs', []))} pairs found")
    except Exception as e:
        results["tasks"]["tool_cooccurrence"] = {"success": False, "error": str(e)}
        logger.warning(f"Tool co-occurrence analysis failed: {e}")

    # 4. Cluster queries
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service
        pattern_service = get_pattern_recognition_service()
        cluster_result = pattern_service.cluster_queries(days=days)
        results["tasks"]["query_clusters"] = {
            "success": cluster_result.get("success", False),
            "clusters_found": cluster_result.get("clusters_found", 0)
        }
        logger.info(f"Query clustering: {cluster_result.get('clusters_found', 0)} clusters")
    except Exception as e:
        results["tasks"]["query_clusters"] = {"success": False, "error": str(e)}
        logger.warning(f"Query clustering failed: {e}")

    # 5. Detect anomalies
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service
        pattern_service = get_pattern_recognition_service()
        anomaly_result = pattern_service.detect_anomalies(days=min(days, 7))
        results["tasks"]["anomaly_detection"] = {
            "success": anomaly_result.get("success", False),
            "anomalies_found": anomaly_result.get("anomalies_found", 0)
        }
        if anomaly_result.get("anomalies_found", 0) > 0:
            logger.warning(f"Anomalies detected: {anomaly_result.get('anomalies_found')}")
    except Exception as e:
        results["tasks"]["anomaly_detection"] = {"success": False, "error": str(e)}
        logger.warning(f"Anomaly detection failed: {e}")

    # 6. Learn context → tool mappings
    try:
        from app.services.context_tool_learner import get_context_tool_learner
        learner = get_context_tool_learner()
        learn_result = learner.learn_from_audit(days=days)
        results["tasks"]["context_mappings"] = {
            "success": learn_result.get("success", False),
            "mappings_created": learn_result.get("mappings_created", 0)
        }
        logger.info(f"Context mappings: {learn_result.get('mappings_created', 0)} created")
    except Exception as e:
        results["tasks"]["context_mappings"] = {"success": False, "error": str(e)}
        logger.warning(f"Context mapping learning failed: {e}")

    results["completed_at"] = datetime.now().isoformat()
    results["success"] = all(
        task.get("success", False)
        for task in results["tasks"].values()
    )

    # Send notification if requested
    if notify:
        try:
            _send_learning_summary(results)
        except Exception as e:
            logger.warning(f"Failed to send learning notification: {e}")

    return results


def _send_learning_summary(results: Dict[str, Any]):
    """Send learning summary via Telegram."""
    try:
        from app.notification_service import send_notification

        successful = sum(1 for t in results["tasks"].values() if t.get("success"))
        total = len(results["tasks"])

        message = f"**Pattern Learning Complete**\n\n"
        message += f"Tasks: {successful}/{total} successful\n\n"

        for name, task in results["tasks"].items():
            status = "✓" if task.get("success") else "✗"
            message += f"{status} {name}\n"

        send_notification(
            message=message,
            priority="low",
            channel="telegram"
        )
    except Exception as e:
        logger.debug(f"Notification send failed: {e}")


def schedule_pattern_learning():
    """
    Schedule the pattern learning job to run periodically.

    Should be called from main.py on startup.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler()

        # Run daily at 3 AM
        scheduler.add_job(
            run_pattern_learning,
            CronTrigger(hour=3, minute=0),
            kwargs={"days": 7, "notify": False},
            id="pattern_learning_daily",
            replace_existing=True
        )

        # Run weekly deep analysis on Sundays at 4 AM
        scheduler.add_job(
            run_pattern_learning,
            CronTrigger(day_of_week="sun", hour=4, minute=0),
            kwargs={"days": 30, "notify": True},
            id="pattern_learning_weekly",
            replace_existing=True
        )

        scheduler.start()
        logger.info("Pattern learning jobs scheduled (daily 3 AM, weekly Sunday 4 AM)")
        return scheduler

    except Exception as e:
        logger.warning(f"Failed to schedule pattern learning: {e}")
        return None
