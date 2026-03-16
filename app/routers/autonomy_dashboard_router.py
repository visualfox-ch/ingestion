"""
Autonomy Dashboard Router - Phase 19.6

Provides a unified dashboard view of Jarvis's autonomous capabilities:
- Decision Rules and their match counts
- Tool execution stats
- Active guardrails (prompt fragments)
- Recent self-modifications
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timedelta

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.autonomy_dashboard")
router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("/dashboard")
def get_autonomy_dashboard():
    """
    Get complete autonomy dashboard with all metrics.

    Returns unified view of:
    - Decision rules (active, match counts)
    - Tool stats (usage, performance)
    - Guardrails (active prompt fragments)
    - Recent modifications
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get decision rules
                cur.execute("""
                    SELECT id, name, condition_type, action_type,
                           match_count, last_matched_at, priority, enabled
                    FROM jarvis_decision_rules
                    ORDER BY match_count DESC, priority DESC
                """)
                rules = cur.fetchall()

                # Get tool execution stats (last 7 days)
                cur.execute("""
                    SELECT tool_name,
                           COUNT(*) as executions,
                           AVG(latency_ms)::int as avg_latency,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) * 100 as success_rate
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name
                    ORDER BY executions DESC
                    LIMIT 20
                """)
                tool_stats = cur.fetchall()

                # Get slowest tools
                cur.execute("""
                    SELECT tool_name, AVG(latency_ms)::int as avg_latency
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name
                    HAVING AVG(latency_ms) > 300
                    ORDER BY avg_latency DESC
                    LIMIT 5
                """)
                slow_tools = cur.fetchall()

                # Get guardrails (high-priority prompt fragments)
                cur.execute("""
                    SELECT name, priority, fragment_type
                    FROM jarvis_prompt_fragments
                    WHERE enabled = true AND fragment_type = 'guardrail'
                    ORDER BY priority DESC
                """)
                guardrails = cur.fetchall()

                # Get recent self-modifications
                cur.execute("""
                    SELECT target_table, target_name, modification_type,
                           reason, created_at
                    FROM jarvis_self_modifications
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                modifications = cur.fetchall()

                # Get tool counts
                cur.execute("SELECT COUNT(*) FROM jarvis_tools WHERE enabled = true")
                enabled_tools = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) FROM jarvis_tools")
                total_tools = cur.fetchone()["count"]

                # Get response style
                cur.execute("""
                    SELECT name, tone, verbosity
                    FROM jarvis_response_styles
                    WHERE is_default = true AND enabled = true
                    LIMIT 1
                """)
                style_row = cur.fetchone()

        return {
            "timestamp": datetime.now().isoformat(),
            "rules": {
                "total": len(rules),
                "active": len([r for r in rules if r["enabled"]]),
                "top_matched": [
                    {
                        "name": r["name"],
                        "condition_type": r["condition_type"],
                        "action_type": r["action_type"],
                        "match_count": r["match_count"] or 0,
                        "last_matched": r["last_matched_at"].isoformat() if r["last_matched_at"] else None,
                        "priority": r["priority"]
                    }
                    for r in rules[:10]
                ]
            },
            "tools": {
                "total": total_tools,
                "enabled": enabled_tools,
                "top_used": [
                    {
                        "name": t["tool_name"],
                        "executions": t["executions"],
                        "avg_latency_ms": t["avg_latency"],
                        "success_rate": round(t["success_rate"], 1)
                    }
                    for t in tool_stats
                ],
                "slowest": [
                    {"name": t["tool_name"], "avg_ms": t["avg_latency"]}
                    for t in slow_tools
                ]
            },
            "guardrails": {
                "active": [
                    {"name": g["name"], "priority": g["priority"]}
                    for g in guardrails
                ]
            },
            "response_style": {
                "name": style_row["name"] if style_row else "default",
                "tone": style_row["tone"] if style_row else "friendly",
                "verbosity": style_row["verbosity"] if style_row else "balanced"
            },
            "recent_modifications": [
                {
                    "table": m["target_table"],
                    "name": m["target_name"],
                    "type": m["modification_type"],
                    "reason": m["reason"],
                    "timestamp": m["created_at"].isoformat() if m["created_at"] else None
                }
                for m in modifications
            ]
        }

    except Exception as e:
        log_with_context(logger, "error", "Dashboard query failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@router.get("/rules")
def get_decision_rules(
    enabled_only: bool = Query(True, description="Only show enabled rules")
):
    """Get all decision rules with details."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if enabled_only:
                    cur.execute("""
                        SELECT id, name, description, condition_type, condition_value,
                               action_type, action_value, priority, match_count,
                               last_matched_at, created_at
                        FROM jarvis_decision_rules
                        WHERE enabled = true
                        ORDER BY priority DESC
                    """)
                else:
                    cur.execute("""
                        SELECT id, name, description, condition_type, condition_value,
                               action_type, action_value, priority, match_count,
                               last_matched_at, enabled, created_at
                        FROM jarvis_decision_rules
                        ORDER BY priority DESC
                    """)

                rules = cur.fetchall()

        return {
            "rules": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "condition": {
                        "type": r["condition_type"],
                        "value": r["condition_value"]
                    },
                    "action": {
                        "type": r["action_type"],
                        "value": r["action_value"]
                    },
                    "priority": r["priority"],
                    "match_count": r["match_count"] or 0,
                    "last_matched": r["last_matched_at"].isoformat() if r["last_matched_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None
                }
                for r in rules
            ],
            "count": len(rules)
        }

    except Exception as e:
        log_with_context(logger, "error", "Rules query failed", error=str(e))
        return {"error": str(e), "rules": [], "count": 0}


