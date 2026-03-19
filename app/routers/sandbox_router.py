"""
Sandbox Router - Phase C

API endpoints for code sandbox management.
Allows testing and promoting Jarvis-written tools.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from dataclasses import asdict

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.sandbox_router")
router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class SandboxCodeInput(BaseModel):
    """Request body for writing code to sandbox."""
    code: str
    description: str = ""


class SandboxWorkflowInput(BaseModel):
    """Request body for full sandbox workflow."""
    code: str
    description: str = ""
    auto_promote: bool = False


class SandboxSessionCreateInput(BaseModel):
    """Request body for a runtime sandbox session."""
    purpose: str = "python_exec"


class SandboxRuntimeExecInput(BaseModel):
    """Request body for runtime python execution."""
    code: str
    files: Optional[Dict[str, str]] = None


def _raise_runtime_error(exc: Exception) -> None:
    from ..sandbox import SandboxExecutionError, SandboxNotFoundError, SandboxPolicyError

    if isinstance(exc, SandboxNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SandboxPolicyError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, SandboxExecutionError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


# =============================================================================
# STATUS & LISTING
# =============================================================================

@router.get("/runtime/health")
def get_runtime_sandbox_health():
    """Get health and operator controls for the runtime sandbox adapter."""
    from ..sandbox import get_sandbox_service

    return get_sandbox_service().get_health()


@router.get("/runtime/sessions")
def list_runtime_sandbox_sessions():
    """List active runtime sandbox sessions."""
    from ..sandbox import get_sandbox_service

    return get_sandbox_service().list_sessions()


@router.post("/runtime/sessions")
def create_runtime_sandbox_session(body: SandboxSessionCreateInput):
    """Create a new runtime sandbox session."""
    from ..sandbox import get_sandbox_service

    try:
        return get_sandbox_service().create_session(purpose=body.purpose)
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/runtime/sessions/{session_id}/python")
def execute_runtime_sandbox_python(session_id: str, body: SandboxRuntimeExecInput):
    """Execute Python code inside an existing runtime sandbox session."""
    from ..sandbox import get_sandbox_service

    try:
        return get_sandbox_service().execute_python(
            session_id=session_id,
            code=body.code,
            files=body.files,
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.delete("/runtime/sessions/{session_id}")
def cleanup_runtime_sandbox_session(session_id: str):
    """Cleanup a runtime sandbox session and its workspace."""
    from ..sandbox import get_sandbox_service

    try:
        return get_sandbox_service().cleanup_session(session_id)
    except Exception as exc:
        _raise_runtime_error(exc)


@router.get("/status")
def get_sandbox_status():
    """
    Get sandbox system status.

    Shows counts of files in each stage: pending, tested, approved, promoted.
    """
    from ..sandbox_runner import SandboxRunner
    return SandboxRunner.get_status()


@router.get("/files/{directory}")
def list_sandbox_files(
    directory: str = "pending"
):
    """
    List files in a sandbox directory.

    Args:
        directory: One of: pending, tested, approved, promoted
    """
    from ..sandbox_runner import SandboxRunner

    if directory not in ["pending", "tested", "approved", "promoted"]:
        raise HTTPException(
            status_code=400,
            detail="directory must be one of: pending, tested, approved, promoted"
        )

    files = SandboxRunner.list_files(directory)

    return {
        "directory": directory,
        "files": files,
        "count": len(files)
    }


# =============================================================================
# TESTING
# =============================================================================

@router.post("/test/{filename}")
def test_sandbox_file(filename: str):
    """
    Test a file in the pending/ directory.

    Runs:
    - Syntax check
    - Import validation
    - Structure validation (TOOL_NAME, TOOL_SCHEMA, tool_handler)
    - Security scan
    - Execution test

    If all pass, file is moved to tested/.
    """
    from ..sandbox_runner import SandboxRunner

    result = SandboxRunner.test_file(filename)

    return {
        "file": filename,
        "status": result.status.value,
        "checks": {
            "syntax": result.syntax_ok,
            "imports": result.imports_ok,
            "structure": result.structure_ok,
            "security": result.security_ok,
            "execution": result.execution_ok
        },
        "errors": result.errors,
        "warnings": result.warnings,
        "execution_time_ms": result.execution_time_ms,
        "tested_at": result.tested_at
    }


@router.post("/test-all")
def test_all_pending():
    """
    Test all files in the pending/ directory.

    Returns results for each file.
    """
    from ..sandbox_runner import SandboxRunner

    results = SandboxRunner.test_all_pending()

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.status.value == "passed"),
        "failed": sum(1 for r in results if r.status.value == "failed")
    }

    return {
        "summary": summary,
        "results": [
            {
                "file": r.file_name,
                "status": r.status.value,
                "errors": r.errors,
                "warnings": r.warnings
            }
            for r in results
        ]
    }


# =============================================================================
# APPROVAL & PROMOTION
# =============================================================================

@router.post("/approve/{filename}")
def approve_sandbox_file(filename: str):
    """
    Approve a tested file (human approval step).

    Moves file from tested/ to approved/.
    """
    from ..sandbox_runner import SandboxRunner

    result = SandboxRunner.approve(filename)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))

    log_with_context(logger, "info", "Sandbox file approved", file=filename)

    return result


@router.post("/promote/{filename}")
def promote_sandbox_file(
    filename: str,
    skip_approval: bool = Query(default=False, description="Promote from tested/ directly")
):
    """
    Promote a sandbox file to active dynamic tools.

    The file will be:
    1. Copied to dynamic tools directory
    2. Archived to promoted/
    3. Hot-reloaded into TOOL_REGISTRY

    Args:
        filename: File to promote (must be in tested/ or approved/)
        skip_approval: If True, promote directly from tested/ (no human approval)
    """
    from ..sandbox_runner import SandboxRunner
    from ..live_config import get_config

    # Check if auto-promote is allowed
    if skip_approval and not get_config("self_modification_auto_promote", False):
        raise HTTPException(
            status_code=403,
            detail="Auto-promotion disabled. Set config 'self_modification_auto_promote' to true or use approval flow."
        )

    result = SandboxRunner.promote(filename, skip_approval=skip_approval)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))

    log_with_context(logger, "info", "Sandbox file promoted",
                    file=filename, skip_approval=skip_approval)

    return result


# =============================================================================
# SELF-MODIFICATION WORKFLOW
# =============================================================================

@router.post("/write/{tool_name}")
def write_to_sandbox(
    tool_name: str,
    body: SandboxCodeInput
):
    """
    Write code to the sandbox pending/ directory.

    This is an alternative to the write_dynamic_tool tool,
    accessible via API for testing.
    """
    from ..sandbox_runner import SandboxRunner, PENDING_DIR
    import re

    # Validate tool name
    if not re.match(r"^[a-z][a-z0-9_]*$", tool_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid tool name. Use lowercase letters, numbers, underscores. Must start with letter."
        )

    code = body.code
    description = body.description

    SandboxRunner.ensure_directories()

    # Add metadata header
    from datetime import datetime
    header = f'''"""
{description or 'Auto-generated sandbox tool'}

