"""
Base Channel Adapter Interface

Defines the abstract interface that all channel adapters must implement.
This enables a unified API for sending/receiving messages across different
messaging platforms (Telegram, WhatsApp, Discord, etc.)

Design Goals:
- Platform-agnostic message handling
- Consistent user/chat identification
- Support for text, media, and rich content
- Event-driven architecture for incoming messages
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union
import asyncio


class ChannelType(str, Enum):
    """Supported messaging channels."""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    SIGNAL = "signal"
    SLACK = "slack"
    WEB = "web"  # Web chat interface


class MessageType(str, Enum):
    """Types of messages that can be sent/received."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    VOICE = "voice"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    POLL = "poll"
    COMMAND = "command"  # Slash commands like /start
    CALLBACK = "callback"  # Button callbacks
    REACTION = "reaction"  # Emoji reactions


@dataclass
class MediaAttachment:
    """Represents a media file attached to a message."""
    type: MessageType
    file_id: Optional[str] = None  # Platform-specific file ID
    file_path: Optional[str] = None  # Local file path
    file_url: Optional[str] = None  # Remote URL
    file_bytes: Optional[bytes] = None  # Raw bytes
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[int] = None  # For audio/video (seconds)
    width: Optional[int] = None  # For images/video
    height: Optional[int] = None
    thumbnail: Optional[bytes] = None
    caption: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "file_id": self.file_id,
            "file_path": self.file_path,
            "file_url": self.file_url,
            "mime_type": self.mime_type,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "caption": self.caption,
        }


@dataclass
class ChannelUser:
    """Represents a user on any messaging platform."""
    id: str  # Platform-specific user ID
    channel: ChannelType
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    phone: Optional[str] = None  # For WhatsApp
    avatar_url: Optional[str] = None
    is_bot: bool = False
    language_code: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Platform-specific data

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        if self.display_name:
            return self.display_name
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.username or self.id

    @property
    def unified_id(self) -> str:
        """Get a unified ID across channels: channel:user_id"""
        return f"{self.channel.value}:{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "channel": self.channel.value,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "display_name": self.display_name,
            "full_name": self.full_name,
            "unified_id": self.unified_id,
            "is_bot": self.is_bot,
            "language_code": self.language_code,
        }


@dataclass
class ChannelMessage:
    """
    Unified message format across all channels.

    This is the canonical representation that Jarvis works with internally,
    regardless of which platform the message originated from.
    """
    id: str  # Platform-specific message ID
    channel: ChannelType
    chat_id: str  # Platform-specific chat/conversation ID
    user: ChannelUser
    type: MessageType = MessageType.TEXT
    text: Optional[str] = None
    media: Optional[MediaAttachment] = None
    reply_to_message_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_group: bool = False
    group_name: Optional[str] = None
    thread_id: Optional[str] = None  # For threaded conversations
    command: Optional[str] = None  # Parsed command (without /)
    command_args: Optional[str] = None  # Command arguments
    callback_data: Optional[str] = None  # For button callbacks
    reaction: Optional[str] = None  # Emoji reaction
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Platform-specific data

    @property
    def unified_chat_id(self) -> str:
        """Get a unified chat ID across channels: channel:chat_id"""
        return f"{self.channel.value}:{self.chat_id}"

    @property
    def has_media(self) -> bool:
        """Check if message has media attachment."""
        return self.media is not None

    @property
    def is_command(self) -> bool:
        """Check if message is a command."""
        return self.type == MessageType.COMMAND or self.command is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "channel": self.channel.value,
            "chat_id": self.chat_id,
            "unified_chat_id": self.unified_chat_id,
            "user": self.user.to_dict(),
            "type": self.type.value,
            "text": self.text,
            "media": self.media.to_dict() if self.media else None,
            "reply_to_message_id": self.reply_to_message_id,
            "timestamp": self.timestamp.isoformat(),
            "is_group": self.is_group,
            "group_name": self.group_name,
            "thread_id": self.thread_id,
            "command": self.command,
            "command_args": self.command_args,
            "is_command": self.is_command,
            "has_media": self.has_media,
        }


# Type alias for message handlers
MessageHandler = Callable[[ChannelMessage], Coroutine[Any, Any, None]]


