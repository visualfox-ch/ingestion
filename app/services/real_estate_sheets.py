"""
Real Estate Google Sheets Service

Manages property tracking spreadsheet via n8n webhooks.
Uses n8n as Google API gateway (handles OAuth2 token refresh).
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn
from ..models.property import Property, MatchResult

logger = get_logger("jarvis.real_estate_sheets")

# n8n webhook URL (internal network)
N8N_WEBHOOK_URL = "http://192.168.1.103:25678/webhook/real-estate-sheets"


class RealEstateSheetsService:
    """
    Google Sheets integration for real estate tracking.

    Uses n8n webhook to perform operations:
    - create_sheet: Create new tracking spreadsheet
    - add_property: Add property to spreadsheet
    - update_status: Update property status
    - get_properties: Get all properties from sheet
    """

    def __init__(self):
        self._spreadsheet_id: Optional[str] = None
        self._spreadsheet_url: Optional[str] = None
        self._load_config()

    def _load_config(self):
        """Load spreadsheet ID from database config."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT value FROM jarvis_config
                        WHERE key = 'real_estate_spreadsheet_id'
                    """)
                    row = cur.fetchone()
                    if row:
                        self._spreadsheet_id = row[0]

                    cur.execute("""
                        SELECT value FROM jarvis_config
                        WHERE key = 'real_estate_spreadsheet_url'
                    """)
                    row = cur.fetchone()
                    if row:
                        self._spreadsheet_url = row[0]
        except Exception as e:
            log_with_context(logger, "warning", "Config load failed", error=str(e))

    def _save_config(self, spreadsheet_id: str, spreadsheet_url: str):
        """Save spreadsheet ID to database config."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_config (key, value, description)
                        VALUES ('real_estate_spreadsheet_id', %s, 'Google Sheets ID for real estate tracking')
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """, (spreadsheet_id,))
                    cur.execute("""
                        INSERT INTO jarvis_config (key, value, description)
                        VALUES ('real_estate_spreadsheet_url', %s, 'Google Sheets URL for real estate tracking')
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """, (spreadsheet_url,))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "error", "Config save failed", error=str(e))

    def _call_n8n(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call n8n webhook."""
        try:
            response = requests.post(
                N8N_WEBHOOK_URL,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            log_with_context(logger, "error", "n8n call failed", error=str(e))
            return {"success": False, "error": str(e)}

    @property
    def spreadsheet_id(self) -> Optional[str]:
        """Get current spreadsheet ID."""
        return self._spreadsheet_id

    @property
    def spreadsheet_url(self) -> Optional[str]:
        """Get current spreadsheet URL."""
        return self._spreadsheet_url

    def create_spreadsheet(self, title: str = None) -> Dict[str, Any]:
        """
        Create a new tracking spreadsheet.

        Args:
            title: Spreadsheet title (default: "Jarvis Real Estate Tracker YYYY")

        Returns:
            {success: bool, spreadsheet_id: str, spreadsheet_url: str}
        """
        if title is None:
            title = f"Jarvis Real Estate Tracker {datetime.now().year}"

        result = self._call_n8n({
            "action": "create_sheet",
            "title": title
        })

        if result.get("success"):
            self._spreadsheet_id = result.get("spreadsheet_id")
            self._spreadsheet_url = result.get("spreadsheet_url")
            self._save_config(self._spreadsheet_id, self._spreadsheet_url)

            log_with_context(
                logger, "info", "Spreadsheet created",
                spreadsheet_id=self._spreadsheet_id,
                title=title
            )

        return result

    def ensure_spreadsheet(self) -> str:
        """Ensure spreadsheet exists, create if not."""
        if not self._spreadsheet_id:
            result = self.create_spreadsheet()
            if not result.get("success"):
                raise Exception(f"Failed to create spreadsheet: {result.get('error')}")
        return self._spreadsheet_id

    def add_property(
        self,
        property: Property,
        match: Optional[MatchResult] = None,
        status: str = "Neu"
    ) -> Dict[str, Any]:
        """
        Add property to tracking spreadsheet.

        Args:
            property: Property model
            match: Optional match result for score
            status: Initial status (default: "Neu")

        Returns:
            {success: bool}
        """
        spreadsheet_id = self.ensure_spreadsheet()

        # Format price
        if property.rent_chf:
            price = f"CHF {property.rent_chf:,}/Mt."
        elif property.price_chf:
            price = f"CHF {property.price_chf:,}"
        else:
            price = "k.A."

        # Format location
        loc = property.location
        location = " ".join(filter(None, [loc.postal_code, loc.city]))

        # Format score
        score = f"{match.total_score:.0%}" if match else ""

        result = self._call_n8n({
            "action": "add_property",
            "spreadsheet_id": spreadsheet_id,
            "property": {
                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "source": property.source,
                "title": property.title[:100] if property.title else "",
                "price": price,
                "rooms": property.rooms or "",
                "area": property.living_area_m2 or "",
                "location": location,
                "score": score,
                "status": status,
                "url": property.source_url or "",
                "property_id": property.id,
                "notes": ""
            }
        })

        if result.get("success"):
            log_with_context(
                logger, "info", "Property added to sheet",
                property_id=property.id,
                title=property.title[:50]
            )

        return result

    def update_status(
        self,
        property_id: str,
        status: str,
        notes: str = None
    ) -> Dict[str, Any]:
        """
        Update property status in spreadsheet.

        Args:
            property_id: Property ID to update
            status: New status (Neu, Kontaktiert, Besichtigung, Abgelehnt, Favorit)
            notes: Optional notes

        Returns:
            {success: bool}
        """
        if not self._spreadsheet_id:
            return {"success": False, "error": "No spreadsheet configured"}

        result = self._call_n8n({
            "action": "update_status",
            "spreadsheet_id": self._spreadsheet_id,
            "property_id": property_id,
            "status": status,
            "notes": notes or ""
        })

        if result.get("success"):
            log_with_context(
                logger, "info", "Property status updated",
                property_id=property_id,
                status=status
            )

        return result

    def get_properties(self) -> List[Dict[str, Any]]:
        """
        Get all properties from spreadsheet.

        Returns:
            List of property dictionaries
        """
        if not self._spreadsheet_id:
            return []

        result = self._call_n8n({
            "action": "get_properties",
            "spreadsheet_id": self._spreadsheet_id
        })

        if result.get("success"):
            return result.get("properties", [])
        return []

    def get_stats(self) -> Dict[str, Any]:
        """Get property statistics from sheet."""
        properties = self.get_properties()

        if not properties:
            return {"total": 0}

        status_counts = {}
        for prop in properties:
            status = prop.get("Status", "Unbekannt")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "total": len(properties),
            "by_status": status_counts,
            "spreadsheet_url": self._spreadsheet_url
        }


# =============================================================================
# Singleton
# =============================================================================

_sheets_service: Optional[RealEstateSheetsService] = None


def get_real_estate_sheets() -> RealEstateSheetsService:
    """Get or create sheets service singleton."""
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = RealEstateSheetsService()
    return _sheets_service
