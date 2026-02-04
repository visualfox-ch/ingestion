"""
Anomaly Detector for Self-Optimization

Detects metric anomalies using Statistical Process Control (SPC).
Triggers auto-rollback when metrics deviate beyond control limits.

Research Foundation:
- Page, E.S. (1954). "Continuous Inspection Schemes." Biometrika 41(1):100-115.
- Liu, F.T. et al. (2008). "Isolation Forest." ICDM 2008.

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from .observability import get_logger
from .baseline_recorder import get_baseline_recorder

logger = get_logger("jarvis.anomaly_detector")


class AnomalySeverity(str, Enum):
    """Anomaly severity levels."""
    LOW = "low"           # 2-3 sigma: alert only
    MEDIUM = "medium"     # 3-4 sigma: review required
    HIGH = "high"         # >4 sigma: auto-rollback
    CRITICAL = "critical" # Multiple consecutive anomalies


class AnomalyAction(str, Enum):
    """Actions to take on anomaly detection."""
    NONE = "none"                 # No action (within limits)
    ALERT = "alert"               # Alert only (low severity)
    REVIEW = "review"             # Human review (medium)
    ROLLBACK = "rollback"         # Auto-rollback (high/critical)
    CIRCUIT_BREAK = "circuit_break"  # Disable optimization


class AnomalyDetector:
    """
    Detects metric anomalies using SPC (Statistical Process Control).
    
    Uses 3-sigma rule (99.7% confidence interval):
    - Normal: within ±3 sigma
    - Warning: 2-3 sigma deviation
    - Anomaly: >3 sigma deviation
    - Critical: >4 sigma or 3+ consecutive anomalies
    
    Triggers:
    - Low severity: alert only
    - Medium severity: human review
    - High severity: auto-rollback
    - Critical: circuit breaker (disable optimization)
    """
    
    def __init__(self):
        """Initialize anomaly detector."""
        self.baseline_recorder = get_baseline_recorder()
        self.consecutive_anomalies = {}  # Track consecutive anomalies per metric
        
    def check_anomaly(
        self,
        metric_name: str,
        current_value: float,
        direction: str = "both"  # "both", "upper", "lower"
    ) -> Dict[str, Any]:
        """
        Check if current metric value is anomalous.
        
        Args:
            metric_name: Name of metric to check
            current_value: Current metric value
            direction: Which direction to check ("both", "upper", "lower")
                      "upper" = only check if value is too high
                      "lower" = only check if value is too low
                      "both" = check both directions
                      
        Returns:
            Dict with structure:
            {
                "is_anomaly": bool,
                "severity": AnomalySeverity,
                "action": AnomalyAction,
                "deviation_sigmas": float,
                "current_value": float,
                "baseline_mean": float,
                "baseline_std": float,
                "ucl": float,
                "lcl": float,
                "reason": str,
                "consecutive_count": int
            }
        """
        # Load baseline
        baseline = self.baseline_recorder.load_baseline()
        
        if not baseline or "metrics" not in baseline:
            return {
                "is_anomaly": False,
                "severity": AnomalySeverity.LOW,
                "action": AnomalyAction.NONE,
                "reason": "no_baseline_available",
                "current_value": current_value
            }
        
        if metric_name not in baseline["metrics"]:
            return {
                "is_anomaly": False,
                "severity": AnomalySeverity.LOW,
                "action": AnomalyAction.NONE,
                "reason": f"metric_{metric_name}_not_in_baseline",
                "current_value": current_value
            }
        
        # Get baseline statistics
        stats = baseline["metrics"][metric_name]
        mean = stats["mean"]
        std = stats["std"]
        ucl = stats["ucl"]
        lcl = stats["lcl"]
        
        # Calculate deviation in sigmas
        if std == 0:
            # Avoid division by zero
            deviation_sigmas = 0.0
        else:
            deviation_sigmas = abs(current_value - mean) / std
        
        # Check if anomalous based on direction
        is_upper_anomaly = current_value > ucl
        is_lower_anomaly = current_value < lcl
        
        is_anomaly = False
        if direction == "both":
            is_anomaly = is_upper_anomaly or is_lower_anomaly
        elif direction == "upper":
            is_anomaly = is_upper_anomaly
        elif direction == "lower":
            is_anomaly = is_lower_anomaly
        
        # Update consecutive anomaly counter
        if is_anomaly:
            self.consecutive_anomalies[metric_name] = self.consecutive_anomalies.get(metric_name, 0) + 1
        else:
            self.consecutive_anomalies[metric_name] = 0
        
        consecutive_count = self.consecutive_anomalies[metric_name]
        
        # Determine severity and action
        severity, action = self._determine_severity_action(
            deviation_sigmas,
            consecutive_count,
            is_anomaly
        )
        
        result = {
            "is_anomaly": is_anomaly,
            "severity": severity,
            "action": action,
            "deviation_sigmas": deviation_sigmas,
            "current_value": current_value,
            "baseline_mean": mean,
            "baseline_std": std,
            "ucl": ucl,
            "lcl": lcl,
            "consecutive_count": consecutive_count,
            "direction": "upper" if is_upper_anomaly else "lower" if is_lower_anomaly else "normal",
            "reason": self._build_reason(
                is_anomaly,
                deviation_sigmas,
                consecutive_count,
                direction
            )
        }
        
        if is_anomaly:
            logger.warning(
                "Anomaly detected",
                metric=metric_name,
                severity=severity.value,
                action=action.value,
                deviation=deviation_sigmas,
                consecutive=consecutive_count
            )
        
        return result
    
    def _determine_severity_action(
        self,
        deviation_sigmas: float,
        consecutive_count: int,
        is_anomaly: bool
    ) -> tuple[AnomalySeverity, AnomalyAction]:
        """
        Determine severity and action based on deviation and history.
        
        Rules:
        - Normal (0-2σ): No action
        - Low (2-3σ): Alert only
        - Medium (3-4σ): Review required
        - High (>4σ): Auto-rollback
        - Critical (3+ consecutive): Circuit breaker
        
        Args:
            deviation_sigmas: Number of standard deviations from mean
            consecutive_count: Number of consecutive anomalies
            is_anomaly: Whether this is an anomaly
            
        Returns:
            (severity, action) tuple
        """
        if not is_anomaly:
            return AnomalySeverity.LOW, AnomalyAction.NONE
        
        # Check for critical pattern (3+ consecutive anomalies)
        if consecutive_count >= 3:
            return AnomalySeverity.CRITICAL, AnomalyAction.CIRCUIT_BREAK
        
        # Check deviation magnitude
        if deviation_sigmas > 4.0:
            return AnomalySeverity.HIGH, AnomalyAction.ROLLBACK
        elif deviation_sigmas > 3.0:
            return AnomalySeverity.MEDIUM, AnomalyAction.REVIEW
        elif deviation_sigmas > 2.0:
            return AnomalySeverity.LOW, AnomalyAction.ALERT
        else:
            return AnomalySeverity.LOW, AnomalyAction.NONE
    
    def _build_reason(
        self,
        is_anomaly: bool,
        deviation_sigmas: float,
        consecutive_count: int,
        direction: str
    ) -> str:
        """
        Build human-readable reason for anomaly detection result.
        
        Args:
            is_anomaly: Whether this is an anomaly
            deviation_sigmas: Deviation in sigmas
            consecutive_count: Consecutive anomaly count
            direction: Direction checked
            
        Returns:
            Reason string
        """
        if not is_anomaly:
            return "within_control_limits"
        
        reason_parts = [
            f"{deviation_sigmas:.1f}_sigma_deviation",
            f"direction_{direction}"
        ]
        
        if consecutive_count > 1:
            reason_parts.append(f"consecutive_{consecutive_count}")
        
        return " | ".join(reason_parts)
    
    def check_multiple_metrics(
        self,
        metrics: Dict[str, float],
        directions: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Check multiple metrics for anomalies.
        
        Args:
            metrics: Dict of {metric_name: current_value}
            directions: Optional dict of {metric_name: direction}
                       If not provided, defaults to "both" for all
                       
        Returns:
            Dict with structure:
            {
                "any_anomaly": bool,
                "highest_severity": AnomalySeverity,
                "recommended_action": AnomalyAction,
                "results": {metric_name: anomaly_result},
                "summary": str
            }
        """
        directions = directions or {}
        results = {}
        
        any_anomaly = False
        highest_severity = AnomalySeverity.LOW
        recommended_action = AnomalyAction.NONE
        
        # Check each metric
        for metric_name, current_value in metrics.items():
            direction = directions.get(metric_name, "both")
            result = self.check_anomaly(metric_name, current_value, direction)
            results[metric_name] = result
            
            if result["is_anomaly"]:
                any_anomaly = True
                
                # Track highest severity
                if self._severity_rank(result["severity"]) > self._severity_rank(highest_severity):
                    highest_severity = result["severity"]
                    recommended_action = result["action"]
        
        # Build summary
        anomaly_count = sum(1 for r in results.values() if r["is_anomaly"])
        summary = f"{anomaly_count}/{len(metrics)} metrics anomalous"
        
        if highest_severity == AnomalySeverity.CRITICAL:
            summary += " - CRITICAL: Circuit breaker triggered"
        elif highest_severity == AnomalySeverity.HIGH:
            summary += " - HIGH: Auto-rollback required"
        elif highest_severity == AnomalySeverity.MEDIUM:
            summary += " - MEDIUM: Human review needed"
        
        return {
            "any_anomaly": any_anomaly,
            "highest_severity": highest_severity,
            "recommended_action": recommended_action,
            "anomaly_count": anomaly_count,
            "total_metrics": len(metrics),
            "results": results,
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _severity_rank(self, severity: AnomalySeverity) -> int:
        """Get numeric rank for severity comparison."""
        ranks = {
            AnomalySeverity.LOW: 1,
            AnomalySeverity.MEDIUM: 2,
            AnomalySeverity.HIGH: 3,
            AnomalySeverity.CRITICAL: 4
        }
        return ranks.get(severity, 0)
    
    def reset_consecutive_counts(self) -> None:
        """Reset all consecutive anomaly counters."""
        self.consecutive_anomalies = {}
        logger.info("Consecutive anomaly counters reset")


# Singleton instance
_anomaly_detector: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get singleton anomaly detector instance."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
    return _anomaly_detector
