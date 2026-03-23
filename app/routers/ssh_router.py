"""
SSH Router

Extracted from main.py - SSH Management API:
- Execute command
- Execute script
- Get system status
- Get Docker status
- Restart service
- Get service logs
"""

from fastapi import APIRouter, Depends
from typing import Any

from ..observability import get_logger
from ..rate_limit import rate_limit_dependency
from ..auth import auth_dependency

logger = get_logger("jarvis.ssh")
# SSH endpoints require authentication (critical security surface)
router = APIRouter(
    prefix="/ssh",
    tags=["ssh"],
    dependencies=[Depends(auth_dependency)]
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/execute")
def execute_ssh_command(
    command: str,
    sudo: bool = False,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute a command on the NAS via SSH."""
    from .. import ssh_client

    try:
        result = ssh_client.execute_command(command, sudo)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }


@router.post("/script")
def execute_ssh_script(
    script_content: str,
    interpreter: str = "bash",
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute a script on the NAS via SSH."""
    from .. import ssh_client

    try:
        with ssh_client.SSHClient() as ssh:
            result = ssh.execute_script(script_content, interpreter)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }


@router.get("/status")
def get_ssh_status(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get system status via SSH."""
    from .. import ssh_client

    try:
        return ssh_client.get_system_status()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/docker")
def get_docker_status_ssh(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get Docker container status via SSH."""
    from .. import ssh_client

    try:
        return ssh_client.get_docker_status()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/restart/{service_name}")
def restart_service_ssh(
    service_name: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Restart a Jarvis service via SSH."""
    from .. import ssh_client

    try:
        return ssh_client.restart_jarvis_service(service_name)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/logs/{service_name}")
def get_service_logs_ssh(
    service_name: str,
    lines: int = 50,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get service logs via SSH."""
    from .. import ssh_client

    try:
        return ssh_client.tail_service_logs(service_name, lines)
    except Exception as e:
        return {"success": False, "error": str(e)}
