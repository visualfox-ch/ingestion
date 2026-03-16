"""
Prometheus Metrics Exporter for Self-Optimization

Exports all self-optimization metrics to Prometheus for monitoring:
- Baseline metrics (7-day SPC)
- Anomaly metrics (3-sigma detections)
- Uncertainty metrics (calibration error)
- Hallucination metrics (detection rate)
- Optimization metrics (Thompson trials, convergence)

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import json
from pathlib import Path

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Summary,
        start_http_server,
        REGISTRY
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


def _get_or_create_counter(name: str, description: str, labels: list = None) -> 'Counter':
    """Get existing counter or create new one (avoid duplicate registration)."""
    try:
        return Counter(name, description, labels or [])
    except ValueError:
        # Already registered - get existing
        return REGISTRY._names_to_collectors.get(name)


def _get_or_create_gauge(name: str, description: str, labels: list = None) -> 'Gauge':
    """Get existing gauge or create new one."""
    try:
        return Gauge(name, description, labels or [])
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)


def _get_or_create_histogram(name: str, description: str, labels: list = None, buckets=None) -> 'Histogram':
    """Get existing histogram or create new one."""
    try:
        if buckets:
            return Histogram(name, description, labels or [], buckets=buckets)
        return Histogram(name, description, labels or [])
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)


class PrometheusExporter:
    """Export self-optimization metrics to Prometheus."""
    
    def __init__(self, port: int = 18001):
        """
        Initialize Prometheus exporter.
        
        Args:
            port: Port for metrics HTTP server (default 18001)
        """
        self.port = port
        self.prometheus_available = PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            print("Warning: prometheus_client not installed, metrics disabled")
            return
        
        # Baseline metrics (SPC)
        self.baseline_mean = Gauge(
            'jarvis_baseline_mean',
            'Baseline mean for metric',
            ['metric_name']
        )
        self.baseline_std = Gauge(
            'jarvis_baseline_std',
            'Baseline std for metric',
            ['metric_name']
        )
        self.baseline_ucl = Gauge(
            'jarvis_baseline_ucl',
            'Upper Control Limit for metric',
            ['metric_name']
        )
        self.baseline_lcl = Gauge(
            'jarvis_baseline_lcl',
            'Lower Control Limit for metric',
            ['metric_name']
        )
        
        # Anomaly detection metrics (use helpers to avoid duplicate registration)
        self.anomalies_detected = _get_or_create_counter(
            'jarvis_anomalies_detected_total',
            'Total anomalies detected',
            ['severity', 'metric_name']
        )
        self.anomaly_check_duration = _get_or_create_histogram(
            'jarvis_anomaly_check_seconds',
            'Time to check anomalies',
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0)
        )
        
        # Uncertainty quantification metrics
        self.calibration_error = Gauge(
            'jarvis_calibration_error',
            'Expected Calibration Error (ECE)',
            ['domain']
        )
        self.uncertainty_samples = Counter(
            'jarvis_uncertainty_samples_total',
            'Total uncertainty samples recorded',
            ['domain']
        )
        
        # Hallucination tracking metrics
        self.hallucination_rate = Gauge(
            'jarvis_hallucination_rate',
            'Current hallucination rate',
            ['domain']
        )
        self.hallucinations_detected = Counter(
            'jarvis_hallucinations_detected_total',
            'Total hallucinations detected',
            ['type', 'domain']
        )
        
        # Thompson Sampling optimization metrics
        self.optimization_iterations = Gauge(
            'jarvis_optimization_iterations',
            'Current optimization iteration',
            ['parameter']
        )
        self.variant_success_rate = Gauge(
            'jarvis_variant_success_rate',
            'Success rate for variant',
            ['parameter', 'variant']
        )
        self.variant_trials = Counter(
            'jarvis_variant_trials_total',
            'Total trials for variant',
            ['parameter', 'variant']
        )
        
        # Circuit breaker metrics
        self.circuit_breaker_active = Gauge(
            'jarvis_circuit_breaker_active',
            'Whether circuit breaker is active'
        )
        self.circuit_breaker_triggers = Counter(
            'jarvis_circuit_breaker_triggers_total',
            'Total circuit breaker triggers',
            ['reason']
        )
        
        # Optimization workflow metrics
        self.optimization_cycles = Counter(
            'jarvis_optimization_cycles_total',
            'Total optimization cycles',
            ['parameter', 'status']
        )
        self.optimization_duration = Histogram(
            'jarvis_optimization_duration_seconds',
            'Time to complete optimization cycle',
            ['parameter'],
            buckets=(1, 5, 10, 30, 60, 300, 600)
        )

        # LLM Optimization metrics (O1-O6) - use helpers to avoid duplicate registration
        self.llm_cache_hits = _get_or_create_counter(
            'jarvis_llm_cache_hits_total',
            'Total LLM cache hits',
            ['cache_type']  # anthropic_prompt, openai_response, tool_definitions
        )
        self.llm_cache_misses = _get_or_create_counter(
            'jarvis_llm_cache_misses_total',
            'Total LLM cache misses',
            ['cache_type']
        )
        self.llm_tokens_saved = _get_or_create_counter(
            'jarvis_llm_tokens_saved_total',
            'Total tokens saved by caching',
            ['optimization']  # o2_responses, o3_prompt_cache, o5_tool_cache
        )
        self.llm_context_truncations = _get_or_create_counter(
            'jarvis_llm_context_truncations_total',
            'Total context window truncations (O6)'
        )
        self.llm_context_messages_dropped = _get_or_create_counter(
            'jarvis_llm_context_messages_dropped_total',
            'Total messages dropped due to context limit (O6)'
        )
        self.llm_streaming_chars = _get_or_create_counter(
            'jarvis_llm_streaming_chars_total',
            'Total characters streamed (O4)'
        )
        self.llm_batch_requests = _get_or_create_counter(
            'jarvis_llm_batch_requests_total',
            'Total batch API requests (O1)',
            ['status']  # queued, completed, failed
        )

    def export_baseline(self, baseline: Dict[str, Any]) -> None:
        """Export baseline metrics."""
        if not PROMETHEUS_AVAILABLE or not baseline or "metrics" not in baseline:
            return
        
        for metric_name, stats in baseline["metrics"].items():
            self.baseline_mean.labels(metric_name=metric_name).set(stats["mean"])
            self.baseline_std.labels(metric_name=metric_name).set(stats["std"])
            self.baseline_ucl.labels(metric_name=metric_name).set(stats["ucl"])
            self.baseline_lcl.labels(metric_name=metric_name).set(stats["lcl"])
    
    def export_anomaly(
        self,
        metric_name: str,
        severity: str,
        is_anomaly: bool
    ) -> None:
        """Export anomaly detection."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        if is_anomaly:
            self.anomalies_detected.labels(
                severity=severity,
                metric_name=metric_name
            ).inc()
    
    def export_uncertainty(
        self,
        domain: str,
        calibration_error: Optional[float],
        sample_count: int
    ) -> None:
        """Export uncertainty metrics."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        if calibration_error is not None:
            self.calibration_error.labels(domain=domain).set(calibration_error)
        
        self.uncertainty_samples.labels(domain=domain).inc(sample_count)
    
    def export_hallucination(
        self,
        domain: str,
        hallucination_rate: float,
        detection_type: Optional[str] = None
    ) -> None:
        """Export hallucination metrics."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        self.hallucination_rate.labels(domain=domain).set(hallucination_rate)
        
        if detection_type:
            self.hallucinations_detected.labels(
                type=detection_type,
                domain=domain
            ).inc()
    
    def export_optimization_state(
        self,
        parameter: str,
        iteration: int,
        variants: Dict[str, Any]
    ) -> None:
        """Export Thompson optimization state."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        self.optimization_iterations.labels(parameter=parameter).set(iteration)
        
        for variant_name, variant_data in variants.items():
            success_rate = variant_data.get("success_rate", 0.0)
            trials = variant_data.get("trials", 0)
            
            self.variant_success_rate.labels(
                parameter=parameter,
                variant=variant_name
            ).set(success_rate)
            
            self.variant_trials.labels(
                parameter=parameter,
                variant=variant_name
            ).inc(trials)
    
    def export_circuit_breaker(
        self,
        active: bool,
        reason: Optional[str] = None
    ) -> None:
        """Export circuit breaker state."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        self.circuit_breaker_active.set(1 if active else 0)
        
        if active and reason:
            self.circuit_breaker_triggers.labels(reason=reason).inc()
    
    def export_optimization_cycle(
        self,
        parameter: str,
        status: str
    ) -> None:
        """Export optimization cycle completion."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        self.optimization_cycles.labels(
            parameter=parameter,
            status=status
        ).inc()

    # LLM Optimization export methods (O1-O6)
    def export_llm_cache_hit(self, cache_type: str) -> None:
        """Record LLM cache hit (O2/O3/O5)."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_cache_hits.labels(cache_type=cache_type).inc()

    def export_llm_cache_miss(self, cache_type: str) -> None:
        """Record LLM cache miss."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_cache_misses.labels(cache_type=cache_type).inc()

    def export_llm_tokens_saved(self, optimization: str, tokens: int) -> None:
        """Record tokens saved by optimization."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_tokens_saved.labels(optimization=optimization).inc(tokens)

    def export_llm_context_truncation(self, messages_dropped: int = 0) -> None:
        """Record context window truncation (O6)."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_context_truncations.inc()
        if messages_dropped > 0:
            self.llm_context_messages_dropped.inc(messages_dropped)

    def export_llm_streaming(self, chars: int) -> None:
        """Record streaming characters (O4)."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_streaming_chars.inc(chars)

    def export_llm_batch_request(self, status: str) -> None:
        """Record batch API request (O1)."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.llm_batch_requests.labels(status=status).inc()

    def start_server(self) -> bool:
        """
        Start Prometheus HTTP server.
        
        Returns:
            True if started, False if not available
        """
        if not PROMETHEUS_AVAILABLE:
            return False
        
        try:
            start_http_server(self.port)
            print(f"Prometheus metrics server started on port {self.port}")
            return True
        except Exception as e:
            print(f"Failed to start Prometheus server: {e}")
            return False


# Singleton instance
_exporter: Optional[PrometheusExporter] = None


def get_prometheus_exporter(port: int = 18001) -> PrometheusExporter:
    """Get singleton Prometheus exporter."""
    global _exporter
    if _exporter is None:
        _exporter = PrometheusExporter(port=port)
    return _exporter


# Metrics snapshot storage (for dashboards without Prometheus)
class MetricsSnapshot:
    """Store metrics snapshots for dashboard display."""
    
    def __init__(self, state_path: str = "/brain/system/state"):
        """Initialize metrics snapshot storage."""
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        self.snapshot_file = self.state_path / "metrics_snapshot.json"
    
    def save_snapshot(self, metrics: Dict[str, Any]) -> None:
        """
        Save metrics snapshot.
        
        Args:
            metrics: Dict of metrics to save
        """
        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": metrics
        }
        
        try:
            with open(self.snapshot_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
        except Exception as e:
            print(f"Failed to save metrics snapshot: {e}")
    
    def load_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        Load latest metrics snapshot.
        
        Returns:
            Dict with timestamp and metrics, or None if not available
        """
        if not self.snapshot_file.exists():
            return None
        
        try:
            with open(self.snapshot_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load metrics snapshot: {e}")
            return None
    
    def get_snapshot_age_seconds(self) -> Optional[int]:
        """Get age of snapshot in seconds."""
        snapshot = self.load_snapshot()
        if not snapshot or "timestamp" not in snapshot:
            return None
        
        try:
            snapshot_time = datetime.fromisoformat(snapshot["timestamp"])
            age = (datetime.utcnow() - snapshot_time).total_seconds()
            return int(age)
        except Exception:
            return None


def get_metrics_snapshot(state_path: str = "/brain/system/state") -> MetricsSnapshot:
    """Get metrics snapshot storage."""
    return MetricsSnapshot(state_path=state_path)
