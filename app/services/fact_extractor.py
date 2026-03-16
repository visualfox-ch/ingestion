"""
Atomic Fact Extraction System

Extracts granular, atomic facts from unstructured text.

Fact Types:
1. Biographical: Personal information, preferences, habits
2. Relational: Relationships between entities
3. Temporal: Events, dates, schedules
4. Declarative: Statements of truth/knowledge
5. Procedural: How-to knowledge, processes
6. Contextual: Situational information

Extraction Methods:
1. Pattern-based: Regex and rule-based extraction
2. Structural: Sentence structure analysis
3. Semantic: Meaning-based extraction
4. LLM-enhanced: AI-powered extraction
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import hashlib

logger = logging.getLogger(__name__)


# =============================================================================
# Fact Types and Models
# =============================================================================

class FactType(str, Enum):
    """Types of extractable facts."""
    BIOGRAPHICAL = "biographical"   # About a person
    RELATIONAL = "relational"       # Relationships
    TEMPORAL = "temporal"           # Time-related
    DECLARATIVE = "declarative"     # Statements
    PROCEDURAL = "procedural"       # How-to
    PREFERENCE = "preference"       # Likes/dislikes
    QUANTITATIVE = "quantitative"   # Numbers, measurements
    CONTEXTUAL = "contextual"       # Situational


class FactCategory(str, Enum):
    """High-level fact categories."""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    HEALTH = "health"
    FINANCE = "finance"
    SOCIAL = "social"
    TECHNICAL = "technical"
    GENERAL = "general"


@dataclass
class AtomicFact:
    """A single atomic fact."""
    id: str
    content: str
    fact_type: FactType
    category: FactCategory

    # Subject-Predicate-Object structure
    subject: str
    predicate: str
    object: str

    # Extraction metadata
    source_text: str
    extraction_method: str
    confidence: float

    # Relationships
    entities: List[str] = field(default_factory=list)
    related_facts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Validity
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_negation: bool = False

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_triple(self) -> str:
        """Return fact as triple string."""
        return f"({self.subject}, {self.predicate}, {self.object})"


@dataclass
class ExtractionResult:
    """Result of fact extraction."""
    source_text: str
    facts: List[AtomicFact]
    entities_found: List[str]
    relationships_found: List[Tuple[str, str, str]]
    extraction_time_ms: float
    methods_used: List[str]
    summary: str


# =============================================================================
# Extraction Patterns
# =============================================================================

# Biographical patterns
BIOGRAPHICAL_PATTERNS = [
    # Name patterns
    (r"(?:my name is|ich bin|ich heiße)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
     "name", "is"),
    # Age patterns
    (r"(?:I am|ich bin)\s+(\d+)\s+(?:years old|Jahre alt)",
     "age", "is"),
    # Location patterns
    (r"(?:I live in|ich wohne in|ich lebe in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
     "location", "lives_in"),
    # Occupation patterns
    (r"(?:I work as|ich arbeite als|I am a|ich bin)\s+(?:a\s+)?([a-z]+(?:\s+[a-z]+)?)",
     "occupation", "works_as"),
    # Birthday
    (r"(?:my birthday is|mein geburtstag ist)\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)",
     "birthday", "is"),
]

# Preference patterns
PREFERENCE_PATTERNS = [
    # Likes
    (r"(?:I (?:really )?(?:like|love|enjoy)|ich (?:mag|liebe))\s+(.+?)(?:\.|$|,)",
     "preference", "likes"),
    # Dislikes
    (r"(?:I (?:don't like|hate|dislike)|ich (?:mag nicht|hasse))\s+(.+?)(?:\.|$|,)",
     "preference", "dislikes"),
    # Favorites
    (r"(?:my favorite|mein lieblings)[\s-]?([a-z]+)\s+(?:is|ist)\s+(.+?)(?:\.|$)",
     "favorite", "is"),
    # Preferences
    (r"(?:I prefer|ich bevorzuge)\s+(.+?)\s+(?:over|gegenüber)\s+(.+?)(?:\.|$)",
     "preference", "prefers_over"),
]

# Relational patterns
RELATIONAL_PATTERNS = [
    # Family
    (r"(?:my|mein[e]?)\s+(wife|husband|mother|father|brother|sister|son|daughter|frau|mann|mutter|vater|bruder|schwester|sohn|tochter)(?:'s name)?\s+(?:is|ist|heißt)\s+([A-Z][a-z]+)",
     "family", "has_relation"),
    # Work relationships
    (r"([A-Z][a-z]+)\s+(?:is|ist)\s+my\s+(boss|colleague|client|manager|chef|kollege|kunde)",
     "work", "has_relation"),
    # Friends
    (r"([A-Z][a-z]+)\s+(?:is|ist)\s+(?:my|ein[e]?)\s+(?:friend|freund|freundin|bekannte[r]?)",
     "social", "is_friend"),
]

# Temporal patterns
TEMPORAL_PATTERNS = [
    # Scheduled events
    (r"(?:I have|ich habe)\s+(?:a\s+)?(.+?)\s+(?:on|am)\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\w+day|heute|morgen)",
     "schedule", "has_event"),
    # Recurring events
    (r"(?:every|jeden|jede)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\s+(?:I|ich)\s+(.+?)(?:\.|$)",
     "recurring", "does_regularly"),
    # Deadlines
    (r"(?:deadline|frist)\s+(?:for|für)\s+(.+?)\s+(?:is|ist)\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)",
     "deadline", "due_on"),
]

# Quantitative patterns
QUANTITATIVE_PATTERNS = [
    # Numbers with units
    (r"(\d+(?:[.,]\d+)?)\s*(kg|lbs?|km|miles?|meters?|cm|euros?|dollars?|CHF|%)",
     "measurement", "equals"),
    # Counts
    (r"(?:I have|ich habe)\s+(\d+)\s+([a-z]+s?)",
     "count", "has_quantity"),
]

# Declarative patterns
DECLARATIVE_PATTERNS = [
    # Facts about things
    (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:is|ist|are|sind)\s+(?:a\s+)?(.+?)(?:\.|$)",
     "definition", "is"),
    # Properties
    (r"(?:the|der|die|das)\s+([a-z]+)\s+(?:of|von)\s+([A-Z][a-z]+)\s+(?:is|ist)\s+(.+?)(?:\.|$)",
     "property", "has_value"),
]


# =============================================================================
# Pattern-Based Extractor
# =============================================================================

class PatternExtractor:
    """Extract facts using regex patterns."""

    def __init__(self):
        self.patterns = {
            FactType.BIOGRAPHICAL: BIOGRAPHICAL_PATTERNS,
            FactType.PREFERENCE: PREFERENCE_PATTERNS,
            FactType.RELATIONAL: RELATIONAL_PATTERNS,
            FactType.TEMPORAL: TEMPORAL_PATTERNS,
            FactType.QUANTITATIVE: QUANTITATIVE_PATTERNS,
            FactType.DECLARATIVE: DECLARATIVE_PATTERNS,
        }

    def extract(self, text: str) -> List[AtomicFact]:
        """Extract facts using pattern matching."""
        facts = []

        for fact_type, patterns in self.patterns.items():
            for pattern, subject_type, predicate in patterns:
                try:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        groups = match.groups()
                        if len(groups) >= 1:
                            # Build fact from match
                            fact = self._build_fact(
                                text=text,
                                match=match,
                                groups=groups,
                                fact_type=fact_type,
                                subject_type=subject_type,
                                predicate=predicate,
                            )
                            if fact:
                                facts.append(fact)
                except Exception as e:
                    logger.debug(f"Pattern extraction error: {e}")

        return facts

    def _build_fact(
        self,
        text: str,
        match: re.Match,
        groups: tuple,
        fact_type: FactType,
        subject_type: str,
        predicate: str,
    ) -> Optional[AtomicFact]:
        """Build an AtomicFact from a regex match."""
        try:
            # Determine subject and object from groups
            if len(groups) == 1:
                subject = "user"
                obj = groups[0].strip()
            elif len(groups) == 2:
                subject = groups[0].strip() if groups[0] else "user"
                obj = groups[1].strip()
            else:
                subject = groups[0].strip() if groups[0] else "user"
                obj = " ".join(g.strip() for g in groups[1:] if g)

            # Generate ID
            fact_id = self._generate_id(subject, predicate, obj)

            # Determine category
            category = self._infer_category(fact_type, subject_type)

            # Build content string
            content = f"{subject} {predicate} {obj}"

            return AtomicFact(
                id=fact_id,
                content=content,
                fact_type=fact_type,
                category=category,
                subject=subject,
                predicate=predicate,
                object=obj,
                source_text=match.group(0),
                extraction_method="pattern",
                confidence=0.7,  # Pattern matches have medium confidence
                entities=[e for e in [subject, obj] if e and e != "user"],
            )
        except Exception as e:
            logger.debug(f"Failed to build fact: {e}")
            return None

    def _generate_id(self, subject: str, predicate: str, obj: str) -> str:
        """Generate unique ID for fact."""
        content = f"{subject}:{predicate}:{obj}".lower()
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _infer_category(self, fact_type: FactType, subject_type: str) -> FactCategory:
        """Infer category from fact type and subject."""
        if fact_type == FactType.BIOGRAPHICAL:
            return FactCategory.PERSONAL
        elif fact_type == FactType.RELATIONAL:
            if subject_type in ["work", "professional"]:
                return FactCategory.PROFESSIONAL
            return FactCategory.SOCIAL
        elif fact_type == FactType.PREFERENCE:
            return FactCategory.PERSONAL
        elif subject_type in ["health", "fitness"]:
            return FactCategory.HEALTH
        elif subject_type in ["money", "finance"]:
            return FactCategory.FINANCE
        else:
            return FactCategory.GENERAL


# =============================================================================
# Structural Extractor
# =============================================================================

class StructuralExtractor:
    """Extract facts based on sentence structure."""

    # Simple sentence structure patterns
    STRUCTURES = [
        # "X is Y" / "X ist Y"
        (r"^([A-Z][^,:.]+?)\s+(?:is|ist|are|sind)\s+(.+?)\.?$", "is"),
        # "X has Y" / "X hat Y"
        (r"^([A-Z][^,:.]+?)\s+(?:has|have|hat|haben)\s+(.+?)\.?$", "has"),
        # "X does Y" / "X macht Y"
        (r"^([A-Z][^,:.]+?)\s+(?:does|do|macht|machen)\s+(.+?)\.?$", "does"),
        # "X wants Y" / "X will Y"
        (r"^([A-Z][^,:.]+?)\s+(?:wants|want|will|möchte)\s+(.+?)\.?$", "wants"),
        # "X needs Y" / "X braucht Y"
        (r"^([A-Z][^,:.]+?)\s+(?:needs?|braucht|brauchen)\s+(.+?)\.?$", "needs"),
    ]

    def extract(self, text: str) -> List[AtomicFact]:
        """Extract facts based on sentence structure."""
        facts = []

        # Split into sentences
        sentences = re.split(r'[.!?]\s+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 5:
                continue

            for pattern, predicate in self.STRUCTURES:
                match = re.match(pattern, sentence, re.IGNORECASE)
                if match:
                    subject = match.group(1).strip()
                    obj = match.group(2).strip()

                    fact_id = hashlib.md5(
                        f"{subject}:{predicate}:{obj}".lower().encode()
                    ).hexdigest()[:12]

                    facts.append(AtomicFact(
                        id=fact_id,
                        content=f"{subject} {predicate} {obj}",
                        fact_type=FactType.DECLARATIVE,
                        category=FactCategory.GENERAL,
                        subject=subject,
                        predicate=predicate,
                        object=obj,
                        source_text=sentence,
                        extraction_method="structural",
                        confidence=0.6,
                        entities=[subject],
                    ))
                    break  # One match per sentence

        return facts


# =============================================================================
# LLM Extractor
# =============================================================================

class LLMExtractor:
    """Use LLM for intelligent fact extraction."""

    EXTRACTION_PROMPT = """Extract atomic facts from the following text. Each fact should be:
