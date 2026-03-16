"""
AgentState: Extracted state management for the Jarvis agent loop.

Phase 1.5 Refactoring - Step 1: Extract state management from run_agent().
This class encapsulates all mutable state during an agent run.

Goals:
- Reduce run_agent complexity by isolating state
- Enable easier testing of state transitions
- Prepare for future features (checkpointing, replay)
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import time


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool: str
    input: Dict[str, Any]
    result: Dict[str, Any]
    result_summary: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: Optional[float] = None


@dataclass
class TokenUsage:
    """Token usage tracking."""
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        """Add tokens from a response."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def to_dict(self) -> Dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens
        }


@dataclass
class AgentState:
    """
    Encapsulates all mutable state during an agent run.

    Lifecycle:
    1. Created at start of run_agent()
    2. Updated during tool execution rounds
    3. Used to build final response
    4. Optionally persisted to memory store
    """
    # Identity
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    namespace: str = "work_projektil"
    request_id: Optional[str] = None

    # Model configuration
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024

    # Role/persona
    role: str = "assistant"
    persona_id: Optional[str] = None

    # Query
    query: str = ""

    # Timing
    start_time: float = field(default_factory=time.time)
    timeout_seconds: Optional[int] = None
    timeout_hit: bool = False

    # Progress tracking
    round_num: int = 0
    max_rounds: int = 15
    max_rounds_hit: bool = False

    # Tool execution
    tool_calls: List[ToolCall] = field(default_factory=list)

    # Token usage
    usage: TokenUsage = field(default_factory=TokenUsage)

    # Messages (conversation state)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    # Final answer
    answer: Optional[str] = None

    # Explanation (if requested)
    explanation: Optional[Dict[str, Any]] = None
    
    # Facette detection (Phase 1 - Feb 3, 2026)
    facette_weights: Optional[Dict[str, float]] = None
    dominant_facette: Optional[str] = None
    domain_context: Optional[str] = None

    # Specialist Agent (Tier 3 #8)
    specialist: Optional[str] = None  # 'fit', 'work', 'comm'
    specialist_display_name: Optional[str] = None  # 'FitJarvis', 'WorkJarvis', 'CommJarvis'

    # Context Engine (Tier 3 #10)
    context_profile: Optional[Any] = None  # ContextProfile from context_engine_service

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time since start in milliseconds."""
        return (time.time() - self.start_time) * 1000

    @property
    def is_timed_out(self) -> bool:
        """Check if timeout has been exceeded."""
        if self.timeout_seconds is None:
            return False
        return (time.time() - self.start_time) > self.timeout_seconds

    @property
    def tools_used(self) -> List[str]:
        """List of unique tools used."""
        return list(set(tc.tool for tc in self.tool_calls))

    @property
    def error_count(self) -> int:
        """Count of tool calls that resulted in errors."""
        return sum(1 for tc in self.tool_calls if tc.result_summary == "error")

    @property
    def success_rate(self) -> float:
        """Success rate of tool calls."""
        if not self.tool_calls:
            return 1.0
        return 1.0 - (self.error_count / len(self.tool_calls))

    @property
    def context_switches(self) -> int:
        """Count of domain changes across tool calls."""
        switches = 0
        last_tool = None
        for tc in self.tool_calls:
            if last_tool and tc.tool != last_tool:
                switches += 1
            last_tool = tc.tool
        return switches

    def add_tool_call(
        self,
        tool: str,
        input: Dict[str, Any],
        result: Dict[str, Any],
        result_summary: str,
        duration_ms: Optional[float] = None
    ) -> ToolCall:
        """Record a tool call."""
        tc = ToolCall(
            tool=tool,
            input=input,
            result=result,
            result_summary=result_summary,
            duration_ms=duration_ms
        )
        self.tool_calls.append(tc)
        return tc

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Add tokens from a response."""
        self.usage.add(input_tokens, output_tokens)

    def increment_round(self) -> int:
        """Move to next round, return new round number."""
        self.round_num += 1
        if self.round_num >= self.max_rounds:
            self.max_rounds_hit = True
        return self.round_num

    def check_timeout(self) -> bool:
        """Check and record timeout status."""
        if self.is_timed_out:
            self.timeout_hit = True
            return True
        return False

    def to_response_dict(self) -> Dict[str, Any]:
        """Build the final response dictionary."""
        response = {
            "answer": self.answer or "",
            "tool_calls": [
                {
                    "tool": tc.tool,
                    "input": tc.input,
                    "result_summary": tc.result_summary,
                    "result": tc.result
                }
                for tc in self.tool_calls
            ],
            "rounds": self.round_num + 1,
            "model": self.model,
            "role": self.role,
            "persona_id": self.persona_id,
            "usage": self.usage.to_dict()
        }

        if self.timeout_hit:
            response["timeout_hit"] = True
            response["timeout_seconds"] = self.timeout_seconds

        if self.max_rounds_hit:
            response["max_rounds_hit"] = True

        if self.explanation:
            response["explanation"] = self.explanation
        
        # Add facette info (Phase 1 - Feb 3, 2026)
        if self.facette_weights is not None:
            response["facette_weights"] = self.facette_weights
        if self.dominant_facette is not None:
            response["dominant_facette"] = self.dominant_facette
        if self.domain_context is not None:
            response["domain_context"] = self.domain_context

        return response

    def to_memory_dict(self) -> Dict[str, Any]:
        """Build dictionary for session memory persistence."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "namespace": self.namespace,
            "query": self.query,
            "duration_ms": self.elapsed_ms,
            "rounds": self.round_num + 1,
            "tools_used": self.tools_used,
            "error_count": self.error_count,
            "context_switches": self.context_switches,
            "success_rate": self.success_rate
        }

    @classmethod
    def from_request(
        cls,
        query: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        namespace: str = "work_projektil",
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 1024,
        role: str = "assistant",
        persona_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        max_rounds: Optional[int] = None,
        request_id: Optional[str] = None
    ) -> "AgentState":
        """Create AgentState from request parameters."""
        import os as os_module
        import uuid
        # Read from environment directly to avoid import caching
        env_max_rounds = int(os_module.getenv("JARVIS_AGENT_MAX_ROUNDS", "5"))
        # Generate request_id if not provided
        if request_id is None:
            request_id = f"req_{uuid.uuid4().hex[:12]}"
        return cls(
            user_id=str(user_id) if user_id else None,
            session_id=session_id,
            namespace=namespace,
            request_id=request_id,
            model=model,
            max_tokens=max_tokens,
            role=role,
            persona_id=persona_id,
            query=query,
            timeout_seconds=timeout_seconds,
            max_rounds=max_rounds or env_max_rounds
        )
