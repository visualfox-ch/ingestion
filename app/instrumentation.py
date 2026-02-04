"""
Phase 2.2: Instrumentation for Slow Code Paths

Adds distributed tracing spans and instrumentation to:
- Database queries
- API calls
- LLM inference
- Vector search operations
"""

import time
from functools import wraps
from typing import Callable, Optional, Any, Dict
from contextlib import contextmanager

from .observability import get_logger, log_with_context
from .tracing import get_trace_context

logger = get_logger("jarvis.instrumentation")


# ============ Database Query Instrumentation ============

@contextmanager
def trace_query(query_type: str, table: str, **context):
    """Context manager for tracing database queries
    
    Args:
        query_type: Type of query (SELECT, INSERT, UPDATE, DELETE)
        table: Table name
        **context: Additional context fields
    
    Example:
        with trace_query("SELECT", "person_profile", namespace="coaching"):
            cur.execute("SELECT * FROM person_profile WHERE id = %s", (user_id,))
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        # Log slow queries (> 2000ms)
        if duration_ms > 2000:
            log_with_context(
                logger, "warning",
                f"Slow {query_type} query on {table}: {duration_ms:.2f}ms",
                query_type=query_type,
                table=table,
                duration_ms=duration_ms,
                trace_id=trace_ctx.get("trace_id"),
                request_id=trace_ctx.get("request_id"),
                **context
            )
        else:
            log_with_context(
                logger, "debug",
                f"{query_type} query on {table}: {duration_ms:.2f}ms",
                query_type=query_type,
                table=table,
                duration_ms=duration_ms,
                trace_id=trace_ctx.get("trace_id"),
                **context
            )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"{query_type} query failed on {table}: {str(e)}",
            query_type=query_type,
            table=table,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
        raise


def instrument_query(query_type: str, table: str, **context_fields):
    """Decorator for instrumenting database query functions
    
    Args:
        query_type: Type of query (SELECT, INSERT, UPDATE, DELETE)
        table: Table name
        **context_fields: Default context fields
    
    Example:
        @instrument_query("SELECT", "person_profile", namespace="coaching")
        def get_user_profile(user_id):
            # ... implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with trace_query(query_type, table, **context_fields):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# ============ API Call Instrumentation ============

