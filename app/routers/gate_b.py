"""
Gate B Router - Approval + Execution Framework for Jarvis
Enables bounded autonomy with human oversight and automatic rollback safety
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import json
import os
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
import logging

from .. import metrics

logger = logging.getLogger(__name__)

# Configuration
APPROVAL_SECRET = os.getenv("GATE_B_APPROVAL_SECRET", "dev_secret_change_in_production")
PROPOSALS_FILE = "/brain/system/state/proposals.json"
ROLLBACK_WINDOW_SECONDS = 60
MAX_PROPOSALS_PER_HOUR = 5

# Ensure state directory exists
os.makedirs(os.path.dirname(PROPOSALS_FILE), exist_ok=True)

router = APIRouter(prefix="/api/gate-b", tags=["gate-b"])

# ============================================================================
# SCHEMAS (Pydantic Models)
# ============================================================================

class RollbackCondition(BaseModel):
    enabled: bool = True
    metric: str  # "accuracy_rate", "latency_p95", "error_rate", "token_efficiency"
    threshold: float  # e.g., 0.95 for accuracy
    comparison: str = "below"  # "below" or "above"
    window: int = 60  # seconds to monitor
    fallback: str = "revert_to_previous"

class ProposalScope(BaseModel):
    files: List[str]
    lines: Optional[Dict[str, tuple]] = None
    description: str

class ProposalChanges(BaseModel):
    operation: str  # "modify", "create", "delete"
    format: str = "unified_diff"  # "unified_diff", "json_patch", "yaml_update"
    content: str  # The actual diff
    preview: Optional[str] = None

class EstimatedImpact(BaseModel):
    latency_change_pct: Optional[float] = None
    accuracy_change_pct: Optional[float] = None
    token_efficiency_change_pct: Optional[float] = None

class ProposalCreate(BaseModel):
    type: str  # "code_change", "config_update", "feature_flag", "prompt_optimization"
    scope: ProposalScope
    changes: ProposalChanges
    rollback_condition: RollbackCondition
    rationale: str
    risk_level: str = "medium"  # "low", "medium", "high"
    estimated_impact: Optional[EstimatedImpact] = None

class ApprovalRequest(BaseModel):
    approved: bool
    comment: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None

class ExecutionRequest(BaseModel):
    approval_token: str
    execute_now: bool = True

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_proposals() -> Dict[str, Any]:
    """Load proposals from storage"""
    if os.path.exists(PROPOSALS_FILE):
        with open(PROPOSALS_FILE, 'r') as f:
            return json.load(f)
    return {"proposals": []}


def _record_approval_latency(proposal: Dict[str, Any], decision: str, tier: str = "gate_b") -> None:
    created_at = proposal.get("created_at")
    if not created_at:
        return
    try:
        created_ts = datetime.fromisoformat(created_at)
        latency = max(0.0, (datetime.utcnow() - created_ts).total_seconds())
        metrics.AUTONOMOUS_APPROVAL_LATENCY_SECONDS.labels(decision=decision, tier=tier).observe(latency)
    except Exception:
        logger.exception("Failed to record approval latency", extra={"proposal_id": proposal.get("proposal_id")})

def save_proposals(proposals: Dict[str, Any]):
    """Save proposals to storage"""
    with open(PROPOSALS_FILE, 'w') as f:
        json.dump(proposals, f, indent=2)

def generate_approval_token(proposal_id: str, timestamp: str, approver: str) -> str:
    """Generate HMAC signature for approval"""
    msg = f"{proposal_id}|{timestamp}|{approver}".encode()
    return f"sig_{hmac.new(APPROVAL_SECRET.encode(), msg, hashlib.sha256).hexdigest()}"

def verify_approval_token(approval_token: str, proposal_id: str, timestamp: str, approver: str) -> bool:
    """Verify HMAC signature"""
    expected = generate_approval_token(proposal_id, timestamp, approver)
    return hmac.compare_digest(approval_token, expected)


def _extract_approver_from_bearer(authorization: str) -> str:
    """Best-effort approver extraction from bearer token payload."""
    default_approver = os.getenv("GATE_B_DEFAULT_APPROVER", "unknown_approver")

    try:
        token = authorization.split(" ", 1)[1].strip()
    except Exception:
        return default_approver

    # JWT structure: header.payload.signature
    if token.count(".") != 2:
        return default_approver

    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
    except Exception:
        return default_approver

    for key in ("email", "upn", "preferred_username", "sub"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return default_approver

def get_proposal_by_id(proposal_id: str) -> Optional[Dict]:
    """Retrieve a proposal by ID"""
    proposals = load_proposals()
    for p in proposals.get("proposals", []):
        if p.get("proposal_id") == proposal_id:
            return p
    return None

def generate_proposal_id(proposal_type: str) -> str:
    """Generate unique proposal ID"""
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"jarvis-{proposal_type[:3]}-{timestamp}-{os.urandom(2).hex()}"

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/proposals")
async def create_proposal(
    proposal_data: ProposalCreate,
    authorization: Optional[str] = Header(None)
):
    """
    Create a new proposal for change.
    Jarvis calls this to propose changes (code, config, features, prompts).
    """
    # Verify authorization (simple for now - check for Bearer token)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    # Check rate limit
    proposals = load_proposals()
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    recent = [p for p in proposals.get("proposals", []) 
              if p.get("created_at", "") > one_hour_ago and p.get("proposed_by") == "jarvis"]
    if len(recent) >= MAX_PROPOSALS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: max {MAX_PROPOSALS_PER_HOUR} proposals per hour"
        )
    
    # Generate ID and create proposal
    proposal_id = generate_proposal_id(proposal_data.type)
    now = datetime.utcnow().isoformat()
    
    # Add preview if not provided
    preview = proposal_data.changes.preview
    if not preview and len(proposal_data.changes.content) > 500:
        preview = proposal_data.changes.content[:500] + "..."
    
    new_proposal = {
        "proposal_id": proposal_id,
        "type": proposal_data.type,
        "scope": proposal_data.scope.dict(),
        "changes": {
            **proposal_data.changes.dict(),
            "preview": preview
        },
        "rollback_condition": proposal_data.rollback_condition.dict(),
        "rationale": proposal_data.rationale,
        "risk_level": proposal_data.risk_level,
        "estimated_impact": proposal_data.estimated_impact.dict() if proposal_data.estimated_impact else None,
        "created_at": now,
        "proposed_by": "jarvis",
        "status": "awaiting_approval",
        "version": "1.0"
    }
    
    # Save
    proposals["proposals"].append(new_proposal)
    save_proposals(proposals)

    metrics.AUTONOMOUS_ACTIONS_TOTAL.labels(
        action="proposal",
        tier="gate_b",
        status="created"
    ).inc()
    
    logger.info(f"Proposal created: {proposal_id}", extra={
        "proposal_id": proposal_id,
        "type": proposal_data.type,
        "status": "awaiting_approval"
    })
    
    return {
        "success": True,
        "proposal_id": proposal_id,
        "status": "awaiting_approval",
        "message": f"Proposal {proposal_id} created. Awaiting human approval."
    }

@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str):
    """
    Retrieve a proposal for human review.
    Human uses this to see what Jarvis is proposing.
    """
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    
    return proposal

@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    approval_req: ApprovalRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Approve a proposal.
    Human calls this to grant execution authority.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    approver = _extract_approver_from_bearer(authorization)
    
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    
    if proposal.get("status") != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal status is {proposal['status']}, not awaiting_approval"
        )
    
    now = datetime.utcnow().isoformat()
    
    if not approval_req.approved:
        # Rejection
        proposal["status"] = "rejected"
        proposal["approved_at"] = now
        proposal["approver"] = approver
        proposal["rejection_reason"] = approval_req.comment or "No reason provided"
        
        proposals = load_proposals()
        for i, p in enumerate(proposals["proposals"]):
            if p["proposal_id"] == proposal_id:
                proposals["proposals"][i] = proposal
                break
        save_proposals(proposals)

        metrics.AUTONOMOUS_APPROVAL_DECISIONS.labels(decision="rejected", tier="gate_b").inc()
        metrics.AUTONOMOUS_ACTIONS_TOTAL.labels(action="proposal", tier="gate_b", status="rejected").inc()
        _record_approval_latency(proposal, decision="rejected")
        
        logger.info(f"Proposal rejected: {proposal_id}", extra={"approver": approver})
        
        return {
            "proposal_id": proposal_id,
            "approval_status": "rejected",
            "message": f"Proposal rejected: {approval_req.comment}"
        }
    
    # Approval
    approval_token = generate_approval_token(proposal_id, now, approver)
    
    proposal["status"] = "approved"
    proposal["approved_at"] = now
    proposal["approver"] = approver
    proposal["approval_token"] = approval_token
    proposal["approval_conditions"] = approval_req.conditions or {}
    
    proposals = load_proposals()
    for i, p in enumerate(proposals["proposals"]):
        if p["proposal_id"] == proposal_id:
            proposals["proposals"][i] = proposal
            break
    save_proposals(proposals)

    metrics.AUTONOMOUS_APPROVAL_DECISIONS.labels(decision="approved", tier="gate_b").inc()
    metrics.AUTONOMOUS_ACTIONS_TOTAL.labels(action="proposal", tier="gate_b", status="approved").inc()
    _record_approval_latency(proposal, decision="approved")
    
    logger.info(f"Proposal approved: {proposal_id}", extra={
        "approver": approver,
        "approval_token": approval_token[:20] + "..."
    })
    
    return {
        "proposal_id": proposal_id,
        "approval_status": "approved",
        "approval_token": approval_token,
        "message": f"Proposal approved. Ready for execution.",
        "approval_expires_at": (datetime.utcnow() + timedelta(hours=2)).isoformat()
    }

@router.post("/proposals/{proposal_id}/execute")
async def execute_proposal(
    proposal_id: str,
    exec_req: ExecutionRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Execute an approved proposal.
    Jarvis calls this after getting approval to apply changes + monitor metrics.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    
    if proposal.get("status") != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be approved before execution. Current status: {proposal['status']}"
        )
    
    # Verify approval token
    approval_token = proposal.get("approval_token")
    if not exec_req.approval_token:
        raise HTTPException(status_code=400, detail="Approval token required for execution")
    
    if not hmac.compare_digest(exec_req.approval_token, approval_token):
        raise HTTPException(status_code=403, detail="Invalid approval token")
    
    # Check if approval expired (2 hour window)
    approved_at_raw = proposal.get("approved_at")
    if not approved_at_raw:
        raise HTTPException(status_code=400, detail="Proposal is missing approved_at timestamp")
    try:
        approved_at = datetime.fromisoformat(approved_at_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Proposal has invalid approved_at timestamp")

    if datetime.utcnow() - approved_at > timedelta(hours=2):
        raise HTTPException(status_code=400, detail="Approval expired (> 2 hours old)")
    
    # Mark as executing
    now = datetime.utcnow().isoformat()
    proposal["status"] = "executing"
    proposal["execution"] = {
        "started_at": now,
        "changes_applied": [],
        "rollback_armed": True,
        "monitoring_until": (datetime.utcnow() + timedelta(seconds=ROLLBACK_WINDOW_SECONDS)).isoformat(),
        "status": "executing"
    }
    
    proposals = load_proposals()
    for i, p in enumerate(proposals["proposals"]):
        if p["proposal_id"] == proposal_id:
            proposals["proposals"][i] = proposal
            break
    save_proposals(proposals)

    metrics.AUTONOMOUS_ACTIONS_TOTAL.labels(action="execution", tier="gate_b", status="started").inc()
    
    logger.info(f"Proposal executing: {proposal_id}", extra={
        "rollback_armed": True,
        "monitoring_seconds": ROLLBACK_WINDOW_SECONDS
    })
    
    # TODO: In real implementation, would apply changes here and trigger monitoring loop
    # For now, return execution started response
    return {
        "proposal_id": proposal_id,
        "execution_status": "executing",
        "monitoring_until": proposal["execution"]["monitoring_until"],
        "changes_applied": [],
        "rollback_armed": True,
        "message": "Execution started. Monitoring metrics for 60 seconds."
    }

@router.get("/proposals/{proposal_id}/status")
async def get_execution_status(proposal_id: str):
    """
    Check the status of a proposal (proposal + execution status).
    Anyone can check status for observability.
    """
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    
    return {
        "proposal_id": proposal_id,
        "type": proposal.get("type"),
        "status": proposal.get("status"),
        "created_at": proposal.get("created_at"),
        "approved_at": proposal.get("approved_at"),
        "execution": proposal.get("execution"),
        "rollback_condition": proposal.get("rollback_condition"),
        "rationale": proposal.get("rationale")
    }

@router.get("/proposals")
async def list_proposals(
    status: Optional[str] = None,
    proposed_by: Optional[str] = None,
    limit: int = 20
):
    """
    List all proposals with optional filtering.
    For human review and observability.
    """
    proposals = load_proposals()
    result = proposals.get("proposals", [])
    
    if status:
        result = [p for p in result if p.get("status") == status]
    if proposed_by:
        result = [p for p in result if p.get("proposed_by") == proposed_by]
    
    # Return most recent first, limited
    return {
        "count": len(result),
        "proposals": sorted(
            result,
            key=lambda p: p.get("created_at", ""),
            reverse=True
        )[:limit]
    }

# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def gate_b_health():
    """Health check for Gate B system"""
    try:
        proposals = load_proposals()
        return {
            "status": "healthy",
            "proposals_total": len(proposals.get("proposals", [])),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Gate B health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
