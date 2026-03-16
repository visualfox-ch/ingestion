"""Tests for persistent learning tool helpers.

NOTE: These tests are for a future feature (persistent learning storage).
The app.persistent_learn module and related tool functions are not yet implemented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Skip all tests in this module - persistent_learn module not yet implemented
pytestmark = pytest.mark.skip(reason="persistent_learn module not yet implemented")

from app import tools
from app.persistent_learn import storage


def test_tool_persist_learning_stores_fact(monkeypatch):
    calls = {}

    def _mock_record_fact(**kwargs):
        calls.update(kwargs)
        return {
            "id": "fact-123",
            "status": "active",
            "created_at": "2026-02-05T00:00:00Z",
            "expires_at": None,
        }

    monkeypatch.setattr(storage, "record_fact", _mock_record_fact)

    result = tools.tool_persist_learning(
        user_id="user-1",
        namespace="work_projektil",
        key="preferred_tone",
        value={"tone": "direct"},
        source="user_explicit",
        confidence=0.9,
        sensitivity="low",
        reason="confirmed",
        context={"origin": "test"},
        session_id="sess-1",
    )

    assert result["status"] == "stored"
    assert result["record"]["id"] == "fact-123"
    assert calls["user_id"] == "user-1"
    assert calls["key"] == "preferred_tone"
    assert calls["context"]["session_id"] == "sess-1"


def test_tool_persist_learning_rejects_invalid_sensitivity():
    result = tools.tool_persist_learning(
        user_id="user-1",
        namespace="work_projektil",
        key="preferred_tone",
        value={"tone": "direct"},
        sensitivity="invalid",
    )

    assert result["error"] == "Invalid sensitivity"


def test_tool_recall_learning(monkeypatch):
    def _mock_retrieve(**kwargs):
        return [
            {
                "id": "fact-1",
                "key": "preferred_tone",
                "value": {"tone": "direct"},
                "source": "user_explicit",
                "confidence": 0.9,
                "sensitivity": "low",
                "status": "active",
                "reason": None,
                "context": {},
                "created_at": "2026-02-05T00:00:00Z",
                "updated_at": "2026-02-05T00:00:00Z",
                "expires_at": None,
            }
        ]

    monkeypatch.setattr(storage, "retrieve_facts", _mock_retrieve)

    result = tools.tool_recall_learning(
        user_id="user-1",
        namespace="work_projektil",
        key="preferred_tone",
        min_confidence=0.7,
        limit=5,
    )

    assert result["count"] == 1
    assert result["items"][0]["id"] == "fact-1"
