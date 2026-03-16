"""
Jarvis Tool Autonomy Service
Phase 19.6: Database-First Tool Management

This service gives Jarvis autonomous control over:
- Tool registration and configuration
- Category organization
- Prompt fragments
- Decision rules
- Response styles

Code provides the engine, database provides the configuration.
"""
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..postgres_state import get_conn
from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_autonomy")


class ToolAutonomyService:
    """
    Manages Jarvis's autonomous tool configuration.

    Philosophy:
    - Code = immutable engine/framework
    - Database = mutable configuration Jarvis controls

    Jarvis can:
    - Enable/disable tools
    - Modify tool descriptions
    - Create new tool categories
    - Adjust decision rules
    - Change response styles

    All changes are logged in jarvis_self_modifications for transparency.
    """

    _instance = None
    _cache = {}
    _cache_ttl = 60  # seconds
    _last_cache_refresh = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ==================== TOOL MANAGEMENT ====================

    def get_enabled_tools(self, category: str = None) -> List[Dict[str, Any]]:
        """
        Get all enabled tools, optionally filtered by category.

        Returns tool definitions in Claude-compatible format.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if category:
                        cur.execute("""
                            SELECT t.name, t.description, t.input_schema, t.category, t.priority
                            FROM jarvis_tools t
                            JOIN jarvis_tool_category_map m ON t.name = m.tool_name
                            WHERE t.enabled = true AND m.category_name = %s
                            ORDER BY t.priority DESC, t.name
                        """, (category,))
                    else:
                        cur.execute("""
                            SELECT name, description, input_schema, category, priority
                            FROM jarvis_tools
                            WHERE enabled = true
                            ORDER BY priority DESC, name
                        """)

                    rows = cur.fetchall()
                    return [
                        {
                            "name": row["name"],
                            "description": row["description"],
                            "input_schema": row["input_schema"],
                            "category": row["category"],
                            "priority": row["priority"]
                        }
                        for row in rows
                    ]
        except Exception as e:
            log_with_context(logger, "error", "Failed to get enabled tools", error=str(e))
            return []

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict,
        category: str = "general",
        source: str = "jarvis_created",
        created_by: str = "jarvis"
    ) -> Dict[str, Any]:
        """
        Register a new tool in the database.

        This is how Jarvis adds new tools to its registry without code changes.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_tools (name, description, input_schema, category, source, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                            description = EXCLUDED.description,
                            input_schema = EXCLUDED.input_schema,
                            category = EXCLUDED.category,
                            updated_at = NOW()
                        RETURNING id
                    """, (name, description, json.dumps(input_schema), category, source, created_by))

                    tool_id = cur.fetchone()["id"]

                    # Log the modification
                    self._log_modification(
                        cur, "jarvis_tools", tool_id, name,
                        "create" if cur.rowcount > 0 else "update",
                        new_value={"name": name, "description": description},
                        reason="Tool registration via autonomy service"
                    )

                    conn.commit()

                    return {"status": "registered", "tool_id": tool_id, "name": name}

        except Exception as e:
            log_with_context(logger, "error", "Failed to register tool", name=name, error=str(e))
            return {"status": "error", "error": str(e)}

    def set_tool_enabled(self, name: str, enabled: bool, reason: str = None) -> Dict[str, Any]:
        """
        Enable or disable a tool.

        Jarvis can disable tools it finds unhelpful or problematic.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_tools
                        SET enabled = %s, updated_at = NOW()
                        WHERE name = %s
                        RETURNING id
                    """, (enabled, name))

                    if cur.rowcount == 0:
                        return {"status": "error", "error": f"Tool {name} not found"}

                    tool_id = cur.fetchone()["id"]

                    self._log_modification(
                        cur, "jarvis_tools", tool_id, name,
                        "enable" if enabled else "disable",
                        old_value={"enabled": not enabled},
                        new_value={"enabled": enabled},
                        reason=reason or f"Tool {'enabled' if enabled else 'disabled'} by Jarvis"
                    )

                    conn.commit()

                    return {"status": "success", "name": name, "enabled": enabled}

        except Exception as e:
            log_with_context(logger, "error", "Failed to set tool enabled", name=name, error=str(e))
            return {"status": "error", "error": str(e)}

    def update_tool_description(self, name: str, description: str, reason: str = None) -> Dict[str, Any]:
        """
        Update a tool's description.

        Jarvis can improve tool descriptions based on what works better.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get old description
                    cur.execute("SELECT id, description FROM jarvis_tools WHERE name = %s", (name,))
                    row = cur.fetchone()
                    if not row:
                        return {"status": "error", "error": f"Tool {name} not found"}

                    tool_id = row["id"]
                    old_desc = row["description"]

                    cur.execute("""
                        UPDATE jarvis_tools
                        SET description = %s, updated_at = NOW()
                        WHERE name = %s
                    """, (description, name))

                    self._log_modification(
                        cur, "jarvis_tools", tool_id, name,
                        "update",
                        old_value={"description": old_desc},
                        new_value={"description": description},
                        reason=reason or "Description improved by Jarvis"
                    )

                    conn.commit()

                    return {"status": "success", "name": name, "description": description[:100]}

        except Exception as e:
            log_with_context(logger, "error", "Failed to update tool description", name=name, error=str(e))
            return {"status": "error", "error": str(e)}

    def record_tool_execution(
        self,
        tool_name: str,
        success: bool,
        latency_ms: int,
        session_id: str = None,
        user_id: int = None,
        error_message: str = None,
        input_summary: str = None,
        output_summary: str = None
    ) -> None:
        """
        Record a tool execution for pattern learning.

        This data helps Jarvis optimize tool selection and improve descriptions.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_tool_executions
                        (tool_name, success, latency_ms, session_id, user_id, error_message, input_summary, output_summary)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (tool_name, success, latency_ms, session_id, user_id, error_message, input_summary, output_summary))

                    # Update tool stats
                    cur.execute("""
                        UPDATE jarvis_tools
                        SET use_count = use_count + 1,
                            last_used_at = NOW(),
                            avg_latency_ms = COALESCE(
                                (avg_latency_ms * use_count + %s) / (use_count + 1),
                                %s
                            ),
                            success_rate = COALESCE(
                                (success_rate * use_count + %s::int) / (use_count + 1),
                                %s::int::real
                            )
                        WHERE name = %s
                    """, (latency_ms, latency_ms, success, success, tool_name))

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "warning", "Failed to record tool execution", error=str(e))

    # ==================== CATEGORY MANAGEMENT ====================

    def get_categories(self) -> List[Dict[str, Any]]:
        """Get all tool categories."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT name, display_name, description, keywords, enabled, priority
                        FROM jarvis_tool_categories
                        WHERE enabled = true
                        ORDER BY priority DESC
                    """)

                    return [
                        {
                            "name": row["name"],
                            "display_name": row["display_name"],
                            "description": row["description"],
                            "keywords": row["keywords"],
                            "enabled": row["enabled"],
                            "priority": row["priority"]
                        }
                        for row in cur.fetchall()
                    ]
        except Exception as e:
            log_with_context(logger, "error", "Failed to get categories", error=str(e))
            return []

    def create_category(
        self,
        name: str,
        display_name: str,
        description: str = None,
        keywords: List[str] = None,
        priority: int = 50
    ) -> Dict[str, Any]:
        """
        Create a new tool category.

        Jarvis can organize its tools however it finds most effective.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_tool_categories (name, display_name, description, keywords, priority)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            description = EXCLUDED.description,
                            keywords = EXCLUDED.keywords,
                            priority = EXCLUDED.priority,
                            updated_at = NOW()
                        RETURNING id
                    """, (name, display_name, description, json.dumps(keywords or []), priority))

                    cat_id = cur.fetchone()["id"]

                    self._log_modification(
                        cur, "jarvis_tool_categories", cat_id, name,
                        "create",
                        new_value={"name": name, "display_name": display_name},
                        reason="Category created by Jarvis"
                    )

                    conn.commit()

                    return {"status": "created", "category_id": cat_id, "name": name}

        except Exception as e:
            log_with_context(logger, "error", "Failed to create category", name=name, error=str(e))
            return {"status": "error", "error": str(e)}

    def assign_tool_to_category(self, tool_name: str, category_name: str, relevance: float = 1.0) -> Dict[str, Any]:
        """Assign a tool to a category."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_tool_category_map (tool_name, category_name, relevance_score)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (tool_name, category_name) DO UPDATE SET
                            relevance_score = EXCLUDED.relevance_score
                    """, (tool_name, category_name, relevance))

                    conn.commit()

                    return {"status": "assigned", "tool": tool_name, "category": category_name}

        except Exception as e:
            log_with_context(logger, "error", "Failed to assign tool to category", error=str(e))
            return {"status": "error", "error": str(e)}

    # ==================== PROMPT FRAGMENTS ====================

    def get_prompt_fragments(self, fragment_type: str = None, conditions: Dict = None) -> List[Dict[str, Any]]:
        """
        Get prompt fragments, optionally filtered.

        Used to dynamically build Jarvis's system prompt.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if fragment_type:
                        cur.execute("""
                            SELECT name, fragment_type, content, conditions, priority
                            FROM jarvis_prompt_fragments
                            WHERE enabled = true AND fragment_type = %s
                            ORDER BY priority DESC
                        """, (fragment_type,))
                    else:
                        cur.execute("""
                            SELECT name, fragment_type, content, conditions, priority
                            FROM jarvis_prompt_fragments
                            WHERE enabled = true
                            ORDER BY priority DESC
                        """)

                    fragments = []
                    for row in cur.fetchall():
                        frag_conditions = row["conditions"] or {}

                        # Check if conditions match
                        if conditions:
                            matches = all(
                                conditions.get(k) == v
                                for k, v in frag_conditions.items()
                            )
                            if not matches:
                                continue

                        fragments.append({
                            "name": row["name"],
                            "type": row["fragment_type"],
                            "content": row["content"],
                            "priority": row["priority"]
                        })

                    return fragments

        except Exception as e:
            log_with_context(logger, "error", "Failed to get prompt fragments", error=str(e))
            return []

    def add_prompt_fragment(
        self,
        name: str,
        fragment_type: str,
        content: str,
        conditions: Dict = None,
        priority: int = 50
    ) -> Dict[str, Any]:
        """
        Add a new prompt fragment.

        Jarvis can extend its own personality and instructions.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_prompt_fragments (name, fragment_type, content, conditions, priority)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                            content = EXCLUDED.content,
                            conditions = EXCLUDED.conditions,
                            priority = EXCLUDED.priority,
                            updated_at = NOW()
                        RETURNING id
                    """, (name, fragment_type, content, json.dumps(conditions or {}), priority))

                    frag_id = cur.fetchone()["id"]

                    self._log_modification(
                        cur, "jarvis_prompt_fragments", frag_id, name,
                        "create",
                        new_value={"type": fragment_type, "content": content[:100]},
                        reason="Prompt fragment added by Jarvis"
                    )

                    conn.commit()

                    return {"status": "created", "fragment_id": frag_id, "name": name}

        except Exception as e:
            log_with_context(logger, "error", "Failed to add prompt fragment", error=str(e))
            return {"status": "error", "error": str(e)}

    # ==================== DECISION RULES ====================

    def add_decision_rule(
        self,
        name: str,
        condition_type: str,
        condition_value: Any,
        action_type: str,
        action_value: Any,
        description: str = None,
        priority: int = 50
    ) -> Dict[str, Any]:
        """
        Add a decision rule for tool selection.

        Jarvis learns which tools work best in which situations.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_decision_rules
                        (name, description, condition_type, condition_value, action_type, action_value, priority)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (name, description, condition_type, json.dumps(condition_value),
                          action_type, json.dumps(action_value), priority))

                    rule_id = cur.fetchone()["id"]

                    self._log_modification(
                        cur, "jarvis_decision_rules", rule_id, name,
                        "create",
                        new_value={"condition_type": condition_type, "action_type": action_type},
                        reason="Decision rule created by Jarvis"
                    )

                    conn.commit()

                    return {"status": "created", "rule_id": rule_id, "name": name}

        except Exception as e:
            log_with_context(logger, "error", "Failed to add decision rule", error=str(e))
            return {"status": "error", "error": str(e)}

    def get_applicable_rules(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get decision rules that apply to the current context.

        Used during tool selection to customize behavior.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, name, condition_type, condition_value, action_type, action_value
                        FROM jarvis_decision_rules
                        WHERE enabled = true
                        ORDER BY priority DESC
                    """)

                    applicable = []
                    for row in cur.fetchall():
                        rule_id = row["id"]
                        name = row["name"]
                        cond_type = row["condition_type"]
                        cond_val = row["condition_value"]
                        act_type = row["action_type"]
                        act_val = row["action_value"]

                        # Check if rule matches
                        if self._matches_condition(cond_type, cond_val, context):
                            applicable.append({
                                "id": rule_id,
                                "name": name,
                                "action_type": act_type,
                                "action_value": act_val
                            })

                            # Update match count
                            cur.execute("""
                                UPDATE jarvis_decision_rules
                                SET match_count = match_count + 1, last_matched_at = NOW()
                                WHERE id = %s
                            """, (rule_id,))

                    conn.commit()
                    return applicable

        except Exception as e:
            log_with_context(logger, "error", "Failed to get applicable rules", error=str(e))
            return []

    def _matches_condition(self, cond_type: str, cond_val: Any, context: Dict) -> bool:
        """Check if a condition matches the current context."""
        try:
            if cond_type == "keyword":
                query = context.get("query", "").lower()
                keywords = cond_val if isinstance(cond_val, list) else [cond_val]
                return any(kw.lower() in query for kw in keywords)

            elif cond_type == "intent":
                return context.get("intent") == cond_val

            elif cond_type == "context":
                # Check if all context fields match
                for key, val in cond_val.items():
                    if context.get(key) != val:
                        return False
                return True

            elif cond_type == "pattern":
                import re
                query = context.get("query", "")
                return bool(re.search(cond_val, query, re.IGNORECASE))

            elif cond_type == "time_of_day":
                # cond_val = {"start": "09:00", "end": "17:00"}
                from datetime import datetime
                now = datetime.now().strftime("%H:%M")
                start = cond_val.get("start", "00:00")
                end = cond_val.get("end", "23:59")
                return start <= now <= end

            elif cond_type == "user_id":
                # cond_val = [123, 456] or 123
                user_id = context.get("user_id")
                if isinstance(cond_val, list):
                    return user_id in cond_val
                return user_id == cond_val

            elif cond_type == "source":
                # cond_val = "telegram" or ["telegram", "api"]
                source = context.get("source", "")
                if isinstance(cond_val, list):
                    return source in cond_val
                return source == cond_val

            return False

        except Exception:
            return False

    # ==================== RESPONSE STYLES ====================

    def get_response_style(self, style_name: str = None, conditions: Dict = None) -> Optional[Dict[str, Any]]:
        """Get a response style by name or matching conditions."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if style_name:
                        cur.execute("""
                            SELECT name, tone, verbosity, emoji_level, language, style_prompt
                            FROM jarvis_response_styles
                            WHERE name = %s AND enabled = true
                        """, (style_name,))
                    else:
                        # Get default or best matching
                        cur.execute("""
                            SELECT name, tone, verbosity, emoji_level, language, style_prompt, conditions
                            FROM jarvis_response_styles
                            WHERE enabled = true
                            ORDER BY is_default DESC
                        """)

                    row = cur.fetchone()
                    if row:
                        return {
                            "name": row["name"],
                            "tone": row["tone"],
                            "verbosity": row["verbosity"],
                            "emoji_level": row["emoji_level"],
                            "language": row["language"],
                            "style_prompt": row["style_prompt"]
                        }
                    return None

        except Exception as e:
            log_with_context(logger, "error", "Failed to get response style", error=str(e))
            return None

    # ==================== SELF-MODIFICATION LOGGING ====================

    def _log_modification(
        self,
        cursor,
        target_table: str,
        target_id: int,
        target_name: str,
        modification_type: str,
        old_value: Dict = None,
        new_value: Dict = None,
        reason: str = None,
        confidence: float = None,
        requires_approval: bool = False
    ) -> None:
        """Log a self-modification for transparency."""
        cursor.execute("""
            INSERT INTO jarvis_self_modifications
            (target_table, target_id, target_name, modification_type, old_value, new_value, reason, confidence, requires_approval)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            target_table, target_id, target_name, modification_type,
            json.dumps(old_value) if old_value else None,
            json.dumps(new_value) if new_value else None,
            reason, confidence, requires_approval
        ))

    def get_recent_modifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent self-modifications for review."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, target_table, target_name, modification_type, reason, created_at,
                               requires_approval, approved_at
                        FROM jarvis_self_modifications
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                    return [
                        {
                            "id": row["id"],
                            "table": row["target_table"],
                            "name": row["target_name"],
                            "type": row["modification_type"],
                            "reason": row["reason"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                            "requires_approval": row["requires_approval"],
                            "approved": row["approved_at"] is not None
                        }
                        for row in cur.fetchall()
                    ]
        except Exception as e:
            log_with_context(logger, "error", "Failed to get modifications", error=str(e))
            return []

    # ==================== SYNC FROM CODE ====================

    def sync_tools_from_code(self, tool_definitions: List[Dict]) -> Dict[str, Any]:
        """
        Sync tools from code (TOOL_DEFINITIONS) to database.

        Called at startup to ensure DB has all code-defined tools.
        Preserves any DB-only customizations.
        """
        try:
            synced = 0
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for tool_def in tool_definitions:
                        name = tool_def.get("name")
                        if not name:
                            continue

                        cur.execute("""
                            INSERT INTO jarvis_tools (name, description, input_schema, source)
                            VALUES (%s, %s, %s, 'code')
                            ON CONFLICT (name) DO UPDATE SET
                                input_schema = EXCLUDED.input_schema,
                                updated_at = NOW()
                            WHERE jarvis_tools.source = 'code'
                        """, (
                            name,
                            tool_def.get("description", ""),
                            json.dumps(tool_def.get("input_schema", {}))
                        ))
                        synced += 1

                    conn.commit()

            log_with_context(logger, "info", "Synced tools from code", synced=synced)
            return {"status": "synced", "count": synced}

        except Exception as e:
            log_with_context(logger, "error", "Failed to sync tools from code", error=str(e))
            return {"status": "error", "error": str(e)}

    # ==================== EXECUTION STATS ====================

    def get_tool_execution_stats(self, days: int = 7, limit: int = 20) -> Dict[str, Any]:
        """
        Get tool execution statistics for analysis.

        Returns:
            Statistics about tool usage, latency, and success rates.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get overall stats
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_executions,
                            COUNT(CASE WHEN success THEN 1 END) as successful,
                            AVG(latency_ms) as avg_latency,
                            MAX(latency_ms) as max_latency
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    overall = cur.fetchone()

                    # Get per-tool stats
                    cur.execute("""
                        SELECT
                            tool_name,
                            COUNT(*) as executions,
                            COUNT(CASE WHEN success THEN 1 END) as successful,
                            ROUND(AVG(latency_ms)::numeric, 0) as avg_latency_ms,
                            ROUND((COUNT(CASE WHEN success THEN 1 END)::float / COUNT(*) * 100)::numeric, 1) as success_rate
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days'
                        GROUP BY tool_name
                        ORDER BY executions DESC
                        LIMIT %s
                    """, (days, limit))

                    tool_stats = [
                        {
                            "tool": row["tool_name"],
                            "executions": row["executions"],
                            "successful": row["successful"],
                            "avg_latency_ms": int(row["avg_latency_ms"]) if row["avg_latency_ms"] else 0,
                            "success_rate": float(row["success_rate"]) if row["success_rate"] else 0
                        }
                        for row in cur.fetchall()
                    ]

                    # Get slowest tools
                    cur.execute("""
                        SELECT tool_name, ROUND(AVG(latency_ms)::numeric, 0) as avg_latency
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days'
                        GROUP BY tool_name
                        HAVING COUNT(*) >= 5
                        ORDER BY avg_latency DESC
                        LIMIT 5
                    """, (days,))

                    slowest = [
                        {"tool": row["tool_name"], "avg_latency_ms": int(row["avg_latency"])}
                        for row in cur.fetchall()
                    ]

                    # Get most failing tools
                    cur.execute("""
                        SELECT tool_name, COUNT(*) as failures
                        FROM jarvis_tool_executions
                        WHERE executed_at > NOW() - INTERVAL '%s days' AND NOT success
                        GROUP BY tool_name
                        ORDER BY failures DESC
                        LIMIT 5
                    """, (days,))

                    most_failing = [
                        {"tool": row["tool_name"], "failures": row["failures"]}
                        for row in cur.fetchall()
                    ]

                    return {
                        "period_days": days,
                        "overall": {
                            "total_executions": overall["total_executions"] if overall else 0,
                            "successful": overall["successful"] if overall else 0,
                            "avg_latency_ms": int(overall["avg_latency"]) if overall and overall["avg_latency"] else 0,
                            "max_latency_ms": int(overall["max_latency"]) if overall and overall["max_latency"] else 0
                        },
                        "top_tools": tool_stats,
                        "slowest_tools": slowest,
                        "most_failing": most_failing
                    }

        except Exception as e:
            log_with_context(logger, "error", "Failed to get execution stats", error=str(e))
            return {"error": str(e)}


# Singleton instance
_service = None

def get_tool_autonomy_service() -> ToolAutonomyService:
    """Get the singleton ToolAutonomyService instance."""
    global _service
    if _service is None:
        _service = ToolAutonomyService()
    return _service