1. Self-contained (understandable without context)
2. Specific (not vague)
3. Atomic (one piece of information per fact)

Text:
{text}

For each fact, provide:
- subject: The main entity
- predicate: The relationship/action
- object: The value/target
- type: biographical|relational|temporal|preference|quantitative|declarative
- confidence: 0.0-1.0

Respond in JSON array format:
[
    {{"subject": "...", "predicate": "...", "object": "...", "type": "...", "confidence": 0.9}},
    ...
]

Only include facts that are clearly stated. Do not infer or assume."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY")
            )
        return self._client

    def extract(self, text: str, use_llm: bool = False) -> List[AtomicFact]:
        """Extract facts using LLM."""
        if not use_llm:
            return []

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": self.EXTRACTION_PROMPT.format(text=text[:3000])
                }]
            )

            # Parse response
            import json
            response_text = response.content[0].text if response.content else "[]"

            # Extract JSON array
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if not json_match:
                return []

            facts_data = json.loads(json_match.group())

            facts = []
            for f in facts_data:
                fact_id = hashlib.md5(
                    f"{f['subject']}:{f['predicate']}:{f['object']}".lower().encode()
                ).hexdigest()[:12]

                fact_type = FactType(f.get("type", "declarative"))

                facts.append(AtomicFact(
                    id=fact_id,
                    content=f"{f['subject']} {f['predicate']} {f['object']}",
                    fact_type=fact_type,
                    category=FactCategory.GENERAL,
                    subject=f["subject"],
                    predicate=f["predicate"],
                    object=f["object"],
                    source_text=text[:200],
                    extraction_method="llm",
                    confidence=f.get("confidence", 0.8),
                    entities=[f["subject"]],
                ))

            return facts

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return []


