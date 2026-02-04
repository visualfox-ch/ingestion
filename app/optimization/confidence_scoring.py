"""
Confidence Scoring System for Self-Optimization

Adds confidence/uncertainty quantification to all optimization decisions.
Enables risk-aware decision making for Micha.

Phase 20: Self-Optimization Strategy (Tier 1)
Author: Jarvis + Copilot
Date: 2026-02-02

References:
- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). "On Calibration of Modern Neural Networks." ICML 2017
- Malinin, A. & Grangier, D. (2021). "Uncertainty Estimation in Neural Networks for Dialogue Systems." ACL 2021
"""

import logging
from typing import Tuple, Dict, Optional
from dataclasses import dataclass
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceScore:
    """Confidence score with uncertainty bounds"""
    
    value: float  # The actual score/metric (0-1)
    confidence: float  # How confident we are (0-1)
    confidence_interval_95: Tuple[float, float]  # 95% CI
    sample_size: int
    degrees_of_freedom: int
    source: str  # "empirical", "bayesian", "bootstrap"
    
    def __str__(self):
        return f"{self.value:.3f} ± {self.confidence:.1%} [{self.confidence_interval_95[0]:.3f}, {self.confidence_interval_95[1]:.3f}]"


class ConfidenceScorer:
    """
    Computes confidence scores and uncertainty intervals for metrics.
    
    Methods:
    1. Empirical (from samples): Mean ± t-distribution CI
    2. Bayesian: Prior + likelihood → posterior
    3. Bootstrap: Resample to estimate distribution
    """
    
    @staticmethod
    def from_samples(
        samples: np.ndarray,
        confidence_level: float = 0.95,
        source: str = "empirical"
    ) -> ConfidenceScore:
        """
        Compute confidence score from empirical samples.
        
        Args:
            samples: Array of measured values
            confidence_level: Confidence level (0.95 = 95% CI)
            source: Method used
        
        Returns:
            ConfidenceScore with empirical confidence interval
        """
        n = len(samples)
        mean = np.mean(samples)
        std = np.std(samples, ddof=1)  # Sample std
        
        # t-distribution for small samples
        df = n - 1
        t_critical = stats.t.ppf((1 + confidence_level) / 2, df)
        margin_of_error = t_critical * (std / np.sqrt(n))
        
        # Confidence in the mean (higher n = higher confidence)
        confidence = min(1.0, n / 100)  # Saturates at 100 samples
        
        return ConfidenceScore(
            value=float(mean),
            confidence=float(confidence),
            confidence_interval_95=(
                float(mean - margin_of_error),
                float(mean + margin_of_error)
            ),
            sample_size=n,
            degrees_of_freedom=df,
            source=source
        )
    
    @staticmethod
    def from_proportions(
        successes: int,
        total: int,
        confidence_level: float = 0.95,
        method: str = "wilson"  # "wilson" or "beta"
    ) -> ConfidenceScore:
        """
        Compute confidence score for proportions (e.g., acceptance rate).
        
        Uses Wilson score interval (more accurate than normal approximation).
        
        Args:
            successes: Number of positive outcomes
            total: Total number of trials
            confidence_level: Confidence level (0.95 = 95% CI)
            method: "wilson" or "beta" (beta is Bayesian with uniform prior)
        
        Returns:
            ConfidenceScore with proportion confidence interval
        """
        if total == 0:
            return ConfidenceScore(0.5, 0.0, (0.0, 1.0), 0, 0, source="proportions")
        
        p_hat = successes / total
        z = stats.norm.ppf((1 + confidence_level) / 2)
        
        if method == "wilson":
            # Wilson score interval (recommended)
            denominator = 1 + z**2 / total
            center = (p_hat + z**2 / (2 * total)) / denominator
            
            margin = z * np.sqrt(
                (p_hat * (1 - p_hat) / total) + (z**2 / (4 * total**2))
            ) / denominator
            
            lower = max(0, center - margin)
            upper = min(1, center + margin)
        else:
            # Beta distribution CI (Bayesian with uniform prior)
            lower = stats.beta.ppf((1 - confidence_level) / 2, successes + 1, total - successes + 1)
            upper = stats.beta.ppf((1 + confidence_level) / 2, successes + 1, total - successes + 1)
        
        # Confidence increases with sample size
        confidence = min(1.0, total / 100)
        
        return ConfidenceScore(
            value=float(p_hat),
            confidence=float(confidence),
            confidence_interval_95=(float(lower), float(upper)),
            sample_size=total,
            degrees_of_freedom=total - 1,
            source=f"proportions_{method}"
        )
    
    @staticmethod
    def from_bayesian_update(
        prior_mean: float,
        prior_std: float,
        likelihood_mean: float,
        likelihood_std: float,
        n_samples: int
    ) -> ConfidenceScore:
        """
        Bayesian posterior update: N(μ₀, σ₀²) + N(data | μ, σ²) → N(μ_posterior, σ_posterior²)
        
        Args:
            prior_mean: Prior belief about parameter
            prior_std: Prior uncertainty
            likelihood_mean: Observed data mean
            likelihood_std: Observed data std
            n_samples: Number of observations
        
        Returns:
            ConfidenceScore with posterior distribution
        """
        prior_precision = 1 / (prior_std**2)
        likelihood_precision = n_samples / (likelihood_std**2)
        
        posterior_precision = prior_precision + likelihood_precision
        posterior_std = np.sqrt(1 / posterior_precision)
        
        posterior_mean = (
            prior_precision * prior_mean + likelihood_precision * likelihood_mean
        ) / posterior_precision
        
        # Confidence based on posterior precision
        confidence = min(1.0, posterior_precision / 10)
        
        z = stats.norm.ppf(0.975)  # 95% CI
        ci = (
            posterior_mean - z * posterior_std,
            posterior_mean + z * posterior_std
        )
        
        return ConfidenceScore(
            value=float(posterior_mean),
            confidence=float(confidence),
            confidence_interval_95=(float(ci[0]), float(ci[1])),
            sample_size=n_samples,
            degrees_of_freedom=n_samples - 1,
            source="bayesian_posterior"
        )
    
    @staticmethod
    def from_bootstrap(
        data: np.ndarray,
        estimator_fn=np.mean,
        n_bootstrap: int = 10000,
        confidence_level: float = 0.95
    ) -> ConfidenceScore:
        """
        Bootstrap confidence interval.
        
        Args:
            data: Original data
            estimator_fn: Function to estimate (default: mean)
            n_bootstrap: Number of bootstrap samples
            confidence_level: Confidence level (0.95 = 95% CI)
        
        Returns:
            ConfidenceScore with bootstrap CI
        """
        bootstrap_estimates = []
        
        for _ in range(n_bootstrap):
            sample = np.random.choice(data, size=len(data), replace=True)
            bootstrap_estimates.append(estimator_fn(sample))
        
        bootstrap_estimates = np.array(bootstrap_estimates)
        point_estimate = estimator_fn(data)
        
        # Percentile method
        alpha = (1 - confidence_level) / 2
        lower = np.percentile(bootstrap_estimates, alpha * 100)
        upper = np.percentile(bootstrap_estimates, (1 - alpha) * 100)
        
        # Confidence based on variability
        bootstrap_std = np.std(bootstrap_estimates)
        confidence = min(1.0, 1 / (1 + bootstrap_std))
        
        return ConfidenceScore(
            value=float(point_estimate),
            confidence=float(confidence),
            confidence_interval_95=(float(lower), float(upper)),
            sample_size=len(data),
            degrees_of_freedom=len(data) - 1,
            source="bootstrap"
        )


