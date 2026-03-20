"""
Diagnostics Tools.

System health, memory diagnostics, benchmarks, quality metrics.
Extracted from tools.py (Phase S6).
"""
from typing import Dict, Any
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.diagnostics")


def tool_system_health_check(**kwargs) -> Dict[str, Any]:
    """Return internal health status for core services."""
    log_with_context(logger, "info", "Tool: system_health_check")
    metrics.inc("tool_system_health_check")

    try:
        from .routers import health_router
        return health_router.health_check()
    except Exception as e:
        log_with_context(logger, "error", "System health check failed", error=str(e))
        return {"error": str(e)}


def tool_memory_diagnostics(**kwargs) -> Dict[str, Any]:
    """Diagnose memory and context persistence."""
    log_with_context(logger, "info", "Tool: memory_diagnostics")
    metrics.inc("tool_memory_diagnostics")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.memory_diagnostics()
    except Exception as e:
        log_with_context(logger, "error", "Memory diagnostics failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_context_window_analysis(user_id: int = None, **kwargs) -> Dict[str, Any]:
    """Analyze context window usage patterns."""
    log_with_context(logger, "info", "Tool: context_window_analysis", user_id=user_id)
    metrics.inc("tool_context_window_analysis")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.context_window_analysis(user_id=user_id)
    except Exception as e:
        log_with_context(logger, "error", "Context window analysis failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_benchmark_tool_calls(hours: int = 24, **kwargs) -> Dict[str, Any]:
    """Benchmark tool calls over a time window."""
    log_with_context(logger, "info", "Tool: benchmark_tool_calls", hours=hours)
    metrics.inc("tool_benchmark_tool_calls")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.benchmark_tool_calls(hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Benchmark tool calls failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_compare_code_versions(module: str = "main", **kwargs) -> Dict[str, Any]:
    """Compare a module with recent git history."""
    log_with_context(logger, "info", "Tool: compare_code_versions", module=module)
    metrics.inc("tool_compare_code_versions")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.compare_code_versions(module=module)
    except Exception as e:
        log_with_context(logger, "error", "Compare code versions failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_conversation_continuity_test(user_id: int, **kwargs) -> Dict[str, Any]:
    """Test cross-session continuity for a user."""
    log_with_context(logger, "info", "Tool: conversation_continuity_test", user_id=user_id)
    metrics.inc("tool_conversation_continuity_test")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.conversation_continuity_test(user_id=user_id)
    except Exception as e:
        log_with_context(logger, "error", "Conversation continuity test failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_response_quality_metrics(hours: int = 168, **kwargs) -> Dict[str, Any]:
    """Analyze response quality over time."""
    log_with_context(logger, "info", "Tool: response_quality_metrics", hours=hours)
    metrics.inc("tool_response_quality_metrics")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.response_quality_metrics(hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Response quality metrics failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_proactivity_score(user_id: int = None, hours: int = 168, **kwargs) -> Dict[str, Any]:
    """Measure proactive behavior effectiveness."""
    log_with_context(logger, "info", "Tool: proactivity_score", user_id=user_id, hours=hours)
    metrics.inc("tool_proactivity_score")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.proactivity_score(user_id=user_id, hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Proactivity score failed", error=str(e))
        return {"status": "error", "error": str(e)}


