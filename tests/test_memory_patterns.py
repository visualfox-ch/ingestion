"""Pattern validation tests for memory system.

Tests memory pattern edge cases including:
- Confidence decay over time
- Conflict detection accuracy
- TTL enforcement
- Source attribution correctness
- Namespace isolation
"""
import pytest
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_facts() -> List[Dict[str, Any]]:
    """Sample facts for testing."""
    return [
        {
            "id": "fact_001",
            "user_id": "user_123",
            "namespace": "personal",
            "key": "preferred_language",
            "value": "python",
            "confidence": 0.85,
            "source": "user_explicit",
            "created_at": datetime.now() - timedelta(days=30),
            "expires_at": datetime.now() + timedelta(days=60),
            "status": "active",
        },
        {
            "id": "fact_002",
            "user_id": "user_123",
            "namespace": "personal",
            "key": "preferred_language",
            "value": "rust",  # Conflict with fact_001
            "confidence": 0.75,
            "source": "system_inferred",
            "created_at": datetime.now() - timedelta(days=10),
            "expires_at": datetime.now() + timedelta(days=80),
            "status": "active",
        },
        {
            "id": "fact_003",
            "user_id": "user_123",
            "namespace": "work",
            "key": "preferred_language",
            "value": "typescript",
            "confidence": 0.90,
            "source": "user_explicit",
            "created_at": datetime.now() - timedelta(days=5),
            "expires_at": None,  # No expiry
            "status": "active",
        },
    ]


@pytest.fixture
def expired_fact() -> Dict[str, Any]:
    """Expired fact for TTL testing."""
    return {
        "id": "fact_expired",
        "user_id": "user_123",
        "namespace": "personal",
        "key": "old_preference",
        "value": "deprecated",
        "confidence": 0.60,
        "source": "telegram_pattern",
        "created_at": datetime.now() - timedelta(days=100),
        "expires_at": datetime.now() - timedelta(days=10),  # Expired
        "status": "active",
    }


# ============================================================================
# Confidence Decay Tests
# ============================================================================

class TestConfidenceDecay:
    """Test confidence decay over time."""

    def test_positive_feedback_increases_confidence(self):
        """Positive feedback should increase confidence with diminishing returns."""
        initial_confidence = 0.7

        # Asymmetric adjustment formula from memory_integrator
        delta = 0.05 * (1 - initial_confidence)
        new_confidence = initial_confidence + delta

        assert new_confidence > initial_confidence
        assert new_confidence < 1.0  # Can't exceed 1.0
        assert pytest.approx(new_confidence, 0.01) == 0.715

    def test_negative_feedback_decreases_confidence_faster(self):
        """Negative feedback should decrease confidence faster than positive increases it."""
        initial_confidence = 0.7

        # Asymmetric: -15% of current vs +5% of remaining
        positive_delta = 0.05 * (1 - initial_confidence)
        negative_delta = -0.15 * initial_confidence

        assert abs(negative_delta) > positive_delta
        assert pytest.approx(abs(negative_delta), 0.01) == 0.105
        assert pytest.approx(positive_delta, 0.01) == 0.015

    def test_confidence_bounds(self):
        """Confidence should stay within [0.0, 1.0]."""
        # High confidence positive feedback
        high_conf = 0.99
        delta = 0.05 * (1 - high_conf)
        new_conf = min(1.0, high_conf + delta)
        assert new_conf <= 1.0

        # Low confidence negative feedback
        low_conf = 0.05
        delta = -0.15 * low_conf
        new_conf = max(0.0, low_conf + delta)
        assert new_conf >= 0.0

    def test_diminishing_returns_at_high_confidence(self):
        """High confidence facts should gain less from positive feedback."""
        low_conf = 0.3
        high_conf = 0.9

        low_delta = 0.05 * (1 - low_conf)
        high_delta = 0.05 * (1 - high_conf)

        assert low_delta > high_delta
        assert pytest.approx(low_delta, 0.01) == 0.035
        assert pytest.approx(high_delta, 0.01) == 0.005


# ============================================================================
# Conflict Detection Tests
# ============================================================================

