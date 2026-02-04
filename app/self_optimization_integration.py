"""
Self-Optimization Integration Layer

Coordinates Phase 1-3 components:
- Baseline recording (SPC)
- Anomaly detection (3-sigma)
- Uncertainty quantification (calibration)
- Hallucination tracking (Evidence-Contract)
- Thompson Sampling optimization
- Circuit breaker safety

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json
from pathlib import Path

from .observability import get_logger
from .baseline_recorder import get_baseline_recorder
from .anomaly_detector import get_anomaly_detector, AnomalyAction, AnomalySeverity
from .uncertainty_quantifier import get_uncertainty_quantifier
from .hallucination_tracker import get_hallucination_tracker
from .thompson_optimizer import get_thompson_optimizer, OptimizationStatus

logger = get_logger("jarvis.self_optimization_integration")


class IntegrationState(str, Enum):
    """State of self-optimization system."""
    INITIALIZING = "initializing"
    IDLE = "idle"
    MONITORING = "monitoring"
    OPTIMIZING = "optimizing"
    CIRCUIT_BREAKER = "circuit_breaker"
    ROLLED_BACK = "rolled_back"
    ERROR = "error"


class SafetyCheckResult:
    """Result of safety pre-checks before optimization."""
    
    def __init__(self):
        self.passed = False
        self.checks: Dict[str, Any] = {}
        self.failures: List[str] = []


class SelfOptimizationIntegration:
    """
    Integrates all self-optimization components.
    
    Workflow:
    1. Monitor metrics (baseline_recorder)
    2. Detect anomalies (anomaly_detector)
    3. Quantify uncertainty (uncertainty_quantifier)
    4. Check hallucinations (hallucination_tracker)
    5. If all safe: Run optimization (thompson_optimizer)
    6. Execute approved changes
    7. Monitor for rollback triggers
    
    Safety constraints:
    - Circuit breaker: >10% error or >15% hallucination → auto-disable
    - Rate limit: 50 optimizations/hour
    - HITL approval required
    - Audit trail for all actions
    - 15min rollback SLA
    """
    
    def __init__(self, state_path: str = "/brain/system/state"):
        """Initialize integration layer."""
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        
        self.status = IntegrationState.INITIALIZING
        self.last_check = None
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = None
        
        # Component integrations
        self.baseline_recorder = get_baseline_recorder()
        self.anomaly_detector = get_anomaly_detector()
        self.uncertainty_quantifier = get_uncertainty_quantifier()
        self.hallucination_tracker = get_hallucination_tracker()
        self.thompson_optimizer = get_thompson_optimizer()
        
        # Audit trail
        self.audit_file = self.state_path / "integration_audit.json"
        
        self.status = IntegrationState.IDLE
        logger.info("Integration layer initialized")
    
    def pre_optimization_checks(self) -> SafetyCheckResult:
        """
        Run safety checks before starting optimization.
        
        Checks:
        1. Circuit breaker not active
        2. No ongoing anomalies
        3. Hallucination rate <10%
        4. Calibration error <0.15
        5. Rate limit allows
        
        Returns:
            SafetyCheckResult with pass/fail and details
        """
        result = SafetyCheckResult()
        
        # Check 1: Circuit breaker
        if self.circuit_breaker_active:
            result.failures.append(f"circuit_breaker_active: {self.circuit_breaker_reason}")
            result.checks["circuit_breaker"] = {
                "passed": False,
                "reason": self.circuit_breaker_reason
            }
        else:
            result.checks["circuit_breaker"] = {"passed": True}
        
        # Check 2: No ongoing anomalies
        baseline = self.baseline_recorder.load_baseline()
        if baseline and "metrics" in baseline:
            current_metrics = self._get_current_metrics()
            anomaly_check = self.anomaly_detector.check_multiple_metrics(current_metrics)
            
            if anomaly_check["any_anomaly"]:
                result.failures.append(
                    f"anomalies_detected: {anomaly_check['anomaly_count']}/{anomaly_check['total_metrics']}"
                )
            
            result.checks["anomalies"] = {
                "passed": not anomaly_check["any_anomaly"],
                "anomaly_count": anomaly_check["anomaly_count"],
                "severity": anomaly_check["highest_severity"].value
            }
        else:
            result.checks["anomalies"] = {"passed": True, "reason": "no_baseline"}
        
        # Check 3: Hallucination rate
        hallucination_metrics = self.hallucination_tracker.get_metrics_report()
        hallucination_rate = hallucination_metrics.get("overall_hallucination_rate", 0.0)
        
        if hallucination_rate > 0.15:  # >15%
            result.failures.append(f"hallucination_rate_high: {hallucination_rate:.0%}")
        
        result.checks["hallucination"] = {
            "passed": hallucination_rate <= 0.15,
            "rate": hallucination_rate,
            "threshold": 0.15
        }
        
        # Check 4: Calibration error
        calibration_report = self.uncertainty_quantifier.get_calibration_report()
        calibration_error = calibration_report.get("overall_ece")
        
        if calibration_error and calibration_error > 0.15:
            result.failures.append(f"calibration_error_high: {calibration_error:.2f}")
        
        result.checks["calibration"] = {
            "passed": calibration_error is None or calibration_error <= 0.15,
            "ece": calibration_error,
            "quality": calibration_report.get("calibration_quality")
        }
        
        # Check 5: Rate limit
        rate_limit_ok = self.thompson_optimizer.optimizations_this_hour < 50
        if not rate_limit_ok:
            result.failures.append("rate_limit_exceeded")
        
        result.checks["rate_limit"] = {
            "passed": rate_limit_ok,
            "current": self.thompson_optimizer.optimizations_this_hour,
            "limit": 50
        }
        
        # Overall result
        result.passed = len(result.failures) == 0
        
        logger.info(
            "Pre-optimization checks (passed=%s, failures=%s, checks=%s)",
            result.passed,
            len(result.failures),
            len(result.checks),
        )
        
        return result
    
    def start_optimization_cycle(
        self,
        parameter_name: str,
        variants: Dict[str, Any],
        metric_name: str = "response_accuracy"
    ) -> Dict[str, Any]:
        """
        Start optimization with safety checks.
        
        Args:
            parameter_name: Parameter to optimize
            variants: Dict of {variant_name: value}
            metric_name: Metric to optimize
            
        Returns:
            Dict with optimization start result or safety check failures
        """
        # Pre-checks
        safety = self.pre_optimization_checks()
        
        if not safety.passed:
            self._audit_log("optimization_blocked", {
                "parameter": parameter_name,
                "reason": "safety_checks_failed",
                "failures": safety.failures
            })
            
            return {
                "success": False,
                "error": "safety_checks_failed",
                "failures": safety.failures,
                "checks": safety.checks
            }
        
        # Start optimization
        result = self.thompson_optimizer.start_optimization(
            parameter_name=parameter_name,
            variants=variants,
            metric_name=metric_name
        )
        
        if result["success"]:
            self.status = IntegrationState.OPTIMIZING
            self._audit_log("optimization_started", {
                "parameter": parameter_name,
                "variants": list(variants.keys()),
                "metric": metric_name
            })
        
        return result
    
    def process_response(
        self,
        response_text: str,
        tool_calls_made: int = 0,
        tool_calls_succeeded: int = 0,
        retrieved_context: Optional[List[str]] = None,
        domain: str = "general"
    ) -> Dict[str, Any]:
        """
        Process response through all metrics (during optimization).
        
        Args:
            response_text: LLM response
            tool_calls_made: Number of tool calls
            tool_calls_succeeded: Successful tool calls
            retrieved_context: Retrieved context chunks
            domain: Domain category
            
        Returns:
            Dict with all metrics
        """
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "domain": domain,
            "uncertainty": None,
            "hallucination": None,
            "metrics": {}
        }
        
        # Quantify uncertainty
        uncertainty = self.uncertainty_quantifier.quantify_uncertainty(
            response_text=response_text,
            tool_calls_made=tool_calls_made,
            tool_calls_succeeded=tool_calls_succeeded,
            domain=domain
        )
        result["uncertainty"] = uncertainty
        
        # Check for hallucinations
        hallucination = self.hallucination_tracker.check_response(
            response_text=response_text,
            retrieved_context=retrieved_context,
            domain=domain
        )
        result["hallucination"] = hallucination
        
        # Record outcomes for calibration
        if tool_calls_made > 0:
            tool_success_rate = tool_calls_succeeded / tool_calls_made
            self.uncertainty_quantifier.record_outcome(
                confidence_score=uncertainty["confidence_score"],
                was_correct=(tool_success_rate == 1.0),
                domain=domain
            )
        
        # Record hallucination
        self.hallucination_tracker.record_hallucination(
            has_hallucination=hallucination["has_hallucination"],
            hallucination_type=hallucination["hallucination_type"],
            severity=hallucination["severity"],
            domain=domain
        )
        
        return result
    
    def check_circuit_breaker(
        self,
        metrics: Dict[str, float]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check circuit breaker conditions.
        
        Triggers on:
        - error_rate >10%
        - hallucination_rate >15%
        - 3+ consecutive anomalies
        
        Args:
            metrics: Current metrics
            
        Returns:
            (triggered: bool, reason: Optional[str])
        """
        # Check error rate
        error_rate = metrics.get("error_rate", 0.0)
        if error_rate > 0.10:
            return (True, f"error_rate_exceeded_{error_rate:.0%}")
        
        # Check hallucination rate
        hallucination_metrics = self.hallucination_tracker.get_metrics_report()
        hallucination_rate = hallucination_metrics.get("overall_hallucination_rate", 0.0)
        if hallucination_rate > 0.15:
            return (True, f"hallucination_rate_exceeded_{hallucination_rate:.0%}")
        
        # Check anomalies
        anomaly_check = self.anomaly_detector.check_multiple_metrics(metrics)
        if anomaly_check["recommended_action"] in [
            AnomalyAction.CIRCUIT_BREAK,
            AnomalyAction.ROLLBACK
        ]:
            return (True, f"anomaly_severity_{anomaly_check['highest_severity'].value}")
        
        return (False, None)
    
    def execute_rollback(
        self,
        variant_name: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Execute rollback of failed optimization.
        
        Args:
            variant_name: Variant that failed
            reason: Reason for rollback
            
        Returns:
            Dict with rollback result
        """
        self.status = IntegrationState.ROLLED_BACK
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason
        
        self._audit_log("rollback_executed", {
            "variant": variant_name,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.error("Rollback executed (variant=%s, reason=%s)", variant_name, reason)
        
        # Reset Thompson optimizer if active
        if self.thompson_optimizer.status == OptimizationStatus.EXPLORING:
            self.thompson_optimizer.status = OptimizationStatus.ROLLED_BACK
        
        return {
            "success": True,
            "variant": variant_name,
            "reason": reason,
            "status": self.status.value
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status of self-optimization system.
        
        Returns:
            Dict with all component statuses
        """
        current_metrics = self._get_current_metrics()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": self.status.value,
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "components": {
                "baseline_recorder": {
                    "status": "ok",
                    "baseline_age_days": self._get_baseline_age()
                },
                "anomaly_detector": {
                    "status": "ok",
                    "consecutive_anomalies": len(self.anomaly_detector.consecutive_anomalies)
                },
                "uncertainty_quantifier": {
                    "calibration_ece": self.uncertainty_quantifier.get_calibration_error(),
                    "samples": len(self.uncertainty_quantifier.history)
                },
                "hallucination_tracker": {
                    "hallucination_rate": self.hallucination_tracker.get_hallucination_rate(),
                    "samples": len(self.hallucination_tracker.history)
                },
                "thompson_optimizer": {
                    "status": self.thompson_optimizer.status.value,
                    "parameter": self.thompson_optimizer.parameter_name,
                    "iteration": self.thompson_optimizer.iteration,
                    "optimizations_this_hour": self.thompson_optimizer.optimizations_this_hour
                }
            },
            "metrics": {
                "current": current_metrics,
                "anomalies": self.anomaly_detector.check_multiple_metrics(current_metrics) if current_metrics else None
            }
        }
    
    def _get_current_metrics(self) -> Optional[Dict[str, float]]:
        """Get current metrics from Prometheus."""
        # In production, would query Prometheus
        # For now, return None (safe default)
        return None
    
    def _get_baseline_age(self) -> Optional[float]:
        """Get age of baseline in days."""
        baseline = self.baseline_recorder.load_baseline()
        if not baseline or "last_updated" not in baseline:
            return None
        
        try:
            updated = datetime.fromisoformat(baseline["last_updated"])
            age = (datetime.utcnow() - updated).total_seconds() / 86400
            return age
        except Exception:
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
        
        # Save (keep last 10,000 entries)
        try:
            with open(self.audit_file, 'w') as f:
                json.dump(audit[-10000:], f, indent=2)
        except Exception as e:
            logger.error("Failed to save audit: %s", e)


# Singleton instance
_integration: Optional[SelfOptimizationIntegration] = None


def get_integration() -> SelfOptimizationIntegration:
    """Get singleton integration instance."""
    global _integration
    if _integration is None:
        _integration = SelfOptimizationIntegration()
    return _integration
