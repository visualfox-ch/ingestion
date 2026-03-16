"""
Verify-Before-Act Tools (Phase S2).

Disciplined flow: Plan → Execute → Verify → Handoff

Tools:
- create_action_plan: Plan an action with expected outcome
- get_action_plan: Get plan details
- start_action_execution: Mark execution as started
- record_action_result: Record actual execution result
- verify_action: Verify result against plan
- trigger_action_rollback: Rollback a failed action
- get_active_plans: List plans needing attention
- get_failed_verifications: List failed verifications
- get_verification_stats: Get overall statistics
- mark_verification_reviewed: Mark as human-reviewed
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

VERIFY_TOOLS = [
    {
        "name": "create_action_plan",
        "description": "Create a plan before executing an important action. Define what you expect to happen BEFORE doing it. Use for Tier 2+ tools or multi-step operations.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["tool_call", "multi_step", "external_api", "file_operation"],
                    "description": "Type of action"
                },
                "action_name": {
                    "type": "string",
                    "description": "Name of the tool or operation"
                },
                "action_params": {
                    "type": "object",
                    "description": "Parameters for the action"
                },
                "expected_outcome": {
                    "type": "string",
                    "description": "Human-readable description of expected result"
                },
                "expected_state": {
                    "type": "object",
                    "description": "Machine-checkable expected state (optional)"
                },
                "success_criteria": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of conditions that define success"
                },
                "rollback_plan": {
                    "type": "object",
                    "description": "How to undo the action if it fails"
                },
                "risk_tier": {
                    "type": "integer",
                    "description": "Risk level 0-3 (default 1)"
                }
            },
            "required": ["action_type", "action_name", "expected_outcome"]
        },
        "category": "verification"
    },
    {
        "name": "get_action_plan",
        "description": "Get details of an action plan by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID"
                }
            },
            "required": ["plan_id"]
        },
        "category": "verification"
    },
    {
        "name": "start_action_execution",
        "description": "Mark an action plan as started. Call this just before executing.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID to start executing"
                }
            },
            "required": ["plan_id"]
        },
        "category": "verification"
    },
    {
        "name": "record_action_result",
        "description": "Record the actual result of an action. Call this immediately after execution completes.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID"
                },
                "actual_outcome": {
                    "type": "string",
                    "description": "What actually happened"
                },
                "actual_state": {
                    "type": "object",
                    "description": "Actual resulting state"
                },
                "raw_result": {
                    "type": "object",
                    "description": "Raw result from the tool/API"
                },
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "error", "timeout"],
                    "description": "Execution status"
                },
                "error_message": {
                    "type": "string",
                    "description": "Error message if failed"
                }
            },
            "required": ["plan_id", "actual_outcome", "status"]
        },
        "category": "verification"
    },
    {
        "name": "verify_action",
        "description": "Verify that an action's result matches the expected outcome. Compares actual vs expected and takes action on discrepancy.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID to verify"
                },
                "execution_id": {
                    "type": "integer",
                    "description": "Specific execution ID (optional, uses latest)"
                }
            },
            "required": ["plan_id"]
        },
        "category": "verification"
    },
    {
        "name": "trigger_action_rollback",
        "description": "Trigger rollback for a failed action. Use when verification fails and the action needs to be undone.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID to rollback"
                },
                "reason": {
                    "type": "string",
                    "description": "Why rollback is needed"
                },
                "verification_id": {
                    "type": "integer",
                    "description": "Related verification ID (optional)"
                }
            },
            "required": ["plan_id", "reason"]
        },
        "category": "verification"
    },
    {
        "name": "get_active_plans",
        "description": "Get action plans that need attention (not yet verified or failed).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number to return (default 20)"
                }
            },
            "required": []
        },
        "category": "verification"
    },
    {
        "name": "get_failed_verifications",
        "description": "List verifications that failed and need review.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number to return (default 20)"
                }
            },
            "required": []
        },
        "category": "verification"
    },
    {
        "name": "get_verification_stats",
        "description": "Get overall verification statistics - success rates, failures, rollbacks by action type.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "verification"
    },
    {
        "name": "mark_verification_reviewed",
        "description": "Mark a failed verification as human-reviewed. Use after manually checking a discrepancy.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan ID"
                },
                "reviewer": {
                    "type": "string",
                    "description": "Who reviewed it"
                },
                "notes": {
                    "type": "string",
                    "description": "Review notes"
                }
            },
            "required": ["plan_id", "reviewer"]
        },
        "category": "verification"
    }
]


# =============================================================================
# Tool Handlers
# =============================================================================

def create_action_plan(
    action_type: str,
    action_name: str,
    expected_outcome: str,
    action_params: Optional[Dict] = None,
    expected_state: Optional[Dict] = None,
    success_criteria: Optional[List[Dict]] = None,
    rollback_plan: Optional[Dict] = None,
    risk_tier: int = 1,
    **kwargs
) -> Dict[str, Any]:
    """Create an action plan."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()

        result = service.create_plan(
            action_type=action_type,
            action_name=action_name,
            action_params=action_params or {},
            expected_outcome=expected_outcome,
            expected_state=expected_state,
            success_criteria=success_criteria,
            rollback_plan=rollback_plan,
            risk_tier=risk_tier,
            context=kwargs.get("context")
        )

        return {
            "success": True,
            **result,
            "message": f"Plan created: {result['plan_id']}. Execute, then verify."
        }
    except Exception as e:
        logger.error(f"create_action_plan failed: {e}")
        return {"success": False, "error": str(e)}


