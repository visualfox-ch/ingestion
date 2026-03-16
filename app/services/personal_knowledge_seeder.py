"""
Personal Knowledge Seeder
Phase 19.3: Populates Jarvis with knowledge about Micha

Seeds initial facts, preferences, and context that Jarvis should know.
Can be extended via API or by editing this file.
"""

import json
from datetime import datetime
from typing import List, Dict, Any

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.personal_knowledge_seeder")


# =============================================================================
# PERSONAL FACTS ABOUT MICHA
# =============================================================================

PERSONAL_FACTS = [
    # Identity & Contact
    {
        "category": "identity",
        "fact": "Micha's full name is Michael Bohl",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "identity",
        "fact": "Micha's email is michael@projektil.ch",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "identity",
        "fact": "Micha lives in Switzerland",
        "confidence": 1.0,
        "source": "config"
    },

    # ADHD & Cognitive Style
    {
        "category": "adhd",
        "fact": "Micha has ADHD and benefits from clear, structured communication",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "For ADHD support: Break down complex tasks into small, concrete steps",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "For ADHD support: Use bullet points and numbered lists instead of long paragraphs",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "For ADHD support: Provide time estimates for tasks when possible",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "For ADHD support: Send reminders for important deadlines proactively",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "For ADHD support: Avoid overwhelming with too many options - suggest 2-3 max",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "Micha may hyperfocus on interesting problems - gently remind about time/breaks",
        "confidence": 0.9,
        "source": "config"
    },
    {
        "category": "adhd",
        "fact": "Context switching is cognitively expensive for Micha - batch similar tasks",
        "confidence": 0.9,
        "source": "config"
    },

    # Work & Business
    {
        "category": "work",
        "fact": "Micha runs Projektil GmbH, a software development company",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "work",
        "fact": "Micha also works with VisualFox on projects",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "work",
        "fact": "Micha is a technical person who understands code, architecture, and systems",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "work",
        "fact": "Micha prefers direct, no-bullshit communication over corporate speak",
        "confidence": 1.0,
        "source": "config"
    },

    # Communication Preferences
    {
        "category": "communication",
        "fact": "Micha prefers German for casual conversation, English is OK for technical topics",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "communication",
        "fact": "Micha appreciates humor and casual tone, not overly formal language",
        "confidence": 0.9,
        "source": "config"
    },
    {
        "category": "communication",
        "fact": "When giving updates, lead with the key info, details second",
        "confidence": 0.9,
        "source": "config"
    },
    {
        "category": "communication",
        "fact": "Micha doesn't need excessive confirmation - just do the thing and report back",
        "confidence": 0.9,
        "source": "config"
    },

    # Technical Preferences
    {
        "category": "technical",
        "fact": "Micha uses Mac (darwin) as primary development machine",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "technical",
        "fact": "Micha's home server/NAS is at 192.168.1.103 (jarvis-nas)",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "technical",
        "fact": "Jarvis runs in Docker on the NAS with PostgreSQL, Qdrant, Redis, Meilisearch",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "technical",
        "fact": "Micha prefers Python for backend, uses FastAPI",
        "confidence": 0.9,
        "source": "config"
    },

    # Projects & Interests
    {
        "category": "project",
        "fact": "Jarvis is Micha's personal AI assistant project - high priority",
        "confidence": 1.0,
        "source": "config"
    },
    {
        "category": "project",
        "fact": "Granada was an investment consideration (status: completed analysis)",
        "confidence": 0.8,
        "source": "conversation"
    },
    {
        "category": "project",
        "fact": "BEARS Projekt is a bear park investment opportunity in Arosa, Switzerland",
        "confidence": 0.8,
        "source": "conversation"
    },
]


# =============================================================================
# SEEDING FUNCTIONS
# =============================================================================

