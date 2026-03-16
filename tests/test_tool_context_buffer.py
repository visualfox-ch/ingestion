"""Tests for ToolContextBuffer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tool_context_buffer import ToolContextBuffer


def test_tool_context_buffer_limits_entries_and_bytes():
    buf = ToolContextBuffer(max_entries=2, max_bytes=200, value_max_chars=20)

    buf.add("tool_a", {}, {"status": "ok", "summary": "alpha"}, "success")
    buf.add("tool_b", {}, {"status": "ok", "summary": "beta"}, "success")
    buf.add("tool_c", {}, {"status": "ok", "summary": "gamma"}, "success")

    assert len(buf.to_list()) <= 2
    assert buf.byte_size <= 200


def test_tool_context_buffer_redacts_large_payloads():
    buf = ToolContextBuffer(max_entries=3, max_bytes=1000, value_max_chars=30)

    big_blob = "X" * 500
    buf.add("search_knowledge", {}, {"results": [{"text": big_blob}]}, "success")

    snapshot = buf.snapshot()
    assert big_blob not in snapshot
    assert "results_count" in snapshot
