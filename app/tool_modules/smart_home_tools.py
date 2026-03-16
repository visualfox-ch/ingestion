"""
Smart Home Tools - Home Assistant Integration

Provides tools for:
- Device control (lights, switches, climate)
- Status queries
- Scene/automation triggers
- Device history
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async function from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new event loop in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def control_smart_home(
    entity_id: str,
    action: str,
    brightness: Optional[int] = None,
    color_temp: Optional[int] = None,
    rgb_color: Optional[List[int]] = None,
    temperature: Optional[float] = None,
    hvac_mode: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Control a smart home device.

    Args:
        entity_id: Home Assistant entity ID (e.g., light.living_room)
        action: Action to perform (turn_on, turn_off, toggle, set)
        brightness: Light brightness (0-255, optional)
        color_temp: Light color temperature in mireds (optional)
        rgb_color: RGB color as [r, g, b] (optional)
        temperature: Target temperature for climate devices (optional)
        hvac_mode: HVAC mode (heat, cool, auto, off, optional)

    Returns:
        Dict with success status and result
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service

        service = get_home_assistant_service()

        if not service.is_configured:
            return {
                "success": False,
                "error": "Home Assistant not configured. Set HOME_ASSISTANT_URL, HOME_ASSISTANT_TOKEN, and HOME_ASSISTANT_ENABLED=true"
            }

        async def _execute():
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

            if action == "turn_off":
                return await service.turn_off(entity_id)
            elif action == "toggle":
                return await service.toggle(entity_id)
            elif action == "turn_on" or action == "set":
                if domain == "light":
                    return await service.set_light(
                        entity_id,
                        brightness=brightness,
                        color_temp=color_temp,
                        rgb_color=tuple(rgb_color) if rgb_color else None
                    )
                elif domain == "climate":
                    return await service.set_climate(
                        entity_id,
                        temperature=temperature,
                        hvac_mode=hvac_mode
                    )
                else:
                    return await service.turn_on(entity_id)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        result = _run_async(_execute())
        return result

    except Exception as e:
        logger.error(f"Smart home control failed: {e}")
        return {"success": False, "error": str(e)}


def get_smart_home_status(
    entity_id: Optional[str] = None,
    device_type: Optional[str] = None,
    area: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get status of smart home devices.

    Args:
        entity_id: Specific entity to query (optional)
        device_type: Filter by device type (light, switch, climate, etc.)
        area: Filter by area/room (optional)

    Returns:
        Dict with device status information
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service, DeviceType

        service = get_home_assistant_service()

        if not service.is_configured:
            return {
                "success": False,
                "error": "Home Assistant not configured"
            }

        async def _execute():
            if entity_id:
                device = await service.get_device(entity_id)
                if device:
                    return {
                        "success": True,
                        "device": {
                            "entity_id": device.entity_id,
                            "name": device.friendly_name,
                            "type": device.device_type.value,
                            "state": device.state,
                            "attributes": device.attributes,
                            "area": device.area,
                            "last_changed": device.last_changed.isoformat() if device.last_changed else None
                        }
                    }
                return {"success": False, "error": f"Device not found: {entity_id}"}

            devices = []
            if device_type:
                try:
                    dt = DeviceType(device_type)
                    devices = await service.get_devices_by_type(dt)
                except ValueError:
                    return {"success": False, "error": f"Unknown device type: {device_type}"}
            elif area:
                devices = await service.get_devices_by_area(area)
            else:
                devices = await service.get_states()

            return {
                "success": True,
                "count": len(devices),
                "devices": [
                    {
                        "entity_id": d.entity_id,
                        "name": d.friendly_name,
                        "type": d.device_type.value,
                        "state": d.state,
                        "area": d.area
                    }
                    for d in devices[:50]  # Limit response size
                ]
            }

        return _run_async(_execute())

    except Exception as e:
        logger.error(f"Smart home status query failed: {e}")
        return {"success": False, "error": str(e)}


def list_smart_home_devices(
    device_type: Optional[str] = None,
    area: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    List available smart home devices.

    Args:
        device_type: Filter by type (light, switch, climate, sensor, etc.)
        area: Filter by area/room

    Returns:
        Dict with list of devices grouped by type
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service

        service = get_home_assistant_service()

        if not service.is_configured:
            return {
                "success": False,
                "error": "Home Assistant not configured"
            }

        async def _execute():
            # Check connection first
            conn = await service.check_connection()
            if not conn.get("connected"):
                return {
                    "success": False,
                    "error": conn.get("error", "Connection failed")
                }

            devices = await service.get_states()

            # Filter if requested
            if device_type:
                devices = [d for d in devices if d.device_type.value == device_type]
            if area:
                devices = [d for d in devices if d.area and area.lower() in d.area.lower()]

            # Group by type
            by_type = {}
            for d in devices:
                t = d.device_type.value
                if t not in by_type:
                    by_type[t] = []
                by_type[t].append({
                    "entity_id": d.entity_id,
                    "name": d.friendly_name,
                    "state": d.state,
                    "area": d.area
                })

            # Get areas
            areas = set(d.area for d in devices if d.area)

            return {
                "success": True,
                "home_assistant_version": conn.get("version"),
                "total_devices": len(devices),
                "areas": sorted(list(areas)),
                "device_types": list(by_type.keys()),
                "devices_by_type": by_type
            }

        return _run_async(_execute())

    except Exception as e:
        logger.error(f"List devices failed: {e}")
        return {"success": False, "error": str(e)}


def trigger_smart_home_scene(
    scene_name: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Activate a scene or automation.

    Args:
        scene_name: Scene name or entity_id (e.g., scene.movie_time)

    Returns:
        Dict with activation result
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service

        service = get_home_assistant_service()

        if not service.is_configured:
            return {
                "success": False,
                "error": "Home Assistant not configured"
            }

        async def _execute():
            # Normalize scene name
            entity_id = scene_name
            if not scene_name.startswith("scene.") and not scene_name.startswith("automation."):
                # Try to find matching scene
                scenes = await service.get_devices_by_type(
                    __import__('app.services.home_assistant_service', fromlist=['DeviceType']).DeviceType.SCENE
                )
                matching = [s for s in scenes if scene_name.lower() in s.friendly_name.lower()]
                if matching:
                    entity_id = matching[0].entity_id
                else:
                    entity_id = f"scene.{scene_name.lower().replace(' ', '_')}"

            if entity_id.startswith("automation."):
                result = await service.trigger_automation(entity_id)
            else:
                result = await service.activate_scene(entity_id)

            return {
                "success": result.get("success", False),
                "scene": entity_id,
                "error": result.get("error")
            }

        return _run_async(_execute())

    except Exception as e:
        logger.error(f"Scene activation failed: {e}")
        return {"success": False, "error": str(e)}


def get_smart_home_history(
    entity_id: str,
    hours: int = 24,
    **kwargs
) -> Dict[str, Any]:
    """
    Get state history for a device.

    Args:
        entity_id: Device entity ID
        hours: Number of hours of history (default: 24)

    Returns:
        Dict with state history
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service

        service = get_home_assistant_service()

        if not service.is_configured:
            return {
                "success": False,
                "error": "Home Assistant not configured"
            }

        async def _execute():
            history = await service.get_history(entity_id, hours=hours)

            # Process history entries
            entries = []
            for entry in history[-100:]:  # Last 100 entries
                entries.append({
                    "state": entry.get("state"),
                    "last_changed": entry.get("last_changed"),
                    "attributes": entry.get("attributes", {})
                })

            return {
                "success": True,
                "entity_id": entity_id,
                "hours": hours,
                "entry_count": len(entries),
                "history": entries
            }

        return _run_async(_execute())

    except Exception as e:
        logger.error(f"History query failed: {e}")
        return {"success": False, "error": str(e)}


