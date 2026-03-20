import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import feedback_router


@pytest.mark.asyncio
async def test_feedback_improvements_endpoint_uses_get_improvement_log(monkeypatch):
    app = FastAPI()
    app.include_router(feedback_router.router)

    sample = [
        {
            "id": "1",
            "type": "feedback_pattern",
            "description": "Negative feedback pattern detected",
            "status": "proposed",
        }
    ]

    async def _fake_get_improvement_log(*, improvement_type=None, status=None, limit=20):
        assert limit == 5
        return sample

    monkeypatch.setattr(feedback_router, "get_improvement_log", _fake_get_improvement_log)

    client = TestClient(app)
    response = client.get("/feedback/improvements?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["improvements"][0]["type"] == "feedback_pattern"

def test_feedback_recent_endpoint_returns_wrapped_list(monkeypatch):
    app = FastAPI()
    app.include_router(feedback_router.router)

    sample = [
        {
            "id": "10",
            "type": "general",
            "text": "looks good",
        }
    ]

    async def _fake_get_recent_feedback(*, user_id=None, feedback_type=None, limit=20):
        assert limit == 3
        return sample

    monkeypatch.setattr(feedback_router, "get_recent_feedback", _fake_get_recent_feedback)

    client = TestClient(app)
    response = client.get("/feedback/recent?limit=3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["feedback"][0]["id"] == "10"
    assert "request_id" in payload
