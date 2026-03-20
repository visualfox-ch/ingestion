"""Strategy audio digest service — v1 narrow slice (T-OC-705).

Generates three artifacts from a bounded markdown source set:
  - summary.md
  - audio.mp3
  - metadata.json

Hard guardrails:
  - MAX_SOURCE_COUNT: total source files accepted
  - MAX_SUMMARY_CHARS: capped summary text written to summary.md
  - MAX_TTS_CHARS: capped text sent to TTS provider
  - ALLOWED_DIGEST_TYPES: fail-closed for unknown digest types
  - ALLOWED_OUTPUT_PREFIX: output path must be under an approved root
  - No auto-send to Telegram or public channels
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .voice_tts import OutputFormat, TTSProvider, VoiceConfig, VoiceTTS, get_tts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard guardrails
# ---------------------------------------------------------------------------
MAX_SOURCE_COUNT = 10
MAX_SUMMARY_CHARS = 3000
MAX_TTS_CHARS = 3000
ALLOWED_DIGEST_TYPES = frozenset({"strategy_weekly_digest"})
ALLOWED_OUTPUT_PREFIX = "/brain/data/audio_digests/"
DEFAULT_OUTPUT_ROOT = "/brain/data/audio_digests/strategy"


class VoiceDigestError(RuntimeError):
    """Base error for digest generation."""


class VoiceDigestValidationError(VoiceDigestError):
    """Raised when inputs are invalid — fail-closed."""


class VoiceDigestSynthesisError(VoiceDigestError):
    """Raised when TTS synthesis fails."""


@dataclass
class DigestResult:
    digest_type: str
    output_summary_path: str
    output_audio_path: str
    output_metadata_path: str
    provider: str
    voice_id: str
    format: str
    summary_char_count: int
    tts_char_count: int
    source_files: list[str]
    source_hashes: dict[str, str]
    generated_at: str
    review_status: str = "pending_review"


class VoiceDigestService:
    """Generate traceable strategy audio digests from a bounded markdown source set."""

    def __init__(self, tts: VoiceTTS | None = None) -> None:
        self._tts = tts or get_tts()

    async def generate(
        self,
        *,
        digest_type: str,
        source_paths: list[str],
        output_root: str = DEFAULT_OUTPUT_ROOT,
        provider: TTSProvider = TTSProvider.OPENAI,
        voice_id: str | None = None,
        output_format: OutputFormat = OutputFormat.MP3,
        overwrite: bool = False,
    ) -> DigestResult:
        # --- validate digest type (fail-closed) ---
        if digest_type not in ALLOWED_DIGEST_TYPES:
            raise VoiceDigestValidationError(
                f"digest_type '{digest_type}' is not allowed. "
                f"Allowed: {sorted(ALLOWED_DIGEST_TYPES)}"
            )

        # --- validate source count ---
        if not source_paths:
            raise VoiceDigestValidationError("source_paths must contain at least one entry")
        if len(source_paths) > MAX_SOURCE_COUNT:
            raise VoiceDigestValidationError(
                f"source_paths count {len(source_paths)} exceeds MAX_SOURCE_COUNT={MAX_SOURCE_COUNT}"
            )

        # --- validate output root ---
        if not output_root.startswith(ALLOWED_OUTPUT_PREFIX):
            raise VoiceDigestValidationError(
                f"output_root must start with '{ALLOWED_OUTPUT_PREFIX}'"
            )

        # --- validate and read sources ---
        validated_sources = [self._validate_source(p) for p in source_paths]
        source_texts: list[str] = []
        source_hashes: dict[str, str] = {}
        for source_path in validated_sources:
            raw = source_path.read_text(encoding="utf-8")
            source_hashes[str(source_path)] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            source_texts.append(raw)

        # --- build summary text ---
        combined_text = self._combine_sources(source_texts)
        summary_text = self._build_summary(combined_text, max_chars=MAX_SUMMARY_CHARS)
        if not summary_text:
            raise VoiceDigestValidationError(
                "source files do not contain enough readable text to build a summary"
            )

        # --- cap TTS text ---
        tts_text = summary_text[:MAX_TTS_CHARS]

        # --- resolve output paths ---
        output_dir = self._build_output_dir(output_root, digest_type)
        digest_slug = self._build_digest_slug(digest_type, source_hashes)
        summary_path = output_dir / "summary.md"
        audio_path = output_dir / f"audio.{output_format.value}"
        metadata_path = output_dir / "metadata.json"

        if overwrite or not audio_path.exists():
            resolved_voice_id = self._resolve_voice_id(provider, voice_id)
            config = VoiceConfig(
                provider=provider,
                voice_id=resolved_voice_id,
                output_format=output_format,
            )
            synthesis = await self._tts.synthesize(tts_text, config)
            if not synthesis.audio_bytes:
                raise VoiceDigestSynthesisError(
                    (synthesis.raw_response or {}).get("error", "TTS synthesis failed")
                )
            audio_path.write_bytes(synthesis.audio_bytes)
            used_voice_id = synthesis.voice or resolved_voice_id
        else:
            # Read existing metadata to recover voice_id
            used_voice_id = self._resolve_voice_id(provider, voice_id)

        # --- persist summary.md ---
        summary_path.write_text(summary_text, encoding="utf-8")

        # --- persist metadata.json ---
        generated_at = datetime.now(timezone.utc).isoformat()
        metadata: dict = {
            "type": "strategy_audio_digest",
            "digest_type": digest_type,
            "generated_at": generated_at,
            "provider": provider.value,
            "voice_id": used_voice_id,
            "format": output_format.value,
            "summary_char_count": len(summary_text),
            "tts_char_count": len(tts_text),
            "source_files": [str(p) for p in validated_sources],
            "source_hashes": source_hashes,
            "output_summary_path": str(summary_path),
            "output_audio_path": str(audio_path),
            "output_metadata_path": str(metadata_path),
            "review": {
                "status": "pending_review",
                "publish_mode": "disabled",
                "auto_send": False,
                "notes": "Operator-controlled digest. Listen, then approve or discard.",
            },
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        return DigestResult(
            digest_type=digest_type,
            output_summary_path=str(summary_path),
            output_audio_path=str(audio_path),
            output_metadata_path=str(metadata_path),
            provider=provider.value,
            voice_id=used_voice_id,
            format=output_format.value,
            summary_char_count=len(summary_text),
            tts_char_count=len(tts_text),
            source_files=[str(p) for p in validated_sources],
            source_hashes=source_hashes,
            generated_at=generated_at,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _validate_source(self, source_path: str) -> Path:
        if not source_path.startswith("/"):
            raise VoiceDigestValidationError(
                f"source_path must be an absolute path: {source_path!r}"
            )
        path = Path(source_path)
        if path.suffix.lower() != ".md":
            raise VoiceDigestValidationError(
                f"source_path must be a .md file: {source_path!r}"
            )
        if not path.is_file():
            raise VoiceDigestValidationError(
                f"source_path does not exist: {source_path!r}"
            )
        return path

    def _build_output_dir(self, output_root: str, digest_type: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", digest_type.lower()).strip("-")
        output_dir = Path(output_root) / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _resolve_voice_id(self, provider: TTSProvider, voice_id: str | None) -> str:
        if voice_id:
            return voice_id
        if provider == TTSProvider.OPENAI:
            return "onyx"
        import os
        for env_var in ("VOICE_TTS_DEFAULT_ELEVENLABS_VOICE_ID", "ELEVENLABS_DEFAULT_VOICE_ID"):
            val = os.environ.get(env_var)
            if val:
                return val
        raise VoiceDigestValidationError(
            "voice_id is required for elevenlabs unless VOICE_TTS_DEFAULT_ELEVENLABS_VOICE_ID is set"
        )

    def _build_digest_slug(self, digest_type: str, source_hashes: dict[str, str]) -> str:
        combined = "|".join(sorted(source_hashes.values()))
        short_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "-", digest_type.lower()).strip("-")
        return f"{slug}--{short_hash}"

    def _combine_sources(self, source_texts: list[str]) -> str:
        return "\n\n---\n\n".join(source_texts)

    def _build_summary(self, combined_text: str, *, max_chars: int) -> str:
        """Strip markdown formatting and cap to max_chars."""
        text = re.sub(r"```.*?```", " ", combined_text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"^\s{0,3}#+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s{0,3}[>*-]+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0]
        return text


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_service: VoiceDigestService | None = None


def get_voice_digest_service() -> VoiceDigestService:
    global _service
    if _service is None:
        _service = VoiceDigestService()
    return _service
