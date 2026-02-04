"""
Connector State Management
JSON-based state files for tracking connector sync status, cursors, and health.
Each connector has its own state file at /brain/system/state/connectors/{connector_id}.json
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
try:
    from filelock import FileLock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    FileLock = None

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.connector_state")

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
STATE_DIR = BRAIN_ROOT / "system" / "state" / "connectors"


@dataclass
class SyncRun:
    """Record of a single sync run"""
    started_at: str
    finished_at: Optional[str] = None
    status: str = "running"  # running, success, partial, error
    items_processed: int = 0
    items_skipped: int = 0
    items_errored: int = 0
    error_message: Optional[str] = None
    cursor_before: Optional[str] = None
    cursor_after: Optional[str] = None


@dataclass
class ConnectorState:
    """State for a single connector"""
    connector_id: str
    connector_type: str  # gmail, whatsapp, gchat, calendar
    namespace: str

    # Sync cursor/pagination
    last_sync_cursor: Optional[str] = None  # e.g., Gmail page token, last message ID
    last_sync_ts: Optional[str] = None

    # Health tracking
    enabled: bool = True
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    last_error_ts: Optional[str] = None

    # Metrics
    total_items_synced: int = 0
    total_errors: int = 0

    # Configuration overrides
    config: Dict[str, Any] = field(default_factory=dict)

    # Recent sync history (last 10 runs)
    sync_history: List[Dict] = field(default_factory=list)

    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _ensure_state_dir():
    """Ensure state directory exists"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _state_path(connector_id: str) -> Path:
    """Get path to connector state file"""
    return STATE_DIR / f"{connector_id}.json"


def _lock_path(connector_id: str) -> Path:
    """Get path to lock file"""
    return STATE_DIR / f".{connector_id}.lock"


def _now_iso() -> str:
    """Current timestamp in ISO format"""
    return datetime.now().isoformat(timespec="seconds")


