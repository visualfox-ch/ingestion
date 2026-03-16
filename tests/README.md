# Jarvis Ingestion Test Suite

## Test Types
- API: test_api.py, test_api_mock.py
- Plugins: test_plugins.py, test_plugins_mock.py
- Dashboard: test_dashboard.py, test_dashboard_mock.py

## Coverage
Run coverage report:

    ./test_coverage_report.sh

## Mocking
External dependencies are mocked using unittest.mock or pytest-mock.

## Example
To run all tests with coverage:

    pytest --cov=app --cov-report=html --cov-report=term

HTML report will be in `htmlcov/`.
# Jarvis Ingestion Test Suite

## Quick Start

```bash
# Run all tests
cd /Volumes/BRAIN/system/ingestion
pytest

# Run with verbose output
pytest -v

# Run fast tests only (skip slow/integration)
pytest -m "not slow and not integration"

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

## Test Categories

Tests are organized with markers for selective execution:

| Marker | Description | Example |
|--------|-------------|---------|
| `slow` | Tests taking >5s | Large data processing |
| `integration` | Requires external services | API calls, DB writes |
| `requires_redis` | Needs Redis connection | Caching tests |
| `requires_api` | Needs running Jarvis API | E2E tests |
| `requires_db` | Needs PostgreSQL | Persistence tests |

### Running by Category

```bash
# Only unit tests (fast, isolated)
pytest -m "not integration and not requires_redis and not requires_api"

# Only integration tests
pytest -m "integration"

# Skip Redis-dependent tests
pytest -m "not requires_redis"
```

## Directory Structure

```
tests/
├── __init__.py              # Package marker
├── conftest.py              # Shared fixtures
├── integration_helpers.py   # Test utilities
├── README.md                # This file
├── test_*.py                # Test modules
└── ...
```

## Shared Fixtures

Available in all tests via `conftest.py`:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `api_base_url` | session | Jarvis API URL |
| `api_key` | session | API authentication key |
| `jarvis_test_client` | session | Pre-configured HTTP client |
| `sample_messages` | function | Sample message data |
| `sample_learned_fact` | function | Sample fact record |
| `mock_qdrant` | function | Mocked vector DB |
| `mock_redis` | function | Mocked cache |
| `tmp_test_dir` | function | Temp directory for files |

## Adding New Tests

1. Create `test_<module>.py` in `tests/`
2. Use fixtures from conftest.py
3. Add markers for slow/integration tests:

```python
import pytest

def test_fast_unit():
    """Fast unit test - no marker needed."""
    assert 1 + 1 == 2

@pytest.mark.slow
def test_large_dataset():
    """Slow test - marked for optional skip."""
    # Process large data...

@pytest.mark.integration
@pytest.mark.requires_api
def test_api_endpoint(jarvis_test_client):
    """Integration test requiring running API."""
    result = jarvis_test_client.get("/health")
    assert result["status"] == 200
```

## Coverage

Coverage is configured in `pyproject.toml`:

```bash
# Generate coverage report
pytest --cov=app --cov-report=term-missing

# HTML report
pytest --cov=app --cov-report=html
open htmlcov/index.html

# Fail if coverage < 60%
pytest --cov=app --cov-fail-under=60
```

## Troubleshooting

### Tests skipped with "Redis not available"
Redis connection failed. Either:
- Start Redis: `docker start jarvis-redis`
- Or skip these tests: `pytest -m "not requires_redis"`

### Import errors
Ensure you're in the ingestion directory:
```bash
cd /Volumes/BRAIN/system/ingestion
pytest
```

### Async test issues
Tests use `asyncio_mode = "auto"`. For manual async:
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_call()
    assert result is not None
```

### Local vs Container Testing

**Local (Mac):** Some tests fail because they need Docker services:
- PostgreSQL at `postgres:5432`
- Redis at `redis:6379`
- `/brain` volume mount

Run subset locally:
```bash
BRAIN_ROOT=/tmp/brain_test pytest tests/test_facette_detector.py -v
```

**In Container (full suite):**
```bash
ssh jarvis-nas
docker exec -it jarvis-ingestion pytest
```

## Known Skipped Tests

Some tests are skipped due to API evolution or missing modules:

| File | Reason |
|------|--------|
| `test_phase_5_5_integration.py` | DecayModeler/TrendAnalysis API changed |
| `test_tools_persistent_learn.py` | `app.persistent_learn` not implemented |
| `test_transparency_api.py` | `transparency_tool` module not implemented |
| `test_plugins.py` | `app.plugins` module not implemented |

These are tracked for future updates. Run `pytest --collect-only` to see all skips.
