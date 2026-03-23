"""
Real Estate Geo Scoring Service

Ring model + Quartier quality + ÖV/Waldnähe scoring for Zürich region.
Adapted from Claude Cowork for Jarvis integration.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.real_estate_geo")


# =============================================================================
# Zürich Geo Data
# =============================================================================

ZURICH_CENTER = (47.3769, 8.5417)

# Priorisierte Quartiere: (lat, lon, quality_score, waldnähe_score, öv_score)
ZURICH_QUARTIERE: Dict[str, Tuple[float, float, float, float, float]] = {
    "witikon":        (47.3574, 8.5894, 0.90, 0.95, 0.70),
    "fluntern":       (47.3800, 8.5600, 0.95, 0.90, 0.80),
    "schwamendingen": (47.4050, 8.5650, 0.65, 0.70, 0.80),
    "affoltern":      (47.4230, 8.5150, 0.60, 0.75, 0.70),
    "oerlikon":       (47.4100, 8.5450, 0.70, 0.50, 0.95),
    "zürichberg":     (47.3750, 8.5700, 0.95, 0.95, 0.75),
    "höngg":          (47.4000, 8.4950, 0.80, 0.85, 0.75),
    "wipkingen":      (47.3940, 8.5250, 0.75, 0.60, 0.90),
    "altstetten":     (47.3900, 8.4850, 0.60, 0.40, 0.85),
    "seefeld":        (47.3570, 8.5550, 0.90, 0.50, 0.90),
    "enge":           (47.3620, 8.5300, 0.85, 0.55, 0.95),
    "wollishofen":    (47.3420, 8.5250, 0.80, 0.65, 0.85),
    "leimbach":       (47.3280, 8.5150, 0.65, 0.80, 0.65),
    "adlisberg":      (47.3650, 8.5800, 0.90, 0.95, 0.60),
    "kreis_1":        (47.3720, 8.5400, 0.85, 0.20, 0.98),
    "kreis_4":        (47.3780, 8.5280, 0.70, 0.15, 0.98),
    "kreis_5":        (47.3860, 8.5200, 0.75, 0.20, 0.95),
}

# Umland with S-Bahn: (lat, lon, ring, öv_score)
UMLAND_GEMEINDEN: Dict[str, Tuple[float, float, int, float]] = {
    "adliswil":       (47.3100, 8.5250, 2, 0.80),
    "kilchberg":      (47.3200, 8.5400, 2, 0.75),
    "küsnacht":       (47.3180, 8.5800, 2, 0.85),
    "zollikon":       (47.3400, 8.5700, 2, 0.85),
    "wallisellen":    (47.4150, 8.5950, 2, 0.85),
    "dübendorf":      (47.3970, 8.6200, 2, 0.80),
    "dietikon":       (47.4050, 8.4000, 2, 0.85),
    "schlieren":      (47.3970, 8.4500, 2, 0.85),
    "opfikon":        (47.4300, 8.5700, 2, 0.80),
    "regensdorf":     (47.4350, 8.4700, 3, 0.70),
    "bülach":         (47.5200, 8.5400, 3, 0.70),
    "uster":          (47.3500, 8.7200, 3, 0.75),
    "wetzikon":       (47.3250, 8.8000, 3, 0.65),
    "winterthur":     (47.5000, 8.7250, 3, 0.80),
    "baden":          (47.4730, 8.3070, 3, 0.75),
    "thalwil":        (47.2920, 8.5600, 2, 0.80),
    "horgen":         (47.2600, 8.6000, 3, 0.75),
    "meilen":         (47.2750, 8.6450, 3, 0.70),
    "stäfa":          (47.2400, 8.7250, 3, 0.65),
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GeoZone:
    """Search zone definition with priority."""
    name: str
    center_lat: float
    center_lon: float
    radius_km: float
    ring: int = 1            # 1=Core, 2=City border, 3=Umland
    base_score: float = 1.0  # Score multiplier


@dataclass
class GeoProfile:
    """
    Extended geo configuration for search profiles.
    Replaces simple GeoFilter when detailed scoring is needed.
    """
    zones: List[GeoZone] = field(default_factory=list)
    waldnaehe_weight: float = 0.15
    oev_weight: float = 0.15
    quartier_weight: float = 0.10
    auto_expand: bool = True
    max_ring: int = 2

    @classmethod
    def zurich_default(cls) -> "GeoProfile":
        """Default profile for Zürich with 3 rings."""
        return cls(
            zones=[
                GeoZone("Zürich Stadt", 47.3769, 8.5417, 6.0, ring=1, base_score=1.0),
                GeoZone("Zürich Umland Nah", 47.3769, 8.5417, 12.0, ring=2, base_score=0.80),
                GeoZone("Zürich Umland Weit", 47.3769, 8.5417, 20.0, ring=3, base_score=0.55),
            ],
        )


# =============================================================================
# Geo Scoring Service
# =============================================================================

class GeoScoringService:
    """
    Detailed geo scoring based on:
    1. Ring membership (which zone is the property in?)
    2. Waldnähe (proximity to forests/green areas)
    3. ÖV connection (public transport quality)
    4. Quartier quality (prioritized neighborhoods)
    """

    def __init__(self, profile: Optional[GeoProfile] = None):
        self.profile = profile or GeoProfile.zurich_default()

    def compute_geo_score(
        self,
        lat: Optional[float],
        lon: Optional[float],
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
    ) -> Dict:
        """
        Compute combined geo score.

        Returns:
            {
                "total": 0.0-1.0,
                "ring": 1|2|3|None,
                "ring_score": 0.0-1.0,
                "waldnaehe_score": 0.0-1.0,
                "oev_score": 0.0-1.0,
                "quartier_score": 0.0-1.0,
                "matched_zone": "name",
                "matched_quartier": "name" | None,
            }
        """
        result = {
            "total": 0.0,
            "ring": None,
            "ring_score": 0.0,
            "waldnaehe_score": 0.5,
            "oev_score": 0.5,
            "quartier_score": 0.5,
            "matched_zone": None,
            "matched_quartier": None,
        }

        # Step 1: Determine ring
        ring_score, ring, zone_name = self._compute_ring_score(lat, lon, city)
        result["ring"] = ring
        result["ring_score"] = ring_score
        result["matched_zone"] = zone_name

        # Step 2: Check quartier match
        q_score, q_wald, q_oev, q_name = self._match_quartier(lat, lon, city, postal_code)
        if q_name:
            result["matched_quartier"] = q_name
            result["quartier_score"] = q_score
            result["waldnaehe_score"] = q_wald
            result["oev_score"] = q_oev
        else:
            # Fallback: check Umland
            u_oev, u_ring, u_name = self._match_umland(city)
            if u_name:
                result["oev_score"] = u_oev
                if ring is None:
                    result["ring"] = u_ring
                    result["ring_score"] = 0.55 if u_ring == 2 else 0.35

        # Step 3: Total score
        p = self.profile
        base = result["ring_score"]
        bonus = (
            result["waldnaehe_score"] * p.waldnaehe_weight
            + result["oev_score"] * p.oev_weight
            + result["quartier_score"] * p.quartier_weight
        )
        # Base ~60%, bonuses ~40%
        result["total"] = min(1.0, base * 0.60 + bonus + 0.05)

        log_with_context(
            logger, "debug", "Geo score computed",
            total=round(result["total"], 3),
            ring=result["ring"],
            quartier=result["matched_quartier"]
        )

        return result

    def should_expand_search(self, current_results: int, min_results: int = 5) -> Optional[int]:
        """
        Returns next ring to expand to if too few results.
        Returns None if max_ring reached.
        """
        if current_results >= min_results:
            return None
        if not self.profile.auto_expand:
            return None
        for zone in self.profile.zones:
            if zone.ring > 1:
                return min(zone.ring, self.profile.max_ring)
        return None

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _compute_ring_score(
        self, lat: Optional[float], lon: Optional[float], city: Optional[str]
    ) -> Tuple[float, Optional[int], Optional[str]]:
        """Determine ring and score based on coordinates."""
        if lat is None or lon is None:
            # Fallback: check city name
            if city and "zürich" in city.lower():
                return (0.90, 1, "Zürich Stadt (Name-Match)")
            return (0.3, None, None)

        # Check distance to each zone
        for zone in sorted(self.profile.zones, key=lambda z: z.ring):
            dist = self._haversine(zone.center_lat, zone.center_lon, lat, lon)
            if dist <= zone.radius_km:
                # Score decreases linearly within zone
                inner_score = 1.0 - (dist / zone.radius_km) * 0.3
                return (zone.base_score * inner_score, zone.ring, zone.name)

        return (0.1, None, None)

    def _match_quartier(
        self,
        lat: Optional[float],
        lon: Optional[float],
        city: Optional[str],
        postal_code: Optional[str],
    ) -> Tuple[float, float, float, Optional[str]]:
        """Check if property is in a known quartier."""

        # Name-based match
        if city:
            city_lower = city.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")
            for q_name, (q_lat, q_lon, q_qual, q_wald, q_oev) in ZURICH_QUARTIERE.items():
                q_search = q_name.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")
                if q_search in city_lower or city_lower in q_search:
                    return (q_qual, q_wald, q_oev, q_name)

        # Coordinate-based match
        if lat and lon:
            best = None
            best_dist = 999.0
            for q_name, (q_lat, q_lon, q_qual, q_wald, q_oev) in ZURICH_QUARTIERE.items():
                dist = self._haversine(q_lat, q_lon, lat, lon)
                if dist < 1.5 and dist < best_dist:  # Within 1.5km
                    best_dist = dist
                    best = (q_qual, q_wald, q_oev, q_name)
            if best:
                return best

        return (0.5, 0.5, 0.5, None)

    def _match_umland(self, city: Optional[str]) -> Tuple[float, int, Optional[str]]:
        """Check if property is in a known Umland municipality."""
        if not city:
            return (0.5, 3, None)

        city_lower = city.lower()
        for g_name, (g_lat, g_lon, g_ring, g_oev) in UMLAND_GEMEINDEN.items():
            if g_name in city_lower or city_lower in g_name:
                return (g_oev, g_ring, g_name)

        return (0.5, 3, None)

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

_geo_service: Optional[GeoScoringService] = None


def get_geo_scoring_service(profile: Optional[GeoProfile] = None) -> GeoScoringService:
    """Get or create geo scoring service singleton."""
    global _geo_service
    if _geo_service is None:
        _geo_service = GeoScoringService(profile)
    return _geo_service