def get_action_plan(plan_id: str, **kwargs) -> Dict[str, Any]:
    """Get plan details."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        plan = service.get_plan(plan_id)

        if not plan:
            return {"error": f"Plan {plan_id} not found"}
        return plan
    except Exception as e:
        logger.error(f"get_action_plan failed: {e}")
        return {"error": str(e)}


def start_action_execution(plan_id: str, **kwargs) -> Dict[str, Any]:
    """Mark execution as started."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        exec_id = service.start_execution(plan_id)

        return {
            "success": True,
            "execution_id": exec_id,
            "plan_id": plan_id,
            "message": "Execution started. Record result when done."
        }
    except Exception as e:
        logger.error(f"start_action_execution failed: {e}")
        return {"success": False, "error": str(e)}


def record_action_result(
    plan_id: str,
    actual_outcome: str,
    status: str,
    actual_state: Optional[Dict] = None,
    raw_result: Optional[Dict] = None,
    error_message: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Record execution result."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()

        result = service.record_execution(
            plan_id=plan_id,
            actual_outcome=actual_outcome,
            actual_state=actual_state,
            raw_result=raw_result,
            status=status,
            error_message=error_message
        )

        return {
            "success": True,
            **result,
            "message": f"Result recorded. Now verify with verify_action."
        }
    except Exception as e:
        logger.error(f"record_action_result failed: {e}")
        return {"success": False, "error": str(e)}


def verify_action(
    plan_id: str,
    execution_id: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """Verify execution against plan."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()

        result = service.verify_execution(plan_id, execution_id)

        if result.get("error"):
            return {"success": False, **result}

        # Add guidance based on result
        if result.get("passed"):
            result["message"] = "Verification passed. Action completed successfully."
        else:
            action = result.get("action_taken", "manual_review")
            if action == "auto_rollback":
                result["message"] = "Verification FAILED. Auto-rollback triggered."
            elif action == "alert_user":
                result["message"] = "Verification FAILED. User has been alerted."
            else:
                result["message"] = "Verification FAILED. Manual review needed."

        return {"success": True, **result}
    except Exception as e:
        logger.error(f"verify_action failed: {e}")
        return {"success": False, "error": str(e)}


def trigger_action_rollback(
    plan_id: str,
    reason: str,
    verification_id: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """Trigger rollback."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()

        result = service.trigger_rollback(plan_id, reason, verification_id)

        return {
            "success": True,
            **result,
            "message": f"Rollback initiated for {plan_id}."
        }
    except Exception as e:
        logger.error(f"trigger_action_rollback failed: {e}")
        return {"success": False, "error": str(e)}


def get_active_plans(limit: int = 20, **kwargs) -> Dict[str, Any]:
    """Get active plans."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        plans = service.get_active_plans(limit)

        return {
            "count": len(plans),
            "plans": plans
        }
    except Exception as e:
        logger.error(f"get_active_plans failed: {e}")
        return {"error": str(e)}


def get_failed_verifications(limit: int = 20, **kwargs) -> Dict[str, Any]:
    """Get failed verifications."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        failures = service.get_failed_verifications(limit)

        return {
            "count": len(failures),
            "failures": failures,
            "message": f"{len(failures)} verifications need review."
        }
    except Exception as e:
        logger.error(f"get_failed_verifications failed: {e}")
        return {"error": str(e)}


def get_verification_stats(**kwargs) -> Dict[str, Any]:
    """Get verification statistics."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        return service.get_verification_stats()
    except Exception as e:
        logger.error(f"get_verification_stats failed: {e}")
        return {"error": str(e)}


def mark_verification_reviewed(
    plan_id: str,
    reviewer: str,
    notes: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Mark verification as reviewed."""
    try:
        from app.services.verify_before_act import get_verify_service
        service = get_verify_service()
        return service.mark_reviewed(plan_id, reviewer, notes)
    except Exception as e:
        logger.error(f"mark_verification_reviewed failed: {e}")
        return {"success": False, "error": str(e)}


def get_verify_tools() -> List[Dict]:
    """Get all verify tool definitions."""
    return VERIFY_TOOLS
