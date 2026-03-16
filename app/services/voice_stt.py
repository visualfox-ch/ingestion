"""
Voice Speech-to-Text Service

Provides speech recognition using OpenAI Whisper API or local Whisper model.
Supports multiple audio formats and automatic language detection.

Usage:
    from app.services.voice_stt import VoiceSTT

    stt = VoiceSTT()
    result = await stt.transcribe(audio_bytes, format="ogg")
    print(result.text)  # "Hello, how are you?"
    print(result.language)  # "en"
"""

import asyncio
import io
import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class AudioFormat(str, Enum):
    """Supported audio formats."""
    MP3 = "mp3"
    MP4 = "mp4"
    MPEG = "mpeg"
    MPGA = "mpga"
    M4A = "m4a"
    WAV = "wav"
    WEBM = "webm"
    OGG = "ogg"
    OGA = "oga"
    FLAC = "flac"


class WhisperModel(str, Enum):
    """Available Whisper models."""
    WHISPER_1 = "whisper-1"  # OpenAI API
    # Local models (if using local Whisper)
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"


@dataclass
class TranscriptionResult:
    """Result of speech-to-text transcription."""
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    confidence: Optional[float] = None
    segments: Optional[list] = None
    raw_response: Optional[dict] = None


class VoiceSTT:
    """
    Speech-to-Text service using OpenAI Whisper API.

    Features:
    - Multiple audio format support
    - Automatic language detection
    - Optional language hint for better accuracy
    - Timestamp segments for long audio
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: WhisperModel = WhisperModel.WHISPER_1,
        use_local: bool = False,
    ):
        """
        Initialize Voice STT service.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Whisper model to use
            use_local: Use local Whisper model instead of API
        """
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._use_local = use_local
        self._local_model = None

        if not self._use_local and not self._api_key:
            logger.warning("No OpenAI API key provided for STT service")

    async def transcribe(
        self,
        audio: Union[bytes, Path, str],
        format: Optional[str] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        response_format: str = "json",
        temperature: float = 0.0,
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio: Audio data as bytes, file path, or URL
            format: Audio format hint (auto-detected if not provided)
            language: Language hint (ISO 639-1 code, e.g., "en", "de")
            prompt: Optional prompt to guide transcription style
            response_format: Output format ("json", "text", "srt", "vtt", "verbose_json")
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            TranscriptionResult with transcribed text
        """
        if self._use_local:
            return await self._transcribe_local(audio, format, language)

        return await self._transcribe_api(
            audio, format, language, prompt, response_format, temperature
        )

    async def _transcribe_api(
        self,
        audio: Union[bytes, Path, str],
        format: Optional[str],
        language: Optional[str],
        prompt: Optional[str],
        response_format: str,
        temperature: float,
    ) -> TranscriptionResult:
        """Transcribe using OpenAI Whisper API."""
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=self._api_key)

            # Prepare audio file
            if isinstance(audio, bytes):
                # Create temp file with appropriate extension
                ext = format or "ogg"
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                    f.write(audio)
                    temp_path = f.name

                try:
                    with open(temp_path, "rb") as audio_file:
                        response = await client.audio.transcriptions.create(
                            model=self._model.value,
                            file=audio_file,
                            language=language,
                            prompt=prompt,
                            response_format=response_format,
                            temperature=temperature,
                        )
                finally:
                    os.unlink(temp_path)

            elif isinstance(audio, (Path, str)):
                with open(audio, "rb") as audio_file:
                    response = await client.audio.transcriptions.create(
                        model=self._model.value,
                        file=audio_file,
                        language=language,
                        prompt=prompt,
                        response_format=response_format,
                        temperature=temperature,
                    )
            else:
                raise ValueError(f"Unsupported audio type: {type(audio)}")

            # Parse response based on format
            if response_format == "text":
                return TranscriptionResult(text=response)
            elif response_format == "verbose_json":
                return TranscriptionResult(
                    text=response.text,
                    language=response.language,
                    duration_seconds=response.duration,
                    segments=[
                        {
                            "start": s.start,
                            "end": s.end,
                            "text": s.text,
                        }
                        for s in (response.segments or [])
                    ],
                    raw_response=response.model_dump(),
                )
            else:
                return TranscriptionResult(
                    text=response.text,
                    language=getattr(response, "language", language),
                )

        except ImportError:
            logger.error("openai package not installed")
            return TranscriptionResult(
                text="",
                raw_response={"error": "openai package not installed"},
            )
        except Exception as e:
            logger.error(f"Whisper API error: {e}")
            return TranscriptionResult(
                text="",
                raw_response={"error": str(e)},
            )

    async def _transcribe_local(
        self,
        audio: Union[bytes, Path, str],
        format: Optional[str],
        language: Optional[str],
    ) -> TranscriptionResult:
        """Transcribe using local Whisper model."""
        try:
            import whisper

            # Load model lazily
            if self._local_model is None:
                model_name = self._model.value
                if model_name == "whisper-1":
                    model_name = "base"  # Default for local
                logger.info(f"Loading local Whisper model: {model_name}")
                self._local_model = whisper.load_model(model_name)

            # Handle audio input
            if isinstance(audio, bytes):
                ext = format or "ogg"
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                    f.write(audio)
                    audio_path = f.name
                cleanup = True
            else:
                audio_path = str(audio)
                cleanup = False

            try:
                # Run transcription in thread pool (CPU-bound)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self._local_model.transcribe(
                        audio_path,
                        language=language,
                    ),
                )
            finally:
                if cleanup:
                    os.unlink(audio_path)

            return TranscriptionResult(
                text=result["text"].strip(),
                language=result.get("language"),
                segments=[
                    {
                        "start": s["start"],
                        "end": s["end"],
                        "text": s["text"],
                    }
                    for s in result.get("segments", [])
                ],
                raw_response=result,
            )

        except ImportError:
            logger.error("whisper package not installed for local transcription")
            return TranscriptionResult(
                text="",
                raw_response={"error": "whisper package not installed"},
            )
        except Exception as e:
            logger.error(f"Local Whisper error: {e}")
            return TranscriptionResult(
                text="",
                raw_response={"error": str(e)},
            )

    async def detect_language(
        self,
        audio: Union[bytes, Path, str],
        format: Optional[str] = None,
    ) -> Optional[str]:
        """
        Detect the language of audio content.

        Args:
            audio: Audio data
            format: Audio format hint

        Returns:
            ISO 639-1 language code or None
        """
        result = await self.transcribe(
            audio,
            format=format,
            response_format="verbose_json",
        )
        return result.language


# Singleton instance for convenience
_default_stt: Optional[VoiceSTT] = None


def get_stt() -> VoiceSTT:
    """Get the default STT instance."""
    global _default_stt
    if _default_stt is None:
        _default_stt = VoiceSTT()
    return _default_stt


async def transcribe_audio(
    audio: Union[bytes, Path, str],
    format: Optional[str] = None,
    language: Optional[str] = None,
) -> TranscriptionResult:
    """
    Convenience function to transcribe audio.

    Args:
        audio: Audio data as bytes, file path, or URL
        format: Audio format hint
        language: Language hint

    Returns:
        TranscriptionResult
    """
    stt = get_stt()
    return await stt.transcribe(audio, format=format, language=language)
