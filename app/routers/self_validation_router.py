"""
Self-Validation Router

API endpoints for Jarvis self-monitoring and validation.
Phase 19: Self-Awareness Tools
"""

from fastapi import APIRouter, Query
from typing import Dict, Any, Optional

router = APIRouter(prefix="/self", tags=["self-validation"])


# =============================================================================
# PHASE 1: Quick Wins
# =============================================================================

@router.get("/pulse", response_model=Dict[str, Any])
async def quick_pulse():
    """
    Lightweight health check for real-time monitoring.
    Target: <50ms response time.

    Uses caching and minimal system calls for speed.
    Ideal for dashboards and frequent polling.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.quick_pulse()


@router.get("/health/detailed", response_model=Dict[str, Any])
async def get_detailed_system_health():
    """
    Get comprehensive system health metrics.

    Returns CPU, memory, disk usage, process info, and uptime.
    More detailed than /health endpoint.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.get_system_health()


@router.get("/tools/validate", response_model=Dict[str, Any])
async def validate_tool_registry():
    """
    Validate all tools in TOOL_REGISTRY.

    Returns tool count, categorization, and any configuration issues.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.validate_tool_registry()


@router.get("/metrics/response", response_model=Dict[str, Any])
async def get_response_metrics(
    hours: int = Query(default=24, ge=1, le=720, description="Hours to analyze")
):
    """
    Get response performance metrics.

    Returns latency stats, token usage, and tool call distribution.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.get_response_metrics(hours=hours)


# =============================================================================
# PHASE 2: Medium Complexity
# =============================================================================

@router.get("/memory/diagnostics", response_model=Dict[str, Any])
async def get_memory_diagnostics():
    """
    Diagnose memory and context persistence.

    Returns session stats, context table status, and diagnostic messages.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.memory_diagnostics()


@router.get("/context/analysis", response_model=Dict[str, Any])
async def analyze_context_window(
    user_id: int = Query(default=None, description="Optional user to analyze")
):
    """
    Analyze context window usage patterns.

    Returns token usage patterns, context sizes, and recommendations.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.context_window_analysis(user_id=user_id)


# =============================================================================
# PHASE 3: Advanced
# =============================================================================

@router.get("/tools/benchmark", response_model=Dict[str, Any])
async def benchmark_tool_calls(
    hours: int = Query(default=24, ge=1, le=720, description="Hours to analyze")
):
    """
    Benchmark tool call performance.

    Returns per-tool latency, success rates, and performance trends.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.benchmark_tool_calls(hours=hours)


@router.get("/code/versions", response_model=Dict[str, Any])
async def compare_code_versions(
    module: str = Query(default="main", description="Module to compare (main, agent, tools, etc.)")
):
    """
    Compare current code with git history.

    Returns recent changes and diff summary for the specified module.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.compare_code_versions(module=module)


@router.get("/continuity/{user_id}", response_model=Dict[str, Any])
async def test_conversation_continuity(user_id: int):
    """
    Test cross-session memory continuity for a user.

    Returns memory gaps, continuity score, and recommendations.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.conversation_continuity_test(user_id=user_id)


# =============================================================================
# PHASE 4: AI/ML Metrics
# =============================================================================

@router.get("/quality/metrics", response_model=Dict[str, Any])
async def get_quality_metrics(
    hours: int = Query(default=168, ge=1, le=720, description="Hours to analyze (default 7 days)")
):
    """
    Analyze response quality over time.

    Returns quality indicators, feedback stats, and improvement trends.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.response_quality_metrics(hours=hours)


@router.get("/proactivity/score", response_model=Dict[str, Any])
async def get_proactivity_score(
    user_id: int = Query(default=None, description="Optional specific user"),
    hours: int = Query(default=168, ge=1, le=720, description="Hours to analyze")
):
    """
    Measure proactive behavior effectiveness.

    Returns proactive hints sent, acceptance rate, and timing analysis.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.proactivity_score(user_id=user_id, hours=hours)


# =============================================================================
# COMBINED DASHBOARD
# =============================================================================

@router.get("/dashboard", response_model=Dict[str, Any])
async def get_self_validation_dashboard():
    """
    Get combined self-validation dashboard.

    Returns a summary of all self-validation metrics in one call.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.dashboard_snapshot()


@router.get("/reality-check-snapshot", response_model=Dict[str, Any])
async def get_reality_check_snapshot(
    hours: int = Query(default=168, ge=1, le=720, description="Hours to analyze"),
    days: int = Query(default=7, ge=1, le=90, description="Days window for continuity checks"),
    user_id: Optional[int] = Query(default=None, description="Optional user for continuity checks"),
):
    """
    Return a compact deploy-time reality-check snapshot.

    Payload includes the four dimensions: agency, memory, proactive, calibration,
    each with pass/warn/fail/no_data metric statuses.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.reality_check_snapshot(hours=hours, days=days, user_id=user_id)


# =============================================================================
# T-RI-06 Step 3: Calibration Feedback
# =============================================================================

@router.post("/calibration-feedback", response_model=Dict[str, Any])
async def submit_calibration_feedback(
    confidence: float = Query(..., ge=0.0, le=1.0, description="Predicted confidence [0..1]"),
    actual_correct: bool = Query(..., description="Whether the prediction was correct"),
    category: Optional[str] = Query(None, description="Optional label/category"),
):
    """
    Submit a calibration data point (confidence vs actual outcome).

    Used to build an ECE (Expected Calibration Error) baseline from real
    outcomes. Stored in SQLite state DB and read as fallback in
    /self/reality-check-snapshot when the uncertainty_quantifier has no data.
    """
    from ..services.self_validation_service import get_self_validation_service

    service = get_self_validation_service()
    return service.save_calibration_feedback(
        confidence=confidence,
        actual_correct=actual_correct,
        category=category,
    )


# =============================================================================
# PHASE 19: SCHEDULED SELF-DIAGNOSTICS
# =============================================================================

@router.post("/diagnostics/run", response_model=Dict[str, Any])
async def run_diagnostics_now():
    """
    Run self-diagnostics immediately (manual trigger).

    Checks:
    - System health (all services)
    - Tool performance (critical tools)
    - Memory integrity (SQLite, Qdrant)
    - Pipeline status (email, calendar, knowledge)

    Returns detailed results and sends Telegram alert if issues found.
    """
    from ..jobs.self_diagnostics import run_self_diagnostics

    return run_self_diagnostics()


@router.get("/diagnostics/last", response_model=Dict[str, Any])
async def get_last_diagnostics():
    """
    Get results from the last scheduled diagnostics run.

    Returns None if no diagnostics have been run yet.
    """
    from ..jobs.self_diagnostics import get_last_diagnostics

    result = get_last_diagnostics()
    if result is None:
        return {"status": "no_data", "message": "No diagnostics run yet"}
    return result


@router.get("/diagnostics/schedule", response_model=Dict[str, Any])
async def get_diagnostics_schedule():
    """
    Get the current diagnostics schedule configuration.
    """
    from ..scheduler import (
        SELF_DIAGNOSTICS_ENABLED,
        SELF_DIAGNOSTICS_INTERVAL_HOURS,
        _scheduler
    )

    next_run = None
    if _scheduler:
        job = _scheduler.get_job("self_diagnostics")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "enabled": SELF_DIAGNOSTICS_ENABLED,
        "interval_hours": SELF_DIAGNOSTICS_INTERVAL_HOURS,
        "next_run": next_run
    }