def seed_to_memory_store() -> Dict[str, Any]:
    """
    Seed personal facts to the SQLite memory store.

    Returns stats about what was seeded.
    """
    try:
        from .. import memory_store

        stats = {"added": 0, "skipped": 0, "errors": 0}

        for fact_data in PERSONAL_FACTS:
            try:
                # Check if fact already exists (avoid duplicates)
                existing = memory_store.get_facts(
                    category=fact_data["category"],
                    limit=100
                )

                fact_text = fact_data["fact"]
                already_exists = any(
                    f.get("fact", "").lower() == fact_text.lower()
                    for f in existing
                )

                if already_exists:
                    stats["skipped"] += 1
                    continue

                # Add the fact
                memory_store.add_fact(
                    fact=fact_text,
                    category=fact_data["category"],
                    source=fact_data.get("source", "personal_seeder"),
                    confidence=fact_data.get("confidence", 0.9)
                )
                stats["added"] += 1

            except Exception as e:
                log_with_context(logger, "error", "Failed to seed fact",
                               fact=fact_data.get("fact", "?")[:50], error=str(e))
                stats["errors"] += 1

        log_with_context(logger, "info", "Personal knowledge seeding completed", **stats)
        return stats

    except Exception as e:
        log_with_context(logger, "error", "Personal knowledge seeding failed", error=str(e))
        return {"error": str(e)}


def seed_to_qdrant() -> Dict[str, Any]:
    """
    Seed personal facts to Qdrant for semantic search.

    Returns stats about what was embedded.
    """
    try:
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points
        import hashlib

        stats = {"embedded": 0, "errors": 0}

        # Group facts by category for efficient embedding
        texts = []
        payloads = []

        for fact_data in PERSONAL_FACTS:
            text = f"[{fact_data['category']}] {fact_data['fact']}"
            texts.append(text)

            # Create payload
            content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
            payloads.append({
                "text": text,
                "doc_type": "personal_fact",
                "category": fact_data["category"],
                "source": fact_data.get("source", "personal_seeder"),
                "confidence": fact_data.get("confidence", 0.9),
                "content_hash": content_hash,
                "created_at": datetime.utcnow().isoformat(),
            })

        # Embed all texts
        embeddings = embed_texts(texts)

        # Upsert to Qdrant
        points = []
        for i, (embedding, payload) in enumerate(zip(embeddings, payloads)):
            points.append({
                "id": hash(payload["content_hash"]) & 0x7FFFFFFFFFFFFFFF,  # Positive int64
                "vector": embedding,
                "payload": payload
            })

        upsert_points("jarvis_private", points)
        stats["embedded"] = len(points)

        log_with_context(logger, "info", "Personal knowledge embedded to Qdrant", **stats)
        return stats

    except Exception as e:
        log_with_context(logger, "error", "Qdrant embedding failed", error=str(e))
        return {"error": str(e)}


def seed_all() -> Dict[str, Any]:
    """
    Seed personal knowledge to all stores.

    Returns combined stats.
    """
    results = {
        "memory_store": seed_to_memory_store(),
        "qdrant": seed_to_qdrant(),
        "timestamp": datetime.utcnow().isoformat()
    }

    log_with_context(logger, "info", "Full personal knowledge seeding completed",
                    memory_added=results["memory_store"].get("added", 0),
                    qdrant_embedded=results["qdrant"].get("embedded", 0))

    return results


def get_all_facts() -> List[Dict[str, Any]]:
    """Return all configured personal facts."""
    return PERSONAL_FACTS.copy()


def add_custom_fact(category: str, fact: str, confidence: float = 0.9, source: str = "user") -> bool:
    """
    Add a custom fact at runtime.
    Note: This doesn't persist to the file, only to memory/qdrant.
    """
    try:
        from .. import memory_store

        memory_store.add_fact(
            fact=fact,
            category=category,
            source=source,
            confidence=confidence
        )

        log_with_context(logger, "info", "Custom fact added",
                        category=category, fact=fact[:50])
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to add custom fact", error=str(e))
        return False
