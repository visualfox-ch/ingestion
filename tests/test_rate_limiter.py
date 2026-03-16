"""Tests for rate limiter endpoint tier mapping."""

from app.rate_limiter import get_tier_for_endpoint


def test_transparency_exact_endpoints_use_readonly():
    assert get_tier_for_endpoint("/api/v1/transparency/docs/list") == "readonly"
    assert get_tier_for_endpoint("/api/v1/transparency/docs/current-phase") == "readonly"
    assert get_tier_for_endpoint("/api/v1/transparency/docs/tasks/active") == "readonly"
    assert get_tier_for_endpoint("/api/v1/transparency/stats") == "readonly"


def test_transparency_doc_prefix_uses_normal():
    assert get_tier_for_endpoint("/api/v1/transparency/docs/roadmap") == "normal"
    assert get_tier_for_endpoint("/api/v1/transparency/docs/memory") == "normal"


def test_default_tiers():
    assert get_tier_for_endpoint("/ingest_drive") == "ingest"
    assert get_tier_for_endpoint("/some/unknown/path") == "normal"
