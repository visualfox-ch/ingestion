"""
Phase 0.4: Connection Pool Monitoring Metrics

Add Prometheus metrics for database connection pool health.
"""

from typing import Optional
import time

class ConnectionPoolMetrics:
    """Track connection pool health metrics."""
    
    def __init__(self, pool_name: str):
        self.pool_name = pool_name
        self.creation_time = time.time()
        self.total_acquired = 0
        self.total_released = 0
        self.max_wait_time = 0.0
        self.wait_times = []  # Last 100 wait times
        self.last_pool_size = 0
        self.last_in_use = 0
        self.last_available = 0
        
    def record_acquisition(self, wait_time: float):
        """Record a connection acquisition event."""
        self.total_acquired += 1
        if wait_time > self.max_wait_time:
            self.max_wait_time = wait_time
        
        self.wait_times.append(wait_time)
        if len(self.wait_times) > 100:
            self.wait_times.pop(0)
    
    def record_release(self):
        """Record a connection release event."""
        self.total_released += 1

    def record_pool_state(self, total: int, in_use: int, available: int):
        """Record the current pool size and usage."""
        self.last_pool_size = total
        self.last_in_use = in_use
        self.last_available = available
    
    def get_avg_wait_time(self) -> float:
        """Get average wait time in seconds."""
        if not self.wait_times:
            return 0.0
        return sum(self.wait_times) / len(self.wait_times)
    
    def get_p95_wait_time(self) -> float:
        """Get 95th percentile wait time."""
        if not self.wait_times:
            return 0.0
        sorted_times = sorted(self.wait_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[idx] if idx < len(sorted_times) else sorted_times[-1]
    
    def get_p99_wait_time(self) -> float:
        """Get 99th percentile wait time."""
        if not self.wait_times:
            return 0.0
        sorted_times = sorted(self.wait_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[idx] if idx < len(sorted_times) else sorted_times[-1]
    
    def as_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        return f"""
# HELP jarvis_db_pool_acquisitions_total Total connection acquisitions
# TYPE jarvis_db_pool_acquisitions_total counter
jarvis_db_pool_acquisitions_total{{pool="{self.pool_name}"}} {self.total_acquired}

# HELP jarvis_db_pool_releases_total Total connection releases
# TYPE jarvis_db_pool_releases_total counter
jarvis_db_pool_releases_total{{pool="{self.pool_name}"}} {self.total_released}

# HELP jarvis_db_pool_wait_time_avg_seconds Average wait time for connection acquisition
# TYPE jarvis_db_pool_wait_time_avg_seconds gauge
jarvis_db_pool_wait_time_avg_seconds{{pool="{self.pool_name}"}} {self.get_avg_wait_time()}

# HELP jarvis_db_pool_wait_time_p95_seconds 95th percentile wait time
# TYPE jarvis_db_pool_wait_time_p95_seconds gauge
jarvis_db_pool_wait_time_p95_seconds{{pool="{self.pool_name}"}} {self.get_p95_wait_time()}

# HELP jarvis_db_pool_wait_time_p99_seconds 99th percentile wait time
# TYPE jarvis_db_pool_wait_time_p99_seconds gauge
jarvis_db_pool_wait_time_p99_seconds{{pool="{self.pool_name}"}} {self.get_p99_wait_time()}

# HELP jarvis_db_pool_wait_time_max_seconds Maximum observed wait time
# TYPE jarvis_db_pool_wait_time_max_seconds gauge
jarvis_db_pool_wait_time_max_seconds{{pool="{self.pool_name}"}} {self.max_wait_time}

# HELP jarvis_db_pool_size_total Total connections in pool
# TYPE jarvis_db_pool_size_total gauge
jarvis_db_pool_size_total{{pool="{self.pool_name}"}} {self.last_pool_size}

# HELP jarvis_db_pool_in_use Connections currently checked out
# TYPE jarvis_db_pool_in_use gauge
jarvis_db_pool_in_use{{pool="{self.pool_name}"}} {self.last_in_use}

# HELP jarvis_db_pool_available Connections currently available
# TYPE jarvis_db_pool_available gauge
jarvis_db_pool_available{{pool="{self.pool_name}"}} {self.last_available}
"""

# Global instances
_postgres_state_metrics = ConnectionPoolMetrics("postgres_state")
_knowledge_db_metrics = ConnectionPoolMetrics("knowledge_db")

def get_pool_metrics(pool_name: str) -> ConnectionPoolMetrics:
    """Get metrics instance for pool."""
    if pool_name == "postgres_state":
        return _postgres_state_metrics
    elif pool_name == "knowledge_db":
        return _knowledge_db_metrics
    else:
        raise ValueError(f"Unknown pool: {pool_name}")

def export_all_pool_metrics() -> str:
    """Export all pool metrics in Prometheus format."""
    return (
        _postgres_state_metrics.as_prometheus_metrics() + 
        "\n" + 
        _knowledge_db_metrics.as_prometheus_metrics()
    )
