"""
Tests for Advanced Complexity Analyzer (IMR P3).
"""
import pytest
from app.routing import ComplexityProfile, AdvancedComplexityAnalyzer, analyze_complexity


class TestComplexityProfile:
    """Tests for ComplexityProfile dataclass."""

    def test_default_values(self):
        """Test default complexity is zero."""
        profile = ComplexityProfile()
        assert profile.overall_complexity == 0.0
        assert profile.model_recommendation == "cheap"
        assert not profile.requires_premium_model

    def test_overall_complexity_weighted(self):
        """Test weighted overall complexity calculation."""
        profile = ComplexityProfile(
            cognitive_complexity=1.0,
            technical_complexity=1.0,
            creative_complexity=0.0,
            emotional_complexity=0.0,
            domain_complexity=0.0,
            interaction_complexity=0.0,
        )
        # cognitive(0.25) + technical(0.25) = 0.5
        assert profile.overall_complexity == 0.5

    def test_max_dimension(self):
        """Test max dimension detection."""
        profile = ComplexityProfile(
            cognitive_complexity=0.2,
            technical_complexity=0.9,
            creative_complexity=0.1,
            emotional_complexity=0.3,
        )
        assert profile.max_dimension == ("technical", 0.9)

    def test_requires_premium_high_overall(self):
        """Test premium required for high overall complexity."""
        profile = ComplexityProfile(
            cognitive_complexity=0.8,
            technical_complexity=0.7,
            creative_complexity=0.5,
            emotional_complexity=0.4,
        )
        assert profile.overall_complexity >= 0.6
        assert profile.requires_premium_model

    def test_requires_premium_high_single_dimension(self):
        """Test premium required for single high dimension."""
        profile = ComplexityProfile(
            cognitive_complexity=0.85,  # >= 0.8 threshold
            technical_complexity=0.2,
        )
        assert profile.requires_premium_model

    def test_requires_premium_emotional(self):
        """Test premium required for high emotional complexity."""
        profile = ComplexityProfile(
            emotional_complexity=0.75,  # >= 0.7 threshold
        )
        assert profile.requires_premium_model

    def test_model_recommendation_cheap(self):
        """Test cheap recommendation for low complexity."""
        profile = ComplexityProfile(
            cognitive_complexity=0.1,
            technical_complexity=0.1,
        )
        assert profile.model_recommendation == "cheap"

    def test_model_recommendation_default(self):
        """Test default recommendation for medium complexity."""
        profile = ComplexityProfile(
            cognitive_complexity=0.4,
            technical_complexity=0.4,
        )
        assert profile.model_recommendation == "default"

    def test_model_recommendation_premium(self):
        """Test premium recommendation for high complexity."""
        profile = ComplexityProfile(
            cognitive_complexity=0.9,
            technical_complexity=0.8,
        )
        assert profile.model_recommendation == "premium"

    def test_to_dict(self):
        """Test dictionary conversion."""
        profile = ComplexityProfile(
            cognitive_complexity=0.5,
            technical_complexity=0.3,
            indicators_found=["test1", "test2"],
        )
        d = profile.to_dict()
        assert d["cognitive"] == 0.5
        assert d["technical"] == 0.3
        assert "overall" in d
        assert "recommendation" in d
        assert "indicators" in d


class TestAdvancedComplexityAnalyzer:
    """Tests for AdvancedComplexityAnalyzer."""

    def test_simple_greeting(self):
        """Test simple greeting has low complexity."""
        profile = analyze_complexity("Hallo!")
        assert profile.overall_complexity < 0.3
        assert profile.model_recommendation == "cheap"

    def test_technical_query(self):
        """Test technical query detection."""
        query = "Debug den Python code mit dem traceback error in der API"
        profile = analyze_complexity(query)
        assert profile.technical_complexity > 0.3
        assert "technical" in str(profile.indicators_found)

    def test_emotional_query(self):
        """Test emotional query detection."""
        query = "Ich fühle mich gestresst und überfordert mit der Arbeit"
        profile = analyze_complexity(query)
        assert profile.emotional_complexity > 0.3
        assert profile.requires_premium_model or profile.emotional_complexity >= 0.5

    def test_creative_query(self):
        """Test creative query detection."""
        query = "Brainstorme innovative Ideen für eine neue Marketing Kampagne"
        profile = analyze_complexity(query)
        assert profile.creative_complexity > 0.2

    def test_cognitive_query(self):
        """Test cognitive/reasoning query detection."""
        query = "Analysiere die Vor- und Nachteile und vergleiche die beiden Strategien"
        profile = analyze_complexity(query)
        assert profile.cognitive_complexity > 0.3

    def test_domain_legal(self):
        """Test legal domain detection."""
        query = "Was sagt die DSGVO zu diesem Vertrag und der Datenschutz Klausel?"
        profile = analyze_complexity(query)
        assert profile.domain_complexity > 0.2

    def test_domain_financial(self):
        """Test financial domain detection."""
        query = "Wie berechne ich die Steuer auf meine Investitionen und das Portfolio?"
        profile = analyze_complexity(query)
        assert profile.domain_complexity > 0.2

    def test_code_block_increases_technical(self):
        """Test code blocks increase technical complexity."""
        query = """Fix this code:
        ```python
        def broken():
            return None
        ```
        """
        profile = analyze_complexity(query)
        assert profile.technical_complexity > 0.3

    def test_conversation_history_increases_interaction(self):
        """Test conversation history increases interaction complexity."""
        history = [{"content": "test"} for _ in range(10)]
        analyzer = AdvancedComplexityAnalyzer(conversation_history=history)
        profile = analyzer.analyze("und was ist mit dem anderen Thema?")
        assert profile.interaction_complexity > 0.2

    def test_multi_question_increases_cognitive(self):
        """Test multiple questions increase cognitive complexity."""
        query = "Warum ist das so? Und wie funktioniert es? Was sind die Alternativen?"
        profile = analyze_complexity(query)
        assert profile.cognitive_complexity > 0.2

    def test_short_query_low_complexity(self):
        """Test short queries have low complexity."""
        profile = analyze_complexity("ok")
        assert profile.overall_complexity < 0.3

    def test_empty_query_returns_default(self):
        """Test empty query returns default profile."""
        profile = analyze_complexity("")
        assert profile.overall_complexity == 0.0

    def test_none_query_returns_default(self):
        """Test None query returns default profile."""
        profile = analyze_complexity(None)
        assert profile.overall_complexity == 0.0

    def test_complex_multi_dimensional(self):
        """Test complex query triggers multiple dimensions."""
        query = """
        Ich bin gestresst wegen dem Code Bug im API Endpoint.
        Kannst du analysieren warum der traceback Error kommt
        und kreative Lösungen brainstormen?
        """
        profile = analyze_complexity(query)
        # Should have multiple dimensions elevated
        assert profile.technical_complexity > 0.2
        assert profile.emotional_complexity > 0.2
        assert profile.cognitive_complexity > 0.1
        # Overall should be moderate to high
        assert profile.overall_complexity > 0.3


class TestAnalyzeComplexityFunction:
    """Tests for the convenience function."""

    def test_convenience_function_works(self):
        """Test analyze_complexity convenience function."""
        profile = analyze_complexity("Test query")
        assert isinstance(profile, ComplexityProfile)

    def test_with_history(self):
        """Test with conversation history."""
        history = [{"content": "previous message"}]
        profile = analyze_complexity("follow up", conversation_history=history)
        assert isinstance(profile, ComplexityProfile)
