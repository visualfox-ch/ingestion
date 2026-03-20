"""
Voice API Router

REST endpoints for voice services:
- Speech-to-text transcription
- Text-to-speech synthesis
- User voice preferences
"""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


# =============================================================================
# Request/Response Models
# =============================================================================


class TranscribeRequest(BaseModel):
    """Request for transcription with base64 audio."""
    audio_base64: str = Field(..., description="Base64-encoded audio data")
    format: Optional[str] = Field(None, description="Audio format (ogg, mp3, wav, etc.)")
    language: Optional[str] = Field(None, description="Language hint (ISO 639-1 code)")
    user_id: Optional[str] = Field(None, description="User ID for preference lookup")


class TranscribeResponse(BaseModel):
    """Transcription response."""
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    processing_time_ms: float = 0.0


class SynthesizeRequest(BaseModel):
    """Request for speech synthesis."""
    text: str = Field(..., description="Text to convert to speech")
    voice: Optional[str] = Field(None, description="Voice ID (default: onyx)")
    speed: float = Field(1.0, ge=0.25, le=4.0, description="Speech speed multiplier")
    format: str = Field("mp3", description="Output format (mp3, opus, aac, flac, wav)")
    user_id: Optional[str] = Field(None, description="User ID for preference lookup")


class SynthesizeResponse(BaseModel):
    """Speech synthesis response."""
    audio_base64: str
    format: str
    duration_seconds: Optional[float] = None
    character_count: int


class VoicePreferenceRequest(BaseModel):
    """Request to update voice preferences."""
    preference: str = Field(
        "voice_in",
        description="Voice mode: text_only, voice_in, voice_out, full_voice, auto"
    )
    preferred_language: Optional[str] = Field(None, description="Preferred language code")
    voice_id: Optional[str] = Field(None, description="Custom voice ID for responses")
    voice_speed: float = Field(1.0, ge=0.25, le=4.0, description="Speech speed")
    auto_transcribe: bool = Field(True, description="Auto-transcribe voice messages")


class VoicePreferenceResponse(BaseModel):
    """Voice preference response."""
    user_id: str
    preference: str
    preferred_language: Optional[str]
    voice_id: Optional[str]
    voice_speed: float
    auto_transcribe: bool


class VoiceListResponse(BaseModel):
    """List of available voices."""
    voices: list


class HealthResponse(BaseModel):
    """Voice service health status."""
    status: str
    stt_available: bool
    tts_available: bool
    openai_configured: bool
    elevenlabs_configured: bool


class ProoflistPreviewRequest(BaseModel):
    """Request payload for a read-only markdown prooflist preview."""
    source_path: str = Field(..., description="Absolute markdown source path")
    output_root: str = Field(
        "/brain/data/audio_prooflists/visualfox",
        description="Absolute output root under /brain/data/audio_prooflists/",
    )
    provider: str = Field("elevenlabs", description="TTS provider: elevenlabs or openai")
    voice: Optional[str] = Field(None, description="Provider voice ID")
    speed: float = Field(1.0, ge=0.25, le=4.0, description="Speech speed multiplier")
    format: str = Field("mp3", description="Output format (mp3, opus, aac, flac, wav)")
    overwrite: bool = Field(False, description="Overwrite existing generated artifacts")


