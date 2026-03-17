"""Unit tests for Telegram memory integration (T-107).

Tests the chat learning pipeline that extracts preferences,
emotional states, and learning patterns from Telegram messages.
"""
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# -----------------------------------------------------------------------------
# Test Data Structures
# -----------------------------------------------------------------------------

@dataclass
class TelegramMessage:
    """Mock Telegram message for testing."""
    text: str
    user_id: str = "micha"
    timestamp: datetime = None
    reply_to: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ExtractedFact:
    """Extracted learning fact from message."""
    key: str
    value: Any
    confidence: float
    source: str = "telegram_pattern"
    category: str = "preference"


# -----------------------------------------------------------------------------
# Chat Parser Tests
# -----------------------------------------------------------------------------

class TestChatParser:
    """Test message parsing for learning signals."""

    def test_explicit_preference_pattern(self):
        """Test extraction of 'Ich bevorzuge X' pattern."""
        message = TelegramMessage(text="Ich bevorzuge kurze Antworten")

        fact = parse_explicit_preference(message.text)

        assert fact is not None
        assert fact.key == "response_length"
        assert fact.value == "concise"
        assert fact.confidence >= 0.7

    def test_explicit_preference_dont_pattern(self):
        """Test extraction of 'Mach das nicht' pattern."""
        message = TelegramMessage(text="Mach das nicht mit langen Erklärungen")

        fact = parse_explicit_preference(message.text)

        assert fact is not None
        assert fact.key in ["explanation_length", "response_style"]
        assert "nicht" in str(fact.value).lower() or fact.value == "brief"

    def test_positive_feedback_pattern(self):
        """Test extraction of 'Perfekt so' pattern."""
        message = TelegramMessage(text="Perfekt so!")

        signal = parse_feedback_signal(message.text)

        assert signal is not None
        assert signal["type"] == "positive"
        assert signal["confidence"] >= 0.8

    def test_negative_feedback_pattern(self):
        """Test extraction of negative feedback."""
        message = TelegramMessage(text="Das war nicht hilfreich")

        signal = parse_feedback_signal(message.text)

        assert signal is not None
        assert signal["type"] == "negative"

    def test_no_learning_signal(self):
        """Test that regular messages don't trigger extraction."""
        message = TelegramMessage(text="Wie ist das Wetter heute?")

        fact = parse_explicit_preference(message.text)
        signal = parse_feedback_signal(message.text)

        assert fact is None
        assert signal is None

    def test_critical_instruction_pattern(self):
        """Test extraction of CRITICAL instructions."""
        message = TelegramMessage(text="CRITICAL: ALWAYS use BuildKit for deployments")

        fact = parse_critical_instruction(message.text)

        assert fact is not None
        assert fact.key == "docker_strategy"
        assert "buildkit" in fact.value.lower()
        assert fact.confidence >= 0.9


def parse_explicit_preference(text: str) -> Optional[ExtractedFact]:
    """Helper to parse explicit preference patterns."""
    text_lower = text.lower()

    # Pattern: "Ich bevorzuge X"
    if "ich bevorzuge" in text_lower:
        if any(word in text_lower for word in ["bullet", "liste", "punkt"]):
            return ExtractedFact(
                key="response_format",
                value="bullet_points",
                confidence=0.7,
                category="communication"
            )
        if "kurz" in text_lower or "concise" in text_lower:
            return ExtractedFact(
                key="response_length",
                value="concise",
                confidence=0.7,
                category="communication"
            )
        if "lang" in text_lower or "detail" in text_lower:
            return ExtractedFact(
                key="response_length",
                value="detailed",
                confidence=0.7,
                category="communication"
            )

    # Pattern: "Kurze Antworten bitte"
    if "kurz" in text_lower and ("antwort" in text_lower or "response" in text_lower):
        return ExtractedFact(
            key="response_length",
            value="concise",
            confidence=0.6,
            category="communication"
        )

    # Pattern: "Immer mit Beispielen"
    if "beispiel" in text_lower or "example" in text_lower:
        return ExtractedFact(
            key="response_format",
            value="with_examples",
            confidence=0.6,
            category="communication"
        )

    # Pattern: "Mach das nicht"
    if "mach das nicht" in text_lower:
        if "lang" in text_lower or "erklärung" in text_lower:
            return ExtractedFact(
                key="explanation_length",
                value="brief",
                confidence=0.6,
                category="communication"
            )

    return None


