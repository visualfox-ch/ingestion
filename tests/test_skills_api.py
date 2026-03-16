import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
API_KEY = "jarvis-secret-key"


def test_skill_lifecycle():
    # Register a new skill
    skill = {
        "name": "echo_test",
        "description": "Echoes input for testing.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]
        }
    }
    resp = client.post("/api/v1/skills/register", json=skill, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"

    # List skills and check presence
    resp = client.get("/api/v1/skills/", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    found = any(s["name"] == "echo_test" for s in resp.json())
    assert found

    # Unregister the skill
    resp = client.post("/api/v1/skills/unregister/echo_test", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unregistered"

    # Ensure skill is gone
    resp = client.get("/api/v1/skills/", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    found = any(s["name"] == "echo_test" for s in resp.json())
    assert not found
