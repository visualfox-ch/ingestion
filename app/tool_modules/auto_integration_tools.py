"""
Auto-Integration Tools - Phase 4

Tools for managing the auto-learning system:
- Trigger pattern learning manually
- Get learning status
- Configure auto-learning settings
- View learning history
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def trigger_pattern_learning(
    days: int = 7,
    notify: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Manually trigger pattern learning analysis.

    Runs all pattern learning tasks immediately.

    Args:
        days: Number of days to analyze (default: 7)
        notify: Send notification on completion (default: False)

    Returns:
        Dict with results from all learning tasks
    """
    try:
        from app.jobs.pattern_learning_job import run_pattern_learning

        result = run_pattern_learning(days=days, notify=notify)
        return result

    except Exception as e:
        logger.error(f"Trigger pattern learning failed: {e}")
        return {"success": False, "error": str(e)}


def get_learning_status(**kwargs) -> Dict[str, Any]:
    """
    Get status of the auto-learning system.

    Shows what has been learned and system health.

    Returns:
        Dict with learning status and statistics
    """
    try:
        status = {
            "success": True,
            "components": {}
        }

        # 1. Tool chain status
        try:
            from app.services.smart_tool_chain_service import get_smart_tool_chain_service
            chain_service = get_smart_tool_chain_service()
            chains = chain_service.get_top_chains(limit=5)
            status["components"]["tool_chains"] = {
                "enabled": True,
                "chains_learned": len(chains.get("chains", [])),
                "top_chain": chains.get("chains", [{}])[0].get("chain") if chains.get("chains") else None
            }
        except Exception as e:
            status["components"]["tool_chains"] = {"enabled": False, "error": str(e)}

        # 2. Decision tracking status
        try:
            from app.services.decision_tracker import get_decision_tracker
            tracker = get_decision_tracker()
            stats = tracker.get_decision_stats(days=7)
            status["components"]["decision_tracking"] = {
                "enabled": True,
                "decisions_7d": stats.get("stats", {}).get("total_decisions", 0),
                "success_rate": stats.get("stats", {}).get("success_rate", 0)
            }
        except Exception as e:
            status["components"]["decision_tracking"] = {"enabled": False, "error": str(e)}

        # 3. Pattern recognition status
        try:
            from app.services.pattern_recognition_service import get_pattern_recognition_service
            pattern_service = get_pattern_recognition_service()
            patterns = pattern_service.get_recognized_patterns(limit=5)
            status["components"]["pattern_recognition"] = {
                "enabled": True,
                "patterns_found": len(patterns.get("patterns", []))
            }
        except Exception as e:
            status["components"]["pattern_recognition"] = {"enabled": False, "error": str(e)}

        # 4. Context routing status
        try:
            from app.services.contextual_tool_router import get_contextual_tool_router
            router = get_contextual_tool_router()
            rules = router.get_routing_rules()
            affinities = router.get_tool_affinities(limit=5)
            status["components"]["contextual_routing"] = {
                "enabled": True,
                "rules_count": len(rules.get("rules", [])),
                "affinities_learned": len(affinities.get("top_affinities", []))
            }
        except Exception as e:
            status["components"]["contextual_routing"] = {"enabled": False, "error": str(e)}

        # 5. Session patterns status
        try:
            from app.services.session_pattern_service import get_session_pattern_service
            session_service = get_session_pattern_service()
            current = session_service.get_current_session()
            status["components"]["session_patterns"] = {
                "enabled": True,
                "current_session": current.get("session_type") if current.get("success") else None
            }
        except Exception as e:
            status["components"]["session_patterns"] = {"enabled": False, "error": str(e)}

        # Overall health
        enabled_count = sum(
            1 for c in status["components"].values()
            if c.get("enabled", False)
        )
        status["overall_health"] = f"{enabled_count}/{len(status['components'])} components active"

        return status

    except Exception as e:
        logger.error(f"Get learning status failed: {e}")
        return {"success": False, "error": str(e)}


