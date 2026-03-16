"""
Models subpackage: LLM provider clients, routing infrastructure, and shared data models.

T-005 Implementation.

Components:
- circuit_breaker: Provider failover logic
- scope_ref: ScopeRef model (replaces legacy namespace strings)
"""
from .circuit_breaker import CircuitBreaker, CircuitState
from typing import Optional
from pydantic import BaseModel

# ============ Namespace → Scope mapping (shared across modules) ============

# Backward-compatibility mapping: legacy namespace string → (org, visibility)
_NAMESPACE_TO_SCOPE = {
    "private":        ("personal",  "private"),
    "work_projektil": ("projektil", "internal"),
    "work_visualfox": ("visualfox", "internal"),
    "shared":         ("personal",  "shared"),
}

_SCOPE_TO_NAMESPACE = {
    ("personal",  "private"):  "private",
    ("projektil", "internal"): "work_projektil",
    ("visualfox", "internal"): "work_visualfox",
    ("personal",  "shared"):   "shared",
}


class ScopeRef(BaseModel):
    """Replaces namespace string. Represents who owns the data and how private it is."""
    org: str = "projektil"          # "projektil" | "visualfox" | "personal"
    visibility: str = "internal"    # "private" | "internal" | "shared" | "public"
    domain: Optional[str] = None    # "linkedin" | "email" | "code" | None
    owner: str = "michael_bohl"

    @classmethod
    def from_legacy_namespace(cls, namespace: str) -> "ScopeRef":
        """Convert old namespace string to ScopeRef."""
        org, vis = _NAMESPACE_TO_SCOPE.get(namespace, ("projektil", "internal"))
        return cls(org=org, visibility=vis)

    def to_legacy_namespace(self) -> str:
        """Reverse-compatibility: convert ScopeRef back to namespace string."""
        return _SCOPE_TO_NAMESPACE.get((self.org, self.visibility), "work_projektil")


__all__ = ["CircuitBreaker", "CircuitState", "ScopeRef", "_NAMESPACE_TO_SCOPE", "_SCOPE_TO_NAMESPACE"]
