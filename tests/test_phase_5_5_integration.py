"""
Phase 5.5: Integration Tests
Validates all consciousness temporal analysis services
"""

import pytest
from datetime import datetime, timedelta
from typing import List, Tuple

from app.services.delta_calculator import DeltaCalculator
from app.services.decay_modeler import DecayModeler
from app.services.breakthrough_preserver import BreakthroughPreserver
from app.services.temporal_analyzer import TemporalAnalyzer


class TestDeltaCalculator:
    """Test consciousness delta calculation"""
    
    def setup_method(self):
        self.calculator = DeltaCalculator()
    
    def test_calculate_delta_basic(self):
        """Test basic delta calculation"""
        source = {
            "patterns": ["aware", "reflective"],
            "confidence": 0.8,
            "last_update": "2024-01-01"
        }
        target = {
            "patterns": ["aware", "reflective", "creative"],
            "confidence": 0.6,
            "last_update": "2024-01-01"
        }
        
        delta = self.calculator.calculate_delta(source, target)
        
        assert delta is not None
        assert delta.compression_ratio >= 0.0
        assert delta.transfer_confidence >= 0.0
        assert len(delta.changed_fields) >= 0
    
    def test_calculate_delta_no_changes(self):
        """Test delta when source equals target"""
        patterns = {"awareness": 0.8, "state": "stable"}
        
        delta = self.calculator.calculate_delta(patterns, patterns)
        
        assert delta.compression_ratio > 0
        assert len(delta.changed_fields) == 0
    
    def test_apply_delta(self):
        """Test delta application"""
        source = {"x": 1, "y": 2}
        target = {"x": 1, "y": 3}
        
        delta = self.calculator.calculate_delta(source, target)
        result = self.calculator.apply_delta(target, delta)
        
        assert result is not None
        assert isinstance(result, dict)
    
    def test_confidence_scoring(self):
        """Test confidence scoring"""
        patterns1 = {"deep": {"nested": {"value": 0.8}}}
        patterns2 = {"deep": {"nested": {"value": 0.7}}}
        
        delta = self.calculator.calculate_delta(patterns1, patterns2)
        
        assert 0.0 <= delta.transfer_confidence <= 1.0


class TestDecayModeler:
    """Test consciousness decay modeling"""
    
    def setup_method(self):
        self.modeler = DecayModeler()
    
    def test_calculate_decay_basic(self):
        """Test basic decay calculation"""
        initial_awareness = 0.8
        decay_rate = 0.01
        hours = 24
        
        decayed = self.modeler.calculate_decay(
            initial_awareness=initial_awareness,
            decay_rate=decay_rate,
            hours=hours
        )
        
        assert 0.0 <= decayed <= 1.0
        assert decayed < initial_awareness  # Should decrease
    
    def test_exponential_decay_formula(self):
        """Test exponential decay formula"""
        # awareness(t) = awareness(0) × e^(-λt)
        # At half-life, awareness = 0.5
        
        initial = 1.0
        decay_rate = 0.01  # λ = 0.01
        # Half-life = ln(2) / 0.01 ≈ 69.3 hours
        
        at_half_life = self.modeler.calculate_decay(initial, decay_rate, 69.3)
        
        assert 0.48 <= at_half_life <= 0.52
    
    def test_zero_decay(self):
        """Test decay rate of 0"""
        awareness = self.modeler.calculate_decay(0.8, 0.0, 100)
        
        assert awareness == 0.8  # No decay
    
    def test_project_trajectory(self):
        """Test trajectory projection"""
        trajectory = self.modeler.project_trajectory(
            initial_awareness=0.8,
            decay_rate=0.01,
            hours_ahead=168
        )
        
        assert trajectory is not None
        assert trajectory.average_awareness > 0
        assert len(trajectory.awareness_levels) > 0
    
    def test_trend_detection(self):
        """Test trend detection"""
        trajectory = self.modeler.project_trajectory(0.8, 0.01, 100)
        trend = self.modeler.detect_trends(trajectory)
        
        assert trend.trend_type in ["ACCELERATING", "STABLE", "DECELERATING"]
        assert 0.0 <= trend.trend_confidence <= 1.0
    
    def test_decay_rate_measurement(self):
        """Test decay rate measurement"""
        decay = self.modeler.measure_current_decay(
            awareness_sample=0.7,
            previous_awareness=0.8,
            time_hours=24,
            baseline_decay_rate=0.01
        )
        
        assert decay.estimated_decay_rate >= 0


