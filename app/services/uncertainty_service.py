"""
Uncertainty Quantification Service - Phase A2 (AGI Evolution)

Enables Jarvis to know what he doesn't know (metacognition).

Based on:
- Gal & Ghahramani (2016). "Dropout as Bayesian Approximation"
- Calibration research from forecasting literature

Components:
1. Confidence Scoring - Assess confidence in responses
2. Uncertainty Detection - Identify signals of uncertainty
3. Knowledge Gap Tracking - Track what is unknown
4. Calibration Monitoring - Ensure confidence is well-calibrated
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Singleton instance
_uncertainty_service = None


def get_uncertainty_service():
    """Get singleton instance of UncertaintyService."""
    global _uncertainty_service
    if _uncertainty_service is None:
        _uncertainty_service = UncertaintyService()
    return _uncertainty_service


class UncertaintyService:
    """
    Uncertainty Quantification Engine.

    Provides metacognitive capabilities - knowing what you don't know.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._signal_cache = None
        self._signal_cache_time = None

    # ==================== CONFIDENCE SCORING ====================

    def assess_confidence(
        self,
        query: str,
        response: str,
        tool_calls: List[Dict] = None,
        context: Dict = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Assess confidence in a response.

        Analyzes the response for uncertainty signals and knowledge gaps,
        then produces calibrated confidence scores.

        Args:
            query: The original query
            response: The generated response
            tool_calls: Tools that were called
            context: Additional context
            session_id: Session identifier

        Returns:
            Dict with confidence scores and uncertainty analysis
        """
        try:
            # 1. Detect uncertainty signals in response
            signals = self._detect_uncertainty_signals(response)

            # 2. Assess component confidences
            knowledge_conf = self._assess_knowledge_confidence(query, response, tool_calls)
            reasoning_conf = self._assess_reasoning_confidence(query, response)
            factual_conf = self._assess_factual_confidence(response, tool_calls)
            completeness_conf = self._assess_completeness_confidence(query, response)

            # 3. Calculate overall confidence
            base_confidence = (
                knowledge_conf * 0.35 +
                reasoning_conf * 0.25 +
                factual_conf * 0.25 +
                completeness_conf * 0.15
            )

            # 4. Apply signal impacts
            signal_impact = sum(s.get("impact", 0) for s in signals)
            overall_confidence = max(0.0, min(1.0, base_confidence + signal_impact))

            # 5. Categorize confidence
            category = self._categorize_confidence(overall_confidence)

            # 6. Identify knowledge gaps
            knowledge_gaps = self._identify_knowledge_gaps(query, response, signals)

            # 7. Log assessment
            assessment_id = self._log_assessment(
                session_id=session_id,
                query=query,
                overall_confidence=overall_confidence,
                category=category,
                knowledge_conf=knowledge_conf,
                reasoning_conf=reasoning_conf,
                factual_conf=factual_conf,
                completeness_conf=completeness_conf,
                signals=signals,
                knowledge_gaps=knowledge_gaps
            )

            return {
                "success": True,
                "assessment_id": assessment_id,
                "overall_confidence": round(overall_confidence, 3),
                "confidence_category": category,
                "component_scores": {
                    "knowledge": round(knowledge_conf, 3),
                    "reasoning": round(reasoning_conf, 3),
                    "factual": round(factual_conf, 3),
                    "completeness": round(completeness_conf, 3)
                },
                "uncertainty_signals": signals,
                "knowledge_gaps": knowledge_gaps,
                "should_express_uncertainty": overall_confidence < 0.6,
                "suggested_disclaimer": self._generate_disclaimer(overall_confidence, signals, knowledge_gaps)
            }

        except Exception as e:
            self.logger.error(f"Assess confidence failed: {e}")
            return {"success": False, "error": str(e)}

    def _detect_uncertainty_signals(self, response: str) -> List[Dict]:
        """Detect uncertainty signals in response text."""
        signals = self._get_uncertainty_signals()
        detected = []

        response_lower = response.lower()

        for signal in signals:
            pattern = signal.get("detection_pattern")
            if not pattern:
                continue

            try:
                if re.search(pattern, response_lower, re.IGNORECASE):
                    detected.append({
                        "name": signal["signal_name"],
                        "type": signal["signal_type"],
                        "impact": signal["confidence_impact"],
                        "severity": signal["severity"]
                    })
            except re.error:
                # Invalid regex, try simple contains
                if any(p.strip() in response_lower for p in pattern.split("|")):
                    detected.append({
                        "name": signal["signal_name"],
                        "type": signal["signal_type"],
                        "impact": signal["confidence_impact"],
                        "severity": signal["severity"]
                    })

        return detected

    def _get_uncertainty_signals(self) -> List[Dict]:
        """Get uncertainty signals from database with caching."""
        # Cache for 5 minutes
        if (self._signal_cache is not None and
            self._signal_cache_time is not None and
            datetime.now() - self._signal_cache_time < timedelta(minutes=5)):
            return self._signal_cache

        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT signal_name, signal_type, detection_pattern,
                           confidence_impact, severity
                    FROM uncertainty_signals
                    WHERE is_active = TRUE
                """)
                rows = cur.fetchall()

            self._signal_cache = [
                {
                    "signal_name": r["signal_name"],
                    "signal_type": r["signal_type"],
                    "detection_pattern": r["detection_pattern"],
                    "confidence_impact": r["confidence_impact"],
                    "severity": r["severity"]
                }
                for r in rows
            ]
            self._signal_cache_time = datetime.now()
            return self._signal_cache

        except Exception as e:
            self.logger.warning(f"Failed to get uncertainty signals: {e}")
            return []

    def _assess_knowledge_confidence(
        self,
        query: str,
        response: str,
        tool_calls: List[Dict]
    ) -> float:
        """Assess confidence in knowledge availability."""
        confidence = 0.7  # Base confidence

        # Boost if tools were used successfully
        if tool_calls:
            successful_tools = sum(1 for tc in tool_calls
                                   if tc.get("result", {}).get("success", True))
            if successful_tools > 0:
                confidence += 0.1

            # Memory/search tools indicate good knowledge retrieval
            knowledge_tools = ["search_knowledge_base", "recall_conversation_history",
                             "search_facts", "get_person_info"]
            if any(tc.get("tool") in knowledge_tools for tc in tool_calls):
                confidence += 0.1

        # Check response length (too short might indicate uncertainty)
        if len(response) < 50:
            confidence -= 0.1
        elif len(response) > 500:
            confidence += 0.05

        return min(1.0, max(0.0, confidence))

    def _assess_reasoning_confidence(self, query: str, response: str) -> float:
        """Assess confidence in reasoning quality."""
        confidence = 0.75  # Base confidence

        # Check for structured reasoning indicators
        reasoning_indicators = [
            "weil", "because", "therefore", "deshalb", "daher",
            "folglich", "consequently", "first", "second", "erstens",
            "zunächst", "dann", "schließlich", "finally"
        ]

        response_lower = response.lower()
        reasoning_count = sum(1 for ind in reasoning_indicators if ind in response_lower)

        if reasoning_count >= 3:
            confidence += 0.1
        elif reasoning_count >= 1:
            confidence += 0.05

        # Check for logical connectors
        logical_connectors = ["jedoch", "aber", "although", "however", "dennoch",
                            "trotzdem", "nevertheless", "andererseits", "on the other hand"]
        if any(c in response_lower for c in logical_connectors):
            confidence += 0.05  # Nuanced reasoning

        return min(1.0, max(0.0, confidence))

    def _assess_factual_confidence(
        self,
        response: str,
        tool_calls: List[Dict]
    ) -> float:
        """Assess confidence in factual accuracy."""
        confidence = 0.7  # Base confidence

        # If facts came from tools, higher confidence
        if tool_calls:
            fact_tools = ["search_knowledge_base", "search_facts", "get_calendar_events",
                         "get_person_info", "search_linkedin_knowledge"]
            fact_tool_used = any(tc.get("tool") in fact_tools for tc in tool_calls)
            if fact_tool_used:
                confidence += 0.15

        # Check for specific numbers/dates (might be uncertain)
        has_specific_numbers = bool(re.search(r'\b\d{4,}\b', response))
        has_dates = bool(re.search(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b', response))

        if has_specific_numbers or has_dates:
            # Specific claims need verification
            if not tool_calls:
                confidence -= 0.1

        return min(1.0, max(0.0, confidence))

    def _assess_completeness_confidence(self, query: str, response: str) -> float:
        """Assess confidence that the response is complete."""
        confidence = 0.75  # Base confidence

        # Check if response addresses question markers
        question_words = ["was", "what", "wie", "how", "warum", "why",
                         "wer", "who", "wann", "when", "wo", "where"]
        query_lower = query.lower()
        response_lower = response.lower()

        # Simple heuristic: if question word is in query, check if response seems to answer it
        for qw in question_words:
            if qw in query_lower:
                # Response should be reasonably substantial
                if len(response) > 100:
                    confidence += 0.05
                break

        # Check for explicit incompleteness markers
        incompleteness_markers = [
            "weitere Informationen", "more information needed",
            "ich kann nicht alle", "I cannot cover all",
            "dies ist nur ein Teil", "this is just part"
        ]
        if any(m in response_lower for m in incompleteness_markers):
            confidence -= 0.15

        return min(1.0, max(0.0, confidence))

    def _categorize_confidence(self, confidence: float) -> str:
        """Categorize confidence level."""
        if confidence >= 0.85:
            return "very_high"
        elif confidence >= 0.70:
            return "high"
        elif confidence >= 0.50:
            return "medium"
        elif confidence >= 0.30:
            return "low"
        else:
            return "very_low"

    def _identify_knowledge_gaps(
        self,
        query: str,
        response: str,
        signals: List[Dict]
    ) -> List[Dict]:
        """Identify knowledge gaps from the interaction."""
        gaps = []

        # Check for explicit knowledge gap signals
        knowledge_signals = [s for s in signals if s.get("type") == "knowledge"]
        for signal in knowledge_signals:
            gaps.append({
                "topic": self._extract_topic(query),
                "severity": signal.get("severity", "medium"),
                "signal": signal.get("name")
            })

        # Check for domain-specific patterns
        response_lower = response.lower()
        domain_uncertainty_patterns = {
            "medical": ["ich bin kein arzt", "consult a doctor", "medizinischen rat"],
            "legal": ["kein rechtsanwalt", "legal advice", "rechtliche beratung"],
            "financial": ["keine finanzberatung", "financial advisor", "finanzberater"],
            "technical_deep": ["implementation details", "source code", "low-level"]
        }

        for domain, patterns in domain_uncertainty_patterns.items():
            if any(p in response_lower for p in patterns):
                gaps.append({
                    "topic": domain,
                    "severity": "high",
                    "signal": "domain_limitation"
                })

        return gaps

    def _extract_topic(self, query: str) -> str:
        """Extract main topic from query."""
        # Simple extraction: first few significant words
        stop_words = {"was", "wie", "wer", "wo", "wann", "warum", "ist", "sind",
                     "what", "how", "who", "where", "when", "why", "is", "are",
                     "the", "a", "an", "der", "die", "das", "ein", "eine"}
        words = [w for w in query.lower().split() if w not in stop_words]
        return " ".join(words[:3]) if words else "unknown"

    def _generate_disclaimer(
        self,
        confidence: float,
        signals: List[Dict],
        knowledge_gaps: List[Dict]
    ) -> Optional[str]:
        """Generate appropriate disclaimer based on uncertainty."""
        if confidence >= 0.7:
            return None  # No disclaimer needed

        disclaimers = []

        if confidence < 0.4:
            disclaimers.append("Ich bin mir bei dieser Antwort nicht sicher.")

        if any(s.get("type") == "knowledge" for s in signals):
            disclaimers.append("Mein Wissen zu diesem Thema ist begrenzt.")

        if any(g.get("severity") == "high" for g in knowledge_gaps):
            disclaimers.append("Dies liegt ausserhalb meines Fachgebiets.")

        if any(s.get("name") == "future_prediction" for s in signals):
            disclaimers.append("Vorhersagen über die Zukunft sind naturgemäss unsicher.")

        return " ".join(disclaimers) if disclaimers else None

    def _log_assessment(
        self,
        session_id: str,
        query: str,
        overall_confidence: float,
        category: str,
        knowledge_conf: float,
        reasoning_conf: float,
        factual_conf: float,
        completeness_conf: float,
        signals: List[Dict],
        knowledge_gaps: List[Dict]
    ) -> Optional[int]:
        """Log uncertainty assessment to database."""
        try:
            from app.postgres_state import get_dict_cursor
            import json

            query_hash = hashlib.sha256(query.encode()).hexdigest()[:64]

            with get_dict_cursor() as cur:
                cur.execute("""
                    INSERT INTO uncertainty_assessments
                    (session_id, query_hash, query_text, overall_confidence, confidence_category,
                     knowledge_confidence, reasoning_confidence, factual_confidence, completeness_confidence,
                     uncertainty_signals, knowledge_gaps)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    session_id, query_hash, query[:500],
                    overall_confidence, category,
                    knowledge_conf, reasoning_conf, factual_conf, completeness_conf,
                    json.dumps(signals), json.dumps(knowledge_gaps)
                ))

                result = cur.fetchone()

                # Track knowledge gaps
                for gap in knowledge_gaps:
                    self._track_knowledge_gap(cur, gap)

                return result["id"] if result else None

        except Exception as e:
            self.logger.warning(f"Failed to log assessment: {e}")
            return None

    def _track_knowledge_gap(self, cursor, gap: Dict):
        """Track or update a knowledge gap."""
        try:
            cursor.execute("""
                INSERT INTO knowledge_gaps (topic, domain, severity, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (topic, domain) DO UPDATE SET
                    occurrence_count = knowledge_gaps.occurrence_count + 1,
                    last_encountered = NOW(),
                    severity = CASE
                        WHEN EXCLUDED.severity = 'critical' THEN 'critical'
                        WHEN EXCLUDED.severity = 'high' AND knowledge_gaps.severity != 'critical' THEN 'high'
                        ELSE knowledge_gaps.severity
                    END
            """, (
                gap.get("topic", "unknown"),
                gap.get("domain"),
                gap.get("severity", "medium"),
                gap.get("signal")
            ))
        except Exception as e:
            self.logger.debug(f"Failed to track knowledge gap: {e}")

    # ==================== KNOWLEDGE GAP MANAGEMENT ====================

    def get_knowledge_gaps(
        self,
        domain: str = None,
        min_severity: str = None,
        include_resolved: bool = False,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get tracked knowledge gaps."""
        try:
            from app.postgres_state import get_dict_cursor

            query = """
                SELECT topic, domain, severity, description, occurrence_count,
                       last_encountered, is_resolved, resolution_method
                FROM knowledge_gaps
                WHERE 1=1
            """
            params = []

            if not include_resolved:
                query += " AND is_resolved = FALSE"

            if domain:
                query += " AND domain = %s"
                params.append(domain)

            if min_severity:
                severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
                min_order = severity_order.get(min_severity, 2)
                query += """ AND CASE severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1 END >= %s"""
                params.append(min_order)

            query += " ORDER BY occurrence_count DESC, last_encountered DESC LIMIT %s"
            params.append(limit)

            with get_dict_cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            gaps = [
                {
                    "topic": r["topic"],
                    "domain": r["domain"],
                    "severity": r["severity"],
                    "description": r["description"],
                    "occurrences": r["occurrence_count"],
                    "last_seen": r["last_encountered"].isoformat() if r["last_encountered"] else None,
                    "resolved": r["is_resolved"],
                    "resolution": r["resolution_method"]
                }
                for r in rows
            ]

            return {
                "success": True,
                "gap_count": len(gaps),
                "gaps": gaps
            }

        except Exception as e:
            self.logger.error(f"Get knowledge gaps failed: {e}")
            return {"success": False, "error": str(e)}

    def resolve_knowledge_gap(
        self,
        topic: str,
        domain: str = None,
        resolution_method: str = "learned"
    ) -> Dict[str, Any]:
        """Mark a knowledge gap as resolved."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    UPDATE knowledge_gaps
                    SET is_resolved = TRUE, resolution_method = %s, resolved_at = NOW()
                    WHERE topic = %s AND (domain = %s OR (%s IS NULL AND domain IS NULL))
                    RETURNING id
                """, (resolution_method, topic, domain, domain))

                result = cur.fetchone()

            if result:
                return {
                    "success": True,
                    "message": f"Knowledge gap '{topic}' marked as resolved"
                }
            else:
                return {"success": False, "error": "Knowledge gap not found"}

        except Exception as e:
            self.logger.error(f"Resolve knowledge gap failed: {e}")
            return {"success": False, "error": str(e)}

    # ==================== CALIBRATION ====================

    def update_calibration(
        self,
        assessment_id: int,
        was_correct: bool
    ) -> Dict[str, Any]:
        """
        Update calibration data based on whether prediction was correct.

        Call this when you learn whether a confident prediction was accurate.
        """
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                # Get the assessment
                cur.execute("""
                    SELECT overall_confidence, confidence_category
                    FROM uncertainty_assessments
                    WHERE id = %s
                """, (assessment_id,))
                result = cur.fetchone()

                if not result:
                    return {"success": False, "error": "Assessment not found"}

                confidence = result["overall_confidence"]
                category = result["confidence_category"]

                # Update the assessment
                calibration_score = 1.0 if was_correct else 0.0
                cur.execute("""
                    UPDATE uncertainty_assessments
                    SET was_correct = %s, calibration_score = %s
                    WHERE id = %s
                """, (was_correct, calibration_score, assessment_id))

                # Update calibration bucket
                bucket = self._get_confidence_bucket(confidence)
                today = datetime.now().date()

                cur.execute("""
                    INSERT INTO confidence_calibration
                    (calibration_date, confidence_bucket, predictions_count, correct_count,
                     expected_accuracy)
                    VALUES (%s, %s, 1, %s, %s)
                    ON CONFLICT (calibration_date, confidence_bucket) DO UPDATE SET
                        predictions_count = confidence_calibration.predictions_count + 1,
                        correct_count = confidence_calibration.correct_count + EXCLUDED.correct_count,
                        accuracy_rate = (confidence_calibration.correct_count + EXCLUDED.correct_count)::float /
                                       (confidence_calibration.predictions_count + 1),
                        calibration_error = ABS(confidence_calibration.expected_accuracy -
                            (confidence_calibration.correct_count + EXCLUDED.correct_count)::float /
                            (confidence_calibration.predictions_count + 1))
                """, (today, bucket, 1 if was_correct else 0, self._bucket_midpoint(bucket)))

            return {
                "success": True,
                "assessment_id": assessment_id,
                "was_correct": was_correct,
                "confidence_was": confidence,
                "bucket": bucket
            }

        except Exception as e:
            self.logger.error(f"Update calibration failed: {e}")
            return {"success": False, "error": str(e)}

    def _get_confidence_bucket(self, confidence: float) -> str:
        """Get the calibration bucket for a confidence level."""
        if confidence < 0.2:
            return "0-20"
        elif confidence < 0.4:
            return "20-40"
        elif confidence < 0.6:
            return "40-60"
        elif confidence < 0.8:
            return "60-80"
        else:
            return "80-100"

    def _bucket_midpoint(self, bucket: str) -> float:
        """Get the expected accuracy for a bucket (midpoint)."""
        midpoints = {
            "0-20": 0.1,
            "20-40": 0.3,
            "40-60": 0.5,
            "60-80": 0.7,
            "80-100": 0.9
        }
        return midpoints.get(bucket, 0.5)

    def get_calibration_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get calibration statistics."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT confidence_bucket,
                           SUM(predictions_count) as total_predictions,
                           SUM(correct_count) as total_correct,
                           AVG(expected_accuracy) as expected_accuracy
                    FROM confidence_calibration
                    WHERE calibration_date > NOW() - INTERVAL '%s days'
                    GROUP BY confidence_bucket
                    ORDER BY confidence_bucket
                """, (days,))

                rows = cur.fetchall()

            buckets = []
            total_predictions = 0
            total_correct = 0
            total_calibration_error = 0

            for r in rows:
                bucket_name = r["confidence_bucket"]
                predictions = r["total_predictions"]
                correct = r["total_correct"]
                expected = r["expected_accuracy"]
                actual = correct / predictions if predictions > 0 else 0
                error = abs(expected - actual)

                buckets.append({
                    "bucket": bucket_name,
                    "predictions": predictions,
                    "correct": correct,
                    "accuracy": round(actual, 3),
                    "expected": round(expected, 3),
                    "calibration_error": round(error, 3)
                })

                total_predictions += predictions
                total_correct += correct
                total_calibration_error += error * predictions

            overall_calibration = total_calibration_error / total_predictions if total_predictions > 0 else 0

            return {
                "success": True,
                "period_days": days,
                "total_predictions": total_predictions,
                "total_correct": total_correct,
                "overall_accuracy": round(total_correct / total_predictions, 3) if total_predictions > 0 else 0,
                "calibration_error": round(overall_calibration, 3),
                "is_well_calibrated": overall_calibration < 0.15,
                "buckets": buckets
            }

        except Exception as e:
            self.logger.error(f"Get calibration stats failed: {e}")
            return {"success": False, "error": str(e)}

    # ==================== UNCERTAINTY SIGNAL MANAGEMENT ====================

    def add_uncertainty_signal(
        self,
        signal_name: str,
        signal_type: str,
        detection_pattern: str,
        confidence_impact: float = -0.1,
        severity: str = "medium"
    ) -> Dict[str, Any]:
        """Add a new uncertainty signal."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    INSERT INTO uncertainty_signals
                    (signal_name, signal_type, detection_pattern, confidence_impact, severity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (signal_name) DO UPDATE SET
                        signal_type = EXCLUDED.signal_type,
                        detection_pattern = EXCLUDED.detection_pattern,
                        confidence_impact = EXCLUDED.confidence_impact,
                        severity = EXCLUDED.severity
                    RETURNING id
                """, (signal_name, signal_type, detection_pattern, confidence_impact, severity))

                result = cur.fetchone()

            # Clear cache
            self._signal_cache = None

            return {
                "success": True,
                "signal_id": result[0] if result else None,
                "signal_name": signal_name
            }

        except Exception as e:
            self.logger.error(f"Add uncertainty signal failed: {e}")
            return {"success": False, "error": str(e)}

    def get_uncertainty_signals_list(self) -> Dict[str, Any]:
        """Get all uncertainty signals."""
        try:
            signals = self._get_uncertainty_signals()
            return {
                "success": True,
                "signal_count": len(signals),
                "signals": signals
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== CONFIDENCE EXPRESSION ====================

    def should_express_uncertainty(self, confidence: float) -> Tuple[bool, str]:
        """
        Determine if and how to express uncertainty.

        Returns:
            Tuple of (should_express, suggested_phrase)
        """
        if confidence >= 0.85:
            return False, ""
        elif confidence >= 0.70:
            return True, "Ich bin ziemlich sicher, dass"
        elif confidence >= 0.50:
            return True, "Soweit ich weiss"
        elif confidence >= 0.30:
            return True, "Ich bin nicht ganz sicher, aber"
        else:
            return True, "Ich bin mir sehr unsicher, aber"

    def get_confidence_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get summary of confidence assessments."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT
                        confidence_category,
                        COUNT(*) as count,
                        AVG(overall_confidence) as avg_confidence
                    FROM uncertainty_assessments
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY confidence_category
                    ORDER BY avg_confidence DESC
                """, (days,))

                by_category = [
                    {"category": r["confidence_category"], "count": r["count"], "avg_confidence": round(r["avg_confidence"], 3)}
                    for r in cur.fetchall()
                ]

                cur.execute("""
                    SELECT COUNT(*) as total_count, AVG(overall_confidence) as avg_conf
                    FROM uncertainty_assessments
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))

                total = cur.fetchone()

            return {
                "success": True,
                "period_days": days,
                "total_assessments": total["total_count"] if total else 0,
                "average_confidence": round(total["avg_conf"], 3) if total and total["avg_conf"] else 0,
                "by_category": by_category
            }

        except Exception as e:
            self.logger.error(f"Get confidence summary failed: {e}")
            return {"success": False, "error": str(e)}
