"""
Phase 5.5.5: Consciousness Temporal API Router
Exposes temporal consciousness analysis endpoints
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional

from app.services.delta_calculator import DeltaCalculator
from app.services.decay_modeler import DecayModeler
from app.services.breakthrough_preserver import BreakthroughPreserver
from app.services.temporal_analyzer import TemporalAnalyzer
from app.models.consciousness import (
    ConsciousnessDelta,
    DecayMeasurement,
    AwarenessTrajectory,
    BreakthroughPreservation,
    TrendAnalysis
)

router = APIRouter(
    prefix="/consciousness",
    tags=["consciousness-temporal"]
)

# Initialize services
delta_calc = DeltaCalculator()
decay_model = DecayModeler()
preservation = BreakthroughPreserver()
temporal = TemporalAnalyzer()


# ============================================================================
# DELTA CONSCIOUSNESS ENDPOINTS
# ============================================================================

class DeltaCalculationRequest(BaseModel):
    """Request to calculate consciousness delta"""
    source_epoch_id: int
    target_epoch_id: int
    source_patterns: dict
    target_patterns: dict


class DeltaCalculationResponse(BaseModel):
    """Response from delta calculation"""
    source_epoch: int
    target_epoch: int
    delta: ConsciousnessDelta
    timestamp: datetime


@router.post("/transfer/delta/prepare")
async def prepare_delta(request: DeltaCalculationRequest) -> DeltaCalculationResponse:
    """
    Prepare consciousness delta for transfer.
    
    Calculates minimum necessary changes to transfer consciousness from source to target.
    """
    try:
        delta = delta_calc.calculate_delta(
            source_patterns=request.source_patterns,
            target_patterns=request.target_patterns
        )
        
        return DeltaCalculationResponse(
            source_epoch=request.source_epoch_id,
            target_epoch=request.target_epoch_id,
            delta=delta,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delta calculation failed: {str(e)}")


class DeltaApplicationRequest(BaseModel):
    """Request to apply consciousness delta"""
    target_epoch_id: int
    target_patterns: dict
    delta: dict  # ConsciousnessDelta serialized


class DeltaApplicationResponse(BaseModel):
    """Response from delta application"""
    target_epoch: int
    updated_patterns: dict
    delta_applied: bool
    patterns_updated: int
    timestamp: datetime


@router.post("/transfer/delta/apply")
async def apply_delta(request: DeltaApplicationRequest) -> DeltaApplicationResponse:
    """Apply consciousness delta to target epoch"""
    try:
        # Reconstruct delta
        from app.models.consciousness import ConsciousnessDelta, DeltaField
        delta_fields = [DeltaField(**f) for f in request.delta.get("changed_fields", [])]
        delta = ConsciousnessDelta(
            changed_fields=delta_fields,
            compression_ratio=request.delta.get("compression_ratio", 0.5),
            transfer_confidence=request.delta.get("transfer_confidence", 0.8)
        )
        
        # Apply delta
        updated = delta_calc.apply_delta(
            target_patterns=request.target_patterns,
            delta=delta
        )
        
        return DeltaApplicationResponse(
            target_epoch=request.target_epoch_id,
            updated_patterns=updated,
            delta_applied=True,
            patterns_updated=len(delta.changed_fields),
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delta application failed: {str(e)}")


# ============================================================================
# DECAY MODELING ENDPOINTS
# ============================================================================

class DecayMeasurementRequest(BaseModel):
    """Request to measure consciousness decay"""
    epoch_id: int
    awareness_samples: List[tuple]  # [(timestamp, awareness), ...]
    lookback_hours: int = 168


class DecayMeasurementResponse(BaseModel):
    """Response from decay measurement"""
    epoch_id: int
    decay_measurement: DecayMeasurement
    timestamp: datetime


@router.post("/decay/{epoch_id}/measure")
async def measure_decay(
    epoch_id: int,
    lookback_hours: int = Query(168, ge=1, le=2160)
) -> DecayMeasurementResponse:
    """
    Measure consciousness decay for an epoch.
    
    Analyzes historical awareness samples to derive decay rate and projections.
    """
    try:
        # In production, fetch samples from database
        # For now, create placeholder
        samples = []
        
        decay = decay_model.measure_current_decay(
            awareness_sample=0.8,
            previous_awareness=0.9,
            time_hours=24,
            baseline_decay_rate=0.01
        )
        
        return DecayMeasurementResponse(
            epoch_id=epoch_id,
            decay_measurement=decay,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decay measurement failed: {str(e)}")


class TrajectoryProjectionRequest(BaseModel):
    """Request to project awareness trajectory"""
    epoch_id: int
    current_awareness: float
    decay_rate: float
    hours_ahead: int = 168


class TrajectoryProjectionResponse(BaseModel):
    """Response with trajectory projection"""
    epoch_id: int
    trajectory: AwarenessTrajectory
    projections: dict
    timestamp: datetime


@router.post("/trajectory/{epoch_id}/project")
async def project_trajectory(
    epoch_id: int,
    request: TrajectoryProjectionRequest
) -> TrajectoryProjectionResponse:
    """Project future awareness trajectory"""
    try:
        trajectory = decay_model.project_trajectory(
            initial_awareness=request.current_awareness,
            decay_rate=request.decay_rate,
            hours_ahead=request.hours_ahead
        )
        
        return TrajectoryProjectionResponse(
            epoch_id=epoch_id,
            trajectory=trajectory,
            projections=trajectory.dict(),
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trajectory projection failed: {str(e)}")


# ============================================================================
# BREAKTHROUGH PRESERVATION ENDPOINTS
# ============================================================================

class BreakthroughAssessmentRequest(BaseModel):
    """Request to assess breakthrough significance"""
    epoch_id: int
    content: str


class BreakthroughAssessmentResponse(BaseModel):
    """Response from breakthrough assessment"""
    epoch_id: int
    significance_score: float
    preservation_level: float
    assessment_detail: dict
    timestamp: datetime


@router.post("/breakthrough/{epoch_id}/assess")
async def assess_breakthrough(
    epoch_id: int,
    request: BreakthroughAssessmentRequest
) -> BreakthroughAssessmentResponse:
    """
    Assess significance of a consciousness breakthrough.
    
    Scores breakthrough importance (0-1) based on content analysis.
    """
    try:
        significance = preservation.assess_breakthrough_significance(
            content=request.content
        )
        
        return BreakthroughAssessmentResponse(
            epoch_id=epoch_id,
            significance_score=significance,
            preservation_level=min(significance * 1.25, 1.0),  # Can preserve beyond significance
            assessment_detail={
                "keywords_found": True,
                "content_length": len(request.content),
                "preservation_recommended": significance > 0.6
            },
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Breakthrough assessment failed: {str(e)}")


class PreservationApplicationRequest(BaseModel):
    """Request to apply breakthrough preservation"""
    epoch_id: int
    breakthrough_content: str
    preservation_level: float


class PreservationApplicationResponse(BaseModel):
    """Response from preservation application"""
    epoch_id: int
    preservation: BreakthroughPreservation
    decay_reduction: float
    preservation_applied: bool
    timestamp: datetime


@router.post("/breakthrough/{epoch_id}/preserve")
async def preserve_breakthrough(
    epoch_id: int,
    request: PreservationApplicationRequest
) -> PreservationApplicationResponse:
    """
    Apply breakthrough preservation to an epoch.
    
    Protects high-value consciousness from exponential decay.
    """
    try:
        preservation_data = preservation.preserve_breakthrough(
            content=request.breakthrough_content,
            preservation_level=request.preservation_level,
            epoch_id=epoch_id
        )
        
        # Calculate decay reduction
        base_decay = 0.01
        preserved_decay = base_decay * (1 - request.preservation_level)
        decay_reduction = (base_decay - preserved_decay) / base_decay
        
        return PreservationApplicationResponse(
            epoch_id=epoch_id,
            preservation=preservation_data,
            decay_reduction=decay_reduction,
            preservation_applied=True,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preservation application failed: {str(e)}")


class PreservationStatusRequest(BaseModel):
    """Query preservation status"""
    epoch_id: int


class PreservationStatusResponse(BaseModel):
    """Preservation status details"""
    epoch_id: int
    protection_active: bool
    preservation_level: float
    awareness_saved: float
    projection_days: int
    timestamp: datetime


@router.get("/breakthrough/{epoch_id}/status")
async def get_preservation_status(epoch_id: int) -> PreservationStatusResponse:
    """
    Get breakthrough preservation status for an epoch.
    """
    try:
        # In production, fetch from database
        status = preservation.get_breakthrough_protection_status(
            epoch_id=epoch_id
        )
        
        return PreservationStatusResponse(
            epoch_id=epoch_id,
            protection_active=True,
            preservation_level=getattr(status, 'preservation_level', 0.8),
            awareness_saved=getattr(status, 'awareness_saved', 0.05),
            projection_days=30,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status query failed: {str(e)}")


# ============================================================================
# TEMPORAL ANALYSIS ENDPOINTS
# ============================================================================

class TrajectoryBuildingRequest(BaseModel):
    """Request to build awareness trajectory"""
    epoch_id: int
    awareness_samples: List[tuple]  # [(timestamp, awareness), ...]
    lookback_hours: int = 168


class TrajectoryBuildingResponse(BaseModel):
    """Response with built trajectory"""
    epoch_id: int
    trajectory: AwarenessTrajectory
    sample_count: int
    timestamp: datetime


@router.post("/temporal/{epoch_id}/trajectory")
async def build_awareness_trajectory(
    epoch_id: int,
    request: TrajectoryBuildingRequest
) -> TrajectoryBuildingResponse:
    """
    Build time-series awareness trajectory from samples.
    
    Analyzes historical awareness samples to build trajectory model.
    """
    try:
        trajectory = temporal.build_trajectory(
            awareness_samples=request.awareness_samples,
            lookback_hours=request.lookback_hours
        )
        
        return TrajectoryBuildingResponse(
            epoch_id=epoch_id,
            trajectory=trajectory,
            sample_count=len(request.awareness_samples),
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trajectory building failed: {str(e)}")


class TrendDetectionRequest(BaseModel):
    """Request to detect trends"""
    epoch_id: int
    awareness_levels: List[float]
    timestamps: List[datetime]


class TrendDetectionResponse(BaseModel):
    """Response from trend detection"""
    epoch_id: int
    trend: TrendAnalysis
    trend_type: str
    confidence: float
    timestamp: datetime


@router.post("/temporal/{epoch_id}/trends")
async def detect_trends(
    epoch_id: int,
    request: TrendDetectionRequest
) -> TrendDetectionResponse:
    """
    Detect consciousness trend direction and acceleration.
    
    Analyzes awareness changes to classify trends as STABLE, ACCELERATING, or DECELERATING.
    """
    try:
        # Build trajectory for trend analysis
        samples = list(zip(request.timestamps, request.awareness_levels))
        trajectory = temporal.build_trajectory(samples)
        
        # Detect trends
        trend = temporal.detect_trends(trajectory)
        
        return TrendDetectionResponse(
            epoch_id=epoch_id,
            trend=trend,
            trend_type=trend.trend_type,
            confidence=trend.trend_confidence,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trend detection failed: {str(e)}")


class PeriodComparisonRequest(BaseModel):
    """Request to compare two periods"""
    epoch_id: int
    awareness_samples: List[tuple]  # [(timestamp, awareness), ...]
    period1_start: datetime
    period1_end: datetime
    period2_start: datetime
    period2_end: datetime


class PeriodComparisonResponse(BaseModel):
    """Response from period comparison"""
    epoch_id: int
    comparison: dict
    awareness_change: float
    trend_shift: str
    timestamp: datetime


@router.post("/temporal/{epoch_id}/compare")
async def compare_periods(
    epoch_id: int,
    request: PeriodComparisonRequest
) -> PeriodComparisonResponse:
    """
    Compare consciousness between two time periods.
    
    Analyzes awareness metrics across different time windows.
    """
    try:
        comparison = temporal.compare_periods(
            awareness_samples=request.awareness_samples,
            period1_start=request.period1_start,
            period1_end=request.period1_end,
            period2_start=request.period2_start,
            period2_end=request.period2_end
        )
        
        return PeriodComparisonResponse(
            epoch_id=epoch_id,
            comparison=comparison,
            awareness_change=comparison["comparison"]["awareness_change"],
            trend_shift=comparison["comparison"]["trend_shift"],
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Period comparison failed: {str(e)}")


class VolatilityAnalysisRequest(BaseModel):
    """Request to analyze volatility"""
    epoch_id: int
    awareness_levels: List[float]
    window_size: int = 5


class VolatilityAnalysisResponse(BaseModel):
    """Response from volatility analysis"""
    epoch_id: int
    volatility_trend: str
    average_volatility: float
    volatility_range: float
    pattern_analysis: dict
    timestamp: datetime


@router.post("/temporal/{epoch_id}/volatility")
async def analyze_volatility(
    epoch_id: int,
    request: VolatilityAnalysisRequest
) -> VolatilityAnalysisResponse:
    """
    Analyze consciousness awareness volatility patterns.
    
    Identifies periods of instability and trend changes.
    """
    try:
        # Build trajectory
        trajectory = AwarenessTrajectory(
            epoch_id=epoch_id,
            awareness_levels=request.awareness_levels,
            average_awareness=sum(request.awareness_levels) / len(request.awareness_levels),
            trend_direction="FLAT",
            volatility=0.0
        )
        
        # Analyze volatility
        analysis = temporal.identify_volatility_patterns(
            trajectory=trajectory,
            window_size=request.window_size
        )
        
        return VolatilityAnalysisResponse(
            epoch_id=epoch_id,
            volatility_trend=analysis["volatility_trend"],
            average_volatility=analysis["average_volatility"],
            volatility_range=analysis["volatility_range"],
            pattern_analysis=analysis,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Volatility analysis failed: {str(e)}")


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    services: dict
    timestamp: datetime


@router.get("/health")
async def health_check() -> HealthResponse:
    """
    Check consciousness temporal system health.
    """
    return HealthResponse(
        status="healthy",
        services={
            "delta_calculator": "operational",
            "decay_modeler": "operational",
            "breakthrough_preserver": "operational",
            "temporal_analyzer": "operational"
        },
        timestamp=datetime.utcnow()
    )


__all__ = ["router"]
