"""
LLM Call Optimizations (O4-O6).

O4: Streaming Optimizations - Buffered streaming with progress tracking
O5: Tool Caching - Cache tool definitions with TTL
O6: Context Window Optimization - Smart message truncation
"""

import time
import hashlib
import threading
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

# Prometheus metrics (lazy import to avoid circular deps)
_prometheus_exporter = None


def _get_exporter():
    """Get prometheus exporter (lazy load)."""
    global _prometheus_exporter
    if _prometheus_exporter is None:
        try:
            from ..prometheus_exporter import get_prometheus_exporter
            _prometheus_exporter = get_prometheus_exporter()
        except Exception:
            pass
    return _prometheus_exporter


# =============================================================================
# O4: STREAMING OPTIMIZATIONS
# =============================================================================

@dataclass
class StreamingConfig:
    """Configuration for optimized streaming."""
    buffer_size: int = 3  # Characters to buffer before flushing
    flush_interval_ms: int = 50  # Max time before flush
    enable_progress: bool = True  # Track streaming progress
    chunk_metrics: bool = True  # Log chunk statistics


class StreamBuffer:
    """
    Buffered streaming for smoother output.

    Buffers small chunks and flushes at intervals for better UX.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        config: StreamingConfig = None
    ):
        self.callback = callback
        self.config = config or StreamingConfig()
        self.buffer = ""
        self.last_flush = time.time()
        self.total_chars = 0
        self.chunk_count = 0
        self.start_time = time.time()
        self._lock = threading.Lock()

    def write(self, chunk: str) -> None:
        """Write a chunk to the buffer."""
        with self._lock:
            self.buffer += chunk
            self.chunk_count += 1

            # Flush if buffer is large enough or interval exceeded
            now = time.time()
            interval_ms = (now - self.last_flush) * 1000

            should_flush = (
                len(self.buffer) >= self.config.buffer_size or
                interval_ms >= self.config.flush_interval_ms
            )

            if should_flush and self.buffer:
                self._flush()

    def _flush(self) -> None:
        """Flush buffer to callback."""
        if self.buffer:
            try:
                self.callback(self.buffer)
                self.total_chars += len(self.buffer)
            except Exception as e:
                logger.debug(f"Stream callback error: {e}")
            finally:
                self.buffer = ""
                self.last_flush = time.time()

    def finish(self) -> Dict[str, Any]:
        """Flush remaining buffer and return metrics."""
        with self._lock:
            self._flush()

            duration_ms = (time.time() - self.start_time) * 1000

            # Record streaming metrics (O4)
            if self.total_chars > 0:
                exporter = _get_exporter()
                if exporter:
                    exporter.export_llm_streaming(self.total_chars)

            return {
                "total_chars": self.total_chars,
                "chunk_count": self.chunk_count,
                "duration_ms": round(duration_ms, 2),
                "chars_per_second": round(self.total_chars / (duration_ms / 1000), 2) if duration_ms > 0 else 0
            }


def create_optimized_stream_callback(
    user_callback: Callable[[str], None],
    config: StreamingConfig = None
) -> tuple:
    """
    Create an optimized streaming callback wrapper.

    Returns:
        (wrapped_callback, finish_fn) - Use finish_fn to get metrics
    """
    buffer = StreamBuffer(user_callback, config)
    return buffer.write, buffer.finish


# =============================================================================
# O5: TOOL CACHING
# =============================================================================

@dataclass
class ToolCache:
    """Cache for tool definitions with TTL."""
    definitions: List[Dict] = field(default_factory=list)
    hash_key: str = ""
    timestamp: float = 0.0
    ttl_seconds: float = 60.0  # 1 minute default


_tool_cache = ToolCache()
_tool_cache_lock = threading.Lock()


def _compute_tool_hash(tool_registry: List[Dict]) -> str:
    """Compute hash of tool registry for cache invalidation."""
    # Use tool names + descriptions for hash (fast, catches changes)
    hasher = hashlib.md5()
    for tool in sorted(tool_registry, key=lambda t: t.get("name", "")):
        hasher.update(tool.get("name", "").encode())
        hasher.update(tool.get("description", "")[:100].encode())
    return hasher.hexdigest()[:16]


def get_cached_tool_definitions(
    get_definitions_fn: Callable[[], List[Dict]],
    tool_registry: List[Dict] = None,
    ttl_seconds: float = 60.0
) -> List[Dict]:
    """
    Get tool definitions with caching.

    Args:
        get_definitions_fn: Function to get fresh definitions
        tool_registry: Registry to hash for invalidation (optional)
        ttl_seconds: Cache TTL in seconds

    Returns:
        Cached or fresh tool definitions
    """
    global _tool_cache

    with _tool_cache_lock:
        now = time.time()

        # Check if cache is valid
        cache_age = now - _tool_cache.timestamp

        if _tool_cache.definitions and cache_age < ttl_seconds:
            # Check hash if registry provided
            if tool_registry:
                current_hash = _compute_tool_hash(tool_registry)
                if current_hash == _tool_cache.hash_key:
                    logger.debug(f"O5: Tool cache HIT (age={cache_age:.1f}s)")
                    exporter = _get_exporter()
                    if exporter:
                        exporter.export_llm_cache_hit("tool_definitions")
                    return _tool_cache.definitions
            else:
                logger.debug(f"O5: Tool cache HIT (age={cache_age:.1f}s)")
                exporter = _get_exporter()
                if exporter:
                    exporter.export_llm_cache_hit("tool_definitions")
                return _tool_cache.definitions

        # Cache miss - get fresh definitions
        logger.debug(f"O5: Tool cache MISS (age={cache_age:.1f}s)")
        exporter = _get_exporter()
        if exporter:
            exporter.export_llm_cache_miss("tool_definitions")
        definitions = get_definitions_fn()

        # Update cache
        _tool_cache.definitions = definitions
        _tool_cache.timestamp = now
        _tool_cache.ttl_seconds = ttl_seconds

        if tool_registry:
            _tool_cache.hash_key = _compute_tool_hash(tool_registry)

        return definitions


def invalidate_tool_cache() -> None:
    """Force invalidate the tool cache."""
    global _tool_cache
    with _tool_cache_lock:
        _tool_cache.timestamp = 0.0
        logger.debug("O5: Tool cache invalidated")


# =============================================================================
# O6: CONTEXT WINDOW OPTIMIZATION
# =============================================================================

@dataclass
class ContextConfig:
    """Configuration for context window optimization."""
    max_tokens: int = 180000  # Claude's context limit
    reserve_output: int = 4096  # Reserve for response
    reserve_tools: int = 20000  # Reserve for tool definitions
    chars_per_token: float = 4.0  # Rough estimate
    keep_recent_messages: int = 10  # Always keep N most recent
    summarize_threshold: int = 20  # Summarize if more than N messages
    system_prompt_budget: float = 0.15  # 15% for system prompt


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Estimate token count from text length."""
    if not text:
        return 0
    return int(len(text) / chars_per_token)


