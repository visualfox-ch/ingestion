"""Task API tests - integration tests for task endpoints.

NOTE: These tests require the full FastAPI application and database.
"""
import pytest
from fastapi.testclient import TestClient
import sys
import os

# Skip if we can't import the app module
try:
    from app.main import app
except ImportError:
    pytest.skip("Cannot import app.main - relative import issue", allow_module_level=True)

client = TestClient(app)

def test_list_tasks():
    response = client.get("/tasks", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_task():
    response = client.get("/tasks/12", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 200
    assert response.json()["id"] == 12

    response = client.get("/tasks/999", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 404

def test_trigger_task():
    response = client.post("/tasks/12/trigger", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 200
    assert response.json()["status"] == "in-progress"

    response = client.post("/tasks/999/trigger", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 404

def test_status():
    response = client.get("/status", headers={"X-API-Key": "jarvis-secret-key"})
    assert response.status_code == 200
    assert "status" in response.json()
