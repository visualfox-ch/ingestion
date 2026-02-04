"""
Anomaly Detection System for Self-Optimization

Implements Statistical Process Control (SPC) and CUSUM monitoring.
Detects regressions and triggers automatic rollback when needed.

Phase 20: Self-Optimization Strategy (Tier 1)
Author: Jarvis + Copilot
Date: 2026-02-02

References:
- Page, E. S. (1954). "Continuous Inspection Schemes." Biometrika 41(1):100-115
- Liu, F. T., Ting, K. M. & Zhou, Z.-H. (2008). "Isolation Forest." ICDM 2008
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import deque
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


@dataclass
class AnomalyAlert:
    """Alert when anomaly is detected"""
    timestamp: str
    metric_name: str
    detector_type: str  # "spc", "cusum", "isolation_forest"
    severity: str  # "WARNING", "CRITICAL"
    value: float
    threshold: float
    message: str
    recommended_action: str  # "monitor", "rollback", "escalate"


class SPCMonitor:
    """
    Statistical Process Control Monitor (3-Sigma Rule).
    
    Detects when metric values fall outside mean ± 3 * std_dev.
    Based on Shewhart control charts.
    """
    
    def __init__(self, metric_name: str, baseline_window: int = 30):
        self.metric_name = metric_name
        self.baseline_window = baseline_window
        self.values = deque(maxlen=baseline_window)
        self.mean: Optional[float] = None
        self.std: Optional[float] = None
        self.is_trained = False
    
    def train(self, historical_values: List[float]) -> None:
        """Train on historical data to establish control limits"""
        if len(historical_values) < 10:
            logger.warning(f"⚠️ SPCMonitor.train: Too few samples for {self.metric_name} ({len(historical_values)})")
            return
        
        self.mean = np.mean(historical_values)
        self.std = np.std(historical_values)
        self.is_trained = True
        logger.info(f"✅ SPC Monitor trained for {self.metric_name}: mean={self.mean:.3f}, std={self.std:.3f}")
    
    def check(self, value: float) -> Tuple[bool, Optional[AnomalyAlert]]:
        """
        Check if value is anomalous.
        
        Returns: (is_anomaly, alert)
        """
        if not self.is_trained:
            logger.warning(f"⚠️ SPC Monitor not trained for {self.metric_name}")
            return False, None
        
        self.values.append(value)
        
        # 3-sigma rule: outside mean ± 3*std
        upper_control_limit = self.mean + 3 * self.std
        lower_control_limit = self.mean - 3 * self.std
        
        is_anomaly = value > upper_control_limit or value < lower_control_limit
        
        if is_anomaly:
            alert = AnomalyAlert(
                timestamp=datetime.utcnow().isoformat(),
                metric_name=self.metric_name,
                detector_type="spc",
                severity="WARNING" if abs(value - self.mean) < 4 * self.std else "CRITICAL",
                value=value,
                threshold=max(abs(upper_control_limit), abs(lower_control_limit)),
                message=f"SPC: {self.metric_name} = {value:.3f} outside control limits [{lower_control_limit:.3f}, {upper_control_limit:.3f}]",
                recommended_action="monitor" if is_anomaly else "escalate"
            )
            logger.warning(f"🔴 {alert.message}")
            return True, alert
        
        return False, None


class CUSUMDetector:
    """
    CUSUM (Cumulative Sum Control Chart) Detector.
    
    Detects sustained drift in metrics.
    More sensitive to small shifts than SPC.
    
    Reference: Page, E. S. (1954)
    """
    
    def __init__(
        self,
        metric_name: str,
        target: float = 0.0,
        threshold: float = 5.0,
        drift_param: float = 0.5
    ):
        """
        Args:
            metric_name: Name of metric being monitored
            target: Target value (0 for normalized metrics)
            threshold: H parameter in CUSUM (detection threshold)
            drift_param: k parameter in CUSUM (drift detection sensitivity)
        """
        self.metric_name = metric_name
        self.target = target
        self.threshold = threshold
        self.drift_param = drift_param  # k parameter
        self.cusum_pos = 0.0  # Cumulative sum for positive drift
        self.cusum_neg = 0.0  # Cumulative sum for negative drift
        self.is_anomaly = False
    
    def update(self, value: float) -> Tuple[bool, Optional[AnomalyAlert]]:
        """
        Update CUSUM with new value.
        Returns: (is_anomaly, alert)
        """
        deviation = value - self.target
        
        # Update cumulative sums
        self.cusum_pos = max(0, self.cusum_pos + deviation - self.drift_param)
        self.cusum_neg = max(0, self.cusum_neg - deviation - self.drift_param)
        
        # Check thresholds
        was_anomaly = self.is_anomaly
        self.is_anomaly = (self.cusum_pos > self.threshold) or (self.cusum_neg > self.threshold)
        
        if self.is_anomaly and not was_anomaly:
            # Anomaly just started
            direction = "INCREASE" if self.cusum_pos > self.threshold else "DECREASE"
            alert = AnomalyAlert(
                timestamp=datetime.utcnow().isoformat(),
                metric_name=self.metric_name,
                detector_type="cusum",
                severity="CRITICAL",
                value=value,
                threshold=self.threshold,
                message=f"CUSUM: Sustained {direction} detected in {self.metric_name} (value={value:.3f})",
                recommended_action="rollback"
            )
            logger.error(f"🔴🔴 {alert.message}")
            return True, alert
        
        elif not self.is_anomaly and was_anomaly:
            # Anomaly resolved
            logger.info(f"✅ CUSUM: Anomaly in {self.metric_name} has resolved")
        
        return False, None


class IsolationForestAnomalyDetector:
    """
    Multivariate Anomaly Detector using Isolation Forest.
    
    Detects unusual combinations of metrics that individual monitors might miss.
    
    Reference: Liu, F. T., Ting, K. M. & Zhou, Z.-H. (2008). "Isolation Forest." ICDM 2008
    """
    
    def __init__(self, metric_names: List[str], contamination: float = 0.05):
        self.metric_names = metric_names
        self.contamination = contamination
        self.model: Optional[IsolationForest] = None
        self.training_data = []
    
    def train(self, historical_data: List[Dict[str, float]]) -> None:
        """
        Train on historical data.
        
        Args:
            historical_data: List of dicts with metric values
                e.g., [
                    {'latency': 245, 'error_rate': 0.002, 'satisfaction': 0.82},
                    {'latency': 238, 'error_rate': 0.0018, 'satisfaction': 0.84},
                    ...
                ]
        """
        if len(historical_data) < 20:
            logger.warning(f"⚠️ IsolationForest.train: Too few samples ({len(historical_data)})")
            return
        
        # Convert to matrix
        X = np.array([
            [d.get(name, 0.0) for name in self.metric_names]
            for d in historical_data
        ])
        
        # Normalize
        X_normalized = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)
        
        self.model = IsolationForest(contamination=self.contamination, random_state=42)
        self.model.fit(X_normalized)
        self.training_data = historical_data
        
        logger.info(f"✅ IsolationForest trained on {len(historical_data)} samples")
    
    def check(self, metrics: Dict[str, float]) -> Tuple[bool, Optional[AnomalyAlert]]:
        """
        Check if metrics are anomalous.
        Returns: (is_anomaly, alert)
        """
        if not self.model:
            logger.warning("⚠️ IsolationForest not trained")
            return False, None
        
        # Prepare data point
        X = np.array([[metrics.get(name, 0.0) for name in self.metric_names]])
        
        # Normalize using training data stats
        if self.training_data:
            train_X = np.array([
                [d.get(name, 0.0) for name in self.metric_names]
                for d in self.training_data
            ])
            X_normalized = (X - train_X.mean(axis=0)) / (train_X.std(axis=0) + 1e-8)
        else:
            X_normalized = X
        
        # Predict (-1 = anomaly, 1 = normal)
        prediction = self.model.predict(X_normalized)[0]
        is_anomaly = prediction == -1
        
        if is_anomaly:
            anomaly_score = self.model.score_samples(X_normalized)[0]
            alert = AnomalyAlert(
                timestamp=datetime.utcnow().isoformat(),
                metric_name="multivariate_metrics",
                detector_type="isolation_forest",
                severity="WARNING",
                value=anomaly_score,
                threshold=self.model.offset_,
                message=f"Multivariate anomaly detected: {metrics}",
                recommended_action="monitor"
            )
            logger.warning(f"🟠 {alert.message}")
            return True, alert
        
        return False, None


class AnomalyDetectionSystem:
    """
    Integrated anomaly detection system.
    Combines SPC, CUSUM, and Isolation Forest.
    """
    
    def __init__(self):
        self.spc_monitors: Dict[str, SPCMonitor] = {}
        self.cusum_detectors: Dict[str, CUSUMDetector] = {}
        self.isolation_forest: Optional[IsolationForestAnomalyDetector] = None
        self.alerts: List[AnomalyAlert] = []
    
    def register_spc_metric(self, metric_name: str, baseline_window: int = 30) -> None:
        """Register a metric for SPC monitoring"""
        self.spc_monitors[metric_name] = SPCMonitor(metric_name, baseline_window)
    
    def register_cusum_metric(
        self,
        metric_name: str,
        target: float = 0.0,
        threshold: float = 5.0
    ) -> None:
        """Register a metric for CUSUM monitoring"""
        self.cusum_detectors[metric_name] = CUSUMDetector(metric_name, target, threshold)
    
    def setup_isolation_forest(self, metric_names: List[str]) -> None:
        """Setup multivariate anomaly detection"""
        self.isolation_forest = IsolationForestAnomalyDetector(metric_names)
    
    def train_on_baseline(self, baseline_data: List[Dict]) -> None:
        """
        Train all detectors on historical baseline data.
        
        Args:
            baseline_data: List of metric snapshots
        """
        # Train individual monitors
        for metric_name, monitor in self.spc_monitors.items():
            values = [d.get(metric_name, 0.0) for d in baseline_data]
            monitor.train(values)
        
        # Train isolation forest
        if self.isolation_forest:
            self.isolation_forest.train(baseline_data)
        
        logger.info(f"✅ Anomaly detection system trained on {len(baseline_data)} samples")
    
    def check_metrics(self, metrics: Dict[str, float]) -> List[AnomalyAlert]:
        """
        Check metrics for anomalies using all detectors.
        Returns list of alerts (empty = all normal).
        """
        current_alerts = []
        
        # SPC checks
        for metric_name, monitor in self.spc_monitors.items():
            if metric_name in metrics:
                is_anomaly, alert = monitor.check(metrics[metric_name])
                if is_anomaly:
                    current_alerts.append(alert)
        
        # CUSUM checks
        for metric_name, detector in self.cusum_detectors.items():
            if metric_name in metrics:
                is_anomaly, alert = detector.update(metrics[metric_name])
                if is_anomaly:
                    current_alerts.append(alert)
        
        # Isolation Forest check
        if self.isolation_forest:
            is_anomaly, alert = self.isolation_forest.check(metrics)
            if is_anomaly:
                current_alerts.append(alert)
        
        # Store and log
        self.alerts.extend(current_alerts)
        
        if current_alerts:
            logger.warning(f"⚠️ {len(current_alerts)} anomaly(ies) detected")
        
        return current_alerts
    
    def should_trigger_rollback(self, alerts: List[AnomalyAlert]) -> bool:
        """
        Determine if we should trigger automatic rollback.
        
        Criteria:
        - CRITICAL severity alert
        - CUSUM detector (indicates sustained drift)
        - Multiple simultaneous alerts
        """
        if not alerts:
            return False
        
        critical_alerts = [a for a in alerts if a.severity == "CRITICAL"]
        cusum_alerts = [a for a in alerts if a.detector_type == "cusum"]
        
        # Trigger rollback if:
        return bool(
            critical_alerts or  # Any critical alert
            (len(cusum_alerts) >= 2 and len(alerts) >= 2)  # Multiple sustained drifts
        )


# Global instance
_anomaly_system: Optional[AnomalyDetectionSystem] = None


def get_anomaly_detection_system() -> AnomalyDetectionSystem:
    """Get or create global anomaly detection system"""
    global _anomaly_system
    if not _anomaly_system:
        _anomaly_system = AnomalyDetectionSystem()
    return _anomaly_system


if __name__ == "__main__":
    # Test/Example usage
    logging.basicConfig(level=logging.INFO)
    
    system = AnomalyDetectionSystem()
    
    # Register metrics
    system.register_spc_metric("latency_p95")
    system.register_cusum_metric("error_rate", target=0.002, threshold=5.0)
    system.setup_isolation_forest(["latency_p95", "error_rate", "satisfaction"])
    
    # Create baseline data
    baseline_data = [
        {
            "latency_p95": 245 + np.random.normal(0, 10),
            "error_rate": 0.002 + np.random.normal(0, 0.0003),
            "satisfaction": 0.82 + np.random.normal(0, 0.02),
        }
        for _ in range(50)
    ]
    
    # Train
    system.train_on_baseline(baseline_data)
    
    # Test normal
    print("\n=== Testing Normal Metrics ===")
    alerts = system.check_metrics({
        "latency_p95": 248,
        "error_rate": 0.0021,
        "satisfaction": 0.83,
    })
    print(f"Alerts: {len(alerts)}")
    
    # Test anomalous
    print("\n=== Testing Anomalous Metrics ===")
    alerts = system.check_metrics({
        "latency_p95": 400,  # Way outside normal range
        "error_rate": 0.01,  # Way outside normal range
        "satisfaction": 0.5,
    })
    print(f"Alerts: {len(alerts)}")
    for alert in alerts:
        print(f"  - {alert.detector_type}: {alert.message} (severity: {alert.severity})")
    
    should_rollback = system.should_trigger_rollback(alerts)
    print(f"\nShould trigger rollback: {should_rollback}")
