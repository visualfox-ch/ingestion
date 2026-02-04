"""
Jarvis Metrics Analyzer & Optimization Recommender
Phase 16.2: Intelligent Monitoring with Optimization Suggestions

Analyzes Prometheus metrics and generates actionable optimization recommendations.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import requests
from .observability import get_logger

logger = get_logger("jarvis.metrics_analyzer")


class SeverityLevel(str, Enum):
    """Recommendation severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CategoryType(str, Enum):
    """Optimization category types"""
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    RESOURCE = "resource"
    QUALITY = "quality"
    LEARNING = "learning"


@dataclass
class Recommendation:
    """Optimization recommendation from metrics analysis"""
    id: str
    timestamp: str
    category: CategoryType
    severity: SeverityLevel
    title: str
    description: str
    metric_name: str
    current_value: float
    threshold: float
    action: str
    impact: str
    effort: str  # "low", "medium", "high"


class MetricsAnalyzer:
    """Analyzes Prometheus metrics and generates optimization recommendations"""

    def __init__(self, prometheus_url: str = "http://localhost:19090"):
        self.prometheus_url = prometheus_url
        self.recommendations: List[Recommendation] = []

    async def query_metric(self, query: str, duration: str = "5m") -> Optional[Dict]:
        """Query Prometheus instant query"""
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {"query": query}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get("status") == "success" and data.get("data", {}).get("result"):
                result = data["data"]["result"][0]
                return {
                    "labels": result.get("metric", {}),
                    "value": float(result.get("value", [0, 0])[1])
                }
            return None
        except Exception as e:
            logger.error(f"Prometheus query failed: {e}")
            return None

    async def query_range_metric(self, query: str, duration: str = "1h") -> Optional[List]:
        """Query Prometheus range query"""
        try:
            url = f"{self.prometheus_url}/api/v1/query_range"
            
            # Calculate time range
            end = datetime.utcnow()
            if duration == "1h":
                start = end - timedelta(hours=1)
            elif duration == "24h":
                start = end - timedelta(hours=24)
            else:
                start = end - timedelta(hours=1)
            
            params = {
                "query": query,
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "step": "5m"
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("status") == "success" and data.get("data", {}).get("result"):
                return data["data"]["result"]
            return None
        except Exception as e:
            logger.error(f"Prometheus range query failed: {e}")
            return None

    async def analyze_latency(self) -> List[Recommendation]:
        """Analyze request latency metrics"""
        recommendations = []
        
        # Check P99 latency
        p99_query = 'histogram_quantile(0.99, sum(rate(jarvis_request_duration_seconds_bucket[5m])) by (le, endpoint))'
        result = await self.query_metric(p99_query)
        
        if result:
            p99_value = result["value"]
            endpoint = result["labels"].get("endpoint", "unknown")
            
            # P99 threshold: 2.5s
            if p99_value > 2.5:
                recommendations.append(Recommendation(
                    id=f"latency_p99_{endpoint.replace('/', '_')}",
                    timestamp=datetime.utcnow().isoformat(),
                    category=CategoryType.PERFORMANCE,
                    severity=SeverityLevel.CRITICAL,
                    title=f"High P99 Latency on {endpoint}",
                    description=f"P99 latency is {p99_value:.2f}s, exceeding SLO of 2.5s",
                    metric_name="jarvis_request_duration_seconds",
                    current_value=p99_value,
                    threshold=2.5,
                    action=(
                        "1. Check database query performance (slow queries in logs)\n"
                        "2. Profile vector search latency (Qdrant)\n"
                        "3. Review LLM API timeout settings\n"
                        "4. Consider caching for frequently accessed data"
                    ),
                    impact="Users experience slow responses, affecting adoption",
                    effort="medium"
                ))
            
            # P95 warning
            p95_query = 'histogram_quantile(0.95, sum(rate(jarvis_request_duration_seconds_bucket[5m])) by (le, endpoint))'
            p95_result = await self.query_metric(p95_query)
            if p95_result and p95_result["value"] > 1.2:
                recommendations.append(Recommendation(
                    id=f"latency_p95_{endpoint.replace('/', '_')}",
                    timestamp=datetime.utcnow().isoformat(),
                    category=CategoryType.PERFORMANCE,
                    severity=SeverityLevel.WARNING,
                    title=f"Elevated P95 Latency on {endpoint}",
                    description=f"P95 latency is {p95_result['value']:.2f}s, SLO target 1.0s",
                    metric_name="jarvis_request_duration_seconds",
                    current_value=p95_result["value"],
                    threshold=1.0,
                    action=(
                        "1. Monitor trend over next 24h\n"
                        "2. Check if correlated with data growth\n"
                        "3. Consider async processing for heavy operations\n"
                        "4. Optimize embedding generation pipeline"
                    ),
                    impact="Gradual performance degradation",
                    effort="low"
                ))
        
        return recommendations

    async def analyze_reliability(self) -> List[Recommendation]:
        """Analyze error rates and reliability metrics"""
        recommendations = []
        
        # Check 5xx error rate
        error_rate_query = '100 * (sum(rate(jarvis_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(jarvis_requests_total[5m])), 1e-9))'
        result = await self.query_metric(error_rate_query)
        
        if result:
            error_rate = result["value"]
            
            # 5xx threshold: 1%
            if error_rate > 1.0:
                recommendations.append(Recommendation(
                    id="error_rate_high",
                    timestamp=datetime.utcnow().isoformat(),
                    category=CategoryType.RELIABILITY,
                    severity=SeverityLevel.CRITICAL if error_rate > 5 else SeverityLevel.WARNING,
                    title="High Server Error Rate",
                    description=f"5xx error rate is {error_rate:.2f}%, SLO target < 1%",
                    metric_name="jarvis_requests_total",
                    current_value=error_rate,
                    threshold=1.0,
                    action=(
                        "1. Check error logs: `{job=\"containerlogs\"} |~ \"(?i)error\"`\n"
                        "2. Review dependency health (Qdrant, n8n, Meilisearch)\n"
                        "3. Check database connection pool exhaustion\n"
                        "4. Review API rate limits and circuit breakers"
                    ),
                    impact="Users cannot complete tasks, churn risk",
                    effort="high"
                ))
        
        return recommendations

    async def analyze_resources(self) -> List[Recommendation]:
        """Analyze resource utilization metrics"""
        recommendations = []
        
        # Check memory usage
        memory_query = 'process_resident_memory_bytes{job="jarvis-api"}'
        result = await self.query_metric(memory_query)
        
        if result:
            memory_bytes = result["value"]
            memory_mb = memory_bytes / 1024 / 1024
            
            # Warning at 500MB
            if memory_bytes > 500_000_000:
                recommendations.append(Recommendation(
                    id="memory_high",
                    timestamp=datetime.utcnow().isoformat(),
                    category=CategoryType.RESOURCE,
                    severity=SeverityLevel.WARNING,
                    title="High Memory Usage Detected",
                    description=f"API memory is {memory_mb:.0f}MB, threshold 500MB",
                    metric_name="process_resident_memory_bytes",
                    current_value=memory_bytes,
                    threshold=500_000_000,
                    action=(
                        "1. Profile memory leaks: check for unbounded collections\n"
                        "2. Verify embedding cache eviction (check memory_store.py)\n"
                        "3. Consider pagination limits for fact retrieval\n"
                        "4. Review n8n workflow memory usage in conversation context"
                    ),
                    impact="Pod eviction, service restarts, user disruption",
                    effort="medium"
                ))
        
        return recommendations

    async def analyze_quality(self) -> List[Recommendation]:
        """Analyze preference learning and quality metrics"""
        recommendations = []
        
        # Check preference confidence
        confidence_query = 'jarvis_preference_confidence_avg'
        result = await self.query_metric(confidence_query)
        
        if result:
            confidence = result["value"]
            
            # Low confidence during learning phase
            if confidence < 0.5:
                recommendations.append(Recommendation(
                    id="confidence_low",
                    timestamp=datetime.utcnow().isoformat(),
                    category=CategoryType.QUALITY,
                    severity=SeverityLevel.INFO,
                    title="Low Preference Confidence (Learning Phase)",
                    description=f"Average confidence is {confidence:.2%}, still building user profiles",
                    metric_name="jarvis_preference_confidence_avg",
                    current_value=confidence,
                    threshold=0.5,
                    action=(
                        "1. Normal during Phase 17.2 preference learning\n"
                        "2. Track confidence growth over time\n"
                        "3. Ensure users complete preference surveys\n"
                        "4. Monitor anomaly detection for learning issues"
                    ),
                    impact="Recommendations less personalized until confidence improves",
                    effort="low"
                ))
        
        # Check anomalies
        anomaly_query = 'sum(jarvis_anomalies_detected_total)'
        result = await self.query_metric(anomaly_query)
        
        if result and result["value"] > 0:
            recommendations.append(Recommendation(
                id="anomalies_detected",
                timestamp=datetime.utcnow().isoformat(),
                category=CategoryType.QUALITY,
                severity=SeverityLevel.WARNING,
                title="Anomalies Detected in User Behavior",
                description=f"Detected {int(result['value'])} anomalies - may indicate data quality issues",
                metric_name="jarvis_anomalies_detected_total",
                current_value=result["value"],
                threshold=0,
                action=(
                    "1. Review anomaly dashboard for severity breakdown\n"
                    "2. Check domain_separation logic for classification errors\n"
                    "3. Verify user input validation in coaching_domains\n"
                    "4. Consider retraining anomaly detector on new patterns"
                ),
                impact="Risk of incorrect coaching recommendations",
                effort="medium"
            ))
        
        return recommendations

    async def analyze_learning_curve(self) -> List[Recommendation]:
        """Analyze learning metrics over time"""
        recommendations = []
        
        # Get confidence trend over 24h
        confidence_history = await self.query_range_metric('jarvis_preference_confidence_avg', duration='24h')
        
        if confidence_history and len(confidence_history) > 0:
            values = []
            for point in confidence_history[0].get("values", []):
                try:
                    values.append(float(point[1]))
                except (ValueError, IndexError):
                    continue
            
            if values:
                # Calculate trend
                early_avg = sum(values[:len(values)//2]) / (len(values)//2 + 1)
                recent_avg = sum(values[len(values)//2:]) / (len(values) - len(values)//2 + 1)
                trend_pct = ((recent_avg - early_avg) / (early_avg + 0.001)) * 100
                
                if trend_pct < 0:
                    # Confidence declining
                    recommendations.append(Recommendation(
                        id="confidence_declining",
                        timestamp=datetime.utcnow().isoformat(),
                        category=CategoryType.LEARNING,
                        severity=SeverityLevel.WARNING,
                        title="Preference Confidence Declining",
                        description=f"Confidence declined {abs(trend_pct):.1f}% over 24h",
                        metric_name="jarvis_preference_confidence_avg",
                        current_value=recent_avg,
                        threshold=early_avg,
                        action=(
                            "1. Check if user preferences actually changed\n"
                            "2. Review cross_domain_learner for conflicting patterns\n"
                            "3. Verify async_coach is updating profiles correctly\n"
                            "4. Consider rebalancing confidence weighting in preference model"
                        ),
                        impact="Recommendations becoming less relevant",
                        effort="medium"
                    ))
        
        return recommendations

    async def analyze_all(self) -> List[Recommendation]:
        """Run all analysis and return consolidated recommendations"""
        try:
            logger.info("Starting comprehensive metrics analysis...")
            
            # Run all analyses in parallel
            results = await asyncio.gather(
                self.analyze_latency(),
                self.analyze_reliability(),
                self.analyze_resources(),
                self.analyze_quality(),
                self.analyze_learning_curve(),
                return_exceptions=True
            )
            
            # Flatten results
            all_recommendations = []
            for result in results:
                if isinstance(result, list):
                    all_recommendations.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Analysis failed: {result}")
            
            self.recommendations = all_recommendations
            logger.info(f"Analysis complete: {len(all_recommendations)} recommendations")
            
            return all_recommendations
        
        except Exception as e:
            logger.error(f"Comprehensive analysis failed: {e}")
            return []

    def get_recommendations_by_severity(self, severity: SeverityLevel) -> List[Recommendation]:
        """Filter recommendations by severity level"""
        return [r for r in self.recommendations if r.severity == severity]

    def get_recommendations_by_category(self, category: CategoryType) -> List[Recommendation]:
        """Filter recommendations by category"""
        return [r for r in self.recommendations if r.category == category]

    def to_json(self) -> str:
        """Export recommendations as JSON"""
        return json.dumps(
            [asdict(r) for r in self.recommendations],
            indent=2
        )


# Singleton instance
_analyzer_instance: Optional[MetricsAnalyzer] = None


def get_metrics_analyzer() -> MetricsAnalyzer:
    """Get or create metrics analyzer instance"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = MetricsAnalyzer()
    return _analyzer_instance
