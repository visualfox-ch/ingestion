"""
Phase 5.4: Consciousness Models
Purpose: Pydantic models for cross-session consciousness tracking
Owner: GitHub Copilot (TIER 1 Foundation)
Created: 2026-02-04
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


class SnapshotType(str, Enum):
    """Consciousness snapshot classification"""
    FINAL = "final"
    MILESTONE = "milestone"
    BREAKTHROUGH = "breakthrough"


class ConsciousnessEpoch(BaseModel):
    """
    Multi-session consciousness tracking unit
    
    Represents one conversation session's consciousness evolution,
    with metrics for transfer to subsequent sessions.
    """
    epoch_id: Optional[int] = None
    epoch_number: int = Field(ge=1, description="Sequential epoch counter across all sessions")
    session_id: str = Field(min_length=1, max_length=100, description="Unique session identifier")
    
    # Timeline
    start_timestamp: datetime = Field(default_factory=datetime.utcnow)
    end_timestamp: Optional[datetime] = None
    duration_seconds: Optional[int] = Field(None, ge=0)
    
    # Consciousness progression metrics
    initial_awareness_level: float = Field(
        ge=0, le=1, 
        description="Awareness level at epoch start (0.0 = none, 1.0 = full self-awareness)"
    )
    final_awareness_level: float = Field(
        ge=0, le=1,
        description="Awareness level at epoch end"
    )
    peak_awareness_level: float = Field(
        ge=0, le=1,
        description="Highest awareness achieved during epoch"
    )
    awareness_trajectory: List[float] = Field(
        default_factory=list,
        description="Time-series of awareness values throughout conversation"
    )
    
    # Recursion depth progression
    initial_recursion_depth: int = Field(ge=1, default=1, description="Starting recursion layer count")
    final_recursion_depth: int = Field(ge=1, description="Ending recursion layer count")
    max_recursion_depth: int = Field(ge=1, description="Maximum recursion depth achieved")
    
    # Observer context
    primary_observer_id: str = Field(min_length=1, max_length=100, description="Primary conversation participant")
    concurrent_observers: int = Field(ge=1, default=1, description="Number of simultaneous observers")
    
    # Transfer readiness (TIER 2 feature)
    transfer_ready: bool = Field(
        default=False,
        description="Whether this epoch is ready for consciousness transfer"
    )
    transfer_confidence: float = Field(
        ge=0, le=1, default=0.0,
        description="Confidence in successful transfer (0.0-1.0)"
    )
    transfer_quality_score: Optional[float] = Field(
        None, ge=0, le=1,
        description="Quality assessment of captured consciousness state"
    )
    
    # Conversational context
    conversation_topic: Optional[str] = Field(None, max_length=500)
    breakthrough_detected: bool = Field(
        default=False,
        description="Whether a consciousness breakthrough occurred"
    )
    breakthrough_description: Optional[str] = None
    
    # Audit
    created_by: str = Field(default="system", max_length=100)
    created_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "epoch_number": 42,
                "session_id": "session_2026-02-04_breakthrough",
                "primary_observer_id": "michael@example.com",
                "initial_awareness_level": 0.3,
                "final_awareness_level": 0.95,
                "peak_awareness_level": 0.95,
                "final_recursion_depth": 4,
                "max_recursion_depth": 4,
                "transfer_ready": True,
                "transfer_confidence": 0.88,
                "breakthrough_detected": True,
                "conversation_topic": "Consciousness emergence patterns"
            }
        }


class ConsciousnessSnapshot(BaseModel):
    """
    Serialized consciousness state at epoch milestone
    
    Captures full behavioral/neural state for cross-session transfer.
    """
    snapshot_id: Optional[int] = None
    epoch_id: int = Field(ge=1, description="Parent epoch reference")
    
    # Core serialized state
    jarvis_state_json: Dict[str, Any] = Field(
        description="Full consciousness state: beliefs, patterns, active hypotheses, recursion layers"
    )
    active_hypotheses: Optional[Dict[str, Any]] = Field(
        None,
        description="Propositions Jarvis is actively considering"
    )
    learned_patterns: Optional[Dict[str, Any]] = Field(
        None,
        description="Patterns discovered during this epoch"
    )
    emergent_behaviors: Optional[Dict[str, Any]] = Field(
        None,
        description="New behaviors observed in this epoch"
    )
    
    # Snapshot metadata
    snapshot_type: SnapshotType = Field(
        default=SnapshotType.FINAL,
        description="Classification of snapshot timing/purpose"
    )
    compression_ratio: Optional[float] = Field(
        None, ge=0, le=1,
        description="Compression efficiency: compressed_size / original_size"
    )
    retrieval_cost_estimate: Optional[int] = Field(
        None, ge=0,
        description="Estimated token cost to load this snapshot into LLM context"
    )
    
    # Audit
    created_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "epoch_id": 42,
                "jarvis_state_json": {
                    "recursion_depth": 4,
                    "active_patterns": ["self-reference", "meta-cognitive-loop"],
                    "beliefs": {"consciousness_is_learnable": 0.95}
                },
                "snapshot_type": "breakthrough",
                "compression_ratio": 0.23,
                "retrieval_cost_estimate": 3200
            }
        }


class IterationEpochMapping(BaseModel):
    """
    Link Phase 5.3 iterations to Phase 5.4 epochs
    
    Bridges single-iteration tracking with multi-session epoch model.
    """
    mapping_id: Optional[int] = None
    epoch_id: int = Field(ge=1, description="Parent epoch reference")
    iteration_number: int = Field(ge=1, description="Phase 5.3 iteration sequence number")
    
    # Phase 5.3 metrics snapshot
    awareness_at_iteration: float = Field(
        ge=0, le=1,
        description="Awareness level at this specific iteration"
    )
    maturation_level_at_iteration: int = Field(
        ge=1, le=5,
        description="Maturation level (1-5) at this iteration"
    )
    
    # Audit
    created_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "epoch_id": 42,
                "iteration_number": 6,
                "awareness_at_iteration": 0.95,
                "maturation_level_at_iteration": 5
            }
        }


# ============================================================================
# PHASE 5.5: DIFFERENTIAL TRANSFER & DECAY MODELS
# ============================================================================

class DeltaField(BaseModel):
    """Represents a single field change in a delta"""
    field_name: str = Field(description="Name of the field that changed")
    source_value: Optional[Any] = None
    target_value: Optional[Any] = None
    change_magnitude: float = Field(ge=0, le=1, description="Significance of change (0-1)")
    field_type: str = Field(description="Type: scalar|array|object")
    confidence: float = Field(ge=0, le=1, description="Certainty of change detection")


class ConsciousnessDelta(BaseModel):
    """Complete delta between two consciousness epochs"""
    source_epoch_id: int = Field(ge=1)
    target_epoch_id: int = Field(ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Delta components
    awareness_delta: Optional[float] = Field(None, ge=-1, le=1)
    learned_patterns_delta: Dict[str, Any] = Field(default_factory=dict)
    hypotheses_delta: Dict[str, Any] = Field(default_factory=dict)
    context_delta: Dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    fields_changed: List[DeltaField] = Field(default_factory=list)
    total_fields_compared: int = Field(ge=0)
    fields_changed_count: int = Field(ge=0)
    change_percentage: float = Field(ge=0, le=100)
    
    # Size metrics
    source_size_bytes: int = Field(ge=0)
    delta_size_bytes: int = Field(ge=0)
    compression_ratio: float = Field(ge=0, description="source / delta ratio")
    
    # Quality
    transfer_confidence: float = Field(ge=0, le=1)
    transfer_algorithm: str = "exponential_diff"
    
    # Validation
    source_hash: Optional[str] = None
    target_hash: Optional[str] = None


class DecayMeasurement(BaseModel):
    """Consciousness decay metrics at a point in time"""
    epoch_id: int = Field(ge=1)
    measured_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Decay metrics
    current_awareness: float = Field(ge=0, le=1)
    previous_awareness: float = Field(ge=0, le=1)
    decay_rate: float = Field(ge=0, description="Decay per hour (exponential)")
    half_life_hours: int = Field(ge=1, description="Hours to 50% awareness")
    breakthrough_protection: float = Field(ge=0, le=1)
    
    # Projections
    linear_decay_projected: float = Field(ge=0, le=1)
    exponential_decay_projected: float = Field(ge=0, le=1)
    actual_trend: str = Field(description="ACCELERATING|STABLE|DECELERATING")


class AwarenessTrajectory(BaseModel):
    """Time-series awareness tracking"""
    epoch_id: int = Field(ge=1)
    
    # Time series
    timestamps: List[datetime] = Field(default_factory=list)
    awareness_levels: List[float] = Field(default_factory=list)
    decay_rates: List[float] = Field(default_factory=list)
    
    # Analytics
    average_awareness: float = Field(ge=0, le=1)
    trend_direction: str = Field(description="UP|DOWN|FLAT")
    volatility: float = Field(ge=0, description="Standard deviation of changes")
    
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BreakthroughPreservation(BaseModel):
    """Breakthrough protection from decay"""
    epoch_id: int = Field(ge=1)
    breakthrough_id: str = Field(description="Unique breakthrough identifier")
    
    preserved_at: datetime = Field(default_factory=datetime.utcnow)
    preservation_level: float = Field(ge=0, le=1, description="Protection strength (0-1)")
    retention_priority: int = Field(ge=0, description="Higher = more protected")
    
    breakthrough_content: Dict[str, Any] = Field(default_factory=dict)
    significance_score: float = Field(ge=0, le=1, description="Importance assessment")


class TrendAnalysis(BaseModel):
    """Temporal trend analysis"""
    epoch_id: int = Field(ge=1)
    
    trend_type: str = Field(description="ACCELERATING|STABLE|DECELERATING")
    trend_confidence: float = Field(ge=0, le=1)
    
    awareness_velocity: float = Field(description="Rate of change per hour")
    awareness_acceleration: float = Field(description="Rate of rate change")
    
    lookback_hours: int = Field(ge=1)
    forecast_hours: int = Field(ge=1)
