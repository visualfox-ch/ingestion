"""
Tool Meta Tools.

Tool registry management, tool chains, performance metrics.
Extracted from tools.py (Phase S6).
"""
from typing import Dict, Any, List
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.toolmeta")


def tool_list_available_tools(category: str = None, search: str = None, **kwargs) -> Dict[str, Any]:
    """
    List all available tools that Jarvis can use.

    Use this BEFORE trying to call a tool you're not sure about!
    This prevents hallucinating non-existent tools.

    Args:
        category: Filter by category (memory, calendar, email, system, dynamic, etc.)
        search: Search for tools by name or description

    Returns:
        List of available tool names with descriptions
    """
    log_with_context(logger, "info", "Tool: list_available_tools", category=category, search=search)
    metrics.inc("tool_list_available_tools")

    try:
        # Lazy import to avoid circular dependency
        from ..tools import TOOL_REGISTRY

        # Get all registered tools
        all_tools = list(TOOL_REGISTRY.keys())

        # Categorize tools
        categories = {
            "memory": ["search_knowledge", "remember_fact", "recall_facts", "remember_conversation_context",
                      "recall_conversation_history", "get_person_context", "propose_knowledge_update"],
            "calendar": ["get_calendar_events", "create_calendar_event"],
            "email": ["search_emails", "get_gmail_messages", "send_email"],
            "chat": ["search_chats"],
            "project": ["add_project", "list_projects", "update_project_status", "manage_thread"],
            "file": ["read_project_file", "write_project_file", "read_my_source_files", "read_own_code",
                    "list_own_source_files", "read_roadmap_and_tasks"],
            "system": ["system_health_check", "get_development_status", "validate_tool_registry",
                      "self_validation_dashboard", "self_validation_pulse", "mind_snapshot"],
            "dynamic": [],  # Populated below
            "ollama": ["delegate_ollama_task", "get_ollama_task_status", "ask_ollama", "ollama_python"],
            "python": ["execute_python", "request_python_sandbox"],
            "self_improvement": ["write_dynamic_tool", "promote_sandbox_tool", "system_pulse"],
        }

        # Find dynamic tools
        try:
            from .tool_loader import DynamicToolLoader
            dynamic_tools = list(DynamicToolLoader.get_all_tools().keys())
            categories["dynamic"] = dynamic_tools
        except Exception:
            pass

        # Filter by category
        if category:
            category_lower = category.lower()
            if category_lower in categories:
                filtered = categories[category_lower]
            else:
                filtered = [t for t in all_tools if category_lower in t.lower()]
        else:
            filtered = all_tools

        # Filter by search
        if search:
            search_lower = search.lower()
            filtered = [t for t in filtered if search_lower in t.lower()]

        # Build result with descriptions
        tool_info = []
        for tool_name in sorted(filtered):
            # Find description from TOOL_DEFINITIONS
            desc = ""
            for td in TOOL_DEFINITIONS:
                if td.get("name") == tool_name:
                    desc = td.get("description", "")[:100]
                    break
            tool_info.append({"name": tool_name, "description": desc})

        return {
            "total_tools": len(all_tools),
            "filtered_count": len(tool_info),
            "category": category,
            "search": search,
            "tools": tool_info[:50],  # Limit to 50
            "categories_available": list(categories.keys()),
            "hint": "Use category='self_improvement' to see tools for creating new tools!"
        }
    except Exception as e:
        log_with_context(logger, "error", "List available tools failed", error=str(e))
        return {"status": "error", "error": str(e)}


# ============ Tool Autonomy (Phase 19.6) ============

