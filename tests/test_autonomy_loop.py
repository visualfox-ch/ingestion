"""Tests for Self-Optimization Autonomy Loop (T-301).

Tests the decision rubric, guardrails, risk scoring,
and pattern confidence system for autonomous self-improvement.

Based on:
- SELF_OPTIMIZATION_AUTONOMY_SPEC.md
- METRICS_TO_ACTION_MAP.md
- SELF_OPTIMIZATION_PLAYBOOK.md
"""
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------

class ApprovalTier(Enum):
    """Approval tier for optimization proposals."""
    TIER_1_AUTO = 1  # Auto-approve (risk 0-29)
    TIER_2_REVIEW = 2  # Human review (risk 30-69)
    TIER_3_FORBIDDEN = 3  # Never approve (risk 70+)


@dataclass
class OptimizationProposal:
    """A proposed optimization change."""
    id: str
    pattern: str
    files: List[str]
    lines_changed: int
    risk_score: int = 0
    tier: ApprovalTier = ApprovalTier.TIER_1_AUTO
    confidence: float = 0.5


# Pattern risk weights from spec
PATTERN_RISK_WEIGHTS = {
    "documentation": 5,
    "type_hint": 10,
    "import_optimization": 10,
    "dead_code_removal": 15,
    "constant_extraction": 15,
    "variable_renaming": 20,
    "loop_optimization": 35,
    "logic_refactoring": 50,
    "algorithm_change": 60,
    "schema_migration": 75,
    "security_related": 90,
}

# Forbidden modules that cannot be modified
FORBIDDEN_MODULES = [
    "approval_gate.py",
    "rollback.py",
    "audit_trail.py",
    "circuit_breaker.py",
    "security_validation.py",
    "metrics.py",
    "permissions.py",
]


# -----------------------------------------------------------------------------
# Risk Scoring Tests
# -----------------------------------------------------------------------------

class TestRiskScoring:
    """Test risk score calculation."""

    def test_base_risk_documentation(self):
        """Documentation changes should have low base risk."""
        assert PATTERN_RISK_WEIGHTS["documentation"] == 5

    def test_base_risk_security(self):
        """Security-related changes should have high base risk."""
        assert PATTERN_RISK_WEIGHTS["security_related"] == 90

    def test_risk_score_formula(self):
        """Test the full risk score formula."""
        proposal = OptimizationProposal(
            id="test-1",
            pattern="type_hint",
            files=["app/utils.py"],
            lines_changed=10
        )

        score = calculate_risk_score(
            proposal,
            recent_rollbacks=0,
            recent_failures=0,
            is_novel_pattern=False
        )

        # base_risk (10) + scope (1*5 + 10*0.1) + history (0) + novelty (0)
        expected = 10 + 6 + 0 + 0
        assert score == expected

    def test_risk_score_with_history_penalty(self):
        """Recent failures should increase risk score."""
        proposal = OptimizationProposal(
            id="test-2",
            pattern="type_hint",
            files=["app/utils.py"],
            lines_changed=10
        )

        score_no_history = calculate_risk_score(proposal, 0, 0, False)
        score_with_failures = calculate_risk_score(proposal, 0, 2, False)

        # failures add 10 each
        assert score_with_failures == score_no_history + 20

    def test_risk_score_with_rollbacks(self):
        """Recent rollbacks should add penalty."""
        proposal = OptimizationProposal(
            id="test-3",
            pattern="type_hint",
            files=["app/utils.py"],
            lines_changed=5
        )

        score_no_rollback = calculate_risk_score(proposal, 0, 0, False)
        score_with_rollback = calculate_risk_score(proposal, 1, 0, False)

        # rollbacks add 15 each
        assert score_with_rollback == score_no_rollback + 15

    def test_novelty_factor(self):
        """Novel patterns should get +20 risk."""
        proposal = OptimizationProposal(
            id="test-4",
            pattern="type_hint",
            files=["app/utils.py"],
            lines_changed=5
        )

        score_known = calculate_risk_score(proposal, 0, 0, False)
        score_novel = calculate_risk_score(proposal, 0, 0, True)

        assert score_novel == score_known + 20

    def test_multi_file_scope_modifier(self):
        """Multiple files should increase risk."""
        single_file = OptimizationProposal(
            id="test-5",
            pattern="type_hint",
            files=["app/a.py"],
            lines_changed=10
        )

        multi_file = OptimizationProposal(
            id="test-6",
            pattern="type_hint",
            files=["app/a.py", "app/b.py", "app/c.py"],
            lines_changed=10
        )

        score_single = calculate_risk_score(single_file, 0, 0, False)
        score_multi = calculate_risk_score(multi_file, 0, 0, False)

        # 3 files vs 1 file = +10 scope modifier
        assert score_multi == score_single + 10


