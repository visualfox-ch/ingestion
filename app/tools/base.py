"""
Base classes and types for Jarvis tools.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional


class ToolCategory(Enum):
    """Tool categories for organization and routing."""
    KNOWLEDGE = "knowledge"
    COMMUNICATION = "communication"
    CALENDAR = "calendar"
    PROJECT = "project"
    SYSTEM = "system"
    VOICE = "voice"
    RESEARCH = "research"
    MONITORING = "monitoring"
    AUTONOMY = "autonomy"
    LEARNING = "learning"
    DECISION = "decision"


@dataclass
class ToolMetadata:
    """Metadata for a tool."""
    category: ToolCategory
    requires_auth: bool = False
    is_async: bool = False
    timeout_seconds: int = 30
    keywords: List[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high
    description_short: Optional[str] = None
