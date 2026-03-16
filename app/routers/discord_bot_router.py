"""
Discord Bot Management Router

Endpoints for managing the Discord bot connection and sending messages.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discord/bot", tags=["discord-bot"])


# =============================================================================
# Response Models
# =============================================================================


class BotStatusResponse(BaseModel):
    """Discord bot status."""
    connected: bool
    bot_user: Optional[str] = None
    guild_count: int = 0
    guilds: List[dict] = []
    uptime_seconds: float = 0
    allowed_channels: List[int] = []
    allowed_guilds: List[int] = []


class SendMessageRequest(BaseModel):
    """Send message request."""
    channel_id: int = Field(..., description="Discord channel ID")
    content: str = Field(..., description="Message content")


class SendMessageResponse(BaseModel):
    """Send message response."""
    success: bool
    error: Optional[str] = None


class ChannelMessage(BaseModel):
    """Channel message."""
    id: str
    author_id: str
    author_name: str
    content: str
    timestamp: str
    attachments: List[dict] = []


class ChannelHistoryResponse(BaseModel):
    """Channel history response."""
    channel_id: int
    message_count: int
    messages: List[ChannelMessage]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status():
    """Get Discord bot connection status."""
    try:
        from ..services.discord_bot import get_discord_bot

        bot = get_discord_bot()
        if not bot:
            return BotStatusResponse(
                connected=False,
                bot_user=None,
                guild_count=0,
                guilds=[],
                uptime_seconds=0,
                allowed_channels=[],
                allowed_guilds=[],
            )

        status = bot.get_status()
        return BotStatusResponse(**status)

    except Exception as e:
        logger.error(f"Failed to get bot status: {e}")
        return BotStatusResponse(
            connected=False,
            bot_user=None,
            guild_count=0,
            guilds=[],
            uptime_seconds=0,
            allowed_channels=[],
            allowed_guilds=[],
        )


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """Send a message to a Discord channel."""
    try:
        from ..services.discord_bot import get_discord_bot

        bot = get_discord_bot()
        if not bot or not bot.is_ready:
            return SendMessageResponse(
                success=False,
                error="Discord bot not connected"
            )

        success = await bot.send_message(request.channel_id, request.content)

        if success:
            return SendMessageResponse(success=True)
        else:
            return SendMessageResponse(
                success=False,
                error="Failed to send message"
            )

    except Exception as e:
        logger.error(f"Failed to send Discord message: {e}")
        return SendMessageResponse(success=False, error=str(e))


@router.get("/history/{channel_id}", response_model=ChannelHistoryResponse)
async def get_channel_history(
    channel_id: int,
    limit: int = Query(50, ge=1, le=100, description="Number of messages")
):
    """Get message history from a Discord channel."""
    try:
        from ..services.discord_bot import get_discord_bot

        bot = get_discord_bot()
        if not bot or not bot.is_ready:
            raise HTTPException(
                status_code=503,
                detail="Discord bot not connected"
            )

        messages = await bot.get_channel_history(channel_id, limit=limit)

        return ChannelHistoryResponse(
            channel_id=channel_id,
            message_count=len(messages),
            messages=[ChannelMessage(**m) for m in messages],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get channel history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_bot():
    """Manually start the Discord bot."""
    try:
        from ..services.discord_bot import init_discord_bot, get_discord_bot
        from ..services.channel_router import route_message

        # Check if already running
        bot = get_discord_bot()
        if bot and bot.is_ready:
            return {
                "status": "already_running",
                "message": "Discord bot is already connected"
            }

        # Start with message handler
        success = await init_discord_bot(message_handler=route_message)

        if success:
            return {
                "status": "started",
                "message": "Discord bot started successfully"
            }
        else:
            return {
                "status": "failed",
                "message": "Failed to start Discord bot. Check DISCORD_BOT_TOKEN."
            }

    except ImportError:
        return {
            "status": "unavailable",
            "message": "discord.py not installed"
        }
    except Exception as e:
        logger.error(f"Failed to start Discord bot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_bot():
    """Manually stop the Discord bot."""
    try:
        from ..services.discord_bot import shutdown_discord_bot, get_discord_bot

        bot = get_discord_bot()
        if not bot or not bot.is_ready:
            return {
                "status": "not_running",
                "message": "Discord bot is not running"
            }

        await shutdown_discord_bot()

        return {
            "status": "stopped",
            "message": "Discord bot stopped successfully"
        }

    except Exception as e:
        logger.error(f"Failed to stop Discord bot: {e}")
        raise HTTPException(status_code=500, detail=str(e))
