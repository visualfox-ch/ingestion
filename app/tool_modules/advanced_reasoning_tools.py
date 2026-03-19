"""
Advanced Reasoning Tools - Phase 21 Option 3B

Tools for multi-step reasoning with intermediate validation.
"""
from typing import Dict, Any, Optional

from ..observability import get_logger

logger = get_logger("jarvis.tools.advanced_reasoning")


def decompose_complex_question(
    query: Optional[str] = None,
    context: Optional[str] = None,
    question: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Decompose a complex question into reasoning steps.

    Use this for questions that require multi-step reasoning,
    comparisons, causal analysis, or strategic planning.

    Args:
        query: The complex question to decompose
        question: Alias for query (accepted for compatibility)
        context: Additional context

    Returns:
        Dict with reasoning plan and steps
    """
    try:
        if not query:
            query = question
        if not query:
            return {"success": False, "error": "missing query/question"}

        from ..services.advanced_reasoning import get_advanced_reasoning_service

        service = get_advanced_reasoning_service()
        plan = service.decompose_question(query, context)

        result = {
            "success": True,
            "plan": service.get_plan_summary(plan),
            "step_count": len(plan.steps)
        }

        # Format for easy reading
        formatted = f"\n**Reasoning Plan für:** {query[:80]}...\n\n"
        formatted += f"**Ziel:** {plan.goal}\n\n"
        formatted += "**Schritte:**\n"
        for step in plan.steps:
            deps = f" (abhängig von: {step.dependencies})" if step.dependencies else ""
            formatted += f"{step.id}. {step.description}{deps}\n"
            formatted += f"   → Aktion: {step.action}\n"

        result["formatted"] = formatted
        result["_plan_object"] = plan  # For use in execute

        return result

    except Exception as e:
        logger.error(f"Failed to decompose question: {e}")
        return {"success": False, "error": str(e)}


def execute_reasoning_plan(
    query: str,
    validate_each_step: bool = True
) -> Dict[str, Any]:
    """
    Execute a complete reasoning plan with validation.

    Decomposes the question, executes each step, validates results,
    and synthesizes the final answer.

    Use this for complex questions requiring structured reasoning.

    Args:
        query: The complex question to reason through
        validate_each_step: Whether to validate each step

    Returns:
        Dict with reasoning results and final answer
    """
    try:
        from ..services.advanced_reasoning import get_advanced_reasoning_service

        service = get_advanced_reasoning_service()

        # Create plan
        plan = service.decompose_question(query)

        # Execute plan
        plan = service.execute_plan(plan)

        # Get summary
        summary = service.get_plan_summary(plan)

        result = {
            "success": plan.status == "completed",
            "status": plan.status,
            "final_answer": plan.final_answer,
            "summary": summary
        }

        # Format for easy reading
        formatted = f"\n**Reasoning für:** {query[:60]}...\n\n"
        formatted += f"**Status:** {plan.status}\n"
        formatted += f"**Schritte:** {summary['steps_completed']}/{summary['steps_total']} abgeschlossen\n\n"

        if plan.final_answer:
            formatted += f"**Antwort:** {plan.final_answer}\n"

        if summary.get("steps_failed", 0) > 0:
            formatted += "\n**Fehlgeschlagene Schritte:**\n"
            for step in summary.get("steps", []):
                if step["status"] == "failed":
                    formatted += f"- Schritt {step['id']}: {step['error']}\n"

        result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to execute reasoning plan: {e}")
        return {"success": False, "error": str(e)}


def reason_step_by_step(
    query: str,
    steps: Optional[int] = None
) -> Dict[str, Any]:
    """
    Perform step-by-step reasoning, showing intermediate results.

    Use this when you want to see the reasoning process in detail.

    Args:
        query: The question to reason about
        steps: Maximum number of steps (None for all)

    Returns:
        Dict with step-by-step reasoning
    """
    try:
        from ..services.advanced_reasoning import get_advanced_reasoning_service

        service = get_advanced_reasoning_service()

        # Create and execute plan
        plan = service.decompose_question(query)

        # Limit steps if requested
        if steps and steps < len(plan.steps):
            plan.steps = plan.steps[:steps]

        plan = service.execute_plan(plan)

        # Build detailed step-by-step output
        step_outputs = []
        for step in plan.steps:
            step_output = {
                "step": step.id,
                "description": step.description,
                "action": step.action,
                "status": step.status.value,
                "result": step.result,
                "validation": step.validation_result,
                "error": step.error
            }
            step_outputs.append(step_output)

        result = {
            "success": plan.status == "completed",
            "query": query,
            "steps": step_outputs,
            "final_answer": plan.final_answer
        }

        # Format for reading
        formatted = f"\n**Schrittweises Reasoning:**\n\n"
        for so in step_outputs:
            status_emoji = {
                "completed": "✅",
                "failed": "❌",
                "running": "🔄",
                "pending": "⏳",
                "skipped": "⏭️"
            }.get(so["status"], "❓")

            formatted += f"{status_emoji} **Schritt {so['step']}:** {so['description']}\n"
            if so.get("result"):
                formatted += f"   Ergebnis: {str(so['result'])[:100]}...\n"
            if so.get("error"):
                formatted += f"   Fehler: {so['error']}\n"
            formatted += "\n"

        if plan.final_answer:
            formatted += f"**Fazit:** {plan.final_answer}\n"

        result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed step-by-step reasoning: {e}")
        return {"success": False, "error": str(e)}


def validate_my_reasoning(
    conclusion: str,
    premises: list,
    reasoning_type: str = "deductive"
) -> Dict[str, Any]:
    """
    Validate a reasoning chain.

    Use this to check if your reasoning is sound before presenting
    a conclusion.

    Args:
        conclusion: The conclusion reached
        premises: List of premises/facts used
        reasoning_type: Type of reasoning (deductive, inductive, abductive)

    Returns:
        Dict with validation results
    """
    try:
        validation_result = {
            "success": True,
            "conclusion": conclusion,
            "premises_count": len(premises),
            "reasoning_type": reasoning_type,
            "checks": []
        }

        issues = []
        score = 1.0

        # Check 1: Are there enough premises?
        if len(premises) < 2:
            issues.append("Wenige Prämissen - Schlussfolgerung könnte schwach fundiert sein")
            score -= 0.2

        # Check 2: Is the conclusion non-empty?
        if not conclusion or len(conclusion) < 10:
            issues.append("Schlussfolgerung zu kurz oder leer")
            score -= 0.3

        # Check 3: Reasoning type appropriateness
        if reasoning_type == "deductive" and len(premises) < 2:
            issues.append("Deduktives Reasoning benötigt mindestens 2 Prämissen")
            score -= 0.2

        validation_result["checks"] = [
            {"check": "premise_count", "passed": len(premises) >= 2},
            {"check": "conclusion_quality", "passed": len(conclusion) >= 10},
            {"check": "reasoning_type_match", "passed": reasoning_type in ["deductive", "inductive", "abductive"]}
        ]

        validation_result["issues"] = issues
        validation_result["score"] = max(0, round(score, 2))
        validation_result["is_valid"] = score >= 0.7

        # Format
        formatted = f"\n**Reasoning-Validierung:**\n\n"
        formatted += f"Typ: {reasoning_type}\n"
        formatted += f"Prämissen: {len(premises)}\n"
        formatted += f"Score: {validation_result['score']}\n"
        formatted += f"Gültig: {'✅ Ja' if validation_result['is_valid'] else '❌ Nein'}\n"

        if issues:
            formatted += "\n**Probleme:**\n"
            for issue in issues:
                formatted += f"- {issue}\n"

        validation_result["formatted"] = formatted

        return validation_result

    except Exception as e:
        logger.error(f"Failed to validate reasoning: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
TOOLS = [
    {
        "name": "decompose_complex_question",
        "description": "Decompose a complex question into reasoning steps. Use for multi-step reasoning, comparisons, or strategic planning.",
        "function": decompose_complex_question,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The complex question to decompose"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context"
                }
            },
            "required": ["query"]
        },
        "category": "reasoning",
        "risk_tier": 0
    },
    {
        "name": "execute_reasoning_plan",
        "description": "Execute a complete reasoning plan with validation. Synthesizes final answer from multiple steps.",
        "function": execute_reasoning_plan,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The complex question to reason through"
                },
                "validate_each_step": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to validate each step"
                }
            },
            "required": ["query"]
        },
        "category": "reasoning",
        "risk_tier": 0
    },
    {
        "name": "reason_step_by_step",
        "description": "Perform step-by-step reasoning showing intermediate results",
        "function": reason_step_by_step,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to reason about"
                },
                "steps": {
                    "type": "integer",
                    "description": "Maximum number of steps"
                }
            },
            "required": ["query"]
        },
        "category": "reasoning",
        "risk_tier": 0
    },
    {
        "name": "validate_my_reasoning",
        "description": "Validate a reasoning chain before presenting a conclusion",
        "function": validate_my_reasoning,
        "parameters": {
            "type": "object",
            "properties": {
                "conclusion": {
                    "type": "string",
                    "description": "The conclusion reached"
                },
                "premises": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of premises/facts used"
                },
                "reasoning_type": {
                    "type": "string",
                    "enum": ["deductive", "inductive", "abductive"],
                    "default": "deductive",
                    "description": "Type of reasoning"
                }
            },
            "required": ["conclusion", "premises"]
        },
        "category": "reasoning",
        "risk_tier": 0
    }
]