def calculate_risk_score(
    proposal: OptimizationProposal,
    recent_rollbacks: int = 0,
    recent_failures: int = 0,
    is_novel_pattern: bool = False
) -> int:
    """Calculate risk score for a proposal."""
    # Base risk from pattern
    base_risk = PATTERN_RISK_WEIGHTS.get(proposal.pattern, 50)

    # Scope modifier
    scope_modifier = len(proposal.files) * 5 + int(proposal.lines_changed * 0.1)

    # History penalty
    history_penalty = recent_rollbacks * 15 + recent_failures * 10

    # Novelty factor
    novelty_factor = 20 if is_novel_pattern else 0

    return base_risk + scope_modifier + history_penalty + novelty_factor


# -----------------------------------------------------------------------------
# Tier Assignment Tests
# -----------------------------------------------------------------------------

class TestTierAssignment:
    """Test approval tier assignment based on risk score."""

    def test_tier_1_low_risk(self):
        """Risk 0-29 should be Tier 1 (auto-approve)."""
        for risk in [0, 15, 29]:
            tier = get_approval_tier(risk)
            assert tier == ApprovalTier.TIER_1_AUTO

    def test_tier_2_medium_risk(self):
        """Risk 30-69 should be Tier 2 (human review)."""
        for risk in [30, 50, 69]:
            tier = get_approval_tier(risk)
            assert tier == ApprovalTier.TIER_2_REVIEW

    def test_tier_3_high_risk(self):
        """Risk 70+ should be Tier 3 (forbidden)."""
        for risk in [70, 85, 100]:
            tier = get_approval_tier(risk)
            assert tier == ApprovalTier.TIER_3_FORBIDDEN

    def test_tier_boundary_29_30(self):
        """Test boundary between Tier 1 and Tier 2."""
        assert get_approval_tier(29) == ApprovalTier.TIER_1_AUTO
        assert get_approval_tier(30) == ApprovalTier.TIER_2_REVIEW

    def test_tier_boundary_69_70(self):
        """Test boundary between Tier 2 and Tier 3."""
        assert get_approval_tier(69) == ApprovalTier.TIER_2_REVIEW
        assert get_approval_tier(70) == ApprovalTier.TIER_3_FORBIDDEN


def get_approval_tier(risk_score: int) -> ApprovalTier:
    """Get approval tier based on risk score."""
    if risk_score < 30:
        return ApprovalTier.TIER_1_AUTO
    elif risk_score < 70:
        return ApprovalTier.TIER_2_REVIEW
    else:
        return ApprovalTier.TIER_3_FORBIDDEN


# -----------------------------------------------------------------------------
# Guardrails Tests
# -----------------------------------------------------------------------------

class TestGuardrails:
    """Test guardrail enforcement."""

    def test_forbidden_module_detection(self):
        """Should detect attempts to modify forbidden modules."""
        forbidden_file = "app/approval_gate.py"
        allowed_file = "app/utils.py"

        assert is_forbidden_module(forbidden_file)
        assert not is_forbidden_module(allowed_file)

    def test_all_forbidden_modules(self):
        """All forbidden modules should be detected."""
        for module in FORBIDDEN_MODULES:
            assert is_forbidden_module(f"app/{module}")
            assert is_forbidden_module(f"ingestion/app/{module}")

    def test_rate_limit_check(self):
        """Rate limits should be enforced."""
        # Daily limit
        assert check_rate_limit(writes_today=9, limit_daily=10)
        assert not check_rate_limit(writes_today=10, limit_daily=10)

        # Hourly limit
        assert check_rate_limit(writes_hour=1, limit_hourly=2)
        assert not check_rate_limit(writes_hour=2, limit_hourly=2)

    def test_bytes_limit(self):
        """Byte limit per write should be enforced."""
        assert check_size_limit(bytes_changed=500, max_bytes=1000)
        assert check_size_limit(bytes_changed=1000, max_bytes=1000)
        assert not check_size_limit(bytes_changed=1001, max_bytes=1000)

    def test_files_per_write_limit(self):
        """Only 1 file per write allowed."""
        assert check_files_limit(files_count=1, max_files=1)
        assert not check_files_limit(files_count=2, max_files=1)


