"""
Channel Manager - Central Hub for Multi-Platform Messaging

Manages registration, routing, and lifecycle of channel adapters.
Provides a unified interface for sending messages across any platform.

Usage:
    manager = ChannelManager()
    manager.register(TelegramAdapter(bot_token="..."))
    manager.register(WhatsAppAdapter(session_path="..."))

    # Send to specific channel
    await manager.send_message("telegram", chat_id="123", text="Hello")

    # Broadcast to all channels for a user
    await manager.broadcast(user_id="user123", text="Important update")
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from .base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelType,
    ChannelUser,
    MediaAttachment,
    MessageHandler,
)

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Central manager for all channel adapters.

    Responsibilities:
    - Register/unregister channel adapters
    - Route outgoing messages to the correct adapter
    - Dispatch incoming messages to handlers
    - Track user presence across channels
    - Manage adapter lifecycle (start/stop)
    """

    def __init__(self):
        self._adapters: Dict[ChannelType, ChannelAdapter] = {}
        self._message_handlers: List[MessageHandler] = []
        self._user_channels: Dict[str, Set[str]] = {}  # user_id -> set of unified_chat_ids
        self._is_running = False
        self._startup_time: Optional[datetime] = None

    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._is_running

    @property
    def registered_channels(self) -> List[str]:
        """Get list of registered channel names."""
        return [ct.value for ct in self._adapters.keys()]

    @property
    def health_status(self) -> Dict[str, Any]:
        """Get aggregated health status of all adapters."""
        adapter_statuses = {}
        for channel_type, adapter in self._adapters.items():
            adapter_statuses[channel_type.value] = adapter.health_status

        # Calculate overall health
        all_connected = all(
            status.get("connected", False)
            for status in adapter_statuses.values()
        ) if adapter_statuses else False

        any_running = any(
            status.get("is_running", False)
            for status in adapter_statuses.values()
        ) if adapter_statuses else False

        return {
            "is_running": self._is_running,
            "startup_time": self._startup_time.isoformat() if self._startup_time else None,
            "registered_channels": self.registered_channels,
            "all_connected": all_connected,
            "any_running": any_running,
            "adapters": adapter_statuses,
        }

    # =========================================================================
    # Adapter Registration
    # =========================================================================

    def register(self, adapter: ChannelAdapter) -> None:
        """
        Register a channel adapter.

        Args:
            adapter: The adapter to register

        Raises:
            ValueError: If an adapter for this channel is already registered
        """
        if adapter.channel_type in self._adapters:
            raise ValueError(
                f"Adapter for {adapter.channel_type.value} is already registered"
            )

        # Wire up message handler to dispatch through manager
        adapter.register_handler(self._on_message_received)
        self._adapters[adapter.channel_type] = adapter

        logger.info(f"Registered channel adapter: {adapter.channel_name}")

    def unregister(self, channel_type: ChannelType) -> Optional[ChannelAdapter]:
        """
        Unregister a channel adapter.

        Args:
            channel_type: The channel type to unregister

        Returns:
            The unregistered adapter, or None if not found
        """
        adapter = self._adapters.pop(channel_type, None)
        if adapter:
            adapter.unregister_handler(self._on_message_received)
            logger.info(f"Unregistered channel adapter: {adapter.channel_name}")
        return adapter

    def get_adapter(self, channel: str | ChannelType) -> Optional[ChannelAdapter]:
        """
        Get an adapter by channel type.

        Args:
            channel: Channel type (string or enum)

        Returns:
            The adapter, or None if not registered
        """
        if isinstance(channel, str):
            try:
                channel = ChannelType(channel.lower())
            except ValueError:
                return None
        return self._adapters.get(channel)

    # =========================================================================
    # Message Handler Registration
    # =========================================================================

    def register_handler(self, handler: MessageHandler) -> None:
        """Register a handler for incoming messages from any channel."""
        self._message_handlers.append(handler)

    def unregister_handler(self, handler: MessageHandler) -> None:
        """Unregister a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    async def _on_message_received(self, message: ChannelMessage) -> None:
        """
        Internal handler for messages from adapters.
        Dispatches to all registered handlers and tracks user presence.
        """
        # Track user presence
        user_id = message.user.unified_id
        if user_id not in self._user_channels:
            self._user_channels[user_id] = set()
        self._user_channels[user_id].add(message.unified_chat_id)

        # Dispatch to all handlers
        for handler in self._message_handlers:
            try:
                await handler(message)
            except Exception as e:
                logger.error(
                    f"Handler error for message {message.id}: {e}",
                    exc_info=True
                )

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """Start all registered adapters."""
        if self._is_running:
            logger.warning("ChannelManager is already running")
            return

        self._startup_time = datetime.utcnow()

        # Start all adapters concurrently
        start_tasks = []
        for adapter in self._adapters.values():
            start_tasks.append(self._start_adapter(adapter))

        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)

        self._is_running = True
        logger.info(
            f"ChannelManager started with {len(self._adapters)} adapters: "
            f"{', '.join(self.registered_channels)}"
        )

    async def _start_adapter(self, adapter: ChannelAdapter) -> None:
        """Start a single adapter with error handling."""
        try:
            await adapter.start()
            logger.info(f"Started adapter: {adapter.channel_name}")
        except Exception as e:
            logger.error(f"Failed to start {adapter.channel_name}: {e}", exc_info=True)

    async def stop(self) -> None:
        """Stop all registered adapters."""
        if not self._is_running:
            return

        # Stop all adapters concurrently
        stop_tasks = []
        for adapter in self._adapters.values():
            stop_tasks.append(self._stop_adapter(adapter))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self._is_running = False
        logger.info("ChannelManager stopped")

    async def _stop_adapter(self, adapter: ChannelAdapter) -> None:
        """Stop a single adapter with error handling."""
        try:
            await adapter.stop()
            logger.info(f"Stopped adapter: {adapter.channel_name}")
        except Exception as e:
            logger.error(f"Failed to stop {adapter.channel_name}: {e}", exc_info=True)

    # =========================================================================
    # Sending Messages
    # =========================================================================

    async def send_message(
        self,
        channel: str | ChannelType,
        chat_id: str,
        text: str,
        reply_to_message_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
        disable_notification: bool = False,
        **kwargs,
    ) -> Optional[str]:
        """
        Send a text message through a specific channel.

        Args:
            channel: Target channel (e.g., "telegram", ChannelType.TELEGRAM)
            chat_id: Platform-specific chat ID
            text: Message text
            reply_to_message_id: Optional message ID to reply to
            parse_mode: Text formatting mode
            disable_notification: Send silently
            **kwargs: Additional platform-specific options

        Returns:
            Message ID if sent successfully, None otherwise
        """
        adapter = self.get_adapter(channel)
        if not adapter:
            logger.error(f"No adapter registered for channel: {channel}")
            return None

        if not adapter.is_running:
            logger.warning(f"Adapter {adapter.channel_name} is not running")
            return None

        try:
            return await adapter.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
                **kwargs,
            )
        except Exception as e:
            logger.error(
                f"Failed to send message via {adapter.channel_name}: {e}",
                exc_info=True
            )
            return None

    async def send_media(
        self,
        channel: str | ChannelType,
        chat_id: str,
        media: MediaAttachment,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Send media through a specific channel.

        Args:
            channel: Target channel
            chat_id: Platform-specific chat ID
            media: Media attachment to send
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to
            **kwargs: Additional platform-specific options

        Returns:
            Message ID if sent successfully, None otherwise
        """
        adapter = self.get_adapter(channel)
        if not adapter:
            logger.error(f"No adapter registered for channel: {channel}")
            return None

        if not adapter.is_running:
            logger.warning(f"Adapter {adapter.channel_name} is not running")
            return None

        try:
            return await adapter.send_media(
                chat_id=chat_id,
                media=media,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                **kwargs,
            )
        except Exception as e:
            logger.error(
                f"Failed to send media via {adapter.channel_name}: {e}",
                exc_info=True
            )
            return None

    async def send_typing(
        self,
        channel: str | ChannelType,
        chat_id: str,
    ) -> None:
        """Send typing indicator through a channel."""
        adapter = self.get_adapter(channel)
        if adapter and adapter.is_running:
            try:
                await adapter.send_typing(chat_id)
            except Exception as e:
                logger.debug(f"Failed to send typing via {channel}: {e}")

    # =========================================================================
    # Broadcast & Multi-Channel Operations
    # =========================================================================

    async def broadcast(
        self,
        text: str,
        user_id: Optional[str] = None,
        channels: Optional[List[str | ChannelType]] = None,
        **kwargs,
    ) -> Dict[str, Optional[str]]:
        """
        Broadcast a message to multiple channels.

        Args:
            text: Message text
            user_id: If provided, send to all known chats for this user
            channels: List of channels to broadcast to (default: all)
            **kwargs: Additional options for send_message

        Returns:
            Dict mapping channel names to message IDs (or None if failed)
        """
        results = {}

        if user_id and user_id in self._user_channels:
            # Send to all known chats for this user
            for unified_chat_id in self._user_channels[user_id]:
                channel_name, chat_id = unified_chat_id.split(":", 1)
                msg_id = await self.send_message(
                    channel=channel_name,
                    chat_id=chat_id,
                    text=text,
                    **kwargs,
                )
                results[unified_chat_id] = msg_id
        elif channels:
            # Send to specified channels (need chat_id in kwargs)
            chat_id = kwargs.pop("chat_id", None)
            if not chat_id:
                logger.error("broadcast requires chat_id when not using user_id")
                return results

            for channel in channels:
                msg_id = await self.send_message(
                    channel=channel,
                    chat_id=chat_id,
                    text=text,
                    **kwargs,
                )
                channel_name = channel.value if isinstance(channel, ChannelType) else channel
                results[channel_name] = msg_id

        return results

    # =========================================================================
    # User & Chat Information
    # =========================================================================

    async def get_user_info(
        self,
        channel: str | ChannelType,
        user_id: str,
    ) -> Optional[ChannelUser]:
        """Get user information from a specific channel."""
        adapter = self.get_adapter(channel)
        if not adapter:
            return None

        try:
            return await adapter.get_user_info(user_id)
        except Exception as e:
            logger.error(f"Failed to get user info from {channel}: {e}")
            return None

    async def get_chat_info(
        self,
        channel: str | ChannelType,
        chat_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get chat information from a specific channel."""
        adapter = self.get_adapter(channel)
        if not adapter:
            return None

        try:
            return await adapter.get_chat_info(chat_id)
        except Exception as e:
            logger.error(f"Failed to get chat info from {channel}: {e}")
            return None

    def get_user_channels(self, user_id: str) -> List[str]:
        """
        Get all channels where a user has been seen.

        Args:
            user_id: Unified user ID (channel:id)

        Returns:
            List of unified chat IDs for this user
        """
        return list(self._user_channels.get(user_id, set()))

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def parse_unified_id(self, unified_id: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse a unified ID (channel:id) into components.

        Args:
            unified_id: String in format "channel:id"

        Returns:
            Tuple of (channel_name, id) or (None, None) if invalid
        """
        if ":" not in unified_id:
            return None, None

        parts = unified_id.split(":", 1)
        if len(parts) != 2:
            return None, None

        return parts[0], parts[1]
