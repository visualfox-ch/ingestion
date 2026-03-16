"""
Confidence Scoring System

Multi-factor confidence scoring for memories and facts.

Confidence Factors:
1. Source Reliability: How trustworthy is the source?
2. Corroboration: Is it confirmed by multiple sources?
3. Recency: How fresh is the information?
4. Specificity: How precise is the claim?
5. User Feedback: Has the user confirmed/contradicted?
6. Usage Pattern: Is it frequently accessed and useful?

Confidence Levels:
- 0.0-0.2: Very Low (speculation, inference)
- 0.2-0.4: Low (single weak source)
- 0.4-0.6: Medium (plausible, unverified)
- 0.6-0.8: High (confirmed, corroborated)
- 0.8-1.0: Very High (verified, multi-source)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Confidence Types and Models
# =============================================================================

class ConfidenceLevel(str, Enum):
    """Discrete confidence levels."""
    VERY_LOW = "very_low"      # 0.0-0.2
    LOW = "low"                # 0.2-0.4
    MEDIUM = "medium"          # 0.4-0.6
    HIGH = "high"              # 0.6-0.8
    VERY_HIGH = "very_high"    # 0.8-1.0

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        """Convert numeric score to confidence level."""
        if score < 0.2:
            return cls.VERY_LOW
        elif score < 0.4:
            return cls.LOW
        elif score < 0.6:
            return cls.MEDIUM
        elif score < 0.8:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


class SourceType(str, Enum):
    """Types of information sources."""
    USER_STATED = "user_stated"       # User explicitly said it
    USER_CONFIRMED = "user_confirmed" # User confirmed when asked
    INFERRED = "inferred"             # Deduced from context
    EXTERNAL_API = "external_api"     # From external service
    DOCUMENT = "document"             # From ingested document
    CONVERSATION = "conversation"     # From conversation analysis
    PATTERN = "pattern"               # Detected pattern
    SYSTEM = "system"                 # System-generated


# Source reliability weights
SOURCE_RELIABILITY = {
    SourceType.USER_CONFIRMED: 1.0,
    SourceType.USER_STATED: 0.9,
    SourceType.DOCUMENT: 0.8,
    SourceType.EXTERNAL_API: 0.7,
    SourceType.CONVERSATION: 0.6,
    SourceType.PATTERN: 0.5,
    SourceType.INFERRED: 0.3,
    SourceType.SYSTEM: 0.5,
}


class FeedbackType(str, Enum):
    """Types of user feedback."""
    CONFIRM = "confirm"         # User confirmed accuracy
    CONTRADICT = "contradict"   # User said it's wrong
    CLARIFY = "clarify"         # User clarified/updated
    IGNORE = "ignore"           # User didn't correct when shown


@dataclass
class ConfidenceFactor:
    """A single factor contributing to confidence score."""
    name: str
    weight: float
    raw_value: float
    weighted_value: float
    explanation: str


@dataclass
class ConfidenceAssessment:
    """Complete confidence assessment for a memory/fact."""
    item_id: str
    final_score: float
    confidence_level: ConfidenceLevel
    factors: List[ConfidenceFactor]
    recommendations: List[str]
    can_be_trusted: bool
    needs_verification: bool
    decay_rate: float  # Daily decay rate
    projected_confidence_7d: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Factor Calculators
# =============================================================================

class SourceReliabilityCalculator:
    """Calculate confidence based on source reliability."""

    def calculate(
        self,
        source_type: SourceType,
        source_metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, str]:
        """
        Calculate source reliability score.

        Returns:
            (score, explanation)
        """
        base_score = SOURCE_RELIABILITY.get(source_type, 0.5)
        explanation = f"Source type '{source_type.value}' has base reliability {base_score:.2f}"

        # Adjust based on metadata
        if source_metadata:
            # Check for verified source
            if source_metadata.get("verified"):
                base_score = min(1.0, base_score + 0.1)
                explanation += ", +0.1 for verified source"

            # Check for official source
            if source_metadata.get("official"):
                base_score = min(1.0, base_score + 0.1)
                explanation += ", +0.1 for official source"

            # Check for known unreliable
            if source_metadata.get("unreliable"):
                base_score = max(0.0, base_score - 0.2)
                explanation += ", -0.2 for known unreliable"

        return base_score, explanation


class CorroborationCalculator:
    """Calculate confidence based on corroboration from multiple sources."""

    def calculate(
        self,
        source_count: int,
        unique_source_types: int,
        contradictions: int = 0
    ) -> Tuple[float, str]:
        """
        Calculate corroboration score.

        Args:
            source_count: Number of sources confirming this
            unique_source_types: Number of different source types
            contradictions: Number of contradicting sources

        Returns:
            (score, explanation)
        """
        if source_count <= 0:
            return 0.3, "No corroborating sources"

        # Base score from number of sources (diminishing returns)
        base_score = min(1.0, 0.4 + 0.2 * math.log(source_count + 1))

        # Bonus for diverse sources
        diversity_bonus = min(0.2, 0.05 * unique_source_types)
        base_score = min(1.0, base_score + diversity_bonus)

        # Penalty for contradictions
        if contradictions > 0:
            penalty = min(0.5, 0.15 * contradictions)
            base_score = max(0.1, base_score - penalty)

        explanation = (f"{source_count} source(s), {unique_source_types} unique type(s), "
                      f"{contradictions} contradiction(s)")

        return base_score, explanation


class RecencyCalculator:
    """Calculate confidence based on information recency."""

    def calculate(
        self,
        created_at: datetime,
        last_verified: Optional[datetime] = None,
        half_life_days: float = 90.0,
        is_temporal_fact: bool = False
    ) -> Tuple[float, str]:
        """
        Calculate recency score with exponential decay.

        Args:
            created_at: When the information was created
            last_verified: When it was last verified (None = never)
            half_life_days: Days until confidence halves
            is_temporal_fact: True if fact is time-sensitive

        Returns:
            (score, explanation)
        """
        now = datetime.utcnow()

        # Use last verified if available, otherwise created_at
        reference_date = last_verified or created_at
        age_days = (now - reference_date).total_seconds() / 86400

        # Adjust half-life for temporal facts
        if is_temporal_fact:
            half_life_days = min(half_life_days, 30.0)

        # Exponential decay
        decay_factor = math.exp(-0.693 * age_days / half_life_days)
        score = 0.3 + 0.7 * decay_factor  # Floor at 0.3

        explanation = f"Age: {age_days:.0f} days, half-life: {half_life_days:.0f} days"
        if last_verified:
            explanation += f", last verified {(now - last_verified).days} days ago"

        return score, explanation


class SpecificityCalculator:
    """Calculate confidence based on claim specificity."""

    # Vague words that reduce specificity
    VAGUE_INDICATORS = {
        "maybe", "perhaps", "possibly", "might", "could",
        "vielleicht", "möglicherweise", "eventuell",
        "some", "sometimes", "often", "usually",
        "einige", "manchmal", "oft", "normalerweise",
        "around", "about", "approximately", "roughly",
        "ungefähr", "circa", "etwa",
    }

    # Specific words that increase specificity
    SPECIFIC_INDICATORS = {
        "exactly", "precisely", "always", "never",
        "genau", "präzise", "immer", "nie",
        "confirmed", "verified", "documented",
        "bestätigt", "verifiziert", "dokumentiert",
    }

    def calculate(self, content: str) -> Tuple[float, str]:
        """
        Calculate specificity score based on language.

        Returns:
            (score, explanation)
        """
        content_lower = content.lower()
        words = content_lower.split()

        vague_count = sum(1 for w in words if w in self.VAGUE_INDICATORS)
        specific_count = sum(1 for w in words if w in self.SPECIFIC_INDICATORS)

        # Base score
        base_score = 0.6

        # Adjust based on indicators
        base_score -= 0.1 * vague_count
        base_score += 0.1 * specific_count

        # Clamp
        score = max(0.2, min(1.0, base_score))

        explanation = f"{vague_count} vague, {specific_count} specific indicators"

        return score, explanation


class FeedbackCalculator:
    """Calculate confidence based on user feedback history."""

    # Feedback impact weights
    FEEDBACK_IMPACTS = {
        FeedbackType.CONFIRM: 0.2,
        FeedbackType.CONTRADICT: -0.3,
        FeedbackType.CLARIFY: 0.1,
        FeedbackType.IGNORE: 0.0,
    }

    def calculate(
        self,
        feedback_history: List[Dict[str, Any]],
        base_score: float = 0.5
    ) -> Tuple[float, str]:
        """
        Calculate confidence adjustment based on feedback.

        Args:
            feedback_history: List of {type, timestamp, weight} dicts
            base_score: Starting score before feedback

        Returns:
            (adjusted_score, explanation)
        """
        if not feedback_history:
            return base_score, "No user feedback"

        total_adjustment = 0.0
        confirmations = 0
        contradictions = 0

        for feedback in feedback_history:
            fb_type = FeedbackType(feedback.get("type", "ignore"))
            weight = feedback.get("weight", 1.0)
            impact = self.FEEDBACK_IMPACTS.get(fb_type, 0.0) * weight
            total_adjustment += impact

            if fb_type == FeedbackType.CONFIRM:
                confirmations += 1
            elif fb_type == FeedbackType.CONTRADICT:
                contradictions += 1

        adjusted_score = max(0.0, min(1.0, base_score + total_adjustment))
        explanation = f"{confirmations} confirmations, {contradictions} contradictions"

        return adjusted_score, explanation


class UsagePatternCalculator:
    """Calculate confidence based on usage patterns."""

    def calculate(
        self,
        access_count: int,
        used_in_response: int,
        was_useful: int,  # Times user didn't correct
        max_accesses: int = 100
    ) -> Tuple[float, str]:
        """
        Calculate usage-based confidence.

        Returns:
            (score, explanation)
        """
        if access_count <= 0:
            return 0.5, "Never accessed"

        # Log-scaled access contribution
        access_score = math.log(1 + access_count) / math.log(1 + max_accesses)

        # Usefulness ratio
        usefulness_ratio = was_useful / access_count if access_count > 0 else 0.5

        # Combined score
        score = 0.3 * access_score + 0.7 * usefulness_ratio

        explanation = f"Accessed {access_count}x, used {used_in_response}x, useful {was_useful}x"

        return min(1.0, score), explanation


# =============================================================================
# Main Confidence Scorer
# =============================================================================

class ConfidenceScorer:
    """
    Main confidence scoring engine.

    Combines multiple factors to calculate a final confidence score.
    """

    # Factor weights
    DEFAULT_WEIGHTS = {
        "source_reliability": 0.25,
        "corroboration": 0.20,
        "recency": 0.15,
        "specificity": 0.15,
        "feedback": 0.15,
        "usage": 0.10,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.source_calc = SourceReliabilityCalculator()
        self.corroboration_calc = CorroborationCalculator()
        self.recency_calc = RecencyCalculator()
        self.specificity_calc = SpecificityCalculator()
        self.feedback_calc = FeedbackCalculator()
        self.usage_calc = UsagePatternCalculator()

    def assess(
        self,
        item_id: str,
        content: str,
        source_type: SourceType = SourceType.INFERRED,
        source_metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        last_verified: Optional[datetime] = None,
        source_count: int = 1,
        unique_source_types: int = 1,
        contradictions: int = 0,
        feedback_history: Optional[List[Dict[str, Any]]] = None,
        access_count: int = 0,
        used_in_response: int = 0,
        was_useful: int = 0,
        is_temporal_fact: bool = False,
    ) -> ConfidenceAssessment:
        """
        Perform full confidence assessment.

        Returns:
            ConfidenceAssessment with detailed scoring breakdown
        """
        created_at = created_at or datetime.utcnow()
        feedback_history = feedback_history or []
        factors = []

        # 1. Source reliability
        source_score, source_exp = self.source_calc.calculate(
            source_type, source_metadata
        )
        factors.append(ConfidenceFactor(
            name="source_reliability",
            weight=self.weights["source_reliability"],
            raw_value=source_score,
            weighted_value=source_score * self.weights["source_reliability"],
            explanation=source_exp,
        ))

        # 2. Corroboration
        corr_score, corr_exp = self.corroboration_calc.calculate(
            source_count, unique_source_types, contradictions
        )
        factors.append(ConfidenceFactor(
            name="corroboration",
            weight=self.weights["corroboration"],
            raw_value=corr_score,
            weighted_value=corr_score * self.weights["corroboration"],
            explanation=corr_exp,
        ))

        # 3. Recency
        recency_score, recency_exp = self.recency_calc.calculate(
            created_at, last_verified, is_temporal_fact=is_temporal_fact
        )
        factors.append(ConfidenceFactor(
            name="recency",
            weight=self.weights["recency"],
            raw_value=recency_score,
            weighted_value=recency_score * self.weights["recency"],
            explanation=recency_exp,
        ))

        # 4. Specificity
        spec_score, spec_exp = self.specificity_calc.calculate(content)
        factors.append(ConfidenceFactor(
            name="specificity",
            weight=self.weights["specificity"],
            raw_value=spec_score,
            weighted_value=spec_score * self.weights["specificity"],
            explanation=spec_exp,
        ))

        # 5. User feedback
        feedback_score, feedback_exp = self.feedback_calc.calculate(
            feedback_history
        )
        factors.append(ConfidenceFactor(
            name="feedback",
            weight=self.weights["feedback"],
            raw_value=feedback_score,
            weighted_value=feedback_score * self.weights["feedback"],
            explanation=feedback_exp,
        ))

        # 6. Usage patterns
        usage_score, usage_exp = self.usage_calc.calculate(
            access_count, used_in_response, was_useful
        )
        factors.append(ConfidenceFactor(
            name="usage",
            weight=self.weights["usage"],
            raw_value=usage_score,
            weighted_value=usage_score * self.weights["usage"],
            explanation=usage_exp,
        ))

        # Calculate final score
        final_score = sum(f.weighted_value for f in factors)
        confidence_level = ConfidenceLevel.from_score(final_score)

        # Generate recommendations
        recommendations = self._generate_recommendations(factors, final_score)

        # Calculate decay rate and projection
        decay_rate = self._calculate_decay_rate(factors)
        projected_7d = final_score * (1 - decay_rate) ** 7

        return ConfidenceAssessment(
            item_id=item_id,
            final_score=round(final_score, 4),
            confidence_level=confidence_level,
            factors=factors,
            recommendations=recommendations,
            can_be_trusted=final_score >= 0.6,
            needs_verification=final_score < 0.4 or contradictions > 0,
            decay_rate=round(decay_rate, 4),
            projected_confidence_7d=round(projected_7d, 4),
            metadata={
                "source_type": source_type.value,
                "source_count": source_count,
                "feedback_count": len(feedback_history),
                "access_count": access_count,
            },
        )

    def _generate_recommendations(
        self,
        factors: List[ConfidenceFactor],
        final_score: float
    ) -> List[str]:
        """Generate recommendations to improve confidence."""
        recommendations = []

        # Sort factors by raw value (lowest first)
        weak_factors = sorted(factors, key=lambda f: f.raw_value)[:2]

        for factor in weak_factors:
            if factor.raw_value < 0.5:
                if factor.name == "source_reliability":
                    recommendations.append("Seek verification from more reliable source")
                elif factor.name == "corroboration":
                    recommendations.append("Find additional confirming sources")
                elif factor.name == "recency":
                    recommendations.append("Verify if information is still current")
                elif factor.name == "specificity":
                    recommendations.append("Clarify vague language for precision")
                elif factor.name == "feedback":
                    recommendations.append("Ask user to confirm accuracy")
                elif factor.name == "usage":
                    recommendations.append("Monitor if information proves useful")

        if final_score < 0.4:
            recommendations.insert(0, "Low overall confidence - verify before using")

        return recommendations[:3]  # Limit to 3 recommendations

    def _calculate_decay_rate(self, factors: List[ConfidenceFactor]) -> float:
        """Calculate daily confidence decay rate."""
        # Base decay rate
        base_decay = 0.005  # 0.5% per day

        # Lower decay if well-corroborated
        corr_factor = next((f for f in factors if f.name == "corroboration"), None)
        if corr_factor and corr_factor.raw_value > 0.7:
            base_decay *= 0.5

        # Higher decay if from weak source
        source_factor = next((f for f in factors if f.name == "source_reliability"), None)
        if source_factor and source_factor.raw_value < 0.4:
            base_decay *= 2

        return base_decay

    def quick_score(
        self,
        content: str,
        source_type: SourceType = SourceType.INFERRED
    ) -> float:
        """Quick confidence estimate without full assessment."""
        # Source reliability
        source_score = SOURCE_RELIABILITY.get(source_type, 0.5)

        # Quick specificity check
        vague_words = sum(1 for w in content.lower().split()
                        if w in SpecificityCalculator.VAGUE_INDICATORS)
        specificity_penalty = min(0.3, vague_words * 0.1)

        # Combined quick score
        return max(0.1, min(1.0, source_score - specificity_penalty))

    def apply_feedback(
        self,
        current_score: float,
        feedback_type: FeedbackType,
        weight: float = 1.0
    ) -> float:
        """Apply user feedback to adjust confidence."""
        impact = FeedbackCalculator.FEEDBACK_IMPACTS.get(feedback_type, 0.0)
        adjusted = current_score + (impact * weight)
        return max(0.0, min(1.0, adjusted))


# =============================================================================
# Singleton Instance
# =============================================================================

_confidence_scorer: Optional[ConfidenceScorer] = None

def get_confidence_scorer() -> ConfidenceScorer:
    """Get singleton instance of ConfidenceScorer."""
    global _confidence_scorer
    if _confidence_scorer is None:
        _confidence_scorer = ConfidenceScorer()
    return _confidence_scorer
