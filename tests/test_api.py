import pytest
from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch
import sys
import types

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
            "query": "contract test legacy namespace",
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
            "query": "contract test explicit scope",
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


def test_agent_accepts_missing_namespace_with_api_default_scope(monkeypatch):
    # Legacy namespace remains the compatibility output shape of scope defaults.
    call_log = []
    _patch_agent_dependencies(monkeypatch, call_log)
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )

    resp = client.post(
        "/agent",
        json={
            "query": "contract test api default",
            "stream": False,
            "source": "api",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer") == "ok"
    assert len(call_log) == 1
    assert call_log[0]["namespace"] == "work_projektil"
    assert call_log[0]["scope"].org == "projektil"
    assert call_log[0]["scope"].visibility == "internal"


def test_agent_accepts_missing_namespace_with_telegram_default_scope(monkeypatch):
    # Legacy namespace remains the compatibility output shape of scope defaults.
    call_log = []
    _patch_agent_dependencies(monkeypatch, call_log)
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "personal", "visibility": "private", "owner": "michael_bohl"},
    )

    resp = client.post(
        "/agent",
        json={
            "query": "contract test telegram default",
            "stream": False,
            "source": "telegram",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer") == "ok"
    assert len(call_log) == 1
    assert call_log[0]["namespace"] == "private"
    assert call_log[0]["scope"].org == "personal"
    assert call_log[0]["scope"].visibility == "private"


def test_agent_prefers_provided_conversation_history_over_db(monkeypatch):
    call_log = []
    _patch_agent_dependencies(monkeypatch, call_log)

    monkeypatch.setattr(
        "app.main.state_db.get_conversation_history",
        lambda *args, **kwargs: [{"role": "assistant", "content": "from-db"}],
    )

    supplied_history = [
        {"role": "user", "content": "from-request-1"},
        {"role": "assistant", "content": "from-request-2"},
    ]

    resp = client.post(
        "/agent",
        json={
            "query": "contract test direct history",
            "stream": False,
            "source": "api",
            "conversation_history": supplied_history,
        },
    )

    assert resp.status_code == 200
    assert len(call_log) == 1
    assert call_log[0]["conversation_history"] == supplied_history


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


def test_n8n_drive_sync_uses_api_default_namespace_when_missing(monkeypatch):
    # Endpoint still passes legacy namespace identifiers internally.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )

    captured = {}

    def _fake_trigger_drive_sync(folder_id=None, limit=50, namespace=None):
        captured["folder_id"] = folder_id
        captured["limit"] = limit
        captured["namespace"] = namespace
        return {"success": True, "total": 0, "message": "ok"}

    monkeypatch.setattr("app.n8n_client.trigger_drive_sync", _fake_trigger_drive_sync)

    resp = client.post("/n8n/drive/sync", json={"limit": 0})

    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert captured["namespace"] == "work_projektil"


def test_n8n_gmail_sync_uses_default_namespace_for_storage(monkeypatch, tmp_path):
    # Storage path currently uses legacy namespace folder names.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )
    monkeypatch.setattr("app.main.PARSED_DIR", tmp_path)

    def _fake_get_gmail_projektil_with_retry(limit=50):
        return {
            "emails": [
                {
                    "id": "smoke-msg-1",
                    "from": "sender@example.com",
                    "to": "receiver@example.com",
                    "subject": "Test",
                    "date": "2026-03-16",
                    "text": "Hello from test",
                }
            ],
            "rate_limited": False,
        }

    monkeypatch.setattr("app.n8n_client.get_gmail_projektil_with_retry", _fake_get_gmail_projektil_with_retry)

    resp = client.post(
        "/n8n/gmail/sync",
        json={"limit": 1, "batch_size": 1, "days_back": 1, "ingest": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("stored") == 1
    assert (tmp_path / "work_projektil" / "email" / "inbox" / "smoke-msg-1.txt").exists()


def test_consolidate_run_uses_api_default_namespace_when_missing(monkeypatch):
    # Consolidation response currently exposes legacy namespace naming.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )

    captured = {}

    def _fake_run_consolidation(namespace, days, min_person_mentions, min_topic_mentions, dry_run):
        captured["namespace"] = namespace
        return {"namespace": namespace, "dry_run": dry_run}

    monkeypatch.setattr("app.consolidation.run_consolidation", _fake_run_consolidation)

    resp = client.post("/consolidate/run?dry_run=true&days=1")

    assert resp.status_code == 200
    assert resp.json().get("namespace") == "work_projektil"
    assert captured["namespace"] == "work_projektil"


def test_ingest_drive_uses_api_default_namespace_when_missing(monkeypatch):
    # Qdrant collections are still keyed by legacy namespace identifiers.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )
    monkeypatch.setattr("app.llm.get_embedding", lambda text: [0.1, 0.2, 0.3], raising=False)

    captured = {}

    def _fake_upsert_vectors(collection, vectors, payloads, ids):
        captured["collection"] = collection
        captured["ids"] = ids
        return {"status": "ok"}

    monkeypatch.setattr("app.main.upsert_vectors", _fake_upsert_vectors)

    resp = client.post(
        "/ingest/drive",
        json={
            "file_id": "drive-default-ns-test",
            "name": "doc.txt",
            "mime_type": "text/plain",
            "doc_type": "text",
            "text_content": "This is a long enough body to trigger ingestion path.",
        },
    )

    assert resp.status_code == 200
    assert resp.json().get("status") == "ingested"
    assert captured["collection"] == "jarvis_work_projektil"


def test_drive_documents_uses_api_default_namespace_when_missing(monkeypatch):
    # Document listing still resolves to legacy namespace collection names.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )

    captured = {}

    class _FakeQdrantClient:
        def __init__(self, host=None, port=None):
            self.host = host
            self.port = port

        def scroll(self, collection_name, scroll_filter, limit, with_payload, with_vectors):
            captured["collection"] = collection_name
            return ([], None)

    class _Filter:
        def __init__(self, must):
            self.must = must

    class _FieldCondition:
        def __init__(self, key, match):
            self.key = key
            self.match = match

    class _MatchValue:
        def __init__(self, value):
            self.value = value

    monkeypatch.setitem(sys.modules, "qdrant_client", types.SimpleNamespace(QdrantClient=_FakeQdrantClient))
    monkeypatch.setitem(
        sys.modules,
        "qdrant_client.models",
        types.SimpleNamespace(Filter=_Filter, FieldCondition=_FieldCondition, MatchValue=_MatchValue),
    )

    resp = client.get("/drive/documents?limit=1")

    assert resp.status_code == 200
    assert resp.json().get("namespace") == "work_projektil"
    assert captured["collection"] == "jarvis_work_projektil"


def test_drive_search_uses_api_default_namespace_when_missing(monkeypatch):
    # Search still resolves to legacy namespace collection names.
    monkeypatch.setattr(
        "app.main.get_default_scope",
        lambda source: {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"},
    )
    monkeypatch.setattr("app.llm.get_embedding", lambda text: [0.1, 0.2, 0.3], raising=False)

    captured = {}

    class _Hit:
        payload = {"name": "doc", "text": "content"}
        score = 0.9

    class _FakeQdrantClient:
        def __init__(self, host=None, port=None):
            self.host = host
            self.port = port

        def search(self, collection_name, query_vector, query_filter, limit, with_payload):
            captured["collection"] = collection_name
            return [_Hit()]

    class _Filter:
        def __init__(self, must):
            self.must = must

    class _FieldCondition:
        def __init__(self, key, match):
            self.key = key
            self.match = match

    class _MatchValue:
        def __init__(self, value):
            self.value = value

    monkeypatch.setitem(sys.modules, "qdrant_client", types.SimpleNamespace(QdrantClient=_FakeQdrantClient))
    monkeypatch.setitem(
        sys.modules,
        "qdrant_client.models",
        types.SimpleNamespace(Filter=_Filter, FieldCondition=_FieldCondition, MatchValue=_MatchValue),
    )

    resp = client.get("/drive/search?query=test&limit=1")

    assert resp.status_code == 200
    assert captured["collection"] == "jarvis_work_projektil"
    assert len(resp.json().get("results", [])) == 1
