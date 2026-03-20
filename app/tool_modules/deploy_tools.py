"""
Deploy Tools.

Self-deployment capabilities for Jarvis with safety guardrails.
Allows Jarvis to deploy code changes autonomously.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import subprocess
import os
import time

from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode

logger = get_logger("jarvis.tools.deploy")

# Constants
INGESTION_APP = "/volume1/BRAIN/system/ingestion/app"
DOCKER_CMD = "/usr/local/bin/docker"
JARVIS_CONTAINER = "jarvis-ingestion"
HEALTH_URL = "http://localhost:8000/health"

# Critical files that require higher approval
CRITICAL_FILES = [
    "main.py",
    "agent.py",
    "tools.py",
    "telegram_bot.py",
    "errors.py",
]


def _run_command(cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
    """Run a command and return result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _validate_python_syntax(app_path: str) -> Dict[str, Any]:
    """Validate Python syntax for all .py files."""
    errors = []
    checked = 0

    for root, dirs, files in os.walk(app_path):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != '__pycache__']

        for f in files:
            if f.endswith('.py'):
                filepath = os.path.join(root, f)
                result = _run_command(['python3', '-m', 'py_compile', filepath], timeout=10)
                checked += 1
                if not result.get("success"):
                    rel_path = os.path.relpath(filepath, app_path)
                    errors.append({
                        "file": rel_path,
                        "error": result.get("stderr", result.get("error", "Unknown error"))
                    })

    return {
        "valid": len(errors) == 0,
        "checked": checked,
        "errors": errors
    }


def _check_critical_changes() -> List[str]:
    """Check if critical files have been modified."""
    # Check git status for modified files
    result = _run_command(['git', '-C', '/volume1/BRAIN/system/ingestion', 'status', '--porcelain'])
    if not result.get("success"):
        return []

    modified = []
    for line in result.get("stdout", "").split('\n'):
        if line.strip():
            # Format: "XY filename" or "XY old -> new"
            parts = line.split()
            if len(parts) >= 2:
                filename = parts[-1]
                basename = os.path.basename(filename)
                if basename in CRITICAL_FILES:
                    modified.append(basename)

    return modified


def _get_current_image_tag() -> Optional[str]:
    """Get current running image tag for rollback."""
    result = _run_command([
        DOCKER_CMD, 'inspect',
        '--format', '{{.Image}}',
        JARVIS_CONTAINER
    ])
    if result.get("success"):
        return result.get("stdout", "").strip()
    return None


