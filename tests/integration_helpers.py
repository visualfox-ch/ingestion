"""Integration test helpers for Codex and Copilot.

Provides reusable utilities for:
- API endpoint testing
- Database fixtures
- Mock services
- Assertion helpers
- Performance benchmarking

Usage:
    from tests.integration_helpers import JarvisTestClient, DatabaseFixtures, Assertions
"""
import os
import json
import time
import asyncio
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, AsyncMock


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class TestConfig:
    """Test configuration with environment defaults."""
    api_base_url: str = "http://192.168.1.103:18000"
    api_key: str = field(default_factory=lambda: os.environ.get(
        "JARVIS_API_KEY",
        "qyCnbWkM2fr-GAhR3f_Vy3o9eWRas1vNLoPyifFqjQQxCYCp1VBn7d8DXmoFFRA0"
    ))
    timeout_seconds: int = 30
    retry_count: int = 3
    retry_delay_seconds: float = 1.0


# ============================================================================
# API Client for Integration Tests
# ============================================================================

class JarvisTestClient:
    """HTTP client for Jarvis API integration tests."""

    def __init__(self, config: Optional[TestConfig] = None):
        self.config = config or TestConfig()
        self._session = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
        }

    def get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request."""
        import requests
        url = f"{self.config.api_base_url}{path}"
        response = requests.get(
            url,
            headers=self._headers(),
            params=params,
            timeout=self.config.timeout_seconds
        )
        return {"status": response.status_code, "data": response.json()}

    def post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request."""
        import requests
        url = f"{self.config.api_base_url}{path}"
        response = requests.post(
            url,
            headers=self._headers(),
            json=data,
            timeout=self.config.timeout_seconds
        )
        return {"status": response.status_code, "data": response.json()}

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            result = self.get("/health")
            return result["status"] == 200
        except Exception:
            return False

    def wait_for_healthy(self, timeout: int = 60) -> bool:
        """Wait for API to become healthy."""
        start = time.time()
        while time.time() - start < timeout:
            if self.health_check():
                return True
            time.sleep(2)
        return False


# ============================================================================
# Database Fixtures
# ============================================================================

class DatabaseFixtures:
    """Database fixture management for tests."""

    @staticmethod
    def sample_learned_fact(
        user_id: str = "test_user",
        namespace: str = "test",
        key: str = "test_key",
        value: Any = "test_value",
        confidence: float = 0.8,
        source: str = "test",
    ) -> Dict[str, Any]:
        """Create a sample learned_fact record."""
        now = datetime.now()
        return {
            "user_id": user_id,
            "namespace": namespace,
            "key": key,
            "value": value,
            "confidence": confidence,
            "source": source,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(days=90),
            "sensitivity": "low",
        }

    @staticmethod
    def sample_decision_log(
        decision_id: str = "dec_001",
        context: str = "test_context",
        options: List[str] = None,
        chosen: str = "option_a",
        confidence: float = 0.7,
    ) -> Dict[str, Any]:
        """Create a sample decision_log record."""
        return {
            "decision_id": decision_id,
            "context": context,
            "options": options or ["option_a", "option_b"],
            "chosen_option": chosen,
            "confidence": confidence,
            "rationale": "Test decision",
            "outcome_known": False,
            "created_at": datetime.now(),
        }

    @staticmethod
    def sample_telegram_message(
        chat_id: int = 12345,
        user_id: int = 67890,
        text: str = "Test message",
    ) -> Dict[str, Any]:
        """Create a sample Telegram message payload."""
        return {
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Test", "is_bot": False},
                "text": text,
                "date": int(time.time()),
            }
        }


# ============================================================================
# Mock Services
# ============================================================================

