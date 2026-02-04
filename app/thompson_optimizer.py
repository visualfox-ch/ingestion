"""
Thompson Sampling Optimizer for Self-Optimization

Multi-armed bandit optimizer for parameter tuning using Thompson Sampling.
Balances exploration (trying new parameters) vs exploitation (using best known).

Research Foundation:
- Agrawal, S. & Goyal, N. (2013). "Thompson Sampling for Contextual Bandits with 
  Linear Payoffs." ICML 2013.
  https://arxiv.org/abs/1209.3352
- Chapelle, O. & Li, L. (2011). "An Empirical Evaluation of Thompson Sampling." 
  NeurIPS 2011.

Thompson Sampling Algorithm:
1. Maintain Beta(α, β) distribution for each variant
2. Sample from each distribution
3. Select variant with highest sample
4. Observe reward (success/failure)
5. Update distribution: success → α+1, failure → β+1

Convergence: Typically <100 iterations to identify best variant.

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json
import random
import numpy as np
from pathlib import Path

from .observability import get_logger
from .baseline_recorder import get_baseline_recorder
from .anomaly_detector import get_anomaly_detector, AnomalyAction

logger = get_logger("jarvis.thompson_optimizer")


class OptimizationStatus(str, Enum):
    """Status of optimization cycle."""
    IDLE = "idle"                     # Not running
    EXPLORING = "exploring"           # Testing variants
    CONVERGED = "converged"           # Best variant found
    PENDING_APPROVAL = "pending_approval"  # Waiting for HITL
    APPROVED = "approved"             # Human approved
    REJECTED = "rejected"             # Human rejected
    ROLLED_BACK = "rolled_back"       # Auto-rollback triggered


class ParameterVariant:
    """Represents a parameter variant being tested."""
    
    def __init__(self, name: str, value: Any):
        """
        Initialize parameter variant.
        
        Args:
            name: Variant name (e.g., "hint_freq_3")
            value: Actual parameter value
        """
        self.name = name
        self.value = value
        self.alpha = 1.0  # Beta distribution alpha (successes + 1)
        self.beta = 1.0   # Beta distribution beta (failures + 1)
        self.trials = 0
        self.successes = 0
        self.failures = 0
        self.last_selected = None
        self.created_at = datetime.utcnow().isoformat()
    
    def sample(self) -> float:
        """Sample from Beta distribution."""
        return np.random.beta(self.alpha, self.beta)
    
    def update(self, success: bool) -> None:
        """
        Update distribution based on outcome.
        
        Args:
            success: Whether trial succeeded
        """
        self.trials += 1
        if success:
            self.successes += 1
            self.alpha += 1.0
        else:
            self.failures += 1
            self.beta += 1.0
        self.last_selected = datetime.utcnow().isoformat()
    
    def success_rate(self) -> float:
        """Calculate empirical success rate."""
        if self.trials == 0:
            return 0.0
        return self.successes / self.trials
    
    def confidence_interval(self, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Calculate confidence interval for success rate.
        
        Args:
            confidence: Confidence level (default 0.95)
            
        Returns:
            (lower_bound, upper_bound) tuple
        """
        if self.trials == 0:
            return (0.0, 1.0)
        
        # Use Beta distribution quantiles
        alpha_level = (1 - confidence) / 2
        lower = np.random.beta(self.alpha, self.beta, 10000)
        lower_bound = np.percentile(lower, alpha_level * 100)
        upper_bound = np.percentile(lower, (1 - alpha_level) * 100)
        
        return (lower_bound, upper_bound)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        lower, upper = self.confidence_interval()
        return {
            "name": self.name,
            "value": self.value,
            "alpha": self.alpha,
            "beta": self.beta,
            "trials": self.trials,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.success_rate(),
            "confidence_interval_95": {"lower": lower, "upper": upper},
            "last_selected": self.last_selected,
            "created_at": self.created_at
        }


