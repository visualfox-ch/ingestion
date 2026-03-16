"""
CK-Track inference endpoint tests.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def _create_event(client, payload):
    response = client.post("/causal/events", json=payload)
    assert response.status_code in (200, 201)
    data = response.json()
    return data["event"]["event_id"]


def test_inference_stats(client):
    response = client.get("/causal/inference-stats")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "temporal_windows" in data
    assert "causal_priors" in data


def test_analyze_link(client):
    base_time = datetime.now(timezone.utc)
    source_id = _create_event(
        client,
        {
            "event_type": "decision",
            "actor": "copilot",
            "description": "Test source event",
            "task_id": "T-CKTRACK-TEST",
            "timestamp": base_time.isoformat(),
        },
    )
    target_id = _create_event(
        client,
        {
            "event_type": "outcome",
            "actor": "copilot",
            "description": "Test target event",
            "task_id": "T-CKTRACK-TEST",
            "timestamp": (base_time + timedelta(minutes=5)).isoformat(),
        },
    )

    response = client.post(
        "/causal/analyze-link",
        json={
            "source_event_id": source_id,
            "target_event_id": target_id,
            "analyze_confidence": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["causal_link"]["source_event_id"] == source_id
    assert data["causal_link"]["target_event_id"] == target_id


def test_discover_links(client):
    base_time = datetime.now(timezone.utc)
    target_id = _create_event(
        client,
        {
            "event_type": "action",
            "actor": "copilot",
            "description": "Target event",
            "timestamp": base_time.isoformat(),
        },
    )
    _create_event(
        client,
        {
            "event_type": "outcome",
            "actor": "copilot",
            "description": "Forward candidate",
            "timestamp": (base_time + timedelta(minutes=2)).isoformat(),
        },
    )
    _create_event(
        client,
        {
            "event_type": "decision",
            "actor": "copilot",
            "description": "Backward candidate",
            "timestamp": (base_time - timedelta(minutes=2)).isoformat(),
        },
    )

    response = client.get(
        "/causal/discover-links",
        params={
            "event_id": target_id,
            "direction": "both",
            "max_window_hours": 1,
            "min_strength": 0.1,
            "max_results": 5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event_id"] == target_id
    assert isinstance(data["discovered_links"], list)


def test_insights_endpoint(client):
    base_time = datetime.now(timezone.utc)
    event_id = _create_event(
        client,
        {
            "event_type": "decision",
            "actor": "codex",
            "description": "Insights source event",
            "timestamp": base_time.isoformat(),
        },
    )
    _create_event(
        client,
        {
            "event_type": "outcome",
            "actor": "codex",
            "description": "Insights candidate",
            "timestamp": (base_time + timedelta(minutes=3)).isoformat(),
        },
    )

    response = client.get(
        "/causal/insights",
        params={"event_id": event_id, "window_seconds": 600, "max_links": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["event_id"] == event_id
    assert "inferred_links" in data


def test_recommendations_endpoint(client):
    response = client.get(
        "/causal/recommendations",
        params={"limit": 5, "min_quality": 0.5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "recommendations" in data


def test_validate_hypothesis_endpoint(client):
    base_time = datetime.now(timezone.utc)
    source_id = _create_event(
        client,
        {
            "event_type": "decision",
            "actor": "codex",
            "description": "Hypothesis source",
            "timestamp": base_time.isoformat(),
        },
    )
    target_id = _create_event(
        client,
        {
            "event_type": "outcome",
            "actor": "codex",
            "description": "Hypothesis target",
            "timestamp": (base_time + timedelta(minutes=1)).isoformat(),
        },
    )
    response = client.post(
        "/causal/validate-hypothesis",
        json={"source_event_id": source_id, "target_event_id": target_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source_event_id"] == source_id
    assert data["target_event_id"] == target_id
