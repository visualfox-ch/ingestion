from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services.channel_router import list_channel_audit_events

router = APIRouter(prefix="/info/channels", tags=["channel-observability"])


@router.get("/envelopes/recent", response_model=Dict[str, Any])
async def get_recent_channel_envelopes(
    limit: int = Query(20, ge=1, le=100),
    channel: Optional[str] = Query(None, description="Optional channel filter"),
    direction: Optional[str] = Query(None, description="Optional direction filter: inbound|outbound"),
):
    """Return recent channel envelope audit events from the in-memory observability buffer."""
    events = list_channel_audit_events(limit=limit, channel=channel, direction=direction)
    return {
        "status": "ok",
        "count": len(events),
        "filters": {
            "limit": limit,
            "channel": channel,
            "direction": direction,
        },
        "events": events,
    }