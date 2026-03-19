"""
OpenSandbox-inspired session service for narrow execution POCs.

This is deliberately a small adapter that can later be swapped with a real
sidecar/runtime backend without changing the API surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis.opensandbox")

_DEFAULT_BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
_DEFAULT_BASE_DIR = _DEFAULT_BRAIN_ROOT / "system" / "data" / "opensandbox"
_DEFAULT_OPERATOR_CONTROLS = [
    "sandbox_runtime_enabled",
    "sandbox_runtime_allow_network",
    "sandbox_runtime_timeout_seconds",
    "sandbox_runtime_max_code_bytes",
    "sandbox_runtime_max_output_bytes",
    "sandbox_runtime_session_ttl_seconds",
    "sandbox_runtime_max_artifacts",
    "sandbox_runtime_max_sessions",
]

_BOOTSTRAP_CODE = textwrap.dedent(
    """
    import builtins
    import os
    import pathlib
    import runpy
    import socket
    import sys

    WORKSPACE_ROOT = os.path.realpath(os.environ["JARVIS_SANDBOX_WORKSPACE"])
    ALLOW_NETWORK = os.environ.get("JARVIS_SANDBOX_ALLOW_NETWORK", "false").lower() in {"1", "true", "yes", "on"}

    def _resolve_target(path):
        if isinstance(path, pathlib.Path):
            path = str(path)
        candidate = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
        resolved = os.path.realpath(candidate)
        if resolved != WORKSPACE_ROOT and not resolved.startswith(WORKSPACE_ROOT + os.sep):
            raise PermissionError(f"path outside sandbox workspace: {path}")
        return resolved

    _real_open = builtins.open
    _real_os_open = os.open
    _real_remove = os.remove
    _real_unlink = os.unlink
    _real_mkdir = os.mkdir
    _real_rmdir = os.rmdir
    _real_rename = os.rename
    _real_replace = os.replace
    _real_makedirs = os.makedirs

    def guarded_open(path, *args, **kwargs):
        return _real_open(_resolve_target(path), *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        return _real_os_open(_resolve_target(path), flags, *args, **kwargs)

    def guarded_remove(path, *args, **kwargs):
        return _real_remove(_resolve_target(path), *args, **kwargs)

    def guarded_unlink(path, *args, **kwargs):
        return _real_unlink(_resolve_target(path), *args, **kwargs)

    def guarded_mkdir(path, *args, **kwargs):
        return _real_mkdir(_resolve_target(path), *args, **kwargs)

    def guarded_rmdir(path, *args, **kwargs):
        return _real_rmdir(_resolve_target(path), *args, **kwargs)

    def guarded_rename(src, dst, *args, **kwargs):
        return _real_rename(_resolve_target(src), _resolve_target(dst), *args, **kwargs)

    def guarded_replace(src, dst, *args, **kwargs):
        return _real_replace(_resolve_target(src), _resolve_target(dst), *args, **kwargs)

    def guarded_makedirs(name, mode=0o777, exist_ok=False):
        return _real_makedirs(_resolve_target(name), mode=mode, exist_ok=exist_ok)

    builtins.open = guarded_open
    os.open = guarded_os_open
    os.remove = guarded_remove
    os.unlink = guarded_unlink
    os.mkdir = guarded_mkdir
    os.rmdir = guarded_rmdir
    os.rename = guarded_rename
    os.replace = guarded_replace
    os.makedirs = guarded_makedirs
    pathlib.Path.open = lambda self, *args, **kwargs: guarded_open(str(self), *args, **kwargs)
    pathlib.Path.unlink = lambda self, *args, **kwargs: guarded_unlink(str(self), *args, **kwargs)
    pathlib.Path.mkdir = lambda self, mode=0o777, parents=False, exist_ok=False: (
        guarded_makedirs(str(self), mode=mode, exist_ok=exist_ok)
        if parents else guarded_mkdir(str(self), mode)
    )
    pathlib.Path.rename = lambda self, target: pathlib.Path(guarded_rename(str(self), target) or _resolve_target(target))
    pathlib.Path.replace = lambda self, target: pathlib.Path(guarded_replace(str(self), target) or _resolve_target(target))
    pathlib.Path.write_text = lambda self, data, *args, **kwargs: guarded_open(str(self), "w", *args, **kwargs).write(data)
    pathlib.Path.write_bytes = lambda self, data, *args, **kwargs: guarded_open(str(self), "wb", *args, **kwargs).write(data)

    if not ALLOW_NETWORK:
        def _network_blocked(*args, **kwargs):
            raise PermissionError("network disabled in sandbox session")

        socket.socket = _network_blocked
        socket.create_connection = _network_blocked
        socket.getaddrinfo = _network_blocked

    script_path = _resolve_target(sys.argv[1])
    sys.argv = [script_path, *sys.argv[2:]]
    runpy.run_path(script_path, run_name="__main__")
    """
).strip() + "\n"


class SandboxError(Exception):
    """Base sandbox exception."""


class SandboxPolicyError(SandboxError):
    """Raised when execution violates sandbox policy."""


class SandboxNotFoundError(SandboxError):
    """Raised when a sandbox session does not exist."""


class SandboxExecutionError(SandboxError):
    """Raised when a sandboxed command fails before execution starts."""


@dataclass(frozen=True)
class SandboxLimits:
    enabled: bool
    allow_network: bool
    timeout_seconds: int
    max_code_bytes: int
    max_output_bytes: int
    session_ttl_seconds: int
    max_artifacts: int
    max_sessions: int

    @classmethod
    def from_runtime_config(cls) -> "SandboxLimits":
        return cls(
            enabled=_get_runtime_bool("sandbox_runtime_enabled", "JARVIS_SANDBOX_RUNTIME_ENABLED", False),
            allow_network=_get_runtime_bool("sandbox_runtime_allow_network", "JARVIS_SANDBOX_RUNTIME_ALLOW_NETWORK", False),
            timeout_seconds=_get_runtime_int("sandbox_runtime_timeout_seconds", "JARVIS_SANDBOX_RUNTIME_TIMEOUT_SECONDS", 15),
            max_code_bytes=_get_runtime_int("sandbox_runtime_max_code_bytes", "JARVIS_SANDBOX_RUNTIME_MAX_CODE_BYTES", 20000),
            max_output_bytes=_get_runtime_int("sandbox_runtime_max_output_bytes", "JARVIS_SANDBOX_RUNTIME_MAX_OUTPUT_BYTES", 65536),
            session_ttl_seconds=_get_runtime_int("sandbox_runtime_session_ttl_seconds", "JARVIS_SANDBOX_RUNTIME_SESSION_TTL_SECONDS", 1800),
            max_artifacts=_get_runtime_int("sandbox_runtime_max_artifacts", "JARVIS_SANDBOX_RUNTIME_MAX_ARTIFACTS", 32),
            max_sessions=_get_runtime_int("sandbox_runtime_max_sessions", "JARVIS_SANDBOX_RUNTIME_MAX_SESSIONS", 4),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allow_network": self.allow_network,
            "timeout_seconds": self.timeout_seconds,
            "max_code_bytes": self.max_code_bytes,
            "max_output_bytes": self.max_output_bytes,
            "session_ttl_seconds": self.session_ttl_seconds,
            "max_artifacts": self.max_artifacts,
            "max_sessions": self.max_sessions,
        }


@dataclass
class SandboxSession:
    session_id: str
    purpose: str
    workspace_dir: Path
    created_at: datetime
    expires_at: datetime
    limits: SandboxLimits

    def to_dict(self) -> Dict[str, Any]:
        now = datetime.utcnow()
        return {
            "session_id": self.session_id,
            "purpose": self.purpose,
            "workspace_dir": str(self.workspace_dir),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "remaining_ttl_seconds": max(0, int((self.expires_at - now).total_seconds())),
            "limits": self.limits.to_dict(),
        }


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_live_config_value(key: str, default: Any) -> Any:
    try:
        from ..live_config import get_config

        return get_config(key, default)
    except Exception:
        return default


def _get_runtime_bool(config_key: str, env_key: str, default: bool) -> bool:
    if env_key in os.environ:
        return _coerce_bool(os.environ.get(env_key), default)
    return _coerce_bool(_get_live_config_value(config_key, default), default)


def _get_runtime_int(config_key: str, env_key: str, default: int) -> int:
    if env_key in os.environ:
        return _coerce_int(os.environ.get(env_key), default)
    return _coerce_int(_get_live_config_value(config_key, default), default)


class OpenSandboxService:
    """Minimal session-oriented execution sandbox."""

    def __init__(self, base_dir: Optional[str | Path] = None):
        self.base_dir = Path(base_dir or os.environ.get("JARVIS_SANDBOX_BASE_DIR", str(_DEFAULT_BASE_DIR)))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, SandboxSession] = {}
        self._lock = threading.Lock()

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired_locked()
            limits = SandboxLimits.from_runtime_config()
            return {
                "status": "ok",
                "enabled": limits.enabled,
                "base_dir": str(self.base_dir),
                "active_sessions": len(self._sessions),
                "limits": limits.to_dict(),
                "operator_controls": list(_DEFAULT_OPERATOR_CONTROLS),
                "recommended_topology": "sidecar_for_browser_and_code_interpreter",
                "current_backend": "local_python_exec_adapter",
            }

    def list_sessions(self) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired_locked()
            return {
                "sessions": [session.to_dict() for session in self._sessions.values()],
                "count": len(self._sessions),
            }

    def create_session(self, purpose: str = "python_exec", limits: Optional[SandboxLimits] = None) -> Dict[str, Any]:
        session_limits = limits or SandboxLimits.from_runtime_config()
        if not session_limits.enabled:
            raise SandboxPolicyError("Sandbox runtime is disabled by operator policy")
        session_id = uuid.uuid4().hex[:12]
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(seconds=session_limits.session_ttl_seconds)
        workspace_dir = self.base_dir / session_id / "workspace"

        with self._lock:
            self._cleanup_expired_locked()
            if len(self._sessions) >= session_limits.max_sessions:
                raise SandboxPolicyError(
                    f"Sandbox session quota reached ({session_limits.max_sessions})"
                )
            workspace_dir.mkdir(parents=True, exist_ok=True)
            (workspace_dir / ".keep").write_text("", encoding="utf-8")
            session = SandboxSession(
                session_id=session_id,
                purpose=purpose,
                workspace_dir=workspace_dir,
                created_at=created_at,
                expires_at=expires_at,
                limits=session_limits,
            )
            self._sessions[session_id] = session
        self._write_session_metadata(session)
        return session.to_dict()

    def execute_python(
        self,
        session_id: str,
        code: str,
        files: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired_locked()
            session = self._sessions.get(session_id)

        if session is None:
            raise SandboxNotFoundError(f"Unknown sandbox session: {session_id}")
        if not session.limits.enabled:
            raise SandboxPolicyError("Sandbox runtime is disabled by operator policy")

        encoded_code = code.encode("utf-8")
        if len(encoded_code) > session.limits.max_code_bytes:
            raise SandboxPolicyError(
                f"Code payload exceeds max_code_bytes ({session.limits.max_code_bytes})"
            )

        self._write_input_files(session, files or {})
        user_code_path = session.workspace_dir / "user_code.py"
        bootstrap_path = session.workspace_dir / "_sandbox_bootstrap.py"
        user_code_path.write_text(code, encoding="utf-8")
        bootstrap_path.write_text(_BOOTSTRAP_CODE, encoding="utf-8")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(session.workspace_dir),
            "TMPDIR": str(session.workspace_dir / "tmp"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "JARVIS_SANDBOX_WORKSPACE": str(session.workspace_dir.resolve()),
            "JARVIS_SANDBOX_ALLOW_NETWORK": "true" if session.limits.allow_network else "false",
        }
        (session.workspace_dir / "tmp").mkdir(exist_ok=True)

        started = time.time()
        try:
            completed = subprocess.run(
                [sys.executable, str(bootstrap_path.name), str(user_code_path.name)],
                cwd=session.workspace_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=session.limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxExecutionError(
                f"Sandbox execution exceeded timeout ({session.limits.timeout_seconds}s)"
            ) from exc

        duration_ms = round((time.time() - started) * 1000, 2)
        stdout, stdout_truncated = _truncate_text(completed.stdout, session.limits.max_output_bytes)
        stderr, stderr_truncated = _truncate_text(completed.stderr, session.limits.max_output_bytes)
        artifacts = self._list_artifacts(session, max_items=session.limits.max_artifacts)

        return {
            "status": "ok" if completed.returncode == 0 else "error",
            "session_id": session_id,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "duration_ms": duration_ms,
            "artifacts": artifacts,
            "limits": session.limits.to_dict(),
            "network_allowed": session.limits.allow_network,
        }

    def cleanup_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise SandboxNotFoundError(f"Unknown sandbox session: {session_id}")

        shutil.rmtree(session.workspace_dir.parent, ignore_errors=True)
        return {
            "success": True,
            "session_id": session_id,
            "removed_path": str(session.workspace_dir.parent),
        }

    def _cleanup_expired_locked(self) -> None:
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= datetime.utcnow()
        ]
        for session_id in expired_ids:
            session = self._sessions.pop(session_id)
            shutil.rmtree(session.workspace_dir.parent, ignore_errors=True)

    def _write_session_metadata(self, session: SandboxSession) -> None:
        metadata_path = session.workspace_dir.parent / "session.json"
        metadata_path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")

    def _write_input_files(self, session: SandboxSession, files: Dict[str, str]) -> None:
        for relative_path, content in files.items():
            target = _resolve_relative_workspace_path(session.workspace_dir, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _list_artifacts(self, session: SandboxSession, max_items: int) -> list[Dict[str, Any]]:
        artifacts = []
        ignored_names = {"user_code.py", "_sandbox_bootstrap.py", ".keep"}
        for path in sorted(session.workspace_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name in ignored_names:
                continue
            relpath = path.relative_to(session.workspace_dir).as_posix()
            artifacts.append(
                {
                    "path": relpath,
                    "size_bytes": path.stat().st_size,
                }
            )
            if len(artifacts) >= max_items:
                break
        return artifacts


def _resolve_relative_workspace_path(workspace_dir: Path, relative_path: str) -> Path:
    candidate = workspace_dir / relative_path
    resolved = candidate.resolve()
    workspace_root = workspace_dir.resolve()
    if resolved != workspace_root and not str(resolved).startswith(str(workspace_root) + os.sep):
        raise SandboxPolicyError(f"Path escapes sandbox workspace: {relative_path}")
    return resolved


def _truncate_text(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated, True


_sandbox_service: Optional[OpenSandboxService] = None


def get_sandbox_service() -> OpenSandboxService:
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = OpenSandboxService()
    return _sandbox_service
