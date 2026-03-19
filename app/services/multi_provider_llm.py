"""
Multi-Provider LLM Client.

Supports OpenAI, Anthropic, and Ollama models with a unified interface.

O2 Migration: OpenAI uses Responses API for server-side caching.
"""

import os
import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str
    raw_response: Any = None
    response_id: Optional[str] = None  # O2: OpenAI Responses API ID for multi-turn


class MultiProviderLLM:
    """
    Unified interface for calling OpenAI, Anthropic, and Ollama models.
    """

    def __init__(self):
        self._openai_client = None
        self._anthropic_client = None
        self._ollama_client = None

    def _get_openai_client(self):
        """Lazy initialization of OpenAI client."""
        if self._openai_client is None:
            try:
                from openai import OpenAI
                api_key = os.environ.get('OPENAI_API_KEY')
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not set")
                self._openai_client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai")
        return self._openai_client

    def _get_anthropic_client(self):
        """Lazy initialization of Anthropic client."""
        if self._anthropic_client is None:
            try:
                import anthropic
                api_key = os.environ.get('ANTHROPIC_API_KEY')
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._anthropic_client

    def _get_ollama_client(self) -> OllamaClient:
        """Lazy initialization of Ollama client."""
        if self._ollama_client is None:
            self._ollama_client = OllamaClient()
        return self._ollama_client

    def chat(
        self,
        model: str,
        provider: Provider,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None,
        previous_response_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Send a chat request to the specified model.

        Args:
            model: Model ID (e.g., 'gpt-4o-mini', 'claude-sonnet-4-20250514')
            provider: Provider enum (OPENAI, ANTHROPIC, or OLLAMA)
            messages: List of message dicts with 'role' and 'content'
            system: System prompt (optional)
            max_tokens: Maximum output tokens
            temperature: Sampling temperature
            tools: Tool definitions (optional)
            previous_response_id: O2 - OpenAI Responses API chain ID for multi-turn

        Returns:
            LLMResponse with unified format (includes response_id for OpenAI)
        """
        start_time = time.time()

        if provider == Provider.OPENAI:
            response = self._call_openai(
                model, messages, system, max_tokens, temperature, tools,
                previous_response_id=previous_response_id
            )
        elif provider == Provider.ANTHROPIC:
            response = self._call_anthropic(model, messages, system, max_tokens, temperature, tools)
        elif provider == Provider.OLLAMA:
            response = self._call_ollama(model, messages, system, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        response.latency_ms = int((time.time() - start_time) * 1000)
        return response

    def _call_openai(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[Dict]],
        previous_response_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Call OpenAI Responses API (O2 Migration).

        Uses Responses API for server-side caching and multi-turn chaining.
        """
        client = self._get_openai_client()

        # Build input messages for Responses API
        input_messages = []

        # Add system message as developer role
        if system:
            input_messages.append({"role": "developer", "content": system})

        # Convert messages to Responses API format
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')

            # Handle different content formats
            if isinstance(content, list):
                # Multi-part content (text + images)
                parts = []
                for part in content:
                    if part.get('type') == 'text':
                        parts.append({"type": "input_text", "text": part.get('text', '')})
                    elif part.get('type') == 'image':
                        parts.append({
                            "type": "input_image",
                            "image_url": part.get('source', {}).get('data', '')
                        })
                input_messages.append({"role": role, "content": parts})
            else:
                input_messages.append({"role": role, "content": str(content)})

        # Build Responses API kwargs
        kwargs = {
            "model": model,
            "input": input_messages,
            "store": True,  # O2: Enable server-side caching
        }

        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens

        # O2: Chain to previous response
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
            logger.debug(f"Using previous_response_id: {previous_response_id[:20]}...")

        # Add tools if provided
        if tools:
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "name": tool.get('name'),
                    "description": tool.get('description', ''),
                    "parameters": tool.get('input_schema', {}),
                })
            kwargs["tools"] = openai_tools

        # Make the Responses API call
        response = client.responses.create(**kwargs)

        # Extract content from Responses API format
        content = ""
        saw_function_call = False

        # Handle output_text (simple text response)
        if hasattr(response, 'output_text') and response.output_text:
            content = response.output_text

        # Handle output array (structured response with potential tool calls)
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'type'):
                    if item.type == "message":
                        if hasattr(item, 'content'):
                            for c in item.content:
                                if hasattr(c, 'type') and c.type == "output_text":
                                    if hasattr(c, 'text'):
                                        content = c.text
                                        break
                    elif item.type == "function_call":
                        import json
                        saw_function_call = True
                        content = {
                            "tool_calls": [{
                                "id": item.call_id if hasattr(item, 'call_id') else item.id,
                                "name": item.name,
                                "arguments": item.arguments if isinstance(item.arguments, str) else json.dumps(item.arguments),
                            }]
                        }
                        break

        # Extract usage
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, 'usage'):
            input_tokens = getattr(response.usage, 'input_tokens', 0)
            output_tokens = getattr(response.usage, 'output_tokens', 0)

        # Map status to stop_reason
        status = getattr(response, 'status', 'completed')
        stop_reason_map = {
            "completed": "stop",
            "incomplete": "length",
        }
        stop_reason = "tool_use" if saw_function_call else stop_reason_map.get(status, status)

        return LLMResponse(
            content=content,
            model=model,
            provider="openai",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=0,  # Will be set by caller
            stop_reason=stop_reason,
            raw_response=response,
            response_id=response.id,  # O2: Return for multi-turn chaining
        )

    def _call_anthropic(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[Dict]],
        enable_prompt_cache: bool = True,
    ) -> LLMResponse:
        """
        Call Anthropic API with prompt caching (O3).

        O3 Prompt Caching:
        - Converts system prompt to cached content blocks
        - Saves up to 90% on input costs for repeated prompts
        - 5-minute cache TTL on Anthropic's side
        """
        client = self._get_anthropic_client()

        # Build API call kwargs
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # O3: Build cached system prompt
        if system:
            if enable_prompt_cache:
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            else:
                kwargs["system"] = system

        # Only set temperature for non-o1 models (Anthropic doesn't use temp for some models)
        if temperature is not None and temperature != 1.0:
            kwargs["temperature"] = temperature

        # Add tools if provided
        if tools:
            kwargs["tools"] = tools

        # Make the call
        response = client.messages.create(**kwargs)

        # O3: Log cache stats if available
        if hasattr(response.usage, 'cache_creation_input_tokens'):
            cache_created = getattr(response.usage, 'cache_creation_input_tokens', 0)
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            if cache_created > 0 or cache_read > 0:
                logger.debug(f"Anthropic cache stats: created={cache_created}, read={cache_read}")

        # Extract content
        content = ""
        for block in response.content:
            if block.type == "text":
                content = block.text
                break
            elif block.type == "tool_use":
                content = {
                    "tool_calls": [{
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    }]
                }
                break

        return LLMResponse(
            content=content,
            model=model,
            provider="anthropic",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=0,  # Will be set by caller
            stop_reason=response.stop_reason,
            raw_response=response,
        )

    def _call_ollama(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call local/remote Ollama using OpenAI-compatible API."""
        client = self._get_ollama_client()
        result = client.chat(
            model=model,
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if not result.success:
            raise RuntimeError(result.error or "Ollama request failed")

        return LLMResponse(
            content=result.content,
            model=result.model,
            provider="ollama",
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            latency_ms=int(result.duration_ms),
            stop_reason=result.stop_reason,
            raw_response=result.raw_response,
            response_id=result.response_id,
        )


# Singleton instance
_llm: Optional[MultiProviderLLM] = None


def get_multi_provider_llm() -> MultiProviderLLM:
    """Get or create the multi-provider LLM singleton."""
    global _llm
    if _llm is None:
        _llm = MultiProviderLLM()
    return _llm
