from pathlib import Path
import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.modules.setdefault("redis", types.SimpleNamespace(Redis=object))

from app.routers.sandbox_router import router as sandbox_router
from app.sandbox import service as sandbox_service_module
from app.sandbox.service import (
    OpenSandboxService,
    SandboxLimits,
    SandboxPolicyError,
)


def _limits(**overrides) -> SandboxLimits:
    values = {
        "enabled": True,
        "allow_network": False,
        "timeout_seconds": 5,
        "max_code_bytes": 8000,
        "max_output_bytes": 8192,
        "session_ttl_seconds": 60,
        "max_artifacts": 10,
        "max_sessions": 4,
    }
    values.update(overrides)
    return SandboxLimits(**values)


def test_open_sandbox_service_exec_and_cleanup(tmp_path: Path) -> None:
    service = OpenSandboxService(base_dir=tmp_path)
    session = service.create_session(purpose="unit_test", limits=_limits())

    result = service.execute_python(
        session["session_id"],
        """
from pathlib import Path

Path("artifact.txt").write_text("sandbox-ok", encoding="utf-8")
print("hello from sandbox")
""".strip(),
    )

    assert result["status"] == "ok"
    assert result["exit_code"] == 0
    assert "hello from sandbox" in result["stdout"]
    assert result["artifacts"] == [{"path": "artifact.txt", "size_bytes": 10}]

    cleanup = service.cleanup_session(session["session_id"])
    assert cleanup["success"] is True
    assert not (tmp_path / session["session_id"]).exists()


def test_open_sandbox_service_denies_network_and_workspace_escape(tmp_path: Path) -> None:
    service = OpenSandboxService(base_dir=tmp_path)
    session = service.create_session(purpose="policy_test", limits=_limits())

    network_result = service.execute_python(
        session["session_id"],
        """
import socket

socket.create_connection(("example.com", 80), timeout=1)
""".strip(),
    )
    assert network_result["status"] == "error"
    assert "network disabled" in network_result["stderr"]

    escape_result = service.execute_python(
        session["session_id"],
        """
from pathlib import Path

Path("../escape.txt").write_text("nope", encoding="utf-8")
""".strip(),
    )
    assert escape_result["status"] == "error"
    assert "outside sandbox workspace" in escape_result["stderr"]


def test_open_sandbox_service_enforces_session_quota(tmp_path: Path) -> None:
    service = OpenSandboxService(base_dir=tmp_path)
    limits = _limits(max_sessions=1)

    service.create_session(purpose="quota_one", limits=limits)

    try:
        service.create_session(purpose="quota_two", limits=limits)
    except SandboxPolicyError as exc:
        assert "quota reached" in str(exc)
    else:
        raise AssertionError("Expected SandboxPolicyError for session quota")


def test_sandbox_router_runtime_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_SANDBOX_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("JARVIS_SANDBOX_RUNTIME_ALLOW_NETWORK", "false")
    monkeypatch.setenv("JARVIS_SANDBOX_RUNTIME_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("JARVIS_SANDBOX_RUNTIME_MAX_SESSIONS", "2")
    monkeypatch.setattr(
        sandbox_service_module,
        "_sandbox_service",
        OpenSandboxService(base_dir=tmp_path),
    )

    app = FastAPI()
    app.include_router(sandbox_router)
    client = TestClient(app)

    health = client.get("/sandbox/runtime/health")
    assert health.status_code == 200
    assert health.json()["enabled"] is True

    created = client.post("/sandbox/runtime/sessions", json={"purpose": "router_test"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    executed = client.post(
        f"/sandbox/runtime/sessions/{session_id}/python",
        json={
            "code": "from pathlib import Path\nPath('out.txt').write_text('ok', encoding='utf-8')\nprint('router-ok')",
            "files": {"input.txt": "seed"},
        },
    )
    assert executed.status_code == 200
    payload = executed.json()
    assert payload["status"] == "ok"
    assert "router-ok" in payload["stdout"]
    assert any(item["path"] == "out.txt" for item in payload["artifacts"])

    listed = client.get("/sandbox/runtime/sessions")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    cleaned = client.delete(f"/sandbox/runtime/sessions/{session_id}")
    assert cleaned.status_code == 200
    assert cleaned.json()["success"] is True
