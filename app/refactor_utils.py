"""
Refactoring utility for converting generic exception handlers to JarvisException.

This module provides patterns and helpers for systematically refactoring
exception handling across the codebase while minimizing regression risk.

Usage:
    from .refactor_utils import safe_wrap_exception, determine_error_code
    
    try:
        risky_operation()
    except SpecificError as e:
        raise JarvisException(
            code=determine_error_code(type(e).__name__),
            message=f"Operation failed: {str(e)}",
            status_code=500,
            recoverable=True,
            hint=safe_wrap_exception(e)
        )
"""

from typing import Optional, Dict, Type
from .errors import ErrorCode, JarvisException


def determine_error_code(exception_type_name: str, context: Optional[str] = None) -> ErrorCode:
    """
    Map exception type to appropriate ErrorCode.
    
    Args:
        exception_type_name: Name of exception class (e.g., "TimeoutError", "ValueError")
        context: Optional context (e.g., "postgres", "claude", "qdrant")
    
    Returns:
        Best-matching ErrorCode for the exception
    
    Example:
        >>> determine_error_code("TimeoutError")
        ErrorCode.TIMEOUT
        
        >>> determine_error_code("ConnectionError", context="postgres")
        ErrorCode.POSTGRES_UNAVAILABLE
    """
    
    # Timeout errors
    if "Timeout" in exception_type_name or "timeout" in exception_type_name:
        return ErrorCode.TIMEOUT
    
    # Connection/network errors (context-aware)
    if "Connection" in exception_type_name or "Connection" in exception_type_name:
        if context == "postgres":
            return ErrorCode.POSTGRES_UNAVAILABLE
        elif context == "qdrant":
            return ErrorCode.QDRANT_UNAVAILABLE
        else:
            return ErrorCode.SERVICE_UNAVAILABLE
    
    # Database errors
    if "postgres" in exception_type_name.lower():
        return ErrorCode.POSTGRES_ERROR
    
    # Vector database errors
    if "qdrant" in exception_type_name.lower():
        return ErrorCode.QDRANT_ERROR
    
    # API/external service errors
    if "API" in exception_type_name or "api" in exception_type_name:
        if context == "claude":
            return ErrorCode.CLAUDE_ERROR
        elif context == "gmail":
            return ErrorCode.GMAIL_API_ERROR
        elif context == "drive":
            return ErrorCode.DRIVE_API_ERROR
        else:
            return ErrorCode.SERVICE_UNAVAILABLE
    
    # Rate limit errors
    if "Rate" in exception_type_name or "rate" in exception_type_name:
        if context == "claude":
            return ErrorCode.CLAUDE_RATE_LIMIT
        else:
            return ErrorCode.RATE_LIMIT_EXCEEDED
    
    # Validation errors
    if "Validation" in exception_type_name or "Value" in exception_type_name:
        return ErrorCode.VALIDATION_ERROR
    
    # File/upload errors
    if "File" in exception_type_name or "Upload" in exception_type_name:
        return ErrorCode.UPLOAD_FAILED
    
    # Auth errors
    if "Auth" in exception_type_name or "Unauthorized" in exception_type_name:
        return ErrorCode.UNAUTHORIZED
    
    # Fallback
    return ErrorCode.INTERNAL_ERROR


def safe_wrap_exception(exception: Exception) -> str:
    """
    Wrap exception message safely for user-facing hints.
    
    Filters sensitive information and provides actionable guidance.
    
    Args:
        exception: The exception to wrap
    
    Returns:
        Safe, user-friendly error hint
    """
    msg = str(exception).strip()
    
    # Don't expose internal paths or sensitive details
    if "/brain/" in msg or "/root/" in msg or "/home/" in msg:
        return "Database operation failed. Please try again."
    
    if "password" in msg.lower() or "token" in msg.lower() or "key" in msg.lower():
        return "Authentication failed. Please check your credentials."
    
    if "timeout" in msg.lower():
        return "The operation is taking too long. Please try again."
    
    if len(msg) > 100:
        # Truncate very long messages
        return msg[:97] + "..."
    
    return msg


