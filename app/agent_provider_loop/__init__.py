"""
Provider-agnostic tool loop helpers for Jarvis.

Normalizes provider responses into one shared shape and keeps provider-
specific follow-up message formatting out of the main agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol


@dataclass
class NormalizedContentBlock:
    """Provider-independent content block."""

    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None


@dataclass
class NormalizedUsage:
    """Token usage in a provider-independent shape."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class NormalizedProviderResponse:
    """Normalized LLM response used by the shared agent loop."""

    content: List[NormalizedContentBlock]
    usage: NormalizedUsage
    model: str
    provider: str
    stop_reason: str
    provider_response_id: Optional[str] = None
    raw_response: Optional[Any] = None


@dataclass
class ProviderToolLoopState:
    """Mutable provider-specific loop state across tool rounds."""

    provider: str
    previous_response_id: Optional[str] = None


class ProviderToolLoopError(RuntimeError):
    """Raised when a provider cannot participate in the shared tool loop."""


class ProviderToolLoopAdapter(Protocol):
    """Provider-specific hooks around the shared normalized loop."""

    provider: str

    def apply_response_state(
        self,
        response: NormalizedProviderResponse,
        state: ProviderToolLoopState,
    ) -> None:
        ...

    def append_followup_messages(
        self,
        messages: List[Dict[str, Any]],
        assistant_content: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ...


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_content_blocks(blocks: Iterable[Any]) -> List[NormalizedContentBlock]:
    normalized: List[NormalizedContentBlock] = []

    for block in blocks or []:
        block_type = _get_attr(block, "type")
        if not block_type:
            continue

        normalized.append(
            NormalizedContentBlock(
                type=block_type,
                text=_get_attr(block, "text"),
                id=_get_attr(block, "id"),
                name=_get_attr(block, "name"),
                input=_get_attr(block, "input"),
            )
        )

    return normalized


def normalize_anthropic_response(response: Any, model: str) -> NormalizedProviderResponse:
    """Convert a raw Anthropic message into the shared response shape."""

    usage = _get_attr(response, "usage") or {}
    return NormalizedProviderResponse(
        content=_normalize_content_blocks(_get_attr(response, "content", [])),
        usage=NormalizedUsage(
            input_tokens=_get_attr(usage, "input_tokens", 0),
            output_tokens=_get_attr(usage, "output_tokens", 0),
        ),
        model=model,
        provider="anthropic",
        stop_reason=_get_attr(response, "stop_reason", "end_turn"),
        raw_response=response,
    )


def normalize_model_router_response(response: Dict[str, Any]) -> NormalizedProviderResponse:
    """Convert the model router payload into the shared response shape."""

    usage = response.get("usage") or {}
    return NormalizedProviderResponse(
        content=_normalize_content_blocks(response.get("content", [])),
        usage=NormalizedUsage(
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        ),
        model=response.get("model", ""),
        provider=response.get("provider", ""),
        stop_reason=response.get("stop_reason", "end_turn"),
        provider_response_id=response.get("openai_response_id"),
        raw_response=response,
    )


class AnthropicToolLoopAdapter:
    provider = "anthropic"

    def apply_response_state(
        self,
        response: NormalizedProviderResponse,
        state: ProviderToolLoopState,
    ) -> None:
        state.provider = self.provider
        state.previous_response_id = None

    def append_followup_messages(
        self,
        messages: List[Dict[str, Any]],
        assistant_content: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
        return messages


class OpenAIToolLoopAdapter:
    provider = "openai"

    def apply_response_state(
        self,
        response: NormalizedProviderResponse,
        state: ProviderToolLoopState,
    ) -> None:
        state.provider = self.provider
        state.previous_response_id = response.provider_response_id

    def append_followup_messages(
        self,
        messages: List[Dict[str, Any]],
        assistant_content: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        assistant_text_blocks = [
            block
            for block in assistant_content
            if block.get("type") == "text" and block.get("text")
        ]
        if assistant_text_blocks:
            messages.append({"role": "assistant", "content": assistant_text_blocks})

        messages.append({"role": "tool", "content": tool_results})
        return messages


_ADAPTERS: Dict[str, ProviderToolLoopAdapter] = {
    "anthropic": AnthropicToolLoopAdapter(),
    "openai": OpenAIToolLoopAdapter(),
}


def get_provider_tool_loop_adapter(provider: str) -> ProviderToolLoopAdapter:
    """Return the provider adapter or raise with a clear capability error."""

    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ProviderToolLoopError(
            f"Provider '{provider}' does not expose a normalized tool-loop adapter."
        )
    return adapter
