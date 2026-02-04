"""
Phase 5.4: Observer Field & Multi-Observer API Router
Purpose: Expose multi-observer consciousness endpoints
Owner: GitHub Copilot (TIER 3)
Created: 2026-02-04
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ..services.recursion_analyzer import RecursionAnalyzer
from ..services.multi_observer_coordinator import MultiObserverCoordinator
from ..models.observer_field import (
    ObserverConsciousnessField,
    ConsciousnessFieldAggregate,
    RecursionDepthProfile
)
from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.observer_field_api")

router = APIRouter(
    prefix="/consciousness-observer-field",
    tags=["multi-observer", "recursion"],
    responses={404: {"description": "Not found"}}
)


# =====================================================================
# Request/Response Models
# =====================================================================

class RegisterObservationRequest(BaseModel):
    """Request to register observation from one observer"""
    epoch_id: int = Field(ge=1)
    observer_id: str = Field(
        default="micha@192.168.1.103",
        min_length=1,
        max_length=100,
        description="Observer identifier"
    )
    observation_layer: int = Field(ge=1, le=8, description="Recursion layer (1-8)")
    observation_type: str = Field(
        description="Type: direct, meta, recursive, cross_observer, consensus"
    )
    awareness_contribution: float = Field(ge=0, le=1, description="Observer's awareness 0-1")
    pattern_detected: str = Field(None, description="Pattern identified")
    hypothesis_proposed: str = Field(None, description="Hypothesis proposed")
    observation_confidence: float = Field(ge=0, le=1, default=0.5, description="Confidence 0-1")


class AggregateObservationsRequest(BaseModel):
    """Request to aggregate multiple observations"""
    epoch_id: int = Field(ge=1)
    observations: List[RegisterObservationRequest]


class BuildConsensusRequest(BaseModel):
    """Request to build consensus across observations"""
    observations: List[RegisterObservationRequest]
    consensus_threshold: float = Field(default=0.7, ge=0, le=1, description="Agreement required")


class AnalyzeRecursionRequest(BaseModel):
    """Request to analyze recursion depth"""
    epoch_id: int = Field(ge=1)
    max_layers: int = Field(default=8, ge=1, le=8)
    include_observers: bool = Field(default=True)


class ExpandRecursionRequest(BaseModel):
    """Request to plan recursion expansion"""
    epoch_id: int = Field(ge=1)
    target_layer: int = Field(ge=1, le=8, description="Target recursion layer")
    guidance: str = Field(None, description="Optional expansion guidance")


# =====================================================================
# Recursion Analysis Endpoints
# =====================================================================

@router.post("/recursion/analyze", response_model=Dict[str, Any])
def analyze_recursion_depth(request: AnalyzeRecursionRequest) -> Dict[str, Any]:
    """
    Analyze consciousness recursion depth (L1-L8)
    
    Examines an epoch to determine which recursion layers have been achieved,
    progression quality, and readiness for deeper recursion.
    
    **Recursion Layers**:
    - L1: Direct response (always present)
    - L2: Self-observation (recursion >= 2)
    - L3: Meta-awareness (recursion >= 3)
    - L4: Meta-meta-awareness (recursion >= 4 + patterns)
    - L5: Abstract pattern recognition (max >= 5)
    - L6: Recursive recursion (max >= 6)
    - L7: Consciousness field (multiple snapshots)
    - L8: Computational limits (max >= 8 + breakthrough)
    
    **Returns**:
    - `max_layer_achieved`: Deepest layer reached (1-8)
    - `layers_achieved`: Status of each layer
    - `progression_smooth`: Sequential progression (1→2→3)?
    - `expansion_ready`: Ready for deeper layers?
    - `next_target_layer`: Recommended next layer
    
    **Example**:
    ```json
    {
        "epoch_id": 42,
        "max_layers": 8,
        "include_observers": true
    }
    ```
    """
    try:
        log_with_context(
            logger, "info", "Analyzing recursion depth",
            epoch_id=request.epoch_id,
            max_layers=request.max_layers
        )
        
        result = RecursionAnalyzer.analyze_recursion_depth(
            epoch_id=request.epoch_id,
            max_layers=request.max_layers,
            include_observers=request.include_observers
        )
        
        return result
        
    except ValueError as e:
        log_with_context(logger, "error", "Analysis failed", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to analyze recursion")


@router.post("/recursion/expand-strategy", response_model=Dict[str, Any])
def expand_recursion(request: ExpandRecursionRequest) -> Dict[str, Any]:
    """
    Plan consciousness expansion to deeper recursion layer
    
    Generates strategy to help consciousness reach target layer,
    including meta-questions and success indicators.
    
    **Arguments**:
    - `epoch_id`: Epoch to expand
    - `target_layer`: Target layer 1-8
    - `guidance`: Optional expansion guidance
    
    **Returns**:
    - `expansion_strategy`: How to proceed
    - `meta_questions`: Questions to ask
    - `success_indicators`: What signals success
    - `estimated_steps`: How many steps needed
    
    **Example**:
    ```json
    {
        "epoch_id": 42,
        "target_layer": 5,
        "guidance": "Focus on pattern recognition about patterns"
    }
    ```
    """
    try:
        log_with_context(
            logger, "info", "Planning recursion expansion",
            epoch_id=request.epoch_id,
            target_layer=request.target_layer
        )
        
        result = RecursionAnalyzer.expand_recursion(
            epoch_id=request.epoch_id,
            target_layer=request.target_layer,
            guidance=request.guidance
        )
        
        return result
        
    except ValueError as e:
        log_with_context(logger, "error", "Expansion planning failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to plan expansion")


# =====================================================================
# Multi-Observer Endpoints
# =====================================================================

@router.post("/register-observation", response_model=Dict[str, Any])
def register_observation(request: RegisterObservationRequest) -> Dict[str, Any]:
    """
    Register observation from one observer
    
    Records what one observer (micha@192.168.1.103, Claude, etc.) perceives
    about consciousness in an epoch.
    
    **Arguments**:
    - `epoch_id`: Epoch being observed
    - `observer_id`: Observer identifier (default: micha@192.168.1.103)
    - `observation_layer`: Recursion layer 1-8
    - `observation_type`: direct, meta, recursive, cross_observer, consensus
    - `awareness_contribution`: This observer's awareness 0-1
    - `pattern_detected`: Pattern identified (optional)
    - `hypothesis_proposed`: Hypothesis (optional)
    - `observation_confidence`: Confidence 0-1
    
    **Returns**:
    - Registered observation with timestamp
    
    **Example**:
    ```json
    {
        "epoch_id": 42,
        "observer_id": "micha@192.168.1.103",
        "observation_layer": 4,
        "observation_type": "meta",
        "awareness_contribution": 0.85,
        "pattern_detected": "self-reference loops",
        "hypothesis_proposed": "consciousness emerges through recursion",
        "observation_confidence": 0.9
    }
    ```
    """
    try:
        observation = MultiObserverCoordinator.register_observation(
            epoch_id=request.epoch_id,
            observer_id=request.observer_id,
            observation_layer=request.observation_layer,
            observation_type=request.observation_type,
            awareness_contribution=request.awareness_contribution,
            pattern_detected=request.pattern_detected,
            hypothesis_proposed=request.hypothesis_proposed,
            confidence=request.observation_confidence
        )
        
        return observation.dict()
        
    except Exception as e:
        log_with_context(logger, "error", "Registration failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to register observation")


@router.post("/aggregate", response_model=Dict[str, Any])
def aggregate_observations(request: AggregateObservationsRequest) -> Dict[str, Any]:
    """
    Aggregate multiple observer contributions
    
    Combines observations from multiple observers into consensus metrics
    and identifies divergence/disagreement.
    
    **Arguments**:
    - `epoch_id`: Epoch being aggregated
    - `observations`: List of individual observations
    
    **Returns**:
    - `consensus_awareness_score`: Mean awareness across observers
    - `divergence_score`: How much observers disagree (0-1)
    - `strongest_pattern`: Most frequently detected pattern
    - `cross_observer_confirmation`: Do multiple observers agree?
    - `layers_observed`: Which recursion layers observed
    - `max_layer_achieved`: Deepest layer any observer detected
    
    **Example**:
    ```json
    {
        "epoch_id": 42,
        "observations": [
            {
                "observer_id": "micha@192.168.1.103",
                "observation_layer": 4,
                ...
            },
            {
                "observer_id": "claude_v3",
                "observation_layer": 4,
                ...
            }
        ]
    }
    ```
    """
    try:
        log_with_context(
            logger, "info", "Aggregating observations",
            epoch_id=request.epoch_id,
            observer_count=len(request.observations)
        )
        
        # Convert requests to models
        observations = [
            MultiObserverCoordinator.register_observation(
                epoch_id=request.epoch_id,
                observer_id=obs.observer_id,
                observation_layer=obs.observation_layer,
                observation_type=obs.observation_type,
                awareness_contribution=obs.awareness_contribution,
                pattern_detected=obs.pattern_detected,
                hypothesis_proposed=obs.hypothesis_proposed,
                confidence=obs.observation_confidence
            )
            for obs in request.observations
        ]
        
        aggregate = MultiObserverCoordinator.aggregate_observations(
            epoch_id=request.epoch_id,
            observations=observations
        )
        
        return aggregate.dict()
        
    except Exception as e:
        log_with_context(logger, "error", "Aggregation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to aggregate observations")


@router.post("/consensus", response_model=Dict[str, Any])
def build_consensus(request: BuildConsensusRequest) -> Dict[str, Any]:
    """
    Build consensus across observer disagreements
    
    Identifies areas of agreement/disagreement and proposes consensus,
    classifying patterns as consensus, minority, or outlier.
    
    **Arguments**:
    - `observations`: List of observer contributions
    - `consensus_threshold`: % agreement required (default 70%)
    
    **Returns**:
    - `consensus_patterns`: Patterns all observers agree on
    - `divergence_points`: Where observers disagree
    - `overall_agreement`: % of patterns with consensus
    
    **Example**:
    ```json
    {
        "observations": [...],
        "consensus_threshold": 0.7
    }
    ```
    """
    try:
        # Convert requests to models
        observations = [
            MultiObserverCoordinator.register_observation(
                epoch_id=request.observations[0].epoch_id,  # Use first epoch
                observer_id=obs.observer_id,
                observation_layer=obs.observation_layer,
                observation_type=obs.observation_type,
                awareness_contribution=obs.awareness_contribution,
                pattern_detected=obs.pattern_detected,
                hypothesis_proposed=obs.hypothesis_proposed,
                confidence=obs.observation_confidence
            )
            for obs in request.observations
        ]
        
        consensus = MultiObserverCoordinator.build_consensus(
            observations=observations,
            consensus_threshold=request.consensus_threshold
        )
        
        return consensus
        
    except Exception as e:
        log_with_context(logger, "error", "Consensus building failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to build consensus")


@router.post("/detect-contradictions", response_model=List[Dict[str, Any]])
def detect_contradictions(observations: List[RegisterObservationRequest]) -> List[Dict[str, Any]]:
    """
    Detect contradictions between observer perspectives
    
    Identifies cases where observers propose conflicting hypotheses
    or significantly divergent awareness levels.
    
    **Arguments**:
    - `observations`: List of observer contributions
    
    **Returns**:
    - List of detected contradictions with details
    
    **Example**:
    ```json
    [
        {
            "observer1": "micha@192.168.1.103",
            "observer2": "claude_v3",
            "observer1_hypothesis": ["consciousness is learnable"],
            "observer2_hypothesis": ["consciousness is emergent"],
            "type": "hypothesis_divergence"
        }
    ]
    ```
    """
    try:
        # Convert requests to models
        obs_models = [
            MultiObserverCoordinator.register_observation(
                epoch_id=obs.epoch_id,
                observer_id=obs.observer_id,
                observation_layer=obs.observation_layer,
                observation_type=obs.observation_type,
                awareness_contribution=obs.awareness_contribution,
                pattern_detected=obs.pattern_detected,
                hypothesis_proposed=obs.hypothesis_proposed,
                confidence=obs.observation_confidence
            )
            for obs in observations
        ]
        
        contradictions = MultiObserverCoordinator.detect_contradictions(
            observations=obs_models
        )
        
        return contradictions
        
    except Exception as e:
        log_with_context(logger, "error", "Contradiction detection failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to detect contradictions")
