"""
Real Estate Alerter Service

Sends property alerts via notification_service based on match scores.
Integrates with Telegram, Email, and Dashboard.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..observability import get_logger, log_with_context
from ..notification_service import send_notification
from ..models.property import (
    Property, MatchResult, AlertPriority
)

logger = get_logger("jarvis.real_estate_alerter")


class RealEstateAlerter:
    """
    Handles alerting for real estate matches.

    Alert priorities:
    - INSTANT (score >= 0.85): Priority 1, immediate Telegram
    - HIGH (score >= 0.65): Priority 2, Telegram + Dashboard
    - NORMAL (score >= 0.40): Priority 3, Dashboard only
    - LOW (score < 0.40): No alert, just logged
    """

    # Event types for notification templates
    EVENT_INSTANT = "real_estate_instant"
    EVENT_HIGH = "real_estate_high"
    EVENT_DAILY = "real_estate_daily_digest"

    async def send_match_alert(
        self,
        property: Property,
        match: MatchResult,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Send alert for a property match.

        Returns:
            {sent: bool, channels: [...], notification_id: str}
        """
        if match.priority == AlertPriority.LOW:
            log_with_context(
                logger, "debug", "Skipping LOW priority match",
                property_id=property.id,
                score=match.total_score
            )
            return {"sent": False, "reason": "low_priority"}

        # Build context for template
        context = self._build_context(property, match)

        # Determine channels and priority
        if match.priority == AlertPriority.INSTANT:
            channels = ["telegram", "dashboard"]
            priority = 1
            event_type = self.EVENT_INSTANT
        elif match.priority == AlertPriority.HIGH:
            channels = ["telegram", "dashboard"]
            priority = 2
            event_type = self.EVENT_HIGH
        else:  # NORMAL
            channels = ["dashboard"]
            priority = 3
            event_type = self.EVENT_HIGH

        # Send via notification service
        result = await send_notification(
            user_id=user_id,
            event_type=event_type,
            event_id=property.id,
            context=context,
            priority=priority,
            channels=channels
        )

        log_with_context(
            logger, "info", "Alert sent",
            property_id=property.id,
            score=match.total_score,
            priority=match.priority.value,
            channels=result.get("channels_sent", [])
        )

        return {
            "sent": result.get("status") == "sent",
            "channels": result.get("channels_sent", []),
            "notification_ids": result.get("notification_ids", []),
            "skipped": result.get("skipped", [])
        }

    def _build_context(self, property: Property, match: MatchResult) -> Dict[str, Any]:
        """Build notification context from property and match."""
        # Price display
        if property.rent_chf:
            price_str = f"CHF {property.rent_chf:,}/Mt."
        elif property.price_chf:
            price_str = f"CHF {property.price_chf:,}"
        else:
            price_str = "Preis auf Anfrage"

        # Location display
        loc = property.location
        location_str = " ".join(filter(None, [
            loc.postal_code,
            loc.city,
            f"({loc.canton})" if loc.canton else None
        ]))

        # Score emoji
        if match.total_score >= 0.85:
            score_emoji = "🔥"
        elif match.total_score >= 0.65:
            score_emoji = "⭐"
        else:
            score_emoji = "📍"

        # Build message
        title = f"{score_emoji} {property.title}"
        body = (
            f"📍 {location_str}\n"
            f"💰 {price_str}\n"
            f"🏠 {property.rooms or '?'} Zimmer"
        )
        if property.living_area_m2:
            body += f" | {property.living_area_m2:.0f} m²"

        body += f"\n\n📊 Match-Score: {match.total_score:.0%}"

        # Score breakdown
        bd = match.breakdown
        body += f"\n  • Preis: {bd.price_score:.0%}"
        body += f"\n  • Lage: {bd.location_score:.0%}"
        body += f"\n  • Grösse: {bd.size_score:.0%}"

        # Add URL if available
        if property.source_url:
            body += f"\n\n🔗 {property.source_url}"

        # Action buttons for Telegram
        action_buttons = []
        if property.source_url:
            action_buttons.append({
                "label": "🔗 Inserat öffnen",
                "action": "open_url",
                "url": property.source_url
            })
        action_buttons.append({
            "label": "✅ Interessant",
            "action": "property_click",
            "property_id": property.id
        })
        action_buttons.append({
            "label": "❌ Nicht interessant",
            "action": "property_dismiss",
            "property_id": property.id
        })

        return {
            "title": title,
            "body": body,
            "property_id": property.id,
            "property_title": property.title,
            "price": price_str,
            "location": location_str,
            "rooms": property.rooms,
            "living_area": property.living_area_m2,
            "score": match.total_score,
            "score_percent": f"{match.total_score:.0%}",
            "source": property.source,
            "source_url": property.source_url,
            "action_buttons": action_buttons,
            # Templates
            "response_template": match.response_template,
            "call_script": match.call_script,
        }

    async def send_daily_digest(
        self,
        matches: List[tuple],  # List of (Property, MatchResult)
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Send daily digest of all matches.

        Args:
            matches: List of (Property, MatchResult) tuples
        """
        if not matches:
            return {"sent": False, "reason": "no_matches"}

        # Sort by score
        sorted_matches = sorted(matches, key=lambda x: x[1].total_score, reverse=True)

        # Build digest
        lines = [f"🏠 *Real Estate Digest* - {len(matches)} neue Objekte\n"]

        for i, (prop, match) in enumerate(sorted_matches[:10], 1):
            # Price
            if prop.rent_chf:
                price = f"CHF {prop.rent_chf:,}/Mt."
            elif prop.price_chf:
                price = f"CHF {prop.price_chf:,}"
            else:
                price = "k.A."

            loc = prop.location.city or prop.location.postal_code or "?"

            lines.append(
                f"{i}. *{prop.title[:40]}*\n"
                f"   {loc} | {price} | {prop.rooms or '?'} Zi. | "
                f"Score: {match.total_score:.0%}"
            )
            if prop.source_url:
                lines.append(f"   🔗 {prop.source_url}")
            lines.append("")

        if len(matches) > 10:
            lines.append(f"_... und {len(matches) - 10} weitere_")

        body = "\n".join(lines)

        result = await send_notification(
            user_id=user_id,
            event_type=self.EVENT_DAILY,
            event_id=f"digest_{datetime.utcnow().strftime('%Y%m%d')}",
            context={
                "title": f"🏠 {len(matches)} neue Immobilien",
                "body": body,
                "match_count": len(matches),
                "top_score": sorted_matches[0][1].total_score if sorted_matches else 0
            },
            priority=3,
            channels=["telegram", "email"]
        )

        log_with_context(
            logger, "info", "Daily digest sent",
            matches=len(matches),
            channels=result.get("channels_sent", [])
        )

        return {
            "sent": result.get("status") == "sent",
            "match_count": len(matches),
            "channels": result.get("channels_sent", [])
        }


# =============================================================================
# Singleton
# =============================================================================

_alerter: Optional[RealEstateAlerter] = None


def get_real_estate_alerter() -> RealEstateAlerter:
    """Get or create alerter singleton."""
    global _alerter
    if _alerter is None:
        _alerter = RealEstateAlerter()
    return _alerter
