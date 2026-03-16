"""
Home Assistant Service.

Integrates with Home Assistant for smart home control.
Supports device control, status queries, and automation triggers.
"""

import os
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import httpx

from app.db_client import get_db_client

logger = logging.getLogger(__name__)


class DeviceType(str, Enum):
    """Types of smart home devices."""
    LIGHT = "light"
    SWITCH = "switch"
    CLIMATE = "climate"
    SENSOR = "sensor"
    COVER = "cover"
    MEDIA_PLAYER = "media_player"
    VACUUM = "vacuum"
    FAN = "fan"
    LOCK = "lock"
    CAMERA = "camera"
    BINARY_SENSOR = "binary_sensor"
    AUTOMATION = "automation"
    SCENE = "scene"
    SCRIPT = "script"


@dataclass
class Device:
    """A smart home device."""
    entity_id: str
    friendly_name: str
    device_type: DeviceType
    state: str
    attributes: Dict[str, Any]
    area: Optional[str] = None
    last_changed: Optional[datetime] = None
    last_updated: Optional[datetime] = None


@dataclass
class ServiceCall:
    """A Home Assistant service call."""
    domain: str
    service: str
    entity_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class HomeAssistantService:
    """
    Service for Home Assistant integration.

    Features:
    - Device discovery and state queries
    - Service calls for device control
    - Automation and scene triggers
    - State history retrieval
    - Area-based device grouping
    """

    def __init__(self):
        self.base_url = os.getenv("HOME_ASSISTANT_URL", "").rstrip("/")
        self.token = os.getenv("HOME_ASSISTANT_TOKEN", "")
        self.enabled = os.getenv("HOME_ASSISTANT_ENABLED", "false").lower() == "true"
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        """Check if Home Assistant is properly configured."""
        return bool(self.base_url and self.token and self.enabled)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def check_connection(self) -> Dict[str, Any]:
        """Check connection to Home Assistant."""
        if not self.is_configured:
            return {
                "connected": False,
                "error": "Home Assistant not configured. Set HOME_ASSISTANT_URL, HOME_ASSISTANT_TOKEN, and HOME_ASSISTANT_ENABLED=true"
            }

        try:
            client = await self._get_client()
            response = await client.get("/api/")
            response.raise_for_status()
            data = response.json()
            return {
                "connected": True,
                "version": data.get("version"),
                "message": data.get("message")
            }
        except Exception as e:
            logger.error(f"Home Assistant connection failed: {e}")
            return {
                "connected": False,
                "error": str(e)
            }

    async def get_states(self) -> List[Device]:
        """Get all entity states."""
        if not self.is_configured:
            return []

        try:
            client = await self._get_client()
            response = await client.get("/api/states")
            response.raise_for_status()
            states = response.json()

            devices = []
            for state in states:
                entity_id = state.get("entity_id", "")
                domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

                try:
                    device_type = DeviceType(domain)
                except ValueError:
                    continue  # Skip unsupported device types

                devices.append(Device(
                    entity_id=entity_id,
                    friendly_name=state.get("attributes", {}).get("friendly_name", entity_id),
                    device_type=device_type,
                    state=state.get("state", "unknown"),
                    attributes=state.get("attributes", {}),
                    area=state.get("attributes", {}).get("area_id"),
                    last_changed=self._parse_datetime(state.get("last_changed")),
                    last_updated=self._parse_datetime(state.get("last_updated"))
                ))

            return devices
        except Exception as e:
            logger.error(f"Failed to get states: {e}")
            return []

    async def get_device(self, entity_id: str) -> Optional[Device]:
        """Get a specific device by entity_id."""
        if not self.is_configured:
            return None

        try:
            client = await self._get_client()
            response = await client.get(f"/api/states/{entity_id}")
            response.raise_for_status()
            state = response.json()

            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            try:
                device_type = DeviceType(domain)
            except ValueError:
                device_type = DeviceType.SENSOR  # Default fallback

            return Device(
                entity_id=entity_id,
                friendly_name=state.get("attributes", {}).get("friendly_name", entity_id),
                device_type=device_type,
                state=state.get("state", "unknown"),
                attributes=state.get("attributes", {}),
                area=state.get("attributes", {}).get("area_id"),
                last_changed=self._parse_datetime(state.get("last_changed")),
                last_updated=self._parse_datetime(state.get("last_updated"))
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get device {entity_id}: {e}")
            return None

    async def get_devices_by_type(self, device_type: DeviceType) -> List[Device]:
        """Get all devices of a specific type."""
        all_devices = await self.get_states()
        return [d for d in all_devices if d.device_type == device_type]

    async def get_devices_by_area(self, area: str) -> List[Device]:
        """Get all devices in a specific area."""
        all_devices = await self.get_states()
        return [d for d in all_devices if d.area and area.lower() in d.area.lower()]

    async def call_service(self, call: ServiceCall) -> Dict[str, Any]:
        """Call a Home Assistant service."""
        if not self.is_configured:
            return {"success": False, "error": "Home Assistant not configured"}

        try:
            client = await self._get_client()

            payload = {}
            if call.entity_id:
                payload["entity_id"] = call.entity_id
            if call.data:
                payload.update(call.data)

            response = await client.post(
                f"/api/services/{call.domain}/{call.service}",
                json=payload
            )
            response.raise_for_status()

            # Log to database
            await self._log_action(call, success=True)

            return {
                "success": True,
                "result": response.json() if response.text else None
            }
        except Exception as e:
            logger.error(f"Service call failed: {e}")
            await self._log_action(call, success=False, error=str(e))
            return {"success": False, "error": str(e)}

    # Convenience methods for common operations

    async def turn_on(self, entity_id: str, **kwargs) -> Dict[str, Any]:
        """Turn on a device."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="turn_on",
            entity_id=entity_id,
            data=kwargs if kwargs else None
        ))

    async def turn_off(self, entity_id: str) -> Dict[str, Any]:
        """Turn off a device."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="turn_off",
            entity_id=entity_id
        ))

    async def toggle(self, entity_id: str) -> Dict[str, Any]:
        """Toggle a device."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="toggle",
            entity_id=entity_id
        ))

    async def set_light(
        self,
        entity_id: str,
        brightness: Optional[int] = None,
        color_temp: Optional[int] = None,
        rgb_color: Optional[tuple] = None,
        transition: Optional[float] = None
    ) -> Dict[str, Any]:
        """Control a light with specific settings."""
        data = {}
        if brightness is not None:
            data["brightness"] = max(0, min(255, brightness))
        if color_temp is not None:
            data["color_temp"] = color_temp
        if rgb_color is not None:
            data["rgb_color"] = list(rgb_color)
        if transition is not None:
            data["transition"] = transition

        return await self.call_service(ServiceCall(
            domain="light",
            service="turn_on",
            entity_id=entity_id,
            data=data if data else None
        ))

    async def set_climate(
        self,
        entity_id: str,
        temperature: Optional[float] = None,
        hvac_mode: Optional[str] = None,
        target_temp_high: Optional[float] = None,
        target_temp_low: Optional[float] = None
    ) -> Dict[str, Any]:
        """Control a climate device."""
        results = []

        if hvac_mode is not None:
            result = await self.call_service(ServiceCall(
                domain="climate",
                service="set_hvac_mode",
                entity_id=entity_id,
                data={"hvac_mode": hvac_mode}
            ))
            results.append(result)

        if temperature is not None:
            result = await self.call_service(ServiceCall(
                domain="climate",
                service="set_temperature",
                entity_id=entity_id,
                data={"temperature": temperature}
            ))
            results.append(result)
        elif target_temp_high is not None or target_temp_low is not None:
            data = {}
            if target_temp_high is not None:
                data["target_temp_high"] = target_temp_high
            if target_temp_low is not None:
                data["target_temp_low"] = target_temp_low
            result = await self.call_service(ServiceCall(
                domain="climate",
                service="set_temperature",
                entity_id=entity_id,
                data=data
            ))
            results.append(result)

        return {
            "success": all(r.get("success") for r in results),
            "results": results
        }

    async def trigger_automation(self, entity_id: str) -> Dict[str, Any]:
        """Trigger an automation."""
        return await self.call_service(ServiceCall(
            domain="automation",
            service="trigger",
            entity_id=entity_id
        ))

    async def activate_scene(self, entity_id: str) -> Dict[str, Any]:
        """Activate a scene."""
        return await self.call_service(ServiceCall(
            domain="scene",
            service="turn_on",
            entity_id=entity_id
        ))

    async def run_script(self, entity_id: str, **variables) -> Dict[str, Any]:
        """Run a script with optional variables."""
        return await self.call_service(ServiceCall(
            domain="script",
            service=entity_id.replace("script.", ""),
            data=variables if variables else None
        ))

    async def get_history(
        self,
        entity_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get state history for an entity."""
        if not self.is_configured:
            return []

        try:
            from datetime import timedelta
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)

            client = await self._get_client()
            response = await client.get(
                f"/api/history/period/{start_time.isoformat()}",
                params={
                    "filter_entity_id": entity_id,
                    "end_time": end_time.isoformat()
                }
            )
            response.raise_for_status()

            history = response.json()
            if history and len(history) > 0:
                return history[0]  # History returns array of arrays
            return []
        except Exception as e:
            logger.error(f"Failed to get history for {entity_id}: {e}")
            return []

    async def get_areas(self) -> List[Dict[str, Any]]:
        """Get all areas/rooms."""
        if not self.is_configured:
            return []

        try:
            client = await self._get_client()
            # Use websocket-style API through REST
            response = await client.get("/api/config")
            response.raise_for_status()
            config = response.json()

            # Areas are in the registry, get devices and extract unique areas
            devices = await self.get_states()
            areas = set()
            for d in devices:
                if d.area:
                    areas.add(d.area)

            return [{"area_id": a, "name": a} for a in sorted(areas)]
        except Exception as e:
            logger.error(f"Failed to get areas: {e}")
            return []

    async def _log_action(
        self,
        call: ServiceCall,
        success: bool,
        error: Optional[str] = None
    ):
        """Log action to database for tracking."""
        try:
            db = get_db_client()
            with db.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO smart_home_actions
                    (domain, service, entity_id, data, success, error, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (
                    call.domain,
                    call.service,
                    call.entity_id,
                    str(call.data) if call.data else None,
                    success,
                    error
                ))
        except Exception as e:
            # Don't fail on logging errors
            logger.warning(f"Failed to log smart home action: {e}")

    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            # Handle various ISO formats
            if "+" in dt_str:
                dt_str = dt_str.split("+")[0]
            if "." in dt_str:
                dt_str = dt_str.split(".")[0]
            return datetime.fromisoformat(dt_str)
        except Exception:
            return None


# Singleton instance
_service: Optional[HomeAssistantService] = None


def get_home_assistant_service() -> HomeAssistantService:
    """Get or create Home Assistant service instance."""
    global _service
    if _service is None:
        _service = HomeAssistantService()
    return _service
