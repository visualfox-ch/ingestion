"""
ToolExecutor: Extracted tool execution for the Jarvis agent loop.

Phase 1.5 Refactoring - Step 3: Extract tool execution from run_agent().
This class encapsulates tool invocation, result formatting, and loop detection.

Goals:
- Reduce run_agent complexity by isolating tool execution
- Make tool execution testable
- Centralize loop detection and alerting
"""
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

from .tools import execute_tool
from .observability import get_logger, log_with_context, metrics, tool_loop_detector

logger = get_logger("jarvis.tool_executor")


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
        on_loop_alert: Optional[Callable[[str, bool, str, Optional[str]], None]] = None
    ):
        self.user_id = user_id
        self.query = query
        self.on_loop_alert = on_loop_alert

        # Execution tracking
        self._executions: List[ToolExecutionResult] = []
        self._total_loops: int = 0

    def process_response(self, response) -> ToolBatchResult:
        """
        Process a Claude response and execute any tool_use blocks.

        Args:
            response: Anthropic API response object

        Returns:
            ToolBatchResult with executions, formatted content, and tool results
        """
        batch_start = time.time()
        batch = ToolBatchResult()

        for block in response.content:
            if block.type == "text":
                batch.assistant_content.append({
                    "type": "text",
                    "text": block.text
                })
            elif block.type == "tool_use":
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

    def _execute_single_tool(self, block) -> ToolExecutionResult:
        """Execute a single tool_use block."""
        tool_name = block.name
        tool_input = block.input
        tool_id = block.id

        log_with_context(logger, "info", f"Executing tool: {tool_name}",
                       input=json.dumps(tool_input)[:200])

        start_time = time.time()

        # Execute the tool
        result = execute_tool(tool_name, tool_input)

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
