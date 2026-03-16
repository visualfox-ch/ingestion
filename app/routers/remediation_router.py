"""
Remediation Router

Extracted from main.py - Phase 16.3 Automated Remediation API endpoints:
- Pending approvals
- Remediation history
- Success statistics
- Approve/reject/execute remediations
- Status callback from n8n
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
import requests

from ..observability import get_logger

logger = get_logger("jarvis.remediation")
router = APIRouter(prefix="/remediate", tags=["remediation"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class ExecuteRemediationRequest(BaseModel):
    """Request body for executing a remediation playbook."""
    dry_run: bool = False


class PlaybookStatusUpdate(BaseModel):
    """Status update from n8n playbook execution."""
    status: str  # "completed", "failed", "rolled_back"
    execution_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None


# n8n webhook URLs for each playbook
N8N_PLAYBOOK_WEBHOOKS = {
    "service_restart": "http://192.168.1.103:25678/webhook/service-restart",
    "log_archival": "http://192.168.1.103:25678/webhook/log-archival",
    "connection_pool_reset": "http://192.168.1.103:25678/webhook/connection-reset",
    "cache_invalidation": "http://192.168.1.103:25678/webhook/cache-invalidation",
    "index_optimization": "http://192.168.1.103:25678/webhook/index-optimization",
}


# =============================================================================
# QUERY ENDPOINTS
# =============================================================================

@router.get("/pending", response_model=Dict[str, Any])
async def get_pending_remediations():
    """
    Get all pending remediations awaiting approval.

    Returns list of Tier 2/3 playbooks that need human review.
    """
    from .. import remediation_manager

    try:
        pending = remediation_manager.get_pending_approvals()
        return {
            "status": "success",
            "count": len(pending),
            "pending_approvals": pending,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get pending remediations: {e}")
        return {
            "status": "error",
            "error": str(e),
            "pending_approvals": []
        }


@router.get("/recent", response_model=Dict[str, Any])
async def get_recent_remediations(days: int = 7):
    """
    Get recent remediation history.

    Args:
        days: Number of days to look back (default: 7)
    """
    from .. import remediation_manager

    try:
        recent = remediation_manager.get_recent_remediations(days=days)
        return {
            "status": "success",
            "count": len(recent),
            "remediations": recent,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get recent remediations: {e}")
        return {
            "status": "error",
            "error": str(e),
            "remediations": []
        }


@router.get("/stats", response_model=Dict[str, Any])
async def get_remediation_stats():
    """
    Get remediation success rates and statistics.

    Shows performance of each playbook type.
    """
    from .. import remediation_manager

    try:
        stats = remediation_manager.get_success_rates()
        return {
            "status": "success",
            "playbook_stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get remediation stats: {e}")
        return {
            "status": "error",
            "error": str(e),
            "playbook_stats": []
        }


# =============================================================================
# APPROVAL ENDPOINTS
# =============================================================================

@router.post("/{remediation_id}/approve", response_model=Dict[str, Any])
async def approve_remediation_endpoint(
    remediation_id: str,
    request: Request
):
    """
    Approve a pending remediation with validated input.

    Args:
        remediation_id: Unique ID of remediation (e.g., rem-20260201-001)

    Body (ApprovalDecisionRequest):
        - user_id: 3-100 chars, alphanumeric with @._-
        - reason: max 500 chars, stripped (optional)
        - idempotency_key: valid UUID v4 if provided
    """
    from .. import remediation_manager
    from ..schemas.remediation_schemas import ApprovalDecisionRequest

    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        body = await request.json()
        req = ApprovalDecisionRequest(**body)

        success = remediation_manager.approve_remediation(
            remediation_id=remediation_id,
            approved_by=req.user_id,
            reason=req.reason
        )

        if success:
            logger.info(
                f"Remediation approved via API",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": req.user_id
                }
            )
            return {
                "status": "success",
                "action": "approved",
                "remediation_id": remediation_id,
                "by": req.user_id,
                "reason": req.reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found or already processed",
                "remediation_id": remediation_id,
                "request_id": request_id
            }
    except Exception as e:
        logger.error(
            f"Failed to approve remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }


@router.post("/{remediation_id}/reject", response_model=Dict[str, Any])
async def reject_remediation_endpoint(
    remediation_id: str,
    request: Request
):
    """
    Reject a pending remediation with validated input.

    Args:
        remediation_id: Unique ID of remediation

    Body (RejectionDecisionRequest):
        - user_id: 3-100 chars, alphanumeric with @._-
        - reason: 5-500 chars, required, stripped
        - idempotency_key: valid UUID v4 if provided
    """
    from .. import remediation_manager
    from ..schemas.remediation_schemas import RejectionDecisionRequest

    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        body = await request.json()
        req = RejectionDecisionRequest(**body)

        success = remediation_manager.reject_remediation(
            remediation_id=remediation_id,
            rejected_by=req.user_id,
            reason=req.reason
        )

        if success:
            logger.info(
                f"Remediation rejected via API",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": req.user_id
                }
            )
            return {
                "status": "success",
                "action": "rejected",
                "remediation_id": remediation_id,
                "by": req.user_id,
                "reason": req.reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found or already processed",
                "remediation_id": remediation_id,
                "request_id": request_id
            }
    except Exception as e:
        logger.error(
            f"Failed to reject remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }


# =============================================================================
# EXECUTION ENDPOINTS
# =============================================================================

@router.post("/{remediation_id}/execute", response_model=Dict[str, Any])
async def execute_remediation_endpoint(
    remediation_id: str,
    req: ExecuteRemediationRequest,
    request: Request
):
    """
    Execute an approved remediation playbook.

    Phase 16.3C: Triggers n8n workflow for the remediation.

    Args:
        remediation_id: Unique ID of remediation
        req: ExecuteRemediationRequest with dry_run flag

    Returns:
        Execution status and workflow ID
    """
    from .. import remediation_manager

    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        # Get remediation details
        remediation = remediation_manager.get_remediation(remediation_id)

        if not remediation:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "error": "Remediation not found",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        # Check if approved (Tier-2) or auto-approved (Tier-1)
        if remediation.get("status") not in ["approved", "auto_approved"]:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error": f"Remediation not approved. Current status: {remediation.get('status')}",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        playbook_type = remediation.get("playbook_type", "unknown")
        webhook_url = N8N_PLAYBOOK_WEBHOOKS.get(playbook_type)

        if not webhook_url:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error": f"Unknown playbook type: {playbook_type}",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        # Prepare payload for n8n
        payload = {
            "remediation_id": remediation_id,
            "playbook_type": playbook_type,
            "trigger_reason": remediation.get("trigger_reason", "Manual execution"),
            "params": remediation.get("params", {}),
            "dry_run": req.dry_run,
            "callback_url": f"http://jarvis-ingestion:18000/remediate/{remediation_id}/status",
            "request_id": request_id
        }

        if req.dry_run:
            # Dry run - don't actually call n8n
            logger.info(
                f"Dry run for remediation",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "playbook_type": playbook_type
                }
            )
            return {
                "status": "dry_run",
                "remediation_id": remediation_id,
                "playbook_type": playbook_type,
                "would_call": webhook_url,
                "payload": payload,
                "request_id": request_id
            }

        # Call n8n webhook
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=30,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                # Update remediation status to executing
                remediation_manager.update_status(remediation_id, "executing")

                logger.info(
                    f"Remediation execution started",
                    extra={
                        "request_id": request_id,
                        "remediation_id": remediation_id,
                        "playbook_type": playbook_type
                    }
                )

                return {
                    "status": "executing",
                    "remediation_id": remediation_id,
                    "playbook_type": playbook_type,
                    "workflow_id": response.json().get("executionId", "unknown"),
                    "started_at": datetime.utcnow().isoformat(),
                    "request_id": request_id
                }
            else:
                logger.error(
                    f"n8n webhook failed",
                    extra={
                        "request_id": request_id,
                        "remediation_id": remediation_id,
                        "status_code": response.status_code,
                        "response": response.text[:500]
                    }
                )
                return JSONResponse(
                    status_code=502,
                    content={
                        "status": "error",
                        "error": f"n8n webhook returned {response.status_code}",
                        "remediation_id": remediation_id,
                        "request_id": request_id
                    }
                )

        except requests.exceptions.Timeout:
            return JSONResponse(
                status_code=504,
                content={
                    "status": "error",
                    "error": "n8n webhook timed out",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )
        except requests.exceptions.ConnectionError:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "error": "Cannot connect to n8n",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

    except Exception as e:
        logger.error(
            f"Failed to execute remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "remediation_id": remediation_id,
                "request_id": request_id
            }
        )


@router.post("/{remediation_id}/status", response_model=Dict[str, Any])
async def update_remediation_status_endpoint(
    remediation_id: str,
    update: PlaybookStatusUpdate,
    request: Request
):
    """
    Receive status update from n8n playbook execution.

    Phase 16.3C: Callback endpoint for n8n workflows.

    Args:
        remediation_id: Unique ID of remediation
        update: PlaybookStatusUpdate with execution result
    """
    from .. import remediation_manager

    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        # Update remediation status in database
        success = remediation_manager.update_execution_result(
            remediation_id=remediation_id,
            status=update.status,
            execution_result=update.execution_result,
            error=update.error,
            duration_seconds=update.duration_seconds
        )

        if success:
            logger.info(
                f"Remediation status updated",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "status": update.status,
                    "duration": update.duration_seconds
                }
            )
            return {
                "status": "success",
                "remediation_id": remediation_id,
                "new_status": update.status,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found",
                "remediation_id": remediation_id,
                "request_id": request_id
            }

    except Exception as e:
        logger.error(
            f"Failed to update remediation status",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }
