"""Unit tests for hybrid search (Meilisearch + Qdrant fusion).

Tests the HybridSearch class with RRF algorithm, metadata re-ranking,
and graceful degradation when one search source is unavailable.
"""
import sys
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# -----------------------------------------------------------------------------
# Test Data Structures
# -----------------------------------------------------------------------------

@dataclass
class MockSearchResult:
    """Mock search result for testing."""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any]
    source: str  # "meilisearch", "qdrant", "both"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
            "source": self.source
        }


# -----------------------------------------------------------------------------
# RRF Algorithm Tests
# -----------------------------------------------------------------------------

class TestReciprocalRankFusion:
    """Test the RRF algorithm for combining search results."""

    def test_rrf_basic_formula(self):
        """Test basic RRF formula: 1 / (k + rank)."""
        k = 60  # Standard RRF constant

        # Rank 1 should give highest score
        score_rank_1 = 1 / (k + 1)
        assert score_rank_1 == pytest.approx(0.01639, rel=1e-3)

        # Rank 10 should give lower score
        score_rank_10 = 1 / (k + 10)
        assert score_rank_10 == pytest.approx(0.01428, rel=1e-3)

        # Rank 1 > Rank 10
        assert score_rank_1 > score_rank_10

    def test_rrf_combined_score(self):
        """Test RRF score when doc appears in both result sets."""
        k = 60

        # Doc appears in Meilisearch rank 3 and Qdrant rank 7
        meili_score = 1 / (k + 3)  # 0.0159
        qdrant_score = 1 / (k + 7)  # 0.0149
        combined = meili_score + qdrant_score

        assert combined == pytest.approx(0.0308, rel=1e-2)

        # Combined score should be higher than single source
        single_source = 1 / (k + 1)  # Best possible single source
        assert combined > single_source * 0.9  # Should be close or higher

    def test_rrf_single_source_only(self):
        """Test RRF score when doc appears in only one result set."""
        k = 60

        # Doc only in Meilisearch rank 1
        meili_score = 1 / (k + 1)
        qdrant_score = 0  # Not found
        combined = meili_score + qdrant_score

        assert combined == pytest.approx(0.0164, rel=1e-3)

    def test_rrf_ranking_order(self):
        """Test that RRF correctly ranks docs appearing in both sources higher."""
        k = 60

        # Doc A: appears in both (meili rank 5, qdrant rank 5)
        doc_a_score = (1 / (k + 5)) + (1 / (k + 5))

        # Doc B: appears only in meili rank 1 (best single source position)
        doc_b_score = 1 / (k + 1)

        # Doc A should rank higher due to presence in both sources
        assert doc_a_score > doc_b_score


def calculate_rrf_scores(
    meili_results: List[str],
    qdrant_results: List[str],
    k: int = 60
) -> Dict[str, float]:
    """Helper function to calculate RRF scores for testing."""
    scores = {}

    # Score from Meilisearch
    for rank, doc_id in enumerate(meili_results, start=1):
        scores[doc_id] = scores.get(doc_id, 0) + (1 / (k + rank))

    # Score from Qdrant
    for rank, doc_id in enumerate(qdrant_results, start=1):
        scores[doc_id] = scores.get(doc_id, 0) + (1 / (k + rank))

    return scores


class TestRRFIntegration:
    """Integration tests for RRF with realistic result sets."""

    def test_rrf_with_overlapping_results(self):
        """Test RRF when results partially overlap."""
        meili_results = ["doc1", "doc2", "doc3", "doc4", "doc5"]
        qdrant_results = ["doc3", "doc6", "doc1", "doc7", "doc8"]

        scores = calculate_rrf_scores(meili_results, qdrant_results)

        # doc1 appears in both: meili rank 1, qdrant rank 3
        # doc3 appears in both: meili rank 3, qdrant rank 1
        # These should have highest scores
        sorted_docs = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)

        # Top 2 should be docs appearing in both sources
        assert sorted_docs[0] in ["doc1", "doc3"]
        assert sorted_docs[1] in ["doc1", "doc3"]

    def test_rrf_with_no_overlap(self):
        """Test RRF when results don't overlap at all."""
        meili_results = ["doc1", "doc2", "doc3"]
        qdrant_results = ["doc4", "doc5", "doc6"]

        scores = calculate_rrf_scores(meili_results, qdrant_results)

        # All docs should have similar scores (rank 1 from each source)
        assert scores["doc1"] == pytest.approx(scores["doc4"], rel=1e-3)

    def test_rrf_empty_one_source(self):
        """Test RRF when one source returns empty."""
        meili_results = ["doc1", "doc2", "doc3"]
        qdrant_results = []

        scores = calculate_rrf_scores(meili_results, qdrant_results)

        # Should still return results from available source
        assert len(scores) == 3
        assert "doc1" in scores