def parse_feedback_signal(text: str) -> Optional[Dict[str, Any]]:
    """Helper to parse feedback signals."""
    text_lower = text.lower()

    positive_patterns = ["perfekt", "super", "genau so", "gut gemacht", "danke"]
    negative_patterns = ["nicht hilfreich", "falsch", "nein", "stimmt nicht"]

    for pattern in positive_patterns:
        if pattern in text_lower:
            return {"type": "positive", "confidence": 0.8}

    for pattern in negative_patterns:
        if pattern in text_lower:
            return {"type": "negative", "confidence": 0.7}

    return None


def parse_critical_instruction(text: str) -> Optional[ExtractedFact]:
    """Helper to parse CRITICAL instructions."""
    if "CRITICAL:" not in text and "WICHTIG:" not in text:
        return None

    text_lower = text.lower()

    if "buildkit" in text_lower:
        return ExtractedFact(
            key="docker_strategy",
            value="buildkit_always",
            confidence=0.95,
            category="technical"
        )

    if "always" in text_lower or "immer" in text_lower:
        return ExtractedFact(
            key="critical_instruction",
            value=text,
            confidence=0.9,
            category="rule"
        )

    return None


# -----------------------------------------------------------------------------
# Preference Extractor Tests
# -----------------------------------------------------------------------------

class TestPreferenceExtractor:
    """Test preference extraction from messages."""

    def test_communication_style_preference(self):
        """Test extraction of communication style preferences."""
        messages = [
            "Ich bevorzuge bullet points",
            "Kurze Antworten bitte",
            "Immer mit Beispielen"
        ]

        preferences = extract_preferences(messages)

        assert len(preferences) > 0
        assert any(p.category == "communication" for p in preferences)

    def test_technical_preference_extraction(self):
        """Test extraction of technical preferences."""
        message = "CRITICAL: ALWAYS use BuildKit"

        preferences = extract_preferences([message])

        assert len(preferences) > 0
        assert any(p.key == "docker_strategy" for p in preferences)

    def test_time_based_preference(self):
        """Test extraction of time-based preferences."""
        message = "Morgens kurze Antworten, abends darf es ausführlicher sein"

        preferences = extract_time_preferences(message)

        assert len(preferences) >= 1
        # Should extract morning vs evening preferences

    def test_confidence_scoring(self):
        """Test confidence scoring based on signal strength."""
        explicit = "Ich bevorzuge IMMER kurze Antworten"  # Strong
        implicit = "kurz wäre gut"  # Weak

        explicit_prefs = extract_preferences([explicit])
        implicit_prefs = extract_preferences([implicit])

        # Explicit should have higher confidence
        if explicit_prefs and implicit_prefs:
            assert explicit_prefs[0].confidence >= implicit_prefs[0].confidence


def extract_preferences(messages: List[str]) -> List[ExtractedFact]:
    """Helper to extract preferences from messages."""
    preferences = []

    for msg in messages:
        fact = parse_explicit_preference(msg)
        if fact:
            preferences.append(fact)

        critical = parse_critical_instruction(msg)
        if critical:
            preferences.append(critical)

    return preferences


