"""
Multi-Channel Routing Service

Unified message routing from multiple channels (Telegram, Discord, WhatsApp)
to Jarvis agent and back. Provides channel abstraction and message normalization.

Architecture:
    [Telegram] ─┐
    [Discord]  ─┼─> [Channel Router] ─> [Jarvis Agent] ─> [Response]
    [WhatsApp] ─┘                                              │
         ↑                                                     │
         └─────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Channel Types and Message Models
# =============================================================================

class ChannelType(str, Enum):
    """Supported messaging channels."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    API = "api"  # Direct API calls


@dataclass
class UnifiedMessage:
    """
    Normalized message format for all channels.

    Provides a consistent interface regardless of source channel.
    """
    channel: ChannelType
    message_id: str
    user_id: str
    user_name: str
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Channel-specific identifiers
    chat_id: Optional[str] = None
    channel_id: Optional[str] = None
    guild_id: Optional[str] = None

    # Metadata
    is_dm: bool = False
    is_reply: bool = False
    reply_to_id: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    # Raw data for channel-specific handling
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel": self.channel.value,
            "message_id": self.message_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "chat_id": self.chat_id,
            "channel_id": self.channel_id,
            "guild_id": self.guild_id,
            "is_dm": self.is_dm,
            "is_reply": self.is_reply,
            "reply_to_id": self.reply_to_id,
            "attachments": self.attachments,
        }


@dataclass
class ChannelResponse:
    """Response to be sent back to a channel."""
    content: str
    channel: ChannelType
    target_id: str  # chat_id, channel_id, or phone number
    reply_to: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Message Adapters
# =============================================================================

def adapt_telegram_message(telegram_data: Dict[str, Any]) -> UnifiedMessage:
    """Convert Telegram message format to UnifiedMessage."""
    message = telegram_data.get("message", telegram_data)

    # Extract user info
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", "unknown"))
    user_name = from_user.get("first_name", "")
    if from_user.get("last_name"):
        user_name += f" {from_user['last_name']}"
    if not user_name:
        user_name = from_user.get("username", "Unknown")

    # Extract chat info
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    is_dm = chat.get("type") == "private"

    # Extract content
    content = message.get("text", "")
    if not content and message.get("caption"):
        content = message["caption"]

    # Check for reply
    reply_to = message.get("reply_to_message")
    reply_to_id = str(reply_to.get("message_id")) if reply_to else None

    # Extract attachments
    attachments = []
    for att_type in ["photo", "document", "audio", "voice", "video"]:
        if att_type in message:
            att_data = message[att_type]
            if isinstance(att_data, list):
                att_data = att_data[-1] if att_data else {}
            attachments.append({
                "type": att_type,
                "file_id": att_data.get("file_id"),
                "file_size": att_data.get("file_size"),
            })

    return UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        message_id=str(message.get("message_id", "")),
        user_id=user_id,
        user_name=user_name,
        content=content,
        timestamp=datetime.fromtimestamp(message.get("date", 0)),
        chat_id=chat_id,
        is_dm=is_dm,
        is_reply=reply_to_id is not None,
        reply_to_id=reply_to_id,
        attachments=attachments,
        raw_data=telegram_data,
    )


def adapt_discord_message(discord_data: Dict[str, Any]) -> UnifiedMessage:
    """Convert Discord message format to UnifiedMessage."""
    return UnifiedMessage(
        channel=ChannelType.DISCORD,
        message_id=discord_data.get("message_id", ""),
        user_id=discord_data.get("author_id", "unknown"),
        user_name=discord_data.get("author_name", "Unknown"),
        content=discord_data.get("content", ""),
        timestamp=datetime.fromisoformat(
            discord_data.get("timestamp", datetime.utcnow().isoformat())
        ),
        channel_id=discord_data.get("channel_id"),
        guild_id=discord_data.get("guild_id"),
        is_dm=discord_data.get("is_dm", False),
        attachments=discord_data.get("attachments", []),
        raw_data=discord_data,
    )


def adapt_whatsapp_message(whatsapp_data: Dict[str, Any]) -> UnifiedMessage:
    """Convert WhatsApp message format to UnifiedMessage."""
    return UnifiedMessage(
        channel=ChannelType.WHATSAPP,
        message_id=whatsapp_data.get("message_id", ""),
        user_id=whatsapp_data.get("phone", "unknown"),
        user_name=whatsapp_data.get("contact_name", whatsapp_data.get("phone", "Unknown")),
        content=whatsapp_data.get("message", ""),
        timestamp=datetime.fromisoformat(
            whatsapp_data.get("timestamp", datetime.utcnow().isoformat())
        ),
        chat_id=whatsapp_data.get("chat_id"),
        is_dm=True,  # WhatsApp messages are typically DMs
        attachments=whatsapp_data.get("attachments", []),
        raw_data=whatsapp_data,
    )


# =============================================================================
# Channel Router
# =============================================================================

