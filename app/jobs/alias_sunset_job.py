"""
Alias Auto-Sunset Job

Tracks usage of the legacy /n8n/calendar/events endpoint and auto-sunsets it
(returns 410 Gone) after JARVIS_ALIAS_SUNSET_DAYS days of zero usage.

No human decision required — the system checks weekly and acts on its own.
"""
import json
import os
import time
from pathlib import Path

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.alias_sunset")

SUNSET_DAYS = int(os.environ.get("JARVIS_ALIAS_SUNSET_DAYS", "30"))
_STATE_FILE = Path("/brain/system/data/.alias_sunset_state.json")

# Runtime flag — True means the alias route returns 410 Gone.
_sunsetted: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(_STATE_FILE)
    except Exception as exc:
        log_with_context(logger, "warning", "alias_sunset: could not write state", error=str(exc))


# ---------------------------------------------------------------------------
# Public API (called by route + scheduler + startup)
# ---------------------------------------------------------------------------

def init_monitoring() -> None:
    """Create state file on first startup if missing."""
    state = _load()
    if "first_monitored_at" not in state:
        state = {
            "first_monitored_at": time.time(),
            "last_called_at": None,
            "total_calls": 0,
            "sunsetted_at": None,
        }
        _save(state)
        log_with_context(logger, "info", "alias_sunset: monitoring started",
                         sunset_days=SUNSET_DAYS,
                         state_file=str(_STATE_FILE))
    else:
        # Re-apply sunset flag after container restart
        if state.get("sunsetted_at") is not None:
            global _sunsetted
            _sunsetted = True
            log_with_context(logger, "info", "alias_sunset: previously sunsetted, 410 active",
                             sunsetted_at=state["sunsetted_at"])


def record_alias_call() -> None:
    """Call from the alias route on every request to track last-used time."""
    state = _load()
    state["last_called_at"] = time.time()
    state["total_calls"] = state.get("total_calls", 0) + 1
    _save(state)


def is_sunsetted() -> bool:
    """True when the alias should return 410 Gone."""
    return _sunsetted


def run_alias_sunset_check() -> None:
    """
    Weekly job (Sunday 05:00): evaluate whether the alias is ready to sunset.

    Sunset condition: no call received for >= SUNSET_DAYS days.
    If the alias was never called, the grace period starts from first_monitored_at.
    """
    global _sunsetted

    if _sunsetted:
        return  # already done

    state = _load()
    if not state:
        log_with_context(logger, "warning", "alias_sunset: state file missing, skipping")
        return

    now = time.time()
    last_called_at = state.get("last_called_at")
    first_monitored_at = state.get("first_monitored_at", now)

    # Use last call time if available, else monitoring start
    reference = last_called_at if last_called_at is not None else first_monitored_at
    days_idle = (now - reference) / 86400

    if days_idle >= SUNSET_DAYS:
        _sunsetted = True
        state["sunsetted_at"] = now
        _save(state)
        log_with_context(
            logger, "warning",
            "alias_sunset: auto-sunsetted — /n8n/calendar/events now returns 410",
            days_idle=round(days_idle, 1),
            total_calls=state.get("total_calls", 0),
        )
    else:
        log_with_context(
            logger, "info",
            "alias_sunset: still in grace period",
            days_idle=round(days_idle, 1),
            days_remaining=round(SUNSET_DAYS - days_idle, 1),
            total_calls=state.get("total_calls", 0),
        )
