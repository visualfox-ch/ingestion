"""
Voice Text-to-Speech Service

Provides speech synthesis using OpenAI TTS API or ElevenLabs.
Supports multiple voices and streaming for long responses.

Usage:
    from app.services.voice_tts import VoiceTTS

    tts = VoiceTTS()
    result = await tts.synthesize("Hello, how are you?")
    # result.audio_bytes contains the audio data
"""

import asyncio
import io
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Optional, Union

logger = logging.getLogger(__name__)


class TTSProvider(str, Enum):
    """Available TTS providers."""
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"


class OpenAIVoice(str, Enum):
    """OpenAI TTS voices."""
    ALLOY = "alloy"      # Neutral
    ECHO = "echo"        # Warm
    FABLE = "fable"      # British
    ONYX = "onyx"        # Deep
    NOVA = "nova"        # Friendly female
    SHIMMER = "shimmer"  # Soft


class OpenAIModel(str, Enum):
    """OpenAI TTS models."""
    TTS_1 = "tts-1"          # Standard quality, low latency
    TTS_1_HD = "tts-1-hd"    # High definition quality


class OutputFormat(str, Enum):
    """Audio output formats."""
    MP3 = "mp3"
    OPUS = "opus"
    AAC = "aac"
    FLAC = "flac"
    WAV = "wav"
    PCM = "pcm"


@dataclass
class SynthesisResult:
    """Result of text-to-speech synthesis."""
    audio_bytes: bytes
    format: str = "mp3"
    duration_seconds: Optional[float] = None
    voice: Optional[str] = None
    character_count: int = 0
    raw_response: Optional[dict] = None


@dataclass
class VoiceConfig:
    """Configuration for a specific voice."""
    provider: TTSProvider = TTSProvider.OPENAI
    voice_id: str = "onyx"  # Deep, Jarvis-like voice
    model: str = "tts-1"
    speed: float = 1.0
    output_format: OutputFormat = OutputFormat.MP3

    # ElevenLabs specific
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True


# Default Jarvis voice configuration
JARVIS_VOICE = VoiceConfig(
    provider=TTSProvider.OPENAI,
    voice_id="onyx",  # Deep, authoritative
    model="tts-1-hd",  # High quality
    speed=1.0,
    output_format=OutputFormat.MP3,
)


