"""
Code Writing Service Module

Phase 21: Jarvis Self-Programming - Autonomous Code Writing
Implements confidence scoring and code change proposal workflow.

Key Components:
1. calculate_confidence() - Assess confidence level for actions
2. propose_code_change() - Stage code changes for approval
3. apply_approved_change() - Execute approved changes with rollback
4. Code validation and syntax checking

Safety: All changes require human approval for confidence < 0.8
Audit trail: Every operation logged to code_write_audit.jsonl
"""

import os
import re
import json
import uuid
import subprocess
import ast
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from .observability import get_logger
from .db_safety import safe_list_query, safe_aggregate_query

logger = get_logger("jarvis.code_writing")

# Configuration
CODE_WRITE_AUDIT_PATH = os.environ.get(
    "JARVIS_CODE_WRITE_AUDIT_PATH",
    "/brain/system/logs/code_write_audit.jsonl"
)

STAGED_CHANGES_PATH = os.environ.get(
    "JARVIS_STAGED_CHANGES_PATH",
    "/brain/system/logs/staged_changes.jsonl"
)

# Allowed file paths for autonomous writing (whitelist)
ALLOWED_PATHS = [
    "/brain/system/ingestion/app/",      # Jarvis app code
    "/brain/system/docker/",              # Docker configs (non-secrets)
    "/brain/system/prompts/",             # Prompts
    "/brain/system/docs/",                # Documentation
]

# Forbidden patterns (blocklist)
FORBIDDEN_PATTERNS = [
    r"\.env",                             # Environment files
    r"secrets?",                          # Secret files
    r"password|token|key|credential",    # Credential patterns in filename
    r"docker-compose\.yml$",              # Main compose file
    r"\.pem$|\.key$",                     # Certificate files
]

# Risk levels by file path pattern
PATH_RISK_LEVELS = {
    r"/docs/": "low",
    r"/prompts/": "low",
    r"README|CHANGELOG|\.md$": "low",
    r"/app/.*_service\.py$": "medium",
    r"/app/main\.py$": "high",
    r"/app/config\.py$": "high",
    r"docker": "high",
}


