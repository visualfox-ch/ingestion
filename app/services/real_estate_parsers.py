"""
Real Estate Email Parsers

Parses property listings from email alerts (Homegate, ImmoScout24, etc.).
Used by the email ingest endpoint.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import json
from dataclasses import dataclass
from abc import ABC, abstractmethod

from ..observability import get_logger, log_with_context
from ..models.property import (
    Property, PropertyType, TransactionType, GeoLocation, Contact
)

logger = get_logger("jarvis.real_estate_parsers")


# =============================================================================
# Base Parser
# =============================================================================

@dataclass
class ParsedProperty:
    """Raw parsed data before conversion to Property model."""
    title: str
    price: Optional[int] = None
    price_type: str = "rent"  # rent or sale
    rooms: Optional[float] = None
    living_area_m2: Optional[float] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    canton: Optional[str] = None
    address: Optional[str] = None
    external_id: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    features: Dict[str, Any] = None
    raw_html: Optional[str] = None


class EmailParser(ABC):
    """Base class for email parsers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source name (e.g., 'homegate')."""
        pass

    @property
    @abstractmethod
    def from_patterns(self) -> List[str]:
        """Email sender patterns to match."""
        pass

    @abstractmethod
    def parse(self, subject: str, body: str, from_address: str) -> List[ParsedProperty]:
        """Parse email and return list of properties."""
        pass

    def to_property(self, parsed: ParsedProperty) -> Property:
        """Convert ParsedProperty to Property model."""
        tx_type = TransactionType.BUY if parsed.price_type == "sale" else TransactionType.RENT

        return Property(
            id=f"{self.source_name}:{parsed.external_id or hash(parsed.title)}",
            external_id=parsed.external_id or str(hash(parsed.title)),
            source=self.source_name,
            source_url=parsed.url,
            title=parsed.title,
            description=parsed.description,
            transaction_type=tx_type,
            property_type=PropertyType.APARTMENT,  # Could be enhanced
            price_chf=parsed.price if tx_type == TransactionType.BUY else None,
            rent_chf=parsed.price if tx_type == TransactionType.RENT else None,
            rooms=parsed.rooms,
            living_area_m2=parsed.living_area_m2,
            location=GeoLocation(
                city=parsed.city,
                postal_code=parsed.postal_code,
                canton=parsed.canton,
                address=parsed.address
            ),
            contact=Contact(
                name=parsed.contact_name,
                phone=parsed.contact_phone,
                email=parsed.contact_email
            ),
            images=parsed.images or [],
            has_balcony=parsed.features.get("balcony") if parsed.features else None,
            has_parking=parsed.features.get("parking") if parsed.features else None,
            has_elevator=parsed.features.get("elevator") if parsed.features else None,
            raw_data={"html": parsed.raw_html} if parsed.raw_html else None
        )


# =============================================================================
# Homegate Parser
# =============================================================================

class HomegateParser(EmailParser):
    """Parser for Homegate.ch email alerts."""

    @property
    def source_name(self) -> str:
        return "homegate"

    @property
    def from_patterns(self) -> List[str]:
        return ["@homegate.ch", "noreply@homegate.ch", "alert@homegate.ch"]

    def parse(self, subject: str, body: str, from_address: str) -> List[ParsedProperty]:
        """Parse Homegate email alert."""
        properties = []

        # Homegate sends HTML emails with multiple listings
        # Pattern: Each listing is in a div with property details

        # Extract individual listings
        # Typical Homegate format in email:
        # - Title with link
        # - Price (CHF X'XXX.– / Monat or CHF X'XXX'XXX.–)
        # - Rooms, m², location

        # Simple regex patterns for common formats
        listing_pattern = re.compile(
            r'(?P<title>[^<\n]{10,100})\s*'
            r'(?:CHF\s*)?(?P<price>[\d\'\.,]+)(?:\.–)?\s*'
            r'(?:/\s*(?P<price_period>Monat|Mt\.|month))?\s*'
            r'(?P<rooms>[\d\.]+)\s*(?:Zimmer|Zi\.?)?\s*'
            r'(?P<area>[\d\.]+)\s*m²?\s*'
            r'(?P<location>[^\n<]{5,50})',
            re.IGNORECASE
        )

        # URL pattern
        url_pattern = re.compile(
            r'https?://(?:www\.)?homegate\.ch/[^\s<>"\']+',
            re.IGNORECASE
        )

        # Find URLs first
        urls = url_pattern.findall(body)

        # Try to extract property IDs from URLs
        for url in urls:
            # Homegate URL format: /mieten/xxxxx or /kaufen/xxxxx
            id_match = re.search(r'/(?:mieten|kaufen|rent|buy)/(\d+)', url)
            if id_match:
                external_id = id_match.group(1)

                # Extract surrounding context
                prop = ParsedProperty(
                    title=f"Homegate Inserat {external_id}",
                    external_id=external_id,
                    url=url,
                    price_type="rent" if "/mieten/" in url or "/rent/" in url else "sale"
                )

                # Try to find more details near the URL
                url_pos = body.find(url)
                context = body[max(0, url_pos-500):url_pos+100]

                # Extract price
                price_match = re.search(r"CHF\s*([\d']+)", context)
                if price_match:
                    prop.price = int(price_match.group(1).replace("'", ""))

                # Extract rooms
                rooms_match = re.search(r"([\d\.]+)\s*(?:Zimmer|Zi)", context)
                if rooms_match:
                    prop.rooms = float(rooms_match.group(1))

                # Extract area
                area_match = re.search(r"([\d\.]+)\s*m²", context)
                if area_match:
                    prop.living_area_m2 = float(area_match.group(1))

                # Extract location (postal code + city)
                loc_match = re.search(r"(\d{4})\s+([A-Za-zäöüÄÖÜ\s-]+?)(?:\s|,|$)", context)
                if loc_match:
                    prop.postal_code = loc_match.group(1)
                    prop.city = loc_match.group(2).strip()

                properties.append(prop)

        log_with_context(
            logger, "info", "Homegate email parsed",
            listings_found=len(properties)
        )

        return properties


# =============================================================================
# ImmoScout24 Parser
# =============================================================================

class ImmoScout24Parser(EmailParser):
    """Parser for ImmoScout24.ch email alerts."""

    @property
    def source_name(self) -> str:
        return "immoscout24"

    @property
    def from_patterns(self) -> List[str]:
        return ["@immoscout24.ch", "noreply@immoscout24.ch", "alert@immoscout24.ch"]

    def parse(self, subject: str, body: str, from_address: str) -> List[ParsedProperty]:
        """Parse ImmoScout24 email alert."""
        properties = []

        # ImmoScout24 URL pattern
        url_pattern = re.compile(
            r'https?://(?:www\.)?immoscout24\.ch/[^\s<>"\']+',
            re.IGNORECASE
        )

        urls = url_pattern.findall(body)

        for url in urls:
            # ImmoScout24 URL format: /de/wohnung/mieten/ort-xxxx/id-xxxxx
            id_match = re.search(r'/id[/-](\d+)', url)
            if id_match:
                external_id = id_match.group(1)

                prop = ParsedProperty(
                    title=f"ImmoScout24 Inserat {external_id}",
                    external_id=external_id,
                    url=url,
                    price_type="rent" if "/mieten/" in url else "sale"
                )

                # Extract context around URL
                url_pos = body.find(url)
                context = body[max(0, url_pos-500):url_pos+100]

                # Price
                price_match = re.search(r"CHF\s*([\d']+)", context)
                if price_match:
                    prop.price = int(price_match.group(1).replace("'", ""))

                # Rooms
                rooms_match = re.search(r"([\d\.]+)\s*(?:Zimmer|Zi|rooms)", context, re.IGNORECASE)
                if rooms_match:
                    prop.rooms = float(rooms_match.group(1))

                # Area
                area_match = re.search(r"([\d\.]+)\s*m²", context)
                if area_match:
                    prop.living_area_m2 = float(area_match.group(1))

                # Location from URL
                loc_match = re.search(r'/ort[/-]([a-z\-]+)', url, re.IGNORECASE)
                if loc_match:
                    prop.city = loc_match.group(1).replace("-", " ").title()

                properties.append(prop)

        log_with_context(
            logger, "info", "ImmoScout24 email parsed",
            listings_found=len(properties)
        )

        return properties


# =============================================================================
# Flatfox Parser
# =============================================================================

class FlatfoxParser(EmailParser):
    """Parser for Flatfox.ch email alerts."""

    @property
    def source_name(self) -> str:
        return "flatfox"

    @property
    def from_patterns(self) -> List[str]:
        return ["@flatfox.ch", "noreply@flatfox.ch"]

    def parse(self, subject: str, body: str, from_address: str) -> List[ParsedProperty]:
        """Parse Flatfox email alert."""
        properties = []

        url_pattern = re.compile(
            r'https?://(?:www\.)?flatfox\.ch/[^\s<>"\']+',
            re.IGNORECASE
        )

        urls = url_pattern.findall(body)

        for url in urls:
            # Flatfox URL: /de/flat/xxxxx/
            id_match = re.search(r'/flat/(\d+)', url)
            if id_match:
                external_id = id_match.group(1)

                prop = ParsedProperty(
                    title=f"Flatfox Inserat {external_id}",
                    external_id=external_id,
                    url=url,
                    price_type="rent"  # Flatfox is primarily rentals
                )

                url_pos = body.find(url)
                context = body[max(0, url_pos-500):url_pos+100]

                # Standard extraction
                price_match = re.search(r"CHF\s*([\d']+)", context)
                if price_match:
                    prop.price = int(price_match.group(1).replace("'", ""))

                rooms_match = re.search(r"([\d\.]+)\s*(?:Zimmer|Zi)", context, re.IGNORECASE)
                if rooms_match:
                    prop.rooms = float(rooms_match.group(1))

                area_match = re.search(r"([\d\.]+)\s*m²", context)
                if area_match:
                    prop.living_area_m2 = float(area_match.group(1))

                properties.append(prop)

        log_with_context(
            logger, "info", "Flatfox email parsed",
            listings_found=len(properties)
        )

        return properties


# =============================================================================
# Comparis Parser
# =============================================================================

class ComparisParser(EmailParser):
    """Parser for Comparis.ch email alerts."""

    @property
    def source_name(self) -> str:
        return "comparis"

    @property
    def from_patterns(self) -> List[str]:
        return ["@comparis.ch", "noreply@comparis.ch"]

    def parse(self, subject: str, body: str, from_address: str) -> List[ParsedProperty]:
        """Parse Comparis email alert."""
        properties = []

        url_pattern = re.compile(
            r'https?://(?:www\.)?comparis\.ch/immobilien/[^\s<>"\']+',
            re.IGNORECASE
        )

        urls = url_pattern.findall(body)

        for url in urls:
            id_match = re.search(r'/(\d+)(?:\?|$)', url)
            if id_match:
                external_id = id_match.group(1)

                prop = ParsedProperty(
                    title=f"Comparis Inserat {external_id}",
                    external_id=external_id,
                    url=url,
                    price_type="rent" if "mieten" in url.lower() else "sale"
                )

                url_pos = body.find(url)
                context = body[max(0, url_pos-500):url_pos+100]

                price_match = re.search(r"CHF\s*([\d']+)", context)
                if price_match:
                    prop.price = int(price_match.group(1).replace("'", ""))

                rooms_match = re.search(r"([\d\.]+)\s*(?:Zimmer|Zi)", context, re.IGNORECASE)
                if rooms_match:
                    prop.rooms = float(rooms_match.group(1))

                area_match = re.search(r"([\d\.]+)\s*m²", context)
                if area_match:
                    prop.living_area_m2 = float(area_match.group(1))

                properties.append(prop)

        log_with_context(
            logger, "info", "Comparis email parsed",
            listings_found=len(properties)
        )

        return properties


# =============================================================================
# Parser Registry
# =============================================================================

class ParserRegistry:
    """Registry of all available parsers."""

    def __init__(self):
        self._parsers: List[EmailParser] = [
            HomegateParser(),
            ImmoScout24Parser(),
            FlatfoxParser(),
            ComparisParser(),
        ]

    def get_parser(self, from_address: str) -> Optional[EmailParser]:
        """Get parser matching the from address."""
        from_lower = from_address.lower()
        for parser in self._parsers:
            for pattern in parser.from_patterns:
                if pattern.lower() in from_lower:
                    return parser
        return None

    def parse_email(
        self,
        from_address: str,
        subject: str,
        body: str
    ) -> List[Property]:
        """
        Parse email and return Property models.

        Returns empty list if no parser found or no properties extracted.
        """
        parser = self.get_parser(from_address)
        if not parser:
            log_with_context(
                logger, "warning", "No parser for email",
                from_address=from_address
            )
            return []

        try:
            parsed = parser.parse(subject, body, from_address)
            properties = [parser.to_property(p) for p in parsed]

            log_with_context(
                logger, "info", "Email parsed",
                source=parser.source_name,
                properties=len(properties)
            )

            return properties

        except Exception as e:
            log_with_context(
                logger, "error", "Parse failed",
                source=parser.source_name,
                error=str(e)
            )
            return []


# =============================================================================
# Singleton
# =============================================================================

_registry: Optional[ParserRegistry] = None


def get_parser_registry() -> ParserRegistry:
    """Get or create parser registry singleton."""
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    return _registry
