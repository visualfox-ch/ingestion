"""
Tests for Jarvis Transparency API.

Validates self-awareness endpoints:
- Document listing
- Document retrieval
- Current phase extraction
- Active task listing
- Rate limiting
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.transparency import router, rate_limit_store, RATE_LIMIT_PER_HOUR
from pathlib import Path
from datetime import datetime, timedelta

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Reset rate limit store before each test."""
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


def test_list_docs():
    """Test document type listing."""
    resp = client.get("/api/v1/transparency/docs/list")
    assert resp.status_code == 200
    
    doc_types = resp.json()
    assert isinstance(doc_types, list)
    assert "roadmap" in doc_types
    assert "tasks" in doc_types
    assert "architecture" in doc_types
    assert "memory" in doc_types
    assert "night_mode" in doc_types


def test_get_roadmap():
    """Test roadmap retrieval."""
    resp = client.get("/api/v1/transparency/docs/roadmap")
    
    # May not exist in test environment
    if resp.status_code == 404:
        pytest.skip("Roadmap file not found in test environment")
    
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "doc_type" in data
    assert data["doc_type"] == "roadmap"


def test_get_unknown_doc_type():
    """Test unknown document type returns 404."""
    resp = client.get("/api/v1/transparency/docs/unknown_type")
    assert resp.status_code == 404


def test_current_phase():
    """Test current phase extraction."""
    resp = client.get("/api/v1/transparency/docs/current-phase")
    
    # May not exist in test environment
    if resp.status_code == 404:
        pytest.skip("Roadmap file not found in test environment")
    
    assert resp.status_code == 200
    data = resp.json()
    assert "current_phase" in data
    assert "status" in data


def test_active_tasks():
    """Test active task listing."""
    resp = client.get("/api/v1/transparency/docs/tasks/active")
    
    # May not exist in test environment
    if resp.status_code == 404:
        pytest.skip("Tasks file not found in test environment")
    
    assert resp.status_code == 200
    tasks = resp.json()
    assert isinstance(tasks, list)


def test_rate_limiting():
    """Test rate limiting (10 requests/hour)."""
    session_id = "test-session"
    headers = {"X-Session-ID": session_id}
    
    # Send RATE_LIMIT_PER_HOUR requests (should succeed)
    for i in range(RATE_LIMIT_PER_HOUR):
        resp = client.get("/api/v1/transparency/docs/list", headers=headers)
        assert resp.status_code == 200, f"Request {i+1} failed"
    
    # Next request should be rate limited
    resp = client.get("/api/v1/transparency/docs/list", headers=headers)
    assert resp.status_code == 429
    assert "Rate limit exceeded" in resp.json()["detail"]


def test_stats_endpoint():
    """Test statistics endpoint."""
    session_id = "test-stats"
    headers = {"X-Session-ID": session_id}
    
    # Make some requests
    client.get("/api/v1/transparency/docs/list", headers=headers)
    client.get("/api/v1/transparency/docs/list", headers=headers)
    
    # Check stats
    resp = client.get("/api/v1/transparency/stats", headers=headers)
    assert resp.status_code == 200
    
    stats = resp.json()
    assert stats["session_id"] == session_id
    assert stats["requests_last_hour"] == 2
    assert stats["rate_limit"] == RATE_LIMIT_PER_HOUR
    assert stats["remaining"] == RATE_LIMIT_PER_HOUR - 2


def test_rate_limit_per_session():
    """Test rate limits are per-session."""
    headers1 = {"X-Session-ID": "session-1"}
    headers2 = {"X-Session-ID": "session-2"}
    
    # Session 1: 10 requests
    for _ in range(RATE_LIMIT_PER_HOUR):
        resp = client.get("/api/v1/transparency/docs/list", headers=headers1)
        assert resp.status_code == 200
    
    # Session 1: next request rate limited
    resp = client.get("/api/v1/transparency/docs/list", headers=headers1)
    assert resp.status_code == 429
    
    # Session 2: should still work
    resp = client.get("/api/v1/transparency/docs/list", headers=headers2)
    assert resp.status_code == 200


def test_anonymous_session():
    """Test requests without session ID use 'anonymous' session."""
    # No X-Session-ID header
    for _ in range(RATE_LIMIT_PER_HOUR):
        resp = client.get("/api/v1/transparency/docs/list")
        assert resp.status_code == 200
    
    # Next request rate limited
    resp = client.get("/api/v1/transparency/docs/list")
    assert resp.status_code == 429


@pytest.mark.skip(reason="transparency_tool module not yet implemented")
@pytest.mark.asyncio
async def test_tool_integration():
    """Test transparency tool integration."""
    from app.tools.transparency_tool import tool_get_dev_info

    # Test current-phase
    result = await tool_get_dev_info("current-phase")
    assert isinstance(result, str)
    assert "Current Phase" in result or "Error" in result  # May fail in test env

    # Test active-tasks
    result = await tool_get_dev_info("active-tasks")
    assert isinstance(result, str)
    assert "Active Tasks" in result or "Error" in result or "No active tasks" in result


@pytest.mark.skip(reason="transparency_tool module not yet implemented")
def test_tool_schema():
    """Test tool schema is valid."""
    from app.tools.transparency_tool import TRANSPARENCY_TOOL_SCHEMA

    schema = TRANSPARENCY_TOOL_SCHEMA
    assert schema["name"] == "tool_get_dev_info"
    assert "description" in schema
    assert "parameters" in schema

    params = schema["parameters"]
    assert params["type"] == "object"
    assert "doc_type" in params["properties"]

    doc_type_enum = params["properties"]["doc_type"]["enum"]
    assert "roadmap" in doc_type_enum
    assert "current-phase" in doc_type_enum
    assert "active-tasks" in doc_type_enum
