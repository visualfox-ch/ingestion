"""
Prometheus Metrics for Remediation System

Phase 16.3: Automated Remediation Infrastructure
Provides observability for approval workflows, execution, and API performance.
"""

from prometheus_client import Counter, Histogram, Gauge
from datetime import datetime
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

# =============================================================================
# APPROVAL METRICS
# =============================================================================

APPROVAL_COUNTER = Counter(
    'remediation_approval_decisions_total',
    'Total remediation approval decisions',
    ['playbook_type', 'decision']  # decision: approved, rejected, expired, error
)

APPROVAL_LATENCY = Histogram(
    'remediation_approval_seconds',
    'Time from trigger to approval decision',
    ['playbook_type'],
    buckets=[60, 300, 900, 3600, 86400]  # 1min, 5min, 15min, 1hr, 1day
)

PENDING_APPROVALS_GAUGE = Gauge(
    'remediation_pending_approvals_count',
    'Current count of pending approvals',
    ['tier']
)

# =============================================================================
# EXECUTION METRICS
# =============================================================================

EXECUTION_COUNTER = Counter(
    'remediation_execution_total',
    'Remediation execution attempts',
    ['playbook_type', 'status']  # status: success, failed, skipped, rolled_back
)

EXECUTION_DURATION = Histogram(
    'remediation_execution_duration_seconds',
    'Remediation execution duration',
    ['playbook_type'],
    buckets=[1, 5, 30, 60, 300, 600]  # 1s, 5s, 30s, 1min, 5min, 10min
)

# =============================================================================
# API METRICS
# =============================================================================

