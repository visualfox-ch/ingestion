from datetime import datetime
from typing import Any, Dict

import pytest

from app.services import channel_router
from app.services.channel_router import (
    ChannelResponse,
    ChannelRouter,
    ChannelType,
    UnifiedMessage,
    get_channel_envelope,
    get_channel_envelope_audit,
    record_api_request_channel_context,
)
from app.services.channel_router import record_api_response_channel_context


def test_build_inbound_envelope_maps_legacy_namespace_to_scope():
    router = ChannelRouter()
    message = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        message_id="msg-1",
        user_id="user-1",
        user_name="User One",
        content="Status?",
        timestamp=datetime(2026, 3, 20, 10, 30, 0),
        chat_id="chat-7",
        is_reply=True,
        reply_to_id="42",
        attachments=[{"type": "photo"}],
    )

    envelope = router.build_inbound_envelope(
        message,
        {
            "channel": "telegram",
            "namespace": "work_visualfox",
            "session_id": "sess-9",
            "thread_id": "thread-2",
            "owner": "michael_bohl",
        },
    )

    assert envelope.direction == "inbound"
    assert envelope.scope.org == "visualfox"
    assert envelope.scope.visibility == "internal"
    assert envelope.scope.legacy_namespace == "work_visualfox"
    assert envelope.scope.confidence == "mapped"
    assert envelope.session.policy == "per_thread"
    assert envelope.session.session_key == "telegram:chat-7:reply:42"
    assert envelope.session.continuity_hint == "sess-9"
    assert envelope.delivery.thread_id == "thread-2"
    assert envelope.delivery.reply_mode == "same_thread"
    assert envelope.formatting_hints.renderer == "telegram"
    assert envelope.formatting_hints.max_length == 4096
    assert envelope.content["attachments"] == [{"type": "photo"}]


def test_build_outbound_envelope_preserves_delivery_and_formatting_hints():
    router = ChannelRouter()
    response = ChannelResponse(
        content="Alles klar.",
        channel=ChannelType.DISCORD,
        target_id="chan-22",
        reply_to="reply-8",
        thread_id="thread-99",
        attachments=[{"type": "file", "name": "note.txt"}],
    )

    envelope = router.build_outbound_envelope(response)

    assert envelope.direction == "outbound"
    assert envelope.source["channel"] == "discord"
    assert envelope.delivery.target_id == "chan-22"
    assert envelope.delivery.thread_id == "thread-99"
    assert envelope.delivery.reply_to_id == "reply-8"
    assert envelope.delivery.reply_mode == "same_thread"
    assert envelope.formatting_hints.renderer == "channel_native"
    assert envelope.formatting_hints.max_length == 2000
    assert envelope.formatting_hints.supports_attachments is True
    assert envelope.provenance.egress_path == "channel_router.send_response"


def test_channel_envelope_audit_projection_is_compact_and_explicit():
    router = ChannelRouter()
    response = ChannelResponse(
        content="Short response",
        channel=ChannelType.WHATSAPP,
        target_id="4912345",
        attachments=[{"type": "image"}],
    )

    envelope = router.build_outbound_envelope(response)
    audit_view = envelope.to_audit_dict()

    assert audit_view["direction"] == "outbound"
    assert audit_view["channel"] == "whatsapp"
    assert audit_view["delivery"]["target_id"] == "4912345"
    assert audit_view["scope"]["org"] == "projektil"
    assert audit_view["content"]["text_length"] == len("Short response")
    assert audit_view["content"]["has_attachments"] is True
    assert audit_view["content"]["attachment_count"] == 1
    assert audit_view["provenance"]["egress_path"] == "channel_router.send_response"


def test_channel_envelope_helpers_return_only_dict_payloads():
    raw_data: Dict[str, Any] = {
        "_channel_envelope": {"direction": "inbound"},
        "_channel_envelope_audit": {"channel": "api"},
    }

    assert get_channel_envelope(raw_data) == {"direction": "inbound"}
    assert get_channel_envelope_audit(raw_data) == {"channel": "api"}
    assert get_channel_envelope(None) is None
    assert get_channel_envelope_audit({"_channel_envelope_audit": "not-a-dict"}) is None


def test_record_api_request_channel_context_uses_session_as_delivery_target():
    channel_router.clear_channel_audit_events()

    envelope, audit_view = record_api_request_channel_context(
        query="hello from api",
        namespace="shared",
        session_id="sess-api-1",
        user_id="user-77",
        source="copilot",
    )

    assert envelope["source"]["channel"] == "api"
    assert envelope["scope"]["legacy_namespace"] == "shared"
    assert envelope["delivery"]["target_id"] == "sess-api-1"
    assert envelope["session"]["continuity_hint"] == "sess-api-1"
    assert audit_view["channel"] == "api"
    assert audit_view["delivery"]["target_id"] == "sess-api-1"
    assert audit_view["content"]["text_length"] == len("hello from api")
    assert channel_router.list_channel_audit_events(limit=1)[0]["delivery"]["target_id"] == "sess-api-1"

    channel_router.clear_channel_audit_events()


