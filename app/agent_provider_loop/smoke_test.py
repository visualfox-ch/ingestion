"""
Smoke test for the provider-agnostic agent tool loop.

Runs one synthetic tool-use roundtrip for Anthropic and OpenAI without
touching external APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from app.agent_provider_loop import (
    ProviderToolLoopState,
    get_provider_tool_loop_adapter,
    normalize_model_router_response,
)
from app.tool_executor import ToolExecutor


@dataclass
class SmokeResult:
    provider: str
    routable_tools: int
    followup_messages: int


def _fixture_response(provider: str) -> dict:
    payload = {
        "content": [
            {"type": "text", "text": "Nutze ein Tool."},
            {
                "type": "tool_use",
                "id": f"{provider}-tool-1",
                "name": "search_knowledge",
                "input": {"query": "Jarvis", "limit": 1},
            },
        ],
        "usage": {"input_tokens": 12, "output_tokens": 5},
        "model": "gpt-4o-mini" if provider == "openai" else "claude-haiku-4-5-20251001",
        "provider": provider,
        "stop_reason": "tool_use",
    }
    if provider == "openai":
        payload["openai_response_id"] = "resp_smoke_123"
    return payload


def _run_provider(provider: str) -> SmokeResult:
    response = normalize_model_router_response(_fixture_response(provider))
    adapter = get_provider_tool_loop_adapter(provider)
    state = ProviderToolLoopState(provider=provider)
    adapter.apply_response_state(response, state)

    executor = ToolExecutor(query="Suche Jarvis Wissen")
    with patch(
        "app.tool_executor._call_execute_tool",
        return_value={"results": [{"title": "Jarvis"}], "count": 1},
    ):
        batch = executor.process_response(response)

    messages = [{"role": "user", "content": "Suche Jarvis Wissen"}]
    adapter.append_followup_messages(messages, batch.assistant_content, batch.tool_results)

    if provider == "openai":
        assert state.previous_response_id == "resp_smoke_123"
        assert any(message["role"] == "tool" for message in messages)
    else:
        assert state.previous_response_id is None
        assert any(message["role"] == "user" for message in messages[1:])

    return SmokeResult(
        provider=provider,
        routable_tools=len(batch.executions),
        followup_messages=len(messages),
    )


def main() -> int:
    results = [_run_provider("anthropic"), _run_provider("openai")]
    for result in results:
        print(
            f"{result.provider}: tools={result.routable_tools} "
            f"followup_messages={result.followup_messages}"
        )
    print("provider_agnostic_tool_loop_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