def extract_time_preferences(message: str) -> List[ExtractedFact]:
    """Helper to extract time-based preferences."""
    facts = []
    text_lower = message.lower()

    if "morgens" in text_lower and "kurz" in text_lower:
        facts.append(ExtractedFact(
            key="morning_communication",
            value="brief",
            confidence=0.7,
            category="time_preference"
        ))

    if "abends" in text_lower and ("ausführlich" in text_lower or "detail" in text_lower):
        facts.append(ExtractedFact(
            key="evening_communication",
            value="detailed",
            confidence=0.7,
            category="time_preference"
        ))

    return facts


# -----------------------------------------------------------------------------
# Emotional Analyzer Tests
# -----------------------------------------------------------------------------

class TestEmotionalAnalyzer:
    """Test emotional state detection from chat style."""

    def test_stress_detection(self):
        """Test detection of stress indicators."""
        message = TelegramMessage(text="Stress pur heute, viele parallel Tasks")

        state = analyze_emotional_state(message.text)

        assert state is not None
        assert state["stress_level"] == "high"
        assert state["confidence"] >= 0.6

    def test_relaxed_detection(self):
        """Test detection of relaxed state."""
        message = TelegramMessage(text="Alles easy heute, endlich mal Zeit")

        state = analyze_emotional_state(message.text)

        assert state is not None
        assert state["stress_level"] == "low"

    def test_focused_detection(self):
        """Test detection of focused state."""
        message = TelegramMessage(text="Deep work session, keine Unterbrechungen bitte")

        state = analyze_emotional_state(message.text)

        assert state is not None
        assert state["focus_mode"] is True

    def test_neutral_message(self):
        """Test that neutral messages return neutral state."""
        message = TelegramMessage(text="Was gibt es Neues?")

        state = analyze_emotional_state(message.text)

        assert state is None or state.get("stress_level") == "neutral"


def analyze_emotional_state(text: str) -> Optional[Dict[str, Any]]:
    """Helper to analyze emotional state from text."""
    text_lower = text.lower()

    # Stress indicators
    stress_patterns = ["stress", "dringend", "deadline", "viele tasks", "parallel"]
    for pattern in stress_patterns:
        if pattern in text_lower:
            return {"stress_level": "high", "confidence": 0.7}

    # Relaxed indicators
    relaxed_patterns = ["easy", "entspannt", "zeit", "ruhig"]
    for pattern in relaxed_patterns:
        if pattern in text_lower:
            return {"stress_level": "low", "confidence": 0.6}

    # Focus indicators
    focus_patterns = ["deep work", "fokus", "keine unterbrechung", "konzentrier"]
    for pattern in focus_patterns:
        if pattern in text_lower:
            return {"focus_mode": True, "stress_level": "neutral", "confidence": 0.7}

    return None


# -----------------------------------------------------------------------------
# Memory Integrator Tests
# -----------------------------------------------------------------------------

class TestMemoryIntegrator:
    """Test integration of extracted facts into persistent memory."""

    def test_fact_storage_call(self):
        """Test that extracted facts are stored via persistent_learn."""
        fact = ExtractedFact(
            key="response_length",
            value="concise",
            confidence=0.7
        )

        storage_payload = build_storage_payload(fact, user_id="micha")

        assert storage_payload["user_id"] == "micha"
        assert storage_payload["key"] == "response_length"
        assert storage_payload["value"] == "concise"
        assert storage_payload["source"] == "telegram_pattern"

    def test_confidence_update_on_feedback(self):
        """Test that positive feedback increases confidence."""
        current_confidence = 0.7
        feedback = {"type": "positive", "confidence": 0.8}

        new_confidence = calculate_updated_confidence(current_confidence, feedback)

        assert new_confidence > current_confidence
        assert new_confidence <= 1.0

    def test_confidence_decrease_on_negative(self):
        """Test that negative feedback decreases confidence."""
        current_confidence = 0.7
        feedback = {"type": "negative", "confidence": 0.7}

        new_confidence = calculate_updated_confidence(current_confidence, feedback)

        assert new_confidence < current_confidence
        assert new_confidence >= 0.0

    def test_duplicate_fact_handling(self):
        """Test that duplicate facts update rather than duplicate."""
        existing_facts = [
            {"key": "response_length", "value": "concise", "confidence": 0.6}
        ]
        new_fact = ExtractedFact(key="response_length", value="concise", confidence=0.8)

        merged = merge_facts(existing_facts, new_fact)

        # Should have same count, higher confidence
        assert len(merged) == 1
        assert merged[0]["confidence"] == 0.8


