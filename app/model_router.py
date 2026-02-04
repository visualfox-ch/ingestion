"""
Model Router: Multi-provider LLM routing with circuit breaker.

T-005 Implementation - Multi-model routing for Jarvis.
Supports Anthropic (Claude) and OpenAI (GPT) with:
- Role-based routing (planner/specialist/reviewer)
- Circuit breaker for failover
- Cost tracking and budget enforcement
- Provider-specific optimizations

Default behavior is conservative (single model) unless multi-model enabled.
"""
import os
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
import threading

from .observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.model_router")


class Provider(str, Enum):
    """LLM Provider."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class AgentRole(str, Enum):
    """Subagent roles for multi-model orchestration."""
    PLANNER = "planner"      # Fast, cheap - task decomposition
    SPECIALIST = "specialist"  # Powerful - main work
    REVIEWER = "reviewer"     # Cross-check, different provider preferred


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    provider: Provider
    model_id: str
    max_tokens: int
    input_price_per_1k: float   # USD per 1K input tokens
    output_price_per_1k: float  # USD per 1K output tokens

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD."""
        return (
            (input_tokens / 1000) * self.input_price_per_1k +
            (output_tokens / 1000) * self.output_price_per_1k
        )


# Model configurations (prices as of 2026-02)
MODELS = {
    # Anthropic
    "claude-3-5-haiku-20241022": ModelConfig(
        provider=Provider.ANTHROPIC,
        model_id="claude-3-5-haiku-20241022",
        max_tokens=500,  # Planner default
        input_price_per_1k=0.001,
        output_price_per_1k=0.005
    ),
    "claude-sonnet-4-20250514": ModelConfig(
        provider=Provider.ANTHROPIC,
        model_id="claude-sonnet-4-20250514",
        max_tokens=4000,  # Specialist default
        input_price_per_1k=0.003,
        output_price_per_1k=0.015
    ),
    # OpenAI
    "gpt-4o-mini": ModelConfig(
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        max_tokens=500,  # Planner default
        input_price_per_1k=0.00015,
        output_price_per_1k=0.0006
    ),
    "gpt-4o": ModelConfig(
        provider=Provider.OPENAI,
        model_id="gpt-4o",
        max_tokens=4000,  # Specialist default
        input_price_per_1k=0.005,
        output_price_per_1k=0.015
    ),
}


# Role -> Model mappings (primary and fallback)
ROLE_ROUTING = {
    AgentRole.PLANNER: {
        "primary": "claude-3-5-haiku-20241022",
        "fallback": "gpt-4o-mini",
        "max_tokens": 500
    },
    AgentRole.SPECIALIST: {
        "primary": "claude-sonnet-4-20250514",
        "fallback": "gpt-4o",
        "max_tokens": 4000
    },
    AgentRole.REVIEWER: {
        "primary": "claude-3-5-haiku-20241022",  # Cross-provider by default
        "fallback": "gpt-4o-mini",
        "max_tokens": 800
    }
}


# Task type -> Provider preferences
TASK_ROUTING_PREFERENCES = {
    "code": {"specialist": Provider.ANTHROPIC, "reviewer": Provider.OPENAI},
    "ops": {"specialist": Provider.ANTHROPIC, "reviewer": Provider.ANTHROPIC},  # Safety-critical
    "writing": {"specialist": Provider.OPENAI, "reviewer": Provider.ANTHROPIC},
    "research": {"specialist": Provider.ANTHROPIC, "reviewer": Provider.OPENAI},
}


@dataclass
class CircuitState:
    """State for circuit breaker pattern."""
    failures: int = 0
    last_failure: Optional[float] = None
    open_until: Optional[float] = None  # Timestamp when circuit can close

    def is_open(self) -> bool:
        """Check if circuit is open (provider unavailable)."""
        if self.open_until is None:
            return False
        return time.time() < self.open_until

    def record_failure(self) -> None:
        """Record a failure."""
        now = time.time()
        # Reset if last failure was > 5 min ago
        if self.last_failure and (now - self.last_failure) > 300:
            self.failures = 0

        self.failures += 1
        self.last_failure = now

        # Open circuit after 3 failures in 5 min
        if self.failures >= 3:
            self.open_until = now + 600  # 10 min cooldown
            log_with_context(logger, "warning", "Circuit breaker opened",
                           failures=self.failures, cooldown_minutes=10)

    def record_success(self) -> None:
        """Record a success, potentially closing circuit."""
        self.failures = 0
        self.open_until = None

    def reset(self) -> None:
        """Reset circuit state."""
        self.failures = 0
        self.last_failure = None
        self.open_until = None


