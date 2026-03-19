import json
import pytest

from app import n8n_client


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_calendar_read_fallback_to_cli_when_n8n_fails(monkeypatch):
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_PRIMARY", "n8n")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK", "cli")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FAILFAST", "false")

    def _n8n_fail(service, account="projektil", params=None, method="GET", body=None):
        return {"success": False, "error": "Timeout"}

    def _cli_ok(cmd, capture_output, text, timeout, env, shell):
        payload = {
            "items": [
                {
                    "id": "evt_1",
                    "summary": "Fallback Event",
                    "start": {"dateTime": "2026-03-19T09:00:00+01:00"},
                    "end": {"dateTime": "2026-03-19T10:00:00+01:00"},
                }
            ]
        }
        return _Proc(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(n8n_client, "_call_google_api", _n8n_fail)
    monkeypatch.setattr(n8n_client.subprocess, "run", _cli_ok)

    events = n8n_client.get_calendar_events(timeframe="today", account="visualfox")
    assert len(events) == 1
    assert events[0]["summary"] == "Fallback Event"
    assert events[0]["account"] == "visualfox"


def test_calendar_read_returns_empty_without_fallback_when_primary_fails(monkeypatch):
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_PRIMARY", "n8n")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK", "cli")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FAILFAST", "false")

    def _n8n_fail(service, account="projektil", params=None, method="GET", body=None):
        return {"success": False, "error": "Timeout"}

    monkeypatch.setattr(n8n_client, "_call_google_api", _n8n_fail)

    events = n8n_client.get_calendar_events(timeframe="today", account="visualfox")
    assert events == []


def test_calendar_read_can_use_cli_as_primary(monkeypatch):
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_PRIMARY", "cli")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK", "n8n")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK_ENABLED", "false")

    def _cli_ok(cmd, capture_output, text, timeout, env, shell):
        payload = {
            "items": [
                {
                    "id": "evt_cli_primary",
                    "summary": "CLI Primary Event",
                    "start": {"dateTime": "2026-03-19T13:00:00+01:00"},
                    "end": {"dateTime": "2026-03-19T14:00:00+01:00"},
                }
            ]
        }
        return _Proc(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(n8n_client.subprocess, "run", _cli_ok)

    events = n8n_client.get_calendar_events(timeframe="today", account="projektil")
    assert len(events) == 1
    assert events[0]["id"] == "evt_cli_primary"
    assert events[0]["account"] == "projektil"


def test_cli_provider_missing_binary_raises_config_error(monkeypatch):
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_PRIMARY", "cli")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("JARVIS_GOOGLE_WORKSPACE_CLI_COMMAND", "/does/not/exist/gws")

    def _cli_missing_binary(cmd, capture_output, text, timeout, env, shell):
        raise FileNotFoundError("No such file or directory")

    monkeypatch.setattr(n8n_client.subprocess, "run", _cli_missing_binary)

    with pytest.raises(n8n_client.CalendarProviderError) as exc_info:
        n8n_client._get_calendar_events_cli_provider(account="projektil", timeframe="today")

    err = exc_info.value
    assert err.error_type == "config"
    assert "CLI command not found" in err.message
    assert "/does/not/exist/gws" in err.message


def test_invalid_cli_timeout_env_uses_default_and_logs_warning(monkeypatch):
    monkeypatch.setenv("JARVIS_GOOGLE_WORKSPACE_CLI_TIMEOUT_SECONDS", "invalid")

    captured_logs = []

    def _capture_log(logger, level, message, **kwargs):
        captured_logs.append({
            "level": level,
            "message": message,
            "kwargs": kwargs,
        })

    monkeypatch.setattr(n8n_client, "log_with_context", _capture_log)

    settings = n8n_client._calendar_provider_settings()

    assert settings["cli_timeout_seconds"] == 20
    assert any(
        log["level"] == "warning"
        and log["message"] == "Invalid integer env value, using default"
        and log["kwargs"].get("env") == "JARVIS_GOOGLE_WORKSPACE_CLI_TIMEOUT_SECONDS"
        for log in captured_logs
    )


def test_invalid_provider_env_values_use_safe_defaults_and_log_warning(monkeypatch):
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_PRIMARY", "invalid_primary")
    monkeypatch.setenv("JARVIS_CALENDAR_PROVIDER_FALLBACK", "invalid_fallback")

    captured_logs = []

    def _capture_log(logger, level, message, **kwargs):
        captured_logs.append({
            "level": level,
            "message": message,
            "kwargs": kwargs,
        })

    monkeypatch.setattr(n8n_client, "log_with_context", _capture_log)

    settings = n8n_client._calendar_provider_settings()

    assert settings["primary"] == "n8n"
    assert settings["fallback"] == "cli"
    assert any(
        log["level"] == "warning"
        and log["message"] == "Invalid calendar primary provider, using default"
        for log in captured_logs
    )
    assert any(
        log["level"] == "warning"
        and log["message"] == "Invalid calendar fallback provider, using default"
        for log in captured_logs
    )