class ChannelRouter:
    """
    Routes messages between channels and Jarvis.

    Provides:
    - Message normalization from different channels
    - User context management across channels
    - Response routing back to correct channel
    - Rate limiting and throttling
    """

    def __init__(self):
        self.adapters = {
            ChannelType.TELEGRAM: adapt_telegram_message,
            ChannelType.DISCORD: adapt_discord_message,
            ChannelType.WHATSAPP: adapt_whatsapp_message,
        }
        self._response_handlers: Dict[ChannelType, Callable] = {}
        self._user_channel_map: Dict[str, Dict[str, Any]] = {}

    def register_response_handler(
        self,
        channel: ChannelType,
        handler: Callable
    ):
        """
        Register a handler for sending responses to a channel.

        Args:
            channel: The channel type
            handler: Async function that sends response to channel
                    Signature: async def handler(response: ChannelResponse) -> bool
        """
        self._response_handlers[channel] = handler
        logger.info(f"Registered response handler for {channel.value}")

    def normalize_message(
        self,
        channel: ChannelType,
        raw_message: Dict[str, Any]
    ) -> UnifiedMessage:
        """
        Convert channel-specific message to unified format.

        Args:
            channel: Source channel type
            raw_message: Raw message data from channel

        Returns:
            Normalized UnifiedMessage
        """
        adapter = self.adapters.get(channel)
        if not adapter:
            raise ValueError(f"No adapter for channel: {channel}")

        return adapter(raw_message)

    async def process_message(
        self,
        message: UnifiedMessage
    ) -> Optional[str]:
        """
        Process a message through Jarvis and return response.

        Args:
            message: Normalized message

        Returns:
            Response text or None
        """
        try:
            # Import agent dynamically to avoid circular imports
            from .. import agent

            # Build context from channel
            context = self._build_context(message)

            # Call Jarvis agent
            result = await asyncio.to_thread(
                agent.run_agent,
                user_query=message.content,
                user_id=message.user_id,
                context=context,
            )

            # Extract response
            if isinstance(result, dict):
                return result.get("answer", str(result))
            return str(result) if result else None

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return f"Error processing message: {str(e)}"

    def _build_context(self, message: UnifiedMessage) -> str:
        """Build context string for agent."""
        parts = [f"channel:{message.channel.value}"]

        if message.guild_id:
            parts.append(f"guild:{message.guild_id}")
        if message.channel_id:
            parts.append(f"channel_id:{message.channel_id}")
        if message.is_dm:
            parts.append("dm:true")

        return ",".join(parts)

    async def send_response(
        self,
        response: ChannelResponse
    ) -> bool:
        """
        Send a response back to the originating channel.

        Args:
            response: Response to send

        Returns:
            True if sent successfully
        """
        handler = self._response_handlers.get(response.channel)
        if not handler:
            logger.warning(f"No handler for channel {response.channel}")
            return False

        try:
            return await handler(response)
        except Exception as e:
            logger.error(f"Error sending response to {response.channel}: {e}")
            return False

    def map_user_identity(
        self,
        user_id: str,
        channel: ChannelType,
        channel_user_id: str
    ):
        """
        Map a channel-specific user ID to unified user ID.

        Enables cross-channel user recognition.
        """
        if user_id not in self._user_channel_map:
            self._user_channel_map[user_id] = {}

        self._user_channel_map[user_id][channel.value] = channel_user_id

    def get_user_channels(self, user_id: str) -> Dict[str, str]:
        """Get all channel IDs for a user."""
        return self._user_channel_map.get(user_id, {})


# =============================================================================
# Global Router Instance
# =============================================================================

_channel_router: Optional[ChannelRouter] = None


def get_channel_router() -> ChannelRouter:
    """Get the global channel router instance."""
    global _channel_router
    if _channel_router is None:
        _channel_router = ChannelRouter()
    return _channel_router


async def route_message(raw_message: Dict[str, Any]) -> Optional[str]:
    """
    Route a message from any channel through Jarvis.

    This is the main entry point for channel integrations.

    Args:
        raw_message: Raw message data with 'channel' field indicating source

    Returns:
        Response text or None
    """
    router = get_channel_router()

    # Determine channel from message
    channel_str = raw_message.get("channel", "api")
    try:
        channel = ChannelType(channel_str)
    except ValueError:
        channel = ChannelType.API

    # Normalize message
    if channel == ChannelType.API:
        # API messages are already normalized
        message = UnifiedMessage(
            channel=ChannelType.API,
            message_id=raw_message.get("message_id", "api"),
            user_id=raw_message.get("user_id", "api"),
            user_name=raw_message.get("user_name", "API User"),
            content=raw_message.get("content", raw_message.get("query", "")),
        )
    else:
        message = router.normalize_message(channel, raw_message)

    # Process through Jarvis
    return await router.process_message(message)


# =============================================================================
# Response Handlers
# =============================================================================

async def send_telegram_response(response: ChannelResponse) -> bool:
    """Send response to Telegram."""
    try:
        # Use existing telegram bot
        from ..telegram_bot import send_telegram_message

        success = await send_telegram_message(
            chat_id=int(response.target_id),
            text=response.content,
            reply_to=int(response.reply_to) if response.reply_to else None,
        )
        return success

    except Exception as e:
        logger.error(f"Failed to send Telegram response: {e}")
        return False


async def send_discord_response(response: ChannelResponse) -> bool:
    """Send response to Discord."""
    try:
        from .discord_bot import get_discord_bot

        bot = get_discord_bot()
        if not bot or not bot.is_ready:
            return False

        return await bot.send_message(int(response.target_id), response.content)

    except Exception as e:
        logger.error(f"Failed to send Discord response: {e}")
        return False


async def send_whatsapp_response(response: ChannelResponse) -> bool:
    """Send response to WhatsApp."""
    try:
        import aiohttp
        import os

        bridge_url = os.environ.get("WHATSAPP_BRIDGE_URL", "http://localhost:3000")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{bridge_url}/send",
                json={
                    "chatId": f"{response.target_id}@c.us",
                    "message": response.content,
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                return resp.status == 200

    except Exception as e:
        logger.error(f"Failed to send WhatsApp response: {e}")
        return False


def init_response_handlers():
    """Initialize response handlers for all channels."""
    router = get_channel_router()
    router.register_response_handler(ChannelType.TELEGRAM, send_telegram_response)
    router.register_response_handler(ChannelType.DISCORD, send_discord_response)
    router.register_response_handler(ChannelType.WHATSAPP, send_whatsapp_response)
