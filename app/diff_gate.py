"""
Diff Gate Validator (Phase 0 Approval Gate)

Purpose:
  Enforce diff-first principle: no code write without explicit diff review + approval.
  
  1. Generate diff (human-readable)
  2. Request approval via Telegram
  3. Wait for decision (SLA: 15 min business hours)
  4. Execute only if approved
  5. Log decision immutably

Safety:
  - Diff preview in Telegram card (7 lines max)
  - Immutable audit trail
  - SLA enforcement (timeout → auto-reject)
  - Risk classification (R0–R3)

References:
  - APPROVAL_WORKFLOW_SPEC.md (Telegram card format)
  - AUTONOMOUS_WRITE_SAFETY_BASELINE.md (Tier 1/2 approvals)
  - JARVIS_SELF_IMPROVEMENT_PROTOCOL.md (Propose → Review → Execute)
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import uuid
import logging
import hashlib
import json

from .audit_trail import AuditTrail
from .permission_matrix import PermissionMatrix, RiskLevel
from .risk_models import RiskClass
from .risk_models import RiskClass
from .approval_auto import AutoApprovalEngine, ApprovalDecision
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.diff_gate")


@dataclass
class CodeChange:
    """A proposed code change awaiting approval."""
    id: str
    file_path: str
    change_type: str  # "config", "optimization", "refactor", "feature", "docs"
    diff_preview: str  # First 500 chars of diff
    full_diff: str  # Complete diff (for audit)
    risk_class: RiskClass
    description: str  # 1-sentence summary
    line_count: int


@dataclass
class ApprovalRequest:
    """Telegram approval card."""
    request_id: str
    change: CodeChange
    diff_preview: str  # Truncated for Telegram (7 lines max)
    confidence_score: Optional[float] = None  # From JarvisConfidenceScorer
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    timeout_sec: int = 900  # 15 minutes for business hours


@dataclass
class ApprovalResult:
    """Result of approval request."""
    request_id: str
    approved: bool
    approver: str  # "manual_approve", "manual_reject", "auto_reject_timeout", etc.
    feedback: Optional[str] = None
    decided_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    audit_hash: str = ""  # SHA256 of decision trail


class DiffGateValidator:
    """
    Enforce diff-first approval gate before any code write.
    
    Phase 0 (Feb 4-9): All writes require manual approval
    Phase 1+ (Feb 10+): Conditional auto-approval based on confidence
    """
    
    def __init__(self, telegram_client=None, approval_store=None, audit_log=None):
        """
        Args:
            telegram_client: TelegramBot instance for sending approval cards
            approval_store: Store for tracking approval requests (Redis)
            audit_log: Immutable audit log backend
        """
        self.telegram_client = telegram_client
        self.approval_store = approval_store
        self.audit_log = audit_log
    
    async def validate_and_request_approval(
        self,
        change: CodeChange,
        confidence_score: Optional[float] = None,
        current_phase: Optional[int] = None
    ) -> ApprovalResult:
        """
        Core gate: diff-first + approval required.
        
        Flow:
          1. Validate change (size, risk class, file path)
          2. Build Telegram approval card
          3. Send to user
          4. Wait for response (SLA: 15 min business hours)
          5. Log decision immutably
          6. Return approval result
        
        Args:
            change: The code change being proposed
            confidence_score: Jarvis' confidence (0.0–1.0)
            current_phase: Current autonomy phase (0=manual, 1+=conditional, 2+=auto). If None, uses hot config.
        
        Returns:
            ApprovalResult (approved=True/False)
        """
        
        request_id = str(uuid.uuid4())
        
        # Step 1: Validate change
        validation = self._validate_change(change)
        if not validation["valid"]:
            logger.warning(
                f"Change validation failed: {validation['reason']}",
                extra={"request_id": request_id, "change_id": change.id}
            )
            return ApprovalResult(
                request_id=request_id,
                approved=False,
                approver="auto_reject_validation",
                feedback=f"Change rejected: {validation['reason']}"
            )
        
        # Step 1b: Phase 1 - Check for conditional auto-approval
        effective_phase = current_phase
        if effective_phase is None:
            effective_phase = AutoApprovalEngine._get_runtime_phase()

        if effective_phase >= 1:
            auto_decision, auto_reason = AutoApprovalEngine.should_auto_approve(
                change_id=change.id,
                audit_id=request_id,  # Use request_id as temp audit_id
                risk_level=change.risk_class,
                confidence_score=confidence_score or 0.0,
                user_id=None,  # Will be updated by caller if available
                phase=effective_phase
            )
            
            if auto_decision == ApprovalDecision.AUTO_APPROVED:
                log_with_context(
                    logger, "info",
                    "Phase 1: Auto-approval granted",
                    change_id=change.id,
                    confidence=f"{confidence_score:.1%}" if confidence_score else "unknown",
                    risk=change.risk_class.value,
                    reason=auto_reason
                )
                
                # Return immediate approval (auto-approved)
                return ApprovalResult(
                    request_id=request_id,
                    approved=True,
                    approver="phase_1_auto_approval",
                    feedback=f"Auto-approved: {auto_reason}"
                )
            
            elif auto_decision == ApprovalDecision.QUEUED:
                log_with_context(
                    logger, "info",
                    "Phase 1: Approval queued for business hours",
                    change_id=change.id,
                    reason=auto_reason
                )
                
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    approver="queued_off_hours",
                    feedback=f"Queued: {auto_reason}"
                )
            
            # Otherwise continue to manual approval (auto_decision == ApprovalDecision.MANUAL_REQUIRED)
        
        # Step 2: Build approval card
        card = self._build_approval_card(
            change=change,
            request_id=request_id,
            confidence_score=confidence_score
        )
        
        # Step 3: Send to Telegram
        if self.telegram_client:
            try:
                await self.telegram_client.send_approval_request(
                    card=card,
                    request_id=request_id,
                    timeout_sec=900  # 15 min
                )
                logger.info(
                    "Approval card sent to Telegram",
                    extra={"request_id": request_id, "change_id": change.id}
                )
            except Exception as e:
                logger.error(
                    f"Failed to send approval card: {e}",
                    extra={"request_id": request_id}
                )
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    approver="auto_reject_telegram_error",
                    feedback="Failed to send approval request"
                )
        
        # Step 4: Wait for response (SLA: 15 min)
        result = await self._wait_for_decision(request_id, timeout_sec=900)
        
        # Step 5: Map risk class to permission matrix
        # Escalate approval tier based on risk and user role
        risk_context = {
            "action": "code_write",
            "file_path": change.file_path,
            "lines_changed": change.line_count,
            "reversible": True if change.risk_class in (RiskClass.R0, RiskClass.R1) else False,
            "data_type": "code"
        }
        
        # Get escalated permission tier (0=no user context, use base tier)
        perm_result = PermissionMatrix.check_permission_with_context(
            action="code_write",
            user_id=None,  # Will be updated by Telegram handler with actual user ID
            context=risk_context
        )
        
        # Step 6: Log decision immutably with permission context
        # Record decision to audit trail (Gate A compliance)
        decision_str = "approved" if result.approved else "rejected"
        sla_seconds = int((datetime.utcnow() - datetime.fromisoformat(result.decided_at.replace('Z', '+00:00'))).total_seconds())
        
        audit_id = AuditTrail.record_decision(
            request_id=request_id,
            change_id=change.id,
            decision=decision_str,
            approver_id=0,  # Will be updated by Telegram handler with actual user ID
            approver_name=result.approver,
            risk_class=change.risk_class.value,
            diff_hash=hashlib.sha256(change.full_diff.encode()).hexdigest(),
            diff_preview=change.diff_preview,
            decision_rationale=result.feedback or "",
            decision_timestamp=datetime.utcnow(),
            sla_seconds=sla_seconds,
            sla_met=(sla_seconds <= 900)  # 15 min SLA
        )
        
        if audit_id:
            # Link permission check to approval decision (Gate B compliance)
            PermissionMatrix.log_decision_link(
                audit_id=audit_id,
                permission_result=perm_result,
                decision=decision_str
            )
            
            # Record auto-approval decision if applicable (Phase 1)
            if current_phase >= 1 and result.approver == "phase_1_auto_approval":
                AutoApprovalEngine.record_decision(
                    change_id=change.id,
                    audit_id=audit_id,
                    risk_level=change.risk_class,
                    confidence_score=confidence_score or 0.0,
                    decision=ApprovalDecision.AUTO_APPROVED,
                    reason=result.feedback or "",
                    user_role=None  # Will be populated from Telegram context
                )
            
            log_with_context(
                logger, "info",
                "Decision recorded to immutable audit trail with permission context",
                request_id=request_id,
                audit_id=audit_id,
                decision=decision_str,
                permission_tier=perm_result.get("tier"),
                risk_level=perm_result.get("risk_level"),
                confidence=f"{confidence_score:.1%}" if confidence_score else "unknown",
                auto_approved=(result.approver == "phase_1_auto_approval")
            )
        else:
            log_with_context(
                logger, "error",
                "Failed to record decision to audit trail",
                request_id=request_id
            )
        
        return result
    
    def _validate_change(self, change: CodeChange) -> Dict[str, Any]:
        """
        Validate change before approval gate.
        
        Checks:
          - File path (no secrets, no critical system files)
          - Line count (max 500 for Phase 0)
          - Risk class (valid)
        
        Returns:
            {"valid": True/False, "reason": str}
        """
        
        # Forbidden file paths (absolute no-go)
        forbidden_paths = [
            ".env",
            "secrets",
            "credentials",
            "PASSWORD",
            "docker-compose.yml",
            "Dockerfile",
            "/etc/",
            ".git/config"
        ]
        
        for forbidden in forbidden_paths:
            if forbidden.lower() in change.file_path.lower():
                return {
                    "valid": False,
                    "reason": f"File path contains forbidden pattern: {forbidden}"
                }
        
        # Line count limit (Phase 0: max 500 lines)
        if change.line_count > 500:
            return {
                "valid": False,
                "reason": f"Change too large ({change.line_count} lines, max 500)"
            }
        
        # Risk class valid?
        try:
            RiskClass[change.risk_class.name]
        except KeyError:
            return {
                "valid": False,
                "reason": f"Invalid risk class: {change.risk_class}"
            }
        
        return {"valid": True, "reason": None}
    
    def _build_approval_card(
        self,
        change: CodeChange,
        request_id: str,
        confidence_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Build Telegram approval card (card-style format).
        
        Format:
          ```
          🔒 Approval Required
          
          [Operation]: Update file X
          [Risk Level]: HIGH (R2)
          [Confidence]: 0.82 (HIGH) ← if confidence_score provided
          [Tokens]: 450 / session limit 1000
          
          Diff preview:
          ```
          ...diff...
          ```
          
          [✅ Approve] [❌ Reject] [📝 Request Changes]
          ```
        """
        
        # Truncate diff to 7 lines for Telegram readability
        diff_lines = change.diff_preview.split("\n")[:7]
        diff_preview = "\n".join(diff_lines)
        if len(change.diff_preview.split("\n")) > 7:
            diff_preview += "\n... (full diff in audit log)"
        
        # Build card
        parts = [
            "🔒 **Approval Required**",
            "",
            f"**Change:** {change.description}",
            f"**File:** `{change.file_path}`",
            f"**Risk Level:** {change.risk_class.value}",
            f"**Lines Changed:** {change.line_count}",
        ]
        
        if confidence_score is not None:
            level = "VERY LOW"
            if confidence_score >= 0.90:
                level = "VERY HIGH"
            elif confidence_score >= 0.75:
                level = "HIGH"
            elif confidence_score >= 0.50:
                level = "MEDIUM"
            elif confidence_score >= 0.25:
                level = "LOW"
            
            parts.append(f"**Confidence:** {confidence_score:.2f} ({level})")
        
        parts.extend([
            "",
            "**Diff preview:**",
            f"```\n{diff_preview}\n```",
            "",
            "**Decision options:**",
            "[✅ Approve] [❌ Reject] [📝 Request Changes]",
            f"Request ID: `{request_id}`"
        ])
        
        return {
            "request_id": request_id,
            "text": "\n".join(parts),
            "buttons": [
                {"label": "✅ Approve", "action": "approve", "request_id": request_id},
                {"label": "❌ Reject", "action": "reject", "request_id": request_id},
                {"label": "📝 Changes", "action": "request_changes", "request_id": request_id}
            ]
        }
    
    async def _wait_for_decision(self, request_id: str, timeout_sec: int = 900) -> ApprovalResult:
        """
        Wait for approval decision from user.
        
        Timeout behavior:
          - Business hours (9–18 CET): 15 min timeout
          - Off-hours: Hold until 9 AM, auto-reject after 2 hours
        
        Returns:
            ApprovalResult (approved=True/False)
        """
        
        if not self.approval_store:
            # Fallback: auto-reject if no store configured
            logger.warning(
                "No approval store configured, auto-rejecting",
                extra={"request_id": request_id}
            )
            return ApprovalResult(
                request_id=request_id,
                approved=False,
                approver="auto_reject_no_store",
                feedback="Approval store not available"
            )
        
        # Wait for decision (with timeout)
        try:
            decision = await self.approval_store.wait_for_decision(
                request_id,
                timeout_sec=timeout_sec
            )
            
            if decision is None:
                # Timeout: auto-reject
                return ApprovalResult(
                    request_id=request_id,
                    approved=False,
                    approver="auto_reject_timeout",
                    feedback=f"No response within {timeout_sec}s"
                )
            
            return ApprovalResult(
                request_id=request_id,
                approved=decision.get("approved", False),
                approver=decision.get("approver", "unknown"),
                feedback=decision.get("feedback")
            )
        
        except Exception as e:
            logger.error(
                f"Error waiting for approval decision: {e}",
                extra={"request_id": request_id}
            )
            return ApprovalResult(
                request_id=request_id,
                approved=False,
                approver="auto_reject_error",
                feedback=f"Error: {str(e)}"
            )
    
    async def execute_if_approved(
        self,
        change: CodeChange,
        approval: ApprovalResult,
        execute_fn
    ) -> Dict[str, Any]:
        """
        Execute change only if approved.
        
        Args:
            change: The code change
            approval: Result from validate_and_request_approval()
            execute_fn: Async function to execute the change
        
        Returns:
            {"success": bool, "message": str, "audit_trail": str}
        """
        
        if not approval.approved:
            return {
                "success": False,
                "message": f"Change rejected: {approval.feedback}",
                "audit_trail": approval.request_id
            }
        
        try:
            result = await execute_fn()
            
            logger.info(
                "Change executed successfully",
                extra={
                    "request_id": approval.request_id,
                    "change_id": change.id,
                    "approver": approval.approver
                }
            )
            
            return {
                "success": True,
                "message": "Change executed and deployed",
                "audit_trail": approval.request_id,
                "result": result
            }
        
        except Exception as e:
            logger.error(
                f"Change execution failed: {e}",
                extra={"request_id": approval.request_id, "change_id": change.id}
            )
            
            return {
                "success": False,
                "message": f"Execution error: {str(e)}",
                "audit_trail": approval.request_id
            }
