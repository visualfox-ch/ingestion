"""
API Authentication for Jarvis

Simple API-Key based authentication with logging for failed attempts.
"""
import secrets
from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader
from typing import Optional
from datetime import datetime

from . import config
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.auth")

# API Key header scheme
api_key_header = APIKeyHeader(name=config.API_KEY_HEADER, auto_error=False)


def is_public_endpoint(path: str) -> bool:
    """Check if the endpoint is public (no auth required)."""
    for public_path in config.PUBLIC_ENDPOINTS:
        if path == public_path or path.startswith(public_path + "/"):
            return True
    return False


def is_auth_enabled() -> bool:
    """Check if authentication is enabled (API key is configured)."""
    return bool(config.API_KEY) and len(config.API_KEY) >= config.API_KEY_MIN_LENGTH


def validate_api_key(api_key: Optional[str], request: Request) -> bool:
    """
    Validate the provided API key.

    Returns True if valid, raises HTTPException if invalid.
    """
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    # If auth is not enabled, allow all requests
    if not is_auth_enabled():
        return True

    # Public endpoints don't need auth
    if is_public_endpoint(path):
        return True

    # No key provided
    if not api_key:
        log_with_context(
            logger, "warning", "Auth failed: No API key provided",
            client_ip=client_ip,
            path=path,
            timestamp=datetime.now().isoformat()
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"}
        )

    # Invalid key (constant-time comparison to prevent timing attacks)
    if not secrets.compare_digest(api_key, config.API_KEY):
        log_with_context(
            logger, "warning", "Auth failed: Invalid API key",
            client_ip=client_ip,
            path=path,
            key_prefix=api_key[:8] + "..." if len(api_key) > 8 else "***",
            timestamp=datetime.now().isoformat()
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return True


async def auth_dependency(request: Request, api_key: Optional[str] = None):
    """
    FastAPI dependency for API key authentication.

    Usage:
        @app.get("/endpoint")
        def endpoint(auth: bool = Depends(auth_dependency)):
            ...
    """
    # Get API key from header only (query-param auth removed for security)
    if api_key is None:
        api_key = request.headers.get(config.API_KEY_HEADER)

    return validate_api_key(api_key, request)


def get_auth_status() -> dict:
    """Get current authentication configuration status."""
    return {
        "enabled": is_auth_enabled(),
        "key_configured": bool(config.API_KEY),
        "key_length_valid": len(config.API_KEY) >= config.API_KEY_MIN_LENGTH if config.API_KEY else False,
        "min_key_length": config.API_KEY_MIN_LENGTH,
        "public_endpoints": config.PUBLIC_ENDPOINTS,
        "header_name": config.API_KEY_HEADER
    }
