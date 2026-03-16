import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_dashboard_external_api_mock():
    with patch("app.dashboard.external_api_call") as mock_api:
        mock_api.return_value = {"status": "ok", "data": {"value": 42}}
        resp = client.get("/dashboard/external-data")
        assert resp.status_code == 200
        assert resp.json()["data"]["value"] == 42