@router.get("/rules/{rule_id}/history")
def get_rule_history(rule_id: int):
    """Get modification history for a specific rule."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT modification_type, old_value, new_value, reason, created_at
                    FROM jarvis_self_modifications
                    WHERE target_table = 'jarvis_decision_rules' AND target_id = %s
                    ORDER BY created_at DESC
                """, (rule_id,))

                history = cur.fetchall()

        return {
            "rule_id": rule_id,
            "history": [
                {
                    "type": h["modification_type"],
                    "old_value": h["old_value"],
                    "new_value": h["new_value"],
                    "reason": h["reason"],
                    "timestamp": h["created_at"].isoformat() if h["created_at"] else None
                }
                for h in history
            ]
        }

    except Exception as e:
        log_with_context(logger, "error", "Rule history query failed", error=str(e))
        return {"error": str(e), "rule_id": rule_id, "history": []}


@router.get("/guardrails")
def get_guardrails():
    """Get all active guardrails (high-priority prompt fragments)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, content, priority, created_at, updated_at
                    FROM jarvis_prompt_fragments
                    WHERE enabled = true AND fragment_type = 'guardrail'
                    ORDER BY priority DESC
                """)

                guardrails = cur.fetchall()

        return {
            "guardrails": [
                {
                    "name": g["name"],
                    "content": g["content"],
                    "priority": g["priority"],
                    "created_at": g["created_at"].isoformat() if g["created_at"] else None
                }
                for g in guardrails
            ],
            "count": len(guardrails)
        }

    except Exception as e:
        log_with_context(logger, "error", "Guardrails query failed", error=str(e))
        return {"error": str(e), "guardrails": [], "count": 0}


@router.get("/performance")
def get_performance_overview(
    days: int = Query(7, description="Number of days to analyze")
):
    """Get performance overview for tool autonomy."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Total executions
                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                           AVG(latency_ms)::int as avg_latency
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '%s days'
                """, (days,))
                totals = cur.fetchone()

                # Executions by day
                cur.execute("""
                    SELECT DATE(executed_at) as date,
                           COUNT(*) as executions,
                           AVG(latency_ms)::int as avg_latency
                    FROM jarvis_tool_executions
                    WHERE executed_at > NOW() - INTERVAL '%s days'
                    GROUP BY DATE(executed_at)
                    ORDER BY date DESC
                """, (days,))
                daily = cur.fetchall()

                # Rule matches
                cur.execute("""
                    SELECT SUM(match_count) as total_matches
                    FROM jarvis_decision_rules
                """)
                rule_matches = cur.fetchone()

        return {
            "period_days": days,
            "totals": {
                "executions": totals["total"] or 0,
                "successful": totals["successful"] or 0,
                "avg_latency_ms": totals["avg_latency"] or 0,
                "success_rate": round((totals["successful"] or 0) / max(totals["total"] or 1, 1) * 100, 1)
            },
            "daily": [
                {
                    "date": d["date"].isoformat() if d["date"] else None,
                    "executions": d["executions"],
                    "avg_latency_ms": d["avg_latency"]
                }
                for d in daily
            ],
            "rule_matches_total": rule_matches["total_matches"] or 0
        }

    except Exception as e:
        log_with_context(logger, "error", "Performance query failed", error=str(e))
        return {"error": str(e)}


@router.get("/health")
def get_autonomy_health():
    """Quick health check for autonomy system."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                checks = {}

                # Check tables exist and have data
                cur.execute("SELECT COUNT(*) FROM jarvis_tools")
                checks["tools_registered"] = cur.fetchone()["count"] > 0

                cur.execute("SELECT COUNT(*) FROM jarvis_decision_rules WHERE enabled = true")
                checks["rules_active"] = cur.fetchone()["count"] > 0

                cur.execute("SELECT COUNT(*) FROM jarvis_tool_executions WHERE executed_at > NOW() - INTERVAL '1 hour'")
                checks["recent_executions"] = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) FROM jarvis_response_styles WHERE enabled = true")
                checks["styles_configured"] = cur.fetchone()["count"] > 0

        all_healthy = all([
            checks["tools_registered"],
            checks["rules_active"],
            checks["styles_configured"]
        ])

        return {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