class ChangeType(str, Enum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    CREATE_FILE = "create_file"


class ChangeStatus(str, Enum):
    STAGED = "staged"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


@dataclass
class CodeChange:
    """Represents a proposed code change."""
    change_id: str
    file_path: str
    change_type: ChangeType
    description: str
    code_snippet: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    justification: str
    confidence: float
    risk_level: str
    status: ChangeStatus
    preview: str
    created_at: str
    reviewed_at: Optional[str]
    reviewer: Optional[str]
    applied_at: Optional[str]
    rollback_info: Optional[Dict[str, Any]]


# =============================================================================
# 1. CONFIDENCE SCORING
# =============================================================================

def calculate_confidence(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate confidence score for an action based on multiple factors.

    Factors:
    - Context quality (source count, recency, explicit user input)
    - Historical success rate for similar actions
    - Tool/action complexity
    - User state modifier

    Returns:
        - score: 0.0-1.0 confidence value
        - category: "high", "medium", "low"
        - breakdown: Factor contributions
        - recommendation: What to do based on score
    """
    breakdown = {}

    # Base score
    base_score = 0.3
    breakdown["base"] = base_score

    # Factor 1: Context Quality (0.0-0.3)
    context_score = 0.0
    source_count = context.get('source_count', 0)
    if source_count >= 3:
        context_score += 0.15
    elif source_count >= 1:
        context_score += 0.08

    if context.get('recent_activity', False):
        context_score += 0.10

    if context.get('explicit_user_input', False):
        context_score += 0.05

    breakdown["context_quality"] = round(context_score, 3)

    # Factor 2: Historical Success (0.0-0.25)
    similar_decisions = context.get('similar_decisions', [])
    if similar_decisions:
        success_count = sum(
            1 for d in similar_decisions
            if d.get('outcome_rating', 3) >= 4
        )
        success_rate = success_count / len(similar_decisions)
        historical_score = success_rate * 0.25
    else:
        historical_score = 0.1  # Default when no history

    breakdown["historical_success"] = round(historical_score, 3)

    # Factor 3: Action Complexity (penalty: 0.0 to -0.2)
    complexity_penalties = {
        'search_knowledge': 0.0,
        'read_project_file': 0.0,
        'recall_conversation_history': 0.0,
        'remember_fact': -0.03,
        'create_calendar_event': -0.08,
        'send_telegram_message': -0.05,
        'propose_code_change': -0.15,
        'apply_code_change': -0.20,
    }

    tools_needed = context.get('tools_needed', [])
    tool_penalty = sum(
        complexity_penalties.get(tool, -0.05)
        for tool in tools_needed
    )
    tool_penalty = max(-0.2, tool_penalty)  # Cap at -0.2

    breakdown["complexity_penalty"] = round(tool_penalty, 3)

    # Factor 4: User State Modifier (±0.15)
    user_state = context.get('user_emotion', 'unknown')
    state_modifiers = {
        'calm': 0.10,
        'focused': 0.08,
        'energized': 0.05,
        'neutral': 0.0,
        'tired': -0.05,
        'stressed': -0.10,
        'frustrated': -0.05,
        'overwhelmed': -0.15,
    }

    state_modifier = state_modifiers.get(user_state, 0.0)
    breakdown["user_state"] = round(state_modifier, 3)

    # Calculate final score
    final_score = (
        base_score +
        context_score +
        historical_score +
        tool_penalty +
        state_modifier
    )
    final_score = min(1.0, max(0.0, final_score))
    final_score = round(final_score, 2)

    # Determine category and recommendation
    if final_score >= 0.8:
        category = "high"
        recommendation = "Direct action - proceed autonomously"
    elif final_score >= 0.5:
        category = "medium"
        recommendation = "Ask for confirmation before proceeding"
    else:
        category = "low"
        recommendation = "Explain reasoning and seek explicit approval"

    return {
        "score": final_score,
        "category": category,
        "breakdown": breakdown,
        "recommendation": recommendation,
        "context_summary": {
            "sources": context.get('source_count', 0),
            "tools": tools_needed,
            "user_state": user_state
        }
    }


# =============================================================================
# 2. CODE CHANGE PROPOSAL
# =============================================================================

async def propose_code_change(
    file_path: str,
    change_type: str,
    description: str,
    code_snippet: Optional[str] = None,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    justification: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Propose a code change for human review.

    Args:
        file_path: Relative path from project root
        change_type: "add", "modify", "delete", "create_file"
        description: What the change does
        code_snippet: The new code (for add/modify/create_file)
        line_start: Start line for modify/delete
        line_end: End line for modify/delete
        justification: Why this change is needed
        context: Context for confidence calculation

    Returns:
        - change_id: Unique identifier
        - status: "staged"
        - preview: Git diff-style preview
        - confidence: Calculated confidence score
        - risk_level: "low", "medium", "high"
        - validation: Syntax check results
    """
    result = {
        "status": "error",
        "change_id": None
    }

    try:
        # 1. Validate file path
        path_validation = _validate_file_path(file_path)
        if not path_validation["allowed"]:
            result["error"] = path_validation["reason"]
            return result

        # 2. Validate change type
        try:
            change_type_enum = ChangeType(change_type)
        except ValueError:
            result["error"] = f"Invalid change_type: {change_type}"
            return result

        # 3. Calculate risk level
        risk_level = _calculate_risk_level(file_path, change_type_enum)

        # 4. Calculate confidence
        ctx = context or {}
        ctx["tools_needed"] = ["propose_code_change"]
        confidence_result = calculate_confidence(ctx)
        confidence = confidence_result["score"]

        # 5. Validate code syntax if applicable
        validation = {"valid": True, "errors": []}
        if code_snippet and file_path.endswith(".py"):
            validation = _validate_python_syntax(code_snippet)

        if not validation["valid"]:
            result["status"] = "validation_failed"
            result["validation_errors"] = validation["errors"]
            return result

        # 6. Generate preview
        preview = _generate_preview(
            file_path, change_type_enum, code_snippet,
            line_start, line_end
        )

        # 7. Create change record
        change_id = f"chg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        change = CodeChange(
            change_id=change_id,
            file_path=file_path,
            change_type=change_type_enum,
            description=description,
            code_snippet=code_snippet,
            line_start=line_start,
            line_end=line_end,
            justification=justification or "No justification provided",
            confidence=confidence,
            risk_level=risk_level,
            status=ChangeStatus.STAGED,
            preview=preview,
            created_at=datetime.now().isoformat(),
            reviewed_at=None,
            reviewer=None,
            applied_at=None,
            rollback_info=None
        )

        # 8. Save to staging area
        _save_staged_change(change)

        # 9. Log to audit trail
        _log_code_action("propose", change_id, {
            "file_path": file_path,
            "change_type": change_type,
            "confidence": confidence,
            "risk_level": risk_level
        })

        # 10. Determine if auto-approval possible
        auto_approve = (
            confidence >= 0.8 and
            risk_level == "low" and
            validation["valid"]
        )

        result = {
            "status": "staged",
            "change_id": change_id,
            "file_path": file_path,
            "change_type": change_type,
            "description": description,
            "preview": preview,
            "confidence": confidence_result,
            "risk_level": risk_level,
            "validation": validation,
            "auto_approve_eligible": auto_approve,
            "next_steps": [
                f"Review change at /code/changes/{change_id}",
                f"Approve: POST /code/changes/{change_id}/approve",
                f"Reject: POST /code/changes/{change_id}/reject"
            ] if not auto_approve else [
                "Change is eligible for auto-approval",
                f"Apply: POST /code/changes/{change_id}/apply"
            ]
        }

        return result

    except Exception as e:
        logger.error(f"Error proposing code change: {e}", exc_info=True)
        result["error"] = str(e)
        return result


def _validate_file_path(file_path: str) -> Dict[str, Any]:
    """Validate that file path is allowed for modification."""
    # Normalize path
    normalized = os.path.normpath(file_path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized

    # Check against forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return {
                "allowed": False,
                "reason": f"Path matches forbidden pattern: {pattern}"
            }

    # Check against allowed paths
    for allowed in ALLOWED_PATHS:
        if normalized.startswith(allowed):
            return {"allowed": True, "reason": None}

    return {
        "allowed": False,
        "reason": f"Path not in allowed directories: {ALLOWED_PATHS}"
    }


def _calculate_risk_level(file_path: str, change_type: ChangeType) -> str:
    """Calculate risk level based on file path and change type."""
    # Check path patterns
    for pattern, level in PATH_RISK_LEVELS.items():
        if re.search(pattern, file_path, re.IGNORECASE):
            return level

    # Change type modifiers
    if change_type == ChangeType.DELETE:
        return "high"
    elif change_type == ChangeType.CREATE_FILE:
        return "medium"

    return "medium"  # Default


def _validate_python_syntax(code: str) -> Dict[str, Any]:
    """Validate Python code syntax."""
    try:
        ast.parse(code)
        return {"valid": True, "errors": []}
    except SyntaxError as e:
        return {
            "valid": False,
            "errors": [f"Line {e.lineno}: {e.msg}"]
        }


def _generate_preview(
    file_path: str,
    change_type: ChangeType,
    code_snippet: Optional[str],
    line_start: Optional[int],
    line_end: Optional[int]
) -> str:
    """Generate a git diff-style preview of the change."""
    preview_lines = []

    if change_type == ChangeType.CREATE_FILE:
        preview_lines.append(f"--- /dev/null")
        preview_lines.append(f"+++ b{file_path}")
        if code_snippet:
            for i, line in enumerate(code_snippet.split('\n'), 1):
                preview_lines.append(f"+{line}")

    elif change_type == ChangeType.ADD:
        preview_lines.append(f"--- a{file_path}")
        preview_lines.append(f"+++ b{file_path}")
        preview_lines.append(f"@@ +{line_start or 1} @@")
        if code_snippet:
            for line in code_snippet.split('\n'):
                preview_lines.append(f"+{line}")

    elif change_type == ChangeType.MODIFY:
        preview_lines.append(f"--- a{file_path}")
        preview_lines.append(f"+++ b{file_path}")
        preview_lines.append(f"@@ -{line_start or 1},{(line_end or line_start or 1) - (line_start or 1) + 1} @@")
        preview_lines.append(f"[Lines {line_start}-{line_end} will be replaced with:]")
        if code_snippet:
            for line in code_snippet.split('\n'):
                preview_lines.append(f"+{line}")

    elif change_type == ChangeType.DELETE:
        preview_lines.append(f"--- a{file_path}")
        preview_lines.append(f"+++ b{file_path}")
        preview_lines.append(f"@@ -{line_start or 1},{(line_end or line_start or 1) - (line_start or 1) + 1} @@")
        preview_lines.append(f"[Lines {line_start}-{line_end} will be deleted]")

    return '\n'.join(preview_lines)


def _save_staged_change(change: CodeChange):
    """Save a staged change to the staging file."""
    try:
        os.makedirs(os.path.dirname(STAGED_CHANGES_PATH), exist_ok=True)
        with open(STAGED_CHANGES_PATH, "a") as f:
            f.write(json.dumps(asdict(change)) + "\n")
    except Exception as e:
        logger.error(f"Failed to save staged change: {e}")


def _log_code_action(action: str, change_id: str, details: Dict[str, Any]):
    """Log a code writing action to audit trail."""
    try:
        os.makedirs(os.path.dirname(CODE_WRITE_AUDIT_PATH), exist_ok=True)
        entry = {
            "action": action,
            "change_id": change_id,
            "timestamp": datetime.now().isoformat(),
            "details": details
        }
        with open(CODE_WRITE_AUDIT_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to log code action: {e}")


# =============================================================================
# 3. CHANGE MANAGEMENT
# =============================================================================

async def get_staged_changes(
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all staged changes, optionally filtered by status."""
    changes = []

    try:
        if os.path.exists(STAGED_CHANGES_PATH):
            with open(STAGED_CHANGES_PATH, "r") as f:
                for line in f:
                    try:
                        change = json.loads(line.strip())
                        if status is None or change.get("status") == status:
                            changes.append(change)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Error reading staged changes: {e}")

    return changes


async def get_change_by_id(change_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific change by ID."""
    changes = await get_staged_changes()
    for change in changes:
        if change.get("change_id") == change_id:
            return change
    return None


async def approve_change(
    change_id: str,
    reviewer: str = "human"
) -> Dict[str, Any]:
    """Approve a staged change."""
    return await _update_change_status(
        change_id,
        ChangeStatus.APPROVED,
        reviewer=reviewer
    )


async def reject_change(
    change_id: str,
    reason: str = "",
    reviewer: str = "human"
) -> Dict[str, Any]:
    """Reject a staged change."""
    return await _update_change_status(
        change_id,
        ChangeStatus.REJECTED,
        reviewer=reviewer,
        rejection_reason=reason
    )


async def apply_change(change_id: str) -> Dict[str, Any]:
    """Apply an approved change to the actual file."""
    change = await get_change_by_id(change_id)

    if not change:
        return {"status": "error", "message": f"Change {change_id} not found"}

    if change.get("status") != ChangeStatus.APPROVED.value:
        return {
            "status": "error",
            "message": f"Change must be approved first (current: {change.get('status')})"
        }

    try:
        # Create backup
        file_path = change["file_path"]
        backup_path = None

        if os.path.exists(file_path):
            backup_path = f"{file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(file_path, "r") as f:
                original_content = f.read()
            with open(backup_path, "w") as f:
                f.write(original_content)

        # Apply change based on type
        change_type = change["change_type"]
        code_snippet = change.get("code_snippet", "")

        if change_type == ChangeType.CREATE_FILE.value:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(code_snippet)

        elif change_type == ChangeType.ADD.value:
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    lines = f.readlines()
            else:
                lines = []

            insert_at = (change.get("line_start") or len(lines) + 1) - 1
            new_lines = code_snippet.split('\n')
            for i, line in enumerate(new_lines):
                lines.insert(insert_at + i, line + '\n')

            with open(file_path, "w") as f:
                f.writelines(lines)

        elif change_type == ChangeType.MODIFY.value:
            with open(file_path, "r") as f:
                lines = f.readlines()

            start = (change.get("line_start") or 1) - 1
            end = change.get("line_end") or start + 1

            new_lines = [line + '\n' for line in code_snippet.split('\n')]
            lines[start:end] = new_lines

            with open(file_path, "w") as f:
                f.writelines(lines)

        elif change_type == ChangeType.DELETE.value:
            with open(file_path, "r") as f:
                lines = f.readlines()

            start = (change.get("line_start") or 1) - 1
            end = change.get("line_end") or start + 1

            del lines[start:end]

            with open(file_path, "w") as f:
                f.writelines(lines)

        # Update change status
        await _update_change_status(
            change_id,
            ChangeStatus.APPLIED,
            rollback_info={"backup_path": backup_path, "original_content": original_content if backup_path else None}
        )

        # Log action
        _log_code_action("apply", change_id, {
            "file_path": file_path,
            "backup_path": backup_path,
            "success": True
        })

        return {
            "status": "success",
            "message": f"Change {change_id} applied to {file_path}",
            "backup_path": backup_path,
            "next_steps": [
                "Test the changes",
                f"Rollback if needed: POST /code/changes/{change_id}/rollback"
            ]
        }

    except Exception as e:
        logger.error(f"Error applying change: {e}", exc_info=True)
        _log_code_action("apply", change_id, {
            "file_path": change["file_path"],
            "success": False,
            "error": str(e)
        })
        return {"status": "error", "message": str(e)}


async def rollback_change(change_id: str) -> Dict[str, Any]:
    """Rollback an applied change using the backup."""
    change = await get_change_by_id(change_id)

    if not change:
        return {"status": "error", "message": f"Change {change_id} not found"}

    if change.get("status") != ChangeStatus.APPLIED.value:
        return {"status": "error", "message": "Can only rollback applied changes"}

    rollback_info = change.get("rollback_info", {})
    backup_path = rollback_info.get("backup_path")

    if not backup_path or not os.path.exists(backup_path):
        return {"status": "error", "message": "No backup available for rollback"}

    try:
        # Restore from backup
        file_path = change["file_path"]
        with open(backup_path, "r") as f:
            original_content = f.read()
        with open(file_path, "w") as f:
            f.write(original_content)

        # Update status
        await _update_change_status(change_id, ChangeStatus.ROLLED_BACK)

        # Log action
        _log_code_action("rollback", change_id, {
            "file_path": file_path,
            "backup_path": backup_path,
            "success": True
        })

        return {
            "status": "success",
            "message": f"Change {change_id} rolled back",
            "restored_from": backup_path
        }

    except Exception as e:
        logger.error(f"Error rolling back change: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _update_change_status(
    change_id: str,
    new_status: ChangeStatus,
    reviewer: Optional[str] = None,
    rejection_reason: Optional[str] = None,
    rollback_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """Update the status of a staged change."""
    entries = []
    found = False

    try:
        if os.path.exists(STAGED_CHANGES_PATH):
            with open(STAGED_CHANGES_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("change_id") == change_id:
                            entry["status"] = new_status.value
                            entry["reviewed_at"] = datetime.now().isoformat()
                            if reviewer:
                                entry["reviewer"] = reviewer
                            if rejection_reason:
                                entry["rejection_reason"] = rejection_reason
                            if rollback_info:
                                entry["rollback_info"] = rollback_info
                            if new_status == ChangeStatus.APPLIED:
                                entry["applied_at"] = datetime.now().isoformat()
                            found = True
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not found:
            return {"status": "error", "message": f"Change {change_id} not found"}

        with open(STAGED_CHANGES_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        _log_code_action(new_status.value, change_id, {
            "reviewer": reviewer,
            "rejection_reason": rejection_reason
        })

        return {
            "status": "success",
            "change_id": change_id,
            "new_status": new_status.value
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# 4. DASHBOARD / SUMMARY
# =============================================================================

async def get_code_writing_dashboard() -> Dict[str, Any]:
    """Get summary of code writing activity."""
    all_changes = await get_staged_changes()

    status_counts = {}
    for change in all_changes:
        status = change.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    recent_changes = sorted(
        all_changes,
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )[:10]

    # Calculate success metrics
    applied = [c for c in all_changes if c.get("status") == "applied"]
    rolled_back = [c for c in all_changes if c.get("status") == "rolled_back"]

    success_rate = None
    if applied or rolled_back:
        success_rate = len(applied) / (len(applied) + len(rolled_back))

    return {
        "status": "success",
        "summary": {
            "total_changes": len(all_changes),
            "by_status": status_counts,
            "success_rate": round(success_rate, 3) if success_rate else None,
            "pending_review": status_counts.get("staged", 0)
        },
        "recent_changes": [
            {
                "change_id": c.get("change_id"),
                "file_path": c.get("file_path"),
                "change_type": c.get("change_type"),
                "status": c.get("status"),
                "confidence": c.get("confidence"),
                "created_at": c.get("created_at")
            }
            for c in recent_changes
        ]
    }
