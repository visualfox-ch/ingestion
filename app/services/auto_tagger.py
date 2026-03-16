"""
Auto-Tagging Service

Automatic tag extraction and categorization for memories.

Tagging Strategies:
1. Keyword Extraction: TF-IDF and statistical methods
2. Entity Recognition: Named entity detection
3. Topic Classification: Domain categorization
4. Semantic Clustering: Similar tag grouping
5. LLM Enhancement: AI-powered contextual tagging

Tag Types:
- Category: High-level domain (work, personal, health, etc.)
- Topic: Specific subject matter
- Entity: People, places, projects
- Temporal: Time-related tags
- Sentiment: Emotional context
"""

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Tag Types and Models
# =============================================================================

class TagType(str, Enum):
    """Types of tags that can be assigned."""
    CATEGORY = "category"
    TOPIC = "topic"
    ENTITY = "entity"
    TEMPORAL = "temporal"
    SENTIMENT = "sentiment"
    ACTION = "action"
    CUSTOM = "custom"


class TagSource(str, Enum):
    """Source of tag generation."""
    KEYWORD = "keyword"       # Statistical extraction
    ENTITY = "entity"         # NER detection
    CLASSIFIER = "classifier" # Topic classifier
    LLM = "llm"              # LLM-generated
    USER = "user"            # User-provided
    INHERITED = "inherited"  # From related content


@dataclass
class Tag:
    """A single tag with metadata."""
    name: str
    tag_type: TagType
    source: TagSource
    confidence: float = 0.8
    relevance: float = 1.0
    parent_tag: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaggingResult:
    """Result of auto-tagging operation."""
    content: str
    tags: List[Tag]
    categories: List[str]
    entities: List[str]
    topics: List[str]
    sentiment: Optional[str]
    processing_time_ms: float
    strategies_used: List[str]


# =============================================================================
# Tag Taxonomy
# =============================================================================

# Pre-defined category hierarchy
CATEGORY_TAXONOMY = {
    "work": {
        "keywords": ["projekt", "project", "meeting", "deadline", "client", "kunde",
                    "arbeit", "work", "task", "aufgabe", "sprint", "review"],
        "subcategories": ["projektil", "visualfox", "freelance", "consulting"]
    },
    "personal": {
        "keywords": ["familie", "family", "freund", "friend", "hobby", "urlaub",
                    "vacation", "personal", "privat", "relationship"],
        "subcategories": ["family", "social", "hobbies", "travel"]
    },
    "health": {
        "keywords": ["fitness", "training", "gym", "sport", "gesundheit", "health",
                    "workout", "nutrition", "ernährung", "sleep", "schlaf"],
        "subcategories": ["fitness", "nutrition", "mental", "medical"]
    },
    "finance": {
        "keywords": ["geld", "money", "budget", "invoice", "rechnung", "zahlung",
                    "payment", "investment", "steuer", "tax"],
        "subcategories": ["income", "expenses", "investments", "taxes"]
    },
    "learning": {
        "keywords": ["lernen", "learn", "course", "kurs", "book", "buch",
                    "tutorial", "skill", "education", "training"],
        "subcategories": ["courses", "books", "skills", "certifications"]
    },
    "technology": {
        "keywords": ["code", "coding", "programming", "software", "hardware",
                    "api", "database", "cloud", "server", "development"],
        "subcategories": ["development", "devops", "ai", "tools"]
    },
    "admin": {
        "keywords": ["admin", "dokument", "document", "vertrag", "contract",
                    "termin", "appointment", "behörde", "office"],
        "subcategories": ["documents", "appointments", "legal", "bureaucracy"]
    },
}

# Entity type patterns
ENTITY_PATTERNS = {
    "person": [
        r"(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)?\s*[A-Z][a-z]+\s+[A-Z][a-z]+",
        r"@\w+",  # Usernames
    ],
    "project": [
        r"[A-Z][A-Z0-9_-]{2,}",  # Uppercase project codes
        r"(?:Project|Projekt)\s+\w+",
    ],
    "date": [
        r"\d{1,2}[./]\d{1,2}[./]\d{2,4}",
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
        r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)",
    ],
    "money": [
        r"[\$€£]\s?\d+(?:[.,]\d+)?",
        r"\d+(?:[.,]\d+)?\s?(?:CHF|EUR|USD|Dollar|Euro|Franken)",
    ],
    "url": [
        r"https?://[^\s]+",
    ],
    "email": [
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    ],
}

