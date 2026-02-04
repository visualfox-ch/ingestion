"""
Pydantic Validation Schemas for Remediation API

Phase 16.3: Automated Remediation Infrastructure
Provides input validation for all remediation-related API endpoints.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class ApprovalDecisionRequest(BaseModel):
    """
    Validates remediation approval requests.

    Ensures:
    - user_id is alphanumeric with allowed special chars
    - reason is limited to 500 chars
    - idempotency_key is valid UUID (optional for backwards compat)
    """
    user_id: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="User ID making the approval (email or username)"
    )
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Approval reason/comment (max 500 chars)"
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="UUID v4 for request deduplication (optional)"
    )

    @field_validator('user_id')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """User ID must be alphanumeric with @, _, -, ."""
        if not re.match(r'^[a-zA-Z0-9@._-]+$', v):
            raise ValueError("user_id must contain only letters, numbers, @, ., _, -")
        return v.lower().strip()

    @field_validator('reason')
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        """Reason cannot be whitespace-only if provided."""
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
        return v

    @field_validator('idempotency_key')
    @classmethod
    def validate_idempotency_key(cls, v: Optional[str]) -> Optional[str]:
        """Idempotency key must be valid UUID v4 format if provided."""
        if v is not None:
            # UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
            uuid_pattern = re.compile(
                r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$',
                re.IGNORECASE
            )
            if not uuid_pattern.match(v):
                raise ValueError("idempotency_key must be a valid UUID v4")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "micha",
                    "reason": "Verified cache is stale and safe to clear",
                    "idempotency_key": "550e8400-e29b-41d4-a716-446655440000"
                }
            ]
        }
    }


class RejectionDecisionRequest(BaseModel):
    """
    Validates remediation rejection requests.

    Rejection requires a reason (unlike approval).
    """
    user_id: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="User ID making the rejection"
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Rejection reason (required, 5-500 chars)"
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="UUID v4 for request deduplication (optional)"
    )

    @field_validator('user_id')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """User ID must be alphanumeric with @, _, -, ."""
        if not re.match(r'^[a-zA-Z0-9@._-]+$', v):
            raise ValueError("user_id must contain only letters, numbers, @, ., _, -")
        return v.lower().strip()

    @field_validator('reason')
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Reason must be meaningful (not just whitespace)."""
        v = v.strip()
        if len(v) < 5:
            raise ValueError("rejection reason must be at least 5 characters")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "micha",
                    "reason": "Not safe to execute during peak hours",
                    "idempotency_key": "550e8400-e29b-41d4-a716-446655440001"
                }
            ]
        }
    }


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class PendingApprovalItem(BaseModel):
    """A single pending approval item."""
    remediation_id: str
    playbook: str
    tier: int
    trigger_condition: Optional[str] = None
    trigger_timestamp: str
    metrics_before: Dict[str, Any] = Field(default_factory=dict)
    hours_pending: float


class PendingApprovalResponse(BaseModel):
    """Response format for pending approvals endpoint."""
    status: str = "success"
    count: int
    pending: List[PendingApprovalItem]
    timestamp: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "count": 2,
                "pending": [
                    {
                        "remediation_id": "rem-20260201-001",
                        "playbook": "cache_invalidation",
                        "tier": 2,
                        "trigger_condition": "cache_hit_rate < 0.5",
                        "trigger_timestamp": "2026-02-01T10:30:00Z",
                        "metrics_before": {"cache_hit_rate": 0.45},
                        "hours_pending": 2.5
                    }
                ],
                "timestamp": "2026-02-01T13:00:00Z"
            }
        }
    }


class RecentRemediationItem(BaseModel):
    """A single recent remediation item."""
    remediation_id: str
    playbook: str
    tier: int
    status: Optional[str] = None
    started_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    improvement_pct: Optional[float] = None
    rolled_back: Optional[bool] = False
    escalated: Optional[bool] = False
    created_at: str


class RecentRemediationResponse(BaseModel):
    """Response format for recent remediations endpoint."""
    status: str = "success"
    count: int
    days: int
    recent: List[RecentRemediationItem]
    timestamp: str


class PlaybookStats(BaseModel):
    """Statistics for a single playbook."""
    playbook: str
    total_attempts: int
    successful: int
    rolled_back: int
    failed: int
    success_rate_pct: float
    avg_duration_seconds: Optional[float] = None
    avg_improvement_pct: Optional[float] = None


class RemediationStatsResponse(BaseModel):
    """Response format for remediation stats endpoint."""
    status: str = "success"
    playbooks: List[PlaybookStats]
    summary: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "playbooks": [
                    {
                        "playbook": "cache_invalidation",
                        "total_attempts": 15,
                        "successful": 14,
                        "rolled_back": 1,
                        "failed": 0,
                        "success_rate_pct": 93.33,
                        "avg_duration_seconds": 45.2,
                        "avg_improvement_pct": 35.5
                    }
                ],
                "summary": {
                    "total_remediations": 15,
                    "overall_success_rate": 93.33
                },
                "timestamp": "2026-02-01T13:00:00Z"
            }
        }
    }


class ApprovalResultResponse(BaseModel):
    """Response format for approval/rejection actions."""
    status: str
    remediation_id: str
    action: str  # 'approved' or 'rejected'
    by: str
    reason: Optional[str] = None
    timestamp: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "remediation_id": "rem-20260201-001",
                "action": "approved",
                "by": "micha",
                "reason": "Verified safe to execute",
                "timestamp": "2026-02-01T13:05:00Z"
            }
        }
    }