def tool_manage_tool_registry(
    action: str = None,
    tool_name: str = None,
    enabled: bool = None,
    description: str = None,
    category: str = None,
    reason: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Manage tool registry - enable/disable tools, update descriptions, assign categories.

    This gives Jarvis autonomous control over its own capabilities!

    Args:
        action: "enable", "disable", "update_description", "assign_category", "get_stats"
        tool_name: Name of the tool to manage
        enabled: For enable/disable actions
        description: New description for update_description
        category: Category name for assign_category
        reason: Why this change is being made

    Returns:
        Result of the management action
    """
    log_with_context(logger, "info", "Tool: manage_tool_registry", action=action, tool_name=tool_name)
    metrics.inc("tool_manage_tool_registry")

    if not action:
        return {"error": "action is required (enable, disable, update_description, assign_category, get_stats)"}

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        if action == "enable" and tool_name:
            return service.set_tool_enabled(tool_name, True, reason)

        elif action == "disable" and tool_name:
            return service.set_tool_enabled(tool_name, False, reason)

        elif action == "update_description" and tool_name and description:
            return service.update_tool_description(tool_name, description, reason)

        elif action == "assign_category" and tool_name and category:
            return service.assign_tool_to_category(tool_name, category)

        elif action == "get_stats":
            tools = service.get_enabled_tools()
            categories = service.get_categories()
            mods = service.get_recent_modifications(limit=5)
            return {
                "enabled_tools": len(tools),
                "categories": len(categories),
                "recent_modifications": mods
            }

        else:
            return {"error": f"Invalid action '{action}' or missing required parameters"}

    except Exception as e:
        log_with_context(logger, "error", "manage_tool_registry failed", error=str(e))
        return {"error": str(e)}


def tool_get_execution_stats(days: int = 7, limit: int = 20, **kwargs) -> Dict[str, Any]:
    """
    Get tool execution statistics - latency, success rates, usage patterns.

    Use this to analyze your tool performance and identify issues.

    Args:
        days: Number of days to analyze (default 7)
        limit: Max tools to show in rankings (default 20)

    Returns:
        Statistics about tool usage, performance, and failures
    """
    log_with_context(logger, "info", "Tool: get_execution_stats", days=days)
    metrics.inc("tool_get_execution_stats")

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()
        return service.get_tool_execution_stats(days=days, limit=limit)

    except Exception as e:
        log_with_context(logger, "error", "get_execution_stats failed", error=str(e))
        return {"error": str(e)}


# ============ Diagram Generation (Jarvis Wish: Visual Thinking) ============

def tool_get_tool_chain_suggestions(
    current_tools: List[str],
    context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Suggest next tool based on current sequence."""
    log_with_context(logger, "info", "Tool: get_tool_chain_suggestions", chain_length=len(current_tools))
    metrics.inc("tool_get_tool_chain_suggestions")

    try:
        from app.services.tool_chain_analyzer import get_tool_chain_analyzer
        analyzer = get_tool_chain_analyzer()
        return analyzer.suggest_next_tool(current_tools, context)
    except Exception as e:
        log_with_context(logger, "error", "get_tool_chain_suggestions failed", error=str(e))
        return {"error": str(e)}


def tool_get_popular_tool_chains(
    min_occurrences: int = 3,
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """Get popular tool chains."""
    log_with_context(logger, "info", "Tool: get_popular_tool_chains")
    metrics.inc("tool_get_popular_tool_chains")

    try:
        from app.services.tool_chain_analyzer import get_tool_chain_analyzer
        analyzer = get_tool_chain_analyzer()
        chains = analyzer.get_popular_chains(min_occurrences, limit)
        return {"chains": chains, "count": len(chains)}
    except Exception as e:
        log_with_context(logger, "error", "get_popular_tool_chains failed", error=str(e))
        return {"error": str(e)}


# T-21A-04: Tool Performance Learning
def tool_get_tool_performance(
    tool_name: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Get tool performance statistics."""
    log_with_context(logger, "info", "Tool: get_tool_performance", tool=tool_name)
    metrics.inc("tool_get_tool_performance")

    try:
        from app.services.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        stats = tracker.get_tool_stats(tool_name)
        return {"stats": stats, "count": len(stats)}
    except Exception as e:
        log_with_context(logger, "error", "get_tool_performance failed", error=str(e))
        return {"error": str(e)}


def tool_get_tool_recommendations(
    query_context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Get tool recommendations based on context."""
    log_with_context(logger, "info", "Tool: get_tool_recommendations")
    metrics.inc("tool_get_tool_recommendations")

    try:
        from app.services.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        return tracker.get_tool_recommendations(query_context)
    except Exception as e:
        log_with_context(logger, "error", "get_tool_recommendations failed", error=str(e))
        return {"error": str(e)}


# T-21B-01: CK-Track (Causal Knowledge)
