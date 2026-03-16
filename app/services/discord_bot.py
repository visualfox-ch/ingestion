"""
Discord Bot Service

Connects to Discord and enables Jarvis to interact with Discord channels.
Starts automatically with the FastAPI application.

Setup:
1. Set DISCORD_BOT_TOKEN environment variable
2. Configure DISCORD_ALLOWED_CHANNELS for channel IDs
3. Bot will connect on FastAPI startup
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

def get_bot_token() -> Optional[str]:
    """Get Discord bot token from environment."""
    return os.environ.get("DISCORD_BOT_TOKEN")


def get_allowed_channels() -> List[int]:
    """Get list of allowed channel IDs."""
    channels_str = os.environ.get("DISCORD_ALLOWED_CHANNELS", "")
    if not channels_str:
        return []
    try:
        return [int(c.strip()) for c in channels_str.split(",") if c.strip()]
    except ValueError:
        logger.warning("Invalid DISCORD_ALLOWED_CHANNELS format")
        return []


def get_allowed_guilds() -> List[int]:
    """Get list of allowed guild/server IDs."""
    guilds_str = os.environ.get("DISCORD_ALLOWED_GUILDS", "")
    if not guilds_str:
        return []
    try:
        return [int(g.strip()) for g in guilds_str.split(",") if g.strip()]
    except ValueError:
        logger.warning("Invalid DISCORD_ALLOWED_GUILDS format")
        return []


# =============================================================================
# Discord Bot Class
# =============================================================================

class JarvisDiscordBot:
    """
    Discord bot that integrates with Jarvis.

    Handles:
    - Message listening and routing
    - Command processing
    - Channel history access
    - Response delivery
    """

    def __init__(self, message_handler: Optional[Callable] = None):
        """
        Initialize the bot.

        Args:
            message_handler: Async callback for processing messages.
                           Signature: async def handler(message_data: dict) -> Optional[str]
        """
        self.client = None
        self.message_handler = message_handler
        self.is_ready = False
        self.connected_guilds: List[Dict[str, Any]] = []
        self.start_time: Optional[datetime] = None

    async def start(self) -> bool:
        """
        Start the Discord bot.

        Returns:
            True if started successfully, False otherwise.
        """
        try:
            import discord
        except ImportError:
            logger.warning("discord.py not installed. Discord bot disabled.")
            return False

        token = get_bot_token()
        if not token:
            logger.info("DISCORD_BOT_TOKEN not set. Discord bot disabled.")
            return False

        # Configure intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = False  # Not needed for basic functionality

        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready():
            self.is_ready = True
            self.start_time = datetime.utcnow()
            self.connected_guilds = [
                {"id": g.id, "name": g.name, "member_count": g.member_count}
                for g in self.client.guilds
            ]
            logger.info(f"Discord bot connected as {self.client.user}")
            logger.info(f"Connected to {len(self.connected_guilds)} guild(s)")

        @self.client.event
        async def on_message(message):
            # Ignore own messages
            if message.author == self.client.user:
                return

            # Check channel restrictions
            allowed_channels = get_allowed_channels()
            if allowed_channels and message.channel.id not in allowed_channels:
                return

            # Check guild restrictions
            allowed_guilds = get_allowed_guilds()
            if allowed_guilds and message.guild and message.guild.id not in allowed_guilds:
                return

            # Check for bot mention or DM
            is_mentioned = self.client.user in message.mentions
            is_dm = message.guild is None

            # Process if mentioned, DM, or starts with command prefix
            should_process = is_mentioned or is_dm or message.content.startswith("!jarvis")

            if should_process and self.message_handler:
                # Prepare message data
                message_data = {
                    "channel": "discord",
                    "message_id": str(message.id),
                    "channel_id": str(message.channel.id),
                    "channel_name": getattr(message.channel, "name", "DM"),
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "guild_name": message.guild.name if message.guild else None,
                    "author_id": str(message.author.id),
                    "author_name": message.author.display_name,
                    "content": message.content,
                    "timestamp": message.created_at.isoformat(),
                    "is_dm": is_dm,
                    "is_mention": is_mentioned,
                    "attachments": [
                        {"filename": a.filename, "url": a.url, "size": a.size}
                        for a in message.attachments
                    ],
                }

                try:
                    # Call the message handler
                    response = await self.message_handler(message_data)

                    if response:
                        # Send response (split if too long)
                        if len(response) <= 2000:
                            await message.reply(response)
                        else:
                            # Split into chunks
                            chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await message.reply(chunk)
                                else:
                                    await message.channel.send(chunk)

                except Exception as e:
                    logger.error(f"Error processing Discord message: {e}")
                    await message.add_reaction("❌")

        # Start bot in background task
        asyncio.create_task(self._run_bot(token))
        return True

    async def _run_bot(self, token: str):
        """Run the bot connection."""
        try:
            await self.client.start(token)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self.is_ready = False

    async def stop(self):
        """Stop the Discord bot."""
        if self.client:
            await self.client.close()
            self.is_ready = False
            logger.info("Discord bot disconnected")

    async def send_message(self, channel_id: int, content: str) -> bool:
        """
        Send a message to a specific channel.

        Args:
            channel_id: Discord channel ID
            content: Message content

        Returns:
            True if sent successfully
        """
        if not self.client or not self.is_ready:
            return False

        try:
            channel = self.client.get_channel(channel_id)
            if not channel:
                channel = await self.client.fetch_channel(channel_id)

            if channel:
                await channel.send(content)
                return True
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")

        return False

    async def get_channel_history(
        self,
        channel_id: int,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get message history from a channel.

        Args:
            channel_id: Discord channel ID
            limit: Maximum messages to retrieve

        Returns:
            List of message dictionaries
        """
        if not self.client or not self.is_ready:
            return []

        try:
            channel = self.client.get_channel(channel_id)
            if not channel:
                channel = await self.client.fetch_channel(channel_id)

            if not channel:
                return []

            messages = []
            async for msg in channel.history(limit=limit):
                messages.append({
                    "id": str(msg.id),
                    "author_id": str(msg.author.id),
                    "author_name": msg.author.display_name,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat(),
                    "attachments": [
                        {"filename": a.filename, "url": a.url}
                        for a in msg.attachments
                    ],
                })

            return messages

        except Exception as e:
            logger.error(f"Failed to get Discord channel history: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Get bot connection status."""
        return {
            "connected": self.is_ready,
            "bot_user": str(self.client.user) if self.client and self.client.user else None,
            "guilds": self.connected_guilds,
            "guild_count": len(self.connected_guilds),
            "uptime_seconds": (
                (datetime.utcnow() - self.start_time).total_seconds()
                if self.start_time else 0
            ),
            "allowed_channels": get_allowed_channels(),
            "allowed_guilds": get_allowed_guilds(),
        }


# =============================================================================
# Global Bot Instance
# =============================================================================

_discord_bot: Optional[JarvisDiscordBot] = None


def get_discord_bot() -> Optional[JarvisDiscordBot]:
    """Get the global Discord bot instance."""
    return _discord_bot


async def init_discord_bot(message_handler: Optional[Callable] = None) -> bool:
    """
    Initialize and start the global Discord bot.

    Args:
        message_handler: Async callback for processing messages.

    Returns:
        True if started successfully
    """
    global _discord_bot

    if _discord_bot and _discord_bot.is_ready:
        logger.info("Discord bot already running")
        return True

    _discord_bot = JarvisDiscordBot(message_handler=message_handler)
    return await _discord_bot.start()


async def shutdown_discord_bot():
    """Shutdown the global Discord bot."""
    global _discord_bot

    if _discord_bot:
        await _discord_bot.stop()
        _discord_bot = None
