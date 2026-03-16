"""
ML Pattern Recognition Service (Tier 4 #14)

Advanced time-series analysis and pattern detection:
- Seasonal decomposition (daily, weekly patterns)
- Trend forecasting with confidence intervals
- Anomaly detection with auto-thresholds
- Multi-dimensional pattern correlation
- Predictive alerts for proactive action

Uses pure Python math when ML libraries unavailable,
with optional statsmodels/numpy for advanced analysis.
"""

import logging
import math
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, asdict

from ..postgres_state import get_cursor

logger = logging.getLogger(__name__)

# Try to import optional ML libraries
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    stats = None


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""
    timestamp: datetime
    value: float
    metadata: Optional[Dict] = None


@dataclass
class SeasonalPattern:
    """Detected seasonal pattern."""
    pattern_type: str  # hourly, daily, weekly
    period_hours: int
    amplitude: float  # strength of seasonality
    peak_time: str  # when the peak occurs
    trough_time: str  # when the trough occurs
    confidence: float


@dataclass
class Forecast:
    """Time series forecast."""
    horizon_hours: int
    predictions: List[Dict]  # [{timestamp, value, lower, upper}]
    method: str
    confidence_level: float


@dataclass
class PatternAlert:
    """Predictive alert based on pattern analysis."""
    alert_type: str
    severity: str  # low, medium, high, critical
    metric: str
    message: str
    predicted_at: datetime
    expected_when: datetime
    confidence: float
    recommendation: str


