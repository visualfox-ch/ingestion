import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_dashboard_html_served():
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Jarvis Remediation Dashboard" in resp.text

# Example: Mocking external API call
import requests
from unittest.mock import patch

def test_dashboard_metrics_mock():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"metrics": {"active": 5}}
        resp = client.get("/dashboard/metrics")
        assert resp.status_code == 200
        assert resp.json()["metrics"]["active"] == 5
