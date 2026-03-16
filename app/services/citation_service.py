"""
Citation Grounding Service (Phase S1).

Anti-Halluzination Layer: Links facts to verifiable sources.

Features:
- Track citations for facts
- Manage source trust scores
- Update verification status automatically
- Flag conflicting citations
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Singleton
_citation_service = None


def get_citation_service():
    """Get singleton instance."""
    global _citation_service
    if _citation_service is None:
        _citation_service = CitationService()
    return _citation_service


@dataclass
class Citation:
    """A citation linking a fact to a source."""
    id: int
    fact_id: str
    source_id: Optional[int]
    url: str
    title: Optional[str]
    excerpt: Optional[str]
    access_date: datetime
    relevance_score: float
    supports_fact: bool
    source_domain: Optional[str] = None
    source_trust: Optional[float] = None


@dataclass
class CitationSource:
    """A registered citation source."""
    id: int
    domain: str
    display_name: Optional[str]
    trust_score: float
    source_type: str
    is_trusted: bool
    citation_count: int


class CitationService:
    """
    Service for managing fact citations.

    Handles:
    - Adding citations to facts
    - Managing source trust scores
    - Updating verification status
    - Querying citations
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _get_cursor(self):
        """Get database cursor context manager."""
        from app.postgres_state import get_cursor
        return get_cursor()

    # =========================================================================
    # Citation Management
    # =========================================================================

    def add_citation(
        self,
        fact_id: str,
        url: str,
        title: Optional[str] = None,
        excerpt: Optional[str] = None,
        relevance_score: float = 0.5,
        supports_fact: bool = True,
        context: Optional[Dict] = None,
        created_by: str = "system"
    ) -> Tuple[Citation, str]:
        """
        Add a citation to a fact.

        Returns:
            (Citation, new_verification_status)
        """
        import json

        # Extract domain
        domain = self._extract_domain(url)

        # Get or create source
        source_id = self._get_or_create_source(domain)

        with self._get_cursor() as cur:
            # Insert citation (upsert)
            cur.execute(
                """
                INSERT INTO fact_citations
                    (fact_id, source_id, url, title, excerpt, relevance_score,
                     supports_fact, context, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fact_id, url) DO UPDATE SET
                    title = EXCLUDED.title,
                    excerpt = EXCLUDED.excerpt,
                    relevance_score = EXCLUDED.relevance_score,
                    supports_fact = EXCLUDED.supports_fact,
                    context = EXCLUDED.context
                RETURNING id, access_date
                """,
                (fact_id, source_id, url, title, excerpt,
                 relevance_score, supports_fact,
                 json.dumps(context) if context else None, created_by)
            )
            row = cur.fetchone()
            citation_id = row[0]
            access_date = row[1]

            # Update source citation count
            cur.execute(
                """
                UPDATE citation_sources
                SET citation_count = citation_count + 1,
                    last_cited_at = NOW()
                WHERE id = %s
                """,
                (source_id,)
            )

        # Update fact verification status
        new_status = self._update_verification_status(fact_id)

        citation = Citation(
            id=citation_id,
            fact_id=fact_id,
            source_id=source_id,
            url=url,
            title=title,
            excerpt=excerpt,
            access_date=access_date,
            relevance_score=relevance_score,
            supports_fact=supports_fact,
            source_domain=domain,
        )

        self.logger.info(
            f"Added citation for fact {fact_id}: {domain} "
            f"(supports={supports_fact}, status={new_status})"
        )

        return citation, new_status

    def add_citations_from_research(
        self,
        fact_id: str,
        sources: List[Dict],
        query_used: Optional[str] = None
    ) -> List[Citation]:
        """
        Add multiple citations from research results.

        Args:
            fact_id: The fact to cite
            sources: List of {url, domain, title?, excerpt?}
            query_used: The research query (for context)
        """
        citations = []
        context = {"research_query": query_used} if query_used else None

        for source in sources:
            url = source.get("url")
            if not url:
                continue

            citation, _ = self.add_citation(
                fact_id=fact_id,
                url=url,
                title=source.get("title"),
                excerpt=source.get("excerpt"),
                relevance_score=source.get("relevance", 0.6),
                supports_fact=True,
                context=context,
                created_by="research"
            )
            citations.append(citation)

        return citations

    def get_citations(self, fact_id: str) -> List[Citation]:
        """Get all citations for a fact."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    fc.id, fc.fact_id, fc.source_id, fc.url, fc.title,
                    fc.excerpt, fc.access_date, fc.relevance_score, fc.supports_fact,
                    cs.domain as source_domain, cs.trust_score as source_trust
                FROM fact_citations fc
                LEFT JOIN citation_sources cs ON fc.source_id = cs.id
                WHERE fc.fact_id = %s
                ORDER BY fc.relevance_score DESC
                """,
                (fact_id,)
            )
            rows = cur.fetchall()

        return [
            Citation(
                id=row[0],
                fact_id=row[1],
                source_id=row[2],
                url=row[3],
                title=row[4],
                excerpt=row[5],
                access_date=row[6],
                relevance_score=row[7],
                supports_fact=row[8],
                source_domain=row[9],
                source_trust=row[10],
            )
            for row in rows
        ]

    def remove_citation(self, citation_id: int) -> bool:
        """Remove a citation."""
        with self._get_cursor() as cur:
            cur.execute(
                "DELETE FROM fact_citations WHERE id = %s RETURNING fact_id",
                (citation_id,)
            )
            row = cur.fetchone()

        if row:
            self._update_verification_status(row[0])
            return True
        return False

    # =========================================================================
    # Verification Status
    # =========================================================================

    def get_verification_status(self, fact_id: str) -> Dict:
        """Get detailed verification status for a fact."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    verification_status,
                    verification_count,
                    last_verified_at
                FROM learned_facts
                WHERE id = %s
                """,
                (fact_id,)
            )
            row = cur.fetchone()

        if not row:
            return {"error": "Fact not found"}

        citations = self.get_citations(fact_id)

        supporting = [c for c in citations if c.supports_fact]
        contradicting = [c for c in citations if not c.supports_fact]
        trusted = [c for c in supporting if c.source_trust and c.source_trust >= 0.7]

        return {
            "fact_id": fact_id,
            "status": row[0],
            "citation_count": row[1],
            "last_verified_at": row[2],
            "supporting_citations": len(supporting),
            "contradicting_citations": len(contradicting),
            "trusted_citations": len(trusted),
            "primary_sources": [c.source_domain for c in trusted[:3]],
        }

    def mark_verified(self, fact_id: str, verified_by: str = "user") -> str:
        """Manually mark a fact as verified."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                UPDATE learned_facts
                SET verification_status = 'verified',
                    last_verified_at = NOW()
                WHERE id = %s
                """,
                (fact_id,)
            )

            # Log the manual verification
            cur.execute(
                """
                INSERT INTO verification_requests
                    (fact_id, request_reason, status, verified_by, completed_at)
                VALUES (%s, 'manual verification', 'completed', %s, NOW())
                """,
                (fact_id, verified_by)
            )

        return "verified"

    def request_verification(
        self,
        fact_id: str,
        reason: Optional[str] = None,
        priority: int = 0
    ) -> int:
        """Queue a fact for manual verification."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO verification_requests
                    (fact_id, request_reason, priority, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING id
                """,
                (fact_id, reason, priority)
            )
            row = cur.fetchone()
        return row[0]

    def get_pending_verifications(self, limit: int = 20) -> List[Dict]:
        """Get facts pending verification."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    vr.id as request_id,
                    vr.fact_id,
                    vr.request_reason,
                    vr.priority,
                    vr.created_at,
                    f.key,
                    f.value_text,
                    f.confidence
                FROM verification_requests vr
                JOIN learned_facts f ON vr.fact_id = f.id
                WHERE vr.status = 'pending'
                ORDER BY vr.priority DESC, vr.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            rows = cur.fetchall()

        return [
            {
                "request_id": row[0],
                "fact_id": row[1],
                "request_reason": row[2],
                "priority": row[3],
                "created_at": row[4],
                "key": row[5],
                "value_text": row[6],
                "confidence": row[7],
            }
            for row in rows
        ]

    # =========================================================================
    # Source Management
    # =========================================================================

    def get_source(self, domain: str) -> Optional[CitationSource]:
        """Get a citation source by domain."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT id, domain, display_name, trust_score, source_type,
                       is_trusted, citation_count
                FROM citation_sources
                WHERE domain = %s
                """,
                (domain,)
            )
            row = cur.fetchone()

        if not row:
            return None

        return CitationSource(
            id=row[0],
            domain=row[1],
            display_name=row[2],
            trust_score=row[3],
            source_type=row[4],
            is_trusted=row[5],
            citation_count=row[6],
        )

    def set_source_trust(
        self,
        domain: str,
        trust_score: float,
        is_trusted: Optional[bool] = None
    ) -> bool:
        """Update trust score for a source."""
        trust_score = max(0.0, min(1.0, trust_score))

        if is_trusted is None:
            is_trusted = trust_score >= 0.7

        with self._get_cursor() as cur:
            cur.execute(
                """
                UPDATE citation_sources
                SET trust_score = %s, is_trusted = %s
                WHERE domain = %s
                """,
                (trust_score, is_trusted, domain)
            )
            return cur.rowcount > 0

    def get_source_stats(self) -> List[Dict]:
        """Get statistics for all sources."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM v_citation_source_stats
                ORDER BY actual_citations DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [dict(zip(columns, row)) for row in rows]

    def register_source(
        self,
        domain: str,
        display_name: Optional[str] = None,
        trust_score: float = 0.5,
        source_type: str = "web",
        is_trusted: bool = False
    ) -> CitationSource:
        """Register a new citation source."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO citation_sources
                    (domain, display_name, trust_score, source_type, is_trusted)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (domain) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, citation_sources.display_name),
                    trust_score = EXCLUDED.trust_score,
                    source_type = EXCLUDED.source_type,
                    is_trusted = EXCLUDED.is_trusted
                RETURNING id, citation_count
                """,
                (domain, display_name, trust_score, source_type, is_trusted)
            )
            row = cur.fetchone()

        return CitationSource(
            id=row[0],
            domain=domain,
            display_name=display_name,
            trust_score=trust_score,
            source_type=source_type,
            is_trusted=is_trusted,
            citation_count=row[1],
        )

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_unverified_facts(
        self,
        limit: int = 50,
        min_confidence: float = 0.5
    ) -> List[Dict]:
        """Get facts that need verification."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM v_unverified_facts
                WHERE confidence >= %s
                LIMIT %s
                """,
                (min_confidence, limit)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [dict(zip(columns, row)) for row in rows]

    def get_conflicting_facts(self, limit: int = 20) -> List[Dict]:
        """Get facts with conflicting citations."""
        with self._get_cursor() as cur:
            cur.execute(
                "SELECT * FROM v_conflicting_facts LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [dict(zip(columns, row)) for row in rows]

    def get_facts_by_source(self, domain: str, limit: int = 50) -> List[Dict]:
        """Get all facts cited from a specific source."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    f.id, f.key, f.value_text, f.confidence,
                    f.verification_status,
                    fc.url, fc.title, fc.supports_fact
                FROM learned_facts f
                JOIN fact_citations fc ON f.id = fc.fact_id
                JOIN citation_sources cs ON fc.source_id = cs.id
                WHERE cs.domain = %s
                ORDER BY fc.access_date DESC
                LIMIT %s
                """,
                (domain, limit)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [dict(zip(columns, row)) for row in rows]

    def search_citations(self, query: str, limit: int = 20) -> List[Dict]:
        """Search citations by URL or title."""
        search_pattern = f"%{query}%"
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    fc.id, fc.fact_id, fc.url, fc.title, fc.excerpt,
                    fc.relevance_score, fc.supports_fact,
                    cs.domain, cs.trust_score,
                    f.key as fact_key, f.value_text as fact_value
                FROM fact_citations fc
                LEFT JOIN citation_sources cs ON fc.source_id = cs.id
                JOIN learned_facts f ON fc.fact_id = f.id
                WHERE fc.url ILIKE %s
                   OR fc.title ILIKE %s
                   OR f.value_text ILIKE %s
                ORDER BY fc.relevance_score DESC
                LIMIT %s
                """,
                (search_pattern, search_pattern, search_pattern, limit)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [dict(zip(columns, row)) for row in rows]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_citation_stats(self) -> Dict:
        """Get overall citation statistics."""
        with self._get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM learned_facts WHERE status = 'active') as total_facts,
                    (SELECT COUNT(*) FROM learned_facts WHERE verification_status = 'verified') as verified_facts,
                    (SELECT COUNT(*) FROM learned_facts WHERE verification_status = 'unverified') as unverified_facts,
                    (SELECT COUNT(*) FROM learned_facts WHERE verification_status = 'contradicted') as contradicted_facts,
                    (SELECT COUNT(*) FROM fact_citations) as total_citations,
                    (SELECT COUNT(*) FROM citation_sources) as total_sources,
                    (SELECT COUNT(*) FROM citation_sources WHERE is_trusted) as trusted_sources,
                    (SELECT COUNT(*) FROM verification_requests WHERE status = 'pending') as pending_verifications
                """
            )
            row = cur.fetchone()

        total = row[0] or 1
        return {
            "total_facts": row[0],
            "verified_facts": row[1],
            "unverified_facts": row[2],
            "contradicted_facts": row[3],
            "verification_rate": round((row[1] or 0) / total * 100, 1),
            "total_citations": row[4],
            "total_sources": row[5],
            "trusted_sources": row[6],
            "pending_verifications": row[7],
        }

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url

    def _get_or_create_source(self, domain: str) -> int:
        """Get source ID, creating if needed."""
        with self._get_cursor() as cur:
            cur.execute(
                "SELECT id FROM citation_sources WHERE domain = %s",
                (domain,)
            )
            row = cur.fetchone()
            if row:
                return row[0]

            # Create new source with default trust
            cur.execute(
                """
                INSERT INTO citation_sources (domain, trust_score)
                VALUES (%s, 0.5)
                RETURNING id
                """,
                (domain,)
            )
            row = cur.fetchone()
            return row[0]

    def _update_verification_status(self, fact_id: str) -> str:
        """Update verification status based on citations."""
        with self._get_cursor() as cur:
            cur.execute(
                "SELECT update_fact_verification_status(%s) as status",
                (fact_id,)
            )
            row = cur.fetchone()
        return row[0] if row else "unknown"