@dataclass
class CostTracker:
    """Track LLM costs with daily budget enforcement."""
    daily_budget_usd: float = 10.0  # Default $10/day
    alert_threshold: float = 0.8    # Alert at 80% spend

    # Tracking
    _costs: Dict[str, float] = field(default_factory=dict)  # date -> total
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def add_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Add cost from a request, return total for today."""
        if model_id not in MODELS:
            return 0.0

        config = MODELS[model_id]
        cost = config.calculate_cost(input_tokens, output_tokens)

        with self._lock:
            today = self._today()
            self._costs[today] = self._costs.get(today, 0.0) + cost
            daily_total = self._costs[today]

        # Log and track
        metrics.inc("model_router_cost_usd", cost)
        log_with_context(logger, "debug", "Cost tracked",
                        model=model_id, cost_usd=round(cost, 4),
                        daily_total=round(daily_total, 2))

        # Check alert threshold
        if daily_total >= self.daily_budget_usd * self.alert_threshold:
            log_with_context(logger, "warning", "Daily budget alert",
                           spent=round(daily_total, 2),
                           budget=self.daily_budget_usd,
                           threshold_pct=int(self.alert_threshold * 100))
            metrics.inc("model_router_budget_alert")

        return daily_total

    def get_daily_remaining(self) -> float:
        """Get remaining budget for today."""
        with self._lock:
            today = self._today()
            spent = self._costs.get(today, 0.0)
        return max(0, self.daily_budget_usd - spent)

    def is_over_budget(self) -> bool:
        """Check if daily budget exceeded."""
        return self.get_daily_remaining() <= 0


class ModelRouter:
    """
    Routes requests to appropriate LLM providers based on role and task type.

    Features:
    - Role-based model selection (planner/specialist/reviewer)
    - Circuit breaker for provider failover
    - Cost tracking with daily budget
    - Task-type routing preferences

    Usage:
        router = ModelRouter()
        model = router.route_request(AgentRole.SPECIALIST, task_type="code")
        response = router.execute_with_fallback(model, messages)
    """

    def __init__(
        self,
        multi_model_enabled: bool = False,
        daily_budget_usd: float = 10.0
    ):
        self.multi_model_enabled = multi_model_enabled
        self.cost_tracker = CostTracker(daily_budget_usd=daily_budget_usd)

        # Circuit breakers per provider
        self._circuits: Dict[Provider, CircuitState] = {
            Provider.ANTHROPIC: CircuitState(),
            Provider.OPENAI: CircuitState(),
        }

        # Clients (lazy-loaded)
        self._anthropic_client = None
        self._openai_client = None

    def _get_anthropic_client(self):
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                secrets_path = "/brain/system/secrets/anthropic_api_key.txt"
                if os.path.exists(secrets_path):
                    with open(secrets_path) as f:
                        api_key = f.read().strip()
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            self._anthropic_client = anthropic.Anthropic(api_key=api_key)
        return self._anthropic_client

    def _get_openai_client(self):
        """Get or create OpenAI client."""
        if self._openai_client is None:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                secrets_path = "/brain/system/secrets/openai_api_key.txt"
                if os.path.exists(secrets_path):
                    with open(secrets_path) as f:
                        api_key = f.read().strip()
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client

    def is_provider_available(self, provider: Provider) -> bool:
        """Check if provider is available (circuit closed)."""
        return not self._circuits[provider].is_open()

    def route_request(
        self,
        role: AgentRole = AgentRole.SPECIALIST,
        task_type: Optional[str] = None,
        prefer_cross_provider: bool = False,
        previous_provider: Optional[Provider] = None
    ) -> ModelConfig:
        """
        Select the best model for a request.

        Args:
            role: Agent role (planner, specialist, reviewer)
            task_type: Optional task type for preferences (code, ops, writing, research)
            prefer_cross_provider: If True, prefer different provider than previous
            previous_provider: Provider used in previous step (for cross-provider review)

        Returns:
            ModelConfig for the selected model
        """
        if not self.multi_model_enabled:
            # Conservative: always use default specialist model
            return MODELS["claude-sonnet-4-20250514"]

        routing = ROLE_ROUTING[role]
        primary_model_id = routing["primary"]
        fallback_model_id = routing["fallback"]

        # Apply task-type preferences
        if task_type and task_type in TASK_ROUTING_PREFERENCES:
            prefs = TASK_ROUTING_PREFERENCES[task_type]
            role_key = "specialist" if role == AgentRole.SPECIALIST else "reviewer"
            preferred_provider = prefs.get(role_key)

            if preferred_provider:
                # Find model matching preferred provider
                for model_id, config in MODELS.items():
                    if config.provider == preferred_provider:
                        if role == AgentRole.PLANNER and "haiku" in model_id or "mini" in model_id:
                            primary_model_id = model_id
                            break
                        elif role == AgentRole.SPECIALIST and ("sonnet" in model_id or model_id == "gpt-4o"):
                            primary_model_id = model_id
                            break

        # Cross-provider preference (for reviewers)
        if prefer_cross_provider and previous_provider:
            primary_config = MODELS[primary_model_id]
            if primary_config.provider == previous_provider:
                # Swap to fallback (different provider)
                primary_model_id, fallback_model_id = fallback_model_id, primary_model_id

        # Check circuit breaker
        primary_config = MODELS[primary_model_id]
        if not self.is_provider_available(primary_config.provider):
            log_with_context(logger, "info", "Primary provider unavailable, using fallback",
                           primary=primary_model_id, fallback=fallback_model_id)
            metrics.inc("model_router_fallback")
            return MODELS[fallback_model_id]

        return primary_config

    def execute_with_fallback(
        self,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute request with automatic fallback on failure.

        Returns:
            Dict with 'content', 'usage', 'model', 'provider', 'stop_reason'
        """
        max_tokens = max_tokens or model_config.max_tokens

        try:
            if model_config.provider == Provider.ANTHROPIC:
                result = self._call_anthropic(model_config, messages, system_prompt, tools, max_tokens)
            else:
                result = self._call_openai(model_config, messages, system_prompt, tools, max_tokens)

            # Record success
            self._circuits[model_config.provider].record_success()

            # Track cost
            self.cost_tracker.add_cost(
                model_config.model_id,
                result["usage"]["input_tokens"],
                result["usage"]["output_tokens"]
            )

            return result

        except Exception as e:
            log_with_context(logger, "error", "Model call failed",
                           model=model_config.model_id, error=str(e))

            # Record failure and try fallback
            self._circuits[model_config.provider].record_failure()
            metrics.inc("model_router_failure")

            # Find fallback model
            fallback_provider = (
                Provider.OPENAI if model_config.provider == Provider.ANTHROPIC
                else Provider.ANTHROPIC
            )

            if not self.is_provider_available(fallback_provider):
                raise RuntimeError(f"Both providers unavailable: {e}")

            # Get equivalent model from fallback provider
            fallback_model_id = self._get_equivalent_model(model_config.model_id, fallback_provider)
            fallback_config = MODELS[fallback_model_id]

            log_with_context(logger, "info", "Falling back to alternate provider",
                           original=model_config.model_id, fallback=fallback_model_id)

            return self.execute_with_fallback(
                fallback_config, messages, system_prompt, tools, max_tokens
            )

    def _get_equivalent_model(self, model_id: str, target_provider: Provider) -> str:
        """Get equivalent model from different provider."""
        # Mapping of equivalent models
        equivalents = {
            "claude-3-5-haiku-20241022": "gpt-4o-mini",
            "claude-sonnet-4-20250514": "gpt-4o",
            "gpt-4o-mini": "claude-3-5-haiku-20241022",
            "gpt-4o": "claude-sonnet-4-20250514",
        }
        return equivalents.get(model_id, "gpt-4o" if target_provider == Provider.OPENAI else "claude-sonnet-4-20250514")

    def _call_anthropic(
        self,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: Optional[List[Dict]],
        max_tokens: int
    ) -> Dict[str, Any]:
        """Call Anthropic API."""
        client = self._get_anthropic_client()

        kwargs = {
            "model": model_config.model_id,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages
        }
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        # Extract content
        content = []
        for block in response.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })

        return {
            "content": content,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            "model": model_config.model_id,
            "provider": Provider.ANTHROPIC.value,
            "stop_reason": response.stop_reason
        }

    def _call_openai(
        self,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: Optional[List[Dict]],
        max_tokens: int
    ) -> Dict[str, Any]:
        """Call OpenAI API."""
        client = self._get_openai_client()

        # Convert messages format (Anthropic -> OpenAI)
        openai_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, list):
                # Handle tool results - convert to OpenAI format
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "tool_result":
                            text_parts.append(f"[Tool Result: {item.get('content', '')}]")
                content = "\n".join(text_parts) if text_parts else str(content)

            openai_messages.append({"role": role, "content": content})

        # Convert tools format
        openai_tools = None
        if tools:
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {})
                    }
                })

        kwargs = {
            "model": model_config.model_id,
            "max_tokens": max_tokens,
            "messages": openai_messages
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = client.chat.completions.create(**kwargs)

        # Extract content (convert back to Anthropic-like format)
        content = []
        choice = response.choices[0]
        if choice.message.content:
            content.append({"type": "text", "text": choice.message.content})

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments) if tc.function.arguments else {}
                })

        # Map finish reason to Anthropic stop_reason
        stop_reason_map = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens"
        }
        stop_reason = stop_reason_map.get(choice.finish_reason, choice.finish_reason)

        return {
            "content": content,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            },
            "model": model_config.model_id,
            "provider": Provider.OPENAI.value,
            "stop_reason": stop_reason
        }


# Singleton instance
_router: Optional[ModelRouter] = None


def get_router(multi_model_enabled: bool = False, daily_budget_usd: float = 10.0) -> ModelRouter:
    """Get or create the model router singleton."""
    global _router
    if _router is None:
        _router = ModelRouter(
            multi_model_enabled=multi_model_enabled,
            daily_budget_usd=daily_budget_usd
        )
    return _router
