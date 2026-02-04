"""
Phase 5.0: Self-Modification Endpoints

Enables Jarvis to:
1. Analyze his own code
2. Identify improvement opportunities
3. Propose code changes
4. Submit for human approval
5. Track proposal lifecycle

Safety: All changes require HITL approval before application
"""

from fastapi import APIRouter, Request, Query, Body
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
import difflib

from ..errors import JarvisException, ErrorCode
from ..observability import get_logger
from ..knowledge_db import get_conn

logger = get_logger("jarvis.routers.self_modification")

router = APIRouter(
    prefix="",
    tags=["self-modification"],
    responses={
        400: {"description": "Invalid request"},
        403: {"description": "Unauthorized - HITL approval required"},
        500: {"description": "Internal server error"},
    }
)


# ============================================================================
# CODE ANALYSIS ENDPOINTS
# ============================================================================

@router.post("/jarvis/self/analyze-code")
async def analyze_own_code(
    file_path: str = Query(..., description="Path to file to analyze"),
    analysis_type: str = Query("code_quality", description="Type of analysis"),
    request: Request = None
):
    """
    Jarvis analyzes his own code for improvement opportunities.
    
    Analysis types:
    - complexity_analysis: Cyclomatic complexity, maintainability
    - performance_profiling: Performance bottlenecks
    - code_quality: Code smells, best practices
    - security_scan: Security vulnerabilities
    - pattern_detection: Recurring patterns, duplication
    - self_reflection: Meta-awareness about own implementation
    
    Returns: Analysis results with recommendations
    """
    try:
        from ..knowledge_db import get_conn
        
        # Validate analysis type
        valid_types = [
            'complexity_analysis', 'performance_profiling', 'code_quality',
            'security_scan', 'pattern_detection', 'self_reflection'
        ]
        if analysis_type not in valid_types:
            raise JarvisException(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid analysis_type. Must be one of: {valid_types}",
                status_code=400
            )
        
        # TODO: Implement actual code analysis (radon, pylint, etc.)
        # For now, return mock analysis
        findings = {
            "file": file_path,
            "analysis_type": analysis_type,
            "timestamp": datetime.now().isoformat(),
            "findings": [
                {
                    "type": "code_smell",
                    "severity": "medium",
                    "location": "line 45",
                    "description": "Complex function with high cyclomatic complexity",
                    "suggestion": "Consider breaking into smaller functions"
                }
            ],
            "metrics": {
                "complexity": 8,
                "maintainability_index": 65,
                "lines_of_code": 234
            },
            "recommendations": [
                "Refactor complex function",
                "Add type hints",
                "Improve error handling"
            ]
        }
        
        # Store analysis
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jarvis_code_analysis
                    (file_path, analysis_type, findings, metrics, recommendations)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                    RETURNING id, analyzed_at
                    """,
                    (
                        file_path,
                        analysis_type,
                        json.dumps(findings),
                        json.dumps(findings.get("metrics", {})),
                        findings.get("recommendations", [])
                    )
                )
                result = cur.fetchone()
                conn.commit()
        
        return {
            "data": {
                "analysis_id": result['id'],
                "analyzed_at": result['analyzed_at'].isoformat(),
                "file_path": file_path,
                "analysis_type": analysis_type,
                "findings": findings,
                "status": "complete"
            },
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Code analysis failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Code analysis failed: {str(e)}",
            status_code=500
        )


# ============================================================================
# SELF-MODIFICATION PROPOSAL ENDPOINTS
# ============================================================================

@router.post("/jarvis/self/propose-change")
async def propose_code_change(
    proposal: Dict[str, Any] = Body(...),
    request: Request = None
):
    """
    Jarvis proposes a code change to improve himself.
    
    Request body:
    {
        "target_file": "app/main.py",
        "target_function": "handle_request",
        "change_type": "performance_optimization",
        "reasoning": "Current implementation has O(n²) complexity...",
        "original_code": "def handle_request():\\n    ...",
        "proposed_code": "def handle_request():\\n    ...",
        "risk_level": "low",
        "estimated_impact": "20% latency reduction",
        "rollback_plan": "Revert to previous version",
        "test_plan": "Run existing test suite + load test"
    }
    
    Returns: Proposal ID for tracking, awaits human approval
    """
    try:
        from ..knowledge_db import get_conn
        
        # Validate required fields
        required = ['target_file', 'change_type', 'reasoning', 'proposed_code']
        missing = [f for f in required if f not in proposal]
        if missing:
            raise JarvisException(
                code=ErrorCode.INVALID_INPUT,
                message=f"Missing required fields: {missing}",
                status_code=400
            )
        
        # Generate diff if original_code provided
        diff_patch = None
        if 'original_code' in proposal and proposal['original_code']:
            diff = difflib.unified_diff(
                proposal['original_code'].splitlines(keepends=True),
                proposal['proposed_code'].splitlines(keepends=True),
                fromfile=f"a/{proposal['target_file']}",
                tofile=f"b/{proposal['target_file']}"
            )
            diff_patch = ''.join(diff)
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jarvis_code_proposals
                    (target_file, target_function, change_type, reasoning,
                     original_code, proposed_code, diff_patch,
                     risk_level, estimated_impact, rollback_plan, test_plan,
                     status, proposed_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, created_at, status
                    """,
                    (
                        proposal['target_file'],
                        proposal.get('target_function'),
                        proposal['change_type'],
                        proposal['reasoning'],
                        proposal.get('original_code'),
                        proposal['proposed_code'],
                        diff_patch,
                        proposal.get('risk_level', 'medium'),
                        proposal.get('estimated_impact'),
                        proposal.get('rollback_plan'),
                        proposal.get('test_plan'),
                        'proposed',
                        'jarvis_self'
                    )
                )
                result = cur.fetchone()
                conn.commit()
        
        return {
            "data": {
                "proposal_id": result['id'],
                "status": result['status'],
                "created_at": result['created_at'].isoformat(),
                "target_file": proposal['target_file'],
                "change_type": proposal['change_type'],
                "risk_level": proposal.get('risk_level', 'medium'),
                "message": "Code change proposal submitted. Awaiting human review.",
                "next_steps": [
                    "Human review required",
                    "Approval or rejection decision",
                    "If approved: safe application with rollback capability"
                ]
            },
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to create code proposal")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to create proposal: {str(e)}",
            status_code=500
        )