class ProoflistPreviewResponse(BaseModel):
    """Response payload with generated prooflist artifact paths and traceability."""
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


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def voice_health():
    """Check voice service health."""
    import os

    openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    elevenlabs_key = bool(os.environ.get("ELEVENLABS_API_KEY"))

    return HealthResponse(
        status="healthy" if openai_key or elevenlabs_key else "degraded",
        stt_available=openai_key,
        tts_available=openai_key or elevenlabs_key,
        openai_configured=openai_key,
        elevenlabs_configured=elevenlabs_key,
    )


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(request: TranscribeRequest):
    """
    Transcribe audio to text.

    Accepts base64-encoded audio and returns transcribed text.
    """
    import time

    try:
        from ..services.voice_handler import get_voice_handler

        handler = get_voice_handler()
        start_time = time.time()

        # Decode audio
        try:
            audio_bytes = base64.b64decode(request.audio_base64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")

        # Transcribe
        result = await handler.process_voice_message(
            audio=audio_bytes,
            user_id=request.user_id or "api_user",
            channel="api",
            format=request.format,
            language_hint=request.language,
        )

        return TranscribeResponse(
            text=result.transcription.text,
            language=result.language_detected,
            duration_seconds=result.duration_seconds,
            processing_time_ms=result.processing_time_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcribe/file", response_model=TranscribeResponse)
async def transcribe_audio_file(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
):
    """
    Transcribe uploaded audio file to text.
    """
    import time

    try:
        from ..services.voice_handler import get_voice_handler

        handler = get_voice_handler()
        start_time = time.time()

        # Read file
        audio_bytes = await file.read()

        # Determine format from filename
        format = None
        if file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ["mp3", "ogg", "wav", "m4a", "webm", "flac"]:
                format = ext

        # Transcribe
        result = await handler.process_voice_message(
            audio=audio_bytes,
            user_id=user_id or "api_user",
            channel="api",
            format=format,
            language_hint=language,
        )

        return TranscribeResponse(
            text=result.transcription.text,
            language=result.language_detected,
            duration_seconds=result.duration_seconds,
            processing_time_ms=result.processing_time_ms,
        )

    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize_speech(request: SynthesizeRequest):
    """
    Convert text to speech.

    Returns base64-encoded audio data.
    """
    try:
        from ..services.voice_tts import get_tts, VoiceConfig, OutputFormat

        tts = get_tts()

        # Build config
        config = VoiceConfig(
            voice_id=request.voice or "onyx",
            speed=request.speed,
            output_format=OutputFormat(request.format),
        )

        # Synthesize
        result = await tts.synthesize(request.text, config)

        if not result.audio_bytes:
            raise HTTPException(
                status_code=500,
                detail=result.raw_response.get("error", "Synthesis failed")
            )

        return SynthesizeResponse(
            audio_base64=base64.b64encode(result.audio_bytes).decode(),
            format=result.format,
            duration_seconds=result.duration_seconds,
            character_count=result.character_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/voices", response_model=VoiceListResponse)
async def list_voices(provider: Optional[str] = None):
    """
    List available TTS voices.

    Optionally filter by provider (openai, elevenlabs).
    """
    try:
        from ..services.voice_tts import get_tts, TTSProvider

        tts = get_tts()

        provider_enum = None
        if provider:
            try:
                provider_enum = TTSProvider(provider.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid provider: {provider}. Use 'openai' or 'elevenlabs'"
                )

        voices = await tts.list_voices(provider_enum)

        return VoiceListResponse(voices=voices)

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.warning(f"List voices upstream error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"List voices error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prooflist/preview", response_model=ProoflistPreviewResponse)
async def prooflist_preview(request: ProoflistPreviewRequest):
    """Generate a read-only prooflist audio preview from a markdown draft."""
    try:
        from ..services.voice_prooflist import (
            VoiceProoflistSynthesisError,
            VoiceProoflistValidationError,
            get_voice_prooflist_service,
        )
        from ..services.voice_tts import OutputFormat, TTSProvider

        service = get_voice_prooflist_service()

        try:
            provider = TTSProvider(request.provider.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider: {request.provider}. Use 'openai' or 'elevenlabs'",
            )

        try:
            output_format = OutputFormat(request.format.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid format: {request.format}. Use mp3, opus, aac, flac, or wav",
            )

        result = await service.generate_preview(
            source_path=request.source_path,
            output_root=request.output_root,
            provider=provider,
            voice_id=request.voice,
            speed=request.speed,
            output_format=output_format,
            overwrite=request.overwrite,
        )

        return ProoflistPreviewResponse(
            source_path=result.source_path,
            output_audio_path=result.output_audio_path,
            output_metadata_path=result.output_metadata_path,
            provider=result.provider,
            voice_id=result.voice_id,
            format=result.format,
            character_count=result.character_count,
            source_sha256=result.source_sha256,
            review_status=result.review_status,
            review_options=result.review_options,
        )

    except HTTPException:
        raise
    except VoiceProoflistValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VoiceProoflistSynthesisError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Prooflist preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preferences/{user_id}", response_model=VoicePreferenceResponse)
async def get_voice_preferences(user_id: str):
    """Get voice preferences for a user."""
    try:
        from ..services.voice_handler import get_voice_handler

        handler = get_voice_handler()
        settings = handler.get_user_settings(user_id)

        return VoicePreferenceResponse(
            user_id=settings.user_id,
            preference=settings.preference.value,
            preferred_language=settings.preferred_language,
            voice_id=settings.voice_id,
            voice_speed=settings.voice_speed,
            auto_transcribe=settings.auto_transcribe,
        )

    except Exception as e:
        logger.error(f"Get preferences error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/preferences/{user_id}", response_model=VoicePreferenceResponse)
async def update_voice_preferences(user_id: str, request: VoicePreferenceRequest):
    """Update voice preferences for a user."""
    try:
        from ..services.voice_handler import get_voice_handler, VoicePreference

        handler = get_voice_handler()

        # Validate preference
        try:
            preference = VoicePreference(request.preference)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid preference: {request.preference}"
            )

        settings = handler.update_user_settings(
            user_id=user_id,
            preference=preference,
            preferred_language=request.preferred_language,
            voice_id=request.voice_id,
            voice_speed=request.voice_speed,
            auto_transcribe=request.auto_transcribe,
        )

        return VoicePreferenceResponse(
            user_id=settings.user_id,
            preference=settings.preference.value,
            preferred_language=settings.preferred_language,
            voice_id=settings.voice_id,
            voice_speed=settings.voice_speed,
            auto_transcribe=settings.auto_transcribe,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update preferences error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
