"""
WhatsApp Pairing & Status Router

Endpoints for WhatsApp Web pairing via QR code and connection management.
Works with the WhatsApp Bridge service (Node.js).

Setup:
1. Start the WhatsApp bridge service
2. Call GET /whatsapp/qr to get QR code
3. Scan with WhatsApp mobile app
4. Check GET /whatsapp/status for connection state
"""

import base64
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# =============================================================================
# Configuration
# =============================================================================

def get_bridge_url() -> str:
    """Get WhatsApp bridge service URL."""
    return os.environ.get("WHATSAPP_BRIDGE_URL", "http://localhost:3000")


# =============================================================================
# Response Models
# =============================================================================


class HealthResponse(BaseModel):
    """WhatsApp service health."""
    status: str
    bridge_url: str
    bridge_reachable: bool
    whatsapp_connected: bool
    phone_number: Optional[str] = None


class QRResponse(BaseModel):
    """QR code response."""
    status: str
    qr_base64: Optional[str] = None
    qr_data: Optional[str] = None
    message: str


class StatusResponse(BaseModel):
    """Connection status response."""
    status: str
    connected: bool
    phone_number: Optional[str] = None
    phone_name: Optional[str] = None
    battery: Optional[int] = None
    last_seen: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send message request."""
    phone: str = Field(..., description="Phone number with country code (e.g., 491234567890)")
    message: str = Field(..., description="Message text")


class SendMessageResponse(BaseModel):
    """Send message response."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def whatsapp_health():
    """Check WhatsApp service health and bridge connectivity."""
    import aiohttp

    bridge_url = get_bridge_url()
    bridge_reachable = False
    whatsapp_connected = False
    phone_number = None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{bridge_url}/health",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    bridge_reachable = True
                    data = await resp.json()
                    whatsapp_connected = data.get("status") == "connected"
                    phone_number = data.get("phoneNumber")

    except Exception as e:
        logger.debug(f"Bridge health check failed: {e}")

    status = "healthy" if whatsapp_connected else ("degraded" if bridge_reachable else "unavailable")

    return HealthResponse(
        status=status,
        bridge_url=bridge_url,
        bridge_reachable=bridge_reachable,
        whatsapp_connected=whatsapp_connected,
        phone_number=phone_number,
    )


@router.get("/qr", response_model=QRResponse)
async def get_qr_code():
    """
    Get QR code for WhatsApp Web pairing.

    Returns base64-encoded QR code image or status if already connected.
    """
    import aiohttp

    bridge_url = get_bridge_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{bridge_url}/qr",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return QRResponse(
                        status="qr_ready",
                        qr_base64=data.get("qr"),
                        qr_data=data.get("qrData"),
                        message="Scan this QR code with WhatsApp on your phone",
                    )
                elif resp.status == 204:
                    return QRResponse(
                        status="already_connected",
                        message="WhatsApp is already connected. No QR code needed.",
                    )
                else:
                    error = await resp.text()
                    return QRResponse(
                        status="error",
                        message=f"Bridge returned error: {error}",
                    )

    except aiohttp.ClientError as e:
        return QRResponse(
            status="bridge_unavailable",
            message=f"Cannot reach WhatsApp bridge at {bridge_url}. Is it running?",
        )
    except Exception as e:
        logger.error(f"QR code fetch failed: {e}")
        return QRResponse(
            status="error",
            message=str(e),
        )


