"""
Entities Router

Extracted from main.py - Entity Extraction endpoints:
- Extract all entities
- Extract people
- Extract dates
"""

from fastapi import APIRouter

from ..observability import get_logger

logger = get_logger("jarvis.entities")
router = APIRouter(prefix="/entities", tags=["entities"])


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/extract")
def extract_entities_endpoint(
    text: str,
    user_id: int = None,
    people: bool = True,
    projects: bool = True,
    dates: bool = True,
    orgs: bool = True,
    known_only: bool = False
):
    """Extract entities (people, projects, dates) from text"""
    from .. import entity_extractor
    result = entity_extractor.extract_entities(
        text=text,
        user_id=user_id,
        extract_people_flag=people,
        extract_projects_flag=projects,
        extract_dates_flag=dates,
        extract_orgs_flag=orgs,
        known_only=known_only
    )
    return result.to_dict()


@router.get("/people")
def extract_people_endpoint(text: str, known_only: bool = False):
    """Extract only people from text"""
    from .. import entity_extractor
    entities = entity_extractor.extract_people(text, known_only=known_only)
    return {
        "entities": [e.__dict__ for e in entities],
        "count": len(entities)
    }


@router.get("/dates")
def extract_dates_endpoint(text: str):
    """Extract only dates/times from text"""
    from .. import entity_extractor
    entities = entity_extractor.extract_dates(text)
    return {
        "entities": [e.__dict__ for e in entities],
        "count": len(entities)
    }
