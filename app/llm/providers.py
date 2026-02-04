"""
Abstract LLM Provider Interface

Enables multi-provider support (Anthropic, OpenAI, etc.)
with unified interface for routing and cost calculation.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import os


@dataclass
class ModelConfig:
    """Configuration for an LLM model"""
    model_name: str
    provider: str  # 'anthropic' or 'openai'
    max_tokens: int
    timeout: int  # seconds
    temperature: float = 0.7
    top_p: float = 1.0
    input_cost_per_1m: float = 0.0  # USD
    output_cost_per_1m: float = 0.0  # USD


class LLMProvider(ABC):
    """Abstract base for LLM providers"""
    
    provider_name: str
    
    @abstractmethod
    def call(
        self,
        messages: List[Dict[str, str]],
        system: str,
        model: str,
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs
    ) -> tuple[str, Dict[str, Any]]:
        """
        Call LLM with messages
        
        Returns:
            (response_text, usage_dict with input_tokens, output_tokens)
        """
        pass
    
    @abstractmethod
    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """Calculate cost in USD"""
        pass
    
    @abstractmethod
    def get_api_key(self) -> str:
        """Get API key from env or secrets file"""
        pass
    
    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Quick health check of provider"""
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider"""
    
    provider_name = "anthropic"
    
    # Pricing per 1M tokens (as of Feb 2026)
    MODEL_COSTS = {
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        "claude-3-5-haiku-20250110": {"input": 0.80, "output": 4.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    }
    
    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=self.get_api_key())
    
    def get_api_key(self) -> str:
        """Load Anthropic API key from env or secrets"""
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
        
        secrets_path = "/brain/system/secrets/anthropic_api_key.txt"
        if os.path.exists(secrets_path):
            with open(secrets_path) as f:
                return f.read().strip()
        
        raise ValueError("ANTHROPIC_API_KEY not configured")
    
    def call(
        self,
        messages: List[Dict[str, str]],
        system: str,
        model: str,
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs
    ) -> tuple[str, Dict[str, Any]]:
        """Call Claude API"""
        timeout = kwargs.get("timeout")
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
                timeout=timeout,
            )
        except TypeError:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )
        
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        
        return text, usage
    
    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """Calculate cost in USD for Claude model"""
        costs = self.MODEL_COSTS.get(model, self.MODEL_COSTS.get("claude-3-5-sonnet-20241022"))
        
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        
        return input_cost + output_cost
    
    def health_check(self) -> Dict[str, Any]:
        """Check if Anthropic API is accessible"""
        try:
            # Just verify we have the key
            api_key = self.get_api_key()
            return {
                "status": "healthy",
                "provider": "anthropic",
                "configured": bool(api_key),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": "anthropic",
                "error": str(e),
            }


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""
    
    provider_name = "openai"
    
    # Pricing per 1M tokens (as of Feb 2026)
    MODEL_COSTS = {
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    }
    
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=self.get_api_key())
    
    def get_api_key(self) -> str:
        """Load OpenAI API key from env or secrets"""
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return key
        
        secrets_path = "/brain/system/secrets/openai_api_key.txt"
        if os.path.exists(secrets_path):
            with open(secrets_path) as f:
                return f.read().strip()
        
        raise ValueError("OPENAI_API_KEY not configured")
    
    def call(
        self,
        messages: List[Dict[str, str]],
        system: str,
        model: str,
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs
    ) -> tuple[str, Dict[str, Any]]:
        """Call OpenAI API"""
        # Prepend system message
        all_messages = [{"role": "system", "content": system}] + messages

        timeout = kwargs.get("timeout")
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        except TypeError:
            response = self.client.chat.completions.create(
                model=model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        
        text = response.choices[0].message.content
        
        usage = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        }
        
        return text, usage
    
    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """Calculate cost in USD for GPT model"""
        costs = self.MODEL_COSTS.get(model, self.MODEL_COSTS.get("gpt-4-turbo"))
        
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        
        return input_cost + output_cost
    
    def health_check(self) -> Dict[str, Any]:
        """Check if OpenAI API is accessible"""
        try:
            api_key = self.get_api_key()
            return {
                "status": "healthy",
                "provider": "openai",
                "configured": bool(api_key),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": "openai",
                "error": str(e),
            }


# ============ Provider Registry ============

_providers = {}

def get_provider(provider_name: str) -> LLMProvider:
    """Get or create provider instance"""
    global _providers
    
    if provider_name not in _providers:
        if provider_name == "anthropic":
            _providers[provider_name] = AnthropicProvider()
        elif provider_name == "openai":
            _providers[provider_name] = OpenAIProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")
    
    return _providers[provider_name]


def get_all_providers() -> List[LLMProvider]:
    """Get all configured providers"""
    providers = []
    
    for name in ["anthropic", "openai"]:
        try:
            providers.append(get_provider(name))
        except ValueError:
            # Provider not configured
            pass
    
    return providers
