"""
Request/Response Service - Phase 22B-03

Synchronous request/response patterns for inter-agent queries:
- Blocking request with timeout
- Async request with callback
- Request correlation
- Response caching
- Circuit breaker for failing agents

Patterns:
1. Sync Request: Agent A blocks until Agent B responds
2. Async Request: Agent A continues, polls or gets callback
3. Scatter-Gather: Request to multiple agents, aggregate responses
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import json
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.request_response")


class RequestState(str, Enum):
    """State of a request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class AgentRequest:
    """A request to an agent."""
    request_id: str
    from_agent: str
    to_agent: str
    method: str
    params: Dict[str, Any]
    timeout_ms: int
    state: RequestState
    created_at: datetime
    correlation_id: Optional[str] = None


@dataclass
class AgentResponse:
    """Response from an agent."""
    request_id: str
    from_agent: str
    success: bool
    result: Any
    error: Optional[str]
    execution_time_ms: int


@dataclass
class CircuitBreaker:
    """Circuit breaker for an agent."""
    agent_name: str
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_at: Optional[datetime]
    last_success_at: Optional[datetime]
    threshold: int = 5
    reset_timeout_seconds: int = 60


class RequestResponseService:
    """
    Synchronous request/response patterns for agents.

    Features:
    - Blocking requests with timeout
    - Request correlation and tracking
    - Response caching
    - Circuit breaker per agent
    - Scatter-gather pattern
    """

    def __init__(self):
        self._ensure_tables()
        self._handlers: Dict[str, Callable] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._response_cache: Dict[str, Any] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._executor = ThreadPoolExecutor(max_workers=10)

    def _ensure_tables(self):
        """Ensure request tracking tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_agent_requests (
                            id SERIAL PRIMARY KEY,
                            request_id VARCHAR(50) UNIQUE NOT NULL,
                            correlation_id VARCHAR(50),
                            from_agent VARCHAR(50) NOT NULL,
                            to_agent VARCHAR(50) NOT NULL,
                            method VARCHAR(100) NOT NULL,
                            params JSONB DEFAULT '{}',
                            timeout_ms INTEGER DEFAULT 30000,
                            state VARCHAR(20) DEFAULT 'pending',
                            result JSONB,
                            error TEXT,
                            execution_time_ms INTEGER,
                            created_at TIMESTAMP DEFAULT NOW(),
                            completed_at TIMESTAMP
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_circuit_breakers (
                            id SERIAL PRIMARY KEY,
                            agent_name VARCHAR(50) UNIQUE NOT NULL,
                            state VARCHAR(20) DEFAULT 'closed',
                            failure_count INTEGER DEFAULT 0,
                            success_count INTEGER DEFAULT 0,
                            threshold INTEGER DEFAULT 5,
                            reset_timeout_seconds INTEGER DEFAULT 60,
                            last_failure_at TIMESTAMP,
                            last_success_at TIMESTAMP,
                            last_state_change TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_requests_state
                        ON jarvis_agent_requests(state, created_at)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_requests_correlation
                        ON jarvis_agent_requests(correlation_id)
                        WHERE correlation_id IS NOT NULL
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation failed", error=str(e))

    def register_handler(self, agent_name: str, method: str, handler: Callable):
        """Register a handler for agent method calls."""
        key = f"{agent_name}:{method}"
        self._handlers[key] = handler
        log_with_context(logger, "info", "Handler registered", agent=agent_name, method=method)

    def request(
        self,
        from_agent: str,
        to_agent: str,
        method: str,
        params: Dict[str, Any] = None,
        timeout_ms: int = 30000,
        correlation_id: Optional[str] = None,
        use_cache: bool = False
    ) -> Dict[str, Any]:
        """
        Make a synchronous request to another agent.

        Blocks until response or timeout.

        Args:
            from_agent: Requesting agent
            to_agent: Target agent
            method: Method to call
            params: Method parameters
            timeout_ms: Timeout in milliseconds
            correlation_id: Optional correlation ID for tracking
            use_cache: Use cached response if available

        Returns:
            Dict with result or error
        """
        params = params or {}
        request_id = f"req_{uuid.uuid4().hex[:12]}"

        # Check circuit breaker
        if not self._check_circuit(to_agent):
            return {
                "success": False,
                "request_id": request_id,
                "error": f"Circuit breaker open for {to_agent}",
                "circuit_state": "open"
            }

        # Check cache
        if use_cache:
            cache_key = f"{to_agent}:{method}:{json.dumps(params, sort_keys=True)}"
            cached = self._get_cached(cache_key)
            if cached:
                return {
                    "success": True,
                    "request_id": request_id,
                    "result": cached,
                    "cached": True
                }

        # Record request
        self._record_request(request_id, from_agent, to_agent, method, params, timeout_ms, correlation_id)

        start_time = time.time()

        try:
            # Look for handler
            handler_key = f"{to_agent}:{method}"
            if handler_key in self._handlers:
                handler = self._handlers[handler_key]

                # Execute with timeout
                future = self._executor.submit(handler, **params)
                try:
                    result = future.result(timeout=timeout_ms / 1000)
                    execution_time = int((time.time() - start_time) * 1000)

                    # Record success
                    self._record_success(to_agent)
                    self._complete_request(request_id, result, None, execution_time)

                    # Cache result
                    if use_cache:
                        self._set_cached(cache_key, result)

                    return {
                        "success": True,
                        "request_id": request_id,
                        "result": result,
                        "execution_time_ms": execution_time
                    }

                except FuturesTimeout:
                    self._record_failure(to_agent, "timeout")
                    self._complete_request(request_id, None, "Timeout", timeout_ms)
                    return {
                        "success": False,
                        "request_id": request_id,
                        "error": "Request timeout",
                        "timeout_ms": timeout_ms
                    }

            else:
                # No handler - simulate response
                execution_time = int((time.time() - start_time) * 1000)
                result = {
                    "simulated": True,
                    "agent": to_agent,
                    "method": method,
                    "params": params
                }
                self._complete_request(request_id, result, None, execution_time)

                return {
                    "success": True,
                    "request_id": request_id,
                    "result": result,
                    "execution_time_ms": execution_time,
                    "note": "No handler registered, simulated response"
                }

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            self._record_failure(to_agent, str(e))
            self._complete_request(request_id, None, str(e), execution_time)

            return {
                "success": False,
                "request_id": request_id,
                "error": str(e),
                "execution_time_ms": execution_time
            }

    def scatter_gather(
        self,
        from_agent: str,
        to_agents: List[str],
        method: str,
        params: Dict[str, Any] = None,
        timeout_ms: int = 30000,
        require_all: bool = False
    ) -> Dict[str, Any]:
        """
        Send request to multiple agents and gather responses.

        Args:
            from_agent: Requesting agent
            to_agents: List of target agents
            method: Method to call on all
            params: Shared parameters
            timeout_ms: Timeout for all requests
            require_all: Fail if any agent fails

        Returns:
            Dict with results from all agents
        """
        correlation_id = f"scatter_{uuid.uuid4().hex[:8]}"
        params = params or {}
        start_time = time.time()

        results = {}
        errors = {}

        # Submit all requests in parallel
        futures = {}
        for agent in to_agents:
            future = self._executor.submit(
                self.request,
                from_agent=from_agent,
                to_agent=agent,
                method=method,
                params=params,
                timeout_ms=timeout_ms,
                correlation_id=correlation_id
            )
            futures[agent] = future

        # Gather results
        for agent, future in futures.items():
            try:
                result = future.result(timeout=timeout_ms / 1000)
                if result.get("success"):
                    results[agent] = result.get("result")
                else:
                    errors[agent] = result.get("error")
            except Exception as e:
                errors[agent] = str(e)

        total_time = int((time.time() - start_time) * 1000)

        if require_all and errors:
            return {
                "success": False,
                "correlation_id": correlation_id,
                "error": "Not all agents responded successfully",
                "results": results,
                "errors": errors,
                "total_time_ms": total_time
            }

        return {
            "success": True,
            "correlation_id": correlation_id,
            "results": results,
            "errors": errors if errors else None,
            "agents_succeeded": len(results),
            "agents_failed": len(errors),
            "total_time_ms": total_time
        }

    def _check_circuit(self, agent_name: str) -> bool:
        """Check if circuit breaker allows request."""
        if agent_name not in self._circuit_breakers:
            self._circuit_breakers[agent_name] = CircuitBreaker(
                agent_name=agent_name,
                state=CircuitState.CLOSED,
                failure_count=0,
                success_count=0,
                last_failure_at=None,
                last_success_at=None
            )

        cb = self._circuit_breakers[agent_name]

        if cb.state == CircuitState.CLOSED:
            return True

        if cb.state == CircuitState.OPEN:
            # Check if reset timeout passed
            if cb.last_failure_at:
                elapsed = (datetime.now() - cb.last_failure_at).total_seconds()
                if elapsed >= cb.reset_timeout_seconds:
                    cb.state = CircuitState.HALF_OPEN
                    return True
            return False

        # HALF_OPEN - allow one request to test
        return True

    def _record_success(self, agent_name: str):
        """Record successful request for circuit breaker."""
        if agent_name in self._circuit_breakers:
            cb = self._circuit_breakers[agent_name]
            cb.success_count += 1
            cb.last_success_at = datetime.now()

            if cb.state == CircuitState.HALF_OPEN:
                cb.state = CircuitState.CLOSED
                cb.failure_count = 0

    def _record_failure(self, agent_name: str, error: str):
        """Record failed request for circuit breaker."""
        if agent_name not in self._circuit_breakers:
            self._circuit_breakers[agent_name] = CircuitBreaker(
                agent_name=agent_name,
                state=CircuitState.CLOSED,
                failure_count=0,
                success_count=0,
                last_failure_at=None,
                last_success_at=None
            )

        cb = self._circuit_breakers[agent_name]
        cb.failure_count += 1
        cb.last_failure_at = datetime.now()

        if cb.state == CircuitState.HALF_OPEN:
            cb.state = CircuitState.OPEN
        elif cb.failure_count >= cb.threshold:
            cb.state = CircuitState.OPEN
            log_with_context(logger, "warning", "Circuit breaker opened",
                           agent=agent_name, failures=cb.failure_count)

    def _record_request(
        self,
        request_id: str,
        from_agent: str,
        to_agent: str,
        method: str,
        params: Dict[str, Any],
        timeout_ms: int,
        correlation_id: Optional[str]
    ):
        """Record request in database."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_agent_requests
                        (request_id, correlation_id, from_agent, to_agent, method, params, timeout_ms)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        request_id, correlation_id, from_agent, to_agent,
                        method, json.dumps(params), timeout_ms
                    ))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Request recording failed", error=str(e))

    def _complete_request(
        self,
        request_id: str,
        result: Any,
        error: Optional[str],
        execution_time_ms: int
    ):
        """Complete request record."""
        try:
            state = "completed" if error is None else "error"
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_agent_requests
                        SET state = %s,
                            result = %s,
                            error = %s,
                            execution_time_ms = %s,
                            completed_at = NOW()
                        WHERE request_id = %s
                    """, (
                        state,
                        json.dumps(result) if result else None,
                        error,
                        execution_time_ms,
                        request_id
                    ))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Request completion failed", error=str(e))

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached response."""
        if key in self._response_cache:
            cached = self._response_cache[key]
            if datetime.now() - cached["time"] < self._cache_ttl:
                return cached["value"]
            del self._response_cache[key]
        return None

    def _set_cached(self, key: str, value: Any):
        """Set cached response."""
        self._response_cache[key] = {
            "value": value,
            "time": datetime.now()
        }

    def get_circuit_status(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Get circuit breaker status."""
        if agent_name:
            if agent_name in self._circuit_breakers:
                cb = self._circuit_breakers[agent_name]
                return {
                    "success": True,
                    "agent": agent_name,
                    "state": cb.state.value,
                    "failure_count": cb.failure_count,
                    "success_count": cb.success_count,
                    "last_failure": cb.last_failure_at.isoformat() if cb.last_failure_at else None
                }
            return {"success": True, "agent": agent_name, "state": "closed", "note": "No breaker exists"}

        return {
            "success": True,
            "circuits": {
                name: {
                    "state": cb.state.value,
                    "failures": cb.failure_count,
                    "successes": cb.success_count
                }
                for name, cb in self._circuit_breakers.items()
            }
        }

    def get_request_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get request statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            to_agent,
                            state,
                            COUNT(*) as count,
                            AVG(execution_time_ms) as avg_time
                        FROM jarvis_agent_requests
                        WHERE created_at > NOW() - INTERVAL '%s hours'
                        GROUP BY to_agent, state
                    """, (hours,))

                    rows = cur.fetchall()

                    by_agent: Dict[str, Dict] = {}
                    for row in rows:
                        agent = row["to_agent"]
                        if agent not in by_agent:
                            by_agent[agent] = {"total": 0, "by_state": {}}
                        by_agent[agent]["by_state"][row["state"]] = {
                            "count": row["count"],
                            "avg_time_ms": round(row["avg_time"] or 0)
                        }
                        by_agent[agent]["total"] += row["count"]

                    return {
                        "success": True,
                        "period_hours": hours,
                        "by_agent": by_agent
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[RequestResponseService] = None


def get_request_response_service() -> RequestResponseService:
    """Get or create request/response service singleton."""
    global _service
    if _service is None:
        _service = RequestResponseService()
    return _service
