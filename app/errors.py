"""
Structured error responses for Jarvis API.

Provides consistent error format across all endpoints with:
- Error codes for programmatic handling
- Human-readable messages
- Debug details when appropriate
- Recovery hints
"""
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from enum import Enum
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.errors")


class ErrorCode(str, Enum):
    """Standard error codes for Jarvis API."""

    # Client errors (4xx)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    BAD_REQUEST = "BAD_REQUEST"
    DUPLICATE_UPLOAD = "DUPLICATE_UPLOAD"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"

    # Service errors (5xx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    QDRANT_UNAVAILABLE = "QDRANT_UNAVAILABLE"
    QDRANT_ERROR = "QDRANT_ERROR"
    POSTGRES_UNAVAILABLE = "POSTGRES_UNAVAILABLE"
    POSTGRES_ERROR = "POSTGRES_ERROR"
    CLAUDE_ERROR = "CLAUDE_ERROR"
    CLAUDE_RATE_LIMIT = "CLAUDE_RATE_LIMIT"
    CLAUDE_OVERLOADED = "CLAUDE_OVERLOADED"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    GMAIL_AUTH_ERROR = "GMAIL_AUTH_ERROR"
    GMAIL_API_ERROR = "GMAIL_API_ERROR"
    DRIVE_AUTH_ERROR = "DRIVE_AUTH_ERROR"
    DRIVE_API_ERROR = "DRIVE_API_ERROR"
    CALENDAR_AUTH_ERROR = "CALENDAR_AUTH_ERROR"
    CALENDAR_API_ERROR = "CALENDAR_API_ERROR"
    TELEGRAM_ERROR = "TELEGRAM_ERROR"
    SCHEDULER_ERROR = "SCHEDULER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"

    # Upload/Processing errors
    UPLOAD_FAILED = "UPLOAD_FAILED"
    PARSE_ERROR = "PARSE_ERROR"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    PROFILE_EXTRACTION_FAILED = "PROFILE_EXTRACTION_FAILED"


