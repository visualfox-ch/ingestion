"""
Langfuse AI Observability Integration for Jarvis

Provides LLM call tracing, cost tracking, and performance monitoring.
Phase 3: AI Observability
"""
import os
import time
from typing import Any, Dict, Optional, Callable
from functools import wraps
from contextlib import contextmanager

# Graceful import - don't break if Langfuse not installed
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
    try:
        from langfuse import observe as _lf_observe
    except Exception:
        try:
            from langfuse.decorators import observe as _lf_observe
        except Exception:
            _lf_observe = None
    try:
        from langfuse import propagate_attributes as _lf_propagate_attributes
    except Exception:
        try:
            from langfuse.decorators import propagate_attributes as _lf_propagate_attributes
        except Exception:
            _lf_propagate_attributes = None

    try:
        from langfuse import langfuse_context
    except Exception:
        try:
            from langfuse.decorators import langfuse_context
        except Exception:
            langfuse_context = None
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None
    _lf_observe = None
    _lf_propagate_attributes = None
    langfuse_context = None

from .observability import get_logger, log_with_context, llm_metrics

logger = get_logger("jarvis.langfuse")


# ============ Configuration ============

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"


def _merge_tags(base_tags: list, extra_tags: Optional[list]) -> list:
    """Merge tags preserving order and removing duplicates."""
    result = []
    seen = set()
    for tag in base_tags + (extra_tags or []):
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _safe_str(value: Any, max_len: int = 200) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Langfuse metadata keys must be alphanumeric; values <=200 chars."""
    cleaned: Dict[str, str] = {}
    if not metadata:
        return cleaned
    for key, value in metadata.items():
        if value is None:
            continue
        key_str = "".join(ch for ch in str(key) if ch.isalnum())
        if not key_str:
            continue
        val_str = _safe_str(value)
        if val_str is None:
            continue
        cleaned[key_str] = val_str
    return cleaned


def _sanitize_tags(tags: Optional[list]) -> Optional[list]:
    if not tags:
        return None
    cleaned = []
    for tag in tags:
        s = _safe_str(tag)
        if s:
            cleaned.append(s)
    return cleaned or None


@contextmanager
def langfuse_attribute_scope(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list] = None,
    version: Optional[str] = None,
    trace_name: Optional[str] = None,
    as_baggage: bool = False,
):
    """
    Propagate Langfuse attributes to all spans in the current context.
    Uses SDK propagate_attributes if available; no-op otherwise.
    """
    if not _lf_propagate_attributes:
        yield
        return
    try:
        with _lf_propagate_attributes(
            user_id=_safe_str(user_id),
            session_id=_safe_str(session_id),
            metadata=_sanitize_metadata(metadata),
            tags=_sanitize_tags(tags),
            version=_safe_str(version),
            trace_name=_safe_str(trace_name),
            as_baggage=as_baggage,
        ):
            yield
    except Exception:
        # Fail-safe: never break request flow on propagation errors
        yield


# ============ Client Singleton ============

_langfuse_client: Optional[Langfuse] = None


def get_langfuse() -> Optional[Langfuse]:
    """Get the Langfuse client singleton, initializing if needed."""
    global _langfuse_client

    if not LANGFUSE_AVAILABLE:
        return None

    if not LANGFUSE_ENABLED:
        return None

    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None

    if _langfuse_client is None:
        try:
            _langfuse_client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST,
            )
            log_with_context(logger, "info", "Langfuse client initialized",
                           host=LANGFUSE_HOST)
        except Exception as e:
            log_with_context(logger, "warning", "Failed to initialize Langfuse",
                           error=str(e))
            return None

    return _langfuse_client


def is_langfuse_enabled() -> bool:
    """Check if Langfuse is available and configured."""
    return get_langfuse() is not None


# ============ Model Cost Mapping ============

# Token costs per 1M tokens (input/output) - as of Feb 2026
# Anthropic pricing
ANTHROPIC_COSTS = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20250110": {"input": 0.80, "output": 4.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
}

# OpenAI pricing
OPENAI_COSTS = {
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
}

# Unified cost lookup
MODEL_COSTS = {**ANTHROPIC_COSTS, **OPENAI_COSTS}
MODEL_COSTS["default"] = {"input": 3.00, "output": 15.00}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token count."""
    costs = MODEL_COSTS.get(model, MODEL_COSTS["default"])
    input_cost = (input_tokens / 1_000_000) * costs["input"]
    output_cost = (output_tokens / 1_000_000) * costs["output"]
    return round(input_cost + output_cost, 6)