class MockServices:
    """Mock external services for testing."""

    @staticmethod
    @contextmanager
    def mock_qdrant():
        """Mock Qdrant vector database."""
        with patch("app.qdrant_client") as mock:
            mock.search.return_value = [
                MagicMock(id="doc1", score=0.95, payload={"text": "test"}),
                MagicMock(id="doc2", score=0.85, payload={"text": "test2"}),
            ]
            mock.upsert.return_value = True
            yield mock

    @staticmethod
    @contextmanager
    def mock_meilisearch():
        """Mock Meilisearch."""
        with patch("app.meili_client") as mock:
            mock.search.return_value = {
                "hits": [{"id": "1", "text": "test"}],
                "estimatedTotalHits": 1,
            }
            yield mock

    @staticmethod
    @contextmanager
    def mock_redis():
        """Mock Redis client."""
        with patch("app.redis_client") as mock:
            cache = {}
            mock.get.side_effect = lambda k: cache.get(k)
            mock.set.side_effect = lambda k, v, **kw: cache.update({k: v})
            mock.delete.side_effect = lambda k: cache.pop(k, None)
            yield mock

    @staticmethod
    @contextmanager
    def mock_postgres():
        """Mock PostgreSQL connection."""
        with patch("app.db_safety.get_db_connection") as mock:
            cursor = MagicMock()
            cursor.fetchone.return_value = {"count": 1}
            cursor.fetchall.return_value = []
            mock.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
            yield mock

    @staticmethod
    @contextmanager
    def mock_anthropic():
        """Mock Anthropic API."""
        with patch("anthropic.Anthropic") as mock:
            mock.return_value.messages.create.return_value = MagicMock(
                content=[MagicMock(text="Test response")],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            )
            yield mock


# ============================================================================
# Assertion Helpers
# ============================================================================

class Assertions:
    """Custom assertions for integration tests."""

    @staticmethod
    def assert_response_ok(response: Dict[str, Any], expected_keys: List[str] = None):
        """Assert API response is successful."""
        assert response["status"] == 200, f"Expected 200, got {response['status']}"
        if expected_keys:
            for key in expected_keys:
                assert key in response["data"], f"Missing key: {key}"

    @staticmethod
    def assert_response_error(response: Dict[str, Any], expected_status: int):
        """Assert API response is an error."""
        assert response["status"] == expected_status

    @staticmethod
    def assert_health_status(data: Dict[str, Any], expected: str):
        """Assert health status matches expected."""
        assert data.get("health_status") == expected, \
            f"Expected {expected}, got {data.get('health_status')}"

    @staticmethod
    def assert_confidence_in_range(value: float, min_val: float = 0.0, max_val: float = 1.0):
        """Assert confidence is within valid range."""
        assert min_val <= value <= max_val, \
            f"Confidence {value} not in [{min_val}, {max_val}]"

    @staticmethod
    def assert_latency_under(elapsed_ms: float, threshold_ms: float):
        """Assert latency is under threshold."""
        assert elapsed_ms < threshold_ms, \
            f"Latency {elapsed_ms}ms exceeds threshold {threshold_ms}ms"

    @staticmethod
    def assert_no_pii(data: Dict[str, Any], pii_patterns: List[str] = None):
        """Assert response doesn't contain PII patterns."""
        pii_patterns = pii_patterns or [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
            r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
            r"\b\d{16}\b",  # Credit card
        ]
        import re
        text = json.dumps(data)
        for pattern in pii_patterns:
            assert not re.search(pattern, text), f"PII pattern found: {pattern}"


# ============================================================================
# Performance Helpers
# ============================================================================

class PerformanceHelpers:
    """Helpers for performance testing."""

    @staticmethod
    def time_function(func: Callable, *args, **kwargs) -> tuple:
        """Time a function call, return (result, elapsed_ms)."""
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return result, elapsed

    @staticmethod
    async def time_async(func: Callable, *args, **kwargs) -> tuple:
        """Time an async function call."""
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return result, elapsed

    @staticmethod
    def benchmark(func: Callable, iterations: int = 100) -> Dict[str, float]:
        """Benchmark a function over multiple iterations."""
        import statistics
        timings = []
        for _ in range(iterations):
            start = time.perf_counter()
            func()
            timings.append((time.perf_counter() - start) * 1000)

        return {
            "iterations": iterations,
            "min_ms": min(timings),
            "max_ms": max(timings),
            "mean_ms": statistics.mean(timings),
            "median_ms": statistics.median(timings),
            "std_dev_ms": statistics.stdev(timings) if len(timings) > 1 else 0,
        }


# ============================================================================
# Test Data Generators
# ============================================================================

