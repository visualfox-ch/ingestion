"""
Test suite for Thompson Sampling Optimizer

Validates Phase 2 implementation:
- Thompson Sampling algorithm
- Convergence detection
- Circuit breaker integration
- HITL approval workflow
- Rate limiting
- Audit trail

Run: python -m pytest tests/test_thompson_optimizer.py -v
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from app.thompson_optimizer import (
    ThompsonOptimizer,
    ParameterVariant,
    OptimizationStatus,
    get_thompson_optimizer
)


@pytest.fixture
def temp_state_dir():
    """Create temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def optimizer(temp_state_dir):
    """Create optimizer instance with temp state."""
    return ThompsonOptimizer(
        state_path=temp_state_dir,
        max_iterations=100,
        convergence_threshold=0.95
    )


class TestParameterVariant:
    """Test ParameterVariant class."""
    
    def test_initialization(self):
        """Test variant initialization."""
        var = ParameterVariant("freq_3", 3)
        assert var.name == "freq_3"
        assert var.value == 3
        assert var.alpha == 1.0
        assert var.beta == 1.0
        assert var.trials == 0
        assert var.successes == 0
        assert var.failures == 0
    
    def test_update_success(self):
        """Test updating with success."""
        var = ParameterVariant("freq_3", 3)
        var.update(success=True)
        
        assert var.trials == 1
        assert var.successes == 1
        assert var.failures == 0
        assert var.alpha == 2.0
        assert var.beta == 1.0
        assert var.success_rate() == 1.0
    
    def test_update_failure(self):
        """Test updating with failure."""
        var = ParameterVariant("freq_3", 3)
        var.update(success=False)
        
        assert var.trials == 1
        assert var.successes == 0
        assert var.failures == 1
        assert var.alpha == 1.0
        assert var.beta == 2.0
        assert var.success_rate() == 0.0
    
    def test_multiple_updates(self):
        """Test multiple updates."""
        var = ParameterVariant("freq_3", 3)
        
        # 7 successes, 3 failures
        for _ in range(7):
            var.update(success=True)
        for _ in range(3):
            var.update(success=False)
        
        assert var.trials == 10
        assert var.successes == 7
        assert var.failures == 3
        assert var.alpha == 8.0  # 1 + 7
        assert var.beta == 4.0   # 1 + 3
        assert var.success_rate() == 0.7
    
    def test_sampling(self):
        """Test Beta distribution sampling."""
        var = ParameterVariant("freq_3", 3)
        var.alpha = 8.0
        var.beta = 4.0
        
        # Sample should be between 0 and 1
        for _ in range(100):
            sample = var.sample()
            assert 0.0 <= sample <= 1.0
    
    def test_confidence_interval(self):
        """Test confidence interval calculation."""
        var = ParameterVariant("freq_3", 3)
        
        # With no trials
        lower, upper = var.confidence_interval()
        assert lower == 0.0
        assert upper == 1.0
        
        # With trials
        for _ in range(7):
            var.update(success=True)
        for _ in range(3):
            var.update(success=False)
        
        lower, upper = var.confidence_interval(confidence=0.95)
        assert 0.0 <= lower < upper <= 1.0
        assert lower < var.success_rate() < upper