def is_forbidden_module(filepath: str) -> bool:
    """Check if file is a forbidden module."""
    filename = Path(filepath).name
    return filename in FORBIDDEN_MODULES


def check_rate_limit(
    writes_today: int = 0,
    writes_hour: int = 0,
    limit_daily: int = 10,
    limit_hourly: int = 2
) -> bool:
    """Check if rate limits allow more writes."""
    return writes_today < limit_daily and writes_hour < limit_hourly


def check_size_limit(bytes_changed: int, max_bytes: int = 1000) -> bool:
    """Check if change size is within limits."""
    return bytes_changed <= max_bytes


def check_files_limit(files_count: int, max_files: int = 1) -> bool:
    """Check if file count is within limits."""
    return files_count <= max_files


# -----------------------------------------------------------------------------
# Confidence System Tests
# -----------------------------------------------------------------------------

class TestConfidenceSystem:
    """Test pattern confidence adjustment."""

    def test_confidence_increase_on_success(self):
        """Success should slowly increase confidence."""
        current = 0.7
        new_confidence = adjust_confidence(current, success=True)

        assert new_confidence > current
        assert new_confidence <= 1.0

    def test_confidence_decrease_on_failure(self):
        """Failure should quickly decrease confidence."""
        current = 0.7
        new_confidence = adjust_confidence(current, success=False)

        assert new_confidence < current
        assert new_confidence >= 0.0

    def test_confidence_asymmetric_adjustment(self):
        """Failures should impact more than successes."""
        current = 0.5

        success_delta = adjust_confidence(current, True) - current
        failure_delta = current - adjust_confidence(current, False)

        # Failure delta should be larger (more impact)
        assert failure_delta > success_delta

    def test_confidence_bounded_0_1(self):
        """Confidence should stay in [0, 1] range."""
        # Test upper bound
        high = adjust_confidence(0.99, success=True)
        assert high <= 1.0

        # Test lower bound
        low = adjust_confidence(0.01, success=False)
        assert low >= 0.0

    def test_diminishing_returns(self):
        """High confidence should have diminishing returns."""
        low_conf_gain = adjust_confidence(0.3, True) - 0.3
        high_conf_gain = adjust_confidence(0.9, True) - 0.9

        # Low confidence should gain more
        assert low_conf_gain > high_conf_gain


def adjust_confidence(current: float, success: bool) -> float:
    """Adjust pattern confidence based on outcome."""
    if success:
        # Slow increase with diminishing returns
        delta = 0.05 * (1 - current)
    else:
        # Fast decrease
        delta = -0.15 * current

    return max(0.0, min(1.0, current + delta))


# -----------------------------------------------------------------------------
# Pattern Graduation Tests
# -----------------------------------------------------------------------------

class TestPatternGraduation:
    """Test pattern graduation from Tier 2 to Tier 1."""

    def test_graduation_requirements(self):
        """Test all graduation requirements."""
        # Should graduate
        can_graduate = check_graduation_eligibility(
            successful_executions=15,
            confidence=0.9,
            rollbacks_last_20=0,
            approval_rate=0.98,
            days_since_first_use=21
        )
        assert can_graduate

    def test_insufficient_executions(self):
        """Should not graduate with <10 executions."""
        cannot_graduate = check_graduation_eligibility(
            successful_executions=8,  # < 10
            confidence=0.9,
            rollbacks_last_20=0,
            approval_rate=0.98,
            days_since_first_use=21
        )
        assert not cannot_graduate

    def test_low_confidence(self):
        """Should not graduate with confidence <0.85."""
        cannot_graduate = check_graduation_eligibility(
            successful_executions=15,
            confidence=0.8,  # < 0.85
            rollbacks_last_20=0,
            approval_rate=0.98,
            days_since_first_use=21
        )
        assert not cannot_graduate

    def test_recent_rollbacks(self):
        """Should not graduate with any rollbacks in last 20."""
        cannot_graduate = check_graduation_eligibility(
            successful_executions=15,
            confidence=0.9,
            rollbacks_last_20=1,  # > 0
            approval_rate=0.98,
            days_since_first_use=21
        )
        assert not cannot_graduate

    def test_low_approval_rate(self):
        """Should not graduate with approval rate <95%."""
        cannot_graduate = check_graduation_eligibility(
            successful_executions=15,
            confidence=0.9,
            rollbacks_last_20=0,
            approval_rate=0.90,  # < 0.95
            days_since_first_use=21
        )
        assert not cannot_graduate

    def test_too_recent(self):
        """Should not graduate before 14 days."""
        cannot_graduate = check_graduation_eligibility(
            successful_executions=15,
            confidence=0.9,
            rollbacks_last_20=0,
            approval_rate=0.98,
            days_since_first_use=10  # < 14
        )
        assert not cannot_graduate


