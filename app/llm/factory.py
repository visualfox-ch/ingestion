"""
LLM Factory - Unified interface for multi-provider LLM operations
"""
import time
from typing import List, Dict, Any, Optional
from .providers import get_provider, get_all_providers, LLMProvider
from .router import LLMRouter, TaskIntent, Complexity, TaskProfile
from ..observability import get_logger, log_with_context, metrics
from .. import config

logger = get_logger("jarvis.llm.factory")


class LLMFactory:
    """
    Factory for LLM operations with intelligent routing.
    
    Features:
    - Automatic provider selection based on task type
    - Cost optimization
    - Unified error handling
    - Langfuse integration (via parent caller)
    """
    
    def __init__(self):
        self.router = LLMRouter()
        self._providers_cache = None
        self._circuit = {}  # provider_name -> {"failures":[ts...], "opened_until": float}

    def _circuit_state(self, provider_name: str) -> Dict[str, Any]:
        return self._circuit.setdefault(provider_name, {"failures": [], "opened_until": 0.0})

    @staticmethod
    def _is_transient_error(err: Exception) -> bool:
        name = type(err).__name__.lower()
        msg = str(err).lower()
        markers = (
            "timeout",
            "timed out",
            "rate limit",
            "429",
            "connection",
            "connection reset",
            "temporarily unavailable",
            "overloaded",
            "service unavailable",
            "502",
            "503",
            "504",
        )
        haystack = f"{name} {msg}"
        return any(m in haystack for m in markers)

    def _circuit_is_open(self, provider_name: str) -> bool:
        if not config.LLM_CIRCUIT_BREAKER_ENABLED:
            return False
        state = self._circuit_state(provider_name)
        return time.time() < float(state.get("opened_until", 0.0) or 0.0)

    def _circuit_on_success(self, provider_name: str) -> None:
        if not config.LLM_CIRCUIT_BREAKER_ENABLED:
            return
        state = self._circuit_state(provider_name)
        state["failures"] = []
        state["opened_until"] = 0.0

    def _circuit_on_failure(self, provider_name: str, err: Exception) -> None:
        if not config.LLM_CIRCUIT_BREAKER_ENABLED:
            return
        if not self._is_transient_error(err):
            return

        threshold = max(1, int(config.LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD))
        window_s = max(1, int(config.LLM_CIRCUIT_BREAKER_WINDOW_SECONDS))
        cooldown_s = max(1, int(config.LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS))

        now = time.time()
        state = self._circuit_state(provider_name)
        failures = [t for t in state.get("failures", []) if (now - float(t)) <= window_s]
        failures.append(now)
        state["failures"] = failures

        if len(failures) >= threshold:
            state["failures"] = []
            state["opened_until"] = now + cooldown_s
            metrics.inc("llm_circuit_open_total")
            metrics.inc(f"llm_circuit_open_by_provider_{provider_name}")
            log_with_context(
                logger,
                "warning",
                "LLM circuit opened",
                provider=provider_name,
                window_seconds=window_s,
                threshold=threshold,
                cooldown_seconds=cooldown_s,
                error_type=type(err).__name__,
                error=str(err)[:200],
            )

    @property
    def available_providers(self) -> List[str]:
        """Get list of available provider names"""
        if self._providers_cache is None:
            self._providers_cache = []
            for provider in get_all_providers():
                try:
                    health = provider.health_check()
                    if health["status"] == "healthy":
                        self._providers_cache.append(provider.provider_name)
                except Exception as e:
                    log_with_context(
                        logger, "warning",
                        f"Provider {provider.provider_name} health check failed",
                        error=str(e)
                    )
        return self._providers_cache
    
    def call(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        intent: Optional[TaskIntent] = None,
        complexity: Optional[Complexity] = None,
        model_override: Optional[str] = None,
        max_tokens_override: Optional[int] = None,
        query_for_classification: str = "",
        context_size: int = 0,
    ) -> Dict[str, Any]:
        """
        Call LLM with intelligent routing.
        
        Args:
            messages: Chat messages
            system_prompt: System prompt
            intent: Task intent (auto-detected if None)
            complexity: Task complexity (auto-detected if None)
            model_override: Force specific model (skips routing)
            max_tokens_override: Override max tokens
            query_for_classification: Query text for auto-classification
            context_size: Approximate context size in chars
        
        Returns:
            {
                "response": "...",
                "model": "claude-...",
                "provider": "anthropic",
                "tokens": {"input": ..., "output": ...},
                "cost_usd": 0.0125,
            }
        """
        start_time = time.time()
        task = None
        provider_name = None
        model_name = None
        
        try:
            # Determine model
            if model_override:
                config = {"model": model_override}
                provider_name, model_name = self._resolve_model_and_provider(model_override)
            else:
                # Classify task
                task = self.router.classify_task(
                    query_for_classification,
                    context_size,
                    intent_hint=intent
                )
                
                # Get config
                config = self.router.get_best_available_model(
                    task,
                    available_providers=self.available_providers
                )
                provider_name = config.get("provider")
                model_name = config.get("model")
            
            max_tokens = max_tokens_override or config.get("max_tokens", 2048)
            timeout = config.get("timeout", 30)

            # Circuit breaker: fail fast (and optionally re-route) on transient provider outages
            if provider_name and self._circuit_is_open(provider_name):
                metrics.inc("llm_circuit_reject_total")
                metrics.inc(f"llm_circuit_reject_by_provider_{provider_name}")
                log_with_context(
                    logger,
                    "warning",
                    "LLM circuit open; rejecting call",
                    provider=provider_name,
                    model=model_name,
                )

                if task is not None and not model_override:
                    fallback_providers = [p for p in self.available_providers if not self._circuit_is_open(p)]
                    if fallback_providers:
                        config = self.router.get_best_available_model(task, available_providers=fallback_providers)
                        provider_name = config.get("provider")
                        model_name = config.get("model")
                        max_tokens = max_tokens_override or config.get("max_tokens", 2048)
                        timeout = config.get("timeout", 30)
                    else:
                        raise RuntimeError(f"LLM circuit open for all providers (last tried: {provider_name})")
                else:
                    raise RuntimeError(f"LLM circuit open for provider: {provider_name}")
            
            # Budget check (Tier 1 Quick Win)
            from ..services.cost_tracker import check_budget_before_llm_call, get_budget_manager, BudgetExceededException
            budget_ok, budget_error = check_budget_before_llm_call(
                estimated_tokens=max_tokens * 2,  # Rough estimate: input + output
                model=model_name,
                budget_id="daily"
            )
            if not budget_ok:
                metrics.inc("llm_budget_rejected_total")
                log_with_context(logger, "warning", "LLM call rejected: budget exceeded",
                               error=budget_error, model=model_name)
                raise BudgetExceededException(budget_error)

            # Get provider
            provider = get_provider(provider_name)

            # Extract effort from config (for latency optimization)
            effort = config.get("effort")  # "low", "medium", "high", or None

            # Call
            response_text, usage = provider.call(
                messages=messages,
                system=system_prompt,
                model=model_name,
                max_tokens=max_tokens,
                timeout=timeout,
                effort=effort,
            )

            if provider_name:
                self._circuit_on_success(provider_name)
            
            # Calculate cost
            cost = provider.calculate_cost(
                model_name,
                usage["input_tokens"],
                usage["output_tokens"]
            )

            # Track against budget
            try:
                budget_manager = get_budget_manager()
                budget_manager.add_spent("daily", cost)
            except Exception as budget_err:
                log_with_context(logger, "debug", "Budget tracking failed", error=str(budget_err))

            duration_ms = (time.time() - start_time) * 1000

            # Log metrics
            metrics.inc("llm_api_calls_total")
            metrics.observe("llm_call_duration_ms", duration_ms)
            metrics.inc(f"llm_calls_by_provider_{provider_name}")
            metrics.inc(f"llm_calls_by_model_{model_name.replace('-', '_')}")
            if effort:
                metrics.inc(f"llm_calls_by_effort_{effort}")
            
            log_with_context(
                logger, "info",
                f"LLM call successful ({provider_name})",
                model=model_name,
                effort=effort or "default",
                tokens_in=usage["input_tokens"],
                tokens_out=usage["output_tokens"],
                cost_usd=f"${cost:.4f}",
                latency_ms=round(duration_ms, 1),
            )
            
            return {
                "response": response_text,
                "model": model_name,
                "provider": provider_name,
                "tokens": usage,
                "cost_usd": cost,
                "latency_ms": round(duration_ms, 1),
            }
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            metrics.inc("llm_api_errors_total")

            if provider_name:
                self._circuit_on_failure(provider_name, e)
            
            log_with_context(
                logger, "error",
                "LLM call failed",
                error=str(e)[:200],
                error_type=type(e).__name__,
                latency_ms=round(duration_ms, 1),
            )
            raise
    
    @staticmethod
    def _resolve_model_and_provider(model_str: str) -> tuple[str, str]:
        """
        Resolve provider from model string.
        
        Examples:
            "gpt-4-turbo" → ("openai", "gpt-4-turbo")
            "claude-opus-4-20250514" → ("anthropic", "claude-opus-4-20250514")
        """
        if model_str.startswith("gpt") or model_str.startswith("text-"):
            return "openai", model_str
        return "anthropic", model_str
    
    def get_provider_stats(self) -> Dict[str, Any]:
        """Get health and capability info for all providers"""
        stats = {}
        
        for provider in get_all_providers():
            try:
                health = provider.health_check()
                stats[provider.provider_name] = health
            except Exception as e:
                stats[provider.provider_name] = {
                    "status": "error",
                    "error": str(e)
                }
        
        return stats


# Singleton instance
_factory = None

def get_llm_factory() -> LLMFactory:
    """Get or create LLM factory singleton"""
    global _factory
    if _factory is None:
        _factory = LLMFactory()
    return _factory