@dataclass
class JarvisError:
    """
    Structured error response.

    Attributes:
        code: Machine-readable error code
        message: Human-readable error message
        details: Additional context (optional)
        recoverable: Whether the client can retry
        retry_after: Seconds to wait before retrying (if applicable)
        hint: Suggestion for resolving the error
    """
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None
    recoverable: bool = False
    retry_after: Optional[int] = None
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        result = {
            "error": True,
            "code": self.code.value if isinstance(self.code, ErrorCode) else self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.details:
            result["details"] = self.details
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        if self.hint:
            result["hint"] = self.hint
        return result


class JarvisException(Exception):
    """
    Custom exception that carries structured error info.

    Use this to raise errors that will be converted to structured responses.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
        retry_after: Optional[int] = None,
        hint: Optional[str] = None,
    ):
        self.error = JarvisError(
            code=code,
            message=message,
            details=details,
            recoverable=recoverable,
            retry_after=retry_after,
            hint=hint,
        )
        self.status_code = status_code
        super().__init__(message)


# ============ Pre-built error factories ============

def qdrant_unavailable(details: Optional[Dict] = None) -> JarvisException:
    """Qdrant vector database is not reachable."""
    return JarvisException(
        code=ErrorCode.QDRANT_UNAVAILABLE,
        message="Vector database is temporarily unavailable",
        status_code=503,
        details=details,
        recoverable=True,
        retry_after=30,
        hint="The system will automatically retry. If this persists, check Qdrant container status."
    )


def postgres_unavailable(details: Optional[Dict] = None) -> JarvisException:
    """Postgres database is not reachable."""
    return JarvisException(
        code=ErrorCode.POSTGRES_UNAVAILABLE,
        message="Knowledge database is temporarily unavailable",
        status_code=503,
        details=details,
        recoverable=True,
        retry_after=30,
        hint="The system will automatically retry. If this persists, check Postgres container status."
    )


def claude_rate_limit(retry_after: int = 60) -> JarvisException:
    """Claude API rate limit exceeded."""
    return JarvisException(
        code=ErrorCode.CLAUDE_RATE_LIMIT,
        message="AI service rate limit exceeded",
        status_code=429,
        recoverable=True,
        retry_after=retry_after,
        hint="Wait a moment before sending another request."
    )


def claude_overloaded(retry_after: int = 120) -> JarvisException:
    """Claude API is overloaded."""
    return JarvisException(
        code=ErrorCode.CLAUDE_OVERLOADED,
        message="AI service is temporarily overloaded",
        status_code=503,
        recoverable=True,
        retry_after=retry_after,
        hint="The AI service is experiencing high demand. Please try again shortly."
    )


def claude_error(message: str, details: Optional[Dict] = None) -> JarvisException:
    """Generic Claude API error."""
    return JarvisException(
        code=ErrorCode.CLAUDE_ERROR,
        message=f"AI service error: {message}",
        status_code=502,
        details=details,
        recoverable=True,
        retry_after=10,
    )


def gmail_auth_error(details: Optional[Dict] = None) -> JarvisException:
    """Gmail OAuth authentication failed."""
    return JarvisException(
        code=ErrorCode.GMAIL_AUTH_ERROR,
        message="Gmail authentication failed - token may need refresh",
        status_code=401,
        details=details,
        recoverable=False,
        hint="Re-authenticate with Gmail by refreshing the OAuth token."
    )


def not_found(resource: str, identifier: str) -> JarvisException:
    """Resource not found."""
    return JarvisException(
        code=ErrorCode.NOT_FOUND,
        message=f"{resource} not found: {identifier}",
        status_code=404,
        details={"resource": resource, "identifier": identifier},
        recoverable=False,
    )


def validation_error(message: str, details: Optional[Dict] = None) -> JarvisException:
    """Request validation failed."""
    return JarvisException(
        code=ErrorCode.VALIDATION_ERROR,
        message=message,
        status_code=400,
        details=details,
        recoverable=False,
        hint="Check the request parameters and try again."
    )


def upload_failed(message: str, details: Optional[Dict] = None) -> JarvisException:
    """File upload failed."""
    return JarvisException(
        code=ErrorCode.UPLOAD_FAILED,
        message=message,
        status_code=500,
        details=details,
        recoverable=True,
        retry_after=10,
        hint="Try uploading the file again."
    )


def parse_error(message: str, details: Optional[Dict] = None) -> JarvisException:
    """File parsing failed."""
    return JarvisException(
        code=ErrorCode.PARSE_ERROR,
        message=message,
        status_code=400,
        details=details,
        recoverable=False,
        hint="Ensure the file format matches the specified source_type."
    )


def processing_failed(message: str, details: Optional[Dict] = None) -> JarvisException:
    """File processing failed."""
    return JarvisException(
        code=ErrorCode.PROCESSING_FAILED,
        message=message,
        status_code=500,
        details=details,
        recoverable=True,
        retry_after=30,
        hint="Processing will be retried automatically. Check the processing log for details."
    )


def profile_extraction_failed(message: str, details: Optional[Dict] = None) -> JarvisException:
    """Profile extraction from messages failed."""
    return JarvisException(
        code=ErrorCode.PROFILE_EXTRACTION_FAILED,
        message=message,
        status_code=500,
        details=details,
        recoverable=True,
        retry_after=60,
        hint="Profile extraction uses AI and may fail due to rate limits. Try again later."
    )


def internal_error(message: str = "An unexpected error occurred", details: Optional[Dict] = None) -> JarvisException:
    """Generic internal error."""
    return JarvisException(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        status_code=500,
        details=details,
        recoverable=True,
        retry_after=10,
    )


# ============ FastAPI Exception Handlers ============

async def jarvis_exception_handler(request: Request, exc: JarvisException) -> JSONResponse:
    """Handle JarvisException and return structured response."""
    log_with_context(
        logger, "warning", "JarvisException raised",
        code=exc.error.code.value if isinstance(exc.error.code, ErrorCode) else exc.error.code,
        message=exc.error.message,
        path=request.url.path,
        status_code=exc.status_code
    )

    headers = {}
    if exc.error.retry_after:
        headers["Retry-After"] = str(exc.error.retry_after)

    return JSONResponse(
        status_code=exc.status_code,
        content=exc.error.to_dict(),
        headers=headers
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors with structured response."""
    errors = exc.errors()

    # Extract field names and messages
    field_errors = []
    for err in errors:
        loc = ".".join(str(l) for l in err.get("loc", []))
        field_errors.append({
            "field": loc,
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "unknown")
        })

    error = JarvisError(
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed",
        details={"errors": field_errors},
        recoverable=False,
        hint="Check the request body/parameters against the API schema."
    )

    log_with_context(
        logger, "warning", "Validation error",
        path=request.url.path,
        errors=len(field_errors)
    )

    return JSONResponse(
        status_code=422,
        content=error.to_dict()
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with structured response."""
    log_with_context(
        logger, "error", "Unhandled exception",
        path=request.url.path,
        error_type=type(exc).__name__,
        error=str(exc)
    )

    # Don't expose internal details in production
    error = JarvisError(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred",
        details={"type": type(exc).__name__} if str(exc) else None,
        recoverable=True,
        retry_after=10,
    )

    return JSONResponse(
        status_code=500,
        content=error.to_dict()
    )


def register_exception_handlers(app):
    """Register all exception handlers with the FastAPI app."""
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(JarvisException, jarvis_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Note: Generic handler catches too much, only enable in production
    # app.add_exception_handler(Exception, generic_exception_handler)


# ============ Helper for wrapping existing errors ============

def wrap_external_error(exc: Exception, service: str = "external") -> JarvisException:
    """
    Wrap an external service exception into a JarvisException.

    Detects common error patterns and returns appropriate structured errors.
    """
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__

    # Qdrant errors
    if "qdrant" in exc_type.lower() or "qdrant" in exc_str:
        if "timeout" in exc_str or "connect" in exc_str:
            return qdrant_unavailable({"original_error": str(exc)})
        return JarvisException(
            code=ErrorCode.QDRANT_ERROR,
            message=f"Vector database error: {str(exc)[:100]}",
            status_code=502,
            recoverable=True,
            retry_after=10
        )

    # Anthropic/Claude errors
    if "anthropic" in exc_type.lower() or "claude" in exc_str:
        if "rate" in exc_str and "limit" in exc_str:
            return claude_rate_limit()
        if "overload" in exc_str:
            return claude_overloaded()
        return claude_error(str(exc)[:100])

    # PostgreSQL errors
    if "psycopg" in exc_type.lower() or "postgres" in exc_str:
        if "connect" in exc_str or "timeout" in exc_str:
            return postgres_unavailable({"original_error": str(exc)})
        return JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message=f"Database error: {str(exc)[:100]}",
            status_code=502,
            recoverable=True,
            retry_after=10
        )

    # Google API errors
    if "google" in exc_type.lower() or "google" in exc_str:
        if "auth" in exc_str or "credential" in exc_str or "token" in exc_str:
            return gmail_auth_error({"original_error": str(exc)})
        return JarvisException(
            code=ErrorCode.GMAIL_API_ERROR,
            message=f"Google API error: {str(exc)[:100]}",
            status_code=502,
            recoverable=True,
            retry_after=30
        )

    # Timeout errors
    if "timeout" in exc_str or "timed out" in exc_str:
        return JarvisException(
            code=ErrorCode.TIMEOUT,
            message=f"Operation timed out: {service}",
            status_code=504,
            recoverable=True,
            retry_after=30
        )

    # Default: internal error
    return internal_error(
        message=f"Service error ({service}): {str(exc)[:100]}",
        details={"service": service, "error_type": exc_type}
    )
