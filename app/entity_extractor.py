"""
Entity Extraction Module
Extracts people, projects, and dates from text.
Links to Knowledge Layer and Active Projects.
"""
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.entities")


@dataclass
class ExtractedEntity:
    """Represents an extracted entity"""
    entity_type: str  # "person", "project", "date", "organization"
    value: str  # The extracted text
    normalized: str  # Normalized/canonical form
    start_pos: int  # Position in text
    end_pos: int
    confidence: float  # 0.0 - 1.0
    linked_id: Optional[str] = None  # ID in Knowledge Layer or Projects
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Result of entity extraction"""
    text: str
    entities: List[ExtractedEntity]
    person_count: int = 0
    project_count: int = 0
    date_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_length": len(self.text),
            "entities": [asdict(e) for e in self.entities],
            "person_count": self.person_count,
            "project_count": self.project_count,
            "date_count": self.date_count,
            "total_entities": len(self.entities)
        }


# Cache for known entities (refreshed periodically)
_known_people: Dict[str, Dict] = {}
_known_projects: Dict[str, Dict] = {}
_cache_timestamp: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # 5 minutes


def _refresh_cache_if_needed():
    """Refresh entity cache from Knowledge Layer and Projects"""
    global _known_people, _known_projects, _cache_timestamp

    now = datetime.now()
    if _cache_timestamp and (now - _cache_timestamp).total_seconds() < CACHE_TTL_SECONDS:
        return

    # Refresh people from Knowledge Layer
    try:
        from . import knowledge_db
        profiles = knowledge_db.get_all_person_profiles(status="active")
        _known_people = {}
        for p in profiles:
            person_id = p.get("person_id", "")
            name = p.get("name", "")
            if name:
                # Index by lowercase name for matching
                _known_people[name.lower()] = {
                    "person_id": person_id,
                    "name": name,
                    "org": p.get("org", ""),
                    "profile_type": p.get("profile_type", "")
                }
                # Also index by first name if multi-word
                parts = name.split()
                if len(parts) > 1:
                    _known_people[parts[0].lower()] = _known_people[name.lower()]
        log_with_context(logger, "debug", f"Cached {len(profiles)} people from Knowledge Layer")
    except Exception as e:
        log_with_context(logger, "warning", "Failed to refresh people cache", error=str(e))

    # Refresh projects from Active Projects
    try:
        from . import projects
        # Get all users' projects (use user_id=0 as a default, or get from all)
        # For now, we'll cache project names without user context
        _known_projects = {}
        # Projects are user-specific, so we can't easily cache all
        # Instead, we'll rely on pattern matching for common project names
        log_with_context(logger, "debug", "Project cache updated")
    except Exception as e:
        log_with_context(logger, "warning", "Failed to refresh projects cache", error=str(e))

    _cache_timestamp = now


def _load_user_projects(user_id: int) -> Dict[str, Dict]:
    """Load projects for a specific user"""
    try:
        from . import projects
        user_projects = projects.get_active_projects(user_id, include_paused=True)
        result = {}
        for p in user_projects:
            name_lower = p.name.lower()
            result[name_lower] = {
                "project_id": p.id,
                "name": p.name,
                "priority": p.priority,
                "status": p.status
            }
        return result
    except Exception as e:
        log_with_context(logger, "warning", "Failed to load user projects", error=str(e))
        return {}


# German and English date patterns
DATE_PATTERNS = [
    # Relative dates (German)
    (r'\b(heute)\b', 'today'),
    (r'\b(morgen)\b', 'tomorrow'),
    (r'\b(gestern)\b', 'yesterday'),
    (r'\b(übermorgen)\b', 'day_after_tomorrow'),
    (r'\b(vorgestern)\b', 'day_before_yesterday'),
    (r'\bnächste[rn]?\s+woche\b', 'next_week'),
    (r'\bletzte[rn]?\s+woche\b', 'last_week'),
    (r'\bdiese[rn]?\s+woche\b', 'this_week'),
    (r'\bnächste[rn]?\s+monat\b', 'next_month'),
    (r'\bletzte[rn]?\s+monat\b', 'last_month'),
    (r'\bdiese[rn]?\s+monat\b', 'this_month'),
    (r'\bam\s+(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b', 'weekday'),
    (r'\bnächsten?\s+(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b', 'next_weekday'),

    # Relative dates (English)
    (r'\b(today)\b', 'today'),
    (r'\b(tomorrow)\b', 'tomorrow'),
    (r'\b(yesterday)\b', 'yesterday'),
    (r'\bnext\s+week\b', 'next_week'),
    (r'\blast\s+week\b', 'last_week'),
    (r'\bthis\s+week\b', 'this_week'),
    (r'\bnext\s+month\b', 'next_month'),
    (r'\blast\s+month\b', 'last_month'),
    (r'\bthis\s+month\b', 'this_month'),
    (r'\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', 'weekday'),
    (r'\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', 'next_weekday'),

    # Absolute dates
    (r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', 'date_de'),  # 30.01.2026
    (r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', 'date_us'),    # 01/30/2026
    (r'\b(\d{4})-(\d{2})-(\d{2})\b', 'date_iso'),         # 2026-01-30

    # Quarter references
    (r'\bq([1-4])\s*(\d{4})?\b', 'quarter'),
    (r'\bende\s+q([1-4])\b', 'end_quarter'),
    (r'\bbis\s+ende\s+q([1-4])\b', 'until_end_quarter'),

    # Time expressions
    (r'\basap\b', 'asap'),
    (r'\bsofort\b', 'immediately'),
    (r'\bdringend\b', 'urgent'),
    (r'\bbald\b', 'soon'),
    (r'\bzeitnah\b', 'soon'),
]


def extract_dates(text: str) -> List[ExtractedEntity]:
    """Extract date/time expressions from text"""
    entities = []
    text_lower = text.lower()

    for pattern, date_type in DATE_PATTERNS:
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            entity = ExtractedEntity(
                entity_type="date",
                value=match.group(0),
                normalized=date_type,
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=0.9,
                metadata={"date_type": date_type}
            )
            entities.append(entity)

    return entities


def extract_people(text: str, known_only: bool = False) -> List[ExtractedEntity]:
    """Extract person names from text"""
    _refresh_cache_if_needed()

    entities = []
    text_lower = text.lower()

    # First, match against known people
    for name_lower, person_data in _known_people.items():
        # Use word boundaries for matching
        pattern = r'\b' + re.escape(name_lower) + r'\b'
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            entity = ExtractedEntity(
                entity_type="person",
                value=match.group(0),
                normalized=person_data["name"],
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=1.0,  # High confidence for known people
                linked_id=person_data["person_id"],
                metadata={
                    "org": person_data.get("org", ""),
                    "profile_type": person_data.get("profile_type", ""),
                    "source": "knowledge_layer"
                }
            )
            entities.append(entity)

    if not known_only:
        # Also look for capitalized name patterns (potential new people)
        # Pattern: Two capitalized words together (First Last)
        name_pattern = r'\b([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß]+)\b'
        for match in re.finditer(name_pattern, text):
            full_name = match.group(0)
            # Skip if already found as known person
            if any(e.value.lower() == full_name.lower() for e in entities):
                continue
            # Skip common non-name patterns
            skip_words = {
                "Von Der", "In Der", "Auf Der", "Bei Der", "New York", "Los Angeles",
                "Das Projekt", "Die Deadline", "Der Status", "Das Meeting",
                "Projekt Und", "Granada Projekt", "Vioso Projekt",
                "High Priority", "Low Priority", "Medium Priority"
            }
            if full_name in skip_words:
                continue
            # Skip if contains common project/date keywords
            skip_suffixes = ("Projekt", "Project", "Meeting", "Deadline", "Status", "Update")
            if any(full_name.endswith(s) for s in skip_suffixes):
                continue

            entity = ExtractedEntity(
                entity_type="person",
                value=full_name,
                normalized=full_name,
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=0.6,  # Lower confidence for unknown patterns
                metadata={"source": "pattern_match"}
            )
            entities.append(entity)

    return entities


def extract_projects(text: str, user_id: int = None) -> List[ExtractedEntity]:
    """Extract project references from text"""
    entities = []
    text_lower = text.lower()

    # Load user-specific projects if user_id provided
    user_projects = _load_user_projects(user_id) if user_id else {}

    # Match against known projects
    for name_lower, project_data in user_projects.items():
        pattern = r'\b' + re.escape(name_lower) + r'\b'
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            entity = ExtractedEntity(
                entity_type="project",
                value=match.group(0),
                normalized=project_data["name"],
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=1.0,
                linked_id=project_data["project_id"],
                metadata={
                    "priority": project_data.get("priority", 2),
                    "status": project_data.get("status", ""),
                    "source": "active_projects"
                }
            )
            entities.append(entity)

    # Common project-related patterns (even if not in Active Projects)
    project_patterns = [
        (r'\b(projekt|project)\s+([A-Za-z][A-Za-z0-9_-]{2,})\b', 2),  # "Projekt X" (min 3 chars)
        (r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)?)\s+(projekt|project)\b', 1),  # "X Projekt"
    ]
    # Words that shouldn't be matched as project names
    skip_project_words = {"und", "oder", "mit", "für", "the", "and", "for", "with"}

    for pattern, group_idx in project_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            project_name = match.group(group_idx) if group_idx else match.group(0)
            # Skip common words
            if project_name.lower() in skip_project_words:
                continue
            # Skip if already found
            if any(e.value.lower() == project_name.lower() for e in entities):
                continue

            entity = ExtractedEntity(
                entity_type="project",
                value=match.group(0),
                normalized=project_name,
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=0.7,
                metadata={"source": "pattern_match"}
            )
            entities.append(entity)

    return entities


def extract_organizations(text: str) -> List[ExtractedEntity]:
    """Extract organization names from text"""
    entities = []

    # Common organization suffixes
    org_patterns = [
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(GmbH|AG|Inc|LLC|Ltd|SE|SA)\b',
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(Technologies?|Solutions?|Systems?|Software)\b',
    ]

    for pattern in org_patterns:
        for match in re.finditer(pattern, text):
            entity = ExtractedEntity(
                entity_type="organization",
                value=match.group(0),
                normalized=match.group(0),
                start_pos=match.start(),
                end_pos=match.end(),
                confidence=0.8,
                metadata={"source": "pattern_match"}
            )
            entities.append(entity)

    return entities


def extract_entities(
    text: str,
    user_id: int = None,
    extract_people_flag: bool = True,
    extract_projects_flag: bool = True,
    extract_dates_flag: bool = True,
    extract_orgs_flag: bool = True,
    known_only: bool = False
) -> ExtractionResult:
    """
    Extract all entity types from text.

    Args:
        text: Input text to analyze
        user_id: User ID for loading their projects
        extract_people_flag: Whether to extract people
        extract_projects_flag: Whether to extract projects
        extract_dates_flag: Whether to extract dates
        extract_orgs_flag: Whether to extract organizations
        known_only: Only return entities that match known entries

    Returns:
        ExtractionResult with all found entities
    """
    all_entities = []

    if extract_people_flag:
        all_entities.extend(extract_people(text, known_only=known_only))

    if extract_projects_flag:
        all_entities.extend(extract_projects(text, user_id=user_id))

    if extract_dates_flag:
        all_entities.extend(extract_dates(text))

    if extract_orgs_flag:
        all_entities.extend(extract_organizations(text))

    # Remove duplicates and overlapping entities
    # Prefer higher confidence and linked entities
    seen_positions = set()
    unique_entities = []

    # Sort by: linked_id (prioritize linked), confidence (desc), then position
    sorted_entities = sorted(
        all_entities,
        key=lambda e: (e.linked_id is not None, e.confidence, -e.start_pos),
        reverse=True
    )

    for e in sorted_entities:
        # Check if this entity overlaps with already added ones
        overlaps = False
        for pos in range(e.start_pos, e.end_pos):
            if pos in seen_positions:
                overlaps = True
                break

        if not overlaps:
            unique_entities.append(e)
            # Mark all positions as seen
            for pos in range(e.start_pos, e.end_pos):
                seen_positions.add(pos)

    # Sort by position
    unique_entities.sort(key=lambda e: e.start_pos)

    # Count by type
    person_count = sum(1 for e in unique_entities if e.entity_type == "person")
    project_count = sum(1 for e in unique_entities if e.entity_type == "project")
    date_count = sum(1 for e in unique_entities if e.entity_type == "date")

    log_with_context(logger, "debug", "Entities extracted",
                    total=len(unique_entities),
                    people=person_count,
                    projects=project_count,
                    dates=date_count)

    return ExtractionResult(
        text=text,
        entities=unique_entities,
        person_count=person_count,
        project_count=project_count,
        date_count=date_count
    )


def build_entity_context(result: ExtractionResult) -> Optional[str]:
    """Build context string from extracted entities for agent prompt"""
    if not result.entities:
        return None

    lines = ["=== DETECTED ENTITIES ==="]

    # Group by type
    people = [e for e in result.entities if e.entity_type == "person" and e.linked_id]
    projects = [e for e in result.entities if e.entity_type == "project" and e.linked_id]
    dates = [e for e in result.entities if e.entity_type == "date"]

    if people:
        lines.append("**People mentioned (from Knowledge Layer):**")
        for p in people:
            org_info = f" ({p.metadata.get('org')})" if p.metadata.get('org') else ""
            lines.append(f"- {p.normalized}{org_info}")

    if projects:
        lines.append("**Projects mentioned (from Active Projects):**")
        for p in projects:
            priority = p.metadata.get('priority', 2)
            prio_label = {1: "HIGH", 2: "MEDIUM", 3: "LOW"}.get(priority, "")
            lines.append(f"- {p.normalized} [{prio_label}]")

    if dates:
        lines.append("**Time references:**")
        for d in dates:
            lines.append(f"- {d.value} ({d.normalized})")

    if len(lines) == 1:
        return None  # Only header, no content

    return "\n".join(lines)


def get_linked_person_context(person_id: str) -> Optional[Dict]:
    """Get full context for a linked person from Knowledge Layer"""
    try:
        from . import knowledge_db
        return knowledge_db.get_person_profile(person_id)
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get person context",
                        person_id=person_id, error=str(e))
        return None