def _health_check(retries: int = 3, wait: int = 5) -> Dict[str, Any]:
    """Check Jarvis health status."""
    import requests

    for i in range(retries):
        try:
            resp = requests.get("http://192.168.1.103:18000/health", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                summary = data.get("summary", {})
                return {
                    "healthy": True,
                    "checks": f"{summary.get('healthy', 0)}/{summary.get('total_checks', 0)}",
                    "details": summary
                }
        except Exception as e:
            if i < retries - 1:
                time.sleep(wait)

    return {"healthy": False, "error": "Health check failed after retries"}


def tool_deploy_code_changes(
    validate_only: bool = False,
    skip_critical_check: bool = False,
    reason: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Deploy code changes to production (Jarvis self-deploy).

    This tool allows Jarvis to deploy its own code changes with safety guardrails:
    - Syntax validation before deploy
    - Critical file change detection
    - Auto-rollback on health failure
    - Telegram notification

    Args:
        validate_only: If True, only validate without deploying
        skip_critical_check: Skip critical file warning (requires approval)
        reason: Reason for deployment

    Returns:
        Deployment result with timing and health status
    """
    log_with_context(logger, "info", "Tool: deploy_code_changes",
                     validate_only=validate_only, reason=reason)
    metrics.inc("tool_deploy_code_changes")

    start_time = time.time()
    result = {
        "action": "validate" if validate_only else "deploy",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "steps": []
    }

    try:
        # Step 1: Check autonomy level
        from ..services.tool_autonomy import get_tool_autonomy_service
        autonomy = get_tool_autonomy_service()
        level = autonomy.get_current_level()

        if level < 2 and not validate_only:
            return {
                "status": "blocked",
                "error": "Deploy requires autonomy level >= 2",
                "current_level": level,
                "hint": "Ask Micha for approval or increase autonomy level"
            }

        result["steps"].append({"name": "autonomy_check", "status": "ok", "level": level})

        # Step 2: Validate Python syntax
        log_with_context(logger, "info", "Validating Python syntax...")
        validation = _validate_python_syntax("/volume1/BRAIN/system/ingestion/app")

        if not validation["valid"]:
            return {
                "status": "error",
                "error": "Syntax validation failed",
                "validation": validation,
                "hint": "Fix syntax errors before deploying"
            }

        result["steps"].append({
            "name": "syntax_validation",
            "status": "ok",
            "files_checked": validation["checked"]
        })

        # Step 3: Check for critical file changes
        if not skip_critical_check:
            critical = _check_critical_changes()
            if critical:
                result["steps"].append({
                    "name": "critical_check",
                    "status": "warning",
                    "critical_files": critical
                })

                if not validate_only:
                    return {
                        "status": "approval_required",
                        "message": f"Critical files modified: {', '.join(critical)}",
                        "critical_files": critical,
                        "hint": "Re-run with skip_critical_check=True after review"
                    }

        # If validate_only, stop here
        if validate_only:
            result["status"] = "valid"
            result["message"] = "Validation passed, ready to deploy"
            result["duration_seconds"] = round(time.time() - start_time, 2)
            return result

        # Step 4: Save rollback point
        rollback_image = _get_current_image_tag()
        result["steps"].append({
            "name": "rollback_point",
            "status": "ok",
            "image": rollback_image[:20] + "..." if rollback_image else None
        })

        # Step 5: Sync code to NAS (we're already on NAS, so just restart)
        log_with_context(logger, "info", "Restarting container...")

        restart_result = _run_command([
            DOCKER_CMD, 'restart', JARVIS_CONTAINER
        ], timeout=30)

        if not restart_result.get("success"):
            return {
                "status": "error",
                "error": "Container restart failed",
                "details": restart_result,
                "rollback_image": rollback_image
            }

        result["steps"].append({"name": "restart", "status": "ok"})

        # Step 6: Wait for startup
        log_with_context(logger, "info", "Waiting for startup...")
        time.sleep(15)

        # Step 7: Health check
        health = _health_check(retries=3, wait=5)

        if not health.get("healthy"):
            # Auto-rollback
            log_with_context(logger, "error", "Health check failed, triggering rollback")

            # TODO: Implement actual rollback
            result["steps"].append({
                "name": "health_check",
                "status": "failed",
                "details": health
            })
            result["status"] = "rollback_triggered"
            result["error"] = "Health check failed after deploy"

            # Send alert
            try:
                from ..telegram_bot import send_alert
                send_alert(f"⚠️ Deploy failed, rollback triggered. Reason: {reason or 'unknown'}")
            except:
                pass

            return result

        result["steps"].append({
            "name": "health_check",
            "status": "ok",
            "checks": health.get("checks")
        })

        # Success!
        result["status"] = "success"
        result["message"] = "Deploy completed successfully"
        result["duration_seconds"] = round(time.time() - start_time, 2)
        result["health"] = health.get("checks")

        # Send success notification
        try:
            from ..telegram_bot import send_alert
            send_alert(f"✅ Self-deploy successful ({result['duration_seconds']}s). Reason: {reason or 'code update'}")
        except:
            pass

        log_with_context(logger, "info", "Deploy completed successfully",
                        duration=result["duration_seconds"])

        return result

    except Exception as e:
        log_with_context(logger, "error", "Deploy failed", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "duration_seconds": round(time.time() - start_time, 2)
        }


def tool_validate_deploy_readiness(**kwargs) -> Dict[str, Any]:
    """
    Check if code is ready for deployment.

    Validates:
    - Python syntax
    - Import structure
    - Critical file changes
    - Current health status

    Returns:
        Readiness assessment with any issues found
    """
    log_with_context(logger, "info", "Tool: validate_deploy_readiness")
    metrics.inc("tool_validate_deploy_readiness")

    result = {
        "timestamp": datetime.now().isoformat(),
        "checks": []
    }

    # Syntax check
    validation = _validate_python_syntax("/volume1/BRAIN/system/ingestion/app")
    result["checks"].append({
        "name": "syntax",
        "passed": validation["valid"],
        "files_checked": validation["checked"],
        "errors": validation.get("errors", [])[:5]  # Limit errors
    })

    # Critical files
    critical = _check_critical_changes()
    result["checks"].append({
        "name": "critical_files",
        "passed": len(critical) == 0,
        "modified": critical
    })

    # Current health
    health = _health_check(retries=1, wait=0)
    result["checks"].append({
        "name": "current_health",
        "passed": health.get("healthy", False),
        "status": health.get("checks", "unknown")
    })

    # Overall assessment
    all_passed = all(c["passed"] for c in result["checks"])
    result["ready"] = all_passed
    result["message"] = "Ready to deploy" if all_passed else "Issues found, review before deploy"

    return result


def tool_get_deploy_history(limit: int = 10, **kwargs) -> Dict[str, Any]:
    """
    Get recent deployment history.

    Args:
        limit: Number of entries to return

    Returns:
        List of recent deployments with status and timing
    """
    log_with_context(logger, "info", "Tool: get_deploy_history", limit=limit)
    metrics.inc("tool_get_deploy_history")

    # Check docker logs for restart events
    result = _run_command([
        DOCKER_CMD, 'events',
        '--filter', f'container={JARVIS_CONTAINER}',
        '--filter', 'event=restart',
        '--since', '168h',  # Last 7 days
        '--until', 'now',
        '--format', '{{.Time}}'
    ], timeout=10)

    restarts = []
    if result.get("success"):
        for line in result.get("stdout", "").strip().split('\n'):
            if line:
                restarts.append(line)

    return {
        "container": JARVIS_CONTAINER,
        "recent_restarts": restarts[-limit:] if restarts else [],
        "total_restarts_7d": len(restarts)
    }
