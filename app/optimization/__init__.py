"""
Self-Optimization Module

Phase 20: Self-Optimization Strategy Implementation

Core components:
- metrics_baseline: Baseline recording and comparison
- anomaly_detection: SPC, CUSUM, Isolation Forest monitoring
- confidence_scoring: Uncertainty quantification for decisions
"""

from .metrics_baseline import (
    BaselineRecorder,
    MetricsBaseline,
    MetricSnapshot,
    get_recorder,
)

from .anomaly_detection import (
    AnomalyDetectionSystem,
    SPCMonitor,
    CUSUMDetector,
    IsolationForestAnomalyDetector,
    AnomalyAlert,
    get_anomaly_detection_system,
)

from .confidence_scoring import (
    ConfidenceScorer,
    ConfidenceScore,
    MetricWithConfidence,
    OptimizationDecision,
)

__all__ = [
    # Baseline
    "BaselineRecorder",
    "MetricsBaseline",
    "MetricSnapshot",
    "get_recorder",
    # Anomaly Detection
    "AnomalyDetectionSystem",
    "SPCMonitor",
    "CUSUMDetector",
    "IsolationForestAnomalyDetector",
    "AnomalyAlert",
    "get_anomaly_detection_system",
    # Confidence Scoring
    "ConfidenceScorer",
    "ConfidenceScore",
    "MetricWithConfidence",
    "OptimizationDecision",
]
