"""Jarvis Ingestion Test Suite.

This package contains all tests for the Jarvis ingestion API.

Test Categories:
- Unit tests: Fast, isolated tests for individual functions
- Integration tests: Tests requiring external services (Redis, Qdrant, etc.)
- Phase tests: Tests for specific development phases

Run all tests:
    pytest

Run only fast tests:
    pytest -m "not slow and not integration"

Run with coverage:
    pytest --cov=app --cov-report=term-missing
"""
