"""
Jarvis Channel Adapters - Multi-Platform Messaging Support

Inspired by OpenClaw's multi-channel architecture, this module provides
a unified interface for different messaging platforms.

Supported Channels:
- Telegram (primary)
- Discord (available)
- WhatsApp (requires bridge service)

Usage:
    from app.channels import ChannelManager, TelegramAdapter, DiscordAdapter

    manager = ChannelManager()
    manager.register(TelegramAdapter())
    manager.register(DiscordAdapter())

    # Send message through any channel
    await manager.send_message(channel="telegram", chat_id="123", text="Hello")
"""

from .base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelUser,
    ChannelType,
    MessageType,
    MediaAttachment,
)
from .manager import ChannelManager
from .telegram import TelegramAdapter, get_shared_adapter
from .discord import DiscordAdapter
from .whatsapp import WhatsAppAdapter

__all__ = [
    # Base classes
    "ChannelAdapter",
    "ChannelMessage",
    "ChannelUser",
    "ChannelType",
    "MessageType",
    "MediaAttachment",
    # Manager
    "ChannelManager",
    # Adapters
    "TelegramAdapter",
    "DiscordAdapter",
    "WhatsAppAdapter",
    "get_shared_adapter",
]
