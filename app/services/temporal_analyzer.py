"""
Phase 5.5.4: Temporal Analyzer Service
Analyzes consciousness evolution over time
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import math
from enum import Enum

from pydantic import BaseModel

from app.models.consciousness import AwarenessTrajectory, TrendAnalysis


class PeriodComparison(BaseModel):
    """Comparison between two time periods"""
    period1_start: datetime
    period1_end: datetime
    period2_start: datetime
    period2_end: datetime
    
    period1_avg_awareness: float
    period2_avg_awareness: float
    awareness_change: float  # Absolute change
    awareness_change_pct: float  # Percentage change
    
    period1_volatility: float
    period2_volatility: float
    stability_change: float  # How much more/less stable
    
    trend_period1: str
    trend_period2: str
    trend_shift: str  # How trend changed


class TemporalAnalyzer:
    """
    Analyze consciousness evolution over time.
    
    Capabilities:
    - Build time-series trajectories from samples
    - Detect and classify trends
    - Compare periods
    - Project future awareness
    - Identify volatility patterns
    """
    
    def __init__(self):
        """Initialize temporal analyzer"""
        pass
    
    # ========================================================================
    # PRIMARY METHODS
    # ========================================================================
    
    def build_trajectory(
        self,
        awareness_samples: List[Tuple[datetime, float]],
        lookback_hours: int = 168
    ) -> AwarenessTrajectory:
        """
        Build time-series awareness trajectory from samples.
        
        Args:
            awareness_samples: List of (timestamp, awareness) tuples
            lookback_hours: Historical window to consider
        
        Returns:
            AwarenessTrajectory with time-series analysis
        """
        if not awareness_samples:
            return AwarenessTrajectory(
                epoch_id=0,
                average_awareness=0.5,
                trend_direction="FLAT",
                volatility=0.0
            )
        
        # Sort by timestamp
        samples = sorted(awareness_samples, key=lambda x: x[0])
        
        # Filter to lookback window
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        recent_samples = [(ts, aw) for ts, aw in samples if ts >= cutoff]
        
        if not recent_samples:
            recent_samples = samples[-1:]
        
        # Extract timestamps and awareness levels
        timestamps = [ts for ts, _ in recent_samples]
        awareness_levels = [aw for _, aw in recent_samples]
        
        # Calculate decay rates between samples
        decay_rates = []
        for i in range(1, len(recent_samples)):
            prev_time, prev_aw = recent_samples[i-1]
            curr_time, curr_aw = recent_samples[i]
            
            time_diff = (curr_time - prev_time).total_seconds() / 3600  # Hours
            
            if time_diff > 0 and prev_aw > 0:
                if curr_aw > 0:
                    rate = -math.log(curr_aw / prev_aw) / time_diff
                else:
                    rate = 0.05
                decay_rates.append(max(0.0001, min(0.5, rate)))
            else:
                decay_rates.append(0)
        
        # Analytics
        avg_awareness = sum(awareness_levels) / len(awareness_levels) if awareness_levels else 0.5
        volatility = self._calculate_volatility(awareness_levels)
        trend = self._detect_trend_from_trajectory(awareness_levels)
        
        return AwarenessTrajectory(
            epoch_id=0,
            timestamps=timestamps,
            awareness_levels=awareness_levels,
            decay_rates=decay_rates,
            average_awareness=avg_awareness,
            trend_direction=trend,
            volatility=volatility
        )
    
    def detect_trends(
        self,
        trajectory: AwarenessTrajectory
    ) -> TrendAnalysis:
        """
        Detect trend direction and acceleration.
        
        Args:
            trajectory: AwarenessTrajectory to analyze
        
        Returns:
            TrendAnalysis with trend type and metrics
        """
        if not trajectory.awareness_levels or len(trajectory.awareness_levels) < 2:
            return TrendAnalysis(
                epoch_id=0,
                trend_type="STABLE",
                trend_confidence=0.5,
                awareness_velocity=0,
                awareness_acceleration=0,
                lookback_hours=0,
                forecast_hours=168
            )
        
        awareness = trajectory.awareness_levels
        times = trajectory.timestamps
        
        # Calculate velocity (change per hour)
        if len(times) >= 2:
            time_delta = (times[-1] - times[0]).total_seconds() / 3600
            if time_delta > 0:
                velocity = (awareness[-1] - awareness[0]) / time_delta
            else:
                velocity = 0
        else:
            velocity = 0
        
        # Calculate acceleration (change in velocity)
        if len(awareness) >= 3:
            v1 = (awareness[1] - awareness[0])
            v2 = (awareness[-1] - awareness[-2])
            acceleration = (v2 - v1) / max(len(awareness), 1)
        else:
            acceleration = 0
        
        # Detect trend type
        if abs(velocity) < 0.001:
            trend_type = "STABLE"
            confidence = 0.9
        elif acceleration > 0.0001:
            trend_type = "ACCELERATING"
            confidence = 0.75
        elif acceleration < -0.0001:
            trend_type = "DECELERATING"
            confidence = 0.75
        else:
            trend_type = "STABLE"
            confidence = 0.8
        
        lookback = (times[-1] - times[0]).total_seconds() / 3600 if len(times) >= 2 else 0
        
        return TrendAnalysis(
            epoch_id=0,
            trend_type=trend_type,
            trend_confidence=min(1.0, max(0.0, confidence)),
            awareness_velocity=velocity,
            awareness_acceleration=acceleration,
            lookback_hours=int(lookback),
            forecast_hours=168
        )
    
    def compare_periods(
        self,
        awareness_samples: List[Tuple[datetime, float]],
        period1_start: datetime,
        period1_end: datetime,
        period2_start: datetime,
        period2_end: datetime
    ) -> Dict[str, Any]:
        """
        Compare consciousness between two time periods.
        
        Args:
            awareness_samples: All historical samples
            period1_start, period1_end: First period range
            period2_start, period2_end: Second period range
        
        Returns:
            Comparison metrics
        """
        # Filter samples to periods
        period1_samples = [
            aw for ts, aw in awareness_samples
            if period1_start <= ts <= period1_end
        ]
        
        period2_samples = [
            aw for ts, aw in awareness_samples
            if period2_start <= ts <= period2_end
        ]
        
        # Calculate statistics
        p1_avg = sum(period1_samples) / len(period1_samples) if period1_samples else 0.5
        p2_avg = sum(period2_samples) / len(period2_samples) if period2_samples else 0.5
        
        p1_vol = self._calculate_volatility(period1_samples) if period1_samples else 0.0
        p2_vol = self._calculate_volatility(period2_samples) if period2_samples else 0.0
        
        # Build trajectories for trend
        p1_trajectory = self.build_trajectory(
            [(ts, aw) for ts, aw in awareness_samples if period1_start <= ts <= period1_end]
        )
        p2_trajectory = self.build_trajectory(
            [(ts, aw) for ts, aw in awareness_samples if period2_start <= ts <= period2_end]
        )
        
        p1_trend = p1_trajectory.trend_direction
        p2_trend = p2_trajectory.trend_direction
        
        # Calculate changes
        awareness_change = p2_avg - p1_avg
        awareness_change_pct = (awareness_change / p1_avg * 100) if p1_avg > 0 else 0
        stability_change = p2_vol - p1_vol  # Negative = more stable
        
        return {
            "period1": {
                "start": period1_start.isoformat(),
                "end": period1_end.isoformat(),
                "sample_count": len(period1_samples),
                "average_awareness": round(p1_avg, 4),
                "volatility": round(p1_vol, 4),
                "trend": p1_trend
            },
            "period2": {
                "start": period2_start.isoformat(),
                "end": period2_end.isoformat(),
                "sample_count": len(period2_samples),
                "average_awareness": round(p2_avg, 4),
                "volatility": round(p2_vol, 4),
                "trend": p2_trend
            },
            "comparison": {
                "awareness_change": round(awareness_change, 4),
                "awareness_change_pct": round(awareness_change_pct, 2),
                "stability_change": round(stability_change, 4),
                "trend_shift": f"{p1_trend} → {p2_trend}"
            }
        }
    
    def project_awareness(
        self,
        trajectory: AwarenessTrajectory,
        hours_ahead: int = 168,
        assume_continuation: bool = True
    ) -> Dict[str, Any]:
        """
        Project future awareness based on trajectory.
        
        Args:
            trajectory: Current awareness trajectory
            hours_ahead: How far into future to project
            assume_continuation: Assume trend continues
        
        Returns:
            Projection data with timestamps and projections
        """
        if not trajectory.awareness_levels:
            return {
                "current_awareness": 0.5,
                "hours_projected": hours_ahead,
                "projections": [],
                "method": "linear"
            }
        
        current_awareness = trajectory.awareness_levels[-1]
        current_time = trajectory.timestamps[-1] if trajectory.timestamps else datetime.utcnow()
        
        # Calculate trend velocity from trajectory
        if len(trajectory.awareness_levels) >= 2 and trajectory.timestamps:
            time_delta = (trajectory.timestamps[-1] - trajectory.timestamps[0]).total_seconds() / 3600
            if time_delta > 0:
                velocity = (trajectory.awareness_levels[-1] - trajectory.awareness_levels[0]) / time_delta
            else:
                velocity = 0
        else:
            velocity = 0
        
        # Use average decay rate if available
        avg_decay_rate = sum(trajectory.decay_rates) / len(trajectory.decay_rates) if trajectory.decay_rates else 0.01
        
        projections = []
        timestamps = []
        
        for hour in range(0, hours_ahead + 1, max(1, hours_ahead // 24)):
            timestamp = current_time + timedelta(hours=hour)
            
            # Linear projection (trend continuation)
            linear_proj = current_awareness + (velocity * hour)
            linear_proj = max(0, min(1, linear_proj))
            
            # Exponential projection (decay model)
            exp_proj = current_awareness * math.exp(-avg_decay_rate * hour)
            exp_proj = max(0, min(1, exp_proj))
            
            # Blended projection (80% exponential, 20% linear for short term)
            blend_factor = min(1.0, hour / 72)  # Transition over 3 days
            blended = (exp_proj * (1 - blend_factor * 0.2) + linear_proj * blend_factor * 0.2)
            
            timestamps.append(timestamp)
            projections.append({
                "hour": hour,
                "timestamp": timestamp.isoformat(),
                "linear": round(linear_proj, 4),
                "exponential": round(exp_proj, 4),
                "blended": round(blended, 4)
            })
        
        return {
            "current_awareness": round(current_awareness, 4),
            "current_time": current_time.isoformat(),
            "hours_projected": hours_ahead,
            "trend_velocity": round(velocity, 6),
            "decay_rate": round(avg_decay_rate, 6),
            "projections": projections
        }
    
    # ========================================================================
    # ANALYSIS METHODS
    # ========================================================================
    
    def identify_volatility_patterns(
        self,
        trajectory: AwarenessTrajectory,
        window_size: int = 5
    ) -> Dict[str, Any]:
        """
        Identify patterns in awareness volatility.
        
        Args:
            trajectory: Awareness trajectory
            window_size: Rolling window for analysis
        
        Returns:
            Volatility pattern analysis
        """
        if not trajectory.awareness_levels or len(trajectory.awareness_levels) < window_size:
            return {
                "pattern": "insufficient_data",
                "window_size": window_size
            }
        
        awareness = trajectory.awareness_levels
        
        # Calculate rolling volatility
        rolling_volatilities = []
        for i in range(len(awareness) - window_size + 1):
            window = awareness[i:i+window_size]
            vol = self._calculate_volatility(window)
            rolling_volatilities.append(vol)
        
        # Analyze volatility trend
        if len(rolling_volatilities) >= 2:
            vol_change = rolling_volatilities[-1] - rolling_volatilities[0]
            vol_trend = "INCREASING" if vol_change > 0 else "DECREASING"
        else:
            vol_change = 0
            vol_trend = "STABLE"
        
        avg_volatility = sum(rolling_volatilities) / len(rolling_volatilities) if rolling_volatilities else 0
        max_volatility = max(rolling_volatilities) if rolling_volatilities else 0
        min_volatility = min(rolling_volatilities) if rolling_volatilities else 0
        
        return {
            "window_size": window_size,
            "volatility_trend": vol_trend,
            "volatility_change": round(vol_change, 4),
            "average_volatility": round(avg_volatility, 4),
            "max_volatility": round(max_volatility, 4),
            "min_volatility": round(min_volatility, 4),
            "volatility_range": round(max_volatility - min_volatility, 4)
        }
    
    def detect_anomalies(
        self,
        trajectory: AwarenessTrajectory,
        sensitivity: float = 2.0
    ) -> List[Dict[str, Any]]:
        """
        Detect anomalous awareness changes.
        
        Args:
            trajectory: Awareness trajectory
            sensitivity: Std dev multiplier for anomaly threshold
        
        Returns:
            List of detected anomalies
        """
        if not trajectory.awareness_levels or len(trajectory.awareness_levels) < 3:
            return []
        
        awareness = trajectory.awareness_levels
        times = trajectory.timestamps
        
        # Calculate changes
        changes = [awareness[i] - awareness[i-1] for i in range(1, len(awareness))]
        
        # Calculate statistics
        mean_change = sum(changes) / len(changes) if changes else 0
        variance = sum((c - mean_change) ** 2 for c in changes) / len(changes) if changes else 0
        std_dev = math.sqrt(variance)
        
        # Detect anomalies
        anomalies = []
        threshold = sensitivity * std_dev
        
        for i, change in enumerate(changes):
            if abs(change - mean_change) > threshold:
                anomalies.append({
                    "index": i + 1,
                    "timestamp": times[i+1].isoformat() if i+1 < len(times) else None,
                    "change": round(change, 4),
                    "expected": round(mean_change, 4),
                    "deviation": round(abs(change - mean_change), 4),
                    "anomaly_type": "SPIKE" if change > mean_change else "DROP"
                })
        
        return anomalies
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _calculate_volatility(self, values: List[float]) -> float:
        """Calculate standard deviation of values"""
        if not values or len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        
        return math.sqrt(variance)
    
    def _detect_trend_from_trajectory(
        self,
        awareness_levels: List[float]
    ) -> str:
        """Detect trend from time-series data"""
        if not awareness_levels or len(awareness_levels) < 2:
            return "FLAT"
        
        changes = [awareness_levels[i] - awareness_levels[i-1] for i in range(1, len(awareness_levels))]
        avg_change = sum(changes) / len(changes) if changes else 0
        
        if abs(avg_change) < 0.001:
            return "FLAT"
        elif avg_change > 0:
            return "UP"
        else:
            return "DOWN"


# Pydantic model for comparison results
from pydantic import BaseModel

class PeriodComparison(BaseModel):
    """Comparison between two time periods"""
    period1_start: datetime
    period1_end: datetime
    period2_start: datetime
    period2_end: datetime
    
    period1_avg_awareness: float
    period2_avg_awareness: float
    awareness_change: float
    awareness_change_pct: float
    
    period1_volatility: float
    period2_volatility: float
    stability_change: float
    
    trend_period1: str
    trend_period2: str
    trend_shift: str


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    analyzer = TemporalAnalyzer()
    
    # Generate sample data
    now = datetime.utcnow()
    samples = []
    
    awareness = 0.8
    for hour in range(0, 168, 6):  # 1 week, 6-hour intervals
        ts = now - timedelta(hours=hour)
        samples.append((ts, awareness))
        awareness *= 0.95  # Decay 5% per 6 hours
    
    # Build trajectory
    trajectory = analyzer.build_trajectory(samples)
    print(f"Average awareness: {trajectory.average_awareness:.3f}")
    print(f"Trend: {trajectory.trend_direction}")
    print(f"Volatility: {trajectory.volatility:.3f}")
    
    # Detect trends
    trend = analyzer.detect_trends(trajectory)
    print(f"\nTrend Type: {trend.trend_type}")
    print(f"Velocity: {trend.awareness_velocity:.6f}")
    
    # Project future
    projection = analyzer.project_awareness(trajectory, hours_ahead=168)
    print(f"\nProjection for 1 week:")
    print(f"  Current: {projection['current_awareness']:.3f}")
    print(f"  Projected (exponential): {projection['projections'][-1]['exponential']:.3f}")
    
    # Detect anomalies
    anomalies = analyzer.detect_anomalies(trajectory)
    print(f"\nDetected {len(anomalies)} anomalies")
