"""
Model Router: Multi-provider LLM routing with circuit breaker.

T-005 Implementation - Multi-model routing for Jarvis.
Supports Anthropic (Claude) and OpenAI (GPT) with:
- Role-based routing (planner/specialist/reviewer)
- Circuit breaker for failover
- Cost tracking and budget enforcement
- Provider-specific optimizations
- OpenAI Responses API for 40-80% cache improvement (O2)

Default behavior is conservative (single model) unless multi-model enabled.

O2 Responses API Migration:
- Uses client.responses.create() instead of chat.completions.create()
- Enables store=True for server-side state (30-day retention)
- Supports previous_response_id for multi-turn conversations
- Automatic 40-80% cache hit improvement on repeated contexts
"""
import os
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
import threading

from .observability import get_logger, log_with_context, metrics
from .services.ollama_client import OllamaClient

logger = get_logger("jarvis.model_router")


class Provider(str, Enum):
    """LLM Provider."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


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


# Model configurations (prices as of 2026-03)
OLLAMA_DEFAULT_MODEL = os.environ.get("JARVIS_OLLAMA_DEFAULT_MODEL", "qwen2.5:7b-instruct")
OLLAMA_FAST_MODEL = os.environ.get("JARVIS_OLLAMA_FAST_MODEL", OLLAMA_DEFAULT_MODEL)
OLLAMA_GENERAL_MODEL = os.environ.get("JARVIS_OLLAMA_GENERAL_MODEL", OLLAMA_DEFAULT_MODEL)

MODELS = {
    # Ollama (local-first, zero marginal token cost)
    "ollama-fast": ModelConfig(
        provider=Provider.OLLAMA,
        model_id=OLLAMA_FAST_MODEL,
        max_tokens=500,
        input_price_per_1k=0.0,
        output_price_per_1k=0.0
    ),
    "ollama-general": ModelConfig(
        provider=Provider.OLLAMA,
        model_id=OLLAMA_GENERAL_MODEL,
        max_tokens=2500,
        input_price_per_1k=0.0,
        output_price_per_1k=0.0
    ),
    # Anthropic - Updated model IDs for Claude 4.5/4.6
    "claude-haiku-4-5-20251001": ModelConfig(
        provider=Provider.ANTHROPIC,
        model_id="claude-haiku-4-5-20251001",
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

MODEL_ALIASES = {
    "gpt-4o-2024-11-20": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
}


def resolve_model_config(model_id: str) -> Optional[ModelConfig]:
    """Resolve dynamic-router aliases to a canonical model config."""
    canonical_id = MODEL_ALIASES.get(model_id, model_id)
    if canonical_id in MODELS:
        return MODELS[canonical_id]
    if model_id == OLLAMA_FAST_MODEL:
        return MODELS.get("ollama-fast")
    if model_id == OLLAMA_GENERAL_MODEL:
        return MODELS.get("ollama-general")
    if model_id.startswith("gpt-4o-mini-"):
        return MODELS.get("gpt-4o-mini")
    if model_id.startswith("gpt-4o-"):
        return MODELS.get("gpt-4o")
    return None


# Role -> Model mappings (primary and fallback)
ROLE_ROUTING = {
    AgentRole.PLANNER: {
        "primary": "claude-haiku-4-5-20251001",
        "fallback": "gpt-4o-mini",
        "max_tokens": 500
    },
    AgentRole.SPECIALIST: {
        "primary": "claude-sonnet-4-20250514",
        "fallback": "gpt-4o",
        "max_tokens": 4000
    },
    AgentRole.REVIEWER: {
        "primary": "claude-haiku-4-5-20251001",  # Cross-provider by default
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
    "general_chat": {"specialist": Provider.OLLAMA, "reviewer": Provider.OPENAI},
    "cheap_local": {"specialist": Provider.OLLAMA, "reviewer": Provider.OPENAI},
    "speed": {"specialist": Provider.OLLAMA, "reviewer": Provider.OPENAI},
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
    - OpenAI Responses API with server-side caching (O2)

    Usage:
        router = ModelRouter()
        model = router.route_request(AgentRole.SPECIALIST, task_type="code")
        response = router.execute_with_fallback(model, messages)
        # For multi-turn: pass response["openai_response_id"] as previous_response_id
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
            Provider.OLLAMA: CircuitState(),
        }

        # Clients (lazy-loaded)
        self._anthropic_client = None
        self._openai_client = None
        self._ollama_client = None

        # OpenAI Responses API: track last response ID per session for multi-turn
        self._last_openai_response_id: Optional[str] = None

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

    def _get_ollama_client(self) -> OllamaClient:
        """Get or create Ollama client."""
        if self._ollama_client is None:
            self._ollama_client = OllamaClient()
        return self._ollama_client

    def _get_role_provider_model_id(self, role: AgentRole, provider: Provider) -> Optional[str]:
        """Select the role-appropriate model for a provider."""
        role_specific_candidates = {
            AgentRole.PLANNER: ["ollama-fast", "claude-haiku-4-5-20251001", "gpt-4o-mini"],
            AgentRole.SPECIALIST: ["ollama-general", "claude-sonnet-4-20250514", "gpt-4o"],
            AgentRole.REVIEWER: ["ollama-fast", "claude-haiku-4-5-20251001", "gpt-4o-mini"],
        }

        for model_id in role_specific_candidates[role]:
            config = MODELS.get(model_id)
            if config and config.provider == provider:
                return model_id

        return next(
            (model_id for model_id, config in MODELS.items() if config.provider == provider),
            None,
        )

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
                preferred_model_id = self._get_role_provider_model_id(role, preferred_provider)
                if preferred_model_id:
                    primary_model_id = preferred_model_id

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
        max_tokens: Optional[int] = None,
        previous_response_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute request with automatic fallback on failure.

        Args:
            model_config: Model configuration
            messages: List of conversation messages
            system_prompt: System prompt
            tools: Optional list of tool definitions
            max_tokens: Max tokens for response
            previous_response_id: OpenAI Responses API - chain to previous response
            session_id: Optional session ID for response tracking

        Returns:
            Dict with 'content', 'usage', 'model', 'provider', 'stop_reason',
            and 'openai_response_id' for OpenAI (for multi-turn chaining)
        """
        max_tokens = max_tokens or model_config.max_tokens

        try:
            if model_config.provider == Provider.ANTHROPIC:
                result = self._call_anthropic(model_config, messages, system_prompt, tools, max_tokens)
            elif model_config.provider == Provider.OLLAMA:
                result = self._call_ollama(model_config, messages, system_prompt, max_tokens)
            else:
                result = self._call_openai(
                    model_config, messages, system_prompt, tools, max_tokens,
                    previous_response_id=previous_response_id
                )

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

            for fallback_provider in self._get_fallback_provider_chain(model_config.provider):
                if not self.is_provider_available(fallback_provider):
                    continue

                fallback_model_id = self._get_equivalent_model(model_config.model_id, fallback_provider)
                fallback_config = resolve_model_config(fallback_model_id)
                if fallback_config is None:
                    continue

                log_with_context(logger, "info", "Falling back to alternate provider",
                               original=model_config.model_id,
                               fallback_provider=fallback_provider.value,
                               fallback=fallback_config.model_id)

                return self.execute_with_fallback(
                    fallback_config, messages, system_prompt, tools, max_tokens
                )

            raise RuntimeError(f"No fallback provider available after failure: {e}")

    def _get_fallback_provider_chain(self, provider: Provider) -> List[Provider]:
        """Return the ordered fallback chain for a provider."""
        if provider == Provider.OLLAMA:
            return [Provider.OPENAI, Provider.ANTHROPIC]
        if provider == Provider.ANTHROPIC:
            return [Provider.OPENAI, Provider.OLLAMA]
        return [Provider.ANTHROPIC, Provider.OLLAMA]

    def _get_equivalent_model(self, model_id: str, target_provider: Provider) -> str:
        """Get equivalent model from different provider."""
        # Mapping of equivalent models
        equivalents = {
            "claude-haiku-4-5-20251001": "gpt-4o-mini",
            "claude-sonnet-4-20250514": "gpt-4o",
            "gpt-4o-mini": "claude-haiku-4-5-20251001",
            "gpt-4o": "claude-sonnet-4-20250514",
            OLLAMA_FAST_MODEL: "gpt-4o-mini",
            OLLAMA_GENERAL_MODEL: "gpt-4o",
        }
        if target_provider == Provider.OLLAMA:
            if any(token in model_id for token in ("mini", "haiku", "fast")):
                return OLLAMA_FAST_MODEL
            return OLLAMA_GENERAL_MODEL

        if target_provider == Provider.OPENAI:
            return equivalents.get(model_id, "gpt-4o")

        return equivalents.get(model_id, "claude-sonnet-4-20250514")

    def _call_ollama(
        self,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Call Ollama through the shared OpenAI-compatible client."""
        client = self._get_ollama_client()
        result = client.chat(
            model=model_config.model_id,
            messages=messages,
            system=system_prompt,
            max_tokens=max_tokens,
        )

        if not result.success:
            raise RuntimeError(result.error or "Ollama request failed")

        return {
            "content": [{"type": "text", "text": result.content}],
            "usage": {
                "input_tokens": result.prompt_tokens,
                "output_tokens": result.completion_tokens,
            },
            "model": result.model,
            "provider": Provider.OLLAMA.value,
            "stop_reason": "end_turn" if result.stop_reason == "stop" else result.stop_reason,
        }

    def _call_anthropic(
        self,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: Optional[List[Dict]],
        max_tokens: int,
        enable_prompt_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Call Anthropic API with prompt caching (O3).

        O3 Prompt Caching:
        - Converts system prompt to cached content blocks
        - Saves up to 90% on input costs for repeated prompts
        - 5-minute cache TTL on Anthropic's side
        """
        client = self._get_anthropic_client()

        # O3: Build cached system prompt
        if enable_prompt_cache:
            system_param = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        else:
            system_param = system_prompt

        kwargs = {
            "model": model_config.model_id,
            "max_tokens": max_tokens,
            "system": system_param,
            "messages": messages
        }
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        # O3: Log cache stats if available
        if hasattr(response.usage, 'cache_creation_input_tokens'):
            cache_created = getattr(response.usage, 'cache_creation_input_tokens', 0)
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            if cache_created > 0 or cache_read > 0:
                log_with_context(logger, "debug", "Anthropic prompt cache stats",
                               cache_created=cache_created, cache_read=cache_read)

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
        max_tokens: int,
        previous_response_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call OpenAI Responses API (O2 Migration).

        Uses Responses API instead of Chat Completions for:
        - Server-side state with store=True (30-day retention)
        - Multi-turn chaining with previous_response_id
        - 40-80% cache improvement on repeated contexts
        """
        client = self._get_openai_client()

        input_messages = self._build_openai_input_messages(
            messages=messages,
            system_prompt=system_prompt,
            previous_response_id=previous_response_id,
        )

        # Convert tools format for Responses API
        openai_tools = None
        if tools:
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                })

        # Build Responses API kwargs
        kwargs = {
            "model": model_config.model_id,
            "input": input_messages,
            "store": True,  # O2: Enable server-side caching (30-day retention)
        }

        # Add max_tokens if supported by model
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens

        # O2: Chain to previous response for multi-turn
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
            log_with_context(logger, "debug", "Using previous_response_id for caching",
                           previous_id=previous_response_id[:20] + "...")
            # Export O2 cache hit metric
            try:
                from .prometheus_exporter import get_prometheus_exporter
                exporter = get_prometheus_exporter()
                exporter.export_llm_cache_hit("openai_response")
            except Exception:
                pass

        if openai_tools:
            kwargs["tools"] = openai_tools

        # Call Responses API
        response = client.responses.create(**kwargs)

        # Store response ID for potential multi-turn
        self._last_openai_response_id = response.id
        log_with_context(logger, "debug", "OpenAI Responses API call",
                        response_id=response.id[:20] + "...",
                        store=True)

        # Extract content from Responses API format
        content = []
        saw_function_call = False

        # Handle output_text (simple text response)
        if hasattr(response, 'output_text') and response.output_text:
            content.append({"type": "text", "text": response.output_text})

        # Handle output array (structured response with potential tool calls)
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'type'):
                    if item.type == "message":
                        # Extract text from message content
                        if hasattr(item, 'content'):
                            for c in item.content:
                                if hasattr(c, 'type') and c.type == "output_text":
                                    if hasattr(c, 'text'):
                                        content.append({"type": "text", "text": c.text})
                    elif item.type == "function_call":
                        import json
                        saw_function_call = True
                        content.append({
                            "type": "tool_use",
                            "id": item.call_id if hasattr(item, 'call_id') else item.id,
                            "name": item.name,
                            "input": json.loads(item.arguments) if isinstance(item.arguments, str) else item.arguments
                        })

        # Map status to Anthropic stop_reason
        stop_reason_map = {
            "completed": "end_turn",
            "incomplete": "max_tokens",
        }
        status = getattr(response, 'status', 'completed')
        stop_reason = "tool_use" if saw_function_call else stop_reason_map.get(status, status)

        # Extract usage (Responses API format)
        usage = {"input_tokens": 0, "output_tokens": 0}
        if hasattr(response, 'usage'):
            usage["input_tokens"] = getattr(response.usage, 'input_tokens', 0)
            usage["output_tokens"] = getattr(response.usage, 'output_tokens', 0)

        return {
            "content": content,
            "usage": usage,
            "model": model_config.model_id,
            "provider": Provider.OPENAI.value,
            "stop_reason": stop_reason,
            "openai_response_id": response.id  # O2: Return for multi-turn chaining
        }

    def _build_openai_input_messages(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        previous_response_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert shared agent messages into Responses API input items."""
        input_messages: List[Dict[str, Any]] = [
            {"role": "developer", "content": system_prompt}
        ]

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role == "tool":
                input_messages.extend(self._build_openai_tool_outputs(content))
                continue

            converted_content = self._flatten_openai_message_content(
                content=content,
                previous_response_id=previous_response_id,
            )
            if converted_content is None:
                continue

            input_messages.append({"role": role, "content": converted_content})

        return input_messages

    def _build_openai_tool_outputs(self, content: Any) -> List[Dict[str, Any]]:
        """Convert normalized tool results into Responses API function outputs."""
        outputs: List[Dict[str, Any]] = []

        if not isinstance(content, list):
            return outputs

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue

            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.get("tool_use_id"),
                    "output": item.get("content", ""),
                }
            )

        return outputs

    def _flatten_openai_message_content(
        self,
        content: Any,
        previous_response_id: Optional[str] = None,
    ) -> Optional[str]:
        """Flatten shared message content into the text form Responses API accepts."""
        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    text_parts.append(str(item))
                    continue

                item_type = item.get("type")
                if item_type == "text":
                    text_value = item.get("text", "")
                    if text_value:
                        text_parts.append(text_value)
                elif item_type == "tool_result":
                    text_parts.append(f"[Tool Result: {item.get('content', '')}]")
                elif item_type == "tool_use" and not previous_response_id:
                    tool_name = item.get("name", "tool")
                    text_parts.append(f"[Tool Call Requested: {tool_name}]")

            if not text_parts:
                return None

            return "\n".join(text_parts)

        if content is None:
            return None

        return content


    def get_last_openai_response_id(self) -> Optional[str]:
        """Get the last OpenAI Responses API response ID for multi-turn chaining."""
        return self._last_openai_response_id

    def clear_openai_response_chain(self) -> None:
        """Clear the response chain (start fresh conversation)."""
        self._last_openai_response_id = None
        log_with_context(logger, "debug", "OpenAI response chain cleared")


# Singleton instance
_router: Optional[ModelRouter] = None


def get_router(multi_model_enabled: bool = None, daily_budget_usd: float = None) -> ModelRouter:
    """Get or create the model router singleton.

    Environment variables:
        MULTI_MODEL_ENABLED: "true" to enable multi-model routing (default: false)
        DAILY_BUDGET_USD: Daily budget limit (default: 10.0)
    """
    global _router
    if _router is None:
        # Read from env vars if not explicitly set
        if multi_model_enabled is None:
            multi_model_enabled = os.environ.get("MULTI_MODEL_ENABLED", "false").lower() == "true"
        if daily_budget_usd is None:
            daily_budget_usd = float(os.environ.get("DAILY_BUDGET_USD", "10.0"))

        _router = ModelRouter(
            multi_model_enabled=multi_model_enabled,
            daily_budget_usd=daily_budget_usd
        )
        logger.info(f"ModelRouter initialized: multi_model={multi_model_enabled}, budget=${daily_budget_usd}")
    return _router
