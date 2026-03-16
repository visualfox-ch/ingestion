"""
Code Router

Extracted from main.py - Phase 21 Code Writing Tools:
- Confidence calculation
- Code change proposals
- Staged changes management
- Approve/reject/apply/rollback
- Code writing dashboard
- Repo graph queries
"""

from fastapi import APIRouter, Request
from typing import Dict, Any, Optional

from ..observability import get_logger
from ..services import repo_graph_service as repo_graph_module

logger = get_logger("jarvis.code")
router = APIRouter(prefix="/code", tags=["code"])


# =============================================================================
# CONFIDENCE & PROPOSALS
# =============================================================================

@router.post("/confidence", response_model=Dict[str, Any])
async def calculate_confidence_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Calculate confidence score for an action.

    Phase 21: Jarvis Self-Programming - Confidence Scoring
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = code_writing_service.calculate_confidence(req)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to calculate confidence: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.post("/propose", response_model=Dict[str, Any])
async def propose_code_change_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Propose a code change for human review.

    Phase 21: Jarvis Self-Programming - Code Change Proposal
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.propose_code_change(
            file_path=req.get("file_path"),
            change_type=req.get("change_type"),
            description=req.get("description", ""),
            code_snippet=req.get("code_snippet"),
            line_start=req.get("line_start"),
            line_end=req.get("line_end"),
            justification=req.get("justification"),
            context=req.get("context", {})
        )
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to propose code change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# CHANGES MANAGEMENT
# =============================================================================

@router.get("/changes", response_model=Dict[str, Any])
async def get_staged_changes_endpoint(
    status: Optional[str] = None,
    request: Request = None
):
    """
    Get all staged code changes.

    Phase 21: Jarvis Self-Programming - List Changes
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        changes = await code_writing_service.get_staged_changes(status)
        return {
            "status": "success",
            "changes": changes,
            "count": len(changes),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get staged changes: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.get("/changes/{change_id}", response_model=Dict[str, Any])
async def get_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Get a specific code change by ID.

    Phase 21: Jarvis Self-Programming - Get Change Details
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        change = await code_writing_service.get_change_by_id(change_id)
        if change:
            return {
                "status": "success",
                "change": change,
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": f"Change {change_id} not found",
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Failed to get change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.post("/changes/{change_id}/approve", response_model=Dict[str, Any])
async def approve_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Approve a staged code change.

    Phase 21: Jarvis Self-Programming - Approve Change
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.approve_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to approve change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.post("/changes/{change_id}/reject", response_model=Dict[str, Any])
async def reject_change_endpoint(
    change_id: str,
    req: Dict[str, Any] = None,
    request: Request = None
):
    """
    Reject a staged code change.

    Phase 21: Jarvis Self-Programming - Reject Change
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    reason = req.get("reason", "") if req else ""

    try:
        result = await code_writing_service.reject_change(change_id, reason)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to reject change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.post("/changes/{change_id}/apply", response_model=Dict[str, Any])
async def apply_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Apply an approved code change to the file.

    Phase 21: Jarvis Self-Programming - Apply Change
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.apply_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to apply change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.post("/changes/{change_id}/rollback", response_model=Dict[str, Any])
async def rollback_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Rollback an applied code change.

    Phase 21: Jarvis Self-Programming - Rollback Change
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.rollback_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to rollback change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# DASHBOARD
# =============================================================================

@router.get("/dashboard", response_model=Dict[str, Any])
async def code_writing_dashboard_endpoint(
    request: Request = None
):
    """
    Get code writing activity dashboard.

    Phase 21: Jarvis Self-Programming - Code Writing Dashboard
    """
    from ..services.code_writing_service import code_writing_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.get_code_writing_dashboard()
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to get code writing dashboard: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# REPO GRAPH
# =============================================================================

@router.get("/repo-graph/health", response_model=Dict[str, Any])
async def repo_graph_health_endpoint(
    force_rebuild: bool = False,
    request: Request = None
):
    """Return repo graph snapshot health and index counters."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        result = repo_graph_module.get_service().get_health(force_rebuild=force_rebuild)
        result["request_id"] = request_id
        return result
    except Exception as e:
        logger.error(f"Failed to get repo graph health: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id,
        }


@router.get("/repo-graph/symbols/{symbol:path}/references", response_model=Dict[str, Any])
async def repo_graph_symbol_references_endpoint(
    symbol: str,
    force_rebuild: bool = False,
    max_results: int = 100,
    request: Request = None
):
    """Return import and call references for a symbol query."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        result = repo_graph_module.get_service().find_symbol_references(
            symbol,
            force_rebuild=force_rebuild,
            max_results=max_results,
        )
        result["request_id"] = request_id
        return result
    except Exception as e:
        logger.error(f"Failed to get repo graph references for {symbol}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id,
        }


@router.get("/repo-graph/symbols/{symbol:path}/impact", response_model=Dict[str, Any])
async def repo_graph_symbol_impact_endpoint(
    symbol: str,
    force_rebuild: bool = False,
    max_depth: int = 2,
    max_results: int = 100,
    request: Request = None
):
    """Estimate transitive caller impact for a symbol query."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        result = repo_graph_module.get_service().estimate_change_impact(
            symbol,
            force_rebuild=force_rebuild,
            max_depth=max_depth,
            max_results=max_results,
        )
        result["request_id"] = request_id
        return result
    except Exception as e:
        logger.error(f"Failed to get repo graph impact for {symbol}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id,
        }


@router.get("/repo-graph/symbols/{symbol:path}/related-files", response_model=Dict[str, Any])
async def repo_graph_related_files_endpoint(
    symbol: str,
    force_rebuild: bool = False,
    max_results: int = 20,
    request: Request = None
):
    """Return related files for a symbol, prioritizing definitions and direct callers."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        result = repo_graph_module.get_service().related_files_for_symbol(
            symbol,
            force_rebuild=force_rebuild,
            max_results=max_results,
        )
        result["request_id"] = request_id
        return result
    except Exception as e:
        logger.error(f"Failed to get related files for {symbol}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id,
        }
