"""Ollama proxy endpoints for controlled local model access."""

from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import auth_dependency
from ..services.ollama_client import OllamaClient

router = APIRouter(prefix="/llm/ollama", tags=["llm", "ollama"])


class OllamaChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Ollama model id")
    messages: List[Dict[str, Any]] = Field(..., description="OpenAI-style chat message array")
    system: Optional[str] = Field(default=None, description="Optional system instruction")
    max_tokens: int = Field(default=1024, ge=1, le=16384)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


@router.post("/chat/completions")
async def create_ollama_chat_completion(
    req: OllamaChatCompletionRequest,
    auth: bool = Depends(auth_dependency),
):
    """Proxy OpenAI-compatible chat completion requests to Ollama."""
    del auth  # Auth is enforced by dependency.

    client = OllamaClient()
    result = client.chat(
        model=req.model,
        messages=req.messages,
        system=req.system,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "Ollama request failed")

    return {
        "id": result.response_id or f"chatcmpl-{uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": result.model,
        "provider": "ollama",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": result.stop_reason,
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
        "latency_ms": round(result.duration_ms, 2),
    }
