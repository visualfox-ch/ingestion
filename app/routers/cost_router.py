"""
Cost & Budget API Router

REST endpoints for cost tracking and budget management.
Inspired by ClawWork's economic accountability.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/costs", tags=["costs"])


# =============================================================================
# Request/Response Models
# =============================================================================


class CostSummaryResponse(BaseModel):
    """Cost summary response."""
    period: str
    start_date: str
    end_date: str
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    by_feature: dict
    by_model: dict
    by_user: dict


class DailyCostResponse(BaseModel):
    """Daily cost entry."""
    date: str
    cost_usd: float
    requests: int


class FeatureCostResponse(BaseModel):
    """Cost by feature."""
    feature: str
    cost_usd: float
    requests: int
    input_tokens: int
    output_tokens: int


class RecentEntryResponse(BaseModel):
    """Recent cost entry."""
    id: int
    timestamp: str
    model: str
    feature: str
    user_id: str
    tokens: int
    cost_usd: float


class BudgetRequest(BaseModel):
    """Budget configuration request."""
    limit_usd: float = Field(..., gt=0, description="Budget limit in USD")
    period: str = Field("monthly", description="Budget period: daily, weekly, monthly")
    alert_threshold: float = Field(0.8, ge=0, le=1, description="Alert threshold (0.0-1.0)")
    hard_limit: bool = Field(False, description="Block requests when exceeded")


class BudgetResponse(BaseModel):
    """Budget configuration response."""
    feature: str
    period: str
    limit_usd: float
    alert_threshold: float
    hard_limit: bool
    created_at: str
    updated_at: str


class BudgetStatusResponse(BaseModel):
    """Budget status response."""
    feature: str
    period: str
    limit_usd: float
    spent_usd: float
    remaining_usd: float
    usage_percent: float
    alert_level: str
    hard_limit: bool
    period_start: str
    period_end: str
    is_blocked: bool


class AlertResponse(BaseModel):
    """Budget alert response."""
    id: int
    feature: str
    level: str
    message: str
    spent_usd: float
    limit_usd: float
    usage_percent: float
    timestamp: str
    acknowledged: bool


class HealthResponse(BaseModel):
    """Cost service health."""
    status: str
    tracker_initialized: bool
    budget_manager_initialized: bool
    total_budgets: int
    active_alerts: int


# =============================================================================
# Cost Tracking Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def cost_health():
    """Check cost tracking service health."""
    try:
        from ..services.cost_tracker import get_cost_tracker
        from ..services.budget_manager import get_budget_manager

        tracker = get_cost_tracker()
        manager = get_budget_manager()

        budgets = manager.list_budgets()
        alerts = manager.get_alerts(unacknowledged_only=True, limit=100)

        return HealthResponse(
            status="healthy",
            tracker_initialized=True,
            budget_manager_initialized=True,
            total_budgets=len(budgets),
            active_alerts=len(alerts),
        )
    except Exception as e:
        logger.error(f"Cost health check failed: {e}")
        return HealthResponse(
            status="error",
            tracker_initialized=False,
            budget_manager_initialized=False,
            total_budgets=0,
            active_alerts=0,
        )


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
    feature: Optional[str] = Query(None, description="Filter by feature"),
    user_id: Optional[str] = Query(None, description="Filter by user"),
):
    """Get cost summary for a time period."""
    try:
        from ..services.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        summary = tracker.get_summary(
            start_date=start_date,
            end_date=end_date,
            feature=feature,
            user_id=user_id,
        )

        return CostSummaryResponse(**summary.to_dict())

    except Exception as e:
        logger.error(f"Failed to get cost summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily", response_model=List[DailyCostResponse])
async def get_daily_costs(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
):
    """Get daily cost totals."""
    try:
        from ..services.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        costs = tracker.get_daily_costs(days=days)

        return [DailyCostResponse(**c) for c in costs]

    except Exception as e:
        logger.error(f"Failed to get daily costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-feature", response_model=List[FeatureCostResponse])
async def get_costs_by_feature(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
):
    """Get costs grouped by feature."""
    try:
        from ..services.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        costs = tracker.get_feature_costs(start_date=start_date, end_date=end_date)

        return [FeatureCostResponse(**c) for c in costs]

    except Exception as e:
        logger.error(f"Failed to get feature costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recent", response_model=List[RecentEntryResponse])
async def get_recent_costs(
    limit: int = Query(50, ge=1, le=500, description="Number of entries"),
    feature: Optional[str] = Query(None, description="Filter by feature"),
):
    """Get recent cost entries."""
    try:
        from ..services.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        entries = tracker.get_recent_entries(limit=limit, feature=feature)

        return [RecentEntryResponse(**e) for e in entries]

    except Exception as e:
        logger.error(f"Failed to get recent costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Budget Management Endpoints
# =============================================================================


@router.get("/budgets", response_model=List[BudgetResponse])
async def list_budgets():
    """List all configured budgets."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()
        budgets = manager.list_budgets()

        return [BudgetResponse(**b.to_dict()) for b in budgets]

    except Exception as e:
        logger.error(f"Failed to list budgets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/budgets/{feature}", response_model=BudgetResponse)
