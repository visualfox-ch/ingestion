"""Utilities for generating read-only audio prooflist previews from cowork drafts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .voice_tts import OutputFormat, TTSProvider, VoiceConfig, VoiceTTS, get_tts

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_ROOT = "/brain/documents/inbox/external_projects/visualfox_claude_cowork"
ALLOWED_SOURCE_PREFIXES = (
    f"{DEFAULT_SOURCE_ROOT}/visualfox/",
    f"{DEFAULT_SOURCE_ROOT}/linkedin/",
)
ALLOWED_OUTPUT_PREFIXES = ("/brain/data/audio_prooflists/",)
DEFAULT_OUTPUT_ROOT = "/brain/data/audio_prooflists/visualfox"
DEFAULT_REVIEW_OPTIONS = ["listen", "approve", "revise", "discard"]


class VoiceProoflistError(RuntimeError):
    """Base error for prooflist preview generation."""


class VoiceProoflistValidationError(VoiceProoflistError):
    """Raised when prooflist inputs are invalid."""


class VoiceProoflistSynthesisError(VoiceProoflistError):
    """Raised when the TTS provider cannot render a preview."""


@dataclass
class ProoflistPreviewResult:
    source_path: str
    output_audio_path: str
    output_metadata_path: str
    provider: str
    voice_id: str
    format: str
    character_count: int
    source_sha256: str
    review_status: str
    review_options: list[str]


class VoiceProoflistService:
    """Render cowork markdown drafts into traceable audio preview artifacts."""

    def __init__(self, tts: VoiceTTS | None = None):
        self._tts = tts or get_tts()

    async def generate_preview(
        self,
        *,
        source_path: str,
        output_root: str = DEFAULT_OUTPUT_ROOT,
        provider: TTSProvider = TTSProvider.ELEVENLABS,
        voice_id: str | None = None,
        speed: float = 1.0,
        output_format: OutputFormat = OutputFormat.MP3,
        overwrite: bool = False,
        max_chars: int = 4000,
    ) -> ProoflistPreviewResult:
        source = self._validate_source_path(source_path)
        output_dir = self._build_output_dir(output_root, source)

        markdown_text = source.read_text(encoding="utf-8")
        preview_text = self._markdown_to_preview_text(markdown_text, max_chars=max_chars)
        if not preview_text:
            raise VoiceProoflistValidationError(
                "source_path does not contain enough readable markdown text for an audio preview"
            )

        source_sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
        preview_stem = self._build_preview_stem(source, source_sha256)
        output_audio_path = output_dir / f"{preview_stem}.{output_format.value}"
        output_metadata_path = output_dir / f"{preview_stem}.json"
        resolved_voice_id = self._resolve_voice_id(provider, voice_id)

        if overwrite or not output_audio_path.exists():
            config = VoiceConfig(
                provider=provider,
                voice_id=resolved_voice_id,
                speed=speed,
                output_format=output_format,
            )
            synthesis = await self._tts.synthesize(preview_text, config)
            if not synthesis.audio_bytes:
                raise VoiceProoflistSynthesisError(
                    (synthesis.raw_response or {}).get("error", "audio preview synthesis failed")
                )
            output_audio_path.write_bytes(synthesis.audio_bytes)
            resolved_voice_id = synthesis.voice or resolved_voice_id

        metadata = {
            "type": "visualfox_audio_prooflist_preview",
            "source_path": str(source),
            "source_relative_path": str(source.relative_to(DEFAULT_SOURCE_ROOT)),
            "source_sha256": source_sha256,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider.value,
            "voice_id": resolved_voice_id,
            "format": output_format.value,
            "character_count": len(preview_text),
            "output_audio_path": str(output_audio_path),
            "review": {
                "status": "pending_review",
                "options": DEFAULT_REVIEW_OPTIONS,
                "publish_mode": "disabled",
                "notes": "Read-only prooflist preview. Listen, then approve, revise, or discard.",
            },
            "preview_excerpt": preview_text[:280],
        }
        output_metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        return ProoflistPreviewResult(
            source_path=str(source),
            output_audio_path=str(output_audio_path),
            output_metadata_path=str(output_metadata_path),
            provider=provider.value,
            voice_id=resolved_voice_id,
            format=output_format.value,
            character_count=len(preview_text),
            source_sha256=source_sha256,
            review_status="pending_review",
            review_options=list(DEFAULT_REVIEW_OPTIONS),
        )

    def _validate_source_path(self, source_path: str) -> Path:
        if not source_path.startswith("/"):
            raise VoiceProoflistValidationError("source_path must be an absolute path")
        if not any(source_path.startswith(prefix) for prefix in ALLOWED_SOURCE_PREFIXES):
            raise VoiceProoflistValidationError(
                f"source_path must start with one of {ALLOWED_SOURCE_PREFIXES}"
            )
        source = Path(source_path)
        if source.suffix.lower() != ".md":
            raise VoiceProoflistValidationError("source_path must point to a markdown file")
        if not source.is_file():
            raise VoiceProoflistValidationError("source_path does not exist")
        return source

    def _build_output_dir(self, output_root: str, source: Path) -> Path:
        if not output_root.startswith("/"):
            raise VoiceProoflistValidationError("output_root must be an absolute path")
        if not any(output_root.startswith(prefix) for prefix in ALLOWED_OUTPUT_PREFIXES):
            raise VoiceProoflistValidationError(
                f"output_root must start with one of {ALLOWED_OUTPUT_PREFIXES}"
            )
        output_root_path = Path(output_root)
        relative_parent = source.relative_to(DEFAULT_SOURCE_ROOT).parent
        output_dir = output_root_path / relative_parent
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _resolve_voice_id(self, provider: TTSProvider, voice_id: str | None) -> str:
        if voice_id:
            return voice_id
        if provider == TTSProvider.OPENAI:
            return "onyx"

        for env_var in (
            "VOICE_TTS_DEFAULT_ELEVENLABS_VOICE_ID",
            "ELEVENLABS_DEFAULT_VOICE_ID",
        ):
            env_value = os.environ.get(env_var)
            if env_value:
                return env_value

        raise VoiceProoflistValidationError(
            "voice_id is required for elevenlabs unless VOICE_TTS_DEFAULT_ELEVENLABS_VOICE_ID is set"
        )

    def _build_preview_stem(self, source: Path, source_sha256: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", source.stem.lower()).strip("-") or "draft"
        return f"{slug}--{source_sha256[:12]}"

    def _markdown_to_preview_text(self, markdown_text: str, *, max_chars: int) -> str:
        text = re.sub(r"```.*?```", " ", markdown_text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"^\s{0,3}[#>*-]+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0].strip()
        return text


_default_voice_prooflist_service: VoiceProoflistService | None = None


def get_voice_prooflist_service() -> VoiceProoflistService:
    global _default_voice_prooflist_service
    if _default_voice_prooflist_service is None:
        _default_voice_prooflist_service = VoiceProoflistService()
    return _default_voice_prooflist_service