import httpx
import pytest
from fastapi import FastAPI

from app.routers.channel_observability_router import router
from app.services.channel_router import clear_channel_audit_events, list_channel_audit_events


app = FastAPI()
app.include_router(router)


def _build_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _add_event(payload: dict) -> None:
    # The route itself is read-only; seed via service-level buffer helper exposure by calling append through import side effect path.
    from app.services import channel_router as channel_router_module

    channel_router_module._record_channel_audit_event(payload)


def setup_function() -> None:
    clear_channel_audit_events()


def teardown_function() -> None:
    clear_channel_audit_events()


@pytest.mark.asyncio
async def test_recent_channel_envelopes_endpoint_returns_buffered_events():
    _add_event(
        {
            "direction": "inbound",
            "channel": "telegram",
            "recorded_at": "2026-03-20T14:00:00",
            "delivery": {"target_id": "123"},
            "content": {"text_length": 12, "attachment_count": 0},
            "scope": {"org": "projektil", "visibility": "internal"},
        },
    )
    _add_event(
        {
            "direction": "outbound",
            "channel": "discord",
            "recorded_at": "2026-03-20T14:01:00",
            "delivery": {"target_id": "chan-1"},
            "content": {"text_length": 4, "attachment_count": 1},
            "scope": {"org": "visualfox", "visibility": "internal"},
        },
    )

    async with _build_client() as client:
        response = await client.get("/info/channels/envelopes/recent?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["count"] == 2
    assert payload["events"][0]["channel"] == "discord"
    assert payload["events"][1]["channel"] == "telegram"


@pytest.mark.asyncio
async def test_recent_channel_envelopes_endpoint_filters_by_channel_and_direction():
    _add_event(
        {
            "direction": "inbound",
            "channel": "telegram",
            "recorded_at": "2026-03-20T14:00:00",
            "delivery": {"target_id": "123"},
            "content": {"text_length": 12, "attachment_count": 0},
            "scope": {"org": "projektil", "visibility": "internal"},
        },
    )
    _add_event(
        {
            "direction": "outbound",
            "channel": "telegram",
            "recorded_at": "2026-03-20T14:02:00",
            "delivery": {"target_id": "123"},
            "content": {"text_length": 20, "attachment_count": 0},
            "scope": {"org": "projektil", "visibility": "internal"},
        },
    )
    _add_event(
        {
            "direction": "outbound",
            "channel": "discord",
            "recorded_at": "2026-03-20T14:01:00",
            "delivery": {"target_id": "chan-1"},
            "content": {"text_length": 4, "attachment_count": 1},
            "scope": {"org": "visualfox", "visibility": "internal"},
        },
    )

    async with _build_client() as client:
        response = await client.get("/info/channels/envelopes/recent?channel=telegram&direction=outbound")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["channel"] == "telegram"
    assert payload["events"][0]["direction"] == "outbound"


def test_list_channel_audit_events_respects_limit():
    _add_event(
        {"direction": "inbound", "channel": "api", "recorded_at": "2026-03-20T14:00:00"},
    )
    _add_event(
        {"direction": "inbound", "channel": "telegram", "recorded_at": "2026-03-20T14:01:00"},
    )

    events = list_channel_audit_events(limit=1)

    assert len(events) == 1
    assert events[0]["channel"] == "telegram"