@pytest.mark.asyncio
async def test_route_message_attaches_channel_envelope_for_api_messages(monkeypatch):
    router = ChannelRouter()
    captured = {}

    async def _fake_process_message(message):
        captured["message"] = message
        return "ok"

    monkeypatch.setattr(channel_router, "get_channel_router", lambda: router)
    monkeypatch.setattr(router, "process_message", _fake_process_message)

    result = await channel_router.route_message(
        {
            "channel": "api",
            "message_id": "api-1",
            "user_id": "user-9",
            "user_name": "API User",
            "query": "hello",
            "namespace": "private",
        }
    )

    assert result == "ok"
    message = captured["message"]
    envelope = get_channel_envelope(message.raw_data)
    assert envelope is not None
    assert envelope["direction"] == "inbound"
    assert envelope["scope"]["org"] == "personal"
    assert envelope["scope"]["visibility"] == "private"
    assert envelope["scope"]["legacy_namespace"] == "private"
    assert envelope["source"]["channel"] == "api"
    assert envelope["content"]["text"] == "hello"
    audit_view = get_channel_envelope_audit(message.raw_data)
    assert audit_view is not None
    assert audit_view["scope"]["org"] == "personal"
    assert audit_view["content"]["text_length"] == len("hello")


def test_build_inbound_envelope_flattens_nested_telegram_payloads():
    router = ChannelRouter()
    telegram_payload = {
        "channel": "telegram",
        "namespace": "work_projektil",
        "message": {
            "message_id": 77,
            "date": 1760000000,
            "text": "Ping",
            "message_thread_id": 991,
            "from": {
                "id": 1465947014,
                "username": "michaelbohl",
                "first_name": "Michael",
            },
            "chat": {
                "id": 123456,
                "type": "private",
            },
        },
    }

    message = router.normalize_message(ChannelType.TELEGRAM, telegram_payload)
    envelope = router.build_inbound_envelope(message, telegram_payload)

    assert envelope.source["actor"]["raw_sender"] == "michaelbohl"
    assert envelope.source["conversation"]["chat_id"] == "123456"
    assert envelope.source["conversation"]["thread_id"] == "991"
    assert envelope.delivery.target_id == "123456"
    assert envelope.delivery.thread_id == "991"
    assert envelope.scope.org == "projektil"
    assert envelope.scope.visibility == "internal"


@pytest.mark.asyncio
async def test_route_message_attaches_channel_envelope_for_telegram_messages(monkeypatch):
    router = ChannelRouter()
    captured = {}

    async def _fake_process_message(message):
        captured["message"] = message
        return "telegram-ok"

    monkeypatch.setattr(channel_router, "get_channel_router", lambda: router)
    monkeypatch.setattr(router, "process_message", _fake_process_message)

    result = await channel_router.route_message(
        {
            "channel": "telegram",
            "namespace": "work_projektil",
            "message": {
                "message_id": 88,
                "date": 1760000100,
                "text": "Hallo Jarvis",
                "from": {
                    "id": 42,
                    "username": "mbohl",
                    "first_name": "Michael",
                },
                "chat": {
                    "id": 999,
                    "type": "private",
                },
            },
        }
    )

    assert result == "telegram-ok"
    envelope = get_channel_envelope(captured["message"].raw_data)
    assert envelope["source"]["channel"] == "telegram"
    assert envelope["source"]["actor"]["raw_sender"] == "mbohl"
    assert envelope["source"]["conversation"]["is_dm"] is True
    assert envelope["delivery"]["target_id"] == "999"
    assert envelope["scope"]["org"] == "projektil"
    assert envelope["scope"]["legacy_namespace"] == "work_projektil"
    assert envelope["content"]["text"] == "Hallo Jarvis"
    audit_view = get_channel_envelope_audit(captured["message"].raw_data)
    assert audit_view["channel"] == "telegram"
    assert audit_view["delivery"]["target_id"] == "999"
    assert audit_view["content"]["text_length"] == len("Hallo Jarvis")


