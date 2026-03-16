"""
Telegram Channel Adapter

Implements ChannelAdapter interface for Telegram messaging.
This adapter wraps the existing telegram_bot.py functionality while
providing a unified interface for the ChannelManager.

Migration Strategy:
- Phase 1: Adapter wraps existing bot, provides send_message/send_media
- Phase 2: Incoming messages routed through ChannelManager
- Phase 3: Command handlers migrated to unified handler system
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from telegram import Bot, InputFile, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError

from .base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelType,
    ChannelUser,
    MediaAttachment,
    MessageType,
)

logger = logging.getLogger(__name__)


def _get_telegram_token() -> Optional[str]:
    """Get Telegram token from env or secrets file."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    secrets_path = "/brain/system/secrets/telegram_bot_token.txt"
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            return f.read().strip()
    return None


class TelegramAdapter(ChannelAdapter):
    """
    Telegram channel adapter implementing the unified messaging interface.

    This adapter provides two modes of operation:
    1. Standalone: Direct bot management with start()/stop()
    2. Wrapped: Works alongside existing telegram_bot.py

    For Phase 1, we use wrapped mode - the existing bot handles polling,
    and this adapter provides send_message/send_media for outgoing messages.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        standalone: bool = False,
    ):
        """
        Initialize Telegram adapter.

        Args:
            bot_token: Telegram bot token (defaults to env/secrets)
            standalone: If True, manage bot lifecycle. If False, share with telegram_bot.py
        """
        super().__init__(ChannelType.TELEGRAM)

        self._token = bot_token or _get_telegram_token()
        self._standalone = standalone
        self._bot: Optional[Bot] = None
        self._application = None  # For standalone mode

        # Create bot instance for sending messages
        if self._token:
            self._bot = Bot(token=self._token)

    @property
    def bot(self) -> Optional[Bot]:
        """Get the underlying Telegram Bot instance."""
        return self._bot

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """
        Start the adapter.

        In wrapped mode (standalone=False): Just marks as running.
        In standalone mode: Starts polling for updates.
        """
        if not self._token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        if self._standalone:
            await self._start_standalone()
        else:
            # Wrapped mode - existing telegram_bot.py handles polling
            self._mark_connected()
            logger.info("TelegramAdapter started in wrapped mode")

    async def _start_standalone(self) -> None:
        """Start in standalone mode with full bot management."""
        from telegram.ext import Application, MessageHandler, filters

        self._application = Application.builder().token(self._token).build()

        # Add a catch-all handler that converts to ChannelMessage
        self._application.add_handler(
            MessageHandler(filters.ALL, self._handle_update)
        )

        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()

        self._mark_connected()
        logger.info("TelegramAdapter started in standalone mode")

    async def stop(self) -> None:
        """Stop the adapter."""
        if self._standalone and self._application:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            self._application = None

        self._mark_disconnected()
        logger.info("TelegramAdapter stopped")

    # =========================================================================
    # Sending Messages
    # =========================================================================

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
        Send a text message via Telegram.

        Args:
            chat_id: Telegram chat ID
            text: Message text
            reply_to_message_id: Message ID to reply to
            parse_mode: "markdown", "html", or None
            disable_notification: Send silently
            **kwargs: Additional options (reply_markup, etc.)

        Returns:
            Message ID as string, or None if failed
        """
        if not self._bot:
            logger.error("Telegram bot not initialized")
            return None

        try:
            # Map parse mode
            pm = None
            if parse_mode:
                pm_lower = parse_mode.lower()
                if pm_lower in ("markdown", "markdownv2"):
                    pm = ParseMode.MARKDOWN_V2
                elif pm_lower == "html":
                    pm = ParseMode.HTML

            # Handle reply_to
            reply_to = None
            if reply_to_message_id:
                try:
                    reply_to = int(reply_to_message_id)
                except ValueError:
                    pass

            message = await self._bot.send_message(
                chat_id=int(chat_id),
                text=text,
                parse_mode=pm,
                reply_to_message_id=reply_to,
                disable_notification=disable_notification,
                **kwargs,
            )

            return str(message.message_id)

        except TelegramError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            self._health_status["error_count"] += 1
            self._health_status["last_error"] = str(e)
            return None

    async def send_media(
        self,
        chat_id: str,
        media: MediaAttachment,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Send media via Telegram.

        Supports: images, documents, audio, video, voice, stickers.
        """
        if not self._bot:
            logger.error("Telegram bot not initialized")
            return None

        try:
            # Determine input source
            input_file = None
            if media.file_bytes:
                input_file = InputFile(media.file_bytes, filename=media.file_name)
            elif media.file_path:
                input_file = open(media.file_path, "rb")
            elif media.file_url:
                input_file = media.file_url
            elif media.file_id:
                input_file = media.file_id
            else:
                logger.error("No media source provided")
                return None

            # Handle reply_to
            reply_to = None
            if reply_to_message_id:
                try:
                    reply_to = int(reply_to_message_id)
                except ValueError:
                    pass

            chat_id_int = int(chat_id)
            final_caption = caption or media.caption

            # Send based on type
            message = None
            if media.type == MessageType.IMAGE:
                message = await self._bot.send_photo(
                    chat_id=chat_id_int,
                    photo=input_file,
                    caption=final_caption,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            elif media.type == MessageType.DOCUMENT:
                message = await self._bot.send_document(
                    chat_id=chat_id_int,
                    document=input_file,
                    caption=final_caption,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            elif media.type == MessageType.AUDIO:
                message = await self._bot.send_audio(
                    chat_id=chat_id_int,
                    audio=input_file,
                    caption=final_caption,
                    duration=media.duration,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            elif media.type == MessageType.VIDEO:
                message = await self._bot.send_video(
                    chat_id=chat_id_int,
                    video=input_file,
                    caption=final_caption,
                    duration=media.duration,
                    width=media.width,
                    height=media.height,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            elif media.type == MessageType.VOICE:
                message = await self._bot.send_voice(
                    chat_id=chat_id_int,
                    voice=input_file,
                    caption=final_caption,
                    duration=media.duration,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            elif media.type == MessageType.STICKER:
                message = await self._bot.send_sticker(
                    chat_id=chat_id_int,
                    sticker=input_file,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )
            else:
                # Fallback to document
                message = await self._bot.send_document(
                    chat_id=chat_id_int,
                    document=input_file,
                    caption=final_caption,
                    reply_to_message_id=reply_to,
                    **kwargs,
                )

            # Close file handle if we opened one
            if media.file_path and hasattr(input_file, "close"):
                input_file.close()

            return str(message.message_id) if message else None

        except TelegramError as e:
            logger.error(f"Failed to send Telegram media: {e}")
            self._health_status["error_count"] += 1
            self._health_status["last_error"] = str(e)
            return None

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator."""
        if not self._bot:
            return

        try:
            await self._bot.send_chat_action(
                chat_id=int(chat_id),
                action="typing",
            )
        except TelegramError as e:
            logger.debug(f"Failed to send typing action: {e}")

    # =========================================================================
    # Message Operations
    # =========================================================================

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Edit an existing message."""
        if not self._bot:
            return False

        try:
            pm = None
            if parse_mode:
                pm_lower = parse_mode.lower()
                if pm_lower in ("markdown", "markdownv2"):
                    pm = ParseMode.MARKDOWN_V2
                elif pm_lower == "html":
                    pm = ParseMode.HTML

            await self._bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=text,
                parse_mode=pm,
                **kwargs,
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to edit message: {e}")
            return False

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message."""
        if not self._bot:
            return False

        try:
            await self._bot.delete_message(
                chat_id=int(chat_id),
                message_id=int(message_id),
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to delete message: {e}")
            return False

    async def send_reaction(
        self,
        chat_id: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        """React to a message with an emoji."""
        if not self._bot:
            return False

        try:
            from telegram import ReactionTypeEmoji

            await self._bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=int(message_id),
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to send reaction: {e}")
            return False

    async def pin_message(self, chat_id: str, message_id: str) -> bool:
        """Pin a message in a chat."""
        if not self._bot:
            return False

        try:
            await self._bot.pin_chat_message(
                chat_id=int(chat_id),
                message_id=int(message_id),
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to pin message: {e}")
            return False

    async def unpin_message(self, chat_id: str, message_id: str) -> bool:
        """Unpin a message."""
        if not self._bot:
            return False

        try:
            await self._bot.unpin_chat_message(
                chat_id=int(chat_id),
                message_id=int(message_id),
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to unpin message: {e}")
            return False

    # =========================================================================
    # User & Chat Information
    # =========================================================================

    async def get_user_info(self, user_id: str) -> Optional[ChannelUser]:
        """Get information about a Telegram user."""
        if not self._bot:
            return None

        try:
            # Note: Telegram bots can't get arbitrary user info,
            # only from chats they're in. This uses get_chat which
            # works for users who have messaged the bot.
            chat = await self._bot.get_chat(chat_id=int(user_id))

            return ChannelUser(
                id=str(chat.id),
                channel=ChannelType.TELEGRAM,
                username=chat.username,
                first_name=chat.first_name,
                last_name=chat.last_name,
                avatar_url=None,  # Would need get_chat_member_profile_photos
                is_bot=False,  # Can't determine from get_chat
                raw_data={"type": chat.type},
            )
        except TelegramError as e:
            logger.error(f"Failed to get user info: {e}")
            return None

    async def get_chat_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a Telegram chat."""
        if not self._bot:
            return None

        try:
            chat = await self._bot.get_chat(chat_id=int(chat_id))

            return {
                "id": str(chat.id),
                "type": chat.type,
                "title": chat.title,
                "username": chat.username,
                "first_name": chat.first_name,
                "last_name": chat.last_name,
                "description": chat.description,
                "is_group": chat.type in ("group", "supergroup"),
                "member_count": getattr(chat, "get_member_count", None),
            }
        except TelegramError as e:
            logger.error(f"Failed to get chat info: {e}")
            return None

    async def download_media(self, media: MediaAttachment) -> Optional[bytes]:
        """Download media content from Telegram."""
        if not self._bot or not media.file_id:
            return None

        try:
            file = await self._bot.get_file(file_id=media.file_id)
            return await file.download_as_bytearray()
        except TelegramError as e:
            logger.error(f"Failed to download media: {e}")
            return None

    # =========================================================================
    # Internal Handlers (for standalone mode)
    # =========================================================================

    async def _handle_update(self, update: Update, context) -> None:
        """
        Handle incoming Telegram update and convert to ChannelMessage.
        Only used in standalone mode.
        """
        if not update.message:
            return

        msg = update.message
        user = msg.from_user

        # Convert to ChannelUser
        channel_user = ChannelUser(
            id=str(user.id),
            channel=ChannelType.TELEGRAM,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_bot=user.is_bot,
            language_code=user.language_code,
            raw_data={},
        )

        # Determine message type and extract content
        msg_type = MessageType.TEXT
        media = None

        if msg.photo:
            msg_type = MessageType.IMAGE
            photo = msg.photo[-1]  # Largest size
            media = MediaAttachment(
                type=MessageType.IMAGE,
                file_id=photo.file_id,
                width=photo.width,
                height=photo.height,
                file_size=photo.file_size,
            )
        elif msg.document:
            msg_type = MessageType.DOCUMENT
            media = MediaAttachment(
                type=MessageType.DOCUMENT,
                file_id=msg.document.file_id,
                file_name=msg.document.file_name,
                mime_type=msg.document.mime_type,
                file_size=msg.document.file_size,
            )
        elif msg.audio:
            msg_type = MessageType.AUDIO
            media = MediaAttachment(
                type=MessageType.AUDIO,
                file_id=msg.audio.file_id,
                duration=msg.audio.duration,
                file_size=msg.audio.file_size,
            )
        elif msg.voice:
            msg_type = MessageType.VOICE
            media = MediaAttachment(
                type=MessageType.VOICE,
                file_id=msg.voice.file_id,
                duration=msg.voice.duration,
                file_size=msg.voice.file_size,
            )
        elif msg.video:
            msg_type = MessageType.VIDEO
            media = MediaAttachment(
                type=MessageType.VIDEO,
                file_id=msg.video.file_id,
                duration=msg.video.duration,
                width=msg.video.width,
                height=msg.video.height,
                file_size=msg.video.file_size,
            )
        elif msg.sticker:
            msg_type = MessageType.STICKER
            media = MediaAttachment(
                type=MessageType.STICKER,
                file_id=msg.sticker.file_id,
                width=msg.sticker.width,
                height=msg.sticker.height,
            )

        # Parse command if present
        command = None
        command_args = None
        text = msg.text or msg.caption or ""

        if text.startswith("/"):
            msg_type = MessageType.COMMAND
            parts = text.split(None, 1)
            command = parts[0][1:]  # Remove leading /
            if "@" in command:
                command = command.split("@")[0]  # Remove bot mention
            command_args = parts[1] if len(parts) > 1 else None

        # Create ChannelMessage
        channel_message = ChannelMessage(
            id=str(msg.message_id),
            channel=ChannelType.TELEGRAM,
            chat_id=str(msg.chat.id),
            user=channel_user,
            type=msg_type,
            text=text,
            media=media,
            reply_to_message_id=str(msg.reply_to_message.message_id) if msg.reply_to_message else None,
            timestamp=msg.date or datetime.utcnow(),
            is_group=msg.chat.type in ("group", "supergroup"),
            group_name=msg.chat.title,
            command=command,
            command_args=command_args,
            raw_data={"chat_type": msg.chat.type},
        )

        # Dispatch to handlers
        await self._dispatch_message(channel_message)


# =========================================================================
# Helper for gradual migration
# =========================================================================

def get_shared_adapter() -> TelegramAdapter:
    """
    Get a shared TelegramAdapter instance for use alongside telegram_bot.py.

    This allows gradual migration - existing code can use this adapter
    for sending messages through the unified interface while keeping
    the existing command handlers.
    """
    return TelegramAdapter(standalone=False)