def load_state(connector_id: str) -> Optional[ConnectorState]:
    """Load connector state from file"""
    _ensure_state_dir()
    path = _state_path(connector_id)

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert sync_history dicts back if needed
        return ConnectorState(
            connector_id=data.get("connector_id", connector_id),
            connector_type=data.get("connector_type", "unknown"),
            namespace=data.get("namespace", "private"),
            last_sync_cursor=data.get("last_sync_cursor"),
            last_sync_ts=data.get("last_sync_ts"),
            enabled=data.get("enabled", True),
            consecutive_errors=data.get("consecutive_errors", 0),
            last_error=data.get("last_error"),
            last_error_ts=data.get("last_error_ts"),
            total_items_synced=data.get("total_items_synced", 0),
            total_errors=data.get("total_errors", 0),
            config=data.get("config", {}),
            sync_history=data.get("sync_history", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
    except (json.JSONDecodeError, KeyError) as e:
        log_with_context(logger, "error", "Failed to load connector state",
                        connector_id=connector_id, error=str(e))
        return None


def save_state(state: ConnectorState) -> bool:
    """Save connector state to file (with file locking if available)"""
    _ensure_state_dir()
    path = _state_path(state.connector_id)

    def _do_save():
        state.updated_at = _now_iso()
        if not state.created_at:
            state.created_at = state.updated_at

        # Keep only last 10 sync runs
        if len(state.sync_history) > 10:
            state.sync_history = state.sync_history[-10:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)

    try:
        if HAS_FILELOCK:
            lock = FileLock(str(_lock_path(state.connector_id)), timeout=10)
            with lock:
                _do_save()
        else:
            _do_save()

        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to save connector state",
                        connector_id=state.connector_id, error=str(e))
        return False


def get_or_create_state(
    connector_id: str,
    connector_type: str,
    namespace: str
) -> ConnectorState:
    """Get existing state or create new one"""
    state = load_state(connector_id)
    if state:
        return state

    state = ConnectorState(
        connector_id=connector_id,
        connector_type=connector_type,
        namespace=namespace,
        created_at=_now_iso(),
    )
    save_state(state)
    return state


def start_sync(connector_id: str, cursor: Optional[str] = None) -> SyncRun:
    """
    Start a new sync run.
    Returns a SyncRun object to track progress.
    """
    state = load_state(connector_id)
    if not state:
        log_with_context(logger, "warning", "Starting sync for unknown connector",
                        connector_id=connector_id)
        return SyncRun(started_at=_now_iso())

    run = SyncRun(
        started_at=_now_iso(),
        cursor_before=cursor or state.last_sync_cursor,
    )

    log_with_context(logger, "info", "Sync started",
                    connector_id=connector_id,
                    cursor=run.cursor_before)

    return run


def finish_sync(
    connector_id: str,
    run: SyncRun,
    status: str = "success",
    items_processed: int = 0,
    items_skipped: int = 0,
    items_errored: int = 0,
    new_cursor: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    """
    Finish a sync run and update connector state.
    """
    state = load_state(connector_id)
    if not state:
        log_with_context(logger, "error", "Cannot finish sync for unknown connector",
                        connector_id=connector_id)
        return False

    # Update run
    run.finished_at = _now_iso()
    run.status = status
    run.items_processed = items_processed
    run.items_skipped = items_skipped
    run.items_errored = items_errored
    run.cursor_after = new_cursor
    run.error_message = error_message

    # Update state
    state.last_sync_ts = run.finished_at
    if new_cursor:
        state.last_sync_cursor = new_cursor

    if status == "success":
        state.consecutive_errors = 0
        state.total_items_synced += items_processed
    elif status == "error":
        state.consecutive_errors += 1
        state.total_errors += 1
        state.last_error = error_message
        state.last_error_ts = run.finished_at
    elif status == "partial":
        # Partial success - some items processed, some errors
        state.total_items_synced += items_processed
        state.total_errors += items_errored
        if items_errored > items_processed:
            state.consecutive_errors += 1
        else:
            state.consecutive_errors = 0

    # Add to history
    state.sync_history.append(asdict(run))

    # Save
    success = save_state(state)

    log_with_context(logger, "info", "Sync finished",
                    connector_id=connector_id,
                    status=status,
                    items_processed=items_processed,
                    items_errored=items_errored)

    return success


def record_error(
    connector_id: str,
    error_message: str,
    increment_counter: bool = True
) -> bool:
    """Record an error without a full sync run"""
    state = load_state(connector_id)
    if not state:
        return False

    state.last_error = error_message
    state.last_error_ts = _now_iso()
    if increment_counter:
        state.consecutive_errors += 1
        state.total_errors += 1

    return save_state(state)


def reset_errors(connector_id: str) -> bool:
    """Reset error counters (e.g., after manual fix)"""
    state = load_state(connector_id)
    if not state:
        return False

    state.consecutive_errors = 0
    state.last_error = None
    state.last_error_ts = None

    return save_state(state)


def set_enabled(connector_id: str, enabled: bool) -> bool:
    """Enable or disable a connector"""
    state = load_state(connector_id)
    if not state:
        return False

    state.enabled = enabled
    log_with_context(logger, "info", f"Connector {'enabled' if enabled else 'disabled'}",
                    connector_id=connector_id)

    return save_state(state)


def update_config(connector_id: str, config_updates: Dict[str, Any]) -> bool:
    """Update connector configuration"""
    state = load_state(connector_id)
    if not state:
        return False

    state.config.update(config_updates)
    return save_state(state)


def list_connectors() -> List[Dict[str, Any]]:
    """List all connector states with summary info"""
    _ensure_state_dir()

    connectors = []
    for path in STATE_DIR.glob("*.json"):
        if path.name.startswith("."):
            continue

        state = load_state(path.stem)
        if state:
            connectors.append({
                "connector_id": state.connector_id,
                "connector_type": state.connector_type,
                "namespace": state.namespace,
                "enabled": state.enabled,
                "last_sync_ts": state.last_sync_ts,
                "consecutive_errors": state.consecutive_errors,
                "total_items_synced": state.total_items_synced,
                "health": _compute_health(state),
            })

    return connectors


def _compute_health(state: ConnectorState) -> str:
    """Compute health status from state"""
    if not state.enabled:
        return "disabled"

    if state.consecutive_errors >= 5:
        return "unhealthy"
    elif state.consecutive_errors >= 2:
        return "degraded"
    elif state.last_sync_ts is None:
        return "never_synced"
    else:
        return "healthy"


def get_connector_summary(connector_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed summary for a single connector"""
    state = load_state(connector_id)
    if not state:
        return None

    # Calculate success rate from history
    if state.sync_history:
        successes = sum(1 for r in state.sync_history if r.get("status") == "success")
        success_rate = successes / len(state.sync_history)
    else:
        success_rate = None

    return {
        "connector_id": state.connector_id,
        "connector_type": state.connector_type,
        "namespace": state.namespace,
        "enabled": state.enabled,
        "health": _compute_health(state),
        "last_sync_ts": state.last_sync_ts,
        "last_sync_cursor": state.last_sync_cursor,
        "consecutive_errors": state.consecutive_errors,
        "last_error": state.last_error,
        "last_error_ts": state.last_error_ts,
        "total_items_synced": state.total_items_synced,
        "total_errors": state.total_errors,
        "success_rate_recent": round(success_rate, 2) if success_rate is not None else None,
        "config": state.config,
        "recent_syncs": state.sync_history[-5:],  # Last 5 syncs
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }
