import pytest
from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch

client = TestClient(app)

def test_api_root():
    resp = client.get("/api/v1/")
    assert resp.status_code == 200
    assert "Jarvis" in resp.text

# Example: Mocking external API call
import requests

def test_api_external_mock():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"result": "mocked"}
        resp = client.get("/api/v1/external")
        assert resp.status_code == 200
        assert resp.json()["result"] == "mocked"


def _agent_result_stub(answer: str = "ok"):
    return {
        "answer": answer,
        "tool_calls": [],
        "rounds": 1,
        "bulk_memory_sync": False,
        "qdrant_registered": False,
        "qdrant_results": {},
        "model": "test-model",
        "role": "assistant",
        "persona_id": None,
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
        },
    }


def _patch_agent_dependencies(monkeypatch, call_log):
    monkeypatch.setattr("app.main.state_db.create_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.state_db.get_conversation_history", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.main.state_db.add_message", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.state_db.get_session_info", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.state_db.update_session_title", lambda *args, **kwargs: None)

    def _fake_run_agent(**kwargs):
        call_log.append(kwargs)
        return _agent_result_stub()

    monkeypatch.setattr("app.main.agent.run_agent", _fake_run_agent)


def test_agent_accepts_legacy_namespace(monkeypatch):
    call_log = []
    _patch_agent_dependencies(monkeypatch, call_log)

    resp = client.post(
        "/agent",
        json={
            "query": "contract test namespace",
            "namespace": "work_projektil",
            "stream": False,
            "source": "api",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer") == "ok"
    assert len(call_log) == 1
    assert call_log[0]["namespace"] == "work_projektil"


def test_agent_accepts_scope_payload(monkeypatch):
    call_log = []
    _patch_agent_dependencies(monkeypatch, call_log)

    resp = client.post(
        "/agent",
        json={
            "query": "contract test scope",
            "scope": {"org": "personal", "visibility": "private"},
            "stream": False,
            "source": "api",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer") == "ok"
    assert len(call_log) == 1
    assert call_log[0]["namespace"] == "private"
    assert call_log[0]["scope"].org == "personal"
    assert call_log[0]["scope"].visibility == "private"


def test_agent_rejects_missing_namespace_and_scope():
    resp = client.post(
        "/agent",
        json={
            "query": "invalid payload",
            "namespace": "",
            "stream": False,
            "source": "api",
        },
    )

    assert resp.status_code == 400
    assert "namespace or scope is required" in resp.json().get("detail", "")
