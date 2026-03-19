"""
Tests for app/jobs/alias_sunset_job.py

Covers:
- init_monitoring creates state file on first call, is idempotent on repeat
- init_monitoring restores _sunsetted flag from a previously-written state file
- record_alias_call increments total_calls and updates last_called_at
- run_alias_sunset_check: no sunset when still within grace period
- run_alias_sunset_check: sunsets and sets flag when idle >= SUNSET_DAYS
- run_alias_sunset_check: skips gracefully when state file is missing
- run_alias_sunset_check: no-op when already sunsetted
- is_sunsetted reflects module-level flag
"""
import json
import time
import importlib
from pathlib import Path


import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_module(tmp_state: Path):
    """Import a fresh copy of alias_sunset_job with the state file pointing at tmp_state."""
    import app.jobs.alias_sunset_job as mod
    # Reset module-level mutable state between tests
    mod._sunsetted = False
    mod._STATE_FILE = tmp_state
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_monitoring_creates_state_file(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    assert not state_file.exists()
    mod.init_monitoring()
    assert state_file.exists()

    state = json.loads(state_file.read_text())
    assert "first_monitored_at" in state
    assert state["last_called_at"] is None
    assert state["total_calls"] == 0
    assert state["sunsetted_at"] is None


def test_init_monitoring_is_idempotent(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    mod.init_monitoring()
    first_ts = json.loads(state_file.read_text())["first_monitored_at"]

    # Second call must not overwrite the timestamp
    time.sleep(0.01)
    mod.init_monitoring()
    second_ts = json.loads(state_file.read_text())["first_monitored_at"]

    assert first_ts == second_ts


def test_init_monitoring_restores_sunset_flag(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time() - 40 * 86400,
        "last_called_at": time.time() - 40 * 86400,
        "total_calls": 1,
        "sunsetted_at": time.time() - 1,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    mod.init_monitoring()
    assert mod._sunsetted is True


def test_record_alias_call_increments_and_timestamps(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time(),
        "last_called_at": None,
        "total_calls": 0,
        "sunsetted_at": None,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._STATE_FILE = state_file

    before = time.time()
    mod.record_alias_call()
    after = time.time()

    state = json.loads(state_file.read_text())
    assert state["total_calls"] == 1
    assert before <= state["last_called_at"] <= after

    mod.record_alias_call()
    state = json.loads(state_file.read_text())
    assert state["total_calls"] == 2


def test_run_alias_sunset_check_no_sunset_in_grace_period(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time() - 5 * 86400,  # only 5 days ago
        "last_called_at": time.time() - 5 * 86400,
        "total_calls": 3,
        "sunsetted_at": None,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    mod.run_alias_sunset_check()

    assert mod._sunsetted is False
    state = json.loads(state_file.read_text())
    assert state["sunsetted_at"] is None


def test_run_alias_sunset_check_sunsets_after_idle_period(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    # last call 31 days ago → should trigger sunset
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time() - 31 * 86400,
        "last_called_at": time.time() - 31 * 86400,
        "total_calls": 1,
        "sunsetted_at": None,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    mod.run_alias_sunset_check()

    assert mod._sunsetted is True
    state = json.loads(state_file.read_text())
    assert state["sunsetted_at"] is not None


def test_run_alias_sunset_check_sunsets_on_never_called(tmp_path):
    """Grace period counts from first_monitored_at when endpoint was never called."""
    state_file = tmp_path / ".alias_sunset_state.json"
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time() - 31 * 86400,
        "last_called_at": None,  # never called
        "total_calls": 0,
        "sunsetted_at": None,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = state_file

    mod.run_alias_sunset_check()

    assert mod._sunsetted is True


def test_run_alias_sunset_check_skips_when_no_state_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = False
    mod._STATE_FILE = missing

    mod.run_alias_sunset_check()  # must not raise

    assert mod._sunsetted is False


def test_run_alias_sunset_check_noop_when_already_sunsetted(tmp_path):
    state_file = tmp_path / ".alias_sunset_state.json"
    # Write a state that WOULD trigger sunset, but _sunsetted is already True
    state_file.write_text(json.dumps({
        "first_monitored_at": time.time() - 60 * 86400,
        "last_called_at": time.time() - 60 * 86400,
        "total_calls": 0,
        "sunsetted_at": time.time() - 1,
    }))

    import app.jobs.alias_sunset_job as mod
    mod._sunsetted = True  # already sunsetted
    mod._STATE_FILE = state_file

    original_mtime = state_file.stat().st_mtime
    time.sleep(0.01)
    mod.run_alias_sunset_check()  # must return early, not re-write the file

    assert state_file.stat().st_mtime == pytest.approx(original_mtime, abs=0.01)


def test_is_sunsetted_reflects_module_flag(tmp_path):
    import app.jobs.alias_sunset_job as mod

    mod._sunsetted = False
    assert mod.is_sunsetted() is False

    mod._sunsetted = True
    assert mod.is_sunsetted() is True

    # Cleanup
    mod._sunsetted = False
