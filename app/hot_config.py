"""
Hot Config - Runtime Configuration without Restart

Micha's 4 Ideas (Feb 3, 2026): Hot Config Reload
Allows changing performance thresholds and behavior settings at runtime
without requiring a Jarvis restart.

Uses existing feature_flags infrastructure with category="hot_config".
Values are stored as JSON in the description field.

Author: Claude Code
Created: 2026-02-03
"""
import json
import logging
from typing import Any, Dict, Optional
from datetime import datetime

from .observability import get_logger

logger = get_logger("jarvis.hot_config")

# =============================================================================
# HOT CONFIG DEFINITIONS
# =============================================================================

# Define which keys are hot-reloadable and their types/defaults
HOT_CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    "log_level": {
        "type": "str",
        "default": "INFO",
        "validator": lambda v: v in ("DEBUG", "INFO", "WARNING", "ERROR"),
        "description": "Logging level (DEBUG, INFO, WARNING, ERROR)"
    },
    "confidence_cap": {
        "type": "float",
        "default": 0.8,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Maximum confidence Jarvis can express (0.0-1.0)"
    },
    "confidence_threshold": {
        "type": "float",
        "default": 0.7,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Show confidence indicator below this threshold"
    },
    "proactive_level": {
        "type": "int",
        "default": 3,
        "validator": lambda v: 1 <= v <= 5,
        "description": "Proactivity dial (1=silent, 3=balanced, 5=proactive)"
    },
    "proactive_max_per_day": {
        "type": "int",
        "default": 5,
        "validator": lambda v: 0 <= v <= 50,
        "description": "Maximum proactive hints per day"
    },
    "agent_max_rounds": {
        "type": "int",
        "default": 5,
        "validator": lambda v: 1 <= v <= 20,
        "description": "Maximum agent tool loops"
    },
    "agent_timeout_seconds": {
        "type": "int",
        "default": 45,
        "validator": lambda v: 10 <= v <= 300,
        "description": "Agent request timeout in seconds"
    },
    "rate_limit_per_minute": {
        "type": "int",
        "default": 60,
        "validator": lambda v: 1 <= v <= 1000,
        "description": "API rate limit per minute"
    },
    "facette_weight_analytical": {
        "type": "float",
        "default": 0.4,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Default weight for analytical facette"
    },
    "facette_weight_empathic": {
        "type": "float",
        "default": 0.2,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Default weight for empathic facette"
    },
    "facette_weight_pragmatic": {
        "type": "float",
        "default": 0.3,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Default weight for pragmatic facette"
    },
    "facette_weight_creative": {
        "type": "float",
        "default": 0.1,
        "validator": lambda v: 0.0 <= v <= 1.0,
        "description": "Default weight for creative facette"
    },
}


# =============================================================================
# GETTER FUNCTIONS
# =============================================================================

def get_hot_config(key: str, default: Any = None) -> Any:
    """Get a hot-reloadable config value.

    Reads from feature_flags table with category='hot_config'.
    Falls back to default if not found or disabled.

    Args:
        key: Config key name
        default: Default value if not found

    Returns:
        The config value (type depends on key)
    """
    from . import feature_flags

    # Get schema default if no default provided
    if default is None and key in HOT_CONFIG_SCHEMA:
        default = HOT_CONFIG_SCHEMA[key]["default"]

    flag_name = f"hot_config_{key}"
    flag = feature_flags.get_flag(flag_name)

    if flag is None or not flag.get("enabled", False):
        return default

    # Value stored as JSON in description field
    try:
        raw_value = flag.get("description", "")
        if raw_value:
            return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Invalid JSON in hot_config {key}, using default")

    return default


