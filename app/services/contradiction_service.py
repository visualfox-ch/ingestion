"""
Contradiction Resolution Service - Phase B3 (AGI Evolution)

Detects and resolves conflicting memories:
- Identify contradictions between facts
- Gather evidence for resolution
- Track fact versions over time
- Maintain consistency

Based on CLIN (Conceptual Lifelong Interaction) pattern.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Singleton instance
_contradiction_service = None


def get_contradiction_service():
    """Get or create the contradiction service singleton."""
    global _contradiction_service
    if _contradiction_service is None:
        _contradiction_service = ContradictionService()
    return _contradiction_service


class ContradictionService:
    """
    Service for detecting and resolving memory contradictions.

    Implements:
    - Automatic contradiction detection
    - Evidence-based resolution
    - Fact versioning
    - Consistency maintenance
    """

    def __init__(self):
        self.contradiction_types = {}
        self.evidence_sources = {}
        self._load_config()
        logger.info("ContradictionService initialized")

    def _get_cursor(self):
        """Get database cursor."""
        from app.db_client import get_cursor
        return get_cursor()

    def _load_config(self):
        """Load contradiction types and evidence sources."""
        try:
            with self._get_cursor() as cur:
                # Load contradiction types
                cur.execute("SELECT id, type_name, severity_default, resolution_strategy FROM contradiction_types")
                for row in cur.fetchall():
                    self.contradiction_types[row[1]] = {
                        'id': row[0],
                        'severity': row[2],
                        'strategy': row[3]
                    }

                # Load evidence sources
                cur.execute("SELECT source_name, reliability FROM evidence_sources")
                for row in cur.fetchall():
                    self.evidence_sources[row[0]] = row[1]

        except Exception as e:
            logger.warning(f"Could not load contradiction config: {e}")
            self.contradiction_types = {
                'factual': {'id': 1, 'severity': 0.7, 'strategy': 'evidence_based'},
                'temporal': {'id': 2, 'severity': 0.5, 'strategy': 'newer_wins'}
            }
            self.evidence_sources = {'user_statement': 0.9, 'system_observation': 0.8}

    # =========================================================================
    # CONTRADICTION DETECTION
    # =========================================================================

    def detect_contradiction(
        self,
        memory_a: Dict,
        memory_b: Dict,
        contradiction_type: str = None
    ) -> Dict[str, Any]:
        """
        Check if two memories contradict each other.

        Args:
            memory_a: First memory (id, key, content)
            memory_b: Second memory (id, key, content)
            contradiction_type: Type hint (factual, temporal, etc.)

        Returns:
            Dict with detection result
        """
        try:
            content_a = memory_a.get('content', '')
            content_b = memory_b.get('content', '')

            # Simple contradiction detection
            # In production, this would use semantic analysis
            is_contradiction = False
            detected_type = contradiction_type
            confidence = 0.0
            description = ""

            # Check for negation patterns
            negation_patterns = [
                (r'\bnot\b', r'\bis\b'),
                (r'\bnein\b', r'\bja\b'),
                (r'\bfalse\b', r'\btrue\b'),
                (r'\bnever\b', r'\balways\b'),
                (r'\bnie\b', r'\bimmer\b'),
            ]

            for neg_pattern, pos_pattern in negation_patterns:
                if (re.search(neg_pattern, content_a, re.I) and re.search(pos_pattern, content_b, re.I)) or \
                   (re.search(pos_pattern, content_a, re.I) and re.search(neg_pattern, content_b, re.I)):
                    is_contradiction = True
                    detected_type = detected_type or 'logical'
                    confidence = 0.6
                    description = "Negation pattern detected"
                    break

            # Check for conflicting numbers
            numbers_a = re.findall(r'\b\d+(?:\.\d+)?\b', content_a)
            numbers_b = re.findall(r'\b\d+(?:\.\d+)?\b', content_b)

            if numbers_a and numbers_b:
                # Check if they're about the same topic but different numbers
                common_words = set(content_a.lower().split()) & set(content_b.lower().split())
                if len(common_words) > 3 and numbers_a != numbers_b:
                    is_contradiction = True
                    detected_type = detected_type or 'quantity'
                    confidence = 0.5
                    description = f"Different quantities: {numbers_a} vs {numbers_b}"

            if not is_contradiction:
                return {
                    "success": True,
                    "is_contradiction": False,
                    "message": "No contradiction detected"
                }

            # Get type info
            type_info = self.contradiction_types.get(detected_type, {})
            severity = type_info.get('severity', 0.5)

            return {
                "success": True,
                "is_contradiction": True,
                "contradiction_type": detected_type,
                "confidence": confidence,
                "severity": severity,
                "description": description,
                "memory_a": memory_a.get('id') or memory_a.get('key'),
                "memory_b": memory_b.get('id') or memory_b.get('key')
            }

        except Exception as e:
            logger.error(f"Detect contradiction failed: {e}")
            return {"success": False, "error": str(e)}

    def report_contradiction(
        self,
        memory_a_key: str,
        memory_b_key: str,
        description: str,
        contradiction_type: str = "factual",
        evidence_for_a: List[Dict] = None,
        evidence_for_b: List[Dict] = None,
        domain: str = None,
        priority: str = "medium"
    ) -> Dict[str, Any]:
        """
        Report a contradiction for resolution.

        Args:
            memory_a_key: First memory key
            memory_b_key: Second memory key
            description: Description of the contradiction
            contradiction_type: Type (factual, temporal, logical, etc.)
            evidence_for_a: Evidence supporting memory A
            evidence_for_b: Evidence supporting memory B
            domain: Domain/category
            priority: Priority level

        Returns:
            Dict with detection ID
        """
        try:
            import json

            type_info = self.contradiction_types.get(contradiction_type, {})
            type_id = type_info.get('id')
            severity = type_info.get('severity', 0.5)

            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO contradiction_detections
                    (memory_key_a, memory_key_b, contradiction_type_id,
                     description, severity, evidence_for_a, evidence_for_b,
                     domain, priority, detected_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'user_flagged')
                    RETURNING id
                """, (
                    memory_a_key, memory_b_key, type_id,
                    description, severity,
                    json.dumps(evidence_for_a or []),
                    json.dumps(evidence_for_b or []),
                    domain, priority
                ))

                detection_id = cur.fetchone()[0]

                return {
                    "success": True,
                    "detection_id": detection_id,
                    "status": "pending",
                    "message": "Contradiction reported and queued for resolution"
                }

        except Exception as e:
            logger.error(f"Report contradiction failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # CONTRADICTION RESOLUTION
    # =========================================================================

    def resolve_contradiction(
        self,
        detection_id: int,
        resolution_method: str,
        winner_key: str = None,
        reasoning: str = None,
        merged_content: str = None,
        loser_action: str = "archived"
    ) -> Dict[str, Any]:
        """
        Resolve a detected contradiction.

        Args:
            detection_id: The detection to resolve
            resolution_method: How to resolve (newer_wins, evidence_weight, manual, merge, both_valid)
            winner_key: Which memory wins (for non-merge resolutions)
            reasoning: Explanation of resolution
            merged_content: New content if merging
            loser_action: What to do with loser (archived, deleted, updated, kept)

        Returns:
            Dict with resolution result
        """
        try:
            with self._get_cursor() as cur:
                # Get detection details
                cur.execute("""
                    SELECT memory_key_a, memory_key_b, evidence_for_a, evidence_for_b
                    FROM contradiction_detections
                    WHERE id = %s
                """, (detection_id,))

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Detection not found"}

                memory_key_a, memory_key_b, evidence_a, evidence_b = row

                # Determine winner if not specified
                if resolution_method == 'newer_wins' and not winner_key:
                    # Get timestamps
                    cur.execute("""
                        SELECT memory_key, created_at FROM memory_items
                        WHERE memory_key IN (%s, %s)
                        ORDER BY created_at DESC LIMIT 1
                    """, (memory_key_a, memory_key_b))
                    newer = cur.fetchone()
                    winner_key = newer[0] if newer else memory_key_a

                elif resolution_method == 'evidence_weight' and not winner_key:
                    # Calculate evidence weights
                    weight_a = self._calculate_evidence_weight(evidence_a)
                    weight_b = self._calculate_evidence_weight(evidence_b)
                    winner_key = memory_key_a if weight_a >= weight_b else memory_key_b

                # Create resolution
                cur.execute("""
                    INSERT INTO contradiction_resolutions
                    (detection_id, resolution_method, winner_memory_key,
                     resolution_reasoning, merged_content, loser_action, resolved_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'system')
                    RETURNING id
                """, (
                    detection_id, resolution_method, winner_key,
                    reasoning, merged_content, loser_action
                ))

                resolution_id = cur.fetchone()[0]

                # Update detection status
                cur.execute("""
                    UPDATE contradiction_detections
                    SET status = 'resolved', updated_at = NOW()
                    WHERE id = %s
                """, (detection_id,))

                # Handle loser memory
                loser_key = memory_key_b if winner_key == memory_key_a else memory_key_a

                if loser_action == 'archived':
                    cur.execute("""
                        UPDATE memory_items
                        SET tier_id = (SELECT id FROM memory_tiers WHERE tier_name = 'archive')
                        WHERE memory_key = %s
                    """, (loser_key,))
                elif loser_action == 'updated' and merged_content:
                    cur.execute("""
                        UPDATE memory_items
                        SET content = %s, updated_at = NOW()
                        WHERE memory_key = %s
                    """, (merged_content, loser_key))

                return {
                    "success": True,
                    "resolution_id": resolution_id,
                    "winner_key": winner_key,
                    "loser_key": loser_key,
                    "method": resolution_method,
                    "loser_action": loser_action
                }

        except Exception as e:
            logger.error(f"Resolve contradiction failed: {e}")
            return {"success": False, "error": str(e)}

    def _calculate_evidence_weight(self, evidence: List[Dict]) -> float:
        """Calculate total evidence weight."""
        if not evidence:
            return 0.0

        total = 0.0
        for item in evidence:
            source = item.get('source', '')
            reliability = self.evidence_sources.get(source, 0.5)
            weight = item.get('weight', 1.0)
            total += reliability * weight

        return total

    # =========================================================================
    # FACT VERSIONING
    # =========================================================================

    def update_fact(
        self,
        fact_key: str,
        new_content: str,
        source: str = None,
        confidence: float = 0.7,
        change_reason: str = None
    ) -> Dict[str, Any]:
        """
        Update a fact, creating a new version.

        Args:
            fact_key: Unique fact identifier
            new_content: New fact content
            source: Source of the update
            confidence: Confidence in new fact
            change_reason: Why the fact changed

        Returns:
            Dict with version info
        """
        try:
            with self._get_cursor() as cur:
                # Get current version
                cur.execute("""
                    SELECT id, version_number, content
                    FROM fact_versions
                    WHERE fact_key = %s AND valid_until IS NULL
                    ORDER BY version_number DESC LIMIT 1
                """, (fact_key,))

                current = cur.fetchone()

                if current:
                    # Mark current as superseded
                    cur.execute("""
                        UPDATE fact_versions
                        SET valid_until = NOW()
                        WHERE id = %s
                    """, (current[0],))

                    new_version = current[1] + 1
                    previous_content = current[2]
                else:
                    new_version = 1
                    previous_content = None

                # Create new version
                cur.execute("""
                    INSERT INTO fact_versions
                    (fact_key, version_number, content, previous_content,
                     source, confidence, change_reason, changed_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'system')
                    RETURNING id
                """, (
                    fact_key, new_version, new_content, previous_content,
                    source, confidence, change_reason
                ))

                version_id = cur.fetchone()[0]

                return {
                    "success": True,
                    "fact_key": fact_key,
                    "version": new_version,
                    "version_id": version_id,
                    "previous_version": new_version - 1 if new_version > 1 else None
                }

        except Exception as e:
            logger.error(f"Update fact failed: {e}")
            return {"success": False, "error": str(e)}

    def get_fact_history(
        self,
        fact_key: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get version history for a fact.

        Args:
            fact_key: The fact key
            limit: Max versions to return

        Returns:
            Dict with version history
        """
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT version_number, content, previous_content,
                           source, confidence, change_reason,
                           valid_from, valid_until
                    FROM fact_versions
                    WHERE fact_key = %s
                    ORDER BY version_number DESC
                    LIMIT %s
                """, (fact_key, limit))

                columns = ['version', 'content', 'previous_content', 'source',
                          'confidence', 'change_reason', 'valid_from', 'valid_until']
                versions = []

                for row in cur.fetchall():
                    version = dict(zip(columns, row))
                    for key in ['valid_from', 'valid_until']:
                        if version.get(key):
                            version[key] = version[key].isoformat()
                    versions.append(version)

                return {
                    "success": True,
                    "fact_key": fact_key,
                    "versions": versions,
                    "total_versions": len(versions),
                    "current_version": versions[0] if versions else None
                }

        except Exception as e:
            logger.error(f"Get fact history failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # PENDING CONTRADICTIONS
    # =========================================================================

    def get_pending_contradictions(
        self,
        priority: str = None,
        domain: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get pending contradictions awaiting resolution.

        Args:
            priority: Filter by priority
            domain: Filter by domain
            limit: Max to return

        Returns:
            Dict with pending contradictions
        """
        try:
            with self._get_cursor() as cur:
                conditions = ["status = 'pending'"]
                params = []

                if priority:
                    conditions.append("priority = %s")
                    params.append(priority)

                if domain:
                    conditions.append("domain = %s")
                    params.append(domain)

                where_clause = " AND ".join(conditions)
                params.append(limit)

                cur.execute(f"""
                    SELECT d.id, d.memory_key_a, d.memory_key_b,
                           d.description, d.severity, d.confidence,
                           d.priority, d.domain, d.detected_at,
                           t.type_name, t.resolution_strategy
                    FROM contradiction_detections d
                    LEFT JOIN contradiction_types t ON d.contradiction_type_id = t.id
                    WHERE {where_clause}
                    ORDER BY
                        CASE d.priority
                            WHEN 'critical' THEN 1
                            WHEN 'high' THEN 2
                            WHEN 'medium' THEN 3
                            ELSE 4
                        END,
                        d.severity DESC
                    LIMIT %s
                """, params)

                columns = ['id', 'memory_key_a', 'memory_key_b', 'description',
                          'severity', 'confidence', 'priority', 'domain',
                          'detected_at', 'type', 'suggested_strategy']
                contradictions = []

                for row in cur.fetchall():
                    c = dict(zip(columns, row))
                    if c.get('detected_at'):
                        c['detected_at'] = c['detected_at'].isoformat()
                    contradictions.append(c)

                return {
                    "success": True,
                    "contradictions": contradictions,
                    "count": len(contradictions)
                }

        except Exception as e:
            logger.error(f"Get pending contradictions failed: {e}")
            return {"success": False, "error": str(e)}

    def add_evidence(
        self,
        detection_id: int,
        for_memory: str,  # 'a' or 'b'
        source: str,
        description: str,
        weight: float = 1.0
    ) -> Dict[str, Any]:
        """
        Add evidence to a pending contradiction.

        Args:
            detection_id: The detection ID
            for_memory: Which memory this supports ('a' or 'b')
            source: Evidence source name
            description: Evidence description
            weight: Weight of this evidence

        Returns:
            Dict with confirmation
        """
        try:
            import json

            column = 'evidence_for_a' if for_memory == 'a' else 'evidence_for_b'

            with self._get_cursor() as cur:
                # Get current evidence
                cur.execute(f"""
                    SELECT {column} FROM contradiction_detections WHERE id = %s
                """, (detection_id,))

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Detection not found"}

                evidence = row[0] if row[0] else []

                # Add new evidence
                reliability = self.evidence_sources.get(source, 0.5)
                evidence.append({
                    'source': source,
                    'description': description,
                    'weight': weight,
                    'reliability': reliability,
                    'added_at': datetime.now().isoformat()
                })

                # Update
                cur.execute(f"""
                    UPDATE contradiction_detections
                    SET {column} = %s, updated_at = NOW()
                    WHERE id = %s
                """, (json.dumps(evidence), detection_id))

                return {
                    "success": True,
                    "detection_id": detection_id,
                    "for_memory": for_memory,
                    "evidence_count": len(evidence)
                }

        except Exception as e:
            logger.error(f"Add evidence failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_contradiction_stats(self) -> Dict[str, Any]:
        """Get statistics about contradictions."""
        try:
            with self._get_cursor() as cur:
                # Status breakdown
                cur.execute("""
                    SELECT status, COUNT(*) FROM contradiction_detections
                    GROUP BY status
                """)
                status_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Type breakdown
                cur.execute("""
                    SELECT t.type_name, COUNT(d.id)
                    FROM contradiction_detections d
                    JOIN contradiction_types t ON d.contradiction_type_id = t.id
                    GROUP BY t.type_name
                """)
                type_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Resolution method breakdown
                cur.execute("""
                    SELECT resolution_method, COUNT(*)
                    FROM contradiction_resolutions
                    GROUP BY resolution_method
                """)
                resolution_methods = {row[0]: row[1] for row in cur.fetchall()}

                # Fact versions
                cur.execute("""
                    SELECT COUNT(DISTINCT fact_key), COUNT(*) FROM fact_versions
                """)
                fact_row = cur.fetchone()

                return {
                    "success": True,
                    "by_status": status_counts,
                    "by_type": type_counts,
                    "resolution_methods": resolution_methods,
                    "facts_tracked": fact_row[0] if fact_row else 0,
                    "total_versions": fact_row[1] if fact_row else 0
                }

        except Exception as e:
            logger.error(f"Get contradiction stats failed: {e}")
            return {"success": False, "error": str(e)}
