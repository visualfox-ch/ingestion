"""
LLM Router Integration Helper

Provides compatibility layer for migrating existing code
to use the new multi-provider router.
"""
from typing import List, Dict, Any, Optional
from .router import TaskIntent, Complexity


def wrap_chat_with_routing(
    query: str,
    search_results: List[Dict[str, Any]],
    system_prompt: str = None,
    intent_hint: Optional[TaskIntent] = None,
    complexity_hint: Optional[Complexity] = None,
    model_override: Optional[str] = None,
    max_tokens: int = 2048,
    conversation_history: List[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Wrapper for existing chat_with_context() to use new router.
    
    This function automatically selects the best model based on:
    - Search result size (context complexity)
    - Query characteristics
    - Intent hints
    
    Returns:
        {
            "response": "...",
            "model": "claude-...",
            "provider": "anthropic",
            "tokens": {...},
            "cost_usd": 0.0123,
        }
    """
    from .factory import get_llm_factory
    
    factory = get_llm_factory()
    
    # Estimate context size
    context_text = "\n".join(
        str(r.get("text", "")) for r in search_results
    )
    context_size = len(context_text)
    
    # Determine intent if not provided
    if not intent_hint:
        # Simple heuristic
        query_lower = query.lower()
        if any(w in query_lower for w in ["analyze", "compare", "evaluate"]):
            intent_hint = TaskIntent.ANALYZE
        elif any(w in query_lower for w in ["code", "implement", "debug"]):
            intent_hint = TaskIntent.CODE
        else:
            intent_hint = TaskIntent.CHAT
    
    # Prepare messages
    messages = [
        {"role": "user", "content": query}
    ]
    
    if conversation_history:
        # Prepend conversation history
        messages = conversation_history + messages
    
    # Call factory with routing
    result = factory.call(
        messages=messages,
        system_prompt=system_prompt or "You are a helpful assistant.",
        intent=intent_hint,
        complexity=complexity_hint,
        model_override=model_override,
        max_tokens_override=max_tokens,
        query_for_classification=query,
        context_size=context_size,
    )
    
    return result


def estimate_task_intent(
    query: str,
    context_size: int = 0
) -> tuple[TaskIntent, Complexity]:
    """
    Utility to analyze a query and estimate intent + complexity.
    
    Useful for debugging routing decisions.
    """
    from .router import LLMRouter
    
    router = LLMRouter()
    task = router.classify_task(query, context_size)
    
    return task.intent, task.complexity


def get_routing_recommendation(
    query: str,
    context_size: int = 0,
) -> Dict[str, Any]:
    """
    Get detailed routing recommendation for a query.
    
    Useful for debugging / understanding model selection.
    
    Returns:
        {
            "intent": "chat",
            "complexity": "medium",
            "recommended_model": "claude-3-5-sonnet-20241022",
            "provider": "anthropic",
            "max_tokens": 2048,
            "estimated_cost_per_100k_tokens": "$0.30",
            "reason": "Medium complexity chat task",
        }
    """
    from .router import LLMRouter
    from .factory import get_llm_factory
    
    router = LLMRouter()
    factory = get_llm_factory()
    
    task = router.classify_task(query, context_size)
    config = router.get_model_config(task)
    
    # Estimate cost (rough)
    provider_name = config.get("provider")
    provider = __import__('ingestion.app.llm.providers', fromlist=['get_provider']).get_provider(provider_name)
    
    # Assume 100K token input
    estimated_cost = provider.calculate_cost(
        config.get("model"),
        input_tokens=100000,
        output_tokens=0
    )
    
    return {
        "intent": task.intent.value,
        "complexity": task.complexity.value,
        "estimated_tokens": task.estimated_tokens,
        "recommended_model": config.get("model"),
        "provider": config.get("provider"),
        "max_tokens": config.get("max_tokens"),
        "timeout_seconds": config.get("timeout"),
        "estimated_cost_per_100k_input_tokens": f"${estimated_cost:.4f}",
        "available_providers": factory.available_providers,
    }
