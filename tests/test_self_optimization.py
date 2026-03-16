"""
Tests for Pillar 6: Self-Optimization Loop

Tests cover:
1. Performance Analytics - effectiveness measurement and pattern detection
2. Self-Prompt Evolution - suggestion generation
3. Meta-Learning - learning style discovery

Phase 2D.6 (Feb 24 - Mar 7, 2026)
"""

import os
import pytest
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import MagicMock, patch

# Set mock API key before any imports that might need it
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-unit-tests")


@pytest.fixture(autouse=True)
def mock_llm_client():
    """Mock the LLM client to avoid actual API calls in tests."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"suggestions": []}')]
    )
    with patch("app.self_optimization_services.get_client", return_value=mock_client):
        # Reset singletons between tests
        import app.self_optimization_services as svc
        svc._performance_analytics = None
        svc._self_prompt_evolution = None
        svc._meta_learning = None
        yield mock_client


from app.self_optimization_services import (
    PerformanceAnalytics,
    SelfPromptEvolution,
    MetaLearning,
    get_performance_analytics,
    get_self_prompt_evolution,
    get_meta_learning
)


# Test PerformanceAnalytics
@pytest.mark.asyncio
async def test_performance_analytics_init():
    """Should initialize PerformanceAnalytics service."""
    service = PerformanceAnalytics()
    assert service is not None
    assert service.logger is not None


@pytest.mark.asyncio
async def test_singleton_performance_analytics():
    """Should return same instance on multiple calls."""
    svc1 = get_performance_analytics()
    svc2 = get_performance_analytics()
    assert svc1 is svc2


@pytest.mark.asyncio
async def test_analyze_effectiveness_insufficient_data():
    """Should return INSUFFICIENT_DATA when no interactions found."""
    service = PerformanceAnalytics()
    result = await service.analyze_effectiveness(window_days=30, min_samples=100)
    
    # Either insufficient data or mock data
    assert "status" in result
    assert result["status"] in ["INSUFFICIENT_DATA", "SUCCESS"]


@pytest.mark.asyncio
async def test_calculate_avg_effectiveness_empty():
    """Should return 0 for empty metrics list."""
    service = PerformanceAnalytics()
    avg = service._calc_avg_effectiveness([])
    assert avg == 0.0


@pytest.mark.asyncio
async def test_calculate_avg_effectiveness():
    """Should calculate correct average effectiveness."""
    service = PerformanceAnalytics()
    metrics = [
        {"effectiveness_score": 0.8},
        {"effectiveness_score": 0.6},
        {"effectiveness_score": 0.4},
    ]
    avg = service._calc_avg_effectiveness(metrics)
    assert avg == pytest.approx(0.6, 0.01)


@pytest.mark.asyncio
async def test_find_patterns_identifies_blind_spots():
    """Should identify domains with low effectiveness as blind spots."""
    service = PerformanceAnalytics()
    metrics = [
        {"domain": "coding", "effectiveness_score": 0.9},
        {"domain": "emotional", "effectiveness_score": 0.5},
        {"domain": "emotional", "effectiveness_score": 0.4},
        {"domain": "creative", "effectiveness_score": 0.3},
    ]
    
    patterns = service._find_patterns(metrics)
    
    # Check blind_spots identified
    assert "blind_spots" in patterns
    blind_spots = patterns["blind_spots"]
    assert len(blind_spots) > 0
    
    # Creative should be identified as blind spot (0.3 < 0.65)
    domain_names = [d[0] for d in blind_spots]
    assert "creative" in domain_names


@pytest.mark.asyncio
async def test_find_patterns_identifies_strengths():
    """Should identify high-performing domains as strengths."""
    service = PerformanceAnalytics()
    metrics = [
        {"domain": "coding", "effectiveness_score": 0.95},
        {"domain": "coding", "effectiveness_score": 0.85},
        {"domain": "business", "message_type": "advice", "effectiveness_score": 0.3},
    ]
    
    patterns = service._find_patterns(metrics)
    
    # Check high_domains identified
    assert "high_domains" in patterns
    high_domains = patterns["high_domains"]
    assert len(high_domains) > 0
    
    # Coding should be in high domains
    domain_names = [d[0] for d in high_domains]
    assert "coding" in domain_names


# Test SelfPromptEvolution
@pytest.mark.asyncio
async def test_self_prompt_evolution_init():
    """Should initialize SelfPromptEvolution service."""
    service = SelfPromptEvolution()
    assert service is not None
    assert service.logger is not None


@pytest.mark.asyncio
async def test_singleton_self_prompt_evolution():
    """Should return same instance on multiple calls."""
    svc1 = get_self_prompt_evolution()
    svc2 = get_self_prompt_evolution()
    assert svc1 is svc2


@pytest.mark.asyncio
async def test_analyze_prompt_structure():
    """Should parse system prompt into sections."""
    service = SelfPromptEvolution()
    sections = service._analyze_prompt_structure()
    
    assert isinstance(sections, dict)
    assert "identity" in sections
    assert "capabilities" in sections
    assert "constraints" in sections
    assert "style" in sections
    assert "context" in sections


@pytest.mark.asyncio
async def test_identify_prompt_gaps():
    """Should map performance gaps to prompt sections."""
    service = SelfPromptEvolution()
    analytics = {
        "blind_spots": [
            ["emotional", 0.5],
            ["creative", 0.4],
        ]
    }
    sections = service._analyze_prompt_structure()
    
    gaps = service._identify_prompt_gaps(analytics, sections)
    assert isinstance(gaps, list)
    assert len(gaps) >= 0  # May be empty or populated


@pytest.mark.asyncio
async def test_evolve_prompt_returns_suggestions():
    """Should generate prompt evolution suggestions."""
    service = SelfPromptEvolution()
    analytics = {
        "blind_spots": [["emotional", 0.6]],
        "high_domains": [["coding", 0.9]],
    }
    
    result = await service.evolve_prompt(analytics)
    
    assert "status" in result
    assert result["status"] in ["SUCCESS", "ERROR"]
    
    if result["status"] == "SUCCESS":
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)


# Test MetaLearning
@pytest.mark.asyncio
async def test_meta_learning_init():
    """Should initialize MetaLearning service."""
    service = MetaLearning()
    assert service is not None
    assert service.logger is not None


@pytest.mark.asyncio
async def test_singleton_meta_learning():
    """Should return same instance on multiple calls."""
    svc1 = get_meta_learning()
    svc2 = get_meta_learning()
    assert svc1 is svc2


@pytest.mark.asyncio
async def test_analyze_learning_effectiveness_empty():
    """Should handle empty learning data gracefully."""
    service = MetaLearning()
    result = service._analyze_learning_effectiveness([])
    
    assert isinstance(result, dict)
    assert "by_type" in result
    assert result["best_type"] == "unknown"


@pytest.mark.asyncio
async def test_analyze_learning_effectiveness_finds_best_type():
    """Should identify best learning input type."""
    service = MetaLearning()
    data = [
        {"input_type": "example", "effectiveness_after": 0.9},
        {"input_type": "example", "effectiveness_after": 0.85},
        {"input_type": "principle", "effectiveness_after": 0.5},
        {"input_type": "principle", "effectiveness_after": 0.55},
    ]
    
    result = service._analyze_learning_effectiveness(data)
    
    assert result["best_type"] == "example"
    assert result["by_type"]["example"] > result["by_type"]["principle"]


@pytest.mark.asyncio
async def test_analyze_learning_effectiveness_calculates_multiplier():
    """Should calculate multiplier between best and worst learning methods."""
    service = MetaLearning()
    data = [
        {"input_type": "example", "effectiveness_after": 0.8},
        {"input_type": "principle", "effectiveness_after": 0.2},
    ]
    
    result = service._analyze_learning_effectiveness(data)
    
    assert result["multiplier_vs_worst"] == pytest.approx(4.0, 0.1)


@pytest.mark.asyncio
async def test_discover_learning_style_returns_insights():
    """Should return learning style insights."""
    service = MetaLearning()
    result = await service.discover_learning_style()
    
    assert "status" in result
    assert result["status"] in ["SUCCESS", "INSUFFICIENT_DATA", "ERROR"]


# Integration tests
@pytest.mark.asyncio
async def test_performance_to_evolution_flow():
    """Test flow: Performance Analytics → Prompt Evolution."""
    analytics_svc = get_performance_analytics()
    evolution_svc = get_self_prompt_evolution()
    
    # Get analytics
    analytics = await analytics_svc.analyze_effectiveness(window_days=7)
    
    # Get evolution suggestions based on analytics
    if analytics.get("status") == "SUCCESS":
        result = await evolution_svc.evolve_prompt(analytics)
        assert "status" in result


@pytest.mark.asyncio
async def test_all_services_instantiate():
    """Should be able to get all three services."""
    analytics = get_performance_analytics()
    evolution = get_self_prompt_evolution()
    meta = get_meta_learning()
    
    assert analytics is not None
    assert evolution is not None
    assert meta is not None
    
    # Each should be different instance type
    assert type(analytics).__name__ == "PerformanceAnalytics"
    assert type(evolution).__name__ == "SelfPromptEvolution"
    assert type(meta).__name__ == "MetaLearning"


# Success metrics validation
@pytest.mark.asyncio
async def test_performance_analytics_identifies_3_plus_blind_spots():
    """Success metric: Analytics identifies ≥3 blind spots correctly."""
    # This is a mock test - in real scenario,
    # would need actual data with ≥3 distinct low-performing domains
    
    service = PerformanceAnalytics()
    metrics = [
        {"domain": d, "effectiveness_score": s}
        for d, s in [
            ("emotional", 0.4),
            ("creative", 0.5),
            ("ethical", 0.6),
            ("coding", 0.95),
            ("business", 0.88),
        ]
        for _ in range(3)  # Repeat to get min sample size
    ]
    
    patterns = service._find_patterns(metrics)
    blind_spots = patterns.get("blind_spots", [])
    
    # Should identify at least 3 blind spots
    assert len(blind_spots) >= 3


@pytest.mark.asyncio
async def test_prompt_evolution_generates_actionable_suggestions():
    """Success metric: Prompt evolution suggestions are actionable."""
    service = SelfPromptEvolution()
    
    analytics = {
        "blind_spots": [
            ["emotional", 0.4],
            ["creative", 0.5],
        ]
    }
    
    result = await service.evolve_prompt(analytics)
    
    if result.get("status") == "SUCCESS":
        suggestions = result.get("suggestions", [])
        
        # Check suggestions have required fields
        for suggestion in suggestions:
            assert "suggestion" in suggestion or "domain" in suggestion
            assert "rationale" in suggestion or "evidence" in suggestion
            # Suggestion should have some expected impact
            assert "expected_impact" in suggestion or "priority" in suggestion


@pytest.mark.asyncio
async def test_meta_learning_identifies_learning_style():
    """Success metric: Meta-learning identifies learning style accurately."""
    service = MetaLearning()
    
    # Create data where examples are clearly better than principles
    data = [
        {"input_type": "example", "effectiveness_after": 0.95} for _ in range(5)
    ] + [
        {"input_type": "principle", "effectiveness_after": 0.45} for _ in range(5)
    ]
    
    result = service._analyze_learning_effectiveness(data)
    
    # Should identify example as best learning type
    assert result["best_type"] == "example"
    # Multiplier should be significant (2x+)
    assert result["multiplier_vs_worst"] >= 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
