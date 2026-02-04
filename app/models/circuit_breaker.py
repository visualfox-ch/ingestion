"""
Circuit Breaker: Fault tolerance pattern for LLM providers.

Implements the circuit breaker pattern to handle provider failures:
- CLOSED: Normal operation, requests pass through
- OPEN: Provider failing, requests blocked/redirected
- HALF_OPEN: Testing if provider recovered

Configuration (from T-005 spec):
- 3 failures in 5 minutes → open circuit
- 10 minute cooldown before retry
- Success in half-open → close circuit
"""
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from functools import wraps


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal, passing requests
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 3       # Failures before opening
    failure_window_seconds: int = 300  # 5 minutes
    cooldown_seconds: int = 600       # 10 minutes
    half_open_max_calls: int = 1      # Calls to test in half-open


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for provider failover.

    Usage:
        breaker = CircuitBreaker("anthropic")

        @breaker.protect
        def call_anthropic():
            ...

        # Or manually
        if breaker.is_available():
            try:
                result = call_provider()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
    """
    provider_id: str
    config: CircuitConfig = field(default_factory=CircuitConfig)

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED)
    _failures: int = field(default=0)
    _failure_timestamps: list = field(default_factory=list)
    _last_failure_time: Optional[float] = field(default=None)
    _open_time: Optional[float] = field(default=None)
    _half_open_calls: int = field(default=0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def state(self) -> CircuitState:
        """Get current state, checking for transitions."""
        with self._lock:
            return self._get_state_internal()

    def _get_state_internal(self) -> CircuitState:
        """Internal state check (must hold lock)."""
        now = time.time()

        if self._state == CircuitState.OPEN:
            # Check if cooldown period has passed
            if self._open_time and (now - self._open_time) >= self.config.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                return CircuitState.HALF_OPEN

        return self._state

    def is_available(self) -> bool:
        """Check if provider is available (circuit not open)."""
        return self.state != CircuitState.OPEN

    def record_failure(self) -> None:
        """Record a failure, potentially opening circuit."""
        with self._lock:
            now = time.time()

            # Add timestamp to failures
            self._failure_timestamps.append(now)

            # Clean old failures outside window
            window_start = now - self.config.failure_window_seconds
            self._failure_timestamps = [
                ts for ts in self._failure_timestamps
                if ts > window_start
            ]

            self._failures = len(self._failure_timestamps)
            self._last_failure_time = now

            # Check threshold
            if self._failures >= self.config.failure_threshold:
                self._open_circuit()

            # If in half-open and failed, re-open
            if self._state == CircuitState.HALF_OPEN:
                self._open_circuit()

    def _open_circuit(self) -> None:
        """Open the circuit (must hold lock)."""
        self._state = CircuitState.OPEN
        self._open_time = time.time()

    def record_success(self) -> None:
        """Record a success, potentially closing circuit."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.config.half_open_max_calls:
                    # Success in half-open, close circuit
                    self._close_circuit()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failures = 0
                self._failure_timestamps = []

    def _close_circuit(self) -> None:
        """Close the circuit (must hold lock)."""
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._failure_timestamps = []
        self._open_time = None
        self._half_open_calls = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._close_circuit()

    def protect(self, func: Callable) -> Callable:
        """
        Decorator to protect a function with this circuit breaker.

        Usage:
            @breaker.protect
            def call_provider():
                ...
        """
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not self.is_available():
                raise CircuitOpenError(
                    f"Circuit open for {self.provider_id}, "
                    f"retry after {self._remaining_cooldown()}s"
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        return wrapper

    def _remaining_cooldown(self) -> int:
        """Get remaining cooldown seconds."""
        if self._open_time is None:
            return 0
        elapsed = time.time() - self._open_time
        remaining = self.config.cooldown_seconds - elapsed
        return max(0, int(remaining))

    def get_status(self) -> dict:
        """Get current status for monitoring."""
        return {
            "provider": self.provider_id,
            "state": self.state.value,
            "failures": self._failures,
            "last_failure": self._last_failure_time,
            "remaining_cooldown": self._remaining_cooldown() if self._state == CircuitState.OPEN else 0
        }


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""
    pass


# Registry of circuit breakers by provider
_breakers: dict = {}
_breakers_lock = threading.Lock()


def get_breaker(provider_id: str, config: Optional[CircuitConfig] = None) -> CircuitBreaker:
    """Get or create circuit breaker for a provider."""
    with _breakers_lock:
        if provider_id not in _breakers:
            _breakers[provider_id] = CircuitBreaker(
                provider_id=provider_id,
                config=config or CircuitConfig()
            )
        return _breakers[provider_id]


def get_all_breaker_status() -> list:
    """Get status of all circuit breakers."""
    with _breakers_lock:
        return [b.get_status() for b in _breakers.values()]
