"""Voice digest API — POST /voice/digest (T-OC-705).

One endpoint, one digest type: strategy_weekly_digest.
Fail-closed on invalid scope. No auto-send. Operator-controlled.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice/digest", tags=["voice-digest"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class DigestRequest(BaseModel):
    digest_type: str = Field(
        ...,
        description="Digest type. Currently only 'strategy_weekly_digest' is supported.",
        examples=["strategy_weekly_digest"],
    )
    source_paths: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Absolute paths to curated .md source files. "
            "Maximum 10 files. Must be absolute paths to existing .md files."
        ),
    )
    output_root: str = Field(
        "/brain/data/audio_digests/strategy",
        description="Absolute output root. Must start with '/brain/data/audio_digests/'.",
    )
    provider: Optional[str] = Field(
        None,
        description="TTS provider: 'openai' (default) or 'elevenlabs'.",
    )
    voice_id: Optional[str] = Field(
        None,
        description="Voice ID override. Defaults to provider default.",
    )
    format: str = Field(
        "mp3",
        description="Output audio format. Default: mp3.",
    )
    overwrite: bool = Field(
        False,
        description="Re-generate even if output artifacts already exist.",
    )


class DigestResponse(BaseModel):
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
    review_status: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", response_model=DigestResponse, summary="Generate strategy audio digest")
async def generate_digest(request: DigestRequest) -> DigestResponse:
    """
    Generate a bounded strategy audio digest.

    Accepts one digest_type (strategy_weekly_digest) and a curated list of
    markdown source files. Persists summary.md, audio.mp3, and metadata.json
    under output_root. Fail-closed on invalid scope. No auto-send.
    """
    from ..services.voice_digest import (
        VoiceDigestValidationError,
        VoiceDigestSynthesisError,
        get_voice_digest_service,
    )
    from ..services.voice_tts import TTSProvider, OutputFormat

    # --- resolve enums (fail-closed on bad values) ---
    try:
        provider_enum = TTSProvider(request.provider.lower()) if request.provider else TTSProvider.OPENAI
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{request.provider}'. Use 'openai' or 'elevenlabs'.",
        )

    try:
        format_enum = OutputFormat(request.format.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{request.format}'. Use 'mp3', 'opus', 'aac', 'flac', 'wav'.",
        )

    service = get_voice_digest_service()
    try:
        result = await service.generate(
            digest_type=request.digest_type,
            source_paths=request.source_paths,
            output_root=request.output_root,
            provider=provider_enum,
            voice_id=request.voice_id,
            output_format=format_enum,
            overwrite=request.overwrite,
        )
    except VoiceDigestValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except VoiceDigestSynthesisError as exc:
        logger.error("Digest TTS synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("Digest generation error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal digest generation error")

    return DigestResponse(
        digest_type=result.digest_type,
        output_summary_path=result.output_summary_path,
        output_audio_path=result.output_audio_path,
        output_metadata_path=result.output_metadata_path,
        provider=result.provider,
        voice_id=result.voice_id,
        format=result.format,
        summary_char_count=result.summary_char_count,
        tts_char_count=result.tts_char_count,
        source_files=result.source_files,
        source_hashes=result.source_hashes,
        generated_at=result.generated_at,
        review_status=result.review_status,
    )
