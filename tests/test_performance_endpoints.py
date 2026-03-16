"""Performance tests for API endpoints.

Quick performance profiling for critical endpoints:
- /memory/health (new T-108 endpoint)
- /health (general health)
- /chat (main chat endpoint)

Run with: pytest tests/test_performance_endpoints.py -v -s
"""
import pytest
import time
import statistics
from typing import List, Dict, Any, Callable
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# ============================================================================
# Performance Test Utilities
# ============================================================================

class PerformanceProfiler:
    """Simple performance profiler for endpoint testing."""

    def __init__(self, name: str):
        self.name = name
        self.timings: List[float] = []

    def time_call(self, func: Callable, *args, **kwargs) -> Any:
        """Time a function call and record the duration."""
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        self.timings.append(elapsed)
        return result

    async def time_async_call(self, func: Callable, *args, **kwargs) -> Any:
        """Time an async function call."""
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        self.timings.append(elapsed)
        return result

    def stats(self) -> Dict[str, float]:
        """Calculate statistics from recorded timings."""
        if not self.timings:
            return {"count": 0}

        sorted_timings = sorted(self.timings)
        return {
            "count": len(self.timings),
            "min_ms": min(self.timings),
            "max_ms": max(self.timings),
            "mean_ms": statistics.mean(self.timings),
            "median_ms": statistics.median(self.timings),
            "p95_ms": sorted_timings[int(len(sorted_timings) * 0.95)] if len(sorted_timings) >= 20 else max(self.timings),
            "p99_ms": sorted_timings[int(len(sorted_timings) * 0.99)] if len(sorted_timings) >= 100 else max(self.timings),
            "std_dev_ms": statistics.stdev(self.timings) if len(self.timings) > 1 else 0,
        }

    def report(self) -> str:
        """Generate a human-readable report."""
        s = self.stats()
        return (
            f"\n{'='*60}\n"
            f"Performance Report: {self.name}\n"
            f"{'='*60}\n"
            f"Calls: {s.get('count', 0)}\n"
            f"Min: {s.get('min_ms', 0):.2f}ms\n"
            f"Max: {s.get('max_ms', 0):.2f}ms\n"
            f"Mean: {s.get('mean_ms', 0):.2f}ms\n"
            f"Median: {s.get('median_ms', 0):.2f}ms\n"
            f"P95: {s.get('p95_ms', 0):.2f}ms\n"
            f"Std Dev: {s.get('std_dev_ms', 0):.2f}ms\n"
            f"{'='*60}"
        )


# ============================================================================
# SLO Thresholds
# ============================================================================

class SLOThresholds:
    """Service Level Objective thresholds."""

    HEALTH_P95_MS = 100  # /health should be <100ms p95
    MEMORY_HEALTH_P95_MS = 500  # /memory/health can be slower (DB queries)
    CHAT_P95_MS = 5000  # /chat involves LLM, so 5s is acceptable


# ============================================================================
# Mock Database for Testing
# ============================================================================

def mock_db_cursor():
    """Create a mock database cursor."""
    cursor = MagicMock()
    cursor.fetchone.return_value = {"count": 5}
    cursor.fetchall.return_value = [
        {"namespace": "personal", "fact_count": 3},
        {"namespace": "work", "fact_count": 2},
    ]
    return cursor


@pytest.fixture
def mock_safe_list_query():
    """Mock the safe_list_query context manager."""
    with patch("app.routers.memory_health_router.safe_list_query") as mock:
        mock.return_value.__enter__ = MagicMock(return_value=mock_db_cursor())
        mock.return_value.__exit__ = MagicMock(return_value=False)
        yield mock


# ============================================================================
# Memory Health Endpoint Performance Tests
# ============================================================================

class TestMemoryHealthPerformance:
    """Performance tests for /memory/health endpoint."""

    def test_get_fact_counts_performance(self, mock_safe_list_query):
        """Test get_fact_counts helper function performance."""
        from app.routers.memory_health_router import get_fact_counts

        profiler = PerformanceProfiler("get_fact_counts")

        for _ in range(100):
            result = profiler.time_call(get_fact_counts)
            assert "total" in result

        stats = profiler.stats()
        print(profiler.report())

        # Should be very fast with mocked DB
        assert stats["mean_ms"] < 10, f"Mean too slow: {stats['mean_ms']}ms"

    def test_get_confidence_distribution_performance(self, mock_safe_list_query):
        """Test confidence distribution calculation performance."""
        from app.routers.memory_health_router import get_confidence_distribution

        profiler = PerformanceProfiler("get_confidence_distribution")

        for _ in range(100):
            result = profiler.time_call(get_confidence_distribution)
            assert hasattr(result, "high")

        stats = profiler.stats()
        print(profiler.report())

        assert stats["mean_ms"] < 10

    def test_assess_health_status_performance(self):
        """Test health assessment logic performance (no DB)."""
        from app.routers.memory_health_router import assess_health_status

        profiler = PerformanceProfiler("assess_health_status")

        for _ in range(1000):
            status, issues = profiler.time_call(
                assess_health_status,
                total_facts=100,
                avg_confidence=0.75,
                conflict_count=3,
                velocity_7d=2.5,
                expired_backlog=50
            )

        stats = profiler.stats()
        print(profiler.report())

        # Pure logic should be < 1ms
        assert stats["mean_ms"] < 1
        assert stats["p95_ms"] < 2


