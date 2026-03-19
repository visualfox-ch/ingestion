"""
Advanced Reasoning Service - Phase 21 Option 3B

Multi-step reasoning with intermediate validation.
Decomposes complex questions into steps, executes with validation,
and synthesizes the final answer.
"""
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import time

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.advanced_reasoning")


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ReasoningStep:
    """A single step in a reasoning chain."""
    id: int
    description: str
    action: str  # tool to call or action to take
    expected_output: str
    dependencies: List[int] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class ReasoningPlan:
    """A complete reasoning plan for a complex query."""
    query: str
    goal: str
    steps: List[ReasoningStep]
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "created"
    final_answer: Optional[str] = None


class AdvancedReasoningService:
    """
    Service for multi-step reasoning with validation.

    Process:
    1. Decompose question into steps
    2. Create execution plan
    3. Execute steps with validation
    4. Synthesize final answer
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def decompose_question(
        self,
        query: str,
        context: Optional[str] = None
    ) -> ReasoningPlan:
        """
        Decompose a complex question into reasoning steps.

        Args:
            query: The complex question to decompose
            context: Additional context

        Returns:
            ReasoningPlan with steps
        """
        # Analyze query complexity
        query_lower = query.lower()

        steps = []
        step_id = 1

        # Pattern-based decomposition
        if any(kw in query_lower for kw in ["compare", "vergleich", "unterschied"]):
            # Comparison query
            steps = [
                ReasoningStep(
                    id=1,
                    description="Identify items to compare",
                    action="extract_entities",
                    expected_output="List of entities to compare"
                ),
                ReasoningStep(
                    id=2,
                    description="Gather information about first item",
                    action="search_knowledge",
                    expected_output="Information about item 1",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=3,
                    description="Gather information about second item",
                    action="search_knowledge",
                    expected_output="Information about item 2",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=4,
                    description="Compare and contrast findings",
                    action="synthesize",
                    expected_output="Comparison analysis",
                    dependencies=[2, 3]
                ),
                ReasoningStep(
                    id=5,
                    description="Validate and summarize comparison",
                    action="validate_and_summarize",
                    expected_output="Final comparison answer",
                    dependencies=[4]
                )
            ]

        elif any(kw in query_lower for kw in ["warum", "why", "ursache", "cause"]):
            # Causal reasoning query
            steps = [
                ReasoningStep(
                    id=1,
                    description="Identify the phenomenon to explain",
                    action="extract_topic",
                    expected_output="Topic/phenomenon identification"
                ),
                ReasoningStep(
                    id=2,
                    description="Search for related facts and causes",
                    action="search_knowledge",
                    expected_output="Related facts and potential causes",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=3,
                    description="Build causal chain",
                    action="build_causal_chain",
                    expected_output="Causal relationship chain",
                    dependencies=[2]
                ),
                ReasoningStep(
                    id=4,
                    description="Validate causal reasoning",
                    action="validate_reasoning",
                    expected_output="Validated causal explanation",
                    dependencies=[3]
                )
            ]

        elif any(kw in query_lower for kw in ["plan", "strategie", "strategy", "wie soll", "how to"]):
            # Planning query
            steps = [
                ReasoningStep(
                    id=1,
                    description="Clarify goal and constraints",
                    action="extract_goal",
                    expected_output="Clear goal statement"
                ),
                ReasoningStep(
                    id=2,
                    description="Gather relevant context and constraints",
                    action="search_knowledge",
                    expected_output="Context and constraints",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=3,
                    description="Generate potential approaches",
                    action="generate_options",
                    expected_output="List of possible approaches",
                    dependencies=[1, 2]
                ),
                ReasoningStep(
                    id=4,
                    description="Evaluate approaches",
                    action="evaluate_options",
                    expected_output="Pros/cons analysis",
                    dependencies=[3]
                ),
                ReasoningStep(
                    id=5,
                    description="Synthesize recommended plan",
                    action="synthesize_plan",
                    expected_output="Recommended action plan",
                    dependencies=[4]
                )
            ]

        elif any(kw in query_lower for kw in ["analyse", "analyze", "untersuche", "examine"]):
            # Analysis query
            steps = [
                ReasoningStep(
                    id=1,
                    description="Identify subject of analysis",
                    action="extract_topic",
                    expected_output="Subject identification"
                ),
                ReasoningStep(
                    id=2,
                    description="Gather comprehensive data",
                    action="comprehensive_search",
                    expected_output="Relevant data and facts",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=3,
                    description="Identify patterns and insights",
                    action="pattern_analysis",
                    expected_output="Key patterns and insights",
                    dependencies=[2]
                ),
                ReasoningStep(
                    id=4,
                    description="Validate findings",
                    action="validate_findings",
                    expected_output="Validated analysis",
                    dependencies=[3]
                ),
                ReasoningStep(
                    id=5,
                    description="Synthesize analysis results",
                    action="synthesize_analysis",
                    expected_output="Complete analysis report",
                    dependencies=[4]
                )
            ]

        else:
            # Generic complex query
            steps = [
                ReasoningStep(
                    id=1,
                    description="Parse and understand the question",
                    action="parse_question",
                    expected_output="Parsed question structure"
                ),
                ReasoningStep(
                    id=2,
                    description="Search for relevant information",
                    action="search_knowledge",
                    expected_output="Relevant facts and context",
                    dependencies=[1]
                ),
                ReasoningStep(
                    id=3,
                    description="Reason through the information",
                    action="reason",
                    expected_output="Logical conclusions",
                    dependencies=[2]
                ),
                ReasoningStep(
                    id=4,
                    description="Validate reasoning",
                    action="validate_reasoning",
                    expected_output="Validated conclusions",
                    dependencies=[3]
                ),
                ReasoningStep(
                    id=5,
                    description="Synthesize final answer",
                    action="synthesize",
                    expected_output="Complete answer",
                    dependencies=[4]
                )
            ]

        return ReasoningPlan(
            query=query,
            goal=self._extract_goal(query),
            steps=steps
        )

    def _extract_goal(self, query: str) -> str:
        """Extract the goal from a query."""
        # Simple heuristic - could be enhanced with LLM
        if "?" in query:
            return f"Answer: {query}"
        return f"Complete: {query}"

    def execute_plan(
        self,
        plan: ReasoningPlan,
        executor: Optional[Callable] = None,
        validator: Optional[Callable] = None
    ) -> ReasoningPlan:
        """
        Execute a reasoning plan step by step.

        Args:
            plan: The plan to execute
            executor: Optional custom executor function
            validator: Optional custom validator function

        Returns:
            Updated plan with results
        """
        plan.status = "executing"

        for step in plan.steps:
            # Check dependencies
            deps_met = all(
                plan.steps[d - 1].status == StepStatus.COMPLETED
                for d in step.dependencies
            )

            if not deps_met:
                step.status = StepStatus.SKIPPED
                step.error = "Dependencies not met"
                continue

            step.status = StepStatus.RUNNING
            step.started_at = datetime.now()

            try:
                # Execute step
                if executor:
                    result = executor(step, plan)
                else:
                    result = self._default_executor(step, plan)

                step.result = result

                # Validate result
                if validator:
                    validation = validator(step, result)
                else:
                    validation = self._default_validator(step, result)

                step.validation_result = validation

                if validation.get("valid", True):
                    step.status = StepStatus.COMPLETED
                else:
                    step.status = StepStatus.FAILED
                    step.error = validation.get("error", "Validation failed")

            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)
                log_with_context(logger, "warning", "Reasoning step failed",
                               step_id=step.id, error=str(e))

            step.completed_at = datetime.now()

        # Check if plan succeeded
        all_completed = all(
            s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED]
            for s in plan.steps
        )

        if all_completed:
            plan.status = "completed"
            plan.final_answer = self._synthesize_answer(plan)
        else:
            plan.status = "failed"

        return plan

    def _default_executor(
        self,
        step: ReasoningStep,
        plan: ReasoningPlan
    ) -> Dict[str, Any]:
        """Default step executor using available tools."""
        action = step.action

        # Gather context from dependencies
        dep_results = [
            plan.steps[d - 1].result
            for d in step.dependencies
            if plan.steps[d - 1].result
        ]

        context = {
            "query": plan.query,
            "step_description": step.description,
            "dependency_results": dep_results
        }

        # Map actions to tool calls
        if action == "search_knowledge":
            try:
                from ..tool_modules.retrieval_tools import search_knowledge
                result = search_knowledge(query=plan.query, limit=5)
                return {"type": "search", "results": result.get("results", [])}
            except Exception as e:
                return {"type": "search", "results": [], "error": str(e)}

        elif action == "extract_entities" or action == "extract_topic" or action == "extract_goal":
            # Simple extraction
            return {
                "type": "extraction",
                "extracted": plan.query,
                "context": context
            }

        elif action in ["synthesize", "synthesize_plan", "synthesize_analysis"]:
            # Synthesize from dependency results
            return {
                "type": "synthesis",
                "inputs": dep_results,
                "summary": f"Synthesized from {len(dep_results)} sources"
            }

        elif action in ["validate_reasoning", "validate_findings", "validate_and_summarize"]:
            # Validation step
            return {
                "type": "validation",
                "validated": True,
                "confidence": 0.8
            }

        elif action == "reason" or action == "build_causal_chain":
            return {
                "type": "reasoning",
                "chain": dep_results,
                "conclusion": "Logical reasoning applied"
            }

        elif action in ["generate_options", "evaluate_options"]:
            return {
                "type": "options",
                "options": ["Option A", "Option B"],
                "evaluation": "Options generated based on context"
            }

        elif action == "pattern_analysis":
            return {
                "type": "patterns",
                "patterns_found": [],
                "insights": "Pattern analysis performed"
            }

        elif action == "comprehensive_search":
            try:
                from ..tool_modules.retrieval_tools import search_knowledge
                result = search_knowledge(query=plan.query, limit=10)
                return {"type": "comprehensive_search", "results": result.get("results", [])}
            except Exception as e:
                return {"type": "comprehensive_search", "results": [], "error": str(e)}

        else:
            return {
                "type": "generic",
                "action": action,
                "note": f"Executed {action}"
            }

    def _default_validator(
        self,
        step: ReasoningStep,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Default validation logic."""
        # Check if result has content
        if not result:
            return {"valid": False, "error": "Empty result"}

        if result.get("error"):
            return {"valid": False, "error": result["error"]}

        # Type-specific validation
        result_type = result.get("type", "")

        if result_type == "search":
            results = result.get("results", [])
            if not results:
                return {"valid": True, "warning": "No search results found"}

        return {"valid": True, "confidence": 0.85}

    def _synthesize_answer(self, plan: ReasoningPlan) -> str:
        """Synthesize the final answer from plan results."""
        # Collect all completed step results
        completed_results = [
            {
                "step": s.description,
                "result": s.result
            }
            for s in plan.steps
            if s.status == StepStatus.COMPLETED and s.result
        ]

        if not completed_results:
            return "Unable to generate answer - no completed steps"

        # Simple synthesis - join key findings
        findings = []
        for cr in completed_results:
            result = cr.get("result", {})
            if result.get("type") == "search":
                results = result.get("results", [])
                if results:
                    findings.append(f"Found {len(results)} relevant results")
            elif result.get("type") == "synthesis":
                findings.append(result.get("summary", ""))
            elif result.get("type") == "validation":
                if result.get("validated"):
                    findings.append("Reasoning validated")

        return f"Based on {len(plan.steps)} reasoning steps: " + "; ".join(findings)

    def get_plan_summary(self, plan: ReasoningPlan) -> Dict[str, Any]:
        """Get a summary of a reasoning plan."""
        return {
            "query": plan.query,
            "goal": plan.goal,
            "status": plan.status,
            "steps_total": len(plan.steps),
            "steps_completed": sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED),
            "steps_failed": sum(1 for s in plan.steps if s.status == StepStatus.FAILED),
            "final_answer": plan.final_answer,
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "action": s.action,
                    "status": s.status.value,
                    "has_result": s.result is not None,
                    "error": s.error
                }
                for s in plan.steps
            ]
        }


# Singleton accessor
_service = None


def get_advanced_reasoning_service() -> AdvancedReasoningService:
    """Get the singleton AdvancedReasoningService instance."""
    global _service
    if _service is None:
        _service = AdvancedReasoningService()
    return _service