async def get_budget(feature: str):
    """Get budget configuration for a feature."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()
        budget = manager.get_budget(feature)

        if not budget:
            raise HTTPException(status_code=404, detail=f"No budget for: {feature}")

        return BudgetResponse(**budget.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/budgets/{feature}", response_model=BudgetResponse)
async def set_budget(feature: str, request: BudgetRequest):
    """Set or update a budget for a feature."""
    try:
        from ..services.budget_manager import get_budget_manager, BudgetPeriod

        manager = get_budget_manager()

        try:
            period = BudgetPeriod(request.period)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid period: {request.period}. Use: daily, weekly, monthly"
            )

        budget = manager.set_budget(
            feature=feature,
            limit_usd=request.limit_usd,
            period=period,
            alert_threshold=request.alert_threshold,
            hard_limit=request.hard_limit,
        )

        return BudgetResponse(**budget.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/budgets/{feature}")
async def delete_budget(feature: str):
    """Delete a budget configuration."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()

        if not manager.delete_budget(feature):
            raise HTTPException(status_code=404, detail=f"No budget for: {feature}")

        return {"status": "deleted", "feature": feature}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/budgets/{feature}/status", response_model=BudgetStatusResponse)
async def get_budget_status(feature: str):
    """Get current budget status for a feature."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()
        status = manager.get_budget_status(feature)

        if not status:
            raise HTTPException(status_code=404, detail=f"No budget for: {feature}")

        return BudgetStatusResponse(**status.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get budget status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/budgets-status", response_model=List[BudgetStatusResponse])
async def get_all_budget_statuses():
    """Get status for all configured budgets."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()
        statuses = manager.get_all_statuses()

        return [BudgetStatusResponse(**s.to_dict()) for s in statuses]

    except Exception as e:
        logger.error(f"Failed to get budget statuses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Alert Endpoints
# =============================================================================


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    feature: Optional[str] = Query(None, description="Filter by feature"),
    unacknowledged_only: bool = Query(False, description="Only unacknowledged"),
    limit: int = Query(50, ge=1, le=500, description="Number of alerts"),
):
    """Get budget alerts."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()
        alerts = manager.get_alerts(
            feature=feature,
            unacknowledged_only=unacknowledged_only,
            limit=limit,
        )

        return [AlertResponse(**a.to_dict()) for a in alerts]

    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """Acknowledge a budget alert."""
    try:
        from ..services.budget_manager import get_budget_manager

        manager = get_budget_manager()

        if not manager.acknowledge_alert(alert_id):
            raise HTTPException(status_code=404, detail=f"Alert not found: {alert_id}")

        return {"status": "acknowledged", "alert_id": alert_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to acknowledge alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LLM Optimization Status (O4-O6)
# =============================================================================


class OptimizationStatusResponse(BaseModel):
    """LLM optimization status."""
    o2_openai_responses_api: bool = True
    o3_anthropic_prompt_cache: bool = True
    o4_streaming_buffer: bool = True
    o5_tool_caching: bool = True
    o5_tool_cache_ttl_seconds: int = 60
    o6_context_optimization: bool = True
    o6_max_context_tokens: int = 180000


@router.get("/optimizations", response_model=OptimizationStatusResponse)
async def get_optimization_status():
    """Get LLM optimization status (O2-O6)."""
    try:
        from ..services.llm_optimizations import _tool_cache

        return OptimizationStatusResponse(
            o2_openai_responses_api=True,
            o3_anthropic_prompt_cache=True,
            o4_streaming_buffer=True,
            o5_tool_caching=True,
            o5_tool_cache_ttl_seconds=int(_tool_cache.ttl_seconds),
            o6_context_optimization=True,
            o6_max_context_tokens=180000
        )
    except Exception as e:
        logger.error(f"Failed to get optimization status: {e}")
        return OptimizationStatusResponse()