@router.get("/qr/image")
async def get_qr_image():
    """
    Get QR code as displayable HTML page.

    Open this URL in a browser to see and scan the QR code.
    """
    import aiohttp

    bridge_url = get_bridge_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{bridge_url}/qr",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    qr_base64 = data.get("qr", "")

                    html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>WhatsApp QR Code - Jarvis</title>
                        <meta http-equiv="refresh" content="30">
                        <style>
                            body {{
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                display: flex;
                                flex-direction: column;
                                align-items: center;
                                justify-content: center;
                                min-height: 100vh;
                                margin: 0;
                                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                                color: white;
                            }}
                            .container {{
                                text-align: center;
                                padding: 2rem;
                            }}
                            h1 {{
                                margin-bottom: 0.5rem;
                            }}
                            p {{
                                color: #888;
                                margin-bottom: 2rem;
                            }}
                            .qr-container {{
                                background: white;
                                padding: 1rem;
                                border-radius: 1rem;
                                box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                            }}
                            img {{
                                max-width: 300px;
                            }}
                            .status {{
                                margin-top: 2rem;
                                color: #4ade80;
                            }}
                            .refresh {{
                                color: #666;
                                font-size: 0.8rem;
                                margin-top: 1rem;
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>🤖 Jarvis WhatsApp</h1>
                            <p>Scan this QR code with WhatsApp on your phone</p>
                            <div class="qr-container">
                                <img src="data:image/png;base64,{qr_base64}" alt="WhatsApp QR Code">
                            </div>
                            <p class="refresh">Page refreshes automatically every 30 seconds</p>
                        </div>
                    </body>
                    </html>
                    """
                    return HTMLResponse(content=html)

                elif resp.status == 204:
                    html = """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>WhatsApp Connected - Jarvis</title>
                        <style>
                            body {
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                min-height: 100vh;
                                margin: 0;
                                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                                color: white;
                            }
                            .container {
                                text-align: center;
                            }
                            .checkmark {
                                font-size: 4rem;
                                margin-bottom: 1rem;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="checkmark">✅</div>
                            <h1>WhatsApp Connected!</h1>
                            <p>Jarvis is ready to receive messages.</p>
                        </div>
                    </body>
                    </html>
                    """
                    return HTMLResponse(content=html)

    except Exception as e:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>WhatsApp Error - Jarvis</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{
                    font-family: -apple-system, sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    margin: 0;
                    background: #1a1a2e;
                    color: white;
                }}
                .error {{ color: #f87171; }}
            </style>
        </head>
        <body>
            <div>
                <h1>⚠️ Bridge Unavailable</h1>
                <p class="error">Cannot reach WhatsApp bridge service.</p>
                <p>Make sure the bridge is running at: {bridge_url}</p>
                <p style="color: #666;">Retrying in 10 seconds...</p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=503)


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Get detailed WhatsApp connection status."""
    import aiohttp

    bridge_url = get_bridge_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{bridge_url}/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return StatusResponse(
                        status=data.get("status", "unknown"),
                        connected=data.get("status") == "connected",
                        phone_number=data.get("phoneNumber"),
                        phone_name=data.get("phoneName"),
                        battery=data.get("battery"),
                        last_seen=data.get("lastSeen"),
                    )
                else:
                    return StatusResponse(
                        status="error",
                        connected=False,
                    )

    except Exception as e:
        return StatusResponse(
            status="bridge_unavailable",
            connected=False,
        )


@router.post("/logout")
async def logout():
    """Logout from WhatsApp (will require QR scan again)."""
    import aiohttp

    bridge_url = get_bridge_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{bridge_url}/logout",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return {"status": "logged_out", "message": "WhatsApp session ended. Scan QR to reconnect."}
                else:
                    error = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error)

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f"Bridge unavailable: {e}")


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """
    Send a WhatsApp message.

    Phone number should include country code without + or 00.
    Example: 491234567890 for German number.
    """
    import aiohttp

    bridge_url = get_bridge_url()

    # Format phone number (ensure it's just digits)
    phone = "".join(filter(str.isdigit, request.phone))
    if not phone:
        return SendMessageResponse(success=False, error="Invalid phone number")

    # Add @c.us suffix for WhatsApp
    chat_id = f"{phone}@c.us"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{bridge_url}/send",
                json={"chatId": chat_id, "message": request.message},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return SendMessageResponse(
                        success=True,
                        message_id=data.get("messageId"),
                    )
                else:
                    error = await resp.text()
                    return SendMessageResponse(success=False, error=error)

    except aiohttp.ClientError as e:
        return SendMessageResponse(success=False, error=f"Bridge unavailable: {e}")
    except Exception as e:
        return SendMessageResponse(success=False, error=str(e))


@router.get("/chats")
async def list_chats(limit: int = 20):
    """List recent WhatsApp chats."""
    import aiohttp

    bridge_url = get_bridge_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{bridge_url}/chats",
                params={"limit": limit},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"chats": data.get("chats", [])}
                else:
                    raise HTTPException(status_code=resp.status, detail="Failed to fetch chats")

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f"Bridge unavailable: {e}")
