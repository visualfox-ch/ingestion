"""
Redis-backed session and user memory storage.

Stores:
- Session state (30 days): emotional state, context, work patterns
- User profiles (90 days): preferences, long-term patterns
- Session snapshots (24h): Quick consciousness continuity

Phase 1: Memory Foundation (Feb 3, 2026)
- Added SessionSnapshot for structured session data
- Added facette tracking for personality evolution
"""
import json
import redis
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from functools import wraps
import time
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# SESSION SNAPSHOT (Phase 1: Memory Foundation)
# =============================================================================

@dataclass
class SessionSnapshot:
    """
    Structured session snapshot for consciousness continuity.

    Captures the essential state after each agent run to enable
    Jarvis to "remember" context across sessions.
    """
    # Identity
    user_id: str
    session_id: str
    namespace: str = "work_projektil"
    scope_org: str = "projektil"
    scope_visibility: str = "internal"

    # Timestamp
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Conversation state
    query_count: int = 0
    topics_discussed: List[str] = field(default_factory=list)

    # Emotional inference
    detected_mood: str = "neutral"  # calm, stressed, excited, neutral, focused
    energy_level: float = 0.5  # 0.0-1.0
    focus_score: float = 0.5  # 0.0-1.0

    # Context
    last_query: str = ""
    last_answer_preview: str = ""  # First 200 chars
    last_tools_used: List[str] = field(default_factory=list)

    # Facette usage (personality evolution)
    facette_weights: Dict[str, float] = field(default_factory=dict)
    dominant_facette: str = "analytical"
    facette_history: Dict[str, int] = field(default_factory=dict)  # facette -> usage count

    # Performance
    avg_latency_ms: float = 0.0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSnapshot":
        """Create from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

# Production settings: timeouts and fallback behavior
REDIS_OPERATION_TIMEOUT = 0.5  # 500ms max for any Redis operation
FALLBACK_ON_ERROR = True  # Return gracefully instead of crashing


def redis_operation(fallback_value=None):
    """
    Decorator for Redis operations with timeout + error handling.
    
    Production-ready pattern:
    - Timeout after REDIS_OPERATION_TIMEOUT seconds
    - Return fallback_value on error
    - Log errors for monitoring
    
    Args:
        fallback_value: Value to return on error/timeout
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start = time.time()
            try:
                # Check if Redis is available (simple connection test)
                self.redis.ping()
                
                # Execute operation with timeout awareness
                result = func(self, *args, **kwargs)
                
                # Warn if operation took too long
                elapsed = time.time() - start
                if elapsed > REDIS_OPERATION_TIMEOUT:
                    logger.warning(
                        f"Redis operation '{func.__name__}' exceeded timeout: {elapsed:.3f}s"
                    )
                
                return result
                
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error in {func.__name__}: {e}")
                return fallback_value
                
            except redis.TimeoutError as e:
                logger.error(f"Redis timeout in {func.__name__}: {e}")
                return fallback_value
                
            except Exception as e:
                logger.error(f"Redis error in {func.__name__}: {e}", exc_info=True)
                return fallback_value if FALLBACK_ON_ERROR else None
                
        return wrapper
    return decorator


