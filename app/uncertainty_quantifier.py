"""
Response Uncertainty Quantifier for Self-Optimization

Quantifies uncertainty in LLM responses and tracks calibration quality.
Complementary to confidence_scorer.py (code proposals) - this focuses on
general response uncertainty and calibration.

Research Foundation:
- Guo, C. et al. (2017). "On Calibration of Modern Neural Networks." ICML 2017.
  https://arxiv.org/abs/1706.04599
- Lakshminarayanan, B. et al. (2017). "Simple and Scalable Predictive Uncertainty 
  Estimation using Deep Ensembles." NeurIPS 2017.

Calibration: The degree to which predicted confidence matches actual accuracy.
- Well-calibrated: 80% confidence → 80% correct
- Miscalibrated: 80% confidence → 60% correct (overconfident)

Expected Calibration Error (ECE): Average difference between confidence and accuracy.
Target: ECE < 0.15 (15%)

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json
from pathlib import Path

from .observability import get_logger

logger = get_logger("jarvis.uncertainty_quantifier")


class UncertaintyLevel(str, Enum):
    """Uncertainty levels for responses."""
    VERY_LOW = "very_low"      # 0-20%: High confidence
    LOW = "low"                # 20-40%: Good confidence
    MEDIUM = "medium"          # 40-60%: Some uncertainty
    HIGH = "high"              # 60-80%: Moderate uncertainty
    VERY_HIGH = "very_high"    # 80-100%: High uncertainty


class UncertaintyQuantifier:
    """
    Quantify uncertainty in LLM responses and track calibration.
    
    Uses multiple signals to estimate uncertainty:
    1. Token probability (if available from API)
    2. Response length (very short/long may indicate uncertainty)
    3. Hedging language ("maybe", "possibly", "I think")
    4. Tool call success rate
    5. Historical accuracy for similar queries
    
    Tracks calibration over time:
    - Predicted confidence vs actual accuracy
    - Expected Calibration Error (ECE)
    - Per-domain calibration (code, facts, reasoning)
    """
    
    def __init__(self, state_path: str = "/brain/system/state"):
        """Initialize uncertainty quantifier."""
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        
        self.calibration_file = self.state_path / "response_calibration.json"
        self.history: List[Dict] = []
        self._load_history()
        
        # Hedging phrases that indicate uncertainty
        self.hedging_phrases = [
            "i think", "i believe", "maybe", "possibly", "perhaps",
            "might be", "could be", "seems like", "appears to",
            "not sure", "uncertain", "unclear", "ambiguous",
            "probably", "likely", "may", "might"
        ]
    
    def quantify_uncertainty(
        self,
        response_text: str,
        token_logprobs: Optional[List[float]] = None,
        tool_calls_made: int = 0,
        tool_calls_succeeded: int = 0,
        response_time_ms: Optional[float] = None,
        domain: str = "general"
    ) -> Dict[str, Any]:
        """
        Calculate uncertainty score for a response.
        
        Args:
            response_text: The response text to score
            token_logprobs: Optional list of log probabilities per token
            tool_calls_made: Number of tool calls made
            tool_calls_succeeded: Number of successful tool calls
            response_time_ms: Response time in milliseconds
            domain: Domain category (code, facts, reasoning, general)
            
        Returns:
            Dict with structure:
            {
                "uncertainty_score": float (0-1, higher = more uncertain),
                "confidence_score": float (0-1, 1 - uncertainty_score),
                "uncertainty_level": UncertaintyLevel,
                "signals": {
                    "token_prob_score": float,
                    "hedging_penalty": float,
                    "tool_success_score": float,
                    "length_score": float
                },
                "reasons": List[str],
                "calibration_advice": str
            }
        """
        signals = {}
        reasons = []
        
        # Signal 1: Token probabilities (if available)
        if token_logprobs:
            avg_logprob = sum(token_logprobs) / len(token_logprobs)
            # Convert log prob to probability (0-1)
            # Higher logprob → lower uncertainty
            token_prob_score = min(1.0, max(0.0, (avg_logprob + 5) / 5))  # Normalize
            signals["token_prob_score"] = token_prob_score
            
            if token_prob_score > 0.8:
                reasons.append("high_token_probability")
            elif token_prob_score < 0.4:
                reasons.append("low_token_probability")
        else:
            signals["token_prob_score"] = None
        
        # Signal 2: Hedging language detection
        text_lower = response_text.lower()
        hedging_count = sum(1 for phrase in self.hedging_phrases if phrase in text_lower)
        hedging_penalty = min(0.5, hedging_count * 0.1)  # Max 50% penalty
        signals["hedging_penalty"] = hedging_penalty
        
        if hedging_count > 3:
            reasons.append(f"high_hedging_language_count_{hedging_count}")
        elif hedging_count > 0:
            reasons.append(f"some_hedging_language_count_{hedging_count}")
        
        # Signal 3: Tool call success rate
        if tool_calls_made > 0:
            tool_success_rate = tool_calls_succeeded / tool_calls_made
            signals["tool_success_score"] = tool_success_rate
            
            if tool_success_rate == 1.0:
                reasons.append("all_tools_succeeded")
            elif tool_success_rate < 0.5:
                reasons.append(f"low_tool_success_rate_{tool_success_rate:.0%}")
        else:
            signals["tool_success_score"] = None
        
        # Signal 4: Response length (very short or very long may indicate uncertainty)
        response_length = len(response_text.split())
        if response_length < 10:
            length_score = 0.5  # Very short responses may lack detail
            reasons.append("very_short_response")
        elif response_length > 500:
            length_score = 0.7  # Very long responses may overexplain due to uncertainty
            reasons.append("very_long_response")
        else:
            length_score = 1.0  # Normal length
        signals["length_score"] = length_score
        
        # Combine signals into uncertainty score
        confidence_score = self._combine_signals(signals)
        uncertainty_score = 1.0 - confidence_score
        uncertainty_level = self._score_to_level(uncertainty_score)
        
        # Get calibration advice
        calibration_advice = self._get_calibration_advice(confidence_score, domain)
        
        result = {
            "uncertainty_score": uncertainty_score,
            "confidence_score": confidence_score,
            "uncertainty_level": uncertainty_level,
            "signals": signals,
            "reasons": reasons,
            "calibration_advice": calibration_advice,
            "domain": domain,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(
            "Uncertainty quantified (uncertainty=%s, confidence=%s, level=%s, domain=%s, hedging_count=%s)",
            uncertainty_score,
            confidence_score,
            uncertainty_level.value,
            domain,
            hedging_count,
        )
        
        return result
    
    def _combine_signals(self, signals: Dict[str, Optional[float]]) -> float:
        """
        Combine multiple signals into final confidence score.
        
        Weighting strategy:
        - Token probability: 40% (if available)
        - Tool success: 30% (if available)
        - Hedging penalty: -20%
        - Length score: 10%
        
        Args:
            signals: Dict of signal scores
            
        Returns:
            Combined confidence score (0-1)
        """
        score = 0.5  # Start at neutral
        weight_total = 0.0
        
        # Token probability (40% weight)
        if signals.get("token_prob_score") is not None:
            score += signals["token_prob_score"] * 0.4
            weight_total += 0.4
        
        # Tool success (30% weight)
        if signals.get("tool_success_score") is not None:
            score += signals["tool_success_score"] * 0.3
            weight_total += 0.3
        
        # Length score (10% weight)
        if signals.get("length_score") is not None:
            score += signals["length_score"] * 0.1
            weight_total += 0.1
        
        # Normalize by actual weights used
        if weight_total > 0:
            score = score / (0.5 + weight_total) * 0.8  # Scale to 0.8 max before penalties
        
        # Apply hedging penalty
        hedging_penalty = signals.get("hedging_penalty", 0)
        score = max(0.0, score - hedging_penalty)
        
        return min(1.0, score)
    
    def _score_to_level(self, uncertainty_score: float) -> UncertaintyLevel:
        """Convert numeric uncertainty score to level."""
        if uncertainty_score >= 0.8:
            return UncertaintyLevel.VERY_HIGH
        elif uncertainty_score >= 0.6:
            return UncertaintyLevel.HIGH
        elif uncertainty_score >= 0.4:
            return UncertaintyLevel.MEDIUM
        elif uncertainty_score >= 0.2:
            return UncertaintyLevel.LOW
        else:
            return UncertaintyLevel.VERY_LOW
    
    def _get_calibration_advice(self, confidence_score: float, domain: str) -> str:
        """
        Get advice on how to interpret this confidence score.
        
        Args:
            confidence_score: Predicted confidence (0-1)
            domain: Domain category
            
        Returns:
            Human-readable advice string
        """
        # Get historical calibration for this domain
        calibration_error = self.get_calibration_error(domain)
        
        if calibration_error is None:
            return "insufficient_data_for_calibration"
        
        if calibration_error > 0.15:
            # Model is miscalibrated
            if calibration_error > 0:
                return f"model_overconfident_domain_{domain}_error_{calibration_error:.2f}"
            else:
                return f"model_underconfident_domain_{domain}_error_{abs(calibration_error):.2f}"
        else:
            return f"well_calibrated_domain_{domain}_error_{calibration_error:.2f}"
    
    def record_outcome(
        self,
        confidence_score: float,
        was_correct: bool,
        domain: str = "general",
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Record the outcome of a prediction for calibration tracking.
        
        Args:
            confidence_score: The predicted confidence (0-1)
            was_correct: Whether the prediction was correct
            domain: Domain category
            metadata: Optional metadata to store
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "confidence_score": confidence_score,
            "was_correct": was_correct,
            "domain": domain,
            "metadata": metadata or {}
        }
        
        self.history.append(entry)
        
        # Limit history size (keep last 10,000 entries)
        if len(self.history) > 10000:
            self.history = self.history[-10000:]
        
        self._save_history()
        
        logger.info(
            "Outcome recorded (confidence=%s, correct=%s, domain=%s)",
            confidence_score,
            was_correct,
            domain,
        )
    
    def get_calibration_error(self, domain: Optional[str] = None) -> Optional[float]:
        """
        Calculate Expected Calibration Error (ECE).
        
        ECE measures the difference between predicted confidence and actual accuracy.
        Lower is better. Target: < 0.15 (15%)
        
        Args:
            domain: Optional domain to filter by (None = all domains)
            
        Returns:
            Calibration error (0-1) or None if insufficient data
        """
        # Filter history by domain
        if domain:
            relevant = [h for h in self.history if h["domain"] == domain]
        else:
            relevant = self.history
        
        if len(relevant) < 20:
            return None  # Insufficient data
        
        # Bin predictions by confidence (10 bins: 0-0.1, 0.1-0.2, ..., 0.9-1.0)
        bins = {i: {"predictions": [], "correct": []} for i in range(10)}
        
        for entry in relevant:
            confidence = entry["confidence_score"]
            bin_idx = min(9, int(confidence * 10))
            bins[bin_idx]["predictions"].append(confidence)
            bins[bin_idx]["correct"].append(1 if entry["was_correct"] else 0)
        
        # Calculate ECE
        total_samples = len(relevant)
        ece = 0.0
        
        for bin_idx, data in bins.items():
            if not data["predictions"]:
                continue
            
            n_samples = len(data["predictions"])
            avg_confidence = sum(data["predictions"]) / n_samples
            avg_accuracy = sum(data["correct"]) / n_samples
            
            # Weighted difference
            ece += (n_samples / total_samples) * abs(avg_confidence - avg_accuracy)
        
        return ece
    
    def get_calibration_report(self) -> Dict[str, Any]:
        """
        Get comprehensive calibration report.
        
        Returns:
            Dict with structure:
            {
                "overall_ece": float,
                "per_domain_ece": {domain: float},
                "total_samples": int,
                "domains": List[str],
                "recent_accuracy": float (last 100 samples),
                "calibration_quality": str
            }
        """
        overall_ece = self.get_calibration_error()
        
        # Get per-domain ECE
        domains = set(h["domain"] for h in self.history)
        per_domain_ece = {}
        for domain in domains:
            ece = self.get_calibration_error(domain)
            if ece is not None:
                per_domain_ece[domain] = ece
        
        # Recent accuracy (last 100 samples)
        recent = self.history[-100:] if len(self.history) >= 100 else self.history
        recent_accuracy = sum(1 for h in recent if h["was_correct"]) / len(recent) if recent else 0
        
        # Calibration quality assessment
        if overall_ece is None:
            quality = "insufficient_data"
        elif overall_ece < 0.05:
            quality = "excellent"
        elif overall_ece < 0.10:
            quality = "good"
        elif overall_ece < 0.15:
            quality = "acceptable"
        else:
            quality = "poor_needs_improvement"
        
        return {
            "overall_ece": overall_ece,
            "per_domain_ece": per_domain_ece,
            "total_samples": len(self.history),
            "domains": list(domains),
            "recent_accuracy": recent_accuracy,
            "calibration_quality": quality,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _load_history(self) -> None:
        """Load calibration history from disk."""
        if self.calibration_file.exists():
            try:
                with open(self.calibration_file, 'r') as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                logger.info("Calibration history loaded (samples=%s)", len(self.history))
            except Exception as e:
                logger.error("Failed to load calibration history: %s", e)
                self.history = []
        else:
            self.history = []
    
    def _save_history(self) -> None:
        """Save calibration history to disk."""
        try:
            data = {
                "history": self.history,
                "last_updated": datetime.utcnow().isoformat()
            }
            with open(self.calibration_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save calibration history: %s", e)


# Singleton instance
_uncertainty_quantifier: Optional[UncertaintyQuantifier] = None


def get_uncertainty_quantifier() -> UncertaintyQuantifier:
    """Get singleton uncertainty quantifier instance."""
    global _uncertainty_quantifier
    if _uncertainty_quantifier is None:
        _uncertainty_quantifier = UncertaintyQuantifier()
    return _uncertainty_quantifier