def get_learning_insights(
    days: int = 7,
    **kwargs
) -> Dict[str, Any]:
    """
    Get insights from the auto-learning system.

    Summarizes what has been learned recently.

    Args:
        days: Number of days to look back (default: 7)

    Returns:
        Dict with learning insights
    """
    try:
        insights = {
            "success": True,
            "period_days": days,
            "insights": []
        }

        # 1. Top tool chains
        try:
            from app.services.smart_tool_chain_service import get_smart_tool_chain_service
            chain_service = get_smart_tool_chain_service()
            chains = chain_service.get_top_chains(limit=3)
            if chains.get("chains"):
                top_chain = chains["chains"][0]
                insights["insights"].append({
                    "type": "tool_chain",
                    "message": f"Most common workflow: {' → '.join(top_chain['chain'])}",
                    "occurrences": top_chain.get("occurrences", 0)
                })
        except Exception:
            pass

        # 2. Best decisions
        try:
            from app.services.decision_tracker import get_decision_tracker
            tracker = get_decision_tracker()
            stats = tracker.get_decision_stats(days=days)
            if stats.get("top_patterns"):
                best = stats["top_patterns"][0]
                insights["insights"].append({
                    "type": "decision_pattern",
                    "message": f"Most effective decision: {best['decision']} ({best['category']})",
                    "score": best.get("score", 0)
                })
        except Exception:
            pass

        # 3. Temporal patterns
        try:
            from app.services.pattern_recognition_service import get_pattern_recognition_service
            pattern_service = get_pattern_recognition_service()
            temporal = pattern_service.analyze_temporal_patterns(days=days)
            if temporal.get("patterns", {}).get("peak_hour") is not None:
                peak = temporal["patterns"]["peak_hour"]
                insights["insights"].append({
                    "type": "temporal",
                    "message": f"Peak activity hour: {peak}:00",
                    "period": temporal["patterns"].get("most_active_period")
                })
        except Exception:
            pass

        # 4. Tool affinities
        try:
            from app.services.contextual_tool_router import get_contextual_tool_router
            router = get_contextual_tool_router()
            affinities = router.get_tool_affinities(limit=1)
            if affinities.get("top_affinities"):
                top = affinities["top_affinities"][0]
                insights["insights"].append({
                    "type": "tool_affinity",
                    "message": f"Strongest tool-context match: {top['tool']} for {top['context']}",
                    "score": top.get("score", 0)
                })
        except Exception:
            pass

        # 5. Anomalies
        try:
            from app.services.pattern_recognition_service import get_pattern_recognition_service
            pattern_service = get_pattern_recognition_service()
            anomalies = pattern_service.detect_anomalies(days=min(days, 7))
            if anomalies.get("anomalies_found", 0) > 0:
                insights["insights"].append({
                    "type": "anomaly",
                    "message": f"Detected {anomalies['anomalies_found']} anomalies in usage patterns",
                    "severity": "warning"
                })
        except Exception:
            pass

        return insights

    except Exception as e:
        logger.error(f"Get learning insights failed: {e}")
        return {"success": False, "error": str(e)}


def configure_auto_learning(
    component: str,
    enabled: bool = None,
    settings: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Configure auto-learning settings.

    Args:
        component: Component to configure (tool_chains, decisions, patterns, routing)
        enabled: Enable/disable the component
        settings: Additional settings for the component

    Returns:
        Dict with confirmation
    """
    try:
        # For now, just return the configuration intent
        # In a full implementation, this would persist to database
        return {
            "success": True,
            "component": component,
            "enabled": enabled,
            "settings": settings,
            "message": f"Configuration for {component} acknowledged. Full persistence not yet implemented."
        }

    except Exception as e:
        logger.error(f"Configure auto learning failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
AUTO_INTEGRATION_TOOLS = [
    {
        "name": "trigger_pattern_learning",
        "description": "Manually trigger pattern learning analysis. Runs all learning tasks immediately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 7)"
                },
                "notify": {
                    "type": "boolean",
                    "description": "Send notification on completion"
                }
            }
        }
    },
    {
        "name": "get_learning_status",
        "description": "Get status of the auto-learning system. Shows component health and statistics.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_learning_insights",
        "description": "Get insights from auto-learning. Summarizes what has been learned recently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to look back (default: 7)"
                }
            }
        }
    },
    {
        "name": "configure_auto_learning",
        "description": "Configure auto-learning settings for a component.",
        "input_schema": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "enum": ["tool_chains", "decisions", "patterns", "routing"],
                    "description": "Component to configure"
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Enable/disable the component"
                },
                "settings": {
                    "type": "object",
                    "description": "Additional settings"
                }
            },
            "required": ["component"]
        }
    }
]