class TestDataGenerators:
    """Generate test data for various scenarios."""

    @staticmethod
    def generate_facts(count: int, namespace: str = "test") -> List[Dict[str, Any]]:
        """Generate multiple test facts."""
        return [
            DatabaseFixtures.sample_learned_fact(
                user_id=f"user_{i % 10}",
                namespace=namespace,
                key=f"key_{i}",
                value=f"value_{i}",
                confidence=0.5 + (i % 5) * 0.1,
            )
            for i in range(count)
        ]

    @staticmethod
    def generate_conflicts(count: int) -> List[Dict[str, Any]]:
        """Generate conflicting facts for testing."""
        facts = []
        for i in range(count):
            # Create two facts with same key but different values
            facts.append(DatabaseFixtures.sample_learned_fact(
                key=f"conflict_key_{i}",
                value=f"value_a_{i}",
                confidence=0.7,
            ))
            facts.append(DatabaseFixtures.sample_learned_fact(
                key=f"conflict_key_{i}",
                value=f"value_b_{i}",
                confidence=0.6,
            ))
        return facts

    @staticmethod
    def generate_expired_facts(count: int) -> List[Dict[str, Any]]:
        """Generate expired facts for TTL testing."""
        now = datetime.now()
        return [
            {
                **DatabaseFixtures.sample_learned_fact(key=f"expired_{i}"),
                "expires_at": now - timedelta(days=i + 1),
                "created_at": now - timedelta(days=100 + i),
            }
            for i in range(count)
        ]


# ============================================================================
# Cleanup Helpers
# ============================================================================

class CleanupHelpers:
    """Helpers for test cleanup."""

    @staticmethod
    @contextmanager
    def temporary_facts(facts: List[Dict[str, Any]]):
        """Context manager to create and cleanup test facts."""
        created_ids = []
        try:
            # In real implementation, insert facts here
            for fact in facts:
                # created_ids.append(insert_fact(fact))
                pass
            yield created_ids
        finally:
            # Cleanup
            for fact_id in created_ids:
                # delete_fact(fact_id)
                pass

    @staticmethod
    def reset_test_namespace(namespace: str = "test"):
        """Delete all facts in test namespace."""
        # In real implementation:
        # DELETE FROM learned_facts WHERE namespace = 'test'
        pass


# ============================================================================
# Verification Helpers (for Copilot deploy verification)
# ============================================================================

class DeployVerification:
    """Helpers for post-deploy verification."""

    def __init__(self, client: JarvisTestClient = None):
        self.client = client or JarvisTestClient()

    def verify_health(self) -> Dict[str, Any]:
        """Verify API health after deploy."""
        result = self.client.get("/health")
        return {
            "healthy": result["status"] == 200,
            "details": result["data"],
        }

    def verify_memory_health(self) -> Dict[str, Any]:
        """Verify memory health endpoint."""
        result = self.client.get("/memory/health")
        return {
            "healthy": result["status"] == 200,
            "status": result["data"].get("health_status"),
            "total_facts": result["data"].get("total_facts"),
        }

    def verify_endpoints(self, endpoints: List[str]) -> Dict[str, bool]:
        """Verify multiple endpoints are responding."""
        results = {}
        for endpoint in endpoints:
            try:
                result = self.client.get(endpoint)
                results[endpoint] = result["status"] == 200
            except Exception as e:
                results[endpoint] = False
        return results

    def full_verification(self) -> Dict[str, Any]:
        """Run full post-deploy verification."""
        return {
            "health": self.verify_health(),
            "memory_health": self.verify_memory_health(),
            "endpoints": self.verify_endpoints([
                "/health",
                "/memory/health",
                "/memory/health/summary",
                "/docs/current-phase",
            ]),
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================================
# Quick Test Runner
# ============================================================================

def run_quick_checks():
    """Run quick integration checks - useful for Copilot verification."""
    print("Running quick integration checks...")

    client = JarvisTestClient()
    verifier = DeployVerification(client)

    # Check health
    print("\n1. Health Check...")
    health = verifier.verify_health()
    print(f"   Healthy: {health['healthy']}")

    # Check memory health
    print("\n2. Memory Health Check...")
    mem_health = verifier.verify_memory_health()
    print(f"   Status: {mem_health.get('status')}")
    print(f"   Facts: {mem_health.get('total_facts')}")

    # Full verification
    print("\n3. Full Verification...")
    full = verifier.full_verification()
    print(f"   Endpoints OK: {sum(full['endpoints'].values())}/{len(full['endpoints'])}")

    return full


if __name__ == "__main__":
    results = run_quick_checks()
    print("\n" + "="*60)
    print("Verification Complete")
    print("="*60)
    print(json.dumps(results, indent=2, default=str))
