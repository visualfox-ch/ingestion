"""
Error Code System for Jarvis
Structured error codes for better debugging
"""

from enum import Enum
from typing import Dict, Any, Optional
import traceback
import uuid
from datetime import datetime

class ErrorCategory(Enum):
    """Error categories with prefixes"""
    QDRANT = "QDR"  # Qdrant vector DB errors
    POSTGRES = "PG"   # PostgreSQL errors
    MEILISEARCH = "MS"  # Meilisearch errors
    N8N = "N8N"  # n8n workflow errors
    SSH = "SSH"  # SSH connection errors
    TELEGRAM = "TG"   # Telegram bot errors
    LLM = "LLM"  # Claude/OpenAI API errors
    AUTH = "AUTH"  # Authentication errors
    VALIDATION = "VAL"  # Input validation errors
    SYSTEM = "SYS"  # System/internal errors

class ErrorCode:
    """Structured error with ID and details"""
    
    def __init__(self, 
                 category: ErrorCategory,
                 code: str,
                 message: str,
                 details: Optional[Dict[str, Any]] = None,
                 original_error: Optional[Exception] = None):
        self.id = f"{category.value}_{code}_{uuid.uuid4().hex[:6]}"
        self.category = category
        self.code = code
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()
        self.original_error = original_error
        
        if original_error:
            self.details["original_error"] = str(original_error)
            self.details["traceback"] = traceback.format_exc()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response"""
        return {
            "error_id": self.id,
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "help": self.get_help_message()
        }
    
    def get_help_message(self) -> str:
        """Get actionable help for this error"""
        help_messages = {
            # Qdrant errors
            "QDR_CONNECTION": "Check if Qdrant is running: docker ps | grep qdrant",
            "QDR_TIMEOUT": "Qdrant is slow. Check: docker logs jarvis-qdrant",
            "QDR_COLLECTION": "Collection missing. Run: /admin/init-collections",
            
            # Postgres errors
            "PG_CONNECTION": "Check if Postgres is running: docker ps | grep postgres",
            "PG_QUERY": "SQL error. Check query syntax and table schema",
            
            # SSH errors
            "SSH_CONNECTION": "Check SSH key permissions: chmod 600 /brain/system/keys/*",
            "SSH_AUTH": "SSH auth failed. Check username and key path",
            "SSH_TIMEOUT": "NAS not responding. Check network and SSH service",
            
            # n8n errors
            "N8N_API_KEY": "Invalid n8n API key. Regenerate in n8n UI settings",
            "N8N_CONNECTION": "Can't reach n8n. Check: docker ps | grep n8n",
            
            # LLM errors
            "LLM_RATE_LIMIT": "Claude rate limit. Wait a minute or check API key",
            "LLM_TIMEOUT": "LLM request timed out. Try shorter query",
            
            # System errors
            "SYS_MEMORY": "Out of memory. Check: docker stats",
            "SYS_DISK": "Disk full. Check: df -h"
        }
        
        error_key = f"{self.category.value}_{self.code}"
        return help_messages.get(error_key, f"Check logs for error ID: {self.id}")

# Pre-defined error codes
class ErrorCodes:
    """Common error code definitions"""
    
    # Qdrant errors
    QDRANT_CONNECTION = lambda e=None: ErrorCode(
        ErrorCategory.QDRANT, "CONNECTION", 
        "Failed to connect to Qdrant", original_error=e
    )
    
    QDRANT_TIMEOUT = lambda timeout=30: ErrorCode(
        ErrorCategory.QDRANT, "TIMEOUT",
        f"Qdrant query timed out after {timeout}s",
        {"timeout_seconds": timeout}
    )
    
    QDRANT_COLLECTION_NOT_FOUND = lambda name: ErrorCode(
        ErrorCategory.QDRANT, "COLLECTION",
        f"Collection '{name}' not found",
        {"collection": name}
    )
    
    # SSH errors
    SSH_CONNECTION_FAILED = lambda host, e=None: ErrorCode(
        ErrorCategory.SSH, "CONNECTION",
        f"SSH connection to {host} failed",
        {"host": host}, original_error=e
    )
    
    SSH_AUTH_FAILED = lambda user: ErrorCode(
        ErrorCategory.SSH, "AUTH",
        f"SSH authentication failed for user {user}",
        {"user": user}
    )
    
    # n8n errors
    N8N_API_ERROR = lambda status, e=None: ErrorCode(
        ErrorCategory.N8N, "API_ERROR",
        f"n8n API returned status {status}",
        {"status_code": status}, original_error=e
    )
    
    # LLM errors
    LLM_RATE_LIMITED = lambda retry_after=60: ErrorCode(
        ErrorCategory.LLM, "RATE_LIMIT",
        "Claude API rate limit exceeded",
        {"retry_after_seconds": retry_after}
    )
    
    # Validation errors
    VALIDATION_REQUIRED_FIELD = lambda field: ErrorCode(
        ErrorCategory.VALIDATION, "REQUIRED",
        f"Required field '{field}' is missing",
        {"field": field}
    )
    
    # System errors
    SYSTEM_OUT_OF_MEMORY = lambda used, total: ErrorCode(
        ErrorCategory.SYSTEM, "MEMORY",
        f"Out of memory: {used}GB/{total}GB used",
        {"memory_used_gb": used, "memory_total_gb": total}
    )