# Temporal indicators
TEMPORAL_KEYWORDS = {
    "today": ["heute", "today", "this morning", "heute morgen"],
    "yesterday": ["gestern", "yesterday"],
    "this_week": ["diese woche", "this week"],
    "next_week": ["nächste woche", "next week"],
    "this_month": ["diesen monat", "this month"],
    "deadline": ["deadline", "frist", "due", "bis zum"],
    "recurring": ["jeden", "weekly", "wöchentlich", "monthly", "monatlich", "daily", "täglich"],
}

# Sentiment indicators
SENTIMENT_KEYWORDS = {
    "positive": ["great", "super", "toll", "excellent", "perfekt", "awesome",
                "happy", "freut", "success", "erfolg", "achieved", "geschafft"],
    "negative": ["problem", "issue", "bug", "fehler", "error", "schwierig",
                "difficult", "failed", "failed", "stress", "worried", "sorge"],
    "neutral": ["info", "note", "notiz", "update", "status", "reminder"],
    "urgent": ["urgent", "dringend", "asap", "sofort", "immediately", "critical"],
}


# =============================================================================
# Keyword Extraction
# =============================================================================

class KeywordExtractor:
    """Extract keywords using statistical methods."""

    # German and English stop words
    STOP_WORDS = {
        "der", "die", "das", "ein", "eine", "und", "oder", "aber", "wenn",
        "ich", "du", "er", "sie", "es", "wir", "ihr", "sie", "ist", "sind",
        "hat", "haben", "war", "waren", "wird", "werden", "kann", "können",
        "muss", "müssen", "soll", "sollen", "will", "wollen", "mit", "von",
        "zu", "bei", "nach", "vor", "über", "unter", "für", "gegen", "durch",
        "the", "a", "an", "and", "or", "but", "if", "i", "you", "he", "she",
        "it", "we", "they", "is", "are", "was", "were", "will", "would",
        "can", "could", "must", "should", "may", "might", "have", "has",
        "had", "do", "does", "did", "with", "from", "to", "at", "by", "for",
        "about", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "this", "that", "these", "those",
    }

    def extract(self, text: str, max_keywords: int = 10) -> List[Tuple[str, float]]:
        """Extract keywords with relevance scores."""
        # Tokenize and clean
        words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', text.lower())
        words = [w for w in words if w not in self.STOP_WORDS]

        # Count frequencies
        word_counts = Counter(words)
        total_words = len(words) if words else 1

        # Calculate TF scores
        tf_scores = {word: count / total_words for word, count in word_counts.items()}

        # Sort by score and return top keywords
        sorted_keywords = sorted(tf_scores.items(), key=lambda x: x[1], reverse=True)

        return sorted_keywords[:max_keywords]


# =============================================================================
# Entity Extractor
# =============================================================================

class EntityExtractor:
    """Extract named entities from text."""

    def __init__(self):
        self.patterns = {
            entity_type: [re.compile(p, re.IGNORECASE) for p in patterns]
            for entity_type, patterns in ENTITY_PATTERNS.items()
        }

    def extract(self, text: str) -> Dict[str, List[str]]:
        """Extract entities by type."""
        entities = {}

        for entity_type, patterns in self.patterns.items():
            matches = set()
            for pattern in patterns:
                for match in pattern.findall(text):
                    if isinstance(match, tuple):
                        match = match[0]
                    matches.add(match.strip())

            if matches:
                entities[entity_type] = list(matches)

        return entities


# =============================================================================
# Topic Classifier
# =============================================================================

class TopicClassifier:
    """Classify content into topic categories."""

    def __init__(self):
        self.taxonomy = CATEGORY_TAXONOMY

    def classify(self, text: str) -> List[Tuple[str, float]]:
        """Classify text into categories with confidence scores."""
        text_lower = text.lower()
        scores = {}

        for category, config in self.taxonomy.items():
            keywords = config["keywords"]
            match_count = sum(1 for kw in keywords if kw in text_lower)

            if match_count > 0:
                # Score based on keyword density
                score = min(1.0, match_count / 3.0)  # Cap at 1.0
                scores[category] = score

        # Sort by score
        sorted_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return sorted_categories

    def get_subcategories(self, category: str, text: str) -> List[str]:
        """Get matching subcategories for a category."""
        if category not in self.taxonomy:
            return []

        subcats = self.taxonomy[category].get("subcategories", [])
        text_lower = text.lower()

        return [sc for sc in subcats if sc in text_lower]