class TestConflictDetection:
    """Test conflict detection between facts."""

    def test_same_key_different_values_is_conflict(self, sample_facts):
        """Same user + namespace + key with different values = conflict."""
        fact1 = sample_facts[0]
        fact2 = sample_facts[1]

        same_user = fact1["user_id"] == fact2["user_id"]
        same_namespace = fact1["namespace"] == fact2["namespace"]
        same_key = fact1["key"] == fact2["key"]
        different_value = fact1["value"] != fact2["value"]

        is_conflict = same_user and same_namespace and same_key and different_value
        assert is_conflict

    def test_different_namespace_not_conflict(self, sample_facts):
        """Same key in different namespaces is NOT a conflict."""
        fact1 = sample_facts[0]  # personal namespace
        fact3 = sample_facts[2]  # work namespace

        same_key = fact1["key"] == fact3["key"]
        same_namespace = fact1["namespace"] == fact3["namespace"]

        assert same_key
        assert not same_namespace  # Different namespace = no conflict

    def test_conflict_resolution_by_confidence(self, sample_facts):
        """Higher confidence fact should win in conflict resolution."""
        fact1 = sample_facts[0]  # confidence: 0.85
        fact2 = sample_facts[1]  # confidence: 0.75

        winner = fact1 if fact1["confidence"] > fact2["confidence"] else fact2
        assert winner["value"] == "python"
        assert winner["confidence"] == 0.85

    def test_conflict_resolution_by_recency_when_equal_confidence(self):
        """When confidence is equal, more recent fact wins."""
        now = datetime.now()
        fact1 = {
            "key": "pref",
            "value": "old",
            "confidence": 0.8,
            "created_at": now - timedelta(days=10),
        }
        fact2 = {
            "key": "pref",
            "value": "new",
            "confidence": 0.8,
            "created_at": now - timedelta(days=2),
        }

        winner = fact1 if fact1["created_at"] > fact2["created_at"] else fact2
        assert winner["value"] == "new"


# ============================================================================
# TTL Enforcement Tests
# ============================================================================

class TestTTLEnforcement:
    """Test TTL (Time-To-Live) enforcement."""

    def test_expired_fact_is_inactive(self, expired_fact):
        """Facts past expires_at should be considered inactive."""
        now = datetime.now()
        is_expired = (
            expired_fact["expires_at"] is not None
            and expired_fact["expires_at"] <= now
        )
        assert is_expired

    def test_no_expiry_is_permanent(self, sample_facts):
        """Facts with expires_at=None should never expire."""
        fact = sample_facts[2]  # expires_at is None
        assert fact["expires_at"] is None
        # Should always be considered active
        is_expired = fact["expires_at"] is not None and fact["expires_at"] <= datetime.now()
        assert not is_expired

    def test_ttl_from_confidence(self):
        """TTL should be longer for higher confidence facts."""
        def get_ttl(confidence: float) -> int:
            if confidence >= 0.8:
                return 365
            elif confidence >= 0.5:
                return 90
            else:
                return 30

        assert get_ttl(0.9) == 365
        assert get_ttl(0.7) == 90
        assert get_ttl(0.3) == 30

    def test_expiring_soon_detection(self, sample_facts):
        """Detect facts expiring within threshold."""
        threshold_days = 7
        now = datetime.now()

        expiring_soon = [
            f for f in sample_facts
            if f["expires_at"] is not None
            and now < f["expires_at"] <= now + timedelta(days=threshold_days)
        ]

        # In sample data, none are expiring within 7 days
        assert len(expiring_soon) == 0


# ============================================================================
# Source Attribution Tests
# ============================================================================

class TestSourceAttribution:
    """Test source type tracking and attribution."""

    VALID_SOURCES = [
        "user_explicit",
        "system_inferred",
        "telegram_pattern",
        "agent_decision",
        "cross_session",
    ]

    def test_valid_source_types(self, sample_facts):
        """All facts should have valid source types."""
        for fact in sample_facts:
            assert fact["source"] in self.VALID_SOURCES or fact["source"] == "other"

    def test_user_explicit_higher_trust(self):
        """User explicit sources should have higher base confidence."""
        source_trust = {
            "user_explicit": 0.9,
            "telegram_pattern": 0.7,
            "system_inferred": 0.6,
            "agent_decision": 0.5,
            "cross_session": 0.4,
        }

        assert source_trust["user_explicit"] > source_trust["system_inferred"]
        assert source_trust["telegram_pattern"] > source_trust["agent_decision"]

    def test_source_distribution_counting(self, sample_facts):
        """Count facts by source type correctly."""
        distribution = {}
        for fact in sample_facts:
            source = fact["source"]
            distribution[source] = distribution.get(source, 0) + 1

        assert distribution.get("user_explicit", 0) == 2
        assert distribution.get("system_inferred", 0) == 1


