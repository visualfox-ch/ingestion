"""
Tests for cost-aware completion routing (IMR-P1).
"""
import os
import sys
import types

import pytest

if "redis" not in sys.modules:
    sys.modules["redis"] = types.SimpleNamespace(Redis=object)

sys.path.insert(0, "/Volumes/BRAIN/system/ingestion")

from app import cost_tracker
from app.simple_task_router import simple_task_router
from app.cost_aware_completion import select_cost_aware_model, build_budget_exceeded_response, CostAwareDecision
from tests.integration_helpers import JarvisTestClient, TestConfig


@pytest.fixture(autouse=True)
def _reset_cost_tracker():
    cost_tracker._tracker = None
    yield
    cost_tracker._tracker = None


def test_simple_task_router_briefing():
    decision = simple_task_router("/briefing heute")
    assert decision is not None
    assert decision.policy == "cheap"


def test_simple_task_router_coaching():
    decision = simple_task_router("Ich fühle mich gestresst, coaching bitte")
    assert decision is not None
    assert decision.policy == "default"


def test_select_cost_aware_model_short_query_cheap(monkeypatch):
    from app import config as cfg
    monkeypatch.setattr(cfg, "COST_AWARE_SHORT_QUERY_WORDS", 200)
    monkeypatch.setattr(cfg, "COST_AWARE_MAX_INPUT_TOKENS", 2000)

    decision = select_cost_aware_model("Hi", preferred_provider="anthropic")
    assert decision.model == cfg.COST_AWARE_CHEAP_MODEL


def test_select_cost_aware_model_emergency_cutoff(monkeypatch):
    import app.hot_config as hot_config

    def _fake_get_hot_config(key, default=None):
        if key == "emergency_cutoff_enabled":
            return True
        if key == "daily_budget_usd":
            return 1.0
        return default

    monkeypatch.setattr(hot_config, "get_hot_config", _fake_get_hot_config)

    tracker = cost_tracker.get_cost_tracker(1.0)
    tracker._costs[tracker._today()] = 2.0  # over budget

    decision = select_cost_aware_model("Status?")
    assert decision.blocked is True


def test_budget_exceeded_response_payload():
    decision = CostAwareDecision(
        model="gpt-4o-mini",
        reason="budget_cutoff",
        query_class="simple",
        task_type="other",
        approx_tokens=10,
        short_query=True,
        over_budget=True,
        daily_budget_usd=1.0,
        daily_spent_usd=2.0,
        blocked=True,
    )

    payload = build_budget_exceeded_response(
        query="test",
        user_id=1,
        session_id="session-1",
        namespace="private",
        decision=decision,
    )

    assert payload.get("budget_exceeded") is True
    assert "Daily budget exhausted" in payload.get("answer", "")
    assert payload.get("daily_cost_usd") == 2.0
    assert payload.get("daily_budget_usd") == 1.0


def test_emergency_cutoff_integration():
    if not os.getenv("JARVIS_INTEGRATION_TESTS"):
        pytest.skip("Set JARVIS_INTEGRATION_TESTS=1 to run integration tests")

    client = JarvisTestClient(TestConfig())
    if not client.health_check():
        pytest.skip("Jarvis API not reachable")

    try:
        client.post(
            "/admin/config/hot",
            {
                "key": "daily_budget_usd",
                "value": 0.0,
                "reason": "IMR-P1 cutoff integration test",
            },
        )
        client.post(
            "/admin/config/hot",
            {
                "key": "emergency_cutoff_enabled",
                "value": True,
                "reason": "IMR-P1 cutoff integration test",
            },
        )

        response = client.post(
            "/agent",
            {
                "query": "test cutoff",
                "namespace": "private",
                "user_id": "copilot",
                "role": "assistant",
            },
        )
        assert response["status"] != 500
        assert response["data"].get("budget_exceeded") is True
    finally:
        client.post(
            "/admin/config/hot",
            {
                "key": "daily_budget_usd",
                "value": 10.0,
                "reason": "IMR-P1 cutoff integration test restore",
            },
        )
        client.post(
            "/admin/config/hot",
            {
                "key": "emergency_cutoff_enabled",
                "value": False,
                "reason": "IMR-P1 cutoff integration test restore",
            },
        )
