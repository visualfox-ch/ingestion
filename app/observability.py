"""
Observability utilities for Jarvis
- Structured JSON logging with distributed trace IDs
- Retry decorator with exponential backoff
- Caching utilities
- Phase 2.2: Structured logging with trace context
"""
import logging
import json
import time
import asyncio
import hashlib
import os
from functools import wraps
from typing import Any, Callable, Dict, Optional
from datetime import datetime
from collections import OrderedDict, deque

from . import config

# ============ In-memory Log Buffer (Phase 1 Monitoring) ============

LOG_BUFFER_SIZE = int(os.getenv("JARVIS_LOG_BUFFER_SIZE", "200"))
_log_buffer = deque(maxlen=LOG_BUFFER_SIZE)
_buffer_handler: Optional[logging.Handler] = None


class LogBufferHandler(logging.Handler):
    """In-memory log buffer for recent warning/error events."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }

            if hasattr(record, "extra_data"):
                log_entry.update(record.extra_data)

            if record.exc_info:
                log_entry["exception"] = self.format(record)

            _log_buffer.append(log_entry)
        except Exception:
            # Avoid logging loops inside the handler
            pass


def get_recent_log_events(limit: int = 50, min_level: str = "WARNING") -> list[dict]:
    """Return recent log events from in-memory buffer.

    Args:
        limit: Max number of events to return
        min_level: Minimum log level (e.g., WARNING, ERROR)
    """
    levelno = logging._nameToLevel.get(min_level.upper(), logging.WARNING)

    def _event_level(event: dict) -> int:
        return logging._nameToLevel.get(event.get("level", "").upper(), 0)

    events = [e for e in list(_log_buffer) if _event_level(e) >= levelno]
    return events[-limit:]


# ============ Structured Logging with Trace Context ============

class JSONFormatter(logging.Formatter):
    """JSON log formatter with distributed trace context"""

    def format(self, record: logging.LogRecord) -> str:
        # Get trace context from request if available
        trace_context = self._get_trace_context()
        
        log_data = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        
        # Add trace context if available
        if trace_context:
            log_data.update(trace_context)

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)
    
    def _get_trace_context(self) -> Optional[Dict[str, str]]:
        """Extract trace context from request context variables"""
        try:
            # Import here to avoid circular imports
            from .tracing import get_trace_context
            ctx = get_trace_context()
            # Only include non-default values
            return {
                "request_id": ctx.get("request_id"),
                "trace_id": ctx.get("trace_id"),
                "user_id": ctx.get("user_id"),
            } if ctx.get("request_id") != "unknown" else None
        except (ImportError, AttributeError):
            return None


def get_logger(name: str) -> logging.Logger:
    """Get a structured JSON logger with trace context support"""
    logger = logging.getLogger(name)

    if not logger.handlers:
        formatter = JSONFormatter()
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        global _buffer_handler
        if _buffer_handler is None:
            _buffer_handler = LogBufferHandler()
            _buffer_handler.setFormatter(formatter)

        if _buffer_handler not in logger.handlers:
            logger.addHandler(_buffer_handler)

        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger


def log_with_context(logger: logging.Logger, level: str, msg: str, **kwargs):
    """Log with additional structured context and trace IDs
    
    Args:
        logger: Logger instance
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        msg: Log message
        **kwargs: Additional structured fields
    """
    record = logger.makeRecord(
        logger.name, getattr(logging, level.upper()), "", 0, msg, (), None
    )
    record.extra_data = kwargs
    logger.handle(record)


def log_api_call(logger: logging.Logger, method: str, endpoint: str, status: int, duration_ms: float, **kwargs):
    """Log API call with standard fields and trace context
    
    Args:
        logger: Logger instance
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path
        status: HTTP status code
        duration_ms: Request duration in milliseconds
        **kwargs: Additional fields (error, user_id, etc.)
    """
    level = "error" if status >= 500 else "warning" if status >= 400 else "info"
    log_with_context(
        logger, level,
        f"{method} {endpoint} - {status}",
        method=method,
        endpoint=endpoint,
        status=status,
        duration_ms=duration_ms,
        **kwargs
    )


def log_database_query(logger: logging.Logger, query_type: str, duration_ms: float, rows_affected: int = 0, **kwargs):
    """Log database query with trace context
    
    Args:
        logger: Logger instance
        query_type: Type of query (SELECT, INSERT, UPDATE, DELETE)
        duration_ms: Query duration in milliseconds
        rows_affected: Number of rows affected
        **kwargs: Additional fields (error, table, etc.)
    """
    level = "warning" if duration_ms > 2000 else "debug" if duration_ms > 100 else "debug"
    log_with_context(
        logger, level,
        f"{query_type} query completed in {duration_ms:.2f}ms",
        query_type=query_type,
        duration_ms=duration_ms,
        rows_affected=rows_affected,
        **kwargs
    )


# ============ Retry with Backoff ============

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    logger_name: str = "retry"
):
    """
    Decorator for exponential backoff retry.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exceptions: Tuple of exceptions to catch and retry
        logger_name: Logger name for retry logs
    """
    logger = get_logger(logger_name)

    def _sleep(seconds: float) -> None:
        """Sleep using asyncio when no running loop; fallback to time.sleep otherwise."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(asyncio.sleep(seconds))
            return
        time.sleep(seconds)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        log_with_context(
                            logger, "error",
                            f"All {max_retries + 1} attempts failed for {func.__name__}",
                            function=func.__name__,
                            error=str(e),
                            error_type=type(e).__name__
                        )
                        raise

                    delay = min(base_delay * (2 ** attempt), max_delay)
                    log_with_context(
                        logger, "warning",
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__}",
                        function=func.__name__,
                        attempt=attempt + 1,
                        delay_seconds=delay,
                        error=str(e),
                        error_type=type(e).__name__
                    )
                    _sleep(delay)

            raise last_exception

        return wrapper
    return decorator