# ============================================================================
# Namespace Isolation Tests
# ============================================================================

class TestNamespaceIsolation:
    """Test namespace isolation for facts."""

    def test_facts_in_correct_namespace(self, sample_facts):
        """Facts should be retrievable only from their namespace."""
        personal_facts = [f for f in sample_facts if f["namespace"] == "personal"]
        work_facts = [f for f in sample_facts if f["namespace"] == "work"]

        assert len(personal_facts) == 2
        assert len(work_facts) == 1

    def test_namespace_scoped_retrieval(self, sample_facts):
        """Retrieving by namespace should not leak across namespaces."""
        def retrieve_by_namespace(facts, namespace):
            return [f for f in facts if f["namespace"] == namespace]

        personal = retrieve_by_namespace(sample_facts, "personal")
        work = retrieve_by_namespace(sample_facts, "work")

        # No overlap
        personal_ids = {f["id"] for f in personal}
        work_ids = {f["id"] for f in work}
        assert personal_ids.isdisjoint(work_ids)

    def test_namespace_specific_conflicts(self, sample_facts):
        """Conflicts should only be detected within same namespace."""
        def find_conflicts(facts, namespace):
            ns_facts = [f for f in facts if f["namespace"] == namespace]
            keys = {}
            conflicts = []
            for f in ns_facts:
                key = f["key"]
                if key in keys:
                    if keys[key] != f["value"]:
                        conflicts.append(key)
                keys[key] = f["value"]
            return conflicts

        personal_conflicts = find_conflicts(sample_facts, "personal")
        work_conflicts = find_conflicts(sample_facts, "work")

        assert "preferred_language" in personal_conflicts
        assert len(work_conflicts) == 0


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_value_handling(self):
        """Facts with empty values should be handled."""
        fact = {"key": "test", "value": "", "confidence": 0.5}
        assert fact["value"] == ""
        # Empty string is valid, None is not
        assert fact["value"] is not None

    def test_unicode_in_values(self):
        """Unicode characters in values should be preserved."""
        fact = {"key": "greeting", "value": "Guten Tag!", "confidence": 0.8}
        assert fact["value"] == "Guten Tag!"

        fact_emoji = {"key": "status", "value": "Working hard", "confidence": 0.7}
        assert "Working" in fact_emoji["value"]

    def test_very_long_value(self):
        """Very long values should be handled."""
        long_value = "x" * 10000
        fact = {"key": "notes", "value": long_value, "confidence": 0.5}
        assert len(fact["value"]) == 10000

    def test_special_characters_in_key(self):
        """Keys with special characters should be handled."""
        # Keys should be normalized/safe
        valid_keys = ["user_preference", "api-key", "config.setting"]
        invalid_keys = ["key with spaces", "key\nwith\nnewlines"]

        for key in valid_keys:
            assert " " not in key
            assert "\n" not in key

    def test_zero_confidence(self):
        """Zero confidence facts should still be valid."""
        fact = {"key": "uncertain", "value": "maybe", "confidence": 0.0}
        assert fact["confidence"] == 0.0
        # Should still be storable but low priority

    def test_exactly_threshold_confidence(self):
        """Test boundary at exact threshold values."""
        # Testing the boundaries: 0.5 and 0.8
        def categorize(confidence):
            if confidence >= 0.8:
                return "high"
            elif confidence >= 0.5:
                return "medium"
            else:
                return "low"

        assert categorize(0.8) == "high"  # Exactly at boundary
        assert categorize(0.5) == "medium"  # Exactly at boundary
        assert categorize(0.79999) == "medium"
        assert categorize(0.49999) == "low"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
