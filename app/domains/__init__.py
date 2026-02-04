"""
Jarvis Coaching Domains - Domain Module Interface

This package contains domain-specific implementations for coaching.
Each domain module can provide:
- Custom context builders
- Domain-specific tools
- Knowledge extraction patterns
- Cross-domain insight generators

Base interface defined here, implementations in separate files.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class DomainContext:
    """Context object passed to domain handlers"""
    user_id: int
    domain_id: str
    session_id: Optional[int] = None
    goals: List[str] = None
    history_summary: str = ""
    user_profile: Dict[str, Any] = None


class BaseDomain(ABC):
    """
    Abstract base class for domain implementations.

    Each domain module (linkedin.py, nutrition.py, etc.) should
    extend this class and implement the abstract methods.
    """

    @property
    @abstractmethod
    def domain_id(self) -> str:
        """Unique domain identifier"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable domain name"""
        pass

    @abstractmethod
    def build_context(self, ctx: DomainContext) -> str:
        """
        Build domain-specific context to inject into system prompt.

        Args:
            ctx: DomainContext with user info, session, goals

        Returns:
            String to append to system prompt
        """
        pass

    @abstractmethod
    def get_tools(self, ctx: DomainContext) -> List[str]:
        """
        Get list of enabled tool IDs for this domain.

        Args:
            ctx: DomainContext

        Returns:
            List of tool IDs from tools.py
        """
        pass

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """
        Extract domain-specific insights from a conversation turn.

        Args:
            message: User message
            response: Assistant response

        Returns:
            List of insight dicts for storage
        """
        return []

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """
        Get patterns that might be relevant to other domains.

        Args:
            ctx: DomainContext

        Returns:
            List of pattern dicts with source_domain, pattern_type, content
        """
        return []

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """
        Hook called when a domain session starts.

        Returns:
            Optional message to include in greeting
        """
        return None

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """
        Hook called when a domain session ends.

        Returns:
            Optional summary or action items
        """
        return None


# ============ Domain Registry ============

_registered_domains: Dict[str, BaseDomain] = {}


def register_domain(domain: BaseDomain) -> None:
    """Register a domain implementation"""
    _registered_domains[domain.domain_id] = domain


def get_domain_impl(domain_id: str) -> Optional[BaseDomain]:
    """Get a registered domain implementation"""
    return _registered_domains.get(domain_id)


def list_registered_domains() -> List[str]:
    """List all registered domain implementations"""
    return list(_registered_domains.keys())


# ============ Convenience Functions ============

def get_domain_context_enhanced(
    domain_id: str,
    user_id: int,
    session_id: int = None,
    goals: List[str] = None,
    user_profile: Dict = None
) -> str:
    """
    Get enhanced domain context using registered implementation if available.
    Falls back to basic context from coaching_domains.py otherwise.
    """
    impl = get_domain_impl(domain_id)

    if impl:
        ctx = DomainContext(
            user_id=user_id,
            domain_id=domain_id,
            session_id=session_id,
            goals=goals or [],
            user_profile=user_profile or {}
        )
        return impl.build_context(ctx)

    # Fallback to basic context
    from ..coaching_domains import build_domain_context
    return build_domain_context(domain_id)


def get_domain_tools_enhanced(
    domain_id: str,
    user_id: int = None
) -> List[str]:
    """
    Get domain tools using registered implementation if available.
    """
    impl = get_domain_impl(domain_id)

    if impl and user_id:
        ctx = DomainContext(user_id=user_id, domain_id=domain_id)
        return impl.get_tools(ctx)

    # Fallback to basic tools
    from ..coaching_domains import get_domain_tools
    return get_domain_tools(domain_id)


# ============ Auto-register Domain Implementations ============

def _register_all_domains():
    """Auto-register all domain implementations."""
    try:
        from .linkedin import linkedin_domain
        register_domain(linkedin_domain)
    except ImportError:
        pass

    try:
        from .communication import communication_domain
        register_domain(communication_domain)
    except ImportError:
        pass

    try:
        from .fitness import fitness_domain
        register_domain(fitness_domain)
    except ImportError:
        pass

    try:
        from .nutrition import nutrition_domain
        register_domain(nutrition_domain)
    except ImportError:
        pass

    try:
        from .work import work_domain
        register_domain(work_domain)
    except ImportError:
        pass

    try:
        from .ideas import ideas_domain
        register_domain(ideas_domain)
    except ImportError:
        pass

    try:
        from .presentation import presentation_domain
        register_domain(presentation_domain)
    except ImportError:
        pass

    try:
        from .mediaserver import mediaserver_domain
        register_domain(mediaserver_domain)
    except ImportError:
        pass


# Register on import
_register_all_domains()
