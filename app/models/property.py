"""
Real Estate Models - Property, SearchProfile, MatchResult

Adapted from Claude Cowork outputs for Jarvis integration.
Used by: real_estate_service, real_estate_router, real_estate_matcher
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class PropertyType(str, Enum):
    """Type of property listing."""
    APARTMENT = "apartment"
    HOUSE = "house"
    VILLA = "villa"
    LAND = "land"
    COMMERCIAL = "commercial"
    PARKING = "parking"
    OTHER = "other"


class TransactionType(str, Enum):
    """Buy or rent."""
    BUY = "buy"
    RENT = "rent"


class AlertPriority(str, Enum):
    """Alert priority based on match score."""
    INSTANT = "instant"   # Score >= 0.85 - immediate notification
    HIGH = "high"         # Score >= 0.65 - digest every 10-15 min
    NORMAL = "normal"     # Score >= 0.40 - daily report
    LOW = "low"           # Score < 0.40 - weekly report only


class SourceType(str, Enum):
    """Property source type."""
    PORTAL = "portal"       # homegate, immoscout24, flatfox
    EMAIL = "email"         # email alerts from portals
    API = "api"             # direct API access
    MANUAL = "manual"       # manually entered


# =============================================================================
# Search Profile Components
# =============================================================================

class PriceRange(BaseModel):
    """Price filter range in CHF."""
    min_chf: Optional[int] = None
    max_chf: Optional[int] = None


class AreaRange(BaseModel):
    """Area filter range in m2."""
    min_m2: Optional[float] = None
    max_m2: Optional[float] = None


class RoomRange(BaseModel):
    """Room count filter (supports half rooms like 3.5)."""
    min_rooms: Optional[float] = None
    max_rooms: Optional[float] = None


class GeoFilter(BaseModel):
    """Geographic filter with cantons, cities, postal codes, or radius."""
    cantons: List[str] = Field(default_factory=list)
    postal_codes: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    radius_km: Optional[float] = None
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None


class SearchProfile(BaseModel):
    """
    User's search criteria for property matching.
    Stored in property_search_profile table.
    """
    id: str = Field(..., description="Profile UUID")
    name: str = Field(..., description="Profile name e.g. 'Zürich 4-Zimmer'")
    active: bool = True
    user_id: str = "1"

    # Object type & transaction
    transaction_type: TransactionType = TransactionType.RENT
    property_types: List[PropertyType] = Field(
        default_factory=lambda: [PropertyType.APARTMENT]
    )

    # Filters
    price: PriceRange = Field(default_factory=PriceRange)
    living_area: AreaRange = Field(default_factory=AreaRange)
    rooms: RoomRange = Field(default_factory=RoomRange)
    geo: GeoFilter = Field(default_factory=GeoFilter)

    # Feature filters
    keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    has_parking: Optional[bool] = None
    has_balcony: Optional[bool] = None
    has_elevator: Optional[bool] = None

    # Scoring weights (must sum to ~1.0)
    weight_price: float = Field(default=0.30, ge=0, le=1)
    weight_location: float = Field(default=0.30, ge=0, le=1)
    weight_size: float = Field(default=0.20, ge=0, le=1)
    weight_features: float = Field(default=0.20, ge=0, le=1)

    # Alert thresholds
    instant_threshold: float = Field(default=0.85)
    high_threshold: float = Field(default=0.65)
    normal_threshold: float = Field(default=0.40)


# =============================================================================
# Property & Location
# =============================================================================

class GeoLocation(BaseModel):
    """Property location data."""
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    canton: Optional[str] = None
    country: str = "CH"
    lat: Optional[float] = None
    lon: Optional[float] = None


class Contact(BaseModel):
    """Property contact/agent info."""
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class Property(BaseModel):
    """
    Normalized property listing.
    All sources (homegate, immoscout24, email) are mapped to this format.
    """
    # Identification
    id: str = Field(..., description="Internal ID (source:external_id)")
    external_id: str
    source: str = Field(..., description="Source name: homegate, immoscout24, etc.")
    source_url: Optional[str] = None

    # Core data
    title: str
    description: Optional[str] = None
    transaction_type: TransactionType
    property_type: PropertyType = PropertyType.OTHER

    # Price (amounts in CHF)
    price_chf: Optional[int] = None          # Purchase price
    rent_chf: Optional[int] = None           # Monthly rent (gross)
    rent_net_chf: Optional[int] = None       # Net rent
    additional_costs_chf: Optional[int] = None

    # Size
    living_area_m2: Optional[float] = None
    rooms: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor: Optional[int] = None

    # Age & condition
    year_built: Optional[int] = None
    year_renovated: Optional[int] = None

    # Features
    has_parking: Optional[bool] = None
    has_balcony: Optional[bool] = None
    has_terrace: Optional[bool] = None
    has_elevator: Optional[bool] = None
    has_view: Optional[bool] = None
    minergie: Optional[bool] = None

    # Location
    location: GeoLocation = Field(default_factory=GeoLocation)

    # Media
    images: List[str] = Field(default_factory=list)

    # Contact
    contact: Contact = Field(default_factory=Contact)

    # Timestamps
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None

    # Dedup
    fingerprint: Optional[str] = None

    # Raw data for debugging
    raw_data: Optional[dict] = None


# =============================================================================
# Match Result
# =============================================================================

class ScoreBreakdown(BaseModel):
    """Detailed scoring breakdown for transparency."""
    price_score: float = 0.0
    location_score: float = 0.0
    size_score: float = 0.0
    features_score: float = 0.0
    keyword_bonus: float = 0.0
    freshness_bonus: float = 0.0


class MatchResult(BaseModel):
    """Result of matching a Property against a SearchProfile."""
    property_id: str
    profile_id: str
    total_score: float = Field(..., ge=0, le=1)
    priority: AlertPriority
    breakdown: ScoreBreakdown
    matched_at: datetime = Field(default_factory=datetime.utcnow)

    # Notification tracking
    notified: bool = False
    notified_at: Optional[datetime] = None
    notified_channel: Optional[str] = None

    # Generated content
    response_template: Optional[str] = None
    call_script: Optional[str] = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "PropertyType",
    "TransactionType",
    "AlertPriority",
    "SourceType",
    # Search Profile
    "PriceRange",
    "AreaRange",
    "RoomRange",
    "GeoFilter",
    "SearchProfile",
    # Property
    "GeoLocation",
    "Contact",
    "Property",
    # Match
    "ScoreBreakdown",
    "MatchResult",
]