class ChannelAdapter(ABC):
    """
    Abstract base class for all channel adapters.

    Each messaging platform (Telegram, WhatsApp, Discord, etc.) must implement
    this interface to be integrated with Jarvis.

    Lifecycle:
        1. __init__() - Configure adapter with credentials
        2. start() - Connect to platform, start receiving messages
        3. handle_message() - Called for each incoming message
        4. send_message() / send_media() - Send responses
        5. stop() - Gracefully disconnect
    """

    def __init__(self, channel_type: ChannelType):
        self.channel_type = channel_type
        self._message_handlers: List[MessageHandler] = []
        self._is_running = False
        self._health_status: Dict[str, Any] = {
            "connected": False,
            "last_message_at": None,
            "error_count": 0,
            "last_error": None,
        }

    @property
    def channel_name(self) -> str:
        """Human-readable channel name."""
        return self.channel_type.value.capitalize()

    @property
    def is_running(self) -> bool:
        """Check if adapter is currently running."""
        return self._is_running

    @property
    def health_status(self) -> Dict[str, Any]:
        """Get current health status of the adapter."""
        return {
            **self._health_status,
            "channel": self.channel_type.value,
            "is_running": self._is_running,
        }

    def register_handler(self, handler: MessageHandler) -> None:
        """Register a handler for incoming messages."""
        self._message_handlers.append(handler)

    def unregister_handler(self, handler: MessageHandler) -> None:
        """Unregister a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    async def _dispatch_message(self, message: ChannelMessage) -> None:
        """Dispatch message to all registered handlers."""
        self._health_status["last_message_at"] = datetime.utcnow().isoformat()
        for handler in self._message_handlers:
            try:
                await handler(message)
            except Exception as e:
                self._health_status["error_count"] += 1
                self._health_status["last_error"] = str(e)
                # Don't re-raise - continue dispatching to other handlers

    def _mark_connected(self) -> None:
        """Mark adapter as connected."""
        self._health_status["connected"] = True
        self._is_running = True

    def _mark_disconnected(self, error: Optional[str] = None) -> None:
        """Mark adapter as disconnected."""
        self._health_status["connected"] = False
        self._is_running = False
        if error:
            self._health_status["last_error"] = error

    # =========================================================================
    # Abstract methods - must be implemented by each adapter
    # =========================================================================

    @abstractmethod
    async def start(self) -> None:
        """
        Start the adapter and begin receiving messages.

        This should:
        - Connect to the messaging platform
        - Set up webhooks or polling
        - Start the message receive loop
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the adapter gracefully.

        This should:
        - Close connections
        - Clean up resources
        - Stop any background tasks
        """
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
        disable_notification: bool = False,
        **kwargs,
    ) -> Optional[str]:
        """
        Send a text message.

        Args:
            chat_id: Platform-specific chat ID
            text: Message text
            reply_to_message_id: ID of message to reply to
            parse_mode: Text formatting (markdown, html, etc.)
            disable_notification: Send silently
            **kwargs: Platform-specific options

        Returns:
            Message ID of the sent message, or None if failed
        """
        pass

    @abstractmethod
    async def send_media(
        self,
        chat_id: str,
        media: MediaAttachment,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Send a media message (image, audio, document, etc.)

        Args:
            chat_id: Platform-specific chat ID
            media: Media attachment to send
            caption: Optional caption for the media
            reply_to_message_id: ID of message to reply to
            **kwargs: Platform-specific options

        Returns:
            Message ID of the sent message, or None if failed
        """
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> Optional[ChannelUser]:
        """
        Get information about a user.

        Args:
            user_id: Platform-specific user ID

        Returns:
            ChannelUser with user information, or None if not found
        """
        pass

    @abstractmethod
    async def get_chat_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a chat/conversation.

        Args:
            chat_id: Platform-specific chat ID

        Returns:
            Dict with chat information, or None if not found
        """
        pass

    # =========================================================================
    # Optional methods - can be overridden for additional features
    # =========================================================================

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator. Override if supported by platform."""
        pass

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Edit an existing message. Override if supported by platform."""
        return False

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message. Override if supported by platform."""
        return False

    async def send_reaction(
        self,
        chat_id: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        """React to a message. Override if supported by platform."""
        return False

    async def download_media(self, media: MediaAttachment) -> Optional[bytes]:
        """Download media content. Override if platform provides file storage."""
        return None

    async def get_message(
        self,
        chat_id: str,
        message_id: str,
    ) -> Optional[ChannelMessage]:
        """Get a specific message by ID. Override if supported by platform."""
        return None

    async def pin_message(self, chat_id: str, message_id: str) -> bool:
        """Pin a message. Override if supported by platform."""
        return False

    async def unpin_message(self, chat_id: str, message_id: str) -> bool:
        """Unpin a message. Override if supported by platform."""
        return False
