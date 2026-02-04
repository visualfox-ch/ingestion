"""
Jarvis Answering Layer
Structured responses with strict source usage, no hallucinations.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.answer")

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
MODES_CONFIG_PATH = BRAIN_ROOT / "system" / "prompts" / "modes.json"

# Cached config
_modes_cache: Optional[Dict] = None


@dataclass
class Source:
    """A single source from search results"""
    source_path: str
    text: str
    score: float
    channel: Optional[str] = None
    doc_type: Optional[str] = None
    ingest_ts: Optional[str] = None
    event_ts_start: Optional[str] = None
    event_ts_end: Optional[str] = None


@dataclass
class SourcesPack:
    """Collection of sources with metadata"""
    sources: List[Source] = field(default_factory=list)
    query: str = ""
    namespace: str = ""
    collection: str = ""

    @property
    def count(self) -> int:
        return len(self.sources)

    @property
    def avg_score(self) -> float:
        if not self.sources:
            return 0.0
        return sum(s.score for s in self.sources) / len(self.sources)

    @property
    def is_empty(self) -> bool:
        return len(self.sources) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sources": [
                {
                    "source_path": s.source_path,
                    "text": s.text[:500] + "..." if len(s.text) > 500 else s.text,
                    "score": round(s.score, 3),
                    "channel": s.channel,
                    "doc_type": s.doc_type,
                    "ingest_ts": s.ingest_ts,
                    "event_ts_start": s.event_ts_start,
                    "event_ts_end": s.event_ts_end,
                }
                for s in self.sources
            ],
            "coverage": {
                "count": self.count,
                "avg_score": round(self.avg_score, 3),
            },
            "query": self.query,
            "namespace": self.namespace,
            "collection": self.collection,
        }


@dataclass
class Mode:
    """Answering mode configuration"""
    id: str
    name: str
    purpose: str
    output_contract: Dict[str, List[str]]
    tone: Dict[str, str]
    forbidden: List[str]
    citation_style: str
    unknown_response: str


def _load_modes() -> Dict:
    """Load modes config from JSON file, with caching"""
    global _modes_cache
    if _modes_cache is not None:
        return _modes_cache

    if not MODES_CONFIG_PATH.exists():
        log_with_context(logger, "warning", "Modes config not found",
                        path=str(MODES_CONFIG_PATH))
        _modes_cache = {"modes": {}, "default_mode": "analyst"}
        return _modes_cache

    try:
        with open(MODES_CONFIG_PATH, "r", encoding="utf-8") as f:
            _modes_cache = json.load(f)
        log_with_context(logger, "info", "Modes config loaded",
                        modes=len(_modes_cache.get("modes", {})))
        return _modes_cache
    except json.JSONDecodeError as e:
        log_with_context(logger, "error", "Invalid modes config JSON", error=str(e))
        _modes_cache = {"modes": {}, "default_mode": "analyst"}
        return _modes_cache


def reload_modes() -> None:
    """Force reload of modes config"""
    global _modes_cache
    _modes_cache = None
    _load_modes()


def get_default_mode() -> str:
    """Get the default mode ID"""
    config = _load_modes()
    return config.get("default_mode", "analyst")


def get_mode(mode_id: str) -> Optional[Mode]:
    """Get a mode by ID"""
    config = _load_modes()
    modes = config.get("modes", {})

    if mode_id not in modes:
        return None

    m = modes[mode_id]
    return Mode(
        id=mode_id,
        name=m.get("name", mode_id),
        purpose=m.get("purpose", ""),
        output_contract=m.get("output_contract", {}),
        tone=m.get("tone", {}),
        forbidden=m.get("forbidden", []),
        citation_style=m.get("citation_style", "inline"),
        unknown_response=m.get("unknown_response", "Not found in memory.")
    )


def list_modes() -> List[Dict[str, str]]:
    """List all available modes"""
    config = _load_modes()
    modes = config.get("modes", {})
    default_id = config.get("default_mode", "analyst")

    return [
        {
            "id": mid,
            "name": m.get("name", mid),
            "purpose": m.get("purpose", ""),
            "is_default": mid == default_id
        }
        for mid, m in modes.items()
    ]


def build_sources_pack(
    search_results: List[Dict[str, Any]],
    query: str,
    namespace: str,
    collection: str
) -> SourcesPack:
    """Build a SourcesPack from search results"""
    sources = []
    for r in search_results:
        sources.append(Source(
            source_path=r.get("source_path", ""),
            text=r.get("text", ""),
            score=r.get("score", 0.0),
            channel=r.get("channel"),
            doc_type=r.get("doc_type"),
            ingest_ts=r.get("ingest_ts"),
            event_ts_start=r.get("event_ts_start"),
            event_ts_end=r.get("event_ts_end"),
        ))

    return SourcesPack(
        sources=sources,
        query=query,
        namespace=namespace,
        collection=collection,
    )


def format_citation(source: Source, style: str) -> str:
    """Format a citation based on style"""
    if style == "inline_subtle":
        # Just mention the source exists
        if source.event_ts_start:
            return f"(from {source.event_ts_start[:10]})"
        return "(from notes)"

    elif style == "explicit_with_dates":
        date = source.event_ts_start or source.ingest_ts or "unknown date"
        if len(date) > 10:
            date = date[:10]
        return f"[{source.source_path}, {date}]"

    elif style == "numbered_references":
        return ""  # Handled separately as a list

    elif style == "count_only":
        return ""  # Just show count

    elif style == "full_metadata":
        parts = [f"path={source.source_path}"]
        if source.channel:
            parts.append(f"channel={source.channel}")
        if source.doc_type:
            parts.append(f"type={source.doc_type}")
        if source.event_ts_start:
            parts.append(f"date={source.event_ts_start[:10]}")
        parts.append(f"score={source.score:.3f}")
        return f"[{', '.join(parts)}]"

    return f"[{source.source_path}]"


def generate_deterministic_answer(
    sources_pack: SourcesPack,
    mode: Mode,
    question: str
) -> Dict[str, Any]:
    """
    Generate a deterministic (no LLM) structured answer.
    Returns an 'answer skeleton' that could later be enhanced by LLM.
    """
    if sources_pack.is_empty:
        return {
            "status": "no_data",
            "mode": mode.id,
            "answer": mode.unknown_response,
            "sections": {},
            "citations": [],
            "sources_pack": sources_pack.to_dict(),
        }

    # Build sections based on mode's output contract
    required = mode.output_contract.get("required_sections", [])
    sections = {}

    # Generate content for each required section
    for section in required:
        if section == "summary" or section == "tldr":
            sections[section] = _generate_summary(sources_pack, mode)
        elif section == "key_findings":
            sections[section] = _generate_findings(sources_pack, mode)
        elif section == "sources":
            sections[section] = _generate_sources_list(sources_pack, mode)
        elif section == "reflection":
            sections[section] = _generate_reflection(sources_pack, question)
        elif section == "patterns_observed":
            sections[section] = _generate_patterns(sources_pack)
        elif section == "questions_to_consider":
            sections[section] = _generate_questions(question)
        elif section == "your_words":
            sections[section] = _generate_quotes(sources_pack)
        elif section == "action_items":
            sections[section] = ["Review the sources below", "Determine next action"]
        elif section == "search_params":
            sections[section] = {
                "query": sources_pack.query,
                "namespace": sources_pack.namespace,
                "collection": sources_pack.collection,
            }
        elif section == "sources_found":
            sections[section] = f"Found {sources_pack.count} sources (avg score: {sources_pack.avg_score:.3f})"
        elif section == "reasoning":
            sections[section] = f"Based on {sources_pack.count} sources, the following information is relevant to '{question}'"
        elif section == "conclusion":
            sections[section] = "See sources below for details. No inference beyond source material."

    # Build citations list
    citations = []
    for i, source in enumerate(sources_pack.sources, 1):
        citation = {
            "ref": i,
            "source_path": source.source_path,
            "formatted": format_citation(source, mode.citation_style),
        }
        if source.event_ts_start:
            citation["date"] = source.event_ts_start[:10]
        citations.append(citation)

    # Build the answer text
    answer_parts = []
    for section_name, content in sections.items():
        if isinstance(content, list):
            content_str = "\n".join(f"- {item}" for item in content)
        elif isinstance(content, dict):
            content_str = json.dumps(content, indent=2)
        else:
            content_str = str(content)
        answer_parts.append(f"## {section_name.replace('_', ' ').title()}\n{content_str}")

    answer_text = "\n\n".join(answer_parts)

    return {
        "status": "ok",
        "mode": mode.id,
        "mode_name": mode.name,
        "answer": answer_text,
        "sections": sections,
        "citations": citations,
        "next_steps": _generate_next_steps(mode, sources_pack),
        "sources_pack": sources_pack.to_dict(),
    }


def _generate_summary(sources_pack: SourcesPack, mode: Mode) -> str:
    """Generate a summary based on sources"""
    if mode.id == "exec":
        return f"Found {sources_pack.count} relevant sources. Review for details."
    return f"Based on {sources_pack.count} sources (avg relevance: {sources_pack.avg_score:.1%}), information is available on this topic."


def _generate_findings(sources_pack: SourcesPack, mode: Mode) -> List[str]:
    """Generate key findings from sources"""
    findings = []
    for i, source in enumerate(sources_pack.sources[:5], 1):
        # Extract first sentence or 100 chars
        text = source.text.strip()
        first_line = text.split('\n')[0][:100]
        if len(first_line) < len(text.split('\n')[0]):
            first_line += "..."
        findings.append(f"[{i}] {first_line}")
    return findings


def _generate_sources_list(sources_pack: SourcesPack, mode: Mode) -> List[str]:
    """Generate formatted sources list"""
    sources_list = []
    for i, source in enumerate(sources_pack.sources, 1):
        date = source.event_ts_start or source.ingest_ts or "unknown"
        if len(date) > 10:
            date = date[:10]
        sources_list.append(f"[{i}] {source.source_path} ({date}, score: {source.score:.2f})")
    return sources_list


def _generate_reflection(sources_pack: SourcesPack, question: str) -> str:
    """Generate a coaching reflection"""
    return f"Looking at your notes about '{question}', I found {sources_pack.count} relevant entries. What stands out to you when you read these?"


def _generate_patterns(sources_pack: SourcesPack) -> List[str]:
    """Identify patterns in sources (deterministic)"""
    patterns = []
    channels = set(s.channel for s in sources_pack.sources if s.channel)
    if channels:
        patterns.append(f"Sources span {len(channels)} channel(s): {', '.join(channels)}")

    doc_types = set(s.doc_type for s in sources_pack.sources if s.doc_type)
    if doc_types:
        patterns.append(f"Document types: {', '.join(doc_types)}")

    return patterns if patterns else ["No clear patterns detected from metadata alone"]


def _generate_questions(question: str) -> List[str]:
    """Generate reflective questions (template-based)"""
    return [
        "What about this topic is most important to you right now?",
        "What would change if you had the answer?",
        "What do you already know that might be relevant?",
    ]


def _generate_quotes(sources_pack: SourcesPack) -> List[str]:
    """Extract direct quotes from sources"""
    quotes = []
    for source in sources_pack.sources[:3]:
        text = source.text.strip()[:200]
        if len(source.text) > 200:
            text += "..."
        date = source.event_ts_start or source.ingest_ts or ""
        if date:
            date = f" ({date[:10]})"
        quotes.append(f'"{text}"{date}')
    return quotes


def _generate_next_steps(mode: Mode, sources_pack: SourcesPack) -> List[str]:
    """Generate suggested next steps based on mode"""
    steps = []

    if mode.id == "coach":
        steps = [
            "Reflect on which source resonates most",
            "Consider what patterns you notice",
            "Decide if you want to explore deeper",
        ]
    elif mode.id == "mirror":
        steps = [
            "Review the quoted excerpts",
            "Note any surprises or confirmations",
        ]
    elif mode.id == "analyst":
        steps = [
            "Review the key findings",
            "Identify any gaps in the data",
            "Determine if more sources are needed",
        ]
    elif mode.id == "exec":
        steps = [
            "Make decision based on available data",
            "Escalate if more info needed",
        ]
    elif mode.id == "debug":
        steps = [
            "Verify search parameters are correct",
            "Check if additional filters needed",
            "Review source metadata for accuracy",
        ]

    return steps


def generate_llm_prompt(
    sources_pack: SourcesPack,
    mode: Mode,
    question: str
) -> str:
    """
    Generate a prompt for LLM-based answering.
    Used by /answer_llm endpoint.
    """
    # Build sources context
    sources_text = []
    for i, source in enumerate(sources_pack.sources, 1):
        meta_parts = []
        if source.source_path:
            meta_parts.append(f"path: {source.source_path}")
        if source.channel:
            meta_parts.append(f"channel: {source.channel}")
        if source.event_ts_start:
            meta_parts.append(f"date: {source.event_ts_start[:10]}")

        meta_str = ", ".join(meta_parts) if meta_parts else "no metadata"
        sources_text.append(f"[Source {i}] ({meta_str})\n{source.text}\n")

    sources_block = "\n---\n".join(sources_text)

    # Build forbidden behaviors
    forbidden_text = "\n".join(f"- {f}" for f in mode.forbidden)

    # Build required sections
    required = mode.output_contract.get("required_sections", [])
    sections_text = ", ".join(required)

    prompt = f"""You are Jarvis, answering in {mode.name} mode.

PURPOSE: {mode.purpose}

TONE: {mode.tone.get('style', 'neutral')}
VOICE: {mode.tone.get('voice', 'Direct')}

REQUIRED OUTPUT SECTIONS: {sections_text}

FORBIDDEN BEHAVIORS:
{forbidden_text}

CRITICAL RULES:
- ONLY use information from the sources below
- If the answer is not in the sources, say: "{mode.unknown_response}"
- Always cite sources using {mode.citation_style} format
- Never invent, guess, or speculate

QUESTION: {question}

SOURCES ({sources_pack.count} found, avg relevance: {sources_pack.avg_score:.1%}):
{sources_block}

Respond now in {mode.name} mode, following the output contract exactly."""

    return prompt
