"""
Live Configuration System - Phase B

Allows runtime configuration changes without code deployment.
Config values are persisted to SQLite and loaded at startup.
"""
from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import RLock

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.live_config")

# Database path
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
CONFIG_DB_PATH = BRAIN_ROOT / "system" / "state" / "jarvis_config.db"

# Thread safety
_config_lock = RLock()


@dataclass
class ConfigValue:
    """A configuration value with metadata."""
    key: str
    value: Any
    value_type: str  # str, int, float, bool, json
    category: str
    description: str
    default: Any
    updated_at: str
    updated_by: str


# Default configuration schema
CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    # Self-Diagnostics
    "self_diagnostics_enabled": {
        "default": True,
        "type": "bool",
        "category": "diagnostics",
        "description": "Enable scheduled self-diagnostics"
    },
    "self_diagnostics_interval_hours": {
        "default": 6,
        "type": "int",
        "category": "diagnostics",
        "description": "Hours between self-diagnostic runs"
    },

    # Proactive Features
    "proactive_hints_enabled": {
        "default": True,
        "type": "bool",
        "category": "proactive",
        "description": "Enable proactive hints to user"
    },
    "proactive_level": {
        "default": 2,
        "type": "int",
        "category": "proactive",
        "description": "Proactive behavior level (1-5)"
    },

    # Memory
    "memory_auto_persist": {
        "default": True,
        "type": "bool",
        "category": "memory",
        "description": "Auto-persist conversation context"
    },
    "memory_consolidation_enabled": {
        "default": True,
        "type": "bool",
        "category": "memory",
        "description": "Enable automatic memory consolidation"
    },
    "memory_max_session_messages": {
        "default": 100,
        "type": "int",
        "category": "memory",
        "description": "Max messages per session before archival"
    },

    # Tool Execution
    "tool_timeout_ms": {
        "default": 30000,
        "type": "int",
        "category": "tools",
        "description": "Default tool execution timeout in ms"
    },
    "tool_benchmark_enabled": {
        "default": True,
        "type": "bool",
        "category": "tools",
        "description": "Enable tool performance benchmarking"
    },

    # Self-Modification
    "self_modification_enabled": {
        "default": True,
        "type": "bool",
        "category": "self_mod",
        "description": "Allow Jarvis to write dynamic tools"
    },
    "self_modification_auto_promote": {
        "default": False,
        "type": "bool",
        "category": "self_mod",
        "description": "Auto-promote sandbox tools (skip human review)"
    },
    "sandbox_auto_test": {
        "default": True,
        "type": "bool",
        "category": "self_mod",
        "description": "Automatically test sandbox code"
    },
    "sandbox_runtime_enabled": {
        "default": False,
        "type": "bool",
        "category": "sandbox",
        "description": "Enable the OpenSandbox-inspired runtime session API"
    },
    "sandbox_runtime_allow_network": {
        "default": False,
        "type": "bool",
        "category": "sandbox",
        "description": "Allow outbound network access inside runtime sandbox sessions"
    },
    "sandbox_runtime_timeout_seconds": {
        "default": 15,
        "type": "int",
        "category": "sandbox",
        "description": "Timeout in seconds for runtime sandbox executions"
    },
    "sandbox_runtime_max_code_bytes": {
        "default": 20000,
        "type": "int",
        "category": "sandbox",
        "description": "Maximum code payload size for runtime sandbox executions"
    },
    "sandbox_runtime_max_output_bytes": {
        "default": 65536,
        "type": "int",
        "category": "sandbox",
        "description": "Maximum stdout or stderr bytes returned from sandbox executions"
    },
    "sandbox_runtime_session_ttl_seconds": {
        "default": 1800,
        "type": "int",
        "category": "sandbox",
        "description": "Session lifetime in seconds before runtime sandbox cleanup"
    },
    "sandbox_runtime_max_artifacts": {
        "default": 32,
        "type": "int",
        "category": "sandbox",
        "description": "Maximum artifact entries returned per runtime sandbox execution"
    },
    "sandbox_runtime_max_sessions": {
        "default": 4,
        "type": "int",
        "category": "sandbox",
        "description": "Maximum concurrent runtime sandbox sessions"
    },

    # Alerts
    "telegram_alerts_enabled": {
        "default": True,
        "type": "bool",
        "category": "alerts",
        "description": "Send alerts via Telegram"
    },
    "alert_on_critical_only": {
        "default": False,
        "type": "bool",
        "category": "alerts",
        "description": "Only alert on critical issues (not warnings)"
    },

    # Response Tuning
    "response_style": {
        "default": "concise",
        "type": "str",
        "category": "response",
        "description": "Response style: concise, detailed, casual"
    },
    "max_response_tokens": {
        "default": 2000,
        "type": "int",
        "category": "response",
        "description": "Maximum tokens in response"
    },

    # Agent Behavior (Phase 19)
    "agent_max_rounds": {
        "default": 8,
        "type": "int",
        "category": "agent",
        "description": "Max tool-calling rounds per query (higher = more complex tasks possible)"
    },
    "agent_timeout_seconds": {
        "default": 45,
        "type": "int",
        "category": "agent",
        "description": "Max seconds for agent to respond"
    },

    # LLM Settings (Phase 19.5) - Jarvis can change his own model!
    "llm_default_model": {
        "default": "claude-sonnet-4-6",
        "type": "str",
        "category": "llm",
        "description": "Default LLM model for complex queries"
    },
    "llm_fast_model": {
        "default": "claude-haiku-4-5",
        "type": "str",
        "category": "llm",
        "description": "Fast LLM model for simple queries"
    },
    "llm_preferred_provider": {
        "default": "anthropic",
        "type": "str",
        "category": "llm",
        "description": "Preferred LLM provider: anthropic, openai, ollama"
    },
    "llm_router_enabled": {
        "default": True,
        "type": "bool",
        "category": "llm",
        "description": "Enable smart model routing based on query complexity"
    },
    "agent_provider_agnostic_tool_loop_enabled": {
        "default": False,
        "type": "bool",
        "category": "llm",
        "description": "Enable the shared Anthropic/OpenAI tool loop path in the agent"
    },
    "llm_temperature": {
        "default": 0.7,
        "type": "float",
        "category": "llm",
        "description": "LLM temperature (0.0-1.0, lower = more deterministic)"
    },

    # Vector/Search Settings
    "vector_cache_enabled": {
        "default": True,
        "type": "bool",
        "category": "search",
        "description": "Enable vector embedding cache"
    },
    "search_hybrid_weight": {
        "default": 0.7,
        "type": "float",
        "category": "search",
        "description": "Weight for semantic vs keyword search (0.0-1.0)"
    },
    "search_max_results": {
        "default": 10,
        "type": "int",
        "category": "search",
        "description": "Max results from knowledge search"
    },

    # Learning Settings (Phase 19.5)
    "learning_auto_extract": {
        "default": True,
        "type": "bool",
        "category": "learning",
        "description": "Auto-extract learnings from sessions"
    },
    "learning_decay_days": {
        "default": 14,
        "type": "int",
        "category": "learning",
        "description": "Days before fact confidence decay starts"
    },
    "learning_migration_threshold": {
        "default": 0.8,
        "type": "float",
        "category": "learning",
        "description": "Min confidence to migrate facts to main store"
    },
}


