"""
Database Safety Wrappers with Timeouts

Phase 16.3: Automated Remediation Infrastructure
Provides safe database access with query timeouts to prevent connection pool exhaustion.
"""

import psycopg2
from psycopg2 import errors as pg_errors
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional
import logging

from . import postgres_state
from .remediation_metrics import record_db_query

logger = logging.getLogger(__name__)

# =============================================================================
# TIMEOUT CONFIGURATION
# =============================================================================

# Default timeouts in seconds
DEFAULT_QUERY_TIMEOUT = 30      # General queries
LIST_QUERY_TIMEOUT = 10         # SELECT queries (should be fast)
WRITE_QUERY_TIMEOUT = 15        # INSERT/UPDATE queries
AGGREGATE_QUERY_TIMEOUT = 20    # GROUP BY, COUNT, etc.

# Warning threshold (log warning if query takes >80% of timeout)
WARNING_THRESHOLD = 0.8


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class DatabaseTimeoutError(Exception):
    """Raised when a database query exceeds its timeout."""
    def __init__(self, timeout: float, query_type: str = "unknown"):
        self.timeout = timeout
        self.query_type = query_type
        super().__init__(f"Database {query_type} query exceeded {timeout}s timeout")


class DatabaseConnectionError(Exception):
    """Raised when database connection fails."""
    pass


# =============================================================================
# SAFE CURSOR CONTEXT MANAGERS
# =============================================================================

@contextmanager
def safe_cursor(
    timeout: float = DEFAULT_QUERY_TIMEOUT,
    query_type: str = "generic",
    table: str = "unknown"
) -> Generator:
    """
    Get a database cursor with timeout and safety checks.

    Usage:
        with safe_cursor(timeout=10, query_type='select', table='remediation_audit_log') as cur:
            cur.execute("SELECT * FROM remediation_audit_log")
            results = cur.fetchall()

    Args:
        timeout: Query timeout in seconds (default: 30)
        query_type: Type of query for metrics (select, insert, update, delete)
        table: Table name for metrics

    Raises:
        DatabaseTimeoutError: If query exceeds timeout
        DatabaseConnectionError: If connection fails

    Note:
        This wraps postgres_state.get_cursor() and adds:
        - Query-level timeout via SET statement_timeout
        - Metrics recording
        - Warning logging for slow queries
    """
    start = datetime.now()
    cur = None

    try:
        # Use the existing get_cursor from postgres_state
        with postgres_state.get_cursor() as cur:
            # Set statement timeout in milliseconds
            timeout_ms = int(timeout * 1000)
            cur.execute(f"SET statement_timeout = {timeout_ms}")

            yield cur

            # Record success metrics
            duration = (datetime.now() - start).total_seconds()
            record_db_query(query_type, table, duration, success=True)

            # Log warning if query was slow (>80% of timeout)
            if duration > timeout * WARNING_THRESHOLD:
                logger.warning(
                    f"Slow query: {query_type} on {table} took {duration:.2f}s "
                    f"({int(duration/timeout*100)}% of {timeout}s timeout)"
                )

    except pg_errors.QueryCanceled:
        duration = (datetime.now() - start).total_seconds()
        logger.error(
            f"Query timeout after {timeout}s",
            extra={
                "query_type": query_type,
                "table": table,
                "actual_duration": duration,
                "timeout": timeout
            }
        )
        record_db_query(query_type, table, duration, success=False)
        raise DatabaseTimeoutError(timeout, query_type)

    except psycopg2.OperationalError as e:
        duration = (datetime.now() - start).total_seconds()
        logger.error(
            f"Database connection error: {e}",
            extra={"error": str(e), "query_type": query_type}
        )
        record_db_query(query_type, table, duration, success=False)
        raise DatabaseConnectionError(str(e))

    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        logger.error(
            f"Database error: {e}",
            extra={"query_type": query_type, "error": str(e)}
        )
        record_db_query(query_type, table, duration, success=False)
        raise


@contextmanager
def safe_list_query(table: str = "unknown", timeout: float = None) -> Generator:
    """
    Context manager optimized for SELECT queries.

    Uses faster timeout (10s) since list queries should be quick.

    Usage:
        with safe_list_query('remediation_audit_log') as cur:
            cur.execute("SELECT * FROM remediation_audit_log WHERE ...")
            return cur.fetchall()
    
    Args:
        table: Table name for metrics
        timeout: Optional custom timeout in seconds (default: 10s)
    """
    effective_timeout = timeout if timeout is not None else LIST_QUERY_TIMEOUT
    with safe_cursor(
        timeout=effective_timeout,
        query_type="select",
        table=table
    ) as cur:
        yield cur


@contextmanager
def safe_write_query(table: str = "unknown") -> Generator:
    """
    Context manager optimized for INSERT/UPDATE/DELETE queries.

    Uses moderate timeout (15s) for write operations.

    Usage:
        with safe_write_query('remediation_audit_log') as cur:
            cur.execute("UPDATE remediation_audit_log SET ...")
    """
    with safe_cursor(
        timeout=WRITE_QUERY_TIMEOUT,
        query_type="write",
        table=table
    ) as cur:
        yield cur


@contextmanager
def safe_aggregate_query(table: str = "unknown") -> Generator:
    """
    Context manager optimized for aggregate queries (COUNT, GROUP BY, etc.).

    Uses slightly longer timeout (20s) for aggregation operations.

    Usage:
        with safe_aggregate_query('remediation_audit_log') as cur:
            cur.execute("SELECT playbook, COUNT(*) FROM ... GROUP BY playbook")
            return cur.fetchall()
    """
    with safe_cursor(
        timeout=AGGREGATE_QUERY_TIMEOUT,
        query_type="aggregate",
        table=table
    ) as cur:
        yield cur


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def test_connection(timeout: float = 5.0) -> bool:
    """
    Test database connection with timeout.

    Returns:
        True if connection is healthy, False otherwise
    """
    try:
        with safe_cursor(timeout=timeout, query_type="health_check") as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def get_connection_stats() -> dict:
    """
    Get database connection pool statistics.

    Returns:
        Dict with pool status information
    """
    try:
        pool = postgres_state._pool
        if pool is None:
            return {"status": "not_initialized", "pool": None}

        return {
            "status": "active",
            "min_connections": pool.minconn,
            "max_connections": pool.maxconn,
            "closed": pool.closed
        }
    except Exception as e:
        logger.error(f"Failed to get connection stats: {e}")
        return {"status": "error", "error": str(e)}
