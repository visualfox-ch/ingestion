"""
Prometheus metrics and health endpoint for Jarvis Memory-Stack.
"""
from fastapi import APIRouter, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time

router = APIRouter()

# Prometheus metrics for memory operations
MEMORY_READS = Counter('jarvis_memory_reads_total', 'Total memory read operations')
MEMORY_WRITES = Counter('jarvis_memory_writes_total', 'Total memory write operations')
MEMORY_ERRORS = Counter('jarvis_memory_errors_total', 'Total memory operation errors')
MEMORY_LATENCY = Histogram('jarvis_memory_latency_seconds', 'Latency for memory operations')
MEMORY_HEALTH = Gauge('jarvis_memory_health', 'Health status of memory stack (1=healthy, 0=unhealthy)')

@router.get('/memory/metrics')
def memory_metrics():
    """Prometheus metrics endpoint for memory stack."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@router.get('/memory/health')
def memory_health():
    """Health check for memory stack (Redis + core logic)."""
    # Health logic: try Redis ping, set gauge accordingly
    from .. import config as cfg
    from ..memory import MemoryStore
    import redis
    try:
        redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
        redis_client.ping()
        MEMORY_HEALTH.set(1)
        return {"status": "healthy", "redis": True}
    except Exception as e:
        MEMORY_HEALTH.set(0)
        MEMORY_ERRORS.inc()
        return {"status": "unhealthy", "redis": False, "error": str(e)}

# Example usage in memory operations (to be added in core logic):
# with MEMORY_LATENCY.time():
#     ... memory operation ...
# MEMORY_READS.inc()
# MEMORY_WRITES.inc()
# MEMORY_ERRORS.inc() on error
