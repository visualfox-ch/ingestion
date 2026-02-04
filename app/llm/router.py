"""
Intelligent LLM Router

Routes tasks to optimal model based on:
- Task complexity/type
- Cost efficiency
- Model capabilities
- Context window requirements
"""
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any
from enum import Enum

from .providers import ModelConfig


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


class LLMRouter:
    """
    Intelligent router for optimal LLM selection.
    
    Strategy:
    - Low complexity → Haiku (ultra-fast, cheapest)
    - Medium → Sonnet (best balance) or GPT-4o
    - High complexity → Opus (best reasoning) or GPT-4-turbo (best code)
    """
    
    # Default routing matrix: (intent, complexity) → model_name
    ROUTING_TABLE = {
        # Low complexity - minimize cost
        (TaskIntent.SEARCH, Complexity.LOW): {
            "model": "claude-3-5-haiku-20241022",
            "provider": "anthropic",
            "max_tokens": 256,
            "timeout": 3,
        },
        (TaskIntent.EXTRACT, Complexity.LOW): {
            "model": "claude-3-5-haiku-20241022",
            "provider": "anthropic",
            "max_tokens": 512,
            "timeout": 5,
        },
        
        # Medium complexity - balance cost & quality
        (TaskIntent.CHAT, Complexity.MEDIUM): {
            "model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 15,
        },
        (TaskIntent.SUMMARIZE, Complexity.MEDIUM): {
            "model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 1024,
            "timeout": 10,
        },
        
        # High complexity - optimize for quality
        (TaskIntent.ANALYZE, Complexity.HIGH): {
            "model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 25,
        },
        (TaskIntent.REASON, Complexity.HIGH): {
            "model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 25,
        },
        (TaskIntent.AGENT, Complexity.HIGH): {
            "model": "claude-opus-4-20250514",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 30,
        },
        
        # Code generation - GPT-4 Turbo is slightly better
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
            "model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 2048,
            "timeout": 15,
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
    def get_model_config(task: TaskProfile) -> Dict[str, Any]:
        """
        Get LLM configuration for a task.
        
        Returns model_name, provider, max_tokens, timeout
        """
        key = (task.intent, task.complexity)
        config = LLMRouter.ROUTING_TABLE.get(key)
        
        if not config:
            # Fallback to default
            config = LLMRouter.ROUTING_TABLE.get(None)
        
        return config
    
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
                    key[0] == task.intent):  # Same intent
                    return config
            
            # Last resort
            return LLMRouter.ROUTING_TABLE[(TaskIntent.CHAT, Complexity.MEDIUM)]
        
        # Fallback to OpenAI if available
        if "openai" in available_providers:
            return {
                "model": "gpt-4o",
                "provider": "openai",
                "max_tokens": 2048,
                "timeout": 15,
            }
        
        raise ValueError("No LLM providers available")