class VoiceTTS:
    """
    Text-to-Speech service supporting multiple providers.

    Features:
    - OpenAI TTS and ElevenLabs support
    - Multiple voice options
    - Streaming for long text
    - Configurable speed and quality
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        elevenlabs_api_key: Optional[str] = None,
        default_config: Optional[VoiceConfig] = None,
    ):
        """
        Initialize Voice TTS service.

        Args:
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            elevenlabs_api_key: ElevenLabs API key (defaults to ELEVENLABS_API_KEY env var)
            default_config: Default voice configuration
        """
        self._openai_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self._elevenlabs_key = elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY")
        self._default_config = default_config or JARVIS_VOICE

        if not self._openai_key and not self._elevenlabs_key:
            logger.warning("No TTS API keys provided")

    async def synthesize(
        self,
        text: str,
        config: Optional[VoiceConfig] = None,
        stream: bool = False,
    ) -> Union[SynthesisResult, AsyncIterator[bytes]]:
        """
        Synthesize text to speech.

        Args:
            text: Text to convert to speech
            config: Voice configuration (uses default if not provided)
            stream: Return streaming iterator instead of complete audio

        Returns:
            SynthesisResult or AsyncIterator[bytes] if streaming
        """
        config = config or self._default_config

        if config.provider == TTSProvider.OPENAI:
            if stream:
                return self._synthesize_openai_stream(text, config)
            return await self._synthesize_openai(text, config)
        elif config.provider == TTSProvider.ELEVENLABS:
            if stream:
                return self._synthesize_elevenlabs_stream(text, config)
            return await self._synthesize_elevenlabs(text, config)
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")

    async def _synthesize_openai(
        self,
        text: str,
        config: VoiceConfig,
    ) -> SynthesisResult:
        """Synthesize using OpenAI TTS API."""
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=self._openai_key)

            response = await client.audio.speech.create(
                model=config.model,
                voice=config.voice_id,
                input=text,
                response_format=config.output_format.value,
                speed=config.speed,
            )

            audio_bytes = response.content

            return SynthesisResult(
                audio_bytes=audio_bytes,
                format=config.output_format.value,
                voice=config.voice_id,
                character_count=len(text),
            )

        except ImportError:
            logger.error("openai package not installed")
            return SynthesisResult(
                audio_bytes=b"",
                raw_response={"error": "openai package not installed"},
            )
        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")
            return SynthesisResult(
                audio_bytes=b"",
                raw_response={"error": str(e)},
            )

    async def _synthesize_openai_stream(
        self,
        text: str,
        config: VoiceConfig,
    ) -> AsyncIterator[bytes]:
        """Stream synthesis using OpenAI TTS API."""
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=self._openai_key)

            async with client.audio.speech.with_streaming_response.create(
                model=config.model,
                voice=config.voice_id,
                input=text,
                response_format=config.output_format.value,
                speed=config.speed,
            ) as response:
                async for chunk in response.iter_bytes(chunk_size=4096):
                    yield chunk

        except ImportError:
            logger.error("openai package not installed")
            yield b""
        except Exception as e:
            logger.error(f"OpenAI TTS streaming error: {e}")
            yield b""

    async def _synthesize_elevenlabs(
        self,
        text: str,
        config: VoiceConfig,
    ) -> SynthesisResult:
        """Synthesize using ElevenLabs API."""
        try:
            import aiohttp

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.voice_id}"

            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self._elevenlabs_key,
            }

            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": config.stability,
                    "similarity_boost": config.similarity_boost,
                    "style": config.style,
                    "use_speaker_boost": config.use_speaker_boost,
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        audio_bytes = await response.read()
                        return SynthesisResult(
                            audio_bytes=audio_bytes,
                            format="mp3",
                            voice=config.voice_id,
                            character_count=len(text),
                        )
                    else:
                        error = await response.text()
                        logger.error(f"ElevenLabs error: {error}")
                        return SynthesisResult(
                            audio_bytes=b"",
                            raw_response={"error": error, "status": response.status},
                        )

        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
            return SynthesisResult(
                audio_bytes=b"",
                raw_response={"error": str(e)},
            )

    async def _synthesize_elevenlabs_stream(
        self,
        text: str,
        config: VoiceConfig,
    ) -> AsyncIterator[bytes]:
        """Stream synthesis using ElevenLabs API."""
        try:
            import aiohttp

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.voice_id}/stream"

            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self._elevenlabs_key,
            }

            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": config.stability,
                    "similarity_boost": config.similarity_boost,
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        async for chunk in response.content.iter_chunked(4096):
                            yield chunk
                    else:
                        logger.error(f"ElevenLabs stream error: {response.status}")
                        yield b""

        except Exception as e:
            logger.error(f"ElevenLabs streaming error: {e}")
            yield b""

    async def list_voices(self, provider: Optional[TTSProvider] = None) -> list:
        """
        List available voices.

        Args:
            provider: Specific provider to list voices for

        Returns:
            List of available voices
        """
        voices = []

        if provider is None or provider == TTSProvider.OPENAI:
            voices.extend([
                {"provider": "openai", "id": v.value, "name": v.value.title()}
                for v in OpenAIVoice
            ])

        if provider is None or provider == TTSProvider.ELEVENLABS:
            if self._elevenlabs_key:
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.elevenlabs.io/v1/voices",
                            headers={"xi-api-key": self._elevenlabs_key},
                        ) as response:
                            if response.status != 200:
                                detail = (await response.text()).strip()
                                raise RuntimeError(
                                    f"ElevenLabs voices API error ({response.status}): {detail[:240]}"
                                )

                            data = await response.json()
                            voices.extend([
                                {
                                    "provider": "elevenlabs",
                                    "id": v["voice_id"],
                                    "name": v["name"],
                                }
                                for v in data.get("voices", [])
                            ])
                except RuntimeError:
                    raise
                except Exception as e:
                    logger.error(f"Failed to fetch ElevenLabs voices: {e}")
                    raise RuntimeError("Failed to fetch ElevenLabs voices") from e

        return voices

    async def save_to_file(
        self,
        text: str,
        file_path: Union[str, Path],
        config: Optional[VoiceConfig] = None,
    ) -> bool:
        """
        Synthesize and save to file.

        Args:
            text: Text to synthesize
            file_path: Output file path
            config: Voice configuration

        Returns:
            True if successful
        """
        result = await self.synthesize(text, config)
        if result.audio_bytes:
            with open(file_path, "wb") as f:
                f.write(result.audio_bytes)
            return True
        return False


# Singleton instance
_default_tts: Optional[VoiceTTS] = None


def get_tts() -> VoiceTTS:
    """Get the default TTS instance."""
    global _default_tts
    if _default_tts is None:
        _default_tts = VoiceTTS()
    return _default_tts


async def synthesize_speech(
    text: str,
    voice: Optional[str] = None,
    provider: TTSProvider = TTSProvider.OPENAI,
) -> SynthesisResult:
    """
    Convenience function to synthesize speech.

    Args:
        text: Text to convert
        voice: Voice ID (uses default Jarvis voice if not provided)
        provider: TTS provider to use

    Returns:
        SynthesisResult
    """
    tts = get_tts()

    config = VoiceConfig(
        provider=provider,
        voice_id=voice or JARVIS_VOICE.voice_id,
    )

    return await tts.synthesize(text, config)
