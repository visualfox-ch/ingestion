"""
Self-Optimization Tools - Phase 21 Option 3C

Tools for proactive self-monitoring and optimization.
"""
from typing import Dict, Any, Optional

from ..observability import get_logger

logger = get_logger("jarvis.tools.self_optimization")


def run_self_optimization_analysis(days: int = 7) -> Dict[str, Any]:
    """
    Run comprehensive self-optimization analysis.

    Analyzes tool performance, query patterns, memory efficiency,
    cost optimization, and response quality to generate improvement proposals.

    Use this proactively to identify areas for improvement.

    Args:
        days: Number of days to analyze

    Returns:
        Dict with analysis results and optimization proposals
    """
    try:
        from ..services.self_optimization import get_self_optimization_service

        service = get_self_optimization_service()
        result = service.run_optimization_analysis(days)

        if result.get("success") and result.get("proposals"):
            # Format for easy reading
            formatted = f"\n**Selbst-Optimierungs-Analyse ({days} Tage)**\n\n"
            formatted += f"Gefundene Vorschläge: {result['total_proposals']}\n\n"

            for i, p in enumerate(result["proposals"][:5], 1):
                impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p["impact"], "⚪")
                formatted += f"{i}. {impact_emoji} **{p['title']}** [{p['category']}]\n"
                formatted += f"   {p['description']}\n"
                formatted += f"   → {p['proposed_action']}\n\n"

            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Self-optimization analysis failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_health_summary() -> Dict[str, Any]:
    """
    Get a quick health summary of my current state.

    Returns key metrics like tool success rate, active tools,
    and response latency.

    Use this for quick status checks.

    Returns:
        Dict with health metrics and status
    """
    try:
        from ..services.self_optimization import get_self_optimization_service

        service = get_self_optimization_service()
        result = service.get_health_summary()

        if result.get("metrics"):
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️",
                "unhealthy": "❌",
                "unknown": "❓"
            }.get(result.get("status", "unknown"), "❓")

            formatted = f"\n{status_emoji} **System Health: {result['status'].upper()}**\n\n"
            for key, value in result.get("metrics", {}).items():
                # Format key nicely
                nice_key = key.replace("_", " ").title()
                formatted += f"- {nice_key}: {value}\n"

            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Health summary failed: {e}")
        return {"success": False, "error": str(e)}


def propose_self_improvement(
    area: Optional[str] = None,
    days: int = 7
) -> Dict[str, Any]:
    """
    Generate self-improvement proposals for a specific area.

    Areas: performance, quality, cost, reliability, or None for all.

    Use this to get focused improvement suggestions.

    Args:
        area: Specific area to analyze (optional)
        days: Number of days to analyze

    Returns:
        Dict with improvement proposals
    """
    try:
        from ..services.self_optimization import get_self_optimization_service

        service = get_self_optimization_service()
        result = service.run_optimization_analysis(days)

        if area and result.get("success"):
            # Filter by area
            filtered = [
                p for p in result.get("proposals", [])
                if p["category"] == area
            ]
            result["proposals"] = filtered
            result["total_proposals"] = len(filtered)
            result["filter_area"] = area

        if result.get("success"):
            proposals = result.get("proposals", [])
            if proposals:
                formatted = f"\n**Verbesserungsvorschläge"
                if area:
                    formatted += f" [{area}]"
                formatted += f":**\n\n"

                for p in proposals[:5]:
                    effort_emoji = {"high": "💪", "medium": "👍", "low": "👌"}.get(p["effort"], "")
                    formatted += f"• **{p['title']}** {effort_emoji}\n"
                    formatted += f"  {p['description']}\n"
                    formatted += f"  Aktion: {p['proposed_action']}\n"
                    formatted += f"  (Impact: {p['impact']}, Confidence: {p['confidence']})\n\n"

                result["formatted"] = formatted
            else:
                result["formatted"] = f"Keine Verbesserungsvorschläge für Bereich '{area}' gefunden."

        return result

    except Exception as e:
        logger.error(f"Self-improvement proposal failed: {e}")
        return {"success": False, "error": str(e)}


