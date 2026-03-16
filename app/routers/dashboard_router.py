"""
Dashboard router with REST bootstrap endpoints and live WebSocket updates.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from ..observability import get_logger
from ..services.dashboard_service import (
    DASHBOARD_CHANNELS,
    DashboardClient,
    get_dashboard_service,
)

logger = get_logger("jarvis.dashboard.router")
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ============================================================================
# Auth helpers
# ============================================================================

def _resolve_auth_config() -> Dict[str, Any]:
    header_name = os.getenv("JARVIS_API_KEY_HEADER", "X-API-Key")
    configured_key = os.getenv("JARVIS_API_KEY", "") or os.getenv("API_KEY", "")
    min_key_length = int(os.getenv("JARVIS_API_KEY_MIN_LENGTH", "1"))

    try:
        from .. import config as app_config  # type: ignore

        header_name = getattr(app_config, "API_KEY_HEADER", header_name)
        configured_key = getattr(app_config, "API_KEY", configured_key) or configured_key
        min_key_length = int(
            getattr(app_config, "API_KEY_MIN_LENGTH", min_key_length) or min_key_length
        )
    except Exception:
        # Fallback for minimal environments where app.config is unavailable.
        pass

    return {
        "header_name": header_name,
        "configured_key": configured_key or "",
        "min_key_length": max(1, min_key_length),
    }


def _auth_enabled() -> bool:
    cfg = _resolve_auth_config()
    key = cfg["configured_key"]
    return bool(key) and len(key) >= cfg["min_key_length"]


def _validate_api_key(api_key: Optional[str]) -> bool:
    cfg = _resolve_auth_config()
    expected = cfg["configured_key"]

    if not _auth_enabled():
        return True
    if not api_key:
        return False
    return hmac.compare_digest(str(api_key), str(expected))


def _extract_http_api_key(request: Request) -> Optional[str]:
    cfg = _resolve_auth_config()
    return request.headers.get(cfg["header_name"]) or request.query_params.get("api_key")


def _extract_ws_api_key(websocket: WebSocket) -> Optional[str]:
    cfg = _resolve_auth_config()
    return websocket.headers.get(cfg["header_name"]) or websocket.query_params.get("api_key")


async def dashboard_auth_dependency(request: Request) -> bool:
    if not _auth_enabled():
        return True

    api_key = _extract_http_api_key(request)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not _validate_api_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return True


# ============================================================================
# REST endpoints (initial dashboard state)
# ============================================================================

@router.get("/state")
async def get_dashboard_state(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return await service.get_dashboard_state()


@router.get("/state/health")
async def get_dashboard_health(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return (await service.get_dashboard_state()).get("health", {})


@router.get("/state/conversations")
async def get_dashboard_conversations(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return (await service.get_dashboard_state()).get("active_conversations", {})


@router.get("/state/tools")
async def get_dashboard_tools(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return (await service.get_dashboard_state()).get("tool_usage", {})


@router.get("/state/channels")
async def get_dashboard_channels(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return (await service.get_dashboard_state()).get("channel_status", {})


@router.get("/state/errors")
async def get_dashboard_errors(_auth: bool = Depends(dashboard_auth_dependency)):
    service = get_dashboard_service()
    return (await service.get_dashboard_state()).get("recent_events", {})


# ============================================================================
# WebSocket endpoint
# ============================================================================

@router.websocket("/ws")
async def dashboard_websocket(websocket: WebSocket):
    if _auth_enabled():
        api_key = _extract_ws_api_key(websocket)
        if not _validate_api_key(api_key):
            # Reject unauthorized websocket before upgrade accept.
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()

    service = get_dashboard_service()
    client_id = str(uuid.uuid4())
    initial_channels = _channels_from_ws_query(websocket.query_params.get("channels"))
    client = await service.register_client(client_id, initial_channels)

    await service.send_to_client(
        client_id,
        _ws_message(
            "connected",
            {
                "client_id": client_id,
                "subscriptions": sorted(client.subscriptions),
                "supported_channels": sorted(DASHBOARD_CHANNELS),
            },
        ),
    )

    initial_state = await service.get_dashboard_state()
    await service.send_to_client(
        client_id,
        _ws_message("dashboard.state", initial_state),
    )

    sender_task = asyncio.create_task(
        _ws_sender_loop(websocket, client),
        name=f"dashboard-ws-sender-{client_id}",
    )
    receiver_task = asyncio.create_task(
        _ws_receiver_loop(websocket, service, client_id),
        name=f"dashboard-ws-receiver-{client_id}",
    )

    try:
        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                logger.warning(
                    f"Dashboard websocket task ended with exception for {client_id}: {exc}"
                )
    finally:
        await service.unregister_client(client_id)
        for task in (sender_task, receiver_task):
            if not task.done():
                task.cancel()
            with contextlib.suppress(Exception):
                await task


async def _ws_sender_loop(websocket: WebSocket, client: DashboardClient) -> None:
    while True:
        payload = await client.queue.get()
        await websocket.send_json(payload)


async def _ws_receiver_loop(
    websocket: WebSocket,
    service,
    client_id: str,
) -> None:
    while True:
        try:
            raw_payload = await websocket.receive_text()
        except WebSocketDisconnect:
            break

        try:
            payload = json.loads(raw_payload) if raw_payload else {}
        except json.JSONDecodeError:
            await service.send_to_client(
                client_id,
                _ws_message("error", {"message": "Invalid JSON payload"}),
            )
            continue

        msg_type = str(payload.get("type", "")).strip().lower()
        if msg_type == "ping":
            await service.send_to_client(client_id, _ws_message("pong", {}))
            continue

        if msg_type == "subscribe":
            channels = payload.get("channels")
            subscriptions = await service.add_subscriptions(client_id, channels)
            await service.send_to_client(
                client_id,
                _ws_message(
                    "subscribed",
                    {"subscriptions": sorted(subscriptions)},
                ),
            )
            continue

        if msg_type == "unsubscribe":
            channels = payload.get("channels")
            subscriptions = await service.remove_subscriptions(client_id, channels)
            await service.send_to_client(
                client_id,
                _ws_message(
                    "unsubscribed",
                    {"subscriptions": sorted(subscriptions)},
                ),
            )
            continue

        if msg_type == "set_subscriptions":
            channels = payload.get("channels")
            subscriptions = await service.set_subscriptions(client_id, channels)
            await service.send_to_client(
                client_id,
                _ws_message(
                    "subscriptions_set",
                    {"subscriptions": sorted(subscriptions)},
                ),
            )
            continue

        if msg_type in {"request_state", "get_state"}:
            force_refresh = bool(payload.get("force_refresh", False))
            state = await service.get_dashboard_state(force_refresh=force_refresh)
            await service.send_to_client(
                client_id,
                _ws_message("dashboard.state", state),
            )
            continue

        await service.send_to_client(
            client_id,
            _ws_message(
                "error",
                {
                    "message": "Unsupported message type",
                    "supported_types": [
                        "ping",
                        "subscribe",
                        "unsubscribe",
                        "set_subscriptions",
                        "request_state",
                    ],
                },
            ),
        )


def _channels_from_ws_query(raw_channels: Optional[str]) -> Set[str]:
    if not raw_channels:
        return {"state"}
    channels = [part.strip() for part in raw_channels.split(",")]
    valid = {
        c.lower()
        for c in channels
        if c and c.lower() in DASHBOARD_CHANNELS
    }
    return valid or {"state"}


def _ws_message(message_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": message_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