def estimate_message_tokens(message: Dict[str, Any], chars_per_token: float = 4.0) -> int:
    """Estimate tokens for a single message."""
    content = message.get("content", "")

    if isinstance(content, str):
        return estimate_tokens(content, chars_per_token)
    elif isinstance(content, list):
        # Multi-part content (text + images)
        total = 0
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""), chars_per_token)
                elif part.get("type") in ("image", "image_url"):
                    total += 1000  # Images cost ~1000 tokens
            elif isinstance(part, str):
                total += estimate_tokens(part, chars_per_token)
        return total

    return 0


def _create_summary_message(messages: List[Dict], max_chars: int = 500) -> Dict:
    """Create a summary of older messages."""
    # Extract key points from messages
    summary_parts = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            # Take first 100 chars of each message
            preview = content[:100].strip()
            if len(content) > 100:
                preview += "..."
            summary_parts.append(f"[{role}]: {preview}")

    summary_text = " | ".join(summary_parts)
    if len(summary_text) > max_chars:
        summary_text = summary_text[:max_chars] + "..."

    return {
        "role": "user",
        "content": f"[Earlier conversation summary: {summary_text}]"
    }


def optimize_context_window(
    messages: List[Dict[str, Any]],
    system_prompt: str = "",
    tool_definitions: List[Dict] = None,
    config: ContextConfig = None
) -> tuple:
    """
    Optimize messages to fit within context window.

    Args:
        messages: Full message history
        system_prompt: System prompt text
        tool_definitions: Tool definitions (for token estimation)
        config: Context configuration

    Returns:
        (optimized_messages, stats) - Truncated messages and statistics
    """
    config = config or ContextConfig()

    # Calculate available budget
    system_tokens = estimate_tokens(system_prompt, config.chars_per_token)
    tools_tokens = sum(
        estimate_tokens(str(t), config.chars_per_token)
        for t in (tool_definitions or [])
    )

    available = config.max_tokens - config.reserve_output - tools_tokens - system_tokens

    stats = {
        "total_messages": len(messages),
        "system_tokens": system_tokens,
        "tools_tokens": tools_tokens,
        "available_tokens": available,
        "truncated": False,
        "summarized": False
    }

    if not messages:
        return messages, stats

    # Calculate total message tokens
    message_tokens = [estimate_message_tokens(m, config.chars_per_token) for m in messages]
    total_tokens = sum(message_tokens)

    stats["original_tokens"] = total_tokens

    # If within budget, return as-is
    if total_tokens <= available:
        stats["final_tokens"] = total_tokens
        return messages, stats

    # Need to truncate - keep recent messages
    stats["truncated"] = True

    # Record truncation metric
    exporter = _get_exporter()
    if exporter:
        exporter.export_llm_context_truncation()

    # Always keep the most recent messages
    keep_recent = min(config.keep_recent_messages, len(messages))
    recent_messages = messages[-keep_recent:]
    recent_tokens = sum(message_tokens[-keep_recent:])

    older_messages = messages[:-keep_recent] if keep_recent < len(messages) else []

    if not older_messages:
        # All messages are "recent" - just return them
        stats["final_tokens"] = recent_tokens
        stats["kept_messages"] = len(recent_messages)
        return recent_messages, stats

    # Budget for older messages
    remaining_budget = available - recent_tokens - 500  # Reserve 500 for summary

    if remaining_budget <= 0:
        # Only room for recent messages + summary
        stats["summarized"] = True
        summary = _create_summary_message(older_messages)
        optimized = [summary] + recent_messages
        stats["final_tokens"] = recent_tokens + estimate_message_tokens(summary, config.chars_per_token)
        stats["kept_messages"] = len(recent_messages)
        stats["summarized_messages"] = len(older_messages)
        return optimized, stats

    # Fit as many older messages as possible
    kept_older = []
    older_kept_tokens = 0

    # Work backwards from oldest recent to oldest
    for i in range(len(older_messages) - 1, -1, -1):
        msg_tokens = message_tokens[i]
        if older_kept_tokens + msg_tokens <= remaining_budget:
            kept_older.insert(0, older_messages[i])
            older_kept_tokens += msg_tokens
        else:
            break

    # Summarize any remaining older messages
    summarized_count = len(older_messages) - len(kept_older)

    if summarized_count > 0:
        stats["summarized"] = True
        summary = _create_summary_message(older_messages[:summarized_count])
        optimized = [summary] + kept_older + recent_messages
        stats["summarized_messages"] = summarized_count

        # Record messages dropped metric
        exporter = _get_exporter()
        if exporter:
            exporter.export_llm_context_truncation(messages_dropped=summarized_count)
    else:
        optimized = kept_older + recent_messages

    stats["final_tokens"] = older_kept_tokens + recent_tokens
    stats["kept_messages"] = len(kept_older) + len(recent_messages)

    return optimized, stats