class TestThompsonOptimizer:
    """Test ThompsonOptimizer class."""
    
    def test_initialization(self, optimizer):
        """Test optimizer initialization."""
        assert optimizer.status == OptimizationStatus.IDLE
        assert optimizer.parameter_name is None
        assert len(optimizer.variants) == 0
        assert optimizer.iteration == 0
        assert optimizer.best_variant is None
    
    def test_start_optimization(self, optimizer):
        """Test starting optimization."""
        result = optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={
                "freq_1": 1,
                "freq_2": 2,
                "freq_3": 3,
                "freq_4": 4,
                "freq_5": 5
            },
            metric_name="response_accuracy"
        )
        
        assert result["success"] is True
        assert result["parameter"] == "hint_frequency"
        assert len(result["variants"]) == 5
        assert optimizer.status == OptimizationStatus.EXPLORING
        assert len(optimizer.variants) == 5
    
    def test_cannot_start_while_running(self, optimizer):
        """Test cannot start new optimization while one is running."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2}
        )
        
        # Try to start another
        result = optimizer.start_optimization(
            parameter_name="other_param",
            variants={"val_1": 1}
        )
        
        assert result["success"] is False
        assert "already_running" in result["error"]
    
    def test_select_variant(self, optimizer):
        """Test variant selection using Thompson Sampling."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2, "freq_3": 3}
        )
        
        # Select variant
        result = optimizer.select_variant()
        
        assert result is not None
        assert "variant_name" in result
        assert result["variant_name"] in ["freq_1", "freq_2", "freq_3"]
        assert "variant_value" in result
        assert result["iteration"] == 1
        assert "thompson_sample" in result
    
    def test_thompson_sampling_exploration(self, optimizer):
        """Test Thompson Sampling explores different variants."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2, "freq_3": 3}
        )
        
        # Run 30 iterations with random outcomes
        selected_variants = []
        for _ in range(30):
            result = optimizer.select_variant()
            selected_variants.append(result["variant_name"])
            
            # Report random outcome
            import random
            optimizer.report_outcome(success=random.choice([True, False]))
        
        # Should have explored multiple variants
        unique_variants = set(selected_variants)
        assert len(unique_variants) >= 2, "Should explore multiple variants"
    
    def test_thompson_sampling_exploitation(self, optimizer):
        """Test Thompson Sampling exploits best variant."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_good": 1, "freq_bad": 2}
        )
        
        # Manually set one variant as clearly better
        optimizer.variants["freq_good"].alpha = 20.0  # 19 successes
        optimizer.variants["freq_good"].beta = 2.0    # 1 failure
        optimizer.variants["freq_good"].trials = 20
        optimizer.variants["freq_good"].successes = 19
        
        optimizer.variants["freq_bad"].alpha = 5.0   # 4 successes
        optimizer.variants["freq_bad"].beta = 16.0   # 15 failures
        optimizer.variants["freq_bad"].trials = 20
        optimizer.variants["freq_bad"].successes = 4
        
        # Select variant multiple times - should prefer good one
        selections = []
        for _ in range(20):
            result = optimizer.select_variant()
            selections.append(result["variant_name"])
            optimizer.report_outcome(success=True)
        
        # Should select good variant more often (>80% of the time)
        good_count = selections.count("freq_good")
        assert good_count >= 16, f"Should exploit good variant (got {good_count}/20)"
    
    def test_report_outcome(self, optimizer):
        """Test reporting outcome."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2}
        )
        
        # Select and report success
        optimizer.select_variant()
        result = optimizer.report_outcome(success=True)
        
        assert result["success"] is True
        assert result["outcome"] == "success"
        assert result["trials"] == 1
        assert result["success_rate"] == 1.0
    
    def test_convergence_detection(self, optimizer):
        """Test convergence detection."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_good": 1, "freq_bad": 2}
        )
        
        # Simulate clear winner (freq_good: 95% success, freq_bad: 20% success)
        for _ in range(30):
            optimizer.current_variant = "freq_good"
            optimizer.variants["freq_good"].update(success=True)
            optimizer.iteration += 1
        for _ in range(2):
            optimizer.current_variant = "freq_good"
            optimizer.variants["freq_good"].update(success=False)
            optimizer.iteration += 1
        
        for _ in range(5):
            optimizer.current_variant = "freq_bad"
            optimizer.variants["freq_bad"].update(success=True)
            optimizer.iteration += 1
        for _ in range(20):
            optimizer.current_variant = "freq_bad"
            optimizer.variants["freq_bad"].update(success=False)
            optimizer.iteration += 1
        
        # Check convergence
        convergence = optimizer._check_convergence()
        
        assert convergence["converged"] is True
        assert convergence["best_variant"] == "freq_good"
        assert optimizer.status == OptimizationStatus.PENDING_APPROVAL
    
    def test_max_iterations_convergence(self, optimizer):
        """Test convergence at max iterations."""
        optimizer.max_iterations = 10
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2}
        )
        
        # Run to max iterations
        for _ in range(10):
            optimizer.select_variant()
            optimizer.report_outcome(success=True)
        
        # Should converge at max iterations
        convergence = optimizer._check_convergence()
        assert convergence["converged"] is True
        assert convergence["reason"] == "max_iterations_reached"
    
    def test_get_recommendation(self, optimizer):
        """Test getting recommendation after convergence."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_baseline": 2, "freq_new": 3}
        )
        
        # Force convergence
        optimizer.status = OptimizationStatus.PENDING_APPROVAL
        optimizer.best_variant = "freq_new"
        optimizer.variants["freq_new"].alpha = 20.0
        optimizer.variants["freq_new"].trials = 20
        optimizer.variants["freq_new"].successes = 19
        
        optimizer.variants["freq_baseline"].alpha = 15.0
        optimizer.variants["freq_baseline"].trials = 20
        optimizer.variants["freq_baseline"].successes = 14
        
        # Get recommendation
        rec = optimizer.get_recommendation()
        
        assert rec is not None
        assert rec["parameter"] == "hint_frequency"
        assert rec["recommended_variant"] == "freq_new"
        assert rec["recommended_value"] == 3
        assert rec["confidence"] > 0.9
        assert "improvement_vs_baseline" in rec
        assert rec["status"] == OptimizationStatus.PENDING_APPROVAL.value
    
    def test_approve_recommendation(self, optimizer):
        """Test HITL approval."""
        optimizer.status = OptimizationStatus.PENDING_APPROVAL
        optimizer.parameter_name = "hint_frequency"
        optimizer.best_variant = "freq_3"
        optimizer.variants["freq_3"] = ParameterVariant("freq_3", 3)
        
        result = optimizer.approve_recommendation(
            approved=True,
            reason="Improved accuracy by 5%"
        )
        
        assert result["success"] is True
        assert result["status"] == OptimizationStatus.APPROVED.value
        assert optimizer.status == OptimizationStatus.APPROVED
    
    def test_reject_recommendation(self, optimizer):
        """Test HITL rejection."""
        optimizer.status = OptimizationStatus.PENDING_APPROVAL
        optimizer.parameter_name = "hint_frequency"
        optimizer.best_variant = "freq_3"
        optimizer.variants["freq_3"] = ParameterVariant("freq_3", 3)
        
        result = optimizer.approve_recommendation(
            approved=False,
            reason="Manual testing showed issues"
        )
        
        assert result["success"] is True
        assert result["status"] == OptimizationStatus.REJECTED.value
        assert optimizer.status == OptimizationStatus.REJECTED
    
    def test_circuit_breaker_error_rate(self, optimizer):
        """Test circuit breaker triggers on high error rate."""
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1}
        )
        optimizer.select_variant()
        
        # Report outcome with high error rate
        result = optimizer.report_outcome(
            success=False,
            metrics={"error_rate": 0.15}  # >10% threshold
        )
        
        assert result["success"] is False
        assert result["triggered"] is True
        assert result["reason"] == "error_rate_exceeded"
        assert optimizer.circuit_breaker_active is True
        assert optimizer.status == OptimizationStatus.ROLLED_BACK
    
    def test_rate_limiting(self, optimizer):
        """Test rate limiting (50/hour)."""
        optimizer.optimizations_this_hour = 50
        
        result = optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1}
        )
        
        assert result["success"] is False
        assert "rate_limit" in result["error"]
    
    def test_state_persistence(self, temp_state_dir):
        """Test state save/load."""
        # Create optimizer and start optimization
        opt1 = ThompsonOptimizer(state_path=temp_state_dir)
        opt1.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1, "freq_2": 2}
        )
        opt1.select_variant()
        opt1.report_outcome(success=True)
        
        # Create new optimizer from same state
        opt2 = ThompsonOptimizer(state_path=temp_state_dir)
        
        assert opt2.parameter_name == "hint_frequency"
        assert opt2.status == OptimizationStatus.EXPLORING
        assert len(opt2.variants) == 2
        assert opt2.iteration == 1
    
    def test_audit_log(self, temp_state_dir):
        """Test audit logging."""
        optimizer = ThompsonOptimizer(state_path=temp_state_dir)
        
        # Perform actions that log
        optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={"freq_1": 1}
        )
        optimizer.select_variant()
        optimizer.report_outcome(success=True)
        
        # Check audit file
        audit_file = Path(temp_state_dir) / "optimization_audit.json"
        assert audit_file.exists()
        
        with open(audit_file, 'r') as f:
            audit = json.load(f)
        
        assert len(audit) >= 2  # At least start + outcome
        assert audit[0]["event"] == "optimization_started"
        assert "timestamp" in audit[0]


class TestIntegration:
    """Integration tests."""
    
    def test_full_optimization_cycle(self, optimizer):
        """Test complete optimization cycle."""
        # Start optimization
        result = optimizer.start_optimization(
            parameter_name="hint_frequency",
            variants={
                "freq_1": 1,
                "freq_2": 2,
                "freq_3": 3
            },
            metric_name="response_accuracy"
        )
        assert result["success"] is True
        
        # Run optimization loop
        for iteration in range(50):
            # Select variant
            selection = optimizer.select_variant()
            assert selection is not None
            
            # Simulate outcome based on variant value
            # Higher frequency = better success rate
            variant_value = selection["variant_value"]
            success_prob = 0.5 + (variant_value * 0.15)  # freq_3 has ~95% success
            
            import random
            success = random.random() < success_prob
            
            # Report outcome
            outcome = optimizer.report_outcome(success=success)
            assert outcome["success"] is True
            
            # Check if converged
            if outcome.get("converged"):
                break
        
        # Should converge
        assert optimizer.status == OptimizationStatus.PENDING_APPROVAL
        assert optimizer.best_variant is not None
        
        # Get recommendation
        rec = optimizer.get_recommendation()
        assert rec is not None
        assert rec["recommended_variant"] in ["freq_1", "freq_2", "freq_3"]
        
        # Approve
        approval = optimizer.approve_recommendation(
            approved=True,
            reason="Test approval"
        )
        assert approval["success"] is True
        assert optimizer.status == OptimizationStatus.APPROVED


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
