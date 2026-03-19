"""
ToolExecutor: Extracted tool execution for the Jarvis agent loop.

Phase 1.5 Refactoring - Step 3: Extract tool execution from run_agent().
This class encapsulates tool invocation, result formatting, and loop detection.

Goals:
- Reduce run_agent complexity by isolating tool execution
- Make tool execution testable
- Centralize loop detection and alerting

Tier 1 Quick Win: Reasoning Observability Integration
- Records tool selection rationale
- Tracks confidence per execution
- Enables reasoning path visibility
"""
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

from .observability import get_logger, log_with_context, metrics, tool_loop_detector

logger = get_logger("jarvis.tool_executor")

# Phase 21 service instances (lazy loaded)
_chain_analyzer = None
_performance_tracker = None
_reasoning_observer = None


def _call_execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy-load the tool registry to keep lightweight tests importable."""
    from .tools import execute_tool

    return execute_tool(tool_name, tool_input)


def _get_reasoning_observer():
    """Get reasoning observer from current context (if available)."""
    try:
        from .services.reasoning_observer import get_current_observer
        return get_current_observer()
    except Exception:
        return None


def _get_chain_analyzer():
    """Get or create tool chain analyzer (lazy load)."""
    global _chain_analyzer
    if _chain_analyzer is None:
        try:
            from .services.tool_chain_analyzer import get_tool_chain_analyzer
            _chain_analyzer = get_tool_chain_analyzer()
        except Exception as e:
            logger.debug(f"Could not load tool_chain_analyzer: {e}")
    return _chain_analyzer


def _get_performance_tracker():
    """Get or create tool performance tracker (lazy load)."""
    global _performance_tracker
    if _performance_tracker is None:
        try:
            from .services.tool_performance_tracker import get_tool_performance_tracker
            _performance_tracker = get_tool_performance_tracker()
        except Exception as e:
            logger.debug(f"Could not load tool_performance_tracker: {e}")
    return _performance_tracker


@dataclass
class ToolExecutionResult:
    """Result of a single tool execution."""
    tool_name: str
    tool_id: str
    input: Dict[str, Any]
    result: Dict[str, Any]
    result_summary: str
    duration_ms: float = 0.0
    loop_detected: bool = False
    loop_count: int = 0


@dataclass
class ToolBatchResult:
    """Result of executing a batch of tools from one response."""
    executions: List[ToolExecutionResult] = field(default_factory=list)
    assistant_content: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    total_duration_ms: float = 0.0
    loops_detected: int = 0

    @property
    def has_loops(self) -> bool:
        """Check if any loops were detected."""
        return self.loops_detected > 0


class ToolExecutor:
    """
    Executes tools requested by Claude and formats results.

    Usage:
        executor = ToolExecutor(
            user_id=user_id,
            query=query,
            on_loop_alert=send_alert_callback
        )

        # Process a response with tool_use blocks
        batch_result = executor.process_response(response)

        # Get formatted messages for Claude
        assistant_msg = {"role": "assistant", "content": batch_result.assistant_content}
        user_msg = {"role": "user", "content": batch_result.tool_results}
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        query: str = "",
        on_loop_alert: Optional[Callable[[str, bool, str, Optional[str]], None]] = None,
        session_id: Optional[str] = None
    ):
        self.user_id = user_id
        self.query = query
        self.on_loop_alert = on_loop_alert
        self.session_id = session_id

        # Execution tracking
        self._executions: List[ToolExecutionResult] = []
        self._total_loops: int = 0
        self._chain_started: bool = False

    def process_response(self, response) -> ToolBatchResult:
        """
        Process a normalized provider response and execute any tool_use blocks.

        Args:
            response: normalized response object or compatible provider response

        Returns:
            ToolBatchResult with executions, formatted content, and tool results
        """
        batch_start = time.time()
        batch = ToolBatchResult()

        for block in self._iter_content_blocks(response):
            block_type = self._get_block_attr(block, "type")
            if block_type == "text":
                batch.assistant_content.append({
                    "type": "text",
                    "text": self._get_block_attr(block, "text", "")
                })
            elif block_type == "tool_use":
                execution = self._execute_single_tool(block)
                batch.executions.append(execution)
                self._executions.append(execution)

                # Add to assistant content
                batch.assistant_content.append({
                    "type": "tool_use",
                    "id": execution.tool_id,
                    "name": execution.tool_name,
                    "input": execution.input
                })

                # Format result for Claude
                batch.tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": execution.tool_id,
                    "content": json.dumps(execution.result, default=str)
                })

                if execution.loop_detected:
                    batch.loops_detected += 1

        batch.total_duration_ms = (time.time() - batch_start) * 1000
        return batch

    def _iter_content_blocks(self, response) -> List[Any]:
        """Return content blocks from normalized dict or object responses."""
        if isinstance(response, dict):
            return response.get("content", []) or []
        return getattr(response, "content", []) or []

    def _get_block_attr(self, block: Any, name: str, default: Any = None) -> Any:
        """Read block fields from dicts, dataclasses, or provider SDK objects."""
        if isinstance(block, dict):
            return block.get(name, default)
        return getattr(block, name, default)

    def _check_requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires user approval before execution."""
        try:
            from .postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute(
                    "SELECT requires_approval FROM jarvis_tools WHERE name = %s",
                    (tool_name,)
                )
                row = cur.fetchone()
                requires_approval = bool(row.get("requires_approval")) if row else False
                log_with_context(
                    logger,
                    "info",
                    "Approval check result",
                    tool=tool_name,
                    row=str(row),
                    requires_approval=requires_approval,
                )
                if requires_approval:
                    log_with_context(logger, "info", f"APPROVAL REQUIRED for tool: {tool_name}")
                    return True
        except Exception as e:
            log_with_context(logger, "warning", "Could not check requires_approval",
                           tool=tool_name, error=str(e))
        return False

    def _execute_single_tool(self, block) -> ToolExecutionResult:
        """Execute a single tool_use block."""
        tool_name = self._get_block_attr(block, "name")
        tool_input = self._get_block_attr(block, "input", {}) or {}
        tool_id = self._get_block_attr(block, "id")

        log_with_context(logger, "info", f"Executing tool: {tool_name}",
                       input=json.dumps(tool_input)[:200])

        start_time = time.time()

        # Check if tool requires approval (unless user already confirmed)
        user_confirmed = tool_input.pop("_user_confirmed", False)
        if self._check_requires_approval(tool_name) and not user_confirmed:
            # Return approval request instead of executing
            log_with_context(logger, "info", f"Tool requires approval: {tool_name}")
            result = {
                "status": "approval_required",
                "tool": tool_name,
                "message": f"Dieses Tool ({tool_name}) benötigt deine Bestätigung.",
                "input_summary": json.dumps(tool_input, ensure_ascii=False)[:200],
                "instruction": "Frage den User ob er das möchte bevor du fortfährst. Erkläre kurz was gespeichert werden soll."
            }
            duration_ms = (time.time() - start_time) * 1000
            return ToolExecutionResult(
                tool_name=tool_name,
                tool_id=tool_id,
                input=tool_input,
                result=result,
                result_summary=f"Approval required for {tool_name}",
                duration_ms=duration_ms,
                loop_detected=False,
                loop_count=0
            )

        # Phase A: Auto-Hook - check_guardrails before autonomous tools
        guardrails_result = self._check_guardrails_hook(tool_name, tool_input)
        if guardrails_result and not guardrails_result.get("allowed", True):
            log_with_context(logger, "warning", f"Guardrails blocked tool: {tool_name}",
                           reason=guardrails_result.get("reason"))
            result = {
                "status": "blocked_by_guardrails",
                "tool": tool_name,
                "reason": guardrails_result.get("reason", "Guardrail violation"),
                "violations": guardrails_result.get("violations", []),
                "instruction": "Diese Aktion wurde durch Leitplanken blockiert. Erkläre dem User warum."
            }
            duration_ms = (time.time() - start_time) * 1000
            return ToolExecutionResult(
                tool_name=tool_name,
                tool_id=tool_id,
                input=tool_input,
                result=result,
                result_summary=f"Blocked by guardrails: {guardrails_result.get('reason', 'violation')}",
                duration_ms=duration_ms,
                loop_detected=False,
                loop_count=0
            )

        # Execute the tool
        result = _call_execute_tool(tool_name, tool_input)

        duration_ms = (time.time() - start_time) * 1000

        # Check for tool loop pattern
        loop_detected = False
        loop_count = 0
        loop_check = tool_loop_detector.check_loop(tool_name, tool_input)

        if loop_check["is_loop"]:
            loop_detected = True
            loop_count = loop_check["count"]
            self._total_loops += 1

            log_with_context(logger, "warning", "TOOL LOOP DETECTED",
                           tool=tool_name,
                           count=loop_check["count"],
                           identical_args=loop_check["identical_args"],
                           loops_total=loop_check["loops_total"])
            metrics.inc("tool_loops_detected")

            # Send alert if callback provided and rate limit allows
            if self.on_loop_alert and tool_loop_detector.should_alert():
                try:
                    self.on_loop_alert(
                        tool_name,
                        loop_check["identical_args"],
                        self.query[:100] if self.query else "",
                        self.user_id
                    )
                except Exception as e:
                    log_with_context(logger, "warning", "Failed to send loop alert",
                                   error=str(e))

        # Build result summary
        result_summary = self._build_result_summary(result)

        # Phase 19.6: Record tool execution for autonomy learning
        self._record_tool_execution(
            tool_name=tool_name,
            success="error" not in result,
            latency_ms=int(duration_ms),
            input_summary=json.dumps(tool_input)[:200] if tool_input else None,
            output_summary=result_summary,
            error_message=result.get("error") if isinstance(result, dict) else None
        )

        # Tier 1 Quick Win: Reasoning Observability
        self._record_reasoning_observation(
            tool_name=tool_name,
            success="error" not in result,
            duration_ms=duration_ms,
            result=result
        )

        # Phase 21A: Track tool chain and performance
        self._track_phase21(
            tool_name=tool_name,
            success="error" not in result,
            duration_ms=int(duration_ms),
            error_type=result.get("error_type") if isinstance(result, dict) else None,
            error_message=result.get("error") if isinstance(result, dict) else None
        )

        return ToolExecutionResult(
            tool_name=tool_name,
            tool_id=tool_id,
            input=tool_input,
            result=result,
            result_summary=result_summary,
            duration_ms=duration_ms,
            loop_detected=loop_detected,
            loop_count=loop_count
        )

    def _build_result_summary(self, result: Dict[str, Any]) -> str:
        """Build a summary string for the tool result."""
        if "count" in result:
            return f"{result['count']} results"
        if "error" in result:
            return "error"
        if "success" in result:
            return "success" if result["success"] else "failed"
        return "executed"

    def _check_guardrails_hook(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Phase A Auto-Hook: Check guardrails before autonomous tool execution.

        This hook automatically calls check_guardrails for tools that can
        modify state, send messages, or affect external systems.

        Returns:
            None if check should be skipped
            Dict with 'allowed', 'reason', 'violations' if checked
        """
        try:
            from .services.agent_hooks import AgentHooks, get_safe_tools, get_autonomous_tools

            # Skip for safe read-only tools (Tier 0 from DB)
            if tool_name in get_safe_tools():
                return None

            # Only check autonomous tools (Tier 2-3 from DB)
            if tool_name not in get_autonomous_tools():
                return None

            hooks = AgentHooks(
                user_id=int(self.user_id) if self.user_id and self.user_id.isdigit() else None,
                session_id=self.session_id
            )

            result = hooks.pre_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                context={"query": self.query[:200] if self.query else ""}
            )

            if result.skipped:
                return None

            return result.data

        except Exception as e:
            log_with_context(logger, "debug", "Guardrails hook failed (allowing tool)",
                           tool=tool_name, error=str(e))
            return None  # Fail open - allow if hook fails

    def get_all_executions(self) -> List[ToolExecutionResult]:
        """Get all tool executions so far."""
        return self._executions

    def get_tool_calls_dict(self) -> List[Dict[str, Any]]:
        """Get tool calls in the legacy dict format for backward compatibility."""
        return [
            {
                "tool": ex.tool_name,
                "input": ex.input,
                "result_summary": ex.result_summary,
                "result": ex.result
            }
            for ex in self._executions
        ]

    def _record_tool_execution(
        self,
        tool_name: str,
        success: bool,
        latency_ms: int,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Record tool execution for autonomy learning (Phase 19.6).

        This data helps Jarvis:
        - Identify slow or failing tools
        - Optimize tool selection
        - Learn usage patterns
        """
        try:
            from .services.tool_autonomy import get_tool_autonomy_service
            service = get_tool_autonomy_service()
            service.record_tool_execution(
                tool_name=tool_name,
                success=success,
                latency_ms=latency_ms,
                session_id=None,  # Could be added via context
                user_id=int(self.user_id) if self.user_id and self.user_id.isdigit() else None,
                error_message=error_message,
                input_summary=input_summary,
                output_summary=output_summary
            )
        except Exception as e:
            # Don't fail tool execution if tracking fails
            log_with_context(logger, "debug", "Tool execution tracking failed", error=str(e))

    def _track_phase21(
        self,
        tool_name: str,
        success: bool,
        duration_ms: int,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Phase 21A: Track tool chains and performance.

        T-21A-01: Smart Tool Chains - Track which tools are used together
        T-21A-04: Tool Performance Learning - Track success/failure with context
        """
        # T-21A-04: Tool Performance Learning
        tracker = _get_performance_tracker()
        if tracker:
            try:
                tracker.record_execution(
                    tool_name=tool_name,
                    user_id=self.user_id or "unknown",
                    success=success,
                    session_id=self.session_id,
                    error_type=error_type,
                    error_message=error_message,
                    duration_ms=duration_ms,
                    query_context=self.query[:200] if self.query else None
                )
            except Exception as e:
                log_with_context(logger, "debug", "Performance tracking failed", error=str(e))

        # Phase 21A: Context-Tool Affinity Learning
        try:
            from .services.contextual_tool_router import get_contextual_tool_router
            router = get_contextual_tool_router()
            router.record_routing_outcome(
                query=self.query[:200] if self.query else "",
                tool_selected=tool_name,
                was_successful=success,
                context={"session_id": self.session_id}
            )
        except Exception as e:
            log_with_context(logger, "debug", "Routing outcome recording failed", error=str(e))

        # T-21A-01: Tool Chain Tracking
        analyzer = _get_chain_analyzer()
        if analyzer and self.session_id:
            try:
                # Start chain if not already started
                if not self._chain_started:
                    analyzer.start_chain(self.session_id, self.user_id or "unknown", self.query)
                    self._chain_started = True

                # Add this tool to the chain
                analyzer.add_tool_to_chain(self.session_id, tool_name)
            except Exception as e:
                log_with_context(logger, "debug", "Chain tracking failed", error=str(e))

    def _record_reasoning_observation(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        result: Dict[str, Any]
    ) -> None:
        """
        Tier 1 Quick Win: Record reasoning observation for this tool execution.

        Tracks:
        - Tool selection confidence (inferred from result quality)
        - Reasoning step outcome
        - Hallucination risk flags
        """
        observer = _get_reasoning_observer()
        if not observer:
            return  # No active observation session

        try:
            from .services.reasoning_observer import (
                SelectionReason,
                HallucinationRisk,
                infer_selection_reason,
            )

            # Infer selection reason from query context
            reason = infer_selection_reason(tool_name, self.query or "")

            # Estimate confidence from result quality
            confidence = 0.8 if success else 0.3
            if isinstance(result, dict):
                if result.get("count", 0) > 0:
                    confidence = 0.9  # Good results found
                elif result.get("error"):
                    confidence = 0.2  # Error occurred

            # Record tool selection
            observer.record_tool_selection(
                tool_name=tool_name,
                reason=reason,
                confidence=confidence,
            )

            # Record reasoning step
            outcome = "success" if success else "failure"
            observer.add_step(
                step_type="tool_call",
                description=f"Executed {tool_name}",
                outcome=outcome,
                confidence=confidence,
                metadata={"duration_ms": duration_ms}
            )

            # Check for hallucination risk
            if isinstance(result, dict):
                if result.get("count", -1) == 0:
                    observer.flag_hallucination_risk(
                        HallucinationRisk.NO_TOOL_DATA,
                        f"Tool {tool_name} returned no results"
                    )
                elif not success and "not found" in str(result.get("error", "")).lower():
                    observer.flag_hallucination_risk(
                        HallucinationRisk.UNVERIFIED_CLAIM,
                        f"Tool {tool_name} could not verify data"
                    )

        except Exception as e:
            log_with_context(logger, "debug", "Reasoning observation failed", error=str(e))

    def finish_chain(self, success: bool = True) -> Dict[str, Any]:
        """
        Finish the current tool chain and save it.

        Called by agent.py when the agent loop completes.
        """
        if not self._chain_started or not self.session_id:
            return {"saved": False, "reason": "no_chain"}

        analyzer = _get_chain_analyzer()
        if not analyzer:
            return {"saved": False, "reason": "no_analyzer"}

        try:
            result = analyzer.finish_chain(
                self.session_id,
                self.user_id or "unknown",
                success=success,
                query_context=self.query[:500] if self.query else None
            )
            log_with_context(logger, "debug", "Tool chain finished",
                           session_id=self.session_id, result=result)

            # Tier 2: Record query-chain mapping for intelligence
            if result.get("saved") and self.query:
                self._record_chain_intelligence(result.get("chain", []), success)

            return result
        except Exception as e:
            log_with_context(logger, "debug", "finish_chain failed", error=str(e))
            return {"saved": False, "reason": str(e)}

    def _record_chain_intelligence(self, chain: List[str], success: bool):
        """Record query-chain mapping for tool chain intelligence."""
        if len(chain) < 2:
            return

        try:
            from .services.tool_chain_intelligence import get_tool_chain_intelligence
            intelligence = get_tool_chain_intelligence()

            # Calculate total duration from executions
            total_duration = sum(ex.duration_ms for ex in self._executions)

            intelligence.record_query_chain_usage(
                query=self.query,
                chain=chain,
                success=success,
                duration_ms=int(total_duration)
            )
            log_with_context(logger, "debug", "Chain intelligence recorded",
                           chain_length=len(chain), success=success)
        except Exception as e:
            log_with_context(logger, "debug", "Chain intelligence recording failed", error=str(e))

    @property
    def total_tools_executed(self) -> int:
        """Count of tools executed."""
        return len(self._executions)

    @property
    def total_loops_detected(self) -> int:
        """Count of loops detected."""
        return self._total_loops

    @property
    def tools_used(self) -> List[str]:
        """Unique list of tools used."""
        return list(set(ex.tool_name for ex in self._executions))
