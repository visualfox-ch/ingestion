import json

import httpx
import pytest
from fastapi import FastAPI

from app.routers import voice_router
from app.services import voice_prooflist
from app.services.voice_tts import OutputFormat, SynthesisResult, TTSProvider


class StubVoiceTTS:
    async def synthesize(self, text, config):
        payload = f"{config.provider.value}:{config.voice_id}:{text[:24]}".encode("utf-8")
        return SynthesisResult(
            audio_bytes=payload,
            format=config.output_format.value,
            voice=config.voice_id,
            character_count=len(text),
        )


def _build_client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(voice_router.router)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_voice_prooflist_preview_rejects_non_cowork_source():
    async with _build_client() as client:
        response = await client.post(
            "/voice/prooflist/preview",
            json={
                "source_path": "/tmp/not-allowed.md",
            },
        )

    assert response.status_code == 400
    assert "source_path must start with" in response.json()["detail"]


@pytest.mark.asyncio
async def test_voice_prooflist_preview_creates_audio_and_metadata(tmp_path, monkeypatch):
    source_root = tmp_path / "brain" / "documents" / "inbox" / "external_projects" / "visualfox_claude_cowork"
    source_file = source_root / "visualfox" / "drafts" / "launch-post.md"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "# Launch Post\n\nThis draft should sound like a calm founder note, not ad copy.\n",
        encoding="utf-8",
    )

    output_root = tmp_path / "brain" / "data" / "audio_prooflists" / "visualfox"

    monkeypatch.setattr(voice_prooflist, "DEFAULT_SOURCE_ROOT", str(source_root))
    monkeypatch.setattr(
        voice_prooflist,
        "ALLOWED_SOURCE_PREFIXES",
        (f"{source_root}/visualfox/", f"{source_root}/linkedin/"),
    )
    monkeypatch.setattr(
        voice_prooflist,
        "ALLOWED_OUTPUT_PREFIXES",
        (f"{tmp_path}/brain/data/audio_prooflists/",),
    )
    monkeypatch.setattr(voice_prooflist, "DEFAULT_OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(
        voice_prooflist,
        "_default_voice_prooflist_service",
        voice_prooflist.VoiceProoflistService(tts=StubVoiceTTS()),
    )

    async with _build_client() as client:
        response = await client.post(
            "/voice/prooflist/preview",
            json={
                "source_path": str(source_file),
                "output_root": str(output_root),
                "provider": "openai",
                "voice": "onyx",
                "format": "mp3",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["voice_id"] == "onyx"
    assert payload["review_status"] == "pending_review"
    assert payload["review_options"] == ["listen", "approve", "revise", "discard"]

    audio_path = output_root / "visualfox" / "drafts" / f"launch-post--{payload['source_sha256'][:12]}.mp3"
    metadata_path = output_root / "visualfox" / "drafts" / f"launch-post--{payload['source_sha256'][:12]}.json"
    assert audio_path.exists()
    assert metadata_path.exists()
    assert audio_path.read_bytes().startswith(b"openai:onyx:")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_path"] == str(source_file)
    assert metadata["provider"] == "openai"
    assert metadata["review"]["publish_mode"] == "disabled"
    assert "Launch Post" in metadata["preview_excerpt"]


@pytest.mark.asyncio
async def test_voice_prooflist_service_requires_voice_id_for_elevenlabs(tmp_path, monkeypatch):
    source_root = tmp_path / "brain" / "documents" / "inbox" / "external_projects" / "visualfox_claude_cowork"
    source_file = source_root / "linkedin" / "draft.md"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("LinkedIn draft text", encoding="utf-8")
    output_root = tmp_path / "brain" / "data" / "audio_prooflists" / "visualfox"

    monkeypatch.setattr(voice_prooflist, "DEFAULT_SOURCE_ROOT", str(source_root))
    monkeypatch.setattr(
        voice_prooflist,
        "ALLOWED_SOURCE_PREFIXES",
        (f"{source_root}/visualfox/", f"{source_root}/linkedin/"),
    )
    monkeypatch.setattr(
        voice_prooflist,
        "ALLOWED_OUTPUT_PREFIXES",
        (f"{tmp_path}/brain/data/audio_prooflists/",),
    )

    service = voice_prooflist.VoiceProoflistService(tts=StubVoiceTTS())

    with pytest.raises(voice_prooflist.VoiceProoflistValidationError) as exc:
        await service.generate_preview(
            source_path=str(source_file),
            output_root=str(output_root),
            provider=TTSProvider.ELEVENLABS,
            voice_id=None,
            output_format=OutputFormat.MP3,
        )

    assert "voice_id is required for elevenlabs" in str(exc.value)