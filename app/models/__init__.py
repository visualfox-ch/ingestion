"""
Models subpackage: LLM provider clients and routing infrastructure.

T-005 Implementation.

Components:
- circuit_breaker: Provider failover logic
- anthropic_client: Anthropic/Claude API wrapper
- openai_client: OpenAI/GPT API wrapper

The main ModelRouter in model_router.py uses these components.
"""
from .circuit_breaker import CircuitBreaker, CircuitState

__all__ = ["CircuitBreaker", "CircuitState"]