def exception_should_be_retryable(exception_type_name: str, status_code: int) -> bool:
    """
    Determine if an exception should be marked as retryable.
    
    Args:
        exception_type_name: Name of exception class
        status_code: HTTP status code that will be returned
    
    Returns:
        True if client should retry, False if error is permanent
    """
    # 5xx errors are typically retryable
    if status_code >= 500:
        return True
    
    # 4xx errors are typically NOT retryable (except rate limit)
    if 400 <= status_code < 500:
        if status_code == 429:  # Rate limit
            return True
        return False
    
    # Specific exception types that are always retryable
    retryable_exceptions = {
        "TimeoutError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "BrokenPipeError",
        "TemporaryError",
    }
    
    return exception_type_name in retryable_exceptions


def exception_retry_after(exception_type_name: str, context: Optional[str] = None) -> Optional[int]:
    """
    Suggest a retry_after value for the exception.
    
    Args:
        exception_type_name: Name of exception class
        context: Optional context (e.g., "claude", "postgres")
    
    Returns:
        Seconds to wait, or None if not applicable
    """
    
    # External API rate limits
    if "Rate" in exception_type_name:
        if context == "claude":
            return 60
        return 30
    
    # External API overload
    if "Overload" in exception_type_name or "Unavailable" in exception_type_name:
        if context == "claude":
            return 120
        return 30
    
    # Database issues (short retry)
    if context == "postgres":
        return 5
    
    # Default timeout retry
    if "Timeout" in exception_type_name:
        return 5
    
    return None


# ============================================================================
# REFACTORING PATTERNS
# ============================================================================

PATTERN_SIMPLE_RETURN = {
    "before": """
    except Exception as e:
        return {"error": str(e)}
    """,
    "after": """
    except Exception as e:
        logger.exception("Operation failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=500,
            recoverable=False
        )
    """
}

PATTERN_STATUS_RETURN = {
    "before": """
    except Exception as e:
        return {"status": "error", "error": str(e)}
    """,
    "after": """
    except Exception as e:
        logger.exception("Operation failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=500,
            recoverable=False
        )
    """
}

PATTERN_SUCCESS_FALSE = {
    "before": """
    except Exception as e:
        return {"success": False, "error": str(e)}
    """,
    "after": """
    except Exception as e:
        logger.exception("Operation failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=500,
            recoverable=False
        )
    """
}

PATTERN_WITH_TRACEBACK = {
    "before": """
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    """,
    "after": """
    except Exception as e:
        logger.exception("Operation failed with traceback", extra={
            "error_type": type(e).__name__
        })
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=500,
            recoverable=False
        )
    """
}

PATTERN_LOGGER_ONLY = {
    "before": """
    except Exception as e:
        logger.error(f"Failed: {e}")
    """,
    "after": """
    except Exception as e:
        logger.exception("Operation failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=500,
            recoverable=False
        )
    """
}

# ============================================================================
# SAFETY CHECKLIST FOR REFACTORING
# ============================================================================

REFACTORING_CHECKLIST = """
✅ PRE-REFACTOR CHECKLIST (Main.py):

1. Backup current state:
   - Git status clean?
   - Create branch: `git checkout -b refactor/main-jarvisexception`

2. Identify critical API paths:
   - Health endpoint (/health) - MUST work
   - Auth endpoints (/auth/*) - MUST work
   - Core business endpoints - MUST work

3. Categorize exception handlers:
   - Startup errors (initialize) - Log only, no API response
   - Request errors (endpoints) - Return JarvisException
   - Shutdown errors (cleanup) - Log only, no response

4. For each endpoint exception handler:
   - Determine appropriate ErrorCode
   - Identify if retryable
   - Add helpful hint for user

✅ REFACTORING APPROACH:

1. Create feature branch (git)
2. Apply refactoring in PHASES (by endpoint group):
   - Phase 1: Health/status endpoints
   - Phase 2: Auth endpoints
   - Phase 3: Knowledge endpoints
   - Phase 4: Emotions endpoints
   - Phase 5: Workflow endpoints
   - Phase 6: Admin endpoints
3. Build + test after each phase
4. Commit each phase separately (easy rollback)

✅ TESTING:

1. Health check: `curl http://localhost:18000/health`
2. Error test: `curl http://localhost:18000/nonexistent`
3. Invalid input test: `curl -X POST http://localhost:18000/endpoint -d '{invalid}'`
4. Service unavailable: Simulate DB down, check error response

✅ ROLLBACK PLAN:

If major regression:
```bash
git checkout HEAD -- app/main.py
bash ./build-ingestion-fast.sh
```

No data loss, service restarts.
"""

if __name__ == "__main__":
    print(REFACTORING_CHECKLIST)
