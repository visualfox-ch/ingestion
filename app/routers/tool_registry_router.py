"""
Tool Registry Router - Phase 19.5

API endpoints for managing the tool registry.
Allows Jarvis to enable/disable tools and view usage stats.
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from ..observability import get_logger

logger = get_logger("jarvis.tool_registry_router")
router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/registry/summary")
def get_registry_summary():
    """Get summary of tool registry."""
    from ..services.tool_registry import get_registry_summary
    return get_registry_summary()


@router.get("/registry/stats")
def get_tool_stats(
    category: Optional[str] = Query(None, description="Filter by category"),
    min_usage: int = Query(0, description="Minimum usage count")
):
    """Get tool usage statistics."""
    from ..services.tool_registry import get_tool_stats
    stats = get_tool_stats(category, min_usage)
    return {"stats": stats, "count": len(stats)}


@router.get("/registry/enabled")
def get_enabled_tools():
    """Get list of enabled tools."""
    from ..services.tool_registry import get_enabled_tools
    tools = get_enabled_tools()
    return {"tools": tools, "count": len(tools)}


@router.get("/registry/disabled")
def get_disabled_tools():
    """Get list of disabled tools with reasons."""
    from ..services.tool_registry import get_disabled_tools
    tools = get_disabled_tools()
    return {"tools": tools, "count": len(tools)}


@router.get("/registry/unused")
def get_unused_tools(days: int = Query(7, description="Days threshold")):
    """Get tools that haven't been used recently."""
    from ..services.tool_registry import get_unused_tools
    tools = get_unused_tools(days)
    return {"tools": tools, "count": len(tools)}


@router.post("/registry/{tool_name}/enable")
def enable_tool(tool_name: str):
    """Enable a tool."""
    from ..services.tool_registry import set_tool_enabled
    success = set_tool_enabled(tool_name, True)
    if not success:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return {"status": "enabled", "tool": tool_name}


@router.post("/registry/{tool_name}/disable")
def disable_tool(
    tool_name: str,
    reason: Optional[str] = Query(None, description="Reason for disabling")
):
    """Disable a tool."""
    from ..services.tool_registry import set_tool_enabled
    success = set_tool_enabled(tool_name, False, reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return {"status": "disabled", "tool": tool_name, "reason": reason}


@router.post("/registry/sync")
def sync_registry():
    """Sync tool registry from code definitions."""
    from ..services.tool_registry import sync_tools_from_code
    from ..tools import get_tool_definitions

    definitions = get_tool_definitions()
    result = sync_tools_from_code(definitions)
    return result


@router.get("/registry/{tool_name}")
def get_tool_info(tool_name: str):
    """Get info about a specific tool."""
    from ..services.tool_registry import _get_conn
    import json

    try:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT * FROM tool_registry WHERE name = ?",
            (tool_name,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

        info = dict(row)
        if info.get("schema_json"):
            info["schema"] = json.loads(info["schema_json"])
            del info["schema_json"]

        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