API_RESPONSE_TIME = Histogram(
    'remediation_api_response_seconds',
    'API endpoint response time',
    ['endpoint', 'method', 'status'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

API_REQUEST_COUNTER = Counter(
    'remediation_api_requests_total',
    'Total API requests',
    ['endpoint', 'method', 'status_code']
)

# =============================================================================
# DATABASE METRICS
# =============================================================================

DATABASE_QUERY_TIME = Histogram(
    'remediation_database_query_seconds',
    'Database query execution time',
    ['query_type', 'table'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0]
)

DATABASE_QUERY_COUNTER = Counter(
    'remediation_database_queries_total',
    'Total database queries',
    ['query_type', 'status']  # status: success, timeout, error
)

# =============================================================================
# DECORATORS FOR TRACKING
# =============================================================================

def track_approval_metrics(playbook_type: str = "unknown"):
    """
    Decorator to track approval decision metrics.

    Usage:
        @track_approval_metrics('cache_invalidation')
        def approve_remediation(remediation_id, user_id, reason=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = datetime.now()
            try:
                result = func(*args, **kwargs)

                # Determine decision from result
                if isinstance(result, bool):
                    decision = 'approved' if result else 'rejected'
                elif isinstance(result, dict):
                    decision = 'approved' if result.get('approved') or result.get('status') == 'approved' else 'rejected'
                else:
                    decision = 'approved'

                APPROVAL_COUNTER.labels(
                    playbook_type=playbook_type,
                    decision=decision
                ).inc()

                latency = (datetime.now() - start).total_seconds()
                APPROVAL_LATENCY.labels(playbook_type=playbook_type).observe(latency)

                return result

            except Exception as e:
                APPROVAL_COUNTER.labels(
                    playbook_type=playbook_type,
                    decision='error'
                ).inc()
                logger.error(f"Approval tracking error for {playbook_type}: {e}")
                raise

        return wrapper
    return decorator


def track_execution_metrics(playbook_type: str = "unknown"):
    """
    Decorator to track remediation execution metrics.

    Usage:
        @track_execution_metrics('cache_invalidation')
        def execute_remediation(remediation_id):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = datetime.now()
            try:
                result = func(*args, **kwargs)

                duration = (datetime.now() - start).total_seconds()
                EXECUTION_DURATION.labels(playbook_type=playbook_type).observe(duration)

                # Determine status from result
                if isinstance(result, dict):
                    status = result.get('status', 'success')
                else:
                    status = 'success'

                EXECUTION_COUNTER.labels(
                    playbook_type=playbook_type,
                    status=status
                ).inc()

                return result

            except Exception as e:
                EXECUTION_COUNTER.labels(
                    playbook_type=playbook_type,
                    status='failed'
                ).inc()
                logger.error(f"Execution tracking error for {playbook_type}: {e}")
                raise

        return wrapper
    return decorator


def track_db_query(query_type: str, table: str = "unknown"):
    """
    Decorator to track database query metrics.

    Usage:
        @track_db_query('select', 'remediation_audit_log')
        def get_pending_approvals():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = datetime.now()
            try:
                result = func(*args, **kwargs)

                duration = (datetime.now() - start).total_seconds()
                DATABASE_QUERY_TIME.labels(
                    query_type=query_type,
                    table=table
                ).observe(duration)

                DATABASE_QUERY_COUNTER.labels(
                    query_type=query_type,
                    status='success'
                ).inc()

                return result

            except TimeoutError:
                DATABASE_QUERY_COUNTER.labels(
                    query_type=query_type,
                    status='timeout'
                ).inc()
                raise

            except Exception as e:
                DATABASE_QUERY_COUNTER.labels(
                    query_type=query_type,
                    status='error'
                ).inc()
                raise

        return wrapper
    return decorator


# =============================================================================
# GAUGE UPDATE FUNCTIONS
# =============================================================================

def update_pending_approvals_gauge(tier: int, count: int):
    """Update the pending approvals gauge for a specific tier."""
    PENDING_APPROVALS_GAUGE.labels(tier=str(tier)).set(count)


def update_all_pending_gauges(tier_counts: dict):
    """
    Update all pending approval gauges.

    Args:
        tier_counts: Dict mapping tier (int) to count (int)
                    e.g., {2: 3, 3: 1}
    """
    for tier, count in tier_counts.items():
        PENDING_APPROVALS_GAUGE.labels(tier=str(tier)).set(count)


# =============================================================================
# MANUAL METRIC RECORDING
# =============================================================================

def record_approval_decision(
    playbook_type: str,
    decision: str,
    latency_seconds: float = None
):
    """
    Manually record an approval decision.

    Args:
        playbook_type: Type of playbook (e.g., 'cache_invalidation')
        decision: One of 'approved', 'rejected', 'expired', 'error'
        latency_seconds: Optional time from trigger to decision
    """
    APPROVAL_COUNTER.labels(
        playbook_type=playbook_type,
        decision=decision
    ).inc()

    if latency_seconds is not None:
        APPROVAL_LATENCY.labels(playbook_type=playbook_type).observe(latency_seconds)


def record_api_request(
    endpoint: str,
    method: str,
    status_code: int,
    duration_seconds: float
):
    """
    Record an API request with timing.

    Args:
        endpoint: API endpoint path (e.g., '/remediate/pending')
        method: HTTP method (e.g., 'GET', 'POST')
        status_code: HTTP status code
        duration_seconds: Request duration
    """
    status = 'success' if 200 <= status_code < 400 else 'error'

    API_RESPONSE_TIME.labels(
        endpoint=endpoint,
        method=method,
        status=status
    ).observe(duration_seconds)

    API_REQUEST_COUNTER.labels(
        endpoint=endpoint,
        method=method,
        status_code=str(status_code)
    ).inc()


def record_db_query(
    query_type: str,
    table: str,
    duration_seconds: float,
    success: bool = True
):
    """
    Record a database query with timing.

    Args:
        query_type: Type of query (select, insert, update, delete)
        table: Table name
        duration_seconds: Query duration
        success: Whether query succeeded
    """
    DATABASE_QUERY_TIME.labels(
        query_type=query_type,
        table=table
    ).observe(duration_seconds)

    DATABASE_QUERY_COUNTER.labels(
        query_type=query_type,
        status='success' if success else 'error'
    ).inc()
