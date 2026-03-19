"""
Smoke test for the OpenSandbox-inspired python execution adapter.
"""

from __future__ import annotations

import json
import os
import tempfile

from .service import OpenSandboxService, SandboxLimits


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jarvis-opensandbox-") as tmp_dir:
        env_overrides = {
            "JARVIS_SANDBOX_RUNTIME_ENABLED": "true",
            "JARVIS_SANDBOX_RUNTIME_ALLOW_NETWORK": "false",
            "JARVIS_SANDBOX_RUNTIME_TIMEOUT_SECONDS": "5",
            "JARVIS_SANDBOX_RUNTIME_MAX_CODE_BYTES": "8000",
            "JARVIS_SANDBOX_RUNTIME_MAX_OUTPUT_BYTES": "8192",
            "JARVIS_SANDBOX_RUNTIME_SESSION_TTL_SECONDS": "60",
            "JARVIS_SANDBOX_RUNTIME_MAX_ARTIFACTS": "10",
            "JARVIS_SANDBOX_RUNTIME_MAX_SESSIONS": "2",
        }
        previous = {key: os.environ.get(key) for key in env_overrides}
        os.environ.update(env_overrides)

        try:
            service = OpenSandboxService(base_dir=tmp_dir)
            limits = SandboxLimits(
                enabled=True,
                allow_network=False,
                timeout_seconds=5,
                max_code_bytes=8000,
                max_output_bytes=8192,
                session_ttl_seconds=60,
                max_artifacts=10,
                max_sessions=2,
            )

            session = service.create_session(purpose="smoke_test", limits=limits)

            success = service.execute_python(
                session["session_id"],
                """
from pathlib import Path

Path("artifact.txt").write_text("sandbox-ok", encoding="utf-8")
print("hello from sandbox")
""".strip(),
            )
            if success["status"] != "ok":
                print(json.dumps({"status": "failed", "step": "success_exec", "result": success}, indent=2))
                return 1

            denied = service.execute_python(
                session["session_id"],
                """
import socket

socket.create_connection(("example.com", 80), timeout=1)
""".strip(),
            )
            if denied["status"] != "error" or "network disabled" not in denied["stderr"]:
                print(json.dumps({"status": "failed", "step": "network_deny", "result": denied}, indent=2))
                return 1

            escape = service.execute_python(
                session["session_id"],
                """
from pathlib import Path

Path("../escape.txt").write_text("nope", encoding="utf-8")
""".strip(),
            )
            if escape["status"] != "error" or "outside sandbox workspace" not in escape["stderr"]:
                print(json.dumps({"status": "failed", "step": "workspace_deny", "result": escape}, indent=2))
                return 1

            cleanup = service.cleanup_session(session["session_id"])
            payload = {
                "status": "ok",
                "health": service.get_health(),
                "success_exec": success,
                "network_deny": denied,
                "workspace_deny": escape,
                "cleanup": cleanup,
            }
            print(json.dumps(payload, indent=2))
            return 0
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
