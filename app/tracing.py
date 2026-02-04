"""
Phase 2: Distributed Request Tracing & Correlation

Adds distributed tracing support using:
- Request ID: Unique identifier per request
- Trace ID: Distributed trace identifier (for Jaeger)
- Span ID: Individual operation span
- Correlation ID: Links related requests
"""

import uuid
import time
from typing import Dict, Any, Optional
from contextvars import ContextVar
from datetime import datetime, timezone

# Context variables for tracing (thread-safe, async-safe)
request_id_var: ContextVar[str] = ContextVar('request_id', default='unknown')
trace_id_var: ContextVar[str] = ContextVar('trace_id', default='unknown')
span_id_var: ContextVar[str] = ContextVar('span_id', default='unknown')
correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='unknown')
user_id_var: ContextVar[str] = ContextVar('user_id', default='0')

def generate_request_id() -> str:
    """Generate unique request ID (UUID4)"""
    return str(uuid.uuid4())[:8]

def generate_trace_id() -> str:
    """Generate trace ID for distributed tracing (128-bit hex)"""
    return uuid.uuid4().hex

def generate_span_id() -> str:
    """Generate span ID (64-bit hex)"""
    return uuid.uuid4().hex[:16]

def set_request_context(
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    user_id: str = '0'
) -> Dict[str, str]:
    """Set tracing context for current request"""
    
    if not request_id:
        request_id = generate_request_id()
    if not trace_id:
        trace_id = generate_trace_id()
    if not span_id:
        span_id = generate_span_id()
    if not correlation_id:
        correlation_id = request_id
    
    request_id_var.set(request_id)
    trace_id_var.set(trace_id)
    span_id_var.set(span_id)
    correlation_id_var.set(correlation_id)
    user_id_var.set(user_id)
    
    return {
        'request_id': request_id,
        'trace_id': trace_id,
        'span_id': span_id,
        'correlation_id': correlation_id,
        'user_id': user_id,
    }

def get_trace_context() -> Dict[str, str]:
    """Get current tracing context"""
    return {
        'request_id': request_id_var.get(),
        'trace_id': trace_id_var.get(),
        'span_id': span_id_var.get(),
        'correlation_id': correlation_id_var.get(),
        'user_id': user_id_var.get(),
    }

def get_trace_headers() -> Dict[str, str]:
    """Get headers for propagating trace to downstream services"""
    ctx = get_trace_context()
    return {
        'X-Request-ID': ctx['request_id'],
        'X-Trace-ID': ctx['trace_id'],
        'X-Span-ID': ctx['span_id'],
        'X-Correlation-ID': ctx['correlation_id'],
        'X-User-ID': ctx['user_id'],
    }

class TraceContext:
    """Context manager for tracing a span"""
    
    def __init__(self, operation_name: str, attributes: Optional[Dict[str, Any]] = None):
        self.operation_name = operation_name
        self.attributes = attributes or {}
        self.start_time = None
        self.end_time = None
        self.parent_span_id = None
    
    def __enter__(self):
        self.parent_span_id = span_id_var.get()
        self.start_time = time.time()
        span_id_var.set(generate_span_id())
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        duration_ms = (self.end_time - self.start_time) * 1000
        
        # Would send to Jaeger here
        span_id_var.set(self.parent_span_id)
        
        return False  # Don't suppress exceptions
    
    def get_duration_ms(self) -> float:
        """Get span duration in milliseconds"""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

def format_trace_context() -> Dict[str, Any]:
    """Format trace context as JSON for logging"""
    ctx = get_trace_context()
    return {
        'request_id': ctx['request_id'],
        'trace_id': ctx['trace_id'],
        'span_id': ctx['span_id'],
        'correlation_id': ctx['correlation_id'],
        'user_id': ctx['user_id'],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

# FastAPI Middleware Integration (use in main.py)
async def add_tracing_middleware(app):
    """Add tracing middleware to FastAPI app"""
    from fastapi import Request, Response
    from fastapi.middleware.base import BaseHTTPMiddleware
    
    class TracingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            # Extract trace context from headers or generate new
            trace_id = request.headers.get('X-Trace-ID', generate_trace_id())
            request_id = request.headers.get('X-Request-ID', generate_request_id())
            correlation_id = request.headers.get('X-Correlation-ID', request_id)
            user_id = request.headers.get('X-User-ID', '0')
            
            # Set context
            set_request_context(
                request_id=request_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                user_id=user_id,
            )
            
            # Add to request state for downstream use
            request.state.request_id = request_id
            request.state.trace_id = trace_id
            request.state.correlation_id = correlation_id
            request.state.user_id = user_id
            
            # Process request
            start_time = time.time()
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            
            # Add trace headers to response
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Trace-ID'] = trace_id
            response.headers['X-Correlation-ID'] = correlation_id
            
            return response
    
    app.add_middleware(TracingMiddleware)


def get_current_user_id() -> str:
    """
    Get the current user_id from context.
    
    Returns the user_id from the current request context, defaulting to '0'
    if not set. This replaces hardcoded user_id values and ensures consistent
    multi-user support across the application.
    
    Usage:
        user_id = get_current_user_id()
        result = some_function(user_id=user_id)
    
    Returns:
        str: Current user_id from context, or '0' if not available
    """
    return user_id_var.get()