def set_hot_config(
    key: str,
    value: Any,
    changed_by: str = "api",
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Set a hot-reloadable config value.

    Validates value against schema and stores in feature_flags.

    Args:
        key: Config key name
        value: New value
        changed_by: Who made the change (for audit)
        reason: Why the change was made (for audit)

    Returns:
        Dict with old_value, new_value, changed_at

    Raises:
        ValueError: If key is not hot-configurable or value is invalid
    """
    from . import feature_flags

    if key not in HOT_CONFIG_SCHEMA:
        raise ValueError(f"Key '{key}' is not hot-configurable. Valid keys: {list(HOT_CONFIG_SCHEMA.keys())}")

    schema = HOT_CONFIG_SCHEMA[key]

    # Type coercion
    type_name = schema["type"]
    try:
        if type_name == "int":
            typed_value = int(value)
        elif type_name == "float":
            typed_value = float(value)
        elif type_name == "str":
            typed_value = str(value)
        elif type_name == "bool":
            typed_value = bool(value)
        else:
            typed_value = value
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid type for '{key}': expected {type_name}, got {type(value).__name__}")

    # Validation
    validator = schema.get("validator")
    if validator and not validator(typed_value):
        raise ValueError(f"Invalid value for '{key}': {typed_value}")

    # Get old value
    old_value = get_hot_config(key)

    # Store in feature flags
    flag_name = f"hot_config_{key}"
    existing = feature_flags.get_flag(flag_name)

    json_value = json.dumps(typed_value)

    if existing:
        feature_flags.update_flag(
            flag_name=flag_name,
            enabled=True,
            description=json_value,
            changed_by=changed_by,
            change_reason=reason or f"Hot config update: {key}"
        )
    else:
        feature_flags.create_flag(
            flag_name=flag_name,
            description=json_value,
            category="hot_config",
            enabled=True,
            changed_by=changed_by
        )

    logger.info(f"Hot config changed: {key} = {typed_value} (was: {old_value})")

    return {
        "key": key,
        "old_value": old_value,
        "new_value": typed_value,
        "changed_at": datetime.utcnow().isoformat(),
        "changed_by": changed_by
    }


def get_all_hot_config() -> Dict[str, Any]:
    """Get all hot config values as a dict.

    Returns:
        Dict mapping config keys to their current values
    """
    result = {}
    for key in HOT_CONFIG_SCHEMA:
        result[key] = get_hot_config(key)
    return result


def reload_hot_config() -> Dict[str, Any]:
    """Force reload all hot config from database.

    Clears the feature_flags cache to force immediate reload.

    Returns:
        Dict with all current values and reload timestamp
    """
    from . import feature_flags

    # Invalidate feature flag cache
    feature_flags._last_refresh = None

    return {
        "config": get_all_hot_config(),
        "reloaded_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# CONVENIENCE GETTERS (Type-Safe)
# =============================================================================

def get_log_level() -> str:
    """Get current log level."""
    return get_hot_config("log_level", "INFO")


def get_confidence_cap() -> float:
    """Get maximum confidence cap."""
    return get_hot_config("confidence_cap", 0.8)


def get_confidence_threshold() -> float:
    """Get confidence threshold for indicators."""
    return get_hot_config("confidence_threshold", 0.7)


def get_proactive_level() -> int:
    """Get proactivity dial level (1-5)."""
    return get_hot_config("proactive_level", 3)


def get_proactive_max_per_day() -> int:
    """Get max proactive hints per day."""
    return get_hot_config("proactive_max_per_day", 5)


def get_agent_max_rounds() -> int:
    """Get max agent tool loops."""
    return get_hot_config("agent_max_rounds", 5)


def get_agent_timeout_seconds() -> int:
    """Get agent timeout in seconds."""
    return get_hot_config("agent_timeout_seconds", 45)


def get_rate_limit_per_minute() -> int:
    """Get API rate limit per minute."""
    return get_hot_config("rate_limit_per_minute", 60)


def get_facette_weights() -> Dict[str, float]:
    """Get all facette weights as a dict."""
    return {
        "analytical": get_hot_config("facette_weight_analytical", 0.4),
        "empathic": get_hot_config("facette_weight_empathic", 0.2),
        "pragmatic": get_hot_config("facette_weight_pragmatic", 0.3),
        "creative": get_hot_config("facette_weight_creative", 0.1),
    }


# =============================================================================
# SCHEMA INFO
# =============================================================================

def get_hot_config_schema() -> Dict[str, Dict[str, Any]]:
    """Get the hot config schema for documentation/UI.

    Returns:
        Dict mapping keys to their schema (type, default, description)
    """
    return {
        key: {
            "type": schema["type"],
            "default": schema["default"],
            "description": schema["description"],
            "current": get_hot_config(key)
        }
        for key, schema in HOT_CONFIG_SCHEMA.items()
    }