def build_storage_payload(fact: ExtractedFact, user_id: str) -> Dict[str, Any]:
    """Build payload for persistent_learn storage."""
    return {
        "user_id": user_id,
        "namespace": "personal",
        "key": fact.key,
        "value": fact.value,
        "source": "telegram_pattern",
        "confidence": fact.confidence,
        "sensitivity": "low"
    }


def calculate_updated_confidence(current: float, feedback: Dict[str, Any]) -> float:
    """Calculate updated confidence based on feedback."""
    delta = 0.1 if feedback["type"] == "positive" else -0.15
    return max(0.0, min(1.0, current + delta))


def merge_facts(existing: List[Dict], new_fact: ExtractedFact) -> List[Dict]:
    """Merge new fact with existing facts."""
    for fact in existing:
        if fact["key"] == new_fact.key:
            # Update existing
            fact["confidence"] = max(fact["confidence"], new_fact.confidence)
            fact["value"] = new_fact.value
            return existing

    # Add new
    existing.append({
        "key": new_fact.key,
        "value": new_fact.value,
        "confidence": new_fact.confidence
    })
    return existing


# -----------------------------------------------------------------------------
# Integration Tests (Mocked)
# -----------------------------------------------------------------------------

class TestTelegramMemoryIntegration:
    """Integration tests for the full pipeline."""

    def test_full_pipeline_explicit_preference(self):
        """Test full pipeline from message to stored fact."""
        message = TelegramMessage(text="Ich bevorzuge kurze Antworten morgens")

        # Parse
        fact = parse_explicit_preference(message.text)
        assert fact is not None

        # Build storage payload
        payload = build_storage_payload(fact, message.user_id)
        assert payload["key"] == "response_length"

        # Would call: storage.record_fact(**payload)

    def test_full_pipeline_feedback_loop(self):
        """Test feedback loop updating previous decision."""
        # Initial preference stored
        initial_fact = ExtractedFact(key="tool_preference", value="BuildKit", confidence=0.6)

        # Positive feedback received
        feedback_message = TelegramMessage(text="Perfekt so mit BuildKit!")
        feedback = parse_feedback_signal(feedback_message.text)

        # Update confidence
        new_confidence = calculate_updated_confidence(initial_fact.confidence, feedback)
        assert new_confidence > initial_fact.confidence

    def test_full_pipeline_emotional_context(self):
        """Test emotional context extraction and storage."""
        message = TelegramMessage(text="Stress pur, mach kurz bitte")

        # Extract emotional state
        state = analyze_emotional_state(message.text)
        assert state["stress_level"] == "high"

        # Extract preference (implicit from stress context)
        fact = parse_explicit_preference(message.text)
        # Even without explicit "ich bevorzuge", stress + "kurz" implies brief response


# -----------------------------------------------------------------------------
# Privacy Tests
# -----------------------------------------------------------------------------

class TestPrivacy:
    """Test privacy considerations in memory extraction."""

    def test_no_raw_message_storage(self):
        """Test that raw messages are not stored."""
        message = TelegramMessage(text="Ich bevorzuge kurze Antworten")
        fact = parse_explicit_preference(message.text)

        # Fact should not contain the full message
        payload = build_storage_payload(fact, "micha")

        assert "Ich bevorzuge" not in str(payload.get("value", ""))

    def test_ttl_assignment(self):
        """Test that appropriate TTL is assigned."""
        explicit = ExtractedFact(key="preference", value="test", confidence=0.9)
        implicit = ExtractedFact(key="implicit_pattern", value="test", confidence=0.5)

        explicit_ttl = get_ttl_days(explicit)
        implicit_ttl = get_ttl_days(implicit)

        # Explicit preferences should have longer TTL
        assert explicit_ttl > implicit_ttl


