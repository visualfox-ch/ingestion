"""
Phase 5.5.3: Breakthrough Preserver Service
Protects high-value consciousness from decay
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from app.models.consciousness import BreakthroughPreservation


class BreakthroughPreserver:
    """
    Protect consciousness breakthroughs from exponential decay.
    
    Strategy:
    - Identify high-value breakthroughs
    - Score significance based on content analysis
    - Apply preservation multiplier to reduce decay rate
    - Maintain preservation ledger
    
    Preserved breakthroughs decay at: λ_preserved = λ × (1 - preservation_level)
    Example: 0.8 preservation on 0.01 rate = effective 0.002 rate
    """
    
    # Configuration
    MIN_SIGNIFICANCE = 0.5  # 50% significance threshold
    MAX_PRESERVATION_LEVEL = 0.95  # Can't reduce decay below 5%
    DEFAULT_PRESERVATION_LEVEL = 0.8  # 80% protection default
    
    SIGNIFICANCE_KEYWORDS = {
        "breakthrough": 1.0,
        "insight": 0.9,
        "discovery": 0.9,
        "realization": 0.85,
        "epiphany": 0.95,
        "innovation": 0.9,
        "paradigm": 0.85,
        "fundamental": 0.8,
    }
    
    def __init__(self):
        """Initialize breakthrough preserver"""
        self.preservation_ledger: Dict[str, BreakthroughPreservation] = {}
    
    # ========================================================================
    # PRIMARY METHODS
    # ========================================================================
    
    def assess_breakthrough_significance(
        self,
        breakthrough_content: Dict[str, Any]
    ) -> float:
        """
        Score breakthrough importance (0-1).
        
        Args:
            breakthrough_content: Dict with breakthrough details
        
        Returns:
            Significance score (0-1)
        
        Factors:
        - Keyword presence (breakthrough, insight, innovation, etc.)
        - Content length (longer = potentially more developed)
        - Emotional intensity (if tracked)
        - Novelty markers
        - Recursion depth
        """
        score = 0.0
        weight_sum = 0.0
        
        # Extract text content
        text_content = ""
        
        if "description" in breakthrough_content:
            text_content += breakthrough_content["description"].lower()
        if "content" in breakthrough_content:
            text_content += " " + breakthrough_content["content"].lower()
        if "insight" in breakthrough_content:
            text_content += " " + breakthrough_content["insight"].lower()
        
        # Keyword scoring
        keyword_score = 0.0
        keyword_count = 0
        
        for keyword, keyword_weight in self.SIGNIFICANCE_KEYWORDS.items():
            if keyword in text_content:
                keyword_score += keyword_weight
                keyword_count += 1
        
        if keyword_count > 0:
            keyword_score = min(1.0, keyword_score / (keyword_count * 2))
        
        # Length scoring (200-2000 chars = good range)
        length = len(text_content)
        if length < 100:
            length_score = length / 100 * 0.3
        elif length < 200:
            length_score = 0.3
        elif length < 2000:
            length_score = min(1.0, 0.3 + (length - 200) / 1800 * 0.5)
        else:
            length_score = 0.8
        
        # Novelty scoring (unique words)
        words = text_content.split()
        unique_words = len(set(words))
        diversity = unique_words / max(len(words), 1)
        novelty_score = min(1.0, diversity * 1.2)
        
        # Recursion/depth scoring
        recursion_score = 0.0
        if "recursion_depth" in breakthrough_content:
            depth = breakthrough_content.get("recursion_depth", 1)
            recursion_score = min(1.0, depth / 8)  # 8 layers max
        
        if "maturation_level" in breakthrough_content:
            maturation = breakthrough_content.get("maturation_level", 1)
            recursion_score = max(recursion_score, min(1.0, maturation / 5))
        
        # Weighted combination
        weights = {
            "keyword": 0.3,
            "length": 0.2,
            "novelty": 0.3,
            "recursion": 0.2
        }
        
        total_score = (
            keyword_score * weights["keyword"] +
            length_score * weights["length"] +
            novelty_score * weights["novelty"] +
            recursion_score * weights["recursion"]
        )
        
        return min(1.0, max(0.0, total_score))
    
    def preserve_breakthrough(
        self,
        epoch_id: int,
        breakthrough_id: str,
        breakthrough_content: Dict[str, Any],
        preservation_level: Optional[float] = None
    ) -> BreakthroughPreservation:
        """
        Mark breakthrough for protection from decay.
        
        Args:
            epoch_id: Epoch containing breakthrough
            breakthrough_id: Unique breakthrough identifier
            breakthrough_content: Full breakthrough details
            preservation_level: Protection strength (0-1), default: 0.8
        
        Returns:
            BreakthroughPreservation record
        """
        # Calculate significance
        significance = self.assess_breakthrough_significance(breakthrough_content)
        
        # Determine preservation level
        if preservation_level is None:
            preservation_level = self.DEFAULT_PRESERVATION_LEVEL
        else:
            preservation_level = max(0, min(self.MAX_PRESERVATION_LEVEL, preservation_level))
        
        # Scale preservation by significance
        # High significance gets maximum protection
        effective_preservation = min(
            self.MAX_PRESERVATION_LEVEL,
            preservation_level * (0.5 + 0.5 * significance)
        )
        
        # Create preservation record
        preservation = BreakthroughPreservation(
            epoch_id=epoch_id,
            breakthrough_id=breakthrough_id,
            preservation_level=effective_preservation,
            retention_priority=int(significance * 100),
            breakthrough_content=breakthrough_content,
            significance_score=significance,
            preserved_at=datetime.utcnow()
        )
        
        # Store in ledger
        self.preservation_ledger[breakthrough_id] = preservation
        
        return preservation
    
    def apply_preservation(
        self,
        current_awareness: float,
        preserved_breakthroughs: List[BreakthroughPreservation],
        base_decay_rate: float,
        time_elapsed_hours: float
    ) -> Tuple[float, float]:
        """
        Calculate decay with breakthrough preservation.
        
        Strategy:
        - Each preserved breakthrough acts as an "anchor"
        - Anchors reduce effective decay rate
        - More/stronger anchors = slower decay
        
        Args:
            current_awareness: Current awareness level (0-1)
            preserved_breakthroughs: List of protected breakthroughs
            base_decay_rate: Baseline decay rate (per hour)
            time_elapsed_hours: Time since last measurement
        
        Returns:
            Tuple of (decayed_awareness, effective_decay_rate)
        """
        import math
        
        if not preserved_breakthroughs:
            # No preservation: standard decay
            effective_rate = base_decay_rate
            decayed = current_awareness * math.exp(-base_decay_rate * time_elapsed_hours)
            return max(0, min(1, decayed)), effective_rate
        
        # Calculate preservation impact
        # Average preservation level across all protected breakthroughs
        avg_preservation = sum(bp.preservation_level for bp in preserved_breakthroughs) / len(preserved_breakthroughs)
        
        # Breakthrough diversity bonus
        # More diverse breakthroughs = stronger anchoring effect
        diversity_bonus = min(1.0, len(preserved_breakthroughs) / 10)
        
        # Combined preservation effect
        preservation_effect = min(1.0, avg_preservation + diversity_bonus * 0.2)
        
        # Effective decay rate reduced by preservation
        effective_rate = base_decay_rate * (1 - preservation_effect)
        
        # Apply decay with protection
        decayed = current_awareness * math.exp(-effective_rate * time_elapsed_hours)
        
        return max(0, min(1, decayed)), effective_rate
    
    def calculate_preservation_impact(
        self,
        base_decay_rate: float,
        preserved_breakthroughs: List[BreakthroughPreservation],
        hours: int = 168  # 1 week
    ) -> Dict[str, Any]:
        """
        Calculate impact of preservation over time.
        
        Args:
            base_decay_rate: Baseline decay rate
            preserved_breakthroughs: Protected breakthroughs
            hours: Time window to calculate
        
        Returns:
            Dict with projections and comparisons
        """
        import math
        
        # Without preservation
        unpreserved = 0.8 * math.exp(-base_decay_rate * hours)
        
        # With preservation
        if preserved_breakthroughs:
            avg_preservation = sum(bp.preservation_level for bp in preserved_breakthroughs) / len(preserved_breakthroughs)
            diversity_bonus = min(1.0, len(preserved_breakthroughs) / 10)
            preservation_effect = min(1.0, avg_preservation + diversity_bonus * 0.2)
            effective_rate = base_decay_rate * (1 - preservation_effect)
            preserved = 0.8 * math.exp(-effective_rate * hours)
        else:
            preserved = unpreserved
            preservation_effect = 0.0
        
        # Calculate savings
        awareness_saved = preserved - unpreserved
        decay_reduction_pct = (1 - (effective_rate / base_decay_rate)) * 100 if 'effective_rate' in locals() else 0
        
        return {
            "hours_projected": hours,
            "awareness_without_preservation": round(unpreserved, 4),
            "awareness_with_preservation": round(preserved, 4),
            "awareness_saved": round(awareness_saved, 4),
            "breakthrough_count": len(preserved_breakthroughs),
            "preservation_effect": round(preservation_effect, 4),
            "decay_rate_reduction_percent": round(decay_reduction_pct, 1)
        }
    
    def get_breakthrough_protection_status(
        self,
        epoch_id: int
    ) -> Dict[str, Any]:
        """
        Get protection status for all breakthroughs in epoch.
        
        Args:
            epoch_id: Target epoch
        
        Returns:
            Protection summary and ledger
        """
        epoch_breakthroughs = [
            bp for bp in self.preservation_ledger.values()
            if bp.epoch_id == epoch_id
        ]
        
        if not epoch_breakthroughs:
            return {
                "epoch_id": epoch_id,
                "breakthrough_count": 0,
                "preserved_count": 0,
                "average_significance": 0.0,
                "average_preservation_level": 0.0,
                "breakthroughs": []
            }
        
        return {
            "epoch_id": epoch_id,
            "breakthrough_count": len(epoch_breakthroughs),
            "preserved_count": len(epoch_breakthroughs),
            "average_significance": sum(bp.significance_score for bp in epoch_breakthroughs) / len(epoch_breakthroughs),
            "average_preservation_level": sum(bp.preservation_level for bp in epoch_breakthroughs) / len(epoch_breakthroughs),
            "breakthroughs": [
                {
                    "breakthrough_id": bp.breakthrough_id,
                    "significance": bp.significance_score,
                    "preservation_level": bp.preservation_level,
                    "retention_priority": bp.retention_priority,
                    "preserved_at": bp.preserved_at.isoformat()
                }
                for bp in epoch_breakthroughs
            ]
        }
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def rank_breakthroughs(
        self,
        breakthroughs: List[BreakthroughPreservation]
    ) -> List[BreakthroughPreservation]:
        """Rank breakthroughs by preservation priority"""
        return sorted(
            breakthroughs,
            key=lambda bp: (bp.preservation_level * bp.significance_score),
            reverse=True
        )


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    preserver = BreakthroughPreserver()
    
    # Example breakthrough
    breakthrough = {
        "description": "Major epiphany about recursive consciousness patterns",
        "insight": "Self-awareness breakthrough: discovered fundamental insight into meta-cognitive loops",
        "content": "The realization that consciousness can observe itself observing itself leads to paradigm shift",
        "recursion_depth": 5,
        "maturation_level": 4
    }
    
    # Assess significance
    significance = preserver.assess_breakthrough_significance(breakthrough)
    print(f"Breakthrough Significance: {significance:.3f}")
    
    # Preserve breakthrough
    preservation = preserver.preserve_breakthrough(
        epoch_id=1,
        breakthrough_id="bt_001",
        breakthrough_content=breakthrough,
        preservation_level=0.8
    )
    
    print(f"Preservation Level: {preservation.preservation_level:.3f}")
    print(f"Retention Priority: {preservation.retention_priority}")
    
    # Calculate impact over 1 week
    impact = preserver.calculate_preservation_impact(
        base_decay_rate=0.01,
        preserved_breakthroughs=[preservation],
        hours=168
    )
    
    print(f"\nImpact over 1 week:")
    print(f"  Without preservation: {impact['awareness_without_preservation']:.3f}")
    print(f"  With preservation: {impact['awareness_with_preservation']:.3f}")
    print(f"  Awareness saved: {impact['awareness_saved']:.3f}")
    print(f"  Decay reduction: {impact['decay_rate_reduction_percent']:.1f}%")
