"""
ResponseBuilder: Extracted response assembly for the Jarvis agent loop.

Phase 1.5 Refactoring - Step 4: Extract response building from run_agent().
This class encapsulates response dictionary construction and explanation building.

Goals:
- Reduce run_agent complexity by isolating response building
- Make response format testable and consistent
- Centralize explanation and cross-session learning integration
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.response_builder")


class CompletionReason(Enum):
    """Reason for agent completion."""
    END_TURN = "end_turn"       # Normal completion
    TIMEOUT = "timeout"         # Hit timeout
    MAX_ROUNDS = "max_rounds"   # Hit max rounds limit


@dataclass
class ResponseBuilder:
    """
    Builds the final response dictionary from agent state.

    Usage:
        builder = ResponseBuilder(
            answer="The answer text",
            tool_calls=all_tool_calls,
            rounds=round_num + 1,
            model=model,
            role=role,
            persona_id=persona_id,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens
        )

        # For normal completion
        response = builder.build()

        # For timeout
        builder.set_timeout(timeout_seconds)
        response = builder.build()

        # Add explanation
        builder.add_explanation(include_explanation=True)
        response = builder.build()
    """
    answer: str
    tool_calls: List[Dict[str, Any]]
    rounds: int
    model: str
    role: str
    persona_id: Optional[str]
    input_tokens: int
    output_tokens: int

    # Completion status
    completion_reason: CompletionReason = CompletionReason.END_TURN
    timeout_seconds: Optional[int] = None

    # Explanation
    _explanation: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _explanation_text: Optional[str] = field(default=None, repr=False)

    # Cross-session learning
    _decision_id: Optional[str] = field(default=None, repr=False)

    def set_timeout(self, timeout_seconds: int) -> "ResponseBuilder":
        """Mark response as timeout."""
        self.completion_reason = CompletionReason.TIMEOUT
        self.timeout_seconds = timeout_seconds
        self.answer = "I apologize, but I wasn't able to complete the task within the allowed time. Please try rephrasing your question."
        return self

    def set_max_rounds(self, max_rounds: int) -> "ResponseBuilder":
        """Mark response as max rounds hit."""
        self.completion_reason = CompletionReason.MAX_ROUNDS
        self.rounds = max_rounds
        self.answer = "I apologize, but I wasn't able to complete the task within the allowed steps. Please try rephrasing your question."
        return self

    def add_explanation(self, include_explanation: bool = True, include_results: bool = True) -> "ResponseBuilder":
        """Add explanation to response."""
        if include_explanation:
            self._explanation = build_explanation(self.tool_calls, include_results)
            self._explanation_text = format_explanation_text(self._explanation)
        return self

    def set_decision_id(self, decision_id: str) -> "ResponseBuilder":
        """Set cross-session learning decision ID."""
        self._decision_id = decision_id
        return self

    def get_confidence(self) -> float:
        """Get confidence from explanation, for cross-session learning."""
        if not self._explanation:
            return 0.7  # Default

        conf = self._explanation.get("confidence", "MEDIUM")
        if conf == "HIGH":
            return 0.9
        elif conf == "MEDIUM":
            return 0.7
        else:
            return 0.4

    def build(self) -> Dict[str, Any]:
        """Build the final response dictionary."""
        response = {
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "rounds": self.rounds,
            "model": self.model,
            "role": self.role,
            "persona_id": self.persona_id,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens
            }
        }

        # Add completion-specific fields
        if self.completion_reason == CompletionReason.TIMEOUT:
            response["timeout_hit"] = True
            response["timeout_seconds"] = self.timeout_seconds
        elif self.completion_reason == CompletionReason.MAX_ROUNDS:
            response["max_rounds_hit"] = True

        # Add explanation if present
        if self._explanation:
            response["explanation"] = self._explanation
        if self._explanation_text:
            response["explanation_text"] = self._explanation_text

        # Add decision ID if present
        if self._decision_id:
            response["decision_id"] = self._decision_id

        return response


def build_explanation(tool_calls: List[Dict], include_results: bool = True) -> Dict[str, Any]:
    """
    Build an explanation of how the answer was derived.

    Returns a structured explanation with:
    - sources: list of sources used (emails, chats, etc.)
    - searches: queries performed
    - confidence: overall confidence level
    - not_found: what wasn't found
    """
    sources = []
    searches = []
    tools_used = []
    not_found = []

    for tc in tool_calls:
        tool_name = tc.get("tool", "")
        tool_input = tc.get("input", {})
        result = tc.get("result", {})

        tools_used.append(tool_name)

        # Extract search queries
        if "query" in tool_input:
            searches.append({
                "tool": tool_name,
                "query": tool_input["query"],
                "namespace": tool_input.get("namespace", "work_projektil"),
                "filters": {k: v for k, v in tool_input.items() if k not in ["query", "namespace", "limit"]}
            })

        # Extract sources from results
        if isinstance(result, dict):
            results_list = result.get("results", [])
            count = result.get("count", len(results_list))

            if count == 0 and "query" in tool_input:
                not_found.append(f"No results for: {tool_input['query']}")

            for r in results_list[:5]:  # Top 5 sources per tool
                source = {
                    "type": r.get("doc_type", r.get("channel", "unknown")),
                    "path": r.get("source_path", ""),
                    "score": round(r.get("score", 0), 3),
                }

                # Add type-specific details
                if r.get("subject"):
                    source["subject"] = r["subject"][:60]
                if r.get("from"):
                    source["from"] = r["from"]
                if r.get("channel"):
                    source["channel"] = r["channel"]
                if r.get("event_ts_start"):
                    source["date"] = r["event_ts_start"][:10]
                elif r.get("event_ts"):
                    source["date"] = r["event_ts"][:10] if r["event_ts"] else None

                sources.append(source)

    # Determine confidence level
    if len(sources) >= 3:
        confidence = "HIGH"
        confidence_reason = f"{len(sources)} relevante Quellen gefunden"
    elif len(sources) >= 1:
        confidence = "MEDIUM"
        confidence_reason = f"Nur {len(sources)} Quelle(n) gefunden"
    elif tools_used and all(t == "no_tool_needed" for t in tools_used):
        confidence = "HIGH"
        confidence_reason = "Aus Kontext/Allgemeinwissen beantwortet"
    else:
        confidence = "LOW"
        confidence_reason = "Keine spezifischen Quellen gefunden"

    return {
        "sources": sources,
        "searches": searches,
        "tools_used": list(set(tools_used)),
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "not_found": not_found
    }


def format_explanation_text(explanation: Dict[str, Any]) -> str:
    """Format explanation as human-readable text block."""
    lines = ["", "---", "**[Antwort basiert auf]**"]

    # Confidence
    conf = explanation.get("confidence", "UNKNOWN")
    reason = explanation.get("confidence_reason", "")
    lines.append(f"Confidence: **{conf}** ({reason})")

    # Sources
    sources = explanation.get("sources", [])
    if sources:
        lines.append(f"{len(sources)} Quellen:")
        for s in sources[:5]:
            src_type = s.get("type", "unknown")
            if src_type == "email":
                subj = s.get("subject", "")
                frm = s.get("from", "")
                date = s.get("date", "")
                lines.append(f"  - Email: \"{subj}\" von {frm} ({date})")
            elif src_type in ["chat_window", "whatsapp", "google_chat"]:
                channel = s.get("channel", src_type)
                date = s.get("date", "")
                lines.append(f"  - Chat ({channel}): {date}")
            else:
                path = s.get("path", "")[:40]
                lines.append(f"  - {src_type}: {path}")

    # Searches performed
    searches = explanation.get("searches", [])
    if searches:
        lines.append("Suchen durchgeführt:")
        for s in searches[:3]:
            query = s.get("query", "")[:50]
            tool = s.get("tool", "").replace("tool_", "").replace("_", " ")
            lines.append(f"  - \"{query}\" ({tool})")

    # Not found
    not_found = explanation.get("not_found", [])
    if not_found:
        lines.append("Nicht gefunden:")
        for nf in not_found[:3]:
            lines.append(f"  - {nf}")

    return "\n".join(lines)
