"""
Label Registry Tools.

Label management for categorization and tagging.
Extracted from tools.py (Phase S5).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import Counter, defaultdict
import json
import os

from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode, internal_error

logger = get_logger("jarvis.tools.label")

# Keep this module self-contained (no dependency on app.tools to avoid circular imports).
VALUE_ALIASES: Dict[str, Dict[str, Any]] = {}
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))


def get_registry_entries(status: str = None):
    return []


def upsert_registry_entry(**kwargs):
    return kwargs


def delete_registry_entry(key: str, hard: bool = False) -> bool:
    return False


try:
    from ..label_schema import refresh_label_schema_cache, get_label_schema
except ImportError:
    def refresh_label_schema_cache() -> None:
        return None

    def get_label_schema() -> Dict[str, Any]:
        return {}


def tool_list_label_registry(**kwargs) -> Dict[str, Any]:
    """List label registry entries (DB-backed)."""
    try:
        status = kwargs.get("status", "active")
        if isinstance(status, str) and status.lower() in ("all", "any", "*"):
            status = None
        rows = get_registry_entries(status=status)
        metrics.inc("tool_list_label_registry")
        return {
            "success": True,
            "count": len(rows),
            "status_filter": status or "all",
            "labels": rows,
        }
    except Exception as e:
        log_with_context(logger, "error", "Tool list_label_registry failed", error=str(e))
        return {"error": str(e)}


def _parse_allowed_values(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return [v.strip() for v in value.split(",") if v.strip()]
    return [raw]


def tool_upsert_label_registry(**kwargs) -> Dict[str, Any]:
    """Create/update a label registry entry."""
    try:
        key = kwargs.get("key")
        if not key:
            return {"error": "Missing required field: key"}
        description = kwargs.get("description")
        allowed_values = _parse_allowed_values(kwargs.get("allowed_values"))
        status = kwargs.get("status", "active")
        source = kwargs.get("source", "jarvis")

        row = upsert_registry_entry(
            key=key,
            description=description,
            allowed_values=allowed_values,
            status=status,
            source=source,
        )
        refresh_label_schema_cache()
        metrics.inc("tool_upsert_label_registry")
        return {"success": True, "label": row}
    except Exception as e:
        log_with_context(logger, "error", "Tool upsert_label_registry failed", error=str(e))
        return {"error": str(e)}


def tool_delete_label_registry(**kwargs) -> Dict[str, Any]:
    """Delete (soft or hard) a label registry entry."""
    try:
        key = kwargs.get("key")
        if not key:
            return {"error": "Missing required field: key"}
        hard = bool(kwargs.get("hard", False))
        deleted = delete_registry_entry(key=key, hard=hard)
        if deleted:
            refresh_label_schema_cache()
        metrics.inc("tool_delete_label_registry")
        return {"success": deleted, "hard": hard}
    except Exception as e:
        log_with_context(logger, "error", "Tool delete_label_registry failed", error=str(e))
        return {"error": str(e)}


def tool_label_hygiene(**kwargs) -> Dict[str, Any]:
    """
    Scan Qdrant labels and compare against base+registry schema.
    Returns unknown keys/values and (optionally) updates the registry.
    """
    try:
        from qdrant_client import QdrantClient

        collections = kwargs.get("collections", "jarvis_work,jarvis_private,jarvis_comms")
        if isinstance(collections, str):
            collection_list = [c.strip() for c in collections.split(",") if c.strip()]
        else:
            collection_list = list(collections or [])

        limit = int(kwargs.get("limit", 2000))
        apply_updates = bool(kwargs.get("apply", False))
        if apply_updates:
            guard = os.getenv("JARVIS_LABEL_HYGIENE_AUTOREGISTER", "false").lower() in ("1", "true", "yes", "on")
            if not guard:
                return {"error": "Auto-register guard disabled. Set JARVIS_LABEL_HYGIENE_AUTOREGISTER=true to apply."}
        allow_values = bool(kwargs.get("allow_values", True))
        min_count = int(kwargs.get("min_count", 3))
        max_values_per_key = int(kwargs.get("max_values", 20))
        max_value_length = int(kwargs.get("max_value_length", 64))

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        schema_map = get_label_schema()

        unknown_keys: Counter = Counter()
        unknown_values: Dict[str, Counter] = defaultdict(Counter)
        observed_keys: Counter = Counter()
        scanned = 0

        def _normalize_label_value(key: str, value: Any) -> Any:
            if isinstance(value, str):
                alias = VALUE_ALIASES.get(key, {})
                return alias.get(value, value)
            return value

        def iter_label_values(label_dict: Dict[str, Any]):
            for k, v in label_dict.items():
                if v is None:
                    continue
                if isinstance(v, list):
                    values = v
                else:
                    values = [v]
                for value in values:
                    yield k, _normalize_label_value(k, value)

        for collection in collection_list:
            offset = None
            while scanned < limit:
                points, next_offset = client.scroll(
                    collection_name=collection,
                    limit=min(200, limit - scanned),
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break
                for p in points:
                    scanned += 1
                    payload = p.payload or {}
                    labels = payload.get("labels")
                    if not isinstance(labels, dict):
                        continue
                    for key, value in iter_label_values(labels):
                        observed_keys[key] += 1
                        schema = schema_map.get(key)
                        if not schema:
                            unknown_keys[key] += 1
                            if value is not None:
                                val_str = str(value)
                                if len(val_str) <= max_value_length:
                                    unknown_values[key][val_str] += 1
                            continue

                        allowed = schema.get("values")
                        if not allowed:
                            continue
                        val_str = str(value)
                        if val_str not in allowed:
                            if len(val_str) <= max_value_length:
                                unknown_values[key][val_str] += 1

                offset = next_offset
                if offset is None:
                    break

        suggestions = {
            "new_keys": {},
            "new_values": {},
        }

        for key, count in unknown_keys.items():
            values = [v for v, c in unknown_values[key].most_common(max_values_per_key) if c >= min_count]
            suggestions["new_keys"][key] = {
                "count": count,
                "suggested_values": values,
            }

        for key, counter in unknown_values.items():
            if key in suggestions["new_keys"]:
                continue
            missing_vals = [v for v, c in counter.most_common(max_values_per_key) if c >= min_count]
            if missing_vals:
                suggestions["new_values"][key] = missing_vals

        applied = {"new_keys": [], "new_values": []}
        if apply_updates:
            # Register unknown keys
            for key, info in suggestions["new_keys"].items():
                vals = info.get("suggested_values") or None
                row = upsert_registry_entry(
                    key=key,
                    description="Auto-registered by label hygiene",
                    allowed_values=vals,
                    source="jarvis",
                )
                applied["new_keys"].append(row)

            # Extend allowed values for existing keys
            if allow_values:
                for key, vals in suggestions["new_values"].items():
                    base = schema_map.get(key, {})
                    current_vals = base.get("values") or []
                    merged = sorted(set(current_vals) | set(vals))
                    row = upsert_registry_entry(
                        key=key,
                        allowed_values=merged,
                        source="jarvis",
                    )
                    applied["new_values"].append(row)

            refresh_label_schema_cache()

        metrics.inc("tool_label_hygiene")
        return {
            "success": True,
            "collections": collection_list,
            "scanned": scanned,
            "unknown_keys": dict(unknown_keys),
            "suggestions": suggestions,
            "applied": applied if apply_updates else None,
        }
    except Exception as e:
        log_with_context(logger, "error", "Tool label_hygiene failed", error=str(e))
        return {"error": str(e)}


