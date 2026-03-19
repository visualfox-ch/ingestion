from unittest.mock import Mock, patch

import requests

from app.services.ollama_client import DEFAULT_OLLAMA_TIMEOUT_SECONDS, OllamaClient


def test_ollama_client_chat_success_parses_openai_shape():
    client = OllamaClient(base_url="http://ollama.local:11434", timeout_seconds=10)

    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "id": "chatcmpl-test-1",
        "model": "qwen2.5:7b-instruct",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hallo aus Ollama"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }

    with patch("app.services.ollama_client.requests.post", return_value=fake_response) as mock_post:
        result = client.chat(
            model="qwen2.5:7b-instruct",
            messages=[{"role": "user", "content": "Sag hallo"}],
            system="Du bist hilfreich.",
            max_tokens=128,
            temperature=0.1,
        )

    assert result.success is True
    assert result.content == "Hallo aus Ollama"
    assert result.model == "qwen2.5:7b-instruct"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert result.total_tokens == 18
    assert result.response_id == "chatcmpl-test-1"
    assert result.error is None

    called_kwargs = mock_post.call_args.kwargs
    assert called_kwargs["json"]["stream"] is False
    assert called_kwargs["json"]["messages"][0]["role"] == "system"


def test_ollama_client_chat_handles_http_errors():
    client = OllamaClient(base_url="http://ollama.local:11434", timeout_seconds=10)

    with patch(
        "app.services.ollama_client.requests.post",
        side_effect=requests.RequestException("boom"),
    ):
        result = client.chat(
            model="qwen2.5:7b-instruct",
            messages=[{"role": "user", "content": "Ping"}],
        )

    assert result.success is False
    assert result.stop_reason == "error"
    assert result.error is not None


def test_ollama_client_uses_ollama_host_env(monkeypatch):
    monkeypatch.delenv("JARVIS_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://192.168.1.103:11434")

    client = OllamaClient()

    assert client.base_url == "http://192.168.1.103:11434"
    assert client.timeout_seconds == DEFAULT_OLLAMA_TIMEOUT_SECONDS


def test_ollama_client_falls_back_to_native_chat_on_404():
    client = OllamaClient(base_url="http://ollama.local:11434", timeout_seconds=10)

    openai_404 = Mock()
    openai_404.status_code = 404
    openai_404.raise_for_status.side_effect = requests.HTTPError("404 not found")

    native_response = Mock()
    native_response.status_code = 200
    native_response.raise_for_status.return_value = None
    native_response.json.return_value = {
        "model": "qwen2.5:7b-instruct",
        "message": {"role": "assistant", "content": "OK"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 9,
        "eval_count": 1,
    }

    with patch(
        "app.services.ollama_client.requests.post",
        side_effect=[openai_404, native_response],
    ) as mock_post:
        result = client.chat(
            model="qwen2.5:7b-instruct",
            messages=[{"role": "user", "content": "Antworte mit OK"}],
        )

    assert result.success is True
    assert result.content == "OK"
    assert result.prompt_tokens == 9
    assert result.completion_tokens == 1
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[1].kwargs["json"]["stream"] is False