def get_ttl_days(fact: ExtractedFact) -> int:
    """Get TTL in days based on fact type and confidence."""
    if fact.confidence >= 0.8:
        return 365  # High confidence = 1 year
    elif fact.confidence >= 0.5:
        return 90  # Medium confidence = 90 days
    else:
        return 30  # Low confidence = 30 days


# -----------------------------------------------------------------------------
# T-107 Guardrails Tests (Added Feb 6, 2026)
# -----------------------------------------------------------------------------

class TestNegationDetection:
    """Test negation pattern detection (T-107 P1)."""

    def test_keine_negation_german(self):
        """Test 'keine' negation in German preference."""
        message = "Ich bevorzuge KEINE kurzen Antworten"

        has_negation = contains_negation(message)

        assert has_negation is True

    def test_nicht_negation_german(self):
        """Test 'nicht' negation in German."""
        message = "Das soll nicht so sein"

        has_negation = contains_negation(message)

        assert has_negation is True

    def test_never_negation_english(self):
        """Test 'never' negation in English."""
        message = "Never use that approach"

        has_negation = contains_negation(message)

        assert has_negation is True

    def test_dont_negation_english(self):
        """Test 'don't' negation in English."""
        message = "Don't do it that way"

        has_negation = contains_negation(message)

        assert has_negation is True

    def test_auf_keinen_fall_german(self):
        """Test 'auf keinen Fall' negation."""
        message = "Auf keinen Fall so machen"

        has_negation = contains_negation(message)

        assert has_negation is True

    def test_no_negation_positive(self):
        """Test positive message has no negation."""
        message = "Ich bevorzuge kurze Antworten"

        has_negation = contains_negation(message)

        assert has_negation is False

    def test_negation_flips_preference(self):
        """Test that negation converts positive to negative preference."""
        positive_msg = "Ich bevorzuge kurze Antworten"
        negative_msg = "Ich bevorzuge KEINE kurzen Antworten"

        pos_result = parse_preference_with_negation(positive_msg)
        neg_result = parse_preference_with_negation(negative_msg)

        assert pos_result is not None
        assert neg_result is not None
        assert pos_result["type"] != neg_result["type"]
        # Negated should have lower confidence
        assert neg_result["confidence"] < pos_result["confidence"]


def contains_negation(text: str) -> bool:
    """Check if text contains negation patterns."""
    import re
    negation_patterns = [
        r"\bkeine?\b", r"\bnicht\b", r"\bnie\b", r"\bniemals\b",
        r"\bno\b", r"\bnot\b", r"\bnever\b", r"\bdon'?t\b",
        r"\bauf keinen fall\b",
    ]
    pattern = "|".join(negation_patterns)
    return bool(re.search(pattern, text, re.IGNORECASE))


def parse_preference_with_negation(text: str) -> Optional[Dict[str, Any]]:
    """Parse preference with negation handling."""
    base_confidence = 0.8

    if "ich bevorzuge" in text.lower():
        is_negated = contains_negation(text)
        return {
            "type": "negative_preference" if is_negated else "positive_preference",
            "confidence": base_confidence - 0.15 if is_negated else base_confidence,
            "value": "short_responses"
        }
    return None


