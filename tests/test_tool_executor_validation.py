"""Tests for tool input validation in ToolExecutor."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import tool_executor


class FakeToolUseBlock:
    def __init__(self, name, tool_input, tool_id="tool-1"):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input
        self.id = tool_id


class FakeResponse:
    def __init__(self, content):
        self.content = content


def test_tool_executor_rejects_empty_execute_python(monkeypatch):
    calls = {"count": 0}

    def _execute_tool(name, tool_input):
        calls["count"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(tool_executor, "execute_tool", _execute_tool)

    executor = tool_executor.ToolExecutor()
    response = FakeResponse([
        FakeToolUseBlock("execute_python", {"code": "   "}, tool_id="tool-123")
    ])

    batch = executor.process_response(response)

    assert calls["count"] == 0
    assert len(batch.executions) == 1
    result = batch.executions[0].result
    assert result["error"] == "code is required"
    assert result["blocked_reason"] == "missing_code"
