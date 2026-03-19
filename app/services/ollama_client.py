"""Ollama API client using OpenAI-compatible chat completions."""

from dataclasses import dataclass
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60.0
DEFAULT_OLLAMA_NATIVE_CHAT_PATH = "/api/chat"


@dataclass
class OllamaChatResult:
    """Normalized result for Ollama chat completions."""

    success: bool
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: float
    stop_reason: str
    response_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class OllamaClient:
    """Small wrapper around Ollama's OpenAI-compatible API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        api_key: Optional[str] = None,
    ):
        env_base_url = (
            os.environ.get("JARVIS_OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
        )
        self.base_url = (base_url or env_base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")

        env_timeout = os.environ.get("JARVIS_OLLAMA_TIMEOUT_SECONDS")
        self.timeout_seconds = DEFAULT_OLLAMA_TIMEOUT_SECONDS
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
        elif env_timeout:
            try:
                self.timeout_seconds = float(env_timeout)
            except ValueError:
                logger.warning(
                    "Invalid JARVIS_OLLAMA_TIMEOUT_SECONDS=%s, using default %.1fs",
                    env_timeout,
                    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
                )

        self.api_key = api_key or os.environ.get("JARVIS_OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY")
        self.chat_path = os.environ.get("JARVIS_OLLAMA_CHAT_COMPLETIONS_PATH", "/v1/chat/completions")

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> requests.Response:
        return requests.post(
            endpoint,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )

    def _native_payload(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if options:
            payload["options"] = options
        if system:
            payload["system"] = system
        return payload

    def _normalize_openai_response(self, model: str, body: Dict[str, Any], duration_ms: float) -> OllamaChatResult:
        usage = body.get("usage") or {}
        choices = body.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        stop_reason = first_choice.get("finish_reason") or "stop"

        return OllamaChatResult(
            success=True,
            content=str(message.get("content") or ""),
            model=body.get("model") or model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            stop_reason=stop_reason,
            response_id=body.get("id"),
            raw_response=body,
        )

    def _normalize_native_response(self, model: str, body: Dict[str, Any], duration_ms: float) -> OllamaChatResult:
        message = body.get("message") or {}
        prompt_tokens = int(body.get("prompt_eval_count") or 0)
        completion_tokens = int(body.get("eval_count") or 0)
        total_tokens = prompt_tokens + completion_tokens
        stop_reason = body.get("done_reason") or ("stop" if body.get("done") else "unknown")

        return OllamaChatResult(
            success=True,
            content=str(message.get("content") or ""),
            model=body.get("model") or model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            stop_reason=stop_reason,
            response_id=body.get("id"),
            raw_response=body,
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: Optional[int] = 1024,
        temperature: Optional[float] = 0.2,
    ) -> OllamaChatResult:
        """Call Ollama chat completions and normalize response."""

        start = time.time()
        endpoint = f"{self.base_url}{self.chat_path}"

        merged_messages: List[Dict[str, Any]] = []
        if system:
            merged_messages.append({"role": "system", "content": system})

        for message in messages or []:
            merged_messages.append(
                {
                    "role": message.get("role", "user"),
                    "content": message.get("content", ""),
                }
            )

        payload: Dict[str, Any] = {
            "model": model,
            "messages": merged_messages,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        try:
            response = self._post(endpoint, payload)
            if response.status_code == 404 and self.chat_path == "/v1/chat/completions":
                native_endpoint = f"{self.base_url}{DEFAULT_OLLAMA_NATIVE_CHAT_PATH}"
                native_response = self._post(
                    native_endpoint,
                    self._native_payload(model, merged_messages, system, max_tokens, temperature),
                )
                native_response.raise_for_status()
                body = native_response.json()
                return self._normalize_native_response(
                    model=model,
                    body=body,
                    duration_ms=(time.time() - start) * 1000,
                )

            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            return OllamaChatResult(
                success=False,
                content="",
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=(time.time() - start) * 1000,
                stop_reason="error",
                error=f"Ollama request failed: {exc}",
            )
        except ValueError as exc:
            return OllamaChatResult(
                success=False,
                content="",
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=(time.time() - start) * 1000,
                stop_reason="error",
                error=f"Invalid Ollama JSON response: {exc}",
            )

        return self._normalize_openai_response(
            model=model,
            body=body,
            duration_ms=(time.time() - start) * 1000,
        )
