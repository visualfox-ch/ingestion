"""Workflow management routes (Phase 3: n8n Workflow Mastery)."""
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field

from ..observability import get_logger, log_with_context
from ..n8n_workflow_manager import N8NWorkflowManager
from ..rate_limiter import rate_limit_dependency

logger = get_logger("jarvis.workflow_router")
router = APIRouter()


class WorkflowCreateRequest(BaseModel):
    workflow_data: Dict[str, Any] = Field(..., description="Full n8n workflow definition")


class WorkflowExecuteRequest(BaseModel):
    data: Optional[Dict[str, Any]] = Field(default=None, description="Input data for execution")


def _audit_log(action: str, workflow_id: Optional[str], request: Optional[Request], **extra):
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    log_with_context(
        logger,
        "info",
        f"workflow_{action}",
        workflow_id=workflow_id,
        request_id=request_id,
        **extra
    )


@router.get("/workflows", response_model=List[Dict[str, Any]])
def list_workflows(
    active_only: bool = False,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """List all n8n workflows."""
    manager = N8NWorkflowManager()
    return manager.list_workflows(active_only=active_only)


@router.get("/workflows/audit", response_model=List[Dict[str, Any]])
def audit_workflows(
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Audit workflows for reliability patterns (error trigger, retry, rate limit)."""
    manager = N8NWorkflowManager()
    return manager.audit_workflows()


@router.post("/workflows/harden", response_model=Dict[str, Any])
def harden_workflows(
    request: Request,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Apply basic reliability hardening (error workflow) to all workflows."""
    manager = N8NWorkflowManager()
    error_workflow_id = manager.ensure_error_handler_workflow()

    if not error_workflow_id:
        raise HTTPException(status_code=500, detail="Failed to create error handler workflow")

    result = manager.apply_error_workflow_to_all(error_workflow_id)
    _audit_log("harden", error_workflow_id, request, updated=result.get("updated"))
    return result


@router.get("/workflows/{workflow_id}", response_model=Dict[str, Any])
def get_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get a specific workflow by ID."""
    manager = N8NWorkflowManager()
    return manager.get_workflow(workflow_id)


@router.post("/workflows/create", response_model=Dict[str, Any])
def create_workflow(
    req: WorkflowCreateRequest,
    request: Request,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Create a new workflow."""
    if not req.workflow_data:
        raise HTTPException(status_code=400, detail="workflow_data is required")

    manager = N8NWorkflowManager()
    result = manager.create_workflow(req.workflow_data)

    _audit_log("create", result.get("id"), request, name=req.workflow_data.get("name"))
    return result


@router.post("/workflows/{workflow_id}/execute", response_model=Dict[str, Any])
def execute_workflow(
    workflow_id: str,
    req: WorkflowExecuteRequest,
    request: Request,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute a workflow manually."""
    manager = N8NWorkflowManager()
    result = manager.execute_workflow(workflow_id, req.data if req else None)

    _audit_log("execute", workflow_id, request)
    return result


@router.get("/workflows/{workflow_id}/executions", response_model=List[Dict[str, Any]])
def list_executions(
    workflow_id: str,
    limit: int = 20,
    status: Optional[str] = None,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get recent executions for a workflow."""
    manager = N8NWorkflowManager()
    return manager.list_executions(workflow_id=workflow_id, limit=limit, status=status)


@router.delete("/workflows/{workflow_id}", response_model=Dict[str, Any])
def delete_workflow(
    workflow_id: str,
    request: Request,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Delete a workflow."""
    manager = N8NWorkflowManager()
    result = manager.delete_workflow(workflow_id)

    _audit_log("delete", workflow_id, request)
    return result