Created: {datetime.utcnow().isoformat()}
"""

'''
    full_code = header + code if not code.startswith('"""') else code

    # Write file
    filename = f"{tool_name}.py"
    file_path = PENDING_DIR / filename

    try:
        file_path.write_text(full_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")

    log_with_context(logger, "info", "Code written to sandbox", file=filename)

    return {
        "success": True,
        "file": filename,
        "location": str(file_path),
        "next_step": f"POST /sandbox/test/{filename}"
    }


@router.post("/full-workflow/{tool_name}")
def run_full_sandbox_workflow(
    tool_name: str,
    body: SandboxWorkflowInput
):
    """
    Run the complete sandbox workflow in one call:
    1. Write code to pending/
    2. Run tests
    3. If passed and auto_promote=True, promote to dynamic tools

    This is the easiest way for Jarvis to self-modify.
    """
    from ..sandbox_runner import SandboxRunner, PENDING_DIR
    from ..live_config import get_config

    code = body.code
    description = body.description
    auto_promote = body.auto_promote
    import re

    # Validate tool name
    if not re.match(r"^[a-z][a-z0-9_]*$", tool_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid tool name"
        )

    # Check if self-modification is enabled
    if not get_config("self_modification_enabled", True):
        raise HTTPException(
            status_code=403,
            detail="Self-modification is disabled. Enable via config."
        )

    SandboxRunner.ensure_directories()

    # 1. Write
    from datetime import datetime
    header = f'''"""
{description or 'Auto-generated sandbox tool'}

Created: {datetime.utcnow().isoformat()}
"""

'''
    full_code = header + code if not code.startswith('"""') else code
    filename = f"{tool_name}.py"
    file_path = PENDING_DIR / filename

    try:
        file_path.write_text(full_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write: {e}")

    # 2. Test
    test_result = SandboxRunner.test_file(filename)

    response = {
        "file": filename,
        "write": "success",
        "test": {
            "status": test_result.status.value,
            "passed": test_result.status.value == "passed",
            "errors": test_result.errors,
            "warnings": test_result.warnings
        },
        "promoted": False
    }

    # 3. Promote if requested and tests passed
    if auto_promote and test_result.status.value == "passed":
        if get_config("self_modification_auto_promote", False):
            promote_result = SandboxRunner.promote(filename, skip_approval=True)
            response["promoted"] = promote_result.get("success", False)
            response["promote_result"] = promote_result
        else:
            response["promote_blocked"] = "auto_promote disabled in config"

    log_with_context(logger, "info", "Sandbox workflow complete",
                    file=filename,
                    test_passed=test_result.status.value == "passed",
                    promoted=response["promoted"])

    return response
