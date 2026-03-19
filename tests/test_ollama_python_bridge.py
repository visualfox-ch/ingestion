from unittest.mock import patch

from app.ollama_python_bridge import ask_ollama, generate_and_execute_python
from app.services.ollama_client import OllamaChatResult


def test_ask_ollama_success():
    fake_result = OllamaChatResult(
        success=True,
        content="Antwort vom lokalen Modell",
        model="qwen2.5:7b-instruct",
        prompt_tokens=12,
        completion_tokens=9,
        total_tokens=21,
        duration_ms=45.0,
        stop_reason="stop",
        response_id="chatcmpl-abc",
        error=None,
        raw_response={"id": "chatcmpl-abc"},
    )

    with patch("app.ollama_python_bridge.OllamaClient.chat", return_value=fake_result):
        result = ask_ollama(prompt="Bitte fasse das zusammen", task_type="summarize")

    assert result.status == "success"
    assert result.answer == "Antwort vom lokalen Modell"
    assert result.model_used == "qwen2.5:7b-instruct"
    assert result.prompt_tokens == 12
    assert result.response_tokens == 9


def test_generate_and_execute_python_no_code_returns_error():
    fake_result = OllamaChatResult(
        success=True,
        content="Hier ist eine Erklaerung ohne Codeblock.",
        model="qwen2.5:7b-instruct",
        prompt_tokens=18,
        completion_tokens=30,
        total_tokens=48,
        duration_ms=60.0,
        stop_reason="stop",
    )

    with patch("app.ollama_python_bridge.OllamaClient.chat", return_value=fake_result):
        result = generate_and_execute_python(task_description="Berechne 2+2")

    assert result.status == "error"
    assert result.validation_error is not None
    assert "No executable Python code" in result.validation_error


def test_generate_and_execute_python_exec_error_passes_through():
    fake_generation = OllamaChatResult(
        success=True,
        content="```python\nprint(2 + 2)\n```",
        model="qwen2.5:7b-instruct",
        prompt_tokens=20,
        completion_tokens=12,
        total_tokens=32,
        duration_ms=55.0,
        stop_reason="stop",
    )

    with patch("app.ollama_python_bridge.OllamaClient.chat", return_value=fake_generation):
        with patch(
            "app.tool_modules.sandbox_tools.tool_execute_python",
            return_value={"error": "sandbox unavailable"},
        ):
            result = generate_and_execute_python(task_description="Berechne 2+2")

    assert result.status == "error"
    assert result.generated_code is not None
    assert result.validation_error == "sandbox unavailable"