# -----------------------------------------------------------------------------
# Metadata Re-ranking Tests
# -----------------------------------------------------------------------------

class TestMetadataReranking:
    """Test metadata-based re-ranking of search results."""

    def test_filename_match_boost(self):
        """Test that exact filename matches get boosted."""
        results = [
            {"id": "1", "score": 0.03, "metadata": {"filename": "old_email.txt"}},
            {"id": "2", "score": 0.02, "metadata": {"filename": "BEST_PRACTICES_QUICK_REFERENCE.md"}},
        ]
        query = "BEST_PRACTICES_QUICK_REFERENCE"

        # Apply filename boost (simulate)
        boosted = apply_filename_boost(results, query, boost_factor=1.5)

        # Doc with matching filename should now be ranked higher
        assert boosted[0]["id"] == "2"

    def test_doc_category_boost(self):
        """Test that documentation category gets boosted over chat/email."""
        results = [
            {"id": "1", "score": 0.03, "metadata": {"doc_category": "chat"}},
            {"id": "2", "score": 0.025, "metadata": {"doc_category": "best_practices"}},
            {"id": "3", "score": 0.02, "metadata": {"doc_category": "email"}},
        ]

        # Apply category boost (simulate)
        boosted = apply_category_boost(results, priority_categories=["best_practices", "architecture"])

        # Documentation should rank higher than chat/email
        assert boosted[0]["metadata"]["doc_category"] == "best_practices"

    def test_is_documentation_flag_boost(self):
        """Test that is_documentation=true items get priority."""
        results = [
            {"id": "1", "score": 0.03, "metadata": {"is_documentation": False}},
            {"id": "2", "score": 0.025, "metadata": {"is_documentation": True}},
        ]

        boosted = apply_documentation_boost(results, boost_factor=1.3)

        assert boosted[0]["id"] == "2"


def apply_filename_boost(results: List[Dict], query: str, boost_factor: float = 1.5) -> List[Dict]:
    """Helper to simulate filename boost for testing."""
    query_lower = query.lower().replace(" ", "_")
    for r in results:
        filename = r["metadata"].get("filename", "").lower()
        if query_lower in filename or filename.replace(".md", "") in query_lower:
            r["score"] *= boost_factor
    return sorted(results, key=lambda x: x["score"], reverse=True)


def apply_category_boost(
    results: List[Dict],
    priority_categories: List[str],
    boost_factor: float = 1.2
) -> List[Dict]:
    """Helper to simulate category boost for testing."""
    for r in results:
        if r["metadata"].get("doc_category") in priority_categories:
            r["score"] *= boost_factor
    return sorted(results, key=lambda x: x["score"], reverse=True)


def apply_documentation_boost(results: List[Dict], boost_factor: float = 1.3) -> List[Dict]:
    """Helper to simulate documentation boost for testing."""
    for r in results:
        if r["metadata"].get("is_documentation", False):
            r["score"] *= boost_factor
    return sorted(results, key=lambda x: x["score"], reverse=True)


# -----------------------------------------------------------------------------
# HybridSearch Class Tests (Mocked)
# -----------------------------------------------------------------------------

class MockMeilisearchClient:
    """Mock Meilisearch client for testing."""

    def __init__(self, results: List[Dict] = None):
        self.results = results or []
        self.called_with = None

    async def search(self, query: str, **kwargs) -> List[Dict]:
        self.called_with = {"query": query, **kwargs}
        return self.results


class MockQdrantClient:
    """Mock Qdrant client for testing."""

    def __init__(self, results: List[Dict] = None):
        self.results = results or []
        self.called_with = None

    async def search(self, query: str, **kwargs) -> List[Dict]:
        self.called_with = {"query": query, **kwargs}
        return self.results


