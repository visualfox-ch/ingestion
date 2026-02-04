"""
SSH Client for Jarvis - Execute commands on Synology NAS

This module provides SSH connectivity to execute commands directly on the NAS.
Uses paramiko for SSH connections with key-based authentication.
"""
import os
import paramiko
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.ssh")

# SSH Configuration
SSH_HOST = os.environ.get("SSH_HOST", "192.168.1.103")
SSH_PORT = int(os.environ.get("SSH_PORT", "22"))
SSH_USER = os.environ.get("SSH_USER", "jarvis")
SSH_KEY_PATH = os.environ.get("SSH_KEY_PATH", "/brain/system/keys/jarvis_nas_key")
SSH_TIMEOUT = int(os.environ.get("SSH_TIMEOUT", "30"))

# Safety restrictions
ALLOWED_COMMANDS = {
    "status": ["docker", "ps", "df", "free", "uptime", "systemctl"],
    "logs": ["docker logs", "tail", "head", "grep", "journalctl"],
    "file_ops": ["ls", "cat", "find", "stat", "du"],
    "process": ["ps", "top", "htop"],
    "network": ["netstat", "ss", "ping", "curl"],
}

BLOCKED_PATTERNS = [
    "rm -rf", "mkfs", "dd if=", "format", "> /dev/",
    "passwd", "usermod", "chmod -R 777", "chown -R",
    "iptables -F", "shutdown", "reboot", "halt",
    "/etc/shadow", "/etc/passwd", "ssh-keygen",
    # Note: sudo is NOT blocked as it's needed for Docker commands
]


