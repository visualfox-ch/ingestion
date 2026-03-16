"""
Dashboard service for live monitoring snapshots and WebSocket fan-out.

This module provides:
- Real-time state aggregation (health, conversations, tools, channels, errors)
- Per-client subscription management
- Queue-based message delivery for WebSocket clients
- Broadcast on state changes
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

import requests

from ..observability import get_logger, get_recent_log_events

logger = get_logger("jarvis.dashboard.service")

DASHBOARD_CHANNELS: Set[str] = {
    "state",
    "health",
    "conversations",
    "tools",
    "channels",
    "errors",
}
DEFAULT_DASHBOARD_SUBSCRIPTIONS: Set[str] = {"state"}

_STATE_SECTION_TO_CHANNEL = {
    "health": "health",
    "active_conversations": "conversations",
    "tool_usage": "tools",
    "channel_status": "channels",
    "recent_events": "errors",
    "summary": "state",
}


@dataclass
class DashboardClient:
    client_id: str
    queue: asyncio.Queue
    subscriptions: Set[str] = field(
        default_factory=lambda: set(DEFAULT_DASHBOARD_SUBSCRIPTIONS)
    )
    connected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    dropped_messages: int = 0


class DashboardService:
    """State aggregation + client routing for the dashboard."""

    def __init__(self) -> None:
        self._clients: Dict[str, DashboardClient] = {}
        self._clients_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._latest_state: Optional[Dict[str, Any]] = None
        self._latest_state_hash: Optional[str] = None
        self._watcher_task: Optional[asyncio.Task] = None
        self._poll_interval_seconds = max(
            1.0, float(os.getenv("JARVIS_DASHBOARD_POLL_SECONDS", "5"))
        )
        self._queue_size = max(20, int(os.getenv("JARVIS_DASHBOARD_QUEUE_SIZE", "200")))

    # =========================================================================
    # Client management
    # =========================================================================

    async def register_client(
        self, client_id: str, subscriptions: Optional[Iterable[str]] = None
    ) -> DashboardClient:
        client = DashboardClient(
            client_id=client_id,
            queue=asyncio.Queue(maxsize=self._queue_size),
            subscriptions=self._normalize_subscriptions(subscriptions),
        )
        async with self._clients_lock:
            self._clients[client_id] = client

        await self.ensure_watcher_running()
        logger.info(f"Dashboard client registered: {client_id}")
        return client

    async def unregister_client(self, client_id: str) -> None:
        async with self._clients_lock:
            self._clients.pop(client_id, None)
        logger.info(f"Dashboard client unregistered: {client_id}")

    async def set_subscriptions(
        self, client_id: str, channels: Optional[Iterable[str]]
    ) -> Set[str]:
        normalized = self._normalize_subscriptions(channels)
        async with self._clients_lock:
            client = self._clients.get(client_id)
            if client:
                client.subscriptions = normalized
        return normalized

    async def add_subscriptions(
        self, client_id: str, channels: Optional[Iterable[str]]
    ) -> Set[str]:
        normalized = self._normalize_subscriptions(channels)
        async with self._clients_lock:
            client = self._clients.get(client_id)
            if client:
                client.subscriptions |= normalized
                return set(client.subscriptions)
        return normalized

    async def remove_subscriptions(
        self, client_id: str, channels: Optional[Iterable[str]]
    ) -> Set[str]:
        channels_to_remove = {
            c.strip().lower()
            for c in (channels or [])
            if c and c.strip().lower() in DASHBOARD_CHANNELS
        }
        async with self._clients_lock:
            client = self._clients.get(client_id)
            if client:
                remaining = set(client.subscriptions) - channels_to_remove
                # Keep at least one channel to avoid a dead client.
                client.subscriptions = remaining or set(DEFAULT_DASHBOARD_SUBSCRIPTIONS)
                return set(client.subscriptions)
        return set(DEFAULT_DASHBOARD_SUBSCRIPTIONS)

    async def client_count(self) -> int:
        async with self._clients_lock:
            return len(self._clients)

    def _normalize_subscriptions(
        self, channels: Optional[Iterable[str]]
    ) -> Set[str]:
        normalized = {
            c.strip().lower()
            for c in (channels or [])
            if c and c.strip().lower() in DASHBOARD_CHANNELS
        }
        return normalized or set(DEFAULT_DASHBOARD_SUBSCRIPTIONS)

    # =========================================================================
    # Message delivery
    # =========================================================================

    async def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        async with self._clients_lock:
            client = self._clients.get(client_id)
        if not client:
            return False
        self._enqueue_message(client, message)
        return True

    async def broadcast(
        self, message: Dict[str, Any], channels: Optional[Set[str]] = None
    ) -> int:
        target_channels = None
        if channels is not None:
            target_channels = {
                c.strip().lower()
                for c in channels
                if c and c.strip().lower() in DASHBOARD_CHANNELS
            }
            if not target_channels:
                return 0

        async with self._clients_lock:
            clients = list(self._clients.values())

        delivered = 0
        for client in clients:
            if target_channels and client.subscriptions.isdisjoint(target_channels):
                continue
            self._enqueue_message(client, message)
            delivered += 1
        return delivered

    def _enqueue_message(self, client: DashboardClient, message: Dict[str, Any]) -> None:
        try:
            client.queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop oldest and enqueue latest, so clients receive fresh data.
            try:
                client.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            client.dropped_messages += 1
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:
                client.dropped_messages += 1

    # =========================================================================
    # Aggregation
    # =========================================================================

    async def get_dashboard_state(self, force_refresh: bool = False) -> Dict[str, Any]:
        if not force_refresh:
            async with self._state_lock:
                if self._latest_state is not None:
                    return deepcopy(self._latest_state)

        state, _, _ = await self._refresh_cached_state()
        return deepcopy(state)

    async def _refresh_cached_state(self) -> tuple[Dict[str, Any], Set[str], bool]:
        state = await self._collect_state_snapshot()
        state_hash = self._state_hash(state)

        async with self._state_lock:
            previous_state = self._latest_state
            previous_hash = self._latest_state_hash
            self._latest_state = state
            self._latest_state_hash = state_hash

        changed_channels = (
            self._diff_channels(previous_state, state) if previous_state else set()
        )
        changed = previous_hash is not None and previous_hash != state_hash
        return state, changed_channels, changed

    async def _collect_state_snapshot(self) -> Dict[str, Any]:
        health, conversations, tool_usage, recent_events = await asyncio.gather(
            asyncio.to_thread(self._collect_health_status),
            asyncio.to_thread(self._collect_active_conversations),
            asyncio.to_thread(self._collect_tool_usage),
            asyncio.to_thread(self._collect_recent_events),
        )
        channel_status = await asyncio.to_thread(self._collect_channel_status, health)
        client_count = await self.client_count()

        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health": health,
            "active_conversations": conversations,
            "tool_usage": tool_usage,
            "channel_status": channel_status,
            "recent_events": recent_events,
            "summary": {
                "health_status": health.get("status", "unknown")
                if isinstance(health, dict)
                else "unknown",
                "active_conversations": conversations.get("active_count", 0),
                "tool_calls_total": tool_usage.get("total_tool_calls", 0),
                "channels_online": channel_status.get("summary", {}).get("online", 0),
                "warnings": recent_events.get("warnings", 0),
                "errors": recent_events.get("errors", 0),
                "connected_clients": client_count,
            },
        }
        return snapshot

    def _collect_health_status(self) -> Dict[str, Any]:
        try:
            from ..routers.health_router import health_check  # type: ignore

            health = health_check()
            if isinstance(health, dict):
                return health
        except Exception as e:
            logger.warning(f"Dashboard health collection failed: {e}")

        return {
            "status": "unknown",
            "checks": {},
            "summary": {"total_checks": 0, "healthy": 0, "warning": 0, "unhealthy": 0},
        }

    def _collect_active_conversations(self) -> Dict[str, Any]:
        limit = max(10, int(os.getenv("JARVIS_DASHBOARD_SESSION_LIMIT", "100")))
        active_window_minutes = max(
            5, int(os.getenv("JARVIS_DASHBOARD_ACTIVE_WINDOW_MINUTES", "1440"))
        )

        try:
            from .. import state_db  # type: ignore

            sessions = state_db.list_sessions(limit=limit) or []
        except Exception as e:
            return {
                "active_count": 0,
                "window_minutes": active_window_minutes,
                "total_recent": 0,
                "sessions": [],
                "error": str(e),
            }

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=active_window_minutes)

        active = []
        for row in sessions:
            if not isinstance(row, dict):
                continue
            updated_raw = (
                row.get("updated_at")
                or row.get("last_message_at")
                or row.get("created_at")
            )
            updated_at = self._parse_datetime(updated_raw)
            if not updated_at or updated_at < cutoff:
                continue
            active.append(
                {
                    "session_id": row.get("session_id"),
                    "title": row.get("title"),
                    "namespace": row.get("namespace"),
                    "updated_at": updated_at.isoformat(),
                    "created_at": self._stringify_datetime(row.get("created_at")),
                    "message_count": row.get("message_count"),
                }
            )

        return {
            "active_count": len(active),
            "window_minutes": active_window_minutes,
            "total_recent": len(sessions),
            "sessions": active[:30],
        }

    def _collect_tool_usage(self) -> Dict[str, Any]:
        try:
            from ..observability import metrics, llm_metrics  # type: ignore

            base_stats = metrics.get_stats()
            counters = base_stats.get("counters", {}) or {}
            tool_counters = {
                key: int(value)
                for key, value in counters.items()
                if key.startswith("tool_")
            }
            top_tools = sorted(
                tool_counters.items(), key=lambda item: item[1], reverse=True
            )[:10]

            llm_totals = {}
            try:
                llm_totals = llm_metrics.get_stats().get("totals", {})
            except Exception:
                llm_totals = {}

            return {
                "uptime_seconds": round(float(base_stats.get("uptime_seconds", 0.0)), 2),
                "total_tool_calls": sum(tool_counters.values()),
                "unique_tools": len(tool_counters),
                "agent_runs": int(counters.get("agent_runs", 0)),
                "agent_errors": int(counters.get("agent_errors", 0)),
                "top_tools": [
                    {
                        "name": name[len("tool_") :],
                        "counter_key": name,
                        "calls": calls,
                    }
                    for name, calls in top_tools
                ],
                "llm_requests": int(llm_totals.get("requests", 0)),
                "llm_errors": int(llm_totals.get("errors", 0)),
                "llm_cost_usd": float(llm_totals.get("cost_usd", 0.0)),
            }
        except Exception as e:
            return {
                "uptime_seconds": 0.0,
                "total_tool_calls": 0,
                "unique_tools": 0,
                "agent_runs": 0,
                "agent_errors": 0,
                "top_tools": [],
                "error": str(e),
            }

    def _collect_channel_status(self, health: Dict[str, Any]) -> Dict[str, Any]:
        checks = health.get("checks", {}) if isinstance(health, dict) else {}
        telegram_health = checks.get("telegram_bot", {}) if isinstance(checks, dict) else {}

        telegram_configured = bool(
            os.getenv("TELEGRAM_BOT_TOKEN")
            or Path("/brain/system/secrets/telegram_bot_token.txt").exists()
        )
        discord_configured = bool(
            os.getenv("DISCORD_BOT_TOKEN")
            or Path("/brain/system/secrets/discord_bot_token.txt").exists()
        )
        whatsapp_bridge_url = os.getenv("WHATSAPP_BRIDGE_URL", "").strip()
        whatsapp_configured = bool(whatsapp_bridge_url)

        telegram_status = self._normalize_channel_status(
            telegram_health.get("status"),
            configured=telegram_configured,
            connected=telegram_health.get("connected"),
        )

        discord_status = "configured" if discord_configured else "not_configured"
        discord_details: Dict[str, Any] = {
            "configured": discord_configured,
            "source": "env_or_secret_file",
        }

        whatsapp_status = "not_configured"
        whatsapp_details: Dict[str, Any] = {
            "configured": whatsapp_configured,
            "bridge_url": whatsapp_bridge_url or None,
        }
        if whatsapp_configured:
            try:
                resp = requests.get(
                    f"{whatsapp_bridge_url.rstrip('/')}/health",
                    timeout=1.5,
                )
                if resp.ok:
                    payload = resp.json()
                    whatsapp_details["health"] = payload
                    whatsapp_status = self._normalize_channel_status(
                        payload.get("status"),
                        configured=True,
                        connected=payload.get("connected"),
                    )
                else:
                    whatsapp_status = "offline"
                    whatsapp_details["error"] = f"bridge_http_{resp.status_code}"
            except Exception as e:
                whatsapp_status = "offline"
                whatsapp_details["error"] = str(e)

        channels = {
            "telegram": {
                "status": telegram_status,
                "configured": telegram_configured,
                "details": telegram_health,
            },
            "discord": {
                "status": discord_status,
                "configured": discord_configured,
                "details": discord_details,
            },
            "whatsapp": {
                "status": whatsapp_status,
                "configured": whatsapp_configured,
                "details": whatsapp_details,
            },
        }

        summary = {
            "online": 0,
            "degraded": 0,
            "offline": 0,
            "configured": 0,
            "not_configured": 0,
        }
        for item in channels.values():
            status = item.get("status", "offline")
            if status == "online":
                summary["online"] += 1
            elif status == "degraded":
                summary["degraded"] += 1
            elif status == "configured":
                summary["configured"] += 1
            elif status == "not_configured":
                summary["not_configured"] += 1
            else:
                summary["offline"] += 1

        channels["summary"] = summary
        return channels

    def _collect_recent_events(self) -> Dict[str, Any]:
        limit = max(5, int(os.getenv("JARVIS_DASHBOARD_EVENTS_LIMIT", "25")))
        try:
            events = get_recent_log_events(limit=limit, min_level="WARNING")
        except Exception as e:
            return {
                "count": 0,
                "warnings": 0,
                "errors": 0,
                "events": [],
                "error": str(e),
            }

        normalized = []
        warning_count = 0
        error_count = 0

        for event in reversed(events):
            level = str(event.get("level", "UNKNOWN")).upper()
            if level in {"WARNING"}:
                warning_count += 1
            if level in {"ERROR", "CRITICAL"}:
                error_count += 1
            normalized.append(
                {
                    "ts": event.get("ts"),
                    "level": level,
                    "logger": event.get("logger"),
                    "message": event.get("msg"),
                }
            )

        return {
            "count": len(normalized),
            "warnings": warning_count,
            "errors": error_count,
            "events": normalized[:limit],
        }

    def _normalize_channel_status(
        self, raw_status: Any, configured: bool, connected: Any = None
    ) -> str:
        if not configured:
            return "not_configured"

        if connected is True:
            return "online"
        if connected is False:
            return "offline"

        status = str(raw_status or "").strip().lower()
        if status in {"healthy", "ok", "running", "connected", "up", "ready"}:
            return "online"
        if status in {"warning", "degraded", "unstable"}:
            return "degraded"
        if status in {"unknown", ""}:
            return "configured"
        return "offline"

    # =========================================================================
    # Change detection + watcher
    # =========================================================================

    async def ensure_watcher_running(self) -> None:
        if self._watcher_task and not self._watcher_task.done():
            return
        self._watcher_task = asyncio.create_task(
            self._watch_state_changes(),
            name="jarvis-dashboard-state-watcher",
        )
        logger.info("Dashboard state watcher started")

    async def _watch_state_changes(self) -> None:
        while True:
            try:
                if await self.client_count() == 0:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue

                state, changed_channels, changed = await self._refresh_cached_state()
                if changed and changed_channels:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    for channel in sorted(changed_channels):
                        section = self._channel_to_section(channel)
                        await self.broadcast(
                            {
                                "type": "dashboard.update",
                                "channel": channel,
                                "timestamp": timestamp,
                                "data": state.get(section),
                            },
                            channels={channel, "state"},
                        )

                    await self.broadcast(
                        {
                            "type": "dashboard.state_changed",
                            "channel": "state",
                            "timestamp": timestamp,
                            "data": {
                                "changed_channels": sorted(changed_channels),
                                "summary": state.get("summary", {}),
                            },
                        },
                        channels={"state"},
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Dashboard watcher iteration failed: {e}")

            await asyncio.sleep(self._poll_interval_seconds)

    def _diff_channels(
        self, previous_state: Dict[str, Any], current_state: Dict[str, Any]
    ) -> Set[str]:
        changed: Set[str] = set()
        for section, channel in _STATE_SECTION_TO_CHANNEL.items():
            if self._fingerprint(previous_state.get(section)) != self._fingerprint(
                current_state.get(section)
            ):
                changed.add(channel)
        return changed

    def _channel_to_section(self, channel: str) -> str:
        for section, mapped_channel in _STATE_SECTION_TO_CHANNEL.items():
            if mapped_channel == channel:
                return section
        return "summary"

    def _state_hash(self, state: Dict[str, Any]) -> str:
        payload = json.dumps(state, sort_keys=True, default=self._json_default)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _fingerprint(self, payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, default=self._json_default)

    def _json_default(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _parse_datetime(self, raw_value: Any) -> Optional[datetime]:
        if raw_value is None:
            return None
        if isinstance(raw_value, datetime):
            if raw_value.tzinfo is None:
                return raw_value.replace(tzinfo=timezone.utc)
            return raw_value.astimezone(timezone.utc)
        if not isinstance(raw_value, str):
            return None

        value = raw_value.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _stringify_datetime(self, raw_value: Any) -> Optional[str]:
        parsed = self._parse_datetime(raw_value)
        if parsed:
            return parsed.isoformat()
        if raw_value is None:
            return None
        return str(raw_value)


_dashboard_service: Optional[DashboardService] = None


def get_dashboard_service() -> DashboardService:
    global _dashboard_service
    if _dashboard_service is None:
        _dashboard_service = DashboardService()
    return _dashboard_service