# =============================================================================
# COMBINED OPTIMIZATION HELPER
# =============================================================================

def apply_llm_optimizations(
    messages: List[Dict],
    system_prompt: str,
    get_tools_fn: Callable[[], List[Dict]],
    stream_callback: Optional[Callable[[str], None]] = None,
    tool_registry: List[Dict] = None
) -> Dict[str, Any]:
    """
    Apply all LLM optimizations (O4-O6).

    Returns dict with:
        - messages: Optimized messages
        - tools: Cached tool definitions
        - stream_callback: Optimized streaming callback (if provided)
        - finish_streaming: Function to call after streaming
        - stats: Optimization statistics
    """
    result = {
        "stats": {}
    }

    # O5: Get cached tools
    tools = get_cached_tool_definitions(get_tools_fn, tool_registry)
    result["tools"] = tools
    result["stats"]["tools_cached"] = True

    # O6: Optimize context window
    optimized_messages, context_stats = optimize_context_window(
        messages, system_prompt, tools
    )
    result["messages"] = optimized_messages
    result["stats"]["context"] = context_stats

    # O4: Optimize streaming if callback provided
    if stream_callback:
        wrapped_callback, finish_fn = create_optimized_stream_callback(stream_callback)
        result["stream_callback"] = wrapped_callback
        result["finish_streaming"] = finish_fn
    else:
        result["stream_callback"] = None
        result["finish_streaming"] = lambda: {}

    return result
