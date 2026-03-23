"""
Real Estate Intelligence Router

API endpoints for property search, alerts, and ingestion.
Integrated with matcher and geo-scoring services.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from ..observability import get_logger, log_with_context
from ..auth import auth_dependency
from ..services.real_estate_service import get_real_estate_service
from ..services.real_estate_parsers import get_parser_registry
from ..services.real_estate_alerter import get_real_estate_alerter
from ..services.real_estate_matcher import get_real_estate_matcher
from ..services.real_estate_sheets import get_real_estate_sheets
from fastapi import Depends

logger = get_logger("jarvis.real_estate")
router = APIRouter(prefix="/real-estate", tags=["real-estate"])


# =============================================================================
# Request/Response Models
# =============================================================================

class PropertySearchRequest(BaseModel):
    """Search criteria for properties."""
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_type: str = "rent"  # rent, sale
    rooms_min: Optional[float] = None
    rooms_max: Optional[float] = None
    locations: Optional[List[str]] = None  # Cities or postal codes
    features: Optional[List[str]] = None
    min_score: float = 0.0
    limit: int = Field(default=20, le=100)


class PropertyResponse(BaseModel):
    """Property listing response."""
    property_id: str
    title: str
    price: float
    price_currency: str = "CHF"
    rooms: Optional[float] = None
    living_space_m2: Optional[float] = None
    address: Optional[str] = None
    url: Optional[str] = None
    match_score: Optional[float] = None
    source: str
    first_seen: datetime


class SearchProfileRequest(BaseModel):
    """Create/update search profile."""
    name: str
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_type: str = "rent"
    rooms_min: Optional[float] = None
    rooms_max: Optional[float] = None
    locations: Optional[List[dict]] = None
    required_features: Optional[List[str]] = None
    alert_threshold: float = 0.7
    digest_threshold: float = 0.5


class EmailIngestRequest(BaseModel):
    """Ingest property from email."""
    from_address: str = Field(..., alias="from")
    subject: str
    body: str
    date: Optional[str] = None
    message_id: Optional[str] = None


class AlertStatsResponse(BaseModel):
    """Alert statistics."""
    total_alerts: int
    instant_alerts: int
    digest_alerts: int
    clicked: int
    dismissed: int
    click_rate: float


# =============================================================================
# Property Search Endpoints
# =============================================================================

@router.post("/search")
async def search_properties(
    request: PropertySearchRequest,
    auth: bool = Depends(auth_dependency)
):
    """
    Search properties matching criteria.
    Returns scored and sorted results.
    """
    service = get_real_estate_service()
    results = service.search_properties(
        price_min=request.price_min,
        price_max=request.price_max,
        price_type=request.price_type,
        rooms_min=request.rooms_min,
        rooms_max=request.rooms_max,
        locations=request.locations,
        min_score=request.min_score,
        limit=request.limit
    )
    log_with_context(logger, "info", "Property search",
                    filters=request.dict(), results=len(results))
    return results


@router.get("/properties/{property_id}")
async def get_property(
    property_id: str,
    auth: bool = Depends(auth_dependency)
):
    """Get single property with match results."""
    service = get_real_estate_service()
    prop = service.get_property_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    # Also get match results
    matches = service.match_property_against_profiles(property_id)

    return {
        "property": prop.dict(),
        "matches": [m.dict() for m in matches],
        "best_score": matches[0].total_score if matches else None
    }


@router.get("/properties/recent")
async def get_recent_properties(
    hours: int = Query(24, le=168),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, le=200),
    auth: bool = Depends(auth_dependency)
):
    """Get recently discovered properties."""
    # TODO: Implement
    return {"properties": [], "count": 0, "hours": hours}


# =============================================================================
# Search Profile Endpoints
# =============================================================================

@router.post("/profiles")
async def create_search_profile(
    request: SearchProfileRequest,
    auth: bool = Depends(auth_dependency)
):
    """Create a new search profile."""
    profile_id = str(uuid.uuid4())
    logger.info(f"Created search profile: {profile_id}")
    return {"profile_id": profile_id, "name": request.name, "status": "created"}


@router.get("/profiles")
async def list_search_profiles(
    active_only: bool = True,
    auth: bool = Depends(auth_dependency)
):
    """List all search profiles."""
    service = get_real_estate_service()
    profiles = service.get_active_profiles()
    return {
        "profiles": [p.dict() for p in profiles],
        "count": len(profiles)
    }


@router.put("/profiles/{profile_id}")
async def update_search_profile(
    profile_id: str,
    request: SearchProfileRequest,
    auth: bool = Depends(auth_dependency)
):
    """Update existing search profile."""
    # TODO: Implement
    return {"profile_id": profile_id, "status": "updated"}


@router.delete("/profiles/{profile_id}")
async def delete_search_profile(
    profile_id: str,
    auth: bool = Depends(auth_dependency)
):
    """Deactivate search profile."""
    # TODO: Implement
    return {"profile_id": profile_id, "status": "deactivated"}


# =============================================================================
# Ingestion Endpoints
# =============================================================================

@router.post("/ingest/email")
async def ingest_email(
    request: EmailIngestRequest,
    auth: bool = Depends(auth_dependency)
):
    """
    Ingest property listing from email.
    Called by n8n IMAP workflow.

    Full workflow:
    1. Parse email to extract properties
    2. Store/update properties in database
    3. Match against active search profiles
    4. Send alerts for high-scoring matches
    """
    log_with_context(
        logger, "info", "Email ingest",
        from_address=request.from_address,
        subject=request.subject
    )

    # Step 1: Parse email
    parser_registry = get_parser_registry()
    properties = parser_registry.parse_email(
        from_address=request.from_address,
        subject=request.subject,
        body=request.body
    )

    if not properties:
        return {
            "status": "no_properties",
            "properties_found": 0,
            "alerts_sent": 0
        }

    # Step 2: Store properties and match
    service = get_real_estate_service()
    matcher = get_real_estate_matcher()
    alerter = get_real_estate_alerter()
    profiles = service.get_active_profiles()

    results = []
    alerts_sent = 0

    for prop in properties:
        # Store property
        store_result = service.create_property(
            source_type="email",
            source_name=prop.source,
            content={
                "title": prop.title,
                "description": prop.description,
                "price": {
                    "amount": prop.rent_chf or prop.price_chf,
                    "currency": "CHF",
                    "type": "rent" if prop.rent_chf else "sale"
                },
                "rooms": prop.rooms,
                "living_space_m2": prop.living_area_m2,
                "address": {
                    "city": prop.location.city,
                    "postal_code": prop.location.postal_code,
                    "canton": prop.location.canton
                },
                "has_balcony": prop.has_balcony,
                "has_parking": prop.has_parking,
                "has_elevator": prop.has_elevator
            },
            external_id=prop.external_id,
            external_url=prop.source_url
        )

        # Step 3: Match against profiles
        best_match = None
        for profile in profiles:
            match = matcher.match(prop, profile)
            if match and (not best_match or match.total_score > best_match.total_score):
                best_match = match

        # Step 4: Send alert if high-scoring match
        alert_sent = False
        if best_match and best_match.total_score >= 0.40:
            alert_result = await alerter.send_match_alert(prop, best_match)
            alert_sent = alert_result.get("sent", False)
            if alert_sent:
                alerts_sent += 1

        # Step 5: Add to Google Sheet
        sheets = get_real_estate_sheets()
        try:
            sheets.add_property(prop, best_match, status="Neu")
        except Exception as e:
            log_with_context(logger, "warning", "Sheet add failed", error=str(e))

        results.append({
            "property_id": store_result.get("property_id"),
            "action": store_result.get("action"),
            "match_score": best_match.total_score if best_match else None,
            "alert_sent": alert_sent
        })

    log_with_context(
        logger, "info", "Email ingest complete",
        properties_found=len(properties),
        alerts_sent=alerts_sent
    )

    return {
        "status": "processed",
        "properties_found": len(properties),
        "properties": results,
        "alerts_sent": alerts_sent
    }


@router.post("/ingest/scrape")
async def ingest_scrape(
    source: str,
    url: str,
    auth: bool = Depends(auth_dependency)
):
    """
    Trigger scrape of a specific URL.
    """
    logger.info(f"Scrape request: {source} - {url}")
    # TODO: Implement with scraper service
    return {"status": "queued", "source": source, "url": url}


# =============================================================================
# Alert Endpoints
# =============================================================================

@router.get("/alerts/stats")
async def get_alert_stats(
    days: int = Query(7, le=90),
    auth: bool = Depends(auth_dependency)
) -> AlertStatsResponse:
    """Get alert statistics."""
    service = get_real_estate_service()
    stats = service.get_alert_stats(days=days)
    if "error" in stats:
        raise HTTPException(status_code=500, detail=stats["error"])
    return AlertStatsResponse(**stats)


@router.post("/alerts/{property_id}/dismiss")
async def dismiss_alert(
    property_id: str,
    auth: bool = Depends(auth_dependency)
):
    """Mark property as not interesting."""
    # TODO: Implement
    return {"property_id": property_id, "status": "dismissed"}


@router.post("/alerts/{property_id}/click")
async def track_alert_click(
    property_id: str,
    auth: bool = Depends(auth_dependency)
):
    """Track that user clicked on alert."""
    # TODO: Implement
    return {"property_id": property_id, "status": "clicked"}


# =============================================================================
# Source Management
# =============================================================================

@router.get("/sources")
async def list_sources(
    auth: bool = Depends(auth_dependency)
):
    """List configured property sources with status."""
    # TODO: Implement from property_source_policy table
    return {"sources": [], "count": 0}


@router.get("/sources/{source_id}/health")
async def get_source_health(
    source_id: str,
    auth: bool = Depends(auth_dependency)
):
    """Get health status of a source."""
    # TODO: Implement
    return {
        "source_id": source_id,
        "enabled": True,
        "last_scrape": None,
        "consecutive_errors": 0
    }


# =============================================================================
# Google Sheets Integration
# =============================================================================

@router.post("/sheets/create")
async def create_tracking_sheet(
    title: str = Query(None, description="Sheet title"),
    auth: bool = Depends(auth_dependency)
):
    """Create a new Google Sheet for property tracking."""
    sheets = get_real_estate_sheets()
    result = sheets.create_spreadsheet(title)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.get("/sheets/info")
async def get_sheet_info(
    auth: bool = Depends(auth_dependency)
):
    """Get current tracking sheet info."""
    sheets = get_real_estate_sheets()
    return {
        "spreadsheet_id": sheets.spreadsheet_id,
        "spreadsheet_url": sheets.spreadsheet_url,
        "configured": sheets.spreadsheet_id is not None
    }


@router.get("/sheets/stats")
async def get_sheet_stats(
    auth: bool = Depends(auth_dependency)
):
    """Get property statistics from sheet."""
    sheets = get_real_estate_sheets()
    return sheets.get_stats()


@router.get("/sheets/properties")
async def get_sheet_properties(
    auth: bool = Depends(auth_dependency)
):
    """Get all properties from tracking sheet."""
    sheets = get_real_estate_sheets()
    properties = sheets.get_properties()
    return {"properties": properties, "count": len(properties)}


class UpdateStatusRequest(BaseModel):
    """Update property status."""
    status: str = Field(..., description="New status: Neu, Kontaktiert, Besichtigung, Abgelehnt, Favorit")
    notes: Optional[str] = None


@router.put("/sheets/properties/{property_id}/status")
async def update_property_status(
    property_id: str,
    request: UpdateStatusRequest,
    auth: bool = Depends(auth_dependency)
):
    """Update property status in tracking sheet."""
    sheets = get_real_estate_sheets()
    result = sheets.update_status(property_id, request.status, request.notes)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result