# ============ Tracing Context Manager ============

@contextmanager
def trace_llm_call(
    name: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list] = None
):
    """
    Context manager for tracing LLM calls in Langfuse.

    Usage:
        with trace_llm_call("chat", "claude-sonnet-4", user_id="user_123") as trace:
            response = call_anthropic(...)
            trace.set_output(response.content[0].text)
            trace.set_usage(response.usage.input_tokens, response.usage.output_tokens)
    """
    langfuse = get_langfuse()

    class TraceContext:
        def __init__(self):
            self.trace = None
            self.generation = None
            self.start_time = time.time()
            self.first_token_time = None
            self.input_tokens = 0
            self.output_tokens = 0
            self.output = None
            self.error_occurred = False

        def set_input(self, prompt: str, messages: list = None):
            """Set the input prompt/messages."""
            if self.generation:
                self.generation.input = {"prompt": prompt, "messages": messages}

        def set_output(self, output: str):
            """Set the output text."""
            self.output = output

        def set_usage(self, input_tokens: int, output_tokens: int):
            """Set token usage."""
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens

        def set_first_token_time(self):
            """Mark when first token was received (for TTFT calculation)."""
            if self.first_token_time is None:
                self.first_token_time = time.time()

        def set_error(self, error: str):
            """Mark the trace as failed."""
            self.error_occurred = True
            if self.generation:
                self.generation.level = "ERROR"
                self.generation.status_message = error

    ctx = TraceContext()

    if langfuse:
        try:
            ctx.trace = langfuse.trace(
                name=name,
                user_id=user_id,
                session_id=session_id,
                metadata=metadata or {},
                tags=tags or ["jarvis", "production"],
            )

            ctx.generation = ctx.trace.generation(
                name=f"{name}-generation",
                model=model,
                metadata={"jarvis_call": name},
            )
        except Exception as e:
            log_with_context(logger, "warning", "Failed to create Langfuse trace",
                           error=str(e), call_name=name)

    try:
        yield ctx
    finally:
        # Calculate metrics
        end_time = time.time()
        total_latency_seconds = end_time - ctx.start_time
        ttft_seconds = None
        if ctx.first_token_time is not None:
            ttft_seconds = ctx.first_token_time - ctx.start_time

        cost = calculate_cost(model, ctx.input_tokens, ctx.output_tokens)

        # Record to local LLM metrics (always, even if Langfuse fails)
        llm_metrics.record_request(
            model=model,
            ttft_seconds=ttft_seconds,
            total_latency_seconds=total_latency_seconds,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
            cost_usd=cost,
            error=ctx.error_occurred
        )

        # Finalize the Langfuse trace
        if ctx.generation:
            try:
                duration_ms = total_latency_seconds * 1000

                ctx.generation.end(
                    output=ctx.output,
                    usage={
                        "input": ctx.input_tokens,
                        "output": ctx.output_tokens,
                        "total": ctx.input_tokens + ctx.output_tokens,
                    },
                    metadata={
                        "duration_ms": round(duration_ms, 2),
                        "cost_usd": cost,
                        "ttft_ms": round(ttft_seconds * 1000, 2) if ttft_seconds else None,
                    }
                )
            except Exception as e:
                log_with_context(logger, "warning", "Failed to end Langfuse generation",
                               error=str(e))

        # Flush traces asynchronously
        if langfuse:
            try:
                langfuse.flush()
            except Exception:
                pass


# ============ Observe Decorator (Fallback) ============

