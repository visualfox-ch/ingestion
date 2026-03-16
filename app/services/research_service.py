"""
Research Service.

Orchestrates research across domains and topics using Perplexity API.
Database-driven with full tracking and reporting capabilities.
"""

import logging
import uuid
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

from app.services.perplexity_client import get_perplexity_client, PerplexityResponse
from app.db_client import get_db_client

logger = logging.getLogger(__name__)


@dataclass
class ResearchDomain:
    """Domain configuration."""
    id: int
    name: str
    display_name: str
    description: Optional[str]
    default_model: str
    search_recency_filter: str
    max_tokens: int
    temperature: float
    prompt_template: str
    output_schema: Optional[Dict]
    default_schedule: Optional[str]
    priority: int
    is_active: bool


@dataclass
class ResearchTopic:
    """Topic within a domain."""
    id: int
    domain_id: int
    name: str
    query_template: Optional[str]
    context: Optional[str]
    priority: int
    search_recency_filter: Optional[str]
    is_active: bool


@dataclass
class ResearchResult:
    """Result from a single research query."""
    topic_id: int
    topic_name: str
    title: str
    summary: str
    content: str
    structured_data: Optional[Dict]
    sources: List[Dict]
    confidence_score: float
    query_used: str
    model_used: str


@dataclass
class ResearchSession:
    """A research session across multiple topics."""
    session_id: str
    domain_id: int
    domain_name: str
    triggered_by: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "running"
    topics_processed: int = 0
    items_created: int = 0
    errors: List[Dict] = field(default_factory=list)
    api_calls: int = 0
    tokens_used: int = 0