class LiveConfig:
    """
    Live configuration manager.

    Usage:
        config = get_live_config()
        value = config.get("proactive_level")
        config.set("proactive_level", 3, updated_by="micha")
    """

    _instance: Optional['LiveConfig'] = None
    _config: Dict[str, ConfigValue] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._last_db_mtime_ns: int = 0
        self._init_db()
        self._load_from_db()

    def _get_db_mtime_ns(self) -> int:
        """Return the current SQLite mtime for cross-worker cache invalidation."""
        try:
            return CONFIG_DB_PATH.stat().st_mtime_ns
        except OSError:
            return 0

    def _refresh_from_db_if_needed(self) -> None:
        """
        Reload config if another worker updated the SQLite store.

        Each worker keeps an in-memory copy, so reads must detect external
        writes and refresh before returning stale values.
        """
        current_mtime_ns = self._get_db_mtime_ns()
        if current_mtime_ns and current_mtime_ns == self._last_db_mtime_ns:
            return
        self._load_from_db()

    def _init_db(self):
        """Initialize SQLite config database."""
        CONFIG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(CONFIG_DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                default_value TEXT,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _load_from_db(self):
        """Load config from database, using defaults for missing keys."""
        with _config_lock:
            # Start with defaults
            for key, schema in CONFIG_SCHEMA.items():
                self._config[key] = ConfigValue(
                    key=key,
                    value=schema["default"],
                    value_type=schema["type"],
                    category=schema["category"],
                    description=schema["description"],
                    default=schema["default"],
                    updated_at=datetime.utcnow().isoformat(),
                    updated_by="system_default"
                )

            # Override with DB values
            try:
                conn = sqlite3.connect(str(CONFIG_DB_PATH))
                cursor = conn.execute("SELECT * FROM config")
                for row in cursor.fetchall():
                    key = row[0]
                    if key in self._config:
                        value = self._deserialize_value(row[1], row[2])
                        self._config[key] = ConfigValue(
                            key=key,
                            value=value,
                            value_type=row[2],
                            category=row[3],
                            description=row[4] or "",
                            default=self._deserialize_value(row[5], row[2]) if row[5] else None,
                            updated_at=row[6],
                            updated_by=row[7]
                        )
                conn.close()
            except Exception as e:
                log_with_context(logger, "warning", "Failed to load config from DB", error=str(e))
            finally:
                self._last_db_mtime_ns = self._get_db_mtime_ns()

    def _serialize_value(self, value: Any, value_type: str) -> str:
        """Serialize value for storage."""
        if value_type == "json":
            return json.dumps(value)
        elif value_type == "bool":
            return "true" if value else "false"
        else:
            return str(value)

    def _deserialize_value(self, value_str: str, value_type: str) -> Any:
        """Deserialize value from storage."""
        if value_type == "int":
            return int(value_str)
        elif value_type == "float":
            return float(value_str)
        elif value_type == "bool":
            return value_str.lower() in ("true", "1", "yes", "on")
        elif value_type == "json":
            return json.loads(value_str)
        else:
            return value_str

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        self._refresh_from_db_if_needed()
        with _config_lock:
            if key in self._config:
                return self._config[key].value
            return default

    def get_full(self, key: str) -> Optional[ConfigValue]:
        """Get full config value with metadata."""
        self._refresh_from_db_if_needed()
        with _config_lock:
            return self._config.get(key)

    def set(self, key: str, value: Any, updated_by: str = "api") -> bool:
        """Set a config value."""
        if key not in CONFIG_SCHEMA:
            log_with_context(logger, "warning", "Unknown config key", key=key)
            return False

        schema = CONFIG_SCHEMA[key]
        value_type = schema["type"]

        # Type validation
        try:
            if value_type == "int":
                value = int(value)
            elif value_type == "float":
                value = float(value)
            elif value_type == "bool":
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
                else:
                    value = bool(value)
        except (ValueError, TypeError) as e:
            log_with_context(logger, "error", "Invalid config value type",
                           key=key, expected=value_type, error=str(e))
            return False

        with _config_lock:
            old_value = self._config[key].value if key in self._config else None

            # Update in-memory
            self._config[key] = ConfigValue(
                key=key,
                value=value,
                value_type=value_type,
                category=schema["category"],
                description=schema["description"],
                default=schema["default"],
                updated_at=datetime.utcnow().isoformat(),
                updated_by=updated_by
            )

            # Persist to DB
            try:
                conn = sqlite3.connect(str(CONFIG_DB_PATH))
                conn.execute("""
                    INSERT OR REPLACE INTO config
                    (key, value, value_type, category, description, default_value, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    key,
                    self._serialize_value(value, value_type),
                    value_type,
                    schema["category"],
                    schema["description"],
                    self._serialize_value(schema["default"], value_type),
                    datetime.utcnow().isoformat(),
                    updated_by
                ))

                # Record history
                conn.execute("""
                    INSERT INTO config_history (key, old_value, new_value, changed_at, changed_by)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    key,
                    self._serialize_value(old_value, value_type) if old_value is not None else None,
                    self._serialize_value(value, value_type),
                    datetime.utcnow().isoformat(),
                    updated_by
                ))

                conn.commit()
                conn.close()
                self._last_db_mtime_ns = self._get_db_mtime_ns()
            except Exception as e:
                log_with_context(logger, "error", "Failed to persist config", key=key, error=str(e))
                return False

        log_with_context(logger, "info", "Config updated",
                        key=key, old=old_value, new=value, by=updated_by)
        return True

    def get_all(self, category: str = None) -> Dict[str, Any]:
        """Get all config values, optionally filtered by category."""
        self._refresh_from_db_if_needed()
        with _config_lock:
            result = {}
            for key, cv in self._config.items():
                if category is None or cv.category == category:
                    result[key] = cv.value
            return result

    def get_all_full(self, category: str = None) -> Dict[str, Dict[str, Any]]:
        """Get all config values with metadata."""
        self._refresh_from_db_if_needed()
        with _config_lock:
            result = {}
            for key, cv in self._config.items():
                if category is None or cv.category == category:
                    result[key] = asdict(cv)
            return result

    def get_categories(self) -> List[str]:
        """Get list of config categories."""
        return list(set(s["category"] for s in CONFIG_SCHEMA.values()))

    def get_schema(self) -> Dict[str, Dict[str, Any]]:
        """Get the config schema."""
        return CONFIG_SCHEMA.copy()

    def reset_to_default(self, key: str, updated_by: str = "api") -> bool:
        """Reset a config value to its default."""
        if key not in CONFIG_SCHEMA:
            return False
        return self.set(key, CONFIG_SCHEMA[key]["default"], updated_by=updated_by)

    def reset_all(self, updated_by: str = "api") -> int:
        """Reset all config values to defaults."""
        count = 0
        for key in CONFIG_SCHEMA:
            if self.reset_to_default(key, updated_by):
                count += 1
        return count

    def get_history(self, key: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get config change history."""
        try:
            conn = sqlite3.connect(str(CONFIG_DB_PATH))
            if key:
                cursor = conn.execute(
                    "SELECT * FROM config_history WHERE key = ? ORDER BY id DESC LIMIT ?",
                    (key, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM config_history ORDER BY id DESC LIMIT ?",
                    (limit,)
                )

            history = []
            for row in cursor.fetchall():
                history.append({
                    "id": row[0],
                    "key": row[1],
                    "old_value": row[2],
                    "new_value": row[3],
                    "changed_at": row[4],
                    "changed_by": row[5]
                })
            conn.close()
            return history
        except Exception as e:
            log_with_context(logger, "error", "Failed to get config history", error=str(e))
            return []


# Singleton accessor
_live_config: Optional[LiveConfig] = None


def get_live_config() -> LiveConfig:
    """Get the singleton LiveConfig instance."""
    global _live_config
    if _live_config is None:
        _live_config = LiveConfig()
    return _live_config


# Convenience functions
def get_config(key: str, default: Any = None) -> Any:
    """Get a config value."""
    return get_live_config().get(key, default)


def set_config(key: str, value: Any, updated_by: str = "api") -> bool:
    """Set a config value."""
    return get_live_config().set(key, value, updated_by)