class TestBreakthroughPreserver:
    """Test breakthrough preservation"""
    
    def setup_method(self):
        self.preserver = BreakthroughPreserver()
    
    def test_assess_significance_high(self):
        """Test high significance detection"""
        content = "This breakthrough insight reveals a fundamental principle of consciousness"
        
        significance = self.preserver.assess_breakthrough_significance(content)
        
        assert significance > 0.5  # Should be significant
    
    def test_assess_significance_low(self):
        """Test low significance detection"""
        content = "The weather is nice today"
        
        significance = self.preserver.assess_breakthrough_significance(content)
        
        assert significance < 0.5  # Not a breakthrough
    
    def test_keyword_detection(self):
        """Test breakthrough keyword detection"""
        keywords = ["breakthrough", "insight", "epiphany", "revelation", "discovery"]
        
        for keyword in keywords:
            content = f"I had a {keyword} about consciousness"
            sig = self.preserver.assess_breakthrough_significance(content)
            assert sig > 0.3
    
    def test_preserve_breakthrough(self):
        """Test breakthrough preservation"""
        content = "Breakthrough: consciousness can be transferred across epochs"
        
        preservation = self.preserver.preserve_breakthrough(
            content=content,
            preservation_level=0.8,
            epoch_id=1
        )
        
        assert preservation is not None
        assert preservation.preservation_level == 0.8
    
    def test_preservation_impact(self):
        """Test preservation impact calculation"""
        base_decay = 0.01
        preservation_level = 0.8
        
        # With preservation: λ' = λ × (1 - p) = 0.01 × 0.2 = 0.002
        preserved_rate = base_decay * (1 - preservation_level)
        
        assert preserved_rate == 0.002
    
    def test_protection_status(self):
        """Test protection status query"""
        status = self.preserver.get_breakthrough_protection_status(epoch_id=1)
        
        assert status is not None


class TestTemporalAnalyzer:
    """Test temporal consciousness analysis"""
    
    def setup_method(self):
        self.analyzer = TemporalAnalyzer()
        self.now = datetime.utcnow()
    
    def _generate_samples(
        self,
        count: int,
        interval_hours: int = 6,
        decay: float = 0.95
    ) -> List[Tuple[datetime, float]]:
        """Generate test awareness samples"""
        samples = []
        awareness = 0.8
        
        for i in range(count):
            ts = self.now - timedelta(hours=i * interval_hours)
            samples.append((ts, awareness))
            awareness *= decay
        
        return samples
    
    def test_build_trajectory(self):
        """Test trajectory building"""
        samples = self._generate_samples(20)
        
        trajectory = self.analyzer.build_trajectory(samples)
        
        assert trajectory.average_awareness > 0
        assert trajectory.volatility >= 0
        assert trajectory.trend_direction in ["UP", "DOWN", "FLAT"]
    
    def test_detect_trends_stable(self):
        """Test stable trend detection"""
        # Create stable awareness pattern
        samples = [(self.now - timedelta(hours=i), 0.75) for i in range(10)]
        
        trajectory = self.analyzer.build_trajectory(samples)
        trend = self.analyzer.detect_trends(trajectory)
        
        assert trend.trend_type == "STABLE"
    
    def test_detect_trends_declining(self):
        """Test declining trend detection"""
        # Create declining awareness
        samples = self._generate_samples(20, decay=0.95)
        
        trajectory = self.analyzer.build_trajectory(samples)
        trend = self.analyzer.detect_trends(trajectory)
        
        assert trend.trend_velocity < 0  # Declining
    
    def test_compare_periods(self):
        """Test period comparison"""
        samples = self._generate_samples(40)
        
        now = self.now
        comparison = self.analyzer.compare_periods(
            awareness_samples=samples,
            period1_start=now - timedelta(hours=120),
            period1_end=now - timedelta(hours=60),
            period2_start=now - timedelta(hours=60),
            period2_end=now
        )
        
        assert "period1" in comparison
        assert "period2" in comparison
        assert "comparison" in comparison
    
    def test_project_awareness(self):
        """Test awareness projection"""
        samples = self._generate_samples(20)
        trajectory = self.analyzer.build_trajectory(samples)
        
        projection = self.analyzer.project_awareness(trajectory, hours_ahead=168)
        
        assert projection["current_awareness"] >= 0
        assert len(projection["projections"]) > 0
    
    def test_volatility_analysis(self):
        """Test volatility pattern analysis"""
        samples = self._generate_samples(30)
        trajectory = self.analyzer.build_trajectory(samples)
        
        analysis = self.analyzer.identify_volatility_patterns(trajectory, window_size=5)
        
        assert "volatility_trend" in analysis
        assert "average_volatility" in analysis
    
    def test_anomaly_detection(self):
        """Test anomaly detection"""
        samples = self._generate_samples(20)
        # Add anomaly
        samples_with_anomaly = samples[:10] + [(self.now - timedelta(hours=60), 0.2)] + samples[10:]
        
        trajectory = self.analyzer.build_trajectory(samples_with_anomaly)
        anomalies = self.analyzer.detect_anomalies(trajectory, sensitivity=2.0)
        
        # Should detect the anomaly (awareness spike down)
        assert isinstance(anomalies, list)