# ============ Simple LRU Cache with TTL ============

class TTLCache:
    """Simple thread-safe LRU cache with TTL"""

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._hits = 0
        self._misses = 0

    def _make_key(self, *args, **kwargs) -> str:
        """Create a cache key from arguments"""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.md5(key_data.encode()).hexdigest()

    def _is_expired(self, key: str) -> bool:
        """Check if cache entry is expired"""
        if key not in self._timestamps:
            return True
        return time.time() - self._timestamps[key] > self.ttl_seconds

    def _evict_expired(self):
        """Remove expired entries"""
        now = time.time()
        expired = [k for k, ts in self._timestamps.items() if now - ts > self.ttl_seconds]
        for k in expired:
            self._cache.pop(k, None)
            self._timestamps.pop(k, None)

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key in self._cache and not self._is_expired(key):
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any):
        """Set value in cache"""
        self._evict_expired()

        if len(self._cache) >= self.maxsize:
            oldest = next(iter(self._cache))
            self._cache.pop(oldest)
            self._timestamps.pop(oldest, None)

        self._cache[key] = value
        self._timestamps[key] = time.time()
        self._cache.move_to_end(key)

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "maxsize": self.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0
        }

    def clear(self):
        """Clear the cache"""
        self._cache.clear()
        self._timestamps.clear()


