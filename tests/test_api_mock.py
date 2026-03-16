import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_external_service_mock():
    with patch("app.api.external_service_call") as mock_service:
        mock_service.return_value = {"result": "mocked"}
        resp = client.get("/api/v1/external-service")
        assert resp.status_code == 200
        assert resp.json()["result"] == "mocked"
