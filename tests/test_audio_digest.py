"""Focused tests for the v1 strategy audio digest slice (T-OC-705).

Tests cover:
  - guardrail: invalid digest_type → fail-closed
  - guardrail: source count exceeds MAX_SOURCE_COUNT
  - guardrail: invalid output_root prefix
  - guardrail: non-.md source file
  - guardrail: non-existent source file
  - guardrail: empty source_paths
  - happy path: artifacts written, metadata correct, no auto-send flag
  - tts char cap: tts_text is capped at MAX_TTS_CHARS even if summary is longer
  - summary cap: summary never exceeds MAX_SUMMARY_CHARS
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

# Stub out redis so ingestion app can be imported without a running Redis
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=object))

from app.services.voice_digest import (
    MAX_SOURCE_COUNT,
    MAX_SUMMARY_CHARS,
    MAX_TTS_CHARS,
    VoiceDigestService,
    VoiceDigestSynthesisError,
    VoiceDigestValidationError,
)
from app.services import voice_tts as voice_tts_module


# ---------------------------------------------------------------------------
# Stub TTS
# ---------------------------------------------------------------------------


class StubTTS:
    """Returns a predictable byte payload so tests stay offline."""

    async def synthesize(self, text: str, config):
        payload = f"AUDIO:{config.provider.value}:{config.voice_id}:{len(text)}".encode()
        return voice_tts_module.SynthesisResult(
            audio_bytes=payload,
            format=config.output_format.value,
            voice=config.voice_id,
            character_count=len(text),
        )


class FailingTTS:
    async def synthesize(self, text: str, config):
        return voice_tts_module.SynthesisResult(
            audio_bytes=b"",
            raw_response={"error": "provider unavailable"},
        )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_md(tmp_path: Path, name: str, content: str = "# Title\n\nSome content here.") -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def _service(tts=None) -> VoiceDigestService:
    return VoiceDigestService(tts=tts or StubTTS())


# ---------------------------------------------------------------------------
# Guardrail: invalid digest_type
# ---------------------------------------------------------------------------


def test_invalid_digest_type_raises(tmp_path):
    svc = _service()
    src = _make_md(tmp_path, "a.md")
    with pytest.raises(VoiceDigestValidationError, match="digest_type"):
        asyncio.run(
            svc.generate(
                digest_type="unknown_type",
                source_paths=[src],
                output_root=str(tmp_path),
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: output_root prefix
# ---------------------------------------------------------------------------


def test_invalid_output_root_raises(tmp_path):
    svc = _service()
    src = _make_md(tmp_path, "a.md")
    with pytest.raises(VoiceDigestValidationError, match="output_root"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[src],
                output_root="/tmp/bad_root",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: source count cap
# ---------------------------------------------------------------------------


def test_too_many_sources_raises(tmp_path):
    svc = _service()
    paths = [_make_md(tmp_path, f"f{i}.md") for i in range(MAX_SOURCE_COUNT + 1)]
    with pytest.raises(VoiceDigestValidationError, match="MAX_SOURCE_COUNT"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=paths,
                output_root="/brain/data/audio_digests/strategy",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: empty source_paths
# ---------------------------------------------------------------------------


def test_empty_source_paths_raises(tmp_path):
    svc = _service()
    with pytest.raises(VoiceDigestValidationError, match="at least one"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[],
                output_root="/brain/data/audio_digests/strategy",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: non-.md source
# ---------------------------------------------------------------------------


def test_non_md_source_raises(tmp_path):
    svc = _service()
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello")
    with pytest.raises(VoiceDigestValidationError, match=r"\.md"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[str(txt_file)],
                output_root="/brain/data/audio_digests/strategy",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: non-existent source
# ---------------------------------------------------------------------------


def test_missing_source_raises(tmp_path):
    svc = _service()
    with pytest.raises(VoiceDigestValidationError, match="does not exist"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=["/brain/does/not/exist.md"],
                output_root="/brain/data/audio_digests/strategy",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: relative source path
# ---------------------------------------------------------------------------


def test_relative_source_path_raises(tmp_path):
    svc = _service()
    with pytest.raises(VoiceDigestValidationError, match="absolute"):
        asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=["relative/path.md"],
                output_root="/brain/data/audio_digests/strategy",
            )
        )


# ---------------------------------------------------------------------------
# Guardrail: TTS synthesis failure → VoiceDigestSynthesisError
# ---------------------------------------------------------------------------


def test_tts_failure_raises_synthesis_error(tmp_path):
    svc = _service(tts=FailingTTS())
    src = _make_md(tmp_path, "a.md", "# Strategy\n\nMeaning content for Jarvis.")
    out_root = tmp_path / "digests"
    out_root.mkdir()
    # Patch the allowed prefix check by using a monkeypatched instance
    import app.services.voice_digest as vd_module

    original = vd_module.ALLOWED_OUTPUT_PREFIX
    # Prefix must be parent of out_root so that out_root starts with it
    vd_module.ALLOWED_OUTPUT_PREFIX = str(tmp_path) + "/"
    try:
        with pytest.raises(VoiceDigestSynthesisError):
            asyncio.run(
                svc.generate(
                    digest_type="strategy_weekly_digest",
                    source_paths=[src],
                    output_root=str(out_root),
                )
            )
    finally:
        vd_module.ALLOWED_OUTPUT_PREFIX = original


# ---------------------------------------------------------------------------
# Happy path: artifacts written, metadata correct, no auto-send
# ---------------------------------------------------------------------------


def test_happy_path_writes_three_artifacts(tmp_path):
    svc = _service()
    src = _make_md(tmp_path, "strategy.md", "# Weekly Strategy\n\nThis week we focus on growth.")
    out_root = tmp_path / "digests"
    out_root.mkdir()

    import app.services.voice_digest as vd_module

    original_prefix = vd_module.ALLOWED_OUTPUT_PREFIX
    # Prefix must be parent of out_root so that out_root is a valid subdirectory
    vd_module.ALLOWED_OUTPUT_PREFIX = str(tmp_path) + "/"
    try:
        result = asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[src],
                output_root=str(out_root),
            )
        )
    finally:
        vd_module.ALLOWED_OUTPUT_PREFIX = original_prefix

    # All three artifact paths exist
    assert Path(result.output_summary_path).is_file(), "summary.md missing"
    assert Path(result.output_audio_path).is_file(), "audio.mp3 missing"
    assert Path(result.output_metadata_path).is_file(), "metadata.json missing"

    # summary.md contains non-empty text
    summary_text = Path(result.output_summary_path).read_text(encoding="utf-8")
    assert len(summary_text) > 0

    # metadata.json is valid JSON with expected keys
    meta = json.loads(Path(result.output_metadata_path).read_text(encoding="utf-8"))
    assert meta["type"] == "strategy_audio_digest"
    assert meta["digest_type"] == "strategy_weekly_digest"
    assert meta["review"]["auto_send"] is False
    assert meta["review"]["publish_mode"] == "disabled"
    assert len(meta["source_files"]) == 1
    assert src in meta["source_files"]

    # source_hashes: SHA-256 of the source file is recorded
    expected_hash = hashlib.sha256(
        Path(src).read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert meta["source_hashes"][src] == expected_hash

    # char counts are within guardrails
    assert result.summary_char_count <= MAX_SUMMARY_CHARS
    assert result.tts_char_count <= MAX_TTS_CHARS


# ---------------------------------------------------------------------------
# Summary cap: text exceeding MAX_SUMMARY_CHARS is truncated
# ---------------------------------------------------------------------------


def test_summary_capped_at_max_chars(tmp_path):
    long_content = "# Big doc\n\n" + ("word " * 2000)  # >> MAX_SUMMARY_CHARS
    src = _make_md(tmp_path, "big.md", long_content)
    svc = _service()
    out_root = tmp_path / "digests"
    out_root.mkdir()

    import app.services.voice_digest as vd_module

    original_prefix = vd_module.ALLOWED_OUTPUT_PREFIX
    vd_module.ALLOWED_OUTPUT_PREFIX = str(tmp_path) + "/"
    try:
        result = asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[src],
                output_root=str(out_root),
            )
        )
    finally:
        vd_module.ALLOWED_OUTPUT_PREFIX = original_prefix

    assert result.summary_char_count <= MAX_SUMMARY_CHARS
    assert result.tts_char_count <= MAX_TTS_CHARS


# ---------------------------------------------------------------------------
# TTS char cap: audio synthesis text is independently capped
# ---------------------------------------------------------------------------


def test_tts_char_count_never_exceeds_cap(tmp_path):
    """Even if summary were longer than MAX_TTS_CHARS, TTS input is capped."""
    import app.services.voice_digest as vd_module

    original_summary_cap = vd_module.MAX_SUMMARY_CHARS
    # Allow a bigger summary but keep TTS cap as-is to verify the cap applies
    vd_module.MAX_SUMMARY_CHARS = MAX_TTS_CHARS + 500
    long_content = "# Doc\n\n" + ("word " * 1500)
    src = _make_md(tmp_path, "tts_test.md", long_content)
    svc = _service()
    out_root = tmp_path / "digests"
    out_root.mkdir()

    original_prefix = vd_module.ALLOWED_OUTPUT_PREFIX
    vd_module.ALLOWED_OUTPUT_PREFIX = str(tmp_path) + "/"
    try:
        result = asyncio.run(
            svc.generate(
                digest_type="strategy_weekly_digest",
                source_paths=[src],
                output_root=str(out_root),
            )
        )
    finally:
        vd_module.MAX_SUMMARY_CHARS = original_summary_cap
        vd_module.ALLOWED_OUTPUT_PREFIX = original_prefix

    assert result.tts_char_count <= MAX_TTS_CHARS