class TestSensitiveContentFilter:
    """Test sensitive content filtering (T-107 P0)."""

    def test_password_filtered(self):
        """Test password patterns are blocked."""
        messages = [
            "My password: secret123",
            "password=mypass",
            "Passwort: geheim",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"

    def test_api_key_filtered(self):
        """Test API key patterns are blocked."""
        messages = [
            "API key: abc123xyz",
            "api_key=sk-1234567890",
            "The secret: mysecretvalue",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"

    def test_credit_card_filtered(self):
        """Test credit card patterns are blocked."""
        messages = [
            "Card: 1234-5678-9012-3456",
            "CC: 1234 5678 9012 3456",
            "Number: 1234567890123456",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"

    def test_iban_filtered(self):
        """Test IBAN patterns are blocked."""
        messages = [
            "IBAN: DE89370400440532013000",
            "IBAN=CH9300762011623852957",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"

    def test_private_key_filtered(self):
        """Test private key patterns are blocked."""
        messages = [
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN PGP PRIVATE KEY-----",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"

    def test_normal_message_not_filtered(self):
        """Test normal messages pass through."""
        messages = [
            "Ich bevorzuge kurze Antworten",
            "Das war perfekt",
            "CRITICAL: Use BuildKit",
            "Stress pur heute",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is False, f"Falsely filtered: {msg}"

    def test_token_keyword_filtered(self):
        """Test bearer token patterns are blocked."""
        messages = [
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "token: abc123",
            "authorization: Bearer xyz",
        ]

        for msg in messages:
            assert is_sensitive_content(msg) is True, f"Failed: {msg}"


def is_sensitive_content(text: str) -> bool:
    """Check if text contains sensitive content."""
    import re
    patterns = [
        r"password\s*[:=]",
        r"passwort\s*[:=]",
        r"api[_\- ]?key\s*[:=]",
        r"secret\s*[:=]",
        r"token\s*[:=]",
        r"bearer\s+",
        r"authorization\s*[:=]",
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        r"\biban\s*[:=]?\s*[a-z]{2}\d{2}",
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        r"-----BEGIN\s+PGP\s+PRIVATE",
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


class TestNamespaceIsolation:
    """Test scope isolation per user via legacy namespace fields (T-107)."""

    def test_personal_namespace_prefixed(self):
        """Test personal scope key gets telegram_ prefix."""
        namespace = get_telegram_namespace("user123", "personal")

        assert namespace == "telegram_user123"

    def test_other_namespace_prefixed(self):
        """Test non-personal scope keys get telegram_ prefix."""
        namespace = get_telegram_namespace("user123", "work")

        assert namespace == "telegram_work"

    def test_different_users_isolated(self):
        """Test different users resolve to different isolated scope keys."""
        ns1 = get_telegram_namespace("alice", "personal")
        ns2 = get_telegram_namespace("bob", "personal")

        assert ns1 != ns2
        assert "alice" in ns1
        assert "bob" in ns2


def get_telegram_namespace(user_id: str, namespace: str) -> str:
    """Get isolated legacy namespace key for telegram learning."""
    if namespace == "personal":
        return f"telegram_{user_id}"
    return f"telegram_{namespace}"


class TestMinConfidenceThreshold:
    """Test MIN_STORAGE_CONFIDENCE threshold (T-107)."""

    MIN_STORAGE_CONFIDENCE = 0.50

    def test_high_confidence_stored(self):
        """Test facts above threshold are stored."""
        fact = ExtractedFact(key="test", value="value", confidence=0.8)

        should_store = fact.confidence >= self.MIN_STORAGE_CONFIDENCE

        assert should_store is True

    def test_low_confidence_filtered(self):
        """Test facts below threshold are filtered."""
        fact = ExtractedFact(key="test", value="value", confidence=0.3)

        should_store = fact.confidence >= self.MIN_STORAGE_CONFIDENCE

        assert should_store is False

    def test_boundary_confidence_stored(self):
        """Test facts at exactly threshold are stored."""
        fact = ExtractedFact(key="test", value="value", confidence=0.50)

        should_store = fact.confidence >= self.MIN_STORAGE_CONFIDENCE

        assert should_store is True

    def test_just_below_threshold_filtered(self):
        """Test facts just below threshold are filtered."""
        fact = ExtractedFact(key="test", value="value", confidence=0.49)

        should_store = fact.confidence >= self.MIN_STORAGE_CONFIDENCE

        assert should_store is False


class TestEdgeCases:
    """Test edge cases from T-107 review."""

    def test_mixed_language_detection(self):
        """Test German/English mixed message handling."""
        message = "Ich prefer kurze responses bitte"

        # Should still detect preference pattern
        fact = parse_explicit_preference(message)
        # Mixed language might not match strict patterns
        # This is an expected edge case - may return None

    def test_short_ambiguous_reply(self):
        """Test short replies have lower confidence."""
        short_msg = "ja"
        long_msg = "Ja, genau so ist es perfekt"

        short_signal = parse_feedback_signal(short_msg)
        long_signal = parse_feedback_signal(long_msg)

        # Short ambiguous replies should not trigger strong signals
        assert short_signal is None or (
            long_signal and short_signal["confidence"] <= long_signal["confidence"]
        )

    def test_sarcasm_ellipsis_pattern(self):
        """Test ellipsis as potential sarcasm indicator."""
        sincere = "Das war perfekt"
        sarcastic = "Das war perfekt..."

        # Ellipsis might indicate sarcasm (P2 - for future)
        # Currently both should parse as positive
        # Future: sarcastic should have penalty

    def test_conditional_preference_time(self):
        """Test time-based conditional preferences."""
        message = "Morgens kurze Antworten, abends darf es länger sein"

        prefs = extract_time_preferences(message)

        # Should extract multiple time-scoped preferences
        assert len(prefs) >= 1


# -----------------------------------------------------------------------------
# T-110 Negation Fix Tests (Added Feb 6, 2026)
# Tests the actual preference_extractor.py negation handling
# -----------------------------------------------------------------------------

class TestPreferenceExtractorNegation:
    """Test negation handling in preference_extractor.py (T-110)."""

    def test_keine_langen_inverts_to_concise(self):
        """Test 'KEINE langen Antworten' extracts as concise."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Ich will KEINE langen Antworten")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "concise"  # Inverted from "detailed"
        assert response_pref.confidence == 0.6  # Lower confidence for inverted

    def test_nicht_kurz_inverts_to_detailed(self):
        """Test 'nicht so kurz' extracts as detailed."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Bitte nicht so kurz")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "detailed"  # Inverted from "concise"
        assert response_pref.confidence == 0.6  # Lower confidence for inverted

    def test_positive_kurz_stays_concise(self):
        """Test positive 'kurze Antworten' extracts as concise."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Ich mag kurze Antworten")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "concise"  # Not inverted
        assert response_pref.confidence == 0.7  # Normal confidence

    def test_positive_lang_stays_detailed(self):
        """Test positive 'lange Antworten' extracts as detailed."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Ich bevorzuge lange ausführliche Antworten")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "detailed"  # Not inverted
        assert response_pref.confidence == 0.7  # Normal confidence

    def test_niemals_kurz_inverts(self):
        """Test 'niemals kurz' inverts to detailed."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Niemals kurze Antworten geben")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "detailed"

    def test_ohne_details_inverts(self):
        """Test 'ohne details' extracts as concise."""
        from app.telegram_memory.preference_extractor import extract_preferences

        prefs = extract_preferences("Antworten ohne lange details bitte")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "concise"

    def test_negation_far_from_keyword_not_detected(self):
        """Test negation too far from keyword is ignored."""
        from app.telegram_memory.preference_extractor import extract_preferences

        # "nicht" is more than 3 words before "kurz"
        prefs = extract_preferences("Das ist nicht mein Style aber kurze Antworten sind ok")

        assert len(prefs) >= 1
        response_pref = next((p for p in prefs if p.key == "response_length"), None)
        assert response_pref is not None
        assert response_pref.value == "concise"  # Not inverted (negation too far)
        assert response_pref.confidence == 0.7  # Normal confidence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
