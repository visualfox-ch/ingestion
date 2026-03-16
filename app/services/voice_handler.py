"""
Voice Message Handler

Orchestrates voice message processing across channels:
- Automatic transcription of incoming voice messages
- Optional voice responses
- User preference management for voice features

Usage:
    from app.services.voice_handler import VoiceHandler

    handler = VoiceHandler()

    # Process incoming voice message
    text = await handler.process_voice_message(audio_bytes, user_id="123")

    # Generate voice response if user prefers it
    audio = await handler.generate_voice_response("Hello!", user_id="123")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Union

from .voice_stt import VoiceSTT, TranscriptionResult, get_stt
from .voice_tts import VoiceTTS, SynthesisResult, VoiceConfig, get_tts, JARVIS_VOICE

logger = logging.getLogger(__name__)


class VoicePreference(str, Enum):
    """User voice preferences."""
    TEXT_ONLY = "text_only"           # Never use voice
    VOICE_IN_TEXT_OUT = "voice_in"    # Transcribe voice, respond with text
    TEXT_IN_VOICE_OUT = "voice_out"   # Text input, respond with voice
    FULL_VOICE = "full_voice"         # Voice in and out
    AUTO = "auto"                     # Match input type


@dataclass
class UserVoiceSettings:
    """Voice settings for a user."""
    user_id: str
    preference: VoicePreference = VoicePreference.VOICE_IN_TEXT_OUT
    preferred_language: Optional[str] = None  # ISO 639-1 code
    voice_id: Optional[str] = None  # Custom voice for responses
    voice_speed: float = 1.0
    auto_transcribe: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class VoiceMessageResult:
    """Result of processing a voice message."""
    transcription: TranscriptionResult
    user_id: str
    channel: str
    duration_seconds: Optional[float] = None
    language_detected: Optional[str] = None
    processing_time_ms: float = 0.0


@dataclass
class VoiceResponseResult:
    """Result of generating a voice response."""
    synthesis: SynthesisResult
    text: str
    user_id: str
    voice_used: str
    format: str = "mp3"


class VoiceHandler:
    """
    Central handler for voice message processing.

    Integrates STT and TTS services with user preferences and channel adapters.
    """

    def __init__(
        self,
        stt: Optional[VoiceSTT] = None,
        tts: Optional[VoiceTTS] = None,
        state_path: Optional[str] = None,
    ):
        """
        Initialize Voice Handler.

        Args:
            stt: Speech-to-text service (uses default if not provided)
            tts: Text-to-speech service (uses default if not provided)
            state_path: Path to store user preferences
        """
        self._stt = stt or get_stt()
        self._tts = tts or get_tts()
        self._state_path = Path(
            state_path or os.environ.get(
                "VOICE_STATE_PATH",
                "/brain/system/state/voice_preferences.json"
            )
        )

        # In-memory cache of user settings
        self._user_settings: Dict[str, UserVoiceSettings] = {}
        self._load_settings()

    def _load_settings(self) -> None:
        """Load user settings from disk."""
        try:
            if self._state_path.exists():
                import json
                with open(self._state_path) as f:
                    data = json.load(f)
                for user_id, settings in data.items():
                    self._user_settings[user_id] = UserVoiceSettings(
                        user_id=user_id,
                        preference=VoicePreference(settings.get("preference", "voice_in")),
                        preferred_language=settings.get("preferred_language"),
                        voice_id=settings.get("voice_id"),
                        voice_speed=settings.get("voice_speed", 1.0),
                        auto_transcribe=settings.get("auto_transcribe", True),
                    )
                logger.info(f"Loaded voice settings for {len(self._user_settings)} users")
        except Exception as e:
            logger.warning(f"Failed to load voice settings: {e}")

    def _save_settings(self) -> None:
        """Save user settings to disk."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            data = {
                user_id: {
                    "preference": settings.preference.value,
                    "preferred_language": settings.preferred_language,
                    "voice_id": settings.voice_id,
                    "voice_speed": settings.voice_speed,
                    "auto_transcribe": settings.auto_transcribe,
                }
                for user_id, settings in self._user_settings.items()
            }
            with open(self._state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save voice settings: {e}")

    def get_user_settings(self, user_id: str) -> UserVoiceSettings:
        """Get voice settings for a user (creates default if not exists)."""
        if user_id not in self._user_settings:
            self._user_settings[user_id] = UserVoiceSettings(user_id=user_id)
        return self._user_settings[user_id]

    def update_user_settings(
        self,
        user_id: str,
        preference: Optional[VoicePreference] = None,
        preferred_language: Optional[str] = None,
        voice_id: Optional[str] = None,
        voice_speed: Optional[float] = None,
        auto_transcribe: Optional[bool] = None,
    ) -> UserVoiceSettings:
        """
        Update voice settings for a user.

        Args:
            user_id: User identifier
            preference: Voice preference mode
            preferred_language: Preferred language for transcription
            voice_id: Custom voice for responses
            voice_speed: Speech speed multiplier
            auto_transcribe: Whether to auto-transcribe voice messages

        Returns:
            Updated settings
        """
        settings = self.get_user_settings(user_id)

        if preference is not None:
            settings.preference = preference
        if preferred_language is not None:
            settings.preferred_language = preferred_language
        if voice_id is not None:
            settings.voice_id = voice_id
        if voice_speed is not None:
            settings.voice_speed = voice_speed
        if auto_transcribe is not None:
            settings.auto_transcribe = auto_transcribe

        settings.updated_at = datetime.utcnow()
        self._save_settings()

        return settings

    async def process_voice_message(
        self,
        audio: Union[bytes, Path, str],
        user_id: str,
        channel: str = "telegram",
        format: Optional[str] = None,
        language_hint: Optional[str] = None,
    ) -> VoiceMessageResult:
        """
        Process an incoming voice message.

        Args:
            audio: Audio data (bytes, file path, or URL)
            user_id: User identifier
            channel: Source channel (telegram, whatsapp, discord)
            format: Audio format hint
            language_hint: Language hint for better transcription

        Returns:
            VoiceMessageResult with transcription
        """
        import time
        start_time = time.time()

        settings = self.get_user_settings(user_id)

        # Use user's preferred language if available
        language = language_hint or settings.preferred_language

        # Transcribe
        transcription = await self._stt.transcribe(
            audio,
            format=format,
            language=language,
        )

        processing_time = (time.time() - start_time) * 1000

        result = VoiceMessageResult(
            transcription=transcription,
            user_id=user_id,
            channel=channel,
            language_detected=transcription.language,
            processing_time_ms=processing_time,
        )

        logger.info(
            f"Transcribed voice message for {user_id}: "
            f"{len(transcription.text)} chars in {processing_time:.0f}ms"
        )

        return result

    async def generate_voice_response(
        self,
        text: str,
        user_id: str,
        force_voice: bool = False,
    ) -> Optional[VoiceResponseResult]:
        """
        Generate a voice response if user prefers it.

        Args:
            text: Text to convert to speech
            user_id: User identifier
            force_voice: Generate voice even if user prefers text

        Returns:
            VoiceResponseResult if voice should be generated, None otherwise
        """
        settings = self.get_user_settings(user_id)

        # Check if user wants voice responses
        should_voice = force_voice or settings.preference in [
            VoicePreference.TEXT_IN_VOICE_OUT,
            VoicePreference.FULL_VOICE,
        ]

        if not should_voice:
            return None

        # Build voice config
        config = VoiceConfig(
            voice_id=settings.voice_id or JARVIS_VOICE.voice_id,
            speed=settings.voice_speed,
        )

        # Synthesize
        synthesis = await self._tts.synthesize(text, config)

        if not synthesis.audio_bytes:
            logger.error(f"Failed to synthesize voice for {user_id}")
            return None

        return VoiceResponseResult(
            synthesis=synthesis,
            text=text,
            user_id=user_id,
            voice_used=config.voice_id,
            format=synthesis.format,
        )

    def should_transcribe(self, user_id: str) -> bool:
        """Check if voice messages should be auto-transcribed for user."""
        settings = self.get_user_settings(user_id)
        return settings.auto_transcribe and settings.preference != VoicePreference.TEXT_ONLY

    def should_respond_with_voice(
        self,
        user_id: str,
        input_was_voice: bool = False,
    ) -> bool:
        """
        Check if response should be voice.

        Args:
            user_id: User identifier
            input_was_voice: Whether the input message was voice

        Returns:
            True if response should be voice
        """
        settings = self.get_user_settings(user_id)

        if settings.preference == VoicePreference.TEXT_ONLY:
            return False
        elif settings.preference == VoicePreference.FULL_VOICE:
            return True
        elif settings.preference == VoicePreference.TEXT_IN_VOICE_OUT:
            return True
        elif settings.preference == VoicePreference.AUTO:
            return input_was_voice
        else:
            return False


# Singleton instance
_default_handler: Optional[VoiceHandler] = None


def get_voice_handler() -> VoiceHandler:
    """Get the default voice handler instance."""
    global _default_handler
    if _default_handler is None:
        _default_handler = VoiceHandler()
    return _default_handler


async def transcribe_voice_message(
    audio: Union[bytes, Path, str],
    user_id: str,
    channel: str = "telegram",
    format: Optional[str] = None,
) -> str:
    """
    Convenience function to transcribe a voice message.

    Args:
        audio: Audio data
        user_id: User identifier
        channel: Source channel
        format: Audio format hint

    Returns:
        Transcribed text
    """
    handler = get_voice_handler()
    result = await handler.process_voice_message(audio, user_id, channel, format)
    return result.transcription.text


async def text_to_voice(
    text: str,
    user_id: str,
) -> Optional[bytes]:
    """
    Convenience function to convert text to voice.

    Args:
        text: Text to convert
        user_id: User identifier

    Returns:
        Audio bytes or None if user prefers text
    """
    handler = get_voice_handler()
    result = await handler.generate_voice_response(text, user_id)
    return result.synthesis.audio_bytes if result else None
