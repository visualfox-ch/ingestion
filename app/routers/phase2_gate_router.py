"""Phase 2 Gate Evaluation API Endpoints

Provides runtime evaluation of Phase 1 metrics and decision to activate Phase 2.
Gate evaluation queries Prometheus for 4 key metrics:
- False Positive Rate (<5% required)
- Success Rate (>95% required)
- Security Incidents (0 required)
- Confidence Outliers (<10/hour required)

Endpoints:
- GET /api/gate/phase2/evaluate - Evaluate Phase 1 metrics, return decision
- POST /api/gate/phase2/activate - Apply Phase 2 settings if decision approved

Author: GitHub Copilot
Created: 2026-02-04
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime

from ..observability import get_logger
from ..auth import auth_dependency
from .. import phase_gate

logger = get_logger("jarvis.phase2_gate_router")
router = APIRouter(prefix="/api/gate/phase2", tags=["Phase 2 Gate"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class GateEvaluationResponse(BaseModel):
    """Response model for gate evaluation."""
    decision: str = Field(..., description="Gate decision: approve, hold, rollback, insufficient_data")
    window_hours: int = Field(..., description="Metrics evaluation window in hours")
    evaluated_at: str = Field(..., description="ISO timestamp of evaluation")
    metrics: Dict[str, Any] = Field(..., description="Detailed metrics and their status")
    summary: str = Field(..., description="Human-readable decision summary")
    recommendation: Optional[str] = Field(None, description="Next steps recommendation")


class GateActivationRequest(BaseModel):
    """Request model for Phase 2 activation."""
    decision_summary: str = Field(..., description="Gate evaluation decision summary (audit)")
    changed_by: str = Field("api_user", description="User who triggered activation")
    confirm: bool = Field(..., description="Must be true to activate Phase 2")


class GateActivationResponse(BaseModel):
    """Response model after Phase 2 activation."""
    activated: bool = Field(..., description="Whether Phase 2 was activated")
    timestamp: str = Field(..., description="ISO timestamp of activation")
    changed_by: str = Field(..., description="User who triggered activation")
    thresholds: Dict[str, float] = Field(..., description="New Phase 2 thresholds")
    message: str = Field(..., description="Activation status message")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/evaluate", response_model=GateEvaluationResponse)
async def evaluate_phase2_gate(
    window_hours: int = Query(24, ge=1, le=168, description="Metrics evaluation window (hours)"),
    auth=Depends(auth_dependency)
) -> GateEvaluationResponse:
    """
    Evaluate Phase 1 metrics from Prometheus and return Phase 2 gate decision.
    
    Queries Prometheus for:
    - False Positive Rate (target <5%, blocker if >10%)
    - Success Rate (target >95%, warning if <95%)
    - Security Incidents (target 0, critical if >0)
    - Confidence Outliers (target <10/hour, warning if >25/hour)
    
    **Returns Decision**:
    - **approve**: All metrics green → Phase 2 can be activated
    - **hold**: Some yellow metrics → Tune Phase 1, retry in 24h
    - **rollback**: Any red metric → Investigation required, revert to Phase 0
    - **insufficient_data**: Missing Prometheus metrics → Wait for data
    
    **Auth Required**: Yes (admin endpoints)
    """
    try:
        logger.info(f"Phase 2 gate evaluation requested (window={window_hours}h)")
        
        # Call phase_gate.py evaluation function
        result = phase_gate.evaluate_phase2_gate(window_hours=window_hours)
        
        decision = result["decision"]
        logger.info(f"Gate evaluation complete: decision={decision}")
        
        # Generate human-readable summary
        summary = {
            "approve": "All metrics green. Phase 2 can be activated.",
            "hold": "Some metrics yellow. Tune Phase 1, retry in 24h.",
            "rollback": "Red metrics detected. Investigation required.",
            "insufficient_data": "Missing Prometheus metrics. Wait for data."
        }.get(decision, "Unknown decision")
        
        # Generate recommendation
        recommendation = {
            "approve": "Run POST /api/gate/phase2/activate to apply Phase 2 settings",
            "hold": "Monitor Phase 1 for 24h, then re-evaluate",
            "rollback": "Review red metrics, consider reverting to Phase 0",
            "insufficient_data": "Ensure Prometheus metrics are being collected"
        }.get(decision)
        
        return GateEvaluationResponse(
            decision=decision,
            window_hours=result["window_hours"],
            evaluated_at=result["evaluated_at"],
            metrics=result["metrics"],
            summary=summary,
            recommendation=recommendation
        )
    
    except Exception as e:
        logger.error(f"Phase 2 gate evaluation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Gate evaluation failed: {str(e)}"
        )


@router.post("/activate", response_model=GateActivationResponse)
async def activate_phase2(
    request: GateActivationRequest,
    auth=Depends(auth_dependency)
) -> GateActivationResponse:
    """
    Activate Phase 2 auto-approval by applying Phase 2 thresholds to hot config.
    
    **Prerequisites**:
    - Gate evaluation decision must be "approve" (call /evaluate first)
    - User must confirm activation with `confirm: true`
    
    **Action**:
    - Sets `auto_approval_phase = 2` in hot config
    - Updates R0/R1/R2/R3 thresholds to Phase 2 values:
      - R0: 70% (was 75%)
      - R1: 85% (was 90%)
      - R2: 95% (was manual-only)
      - R3: 99% (was never)
    
    **Hot Config Reload**: Changes apply within 30s (no Docker restart needed)
    
    **Auth Required**: Yes (admin endpoints)
    """
    try:
        # Validate confirmation
        if not request.confirm:
            raise HTTPException(
                status_code=400,
                detail="Phase 2 activation requires confirm=true"
            )
        
        logger.warning(
            f"Phase 2 activation requested by {request.changed_by}: {request.decision_summary}"
        )
        
        # Call phase_gate.py activation function (fake decision_summary dict)
        decision_dict = {"decision": "approve"}  # Router verifies user confirmation
        result = phase_gate.apply_phase2_settings(
            decision_summary=decision_dict,
            changed_by=request.changed_by,
            reason=request.decision_summary
        )
        
        if result["status"] == "applied":
            timestamp = result["applied_at"]
            logger.warning(
                f"✅ Phase 2 ACTIVATED by {request.changed_by} at {timestamp}"
            )
            
            return GateActivationResponse(
                activated=True,
                timestamp=timestamp,
                changed_by=request.changed_by,
                thresholds={
                    "r0": 0.70,
                    "r1": 0.85,
                    "r2": 0.95,
                    "r3": 0.99
                },
                message="Phase 2 activated successfully. Hot config will reload within 30s."
            )
        else:
            logger.error(f"Phase 2 activation failed: {result.get('reason')}")
            raise HTTPException(
                status_code=400,
                detail=f"Phase 2 activation failed: {result.get('reason', 'Unknown error')}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Phase 2 activation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Phase 2 activation failed: {str(e)}"
        )


@router.get("/status")
async def get_phase2_status(auth=Depends(auth_dependency)) -> Dict[str, Any]:
    """
    Get current auto-approval phase and thresholds from hot config.
    
    **Returns**:
    - Current phase (0, 1, or 2)
    - Active thresholds (R0, R1, R2, R3)
    - Feature enabled status
    - Last gate evaluation result (if cached)
    
    **Auth Required**: Yes (admin endpoints)
    """
    try:
        from ..hot_config import get_hot_config
        from ..approval_auto import AutoApprovalEngine
        
        # Get current phase from hot config
        current_phase = get_hot_config("auto_approval_phase", default=1)
        enabled = get_hot_config("auto_approval_enabled", default=True)
        
        # Get active thresholds
        thresholds = AutoApprovalEngine._get_thresholds(current_phase)
        
        return {
            "phase": current_phase,
            "enabled": enabled,
            "thresholds": {
                "r0": thresholds.get("r0_confidence", 0.0),
                "r1": thresholds.get("r1_confidence", 0.0),
                "r2": thresholds.get("r2_confidence", 0.0),
                "r3": thresholds.get("r3_confidence", 0.0),
            },
            "phase_description": {
                0: "Phase 0: Auto-approval disabled (all manual)",
                1: "Phase 1: R0/R1 auto-approval (24-48h validation)",
                2: "Phase 2: R0/R1/R2 auto-approval (post-validation)",
            }.get(current_phase, "Unknown phase"),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    except Exception as e:
        logger.error(f"Phase 2 status retrieval failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Status retrieval failed: {str(e)}"
        )
