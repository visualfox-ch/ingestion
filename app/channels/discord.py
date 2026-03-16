"""
Discord Channel Adapter

Implements ChannelAdapter interface for Discord messaging.
Uses discord.py library for bot functionality.

Setup:
1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and get the token
3. Enable MESSAGE CONTENT INTENT in the bot settings
4. Set DISCORD_BOT_TOKEN environment variable
5. Invite bot to server with appropriate permissions
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None
    commands = None

from .base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelType,
    ChannelUser,
    MediaAttachment,
    MessageType,
)

logger = logging.getLogger(__name__)


def _get_discord_token() -> Optional[str]:
    """Get Discord bot token from environment."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        return token
    secrets_path = "/brain/system/secrets/discord_bot_token.txt"
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            return f.read().strip()
    return None


class DiscordAdapter(ChannelAdapter):
    """
    Discord channel adapter implementing the unified messaging interface.

    Features:
    - DM and server channel support
    - Slash commands
    - Message embeds
    - File attachments
    - Reactions
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        command_prefix: str = "!",
    ):
        """
        Initialize Discord adapter.

        Args:
            bot_token: Discord bot token (defaults to env/secrets)
            command_prefix: Prefix for text commands (default "!")
        """
        super().__init__(ChannelType.DISCORD)

        if not DISCORD_AVAILABLE:
            logger.warning("discord.py not installed. Discord adapter unavailable.")
            self._token = None
            self._bot = None
            return

        self._token = bot_token or _get_discord_token()
        self._command_prefix = command_prefix
        self._bot: Optional[commands.Bot] = None
        self._ready_event = asyncio.Event()

    @property
    def bot(self) -> Optional[Any]:
        """Get the underlying Discord Bot instance."""
        return self._bot

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """Start the Discord bot."""
        if not DISCORD_AVAILABLE:
            raise RuntimeError("discord.py is not installed")

        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN not configured")

        # Create bot with intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.dm_messages = True

        self._bot = commands.Bot(
            command_prefix=self._command_prefix,
            intents=intents,
        )

        # Register event handlers
        @self._bot.event
        async def on_ready():
            logger.info(f"Discord bot logged in as {self._bot.user}")
            self._mark_connected()
            self._ready_event.set()

        @self._bot.event
        async def on_message(message: discord.Message):
            # Ignore bot's own messages
            if message.author == self._bot.user:
                return

            # Convert to ChannelMessage and dispatch
            channel_message = self._convert_message(message)
            await self._dispatch_message(channel_message)

            # Process commands too
            await self._bot.process_commands(message)

        @self._bot.event
        async def on_disconnect():
            logger.warning("Discord bot disconnected")
            self._mark_disconnected()

        # Start bot in background
        asyncio.create_task(self._run_bot())

        # Wait for ready
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            raise RuntimeError("Discord bot failed to connect within 30 seconds")

    async def _run_bot(self) -> None:
        """Run the bot (blocking)."""
        try:
            await self._bot.start(self._token)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self._mark_disconnected(str(e))

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._bot:
            await self._bot.close()
            self._bot = None

        self._ready_event.clear()
        self._mark_disconnected()
        logger.info("Discord adapter stopped")

    # =========================================================================
    # Message Conversion
    # =========================================================================

    def _convert_message(self, message: discord.Message) -> ChannelMessage:
        """Convert Discord message to ChannelMessage."""
        # Convert user
        author = message.author
        channel_user = ChannelUser(
            id=str(author.id),
            channel=ChannelType.DISCORD,
            username=author.name,
            display_name=author.display_name,
            avatar_url=str(author.avatar.url) if author.avatar else None,
            is_bot=author.bot,
            raw_data={"discriminator": author.discriminator},
        )

        # Determine message type and extract media
        msg_type = MessageType.TEXT
        media = None

        if message.attachments:
            attachment = message.attachments[0]
            content_type = attachment.content_type or ""

            if content_type.startswith("image/"):
                msg_type = MessageType.IMAGE
            elif content_type.startswith("audio/"):
                msg_type = MessageType.AUDIO
            elif content_type.startswith("video/"):
                msg_type = MessageType.VIDEO
            else:
                msg_type = MessageType.DOCUMENT

            media = MediaAttachment(
                type=msg_type,
                file_url=attachment.url,
                file_name=attachment.filename,
                file_size=attachment.size,
                mime_type=content_type,
                width=attachment.width,
                height=attachment.height,
            )

        # Parse command
        command = None
        command_args = None
        text = message.content

        if text.startswith(self._command_prefix):
            msg_type = MessageType.COMMAND
            parts = text[len(self._command_prefix):].split(None, 1)
            command = parts[0] if parts else ""
            command_args = parts[1] if len(parts) > 1 else None

        # Determine if group/DM
        is_group = not isinstance(message.channel, discord.DMChannel)
        group_name = None
        if hasattr(message.channel, 'name'):
            group_name = message.channel.name

        return ChannelMessage(
            id=str(message.id),
            channel=ChannelType.DISCORD,
            chat_id=str(message.channel.id),
            user=channel_user,
            type=msg_type,
            text=text,
            media=media,
            reply_to_message_id=str(message.reference.message_id) if message.reference else None,
            timestamp=message.created_at,
            is_group=is_group,
            group_name=group_name,
            thread_id=str(message.thread.id) if hasattr(message, 'thread') and message.thread else None,
            command=command,
            command_args=command_args,
            raw_data={
                "guild_id": str(message.guild.id) if message.guild else None,
                "channel_type": str(message.channel.type),
            },
        )

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
        """Send a text message to a Discord channel."""
        if not self._bot:
            logger.error("Discord bot not initialized")
            return None

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            # Handle embeds if specified
            embed = kwargs.get("embed")
            if isinstance(embed, dict):
                embed = discord.Embed.from_dict(embed)

            # Handle reply
            reference = None
            if reply_to_message_id:
                try:
                    ref_message = await channel.fetch_message(int(reply_to_message_id))
                    reference = ref_message.to_reference()
                except Exception:
                    pass

            message = await channel.send(
                content=text,
                embed=embed,
                reference=reference,
                silent=disable_notification,
            )

            return str(message.id)

        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
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
        """Send media to a Discord channel."""
        if not self._bot:
            logger.error("Discord bot not initialized")
            return None

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            # Create file object
            file = None
            if media.file_bytes:
                file = discord.File(
                    io.BytesIO(media.file_bytes),
                    filename=media.file_name or "file"
                )
            elif media.file_path:
                file = discord.File(media.file_path)
            elif media.file_url:
                # Discord can embed URLs directly
                return await self.send_message(
                    chat_id,
                    f"{caption or ''}\n{media.file_url}".strip(),
                    reply_to_message_id=reply_to_message_id,
                )

            if not file:
                logger.error("No media source provided")
                return None

            # Handle reply
            reference = None
            if reply_to_message_id:
                try:
                    ref_message = await channel.fetch_message(int(reply_to_message_id))
                    reference = ref_message.to_reference()
                except Exception:
                    pass

            message = await channel.send(
                content=caption,
                file=file,
                reference=reference,
            )

            return str(message.id)

        except Exception as e:
            logger.error(f"Failed to send Discord media: {e}")
            self._health_status["error_count"] += 1
            self._health_status["last_error"] = str(e)
            return None

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator."""
        if not self._bot:
            return

        try:
            channel = self._bot.get_channel(int(chat_id))
            if channel:
                await channel.typing()
        except Exception as e:
            logger.debug(f"Failed to send typing: {e}")

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
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            message = await channel.fetch_message(int(message_id))
            await message.edit(content=text)
            return True

        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            return False

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message."""
        if not self._bot:
            return False

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            message = await channel.fetch_message(int(message_id))
            await message.delete()
            return True

        except Exception as e:
            logger.error(f"Failed to delete message: {e}")
            return False

    async def send_reaction(
        self,
        chat_id: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        """React to a message."""
        if not self._bot:
            return False

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
            return True

        except Exception as e:
            logger.error(f"Failed to add reaction: {e}")
            return False

    async def pin_message(self, chat_id: str, message_id: str) -> bool:
        """Pin a message."""
        if not self._bot:
            return False

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            message = await channel.fetch_message(int(message_id))
            await message.pin()
            return True

        except Exception as e:
            logger.error(f"Failed to pin message: {e}")
            return False

    async def unpin_message(self, chat_id: str, message_id: str) -> bool:
        """Unpin a message."""
        if not self._bot:
            return False

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            message = await channel.fetch_message(int(message_id))
            await message.unpin()
            return True

        except Exception as e:
            logger.error(f"Failed to unpin message: {e}")
            return False

    # =========================================================================
    # User & Chat Information
    # =========================================================================

    async def get_user_info(self, user_id: str) -> Optional[ChannelUser]:
        """Get information about a Discord user."""
        if not self._bot:
            return None

        try:
            user = self._bot.get_user(int(user_id))
            if not user:
                user = await self._bot.fetch_user(int(user_id))

            return ChannelUser(
                id=str(user.id),
                channel=ChannelType.DISCORD,
                username=user.name,
                display_name=user.display_name,
                avatar_url=str(user.avatar.url) if user.avatar else None,
                is_bot=user.bot,
                raw_data={"discriminator": user.discriminator},
            )

        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            return None

    async def get_chat_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a Discord channel."""
        if not self._bot:
            return None

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            info = {
                "id": str(channel.id),
                "type": str(channel.type),
                "name": getattr(channel, 'name', None),
            }

            if hasattr(channel, 'guild'):
                info["guild_id"] = str(channel.guild.id)
                info["guild_name"] = channel.guild.name
                info["is_group"] = True
            else:
                info["is_group"] = False

            return info

        except Exception as e:
            logger.error(f"Failed to get chat info: {e}")
            return None

    async def download_media(self, media: MediaAttachment) -> Optional[bytes]:
        """Download media from Discord."""
        if not media.file_url:
            return None

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(media.file_url) as response:
                    if response.status == 200:
                        return await response.read()
            return None
        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            return None

    # =========================================================================
    # Discord-specific Methods
    # =========================================================================

    async def send_embed(
        self,
        chat_id: str,
        title: str,
        description: str,
        color: int = 0x89b4fa,
        fields: List[Dict[str, str]] = None,
        thumbnail_url: Optional[str] = None,
        image_url: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send a rich embed message.

        Args:
            chat_id: Channel ID
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: [{"name": "...", "value": "...", "inline": True}]
            thumbnail_url: Small image in corner
            image_url: Large image at bottom
            footer: Footer text
        """
        if not self._bot or not DISCORD_AVAILABLE:
            return None

        try:
            channel = self._bot.get_channel(int(chat_id))
            if not channel:
                channel = await self._bot.fetch_channel(int(chat_id))

            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.utcnow(),
            )

            if fields:
                for field in fields:
                    embed.add_field(
                        name=field.get("name", ""),
                        value=field.get("value", ""),
                        inline=field.get("inline", False),
                    )

            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
            if image_url:
                embed.set_image(url=image_url)
            if footer:
                embed.set_footer(text=footer)

            message = await channel.send(embed=embed)
            return str(message.id)

        except Exception as e:
            logger.error(f"Failed to send embed: {e}")
            return None


# Import io for BytesIO
import io
