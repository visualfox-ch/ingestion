"""
Baseline Recorder for Self-Optimization

Records baseline metrics for Statistical Process Control (SPC) anomaly detection.
Establishes control limits using 3-sigma rule for automated rollback decisions.

Research Foundation:
- Page, E.S. (1954). "Continuous Inspection Schemes." Biometrika 41(1):100-115.
- Sculley, D. et al. (2015). "Hidden Technical Debt in ML Systems." NIPS 2015.

Author: GitHub Copilot
Created: 2026-02-03
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import numpy as np
import requests

from .observability import get_logger

logger = get_logger("jarvis.baseline_recorder")

# State file location
BASELINE_FILE = Path("/brain/system/state/metrics_baseline.json")


class BaselineRecorder:
    """
    Records baseline metrics for anomaly detection.
    
    Uses Statistical Process Control (SPC) to establish:
    - Mean (central tendency)
    - Standard Deviation (variability)
    - Upper Control Limit (UCL = mean + 3*std)
    - Lower Control Limit (LCL = max(0, mean - 3*std))
    
    3-sigma rule: 99.7% of normal data falls within ±3 std deviations.
    Values outside this range are anomalies.
    """
    
    def __init__(self, prometheus_url: str = "http://localhost:9090"):
        """
        Initialize baseline recorder.
        
        Args:
            prometheus_url: Prometheus server URL for metric queries
        """
        env_url = os.getenv("JARVIS_PROMETHEUS_URL")
        nas_ip = os.getenv("NAS_IP")
        if env_url:
            self.prometheus_url = env_url
        elif nas_ip:
            self.prometheus_url = f"http://{nas_ip}:19090"
        else:
            self.prometheus_url = prometheus_url
        
    def _query_prometheus(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime,
        step: str = "5m"
    ) -> List[float]:
        """
        Query Prometheus for metric values over time range.
        
        Args:
            query: PromQL query string
            start_time: Range start
            end_time: Range end
            step: Query resolution (default 5min)
            
        Returns:
            List of metric values (floats)
        """
        try:
            url = f"{self.prometheus_url}/api/v1/query_range"
            params = {
                "query": query,
                "start": start_time.timestamp(),
                "end": end_time.timestamp(),
                "step": step
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data["status"] != "success":
                logger.error("Prometheus query failed (query=%s, status=%s)", query, data.get("status"))
                return []
            
            # Extract values from result
            result = data.get("data", {}).get("result", [])
            if not result:
                logger.warning("No data returned from Prometheus (query=%s)", query)
                return []
            
            # Flatten values from all series
            values = []
            for series in result:
                for timestamp, value in series.get("values", []):
                    try:
                        values.append(float(value))
                    except (ValueError, TypeError):
                        continue
            
            return values
            
        except Exception as e:
            logger.error("Failed to query Prometheus (query=%s): %s", query, e)
            return []
    
    def record_baseline(self, duration_days: int = 7) -> Dict[str, Any]:
        """
        Record baseline metrics over specified duration.
        
        Queries Prometheus for the last N days to establish statistical
        control limits for anomaly detection.
        
        Args:
            duration_days: Number of days to analyze (default 7)
            
        Returns:
            Baseline statistics dict with structure:
            {
                "recorded_at": "ISO timestamp",
                "duration_days": 7,
                "metrics": {
                    "metric_name": {
                        "mean": float,
                        "std": float,
                        "ucl": float,  # Upper Control Limit
                        "lcl": float,  # Lower Control Limit
                        "p50": float,  # Median
                        "p95": float,  # 95th percentile
                        "p99": float,  # 99th percentile
                        "sample_count": int
                    }
                }
            }
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=duration_days)
        
        logger.info(
            "Recording baseline (duration_days=%s, start=%s, end=%s)",
            duration_days,
            start_time.isoformat(),
            end_time.isoformat(),
        )
        
        # Define metrics to track (aligned with current Prometheus exports)
        metric_queries = {
            "db_pool_wait_time_p95_seconds": "jarvis_db_pool_wait_time_p95_seconds",
            "db_pool_wait_time_p99_seconds": "jarvis_db_pool_wait_time_p99_seconds",
            "db_pool_wait_time_avg_seconds": "jarvis_db_pool_wait_time_avg_seconds",
            "db_pool_in_use": "jarvis_db_pool_in_use",
            "rag_empty_rate": "jarvis_rag_empty_rate",
            "rag_search_rate": "rate(jarvis_rag_searches_total[5m])",
            "rag_empty_results_rate": "rate(jarvis_rag_empty_results_total[5m])",
            "tool_loops_rate": "rate(jarvis_tool_loops_total[5m])"
        }
        
        baseline = {
            "recorded_at": datetime.utcnow().isoformat(),
            "duration_days": duration_days,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "metrics": {}
        }
        
        # Query each metric and calculate statistics
        for metric_name, query in metric_queries.items():
            values = self._query_prometheus(query, start_time, end_time)
            
            if not values:
                logger.warning("No data for metric (%s)", metric_name)
                continue
            
            # Calculate statistics
            values_array = np.array(values)
            mean = float(np.mean(values_array))
            std = float(np.std(values_array))
            
            baseline["metrics"][metric_name] = {
                "mean": mean,
                "std": std,
                "ucl": mean + 3 * std,  # Upper Control Limit
                "lcl": max(0.0, mean - 3 * std),  # Lower Control Limit (non-negative)
                "p50": float(np.percentile(values_array, 50)),
                "p95": float(np.percentile(values_array, 95)),
                "p99": float(np.percentile(values_array, 99)),
                "sample_count": len(values)
            }
            
            logger.info(
                "Baseline calculated (metric=%s, mean=%s, std=%s, samples=%s)",
                metric_name,
                mean,
                std,
                len(values),
            )
        
        # Save baseline to file
        self.save_baseline(baseline)
        
        return baseline
    
    def save_baseline(self, baseline: Dict[str, Any]) -> None:
        """
        Save baseline to state file.
        
        Args:
            baseline: Baseline statistics dict
        """
        try:
            # Ensure directory exists
            BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Write baseline
            with open(BASELINE_FILE, "w") as f:
                json.dump(baseline, f, indent=2)
            
            logger.info("Baseline saved (path=%s)", str(BASELINE_FILE))
            
        except Exception as e:
            logger.error("Failed to save baseline (path=%s): %s", str(BASELINE_FILE), e)
            raise
    
    def load_baseline(self) -> Optional[Dict[str, Any]]:
        """
        Load baseline from state file.
        
        Returns:
            Baseline dict or None if file doesn't exist
        """
        try:
            if not BASELINE_FILE.exists():
                logger.warning("Baseline file not found (path=%s)", str(BASELINE_FILE))
                return None
            
            with open(BASELINE_FILE, "r") as f:
                baseline = json.load(f)
            
            logger.info("Baseline loaded (path=%s)", str(BASELINE_FILE))
            return baseline
            
        except Exception as e:
            logger.error("Failed to load baseline: %s", e)
            return None
    
    def get_baseline_age(self) -> Optional[timedelta]:
        """
        Get age of current baseline.
        
        Returns:
            Timedelta since baseline was recorded, or None if no baseline exists
        """
        baseline = self.load_baseline()
        if not baseline:
            return None
        
        try:
            recorded_at = datetime.fromisoformat(baseline["recorded_at"])
            return datetime.utcnow() - recorded_at
        except (KeyError, ValueError):
            return None
    
    def should_refresh_baseline(self, max_age_days: int = 30) -> bool:
        """
        Check if baseline should be refreshed.
        
        Baseline should be refreshed if:
        - No baseline exists
        - Baseline is older than max_age_days
        
        Args:
            max_age_days: Maximum age before refresh (default 30)
            
        Returns:
            True if refresh is needed
        """
        age = self.get_baseline_age()
        
        if age is None:
            logger.info("No baseline exists, refresh needed")
            return True
        
        needs_refresh = age.days >= max_age_days
        
        if needs_refresh:
            logger.info(
                "Baseline too old, refresh needed (age_days=%s, max_age_days=%s)",
                age.days,
                max_age_days,
            )
        
        return needs_refresh


# Singleton instance
_baseline_recorder: Optional[BaselineRecorder] = None


def get_baseline_recorder() -> BaselineRecorder:
    """Get singleton baseline recorder instance."""
    global _baseline_recorder
    if _baseline_recorder is None:
        _baseline_recorder = BaselineRecorder()
    return _baseline_recorder