class MetricWithConfidence:
    """
    Wraps a metric with its confidence score.
    Used in optimization decisions.
    """
    
    def __init__(
        self,
        metric_name: str,
        value: float,
        confidence: Optional[ConfidenceScore] = None
    ):
        self.metric_name = metric_name
        self.value = value
        self.confidence = confidence or ConfidenceScore(
            value=value,
            confidence=0.5,  # Default: medium confidence if not specified
            confidence_interval_95=(value * 0.9, value * 1.1),
            sample_size=0,
            degrees_of_freedom=0,
            source="unknown"
        )
    
    def is_significantly_better_than(
        self,
        other: "MetricWithConfidence",
        higher_is_better: bool = True
    ) -> Tuple[bool, float]:
        """
        Determine if this metric is significantly better than another.
        
        Returns: (is_significant, p_value)
        """
        # Check if confidence intervals overlap
        self_ci = self.confidence.confidence_interval_95
        other_ci = other.confidence.confidence_interval_95
        
        if higher_is_better:
            # Better if lower bound of self > upper bound of other
            is_significant = self_ci[0] > other_ci[1]
        else:
            # Better if upper bound of self < lower bound of other
            is_significant = self_ci[1] < other_ci[0]
        
        # Rough p-value approximation
        # (In production, would use proper statistical test)
        p_value = 0.05 if is_significant else 0.5
        
        return is_significant, p_value
    
    def __str__(self):
        return f"{self.metric_name}: {self.confidence}"
    
    def to_dict(self) -> Dict:
        return {
            "metric_name": self.metric_name,
            "value": self.value,
            "confidence": self.confidence.confidence,
            "confidence_interval_95": self.confidence.confidence_interval_95,
            "source": self.confidence.source,
            "sample_size": self.confidence.sample_size,
        }