class MemoryStore:
    """Persistent storage for session and user state."""
    
    def __init__(self, redis_client: redis.Redis):
        """
        Initialize memory store.
        
        Args:
            redis_client: Redis connection instance
        """
        self.redis = redis_client
        self.session_ttl = timedelta(days=30)
        self.user_ttl = timedelta(days=90)

    @staticmethod
    def _scope_from_namespace(namespace: str) -> tuple[str, str]:
        """Best-effort legacy namespace to scope mapping for dual-write state."""
        mapping = {
            "private": ("personal", "private"),
            "work_projektil": ("projektil", "internal"),
            "work_visualfox": ("visualfox", "internal"),
            "shared": ("personal", "shared"),
        }
        return mapping.get(namespace or "work_projektil", ("projektil", "internal"))
    
    @redis_operation(fallback_value=False)
    def save_session_state(
        self,
        session_id: str,
        user_id: str,
        namespace: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
        priming: Dict[str, Any],
        scope_org: Optional[str] = None,
        scope_visibility: Optional[str] = None,
    ) -> bool:
        """
        Save session state to Redis.
        
        Args:
            session_id: Unique session identifier
            user_id: User identifier (e.g., "micha")
            namespace: Work namespace (e.g., "work_projektil")
            state: Emotional/cognitive state dict
            context: Conversation context dict
            priming: Priming data for next session
            
        Returns:
            True if successful, False otherwise
        """
        key = f"session:{session_id}:state"
        resolved_scope_org, resolved_scope_visibility = self._scope_from_namespace(namespace)
        data = {
            "session_id": session_id,
            "user_id": user_id,
            "namespace": namespace,
            "scope_org": scope_org or resolved_scope_org,
            "scope_visibility": scope_visibility or resolved_scope_visibility,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "state": state,
            "context": context,
            "priming": priming
        }
        
        self.redis.setex(
            key,
            int(self.session_ttl.total_seconds()),
            json.dumps(data)
        )
        
        # Also update user's recent session list
        self._update_user_sessions(user_id, session_id)
        
        logger.info(f"Saved session state: {session_id} for user {user_id}")
        return True
    
    @redis_operation(fallback_value=None)
    def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session state from Redis.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session state dict or None if not found
        """
        key = f"session:{session_id}:state"
        data = self.redis.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    @redis_operation(fallback_value=[])
    def get_recent_sessions(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get user's recent session states for context.
        
        Args:
            user_id: User identifier
            limit: Max number of sessions to retrieve
            
        Returns:
            List of recent session state dicts
        """
        key = f"user:{user_id}:recent_sessions"
        session_ids = self.redis.lrange(key, 0, limit - 1)
        
        sessions = []
        for sid in session_ids:
            state = self.get_session_state(sid.decode())
            if state:
                sessions.append(state)
        
        return sessions
    
    def _update_user_sessions(self, user_id: str, session_id: str):
        """
        Add session to user's recent list (internal).
        
        Args:
            user_id: User identifier
            session_id: Session to add
        """
        key = f"user:{user_id}:recent_sessions"
        self.redis.lpush(key, session_id)
        self.redis.ltrim(key, 0, 49)  # Keep last 50 sessions
        self.redis.expire(key, int(self.user_ttl.total_seconds()))
    
    def save_user_profile(self, user_id: str, profile: Dict[str, Any]) -> bool:
        """
        Save user profile/preferences.
        
        Args:
            user_id: User identifier
            profile: Profile data dict
            
        Returns:
            True if successful, False otherwise
        """
        try:
            key = f"user:{user_id}:profile"
            profile["updated_at"] = datetime.utcnow().isoformat()
            
            self.redis.setex(
                key,
                int(self.user_ttl.total_seconds()),
                json.dumps(profile)
            )
            
            logger.info(f"Saved user profile: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save user profile: {e}", exc_info=True)
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve user profile.

        Args:
            user_id: User identifier

        Returns:
            Profile dict or None if not found
        """
        try:
            key = f"user:{user_id}:profile"
            data = self.redis.get(key)

            if data:
                return json.loads(data)
            return None

        except Exception as e:
            logger.error(f"Failed to get user profile: {e}", exc_info=True)
            return None

    # =========================================================================
    # SESSION SNAPSHOTS (Phase 1: Memory Foundation)
    # =========================================================================

    @redis_operation(fallback_value=False)
    def save_snapshot(self, snapshot: SessionSnapshot, ttl_hours: int = 24) -> bool:
        """
        Save session snapshot to Redis with TTL.

        Key pattern: jarvis:session:{user_id}:{session_id}

        Args:
            snapshot: SessionSnapshot instance
            ttl_hours: Time-to-live in hours (default 24)

        Returns:
            True if successful
        """
        key = f"jarvis:snapshot:{snapshot.user_id}:{snapshot.session_id}"
        ttl_seconds = ttl_hours * 3600

        self.redis.setex(
            key,
            ttl_seconds,
            json.dumps(snapshot.to_dict())
        )

        # Also add to user's snapshot list for history
        list_key = f"jarvis:snapshots:{snapshot.user_id}"
        self.redis.lpush(list_key, snapshot.session_id)
        self.redis.ltrim(list_key, 0, 99)  # Keep last 100 snapshots
        self.redis.expire(list_key, ttl_seconds * 7)  # 7 days for list

        # Update facette usage stats
        self._update_facette_stats(snapshot.user_id, snapshot.facette_weights)

        logger.info(f"Saved snapshot: {snapshot.session_id} for user {snapshot.user_id}")
        return True

    @redis_operation(fallback_value=None)
    def get_snapshot(self, user_id: str, session_id: str) -> Optional[SessionSnapshot]:
        """
        Retrieve a session snapshot.

        Args:
            user_id: User identifier
            session_id: Session identifier

        Returns:
            SessionSnapshot or None if not found
        """
        key = f"jarvis:snapshot:{user_id}:{session_id}"
        data = self.redis.get(key)

        if data:
            return SessionSnapshot.from_dict(json.loads(data))
        return None

    @redis_operation(fallback_value=None)
    def get_latest_snapshot(self, user_id: str) -> Optional[SessionSnapshot]:
        """
        Get the most recent snapshot for a user.

        Args:
            user_id: User identifier

        Returns:
            Most recent SessionSnapshot or None
        """
        list_key = f"jarvis:snapshots:{user_id}"
        session_ids = self.redis.lrange(list_key, 0, 0)

        if session_ids:
            session_id = session_ids[0]
            if isinstance(session_id, bytes):
                session_id = session_id.decode()
            return self.get_snapshot(user_id, session_id)
        return None

    @redis_operation(fallback_value=[])
    def get_user_snapshot_history(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[SessionSnapshot]:
        """
        Get recent session snapshots for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of snapshots to retrieve

        Returns:
            List of SessionSnapshots (most recent first)
        """
        list_key = f"jarvis:snapshots:{user_id}"
        session_ids = self.redis.lrange(list_key, 0, limit - 1)

        snapshots = []
        for sid in session_ids:
            if isinstance(sid, bytes):
                sid = sid.decode()
            snapshot = self.get_snapshot(user_id, sid)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    def _update_facette_stats(self, user_id: str, facette_weights: Dict[str, float]):
        """
        Update cumulative facette usage stats for a user.

        Tracks which facettes are used over time for personality evolution.

        Args:
            user_id: User identifier
            facette_weights: Current facette weights from snapshot
        """
        if not facette_weights:
            return

        try:
            key = f"jarvis:facette_stats:{user_id}"

            # Increment usage count for dominant facette
            dominant = max(facette_weights.items(), key=lambda x: x[1])[0] if facette_weights else None
            if dominant:
                self.redis.hincrby(key, f"count_{dominant}", 1)
                self.redis.hincrby(key, "total_sessions", 1)

            # Store latest weights
            self.redis.hset(key, "latest_weights", json.dumps(facette_weights))
            self.redis.expire(key, 30 * 24 * 3600)  # 30 days

        except Exception as e:
            logger.warning(f"Failed to update facette stats: {e}")

    @redis_operation(fallback_value={})
    def get_facette_stats(self, user_id: str) -> Dict[str, Any]:
        """
        Get cumulative facette usage stats for a user.

        Returns:
            Dict with usage counts and latest weights
        """
        key = f"jarvis:facette_stats:{user_id}"
        data = self.redis.hgetall(key)

        if not data:
            return {}

        result = {}
        for k, v in data.items():
            k_str = k.decode() if isinstance(k, bytes) else k
            v_str = v.decode() if isinstance(v, bytes) else v

            if k_str == "latest_weights":
                result[k_str] = json.loads(v_str)
            elif k_str.startswith("count_"):
                facette = k_str.replace("count_", "")
                if "facette_counts" not in result:
                    result["facette_counts"] = {}
                result["facette_counts"][facette] = int(v_str)
            else:
                result[k_str] = int(v_str) if v_str.isdigit() else v_str

        return result
