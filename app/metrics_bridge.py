"""
Jarvis Metrics Bridge (Pre/Post Measurement)

Purpose:
  Measure impact of code changes: baseline → deploy → measurement → delta
  
Flow:
  1. Record pre-deployment metrics (baseline)
  2. Wait for change to execute/stabilize
  3. Record post-deployment metrics
  4. Calculate delta (improvement or regression)
  5. Return impact assessment
  
Impact Metrics (from Phase B):
  - embedding_quality_p95: Relevance (higher = better)
  - search_latency_p95: Speed (lower = better)
  - tokens_per_query_mean: Token efficiency (lower = better)

References:
  - Phase B preflight validation (Gates 3-6)
  - AUTONOMOUS_WRITE_SAFETY_BASELINE.md (Measurement requirements)
  - JARVIS_IMPLEMENTATION_ROADMAP_FEB4.md (Feedback loop)
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
import logging
import asyncio

logger = logging.getLogger("jarvis.metrics_bridge")


class JarvisMetricsBridge:
    """
    Measure pre/post impact of code changes.
    
    Integrates with Prometheus to track:
    - Embedding quality (relevance)
    - Search latency (performance)
    - Token usage (efficiency)
    """
    
    def __init__(self, prometheus_client=None, phase_b_queries: Optional[Dict] = None):
        """
        Args:
            prometheus_client: Prometheus HTTP client
            phase_b_queries: Baseline queries for measurement
                {
                    "embedding_quality_p95": "histogram_quantile(0.95, embedding_quality_bucket)",
                    "search_latency_p95": "histogram_quantile(0.95, search_latency_bucket)",
                    "tokens_per_query_mean": "rate(total_tokens[5m]) / rate(queries[5m])"
                }
        """
        self.prometheus_client = prometheus_client
        
        # Default Phase B metric queries
        self.queries = phase_b_queries or {
            "embedding_quality_p95": "histogram_quantile(0.95, embedding_quality_bucket)",
            "search_latency_p95": "histogram_quantile(0.95, search_latency_bucket)",
            "tokens_per_query_mean": "rate(total_tokens_sum[5m]) / rate(total_tokens_count[5m])"
        }
        
        self.logger = logger
    
    async def measure_change_impact(
        self,
        change,
        duration_sec: int = 300,
        stabilization_delay: int = 30
    ) -> Dict[str, float]:
        """
        Measure full pre/post impact of a code change.
        
        Args:
            change: CodeChange object
            duration_sec: How long to measure after deployment (default 5 min)
            stabilization_delay: Wait before measuring (default 30 sec)
        
        Returns:
            {
                "embedding_quality_delta": 0.05,  # +5% improvement
                "search_latency_delta": -12.3,    # -12.3ms faster
                "tokens_delta": -0.08,            # -8% tokens
                "success": True,
                "measurement_time": "2026-02-04T10:30:00Z"
            }
        """
        
        try:
            self.logger.info(
                "Starting impact measurement",
                extra={"change_id": change.id, "duration_sec": duration_sec}
            )
            
            # Step 1: Record baseline (BEFORE)
            baseline = await self._query_metrics(window="5m")
            
            if not baseline:
                self.logger.error("Failed to capture baseline metrics")
                return {"success": False, "error": "Baseline capture failed"}
            
            self.logger.info(
                "Baseline metrics captured",
                extra={"baseline": baseline}
            )
            
            # Step 2: Wait for stabilization
            self.logger.info(f"Waiting {stabilization_delay}s for stabilization...")
            await asyncio.sleep(stabilization_delay)
            
            # Step 3: Record post-deployment (AFTER)
            # Note: caller will execute change between baseline and this call
            # So we measure starting now
            post_metrics = await self._query_metrics(window="5m")
            
            if not post_metrics:
                self.logger.error("Failed to capture post-deployment metrics")
                return {"success": False, "error": "Post-deployment capture failed"}
            
            self.logger.info(
                "Post-deployment metrics captured",
                extra={"post": post_metrics}
            )
            
            # Step 4: Calculate deltas
            impact = self._calculate_impact(baseline, post_metrics)
            
            self.logger.info(
                "Impact calculated",
                extra={
                    "embedding_quality_delta": impact.get("embedding_quality_delta"),
                    "search_latency_delta": impact.get("search_latency_delta"),
                    "tokens_delta": impact.get("tokens_delta")
                }
            )
            
            return impact
        
        except Exception as e:
            self.logger.error(
                f"Error measuring impact: {e}",
                extra={"change_id": change.id, "error": str(e)}
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _query_metrics(self, window: str = "5m") -> Optional[Dict[str, float]]:
        """
        Query Prometheus for baseline metrics.
        
        Args:
            window: Time window for averaging (e.g., "5m", "10m")
        
        Returns:
            {
                "embedding_quality_p95": 0.82,
                "search_latency_p95": 245.6,
                "tokens_per_query_mean": 1.43
            }
        """
        
        if not self.prometheus_client:
            self.logger.warning("No Prometheus client configured, returning mock data")
            return self._get_mock_metrics()
        
        try:
            metrics = {}
            
            for metric_name, query in self.queries.items():
                try:
                    result = await self.prometheus_client.query_range(
                        query,
                        start_time=datetime.utcnow() - timedelta(minutes=10),
                        end_time=datetime.utcnow(),
                        step="1m"
                    )
                    
                    # Extract value (last point in range)
                    if result and len(result) > 0:
                        # Prometheus returns list of (timestamp, value) tuples
                        latest_value = result[-1][1]
                        metrics[metric_name] = float(latest_value)
                    else:
                        self.logger.warning(f"No data for {metric_name}")
                        metrics[metric_name] = None
                
                except Exception as e:
                    self.logger.error(
                        f"Error querying {metric_name}: {e}",
                        extra={"metric": metric_name}
                    )
                    metrics[metric_name] = None
            
            return metrics if any(v is not None for v in metrics.values()) else None
        
        except Exception as e:
            self.logger.error(f"Error querying metrics: {e}")
            return None
    
    def _calculate_impact(
        self,
        baseline: Dict[str, float],
        post: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Calculate deltas between baseline and post-deployment.
        
        Note: 
          - embedding_quality: higher = better (positive delta = improvement)
          - search_latency: lower = better (negative delta = improvement)
          - tokens: lower = better (negative delta = improvement)
        """
        
        impact = {
            "measurement_time": datetime.utcnow().isoformat() + "Z",
            "success": True
        }
        
        # Embedding quality delta (positive = improvement)
        if baseline.get("embedding_quality_p95") and post.get("embedding_quality_p95"):
            delta = post["embedding_quality_p95"] - baseline["embedding_quality_p95"]
            impact["embedding_quality_delta"] = round(delta, 4)
            
            # Relative improvement (%)
            if baseline["embedding_quality_p95"] > 0:
                pct = (delta / baseline["embedding_quality_p95"]) * 100
                impact["embedding_quality_pct"] = round(pct, 2)
        
        # Search latency delta (negative = improvement)
        if baseline.get("search_latency_p95") and post.get("search_latency_p95"):
            delta = post["search_latency_p95"] - baseline["search_latency_p95"]
            impact["search_latency_delta"] = round(delta, 2)  # ms
            
            # Relative improvement (%)
            if baseline["search_latency_p95"] > 0:
                pct = (delta / baseline["search_latency_p95"]) * 100
                impact["search_latency_pct"] = round(pct, 2)
        
        # Tokens per query delta (negative = improvement)
        if baseline.get("tokens_per_query_mean") and post.get("tokens_per_query_mean"):
            delta = post["tokens_per_query_mean"] - baseline["tokens_per_query_mean"]
            impact["tokens_delta"] = round(delta, 4)
            
            # Relative improvement (%)
            if baseline["tokens_per_query_mean"] > 0:
                pct = (delta / baseline["tokens_per_query_mean"]) * 100
                impact["tokens_pct"] = round(pct, 2)
        
        return impact
    
    def _get_mock_metrics(self) -> Dict[str, float]:
        """
        Return mock metrics for testing (when Prometheus not available).
        
        Used in Phase 0 for development/testing.
        """
        
        import random
        
        return {
            "embedding_quality_p95": 0.75 + random.uniform(0, 0.15),
            "search_latency_p95": 240.0 + random.uniform(-20, 20),
            "tokens_per_query_mean": 1.40 + random.uniform(-0.1, 0.1)
        }
    
    def evaluate_impact_quality(self, impact: Dict[str, float]) -> Dict[str, any]:
        """
        Evaluate whether impact is positive, negative, or neutral.
        
        Returns:
            {
                "overall_quality": "positive",  # positive, neutral, negative
                "relevance_quality": "positive",
                "performance_quality": "neutral",
                "efficiency_quality": "positive",
                "recommendation": "Strong improvement overall. Relevant, though latency unchanged."
            }
        """
        
        if not impact.get("success"):
            return {
                "overall_quality": "unknown",
                "error": impact.get("error", "Unknown error")
            }
        
        scores = {}
        
        # Relevance: positive if delta > 0.02 (2% improvement)
        rel_delta = impact.get("embedding_quality_pct", 0)
        if rel_delta > 2:
            scores["relevance"] = "positive"
        elif rel_delta < -2:
            scores["relevance"] = "negative"
        else:
            scores["relevance"] = "neutral"
        
        # Performance: positive if delta < -5 (5ms faster)
        perf_delta = impact.get("search_latency_delta", 0)
        if perf_delta < -5:
            scores["performance"] = "positive"
        elif perf_delta > 5:
            scores["performance"] = "negative"
        else:
            scores["performance"] = "neutral"
        
        # Efficiency: positive if delta < -5 (5% less tokens)
        eff_delta = impact.get("tokens_pct", 0)
        if eff_delta < -5:
            scores["efficiency"] = "positive"
        elif eff_delta > 5:
            scores["efficiency"] = "negative"
        else:
            scores["efficiency"] = "neutral"
        
        # Overall: positive if 2+ are positive, negative if 2+ are negative
        positive_count = sum(1 for v in scores.values() if v == "positive")
        negative_count = sum(1 for v in scores.values() if v == "negative")
        
        if positive_count >= 2:
            overall = "positive"
        elif negative_count >= 2:
            overall = "negative"
        else:
            overall = "neutral"
        
        return {
            "overall_quality": overall,
            "relevance_quality": scores["relevance"],
            "performance_quality": scores["performance"],
            "efficiency_quality": scores["efficiency"],
            "scores": scores
        }
