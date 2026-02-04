"""
Test suite for confidence_scorer.py

Phase 0 tests (Feb 4, 2026):
  - Verify confidence scoring math (4 factors, weighted sum)
  - Test audit hash immutability
  - Test confidence level mapping
  - Test track record updates
"""

import pytest
from datetime import datetime
from ingestion.app.confidence_scorer import (
    JarvisConfidenceScorer,
    ConfidenceLevel,
    CodeChange,
    ConfidenceScore
)


class TestConfidenceScorer:
    """Tests for JarvisConfidenceScorer"""
    
    def test_score_trivial_change(self):
        """Trivial change (1–10 lines) should score high."""
        
        scorer = JarvisConfidenceScorer()
        
        change = CodeChange(
            id="change_1",
            file_path="ingestion/app/config.py",
            change_type="config",
            line_count=5,
            description="Update timeout value",
            risk_class="R0",
            diff_preview="- timeout = 30\n+ timeout = 60",
            tests_updated=True
        )
        
        score = scorer.score(change, current_phase=0)
        
        # Expected: high confidence (complexity 0.90 + type 0.80 + tests 0.95 + track 0.50) / 4 ≈ 0.79
        assert score.overall >= 0.70
        assert score.level in [ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH]
        assert score.factors["complexity"] == 0.90
    
    def test_score_large_change(self):
        """Large change (200+ lines) should score lower."""
        
        scorer = JarvisConfidenceScorer()
        
        change = CodeChange(
            id="change_2",
            file_path="ingestion/app/agent.py",
            change_type="refactor",
            line_count=350,
            description="Refactor agent loop",
            risk_class="R1",
            diff_preview="- old_code\n+ new_code",
            tests_updated=False
        )
        
        score = scorer.score(change, current_phase=0)
        
        # Expected: lower confidence (large change + refactor + no tests)
        assert score.overall < 0.60
        assert score.level == ConfidenceLevel.MEDIUM or score.level == ConfidenceLevel.LOW
    
    def test_audit_hash_immutable(self):
        """Audit hash must be deterministic and immutable."""
        
        scorer = JarvisConfidenceScorer()
        
        change = CodeChange(
            id="change_3",
            file_path="test.py",
            change_type="config",
            line_count=10,
            description="Test",
            risk_class="R0",
            diff_preview="test",
            tests_updated=True
        )
        
        score1 = scorer.score(change, current_phase=0)
        score2 = scorer.score(change, current_phase=0)
        
        # Same change → same audit hash
        assert score1.audit_hash == score2.audit_hash
    
    def test_confidence_level_mapping(self):
        """Test ConfidenceLevel.from_score() mapping."""
        
        assert ConfidenceLevel.from_score(0.10) == ConfidenceLevel.VERY_LOW
        assert ConfidenceLevel.from_score(0.40) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.60) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.80) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.95) == ConfidenceLevel.VERY_HIGH
    
    def test_feedback_update(self):
        """Test track record feedback update."""
        
        initial_history = {
            "config": {"success_rate": 0.80, "n_samples": 10}
        }
        
        scorer = JarvisConfidenceScorer(feedback_history=initial_history)
        
        # Record success
        scorer.update_feedback("config", success=True)
        
        # Check updated rate
        record = scorer.feedback_history["config"]
        assert record["n_samples"] == 11
        assert record["successes"] == 9  # 8 previous + 1 new
        assert record["success_rate"] > 0.80
    
    def test_phase_determination(self):
        """Test phase progression based on confidence + risk."""
        
        scorer = JarvisConfidenceScorer()
        
        # Low confidence, R0: Phase 0 (manual)
        score_low = scorer._determine_phase(0.50, "R0")
        assert score_low == 0
        
        # High confidence, R0: Phase 1 (conditional auto)
        score_medium = scorer._determine_phase(0.85, "R0")
        assert score_medium == 1
        
        # Very high confidence, R0: Phase 2 (auto)
        score_high = scorer._determine_phase(0.92, "R0")
        assert score_high == 2
        
        # High confidence but R2: Phase 0 (always manual for high-risk)
        score_high_risk = scorer._determine_phase(0.95, "R2")
        assert score_high_risk == 0
    
    def test_to_dict_serialization(self):
        """Test JSON serialization."""
        
        scorer = JarvisConfidenceScorer()
        
        change = CodeChange(
            id="change_4",
            file_path="test.py",
            change_type="config",
            line_count=10,
            description="Test",
            risk_class="R0",
            diff_preview="test",
            tests_updated=True
        )
        
        score = scorer.score(change, current_phase=0)
        
        # Should be JSON-serializable
        score_dict = score.to_dict()
        assert isinstance(score_dict, dict)
        assert "overall" in score_dict
        assert "factors" in score_dict
        assert score_dict["overall"] <= 1.0
        assert score_dict["overall"] >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