# =============================================================================
# Fact Deduplicator
# =============================================================================

class FactDeduplicator:
    """Deduplicate and merge similar facts."""

    def __init__(self, similarity_threshold: float = 0.85):
        self.threshold = similarity_threshold

    def deduplicate(self, facts: List[AtomicFact]) -> List[AtomicFact]:
        """Remove duplicate facts, keeping highest confidence version."""
        if not facts:
            return []

        # Group by subject-predicate
        groups: Dict[str, List[AtomicFact]] = {}
        for fact in facts:
            key = f"{fact.subject.lower()}:{fact.predicate.lower()}"
            if key not in groups:
                groups[key] = []
            groups[key].append(fact)

        # Keep best from each group
        unique_facts = []
        for group in groups.values():
            # Sort by confidence, keep highest
            group.sort(key=lambda f: f.confidence, reverse=True)
            best = group[0]

            # Merge metadata from duplicates
            for other in group[1:]:
                if other.extraction_method != best.extraction_method:
                    best.metadata["also_extracted_by"] = other.extraction_method
                    # Boost confidence if multiple methods agree
                    best.confidence = min(1.0, best.confidence + 0.1)

            unique_facts.append(best)

        return unique_facts


# =============================================================================
# Main Fact Extractor
# =============================================================================

class FactExtractor:
    """
    Main fact extraction engine.

    Combines multiple extraction methods for comprehensive fact extraction.
    """

    def __init__(self):
        self.pattern_extractor = PatternExtractor()
        self.structural_extractor = StructuralExtractor()
        self.llm_extractor = LLMExtractor()
        self.deduplicator = FactDeduplicator()

    def extract(
        self,
        text: str,
        use_llm: bool = False,
        min_confidence: float = 0.5,
        deduplicate: bool = True
    ) -> ExtractionResult:
        """
        Extract atomic facts from text.

        Args:
            text: Source text to extract from
            use_llm: Whether to use LLM for enhanced extraction
            min_confidence: Minimum confidence threshold
            deduplicate: Whether to deduplicate facts

        Returns:
            ExtractionResult with extracted facts
        """
        import time
        start_time = time.time()

        all_facts: List[AtomicFact] = []
        methods_used = []

        # 1. Pattern-based extraction
        pattern_facts = self.pattern_extractor.extract(text)
        all_facts.extend(pattern_facts)
        if pattern_facts:
            methods_used.append("pattern")

        # 2. Structural extraction
        structural_facts = self.structural_extractor.extract(text)
        all_facts.extend(structural_facts)
        if structural_facts:
            methods_used.append("structural")

        # 3. LLM extraction (optional)
        if use_llm:
            llm_facts = self.llm_extractor.extract(text, use_llm=True)
            all_facts.extend(llm_facts)
            if llm_facts:
                methods_used.append("llm")

        # 4. Deduplicate
        if deduplicate and all_facts:
            all_facts = self.deduplicator.deduplicate(all_facts)

        # 5. Filter by confidence
        all_facts = [f for f in all_facts if f.confidence >= min_confidence]

        # 6. Sort by confidence
        all_facts.sort(key=lambda f: f.confidence, reverse=True)

        # Collect entities and relationships
        entities = list(set(
            entity
            for fact in all_facts
            for entity in fact.entities
        ))

        relationships = [
            (fact.subject, fact.predicate, fact.object)
            for fact in all_facts
        ]

        # Generate summary
        summary = self._generate_summary(all_facts)

        elapsed_ms = (time.time() - start_time) * 1000

        return ExtractionResult(
            source_text=text[:500],
            facts=all_facts,
            entities_found=entities,
            relationships_found=relationships,
            extraction_time_ms=elapsed_ms,
            methods_used=methods_used,
            summary=summary,
        )

    def _generate_summary(self, facts: List[AtomicFact]) -> str:
        """Generate summary of extracted facts."""
        if not facts:
            return "No facts extracted"

        type_counts = {}
        for fact in facts:
            type_counts[fact.fact_type.value] = type_counts.get(fact.fact_type.value, 0) + 1

        parts = [f"{count} {type_}" for type_, count in type_counts.items()]
        return f"Extracted {len(facts)} facts: " + ", ".join(parts)

    def extract_from_conversation(
        self,
        messages: List[Dict[str, str]],
        user_id: str = "user"
    ) -> ExtractionResult:
        """Extract facts from conversation history."""
        # Combine messages into text
        text_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                # Facts about user come from user messages
                text_parts.append(content)
            else:
                # Facts about topics come from assistant messages
                text_parts.append(content)

        combined_text = "\n".join(text_parts)
        return self.extract(combined_text, use_llm=False)

    def validate_fact(
        self,
        fact: AtomicFact,
        existing_facts: List[AtomicFact]
    ) -> Tuple[bool, List[AtomicFact]]:
        """
        Validate a fact against existing facts.

        Returns:
            (is_valid, conflicting_facts)
        """
        conflicts = []

        for existing in existing_facts:
            # Same subject and predicate but different object = conflict
            if (fact.subject.lower() == existing.subject.lower() and
                fact.predicate.lower() == existing.predicate.lower() and
                fact.object.lower() != existing.object.lower()):
                conflicts.append(existing)

        is_valid = len(conflicts) == 0
        return is_valid, conflicts


# =============================================================================
# Singleton Instance
# =============================================================================

_fact_extractor: Optional[FactExtractor] = None

def get_fact_extractor() -> FactExtractor:
    """Get singleton instance of FactExtractor."""
    global _fact_extractor
    if _fact_extractor is None:
        _fact_extractor = FactExtractor()
    return _fact_extractor