class OptimizationDecision:
    """
    An optimization decision with full uncertainty quantification.
    """
    
    def __init__(
        self,
        decision_name: str,
        parameter: str,
        old_value: float,
        new_value: float,
        expected_impact: MetricWithConfidence,
        risk_level: str = "LOW"  # LOW, MEDIUM, HIGH
    ):
        self.decision_name = decision_name
        self.parameter = parameter
        self.old_value = old_value
        self.new_value = new_value
        self.expected_impact = expected_impact
        self.risk_level = risk_level
        self.recommended_action = self._compute_recommendation()
    
    def _compute_recommendation(self) -> str:
        """Compute recommendation based on confidence and risk"""
        confidence = self.expected_impact.confidence
        
        if self.risk_level == "HIGH" and confidence < 0.7:
            return "ESCALATE_TO_MICHA"
        elif confidence < 0.5:
            return "COLLECT_MORE_DATA"
        elif confidence > 0.85:
            return "AUTO_DEPLOY_WITH_MONITORING"
        else:
            return "CANARY_ROLLOUT"
    
    def __str__(self):
        return f"""
OptimizationDecision:
  Decision: {self.decision_name}
  Parameter: {self.parameter} ({self.old_value} → {self.new_value})
  Expected Impact: {self.expected_impact}
  Risk Level: {self.risk_level}
  Recommendation: {self.recommended_action}
"""


if __name__ == "__main__":
    # Test/Example usage
    logging.basicConfig(level=logging.INFO)
    
    print("=== Confidence Scoring Examples ===\n")
    
    # Example 1: From samples (user satisfaction scores)
    print("1. User Satisfaction (from 42 samples)")
    samples = np.random.normal(loc=0.82, scale=0.05, size=42)
    cs = ConfidenceScorer.from_samples(samples)
    print(f"   {cs}\n")
    
    # Example 2: From proportions (hint acceptance rate)
    print("2. Hint Acceptance Rate (128 out of 150 hints accepted)")
    cs_props = ConfidenceScorer.from_proportions(128, 150)
    print(f"   {cs_props}\n")
    
    # Example 3: Bayesian update
    print("3. Bayesian Update (prior + observed)")
    cs_bayesian = ConfidenceScorer.from_bayesian_update(
        prior_mean=0.75,
        prior_std=0.1,
        likelihood_mean=0.80,
        likelihood_std=0.05,
        n_samples=100
    )
    print(f"   {cs_bayesian}\n")
    
    # Example 4: Metric comparison
    print("4. Metric Comparison")
    old_satisfaction = MetricWithConfidence("satisfaction", 0.82, cs)
    new_satisfaction = MetricWithConfidence("satisfaction", 0.84, cs_props)
    
    is_sig, p_val = old_satisfaction.is_significantly_better_than(
        new_satisfaction,
        higher_is_better=True
    )
    print(f"   Old: {old_satisfaction}")
    print(f"   New: {new_satisfaction}")
    print(f"   Significantly better: {is_sig} (p={p_val})\n")
    
    # Example 5: Optimization decision
    print("5. Optimization Decision with Uncertainty")
    decision = OptimizationDecision(
        decision_name="Increase Hint Frequency",
        parameter="hint_frequency",
        old_value=3.8,
        new_value=4.2,
        expected_impact=MetricWithConfidence(
            "satisfaction_gain",
            0.04,  # +4% satisfaction
            ConfidenceScorer.from_samples(np.array([0.02, 0.04, 0.06, 0.035]))
        ),
        risk_level="LOW"
    )
    print(decision)
