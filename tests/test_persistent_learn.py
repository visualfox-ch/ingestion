"""Unit tests for persistent learn endpoints."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.auth import auth_dependency
from app.routers.learn_router import router as learn_router
from app.persistent_learn import storage


@pytest.fixture()
def client():
    test_app = FastAPI()
    test_app.include_router(learn_router)
    test_app.dependency_overrides[auth_dependency] = lambda: True
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


def test_record_fact_endpoint(client, monkeypatch):
    def _mock_record_fact(**kwargs):
        return {
            "id": "fact-123",
            "status": "active",
            "created_at": "2026-02-04T00:00:00Z",
            "expires_at": None,
        }

    monkeypatch.setattr(storage, "record_fact", _mock_record_fact)
    payload = {
        "user_id": "123",
        "namespace": "work_projektil",
        "key": "preferred_tone",
        "value": {"tone": "direct"},
        "source": "user_explicit",
        "confidence": 0.9,
        "sensitivity": "low",
    }

    resp = client.post("/learn/record", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "fact-123"
    assert data["status"] == "active"


def test_retrieve_facts_endpoint(client, monkeypatch):
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
                "created_at": "2026-02-04T00:00:00Z",
                "updated_at": "2026-02-04T00:00:00Z",
                "expires_at": None,
            }
        ]

    monkeypatch.setattr(storage, "retrieve_facts", _mock_retrieve)
    resp = client.get("/learn/retrieve", params={"user_id": "123", "namespace": "work_projektil"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["id"] == "fact-1"


def test_analyze_patterns_endpoint(client, monkeypatch):
    def _mock_analyze(**kwargs):
        return (
            {"window_days": 30, "pattern_count": 1},
            [{"key": "preferred_tone", "source": "user_explicit", "count": 3, "avg_confidence": 0.8}],
            "pattern-1",
        )

    monkeypatch.setattr(storage, "analyze_patterns", _mock_analyze)
    payload = {"user_id": "123", "namespace": "work_projektil", "window_days": 30, "limit": 5}
    resp = client.post("/learn/analyze-patterns", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["recorded_id"] == "pattern-1"
    assert data["summary"]["pattern_count"] == 1


def test_redaction_masks_sensitive_fields():
    payload = {
        "email": "user@example.com",
        "token": "secret-token",
        "nested": {"api_key": "abcd", "text": "call +41 79 123 45 67"},
    }
    redacted = storage._redact_value(payload)
    assert redacted["token"] == "[REDACTED]"
    assert "REDACTED_EMAIL" in redacted["email"]
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "REDACTED_PHONE" in redacted["nested"]["text"]