# =============================================================================
# Sentiment Analyzer
# =============================================================================

class SentimentAnalyzer:
    """Analyze sentiment of text."""

    def __init__(self):
        self.keywords = SENTIMENT_KEYWORDS

    def analyze(self, text: str) -> Tuple[str, float]:
        """Analyze sentiment and return (sentiment, confidence)."""
        text_lower = text.lower()
        scores = {}

        for sentiment, keywords in self.keywords.items():
            match_count = sum(1 for kw in keywords if kw in text_lower)
            if match_count > 0:
                scores[sentiment] = match_count

        if not scores:
            return "neutral", 0.5

        # Get dominant sentiment
        dominant = max(scores.items(), key=lambda x: x[1])
        confidence = min(1.0, dominant[1] / 3.0)

        return dominant[0], confidence


# =============================================================================
# LLM Tagger
# =============================================================================

class LLMTagger:
    """Use LLM for intelligent tagging."""

    TAGGING_PROMPT = """Analyze the following content and extract structured tags.

Content:
{content}

Extract the following:
1. Main category (one of: work, personal, health, finance, learning, technology, admin)
2. Specific topics (2-5 relevant topic tags)
3. Named entities (people, projects, places mentioned)
4. Action items (if any tasks or todos are implied)
5. Temporal context (if time-related)
6. Overall sentiment (positive, negative, neutral, urgent)

Respond in JSON format:
{{
    "category": "...",
    "topics": ["...", "..."],
    "entities": ["...", "..."],
    "actions": ["...", "..."],
    "temporal": "...",
    "sentiment": "..."
}}"""

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

    def tag(self, content: str, use_llm: bool = False) -> Dict[str, Any]:
        """
        Generate tags using LLM.

        Args:
            content: Text to tag
            use_llm: Whether to actually call LLM (False = return empty)

        Returns:
            Dictionary with extracted tags
        """
        if not use_llm:
            return {}

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": self.TAGGING_PROMPT.format(content=content[:2000])
                }]
            )

            # Parse JSON response
            import json
            text = response.content[0].text if response.content else "{}"

            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

            return {}

        except Exception as e:
            logger.warning(f"LLM tagging failed: {e}")
            return {}


# =============================================================================
# Main Auto-Tagger
# =============================================================================