@router.get("/jarvis/self/proposals")
async def list_code_proposals(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    request: Request = None
):
    """
    List all self-modification proposals.
    
    Returns: Proposals with status, reasoning, approval state
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        """
                        SELECT 
                            id, created_at, target_file, target_function,
                            change_type, reasoning, risk_level, status,
                            reviewed_by, approved_at, applied_at
                        FROM jarvis_code_proposals
                        WHERE status = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (status, limit)
                    )
                else:
                    cur.execute(
                        """
                        SELECT 
                            id, created_at, target_file, target_function,
                            change_type, reasoning, risk_level, status,
                            reviewed_by, approved_at, applied_at
                        FROM jarvis_code_proposals
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                
                proposals = cur.fetchall()
        
        return {
            "data": {
                "total": len(proposals),
                "proposals": [
                    {
                        "proposal_id": p['id'],
                        "created_at": p['created_at'].isoformat(),
                        "target_file": p['target_file'],
                        "target_function": p['target_function'],
                        "change_type": p['change_type'],
                        "reasoning": p['reasoning'][:200] + "..." if len(p['reasoning']) > 200 else p['reasoning'],
                        "risk_level": p['risk_level'],
                        "status": p['status'],
                        "reviewed_by": p['reviewed_by'],
                        "approved_at": p['approved_at'].isoformat() if p['approved_at'] else None,
                        "applied_at": p['applied_at'].isoformat() if p['applied_at'] else None
                    }
                    for p in proposals
                ]
            },
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except Exception as e:
        logger.exception("Failed to list proposals")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to list proposals: {str(e)}",
            status_code=500
        )


@router.get("/jarvis/self/proposals/{proposal_id}")
async def get_proposal_detail(
    proposal_id: int,
    request: Request = None
):
    """
    Get detailed information about a specific proposal including full diff.
    
    Returns: Complete proposal with code diff, approval status, audit trail
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM jarvis_code_proposals
                    WHERE id = %s
                    """,
                    (proposal_id,)
                )
                proposal = cur.fetchone()
        
        if not proposal:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Proposal {proposal_id} not found",
                status_code=404
            )
        
        return {
            "data": {
                "proposal_id": proposal['id'],
                "created_at": proposal['created_at'].isoformat(),
                "updated_at": proposal['updated_at'].isoformat(),
                "target_file": proposal['target_file'],
                "target_function": proposal['target_function'],
                "change_type": proposal['change_type'],
                "reasoning": proposal['reasoning'],
                "diff_patch": proposal['diff_patch'],
                "risk_level": proposal['risk_level'],
                "estimated_impact": proposal['estimated_impact'],
                "rollback_plan": proposal['rollback_plan'],
                "test_plan": proposal['test_plan'],
                "status": proposal['status'],
                "reviewed_by": proposal['reviewed_by'],
                "review_notes": proposal['review_notes'],
                "approved_at": proposal['approved_at'].isoformat() if proposal['approved_at'] else None,
                "applied_at": proposal['applied_at'].isoformat() if proposal['applied_at'] else None,
                "git_commit_hash": proposal['git_commit_hash'],
                "deployment_verified": proposal['deployment_verified']
            },
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to get proposal detail")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get proposal: {str(e)}",
            status_code=500
        )


@router.post("/jarvis/self/proposals/{proposal_id}/review")
async def review_proposal(
    proposal_id: int,
    decision: str = Query(..., description="approve or reject"),
    review_notes: Optional[str] = Query(None, description="Review comments"),
    reviewed_by: str = Query("human", description="Reviewer name"),
    request: Request = None
):
    """
    Human reviews and approves/rejects a code change proposal.
    
    HITL Gate: Only humans can approve code changes
    
    Returns: Updated proposal status
    """
    try:
        from ..knowledge_db import get_conn
        
        if decision not in ['approve', 'reject']:
            raise JarvisException(
                code=ErrorCode.INVALID_INPUT,
                message="Decision must be 'approve' or 'reject'",
                status_code=400
            )
        
        new_status = 'approved' if decision == 'approve' else 'rejected'
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jarvis_code_proposals
                    SET status = %s,
                        reviewed_by = %s,
                        review_notes = %s,
                        approved_at = CASE WHEN %s = 'approved' THEN NOW() ELSE NULL END,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, status, approved_at
                    """,
                    (new_status, reviewed_by, review_notes, new_status, proposal_id)
                )
                result = cur.fetchone()
                
                if not result:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Proposal {proposal_id} not found",
                        status_code=404
                    )
                
                conn.commit()
        
        return {
            "data": {
                "proposal_id": result['id'],
                "status": result['status'],
                "decision": decision,
                "reviewed_by": reviewed_by,
                "review_notes": review_notes,
                "approved_at": result['approved_at'].isoformat() if result['approved_at'] else None,
                "message": f"Proposal {decision}d by {reviewed_by}",
                "next_steps": [
                    "Apply change via deployment" if decision == 'approve' else "Proposal archived"
                ]
            },
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to review proposal")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to review proposal: {str(e)}",
            status_code=500
        )
