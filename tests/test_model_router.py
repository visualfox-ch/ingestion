"""
Unit tests for ModelRouter (T-005).

Tests cover:
- ModelConfig cost calculation
- CircuitState (circuit breaker pattern)
- CostTracker (daily budget management)
- ModelRouter routing logic
"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, '/Volumes/BRAIN/system/ingestion')

from app.model_router import (
    Provider, AgentRole, ModelConfig, CircuitState, CostTracker,
    ModelRouter, MODELS, ROLE_ROUTING, TASK_ROUTING_PREFERENCES
)
from app.services.ollama_client import OllamaChatResult


class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_calculate_cost_basic(self):
        """Test basic cost calculation."""
        config = ModelConfig(
            provider=Provider.ANTHROPIC,
            model_id="test-model",
            max_tokens=1000,
            input_price_per_1k=0.001,
            output_price_per_1k=0.005
        )

        # 1000 input tokens @ $0.001/1k = $0.001
        # 500 output tokens @ $0.005/1k = $0.0025
        cost = config.calculate_cost(input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.0035, rel=1e-6)

    def test_calculate_cost_zero_tokens(self):
        """Test cost with zero tokens."""
        config = ModelConfig(
            provider=Provider.OPENAI,
            model_id="test-model",
            max_tokens=1000,
            input_price_per_1k=0.005,
            output_price_per_1k=0.015
        )

        cost = config.calculate_cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_claude_sonnet_cost(self):
        """Test cost calculation for Claude Sonnet."""
        config = MODELS["claude-sonnet-4-20250514"]

        # 5000 input tokens @ $0.003/1k = $0.015
        # 1000 output tokens @ $0.015/1k = $0.015
        cost = config.calculate_cost(input_tokens=5000, output_tokens=1000)
        assert cost == pytest.approx(0.030, rel=1e-6)


class TestCircuitState:
    """Tests for CircuitState (circuit breaker pattern)."""

    def test_initial_state_closed(self):
        """Circuit should be closed initially."""
        circuit = CircuitState()
        assert circuit.is_open() is False
        assert circuit.failures == 0
        assert circuit.open_until is None

    def test_single_failure_keeps_circuit_closed(self):
        """One failure should not open the circuit."""
        circuit = CircuitState()
        circuit.record_failure()

        assert circuit.failures == 1
        assert circuit.is_open() is False

    def test_three_failures_opens_circuit(self):
        """Three failures within window should open circuit."""
        circuit = CircuitState()
        circuit.record_failure()
        circuit.record_failure()
        circuit.record_failure()

        assert circuit.failures == 3
        assert circuit.is_open() is True
        assert circuit.open_until is not None

    def test_circuit_cooldown_duration(self):
        """Circuit should stay open for 10 minutes."""
        circuit = CircuitState()

        # Trigger circuit open
        for _ in range(3):
            circuit.record_failure()

        # Should be open
        assert circuit.is_open() is True

        # Check cooldown is approximately 10 minutes
        expected_cooldown = time.time() + 600
        assert abs(circuit.open_until - expected_cooldown) < 5  # Within 5 seconds

    def test_success_resets_failures(self):
        """Success should reset failure count."""
        circuit = CircuitState()
        circuit.record_failure()
        circuit.record_failure()
        assert circuit.failures == 2

        circuit.record_success()
        assert circuit.failures == 0
        assert circuit.open_until is None

    def test_success_closes_open_circuit(self):
        """Success should close an open circuit."""
        circuit = CircuitState()

        # Open circuit
        for _ in range(3):
            circuit.record_failure()
        assert circuit.is_open() is True

        # Close with success
        circuit.record_success()
        assert circuit.is_open() is False
        assert circuit.open_until is None

    def test_reset_clears_all_state(self):
        """Reset should clear all state."""
        circuit = CircuitState()

        # Add some state
        circuit.record_failure()
        circuit.record_failure()
        circuit.last_failure = time.time()

        # Reset
        circuit.reset()
        assert circuit.failures == 0
        assert circuit.last_failure is None
        assert circuit.open_until is None

    def test_failures_reset_after_5_minute_gap(self):
        """Failures should reset if > 5 minutes between failures."""
        circuit = CircuitState()

        circuit.record_failure()
        assert circuit.failures == 1

        # Simulate 6 minutes passing
        circuit.last_failure = time.time() - 360

        circuit.record_failure()
        # Should reset to 1 (not 2) due to time gap
        assert circuit.failures == 1


class TestCostTracker:
    """Tests for CostTracker."""

    def test_initial_state(self):
        """Tracker should start with no costs."""
        tracker = CostTracker(daily_budget_usd=10.0)
        assert tracker.get_daily_remaining() == 10.0
        assert tracker.is_over_budget() is False

    @patch('app.model_router.metrics')
    @patch('app.model_router.log_with_context')
    def test_add_cost_tracks_correctly(self, mock_log, mock_metrics):
        """Adding cost should update daily total."""
        tracker = CostTracker(daily_budget_usd=10.0)

        # Add cost for haiku (cheap model)
        daily_total = tracker.add_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)

        # 1000 input @ $0.001/1k = $0.001
        # 500 output @ $0.005/1k = $0.0025
        assert daily_total == pytest.approx(0.0035, rel=1e-4)
        assert tracker.get_daily_remaining() == pytest.approx(9.9965, rel=1e-4)

    @patch('app.model_router.metrics')
    @patch('app.model_router.log_with_context')
    def test_budget_exceeded(self, mock_log, mock_metrics):
        """Should detect when budget is exceeded."""
        tracker = CostTracker(daily_budget_usd=0.01)  # Very low budget

        # Add cost that exceeds budget
        tracker.add_cost("claude-sonnet-4-20250514", input_tokens=10000, output_tokens=5000)

        # Cost should exceed $0.01
        assert tracker.is_over_budget() is True
        assert tracker.get_daily_remaining() == 0  # Clamped to 0

    @patch('app.model_router.metrics')
    @patch('app.model_router.log_with_context')
    def test_alert_at_80_percent(self, mock_log, mock_metrics):
        """Should log warning at 80% spend."""
        tracker = CostTracker(daily_budget_usd=0.001, alert_threshold=0.8)  # Very low budget

        # Add cost that exceeds 80% threshold
        tracker.add_cost("claude-sonnet-4-20250514", input_tokens=20000, output_tokens=2000)

        # Check that warning was logged with correct message
        warning_calls = [
            call for call in mock_log.call_args_list
            if len(call[0]) >= 3 and call[0][1] == "warning" and "budget" in call[0][2].lower()
        ]
        assert len(warning_calls) >= 1, "Budget alert warning should have been logged"

    @patch('app.model_router.metrics')
    @patch('app.model_router.log_with_context')
    def test_unknown_model_returns_zero(self, mock_log, mock_metrics):
        """Unknown model should return 0 cost."""
        tracker = CostTracker()
        cost = tracker.add_cost("unknown-model-xyz", input_tokens=1000, output_tokens=500)
        assert cost == 0.0


class TestModelRouter:
    """Tests for ModelRouter routing logic."""

    def test_single_model_mode_always_returns_sonnet(self):
        """With multi_model disabled, should always return Sonnet."""
        router = ModelRouter(multi_model_enabled=False)

        # All roles should return Sonnet
        for role in [AgentRole.PLANNER, AgentRole.SPECIALIST, AgentRole.REVIEWER]:
            config = router.route_request(role=role)
            assert config.model_id == "claude-sonnet-4-20250514"

    def test_multi_model_planner_returns_haiku(self):
        """In multi-model mode, planner should use Haiku."""
        router = ModelRouter(multi_model_enabled=True)
        config = router.route_request(role=AgentRole.PLANNER)
        assert config.model_id == "claude-haiku-4-5-20251001"

    def test_multi_model_specialist_returns_sonnet(self):
        """In multi-model mode, specialist should use Sonnet."""
        router = ModelRouter(multi_model_enabled=True)
        config = router.route_request(role=AgentRole.SPECIALIST)
        assert config.model_id == "claude-sonnet-4-20250514"

    def test_multi_model_reviewer_returns_haiku(self):
        """In multi-model mode, reviewer should use Haiku by default."""
        router = ModelRouter(multi_model_enabled=True)
        config = router.route_request(role=AgentRole.REVIEWER)
        assert config.model_id == "claude-haiku-4-5-20251001"

    def test_general_chat_prefers_ollama_specialist(self):
        """General chat should route the specialist role to Ollama first."""
        router = ModelRouter(multi_model_enabled=True)
        config = router.route_request(role=AgentRole.SPECIALIST, task_type="general_chat")
        assert config.provider == Provider.OLLAMA

    def test_cross_provider_preference(self):
        """Cross-provider review should use different provider."""
        router = ModelRouter(multi_model_enabled=True)

        # If previous was Anthropic, reviewer should prefer OpenAI
        config = router.route_request(
            role=AgentRole.REVIEWER,
            prefer_cross_provider=True,
            previous_provider=Provider.ANTHROPIC
        )
        assert config.provider == Provider.OPENAI

    def test_circuit_breaker_fallback(self):
        """Should fallback when primary provider circuit is open."""
        router = ModelRouter(multi_model_enabled=True)

        # Open Anthropic circuit
        for _ in range(3):
            router._circuits[Provider.ANTHROPIC].record_failure()

        assert router.is_provider_available(Provider.ANTHROPIC) is False

        # Should fallback to OpenAI
        config = router.route_request(role=AgentRole.PLANNER)
        assert config.provider == Provider.OPENAI
        assert config.model_id == "gpt-4o-mini"

    def test_provider_availability_check(self):
        """is_provider_available should respect circuit state."""
        router = ModelRouter()

        # Initially both available
        assert router.is_provider_available(Provider.ANTHROPIC) is True
        assert router.is_provider_available(Provider.OPENAI) is True

        # Open Anthropic circuit
        for _ in range(3):
            router._circuits[Provider.ANTHROPIC].record_failure()

        assert router.is_provider_available(Provider.ANTHROPIC) is False
        assert router.is_provider_available(Provider.OPENAI) is True

    def test_get_equivalent_model_anthropic_to_openai(self):
        """Should map Anthropic models to OpenAI equivalents."""
        router = ModelRouter()

        assert router._get_equivalent_model("claude-haiku-4-5-20251001", Provider.OPENAI) == "gpt-4o-mini"
        assert router._get_equivalent_model("claude-sonnet-4-20250514", Provider.OPENAI) == "gpt-4o"

    def test_get_equivalent_model_openai_to_anthropic(self):
        """Should map OpenAI models to Anthropic equivalents."""
        router = ModelRouter()

        assert router._get_equivalent_model("gpt-4o-mini", Provider.ANTHROPIC) == "claude-haiku-4-5-20251001"
        assert router._get_equivalent_model("gpt-4o", Provider.ANTHROPIC) == "claude-sonnet-4-20250514"


class TestRoleRoutingConfig:
    """Tests for ROLE_ROUTING configuration."""

    def test_all_roles_have_routing(self):
        """All AgentRole values should have routing config."""
        for role in AgentRole:
            assert role in ROLE_ROUTING
            assert "primary" in ROLE_ROUTING[role]
            assert "fallback" in ROLE_ROUTING[role]
            assert "max_tokens" in ROLE_ROUTING[role]

    def test_routing_models_exist(self):
        """All models in routing config should exist in MODELS."""
        for role, config in ROLE_ROUTING.items():
            assert config["primary"] in MODELS, f"Primary model for {role} not found"
            assert config["fallback"] in MODELS, f"Fallback model for {role} not found"


class TestTaskRoutingPreferences:
    """Tests for task-type routing preferences."""

    def test_code_tasks_prefer_anthropic_specialist(self):
        """Code tasks should prefer Anthropic for specialist."""
        prefs = TASK_ROUTING_PREFERENCES.get("code", {})
        assert prefs.get("specialist") == Provider.ANTHROPIC

    def test_writing_tasks_prefer_openai_specialist(self):
        """Writing tasks should prefer OpenAI for specialist."""
        prefs = TASK_ROUTING_PREFERENCES.get("writing", {})
        assert prefs.get("specialist") == Provider.OPENAI

    def test_ops_tasks_prefer_anthropic_reviewer(self):
        """Ops tasks should prefer Anthropic for reviewer (safety-critical)."""
        prefs = TASK_ROUTING_PREFERENCES.get("ops", {})
        assert prefs.get("reviewer") == Provider.ANTHROPIC

    def test_general_chat_prefers_ollama_specialist(self):
        """General chat should prefer Ollama for local-first specialist work."""
        prefs = TASK_ROUTING_PREFERENCES.get("general_chat", {})
        assert prefs.get("specialist") == Provider.OLLAMA


class TestModelRouterIntegration:
    """Integration tests (require mocking external APIs)."""

    @patch.object(ModelRouter, '_get_anthropic_client')
    def test_execute_with_fallback_success(self, mock_get_client):
        """Successful execution should track cost and record success."""
        # Setup mock
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Hello")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        router = ModelRouter(multi_model_enabled=True)
        config = MODELS["claude-haiku-4-5-20251001"]

        with patch.object(router.cost_tracker, 'add_cost') as mock_add_cost:
            result = router.execute_with_fallback(
                model_config=config,
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="You are helpful.",
                tools=None
            )

        assert result["stop_reason"] == "end_turn"
        assert result["provider"] == "anthropic"
        mock_add_cost.assert_called_once_with("claude-haiku-4-5-20251001", 100, 50)

    @patch.object(ModelRouter, '_get_anthropic_client')
    @patch.object(ModelRouter, '_get_openai_client')
    def test_execute_with_fallback_on_failure(self, mock_openai, mock_anthropic):
        """Failure should trigger fallback to alternate provider."""
        # Setup mocks - Anthropic fails, OpenAI succeeds
        mock_anthropic.return_value.messages.create.side_effect = Exception("API Error")

        mock_openai_response = MagicMock()
        mock_openai_response.id = "resp_openai_fallback"
        mock_openai_response.output_text = "Hello from OpenAI"
        mock_openai_response.output = []
        mock_openai_response.status = "completed"
        mock_openai_response.usage.input_tokens = 100
        mock_openai_response.usage.output_tokens = 50
        mock_openai.return_value.responses.create.return_value = mock_openai_response

        router = ModelRouter(multi_model_enabled=True)
        config = MODELS["claude-haiku-4-5-20251001"]

        with patch.object(router.cost_tracker, 'add_cost'):
            result = router.execute_with_fallback(
                model_config=config,
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="You are helpful.",
                tools=None
            )

        # Should have fallen back to OpenAI
        assert result["provider"] == "openai"
        assert "Hello from OpenAI" in result["content"][0]["text"]

    @patch.object(ModelRouter, '_get_openai_client')
    @patch.object(ModelRouter, '_get_ollama_client')
    def test_execute_with_fallback_from_ollama_to_openai(self, mock_ollama, mock_openai):
        """Ollama failures should degrade cleanly to OpenAI."""
        mock_ollama.return_value.chat.return_value = OllamaChatResult(
            success=False,
            content="",
            model="qwen2.5:7b-instruct",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            duration_ms=5.0,
            stop_reason="error",
            error="connection refused",
        )

        mock_openai_response = MagicMock()
        mock_openai_response.id = "resp_ollama_fallback"
        mock_openai_response.output_text = "Fallback from OpenAI"
        mock_openai_response.output = []
        mock_openai_response.status = "completed"
        mock_openai_response.usage.input_tokens = 40
        mock_openai_response.usage.output_tokens = 12
        mock_openai.return_value.responses.create.return_value = mock_openai_response

        router = ModelRouter(multi_model_enabled=True)
        config = MODELS["ollama-general"]

        with patch.object(router.cost_tracker, 'add_cost'):
            result = router.execute_with_fallback(
                model_config=config,
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="You are helpful.",
                tools=None,
            )

        assert result["provider"] == "openai"
        assert "Fallback from OpenAI" in result["content"][0]["text"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