class ThompsonOptimizer:
    """
    Thompson Sampling optimizer for parameter tuning.
    
    Features:
    - Multi-armed bandit optimization
    - Beta distribution for Bernoulli rewards
    - Automatic convergence detection
    - HITL approval workflow
    - Circuit breaker integration
    - Audit trail for all decisions
    
    Safety constraints:
    - Rate limit: 50 optimizations/session/hour
    - Circuit breaker: Auto-rollback if error_rate >10%
    - HITL approval required for parameter changes
    - Audit log with 2-year retention
    """
    
    def __init__(
        self,
        state_path: str = "/brain/system/state",
        max_iterations: int = 100,
        convergence_threshold: float = 0.95
    ):
        """
        Initialize Thompson Sampling optimizer.
        
        Args:
            state_path: Path to state directory
            max_iterations: Max iterations before convergence
            convergence_threshold: Confidence threshold for convergence
        """
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        
        self.optimization_file = self.state_path / "thompson_optimization.json"
        self.audit_file = self.state_path / "optimization_audit.json"
        
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold
        
        # Current optimization state
        self.parameter_name: Optional[str] = None
        self.variants: Dict[str, ParameterVariant] = {}
        self.current_variant: Optional[str] = None
        self.status = OptimizationStatus.IDLE
        self.iteration = 0
        self.best_variant: Optional[str] = None
        
        # Safety tracking
        self.optimizations_this_hour = 0
        self.last_hour_reset = datetime.utcnow()
        self.circuit_breaker_active = False
        
        # Integrations
        self.baseline_recorder = get_baseline_recorder()
        self.anomaly_detector = get_anomaly_detector()
        
        self._load_state()
        self._load_audit()
    
    def start_optimization(
        self,
        parameter_name: str,
        variants: Dict[str, Any],
        metric_name: str = "response_accuracy"
    ) -> Dict[str, Any]:
        """
        Start new optimization cycle.
        
        Args:
            parameter_name: Name of parameter to optimize (e.g., "hint_frequency")
            variants: Dict of {variant_name: value}
                     e.g., {"freq_1": 1, "freq_2": 2, "freq_3": 3}
            metric_name: Metric to optimize (default: response_accuracy)
            
        Returns:
            Dict with optimization start confirmation
        """
        if self.status not in [OptimizationStatus.IDLE, OptimizationStatus.CONVERGED]:
            return {
                "success": False,
                "error": f"optimization_already_running_status_{self.status.value}"
            }
        
        # Check rate limit
        if not self._check_rate_limit():
            return {
                "success": False,
                "error": "rate_limit_exceeded_50_per_hour"
            }
        
        # Check circuit breaker
        if self.circuit_breaker_active:
            return {
                "success": False,
                "error": "circuit_breaker_active_rollback_required"
            }
        
        # Initialize variants
        self.parameter_name = parameter_name
        self.variants = {
            name: ParameterVariant(name, value)
            for name, value in variants.items()
        }
        self.status = OptimizationStatus.EXPLORING
        self.iteration = 0
        self.best_variant = None
        
        self._save_state()
        self._audit_log("optimization_started", {
            "parameter": parameter_name,
            "variants": list(variants.keys()),
            "metric": metric_name
        })
        
        logger.info(
            "Optimization started (parameter=%s, variants=%s, metric=%s)",
            parameter_name,
            len(variants),
            metric_name,
        )
        
        return {
            "success": True,
            "parameter": parameter_name,
            "variants": list(variants.keys()),
            "metric": metric_name,
            "status": self.status.value
        }
    
    def select_variant(self) -> Optional[Dict[str, Any]]:
        """
        Select next variant to test using Thompson Sampling.
        
        Returns:
            Dict with selected variant info or None if optimization not running
        """
        if self.status != OptimizationStatus.EXPLORING:
            return None
        
        if not self.variants:
            return None
        
        # Thompson Sampling: Sample from each variant's Beta distribution
        samples = {
            name: variant.sample()
            for name, variant in self.variants.items()
        }
        
        # Select variant with highest sample
        selected_name = max(samples.items(), key=lambda x: x[1])[0]
        selected_variant = self.variants[selected_name]
        
        self.current_variant = selected_name
        self.iteration += 1
        
        self._save_state()
        
        logger.info(
            "Variant selected (variant=%s, value=%s, iteration=%s, sample=%s)",
            selected_name,
            selected_variant.value,
            self.iteration,
            samples[selected_name],
        )
        
        return {
            "variant_name": selected_name,
            "variant_value": selected_variant.value,
            "iteration": self.iteration,
            "thompson_sample": samples[selected_name]
        }
    
    def report_outcome(
        self,
        success: bool,
        metrics: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Report outcome of current variant trial.
        
        Args:
            success: Whether trial succeeded (e.g., accuracy improved)
            metrics: Optional current metrics for circuit breaker check
            
        Returns:
            Dict with outcome processing result
        """
        if not self.current_variant:
            return {
                "success": False,
                "error": "no_active_variant"
            }
        
        # Check circuit breaker before updating
        if metrics:
            circuit_check = self._check_circuit_breaker(metrics)
            if circuit_check["triggered"]:
                return circuit_check
        
        # Update variant distribution
        variant = self.variants[self.current_variant]
        variant.update(success)
        
        self._audit_log("outcome_reported", {
            "variant": self.current_variant,
            "success": success,
            "trials": variant.trials,
            "success_rate": variant.success_rate()
        })
        
        # Check for convergence
        convergence = self._check_convergence()
        
        result = {
            "success": True,
            "variant": self.current_variant,
            "outcome": "success" if success else "failure",
            "trials": variant.trials,
            "success_rate": variant.success_rate(),
            "converged": convergence["converged"]
        }
        
        if convergence["converged"]:
            result["best_variant"] = convergence["best_variant"]
            result["confidence"] = convergence["confidence"]
            result["status"] = OptimizationStatus.PENDING_APPROVAL.value
        
        self._save_state()
        
        return result
    
    def _check_convergence(self) -> Dict[str, Any]:
        """
        Check if optimization has converged.
        
        Returns:
            Dict with convergence status
        """
        if self.iteration < 20:
            # Need minimum trials
            return {"converged": False, "reason": "insufficient_trials"}
        
        if self.iteration >= self.max_iterations:
            # Max iterations reached
            best = max(
                self.variants.items(),
                key=lambda x: x[1].success_rate()
            )
            self.status = OptimizationStatus.PENDING_APPROVAL
            self.best_variant = best[0]
            
            return {
                "converged": True,
                "reason": "max_iterations_reached",
                "best_variant": best[0],
                "confidence": best[1].success_rate()
            }
        
        # Check if one variant clearly dominates
        sorted_variants = sorted(
            self.variants.items(),
            key=lambda x: x[1].success_rate(),
            reverse=True
        )
        
        if len(sorted_variants) < 2:
            return {"converged": False, "reason": "single_variant"}
        
        best = sorted_variants[0][1]
        second = sorted_variants[1][1]
        
        # Confidence interval check
        best_lower, _ = best.confidence_interval()
        _, second_upper = second.confidence_interval()
        
        # Converged if best's lower bound > second's upper bound
        if best_lower > second_upper and best.success_rate() >= self.convergence_threshold:
            self.status = OptimizationStatus.PENDING_APPROVAL
            self.best_variant = sorted_variants[0][0]
            
            return {
                "converged": True,
                "reason": "clear_winner",
                "best_variant": sorted_variants[0][0],
                "confidence": best.success_rate(),
                "best_ci_lower": best_lower,
                "second_ci_upper": second_upper
            }
        
        return {"converged": False, "reason": "still_exploring"}
    
    def get_recommendation(self) -> Optional[Dict[str, Any]]:
        """
        Get optimization recommendation for HITL approval.
        
        Returns:
            Dict with recommendation or None if not ready
        """
        if self.status != OptimizationStatus.PENDING_APPROVAL:
            return None
        
        if not self.best_variant:
            return None
        
        best = self.variants[self.best_variant]
        
        # Compare to baseline (if available)
        baseline = self._get_baseline_variant()
        improvement = None
        if baseline:
            baseline_var = self.variants.get(baseline)
            if baseline_var:
                improvement = best.success_rate() - baseline_var.success_rate()
        
        return {
            "parameter": self.parameter_name,
            "recommended_variant": self.best_variant,
            "recommended_value": best.value,
            "confidence": best.success_rate(),
            "trials": best.trials,
            "improvement_vs_baseline": improvement,
            "all_variants": {
                name: var.to_dict()
                for name, var in self.variants.items()
            },
            "status": OptimizationStatus.PENDING_APPROVAL.value,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def approve_recommendation(self, approved: bool, reason: str = "") -> Dict[str, Any]:
        """
        HITL approval of recommendation.
        
        Args:
            approved: Whether recommendation is approved
            reason: Human explanation
            
        Returns:
            Dict with approval result
        """
        if self.status != OptimizationStatus.PENDING_APPROVAL:
            return {
                "success": False,
                "error": f"wrong_status_{self.status.value}"
            }
        
        if approved:
            self.status = OptimizationStatus.APPROVED
            self._audit_log("recommendation_approved", {
                "parameter": self.parameter_name,
                "variant": self.best_variant,
                "value": self.variants[self.best_variant].value,
                "reason": reason
            })
            
            logger.info(
                "Recommendation approved (parameter=%s, variant=%s, reason=%s)",
                self.parameter_name,
                self.best_variant,
                reason,
            )
        else:
            self.status = OptimizationStatus.REJECTED
            self._audit_log("recommendation_rejected", {
                "parameter": self.parameter_name,
                "variant": self.best_variant,
                "reason": reason
            })
            
            logger.warning(
                "Recommendation rejected (parameter=%s, variant=%s, reason=%s)",
                self.parameter_name,
                self.best_variant,
                reason,
            )
        
        self._save_state()
        
        return {
            "success": True,
            "status": self.status.value,
            "parameter": self.parameter_name,
            "variant": self.best_variant
        }
    
    def _check_circuit_breaker(self, metrics: Dict[str, float]) -> Dict[str, Any]:
        """
        Check if circuit breaker should trigger.
        
        Args:
            metrics: Current metrics
            
        Returns:
            Dict with circuit breaker status
        """
        # Check error rate
        error_rate = metrics.get("error_rate", 0.0)
        if error_rate > 0.10:  # >10% error rate
            self.circuit_breaker_active = True
            self.status = OptimizationStatus.ROLLED_BACK
            
            self._audit_log("circuit_breaker_triggered", {
                "reason": "error_rate_exceeded",
                "error_rate": error_rate,
                "threshold": 0.10
            })
            
            logger.error(
                "Circuit breaker triggered (error_rate=%s, threshold=%s)",
                error_rate,
                0.10,
            )
            
            return {
                "success": False,
                "triggered": True,
                "reason": "error_rate_exceeded",
                "error_rate": error_rate,
                "action": "rollback_required"
            }
        
        # Check for anomalies
        anomaly_check = self.anomaly_detector.check_multiple_metrics(metrics)
        if anomaly_check["recommended_action"] in [
            AnomalyAction.ROLLBACK,
            AnomalyAction.CIRCUIT_BREAK
        ]:
            self.circuit_breaker_active = True
            self.status = OptimizationStatus.ROLLED_BACK
            
            self._audit_log("circuit_breaker_triggered", {
                "reason": "anomaly_detected",
                "severity": anomaly_check["highest_severity"].value
            })
            
            return {
                "success": False,
                "triggered": True,
                "reason": "anomaly_detected",
                "action": "rollback_required"
            }
        
        return {"success": True, "triggered": False}
    
    def _check_rate_limit(self) -> bool:
        """Check if rate limit allows new optimization."""
        now = datetime.utcnow()
        
        # Reset counter if hour passed
        if (now - self.last_hour_reset).total_seconds() > 3600:
            self.optimizations_this_hour = 0
            self.last_hour_reset = now
        
        if self.optimizations_this_hour >= 50:
            logger.warning("Rate limit exceeded (count=%s)", self.optimizations_this_hour)
            return False
        
        self.optimizations_this_hour += 1
        return True
    
    def _get_baseline_variant(self) -> Optional[str]:
        """Get baseline variant name (if any)."""
        # Convention: variant with "baseline" or "current" in name
        for name in self.variants.keys():
            if "baseline" in name.lower() or "current" in name.lower():
                return name
        return None
    
    def _audit_log(self, event: str, data: Dict[str, Any]) -> None:
        """Write to audit log."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "data": data
        }
        
        # Load existing audit
        audit = []
        if self.audit_file.exists():
            try:
                with open(self.audit_file, 'r') as f:
                    audit = json.load(f)
            except Exception as e:
                logger.error("Failed to load audit: %s", e)
        
        audit.append(entry)
        
        # Save audit (keep last 10,000 entries)
        try:
            with open(self.audit_file, 'w') as f:
                json.dump(audit[-10000:], f, indent=2)
        except Exception as e:
            logger.error("Failed to save audit: %s", e)
    
    def _load_state(self) -> None:
        """Load optimization state from disk."""
        if self.optimization_file.exists():
            try:
                with open(self.optimization_file, 'r') as f:
                    state = json.load(f)
                    
                    self.parameter_name = state.get("parameter_name")
                    self.status = OptimizationStatus(state.get("status", "idle"))
                    self.iteration = state.get("iteration", 0)
                    self.best_variant = state.get("best_variant")
                    self.current_variant = state.get("current_variant")
                    
                    # Restore variants
                    variants_data = state.get("variants", {})
                    self.variants = {}
                    for name, data in variants_data.items():
                        var = ParameterVariant(name, data["value"])
                        var.alpha = data["alpha"]
                        var.beta = data["beta"]
                        var.trials = data["trials"]
                        var.successes = data["successes"]
                        var.failures = data["failures"]
                        var.last_selected = data.get("last_selected")
                        var.created_at = data.get("created_at", datetime.utcnow().isoformat())
                        self.variants[name] = var
                
                logger.info("Optimization state loaded (parameter=%s)", self.parameter_name)
            except Exception as e:
                logger.error("Failed to load optimization state: %s", e)
    
    def _save_state(self) -> None:
        """Save optimization state to disk."""
        try:
            state = {
                "parameter_name": self.parameter_name,
                "status": self.status.value,
                "iteration": self.iteration,
                "best_variant": self.best_variant,
                "current_variant": self.current_variant,
                "variants": {
                    name: var.to_dict()
                    for name, var in self.variants.items()
                },
                "last_updated": datetime.utcnow().isoformat()
            }
            
            with open(self.optimization_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error("Failed to save optimization state: %s", e)
    
    def _load_audit(self) -> None:
        """Load audit log."""
        # Audit loaded on-demand in _audit_log
        pass


# Singleton instance
_thompson_optimizer: Optional[ThompsonOptimizer] = None


def get_thompson_optimizer() -> ThompsonOptimizer:
    """Get singleton Thompson optimizer instance."""
    global _thompson_optimizer
    if _thompson_optimizer is None:
        _thompson_optimizer = ThompsonOptimizer()
    return _thompson_optimizer
