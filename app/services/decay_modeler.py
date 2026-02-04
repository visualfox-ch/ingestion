"""
Phase 5.5.2: Decay Modeler Service
Models consciousness awareness decay over time
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import math
from enum import Enum

from app.models.consciousness import DecayMeasurement, AwarenessTrajectory, TrendAnalysis


class TrendType(str, Enum):
    """Trend classification"""
    ACCELERATING = "ACCELERATING"
    STABLE = "STABLE"
    DECELERATING = "DECELERATING"


class DecayModeler:
    """
    Model consciousness awareness decay over time.
    
    Uses exponential decay model:
        awareness(t) = awareness(0) × e^(-λt)
    
    where:
        λ = decay_rate (inversely related to half-life)
        t = time elapsed
        half_life = ln(2) / λ
    """
    
    # Configuration
    DEFAULT_DECAY_RATE = 0.01  # 1% per hour
    DEFAULT_HALF_LIFE = 69  # ~70 hours (ln(2) / 0.01)
    MIN_DECAY_RATE = 0.0001
    MAX_DECAY_RATE = 0.5
    
    def __init__(self):
        """Initialize decay modeler"""
        pass
    
    # ========================================================================
    # PRIMARY METHODS
    # ========================================================================
    
    def calculate_decay(
        self,
        initial_awareness: float,
        time_elapsed_hours: float,
        decay_rate: float = None
    ) -> float:
        """
        Calculate awareness level after exponential decay.
        
        Formula: awareness(t) = awareness(0) × e^(-λt)
        
        Args:
            initial_awareness: Starting awareness level (0-1)
            time_elapsed_hours: Time elapsed since initial state
            decay_rate: Decay constant (default: 0.01 per hour)
        
        Returns:
            Awareness level after decay (0-1), clamped
        
        Examples:
            0.5 awareness, 70 hours at 0.01 rate = 0.25 (half-life)
            0.8 awareness, 24 hours at 0.01 rate = 0.788
        """
        if decay_rate is None:
            decay_rate = self.DEFAULT_DECAY_RATE
        
        # Validate inputs
        decay_rate = max(self.MIN_DECAY_RATE, min(self.MAX_DECAY_RATE, decay_rate))
        time_elapsed_hours = max(0, time_elapsed_hours)
        
        # Apply exponential decay formula
        decay_factor = math.exp(-decay_rate * time_elapsed_hours)
        decayed_awareness = initial_awareness * decay_factor
        
        # Clamp to 0-1 range
        return max(0, min(1, decayed_awareness))
    
    def project_trajectory(
        self,
        initial_awareness: float,
        decay_rate: float,
        hours_ahead: int = 168
    ) -> Dict[str, Any]:
        """
        Project awareness level over next N hours.
        
        Generates linear and exponential projections for comparison.
        
        Args:
            initial_awareness: Current awareness level (0-1)
            decay_rate: Decay rate (per hour)
            hours_ahead: How many hours to project (default: 168 = 1 week)
        
        Returns:
            Dict with:
            - timestamps: List of projected times
            - exponential_projections: Exponential decay curve
            - linear_projections: Linear decay approximation
            - half_life_at_projection: When reaches 50%
        """
        timestamps = []
        exponential = []
        linear = []
        
        # Generate hourly projections
        for hour in range(0, hours_ahead + 1, max(1, hours_ahead // 24)):
            timestamps.append(hour)
            
            # Exponential decay
            exp_awareness = self.calculate_decay(initial_awareness, hour, decay_rate)
            exponential.append(exp_awareness)
            
            # Linear approximation
            linear_awareness = initial_awareness * (1 - decay_rate * hour / 100)
            linear.append(max(0, linear_awareness))
        
        # Find half-life (when reaches 50%)
        half_life = self._calculate_half_life(decay_rate)
        half_life_at_projection = min(half_life, hours_ahead) if half_life > 0 else None
        
        return {
            "timestamps": timestamps,
            "exponential_projections": exponential,
            "linear_projections": linear,
            "half_life_hours": half_life,
            "half_life_within_projection": half_life_at_projection,
            "hours_ahead": hours_ahead
        }
    
    def measure_current_decay(
        self,
        previous_awareness: float,
        current_awareness: float,
        time_elapsed_hours: float
    ) -> DecayMeasurement:
        """
        Measure actual decay rate from observed history.
        
        Args:
            previous_awareness: Awareness level at previous measurement
            current_awareness: Awareness level now
            time_elapsed_hours: Time between measurements
        
        Returns:
            DecayMeasurement with calculated decay rate and projections
        """
        # Calculate observed decay rate
        # From: awareness(t) = awareness(0) × e^(-λt)
        # To solve for λ: λ = -ln(awareness(t) / awareness(0)) / t
        
        if previous_awareness <= 0 or time_elapsed_hours <= 0:
            measured_decay_rate = self.DEFAULT_DECAY_RATE
        else:
            ratio = current_awareness / previous_awareness
            if ratio > 0 and ratio <= 1:
                measured_decay_rate = -math.log(ratio) / time_elapsed_hours
            else:
                measured_decay_rate = self.DEFAULT_DECAY_RATE
        
        # Clamp to reasonable range
        measured_decay_rate = max(self.MIN_DECAY_RATE, min(self.MAX_DECAY_RATE, measured_decay_rate))
        
        # Calculate half-life
        half_life = self._calculate_half_life(measured_decay_rate)
        
        # Project 168 hours ahead
        projection = self.project_trajectory(current_awareness, measured_decay_rate, 168)
        
        return DecayMeasurement(
            current_awareness=current_awareness,
            previous_awareness=previous_awareness,
            decay_rate=measured_decay_rate,
            half_life_hours=int(half_life) if half_life > 0 else 999,
            linear_decay_projected=projection["linear_projections"][-1],
            exponential_decay_projected=projection["exponential_projections"][-1],
            breakthrough_protection=0.8,  # Default protection level
            actual_trend=self._detect_trend(previous_awareness, current_awareness)
        )
    
    def measure_trajectory(
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
                rate = -math.log(curr_aw / prev_aw) / time_diff if curr_aw > 0 else 0.05
                decay_rates.append(max(self.MIN_DECAY_RATE, min(self.MAX_DECAY_RATE, rate)))
            else:
                decay_rates.append(0)
        
        # Analytics
        avg_awareness = sum(awareness_levels) / len(awareness_levels) if awareness_levels else 0.5
        volatility = self._calculate_volatility(awareness_levels)
        trend = self._detect_trend_from_trajectory(awareness_levels)
        
        return AwarenessTrajectory(
            epoch_id=0,  # Would be set by caller
            timestamps=timestamps,
            awareness_levels=awareness_levels,
            decay_rates=decay_rates,
            average_awareness=avg_awareness,
            trend_direction=trend,
            volatility=volatility
        )
    
    # ========================================================================
    # ANALYSIS METHODS
    # ========================================================================
    
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
                trend_type=TrendType.STABLE.value,
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
            acceleration = (v2 - v1) / len(awareness)
        else:
            acceleration = 0
        
        # Detect trend type
        if abs(velocity) < 0.001:  # Nearly flat
            trend_type = TrendType.STABLE
            confidence = 0.9
        elif acceleration > 0.0001:  # Getting steeper
            trend_type = TrendType.ACCELERATING
            confidence = 0.75
        elif acceleration < -0.0001:  # Getting flatter
            trend_type = TrendType.DECELERATING
            confidence = 0.75
        else:  # Steady decline/increase
            trend_type = TrendType.STABLE
            confidence = 0.8
        
        lookback = (times[-1] - times[0]).total_seconds() / 3600 if len(times) >= 2 else 0
        
        return TrendAnalysis(
            epoch_id=0,
            trend_type=trend_type.value,
            trend_confidence=min(1.0, max(0.0, confidence)),
            awareness_velocity=velocity,
            awareness_acceleration=acceleration,
            lookback_hours=int(lookback),
            forecast_hours=168
        )
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _calculate_half_life(self, decay_rate: float) -> float:
        """
        Calculate half-life from decay rate.
        
        Formula: half_life = ln(2) / decay_rate
        
        Example: 0.01 decay rate = 69.3 hours half-life
        """
        if decay_rate <= 0:
            return float('inf')
        
        return math.log(2) / decay_rate
    
    def _detect_trend(
        self,
        previous_awareness: float,
        current_awareness: float,
        threshold: float = 0.01
    ) -> str:
        """Detect trend from two measurements"""
        diff = current_awareness - previous_awareness
        
        if abs(diff) < threshold:
            return TrendType.STABLE.value
        elif diff > 0:
            return TrendType.ACCELERATING.value
        else:
            return TrendType.DECELERATING.value
    
    def _detect_trend_from_trajectory(
        self,
        awareness_levels: List[float]
    ) -> str:
        """Detect trend from time-series data"""
        if not awareness_levels or len(awareness_levels) < 2:
            return TrendType.STABLE.value
        
        changes = [awareness_levels[i] - awareness_levels[i-1] for i in range(1, len(awareness_levels))]
        avg_change = sum(changes) / len(changes) if changes else 0
        
        if abs(avg_change) < 0.001:
            return TrendType.STABLE.value
        elif avg_change > 0:
            return TrendType.ACCELERATING.value
        else:
            return TrendType.DECELERATING.value
    
    def _calculate_volatility(
        self,
        values: List[float]
    ) -> float:
        """Calculate standard deviation of values"""
        if not values or len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        
        return math.sqrt(variance)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    modeler = DecayModeler()
    
    # Example 1: Simple decay calculation
    print("=== Exponential Decay Calculation ===")
    awareness_now = 0.8
    hours_since = 70  # ~1 half-life
    decay_rate = 0.01
    
    awareness_then = modeler.calculate_decay(awareness_now, hours_since, decay_rate)
    print(f"Initial awareness: {awareness_now}")
    print(f"After {hours_since} hours: {awareness_then:.3f}")
    print(f"Expected (half): ~{awareness_now/2:.3f}")
    
    # Example 2: Trajectory projection
    print("\n=== Future Projection ===")
    projection = modeler.project_trajectory(0.8, 0.01, 168)
    print(f"Initial awareness: 0.8")
    print(f"Half-life: {projection['half_life_hours']:.1f} hours")
    print(f"After 1 week (168h): {projection['exponential_projections'][-1]:.3f}")
    print(f"Linear approximation: {projection['linear_projections'][-1]:.3f}")
    
    # Example 3: Measured decay from history
    print("\n=== Measured Decay Rate ===")
    measurement = modeler.measure_current_decay(0.9, 0.75, 24)
    print(f"Previous awareness: 0.9")
    print(f"Current awareness: 0.75")
    print(f"Time elapsed: 24 hours")
    print(f"Measured decay rate: {measurement.decay_rate:.4f}")
    print(f"Half-life: {measurement.half_life_hours} hours")