class ResearchService:
    """
    Service for executing and managing research.

    Features:
    - Domain/topic configuration from database
    - Prompt template expansion
    - Structured output parsing
    - Session tracking
    - Result persistence with embeddings
    """

    def __init__(self):
        self.perplexity = get_perplexity_client()

    async def get_domain(self, domain_name: str) -> Optional[ResearchDomain]:
        """Get domain configuration by name."""
        db = get_db_client()
        row = await db.fetchrow(
            """
            SELECT id, name, display_name, description, default_model,
                   search_recency_filter, max_tokens, temperature::float,
                   prompt_template, output_schema, default_schedule, priority, is_active
            FROM research_domains
            WHERE name = $1
            """,
            domain_name
        )
        if not row:
            return None

        return ResearchDomain(
            id=row["id"],
            name=row["name"],
            display_name=row["display_name"],
            description=row["description"],
            default_model=row["default_model"],
            search_recency_filter=row["search_recency_filter"],
            max_tokens=row["max_tokens"],
            temperature=row["temperature"],
            prompt_template=row["prompt_template"],
            output_schema=row["output_schema"],
            default_schedule=row["default_schedule"],
            priority=row["priority"],
            is_active=row["is_active"],
        )

    async def get_topics(
        self,
        domain_id: int,
        active_only: bool = True
    ) -> List[ResearchTopic]:
        """Get all topics for a domain."""
        db = get_db_client()
        query = """
            SELECT id, domain_id, name, query_template, context, priority,
                   search_recency_filter, is_active
            FROM research_topics
            WHERE domain_id = $1
        """
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY priority DESC"

        rows = await db.fetch(query, domain_id)
        return [
            ResearchTopic(
                id=row["id"],
                domain_id=row["domain_id"],
                name=row["name"],
                query_template=row["query_template"],
                context=row["context"],
                priority=row["priority"],
                search_recency_filter=row["search_recency_filter"],
                is_active=row["is_active"],
            )
            for row in rows
        ]

    def _expand_prompt(
        self,
        template: str,
        topic: ResearchTopic,
        recency: str,
        extra_context: Optional[str] = None
    ) -> str:
        """Expand prompt template with topic data."""
        context_parts = []
        if topic.context:
            context_parts.append(topic.context)
        if extra_context:
            context_parts.append(extra_context)

        return template.format(
            topic=topic.name,
            context=" ".join(context_parts) if context_parts else "General research",
            recency=recency,
            date=datetime.now().strftime("%Y-%m-%d"),
        )

    async def research_topic(
        self,
        domain: ResearchDomain,
        topic: ResearchTopic,
        extra_context: Optional[str] = None,
    ) -> ResearchResult:
        """Execute research for a single topic."""
        # Use topic template override or domain default
        template = topic.query_template or domain.prompt_template
        recency = topic.search_recency_filter or domain.search_recency_filter

        # Expand prompt
        query = self._expand_prompt(template, topic, recency, extra_context)

        # Execute search
        db = get_db_client()
        response = await self.perplexity.search(
            query=query,
            model=domain.default_model,
            search_recency_filter=recency,
            max_tokens=domain.max_tokens,
            temperature=domain.temperature,
            db_client=db,
        )

        # Parse structured data if schema defined
        structured_data = None
        if domain.output_schema:
            structured_data = self._try_parse_structured(
                response.content,
                domain.output_schema
            )

        # Generate title and summary
        title = f"{topic.name} Research - {datetime.now().strftime('%Y-%m-%d')}"
        summary = self._extract_summary(response.content)

        return ResearchResult(
            topic_id=topic.id,
            topic_name=topic.name,
            title=title,
            summary=summary,
            content=response.content,
            structured_data=structured_data,
            sources=[
                {
                    "url": s["url"],
                    "domain": s["domain"],
                }
                for s in response.sources
            ],
            confidence_score=self._calculate_confidence(response),
            query_used=query,
            model_used=response.model,
        )

    def _try_parse_structured(
        self,
        content: str,
        schema: Dict
    ) -> Optional[Dict]:
        """Try to extract structured data from content."""
        # Look for JSON blocks in response
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try parsing the entire content as JSON (for API responses)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        return None

    def _extract_summary(self, content: str, max_length: int = 500) -> str:
        """Extract a summary from the content."""
        # Take first paragraph or first N characters
        paragraphs = content.split('\n\n')
        first_para = paragraphs[0] if paragraphs else content

        if len(first_para) <= max_length:
            return first_para
        return first_para[:max_length - 3] + "..."

    def _calculate_confidence(self, response: PerplexityResponse) -> float:
        """Calculate confidence score based on response quality."""
        score = 0.5  # Base score

        # More sources = higher confidence
        source_count = len(response.sources)
        if source_count >= 5:
            score += 0.2
        elif source_count >= 3:
            score += 0.1
        elif source_count >= 1:
            score += 0.05

        # Content length indicates depth
        content_len = len(response.content)
        if content_len >= 2000:
            score += 0.2
        elif content_len >= 1000:
            score += 0.1
        elif content_len >= 500:
            score += 0.05

        # Cap at 1.0
        return min(score, 1.0)

    async def run_domain_research(
        self,
        domain_name: str,
        topic_names: Optional[List[str]] = None,
        triggered_by: str = "manual",
        extra_context: Optional[str] = None,
    ) -> ResearchSession:
        """
        Run research for an entire domain or specific topics.

        Args:
            domain_name: Name of the domain to research
            topic_names: Optional list of specific topics (default: all active)
            triggered_by: Who/what triggered this research
            extra_context: Additional context for all queries

        Returns:
            ResearchSession with results and statistics
        """
        db = get_db_client()

        # Get domain
        domain = await self.get_domain(domain_name)
        if not domain:
            raise ValueError(f"Domain not found: {domain_name}")

        if not domain.is_active:
            raise ValueError(f"Domain is inactive: {domain_name}")

        # Create session
        session_id = str(uuid.uuid4())
        session = ResearchSession(
            session_id=session_id,
            domain_id=domain.id,
            domain_name=domain.name,
            triggered_by=triggered_by,
            started_at=datetime.now(),
        )

        # Insert session record
        await db.execute(
            """
            INSERT INTO research_sessions (id, domain_id, triggered_by, trigger_context, status)
            VALUES ($1, $2, $3, $4, $5)
            """,
            uuid.UUID(session_id),
            domain.id,
            triggered_by,
            json.dumps({"extra_context": extra_context}) if extra_context else None,
            "running"
        )

        # Get topics
        all_topics = await self.get_topics(domain.id, active_only=True)
        if topic_names:
            topics = [t for t in all_topics if t.name in topic_names]
        else:
            topics = all_topics

        logger.info(f"Starting research session {session_id} for {domain_name} with {len(topics)} topics")

        # Research each topic
        for topic in topics:
            try:
                result = await self.research_topic(domain, topic, extra_context)
                session.api_calls += 1
                session.topics_processed += 1

                # Persist result
                item_id = await self._persist_result(session_id, domain, result)
                if item_id:
                    session.items_created += 1

                # Update topic last_researched
                await db.execute(
                    """
                    UPDATE research_topics
                    SET last_researched_at = NOW(), research_count = research_count + 1
                    WHERE id = $1
                    """,
                    topic.id
                )

            except Exception as e:
                logger.error(f"Error researching topic {topic.name}: {e}")
                session.errors.append({
                    "topic": topic.name,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                })

        # Complete session
        session.completed_at = datetime.now()
        session.status = "completed" if not session.errors else "completed_with_errors"

        # Update session record
        await db.execute(
            """
            UPDATE research_sessions
            SET completed_at = $2, status = $3, topics_processed = $4,
                items_created = $5, errors = $6, api_calls = $7, tokens_used = $8
            WHERE id = $1
            """,
            uuid.UUID(session_id),
            session.completed_at,
            session.status,
            session.topics_processed,
            session.items_created,
            json.dumps(session.errors) if session.errors else None,
            session.api_calls,
            session.tokens_used,
        )

        # Update domain last_research_at
        await db.execute(
            """
            UPDATE research_domains SET last_research_at = NOW() WHERE id = $1
            """,
            domain.id
        )

        logger.info(
            f"Research session {session_id} completed: "
            f"{session.items_created} items, {len(session.errors)} errors"
        )

        return session

    async def _persist_result(
        self,
        session_id: str,
        domain: ResearchDomain,
        result: ResearchResult
    ) -> Optional[int]:
        """Persist a research result to the database."""
        db = get_db_client()

        try:
            item_id = await db.fetchval(
                """
                INSERT INTO research_items (
                    domain_id, topic_id, title, summary, content,
                    structured_data, sources, source_count, query_used,
                    model_used, research_session_id, confidence_score, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING id
                """,
                domain.id,
                result.topic_id,
                result.title,
                result.summary,
                result.content,
                json.dumps(result.structured_data) if result.structured_data else None,
                json.dumps(result.sources),
                len(result.sources),
                result.query_used,
                result.model_used,
                uuid.UUID(session_id),
                result.confidence_score,
                "new"
            )
            return item_id

        except Exception as e:
            logger.error(f"Failed to persist research result: {e}")
            return None

    async def get_recent_items(
        self,
        domain_name: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Get recent research items."""
        db = get_db_client()

        query = """
            SELECT
                i.id, i.title, i.summary, i.created_at, i.status,
                i.confidence_score, i.source_count,
                d.name as domain_name, d.display_name as domain_display,
                t.name as topic_name
            FROM research_items i
            JOIN research_domains d ON d.id = i.domain_id
            LEFT JOIN research_topics t ON t.id = i.topic_id
        """
        params = []

        if domain_name:
            query += " WHERE d.name = $1"
            params.append(domain_name)

        query += " ORDER BY i.created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        rows = await db.fetch(query, *params)
        return [dict(row) for row in rows]

    async def get_domain_stats(self) -> List[Dict]:
        """Get statistics for all domains."""
        db = get_db_client()
        rows = await db.fetch("SELECT * FROM v_research_domain_stats ORDER BY item_count DESC")
        return [dict(row) for row in rows]


# Singleton
_service: Optional[ResearchService] = None


def get_research_service() -> ResearchService:
    """Get or create the research service singleton."""
    global _service
    if _service is None:
        _service = ResearchService()
    return _service