def observe(*args, **kwargs):
    """Compatibility wrapper for Langfuse observe decorator.

    Falls back to trace_llm_call if SDK decorators are unavailable.
    """
    if _lf_observe:
        return _lf_observe(*args, **kwargs)

    name = kwargs.get("name") if kwargs else (args[0] if args else None)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*f_args, **f_kwargs):
            model = f_kwargs.get("model", "unknown")
            user_id = f_kwargs.get("user_id")
            session_id = f_kwargs.get("session_id")
            with trace_llm_call(
                name=name or func.__name__,
                model=model,
                user_id=str(user_id) if user_id else None,
                session_id=session_id,
                metadata={"observe_fallback": True},
                tags=["observe", "fallback"],
            ) as trace:
                try:
                    result = func(*f_args, **f_kwargs)

                    if isinstance(result, dict):
                        usage = result.get("usage", {})
                        trace.set_usage(
                            usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0)
                        )
                        if "answer" in result:
                            trace.set_output(str(result["answer"])[:1000])
                    elif isinstance(result, str):
                        trace.set_output(result[:1000])

                    return result
                except Exception as e:
                    trace.set_error(str(e)[:500])
                    raise

        return wrapper

    return decorator


# ============ Decorator for LLM Functions ============

def trace_llm(
    name: str,
    extract_model: Callable = None,
    extract_user_id: Callable = None,
    tags: list = None
):
    """
    Decorator to automatically trace LLM function calls.

    Args:
        name: Name for this trace type (e.g., "chat", "rewrite", "profile")
        extract_model: Function to extract model name from kwargs
        extract_user_id: Function to extract user_id from kwargs
        tags: Additional tags for the trace

    Usage:
        @trace_llm("chat", extract_model=lambda kw: kw.get("model"))
        def chat_with_context(query, search_results, model="claude-sonnet-4"):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            langfuse = get_langfuse()

            if not langfuse:
                # Langfuse not available, just call the function
                return func(*args, **kwargs)

            # Extract metadata
            model = extract_model(kwargs) if extract_model else kwargs.get("model", "unknown")
            user_id = extract_user_id(kwargs) if extract_user_id else kwargs.get("user_id")

            with trace_llm_call(
                name=name,
                model=model,
                user_id=str(user_id) if user_id else None,
                tags=tags or ["jarvis"],
            ) as trace:
                try:
                    result = func(*args, **kwargs)

                    # Extract usage from result if available
                    if isinstance(result, dict):
                        usage = result.get("usage", {})
                        trace.set_usage(
                            usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0)
                        )
                        if "answer" in result:
                            trace.set_output(result["answer"][:1000])  # Truncate for storage

                    return result

                except Exception as e:
                    trace.set_error(str(e)[:500])
                    raise

        return wrapper
    return decorator


# ============ Manual Trace Helpers ============

def log_chat_trace(
    query: str,
    response: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    user_id: Optional[str] = None,
    context_chunks: int = 0,
    metadata: Dict[str, Any] = None,
    tags: Optional[list] = None,
    journey_stage: Optional[str] = None,
    ttft_ms: Optional[float] = None
):
    """
    Log a completed chat interaction to Langfuse.

    Use this for cases where the decorator approach doesn't fit.
    """
    cost = calculate_cost(model, input_tokens, output_tokens)

    # Always record to local LLM metrics
    llm_metrics.record_request(
        model=model,
        ttft_seconds=ttft_ms / 1000 if ttft_ms else None,
        total_latency_seconds=duration_ms / 1000,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        error=False
    )

    langfuse = get_langfuse()
    if not langfuse:
        return

    try:
        trace = langfuse.trace(
            name="jarvis-chat",
            user_id=user_id,
            metadata={
                "query_length": len(query),
                "context_chunks": context_chunks,
                **({"journey_stage": journey_stage} if journey_stage else {}),
                **(metadata or {})
            },
            tags=_merge_tags(["jarvis", "chat", "production"], tags),
        )

        trace.generation(
            name="chat-generation",
            model=model,
            input={"query": query[:500]},  # Truncate
            output=response[:1000],  # Truncate
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            metadata={
                "duration_ms": round(duration_ms, 2),
                "cost_usd": cost,
                "ttft_ms": round(ttft_ms, 2) if ttft_ms else None,
            }
        )

        langfuse.flush()

    except Exception as e:
        log_with_context(logger, "warning", "Failed to log chat trace",
                       error=str(e))


def log_rewrite_trace(
    original_query: str,
    rewritten_query: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    tags: Optional[list] = None,
    journey_stage: Optional[str] = None
):
    """Log a query rewrite operation to Langfuse."""
    langfuse = get_langfuse()
    if not langfuse:
        return

    try:
        trace = langfuse.trace(
            name="jarvis-rewrite",
            metadata={
                "operation": "query_rewrite",
                **({"journey_stage": journey_stage} if journey_stage else {})
            },
            tags=_merge_tags(["jarvis", "rewrite"], tags),
        )

        trace.generation(
            name="rewrite-generation",
            model=model,
            input={"original": original_query},
            output=rewritten_query,
            usage={
                "input": input_tokens,
                "output": output_tokens,
            },
            metadata={"duration_ms": round(duration_ms, 2)}
        )

        langfuse.flush()

    except Exception as e:
        log_with_context(logger, "warning", "Failed to log rewrite trace",
                       error=str(e))


def log_profile_extraction_trace(
    person_name: str,
    messages_analyzed: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    confidence_score: float = 0.0,
    tags: Optional[list] = None,
    journey_stage: Optional[str] = None
):
    """Log a profile extraction operation to Langfuse."""
    langfuse = get_langfuse()
    if not langfuse:
        return

    try:
        trace = langfuse.trace(
            name="jarvis-profile-extraction",
            metadata={
                "person": person_name,
                "messages_analyzed": messages_analyzed,
                "confidence": confidence_score,
                **({"journey_stage": journey_stage} if journey_stage else {}),
            },
            tags=_merge_tags(["jarvis", "profile", "extraction"], tags),
        )

        trace.generation(
            name="profile-generation",
            model=model,
            usage={
                "input": input_tokens,
                "output": output_tokens,
            },
            metadata={"duration_ms": round(duration_ms, 2)}
        )

        langfuse.flush()

    except Exception as e:
        log_with_context(logger, "warning", "Failed to log profile trace",
                       error=str(e))


# ============ LLM Error Tracking ============

def log_llm_error(
    model: str,
    error: str,
    error_type: str = "unknown",
    input_tokens: int = 0,
    metadata: Dict[str, Any] = None
):
    """
    Log an LLM error to both local metrics and Langfuse.

    Args:
        model: Model name
        error: Error message
        error_type: Type of error (rate_limit, timeout, api_error, etc.)
        input_tokens: Tokens sent before error (for cost estimation)
        metadata: Additional context
    """
    # Record error in local metrics
    llm_metrics.record_request(
        model=model,
        input_tokens=input_tokens,
        error=True
    )

    langfuse = get_langfuse()
    if not langfuse:
        return

    try:
        trace = langfuse.trace(
            name="jarvis-llm-error",
            metadata={
                "error_type": error_type,
                "error_message": error[:500],
                **(metadata or {})
            },
            tags=["jarvis", "error", error_type],
        )

        trace.generation(
            name="error-generation",
            model=model,
            level="ERROR",
            status_message=error[:500],
            usage={"input": input_tokens, "output": 0},
        )

        langfuse.flush()

    except Exception as e:
        log_with_context(logger, "warning", "Failed to log LLM error trace",
                       error=str(e))


# ============ Metrics Access ============

def get_llm_metrics_stats() -> Dict[str, Any]:
    """Get current LLM metrics statistics."""
    return llm_metrics.get_stats()


def get_llm_prometheus_metrics() -> str:
    """Get LLM metrics in Prometheus format."""
    return llm_metrics.get_prometheus_metrics()


# ============ Utility Functions ============

def flush_traces():
    """Flush all pending traces to Langfuse."""
    langfuse = get_langfuse()
    if langfuse:
        try:
            langfuse.flush()
        except Exception as e:
            log_with_context(logger, "warning", "Failed to flush Langfuse traces",
                           error=str(e))


def shutdown_langfuse():
    """Gracefully shutdown Langfuse client."""
    global _langfuse_client
    if _langfuse_client:
        try:
            _langfuse_client.flush()
            _langfuse_client.shutdown()
        except Exception:
            pass
        _langfuse_client = None


def get_langfuse_status() -> Dict[str, Any]:
    """Get Langfuse integration status for health checks."""
    return {
        "available": LANGFUSE_AVAILABLE,
        "enabled": LANGFUSE_ENABLED,
        "configured": bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY),
        "connected": is_langfuse_enabled(),
        "host": LANGFUSE_HOST if is_langfuse_enabled() else None,
    }


def get_session_costs(session_id: str, limit: int = 100) -> Dict[str, Any]:
    """
    Get LLM costs for a specific session from Langfuse.

    Args:
        session_id: The session identifier (e.g., Claude Code session)
        limit: Max traces to fetch

    Returns:
        Dict with total costs, token counts, and breakdown by model
    """
    client = get_langfuse()
    if not client:
        return {
            "error": "Langfuse not available",
            "session_id": session_id,
        }

    try:
        # Query traces for this session
        traces = client.fetch_traces(
            session_id=session_id,
            limit=limit,
        )

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        model_breakdown = {}
        trace_count = 0

        for trace in traces.data:
            trace_count += 1
            # Aggregate observations (LLM calls) within trace
            if hasattr(trace, 'observations'):
                for obs in trace.observations:
                    if obs.type == 'generation':
                        model = obs.model or 'unknown'
                        input_tokens = obs.usage.input or 0 if obs.usage else 0
                        output_tokens = obs.usage.output or 0 if obs.usage else 0
                        cost = obs.calculated_total_cost or 0

                        total_input_tokens += input_tokens
                        total_output_tokens += output_tokens
                        total_cost += cost

                        if model not in model_breakdown:
                            model_breakdown[model] = {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "cost": 0.0,
                                "calls": 0,
                            }
                        model_breakdown[model]["input_tokens"] += input_tokens
                        model_breakdown[model]["output_tokens"] += output_tokens
                        model_breakdown[model]["cost"] += cost
                        model_breakdown[model]["calls"] += 1

        return {
            "session_id": session_id,
            "trace_count": trace_count,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_cost_usd": round(total_cost, 4),
            "model_breakdown": model_breakdown,
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to fetch session costs",
                        session_id=session_id, error=str(e))
        return {
            "error": str(e),
            "session_id": session_id,
        }


def get_recent_sessions_costs(hours: int = 24, limit: int = 20) -> Dict[str, Any]:
    """
    Get costs for recent sessions.

    Args:
        hours: Look back period in hours
        limit: Max sessions to return

    Returns:
        Dict with session costs summary
    """
    client = get_langfuse()
    if not client:
        return {"error": "Langfuse not available"}

    try:
        from datetime import datetime, timedelta
        from_time = datetime.utcnow() - timedelta(hours=hours)

        # Fetch recent traces grouped by session
        traces = client.fetch_traces(
            limit=500,  # Fetch more to aggregate
            from_timestamp=from_time,
        )

        sessions = {}
        for trace in traces.data:
            sid = trace.session_id or "no-session"
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "traces": 0,
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "first_seen": None,
                    "last_seen": None,
                }

            sessions[sid]["traces"] += 1

            if trace.timestamp:
                ts = trace.timestamp
                if sessions[sid]["first_seen"] is None or ts < sessions[sid]["first_seen"]:
                    sessions[sid]["first_seen"] = ts
                if sessions[sid]["last_seen"] is None or ts > sessions[sid]["last_seen"]:
                    sessions[sid]["last_seen"] = ts

            if hasattr(trace, 'observations'):
                for obs in trace.observations:
                    if obs.type == 'generation':
                        tokens = (obs.usage.input or 0) + (obs.usage.output or 0) if obs.usage else 0
                        cost = obs.calculated_total_cost or 0
                        sessions[sid]["total_tokens"] += tokens
                        sessions[sid]["total_cost"] += cost

        # Sort by cost descending, take top N
        sorted_sessions = sorted(
            sessions.values(),
            key=lambda x: x["total_cost"],
            reverse=True
        )[:limit]

        # Format timestamps
        for s in sorted_sessions:
            if s["first_seen"]:
                s["first_seen"] = s["first_seen"].isoformat()
            if s["last_seen"]:
                s["last_seen"] = s["last_seen"].isoformat()
            s["total_cost"] = round(s["total_cost"], 4)

        return {
            "hours": hours,
            "session_count": len(sorted_sessions),
            "sessions": sorted_sessions,
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to fetch recent sessions",
                        error=str(e))
        return {"error": str(e)}
