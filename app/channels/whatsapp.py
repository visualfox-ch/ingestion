"""
WhatsApp Channel Adapter

Implements ChannelAdapter interface for WhatsApp messaging.
Uses a Node.js bridge service (whatsapp-web.js) for actual WhatsApp connectivity.

Architecture:
- This Python adapter communicates with a separate Node.js service
- The Node service handles the WhatsApp Web protocol via whatsapp-web.js
- Communication happens over HTTP/WebSocket

Setup:
1. Run the WhatsApp bridge service (see /brain/system/whatsapp-bridge/)
2. Scan QR code to authenticate
3. Set WHATSAPP_BRIDGE_URL environment variable
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import aiohttp

from .base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelType,
    ChannelUser,
    MediaAttachment,
    MessageType,
)

logger = logging.getLogger(__name__)

# Default bridge URL
DEFAULT_BRIDGE_URL = "http://localhost:3000"


class WhatsAppAdapter(ChannelAdapter):
    """
    WhatsApp channel adapter implementing the unified messaging interface.

    This adapter communicates with a separate Node.js bridge service that
    handles the actual WhatsApp Web protocol.

    Features:
    - Text messages
    - Image/document/audio/video attachments
    - Group chats
    - Message replies
    - Read receipts
    """

    def __init__(
        self,
        bridge_url: Optional[str] = None,
        session_name: str = "jarvis",
    ):
        """
        Initialize WhatsApp adapter.

        Args:
            bridge_url: URL of the WhatsApp bridge service
            session_name: Name for the WhatsApp session (for multi-session support)
        """
        super().__init__(ChannelType.WHATSAPP)

        self._bridge_url = bridge_url or os.environ.get("WHATSAPP_BRIDGE_URL", DEFAULT_BRIDGE_URL)
        self._session_name = session_name
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_task: Optional[asyncio.Task] = None

    @property
    def bridge_url(self) -> str:
        """Get the bridge service URL."""
        return self._bridge_url

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """Start the WhatsApp adapter and connect to bridge."""
        self._session = aiohttp.ClientSession()

        # Check bridge connectivity
        try:
            async with self._session.get(f"{self._bridge_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Bridge health check failed: {resp.status}")

                data = await resp.json()
                if data.get("status") != "connected":
                    logger.warning(f"WhatsApp not connected: {data.get('status')}. May need QR code scan.")

        except aiohttp.ClientError as e:
            raise RuntimeError(f"Cannot connect to WhatsApp bridge at {self._bridge_url}: {e}")

        # Start WebSocket connection for real-time messages
        self._ws_task = asyncio.create_task(self._websocket_listener())

        self._mark_connected()
        logger.info(f"WhatsApp adapter connected to bridge at {self._bridge_url}")

    async def stop(self) -> None:
        """Stop the WhatsApp adapter."""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()

        if self._session:
            await self._session.close()

        self._mark_disconnected()
        logger.info("WhatsApp adapter stopped")

    async def _websocket_listener(self) -> None:
        """Listen for incoming messages via WebSocket."""
        while True:
            try:
                async with self._session.ws_connect(f"{self._bridge_url}/ws") as ws:
                    self._ws = ws
                    logger.info("WhatsApp WebSocket connected")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = msg.json()
                                if data.get("type") == "message":
                                    channel_message = self._convert_message(data.get("data", {}))
                                    await self._dispatch_message(channel_message)
                            except Exception as e:
                                logger.error(f"Error processing WhatsApp message: {e}")

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WhatsApp WebSocket error: {ws.exception()}")
                            break

            except aiohttp.ClientError as e:
                logger.warning(f"WhatsApp WebSocket connection failed: {e}")
                await asyncio.sleep(5)  # Reconnect delay

            except asyncio.CancelledError:
                break

    # =========================================================================
    # Message Conversion
    # =========================================================================

    def _convert_message(self, data: Dict[str, Any]) -> ChannelMessage:
        """Convert bridge message format to ChannelMessage."""
        # Extract sender info
        sender = data.get("sender", {})
        channel_user = ChannelUser(
            id=sender.get("id", ""),
            channel=ChannelType.WHATSAPP,
            username=sender.get("pushname", sender.get("id", "")),
            first_name=sender.get("pushname"),
            phone=sender.get("id", "").split("@")[0] if "@" in sender.get("id", "") else None,
            is_bot=False,
            raw_data=sender,
        )

        # Determine message type
        msg_type = MessageType.TEXT
        media = None

        if data.get("hasMedia"):
            media_type = data.get("mediaType", "document")
            if media_type == "image":
                msg_type = MessageType.IMAGE
            elif media_type == "audio" or media_type == "ptt":
                msg_type = MessageType.VOICE if media_type == "ptt" else MessageType.AUDIO
            elif media_type == "video":
                msg_type = MessageType.VIDEO
            elif media_type == "sticker":
                msg_type = MessageType.STICKER
            else:
                msg_type = MessageType.DOCUMENT

            media = MediaAttachment(
                type=msg_type,
                file_id=data.get("mediaKey"),
                mime_type=data.get("mimetype"),
                file_name=data.get("filename"),
                file_size=data.get("filesize"),
                caption=data.get("caption"),
            )

        # Check for location
        if data.get("type") == "location":
            msg_type = MessageType.LOCATION

        # Group info
        is_group = data.get("isGroup", False)
        chat_id = data.get("chatId", "")

        return ChannelMessage(
            id=data.get("id", {}).get("id", str(datetime.utcnow().timestamp())),
            channel=ChannelType.WHATSAPP,
            chat_id=chat_id,
            user=channel_user,
            type=msg_type,
            text=data.get("body", ""),
            media=media,
            reply_to_message_id=data.get("quotedMsgId"),
            timestamp=datetime.fromtimestamp(data.get("timestamp", datetime.utcnow().timestamp())),
            is_group=is_group,
            group_name=data.get("groupName"),
            raw_data=data,
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
        """Send a text message via WhatsApp."""
        if not self._session:
            logger.error("WhatsApp adapter not started")
            return None

        try:
            payload = {
                "chatId": chat_id,
                "message": text,
            }

            if reply_to_message_id:
                payload["quotedMessageId"] = reply_to_message_id

            async with self._session.post(
                f"{self._bridge_url}/send",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("messageId")
                else:
                    error = await resp.text()
                    logger.error(f"Failed to send WhatsApp message: {error}")
                    return None

        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
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
        """Send media via WhatsApp."""
        if not self._session:
            logger.error("WhatsApp adapter not started")
            return None

        try:
            # Prepare multipart data
            data = aiohttp.FormData()
            data.add_field("chatId", chat_id)

            if caption:
                data.add_field("caption", caption)

            if reply_to_message_id:
                data.add_field("quotedMessageId", reply_to_message_id)

            # Add media
            if media.file_bytes:
                data.add_field(
                    "media",
                    media.file_bytes,
                    filename=media.file_name or "file",
                    content_type=media.mime_type or "application/octet-stream"
                )
            elif media.file_path:
                with open(media.file_path, "rb") as f:
                    file_bytes = f.read()
                data.add_field(
                    "media",
                    file_bytes,
                    filename=media.file_name or os.path.basename(media.file_path),
                    content_type=media.mime_type or "application/octet-stream"
                )
            elif media.file_url:
                data.add_field("mediaUrl", media.file_url)
            else:
                logger.error("No media source provided")
                return None

            async with self._session.post(
                f"{self._bridge_url}/send-media",
                data=data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("messageId")
                else:
                    error = await resp.text()
                    logger.error(f"Failed to send WhatsApp media: {error}")
                    return None

        except Exception as e:
            logger.error(f"Failed to send WhatsApp media: {e}")
            self._health_status["error_count"] += 1
            self._health_status["last_error"] = str(e)
            return None

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator (composing)."""
        if not self._session:
            return

        try:
            await self._session.post(
                f"{self._bridge_url}/typing",
                json={"chatId": chat_id, "state": True},
                timeout=aiohttp.ClientTimeout(total=5)
            )
        except Exception as e:
            logger.debug(f"Failed to send typing: {e}")

    # =========================================================================
    # User & Chat Information
    # =========================================================================

    async def get_user_info(self, user_id: str) -> Optional[ChannelUser]:
        """Get information about a WhatsApp user."""
        if not self._session:
            return None

        try:
            async with self._session.get(
                f"{self._bridge_url}/contact/{user_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return ChannelUser(
                        id=data.get("id", user_id),
                        channel=ChannelType.WHATSAPP,
                        username=data.get("pushname", data.get("name")),
                        first_name=data.get("pushname"),
                        phone=data.get("number"),
                        avatar_url=data.get("profilePicUrl"),
                        is_bot=False,
                        raw_data=data,
                    )
                return None

        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            return None

    async def get_chat_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a WhatsApp chat."""
        if not self._session:
            return None

        try:
            async with self._session.get(
                f"{self._bridge_url}/chat/{chat_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "id": data.get("id", chat_id),
                        "name": data.get("name"),
                        "is_group": data.get("isGroup", False),
                        "participant_count": len(data.get("participants", [])),
                        "unread_count": data.get("unreadCount", 0),
                    }
                return None

        except Exception as e:
            logger.error(f"Failed to get chat info: {e}")
            return None

    async def download_media(self, media: MediaAttachment) -> Optional[bytes]:
        """Download media from WhatsApp."""
        if not self._session or not media.file_id:
            return None

        try:
            async with self._session.get(
                f"{self._bridge_url}/media/{media.file_id}",
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                return None

        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            return None

    # =========================================================================
    # WhatsApp-specific Methods
    # =========================================================================

    async def get_qr_code(self) -> Optional[str]:
        """
        Get QR code for WhatsApp Web authentication.

        Returns:
            Base64-encoded QR code image, or None if already authenticated
        """
        if not self._session:
            return None

        try:
            async with self._session.get(
                f"{self._bridge_url}/qr",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("qr")
                elif resp.status == 204:
                    # Already authenticated
                    return None
                return None

        except Exception as e:
            logger.error(f"Failed to get QR code: {e}")
            return None

    async def get_connection_status(self) -> Dict[str, Any]:
        """Get WhatsApp connection status."""
        if not self._session:
            return {"status": "adapter_not_started"}

        try:
            async with self._session.get(
                f"{self._bridge_url}/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"status": "bridge_error", "code": resp.status}

        except Exception as e:
            return {"status": "connection_error", "error": str(e)}

    async def logout(self) -> bool:
        """Logout from WhatsApp (will require QR scan again)."""
        if not self._session:
            return False

        try:
            async with self._session.post(
                f"{self._bridge_url}/logout",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200

        except Exception as e:
            logger.error(f"Failed to logout: {e}")
            return False
