"""
Thread-safe global state wrapper for Jarvis services.

Centralizes all mutable global state (pool draining, active connections,
worker status, bot status, context data) behind lock-protected accessors.

Pattern: Singleton GlobalState instance with threading.RLock() for re-entrancy.
"""

import threading
from typing import Dict, Any


class GlobalState:
    """Thread-safe wrapper for mutable global state across Jarvis services."""
    
    def __init__(self):
        """Initialize GlobalState with reentrant lock for thread-safety."""
        self._lock = threading.RLock()
        
        # Pool management (main.py endpoint state)
        self._pool_draining = False
        self._active_connections = 0
        
        # Worker management (main.py background worker)
        self._worker_running = False
        self._worker_stats = {
            "started_at": None,
            "processed": 0,
            "failed": 0,
            "last_processed_at": None,
            "last_error": None
        }
        
        # Bot management (telegram_bot.py telegram polling)
        self._bot_running = False
        self._context_data = {}

        # Email draft rate limiting (main.py)
        self._draft_counts = {}
        self._draft_reset_date = ""
    
    # ===== POOL MANAGEMENT (Connection Draining) =====
    
    def get_pool_draining(self) -> bool:
        """Get pool draining status (True = new requests should fail fast)."""
        with self._lock:
            return self._pool_draining
    
    def set_pool_draining(self, value: bool) -> None:
        """Set pool draining status during graceful shutdown."""
        with self._lock:
            self._pool_draining = value
    
    # ===== POOL MANAGEMENT (Active Connection Count) =====
    
    def get_active_connections(self) -> int:
        """Get current count of active request handlers."""
        with self._lock:
            return self._active_connections
    
    def increment_active_connections(self) -> int:
        """Increment active connection count (called at request start)."""
        with self._lock:
            self._active_connections += 1
            return self._active_connections
    
    def decrement_active_connections(self) -> int:
        """Decrement active connection count (called at request end)."""
        with self._lock:
            self._active_connections = max(0, self._active_connections - 1)
            return self._active_connections
    
    # ===== WORKER MANAGEMENT (Running Flag) =====
    
    def get_worker_running(self) -> bool:
        """Get worker thread running status (True = keep processing)."""
        with self._lock:
            return self._worker_running
    
    def set_worker_running(self, value: bool) -> None:
        """Set worker thread running status (shutdown sets to False)."""
        with self._lock:
            self._worker_running = value
    
    # ===== WORKER MANAGEMENT (Stats Dict) =====
    
    def get_worker_stats(self) -> Dict[str, Any]:
        """Get worker stats (returns copy to prevent external mutation)."""
        with self._lock:
            return dict(self._worker_stats)
    
    def increment_worker_processed(self) -> None:
        """Increment processed item count by worker."""
        with self._lock:
            self._worker_stats["processed"] += 1
    
    def increment_worker_failed(self) -> None:
        """Increment failed item count by worker."""
        with self._lock:
            self._worker_stats["failed"] += 1
    
    def set_worker_stats(self, key: str, value: Any) -> None:
        """Set a specific worker stat (e.g., 'last_error', 'started_at')."""
        with self._lock:
            self._worker_stats[key] = value
    
    # ===== BOT MANAGEMENT (Running Flag) =====
    
    def get_bot_running(self) -> bool:
        """Get bot polling thread running status (True = keep polling)."""
        with self._lock:
            return self._bot_running
    
    def set_bot_running(self, value: bool) -> None:
        """Set bot polling thread running status (shutdown sets to False)."""
        with self._lock:
            self._bot_running = value
    
    # ===== BOT MANAGEMENT (Context Data Dict) =====
    
    def get_context_data(self) -> Dict[str, Any]:
        """Get current context data (returns copy to prevent external mutation)."""
        with self._lock:
            return dict(self._context_data)
    
    def set_context_data(self, key: str, value: Any) -> None:
        """Set a context data key-value pair (e.g., 'user_id', 'message_id')."""
        with self._lock:
            self._context_data[key] = value
    
    def clear_context_data(self) -> None:
        """Clear all context data (called on context timeout/reset)."""
        with self._lock:
            self._context_data.clear()

    # ===== EMAIL DRAFT RATE LIMITING =====

    def get_draft_state(self) -> Dict[str, Any]:
        """Return a copy of draft rate-limit state."""
        with self._lock:
            return {
                "counts": dict(self._draft_counts),
                "reset_date": self._draft_reset_date
            }

    def reset_draft_counts(self, reset_date: str) -> None:
        """Reset draft counters and update reset date."""
        with self._lock:
            self._draft_counts = {}
            self._draft_reset_date = reset_date

    def increment_draft_count(self, key: str = "total") -> int:
        """Increment draft counter and return new value."""
        with self._lock:
            self._draft_counts[key] = self._draft_counts.get(key, 0) + 1
            return self._draft_counts[key]


# Global singleton instance (imported by main.py and telegram_bot.py)
global_state = GlobalState()