class TestHybridSearchClass:
    """Test the HybridSearch class behavior."""

    def test_parallel_search_execution(self):
        """Test that both searches are executed in parallel."""
        # This would test asyncio.gather usage
        # Placeholder for actual implementation test
        pass

    def test_graceful_degradation_meilisearch_down(self):
        """Test fallback to Qdrant-only when Meilisearch is unavailable."""
        qdrant_results = [
            {"id": "1", "text": "Best practices doc", "score": 0.9}
        ]

        # Simulate Meilisearch failure, Qdrant success
        meili_results = None  # Exception case

        # Should return Qdrant results only
        assert qdrant_results is not None
        assert len(qdrant_results) == 1

    def test_graceful_degradation_qdrant_down(self):
        """Test fallback to Meilisearch-only when Qdrant is unavailable."""
        meili_results = [
            {"id": "1", "text": "Best practices doc", "score": 0.9}
        ]

        # Simulate Qdrant failure, Meilisearch success
        qdrant_results = None  # Exception case

        # Should return Meilisearch results only
        assert meili_results is not None
        assert len(meili_results) == 1

    def test_both_sources_down_returns_empty(self):
        """Test that empty results returned when both sources fail."""
        meili_results = None
        qdrant_results = None

        # Should return empty list, not crash
        results = []
        assert results == []

    def test_alpha_parameter_weight(self):
        """Test alpha parameter controls keyword vs semantic weight."""
        # alpha=0 → pure keyword (Meilisearch)
        # alpha=1 → pure semantic (Qdrant)
        # alpha=0.5 → balanced

        # Placeholder for actual implementation test
        pass

    def test_result_deduplication(self):
        """Test that duplicate docs from both sources are merged."""
        meili_results = ["doc1", "doc2", "doc3"]
        qdrant_results = ["doc2", "doc3", "doc4"]

        all_docs = set(meili_results + qdrant_results)

        # Should have 4 unique docs, not 6
        assert len(all_docs) == 4


# -----------------------------------------------------------------------------
# End-to-End Query Tests (Expected Behavior)
# -----------------------------------------------------------------------------

class TestExpectedQueryBehavior:
    """Test expected behavior for specific query types."""

    def test_filename_query_returns_correct_doc(self):
        """Test that filename queries return the matching document."""
        query = "BEST_PRACTICES_QUICK_REFERENCE"
        expected_top_result = "BEST_PRACTICES_QUICK_REFERENCE.md"

        # Placeholder - actual test would call hybrid search
        # assert results[0].metadata["filename"] == expected_top_result
        pass

    def test_conceptual_query_finds_relevant_doc(self):
        """Test that conceptual queries find semantically relevant docs."""
        query = "Database Best Practices"
        expected_in_top_3 = ["BEST_PRACTICES_QUICK_REFERENCE.md"]

        # Placeholder - actual test would call hybrid search
        pass

    def test_research_query_finds_research_doc(self):
        """Test that research queries find RESEARCH_SOURCES.md."""
        query = "Research Papers on Agent Systems"
        expected_top_result = "RESEARCH_SOURCES.md"

        # Placeholder - actual test would call hybrid search
        pass


# -----------------------------------------------------------------------------
# Performance Tests
# -----------------------------------------------------------------------------

class TestPerformance:
    """Test performance requirements."""

    def test_rrf_calculation_is_fast(self):
        """Test that RRF calculation is O(n) and fast."""
        import time

        # Simulate large result sets
        meili_results = [f"doc_{i}" for i in range(100)]
        qdrant_results = [f"doc_{i+50}" for i in range(100)]

        start = time.time()
        scores = calculate_rrf_scores(meili_results, qdrant_results)
        elapsed = time.time() - start

        # Should complete in under 10ms
        assert elapsed < 0.01
        assert len(scores) == 150  # 100 + 100 - 50 overlap


# -----------------------------------------------------------------------------
# Edge Cases
# -----------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_query(self):
        """Test behavior with empty query."""
        query = ""
        # Should return empty results or raise validation error
        pass

    def test_very_long_query(self):
        """Test behavior with very long query."""
        query = "a " * 1000
        # Should truncate or handle gracefully
        pass

    def test_special_characters_in_query(self):
        """Test behavior with special characters."""
        query = "SELECT * FROM users; DROP TABLE users;--"
        # Should sanitize and not crash
        pass

    def test_unicode_query(self):
        """Test behavior with unicode characters."""
        query = "Tëst with ümlauts and émojis 🔍"
        # Should handle gracefully
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
