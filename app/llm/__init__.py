"""
LLM Module - Multi-provider language model support

Exports the main factory and router for use throughout Jarvis.
Also re-exports legacy functions from llm_core.py for backwards compatibility.
"""

from .factory import get_llm_factory, LLMFactory
from .router import LLMRouter, TaskIntent, Complexity, TaskProfile
from .providers import get_provider, get_all_providers

# Re-export legacy functions from llm_core.py for backwards compatibility
from ..llm_core import (
    get_client,
    rewrite_query_for_search,
    chat_with_context,
    get_system_prompt_with_self_model,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_BASE,
    # Phase 18.2: Uncertainty Signaling
    calculate_response_confidence,
    format_confidence_prefix,
)

__all__ = [
    # New multi-provider system
    "get_llm_factory",
    "LLMFactory",
    "LLMRouter",
    "TaskIntent",
    "Complexity",
    "TaskProfile",
    "get_provider",
    "get_all_providers",
    # Legacy functions (backwards compatibility)
    "get_client",
    "rewrite_query_for_search",
    "chat_with_context",
    "get_system_prompt_with_self_model",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_BASE",
    # Phase 18.2: Uncertainty Signaling
    "calculate_response_confidence",
    "format_confidence_prefix",
]