def check_graduation_eligibility(
    successful_executions: int,
    confidence: float,
    rollbacks_last_20: int,
    approval_rate: float,
    days_since_first_use: int
) -> bool:
    """Check if pattern is eligible for graduation to Tier 1."""
    return (
        successful_executions >= 10 and
        confidence >= 0.85 and
        rollbacks_last_20 == 0 and
        approval_rate >= 0.95 and
        days_since_first_use >= 14
    )


# -----------------------------------------------------------------------------
# Circuit Breaker Tests
# -----------------------------------------------------------------------------

class TestCircuitBreaker:
    """Test circuit breaker conditions."""

    def test_consecutive_failures_trigger(self):
        """3+ consecutive failures should open circuit."""
        assert should_open_circuit(consecutive_failures=3)
        assert should_open_circuit(consecutive_failures=5)
        assert not should_open_circuit(consecutive_failures=2)

    def test_rollback_rate_trigger(self):
        """>20% rollback rate should open circuit."""
        assert should_open_circuit(rollback_rate=0.25)
        assert not should_open_circuit(rollback_rate=0.15)

    def test_error_spike_trigger(self):
        """>10% error rate increase should open circuit."""
        assert should_open_circuit(error_rate_increase=0.15)
        assert not should_open_circuit(error_rate_increase=0.08)

    def test_health_check_fail_trigger(self):
        """Health check failure should open circuit."""
        assert should_open_circuit(health_check_failed=True)
        assert not should_open_circuit(health_check_failed=False)


def should_open_circuit(
    consecutive_failures: int = 0,
    rollback_rate: float = 0.0,
    error_rate_increase: float = 0.0,
    health_check_failed: bool = False
) -> bool:
    """Determine if circuit breaker should open."""
    return (
        consecutive_failures >= 3 or
        rollback_rate > 0.20 or
        error_rate_increase > 0.10 or
        health_check_failed
    )


# -----------------------------------------------------------------------------
# Pre-Flight Check Tests
# -----------------------------------------------------------------------------

class TestPreFlightChecks:
    """Test pre-execution checks."""

    def test_all_checks_pass(self):
        """All checks passing should return True."""
        result = run_pre_flight_checks(
            syntax_valid=True,
            imports_ok=True,
            no_forbidden=True,
            risk_acceptable=True,
            rate_limit_ok=True,
            backup_exists=True,
            coverage_ok=True,
            complexity_ok=True,
            no_secrets=True
        )
        assert result["passed"]
        assert len(result["failed_checks"]) == 0

    def test_forbidden_path_fails(self):
        """Forbidden path should fail pre-flight."""
        result = run_pre_flight_checks(
            syntax_valid=True,
            imports_ok=True,
            no_forbidden=False,  # FAIL
            risk_acceptable=True,
            rate_limit_ok=True,
            backup_exists=True,
            coverage_ok=True,
            complexity_ok=True,
            no_secrets=True
        )
        assert not result["passed"]
        assert "no_forbidden" in result["failed_checks"]

    def test_secrets_detected_fails(self):
        """Secrets in diff should fail pre-flight."""
        result = run_pre_flight_checks(
            syntax_valid=True,
            imports_ok=True,
            no_forbidden=True,
            risk_acceptable=True,
            rate_limit_ok=True,
            backup_exists=True,
            coverage_ok=True,
            complexity_ok=True,
            no_secrets=False  # FAIL
        )
        assert not result["passed"]
        assert "no_secrets" in result["failed_checks"]


def run_pre_flight_checks(**checks) -> Dict[str, Any]:
    """Run all pre-flight checks and return result."""
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "passed": len(failed) == 0,
        "failed_checks": failed,
        "check_count": len(checks)
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
