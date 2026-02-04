import json
import time
from datetime import datetime
from typing import Any, Optional

import redis

from .observability import get_logger
from . import config as cfg

logger = get_logger("jarvis.config_manager")


class DynamicConfig:
    """Manages runtime configuration from Redis (no redeploy needed)."""

    def __init__(self, redis_client: redis.Redis, cache_ttl_seconds: int = 60):
        self.redis = redis_client
        self.cache_ttl_seconds = cache_ttl_seconds
        self._local_cache = {}
        self._cache_timestamp = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value from Redis with local caching."""
        cache_key = f"jarvis:config:{key}"

        if cache_key in self._local_cache:
            age = time.time() - self._cache_timestamp.get(cache_key, 0)
            if age < self.cache_ttl_seconds:
                return self._local_cache[cache_key]

        value = self.redis.get(cache_key)
        if value is None:
            logger.debug(f"Config not found: {key}, using default: {default}")
            return default

        try:
            parsed = json.loads(value)
        except Exception:
            parsed = value.decode("utf-8") if isinstance(value, bytes) else value

        self._local_cache[cache_key] = parsed
        self._cache_timestamp[cache_key] = time.time()
        return parsed

    def set(self, key: str, value: Any, audit_user: Optional[str] = None) -> None:
        """Set config and audit the change."""
        cache_key = f"jarvis:config:{key}"
        old_value = self.get(key, "unset")

        if isinstance(value, (dict, list)):
            redis_value = json.dumps(value)
        else:
            redis_value = str(value)

        self.redis.set(cache_key, redis_value)

        if cache_key in self._local_cache:
            del self._local_cache[cache_key]

        if audit_user:
            audit_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "user": audit_user,
                "key": key,
                "old_value": str(old_value),
                "new_value": str(value),
                "change": f"{key}: {old_value} → {value}"
            }
            self.redis.lpush("jarvis:config:changes", json.dumps(audit_entry))

        logger.info(f"Config updated: {key} = {value} (user: {audit_user})")

    def get_all(self) -> dict:
        """Get all config values."""
        keys = self.redis.keys("jarvis:config:*")
        config = {}
        for key in keys:
            config_key = key.decode("utf-8").replace("jarvis:config:", "")
            config[config_key] = self.get(config_key)
        return config

    def get_audit_log(self, limit: int = 50) -> list:
        """Get recent config changes."""
        changes = self.redis.lrange("jarvis:config:changes", 0, limit - 1)
        return [json.loads(c.decode("utf-8")) for c in changes]


_config_manager = None


def get_config_manager() -> DynamicConfig:
    global _config_manager
    if _config_manager is None:
        redis_client = redis.Redis(
            host=cfg.REDIS_HOST,
            port=cfg.REDIS_PORT,
            db=cfg.REDIS_DB,
            decode_responses=False
        )
        cfg.init_default_configs(redis_client)
        _config_manager = DynamicConfig(redis_client)
    return _config_manager
