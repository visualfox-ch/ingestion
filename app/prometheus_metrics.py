"""
Prometheus Metrics Query System

Provides real-time metric queries from Prometheus for:
- API response times
- Request rates
- Error rates
- Resource utilization
- Container metrics

Author: GitHub Copilot + Jarvis
Created: 2026-02-04
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json

from .observability import get_logger

logger = get_logger("jarvis.prometheus_client")


@dataclass
class MetricQuery:
    """Prometheus metric query definition."""
    name: str
    query: str
    description: str
    unit: str
    warn_threshold: Optional[float] = None
    crit_threshold: Optional[float] = None


class PrometheusClient:
    """
    Client for querying Prometheus metrics.
    
    Configured to connect to Prometheus on the NAS.
    """
    
    PROMETHEUS_HOST = os.environ.get("PROMETHEUS_HOST", "192.168.1.103")
    PROMETHEUS_PORT = int(os.environ.get("PROMETHEUS_PORT", "19090"))
    PROMETHEUS_BASE = f"http://{PROMETHEUS_HOST}:{PROMETHEUS_PORT}"
    
    # Common metric queries
    METRICS = {
        "api_response_time": MetricQuery(
            name="api_response_time",
            query='histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))',
            description="95th percentile API response time",
            unit="seconds",
            warn_threshold=0.5,
            crit_threshold=1.0
        ),
        "request_rate": MetricQuery(
            name="request_rate",
            query='rate(http_requests_total[1m])',
            description="HTTP request rate (per second)",
            unit="req/s",
            warn_threshold=None,
            crit_threshold=None
        ),
        "error_rate": MetricQuery(
            name="error_rate",
            query='rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])',
            description="Error rate (5xx responses)",
            unit="ratio",
            warn_threshold=0.01,
            crit_threshold=0.05
        ),
        "memory_usage": MetricQuery(
            name="memory_usage",
            query='process_resident_memory_bytes / 1024 / 1024',
            description="Memory usage",
            unit="MB",
            warn_threshold=1000,
            crit_threshold=2000
        ),
        "cpu_usage": MetricQuery(
            name="cpu_usage",
            query='rate(process_cpu_seconds_total[5m]) * 100',
            description="CPU usage",
            unit="percent",
            warn_threshold=75,
            crit_threshold=90
        ),
        "ingestion_queue_depth": MetricQuery(
            name="ingestion_queue_depth",
            query='queue_depth{job="ingestion"}',
            description="Ingestion queue depth",
            unit="messages",
            warn_threshold=100,
            crit_threshold=500
        ),
        "database_connection_pool": MetricQuery(
            name="database_connection_pool",
            query='db_connection_pool_size{job="ingestion"}',
            description="Database connection pool utilization",
            unit="connections",
            warn_threshold=25,
            crit_threshold=30
        ),
    }
    
    def __init__(self):
        """Initialize Prometheus client."""
        self.session = requests.Session()
        self.query_cache: Dict[str, tuple] = {}  # (timestamp, result)
        self.cache_ttl_seconds = 10
    
    def is_available(self) -> bool:
        """Check if Prometheus is available."""
        try:
            response = self.session.get(
                f"{self.PROMETHEUS_BASE}/-/healthy",
                timeout=2
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Prometheus availability check failed: {e}")
            return False
    
    def query_instant(self, query: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Execute instant query against Prometheus.
        
        Args:
            query: PromQL query string
            timeout: Request timeout in seconds
        
        Returns:
            Query result or None if failed
        """
        try:
            response = self.session.get(
                f"{self.PROMETHEUS_BASE}/api/v1/query",
                params={"query": query},
                timeout=timeout
            )
            
            if response.status_code != 200:
                logger.warning(f"Prometheus query failed: {response.status_code}")
                return None
            
            result = response.json()
            
            if result.get("status") != "success":
                logger.warning(f"Prometheus query error: {result.get('error')}")
                return None
            
            return result.get("data")
            
        except Exception as e:
            logger.error(f"Prometheus query error: {e}")
            return None
    
    def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "5m",
        timeout: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Execute range query against Prometheus.
        
        Args:
            query: PromQL query string
            start: Start time
            end: End time
            step: Query resolution (e.g., "5m", "1h")
            timeout: Request timeout in seconds
        
        Returns:
            Query result or None if failed
        """
        try:
            params = {
                "query": query,
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "step": step
            }
            
            response = self.session.get(
                f"{self.PROMETHEUS_BASE}/api/v1/query_range",
                params=params,
                timeout=timeout
            )
            
            if response.status_code != 200:
                logger.warning(f"Prometheus range query failed: {response.status_code}")
                return None
            
            result = response.json()
            
            if result.get("status") != "success":
                logger.warning(f"Prometheus range query error: {result.get('error')}")
                return None
            
            return result.get("data")
            
        except Exception as e:
            logger.error(f"Prometheus range query error: {e}")
            return None
    
    def get_metric(self, metric_name: str) -> Optional[float]:
        """
        Get current value of a predefined metric.
        
        Args:
            metric_name: Name of metric from METRICS dict
        
        Returns:
            Metric value or None if unavailable
        """
        if metric_name not in self.METRICS:
            logger.warning(f"Unknown metric: {metric_name}")
            return None
        
        metric = self.METRICS[metric_name]
        result = self.query_instant(metric.query)
        
        if not result or result.get("type") != "vector":
            return None
        
        values = result.get("result", [])
        if not values:
            return None
        
        try:
            # Return first value
            metric_value = float(values[0]["value"][1])
            return metric_value
        except (IndexError, KeyError, ValueError):
            return None
    
    def get_api_metrics(self) -> Dict[str, Any]:
        """Get key API performance metrics."""
        return {
            "response_time_p95_ms": (self.get_metric("api_response_time") or 0) * 1000,
            "request_rate_per_sec": self.get_metric("request_rate") or 0,
            "error_rate": self.get_metric("error_rate") or 0,
        }
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system resource metrics."""
        return {
            "memory_usage_mb": self.get_metric("memory_usage") or 0,
            "cpu_usage_percent": self.get_metric("cpu_usage") or 0,
        }
    
    def get_queue_metrics(self) -> Dict[str, Any]:
        """Get ingestion queue metrics."""
        return {
            "queue_depth": self.get_metric("ingestion_queue_depth") or 0,
            "db_pool_utilization": self.get_metric("database_connection_pool") or 0,
        }
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive health metrics snapshot."""
        return {
            "timestamp": datetime.now().isoformat(),
            "prometheus_available": self.is_available(),
            "api": self.get_api_metrics(),
            "system": self.get_system_metrics(),
            "queue": self.get_queue_metrics(),
        }
    
    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """
        Detect metric anomalies based on thresholds.
        
        Returns:
            List of anomalies detected
        """
        anomalies = []
        
        for metric_name, metric_def in self.METRICS.items():
            value = self.get_metric(metric_name)
            
            if value is None:
                continue
            
            # Check critical threshold
            if metric_def.crit_threshold and value > metric_def.crit_threshold:
                anomalies.append({
                    "severity": "critical",
                    "metric": metric_name,
                    "value": value,
                    "threshold": metric_def.crit_threshold,
                    "message": f"{metric_name}: {value:.2f} {metric_def.unit} (critical: {metric_def.crit_threshold})"
                })
            
            # Check warning threshold
            elif metric_def.warn_threshold and value > metric_def.warn_threshold:
                anomalies.append({
                    "severity": "warning",
                    "metric": metric_name,
                    "value": value,
                    "threshold": metric_def.warn_threshold,
                    "message": f"{metric_name}: {value:.2f} {metric_def.unit} (warning: {metric_def.warn_threshold})"
                })
        
        return anomalies


# Singleton instance
_prometheus_client: Optional[PrometheusClient] = None


def get_prometheus_client() -> PrometheusClient:
    """Get or create singleton Prometheus client."""
    global _prometheus_client
    if _prometheus_client is None:
        _prometheus_client = PrometheusClient()
    return _prometheus_client
