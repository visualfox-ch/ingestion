"""
Pydantic Models for Jarvis Knowledge Layer

These models define the structure and validation for:
- Person Profiles (full personality profiles)
- Upload Queue (file processing)
- Chat Sync State (incremental processing)
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, validator


# ============ Enums ============

class RelationshipType(str, Enum):
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    BOSS = "boss"
    CLIENT = "client"
    FAMILY = "family"
    ACQUAINTANCE = "acquaintance"


class PowerDynamic(str, Enum):
    EQUAL = "equal"
    MICHA_HIGHER = "micha_higher"
    MICHA_LOWER = "micha_lower"


class Formality(str, Enum):
    FORMAL = "formal"
    SEMI_FORMAL = "semi_formal"
    INFORMAL = "informal"
    VERY_CASUAL = "very_casual"


class MessageLength(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class ResponseSpeed(str, Enum):
    IMMEDIATE = "immediate"
    SAME_DAY = "same_day"
    SLOW = "slow"


class EmojiUsage(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"
    MODERATE = "moderate"
    HEAVY = "heavy"


class DecisionStyle(str, Enum):
    ANALYTICAL = "analytical"
    INTUITIVE = "intuitive"
    COLLABORATIVE = "collaborative"
    QUICK = "quick"


class ConflictStyle(str, Enum):
    AVOIDING = "avoiding"
    ACCOMMODATING = "accommodating"
    COMPETING = "competing"
    COLLABORATING = "collaborating"
    COMPROMISING = "compromising"


class SentimentTrend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class SourceType(str, Enum):
    GOOGLE_CHAT = "google_chat"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    MANUAL = "manual"


class ChannelType(str, Enum):
    GOOGLE_CHAT = "google_chat"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    CALL = "call"


class Namespace(str, Enum):
    """Deprecated: Use ScopeRef instead. Kept for backward compatibility."""
    PRIVATE = "private"
    WORK_PROJEKTIL = "work_projektil"
    WORK_VISUALFOX = "work_visualfox"
    SHARED = "shared"


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


class UploadStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    ARCHIVED = "archived"


# ============ Person Profile Models ============

class Organization(BaseModel):
    """Organization membership"""
    org_id: str
    role: str
    department: Optional[str] = None
    since: Optional[date] = None
    is_active: bool = True


class SharedHistory(BaseModel):
    """Shared history between person and Micha"""
    first_contact: Optional[date] = None
    key_moments: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    inside_jokes: List[str] = Field(default_factory=list)


class RelationshipToMicha(BaseModel):
    """Relationship details to Micha"""
    type: RelationshipType
    closeness: int = Field(ge=1, le=5, default=3)
    trust_level: int = Field(ge=1, le=5, default=3)
    power_dynamic: PowerDynamic = PowerDynamic.EQUAL
    shared_history: SharedHistory = Field(default_factory=SharedHistory)


class MessagePatterns(BaseModel):
    """Observed message patterns"""
    typical_length: MessageLength = MessageLength.MEDIUM
    response_speed: ResponseSpeed = ResponseSpeed.SAME_DAY
    emoji_usage: EmojiUsage = EmojiUsage.MINIMAL
    greeting_style: Optional[str] = None
    sign_off_style: Optional[str] = None


class ChannelPreferences(BaseModel):
    """Preferred channels by urgency"""
    urgent: Optional[ChannelType] = None
    normal: Optional[ChannelType] = None
    casual: Optional[ChannelType] = None


class CommunicationPreferences(BaseModel):
    """Communication preferences"""
    best_contact_times: List[str] = Field(default_factory=list)
    preferred_channels: ChannelPreferences = Field(default_factory=ChannelPreferences)
    likes_voice_messages: bool = False
    prefers_calls_over_text: bool = False


class CommunicationTriggers(BaseModel):
    """What works well / what to avoid"""
    positive: List[str] = Field(default_factory=list)
    negative: List[str] = Field(default_factory=list)
    topics_to_avoid: List[str] = Field(default_factory=list)


class CommunicationStyle(BaseModel):
    """Full communication style profile"""
    languages: List[str] = Field(default_factory=lambda: ["de"])
    primary_language: str = "de"
    formality: Formality = Formality.INFORMAL
    message_patterns: MessagePatterns = Field(default_factory=MessagePatterns)
    preferences: CommunicationPreferences = Field(default_factory=CommunicationPreferences)
    triggers: CommunicationTriggers = Field(default_factory=CommunicationTriggers)


class BigFive(BaseModel):
    """Big Five personality traits (optional)"""
    openness: Optional[int] = Field(None, ge=1, le=5)
    conscientiousness: Optional[int] = Field(None, ge=1, le=5)
    extraversion: Optional[int] = Field(None, ge=1, le=5)
    agreeableness: Optional[int] = Field(None, ge=1, le=5)
    neuroticism: Optional[int] = Field(None, ge=1, le=5)


class Personality(BaseModel):
    """Personality profile"""
    big_five: BigFive = Field(default_factory=BigFive)
    decision_style: Optional[DecisionStyle] = None
    conflict_style: Optional[ConflictStyle] = None
    stress_indicators: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    growth_areas: List[str] = Field(default_factory=list)


class PersonalContext(BaseModel):
    """Personal life context"""
    birthday: Optional[date] = None
    family_situation: Optional[str] = None
    hobbies: List[str] = Field(default_factory=list)
    current_life_phase: Optional[str] = None


class ProfessionalContext(BaseModel):
    """Professional context"""
    expertise_areas: List[str] = Field(default_factory=list)
    current_projects: List[str] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    challenges: List[str] = Field(default_factory=list)


class Context(BaseModel):
    """Combined context"""
    personal: PersonalContext = Field(default_factory=PersonalContext)
    professional: ProfessionalContext = Field(default_factory=ProfessionalContext)


class InteractionHistory(BaseModel):
    """Interaction history summary"""
    last_interaction: Optional[datetime] = None
    total_messages_analyzed: int = 0
    sentiment_trend: Optional[SentimentTrend] = None
    recent_topics: List[str] = Field(default_factory=list)
    pending_items: List[str] = Field(default_factory=list)


class EvidenceSource(BaseModel):
    """Source of profile information"""
    source_type: SourceType
    namespace: str
    message_count: int = 0
    date_range: Optional[Dict[str, date]] = None


class ProfileMeta(BaseModel):
    """Profile metadata"""
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.5)
    needs_review: bool = True
    sources: List[EvidenceSource] = Field(default_factory=list)


class PersonProfileContent(BaseModel):
    """
    Complete person profile content.
    This is stored in person_profile_version.content as JSONB.
    """
    # Identity
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    email_addresses: List[str] = Field(default_factory=list)
    phone_numbers: List[str] = Field(default_factory=list)

    # Organizations
    organizations: List[Organization] = Field(default_factory=list)

    # Relationship
    relationship_to_micha: Optional[RelationshipToMicha] = None

    # Communication
    communication_style: CommunicationStyle = Field(default_factory=CommunicationStyle)

    # Personality
    personality: Personality = Field(default_factory=Personality)

    # Context
    context: Context = Field(default_factory=Context)

    # History
    interaction_history: InteractionHistory = Field(default_factory=InteractionHistory)

    # Meta
    meta: ProfileMeta = Field(default_factory=ProfileMeta)

    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None,
            datetime: lambda v: v.isoformat() if v else None,
        }


# ============ Upload Queue Models ============

class UploadRequest(BaseModel):
    """Request to upload a file for processing"""
    source_type: SourceType
    namespace: Namespace
    channel_hint: Optional[str] = None
    priority: int = Field(ge=1, le=5, default=3)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UploadQueueItem(BaseModel):
    """Upload queue item"""
    id: str
    filename: str
    file_path: str
    file_size_bytes: Optional[int] = None
    file_hash: Optional[str] = None
    source_type: SourceType
    namespace: Namespace
    channel_hint: Optional[str] = None
    status: UploadStatus = UploadStatus.PENDING
    priority: int = Field(ge=1, le=5, default=3)
    messages_extracted: Optional[int] = None
    profiles_updated: List[str] = Field(default_factory=list)
    knowledge_items_created: Optional[int] = None
    error_message: Optional[str] = None
    uploaded_at: datetime
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    uploaded_by: str = "api"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============ Chat Sync State Models ============

class ChatSyncState(BaseModel):
    """Sync state for a chat channel"""
    id: str  # "google_chat:work_projektil:space_abc"
    source_type: SourceType
    namespace: Namespace
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    last_message_ts: Optional[datetime] = None
    last_message_id: Optional[str] = None
    total_messages_processed: int = 0
    total_files_processed: int = 0
    unique_participants: List[str] = Field(default_factory=list)
    first_sync: Optional[datetime] = None
    last_sync: Optional[datetime] = None


# ============ Profile Extraction Request ============

class ProfileExtractionRequest(BaseModel):
    """Request to extract/update profile from text"""
    person_id: str
    namespace: Namespace
    source_type: SourceType
    text_content: str
    channel_id: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)


class ProfileExtractionResult(BaseModel):
    """Result of profile extraction"""
    person_id: str
    status: str  # "created", "updated", "no_changes"
    fields_updated: List[str] = Field(default_factory=list)
    confidence_delta: float = 0.0
    needs_review: bool = True
    extraction_notes: Optional[str] = None


# ============ Helper Functions ============

def create_empty_profile_content(display_name: str) -> PersonProfileContent:
    """Create an empty profile content with just the name"""
    return PersonProfileContent(display_name=display_name)


def merge_profile_content(
    existing: PersonProfileContent,
    updates: Dict[str, Any],
    overwrite: bool = False
) -> PersonProfileContent:
    """
    Merge updates into existing profile content.

    Args:
        existing: Current profile content
        updates: Dict with updates (partial)
        overwrite: If True, replace fields. If False, merge lists.

    Returns:
        Updated PersonProfileContent
    """
    data = existing.dict()

    for key, value in updates.items():
        if value is None:
            continue

        if key in data:
            if isinstance(data[key], list) and isinstance(value, list):
                if overwrite:
                    data[key] = value
                else:
                    # Merge lists, avoiding duplicates for simple types
                    existing_set = set(data[key]) if all(isinstance(x, (str, int, float)) for x in data[key]) else None
                    if existing_set:
                        data[key] = list(existing_set | set(value))
                    else:
                        data[key] = data[key] + value
            elif isinstance(data[key], dict) and isinstance(value, dict):
                # Recursively merge dicts
                data[key] = {**data[key], **value}
            else:
                data[key] = value
        else:
            data[key] = value

    return PersonProfileContent(**data)
