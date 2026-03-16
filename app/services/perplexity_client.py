"""
Perplexity API Client.

Handles API calls to Perplexity/Sonar Pro for research queries.
Database-driven configuration with rate limiting and retry logic.
"""

import os
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import httpx

logger = logging.getLogger(__name__)


@dataclass
class PerplexityConfig:
    """Configuration loaded from database."""
    api_endpoint: str = "https://api.perplexity.ai/chat/completions"
    default_model: str = "sonar-pro"
    rate_limit_rpm: int = 60
    rate_limit_daily: int = 1000
    max_concurrent: int = 3
    retry_attempts: int = 3
    retry_delay_ms: int = 1000


@dataclass
class PerplexityResponse:
    """Structured response from Perplexity API."""
    content: str
    model: str
    citations: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    search_recency: Optional[str] = None
    raw_response: Optional[Dict] = None


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rpm: int = 60, daily: int = 1000):
        self.rpm = rpm
        self.daily = daily
        self._minute_tokens = rpm
        self._daily_tokens = daily
        self._last_minute_reset = time.time()
        self._last_daily_reset = datetime.now().date()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Try to acquire a token. Returns True if successful."""
        async with self._lock:
            now = time.time()
            today = datetime.now().date()

            # Reset daily tokens
            if today > self._last_daily_reset:
                self._daily_tokens = self.daily
                self._last_daily_reset = today

            # Reset minute tokens
            if now - self._last_minute_reset >= 60:
                self._minute_tokens = self.rpm
                self._last_minute_reset = now

            # Check limits
            if self._daily_tokens <= 0:
                logger.warning("Daily rate limit reached")
                return False

            if self._minute_tokens <= 0:
                logger.warning("Per-minute rate limit reached")
                return False

            self._minute_tokens -= 1
            self._daily_tokens -= 1
            return True

    @property
    def remaining_daily(self) -> int:
        return self._daily_tokens

    @property
    def remaining_minute(self) -> int:
        return self._minute_tokens


class PerplexityClient:
    """
    Async client for Perplexity API.

    Features:
    - Database-driven configuration
    - Rate limiting (per-minute and daily)
    - Retry with exponential backoff
    - Source/citation extraction
    - Concurrent request limiting
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY")
        if not self.api_key:
            logger.warning("PERPLEXITY_API_KEY not set")

        self.config = PerplexityConfig()
        self._rate_limiter: Optional[RateLimiter] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._config_loaded = False

    async def _ensure_config(self, db_client=None):
        """Load config from database if not already loaded."""
        if self._config_loaded:
            return

        if db_client:
            try:
                rows = await db_client.fetch(
                    "SELECT key, value FROM perplexity_config"
                )
                config_dict = {row["key"]: row["value"] for row in rows}

                self.config = PerplexityConfig(
                    api_endpoint=config_dict.get("api_endpoint", self.config.api_endpoint),
                    default_model=config_dict.get("default_model", self.config.default_model),
                    rate_limit_rpm=int(config_dict.get("rate_limit_rpm", self.config.rate_limit_rpm)),
                    rate_limit_daily=int(config_dict.get("rate_limit_daily", self.config.rate_limit_daily)),
                    max_concurrent=int(config_dict.get("max_concurrent", self.config.max_concurrent)),
                    retry_attempts=int(config_dict.get("retry_attempts", self.config.retry_attempts)),
                    retry_delay_ms=int(config_dict.get("retry_delay_ms", self.config.retry_delay_ms)),
                )
                logger.info(f"Loaded Perplexity config from DB: model={self.config.default_model}")
            except Exception as e:
                logger.warning(f"Could not load Perplexity config from DB: {e}")

        self._rate_limiter = RateLimiter(
            rpm=self.config.rate_limit_rpm,
            daily=self.config.rate_limit_daily
        )
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._config_loaded = True

    async def search(
        self,
        query: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        search_recency_filter: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        db_client=None,
    ) -> PerplexityResponse:
        """
        Execute a search query via Perplexity API.

        Args:
            query: The search/research query
            model: Model to use (default: sonar-pro)
            system_prompt: System prompt for context
            search_recency_filter: One of: day, week, month, year
            max_tokens: Max output tokens
            temperature: Sampling temperature
            db_client: Optional database client for config loading

        Returns:
            PerplexityResponse with content and citations
        """
        await self._ensure_config(db_client)

        if not self.api_key:
            raise ValueError("PERPLEXITY_API_KEY not configured")

        # Rate limiting
        if not await self._rate_limiter.acquire():
            raise RuntimeError("Rate limit exceeded. Try again later.")

        model = model or self.config.default_model
        start_time = time.time()

        # Build request
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "return_citations": True,
            "return_related_questions": False,
        }

        if search_recency_filter:
            payload["search_recency_filter"] = search_recency_filter

        # Execute with retry and concurrency limit
        async with self._semaphore:
            response = await self._execute_with_retry(payload)

        latency_ms = int((time.time() - start_time) * 1000)

        return self._parse_response(response, model, latency_ms, search_recency_filter)

    async def _execute_with_retry(self, payload: Dict) -> Dict:
        """Execute request with exponential backoff retry."""
        last_error = None

        for attempt in range(self.config.retry_attempts):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self.config.api_endpoint,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                    if response.status_code == 429:
                        # Rate limited by API
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"API rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    # Server error, retry
                    delay = (self.config.retry_delay_ms / 1000) * (2 ** attempt)
                    logger.warning(f"Server error {e.response.status_code}, retry in {delay}s")
                    await asyncio.sleep(delay)
                else:
                    # Client error, don't retry
                    raise

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                delay = (self.config.retry_delay_ms / 1000) * (2 ** attempt)
                logger.warning(f"Connection error, retry in {delay}s: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Failed after {self.config.retry_attempts} attempts: {last_error}")

    def _parse_response(
        self,
        response: Dict,
        model: str,
        latency_ms: int,
        search_recency: Optional[str]
    ) -> PerplexityResponse:
        """Parse API response into structured format."""
        choices = response.get("choices", [])
        content = ""
        citations = []

        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")

        # Extract citations from response
        citations = response.get("citations", [])

        # Build source list from citations
        sources = []
        for i, url in enumerate(citations):
            sources.append({
                "index": i + 1,
                "url": url,
                "domain": self._extract_domain(url),
            })

        # Token usage
        usage = response.get("usage", {})

        return PerplexityResponse(
            content=content,
            model=model,
            citations=citations,
            sources=sources,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            search_recency=search_recency,
            raw_response=response,
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return url

    @property
    def rate_limit_status(self) -> Dict[str, int]:
        """Get current rate limit status."""
        if not self._rate_limiter:
            return {"minute_remaining": -1, "daily_remaining": -1}
        return {
            "minute_remaining": self._rate_limiter.remaining_minute,
            "daily_remaining": self._rate_limiter.remaining_daily,
        }


# Singleton instance
_client: Optional[PerplexityClient] = None


def get_perplexity_client() -> PerplexityClient:
    """Get or create the Perplexity client singleton."""
    global _client
    if _client is None:
        _client = PerplexityClient()
    return _client