def track_improvement_outcome(
    proposal_title: str,
    was_effective: bool,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Track the outcome of an applied improvement.

    Use this after applying an optimization to record whether it worked.

    Args:
        proposal_title: Title of the proposal that was applied
        was_effective: Whether the improvement was effective
        notes: Additional notes about the outcome

    Returns:
        Dict with tracking result
    """
    try:
        from ..postgres_state import get_conn
        import json
        from datetime import datetime

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jarvis_self_modifications
                    (modification_type, target, changes, created_at)
                    VALUES (%s, %s, %s, NOW())
                """, (
                    "improvement_outcome",
                    proposal_title,
                    json.dumps({
                        "was_effective": was_effective,
                        "notes": notes,
                        "tracked_at": datetime.now().isoformat()
                    })
                ))
                conn.commit()

        return {
            "success": True,
            "proposal_title": proposal_title,
            "was_effective": was_effective,
            "message": "Outcome tracked for future learning"
        }

    except Exception as e:
        logger.error(f"Failed to track improvement outcome: {e}")
        return {"success": False, "error": str(e)}


def get_improvement_history(limit: int = 20) -> Dict[str, Any]:
    """
    Get history of applied improvements and their outcomes.

    Use this to see what optimizations have been tried and their results.

    Args:
        limit: Maximum number of records to return

    Returns:
        Dict with improvement history
    """
    try:
        from ..postgres_state import get_conn
        import json

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT modification_type, target, changes, created_at
                    FROM jarvis_self_modifications
                    WHERE modification_type IN ('optimization_applied', 'improvement_outcome')
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))

                history = []
                for row in cur.fetchall():
                    changes = row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {}
                    history.append({
                        "type": row[0],
                        "proposal": row[1],
                        "details": changes,
                        "timestamp": row[3].isoformat() if row[3] else None
                    })

        result = {
            "success": True,
            "history": history,
            "count": len(history)
        }

        if history:
            formatted = "\n**Verbesserungs-Historie:**\n\n"
            for h in history[:10]:
                emoji = "✅" if h.get("details", {}).get("was_effective") else "📝"
                formatted += f"{emoji} {h['proposal']} ({h['type']})\n"
                if h.get("details", {}).get("notes"):
                    formatted += f"   Notes: {h['details']['notes']}\n"
                formatted += f"   {h['timestamp'][:10] if h.get('timestamp') else 'unknown'}\n\n"
            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to get improvement history: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
TOOLS = [
    {
        "name": "run_self_optimization_analysis",
        "description": "Run comprehensive self-optimization analysis. Analyzes performance, quality, cost, and reliability to generate improvement proposals.",
        "function": run_self_optimization_analysis,
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of days to analyze"
                }
            }
        },
        "category": "self_reflection",
        "risk_tier": 0
    },
    {
        "name": "get_my_health_summary",
        "description": "Get a quick health summary with key metrics like tool success rate and latency",
        "function": get_my_health_summary,
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "category": "self_reflection",
        "risk_tier": 0
    },
    {
        "name": "propose_self_improvement",
        "description": "Generate focused self-improvement proposals for a specific area (performance, quality, cost, reliability)",
        "function": propose_self_improvement,
        "parameters": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "enum": ["performance", "quality", "cost", "reliability"],
                    "description": "Specific area to analyze"
                },
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of days to analyze"
                }
            }
        },
        "category": "self_reflection",
        "risk_tier": 0
    },
    {
        "name": "track_improvement_outcome",
        "description": "Track the outcome of an applied improvement to learn from it",
        "function": track_improvement_outcome,
        "parameters": {
            "type": "object",
            "properties": {
                "proposal_title": {
                    "type": "string",
                    "description": "Title of the proposal that was applied"
                },
                "was_effective": {
                    "type": "boolean",
                    "description": "Whether the improvement was effective"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes about the outcome"
                }
            },
            "required": ["proposal_title", "was_effective"]
        },
        "category": "self_reflection",
        "risk_tier": 0
    },
    {
        "name": "get_improvement_history",
        "description": "Get history of applied improvements and their outcomes",
        "function": get_improvement_history,
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of records to return"
                }
            }
        },
        "category": "self_reflection",
        "risk_tier": 0
    }
]