def cached(cache: TTLCache):
    """Decorator to cache function results"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = cache._make_key(func.__name__, *args, **kwargs)
            result = cache.get(key)

            if result is not None:
                return result

            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        wrapper.cache = cache
        return wrapper

    return decorator


# ============ Metrics Tracking ============

class Metrics:
    """Simple in-memory metrics for observability"""

    def __init__(self):
        self._counters: Dict[str, int] = {}
        self._timings: Dict[str, list] = {}
        self._start_time = time.time()

    def inc(self, name: str, value: int = 1):
        """Increment a counter"""
        self._counters[name] = self._counters.get(name, 0) + value

    def timing(self, name: str, duration_ms: float):
        """Record a timing measurement"""
        if name not in self._timings:
            self._timings[name] = []
        self._timings[name].append(duration_ms)
        # Keep only last 1000 measurements
        if len(self._timings[name]) > 1000:
            self._timings[name] = self._timings[name][-1000:]

    def get_stats(self) -> Dict[str, Any]:
        """Get all metrics"""
        stats = {
            "uptime_seconds": time.time() - self._start_time,
            "counters": dict(self._counters),
            "timings": {}
        }

        for name, values in self._timings.items():
            if values:
                sorted_vals = sorted(values)
                stats["timings"][name] = {
                    "count": len(values),
                    "avg_ms": sum(values) / len(values),
                    "p50_ms": sorted_vals[len(sorted_vals) // 2],
                    "p99_ms": sorted_vals[int(len(sorted_vals) * 0.99)] if len(sorted_vals) > 1 else sorted_vals[0]
                }

        return stats


# ============ LLM Performance Metrics ============

class LLMMetrics:
    """
    LLM-specific metrics for performance monitoring.
    Tracks TTFT, tokens/sec, costs, and provides Prometheus-compatible output.
    """

    # Histogram buckets for TTFT (in seconds)
    TTFT_BUCKETS = [0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, float('inf')]

    # Histogram buckets for total latency (in seconds)
    LATENCY_BUCKETS = [0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 30.0, 60.0, float('inf')]

    def __init__(self):
        self._start_time = time.time()

        # Counters by model
        self._requests_total: Dict[str, int] = {}
        self._errors_total: Dict[str, int] = {}
        self._input_tokens_total: Dict[str, int] = {}
        self._output_tokens_total: Dict[str, int] = {}
        self._cost_usd_total: Dict[str, float] = {}

        # Histograms by model (bucket -> count)
        self._ttft_histogram: Dict[str, Dict[float, int]] = {}
        self._latency_histogram: Dict[str, Dict[float, int]] = {}

        # Recent values for percentile calculations
        self._ttft_values: Dict[str, list] = {}
        self._latency_values: Dict[str, list] = {}
        self._tokens_per_sec_values: Dict[str, list] = {}

    def _get_bucket(self, value: float, buckets: list) -> float:
        """Find the appropriate bucket for a value."""
        for bucket in buckets:
            if value <= bucket:
                return bucket
        return buckets[-1]

    def _init_model(self, model: str):
        """Initialize metrics for a model if not exists."""
        if model not in self._requests_total:
            self._requests_total[model] = 0
            self._errors_total[model] = 0
            self._input_tokens_total[model] = 0
            self._output_tokens_total[model] = 0
            self._cost_usd_total[model] = 0.0
            self._ttft_histogram[model] = {b: 0 for b in self.TTFT_BUCKETS}
            self._latency_histogram[model] = {b: 0 for b in self.LATENCY_BUCKETS}
            self._ttft_values[model] = []
            self._latency_values[model] = []
            self._tokens_per_sec_values[model] = []

    def record_request(
        self,
        model: str,
        ttft_seconds: Optional[float] = None,
        total_latency_seconds: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error: bool = False
    ):
        """
        Record an LLM request with all metrics.

        Args:
            model: Model name (e.g., "claude-sonnet-4-20250514")
            ttft_seconds: Time to first token in seconds (None if not streaming)
            total_latency_seconds: Total request latency in seconds
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_usd: Cost in USD
            error: Whether the request resulted in an error
        """
        self._init_model(model)

        self._requests_total[model] += 1

        if error:
            self._errors_total[model] += 1
            return

        # Token counters
        self._input_tokens_total[model] += input_tokens
        self._output_tokens_total[model] += output_tokens
        self._cost_usd_total[model] += cost_usd

        # TTFT histogram
        if ttft_seconds is not None:
            bucket = self._get_bucket(ttft_seconds, self.TTFT_BUCKETS)
            self._ttft_histogram[model][bucket] += 1
            self._ttft_values[model].append(ttft_seconds)
            if len(self._ttft_values[model]) > 1000:
                self._ttft_values[model] = self._ttft_values[model][-1000:]

        # Latency histogram
        if total_latency_seconds > 0:
            bucket = self._get_bucket(total_latency_seconds, self.LATENCY_BUCKETS)
            self._latency_histogram[model][bucket] += 1
            self._latency_values[model].append(total_latency_seconds)
            if len(self._latency_values[model]) > 1000:
                self._latency_values[model] = self._latency_values[model][-1000:]

        # Tokens per second
        if total_latency_seconds > 0 and output_tokens > 0:
            tps = output_tokens / total_latency_seconds
            self._tokens_per_sec_values[model].append(tps)
            if len(self._tokens_per_sec_values[model]) > 1000:
                self._tokens_per_sec_values[model] = self._tokens_per_sec_values[model][-1000:]

    def get_stats(self) -> Dict[str, Any]:
        """Get LLM metrics as a dictionary."""
        stats = {
            "uptime_seconds": time.time() - self._start_time,
            "by_model": {},
            "totals": {
                "requests": sum(self._requests_total.values()),
                "errors": sum(self._errors_total.values()),
                "input_tokens": sum(self._input_tokens_total.values()),
                "output_tokens": sum(self._output_tokens_total.values()),
                "cost_usd": round(sum(self._cost_usd_total.values()), 6),
            }
        }

        for model in self._requests_total.keys():
            ttft_vals = self._ttft_values.get(model, [])
            latency_vals = self._latency_values.get(model, [])
            tps_vals = self._tokens_per_sec_values.get(model, [])

            model_stats = {
                "requests": self._requests_total[model],
                "errors": self._errors_total[model],
                "input_tokens": self._input_tokens_total[model],
                "output_tokens": self._output_tokens_total[model],
                "cost_usd": round(self._cost_usd_total[model], 6),
            }

            if ttft_vals:
                sorted_ttft = sorted(ttft_vals)
                model_stats["ttft"] = {
                    "p50_s": sorted_ttft[len(sorted_ttft) // 2],
                    "p95_s": sorted_ttft[int(len(sorted_ttft) * 0.95)] if len(sorted_ttft) > 1 else sorted_ttft[0],
                    "p99_s": sorted_ttft[int(len(sorted_ttft) * 0.99)] if len(sorted_ttft) > 1 else sorted_ttft[0],
                    "avg_s": sum(sorted_ttft) / len(sorted_ttft),
                }

            if latency_vals:
                sorted_lat = sorted(latency_vals)
                model_stats["latency"] = {
                    "p50_s": sorted_lat[len(sorted_lat) // 2],
                    "p95_s": sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) > 1 else sorted_lat[0],
                    "p99_s": sorted_lat[int(len(sorted_lat) * 0.99)] if len(sorted_lat) > 1 else sorted_lat[0],
                    "avg_s": sum(sorted_lat) / len(sorted_lat),
                }

            if tps_vals:
                sorted_tps = sorted(tps_vals)
                model_stats["tokens_per_second"] = {
                    "p50": sorted_tps[len(sorted_tps) // 2],
                    "avg": sum(sorted_tps) / len(sorted_tps),
                    "max": max(sorted_tps),
                }

            stats["by_model"][model] = model_stats

        return stats

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Request counters
        lines.append("# HELP jarvis_llm_requests_total Total LLM requests by model")
        lines.append("# TYPE jarvis_llm_requests_total counter")
        for model, count in self._requests_total.items():
            lines.append(f'jarvis_llm_requests_total{{model="{model}"}} {count}')

        # Error counters
        lines.append("\n# HELP jarvis_llm_errors_total Total LLM errors by model")
        lines.append("# TYPE jarvis_llm_errors_total counter")
        for model, count in self._errors_total.items():
            lines.append(f'jarvis_llm_errors_total{{model="{model}"}} {count}')

        # Token counters
        lines.append("\n# HELP jarvis_llm_input_tokens_total Total input tokens by model")
        lines.append("# TYPE jarvis_llm_input_tokens_total counter")
        for model, count in self._input_tokens_total.items():
            lines.append(f'jarvis_llm_input_tokens_total{{model="{model}"}} {count}')

        lines.append("\n# HELP jarvis_llm_output_tokens_total Total output tokens by model")
        lines.append("# TYPE jarvis_llm_output_tokens_total counter")
        for model, count in self._output_tokens_total.items():
            lines.append(f'jarvis_llm_output_tokens_total{{model="{model}"}} {count}')

        # Cost counter
        lines.append("\n# HELP jarvis_llm_cost_usd_total Total cost in USD by model")
        lines.append("# TYPE jarvis_llm_cost_usd_total counter")
        for model, cost in self._cost_usd_total.items():
            lines.append(f'jarvis_llm_cost_usd_total{{model="{model}"}} {cost:.6f}')

        # TTFT histogram
        lines.append("\n# HELP jarvis_llm_ttft_seconds Time to first token in seconds")
        lines.append("# TYPE jarvis_llm_ttft_seconds histogram")
        for model, buckets in self._ttft_histogram.items():
            cumulative = 0
            for bucket in self.TTFT_BUCKETS:
                cumulative += buckets.get(bucket, 0)
                le = "+Inf" if bucket == float('inf') else str(bucket)
                lines.append(f'jarvis_llm_ttft_seconds_bucket{{model="{model}",le="{le}"}} {cumulative}')
            lines.append(f'jarvis_llm_ttft_seconds_count{{model="{model}"}} {cumulative}')
            if self._ttft_values.get(model):
                lines.append(f'jarvis_llm_ttft_seconds_sum{{model="{model}"}} {sum(self._ttft_values[model]):.6f}')

        # Latency histogram
        lines.append("\n# HELP jarvis_llm_latency_seconds Total request latency in seconds")
        lines.append("# TYPE jarvis_llm_latency_seconds histogram")
        for model, buckets in self._latency_histogram.items():
            cumulative = 0
            for bucket in self.LATENCY_BUCKETS:
                cumulative += buckets.get(bucket, 0)
                le = "+Inf" if bucket == float('inf') else str(bucket)
                lines.append(f'jarvis_llm_latency_seconds_bucket{{model="{model}",le="{le}"}} {cumulative}')
            lines.append(f'jarvis_llm_latency_seconds_count{{model="{model}"}} {cumulative}')
            if self._latency_values.get(model):
                lines.append(f'jarvis_llm_latency_seconds_sum{{model="{model}"}} {sum(self._latency_values[model]):.6f}')

        # Tokens per second gauge (current average)
        lines.append("\n# HELP jarvis_llm_tokens_per_second Average output tokens per second")
        lines.append("# TYPE jarvis_llm_tokens_per_second gauge")
        for model, values in self._tokens_per_sec_values.items():
            if values:
                avg = sum(values) / len(values)
                lines.append(f'jarvis_llm_tokens_per_second{{model="{model}"}} {avg:.2f}')

        return "\n".join(lines)


# ============ RAG Quality Metrics ============

class RAGMetrics:
    """
    Tracks RAG (Retrieval-Augmented Generation) quality metrics.
    Measures relevance scores, retrieval success, and context quality.
    """

    def __init__(self):
        self._start_time = time.time()

        # Counters
        self._searches_total = 0
        self._empty_results_total = 0
        self._searches_by_type: Dict[str, int] = {}  # semantic, keyword, hybrid

        # Relevance scores (recent values)
        self._relevance_scores: list = []
        self._chunks_retrieved: list = []

        # Source distribution
        self._source_counts: Dict[str, int] = {}  # semantic, keyword, both

    def record_search(
        self,
        search_type: str,
        results_count: int,
        avg_relevance: Optional[float] = None,
        source_distribution: Dict[str, int] = None,
        query_length: int = 0
    ):
        """
        Record a RAG search operation.

        Args:
            search_type: Type of search (semantic, keyword, hybrid)
            results_count: Number of results returned
            avg_relevance: Average relevance/fusion score of results
            source_distribution: Count of results by source (semantic, keyword, both)
            query_length: Length of query in characters
        """
        self._searches_total += 1

        # Track by type
        if search_type not in self._searches_by_type:
            self._searches_by_type[search_type] = 0
        self._searches_by_type[search_type] += 1

        # Track empty results
        if results_count == 0:
            self._empty_results_total += 1

        # Track chunks retrieved
        self._chunks_retrieved.append(results_count)
        if len(self._chunks_retrieved) > 1000:
            self._chunks_retrieved = self._chunks_retrieved[-1000:]

        # Track relevance scores
        if avg_relevance is not None:
            self._relevance_scores.append(avg_relevance)
            if len(self._relevance_scores) > 1000:
                self._relevance_scores = self._relevance_scores[-1000:]

        # Track source distribution
        if source_distribution:
            for source, count in source_distribution.items():
                if source not in self._source_counts:
                    self._source_counts[source] = 0
                self._source_counts[source] += count

    def get_stats(self) -> Dict[str, Any]:
        """Get RAG quality statistics."""
        stats = {
            "uptime_seconds": time.time() - self._start_time,
            "searches_total": self._searches_total,
            "empty_results_total": self._empty_results_total,
            "empty_rate": self._empty_results_total / max(self._searches_total, 1),
            "by_type": self._searches_by_type.copy(),
            "source_distribution": self._source_counts.copy(),
        }

        # Relevance score stats
        if self._relevance_scores:
            sorted_rel = sorted(self._relevance_scores)
            stats["relevance"] = {
                "avg": sum(self._relevance_scores) / len(self._relevance_scores),
                "p50": sorted_rel[len(sorted_rel) // 2],
                "p95": sorted_rel[int(len(sorted_rel) * 0.95)] if len(sorted_rel) > 1 else sorted_rel[0],
                "min": min(self._relevance_scores),
                "max": max(self._relevance_scores),
            }

        # Chunks retrieved stats
        if self._chunks_retrieved:
            sorted_chunks = sorted(self._chunks_retrieved)
            stats["chunks_retrieved"] = {
                "avg": sum(self._chunks_retrieved) / len(self._chunks_retrieved),
                "p50": sorted_chunks[len(sorted_chunks) // 2],
                "max": max(self._chunks_retrieved),
            }

        return stats

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Search counters
        lines.append("# HELP jarvis_rag_searches_total Total RAG searches")
        lines.append("# TYPE jarvis_rag_searches_total counter")
        lines.append(f"jarvis_rag_searches_total {self._searches_total}")

        lines.append("\n# HELP jarvis_rag_searches_by_type RAG searches by type")
        lines.append("# TYPE jarvis_rag_searches_by_type counter")
        for stype, count in self._searches_by_type.items():
            lines.append(f'jarvis_rag_searches_by_type{{type="{stype}"}} {count}')

        # Empty results
        lines.append("\n# HELP jarvis_rag_empty_results_total Searches with no results")
        lines.append("# TYPE jarvis_rag_empty_results_total counter")
        lines.append(f"jarvis_rag_empty_results_total {self._empty_results_total}")

        # Empty rate gauge
        lines.append("\n# HELP jarvis_rag_empty_rate Rate of searches with no results")
        lines.append("# TYPE jarvis_rag_empty_rate gauge")
        empty_rate = self._empty_results_total / max(self._searches_total, 1)
        lines.append(f"jarvis_rag_empty_rate {empty_rate:.4f}")

        # Relevance score gauge (current average)
        if self._relevance_scores:
            avg_relevance = sum(self._relevance_scores) / len(self._relevance_scores)
            lines.append("\n# HELP jarvis_rag_relevance_avg Average relevance score")
            lines.append("# TYPE jarvis_rag_relevance_avg gauge")
            lines.append(f"jarvis_rag_relevance_avg {avg_relevance:.4f}")

        # Average chunks retrieved
        if self._chunks_retrieved:
            avg_chunks = sum(self._chunks_retrieved) / len(self._chunks_retrieved)
            lines.append("\n# HELP jarvis_rag_chunks_avg Average chunks retrieved per search")
            lines.append("# TYPE jarvis_rag_chunks_avg gauge")
            lines.append(f"jarvis_rag_chunks_avg {avg_chunks:.2f}")

        # Source distribution
        lines.append("\n# HELP jarvis_rag_results_by_source Results by source type")
        lines.append("# TYPE jarvis_rag_results_by_source counter")
        for source, count in self._source_counts.items():
            lines.append(f'jarvis_rag_results_by_source{{source="{source}"}} {count}')

        return "\n".join(lines)


# ============ Tool Loop Detection ============

class ToolLoopDetector:
    """
    Detects when the agent gets stuck in tool loops.
    Jarvis: "Manchmal hänge ich in Tool-Loops. Das frustriert mich."

    Detection: Same tool 3x in sequence without meaningful state change.
    """

    def __init__(self, max_same_tool: int = 3, window_size: int = 5):
        self.max_same_tool = max_same_tool
        self.window_size = window_size
        self.tool_history: list = []
        self.arg_history: list = []  # Track args to detect identical calls
        self._loops_total = 0
        self._last_alert_time: float = 0
        self._alert_cooldown_seconds = 3600  # 1 hour between alerts

    def reset(self):
        """Reset history for new session/request."""
        self.tool_history = []
        self.arg_history = []

    def check_loop(self, tool_name: str, tool_args: Dict = None) -> Dict[str, Any]:
        """
        Check if adding this tool call creates a loop pattern.

        Returns:
            Dict with 'is_loop', 'tool_name', 'count', 'identical_args'
        """
        # Track call
        self.tool_history.append(tool_name)
        self.arg_history.append(json.dumps(tool_args or {}, sort_keys=True, default=str)[:500])

        # Keep window limited
        if len(self.tool_history) > self.window_size:
            self.tool_history.pop(0)
            self.arg_history.pop(0)

        # Check for loop pattern: same tool max_same_tool times in last window
        recent_tools = self.tool_history[-self.max_same_tool:]
        if len(recent_tools) >= self.max_same_tool:
            if all(t == tool_name for t in recent_tools):
                # Loop detected - check if args are also identical (stronger signal)
                recent_args = self.arg_history[-self.max_same_tool:]
                identical_args = len(set(recent_args)) == 1

                self._loops_total += 1

                return {
                    "is_loop": True,
                    "tool_name": tool_name,
                    "count": len(recent_tools),
                    "identical_args": identical_args,
                    "loops_total": self._loops_total
                }

        return {"is_loop": False}

    def should_alert(self) -> bool:
        """Check if enough time has passed since last alert (rate limiting)."""
        now = time.time()
        if now - self._last_alert_time > self._alert_cooldown_seconds:
            self._last_alert_time = now
            return True
        return False

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        lines = [
            "# HELP jarvis_tool_loops_total Total tool loops detected",
            "# TYPE jarvis_tool_loops_total counter",
            f"jarvis_tool_loops_total {self._loops_total}"
        ]
        return "\n".join(lines)

    @property
    def loops_total(self) -> int:
        return self._loops_total


# Global instances
metrics = Metrics()
llm_metrics = LLMMetrics()
rag_metrics = RAGMetrics()
tool_loop_detector = ToolLoopDetector()
embedding_cache = TTLCache(maxsize=config.EMBEDDING_CACHE_SIZE, ttl_seconds=config.EMBEDDING_CACHE_TTL)
query_cache = TTLCache(maxsize=config.QUERY_CACHE_SIZE, ttl_seconds=config.QUERY_CACHE_TTL)
vector_cache = TTLCache(maxsize=config.VECTOR_CACHE_SIZE, ttl_seconds=config.VECTOR_CACHE_TTL)
