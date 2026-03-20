"""
Email Tools.

Gmail integration for reading and sending emails.
Extracted from tools.py (Phase S2).
"""
from typing import Dict, Any, List
from datetime import datetime
import requests

from ..observability import get_logger, log_with_context, metrics
from ..errors import (
    JarvisException, ErrorCode, wrap_external_error,
    internal_error
)

logger = get_logger("jarvis.tools.email")

import os
N8N_BASE = os.getenv("N8N_BASE", "http://n8n:5678")
N8N_TIMEOUT = int(os.getenv("N8N_TIMEOUT", "60"))


def tool_get_gmail_messages(
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Get recent emails from Projektil Gmail inbox via n8n (live API).

    This fetches live emails, not indexed/searchable content.
    Use search_emails for semantic search in indexed emails.

    Args:
        limit: Number of emails to fetch (1-20)

    Raises:
        JarvisException: On API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: get_gmail_messages", limit=limit)
    metrics.inc("tool_get_gmail_messages")

    try:
        from . import n8n_client

        emails = n8n_client.get_gmail_projektil(limit=min(limit, 20))

        # Check for API-level errors
        if isinstance(emails, dict) and emails.get("error"):
            error_msg = emails.get("error", "Unknown Gmail error")
            raise JarvisException(
                code=ErrorCode.GMAIL_API_ERROR,
                message=f"Failed to fetch emails: {error_msg}",
                status_code=502,
                details={"limit": limit},
                recoverable="timeout" in str(error_msg).lower() or "rate" in str(error_msg).lower(),
                retry_after=30 if "rate" in str(error_msg).lower() else 10,
                hint="Check n8n Gmail configuration or try again"
            )

        formatted = n8n_client.format_emails_for_briefing(emails, max_items=limit)

        return {
            "emails": emails,
            "count": len(emails),
            "formatted": formatted,
            "source": "gmail_api",
            "account": "projektil"
        }
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Get Gmail messages timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Gmail fetch timed out",
            status_code=504,
            details={"limit": limit},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Get Gmail messages failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="gmail")


def tool_send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Send an email via n8n (Projektil Gmail account).

    Note: Only Projektil has Gmail. Visualfox has no Gmail.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)

    Raises:
        JarvisException: On network, auth, or API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: send_email",
                    to=to, subject=subject[:50])
    metrics.inc("tool_send_email")

    try:
        from . import n8n_client

        result = n8n_client.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc
        )

        # Check for API-level errors returned in result dict
        if not result.get("success") and result.get("error"):
            error_msg = result.get("error", "Unknown email error")
            log_with_context(logger, "error", "Send email API error",
                            to=to, error=error_msg)
            raise JarvisException(
                code=ErrorCode.GMAIL_API_ERROR,
                message=f"Failed to send email: {error_msg}",
                status_code=502,
                details={"to": to, "subject": subject[:50]},
                recoverable="timeout" in error_msg.lower() or "rate" in error_msg.lower(),
                retry_after=30 if "rate" in error_msg.lower() else 10,
                hint="Check n8n Gmail configuration or try again later"
            )

        return result

    except JarvisException:
        raise  # Re-raise our own exceptions
    except requests.Timeout as e:
        log_with_context(logger, "error", "Send email timeout", to=to, error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Email send timed out - n8n or Gmail may be slow",
            status_code=504,
            details={"to": to},
            recoverable=True,
            retry_after=30,
            hint="Try again in a moment"
        )
    except requests.RequestException as e:
        log_with_context(logger, "error", "Send email network error", to=to, error=str(e))
        raise JarvisException(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"Email service unavailable: {str(e)[:100]}",
            status_code=503,
            details={"to": to},
            recoverable=True,
            retry_after=30,
            hint="n8n may be down or unreachable"
        )
    except Exception as e:
        log_with_context(logger, "error", "Send email unexpected error", to=to, error=str(e))
        raise wrap_external_error(e, service="send_email")