class SSHClient:
    """Manages SSH connections to the NAS."""

    def __init__(self):
        self.client = None
        self.connected = False

    def connect(self) -> bool:
        """Establish SSH connection to NAS."""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Load private key
            if os.path.exists(SSH_KEY_PATH):
                key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
                self.client.connect(
                    hostname=SSH_HOST,
                    port=SSH_PORT,
                    username=SSH_USER,
                    pkey=key,
                    timeout=SSH_TIMEOUT
                )
            else:
                # Fallback to password auth if configured
                password = os.environ.get("SSH_PASSWORD")
                if not password:
                    log_with_context(logger, "error", "No SSH key or password available")
                    return False

                self.client.connect(
                    hostname=SSH_HOST,
                    port=SSH_PORT,
                    username=SSH_USER,
                    password=password,
                    timeout=SSH_TIMEOUT
                )

            self.connected = True
            log_with_context(logger, "info", "SSH connection established",
                           host=SSH_HOST, user=SSH_USER)
            return True

        except Exception as e:
            log_with_context(logger, "error", "SSH connection failed",
                           host=SSH_HOST, error=str(e))
            self.connected = False
            return False

    def execute(self, command: str, sudo: bool = False) -> Dict[str, Any]:
        """
        Execute a command on the NAS.

        Args:
            command: Command to execute
            sudo: Whether to run with sudo (requires passwordless sudo)

        Returns:
            Dict with stdout, stderr, exit_code, and success status
        """
        if not self.connected:
            if not self.connect():
                return {
                    "success": False,
                    "error": "Failed to connect",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": -1
                }

        # Safety check
        if not self._is_safe_command(command):
            log_with_context(logger, "warning", "Blocked unsafe command",
                           command=command)
            return {
                "success": False,
                "error": "Command blocked by safety filter",
                "stdout": "",
                "stderr": "",
                "exit_code": -1
            }

        try:
            if sudo:
                command = f"sudo {command}"

            stdin, stdout, stderr = self.client.exec_command(command, timeout=SSH_TIMEOUT)

            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode('utf-8')
            stderr_data = stderr.read().decode('utf-8')

            log_with_context(logger, "info", "Command executed",
                           command=command[:50], exit_code=exit_code)

            return {
                "success": exit_code == 0,
                "stdout": stdout_data,
                "stderr": stderr_data,
                "exit_code": exit_code
            }

        except Exception as e:
            log_with_context(logger, "error", "Command execution failed",
                           command=command[:50], error=str(e))
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1
            }

    def execute_script(self, script_content: str, interpreter: str = "bash") -> Dict[str, Any]:
        """
        Execute a multi-line script on the NAS.

        Args:
            script_content: Script content to execute
            interpreter: Shell interpreter (bash, python3, etc.)

        Returns:
            Execution result
        """
        # Create temporary script file
        script_name = f"/tmp/jarvis_script_{os.getpid()}.sh"
        
        try:
            # Upload script
            sftp = self.client.open_sftp()
            with sftp.file(script_name, 'w') as f:
                f.write(script_content)
            sftp.chmod(script_name, 0o755)
            sftp.close()

            # Execute script
            result = self.execute(f"{interpreter} {script_name}")

            # Cleanup
            self.execute(f"rm -f {script_name}")

            return result

        except Exception as e:
            log_with_context(logger, "error", "Script execution failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1
            }

    def _is_safe_command(self, command: str) -> bool:
        """Check if command is safe to execute."""
        cmd_lower = command.lower()
        
        # Log the command being checked
        log_with_context(logger, "debug", "Checking command safety",
                       command=command, cmd_lower=cmd_lower)

        # Check for blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                log_with_context(logger, "warning", "Command blocked by pattern",
                               command=command, pattern=pattern)
                return False

        # Docker commands should be safe
        if cmd_lower.startswith("/usr/local/bin/docker"):
            log_with_context(logger, "info", "Docker command allowed", command=command)
            return True

        # For extra safety, could implement allowlist
        # return any(allowed in command for category in ALLOWED_COMMANDS.values() 
        #           for allowed in category)

        return True

    def close(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()
            self.connected = False
            log_with_context(logger, "info", "SSH connection closed")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Convenience functions

def execute_command(command: str, sudo: bool = False) -> Dict[str, Any]:
    """Execute a single command on the NAS."""
    with SSHClient() as ssh:
        return ssh.execute(command, sudo)


def test_ssh_connection() -> Dict[str, Any]:
    """Test SSH connection with simple command."""
    return execute_command("echo 'Test successful'")


def get_docker_status() -> Dict[str, Any]:
    """Get Docker container status from NAS."""
    # Need sudo for docker commands
    result = execute_command("/usr/local/bin/docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'", sudo=True)
    
    if result["success"]:
        return {
            "success": True,
            "containers": result["stdout"]
        }
    else:
        return result


def get_system_status() -> Dict[str, Any]:
    """Get system status information."""
    commands = {
        "uptime": "uptime",
        "disk_usage": "df -h | grep -E '^/dev|^/volume'",
        "memory": "free -h",
        "docker": "/usr/local/bin/docker ps --format '{{.Names}}: {{.Status}}'",
    }

    status = {}
    for key, cmd in commands.items():
        result = execute_command(cmd)
        status[key] = result["stdout"] if result["success"] else result["error"]

    return {
        "success": True,
        "status": status,
        "timestamp": datetime.now().isoformat()
    }


def restart_jarvis_service(service_name: str) -> Dict[str, Any]:
    """Restart a specific Jarvis Docker service."""
    if service_name not in ["ingestion", "qdrant", "postgres", "meilisearch", "n8n"]:
        return {
            "success": False,
            "error": f"Unknown service: {service_name}"
        }

    # Use full path to docker on Synology and cd to correct directory
    command = f"cd /volume1/BRAIN/system/docker && sudo /usr/local/bin/docker compose -p jarvis-core restart {service_name}"
    return execute_command(command)


def get_container_logs(container_name: str, lines: int = 50) -> Dict[str, Any]:
    """Get recent logs from a Docker container by name."""
    command = f"/usr/local/bin/docker logs {container_name} --tail {lines}"
    return execute_command(command)


def tail_service_logs(service_name: str, lines: int = 50) -> Dict[str, Any]:
    """Get recent logs from a Jarvis service (legacy wrapper)."""
    container_name = service_name if service_name.startswith("jarvis-") else f"jarvis-{service_name}"
    return get_container_logs(container_name, lines)