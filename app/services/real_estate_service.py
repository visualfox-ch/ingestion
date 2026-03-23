"""
Real Estate Intelligence Service

Core business logic for property matching, scoring, and alerts.
Integrates matcher and geo-scoring from Claude Cowork.
"""
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import hashlib
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn, get_dict_cursor
from ..models.property import (
    Property, PropertyType, TransactionType, GeoLocation, Contact,
    SearchProfile, PriceRange, RoomRange, GeoFilter, MatchResult
)
from .real_estate_matcher import get_real_estate_matcher
from .real_estate_geo import get_geo_scoring_service

logger = get_logger("jarvis.real_estate_service")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PropertyMatch:
    """Result of matching a property against a search profile."""
    property_id: str
    profile_id: str
    score: float  # 0.0 - 1.0
    score_breakdown: Dict[str, float]  # {price: 0.9, location: 0.8, ...}
    alert_type: str  # instant, digest, none


@dataclass
class PropertySummary:
    """Lightweight property representation."""
    property_id: str
    title: str
    price: float
    rooms: Optional[float]
    location: str
    url: str
    match_score: Optional[float]
    source: str


# =============================================================================
# Real Estate Service
# =============================================================================

class RealEstateService:
    """
    Real Estate Intelligence Service.

    Provides:
    - Property search and filtering
    - Profile-based matching with weighted scoring
    - Deduplication via content hash
    - Alert management
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Check that real estate tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'property_listing'
                        )
                    """)
                    exists = cur.fetchone()[0]
                    if not exists:
                        log_with_context(logger, "warning",
                            "Real estate tables not found - run migration 140")
        except Exception as e:
            log_with_context(logger, "error", "Table check failed", error=str(e))

    # =========================================================================
    # Property CRUD
    # =========================================================================

    def create_property(
        self,
        source_type: str,
        source_name: str,
        content: Dict[str, Any],
        external_id: Optional[str] = None,
        external_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create or update a property listing.
        Uses content hash for deduplication.
        """
        # Generate content hash for dedup
        content_hash = self._hash_content(content)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check for existing property by hash
                    cur.execute("""
                        SELECT property_id FROM property_listing
                        WHERE content_hash = %s
                    """, (content_hash,))
                    existing = cur.fetchone()

                    if existing:
                        property_id = existing[0]
                        # Update last_seen and add new version
                        cur.execute("""
                            UPDATE property_listing
                            SET last_seen_at = NOW()
                            WHERE property_id = %s
                        """, (property_id,))
                        action = "updated"
                    else:
                        # Create new property
                        cur.execute("""
                            INSERT INTO property_listing
                            (source_type, source_name, external_id, external_url, content_hash)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING property_id
                        """, (source_type, source_name, external_id, external_url, content_hash))
                        property_id = cur.fetchone()[0]
                        action = "created"

                    # Get next version number
                    cur.execute("""
                        SELECT COALESCE(MAX(version_number), 0) + 1
                        FROM property_listing_version
                        WHERE property_id = %s
                    """, (property_id,))
                    version = cur.fetchone()[0]

                    # Insert version with extracted fields
                    cur.execute("""
                        INSERT INTO property_listing_version
                        (property_id, version_number, content, title, price_amount,
                         price_currency, price_type, rooms, living_space_m2,
                         address_city, address_postal_code, address_canton, raw_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        property_id, version, json.dumps(content),
                        content.get("title"),
                        content.get("price", {}).get("amount"),
                        content.get("price", {}).get("currency", "CHF"),
                        content.get("price", {}).get("type", "rent"),
                        content.get("rooms"),
                        content.get("living_space_m2"),
                        content.get("address", {}).get("city"),
                        content.get("address", {}).get("postal_code"),
                        content.get("address", {}).get("canton"),
                        json.dumps(content.get("raw_data", {}))
                    ))

                    conn.commit()

                    log_with_context(logger, "info", f"Property {action}",
                                   property_id=str(property_id), source=source_name)

                    return {
                        "success": True,
                        "property_id": str(property_id),
                        "version": version,
                        "action": action,
                        "content_hash": content_hash
                    }

        except Exception as e:
            log_with_context(logger, "error", "Property creation failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _hash_content(self, content: Dict[str, Any]) -> str:
        """Generate SHA256 hash for deduplication."""
        # Use key fields for hash
        key_data = {
            "title": content.get("title", ""),
            "price": content.get("price", {}),
            "address": content.get("address", {}),
            "rooms": content.get("rooms"),
            "living_space": content.get("living_space_m2")
        }
        content_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()

    # =========================================================================
    # Search & Matching
    # =========================================================================

    def search_properties(
        self,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        price_type: str = "rent",
        rooms_min: Optional[float] = None,
        rooms_max: Optional[float] = None,
        locations: Optional[List[str]] = None,
        min_score: float = 0.0,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search properties with filters.
        Returns latest version of each matching property.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT DISTINCT ON (p.property_id)
                            p.property_id, v.title, v.price_amount, v.price_currency,
                            v.rooms, v.living_space_m2, v.address_city, v.address_canton,
                            p.external_url, v.match_score, p.source_name, p.first_seen_at
                        FROM property_listing p
                        JOIN property_listing_version v ON p.property_id = v.property_id
                        WHERE p.is_active = TRUE
                          AND v.price_type = %s
                    """
                    params = [price_type]

                    if price_min:
                        query += " AND v.price_amount >= %s"
                        params.append(price_min)

                    if price_max:
                        query += " AND v.price_amount <= %s"
                        params.append(price_max)

                    if rooms_min:
                        query += " AND v.rooms >= %s"
                        params.append(rooms_min)

                    if rooms_max:
                        query += " AND v.rooms <= %s"
                        params.append(rooms_max)

                    if locations:
                        query += " AND (v.address_city = ANY(%s) OR v.address_postal_code = ANY(%s) OR v.address_canton = ANY(%s))"
                        params.extend([locations, locations, locations])

                    if min_score > 0:
                        query += " AND COALESCE(v.match_score, 0) >= %s"
                        params.append(min_score)

                    query += """
                        ORDER BY p.property_id, v.version_number DESC
                        LIMIT %s
                    """
                    params.append(limit)

                    cur.execute(query, tuple(params))

                    results = []
                    for row in cur.fetchall():
                        results.append({
                            "property_id": str(row[0]),
                            "title": row[1],
                            "price": row[2],
                            "price_currency": row[3],
                            "rooms": float(row[4]) if row[4] else None,
                            "living_space_m2": float(row[5]) if row[5] else None,
                            "city": row[6],
                            "canton": row[7],
                            "url": row[8],
                            "match_score": float(row[9]) if row[9] else None,
                            "source": row[10],
                            "first_seen": row[11].isoformat() if row[11] else None
                        })

                    return results

        except Exception as e:
            log_with_context(logger, "error", "Search failed", error=str(e))
            return []

    def get_property_by_id(self, property_id: str) -> Optional[Property]:
        """Get a property by ID and convert to Property model."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            p.property_id, p.external_id, p.source_name, p.external_url,
                            v.title, v.content, v.price_amount, v.price_type,
                            v.rooms, v.living_space_m2, v.address_city,
                            v.address_postal_code, v.address_canton,
                            v.latitude, v.longitude, p.first_seen_at, p.last_seen_at
                        FROM property_listing p
                        JOIN property_listing_version v ON p.property_id = v.property_id
                        WHERE p.property_id = %s
                        ORDER BY v.version_number DESC
                        LIMIT 1
                    """, (property_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_property(row)
        except Exception as e:
            log_with_context(logger, "error", "Get property failed", error=str(e))
            return None

    def _row_to_property(self, row) -> Property:
        """Convert DB row to Property model."""
        content = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")

        # Determine transaction type
        price_type_str = row[7] or "rent"
        tx_type = TransactionType.BUY if price_type_str == "sale" else TransactionType.RENT

        # Build property
        return Property(
            id=f"{row[2]}:{row[1]}" if row[1] else str(row[0]),
            external_id=row[1] or str(row[0]),
            source=row[2] or "unknown",
            source_url=row[3],
            title=row[4] or "Untitled",
            description=content.get("description"),
            transaction_type=tx_type,
            property_type=PropertyType.APARTMENT,  # Default, could be extracted
            price_chf=int(row[6]) if row[6] and tx_type == TransactionType.BUY else None,
            rent_chf=int(row[6]) if row[6] and tx_type == TransactionType.RENT else None,
            rooms=float(row[8]) if row[8] else None,
            living_area_m2=float(row[9]) if row[9] else None,
            location=GeoLocation(
                city=row[10],
                postal_code=row[11],
                canton=row[12],
                lat=float(row[13]) if row[13] else None,
                lon=float(row[14]) if row[14] else None,
            ),
            has_balcony=content.get("has_balcony"),
            has_parking=content.get("has_parking"),
            has_elevator=content.get("has_elevator"),
            first_seen=row[15] or datetime.utcnow(),
            last_seen=row[16] or datetime.utcnow(),
            raw_data=content,
        )

    def get_active_profiles(self, user_id: str = "1") -> List[SearchProfile]:
        """Get all active search profiles for a user."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT profile_id, name, price_min, price_max, price_type,
                               rooms_min, rooms_max, locations, required_features,
                               weight_price, weight_location, weight_size, weight_features,
                               alert_threshold, digest_threshold
                        FROM property_search_profile
                        WHERE user_id = %s AND is_active = TRUE
                        ORDER BY priority DESC
                    """, (user_id,))

                    profiles = []
                    for row in cur.fetchall():
                        locations_json = row[7] or []
                        geo = GeoFilter(
                            cities=[loc.get("city") for loc in locations_json if loc.get("city")],
                            postal_codes=[loc.get("postal_code") for loc in locations_json if loc.get("postal_code")],
                            cantons=[loc.get("canton") for loc in locations_json if loc.get("canton")],
                        )

                        profiles.append(SearchProfile(
                            id=str(row[0]),
                            name=row[1],
                            user_id=user_id,
                            price=PriceRange(min_chf=row[2], max_chf=row[3]),
                            transaction_type=TransactionType.BUY if row[4] == "sale" else TransactionType.RENT,
                            rooms=RoomRange(min_rooms=row[5], max_rooms=row[6]),
                            geo=geo,
                            keywords=row[8] or [],
                            weight_price=row[9] or 0.3,
                            weight_location=row[10] or 0.3,
                            weight_size=row[11] or 0.2,
                            weight_features=row[12] or 0.2,
                            instant_threshold=row[13] or 0.85,
                            normal_threshold=row[14] or 0.40,
                        ))
                    return profiles
        except Exception as e:
            log_with_context(logger, "error", "Get profiles failed", error=str(e))
            return []

    def match_property_against_profiles(
        self,
        property_id: str,
        user_id: str = "1"
    ) -> List[MatchResult]:
        """
        Match a property against all active search profiles.
        Returns matches sorted by score.
        """
        prop = self.get_property_by_id(property_id)
        if not prop:
            return []

        profiles = self.get_active_profiles(user_id)
        if not profiles:
            return []

        matcher = get_real_estate_matcher()
        results = []

        for profile in profiles:
            result = matcher.match(prop, profile)
            if result:
                results.append(result)

        results.sort(key=lambda r: r.total_score, reverse=True)
        log_with_context(
            logger, "info", "Property matched against profiles",
            property_id=property_id,
            profiles_checked=len(profiles),
            matches=len(results)
        )
        return results

    # =========================================================================
    # Alerts
    # =========================================================================

    def create_alert(
        self,
        property_id: str,
        profile_id: Optional[str],
        alert_type: str,
        channel: str,
        match_score: float,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """Create an alert record."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO property_alert
                        (property_id, profile_id, user_id, alert_type, channel, match_score)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING alert_id
                    """, (property_id, profile_id, user_id, alert_type, channel, match_score))
                    alert_id = cur.fetchone()[0]
                    conn.commit()

                    return {"success": True, "alert_id": str(alert_id)}

        except Exception as e:
            log_with_context(logger, "error", "Alert creation failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_alert_stats(self, user_id: str = "1", days: int = 7) -> Dict[str, Any]:
        """Get alert statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(*) FILTER (WHERE alert_type = 'instant') as instant,
                            COUNT(*) FILTER (WHERE alert_type = 'digest') as digest,
                            COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                            COUNT(*) FILTER (WHERE status = 'dismissed') as dismissed
                        FROM property_alert
                        WHERE user_id = %s
                          AND created_at > NOW() - INTERVAL '%s days'
                    """, (user_id, days))
                    row = cur.fetchone()

                    total = row[0] or 0
                    clicked = row[3] or 0

                    return {
                        "total_alerts": total,
                        "instant_alerts": row[1] or 0,
                        "digest_alerts": row[2] or 0,
                        "clicked": clicked,
                        "dismissed": row[4] or 0,
                        "click_rate": round(clicked / total, 3) if total > 0 else 0.0
                    }

        except Exception as e:
            log_with_context(logger, "error", "Stats query failed", error=str(e))
            return {"error": str(e)}


# =============================================================================
# Singleton
# =============================================================================

_service: Optional[RealEstateService] = None


def get_real_estate_service() -> RealEstateService:
    """Get or create real estate service singleton."""
    global _service
    if _service is None:
        _service = RealEstateService()
    return _service