# ============================================================================
# Health Assessment Logic Tests
# ============================================================================

class TestHealthAssessmentPerformance:
    """Test the health assessment scoring performance."""

    def test_health_status_thresholds(self):
        """Test all health threshold combinations."""
        from app.routers.memory_health_router import assess_health_status

        test_cases = [
            # (total, confidence, conflicts, velocity, backlog) -> expected_status
            (100, 0.8, 2, 5.0, 10, "healthy"),
            (100, 0.4, 2, 5.0, 10, "warning"),  # Low confidence
            (100, 0.8, 10, 5.0, 10, "warning"),  # High conflict rate
            (100, 0.8, 2, 0.5, 10, "warning"),  # Low velocity
            (100, 0.8, 2, 5.0, 150, "warning"),  # High backlog
            (0, 0.0, 0, 0.0, 0, "critical"),  # No facts
            (100, 0.2, 2, 5.0, 10, "critical"),  # Very low confidence
        ]

        profiler = PerformanceProfiler("health_threshold_checks")

        for total, conf, conflicts, vel, backlog, expected in test_cases:
            status, issues = profiler.time_call(
                assess_health_status,
                total, conf, conflicts, vel, backlog
            )
            assert status == expected, f"Expected {expected}, got {status} for {(total, conf, conflicts, vel, backlog)}"

        print(profiler.report())


# ============================================================================
# Concurrent Request Simulation
# ============================================================================

class TestConcurrentPerformance:
    """Test performance under simulated concurrent load."""

    def test_parallel_health_assessments(self):
        """Simulate parallel health assessment requests."""
        from app.routers.memory_health_router import assess_health_status
        import concurrent.futures

        def single_assessment():
            return assess_health_status(
                total_facts=50,
                avg_confidence=0.7,
                conflict_count=2,
                velocity_7d=3.0,
                expired_backlog=20
            )

        profiler = PerformanceProfiler("parallel_assessments")
        start = time.perf_counter()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(single_assessment) for _ in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        total_time = (time.perf_counter() - start) * 1000
        print(f"\n100 parallel assessments completed in {total_time:.2f}ms")

        assert len(results) == 100
        assert total_time < 1000  # Should complete in < 1s


# ============================================================================
# Memory Usage Tests
# ============================================================================

class TestMemoryUsage:
    """Test memory usage patterns."""

    def test_no_memory_leak_in_repeated_calls(self, mock_safe_list_query):
        """Ensure no memory accumulation over repeated calls."""
        import gc
        from app.routers.memory_health_router import get_fact_counts

        gc.collect()
        initial_objects = len(gc.get_objects())

        # Run many iterations
        for _ in range(1000):
            _ = get_fact_counts()

        gc.collect()
        final_objects = len(gc.get_objects())

        # Allow some variance but not unbounded growth
        growth = final_objects - initial_objects
        print(f"\nObject count growth: {growth}")

        # Should not grow significantly
        assert growth < 1000, f"Potential memory leak: {growth} new objects"


# ============================================================================
# Response Size Tests
# ============================================================================

class TestResponseSize:
    """Test response payload sizes."""

    def test_health_response_size(self):
        """Memory health response should be reasonably sized."""
        import json
        from app.routers.memory_health_router import (
            MemoryHealthResponse,
            ConfidenceDistribution,
            SourceDistribution
        )

        response = MemoryHealthResponse(
            total_facts=100,
            active_facts=95,
            expired_facts=5,
            by_confidence=ConfidenceDistribution(high=50, medium=30, low=15),
            by_source=SourceDistribution(
                user_explicit=40,
                system_inferred=30,
                telegram_pattern=20,
                agent_decision=5,
                cross_session=5,
                other=0
            ),
            avg_confidence=0.75,
            conflict_count=3,
            duplicate_count=2,
            expiring_soon=10,
            expired_pending_cleanup=5,
            learning_velocity_7d=5.0,
            learning_velocity_30d=3.5,
            memory_coverage=0.85,
            health_status="healthy",
            health_issues=[]
        )

        json_size = len(json.dumps(response.model_dump()))
        print(f"\nHealth response JSON size: {json_size} bytes")

        # Should be < 2KB
        assert json_size < 2048


# ============================================================================
# Database Query Performance Expectations
# ============================================================================

class TestDatabaseQueryExpectations:
    """Document expected database query performance."""

    def test_expected_query_counts(self, mock_safe_list_query):
        """Memory health should use a reasonable number of queries."""
        from app.routers.memory_health_router import (
            get_fact_counts,
            get_confidence_distribution,
            get_source_distribution,
            get_learning_velocity,
            get_conflict_count,
            get_expiring_facts,
            get_average_confidence,
        )

        # Each helper makes 1-3 queries
        get_fact_counts()  # 3 queries
        get_confidence_distribution()  # 1 query
        get_source_distribution()  # 1 query
        get_learning_velocity(7)  # 1 query
        get_conflict_count()  # 1 query
        get_expiring_facts(7)  # 1 query
        get_average_confidence()  # 1 query

        # Total: ~9 queries per /memory/health call
        # This is acceptable but could be optimized to 2-3 queries
        total_expected_queries = 9
        print(f"\nExpected queries per /memory/health: {total_expected_queries}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
