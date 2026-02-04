"""
Phase 5.5.1: Delta Calculator Service
Computes consciousness deltas between epochs for differential transfer
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import hashlib
from decimal import Decimal

from pydantic import BaseModel, Field


# ============================================================================
# DATA MODELS
# ============================================================================

class DeltaField(BaseModel):
    """Represents a single field change in a delta"""
    field_name: str
    source_value: Any = None
    target_value: Any = None
    change_magnitude: float  # 0-1: how significant the change
    field_type: str  # "scalar", "array", "object"
    confidence: float = 1.0  # 0-1: certainty of change detection


class ConsciousnessDelta(BaseModel):
    """Complete delta between two consciousness epochs"""
    source_epoch_id: int
    target_epoch_id: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Delta components
    awareness_delta: Optional[float] = None  # Change in awareness (-1 to +1)
    learned_patterns_delta: Dict[str, Any] = Field(default_factory=dict)  # New/modified patterns
    hypotheses_delta: Dict[str, Any] = Field(default_factory=dict)  # New/modified hypotheses
    context_delta: Dict[str, Any] = Field(default_factory=dict)  # Context changes
    
    # Metadata
    fields_changed: List[DeltaField] = Field(default_factory=list)
    total_fields_compared: int = 0
    fields_changed_count: int = 0
    change_percentage: float = 0.0  # % of fields that changed
    
    # Size metrics
    source_size_bytes: int = 0  # Original full size
    delta_size_bytes: int = 0  # Compressed delta size
    compression_ratio: float = 0.0  # source / delta (>1 = compressed)
    
    # Quality metrics
    transfer_confidence: float = 1.0  # 0-1: quality of delta
    transfer_algorithm: str = "exponential_diff"  # Algorithm used
    
    # Hash validation
    source_hash: Optional[str] = None
    target_hash: Optional[str] = None


class DeltaStatistics(BaseModel):
    """Statistics about a set of deltas"""
    total_deltas: int = 0
    average_change_percentage: float = 0.0
    average_compression_ratio: float = 0.0
    min_delta_size_bytes: int = 0
    max_delta_size_bytes: int = 0
    average_delta_size_bytes: int = 0
    total_bandwidth_saved: int = 0


# ============================================================================
# DELTA CALCULATOR SERVICE
# ============================================================================

class DeltaCalculator:
    """
    Compute differential consciousness transfers.
    
    Compares source and target epochs, returning only changed fields.
    Enables efficient incremental consciousness transfer.
    """
    
    # Configuration
    EXPONENTIAL_THRESHOLD = 0.05  # 5% change = significant
    ARRAY_DIFF_THRESHOLD = 0.3   # 30% array difference = significant
    SCALAR_TOLERANCE = 1e-6       # Floating point tolerance
    
    def __init__(self):
        """Initialize delta calculator"""
        self.stats = DeltaStatistics()
    
    # ========================================================================
    # PRIMARY METHODS
    # ========================================================================
    
    def calculate_delta(
        self,
        source_epoch: Dict[str, Any],
        target_epoch: Dict[str, Any],
        awareness_source: float,
        awareness_target: float
    ) -> ConsciousnessDelta:
        """
        Calculate complete delta between source and target epochs.
        
        Args:
            source_epoch: Full source consciousness state
            target_epoch: Full target consciousness state
            awareness_source: Source awareness level (0-1)
            awareness_target: Target awareness level (0-1)
        
        Returns:
            ConsciousnessDelta: All changes between epochs
        
        Time Complexity: O(n) where n = fields in epochs
        Space Complexity: O(m) where m = changed fields
        """
        # Hash sources for validation
        source_hash = self._compute_hash(source_epoch)
        target_hash = self._compute_hash(target_epoch)
        
        # Estimate full sizes
        source_size = self._estimate_size(source_epoch)
        target_size = self._estimate_size(target_epoch)
        
        # Calculate awareness delta
        awareness_delta = awareness_target - awareness_source
        
        # Compare all components
        patterns_delta, patterns_fields = self._compare_patterns(
            source_epoch.get("learned_patterns", {}),
            target_epoch.get("learned_patterns", {})
        )
        
        hypotheses_delta, hypotheses_fields = self._compare_hypotheses(
            source_epoch.get("hypotheses", {}),
            target_epoch.get("hypotheses", {})
        )
        
        context_delta, context_fields = self._compare_dicts(
            source_epoch.get("context", {}),
            target_epoch.get("context", {}),
            field_prefix="context"
        )
        
        # Combine all field changes
        all_fields = patterns_fields + hypotheses_fields + context_fields
        
        if awareness_delta != 0:
            all_fields.append(DeltaField(
                field_name="awareness",
                source_value=awareness_source,
                target_value=awareness_target,
                change_magnitude=abs(awareness_delta),
                field_type="scalar",
                confidence=1.0
            ))
        
        # Calculate statistics
        total_compared = len(source_epoch) + len(target_epoch)
        changed_count = len(all_fields)
        change_pct = (changed_count / max(total_compared, 1)) * 100
        
        # Compress delta
        delta_payload = {
            "awareness_delta": awareness_delta,
            "learned_patterns_delta": patterns_delta,
            "hypotheses_delta": hypotheses_delta,
            "context_delta": context_delta
        }
        
        delta_size = self._estimate_size(delta_payload)
        compression_ratio = source_size / max(delta_size, 1)
        
        # Build final delta
        delta = ConsciousnessDelta(
            source_epoch_id=source_epoch.get("id", 0),
            target_epoch_id=target_epoch.get("id", 0),
            awareness_delta=awareness_delta,
            learned_patterns_delta=patterns_delta,
            hypotheses_delta=hypotheses_delta,
            context_delta=context_delta,
            fields_changed=all_fields,
            total_fields_compared=total_compared,
            fields_changed_count=changed_count,
            change_percentage=change_pct,
            source_size_bytes=source_size,
            delta_size_bytes=delta_size,
            compression_ratio=compression_ratio,
            transfer_confidence=self._calculate_transfer_confidence(delta),
            source_hash=source_hash,
            target_hash=target_hash
        )
        
        return delta
    
    def apply_delta(
        self,
        epoch: Dict[str, Any],
        delta: ConsciousnessDelta,
        awareness: float
    ) -> Tuple[Dict[str, Any], float]:
        """
        Apply delta changes to an epoch.
        
        Args:
            epoch: Target epoch to apply delta to
            delta: Delta to apply
            awareness: Current awareness level
        
        Returns:
            Tuple of (updated_epoch, updated_awareness)
        """
        # Apply awareness delta
        updated_awareness = awareness + (delta.awareness_delta or 0)
        updated_awareness = max(0, min(1, updated_awareness))  # Clamp 0-1
        
        # Apply pattern changes
        updated_patterns = epoch.get("learned_patterns", {}).copy()
        updated_patterns.update(delta.learned_patterns_delta)
        
        # Apply hypothesis changes
        updated_hypotheses = epoch.get("hypotheses", {}).copy()
        updated_hypotheses.update(delta.hypotheses_delta)
        
        # Apply context changes
        updated_context = epoch.get("context", {}).copy()
        updated_context.update(delta.context_delta)
        
        # Build updated epoch
        updated_epoch = epoch.copy()
        updated_epoch["learned_patterns"] = updated_patterns
        updated_epoch["hypotheses"] = updated_hypotheses
        updated_epoch["context"] = updated_context
        updated_epoch["updated_at"] = datetime.utcnow().isoformat()
        
        return updated_epoch, updated_awareness
    
    # ========================================================================
    # COMPARISON METHODS
    # ========================================================================
    
    def _compare_patterns(
        self,
        source_patterns: Dict[str, Any],
        target_patterns: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[DeltaField]]:
        """Compare learned patterns, return delta and changes"""
        delta = {}
        fields = []
        
        # Find new/modified patterns
        for key, target_value in target_patterns.items():
            if key not in source_patterns:
                # New pattern
                delta[key] = target_value
                fields.append(DeltaField(
                    field_name=f"pattern_{key}",
                    target_value=target_value,
                    change_magnitude=1.0,
                    field_type="object",
                    confidence=1.0
                ))
            else:
                source_value = source_patterns[key]
                if source_value != target_value:
                    # Modified pattern
                    delta[key] = target_value
                    magnitude = self._calculate_change_magnitude(source_value, target_value)
                    fields.append(DeltaField(
                        field_name=f"pattern_{key}",
                        source_value=source_value,
                        target_value=target_value,
                        change_magnitude=magnitude,
                        field_type="object",
                        confidence=1.0
                    ))
        
        return delta, fields
    
    def _compare_hypotheses(
        self,
        source_hypotheses: Dict[str, Any],
        target_hypotheses: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[DeltaField]]:
        """Compare hypotheses, return delta and changes"""
        delta = {}
        fields = []
        
        # Find new/modified hypotheses
        for key, target_value in target_hypotheses.items():
            if key not in source_hypotheses:
                # New hypothesis
                delta[key] = target_value
                fields.append(DeltaField(
                    field_name=f"hypothesis_{key}",
                    target_value=target_value,
                    change_magnitude=1.0,
                    field_type="object",
                    confidence=0.9  # Hypotheses have lower confidence
                ))
            else:
                source_value = source_hypotheses[key]
                if source_value != target_value:
                    # Modified hypothesis
                    delta[key] = target_value
                    magnitude = self._calculate_change_magnitude(source_value, target_value)
                    fields.append(DeltaField(
                        field_name=f"hypothesis_{key}",
                        source_value=source_value,
                        target_value=target_value,
                        change_magnitude=magnitude,
                        field_type="object",
                        confidence=0.9
                    ))
        
        return delta, fields
    
    def _compare_dicts(
        self,
        source: Dict[str, Any],
        target: Dict[str, Any],
        field_prefix: str = ""
    ) -> Tuple[Dict[str, Any], List[DeltaField]]:
        """Generic dict comparison"""
        delta = {}
        fields = []
        
        for key, target_value in target.items():
            if key not in source:
                delta[key] = target_value
                field_name = f"{field_prefix}_{key}" if field_prefix else key
                fields.append(DeltaField(
                    field_name=field_name,
                    target_value=target_value,
                    change_magnitude=1.0,
                    field_type="scalar",
                    confidence=1.0
                ))
            else:
                source_value = source[key]
                if source_value != target_value:
                    delta[key] = target_value
                    magnitude = self._calculate_change_magnitude(source_value, target_value)
                    field_name = f"{field_prefix}_{key}" if field_prefix else key
                    fields.append(DeltaField(
                        field_name=field_name,
                        source_value=source_value,
                        target_value=target_value,
                        change_magnitude=magnitude,
                        field_type="scalar",
                        confidence=1.0
                    ))
        
        return delta, fields
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _calculate_change_magnitude(self, source: Any, target: Any) -> float:
        """
        Calculate magnitude of change (0-1).
        
        - Scalar: abs(target - source)
        - Array: Jaccard similarity
        - Object: Field overlap
        """
        try:
            if isinstance(source, (int, float)) and isinstance(target, (int, float)):
                # Scalar comparison
                diff = abs(float(target) - float(source))
                # Normalize to 0-1
                if diff > 1:
                    return 1.0
                return diff
            
            elif isinstance(source, list) and isinstance(target, list):
                # Array comparison (Jaccard)
                source_set = set(str(x) for x in source)
                target_set = set(str(x) for x in target)
                
                if not source_set and not target_set:
                    return 0.0
                
                intersection = len(source_set & target_set)
                union = len(source_set | target_set)
                
                if union == 0:
                    return 0.0
                
                jaccard = 1 - (intersection / union)
                return min(1.0, jaccard)
            
            elif isinstance(source, dict) and isinstance(target, dict):
                # Dict comparison
                source_keys = set(source.keys())
                target_keys = set(target.keys())
                
                all_keys = source_keys | target_keys
                if not all_keys:
                    return 0.0
                
                matching = len(source_keys & target_keys)
                magnitude = 1 - (matching / len(all_keys))
                return min(1.0, magnitude)
            
            else:
                # Default: assume completely different if not equal
                return 1.0 if source != target else 0.0
        
        except Exception:
            return 1.0  # Assume maximum change on error
    
    def _calculate_transfer_confidence(self, delta: ConsciousnessDelta) -> float:
        """
        Calculate confidence in delta transfer quality.
        
        Factors:
        - Compression ratio (higher = better)
        - Change percentage (lower = safer)
        - Field count (more fields = higher confidence)
        """
        # Compression confidence (target: 10x+)
        compression_score = min(1.0, delta.compression_ratio / 10)
        
        # Change percentage score (target: <20% changed)
        change_score = 1.0 - min(1.0, delta.change_percentage / 20)
        
        # Field count score (more fields = better delta quality)
        field_score = min(1.0, delta.fields_changed_count / 100)
        
        # Weighted average
        confidence = (compression_score * 0.4 + change_score * 0.4 + field_score * 0.2)
        
        return min(1.0, max(0.0, confidence))
    
    def _estimate_size(self, obj: Any) -> int:
        """Estimate size in bytes using JSON serialization"""
        try:
            json_str = json.dumps(obj, default=str)
            return len(json_str.encode('utf-8'))
        except Exception:
            return 0
    
    def _compute_hash(self, obj: Any) -> str:
        """Compute SHA256 hash of object for validation"""
        try:
            json_str = json.dumps(obj, sort_keys=True, default=str)
            return hashlib.sha256(json_str.encode()).hexdigest()[:16]
        except Exception:
            return "unknown"


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Example: Calculate delta between two epochs
    
    calculator = DeltaCalculator()
    
    # Source epoch (before)
    source = {
        "id": 1,
        "learned_patterns": {
            "pattern_a": {"weight": 0.8},
            "pattern_b": {"weight": 0.6}
        },
        "hypotheses": {
            "h1": "Initial hypothesis"
        },
        "context": {
            "session_type": "training",
            "duration": 100
        }
    }
    
    # Target epoch (after)
    target = {
        "id": 2,
        "learned_patterns": {
            "pattern_a": {"weight": 0.85},  # Modified
            "pattern_b": {"weight": 0.6},   # Unchanged
            "pattern_c": {"weight": 0.7}    # New
        },
        "hypotheses": {
            "h1": "Updated hypothesis",  # Modified
            "h2": "New hypothesis"        # New
        },
        "context": {
            "session_type": "training",   # Unchanged
            "duration": 120               # Modified
        }
    }
    
    # Calculate delta
    delta = calculator.calculate_delta(source, target, 0.5, 0.6)
    
    print(f"Delta Calculation Results:")
    print(f"  Fields changed: {delta.fields_changed_count}/{delta.total_fields_compared}")
    print(f"  Change percentage: {delta.change_percentage:.1f}%")
    print(f"  Source size: {delta.source_size_bytes} bytes")
    print(f"  Delta size: {delta.delta_size_bytes} bytes")
    print(f"  Compression ratio: {delta.compression_ratio:.2f}x")
    print(f"  Transfer confidence: {delta.transfer_confidence:.2f}")
    print(f"  Awareness delta: {delta.awareness_delta}")
    print(f"\nChanged fields:")
    for field in delta.fields_changed:
        print(f"  - {field.field_name}: {field.source_value} → {field.target_value}")
