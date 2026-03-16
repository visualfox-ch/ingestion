import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

USER_ID = "testuser"

# --- Timeline Endpoints ---
def test_add_and_get_timeline_event():
    event = {
        "user_id": USER_ID,
        "event_type": "note",
        "title": "Test Event",
        "description": "Memory E2E Test",
        "event_date": "2026-02-19",
        "tags": ["e2e", "memory"]
    }
    resp = client.post("/memory/timeline", json=event)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    event_id = data["event_id"]

    # Get timeline
    resp2 = client.get(f"/memory/timeline?user_id={USER_ID}&limit=10")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "success"
    assert any(ev["title"] == "Test Event" for ev in data2["events"])

# --- Preferences Endpoints ---
def test_learn_and_get_preference():
    pref = {
        "user_id": USER_ID,
        "key": "favorite_color",
        "value": "blue",
        "category": "profile",
        "source": "user_explicit"
    }
    resp = client.post("/memory/preferences/learn", json=pref)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Get preferences
    resp2 = client.get(f"/memory/preferences?user_id={USER_ID}&category=profile")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "success"
    assert any(p["key"] == "favorite_color" for p in data2["preferences"])

# --- Confidence/Tagging/Recall (indirekt via preferences) ---
def test_confirm_and_contradict_preference():
    # Confirm
    resp = client.post(f"/memory/preferences/confirm?user_id={USER_ID}&key=favorite_color")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    # Contradict
    resp2 = client.post(f"/memory/preferences/contradict?user_id={USER_ID}&key=favorite_color")
    assert resp2.status_code == 200
    assert resp2.json()["status"] in ("success", "not_found")
