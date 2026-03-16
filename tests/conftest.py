"""Pytest configuration and shared fixtures for Jarvis tests.

This file provides:
- Shared fixtures with unique names (to avoid conflicts with test-local fixtures)
- Test markers registration
- Session-scoped configuration

Note: Many test files define their own `client` fixture. This conftest uses
prefixed names (jarvis_*, api_*) to avoid conflicts.
"""
import os
import pytest
from typing import Dict, Any, List

# Import from our existing helpers
from tests.integration_helpers import (
    TestConfig,
    JarvisTestClient,
    DatabaseFixtures,
    MockServices,
)


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests requiring external services")
    config.addinivalue_line("markers", "requires_redis: marks tests needing Redis connection")
    config.addinivalue_line("markers", "requires_api: marks tests needing running Jarvis API")
    config.addinivalue_line("markers", "requires_db: marks tests needing PostgreSQL")


# ============================================================================
# Session-Scoped Configuration Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def api_base_url() -> str:
    """API base URL from environment or default."""
    return os.environ.get("JARVIS_API_URL", "http://192.168.1.103:18000")


@pytest.fixture(scope="session")
def api_key() -> str:
    """API key from environment or default."""
    return os.environ.get(
        "JARVIS_API_KEY",
        "qyCnbWkM2fr-GAhR3f_Vy3o9eWRas1vNLoPyifFqjQQxCYCp1VBn7d8DXmoFFRA0"
    )


@pytest.fixture(scope="session")
def test_config(api_base_url, api_key) -> TestConfig:
    """Test configuration for the session."""
    return TestConfig(
        api_base_url=api_base_url,
        api_key=api_key,
    )


# ============================================================================
# API Client Fixtures (prefixed to avoid conflicts)
# ============================================================================

@pytest.fixture(scope="session")
def jarvis_test_client(test_config) -> JarvisTestClient:
    """Session-scoped Jarvis test client.

    Use this for integration tests that need the real API.
    Individual test files may define their own `client` fixture.
    """
    return JarvisTestClient(test_config)


@pytest.fixture
def jarvis_client(test_config) -> JarvisTestClient:
    """Function-scoped Jarvis test client (fresh per test)."""
    return JarvisTestClient(test_config)


# ============================================================================
# Redis Fixtures
# ============================================================================

@pytest.fixture
def redis_connection():
    """Get Redis connection, skip if unavailable.

    Note: test_agent_coordinator.py has its own `redis_client` fixture.
    This fixture uses a different name to avoid conflicts.
    """
    try:
        import redis
        client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "192.168.1.103"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_timeout=5,
        )
        client.ping()
        yield client
        client.close()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


# ============================================================================
# Sample Data Fixtures
# ============================================================================

@pytest.fixture
def sample_messages() -> List[Dict[str, Any]]:
    """Sample message data for testing."""
    return [
        {
            "id": "msg_001",
            "text": "Hallo Jarvis, wie geht's?",
            "sender": "micha",
            "timestamp": "2026-02-08T10:00:00Z",
            "channel": "telegram",
        },
        {
            "id": "msg_002",
            "text": "Kannst du mir bei dem Projekt helfen?",
            "sender": "micha",
            "timestamp": "2026-02-08T10:01:00Z",
            "channel": "telegram",
        },
        {
            "id": "msg_003",
            "text": "Meeting morgen um 14 Uhr nicht vergessen!",
            "sender": "micha",
            "timestamp": "2026-02-08T10:02:00Z",
            "channel": "telegram",
        },
    ]


@pytest.fixture
def sample_learned_fact() -> Dict[str, Any]:
    """Sample learned fact for testing."""
    return DatabaseFixtures.sample_learned_fact()


@pytest.fixture
def sample_telegram_message() -> Dict[str, Any]:
    """Sample Telegram message payload."""
    return DatabaseFixtures.sample_telegram_message()


@pytest.fixture
def sample_decision_log() -> Dict[str, Any]:
    """Sample decision log entry."""
    return DatabaseFixtures.sample_decision_log()


# ============================================================================
# Mock Context Managers
# ============================================================================

@pytest.fixture
def mock_qdrant():
    """Mock Qdrant for tests that don't need real vector DB."""
    with MockServices.mock_qdrant() as mock:
        yield mock


@pytest.fixture
def mock_redis():
    """Mock Redis for tests that don't need real cache."""
    with MockServices.mock_redis() as mock:
        yield mock


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic API for tests that don't need real LLM."""
    with MockServices.mock_anthropic() as mock:
        yield mock


# ============================================================================
# Temporary Directory Fixture
# ============================================================================

@pytest.fixture
def tmp_test_dir(tmp_path):
    """Temporary directory for test files.

    Wrapper around pytest's tmp_path for consistency.
    """
    test_dir = tmp_path / "jarvis_test"
    test_dir.mkdir(exist_ok=True)
    return test_dir


# ============================================================================
# Skip Conditions
# ============================================================================

@pytest.fixture
def skip_if_no_api(jarvis_test_client):
    """Skip test if Jarvis API is not reachable."""
    if not jarvis_test_client.health_check():
        pytest.skip("Jarvis API not available")


@pytest.fixture
def skip_if_no_redis(redis_connection):
    """Skip test if Redis is not reachable."""
    # redis_connection already skips if unavailable
    return redis_connection