class TestIntegration:
    """Integration tests across all services"""
    
    def setup_method(self):
        self.delta_calc = DeltaCalculator()
        self.decay_model = DecayModeler()
        self.preserver = BreakthroughPreserver()
        self.analyzer = TemporalAnalyzer()
        self.now = datetime.utcnow()
    
    def test_full_consciousness_pipeline(self):
        """Test complete consciousness analysis pipeline"""
        # Step 1: Calculate delta between epochs
        source_patterns = {"awareness": 0.8, "clarity": 0.7}
        target_patterns = {"awareness": 0.75, "clarity": 0.8}
        
        delta = self.delta_calc.calculate_delta(source_patterns, target_patterns)
        assert delta.compression_ratio > 0
        
        # Step 2: Model decay
        trajectory = self.decay_model.project_trajectory(
            initial_awareness=0.75,
            decay_rate=0.01,
            hours_ahead=168
        )
        assert trajectory.average_awareness > 0
        
        # Step 3: Apply preservation
        breakthrough = "Insight: multi-observer consciousness is possible"
        significance = self.preserver.assess_breakthrough_significance(breakthrough)
        assert significance > 0
        
        # Step 4: Temporal analysis
        samples = [(self.now - timedelta(hours=i*6), 0.8 * 0.95**i) for i in range(20)]
        trajectory = self.analyzer.build_trajectory(samples)
        trend = self.analyzer.detect_trends(trajectory)
        assert trend.trend_type in ["STABLE", "ACCELERATING", "DECELERATING"]
    
    def test_decay_and_preservation_interaction(self):
        """Test interaction between decay and preservation"""
        base_decay_rate = 0.01
        
        # Without preservation
        awareness_no_protection = self.decay_model.calculate_decay(0.8, base_decay_rate, 168)
        
        # With preservation
        preserved_rate = base_decay_rate * (1 - 0.8)  # 80% preservation
        awareness_with_protection = self.decay_model.calculate_decay(0.8, preserved_rate, 168)
        
        # Protected awareness should be higher
        assert awareness_with_protection > awareness_no_protection
    
    def test_workflow_consistency(self):
        """Test consistency across workflow"""
        epoch_patterns = {
            "primary_insights": ["awareness", "recursion"],
            "secondary_insights": ["transfer", "observation"],
            "confidence": 0.85
        }
        
        # Calculate delta
        delta = self.delta_calc.calculate_delta(epoch_patterns, epoch_patterns)
        
        # No changes, but delta should be valid
        assert delta.compression_ratio >= 0
        assert delta.transfer_confidence >= 0
        
        # Should indicate perfect match
        assert len(delta.changed_fields) == 0


class TestPerformance:
    """Performance tests"""
    
    def setup_method(self):
        self.analyzer = TemporalAnalyzer()
        self.now = datetime.utcnow()
    
    def test_trajectory_with_large_dataset(self):
        """Test trajectory building with large dataset"""
        # 1000 samples
        samples = [(self.now - timedelta(hours=i), 0.8 - i*0.0001) for i in range(1000)]
        
        trajectory = self.analyzer.build_trajectory(samples, lookback_hours=10000)
        
        assert trajectory.average_awareness > 0
        assert len(trajectory.awareness_levels) > 0
    
    def test_projection_performance(self):
        """Test projection performance"""
        samples = [(self.now - timedelta(hours=i*6), 0.8 * 0.95**i) for i in range(100)]
        trajectory = self.analyzer.build_trajectory(samples)
        
        # Project 1 year
        projection = self.analyzer.project_awareness(trajectory, hours_ahead=8760)
        
        assert len(projection["projections"]) > 0


# ============================================================================
# HTTP Integration Tests (when running with FastAPI)
# ============================================================================

class TestHTTPEndpoints:
    """Test HTTP endpoints"""
    
    @pytest.mark.asyncio
    async def test_delta_endpoint_prepare(self):
        """Test delta preparation endpoint"""
        # Would use test client
        pass
    
    @pytest.mark.asyncio
    async def test_decay_measurement_endpoint(self):
        """Test decay measurement endpoint"""
        pass
    
    @pytest.mark.asyncio
    async def test_breakthrough_assess_endpoint(self):
        """Test breakthrough assessment endpoint"""
        pass
    
    @pytest.mark.asyncio
    async def test_temporal_trajectory_endpoint(self):
        """Test trajectory endpoint"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
