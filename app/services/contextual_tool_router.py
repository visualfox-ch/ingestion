"""
Contextual Tool Router - Phase 3.1

Routes tool calls based on learned context patterns:
- Learns which tools work best for which contexts
- Provides routing recommendations
- Tracks routing effectiveness
- Supports conditional tool execution
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json
import hashlib

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)

# Default routing weights
DEFAULT_WEIGHTS = {
    'context_match': 0.4,
    'success_rate': 0.3,
    'recency': 0.2,
    'frequency': 0.1
}


class ContextualToolRouter:
    """
    Routes tool selection based on context patterns.

    Learns from historical tool usage which tools work best
    in which contexts, and provides intelligent routing.
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure routing tables exist."""
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tool_routing_rules (
                        id SERIAL PRIMARY KEY,
                        rule_name VARCHAR(100) UNIQUE NOT NULL,
                        context_conditions JSONB NOT NULL,
                        target_tools JSONB NOT NULL,
                        fallback_tool VARCHAR(100),
                        priority INTEGER DEFAULT 50,
                        is_active BOOLEAN DEFAULT true,
                        success_count INTEGER DEFAULT 0,
                        fail_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_routing_rules_active
                        ON tool_routing_rules(is_active, priority DESC);

                    CREATE TABLE IF NOT EXISTS tool_routing_history (
                        id SERIAL PRIMARY KEY,
                        query_hash VARCHAR(64),
                        context_snapshot JSONB,
                        rule_applied VARCHAR(100),
                        tool_selected VARCHAR(100) NOT NULL,
                        alternative_tools JSONB DEFAULT '[]'::jsonb,
                        was_successful BOOLEAN,
                        routing_score FLOAT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_routing_history_tool
                        ON tool_routing_history(tool_selected);
                    CREATE INDEX IF NOT EXISTS idx_routing_history_created
                        ON tool_routing_history(created_at DESC);

                    CREATE TABLE IF NOT EXISTS context_tool_affinity (
                        id SERIAL PRIMARY KEY,
                        context_key VARCHAR(200) NOT NULL,
                        tool_name VARCHAR(100) NOT NULL,
                        affinity_score FLOAT DEFAULT 0.5,
                        success_count INTEGER DEFAULT 0,
                        total_count INTEGER DEFAULT 0,
                        last_used_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(context_key, tool_name)
                    );

                    CREATE INDEX IF NOT EXISTS idx_tool_affinity_context
                        ON context_tool_affinity(context_key);
                    CREATE INDEX IF NOT EXISTS idx_tool_affinity_score
                        ON context_tool_affinity(affinity_score DESC);
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def create_routing_rule(
        self,
        rule_name: str,
        context_conditions: Dict[str, Any],
        target_tools: List[str],
        fallback_tool: str = None,
        priority: int = 50
    ) -> Dict[str, Any]:
        """
        Create a routing rule for conditional tool selection.

        Args:
            rule_name: Unique name for the rule
            context_conditions: Conditions that trigger this rule
                e.g., {"keywords": ["email", "send"], "session_type": "communication"}
            target_tools: List of tools to route to (in priority order)
            fallback_tool: Tool to use if primary tools fail
            priority: Rule priority (higher = checked first)
        """
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    INSERT INTO tool_routing_rules
                    (rule_name, context_conditions, target_tools, fallback_tool, priority)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (rule_name) DO UPDATE SET
                        context_conditions = EXCLUDED.context_conditions,
                        target_tools = EXCLUDED.target_tools,
                        fallback_tool = EXCLUDED.fallback_tool,
                        priority = EXCLUDED.priority,
                        updated_at = NOW()
                    RETURNING id
                """, (
                    rule_name,
                    json.dumps(context_conditions),
                    json.dumps(target_tools),
                    fallback_tool,
                    priority
                ))

                row = cur.fetchone()
                return {
                    "success": True,
                    "rule_id": row['id'],
                    "rule_name": rule_name,
                    "tools": target_tools
                }

        except Exception as e:
            logger.error(f"Create routing rule failed: {e}")
            return {"success": False, "error": str(e)}

    def route_tool(
        self,
        query: str,
        context: Dict[str, Any] = None,
        available_tools: List[str] = None
    ) -> Dict[str, Any]:
        """
        Route to the best tool based on query and context.

        Args:
            query: The user query
            context: Current context (session_type, recent_tools, etc.)
            available_tools: List of available tools to choose from

        Returns:
            Dict with recommended tool and alternatives
        """
        try:
            context = context or {}
            query_lower = query.lower()

            recommendations = []

            with get_dict_cursor() as cur:
                # 1. Check explicit routing rules
                cur.execute("""
                    SELECT rule_name, context_conditions, target_tools, fallback_tool
                    FROM tool_routing_rules
                    WHERE is_active = true
                    ORDER BY priority DESC
                """)

                for row in cur.fetchall():
                    conditions = row['context_conditions']
                    if self._matches_conditions(query_lower, context, conditions):
                        target_tools = row['target_tools']
                        if available_tools:
                            target_tools = [t for t in target_tools if t in available_tools]

                        if target_tools:
                            return {
                                "success": True,
                                "routing_type": "rule",
                                "rule_name": row['rule_name'],
                                "recommended_tool": target_tools[0],
                                "alternatives": target_tools[1:3],
                                "fallback": row['fallback_tool']
                            }

                # 2. Check learned context-tool affinity
                context_keys = self._extract_context_keys(query_lower, context)

                for key in context_keys:
                    cur.execute("""
                        SELECT tool_name, affinity_score, success_count, total_count
                        FROM context_tool_affinity
                        WHERE context_key = %s
                        AND affinity_score > 0.3
                        ORDER BY affinity_score DESC
                        LIMIT 5
                    """, (key,))

                    for row in cur.fetchall():
                        tool = row['tool_name']
                        if available_tools is None or tool in available_tools:
                            recommendations.append({
                                "tool": tool,
                                "score": row['affinity_score'],
                                "context_key": key,
                                "uses": row['total_count']
                            })

                # 3. Deduplicate and rank
                seen_tools = set()
                unique_recs = []
                for rec in sorted(recommendations, key=lambda x: x['score'], reverse=True):
                    if rec['tool'] not in seen_tools:
                        seen_tools.add(rec['tool'])
                        unique_recs.append(rec)

                if unique_recs:
                    return {
                        "success": True,
                        "routing_type": "affinity",
                        "recommended_tool": unique_recs[0]['tool'],
                        "confidence": unique_recs[0]['score'],
                        "alternatives": [r['tool'] for r in unique_recs[1:4]],
                        "context_match": unique_recs[0]['context_key']
                    }

                return {
                    "success": True,
                    "routing_type": "none",
                    "recommended_tool": None,
                    "message": "No routing match found"
                }

        except Exception as e:
            logger.error(f"Route tool failed: {e}")
            return {"success": False, "error": str(e)}

    def _matches_conditions(
        self,
        query: str,
        context: Dict[str, Any],
        conditions: Dict[str, Any]
    ) -> bool:
        """Check if query/context matches rule conditions."""
        # Check keyword conditions
        if 'keywords' in conditions:
            keywords = conditions['keywords']
            if not any(kw in query for kw in keywords):
                return False

        # Check session type
        if 'session_type' in conditions:
            if context.get('session_type') != conditions['session_type']:
                return False

        # Check recent tools
        if 'after_tool' in conditions:
            recent = context.get('recent_tools', [])
            if conditions['after_tool'] not in recent[:3]:
                return False

        # Check time conditions
        if 'time_range' in conditions:
            hour = datetime.now().hour
            start, end = conditions['time_range']
            if not (start <= hour <= end):
                return False

        return True

    def _extract_context_keys(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> List[str]:
        """Extract context keys for affinity lookup."""
        keys = []

        # Session type key
        if context.get('session_type'):
            keys.append(f"session:{context['session_type']}")

        # Keyword-based keys
        keywords = ['email', 'calendar', 'search', 'code', 'file', 'reminder',
                   'note', 'task', 'project', 'document', 'message', 'send']
        for kw in keywords:
            if kw in query:
                keys.append(f"keyword:{kw}")

        # Recent tool key
        recent = context.get('recent_tools', [])
        if recent:
            keys.append(f"after:{recent[0]}")

        return keys

    def record_routing_outcome(
        self,
        query: str,
        tool_selected: str,
        was_successful: bool,
        context: Dict[str, Any] = None,
        rule_applied: str = None
    ) -> Dict[str, Any]:
        """
        Record the outcome of a tool routing decision.

        Updates affinity scores based on success/failure.
        """
        try:
            context = context or {}
            query_hash = hashlib.md5(query.encode()).hexdigest()

            with get_dict_cursor() as cur:
                # Record history
                cur.execute("""
                    INSERT INTO tool_routing_history
                    (query_hash, context_snapshot, rule_applied, tool_selected, was_successful)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    query_hash,
                    json.dumps(context),
                    rule_applied,
                    tool_selected,
                    was_successful
                ))

                # Update rule stats if applicable
                if rule_applied:
                    if was_successful:
                        cur.execute("""
                            UPDATE tool_routing_rules
                            SET success_count = success_count + 1, updated_at = NOW()
                            WHERE rule_name = %s
                        """, (rule_applied,))
                    else:
                        cur.execute("""
                            UPDATE tool_routing_rules
                            SET fail_count = fail_count + 1, updated_at = NOW()
                            WHERE rule_name = %s
                        """, (rule_applied,))

                # Update context-tool affinity
                context_keys = self._extract_context_keys(query.lower(), context)

                for key in context_keys:
                    cur.execute("""
                        INSERT INTO context_tool_affinity
                        (context_key, tool_name, success_count, total_count, affinity_score)
                        VALUES (%s, %s, %s, 1, %s)
                        ON CONFLICT (context_key, tool_name) DO UPDATE SET
                            success_count = context_tool_affinity.success_count + %s,
                            total_count = context_tool_affinity.total_count + 1,
                            affinity_score = (context_tool_affinity.success_count + %s)::float /
                                           (context_tool_affinity.total_count + 1),
                            last_used_at = NOW()
                    """, (
                        key,
                        tool_selected,
                        1 if was_successful else 0,
                        1.0 if was_successful else 0.0,
                        1 if was_successful else 0,
                        1 if was_successful else 0
                    ))

            return {
                "success": True,
                "recorded": True,
                "tool": tool_selected,
                "outcome": "success" if was_successful else "failure"
            }

        except Exception as e:
            logger.error(f"Record routing outcome failed: {e}")
            return {"success": False, "error": str(e)}

    def get_routing_rules(self, active_only: bool = True) -> Dict[str, Any]:
        """Get all routing rules."""
        try:
            with get_dict_cursor() as cur:
                if active_only:
                    cur.execute("""
                        SELECT rule_name, context_conditions, target_tools,
                               fallback_tool, priority, success_count, fail_count
                        FROM tool_routing_rules
                        WHERE is_active = true
                        ORDER BY priority DESC
                    """)
                else:
                    cur.execute("""
                        SELECT rule_name, context_conditions, target_tools,
                               fallback_tool, priority, is_active, success_count, fail_count
                        FROM tool_routing_rules
                        ORDER BY priority DESC
                    """)

                rules = []
                for row in cur.fetchall():
                    total = row['success_count'] + row['fail_count']
                    success_rate = (row['success_count'] / total * 100) if total > 0 else 0
                    rules.append({
                        "name": row['rule_name'],
                        "conditions": row['context_conditions'],
                        "tools": row['target_tools'],
                        "fallback": row['fallback_tool'],
                        "priority": row['priority'],
                        "success_rate": round(success_rate, 1),
                        "uses": total
                    })

                return {"success": True, "rules": rules}

        except Exception as e:
            logger.error(f"Get routing rules failed: {e}")
            return {"success": False, "error": str(e)}

    def get_tool_affinities(
        self,
        tool_name: str = None,
        context_key: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get learned tool affinities."""
        try:
            with get_dict_cursor() as cur:
                if tool_name:
                    cur.execute("""
                        SELECT context_key, affinity_score, success_count, total_count
                        FROM context_tool_affinity
                        WHERE tool_name = %s
                        ORDER BY affinity_score DESC
                        LIMIT %s
                    """, (tool_name, limit))

                    affinities = [{
                        "context": row['context_key'],
                        "score": round(row['affinity_score'], 3),
                        "successes": row['success_count'],
                        "total": row['total_count']
                    } for row in cur.fetchall()]

                    return {
                        "success": True,
                        "tool": tool_name,
                        "affinities": affinities
                    }

                elif context_key:
                    cur.execute("""
                        SELECT tool_name, affinity_score, success_count, total_count
                        FROM context_tool_affinity
                        WHERE context_key = %s
                        ORDER BY affinity_score DESC
                        LIMIT %s
                    """, (context_key, limit))

                    affinities = [{
                        "tool": row['tool_name'],
                        "score": round(row['affinity_score'], 3),
                        "successes": row['success_count'],
                        "total": row['total_count']
                    } for row in cur.fetchall()]

                    return {
                        "success": True,
                        "context": context_key,
                        "affinities": affinities
                    }

                else:
                    # Top affinities overall
                    cur.execute("""
                        SELECT context_key, tool_name, affinity_score, total_count
                        FROM context_tool_affinity
                        WHERE affinity_score > 0.5
                        ORDER BY affinity_score DESC
                        LIMIT %s
                    """, (limit,))

                    affinities = [{
                        "context": row['context_key'],
                        "tool": row['tool_name'],
                        "score": round(row['affinity_score'], 3),
                        "uses": row['total_count']
                    } for row in cur.fetchall()]

                    return {
                        "success": True,
                        "top_affinities": affinities
                    }

        except Exception as e:
            logger.error(f"Get tool affinities failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[ContextualToolRouter] = None


def get_contextual_tool_router() -> ContextualToolRouter:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = ContextualToolRouter()
    return _service
