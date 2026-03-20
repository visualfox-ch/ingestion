"""
Introspection Tools.

Self-knowledge, capabilities, development status, validation.
Extracted from tools.py (Phase S5).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import os

from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode, internal_error

logger = get_logger("jarvis.tools.introspection")

BRAIN_PATH = os.getenv("BRAIN_PATH", "/brain")


def tool_introspect_capabilities(
    include_catalog: bool = False,
    max_lines: int = 120,
    **kwargs
) -> Dict[str, Any]:
    """Return Jarvis capability metadata from canonical files."""
    log_with_context(logger, "info", "Tool: introspect_capabilities", include_catalog=include_catalog)
    metrics.inc("tool_introspect_capabilities")

    cap_path = "/brain/system/docs/CAPABILITIES.json"
    catalog_path = "/brain/system/docs/CAPABILITY_CATALOG.md"

    result: Dict[str, Any] = {
        "capabilities_json": {},
        "capability_catalog": {},
    }

    # Read CAPABILITIES.json directly (entire file, not truncated)
    try:
        with open(cap_path, "r", encoding="utf-8") as f:
            cap_json = json.load(f)
        tools = cap_json.get("tools", [])
        result["capabilities_json"] = {
            "version": cap_json.get("version"),
            "build_timestamp": cap_json.get("build_timestamp"),
            "tool_count": len(tools),
            "tool_names_sample": [t.get("name") for t in tools[:10]]
        }
    except Exception as e:
        log_with_context(logger, "error", "Failed to read CAPABILITIES.json", error=str(e))
        result["capabilities_json"] = {"error": str(e)}

    try:
        catalog_result = tool_read_project_file(catalog_path, max_lines=max_lines)
        if catalog_result.get("success"):
            result["capability_catalog"] = {
                "present": True,
                "file_size": catalog_result.get("file_size"),
                "lines_read": catalog_result.get("lines_read"),
                "truncated": catalog_result.get("truncated")
            }
            if include_catalog:
                result["capability_catalog"]["preview"] = catalog_result.get("content", "")
        else:
            result["capability_catalog"] = {
                "present": False,
                "error": catalog_result.get("error", "read_failed")
            }
    except Exception as e:
        result["capability_catalog"] = {"present": False, "error": str(e)}

    return result


def tool_get_development_status(**kwargs) -> Dict[str, Any]:
    """Return current development status (phase, active team, next phase)."""
    try:
        from .dev_status import get_development_status
        result = get_development_status()
        metrics.inc("tool_get_development_status")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool get_development_status failed", error=str(e))
        return {"error": str(e)}


def tool_mind_snapshot(**kwargs) -> Dict[str, Any]:
    """Quick 'mind' snapshot: labels, registry, and collection counts."""
    try:
        from qdrant_client import QdrantClient

        collections = kwargs.get("collections", "jarvis_work,jarvis_private,jarvis_comms")
        if isinstance(collections, str):
            collection_list = [c.strip() for c in collections.split(",") if c.strip()]
        else:
            collection_list = list(collections or [])

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        counts = {}
        for collection in collection_list:
            res = client.count(collection_name=collection)
            counts[collection] = res.count if res else 0

        registry = get_registry_entries(status="active")
        schema_map = get_label_schema()

        result = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "collections": counts,
            "label_schema_keys": len(schema_map),
            "label_registry_active": len(registry),
            "label_registry_keys": [r.get("key") for r in registry],
            "tool_count": len(TOOL_REGISTRY),
        }
        metrics.inc("tool_mind_snapshot")
        return {"success": True, "snapshot": result}
    except Exception as e:
        log_with_context(logger, "error", "Tool mind_snapshot failed", error=str(e))
        return {"error": str(e)}


def tool_self_validation_dashboard(**kwargs) -> Dict[str, Any]:
    """Return combined self-validation dashboard metrics."""
    log_with_context(logger, "info", "Tool: self_validation_dashboard")
    metrics.inc("tool_self_validation_dashboard")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.dashboard_snapshot()
    except Exception as e:
        log_with_context(logger, "error", "Self validation dashboard failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_self_validation_pulse(**kwargs) -> Dict[str, Any]:
    """Quick health pulse for real-time monitoring (<50ms target)."""
    log_with_context(logger, "info", "Tool: self_validation_pulse")
    metrics.inc("tool_self_validation_pulse")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.quick_pulse()
    except Exception as e:
        log_with_context(logger, "error", "Self validation pulse failed", error=str(e))
        return {"status": "error", "error": str(e)}


# Dynamic Tool Creation tools MOVED to tool_modules/sandbox_tools.py (T006 refactor)
# Implementations: tool_write_dynamic_tool, tool_promote_sandbox_tool


# Learning & Memory tools MOVED to tool_modules/learning_memory_tools.py (T006 refactor)
# Implementations: tool_record_learning, tool_get_learnings, tool_store_context,
#                  tool_recall_context, tool_forget_context, tool_record_learnings_batch, tool_store_contexts_batch



