"""
T-22C-01: Pattern Generalization Engine
Phase 22 - Emergent Intelligence

Extracts domain-agnostic patterns from CK-Track data and enables
cross-domain knowledge transfer.

Example:
    Domain-Specific:
        "User skips gym when stressed" (fitness)
        "User delays complex tasks when tired" (work)

    Generalized Pattern:
        "Low energy state --> Reduced capacity for demanding activities"

    Transfer:
        When FitJarvis detects fatigue --> WorkJarvis suggests lighter tasks
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import re

from ..observability import get_logger
from ..postgres_state import get_conn
from psycopg2.extras import RealDictCursor

logger = get_logger("jarvis.pattern_generalization")


class PatternDomain(str, Enum):
    """Domains for pattern classification."""
    FITNESS = "fitness"
    WORK = "work"
    COMMUNICATION = "communication"
    FINANCE = "finance"
    LEARNING = "learning"
    CROSS_DOMAIN = "cross_domain"


class TransferStatus(str, Enum):
    """Status of pattern transfer attempts."""
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    TESTING = "testing"


@dataclass
class AbstractPattern:
    """A domain-agnostic pattern extracted from specific observations."""
    pattern_id: str
    abstract_form: str
    source_domains: List[str] = field(default_factory=list)
    evidence_count: int = 0
    confidence: float = 0.5
    applicable_domains: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None


@dataclass
class PatternTransfer:
    """A transfer of a pattern to a new domain."""
    transfer_id: int
    source_pattern_id: int
    abstract_pattern_id: str
    target_domain: str
    transfer_confidence: float = 0.5
    validation_attempts: int = 0
    validation_successes: int = 0
    status: TransferStatus = TransferStatus.PENDING


# Keywords that indicate domain-agnostic concepts
ABSTRACT_CONCEPTS = {
    "energy_state": [
        "tired", "fatigue", "exhausted", "energy", "energized",
        "motivated", "unmotivated", "lazy", "active", "alert"
    ],
    "stress_level": [
        "stressed", "stress", "anxious", "overwhelmed", "pressure",
        "relaxed", "calm", "peaceful", "tense"
    ],
    "time_pressure": [
        "deadline", "urgent", "rushing", "late", "delayed",
        "plenty of time", "ahead of schedule", "on track"
    ],
    "complexity": [
        "complex", "complicated", "difficult", "challenging", "hard",
        "simple", "easy", "straightforward", "routine"
    ],
    "social_context": [
        "alone", "with others", "social", "isolated", "group",
        "meeting", "conversation", "interaction"
    ],
    "capacity": [
        "overloaded", "capacity", "bandwidth", "available", "busy",
        "free", "overwhelmed", "manageable"
    ]
}

# Domain-specific to abstract mappings
DOMAIN_ABSTRACTIONS = {
    "fitness": {
        "skips gym": "avoids demanding activity",
        "works out": "engages in demanding activity",
        "rests": "reduces activity level",
        "eats junk": "makes suboptimal choices",
        "eats healthy": "makes optimal choices",
        "sleeps poorly": "recovery impaired",
        "sleeps well": "recovery optimal"
    },
    "work": {
        "delays tasks": "avoids demanding activity",
        "tackles hard problems": "engages in demanding activity",
        "takes breaks": "reduces activity level",
        "procrastinates": "makes suboptimal choices",
        "prioritizes well": "makes optimal choices",
        "works late": "recovery impaired",
        "maintains boundaries": "recovery optimal"
    },
    "communication": {
        "avoids calls": "avoids demanding activity",
        "initiates contact": "engages in demanding activity",
        "short responses": "reduces activity level",
        "ignores messages": "makes suboptimal choices",
        "responds promptly": "makes optimal choices",
        "always available": "recovery impaired",
        "healthy boundaries": "recovery optimal"
    }
}


class PatternGeneralizationService:
    """
    Service for extracting and transferring domain-agnostic patterns.

    Workflow:
    1. Analyze CK-Track patterns from multiple domains
    2. Identify common abstract structures
    3. Create generalized pattern representations
    4. Test transfers to new domains
    5. Validate and incorporate successful transfers
    """

    def __init__(self):
        self._ensure_tables()
        logger.info("PatternGeneralizationService initialized")

    def _ensure_tables(self):
        """Ensure required tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_abstract_patterns (
                            id SERIAL PRIMARY KEY,
                            pattern_id VARCHAR(50) UNIQUE NOT NULL,
                            abstract_form TEXT NOT NULL,
                            source_domains JSONB DEFAULT '[]',
                            evidence_count INTEGER DEFAULT 0,
                            confidence FLOAT DEFAULT 0.5,
                            applicable_domains JSONB DEFAULT '[]',
                            source_pattern_ids JSONB DEFAULT '[]',
                            created_at TIMESTAMP DEFAULT NOW(),
                            last_validated_at TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_knowledge_transfers (
                            id SERIAL PRIMARY KEY,
                            source_pattern_id INTEGER,
                            abstract_pattern_id VARCHAR(50),
                            source_domain VARCHAR(50),
                            target_domain VARCHAR(50) NOT NULL,
                            transfer_confidence FLOAT DEFAULT 0.5,
                            validation_attempts INTEGER DEFAULT 0,
                            validation_successes INTEGER DEFAULT 0,
                            status VARCHAR(20) DEFAULT 'pending',
                            created_at TIMESTAMP DEFAULT NOW(),
                            last_tested_at TIMESTAMP
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_abstract_patterns_domains
                        ON jarvis_abstract_patterns USING GIN (source_domains)
                    """)

                    conn.commit()
        except Exception as e:
            logger.warning(f"Table creation check failed: {e}")

    def extract_abstract_form(self, cause: str, effect: str, domain: str = None) -> Tuple[str, float]:
        """
        Extract the abstract form of a cause-effect pattern.

        Returns: (abstract_form, confidence)
        """
        cause_lower = cause.lower()
        effect_lower = effect.lower()

        # Check for known abstractions
        abstract_cause = cause_lower
        abstract_effect = effect_lower

        if domain and domain in DOMAIN_ABSTRACTIONS:
            mappings = DOMAIN_ABSTRACTIONS[domain]
            for specific, abstract in mappings.items():
                if specific in cause_lower:
                    abstract_cause = abstract
                    break

            for specific, abstract in mappings.items():
                if specific in effect_lower:
                    abstract_effect = abstract
                    break

        # Check for abstract concepts
        cause_concept = self._detect_abstract_concept(cause_lower)
        effect_concept = self._detect_abstract_concept(effect_lower)

        if cause_concept:
            abstract_cause = f"[{cause_concept}]"
        if effect_concept:
            abstract_effect = f"[{effect_concept}]"

        # Build abstract form
        abstract_form = f"{abstract_cause} --> {abstract_effect}"

        # Calculate confidence based on abstraction quality
        confidence = 0.5
        if cause_concept or effect_concept:
            confidence += 0.2
        if abstract_cause != cause_lower or abstract_effect != effect_lower:
            confidence += 0.1

        return abstract_form, min(confidence, 0.9)

    def _detect_abstract_concept(self, text: str) -> Optional[str]:
        """Detect which abstract concept a text relates to."""
        for concept, keywords in ABSTRACT_CONCEPTS.items():
            for keyword in keywords:
                if keyword in text:
                    return concept
        return None

    def generalize_pattern(
        self,
        user_id: str,
        cause: str,
        effect: str,
        domain: str,
        source_pattern_id: int = None
    ) -> Dict[str, Any]:
        """
        Create or update a generalized pattern from a domain-specific observation.
        """
        abstract_form, confidence = self.extract_abstract_form(cause, effect, domain)

        # Generate pattern ID from abstract form
        import hashlib
        pattern_id = f"ap_{hashlib.md5(abstract_form.encode()).hexdigest()[:12]}"

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if abstract pattern exists
                cur.execute("""
                    SELECT id, pattern_id, source_domains, evidence_count, confidence,
                           source_pattern_ids
                    FROM jarvis_abstract_patterns
                    WHERE pattern_id = %s
                """, (pattern_id,))
                existing = cur.fetchone()

                if existing:
                    # Update existing pattern
                    source_domains = existing['source_domains'] or []
                    if domain not in source_domains:
                        source_domains.append(domain)

                    source_ids = existing['source_pattern_ids'] or []
                    if source_pattern_id and source_pattern_id not in source_ids:
                        source_ids.append(source_pattern_id)

                    new_count = existing['evidence_count'] + 1
                    # Confidence increases with cross-domain evidence
                    new_confidence = min(0.95, existing['confidence'] + 0.03 * len(source_domains))

                    cur.execute("""
                        UPDATE jarvis_abstract_patterns
                        SET source_domains = %s,
                            evidence_count = %s,
                            confidence = %s,
                            source_pattern_ids = %s,
                            updated_at = NOW()
                        WHERE pattern_id = %s
                    """, (
                        json.dumps(source_domains),
                        new_count,
                        new_confidence,
                        json.dumps(source_ids),
                        pattern_id
                    ))

                    result = {
                        "pattern_id": pattern_id,
                        "abstract_form": abstract_form,
                        "is_new": False,
                        "evidence_count": new_count,
                        "source_domains": source_domains,
                        "confidence": new_confidence
                    }
                else:
                    # Create new abstract pattern
                    source_ids = [source_pattern_id] if source_pattern_id else []

                    cur.execute("""
                        INSERT INTO jarvis_abstract_patterns
                        (pattern_id, abstract_form, source_domains, evidence_count,
                         confidence, applicable_domains, source_pattern_ids)
                        VALUES (%s, %s, %s, 1, %s, %s, %s)
                    """, (
                        pattern_id,
                        abstract_form,
                        json.dumps([domain]),
                        confidence,
                        json.dumps([domain]),
                        json.dumps(source_ids)
                    ))

                    result = {
                        "pattern_id": pattern_id,
                        "abstract_form": abstract_form,
                        "is_new": True,
                        "evidence_count": 1,
                        "source_domains": [domain],
                        "confidence": confidence
                    }

                conn.commit()

        logger.info(f"Generalized pattern: {abstract_form} ({pattern_id})")
        return result

    def find_transfer_candidates(
        self,
        domain: str,
        min_confidence: float = 0.6,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find patterns that could be transferred to a new domain.

        Returns patterns that:
        - Have high confidence in other domains
        - Haven't been tested in the target domain yet
        """
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT ap.pattern_id, ap.abstract_form, ap.source_domains,
                           ap.confidence, ap.evidence_count
                    FROM jarvis_abstract_patterns ap
                    WHERE ap.confidence >= %s
                      AND NOT (ap.applicable_domains ? %s)
                      AND jsonb_array_length(ap.source_domains) >= 1
                    ORDER BY ap.confidence DESC, ap.evidence_count DESC
                    LIMIT %s
                """, (min_confidence, domain, limit))

                candidates = []
                for row in cur.fetchall():
                    # Calculate transfer potential
                    source_count = len(row['source_domains'] or [])
                    transfer_potential = row['confidence'] * (0.7 + 0.1 * min(source_count, 3))

                    candidates.append({
                        "pattern_id": row['pattern_id'],
                        "abstract_form": row['abstract_form'],
                        "source_domains": row['source_domains'],
                        "confidence": row['confidence'],
                        "evidence_count": row['evidence_count'],
                        "transfer_potential": round(transfer_potential, 3)
                    })

                return candidates

    def initiate_transfer(
        self,
        abstract_pattern_id: str,
        target_domain: str,
        source_pattern_id: int = None
    ) -> Dict[str, Any]:
        """Start a pattern transfer to a new domain."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get abstract pattern
                cur.execute("""
                    SELECT pattern_id, abstract_form, source_domains, confidence
                    FROM jarvis_abstract_patterns
                    WHERE pattern_id = %s
                """, (abstract_pattern_id,))
                pattern = cur.fetchone()

                if not pattern:
                    return {"success": False, "error": "Pattern not found"}

                source_domain = (pattern['source_domains'] or [None])[0]

                # Check if transfer already exists
                cur.execute("""
                    SELECT id, status, validation_attempts
                    FROM jarvis_knowledge_transfers
                    WHERE abstract_pattern_id = %s AND target_domain = %s
                """, (abstract_pattern_id, target_domain))
                existing = cur.fetchone()

                if existing:
                    return {
                        "success": True,
                        "transfer_id": existing['id'],
                        "status": existing['status'],
                        "already_exists": True
                    }

                # Create new transfer
                cur.execute("""
                    INSERT INTO jarvis_knowledge_transfers
                    (source_pattern_id, abstract_pattern_id, source_domain,
                     target_domain, transfer_confidence, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending')
                    RETURNING id
                """, (
                    source_pattern_id,
                    abstract_pattern_id,
                    source_domain,
                    target_domain,
                    pattern['confidence'] * 0.7  # Initial transfer confidence
                ))
                transfer_id = cur.fetchone()['id']
                conn.commit()

                logger.info(f"Initiated transfer {transfer_id}: {abstract_pattern_id} -> {target_domain}")
                return {
                    "success": True,
                    "transfer_id": transfer_id,
                    "abstract_form": pattern['abstract_form'],
                    "target_domain": target_domain,
                    "initial_confidence": pattern['confidence'] * 0.7,
                    "already_exists": False
                }

    def validate_transfer(
        self,
        transfer_id: int,
        success: bool,
        evidence: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Record a validation attempt for a transfer."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT abstract_pattern_id, target_domain, validation_attempts,
                           validation_successes, transfer_confidence
                    FROM jarvis_knowledge_transfers
                    WHERE id = %s
                """, (transfer_id,))
                transfer = cur.fetchone()

                if not transfer:
                    return {"success": False, "error": "Transfer not found"}

                new_attempts = transfer['validation_attempts'] + 1
                new_successes = transfer['validation_successes'] + (1 if success else 0)
                success_rate = new_successes / new_attempts

                # Adjust confidence based on validation results
                new_confidence = transfer['transfer_confidence']
                if success:
                    new_confidence = min(0.95, new_confidence + 0.1)
                else:
                    new_confidence = max(0.1, new_confidence - 0.15)

                # Determine status
                if new_attempts >= 3:
                    if success_rate >= 0.7:
                        status = "validated"
                    elif success_rate <= 0.3:
                        status = "rejected"
                    else:
                        status = "testing"
                else:
                    status = "testing"

                cur.execute("""
                    UPDATE jarvis_knowledge_transfers
                    SET validation_attempts = %s,
                        validation_successes = %s,
                        transfer_confidence = %s,
                        status = %s,
                        last_tested_at = NOW()
                    WHERE id = %s
                """, (new_attempts, new_successes, new_confidence, status, transfer_id))

                # If validated, add domain to applicable_domains
                if status == "validated":
                    cur.execute("""
                        UPDATE jarvis_abstract_patterns
                        SET applicable_domains = applicable_domains || %s,
                            last_validated_at = NOW()
                        WHERE pattern_id = %s
                          AND NOT (applicable_domains ? %s)
                    """, (
                        json.dumps([transfer['target_domain']]),
                        transfer['abstract_pattern_id'],
                        transfer['target_domain']
                    ))

                conn.commit()

                return {
                    "success": True,
                    "transfer_id": transfer_id,
                    "validation_attempts": new_attempts,
                    "validation_successes": new_successes,
                    "success_rate": round(success_rate, 2),
                    "new_confidence": round(new_confidence, 3),
                    "status": status
                }

    def get_applicable_patterns(
        self,
        domain: str,
        min_confidence: float = 0.6,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get patterns applicable to a domain (including transfers)."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT pattern_id, abstract_form, source_domains,
                           applicable_domains, confidence, evidence_count
                    FROM jarvis_abstract_patterns
                    WHERE confidence >= %s
                      AND (applicable_domains ? %s OR source_domains ? %s)
                    ORDER BY confidence DESC
                    LIMIT %s
                """, (min_confidence, domain, domain, limit))

                return [
                    {
                        "pattern_id": row['pattern_id'],
                        "abstract_form": row['abstract_form'],
                        "source_domains": row['source_domains'],
                        "applicable_domains": row['applicable_domains'],
                        "confidence": row['confidence'],
                        "evidence_count": row['evidence_count'],
                        "is_native": domain in (row['source_domains'] or []),
                        "is_transferred": domain in (row['applicable_domains'] or [])
                                          and domain not in (row['source_domains'] or [])
                    }
                    for row in cur.fetchall()
                ]

    def get_cross_domain_insights(self, user_id: str = None) -> Dict[str, Any]:
        """Get insights about cross-domain pattern learning."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Total patterns
                cur.execute("SELECT COUNT(*) as count FROM jarvis_abstract_patterns")
                total_patterns = cur.fetchone()['count']

                # Patterns by source domain count
                cur.execute("""
                    SELECT
                        jsonb_array_length(source_domains) as domain_count,
                        COUNT(*) as pattern_count
                    FROM jarvis_abstract_patterns
                    GROUP BY jsonb_array_length(source_domains)
                    ORDER BY domain_count
                """)
                by_domain_count = {
                    row['domain_count']: row['pattern_count']
                    for row in cur.fetchall()
                }

                # Transfer statistics
                cur.execute("""
                    SELECT
                        status,
                        COUNT(*) as count,
                        AVG(transfer_confidence) as avg_confidence
                    FROM jarvis_knowledge_transfers
                    GROUP BY status
                """)
                transfers = {
                    row['status']: {
                        "count": row['count'],
                        "avg_confidence": round(row['avg_confidence'] or 0, 3)
                    }
                    for row in cur.fetchall()
                }

                # Top cross-domain patterns
                cur.execute("""
                    SELECT pattern_id, abstract_form, source_domains, confidence
                    FROM jarvis_abstract_patterns
                    WHERE jsonb_array_length(source_domains) > 1
                    ORDER BY confidence DESC, jsonb_array_length(source_domains) DESC
                    LIMIT 5
                """)
                top_patterns = [
                    {
                        "pattern_id": row['pattern_id'],
                        "abstract_form": row['abstract_form'],
                        "domains": row['source_domains'],
                        "confidence": row['confidence']
                    }
                    for row in cur.fetchall()
                ]

                return {
                    "total_abstract_patterns": total_patterns,
                    "patterns_by_domain_coverage": by_domain_count,
                    "cross_domain_patterns": by_domain_count.get(2, 0) + by_domain_count.get(3, 0),
                    "transfer_statistics": transfers,
                    "top_cross_domain_patterns": top_patterns,
                    "generated_at": datetime.now().isoformat()
                }

    def get_pattern_stats(self) -> Dict[str, Any]:
        """Get overall pattern generalization statistics."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_patterns,
                        AVG(confidence) as avg_confidence,
                        SUM(evidence_count) as total_evidence,
                        COUNT(*) FILTER (WHERE jsonb_array_length(source_domains) > 1) as cross_domain_count
                    FROM jarvis_abstract_patterns
                """)
                stats = cur.fetchone()

                cur.execute("""
                    SELECT
                        COUNT(*) as total_transfers,
                        COUNT(*) FILTER (WHERE status = 'validated') as validated,
                        COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                        COUNT(*) FILTER (WHERE status = 'testing') as testing
                    FROM jarvis_knowledge_transfers
                """)
                transfer_stats = cur.fetchone()

                return {
                    "patterns": {
                        "total": stats['total_patterns'] or 0,
                        "avg_confidence": round(stats['avg_confidence'] or 0, 3),
                        "total_evidence": stats['total_evidence'] or 0,
                        "cross_domain": stats['cross_domain_count'] or 0
                    },
                    "transfers": {
                        "total": transfer_stats['total_transfers'] or 0,
                        "validated": transfer_stats['validated'] or 0,
                        "rejected": transfer_stats['rejected'] or 0,
                        "testing": transfer_stats['testing'] or 0
                    }
                }


# Singleton
_service: Optional[PatternGeneralizationService] = None


def get_pattern_generalization_service() -> PatternGeneralizationService:
    """Get or create the pattern generalization service."""
    global _service
    if _service is None:
        _service = PatternGeneralizationService()
    return _service
