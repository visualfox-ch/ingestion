"""
Health Insights & Proactive Monitoring System

Provides:
- Real-time system health metrics
- Proactive alerts based on anomalies
- Performance trend analysis
- Resource utilization predictions
- Actionable recommendations

Author: GitHub Copilot + Jarvis
Created: 2026-02-04
"""

import os
import time
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import json
from pathlib import Path

from .observability import get_logger

logger = get_logger("jarvis.health_insights")


class HealthStatus(str, Enum):
    """System health status levels."""
    OPTIMAL = "🟢 OPTIMAL"
    ATTENTION = "🟡 ATTENTION"
    WARNING = "🟠 WARNING"
    CRITICAL = "🔴 CRITICAL"


@dataclass
class HealthMetrics:
    """Current health metrics snapshot."""
    timestamp: str
    api_response_time_ms: float
    memory_usage_percent: float
    cpu_usage_percent: float
    disk_usage_percent: float
    error_rate_percent: float
    active_sessions: int
    requests_per_minute: float
    containers_healthy: int
    containers_total: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthTrend:
    """24-hour trend for a metric."""
    metric_name: str
    current: float
    avg_24h: float
    max_24h: float
    min_24h: float
    trend: str  # "↑" (increasing), "↓" (decreasing), "→" (stable)
    change_percent: float
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProactiveHint:
    """Actionable insight based on metrics."""
    severity: str  # "info", "warning", "critical"
    category: str  # "performance", "resources", "errors", "trends"
    title: str
    message: str
    recommendation: str
    metric_source: str
    threshold_exceeded: Optional[Tuple[str, float, float]] = None  # (metric, actual, threshold)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HealthInsights:
    """
    Proactive monitoring and insight generation system.
    
    Monitors:
    - API response times
    - Memory/CPU/Disk usage
    - Error rates
    - Container health
    - User session trends
    - Performance anomalies
    """
    
    # Thresholds for health evaluation
    THRESHOLDS = {
        "api_response_time_ms": {
            "optimal": 150,      # < 150ms = optimal
            "attention": 250,    # 150-250ms = attention
            "warning": 500,      # 250-500ms = warning
            "critical": 1000     # > 1000ms = critical
        },
        "memory_percent": {
            "optimal": 50,
            "attention": 70,
            "warning": 85,
            "critical": 95
        },
        "cpu_percent": {
            "optimal": 60,
            "attention": 75,
            "warning": 85,
            "critical": 95
        },
        "disk_percent": {
            "optimal": 60,
            "attention": 75,
            "warning": 85,
            "critical": 95
        },
        "error_rate_percent": {
            "optimal": 0.1,
            "attention": 0.5,
            "warning": 1.0,
            "critical": 5.0
        }
    }
    
    def __init__(self):
        """Initialize health insights system."""
        self.metrics_history: List[HealthMetrics] = []
        self.hints_cache: Dict[str, ProactiveHint] = {}
        self.last_update = datetime.now()
        
    def get_process_metrics(self) -> Dict[str, Any]:
        """Get current process metrics."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                "pid": process.pid,
                "rss_mb": memory_info.rss / 1024 / 1024,
                "vms_mb": memory_info.vms / 1024 / 1024,
                "cpu_percent": process.cpu_percent(interval=0.1),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
            }
        except Exception as e:
            logger.error(f"Failed to get process metrics: {e}")
            return {}
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system-wide metrics."""
        try:
            return {
                "memory_percent": psutil.virtual_memory().percent,
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "disk_percent": psutil.disk_usage("/").percent,
                "load_average": {
                    "1min": os.getloadavg()[0],
                    "5min": os.getloadavg()[1],
                    "15min": os.getloadavg()[2]
                },
                "cpu_count": psutil.cpu_count(),
                "memory_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            }
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {}
    
    def estimate_api_response_time(self, from_metrics: Optional[Dict] = None) -> float:
        """
        Estimate API response time from available metrics.
        In production, this would be collected from actual request logs.
        """
        # Placeholder: In real setup, get from Prometheus or request middleware
        if from_metrics and "api_latency_ms" in from_metrics:
            return from_metrics["api_latency_ms"]
        
        # Estimate based on CPU/Memory load
        sys_metrics = self.get_system_metrics()
        cpu_load = sys_metrics.get("cpu_percent", 0)
        mem_load = sys_metrics.get("memory_percent", 0)
        
        # Simple heuristic: baseline 100ms + load impact
        baseline = 100.0
        cpu_impact = (cpu_load / 100.0) * 150  # Up to +150ms
        mem_impact = (mem_load / 100.0) * 100  # Up to +100ms
        
        return baseline + cpu_impact + mem_impact
    
    def get_container_health(self) -> Dict[str, Any]:
        """Get Docker container health status."""
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return {"healthy": 0, "total": 0, "containers": []}
            
            containers = []
            healthy_count = 0
            
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                
                name, status = parts[0], parts[1]
                is_healthy = "Up" in status and "Exited" not in status
                
                if is_healthy:
                    healthy_count += 1
                
                containers.append({
                    "name": name,
                    "status": status,
                    "healthy": is_healthy
                })
            
            return {
                "healthy": healthy_count,
                "total": len(containers),
                "containers": containers
            }
        except Exception as e:
            logger.warning(f"Could not get container health: {e}")
            return {"healthy": 0, "total": 0, "containers": []}
    
    def evaluate_health_status(self, metrics: HealthMetrics) -> HealthStatus:
        """Determine overall health status based on metrics."""
        thresholds = self.THRESHOLDS
        
        # Count metric violations at each level
        critical_violations = 0
        warning_violations = 0
        attention_violations = 0
        
        # Check API response time
        if metrics.api_response_time_ms > thresholds["api_response_time_ms"]["critical"]:
            critical_violations += 1
        elif metrics.api_response_time_ms > thresholds["api_response_time_ms"]["warning"]:
            warning_violations += 1
        elif metrics.api_response_time_ms > thresholds["api_response_time_ms"]["attention"]:
            attention_violations += 1
        
        # Check memory
        if metrics.memory_usage_percent > thresholds["memory_percent"]["critical"]:
            critical_violations += 1
        elif metrics.memory_usage_percent > thresholds["memory_percent"]["warning"]:
            warning_violations += 1
        elif metrics.memory_usage_percent > thresholds["memory_percent"]["attention"]:
            attention_violations += 1
        
        # Check CPU
        if metrics.cpu_usage_percent > thresholds["cpu_percent"]["critical"]:
            critical_violations += 1
        elif metrics.cpu_usage_percent > thresholds["cpu_percent"]["warning"]:
            warning_violations += 1
        elif metrics.cpu_usage_percent > thresholds["cpu_percent"]["attention"]:
            attention_violations += 1
        
        # Check disk
        if metrics.disk_usage_percent > thresholds["disk_percent"]["critical"]:
            critical_violations += 1
        elif metrics.disk_usage_percent > thresholds["disk_percent"]["warning"]:
            warning_violations += 1
        elif metrics.disk_usage_percent > thresholds["disk_percent"]["attention"]:
            attention_violations += 1
        
        # Check error rate
        if metrics.error_rate_percent > thresholds["error_rate_percent"]["critical"]:
            critical_violations += 1
        elif metrics.error_rate_percent > thresholds["error_rate_percent"]["warning"]:
            warning_violations += 1
        elif metrics.error_rate_percent > thresholds["error_rate_percent"]["attention"]:
            attention_violations += 1
        
        # Determine status based on violations
        if critical_violations > 0:
            return HealthStatus.CRITICAL
        elif warning_violations > 0:
            return HealthStatus.WARNING
        elif attention_violations > 0:
            return HealthStatus.ATTENTION
        else:
            return HealthStatus.OPTIMAL
    
    def generate_proactive_hints(self, metrics: HealthMetrics, trends: Optional[List[HealthTrend]] = None) -> List[ProactiveHint]:
        """Generate actionable hints based on metrics and trends."""
        hints: List[ProactiveHint] = []
        thresholds = self.THRESHOLDS
        
        # 1. API Response Time Analysis
        if metrics.api_response_time_ms > thresholds["api_response_time_ms"]["critical"]:
            hints.append(ProactiveHint(
                severity="critical",
                category="performance",
                title="🚨 API Response Critical",
                message=f"API response time is {metrics.api_response_time_ms:.0f}ms (3x slower than optimal)",
                recommendation="Check Docker resource limits, possible memory leak, or container restart needed",
                metric_source="api_latency",
                threshold_exceeded=("api_response_time_ms", metrics.api_response_time_ms, thresholds["api_response_time_ms"]["critical"])
            ))
        elif metrics.api_response_time_ms > thresholds["api_response_time_ms"]["warning"]:
            hints.append(ProactiveHint(
                severity="warning",
                category="performance",
                title="⚠️ API Response Slow",
                message=f"API response time is {metrics.api_response_time_ms:.0f}ms (elevated)",
                recommendation="Monitor closely, check CPU/Memory usage, consider query optimization",
                metric_source="api_latency",
                threshold_exceeded=("api_response_time_ms", metrics.api_response_time_ms, thresholds["api_response_time_ms"]["warning"])
            ))
        
        # 2. Memory Usage Analysis
        if metrics.memory_usage_percent > thresholds["memory_percent"]["critical"]:
            hints.append(ProactiveHint(
                severity="critical",
                category="resources",
                title="💾 Memory Critical",
                message=f"Memory usage at {metrics.memory_usage_percent:.1f}% (near limit)",
                recommendation="URGENT: Check for memory leaks, restart container, or increase Docker memory limit",
                metric_source="system.memory",
                threshold_exceeded=("memory_percent", metrics.memory_usage_percent, thresholds["memory_percent"]["critical"])
            ))
        elif metrics.memory_usage_percent > thresholds["memory_percent"]["attention"]:
            hints.append(ProactiveHint(
                severity="warning",
                category="resources",
                title="💾 Memory Elevated",
                message=f"Memory usage at {metrics.memory_usage_percent:.1f}% (monitor)",
                recommendation="Check memory usage trend, consider cleaning cache or optimizing queries",
                metric_source="system.memory",
                threshold_exceeded=("memory_percent", metrics.memory_usage_percent, thresholds["memory_percent"]["attention"])
            ))
        
        # 3. Error Rate Analysis
        if metrics.error_rate_percent > thresholds["error_rate_percent"]["critical"]:
            hints.append(ProactiveHint(
                severity="critical",
                category="errors",
                title="🚨 Error Rate Critical",
                message=f"Error rate at {metrics.error_rate_percent:.2f}% ({int(metrics.requests_per_minute * metrics.error_rate_percent / 100)} errors/min)",
                recommendation="Check logs immediately, possible dependency failure or query pattern issue",
                metric_source="http.errors",
                threshold_exceeded=("error_rate_percent", metrics.error_rate_percent, thresholds["error_rate_percent"]["critical"])
            ))
        elif metrics.error_rate_percent > thresholds["error_rate_percent"]["warning"]:
            hints.append(ProactiveHint(
                severity="warning",
                category="errors",
                title="⚠️ Error Rate Elevated",
                message=f"Error rate at {metrics.error_rate_percent:.2f}% (above baseline)",
                recommendation="Review recent logs, check for pattern in failing queries",
                metric_source="http.errors",
                threshold_exceeded=("error_rate_percent", metrics.error_rate_percent, thresholds["error_rate_percent"]["warning"])
            ))
        
        # 4. Disk Usage Analysis
        if metrics.disk_usage_percent > thresholds["disk_percent"]["critical"]:
            hints.append(ProactiveHint(
                severity="critical",
                category="resources",
                title="💾 Disk Space Critical",
                message=f"Disk usage at {metrics.disk_usage_percent:.1f}% (running out of space)",
                recommendation="Delete old logs, archive data, or expand storage immediately",
                metric_source="disk.usage",
                threshold_exceeded=("disk_percent", metrics.disk_usage_percent, thresholds["disk_percent"]["critical"])
            ))
        elif metrics.disk_usage_percent > thresholds["disk_percent"]["attention"]:
            hints.append(ProactiveHint(
                severity="warning",
                category="resources",
                title="💾 Disk Space Elevated",
                message=f"Disk usage at {metrics.disk_usage_percent:.1f}%",
                recommendation="Monitor space usage, plan for storage cleanup or expansion",
                metric_source="disk.usage",
                threshold_exceeded=("disk_percent", metrics.disk_usage_percent, thresholds["disk_percent"]["attention"])
            ))
        
        # 5. Trend Analysis
        if trends:
            for trend in trends:
                if trend.metric_name == "api_response_time_ms" and trend.change_percent > 40:
                    hints.append(ProactiveHint(
                        severity="warning",
                        category="trends",
                        title="📈 API Performance Degrading",
                        message=f"API response time increased {trend.change_percent:.1f}% in last 24h (from {trend.avg_24h:.0f}ms to {trend.current:.0f}ms)",
                        recommendation="Investigate recent changes, check Prometheus for correlation with other metrics",
                        metric_source="trend.api_latency"
                    ))
                
                if trend.metric_name == "memory_percent" and trend.change_percent > 30:
                    hints.append(ProactiveHint(
                        severity="warning",
                        category="trends",
                        title="📈 Memory Growing",
                        message=f"Memory usage trending up {trend.change_percent:.1f}% (possible memory leak)",
                        recommendation="Check application logs for memory issues, consider container restart",
                        metric_source="trend.memory"
                    ))
                
                if trend.metric_name == "error_rate_percent" and trend.current > trend.avg_24h * 1.5:
                    hints.append(ProactiveHint(
                        severity="warning",
                        category="trends",
                        title="📈 Error Rate Spike",
                        message=f"Error rate spike: {trend.current:.2f}% (50% above 24h average of {trend.avg_24h:.2f}%)",
                        recommendation="Review recent changes, check external service dependencies",
                        metric_source="trend.errors"
                    ))
        
        # 6. Positive insights (for optimal status)
        if len(hints) == 0:
            hints.append(ProactiveHint(
                severity="info",
                category="trends",
                title="🚀 System Optimal",
                message="All metrics are within optimal ranges. Good time for maintenance or testing.",
                recommendation="Monitor continues as normal. Consider running self-optimization or performance tests.",
                metric_source="overall"
            ))
        
        return hints
    
    def collect_snapshot(self, additional_metrics: Optional[Dict[str, Any]] = None) -> HealthMetrics:
        """Collect current health metrics snapshot."""
        sys_metrics = self.get_system_metrics()
        
        snapshot = HealthMetrics(
            timestamp=datetime.now().isoformat(),
            api_response_time_ms=self.estimate_api_response_time(additional_metrics),
            memory_usage_percent=sys_metrics.get("memory_percent", 0),
            cpu_usage_percent=sys_metrics.get("cpu_percent", 0),
            disk_usage_percent=sys_metrics.get("disk_percent", 0),
            error_rate_percent=additional_metrics.get("error_rate_percent", 0) if additional_metrics else 0,
            active_sessions=additional_metrics.get("active_sessions", 0) if additional_metrics else 0,
            requests_per_minute=additional_metrics.get("requests_per_minute", 0) if additional_metrics else 0,
            containers_healthy=self.get_container_health().get("healthy", 0),
            containers_total=self.get_container_health().get("total", 0),
        )
        
        self.metrics_history.append(snapshot)
        
        # Keep only last 24 hours (assuming 5-minute intervals = 288 samples)
        if len(self.metrics_history) > 288:
            self.metrics_history = self.metrics_history[-288:]
        
        self.last_update = datetime.now()
        return snapshot
    
    def calculate_trend(self, metric_name: str) -> Optional[HealthTrend]:
        """Calculate 24-hour trend for a metric."""
        if len(self.metrics_history) < 2:
            return None
        
        values = []
        for metrics in self.metrics_history:
            if metric_name == "api_response_time_ms":
                values.append(metrics.api_response_time_ms)
            elif metric_name == "memory_percent":
                values.append(metrics.memory_usage_percent)
            elif metric_name == "cpu_percent":
                values.append(metrics.cpu_usage_percent)
            elif metric_name == "error_rate_percent":
                values.append(metrics.error_rate_percent)
            elif metric_name == "requests_per_minute":
                values.append(metrics.requests_per_minute)
        
        if not values or len(values) < 2:
            return None
        
        current = values[-1]
        avg_24h = sum(values) / len(values)
        max_24h = max(values)
        min_24h = min(values)
        
        # Calculate trend direction
        if len(values) >= 10:
            recent_avg = sum(values[-10:]) / 10
            older_avg = sum(values[:-10]) / 10
            change_percent = ((recent_avg - older_avg) / max(older_avg, 1)) * 100
        else:
            change_percent = ((current - avg_24h) / max(avg_24h, 1)) * 100
        
        if change_percent > 5:
            trend = "↑"
        elif change_percent < -5:
            trend = "↓"
        else:
            trend = "→"
        
        return HealthTrend(
            metric_name=metric_name,
            current=current,
            avg_24h=avg_24h,
            max_24h=max_24h,
            min_24h=min_24h,
            trend=trend,
            change_percent=abs(change_percent)
        )
    
    def get_full_health_report(self, additional_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate comprehensive health report."""
        metrics = self.collect_snapshot(additional_metrics)
        status = self.evaluate_health_status(metrics)
        
        trends = []
        for metric in ["api_response_time_ms", "memory_percent", "cpu_percent", "error_rate_percent"]:
            trend = self.calculate_trend(metric)
            if trend:
                trends.append(trend)
        
        hints = self.generate_proactive_hints(metrics, trends)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": status.value,
            "metrics": metrics.to_dict(),
            "trends": [t.to_dict() for t in trends],
            "proactive_hints": [h.to_dict() for h in hints],
            "system": self.get_system_metrics(),
            "process": self.get_process_metrics(),
            "containers": self.get_container_health(),
            "uptime_hours": (datetime.now() - datetime.fromtimestamp(time.time() - os.getloadavg()[0] * 3600)).total_seconds() / 3600,
        }


# Singleton instance
_health_insights: Optional[HealthInsights] = None


def get_health_insights() -> HealthInsights:
    """Get or create singleton health insights instance."""
    global _health_insights
    if _health_insights is None:
        _health_insights = HealthInsights()
    return _health_insights
