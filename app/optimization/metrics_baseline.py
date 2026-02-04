"""
Baseline Recording System for Self-Optimization

Records metrics snapshots before and after optimizations.
Enables detection of regressions and improvement measurement.

Phase 20: Self-Optimization Strategy (Tier 1)
Author: Jarvis + Copilot
Date: 2026-02-02
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict, field
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

# Baseline storage directory
BASELINE_DIR = Path("/brain/system/logs/baselines")
BASELINE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MetricSnapshot:
    """Single metric measurement with timestamp and metadata"""
    
    timestamp: str
    iteration: int
    metric_name: str
    value: float
    confidence_interval_95: Optional[Tuple[float, float]] = None
    std_dev: Optional[float] = None
    sample_size: Optional[int] = None
    source: str = "unknown"  # e.g., "prometheus", "langfuse", "redis"
    
    def to_dict(self):
        return asdict(self)


@dataclass
class MetricsBaseline:
    """
    Complete baseline snapshot at a point in time.
    Includes: current values, variance estimates, and optimization context.
    """
    
    timestamp: str
    optimization_iteration: int
    optimization_trigger: str  # "manual_review", "scheduled", "performance_threshold"
    
    # Core metrics
    salience_threshold: float
    hint_frequency: float
    context_window_tokens: int
    
    # Performance metrics
    user_satisfaction_score: float
    latency_p95_ms: float
    error_rate: float
    cost_per_inference_usd: float
    
    # Variance/Confidence estimates
    satisfaction_ci_95: Tuple[float, float]
    latency_std_ms: float
    error_rate_std: float
    
    # Metadata
    sample_size: int
    active_users: int
    total_requests: int
    measurement_window_hours: int = 24
    
    # Optional: raw snapshots for later analysis
    snapshots: List[MetricSnapshot] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict"""
        data = asdict(self)
        data['snapshots'] = [s.to_dict() for s in self.snapshots]
        return data
    
    def save(self, filename: Optional[str] = None) -> str:
        """Save baseline to JSON file"""
        if not filename:
            filename = f"baseline_v{self.optimization_iteration}__{self.timestamp.replace(':', '-')}.json"
        
        filepath = BASELINE_DIR / filename
        
        try:
            with open(filepath, 'w') as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.info(f"✅ Baseline saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"❌ Failed to save baseline: {e}")
            raise


class BaselineRecorder:
    """
    Records and manages baseline metrics for self-optimization tracking.
    
    Usage:
        recorder = BaselineRecorder()
        baseline = recorder.record_baseline(
            salience_threshold=0.75,
            hint_frequency=3.8,
            # ... other metrics
        )
        baseline.save()
    """
    
    def __init__(self):
        self.current_baseline: Optional[MetricsBaseline] = None
        self.baseline_history: List[MetricsBaseline] = []
        self._load_history()
    
    def _load_history(self) -> None:
        """Load previous baselines from disk"""
        try:
            for baseline_file in sorted(BASELINE_DIR.glob("baseline_*.json")):
                with open(baseline_file, 'r') as f:
                    data = json.load(f)
                    # Reconstruct MetricsBaseline from dict
                    snapshots = [MetricSnapshot(**s) for s in data.pop('snapshots', [])]
                    baseline = MetricsBaseline(**data)
                    baseline.snapshots = snapshots
                    self.baseline_history.append(baseline)
            
            logger.info(f"✅ Loaded {len(self.baseline_history)} previous baselines")
        except Exception as e:
            logger.warning(f"⚠️ Could not load baseline history: {e}")
    
    def record_baseline(
        self,
        salience_threshold: float,
        hint_frequency: float,
        context_window_tokens: int,
        user_satisfaction_score: float,
        latency_p95_ms: float,
        error_rate: float,
        cost_per_inference_usd: float,
        satisfaction_ci_95: Tuple[float, float],
        latency_std_ms: float,
        error_rate_std: float,
        sample_size: int,
        active_users: int,
        total_requests: int,
        optimization_trigger: str = "manual_review",
        measurement_window_hours: int = 24,
    ) -> MetricsBaseline:
        """
        Record a new baseline snapshot.
        
        Args:
            salience_threshold: Current salience threshold (e.g., 0.75)
            hint_frequency: Proactive hints per session (e.g., 3.8)
            context_window_tokens: Current context window size in tokens
            user_satisfaction_score: User satisfaction on 0-1 scale
            latency_p95_ms: 95th percentile latency in milliseconds
            error_rate: Error rate on 0-1 scale
            cost_per_inference_usd: Cost per inference call in USD
            satisfaction_ci_95: 95% confidence interval for satisfaction
            latency_std_ms: Standard deviation of latency
            error_rate_std: Standard deviation of error rate
            sample_size: Number of samples in measurement
            active_users: Number of active users during window
            total_requests: Total requests during measurement window
            optimization_trigger: What triggered this baseline (e.g., "scheduled", "performance_threshold")
            measurement_window_hours: Measurement window in hours (default 24h)
        
        Returns:
            MetricsBaseline object
        """
        baseline = MetricsBaseline(
            timestamp=datetime.utcnow().isoformat(),
            optimization_iteration=len(self.baseline_history) + 1,
            optimization_trigger=optimization_trigger,
            salience_threshold=salience_threshold,
            hint_frequency=hint_frequency,
            context_window_tokens=context_window_tokens,
            user_satisfaction_score=user_satisfaction_score,
            latency_p95_ms=latency_p95_ms,
            error_rate=error_rate,
            cost_per_inference_usd=cost_per_inference_usd,
            satisfaction_ci_95=satisfaction_ci_95,
            latency_std_ms=latency_std_ms,
            error_rate_std=error_rate_std,
            sample_size=sample_size,
            active_users=active_users,
            total_requests=total_requests,
            measurement_window_hours=measurement_window_hours,
        )
        
        self.current_baseline = baseline
        self.baseline_history.append(baseline)
        logger.info(f"✅ Baseline #{baseline.optimization_iteration} recorded at {baseline.timestamp}")
        
        return baseline
    
    def add_snapshot(self, snapshot: MetricSnapshot) -> None:
        """Add raw metric snapshot to current baseline"""
        if self.current_baseline:
            self.current_baseline.snapshots.append(snapshot)
            logger.debug(f"Added snapshot: {snapshot.metric_name} = {snapshot.value}")
    
    def get_last_baseline(self) -> Optional[MetricsBaseline]:
        """Get previous baseline for comparison"""
        if len(self.baseline_history) >= 2:
            return self.baseline_history[-2]
        return None
    
    def compare_baselines(
        self,
        new_baseline: MetricsBaseline,
        baseline_to_compare: Optional[MetricsBaseline] = None
    ) -> Dict:
        """
        Compare two baselines and compute delta.
        
        Returns: {
            "metric_name": {
                "old": value,
                "new": value,
                "delta_absolute": value,
                "delta_percent": value,
                "is_improvement": bool,
                "statistical_significance": bool  # If confidence intervals overlap
            }
        }
        """
        if not baseline_to_compare:
            baseline_to_compare = self.get_last_baseline()
        
        if not baseline_to_compare:
            logger.warning("No previous baseline to compare")
            return {}
        
        comparisons = {}
        
        # Metrics where HIGHER is better
        higher_is_better = {
            'user_satisfaction_score': True,
        }
        
        # Metrics where LOWER is better
        lower_is_better = {
            'latency_p95_ms': True,
            'error_rate': True,
            'cost_per_inference_usd': True,
        }
        
        # Compare user satisfaction
        comparisons['user_satisfaction'] = self._compare_metric(
            baseline_to_compare.user_satisfaction_score,
            new_baseline.user_satisfaction_score,
            baseline_to_compare.satisfaction_ci_95,
            new_baseline.satisfaction_ci_95,
            higher_is_better=True
        )
        
        # Compare latency
        comparisons['latency_p95'] = self._compare_metric(
            baseline_to_compare.latency_p95_ms,
            new_baseline.latency_p95_ms,
            (
                baseline_to_compare.latency_p95_ms - 2 * baseline_to_compare.latency_std_ms,
                baseline_to_compare.latency_p95_ms + 2 * baseline_to_compare.latency_std_ms,
            ),
            (
                new_baseline.latency_p95_ms - 2 * new_baseline.latency_std_ms,
                new_baseline.latency_p95_ms + 2 * new_baseline.latency_std_ms,
            ),
            higher_is_better=False
        )
        
        # Compare error rate
        comparisons['error_rate'] = self._compare_metric(
            baseline_to_compare.error_rate,
            new_baseline.error_rate,
            (
                baseline_to_compare.error_rate - 2 * baseline_to_compare.error_rate_std,
                baseline_to_compare.error_rate + 2 * baseline_to_compare.error_rate_std,
            ),
            (
                new_baseline.error_rate - 2 * new_baseline.error_rate_std,
                new_baseline.error_rate + 2 * new_baseline.error_rate_std,
            ),
            higher_is_better=False
        )
        
        return comparisons
    
    @staticmethod
    def _compare_metric(
        old_value: float,
        new_value: float,
        old_ci: Tuple[float, float],
        new_ci: Tuple[float, float],
        higher_is_better: bool = True
    ) -> Dict:
        """Compare two metrics with confidence intervals"""
        delta_absolute = new_value - old_value
        delta_percent = (delta_absolute / old_value * 100) if old_value != 0 else 0
        
        # Intervals overlap = NOT statistically significant
        ci_overlap = not (old_ci[1] < new_ci[0] or new_ci[1] < old_ci[0])
        is_significant = not ci_overlap
        
        # Determine if improvement
        if higher_is_better:
            is_improvement = new_value > old_value and is_significant
        else:
            is_improvement = new_value < old_value and is_significant
        
        return {
            'old_value': old_value,
            'new_value': new_value,
            'delta_absolute': delta_absolute,
            'delta_percent': delta_percent,
            'old_ci_95': old_ci,
            'new_ci_95': new_ci,
            'is_significant': is_significant,
            'is_improvement': is_improvement,
        }


# Global recorder instance
_recorder_instance: Optional[BaselineRecorder] = None


def get_recorder() -> BaselineRecorder:
    """Get or create global BaselineRecorder instance"""
    global _recorder_instance
    if not _recorder_instance:
        _recorder_instance = BaselineRecorder()
    return _recorder_instance


if __name__ == "__main__":
    # Test/Example usage
    logging.basicConfig(level=logging.INFO)
    
    recorder = BaselineRecorder()
    
    # Record first baseline
    baseline1 = recorder.record_baseline(
        salience_threshold=0.75,
        hint_frequency=3.8,
        context_window_tokens=8000,
        user_satisfaction_score=0.82,
        latency_p95_ms=245,
        error_rate=0.002,
        cost_per_inference_usd=0.0012,
        satisfaction_ci_95=(0.78, 0.86),
        latency_std_ms=42,
        error_rate_std=0.0005,
        sample_size=1000,
        active_users=42,
        total_requests=15234,
        optimization_trigger="initial_baseline",
    )
    baseline1.save()
    
    # Record second baseline after hypothetical optimization
    baseline2 = recorder.record_baseline(
        salience_threshold=0.76,  # Slightly increased
        hint_frequency=3.9,  # Slightly increased
        context_window_tokens=8000,
        user_satisfaction_score=0.84,  # Improved!
        latency_p95_ms=238,  # Improved!
        error_rate=0.0018,  # Slightly worse
        cost_per_inference_usd=0.00118,  # Slightly worse (makes sense with longer context)
        satisfaction_ci_95=(0.80, 0.88),
        latency_std_ms=40,
        error_rate_std=0.0005,
        sample_size=1050,
        active_users=45,
        total_requests=15890,
        optimization_trigger="scheduled_review",
    )
    baseline2.save()
    
    # Compare
    comparison = recorder.compare_baselines(baseline2, baseline1)
    print("\n=== COMPARISON RESULTS ===")
    print(json.dumps(comparison, indent=2))
