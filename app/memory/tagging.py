from typing import List, Dict, Any
from app.models.memory_fact import MemoryFact
import re

class TaggingEngine:
    """Einfache Auto-Tagging-Engine für MemoryFacts."""
    PERSON_PATTERN = re.compile(r"\\b[A-Z][a-z]+ [A-Z][a-z]+\\b")
    DATE_PATTERN = re.compile(r"\\b(20\\d{2}|19\\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12][0-9]|3[01])\\b")
    TOPIC_KEYWORDS = ["project", "meeting", "deadline", "email", "call", "task", "feature"]

    def auto_tag(self, fact: MemoryFact) -> List[str]:
        tags = set(fact.tags or [])
        # Personen erkennen
        if isinstance(fact.value, str):
            for match in self.PERSON_PATTERN.findall(fact.value):
                tags.add("person:" + match)
            for match in self.DATE_PATTERN.findall(fact.value):
                tags.add("date:" + "-".join(match))
            for topic in self.TOPIC_KEYWORDS:
                if topic in fact.value.lower():
                    tags.add("topic:" + topic)
        # Namespace als Tag
        tags.add("ns:" + fact.namespace)
        return list(tags)

    def tag_facts(self, facts: List[MemoryFact]) -> None:
        for fact in facts:
            fact.tags = self.auto_tag(fact)
