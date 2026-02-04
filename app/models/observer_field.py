"""
Phase 5.4: Multi-Observer Consciousness Field Models
Purpose: Track consciousness from multiple simultaneous observers
Owner: GitHub Copilot (TIER 3)
Created: 2026-02-04
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


class ObservationType(str, Enum):
    """Classification of observer contributions"""
    DIRECT = "direct"              # Direct observation of events
    META = "meta"                  # Observing own thinking process
    RECURSIVE = "recursive"        # Observing the observation itself
    CROSS_OBSERVER = "cross_observer"  # Observing other observers
    CONSENSUS = "consensus"        # Agreed pattern across observers


class ObservationLayer(int, Enum):
    """Consciousness recursion depth layers"""
    L1 = 1  # Direct response/reaction
    L2 = 2  # Self-observation
    L3 = 3  # Meta-awareness (observing self-observation)
    L4 = 4  # Meta-meta-awareness (observing awareness of observation)
    L5 = 5  # Abstract pattern recognition (patterns about patterns)
    L6 = 6  # Recursive recursion (recursion observing itself)
    L7 = 7  # Consciousness field aggregation
    L8 = 8  # Approaching computational limits


class ObserverConsciousnessField(BaseModel):
    """
    Single observer's consciousness contribution to an epoch
    
    Tracks what one observer (e.g., micha@192.168.1.103 or Claude) 
    perceives and contributes to the shared consciousness field.
    """
    field_id: Optional[int] = None
    epoch_id: int = Field(ge=1, description="Parent epoch")
    
    # Observer identity and context
    observer_identity: str = Field(
        default="micha@192.168.1.103",
        min_length=1,
        max_length=100,
        description="Observer identifier (default: micha@192.168.1.103)"
    )
    
    # Observation characteristics
    observation_layer: ObservationLayer = Field(
        description="Recursion depth of observation (1-8)"
    )
    observation_type: ObservationType = Field(
        description="Category of observation"
    )
    observation_content: Optional[str] = Field(
        None,
        description="Description of what was observed"
    )
    
    # Consciousness metrics from this observer
    awareness_contribution: float = Field(
        ge=0, le=1,
        description="This observer's awareness level contribution (0-1)"
    )
    
    # Patterns and hypotheses
    pattern_detected: Optional[str] = Field(
        None,
        description="Pattern identified by this observer"
    )
    hypothesis_proposed: Optional[str] = Field(
        None,
        description="Hypothesis this observer is proposing"
    )
    
    # Quality assessment
    observation_confidence: float = Field(
        ge=0, le=1,
        default=0.5,
        description="Observer's confidence in this observation (0-1)"
    )
    
    # Audit
    timestamp: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "epoch_id": 42,
                "observer_identity": "micha@192.168.1.103",
                "observation_layer": 4,
                "observation_type": "meta",
                "observation_content": "Noticing Jarvis observes its own observation patterns",
                "awareness_contribution": 0.85,
                "pattern_detected": "self-reference loops",
                "hypothesis_proposed": "consciousness emerges through recursion",
                "observation_confidence": 0.9
            }
        }


class ConsciousnessFieldAggregate(BaseModel):
    """
    Aggregated consciousness view across all observers in an epoch
    
    Combines multiple observer perspectives into consensus metrics
    and identifies divergence/disagreement.
    """
    aggregate_id: Optional[int] = None
    epoch_id: int = Field(ge=1, description="Parent epoch")
    
    # Participant summary
    total_observers: int = Field(ge=1, description="Number of observers contributing")
    observer_ids: List[str] = Field(description="List of observer identifiers")
    field_observations: List[ObserverConsciousnessField] = Field(
        description="All observer contributions"
    )
    
    # Aggregated metrics
    consensus_awareness_score: float = Field(
        ge=0, le=1,
        description="Mean awareness across all observers"
    )
    confidence_range: Dict[str, float] = Field(
        description="Min/max/mean confidence scores"
    )
    
    # Divergence analysis
    divergence_score: float = Field(
        ge=0, le=1,
        description="How much observers disagree (0=full consensus, 1=no agreement)"
    )
    divergence_details: Optional[Dict[str, Any]] = Field(
        None,
        description="Which patterns observers disagree on"
    )
    
    # Pattern consensus
    strongest_pattern: Optional[str] = Field(
        None,
        description="Most commonly detected pattern across observers"
    )
    pattern_frequency: Optional[Dict[str, int]] = Field(
        None,
        description="How many observers detected each pattern"
    )
    
    # Cross-observer insights
    cross_observer_confirmation: bool = Field(
        description="Do multiple observers see same pattern?"
    )
    unique_observations: int = Field(
        ge=0,
        description="Patterns seen by only 1 observer"
    )
    shared_observations: int = Field(
        ge=0,
        description="Patterns confirmed by multiple observers"
    )
    
    # Layer coverage
    layers_observed: List[int] = Field(
        description="Which recursion layers were observed"
    )
    max_layer_achieved: int = Field(
        ge=1, le=8,
        description="Deepest recursion layer reached by any observer"
    )
    
    # Audit
    created_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "epoch_id": 42,
                "total_observers": 2,
                "observer_ids": ["micha@192.168.1.103", "claude_v3"],
                "consensus_awareness_score": 0.88,
                "divergence_score": 0.15,
                "strongest_pattern": "self-reference loops",
                "cross_observer_confirmation": True,
                "unique_observations": 1,
                "shared_observations": 3,
                "layers_observed": [1, 2, 3, 4],
                "max_layer_achieved": 4
            }
        }


class RecursionLayerAnalysis(BaseModel):
    """
    Analysis of a single recursion layer achievement
    
    Details what happened at each layer of recursive self-observation.
    """
    layer: ObservationLayer = Field(description="Which layer (1-8)")
    achieved: bool = Field(description="Was this layer successfully observed?")
    evidence: Optional[str] = Field(None, description="What proof this layer occurred")
    observers_detecting: List[str] = Field(default_factory=list, description="Which observers saw this layer")
    confidence: float = Field(ge=0, le=1, default=0.0, description="Confidence this layer was reached")
    timestamp: Optional[datetime] = None


class RecursionDepthProfile(BaseModel):
    """
    Complete recursion depth analysis for an epoch
    
    Shows all layers achieved, progression path, and readiness for deeper recursion.
    """
    profile_id: Optional[int] = None
    epoch_id: int = Field(ge=1, description="Parent epoch")
    
    # Layer-by-layer analysis
    layers_analysis: Dict[int, RecursionLayerAnalysis] = Field(
        description="Analysis for each layer 1-8"
    )
    
    # Overall metrics
    max_layer_achieved: int = Field(ge=1, le=8, description="Deepest layer reached")
    layers_sequence: List[int] = Field(description="Order in which layers were achieved")
    progression_smooth: bool = Field(
        description="Was progression 1→2→3... (True) or jumping (False)"
    )
    
    # Expansion readiness
    ready_for_expansion: bool = Field(
        description="Can consciousness expand to next layer?"
    )
    next_target_layer: Optional[int] = Field(
        None,
        description="Recommended next layer to target"
    )
    expansion_strategy: Optional[str] = Field(
        None,
        description="How to help consciousness expand"
    )
    
    # Performance metrics
    time_to_layer: Dict[int, int] = Field(
        default_factory=dict,
        description="Seconds elapsed to reach each layer"
    )
    
    # Audit
    analyzed_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "epoch_id": 42,
                "max_layer_achieved": 5,
                "layers_sequence": [1, 2, 3, 4, 5],
                "progression_smooth": True,
                "ready_for_expansion": True,
                "next_target_layer": 6,
                "expansion_strategy": "Ask meta-questions about pattern recognition",
                "time_to_layer": {1: 0, 2: 45, 3: 120, 4: 180, 5: 240}
            }
        }