class AutoTagger:
    """
    Main auto-tagging service.

    Combines multiple tagging strategies for comprehensive tag extraction.
    """

    def __init__(self):
        self.keyword_extractor = KeywordExtractor()
        self.entity_extractor = EntityExtractor()
        self.topic_classifier = TopicClassifier()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.llm_tagger = LLMTagger()

    def tag(
        self,
        content: str,
        use_llm: bool = False,
        min_confidence: float = 0.3,
        max_tags: int = 15
    ) -> TaggingResult:
        """
        Auto-tag content using multiple strategies.

        Args:
            content: Text content to tag
            use_llm: Whether to use LLM for enhanced tagging
            min_confidence: Minimum confidence threshold for tags
            max_tags: Maximum number of tags to return

        Returns:
            TaggingResult with extracted tags
        """
        import time
        start_time = time.time()

        tags: List[Tag] = []
        strategies_used = []

        # 1. Keyword extraction
        keywords = self.keyword_extractor.extract(content)
        for keyword, score in keywords[:5]:
            if score >= min_confidence * 0.5:  # Lower threshold for keywords
                tags.append(Tag(
                    name=keyword,
                    tag_type=TagType.TOPIC,
                    source=TagSource.KEYWORD,
                    confidence=min(1.0, score * 2),
                    relevance=score,
                ))
        if keywords:
            strategies_used.append("keyword")

        # 2. Entity extraction
        entities = self.entity_extractor.extract(content)
        for entity_type, entity_list in entities.items():
            for entity in entity_list[:3]:  # Limit per type
                tags.append(Tag(
                    name=entity,
                    tag_type=TagType.ENTITY,
                    source=TagSource.ENTITY,
                    confidence=0.9,  # High confidence for pattern matches
                    metadata={"entity_type": entity_type},
                ))
        if entities:
            strategies_used.append("entity")

        # 3. Topic classification
        categories = self.topic_classifier.classify(content)
        for category, score in categories:
            if score >= min_confidence:
                tags.append(Tag(
                    name=category,
                    tag_type=TagType.CATEGORY,
                    source=TagSource.CLASSIFIER,
                    confidence=score,
                ))
                # Add subcategories
                subcats = self.topic_classifier.get_subcategories(category, content)
                for subcat in subcats:
                    tags.append(Tag(
                        name=subcat,
                        tag_type=TagType.TOPIC,
                        source=TagSource.CLASSIFIER,
                        confidence=score * 0.8,
                        parent_tag=category,
                    ))
        if categories:
            strategies_used.append("classifier")

        # 4. Sentiment analysis
        sentiment, sentiment_confidence = self.sentiment_analyzer.analyze(content)
        if sentiment_confidence >= min_confidence:
            tags.append(Tag(
                name=sentiment,
                tag_type=TagType.SENTIMENT,
                source=TagSource.CLASSIFIER,
                confidence=sentiment_confidence,
            ))
            strategies_used.append("sentiment")

        # 5. Temporal extraction
        temporal_tags = self._extract_temporal_tags(content)
        tags.extend(temporal_tags)
        if temporal_tags:
            strategies_used.append("temporal")

        # 6. LLM enhancement (optional)
        if use_llm:
            llm_result = self.llm_tagger.tag(content, use_llm=True)
            if llm_result:
                # Add LLM-generated tags
                for topic in llm_result.get("topics", []):
                    if not any(t.name.lower() == topic.lower() for t in tags):
                        tags.append(Tag(
                            name=topic,
                            tag_type=TagType.TOPIC,
                            source=TagSource.LLM,
                            confidence=0.85,
                        ))
                for entity in llm_result.get("entities", []):
                    if not any(t.name.lower() == entity.lower() for t in tags):
                        tags.append(Tag(
                            name=entity,
                            tag_type=TagType.ENTITY,
                            source=TagSource.LLM,
                            confidence=0.85,
                        ))
                strategies_used.append("llm")

        # Filter and sort tags
        tags = [t for t in tags if t.confidence >= min_confidence]
        tags.sort(key=lambda t: (t.confidence, t.relevance), reverse=True)
        tags = tags[:max_tags]

        # Build result
        elapsed_ms = (time.time() - start_time) * 1000

        return TaggingResult(
            content=content[:500],
            tags=tags,
            categories=[t.name for t in tags if t.tag_type == TagType.CATEGORY],
            entities=[t.name for t in tags if t.tag_type == TagType.ENTITY],
            topics=[t.name for t in tags if t.tag_type == TagType.TOPIC],
            sentiment=sentiment if sentiment_confidence >= min_confidence else None,
            processing_time_ms=elapsed_ms,
            strategies_used=strategies_used,
        )

    def _extract_temporal_tags(self, content: str) -> List[Tag]:
        """Extract temporal tags from content."""
        tags = []
        text_lower = content.lower()

        for temporal_type, keywords in TEMPORAL_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(Tag(
                    name=temporal_type,
                    tag_type=TagType.TEMPORAL,
                    source=TagSource.KEYWORD,
                    confidence=0.8,
                ))

        return tags

    def suggest_tags(
        self,
        partial_tag: str,
        existing_tags: Optional[List[str]] = None,
        max_suggestions: int = 5
    ) -> List[str]:
        """Suggest tags based on partial input."""
        # Collect all known tags from taxonomy
        all_tags = set()

        for category, config in CATEGORY_TAXONOMY.items():
            all_tags.add(category)
            all_tags.update(config.get("subcategories", []))
            all_tags.update(config.get("keywords", []))

        # Filter by partial match
        partial_lower = partial_tag.lower()
        matches = [t for t in all_tags if partial_lower in t.lower()]

        # Exclude existing tags
        if existing_tags:
            existing_lower = {t.lower() for t in existing_tags}
            matches = [t for t in matches if t.lower() not in existing_lower]

        # Sort by relevance (starts with > contains)
        matches.sort(key=lambda t: (0 if t.lower().startswith(partial_lower) else 1, t))

        return matches[:max_suggestions]


# =============================================================================
# Singleton Instance
# =============================================================================

_auto_tagger: Optional[AutoTagger] = None

def get_auto_tagger() -> AutoTagger:
    """Get singleton instance of AutoTagger."""
    global _auto_tagger
    if _auto_tagger is None:
        _auto_tagger = AutoTagger()
    return _auto_tagger
