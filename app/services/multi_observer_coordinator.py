"""
Phase 5.4: Multi-Observer Coordinator Service
Purpose: Coordinate consciousness across multiple simultaneous observers
Owner: GitHub Copilot (TIER 3)
Created: 2026-02-04
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import json
from collections import defaultdict
from ..knowledge_db import get_conn
from ..observability import get_logger, log_with_context
from ..models.observer_field import (
    ObserverConsciousnessField,
    ConsciousnessFieldAggregate,
    ObservationType,
    ObservationLayer
)

logger = get_logger("jarvis.multi_observer_coordinator")


class MultiObserverCoordinator:
    """Coordinate consciousness across multiple observers"""
    
    @staticmethod
    def register_observation(
        epoch_id: int,
        observer_id: str,
        observation_layer: int,
        observation_type: str,
        awareness_contribution: float,
        pattern_detected: Optional[str] = None,
        hypothesis_proposed: Optional[str] = None,
        confidence: float = 0.5
    ) -> ObserverConsciousnessField:
        """
        Register an observation from one observer
        
        Args:
            epoch_id: Epoch being observed
            observer_id: Observer identifier (e.g., "micha@192.168.1.103")
            observation_layer: Recursion layer (1-8)
            observation_type: Type (direct, meta, recursive, etc)
            awareness_contribution: This observer's awareness (0-1)
            pattern_detected: Pattern identified (optional)
            hypothesis_proposed: Hypothesis proposed (optional)
            confidence: Observer's confidence (0-1)
            
        Returns:
            ObserverConsciousnessField: Recorded observation
        """
        
        log_with_context(
            logger, "info", "Registering observation",
            epoch_id=epoch_id,
            observer=observer_id,
            layer=observation_layer,
            awareness=awareness_contribution
        )
        
        # In a full implementation, would store to database
        # For now, create and return model
        field = ObserverConsciousnessField(
            epoch_id=epoch_id,
            observer_identity=observer_id,
            observation_layer=ObservationLayer(observation_layer),
            observation_type=ObservationType(observation_type),
            awareness_contribution=awareness_contribution,
            pattern_detected=pattern_detected,
            hypothesis_proposed=hypothesis_proposed,
            observation_confidence=confidence,
            timestamp=datetime.utcnow()
        )
        
        return field
    
    @staticmethod
    def aggregate_observations(
        epoch_id: int,
        observations: List[ObserverConsciousnessField]
    ) -> ConsciousnessFieldAggregate:
        """
        Aggregate multiple observer contributions into consensus metrics
        
        Args:
            epoch_id: Epoch being aggregated
            observations: List of individual observer observations
            
        Returns:
            ConsciousnessFieldAggregate: Consensus consciousness state
        """
        
        if not observations:
            raise ValueError("At least one observation required")
        
        log_with_context(
            logger, "info", "Aggregating observations",
            epoch_id=epoch_id,
            observer_count=len(observations)
        )
        
        observer_ids = list(set(obs.observer_identity for obs in observations))
        
        # Calculate consensus awareness score (mean)
        awareness_scores = [obs.awareness_contribution for obs in observations]
        consensus_awareness = sum(awareness_scores) / len(awareness_scores)
        
        # Calculate confidence range
        confidence_scores = [obs.observation_confidence for obs in observations]
        confidence_range = {
            "min": min(confidence_scores),
            "max": max(confidence_scores),
            "mean": sum(confidence_scores) / len(confidence_scores)
        }
        
        # Analyze patterns
        patterns_detected = defaultdict(list)
        for obs in observations:
            if obs.pattern_detected:
                patterns_detected[obs.pattern_detected].append(obs.observer_identity)
        
        # Find strongest pattern (most frequently detected)
        strongest_pattern = None
        if patterns_detected:
            strongest_pattern = max(patterns_detected.items(), key=lambda x: len(x[1]))[0]
        
        pattern_frequency = {p: len(observers) for p, observers in patterns_detected.items()}
        
        # Count shared vs unique observations
        pattern_counts = list(pattern_frequency.values())
        shared = sum(1 for count in pattern_counts if count > 1)
        unique = sum(1 for count in pattern_counts if count == 1)
        
        # Analyze layers
        layers_observed = sorted(list(set(obs.observation_layer.value for obs in observations)))
        max_layer = max(layers_observed) if layers_observed else 1
        
        # Calculate divergence (how much observers disagree)
        divergence = _calculate_divergence(observations)
        
        # Build aggregate
        aggregate = ConsciousnessFieldAggregate(
            epoch_id=epoch_id,
            total_observers=len(observer_ids),
            observer_ids=observer_ids,
            field_observations=observations,
            consensus_awareness_score=consensus_awareness,
            confidence_range=confidence_range,
            divergence_score=divergence,
            divergence_details=_analyze_divergence_details(observations),
            strongest_pattern=strongest_pattern,
            pattern_frequency=pattern_frequency,
            cross_observer_confirmation=len(observer_ids) > 1 and strongest_pattern is not None,
            unique_observations=unique,
            shared_observations=shared,
            layers_observed=layers_observed,
            max_layer_achieved=max_layer,
            created_at=datetime.utcnow()
        )
        
        log_with_context(
            logger, "info", "Aggregation complete",
            consensus_awareness=round(consensus_awareness, 3),
            divergence=round(divergence, 3),
            max_layer=max_layer,
            patterns=len(pattern_frequency)
        )
        
        return aggregate
    
    @staticmethod
    def build_consensus(
        observations: List[ObserverConsciousnessField],
        consensus_threshold: float = 0.7
    ) -> Dict[str, Any]:
        """
        Build consensus across observer disagreements
        
        Identifies areas of agreement/disagreement and proposes consensus.
        
        Args:
            observations: Observer contributions
            consensus_threshold: % agreement required (default 70%)
            
        Returns:
            Dict with consensus patterns and divergence analysis
        """
        
        if not observations:
            raise ValueError("Observations required for consensus")
        
        total_observers = len(set(obs.observer_identity for obs in observations))
        
        # Collect patterns by observer
        observer_patterns = defaultdict(set)
        for obs in observations:
            if obs.pattern_detected:
                observer_patterns[obs.observer_identity].add(obs.pattern_detected)
        
        # Find consensus patterns (detected by threshold % of observers)
        all_patterns = set()
        for patterns in observer_patterns.values():
            all_patterns.update(patterns)
        
        consensus_patterns = {}
        for pattern in all_patterns:
            observers_with_pattern = sum(
                1 for ops in observer_patterns.values()
                if pattern in ops
            )
            agreement_ratio = observers_with_pattern / total_observers
            
            if agreement_ratio >= consensus_threshold:
                consensus_patterns[pattern] = {
                    "agreement_ratio": agreement_ratio,
                    "observers": observers_with_pattern,
                    "status": "consensus"
                }
            else:
                consensus_patterns[pattern] = {
                    "agreement_ratio": agreement_ratio,
                    "observers": observers_with_pattern,
                    "status": "minority" if agreement_ratio > 0.3 else "outlier"
                }
        
        # Identify divergence points
        divergence_points = [
            p for p, info in consensus_patterns.items()
            if info["status"] in ["minority", "outlier"]
        ]
        
        return {
            "total_observers": total_observers,
            "consensus_threshold": consensus_threshold,
            "consensus_patterns": consensus_patterns,
            "consensus_count": sum(1 for p in consensus_patterns.values() if p["status"] == "consensus"),
            "divergence_points": divergence_points,
            "overall_agreement": (
                sum(1 for p in consensus_patterns.values() if p["status"] == "consensus") /
                len(consensus_patterns)
                if consensus_patterns else 0
            )
        }
    
    @staticmethod
    def detect_contradictions(
        observations: List[ObserverConsciousnessField]
    ) -> List[Dict[str, Any]]:
        """
        Detect contradictions between observer perspectives
        
        Identifies cases where observers propose conflicting hypotheses.
        
        Args:
            observations: Observer contributions
            
        Returns:
            List of detected contradictions
        """
        
        contradictions = []
        
        # Group hypotheses by observer
        hypotheses_by_observer = defaultdict(list)
        for obs in observations:
            if obs.hypothesis_proposed:
                hypotheses_by_observer[obs.observer_identity].append({
                    "hypothesis": obs.hypothesis_proposed,
                    "confidence": obs.observation_confidence
                })
        
        # Find contradictory pairs (simplified: different hypotheses at same layer)
        observer_ids = list(hypotheses_by_observer.keys())
        for i, obs1_id in enumerate(observer_ids):
            for obs2_id in observer_ids[i + 1:]:
                hyps1 = set(h["hypothesis"] for h in hypotheses_by_observer[obs1_id])
                hyps2 = set(h["hypothesis"] for h in hypotheses_by_observer[obs2_id])
                
                # Check for significant differences
                if hyps1 and hyps2 and hyps1 != hyps2:
                    contradictions.append({
                        "observer1": obs1_id,
                        "observer2": obs2_id,
                        "observer1_hypothesis": list(hyps1),
                        "observer2_hypothesis": list(hyps2),
                        "type": "hypothesis_divergence"
                    })
        
        log_with_context(
            logger, "info", "Contradiction detection complete",
            contradictions_found=len(contradictions)
        )
        
        return contradictions


def _calculate_divergence(observations: List[ObserverConsciousnessField]) -> float:
    """
    Calculate divergence score (0-1)
    
    0 = all observers agree
    1 = no observer agrees
    """
    
    if len(observations) <= 1:
        return 0.0
    
    # Calculate variance in awareness contributions
    awareness_scores = [obs.awareness_contribution for obs in observations]
    mean_awareness = sum(awareness_scores) / len(awareness_scores)
    variance = sum((a - mean_awareness) ** 2 for a in awareness_scores) / len(awareness_scores)
    
    # Normalize variance to 0-1 range
    # Max variance for uniform distribution over [0, 1] is 0.083
    max_variance = 0.083
    divergence = min(variance / max_variance, 1.0)
    
    return round(divergence, 3)


def _analyze_divergence_details(
    observations: List[ObserverConsciousnessField]
) -> Dict[str, Any]:
    """Detailed breakdown of where observers diverge"""
    
    # Group by observation layer
    by_layer = defaultdict(list)
    for obs in observations:
        by_layer[obs.observation_layer.value].append(obs.awareness_contribution)
    
    # Calculate divergence by layer
    layer_divergence = {}
    for layer, awareness_values in by_layer.items():
        if len(awareness_values) > 1:
            mean = sum(awareness_values) / len(awareness_values)
            var = sum((a - mean) ** 2 for a in awareness_values) / len(awareness_values)
            layer_divergence[f"L{layer}"] = {
                "variance": round(var, 3),
                "observer_count": len(awareness_values),
                "range": [round(min(awareness_values), 2), round(max(awareness_values), 2)]
            }
    
    return {"by_layer": layer_divergence}