def get_smart_home_connection_status(**kwargs) -> Dict[str, Any]:
    """
    Check Home Assistant connection status.

    Returns:
        Dict with connection status and version info
    """
    try:
        from app.services.home_assistant_service import get_home_assistant_service

        service = get_home_assistant_service()

        async def _execute():
            return await service.check_connection()

        return _run_async(_execute())

    except Exception as e:
        logger.error(f"Connection check failed: {e}")
        return {"connected": False, "error": str(e)}


# Tool definitions for Claude
SMART_HOME_TOOLS = [
    {
        "name": "control_smart_home",
        "description": "Control smart home devices (lights, switches, climate). Turn on/off, toggle, set brightness, temperature, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Home Assistant entity ID (e.g., light.living_room, switch.fan, climate.thermostat)"
                },
                "action": {
                    "type": "string",
                    "enum": ["turn_on", "turn_off", "toggle", "set"],
                    "description": "Action to perform"
                },
                "brightness": {
                    "type": "integer",
                    "description": "Light brightness 0-255 (optional, for lights)"
                },
                "color_temp": {
                    "type": "integer",
                    "description": "Color temperature in mireds (optional, for lights)"
                },
                "rgb_color": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "RGB color as [r, g, b] (optional, for lights)"
                },
                "temperature": {
                    "type": "number",
                    "description": "Target temperature (optional, for climate devices)"
                },
                "hvac_mode": {
                    "type": "string",
                    "enum": ["heat", "cool", "auto", "off"],
                    "description": "HVAC mode (optional, for climate devices)"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    {
        "name": "get_smart_home_status",
        "description": "Get status of smart home devices. Query specific device or filter by type/area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Specific entity ID to query (optional)"
                },
                "device_type": {
                    "type": "string",
                    "enum": ["light", "switch", "climate", "sensor", "cover", "media_player", "vacuum", "fan", "lock"],
                    "description": "Filter by device type (optional)"
                },
                "area": {
                    "type": "string",
                    "description": "Filter by area/room name (optional)"
                }
            }
        }
    },
    {
        "name": "list_smart_home_devices",
        "description": "List all available smart home devices, grouped by type. Use to discover what devices are available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_type": {
                    "type": "string",
                    "description": "Filter by device type (optional)"
                },
                "area": {
                    "type": "string",
                    "description": "Filter by area/room (optional)"
                }
            }
        }
    },
    {
        "name": "trigger_smart_home_scene",
        "description": "Activate a Home Assistant scene or automation. Scenes are pre-configured device states (e.g., 'movie time', 'good night').",
        "input_schema": {
            "type": "object",
            "properties": {
                "scene_name": {
                    "type": "string",
                    "description": "Scene name or entity_id (e.g., 'movie_time' or 'scene.movie_time')"
                }
            },
            "required": ["scene_name"]
        }
    },
    {
        "name": "get_smart_home_history",
        "description": "Get state history for a device over time. Useful for analyzing patterns and troubleshooting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Device entity ID"
                },
                "hours": {
                    "type": "integer",
                    "description": "Number of hours of history (default: 24)"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_smart_home_connection_status",
        "description": "Check if Home Assistant is connected and get version info.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
