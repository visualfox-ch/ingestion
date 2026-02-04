"""
Simple in-memory rate limiter for Jarvis API.

Uses sliding window counters to limit requests per time window.
Lightweight implementation without external dependencies.
"""
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from fastapi import Request, HTTPException
from functools import wraps

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.rate_limiter")


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit tier."""
    requests_per_minute: int
    requests_per_hour: int
    name: str


# Rate limit tiers
RATE_LIMITS = {
    # Expensive LLM endpoints - strict limits
    "expensive": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=100,
        name="expensive"
    ),
    # Normal search/query endpoints - moderate limits
    "normal": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=500,
        name="normal"
    ),
    # Ingestion endpoints - generous limits
    "ingest": RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=200,
        name="ingest"
    ),
    # Read-only endpoints - very generous
    "readonly": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        name="readonly"
    ),
}

# Endpoint to tier mapping
ENDPOINT_TIERS: Dict[str, str] = {
    # Expensive (LLM calls)
    "/agent": "expensive",
    "/answer": "expensive",
    "/answer_llm": "expensive",
    "/briefing": "expensive",
    "/mirror": "expensive",
    "/knowledge/insights/propose": "expensive",
    "/render_style_preview": "expensive",

    # Normal (search/queries)
    "/search": "normal",
    "/chat": "normal",
    "/entities/extract": "normal",
    "/sentiment/analyze": "normal",
    "/patterns/relevant": "normal",
    "/optimize": "normal",
    "/coach": "normal",
    "/prompts": "normal",
    "/tasks": "normal",
    "/projects": "normal",
    "/actions": "normal",
    "/remediate": "normal",
    "/code": "normal",

    # Ingest
    "/ingest_txt": "ingest",
    "/ingest_whatsapp_private": "ingest",
    "/ingest_whatsapp_work_projektil": "ingest",
    "/ingest_gchat_private": "ingest",
    "/ingest_gchat_work_projektil": "ingest",
    "/ingest_gmail_inbox_work_projektil": "ingest",
    "/ingest_gmail_sent_work_projektil": "ingest",
    "/ingest_gmail_delta": "ingest",
    "/ingest_gmail_delta_all": "ingest",
    "/ingest_drive": "ingest",

    # Read-only (default for GET endpoints not listed)
    "/health": "readonly",
    "/metrics": "readonly",
    "/monitoring": "readonly",
    "/info": "readonly",
    "/self": "readonly",
    "/sessions": "readonly",
    "/roles": "readonly",
    "/personas": "readonly",
    "/calendar/events": "readonly",
    "/stats": "readonly",
    "/n8n/status": "readonly",
    "/workflows": "normal",
}


class RateLimiter:
    """
    Simple sliding window rate limiter.

    Uses in-memory storage - resets on restart.
    For production with multiple instances, use Redis.
    """

    def __init__(self):
        # {client_key: {minute_window: count, hour_window: count}}
        self._minute_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._hour_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # Cleanup every 5 minutes

    def _get_client_key(self, request: Request) -> str:
        """
        Get a unique key for the client.
        Uses X-Forwarded-For if behind proxy, otherwise client host.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take first IP in chain
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        # Include user_id from query params if present (for Telegram users)
        user_id = request.query_params.get("user_id")
        if user_id:
            return f"{client_ip}:{user_id}"
        return client_ip

    def _get_current_windows(self) -> Tuple[int, int]:
        """Get current minute and hour windows."""
        now = time.time()
        minute_window = int(now // 60)
        hour_window = int(now // 3600)
        return minute_window, hour_window

    def _cleanup_old_windows(self):
        """Remove old window data to prevent memory growth."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        current_minute = int(now // 60)
        current_hour = int(now // 3600)

        # Keep only recent windows
        for client_key in list(self._minute_counts.keys()):
            old_minutes = [m for m in self._minute_counts[client_key] if m < current_minute - 2]
            for m in old_minutes:
                del self._minute_counts[client_key][m]
            if not self._minute_counts[client_key]:
                del self._minute_counts[client_key]

        for client_key in list(self._hour_counts.keys()):
            old_hours = [h for h in self._hour_counts[client_key] if h < current_hour - 2]
            for h in old_hours:
                del self._hour_counts[client_key][h]
            if not self._hour_counts[client_key]:
                del self._hour_counts[client_key]

        self._last_cleanup = now

    def check_rate_limit(self, request: Request, tier: str = "normal") -> Tuple[bool, Optional[Dict]]:
        """
        Check if request is within rate limits.

        Returns:
            Tuple of (allowed: bool, info: dict with limit details)
        """
        self._cleanup_old_windows()

        config = RATE_LIMITS.get(tier, RATE_LIMITS["normal"])
        client_key = self._get_client_key(request)
        minute_window, hour_window = self._get_current_windows()

        # Get current counts
        minute_count = self._minute_counts[client_key][minute_window]
        hour_count = self._hour_counts[client_key][hour_window]

        info = {
            "tier": tier,
            "client": client_key,
            "minute_count": minute_count,
            "minute_limit": config.requests_per_minute,
            "hour_count": hour_count,
            "hour_limit": config.requests_per_hour,
        }

        # Check limits
        if minute_count >= config.requests_per_minute:
            info["retry_after"] = 60 - (time.time() % 60)
            info["limit_type"] = "minute"
            return False, info

        if hour_count >= config.requests_per_hour:
            info["retry_after"] = 3600 - (time.time() % 3600)
            info["limit_type"] = "hour"
            return False, info

        # Increment counters
        self._minute_counts[client_key][minute_window] += 1
        self._hour_counts[client_key][hour_window] += 1

        info["remaining_minute"] = config.requests_per_minute - minute_count - 1
        info["remaining_hour"] = config.requests_per_hour - hour_count - 1

        return True, info

    def get_stats(self) -> Dict:
        """Get current rate limiter statistics."""
        minute_window, hour_window = self._get_current_windows()

        active_clients = set(self._minute_counts.keys()) | set(self._hour_counts.keys())

        return {
            "active_clients": len(active_clients),
            "minute_window": minute_window,
            "hour_window": hour_window,
            "memory_entries": sum(len(v) for v in self._minute_counts.values()) +
                            sum(len(v) for v in self._hour_counts.values())
        }


# Global rate limiter instance
_rate_limiter = RateLimiter()


def get_tier_for_endpoint(path: str) -> str:
    """Get rate limit tier for an endpoint path."""
    # Check exact match first
    if path in ENDPOINT_TIERS:
        return ENDPOINT_TIERS[path]

    # Check prefix matches
    for endpoint, tier in ENDPOINT_TIERS.items():
        if path.startswith(endpoint):
            return tier

    # Default tier based on method hint in path
    if "ingest" in path.lower():
        return "ingest"

    return "normal"


async def rate_limit_dependency(request: Request):
    """
    FastAPI dependency for rate limiting.

    Raises HTTPException 429 if rate limit exceeded.
    """
    path = request.url.path
    tier = get_tier_for_endpoint(path)

    allowed, info = _rate_limiter.check_rate_limit(request, tier)

    if not allowed:
        log_with_context(logger, "warning", "Rate limit exceeded",
                        client=info.get("client"),
                        path=path,
                        tier=tier,
                        limit_type=info.get("limit_type"))

        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. Limit: {info.get('minute_limit')}/min, {info.get('hour_limit')}/hour",
                "retry_after": int(info.get("retry_after", 60)),
                "tier": tier,
            },
            headers={
                "Retry-After": str(int(info.get("retry_after", 60))),
                "X-RateLimit-Limit": str(info.get("minute_limit")),
                "X-RateLimit-Remaining": "0",
            }
        )

    # Add rate limit headers to response (via request state for middleware)
    request.state.rate_limit_info = info


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter


def get_rate_limit_stats() -> Dict:
    """Get rate limiter statistics."""
    return _rate_limiter.get_stats()
