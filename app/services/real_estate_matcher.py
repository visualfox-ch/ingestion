"""
Real Estate Matcher Service

Hard filters (knockout) + soft scoring for property matching.
Adapted from Claude Cowork for Jarvis integration.
"""
from __future__ import annotations
import math
from datetime import datetime, timedelta
from typing import List, Optional

from ..observability import get_logger, log_with_context
from ..models.property import (
    AlertPriority, MatchResult, Property, PropertyType,
    ScoreBreakdown, SearchProfile,
)

logger = get_logger("jarvis.real_estate_matcher")


class RealEstateMatcherService:
    """
    Property matching engine.

    Strategy:
    - Hard filters: knockout criteria (transaction type, budget, rooms, location)
    - Soft scoring: weighted scores for price, location, size, features
    - Bonus scoring: keywords, freshness
    """

    def match(self, property: Property, profile: SearchProfile) -> Optional[MatchResult]:
        """
        Match a property against a search profile.
        Returns None if hard filters fail.
        """
        # Hard filters - knockout
        if not self._passes_hard_filters(property, profile):
            return None

        # Soft scoring
        breakdown = self._compute_scores(property, profile)

        total = (
            breakdown.price_score * profile.weight_price
            + breakdown.location_score * profile.weight_location
            + breakdown.size_score * profile.weight_size
            + breakdown.features_score * profile.weight_features
            + breakdown.keyword_bonus
            + breakdown.freshness_bonus
        )
        total = max(0.0, min(1.0, total))

        # Priority
        priority = self._determine_priority(total, profile)

        # Templates
        response_tpl = self._generate_response_template(property, total)
        call_script = self._generate_call_script(property, total)

        log_with_context(
            logger, "debug", "Property matched",
            property_id=property.id,
            profile_id=profile.id,
            score=round(total, 3),
            priority=priority.value
        )

        return MatchResult(
            property_id=property.id,
            profile_id=profile.id,
            total_score=round(total, 3),
            priority=priority,
            breakdown=breakdown,
            response_template=response_tpl,
            call_script=call_script,
        )

    def match_all(
        self,
        properties: List[Property],
        profile: SearchProfile
    ) -> List[MatchResult]:
        """Match multiple properties, sorted by score descending."""
        results = []
        for prop in properties:
            result = self.match(prop, profile)
            if result:
                results.append(result)
        results.sort(key=lambda r: r.total_score, reverse=True)

        log_with_context(
            logger, "info", "Batch match complete",
            profile_id=profile.id,
            properties_checked=len(properties),
            matches_found=len(results)
        )
        return results

    # =========================================================================
    # Hard Filters
    # =========================================================================

    def _passes_hard_filters(self, prop: Property, profile: SearchProfile) -> bool:
        """Knockout criteria - if any fails, property is rejected."""

        # Transaction type must match
        if prop.transaction_type != profile.transaction_type:
            return False

        # Property type (if specified)
        if profile.property_types:
            if prop.property_type not in profile.property_types:
                if prop.property_type != PropertyType.OTHER:
                    return False

        # Budget (20% tolerance above max)
        price = prop.price_chf if profile.transaction_type.value == "buy" else prop.rent_chf
        if price is not None:
            if profile.price.max_chf and price > profile.price.max_chf * 1.20:
                return False
            if profile.price.min_chf and price < profile.price.min_chf * 0.80:
                return False

        # Rooms (0.5 room tolerance)
        if prop.rooms is not None:
            if profile.rooms.min_rooms and prop.rooms < profile.rooms.min_rooms - 0.5:
                return False
            if profile.rooms.max_rooms and prop.rooms > profile.rooms.max_rooms + 0.5:
                return False

        # Living area (20% tolerance below min)
        if prop.living_area_m2 is not None:
            if profile.living_area.min_m2:
                if prop.living_area_m2 < profile.living_area.min_m2 * 0.80:
                    return False

        # Geography
        if not self._passes_geo_filter(prop, profile):
            return False

        # Exclude keywords
        if profile.exclude_keywords:
            text = f"{prop.title} {prop.description or ''}".lower()
            for kw in profile.exclude_keywords:
                if kw.lower() in text:
                    return False

        return True

    def _passes_geo_filter(self, prop: Property, profile: SearchProfile) -> bool:
        """Check if property is in target region."""
        geo = profile.geo
        loc = prop.location

        # No geo filter = pass
        if not geo.cantons and not geo.postal_codes and not geo.cities and not geo.center_lat:
            return True

        # Canton match
        if geo.cantons and loc.canton:
            if loc.canton.upper() in [c.upper() for c in geo.cantons]:
                return True

        # Postal code match (including prefix matching)
        if geo.postal_codes and loc.postal_code:
            if loc.postal_code in geo.postal_codes:
                return True
            for plz in geo.postal_codes:
                if len(plz) < 4 and loc.postal_code.startswith(plz):
                    return True

        # City match
        if geo.cities and loc.city:
            city_lower = loc.city.lower()
            if any(c.lower() in city_lower or city_lower in c.lower() for c in geo.cities):
                return True

        # Radius around coordinate
        if geo.center_lat and geo.center_lon and geo.radius_km:
            if loc.lat and loc.lon:
                dist = self._haversine(geo.center_lat, geo.center_lon, loc.lat, loc.lon)
                if dist <= geo.radius_km:
                    return True

        # Geo filter defined but nothing matched
        if geo.cantons or geo.postal_codes or geo.cities:
            return False

        return True

    # =========================================================================
    # Soft Scoring
    # =========================================================================

    def _compute_scores(self, prop: Property, profile: SearchProfile) -> ScoreBreakdown:
        return ScoreBreakdown(
            price_score=self._score_price(prop, profile),
            location_score=self._score_location(prop, profile),
            size_score=self._score_size(prop, profile),
            features_score=self._score_features(prop, profile),
            keyword_bonus=self._score_keywords(prop, profile),
            freshness_bonus=self._score_freshness(prop),
        )

    def _score_price(self, prop: Property, profile: SearchProfile) -> float:
        """Price score: 1.0 if perfect, decreases with deviation."""
        price = prop.price_chf if profile.transaction_type.value == "buy" else prop.rent_chf
        if price is None:
            return 0.5  # Unknown = neutral

        max_p = profile.price.max_chf
        min_p = profile.price.min_chf

        if max_p and min_p:
            mid = (max_p + min_p) / 2
            range_half = (max_p - min_p) / 2 if max_p != min_p else max_p * 0.1
            deviation = abs(price - mid) / range_half if range_half else 0
            return max(0.0, 1.0 - deviation * 0.5)
        elif max_p:
            if price <= max_p:
                return 1.0
            over = (price - max_p) / max_p
            return max(0.0, 1.0 - over * 5)
        elif min_p:
            if price >= min_p:
                return 1.0
            under = (min_p - price) / min_p
            return max(0.0, 1.0 - under * 5)
        return 0.5

    def _score_location(self, prop: Property, profile: SearchProfile) -> float:
        """Location score based on proximity."""
        geo = profile.geo
        loc = prop.location

        # Exact postal code or city = 1.0
        if geo.postal_codes and loc.postal_code and loc.postal_code in geo.postal_codes:
            return 1.0
        if geo.cities and loc.city:
            if any(c.lower() == loc.city.lower() for c in geo.cities):
                return 1.0

        # Radius-based
        if geo.center_lat and geo.center_lon and geo.radius_km and loc.lat and loc.lon:
            dist = self._haversine(geo.center_lat, geo.center_lon, loc.lat, loc.lon)
            return max(0.0, 1.0 - (dist / geo.radius_km))

        # Canton match
        if geo.cantons and loc.canton:
            if loc.canton.upper() in [c.upper() for c in geo.cantons]:
                return 0.7

        return 0.3  # Unknown or far

    def _score_size(self, prop: Property, profile: SearchProfile) -> float:
        """Size score combining rooms and living area."""
        scores = []

        # Rooms
        if prop.rooms is not None and (profile.rooms.min_rooms or profile.rooms.max_rooms):
            target = (
                (profile.rooms.min_rooms or 0) + (profile.rooms.max_rooms or 20)
            ) / 2
            diff = abs(prop.rooms - target) / max(target, 1)
            scores.append(max(0.0, 1.0 - diff))

        # Living area
        if prop.living_area_m2 and (profile.living_area.min_m2 or profile.living_area.max_m2):
            target = (
                (profile.living_area.min_m2 or 0) + (profile.living_area.max_m2 or 500)
            ) / 2
            diff = abs(prop.living_area_m2 - target) / max(target, 1)
            scores.append(max(0.0, 1.0 - diff))

        return sum(scores) / len(scores) if scores else 0.5

    def _score_features(self, prop: Property, profile: SearchProfile) -> float:
        """Feature match score."""
        checks = []

        if profile.has_parking is not None and prop.has_parking is not None:
            checks.append(1.0 if prop.has_parking == profile.has_parking else 0.0)
        if profile.has_balcony is not None and prop.has_balcony is not None:
            checks.append(1.0 if prop.has_balcony == profile.has_balcony else 0.0)
        if profile.has_elevator is not None and prop.has_elevator is not None:
            checks.append(1.0 if prop.has_elevator == profile.has_elevator else 0.0)

        return sum(checks) / len(checks) if checks else 0.5

    def _score_keywords(self, prop: Property, profile: SearchProfile) -> float:
        """Keyword bonus: +0.05 per hit, max 0.15."""
        if not profile.keywords:
            return 0.0

        text = f"{prop.title} {prop.description or ''}".lower()
        hits = sum(1 for kw in profile.keywords if kw.lower() in text)
        return min(0.15, hits * 0.05)

    def _score_freshness(self, prop: Property) -> float:
        """Freshness bonus for new listings (up to +0.05)."""
        if not prop.published_at:
            return 0.0

        age_hours = (datetime.utcnow() - prop.published_at).total_seconds() / 3600
        if age_hours < 1:
            return 0.05
        elif age_hours < 6:
            return 0.03
        elif age_hours < 24:
            return 0.01
        return 0.0

    # =========================================================================
    # Priority & Templates
    # =========================================================================

    def _determine_priority(self, score: float, profile: SearchProfile) -> AlertPriority:
        if score >= profile.instant_threshold:
            return AlertPriority.INSTANT
        elif score >= profile.high_threshold:
            return AlertPriority.HIGH
        elif score >= profile.normal_threshold:
            return AlertPriority.NORMAL
        return AlertPriority.LOW

    def _generate_response_template(self, prop: Property, score: float) -> str:
        """Pre-filled email template for quick response."""
        contact_name = prop.contact.name or "Sehr geehrte Damen und Herren"
        return (
            f"Betreff: Anfrage zu {prop.title}\n\n"
            f"Guten Tag {contact_name},\n\n"
            f"mit grossem Interesse habe ich Ihr Inserat \"{prop.title}\" gesehen. "
            f"Das Objekt entspricht genau unseren Vorstellungen.\n\n"
            f"Gerne würde ich einen Besichtigungstermin vereinbaren. "
            f"Ich bin telefonisch und per E-Mail erreichbar.\n\n"
            f"Freundliche Grüsse\n"
            f"[Ihr Name]"
        )

    def _generate_call_script(self, prop: Property, score: float) -> str:
        """Call script for phone outreach."""
        price_info = ""
        if prop.price_chf:
            price_info = f"Preis: CHF {prop.price_chf:,}"
        elif prop.rent_chf:
            price_info = f"Miete: CHF {prop.rent_chf:,}/Mt."

        return (
            f"Objekt: {prop.title}\n"
            f"Ort: {prop.location.city or '?'} {prop.location.postal_code or ''}\n"
            f"{price_info}\n"
            f"Zimmer: {prop.rooms or '?'} | Fläche: {prop.living_area_m2 or '?'} m²\n"
            f"Match-Score: {score:.0%}\n\n"
            f"1. Vorstellen, Interesse am Objekt bekunden\n"
            f"2. Verfügbarkeit und Besichtigungstermin erfragen\n"
            f"3. Nach weiteren Details fragen (Nebenkosten, Zustand)\n"
            f"4. Termin fixieren oder Follow-up vereinbaren"
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in km between two coordinates."""
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# =============================================================================
# Singleton
# =============================================================================

_matcher: Optional[RealEstateMatcherService] = None


def get_real_estate_matcher() -> RealEstateMatcherService:
    """Get or create matcher service singleton."""
    global _matcher
    if _matcher is None:
        _matcher = RealEstateMatcherService()
    return _matcher