def test_build_inbound_envelope_for_whatsapp_preserves_channel_edge_semantics():
    router = ChannelRouter()
    whatsapp_payload = {
        "channel": "whatsapp",
        "namespace": "shared",
        "message_id": "wa-1",
        "phone": "+491701234567",
        "contact_name": "Micha",
        "message": "Bitte kurz zusammenfassen",
        "timestamp": "2026-03-20T12:30:00",
        "chat_id": "491701234567@c.us",
        "attachments": [{"type": "image", "url": "https://example.com/a.jpg"}],
    }

    message = router.normalize_message(ChannelType.WHATSAPP, whatsapp_payload)
    envelope = router.build_inbound_envelope(message, whatsapp_payload)
    audit_view = envelope.to_audit_dict()

    assert message.is_dm is True
    assert envelope.source["channel"] == "whatsapp"
    assert envelope.source["actor"]["raw_sender"] == "+491701234567"
    assert envelope.scope.org == "personal"
    assert envelope.scope.visibility == "shared"
    assert envelope.delivery.target_id == "491701234567@c.us"
    assert envelope.session.policy == "direct"
    assert envelope.formatting_hints.renderer == "plain"
    assert audit_view["channel"] == "whatsapp"
    assert audit_view["scope"]["legacy_namespace"] == "shared"
    assert audit_view["content"]["attachment_count"] == 1


def test_build_inbound_envelope_for_discord_preserves_server_context():
    router = ChannelRouter()
    discord_payload = {
        "channel": "discord",
        "namespace": "work_visualfox",
        "message_id": "discord-1",
        "author_id": "user-55",
        "author_name": "mbohl",
        "content": "Can you summarize this?",
        "timestamp": "2026-03-20T13:45:00",
        "channel_id": "channel-88",
        "guild_id": "guild-7",
        "is_dm": False,
        "attachments": [{"type": "file", "name": "notes.md"}],
    }

    message = router.normalize_message(ChannelType.DISCORD, discord_payload)
    envelope = router.build_inbound_envelope(message, discord_payload)
    audit_view = envelope.to_audit_dict()

    assert message.is_dm is False
    assert envelope.source["channel"] == "discord"
    assert envelope.source["actor"]["raw_sender"] == "mbohl"
    assert envelope.source["conversation"]["channel_id"] == "channel-88"
    assert envelope.scope.org == "visualfox"
    assert envelope.scope.visibility == "internal"
    assert envelope.delivery.target_id == "channel-88"
    assert envelope.session.policy == "shared_chat"
    assert envelope.session.session_key == "discord:channel-88:user-55"
    assert envelope.formatting_hints.renderer == "channel_native"
    assert audit_view["channel"] == "discord"
    assert audit_view["scope"]["legacy_namespace"] == "work_visualfox"
    assert audit_view["content"]["attachment_count"] == 1


@pytest.mark.asyncio
async def test_route_message_attaches_channel_envelope_for_discord_messages(monkeypatch):
    router = ChannelRouter()
    captured = {}

    async def _fake_process_message(message):
        captured["message"] = message
        return "discord-ok"

    monkeypatch.setattr(channel_router, "get_channel_router", lambda: router)
    monkeypatch.setattr(router, "process_message", _fake_process_message)

    result = await channel_router.route_message(
        {
            "channel": "discord",
            "namespace": "work_visualfox",
            "message_id": "discord-2",
            "author_id": "user-77",
            "author_name": "mbohl",
            "content": "Ping from Discord",
            "timestamp": "2026-03-20T13:55:00",
            "channel_id": "channel-22",
            "guild_id": "guild-9",
            "is_dm": False,
        }
    )

    assert result == "discord-ok"
    envelope = get_channel_envelope(captured["message"].raw_data)
    audit_view = get_channel_envelope_audit(captured["message"].raw_data)
    assert envelope is not None
    assert audit_view is not None
    assert envelope["source"]["channel"] == "discord"
    assert envelope["source"]["actor"]["raw_sender"] == "mbohl"
    assert envelope["source"]["conversation"]["channel_id"] == "channel-22"
    assert envelope["scope"]["org"] == "visualfox"
    assert audit_view["channel"] == "discord"
    assert audit_view["delivery"]["target_id"] == "channel-22"
    assert audit_view["content"]["text_length"] == len("Ping from Discord")

def test_record_api_response_channel_context_records_outbound_event():
    channel_router.clear_channel_audit_events()
    envelope, audit_view = record_api_response_channel_context(
        answer="Hello from Jarvis",
        session_id="sess-out-1",
        user_id="user-88",
    )
    assert envelope["source"]["channel"] == "api"
    assert envelope["direction"] == "outbound"
    assert envelope["delivery"]["target_id"] == "sess-out-1"
    assert audit_view["direction"] == "outbound"
    assert audit_view["channel"] == "api"
    assert audit_view["delivery"]["target_id"] == "sess-out-1"
    assert audit_view["content"]["text_length"] == len("Hello from Jarvis")
    events = channel_router.list_channel_audit_events(limit=1)
    assert events[0]["direction"] == "outbound"
    assert events[0]["delivery"]["target_id"] == "sess-out-1"
    channel_router.clear_channel_audit_events()
