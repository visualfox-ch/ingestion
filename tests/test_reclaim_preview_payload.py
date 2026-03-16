"""Tests for Asana to Reclaim payload helpers and preview endpoint."""
from __future__ import annotations

from typing import Dict, Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.asana_reclaim_payload import ReclaimPayloadConfig, build_reclaim_task_payload
from app import config
from app.routers import reclaim_router


def _sample_asana_task(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    task = {
        "gid": "123",
        "name": "Sample Task",
        "due_on": "2026-02-07",
        "permalink_url": "https://app.asana.com/0/1/2",
        "assigned_to_self": True,
        "completed": False,
    }
    if overrides:
        task.update(overrides)
    return task


def test_build_reclaim_task_payload_normalizes_due_date():
    config = ReclaimPayloadConfig(
        duration_minutes=60,
        min_chunk_minutes=30,
        max_chunk_minutes=120,
        event_category="WORK",
        priority="P3",
        always_private=True,
        on_deck=False,
    )

    payload = build_reclaim_task_payload(_sample_asana_task(), "scheme-1", config)

    assert payload["due_on"] == "2026-02-07T00:00:00Z"
    assert payload["payload"]["due"] == "2026-02-07T00:00:00Z"
    assert payload["payload"]["timeSchemeId"] == "scheme-1"
    assert "GID: 123" in payload["notes"]


def test_preview_endpoint_returns_payload_and_skip_reasons(monkeypatch):
    app = FastAPI()
    app.include_router(reclaim_router.router)
    client = TestClient(app)

    def fake_get_items(*_args, **_kwargs):
        return [
            {
                "id": 1,
                "content": {
                    "asana": _sample_asana_task(
                        {
                            "assigned_to_self": False,
                            "completed": True,
                        }
                    ),
                    "reclaim": {"task_id": "task-1"},
                },
            }
        ]

    monkeypatch.setattr(reclaim_router.knowledge_store, "get_knowledge_items", fake_get_items)
    monkeypatch.setattr(reclaim_router, "resolve_time_scheme_id", lambda *_args, **_kwargs: "scheme-1")

    headers = {}
    if config.API_KEY:
        headers[config.API_KEY_HEADER] = config.API_KEY

    response = client.post(
        "/reclaim/asana/preview",
        json={
            "task_gid": "123",
            "namespace": "private",
            "include_completed": False,
            "only_assigned_to_self": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["skipped"] is True
    assert set(payload["skip_reasons"]) == {"not_assigned_to_self", "completed", "already_synced"}
    assert payload["payload"]["timeSchemeId"] == "scheme-1"
    assert payload["title"] == "Sample Task"
