"""Unit + API tests for Phase 2 gate logic and endpoints."""

import sys
from pathlib import Path
from typing import Dict, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import phase_gate
from app.auth import auth_dependency
from app.routers.phase2_gate_router import router as phase2_gate_router


@pytest.fixture()
def client():
    test_app = FastAPI()
    test_app.include_router(phase2_gate_router)
    test_app.dependency_overrides[auth_dependency] = lambda: True
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


def _mock_query_scalar_factory(values: Dict[str, Any]):
    def _mock_query_scalar(query: str):
        for key, value in values.items():
            if key in query:
                return value
        return None

    return _mock_query_scalar


def test_evaluate_phase2_gate_approve(monkeypatch):
    monkeypatch.setattr(
        phase_gate,
        "_query_scalar",
        _mock_query_scalar_factory({
            "false_positives": 0.01,
            "success=\"true\"": 0.97,
            "security_incidents": 0,
            "confidence_score_outliers": 5,
        })
    )

    result = phase_gate.evaluate_phase2_gate(window_hours=24)
    assert result["decision"] == "approve"
    assert result["metrics"]["false_positive_rate"]["status"] == "green"
    assert result["metrics"]["success_rate"]["status"] == "green"
    assert result["metrics"]["security_incidents"]["status"] == "green"
    assert result["metrics"]["confidence_outliers"]["status"] == "green"


def test_evaluate_phase2_gate_hold(monkeypatch):
    monkeypatch.setattr(
        phase_gate,
        "_query_scalar",
        _mock_query_scalar_factory({
            "false_positives": 0.06,
            "success=\"true\"": 0.96,
            "security_incidents": 0,
            "confidence_score_outliers": 5,
        })
    )

    result = phase_gate.evaluate_phase2_gate(window_hours=24)
    assert result["decision"] == "hold"
    assert result["metrics"]["false_positive_rate"]["status"] == "yellow"


def test_evaluate_phase2_gate_rollback(monkeypatch):
    monkeypatch.setattr(
        phase_gate,
        "_query_scalar",
        _mock_query_scalar_factory({
            "false_positives": 0.01,
            "success=\"true\"": 0.96,
            "security_incidents": 1,
            "confidence_score_outliers": 5,
        })
    )

    result = phase_gate.evaluate_phase2_gate(window_hours=24)
    assert result["decision"] == "rollback"
    assert result["metrics"]["security_incidents"]["status"] == "red"


def test_evaluate_phase2_gate_insufficient_data(monkeypatch):
    monkeypatch.setattr(
        phase_gate,
        "_query_scalar",
        _mock_query_scalar_factory({
            "false_positives": None,
            "success=\"true\"": 0.96,
            "security_incidents": 0,
            "confidence_score_outliers": 5,
        })
    )

    result = phase_gate.evaluate_phase2_gate(window_hours=24)
    assert result["decision"] == "insufficient_data"
    assert result["metrics"]["false_positive_rate"]["status"] == "unknown"


def test_apply_phase2_settings_applied(monkeypatch):
    calls = []

    def _set_hot_config(key, value, changed_by=None, reason=None):
        calls.append((key, value, changed_by, reason))

    monkeypatch.setattr(phase_gate, "set_hot_config", _set_hot_config)
    monkeypatch.setattr(phase_gate, "get_hot_config", lambda key, default=None: 2)

    result = phase_gate.apply_phase2_settings({"decision": "approve"}, changed_by="tester")
    assert result["status"] == "applied"
    keys = [call[0] for call in calls]
    assert "auto_approval_enabled" in keys
    assert "auto_approval_phase" in keys
    assert "auto_approval_r0_threshold" in keys
    assert "auto_approval_r1_threshold" in keys
    assert "auto_approval_r2_threshold" in keys
    assert "auto_approval_r3_threshold" in keys


def test_apply_phase2_settings_skipped():
    result = phase_gate.apply_phase2_settings({"decision": "hold"})
    assert result["status"] == "skipped"


def test_api_status(client, monkeypatch):
    import types
    import sys as _sys

    from app import hot_config

    monkeypatch.setattr(hot_config, "get_hot_config", lambda key, default=None: 1 if key == "auto_approval_phase" else True)

    stub_module = types.ModuleType("app.approval_auto")

    class _StubAutoApprovalEngine:
        @staticmethod
        def _get_thresholds(phase):
            return {0: 0.7, 1: 0.85, 2: 0.95, 3: 0.99}

    stub_module.AutoApprovalEngine = _StubAutoApprovalEngine
    _sys.modules["app.approval_auto"] = stub_module

    resp = client.get("/api/gate/phase2/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == 1
    assert data["enabled"] is True


def test_api_evaluate(client, monkeypatch):
    def _mock_evaluate(window_hours=24):
        return {
            "decision": "approve",
            "window_hours": window_hours,
            "evaluated_at": "2026-02-04T00:00:00Z",
            "metrics": {"fake": {"status": "green"}},
        }

    monkeypatch.setattr(phase_gate, "evaluate_phase2_gate", _mock_evaluate)

    resp = client.get("/api/gate/phase2/evaluate?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "approve"
    assert data["summary"]
    assert data["recommendation"]


def test_api_activate_requires_confirm(client):
    resp = client.post(
        "/api/gate/phase2/activate",
        json={"decision_summary": "test", "changed_by": "tester", "confirm": False},
    )
    assert resp.status_code == 400


def test_api_activate_success(client, monkeypatch):
    def _mock_apply(decision_summary, changed_by="api_user", reason=None):
        return {
            "status": "applied",
            "applied_at": "2026-02-04T00:00:00Z",
        }

    monkeypatch.setattr(phase_gate, "apply_phase2_settings", _mock_apply)

    resp = client.post(
        "/api/gate/phase2/activate",
        json={"decision_summary": "approve", "changed_by": "tester", "confirm": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["activated"] is True
    assert data["thresholds"]["r2"] == 0.95
