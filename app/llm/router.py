"""
Intelligent LLM Router

Routes tasks to optimal model based on:
- Task complexity/type
- Cost efficiency
- Model capabilities
- Context window requirements

T-025: Added Ollama for LOW complexity with fast fallback to Haiku
"""
import os
import time
import logging
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any
from enum import Enum

from .providers import ModelConfig

logger = logging.getLogger(__name__)

# Ollama health check cache (avoid repeated checks)
_ollama_available: Optional[bool] = None
_ollama_last_check: float = 0
OLLAMA_CHECK_INTERVAL = 30.0  # Re-check every 30 seconds
OLLAMA_HEALTH_TIMEOUT = 0.5   # 500ms timeout for health check


class TaskIntent(str, Enum):
    """Task classification"""
    SEARCH = "search"               # Simple query rewriting
    EXTRACT = "extract"             # Data extraction, profiles
    CHAT = "chat"                   # Conversational responses
    SUMMARIZE = "summarize"         # Content summarization
    ANALYZE = "analyze"             # Complex analysis
    REASON = "reason"               # Multi-step reasoning
    CODE = "code"                   # Code generation/analysis
    AGENT = "agent"                 # Agent loop execution


class Complexity(str, Enum):
    """Task complexity level"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TaskProfile:
    """Classified task profile"""
    intent: TaskIntent
    complexity: Complexity
    estimated_tokens: int
    requires_function_calling: bool = False
    requires_long_context: bool = False


def is_ollama_available() -> bool:
    """
    Fast check if Ollama (laptop) is reachable.
    Caches result for OLLAMA_CHECK_INTERVAL seconds.
    Returns False immediately if check times out (500ms).
    """
    global _ollama_available, _ollama_last_check

    now = time.time()
    if _ollama_available is not None and (now - _ollama_last_check) < OLLAMA_CHECK_INTERVAL:
        logger.debug(f"Ollama check cached: {_ollama_available}")
        return _ollama_available

    import requests

    ollama_url = os.environ.get(
        "JARVIS_OLLAMA_BASE_URL",
        os.environ.get("OLLAMA_HOST", "http://192.168.1.115:11434")
    )

    try:
        resp = requests.get(
            f"{ollama_url.rstrip('/')}/api/tags",
            timeout=OLLAMA_HEALTH_TIMEOUT
        )
        _ollama_available = resp.status_code == 200
        logger.info(f"Ollama check: {ollama_url} -> {_ollama_available}")
    except Exception as e:
        _ollama_available = False
        logger.info(f"Ollama check failed: {ollama_url} -> {e}")

    _ollama_last_check = now

    if not _ollama_available:
        logger.debug("Ollama unavailable, will use API fallback")

    return _ollama_available


class LLMRouter:
    """
    Intelligent router for optimal LLM selection.

    Strategy:
    - Low complexity → Ollama (free, fast) with Haiku fallback
    - Medium → Sonnet (best balance) + effort: medium
    - High complexity → Sonnet (best reasoning) + effort: high
    """

    # Ollama config for LOW complexity (laptop, free)
    OLLAMA_CONFIG = {
        "model": os.environ.get("JARVIS_OLLAMA_DEFAULT_MODEL", "phi4-mini"),
        "provider": "ollama",
        "max_tokens": 512,
        "timeout": 10,
        "effort": "low",
    }

    # Haiku fallback for LOW complexity (fast API fallback)
    HAIKU_FALLBACK = {
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "max_tokens": 512,
        "timeout": 5,
        "effort": "low",
    }

    # Default routing matrix: (intent, complexity) → model_name + effort
    ROUTING_TABLE = {
        # Low complexity - Ollama first, Haiku fallback
        (TaskIntent.SEARCH, Complexity.LOW): {
            "model": "claude-haiku-4-5",
            "provider": "anthropic",
            "max_tokens": 256,
            "timeout": 3,
            "effort": "low",
            "ollama_eligible": True,  # Can use Ollama if available
        },
        (TaskIntent.EXTRACT, Complexity.LOW): {
            "model": "claude-haiku-4-5",
            "provider": "anthropic",
            "max_tokens": 512,
            "timeout": 5,
            "effort": "low",
            "ollama_eligible": True,
        },
        (TaskIntent.CHAT, Complexity.LOW): {
            "model": "claude-haiku-4-5",
            "provider": "anthropic",
            "max_tokens": 512,
            "timeout": 5,
            "effort": "low",
            "ollama_eligible": True,
        },
        (TaskIntent.SUMMARIZE, Complexity.LOW): {
            "model": "claude-haiku-4-5",
            "provider": "anthropic",
            "max_tokens": 512,
            "timeout": 5,
            "effort": "low",
            "ollama_eligible": True,
        },

        # Medium complexity - balance cost & quality
        (TaskIntent.CHAT, Complexity.MEDIUM): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 15,
            "effort": "medium",
        },
        (TaskIntent.SUMMARIZE, Complexity.MEDIUM): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 1024,
            "timeout": 10,
            "effort": "medium",
        },
        (TaskIntent.EXTRACT, Complexity.MEDIUM): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 1024,
            "timeout": 10,
            "effort": "medium",
        },

        # High complexity - optimize for quality
        (TaskIntent.ANALYZE, Complexity.HIGH): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 25,
            "effort": "high",
        },
        (TaskIntent.REASON, Complexity.HIGH): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 25,
            "effort": "high",
        },
        (TaskIntent.AGENT, Complexity.HIGH): {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 4096,
            "timeout": 60,
            "effort": "high",
        },

        # Code generation - GPT-4o or Claude
        (TaskIntent.CODE, Complexity.HIGH): {
            "model": "gpt-4o",
            "provider": "openai",
            "max_tokens": 4096,
            "timeout": 20,
        },
        (TaskIntent.CODE, Complexity.MEDIUM): {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "max_tokens": 2048,
            "timeout": 15,
        },

        # Fallback
        None: {
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 15,
            "effort": "medium",
        },
    }

    @staticmethod
    def classify_task(
        query: str,
        context_size: int = 0,
        intent_hint: Optional[TaskIntent] = None,
    ) -> TaskProfile:
        """
        Automatically classify task intent and complexity.

        Args:
            query: The user query/prompt
            context_size: Approximate size of context in characters
            intent_hint: Optional hint about intended task (overrides auto-detection)

        Returns:
            TaskProfile with intent, complexity, and other metadata
        """

        # Use hint or detect from keywords
        if intent_hint:
            intent = intent_hint
        else:
            intent = LLMRouter._detect_intent(query)

        # Estimate complexity from context + query length
        complexity = LLMRouter._estimate_complexity(query, context_size)

        # Estimate tokens (rough: 1 char ≈ 0.25 tokens)
        estimated_tokens = int((len(query) + context_size) * 0.25)

        # Check if code/function calling needed
        requires_function = "code" in query.lower() or "json" in query.lower()

        # Check if long context needed
        requires_long = context_size > 10000

        return TaskProfile(
            intent=intent,
            complexity=complexity,
            estimated_tokens=estimated_tokens,
            requires_function_calling=requires_function,
            requires_long_context=requires_long,
        )

    @staticmethod
    def _detect_intent(query: str) -> TaskIntent:
        """Detect task intent from query keywords"""
        query_lower = query.lower()

        keywords = {
            TaskIntent.SEARCH: ["find", "where", "list", "search", "get"],
            TaskIntent.EXTRACT: ["extract", "parse", "identify", "what is", "profile"],
            TaskIntent.ANALYZE: ["analyze", "compare", "evaluate", "assess"],
            TaskIntent.REASON: ["why", "how should", "strategy", "recommend"],
            TaskIntent.CODE: ["code", "function", "debug", "implement", "write"],
            TaskIntent.SUMMARIZE: ["summarize", "summary", "tldr", "brief"],
            TaskIntent.AGENT: ["agent", "tool", "execute", "plan"],
        }

        for intent, words in keywords.items():
            if any(word in query_lower for word in words):
                return intent

        # Default to chat
        return TaskIntent.CHAT

    @staticmethod
    def _estimate_complexity(query: str, context_size: int) -> Complexity:
        """Estimate task complexity from query and context"""

        # Context-based estimation
        if context_size > 15000:
            return Complexity.HIGH
        if context_size > 5000:
            return Complexity.MEDIUM

        # Query-based estimation
        query_lower = query.lower()

        # High complexity indicators
        if any(w in query_lower for w in ["analyze", "compare", "strategy", "multiple", "complex"]):
            return Complexity.HIGH

        # Medium complexity indicators
        if any(w in query_lower for w in ["understand", "explain", "how", "why"]):
            return Complexity.MEDIUM

        return Complexity.LOW

    @staticmethod
    def get_model_config(task: TaskProfile, prefer_ollama: bool = True) -> Dict[str, Any]:
        """
        Get LLM configuration for a task.

        Args:
            task: The classified task profile
            prefer_ollama: If True, use Ollama for eligible LOW tasks (default: True)

        Returns:
            model_name, provider, max_tokens, timeout config
        """
        key = (task.intent, task.complexity)
        config = LLMRouter.ROUTING_TABLE.get(key)

        if not config:
            # Fallback to default
            config = LLMRouter.ROUTING_TABLE.get(None)

        # Check if this task can use Ollama
        if prefer_ollama and config.get("ollama_eligible"):
            if is_ollama_available():
                logger.debug(f"Using Ollama for {task.intent.value}/{task.complexity.value}")
                return LLMRouter.OLLAMA_CONFIG.copy()
            else:
                logger.debug(f"Ollama unavailable, falling back to Haiku")

        # Return copy without internal flags
        result = {k: v for k, v in config.items() if not k.startswith("ollama_")}
        return result

    @staticmethod
    def get_best_available_model(
        task: TaskProfile,
        available_providers: list = None
    ) -> Dict[str, Any]:
        """
        Get best model for task from available providers.

        If preferred provider isn't available, fallback to alternative.
        """
        preferred = LLMRouter.get_model_config(task)

        if not available_providers:
            # All providers available
            return preferred

        preferred_provider = preferred.get("provider")

        if preferred_provider in available_providers:
            return preferred

        # Fallback: use Anthropic if available (more reliable for most tasks)
        if "anthropic" in available_providers:
            task_key = (task.intent, task.complexity)
            # Find anthropic alternative
            for key, config in LLMRouter.ROUTING_TABLE.items():
                if (key != task_key and
                    config.get("provider") == "anthropic" and
                    key and key[0] == task.intent):  # Same intent
                    return {k: v for k, v in config.items() if not k.startswith("ollama_")}

            # Last resort
            return LLMRouter.HAIKU_FALLBACK.copy()

        # Fallback to OpenAI if available
        if "openai" in available_providers:
            return {
                "model": "gpt-4o",
                "provider": "openai",
                "max_tokens": 2048,
                "timeout": 15,
            }

        raise ValueError("No LLM providers available")