@contextmanager
def trace_api_call(method: str, endpoint: str, service: str = "internal", **context):
    """Context manager for tracing API calls
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path
        service: Service name (external, n8n, qdrant, etc.)
        **context: Additional context fields
    
    Example:
        with trace_api_call("GET", "/api/workflows", service="n8n"):
            response = requests.get("http://n8n:5678/api/workflows")
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        log_with_context(
            logger, "debug",
            f"API call {method} {endpoint} completed in {duration_ms:.2f}ms",
            method=method,
            endpoint=endpoint,
            service=service,
            duration_ms=duration_ms,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"API call {method} {endpoint} failed: {str(e)}",
            method=method,
            endpoint=endpoint,
            service=service,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
        raise


# ============ LLM Inference Instrumentation ============

@contextmanager
def trace_llm_call(model: str, prompt_tokens: int = 0, **context):
    """Context manager for tracing LLM inference calls
    
    Args:
        model: Model name (gpt-4, claude-3, etc.)
        prompt_tokens: Number of prompt tokens
        **context: Additional context fields (temperature, max_tokens, etc.)
    
    Example:
        with trace_llm_call("claude-3", prompt_tokens=500, temperature=0.7):
            response = llm.generate(prompt, temperature=0.7)
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        # Log slow LLM calls (> 5000ms)
        level = "warning" if duration_ms > 5000 else "debug"
        log_with_context(
            logger, level,
            f"LLM call {model} completed in {duration_ms:.2f}ms",
            model=model,
            prompt_tokens=prompt_tokens,
            duration_ms=duration_ms,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"LLM call {model} failed: {str(e)}",
            model=model,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
        raise


# ============ Vector Search Instrumentation ============

@contextmanager
def trace_vector_search(operation: str, collection: str, query_size: int = 0, **context):
    """Context manager for tracing vector search operations
    
    Args:
        operation: Operation type (search, insert, update, delete)
        collection: Collection name in Qdrant
        query_size: Size of query vector
        **context: Additional context fields (limit, score_threshold, etc.)
    
    Example:
        with trace_vector_search("search", "knowledge_embeddings", query_size=384, limit=10):
            results = qdrant_client.search(collection_name="knowledge_embeddings", ...)
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        # Log slow searches (> 1000ms)
        level = "warning" if duration_ms > 1000 else "debug"
        log_with_context(
            logger, level,
            f"Vector {operation} on {collection} completed in {duration_ms:.2f}ms",
            operation=operation,
            collection=collection,
            query_size=query_size,
            duration_ms=duration_ms,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"Vector {operation} on {collection} failed: {str(e)}",
            operation=operation,
            collection=collection,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
        raise


# ============ Keyword Search Instrumentation ============

@contextmanager
def trace_keyword_search(index: str, query: str, **context):
    """Context manager for tracing Meilisearch keyword search
    
    Args:
        index: Index name in Meilisearch
        query: Search query string
        **context: Additional context fields (limit, offset, etc.)
    
    Example:
        with trace_keyword_search("knowledge", "coaching tips", limit=10):
            results = meilisearch_client.index("knowledge").search(query)
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        log_with_context(
            logger, "debug",
            f"Keyword search on {index} for '{query[:50]}' completed in {duration_ms:.2f}ms",
            index=index,
            query_preview=query[:100],
            duration_ms=duration_ms,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"Keyword search on {index} failed: {str(e)}",
            index=index,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            **context
        )
        raise


# ============ User Interaction Instrumentation ============

@contextmanager
def trace_user_interaction(interaction_type: str, session_id: str, **context):
    """Context manager for tracing user interactions
    
    Args:
        interaction_type: Type of interaction (message, command, event, etc.)
        session_id: Session identifier
        **context: Additional context fields (namespace, domain, etc.)
    
    Example:
        with trace_user_interaction("message", session_id, namespace="coaching"):
            response = handle_message(text, session_id)
    """
    start_time = time.time()
    trace_ctx = get_trace_context()
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        
        log_with_context(
            logger, "info",
            f"User interaction {interaction_type} completed in {duration_ms:.2f}ms",
            interaction_type=interaction_type,
            session_id=session_id,
            duration_ms=duration_ms,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            user_id=trace_ctx.get("user_id"),
            **context
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_with_context(
            logger, "error",
            f"User interaction {interaction_type} failed: {str(e)}",
            interaction_type=interaction_type,
            session_id=session_id,
            duration_ms=duration_ms,
            error=str(e),
            error_type=type(e).__name__,
            trace_id=trace_ctx.get("trace_id"),
            request_id=trace_ctx.get("request_id"),
            user_id=trace_ctx.get("user_id"),
            **context
        )
        raise


# ============ Performance Tracking ============

class PerformanceTracker:
    """Track performance metrics for various operations"""
    
    def __init__(self):
        self.metrics: Dict[str, list] = {}
        self.trace_ctx = get_trace_context()
    
    def record(self, operation: str, duration_ms: float, success: bool = True, **context):
        """Record an operation's performance
        
        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            success: Whether operation succeeded
            **context: Additional context
        """
        if operation not in self.metrics:
            self.metrics[operation] = []
        
        self.metrics[operation].append({
            "duration_ms": duration_ms,
            "success": success,
            "timestamp": time.time()
        })
        
        # Keep only last 100 measurements per operation
        if len(self.metrics[operation]) > 100:
            self.metrics[operation] = self.metrics[operation][-100:]
    
    def get_stats(self, operation: str) -> Optional[Dict[str, float]]:
        """Get statistics for an operation
        
        Args:
            operation: Operation name
        
        Returns:
            Dictionary with count, avg_ms, p95_ms, p99_ms, success_rate
        """
        if operation not in self.metrics or not self.metrics[operation]:
            return None
        
        durations = [m["duration_ms"] for m in self.metrics[operation]]
        successes = sum(1 for m in self.metrics[operation] if m["success"])
        
        sorted_durations = sorted(durations)
        return {
            "count": len(durations),
            "avg_ms": sum(durations) / len(durations),
            "p95_ms": sorted_durations[int(len(sorted_durations) * 0.95)],
            "p99_ms": sorted_durations[int(len(sorted_durations) * 0.99)],
            "success_rate": successes / len(durations) if durations else 0
        }


# Global performance tracker
perf_tracker = PerformanceTracker()