class MLPatternService:
    """
    Advanced ML-based pattern recognition.

    Capabilities:
    - Time-series decomposition (trend, seasonal, residual)
    - Multi-horizon forecasting
    - Automatic seasonality detection
    - Cross-metric correlation
    - Predictive alerting
    """

    def __init__(self):
        self._ensure_tables()
        self._cache = {}  # Simple in-memory cache

    def _ensure_tables(self):
        """Ensure ML pattern tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ml_time_series (
                        id SERIAL PRIMARY KEY,
                        metric_name VARCHAR(100) NOT NULL,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        value FLOAT NOT NULL,
                        dimensions JSONB DEFAULT '{}',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        UNIQUE(metric_name, timestamp, dimensions)
                    );

                    CREATE INDEX IF NOT EXISTS idx_ml_ts_metric_time
                        ON ml_time_series(metric_name, timestamp DESC);

                    CREATE TABLE IF NOT EXISTS ml_seasonal_patterns (
                        id SERIAL PRIMARY KEY,
                        metric_name VARCHAR(100) NOT NULL,
                        pattern_type VARCHAR(50) NOT NULL,
                        period_hours INTEGER NOT NULL,
                        amplitude FLOAT NOT NULL,
                        peak_time VARCHAR(20),
                        trough_time VARCHAR(20),
                        confidence FLOAT NOT NULL,
                        pattern_data JSONB NOT NULL,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        is_active BOOLEAN DEFAULT true,
                        UNIQUE(metric_name, pattern_type)
                    );

                    CREATE TABLE IF NOT EXISTS ml_forecasts (
                        id SERIAL PRIMARY KEY,
                        metric_name VARCHAR(100) NOT NULL,
                        forecast_horizon_hours INTEGER NOT NULL,
                        predictions JSONB NOT NULL,
                        method VARCHAR(50) NOT NULL,
                        confidence_level FLOAT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        expires_at TIMESTAMP WITH TIME ZONE
                    );

                    CREATE INDEX IF NOT EXISTS idx_ml_forecasts_metric
                        ON ml_forecasts(metric_name, created_at DESC);

                    CREATE TABLE IF NOT EXISTS ml_pattern_alerts (
                        id SERIAL PRIMARY KEY,
                        alert_type VARCHAR(50) NOT NULL,
                        severity VARCHAR(20) NOT NULL,
                        metric_name VARCHAR(100) NOT NULL,
                        message TEXT NOT NULL,
                        predicted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        expected_when TIMESTAMP WITH TIME ZONE,
                        confidence FLOAT NOT NULL,
                        recommendation TEXT,
                        is_acknowledged BOOLEAN DEFAULT false,
                        acknowledged_at TIMESTAMP WITH TIME ZONE,
                        outcome VARCHAR(50)  -- correct, false_positive, missed
                    );

                    CREATE INDEX IF NOT EXISTS idx_ml_alerts_severity
                        ON ml_pattern_alerts(severity, predicted_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_ml_alerts_unack
                        ON ml_pattern_alerts(is_acknowledged, predicted_at DESC);
                """)
        except Exception as e:
            logger.debug(f"ML pattern tables may exist: {e}")

    # =========================================================================
    # Time Series Recording
    # =========================================================================

    def record_metric(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime = None,
        dimensions: Dict = None
    ) -> bool:
        """
        Record a time series data point.

        Args:
            metric_name: Name of the metric (e.g., 'queries_per_hour')
            value: Numeric value
            timestamp: When (defaults to now)
            dimensions: Optional dimensions (e.g., {'source': 'telegram'})
        """
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO ml_time_series (metric_name, timestamp, value, dimensions)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (metric_name, timestamp, dimensions)
                    DO UPDATE SET value = EXCLUDED.value
                """, (
                    metric_name,
                    timestamp or datetime.utcnow(),
                    value,
                    json.dumps(dimensions or {})
                ))
            return True
        except Exception as e:
            logger.error(f"Record metric failed: {e}")
            return False

    def get_time_series(
        self,
        metric_name: str,
        hours: int = 168,
        dimensions: Dict = None
    ) -> List[TimeSeriesPoint]:
        """Get time series data for a metric."""
        try:
            with get_cursor() as cur:
                if dimensions:
                    cur.execute("""
                        SELECT timestamp, value, dimensions
                        FROM ml_time_series
                        WHERE metric_name = %s
                        AND timestamp > NOW() - make_interval(hours => %s)
                        AND dimensions @> %s
                        ORDER BY timestamp ASC
                    """, (metric_name, hours, json.dumps(dimensions)))
                else:
                    cur.execute("""
                        SELECT timestamp, value, dimensions
                        FROM ml_time_series
                        WHERE metric_name = %s
                        AND timestamp > NOW() - make_interval(hours => %s)
                        ORDER BY timestamp ASC
                    """, (metric_name, hours))

                return [
                    TimeSeriesPoint(
                        timestamp=row['timestamp'],
                        value=row['value'],
                        metadata=row['dimensions']
                    )
                    for row in cur.fetchall()
                ]
        except Exception as e:
            logger.error(f"Get time series failed: {e}")
            return []

    # =========================================================================
    # Seasonal Decomposition
    # =========================================================================

    def decompose_seasonal(
        self,
        metric_name: str,
        hours: int = 336  # 2 weeks
    ) -> Dict[str, Any]:
        """
        Decompose time series into trend, seasonal, and residual components.

        Detects hourly, daily, and weekly seasonality patterns.
        """
        try:
            series = self.get_time_series(metric_name, hours)
            if len(series) < 48:  # Need at least 2 days
                return {"success": False, "error": "Insufficient data (need 48+ points)"}

            values = [p.value for p in series]
            timestamps = [p.timestamp for p in series]

            # Calculate overall trend (simple moving average)
            window = min(24, len(values) // 4)
            trend = self._moving_average(values, window)

            # Remove trend to get detrended series
            detrended = [v - t if t else v for v, t in zip(values, trend)]

            # Detect hourly pattern (hour of day)
            hourly_pattern = self._detect_hourly_pattern(timestamps, detrended)

            # Detect daily pattern (day of week)
            daily_pattern = self._detect_daily_pattern(timestamps, detrended)

            # Calculate seasonal component
            seasonal = []
            for ts in timestamps:
                hour_effect = hourly_pattern.get(ts.hour, 0)
                day_effect = daily_pattern.get(ts.weekday(), 0)
                seasonal.append(hour_effect + day_effect)

            # Residual = original - trend - seasonal
            residual = [v - t - s if t else 0
                       for v, t, s in zip(values, trend, seasonal)]

            # Calculate component strengths
            total_var = self._variance(values)
            trend_var = self._variance([t for t in trend if t])
            seasonal_var = self._variance(seasonal)
            residual_var = self._variance(residual)

            trend_strength = trend_var / total_var if total_var > 0 else 0
            seasonal_strength = seasonal_var / total_var if total_var > 0 else 0

            # Save detected patterns
            patterns_found = []

            if seasonal_strength > 0.1:  # Significant seasonality
                # Find hourly peak/trough
                if hourly_pattern:
                    peak_hour = max(hourly_pattern, key=hourly_pattern.get)
                    trough_hour = min(hourly_pattern, key=hourly_pattern.get)
                    amplitude = hourly_pattern[peak_hour] - hourly_pattern[trough_hour]

                    pattern = SeasonalPattern(
                        pattern_type="hourly",
                        period_hours=24,
                        amplitude=amplitude,
                        peak_time=f"{peak_hour:02d}:00",
                        trough_time=f"{trough_hour:02d}:00",
                        confidence=min(0.95, seasonal_strength * 2)
                    )
                    patterns_found.append(pattern)
                    self._save_seasonal_pattern(metric_name, pattern)

                # Find weekly peak/trough
                if daily_pattern:
                    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                    peak_day = max(daily_pattern, key=daily_pattern.get)
                    trough_day = min(daily_pattern, key=daily_pattern.get)
                    amplitude = daily_pattern[peak_day] - daily_pattern[trough_day]

                    pattern = SeasonalPattern(
                        pattern_type="weekly",
                        period_hours=168,
                        amplitude=amplitude,
                        peak_time=days[peak_day],
                        trough_time=days[trough_day],
                        confidence=min(0.95, seasonal_strength * 2)
                    )
                    patterns_found.append(pattern)
                    self._save_seasonal_pattern(metric_name, pattern)

            return {
                "success": True,
                "metric": metric_name,
                "data_points": len(series),
                "components": {
                    "trend_strength": round(trend_strength, 3),
                    "seasonal_strength": round(seasonal_strength, 3),
                    "residual_ratio": round(residual_var / total_var if total_var else 0, 3)
                },
                "hourly_pattern": hourly_pattern,
                "daily_pattern": {
                    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][k]: round(v, 3)
                    for k, v in daily_pattern.items()
                } if daily_pattern else {},
                "patterns_detected": [asdict(p) for p in patterns_found]
            }

        except Exception as e:
            logger.error(f"Seasonal decomposition failed: {e}")
            return {"success": False, "error": str(e)}

    def _detect_hourly_pattern(
        self,
        timestamps: List[datetime],
        values: List[float]
    ) -> Dict[int, float]:
        """Detect hourly (hour of day) pattern."""
        hourly = defaultdict(list)
        for ts, v in zip(timestamps, values):
            hourly[ts.hour].append(v)

        return {h: sum(vs) / len(vs) for h, vs in hourly.items() if vs}

    def _detect_daily_pattern(
        self,
        timestamps: List[datetime],
        values: List[float]
    ) -> Dict[int, float]:
        """Detect daily (day of week) pattern."""
        daily = defaultdict(list)
        for ts, v in zip(timestamps, values):
            daily[ts.weekday()].append(v)

        return {d: sum(vs) / len(vs) for d, vs in daily.items() if vs}

    def _save_seasonal_pattern(self, metric_name: str, pattern: SeasonalPattern):
        """Save detected seasonal pattern."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO ml_seasonal_patterns
                    (metric_name, pattern_type, period_hours, amplitude,
                     peak_time, trough_time, confidence, pattern_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (metric_name, pattern_type) DO UPDATE SET
                        amplitude = EXCLUDED.amplitude,
                        peak_time = EXCLUDED.peak_time,
                        trough_time = EXCLUDED.trough_time,
                        confidence = EXCLUDED.confidence,
                        pattern_data = EXCLUDED.pattern_data,
                        detected_at = NOW()
                """, (
                    metric_name,
                    pattern.pattern_type,
                    pattern.period_hours,
                    pattern.amplitude,
                    pattern.peak_time,
                    pattern.trough_time,
                    pattern.confidence,
                    json.dumps(asdict(pattern))
                ))
        except Exception as e:
            logger.error(f"Save seasonal pattern failed: {e}")

    # =========================================================================
    # Forecasting
    # =========================================================================

    def forecast(
        self,
        metric_name: str,
        horizon_hours: int = 24,
        confidence_level: float = 0.9
    ) -> Dict[str, Any]:
        """
        Generate time series forecast with confidence intervals.

        Uses exponential smoothing with seasonal adjustment.
        """
        try:
            # Get historical data
            series = self.get_time_series(metric_name, hours=336)  # 2 weeks
            if len(series) < 24:
                return {"success": False, "error": "Insufficient data (need 24+ points)"}

            values = [p.value for p in series]
            timestamps = [p.timestamp for p in series]

            # Get seasonal patterns if available
            hourly_pattern = self._detect_hourly_pattern(timestamps, values)

            # Calculate exponential smoothing parameters
            alpha = 0.3  # Level smoothing
            beta = 0.1   # Trend smoothing

            # Initialize
            level = values[0]
            trend = (values[-1] - values[0]) / len(values) if len(values) > 1 else 0

            # Fit model
            fitted = []
            for v in values:
                prev_level = level
                level = alpha * v + (1 - alpha) * (level + trend)
                trend = beta * (level - prev_level) + (1 - beta) * trend
                fitted.append(level + trend)

            # Calculate residual standard error
            residuals = [v - f for v, f in zip(values, fitted)]
            residual_std = math.sqrt(self._variance(residuals)) if residuals else 0

            # Z-score for confidence interval
            z_score = 1.645 if confidence_level >= 0.9 else 1.96 if confidence_level >= 0.95 else 1.28

            # Generate forecasts
            predictions = []
            last_ts = timestamps[-1]
            current_level = level
            current_trend = trend

            for h in range(1, horizon_hours + 1):
                forecast_ts = last_ts + timedelta(hours=h)

                # Base forecast
                base_forecast = current_level + current_trend * h

                # Add seasonal adjustment
                seasonal_adj = hourly_pattern.get(forecast_ts.hour, 0)
                forecast_value = base_forecast + seasonal_adj

                # Confidence interval widens with horizon
                interval_width = z_score * residual_std * math.sqrt(h)

                predictions.append({
                    "timestamp": forecast_ts.isoformat(),
                    "hour": h,
                    "value": round(max(0, forecast_value), 3),
                    "lower": round(max(0, forecast_value - interval_width), 3),
                    "upper": round(forecast_value + interval_width, 3)
                })

            # Save forecast
            self._save_forecast(metric_name, horizon_hours, predictions, confidence_level)

            return {
                "success": True,
                "metric": metric_name,
                "horizon_hours": horizon_hours,
                "confidence_level": confidence_level,
                "method": "exponential_smoothing_seasonal",
                "model_params": {
                    "alpha": alpha,
                    "beta": beta,
                    "residual_std": round(residual_std, 3)
                },
                "last_value": round(values[-1], 3),
                "predictions": predictions[:24] if horizon_hours > 24 else predictions,
                "summary": {
                    "min_forecast": round(min(p['value'] for p in predictions), 3),
                    "max_forecast": round(max(p['value'] for p in predictions), 3),
                    "trend_direction": "up" if current_trend > 0 else "down" if current_trend < 0 else "flat"
                }
            }

        except Exception as e:
            logger.error(f"Forecast failed: {e}")
            return {"success": False, "error": str(e)}

    def _save_forecast(
        self,
        metric_name: str,
        horizon_hours: int,
        predictions: List[Dict],
        confidence_level: float
    ):
        """Save generated forecast."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO ml_forecasts
                    (metric_name, forecast_horizon_hours, predictions,
                     method, confidence_level, expires_at)
                    VALUES (%s, %s, %s, %s, %s, NOW() + make_interval(hours => %s))
                """, (
                    metric_name,
                    horizon_hours,
                    json.dumps(predictions),
                    "exponential_smoothing_seasonal",
                    confidence_level,
                    horizon_hours
                ))
        except Exception as e:
            logger.error(f"Save forecast failed: {e}")

    # =========================================================================
    # Anomaly Detection
    # =========================================================================

    def detect_anomalies_ml(
        self,
        metric_name: str,
        hours: int = 168,
        sensitivity: float = 2.5
    ) -> Dict[str, Any]:
        """
        Detect anomalies using statistical methods.

        Uses seasonal-adjusted Z-scores and contextual analysis.
        """
        try:
            series = self.get_time_series(metric_name, hours)
            if len(series) < 24:
                return {"success": False, "error": "Insufficient data"}

            values = [p.value for p in series]
            timestamps = [p.timestamp for p in series]

            # Get hourly pattern for seasonal adjustment
            hourly_pattern = self._detect_hourly_pattern(timestamps, values)

            # Calculate seasonally-adjusted values
            adjusted = []
            for ts, v in zip(timestamps, values):
                seasonal = hourly_pattern.get(ts.hour, 0)
                mean_seasonal = sum(hourly_pattern.values()) / len(hourly_pattern) if hourly_pattern else 0
                adjusted.append(v - (seasonal - mean_seasonal))

            # Calculate statistics on adjusted values
            mean_val = sum(adjusted) / len(adjusted)
            std_val = math.sqrt(self._variance(adjusted))

            # Detect anomalies
            anomalies = []
            for i, (ts, v, adj) in enumerate(zip(timestamps, values, adjusted)):
                if std_val > 0:
                    z_score = (adj - mean_val) / std_val

                    if abs(z_score) > sensitivity:
                        anomalies.append({
                            "timestamp": ts.isoformat(),
                            "value": round(v, 3),
                            "expected": round(mean_val + hourly_pattern.get(ts.hour, 0), 3),
                            "z_score": round(z_score, 2),
                            "type": "spike" if z_score > 0 else "drop",
                            "severity": "high" if abs(z_score) > 3 else "medium"
                        })

            # Calculate anomaly rate
            anomaly_rate = len(anomalies) / len(series) * 100 if series else 0

            return {
                "success": True,
                "metric": metric_name,
                "period_hours": hours,
                "sensitivity": sensitivity,
                "statistics": {
                    "mean": round(mean_val, 3),
                    "std": round(std_val, 3),
                    "data_points": len(series)
                },
                "anomaly_count": len(anomalies),
                "anomaly_rate_pct": round(anomaly_rate, 2),
                "anomalies": anomalies[:20]  # Limit output
            }

        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Predictive Alerting
    # =========================================================================

    def generate_predictive_alerts(
        self,
        metrics: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate predictive alerts based on pattern analysis.

        Forecasts potential issues before they occur.
        """
        try:
            if metrics is None:
                # Default metrics to monitor
                metrics = [
                    "tool_failure_rate",
                    "response_latency_p95",
                    "queries_per_hour",
                    "error_count"
                ]

            alerts = []

            for metric in metrics:
                series = self.get_time_series(metric, hours=168)
                if len(series) < 24:
                    continue

                values = [p.value for p in series]

                # Check for concerning trends
                recent = values[-24:]  # Last 24 hours
                older = values[-48:-24] if len(values) >= 48 else values[:-24]

                if recent and older:
                    recent_avg = sum(recent) / len(recent)
                    older_avg = sum(older) / len(older)

                    change_pct = ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0

                    # Generate alerts for significant changes
                    if metric in ["tool_failure_rate", "error_count"] and change_pct > 50:
                        alert = PatternAlert(
                            alert_type="degradation_trend",
                            severity="high" if change_pct > 100 else "medium",
                            metric=metric,
                            message=f"{metric} increased {change_pct:.0f}% in last 24h",
                            predicted_at=datetime.utcnow(),
                            expected_when=datetime.utcnow() + timedelta(hours=12),
                            confidence=0.75,
                            recommendation=f"Investigate {metric} trend before it worsens"
                        )
                        alerts.append(alert)
                        self._save_alert(alert)

                    elif metric == "response_latency_p95" and change_pct > 30:
                        alert = PatternAlert(
                            alert_type="latency_degradation",
                            severity="medium",
                            metric=metric,
                            message=f"P95 latency increased {change_pct:.0f}%",
                            predicted_at=datetime.utcnow(),
                            expected_when=datetime.utcnow() + timedelta(hours=6),
                            confidence=0.7,
                            recommendation="Check for resource constraints or slow tools"
                        )
                        alerts.append(alert)
                        self._save_alert(alert)

                    elif metric == "queries_per_hour" and change_pct < -50:
                        alert = PatternAlert(
                            alert_type="usage_drop",
                            severity="low",
                            metric=metric,
                            message=f"Query volume dropped {abs(change_pct):.0f}%",
                            predicted_at=datetime.utcnow(),
                            expected_when=datetime.utcnow(),
                            confidence=0.8,
                            recommendation="Check if this is expected (weekend, holiday)"
                        )
                        alerts.append(alert)
                        self._save_alert(alert)

            return {
                "success": True,
                "metrics_analyzed": len(metrics),
                "alerts_generated": len(alerts),
                "alerts": [asdict(a) for a in alerts]
            }

        except Exception as e:
            logger.error(f"Generate alerts failed: {e}")
            return {"success": False, "error": str(e)}

    def _save_alert(self, alert: PatternAlert):
        """Save predictive alert."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO ml_pattern_alerts
                    (alert_type, severity, metric_name, message,
                     predicted_at, expected_when, confidence, recommendation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    alert.alert_type,
                    alert.severity,
                    alert.metric,
                    alert.message,
                    alert.predicted_at,
                    alert.expected_when,
                    alert.confidence,
                    alert.recommendation
                ))
        except Exception as e:
            logger.error(f"Save alert failed: {e}")

    def get_active_alerts(
        self,
        severity: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get unacknowledged alerts."""
        try:
            with get_cursor() as cur:
                if severity:
                    cur.execute("""
                        SELECT alert_type, severity, metric_name, message,
                               predicted_at, expected_when, confidence, recommendation
                        FROM ml_pattern_alerts
                        WHERE is_acknowledged = false
                        AND severity = %s
                        ORDER BY
                            CASE severity
                                WHEN 'critical' THEN 1
                                WHEN 'high' THEN 2
                                WHEN 'medium' THEN 3
                                ELSE 4
                            END,
                            predicted_at DESC
                        LIMIT %s
                    """, (severity, limit))
                else:
                    cur.execute("""
                        SELECT alert_type, severity, metric_name, message,
                               predicted_at, expected_when, confidence, recommendation
                        FROM ml_pattern_alerts
                        WHERE is_acknowledged = false
                        ORDER BY
                            CASE severity
                                WHEN 'critical' THEN 1
                                WHEN 'high' THEN 2
                                WHEN 'medium' THEN 3
                                ELSE 4
                            END,
                            predicted_at DESC
                        LIMIT %s
                    """, (limit,))

                alerts = [{
                    "type": row['alert_type'],
                    "severity": row['severity'],
                    "metric": row['metric_name'],
                    "message": row['message'],
                    "predicted_at": row['predicted_at'].isoformat(),
                    "expected_when": row['expected_when'].isoformat() if row['expected_when'] else None,
                    "confidence": row['confidence'],
                    "recommendation": row['recommendation']
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "alert_count": len(alerts),
                    "alerts": alerts
                }

        except Exception as e:
            logger.error(f"Get active alerts failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Cross-Metric Correlation
    # =========================================================================

    def correlate_metrics(
        self,
        metric1: str,
        metric2: str,
        hours: int = 168
    ) -> Dict[str, Any]:
        """
        Calculate correlation between two metrics.

        Identifies potential causal relationships.
        """
        try:
            series1 = self.get_time_series(metric1, hours)
            series2 = self.get_time_series(metric2, hours)

            if len(series1) < 10 or len(series2) < 10:
                return {"success": False, "error": "Insufficient data"}

            # Align series by timestamp (hourly buckets)
            buckets1 = {}
            buckets2 = {}

            for p in series1:
                key = p.timestamp.replace(minute=0, second=0, microsecond=0)
                buckets1[key] = p.value

            for p in series2:
                key = p.timestamp.replace(minute=0, second=0, microsecond=0)
                buckets2[key] = p.value

            # Find common timestamps
            common_keys = sorted(set(buckets1.keys()) & set(buckets2.keys()))
            if len(common_keys) < 10:
                return {"success": False, "error": "Not enough aligned data points"}

            values1 = [buckets1[k] for k in common_keys]
            values2 = [buckets2[k] for k in common_keys]

            # Calculate Pearson correlation
            correlation = self._pearson_correlation(values1, values2)

            # Calculate lagged correlations
            lag_correlations = {}
            for lag in range(-6, 7):  # -6 to +6 hours
                if lag == 0:
                    lag_correlations[lag] = correlation
                elif lag < 0:
                    # metric2 leads metric1
                    shifted1 = values1[-lag:]
                    shifted2 = values2[:lag]
                    if len(shifted1) >= 5 and len(shifted2) >= 5:
                        lag_correlations[lag] = self._pearson_correlation(shifted1, shifted2)
                else:
                    # metric1 leads metric2
                    shifted1 = values1[:-lag]
                    shifted2 = values2[lag:]
                    if len(shifted1) >= 5 and len(shifted2) >= 5:
                        lag_correlations[lag] = self._pearson_correlation(shifted1, shifted2)

            # Find strongest lag
            best_lag = max(lag_correlations, key=lambda k: abs(lag_correlations[k]))
            best_corr = lag_correlations[best_lag]

            # Interpret
            if abs(correlation) > 0.7:
                strength = "strong"
            elif abs(correlation) > 0.4:
                strength = "moderate"
            elif abs(correlation) > 0.2:
                strength = "weak"
            else:
                strength = "none"

            direction = "positive" if correlation > 0 else "negative"

            lead_lag = None
            if abs(best_corr) > abs(correlation) + 0.1 and best_lag != 0:
                if best_lag < 0:
                    lead_lag = f"{metric2} leads {metric1} by {-best_lag}h"
                else:
                    lead_lag = f"{metric1} leads {metric2} by {best_lag}h"

            return {
                "success": True,
                "metric1": metric1,
                "metric2": metric2,
                "data_points": len(common_keys),
                "correlation": round(correlation, 3),
                "strength": strength,
                "direction": direction,
                "best_lag_hours": best_lag,
                "best_lag_correlation": round(best_corr, 3),
                "lead_lag_relationship": lead_lag,
                "lag_analysis": {str(k): round(v, 3) for k, v in lag_correlations.items()}
            }

        except Exception as e:
            logger.error(f"Correlate metrics failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _moving_average(self, values: List[float], window: int) -> List[Optional[float]]:
        """Calculate moving average."""
        result = []
        for i in range(len(values)):
            if i < window - 1:
                result.append(None)
            else:
                window_values = values[i - window + 1:i + 1]
                result.append(sum(window_values) / len(window_values))
        return result

    def _variance(self, values: List[float]) -> float:
        """Calculate variance."""
        if not values or len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((x - mean) ** 2 for x in values) / len(values)

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        x = x[:n]
        y = y[:n]

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
        std_x = math.sqrt(self._variance(x))
        std_y = math.sqrt(self._variance(y))

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    def get_pattern_summary(self) -> Dict[str, Any]:
        """Get summary of all detected patterns."""
        try:
            with get_cursor() as cur:
                # Get seasonal patterns
                cur.execute("""
                    SELECT metric_name, pattern_type, amplitude,
                           peak_time, trough_time, confidence
                    FROM ml_seasonal_patterns
                    WHERE is_active = true
                    ORDER BY confidence DESC
                    LIMIT 20
                """)

                seasonal = [{
                    "metric": row['metric_name'],
                    "type": row['pattern_type'],
                    "amplitude": round(row['amplitude'], 3),
                    "peak": row['peak_time'],
                    "trough": row['trough_time'],
                    "confidence": round(row['confidence'], 2)
                } for row in cur.fetchall()]

                # Get recent forecasts
                cur.execute("""
                    SELECT metric_name, forecast_horizon_hours,
                           method, confidence_level, created_at
                    FROM ml_forecasts
                    WHERE expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 10
                """)

                forecasts = [{
                    "metric": row['metric_name'],
                    "horizon_hours": row['forecast_horizon_hours'],
                    "method": row['method'],
                    "created": row['created_at'].isoformat()
                } for row in cur.fetchall()]

                # Get alert summary
                cur.execute("""
                    SELECT severity, COUNT(*) as count
                    FROM ml_pattern_alerts
                    WHERE is_acknowledged = false
                    GROUP BY severity
                """)

                alert_counts = {row['severity']: row['count'] for row in cur.fetchall()}

                return {
                    "success": True,
                    "seasonal_patterns": seasonal,
                    "active_forecasts": forecasts,
                    "unacknowledged_alerts": alert_counts,
                    "ml_capabilities": {
                        "has_numpy": HAS_NUMPY,
                        "has_scipy": HAS_SCIPY
                    }
                }

        except Exception as e:
            logger.error(f"Get pattern summary failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[MLPatternService] = None


def get_ml_pattern_service() -> MLPatternService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = MLPatternService()
    return _service
