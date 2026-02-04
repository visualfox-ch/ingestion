"""
Tests for Facette Detection (T-005 Phase 1)

Tests the Q2 Answer implementation: Sentiment + Context Weight
activation mechanism for unified personality.

Author: GitHub Copilot
Created: 2026-02-03
"""

import pytest
from app.facette_detector import FacetteDetector, FacetteWeights, get_facette_detector


class TestFacetteWeights:
    """Test FacetteWeights dataclass"""
    
    def test_normalize_with_values(self):
        """Test normalization with non-zero weights"""
        weights = FacetteWeights(
            analytical=2.0,
            empathic=1.0,
            pragmatic=1.0,
            creative=0.0
        )
        normalized = weights.normalize()
        
        # Should sum to 1.0
        total = normalized.analytical + normalized.empathic + normalized.pragmatic + normalized.creative
        assert abs(total - 1.0) < 0.01
        
        # Proportions should be correct
        assert abs(normalized.analytical - 0.5) < 0.01  # 2/4
        assert abs(normalized.empathic - 0.25) < 0.01   # 1/4
        assert abs(normalized.pragmatic - 0.25) < 0.01  # 1/4
        assert normalized.creative == 0.0
    
    def test_normalize_zero_defaults(self):
        """Test normalization with all zeros (should return default blend)"""
        weights = FacetteWeights()
        normalized = weights.normalize()
        
        # Should return default blend
        assert normalized.analytical == 0.4
        assert normalized.empathic == 0.2
        assert normalized.pragmatic == 0.3
        assert normalized.creative == 0.1
    
    def test_to_dict(self):
        """Test conversion to dict"""
        weights = FacetteWeights(
            analytical=0.5,
            empathic=0.25,
            pragmatic=0.15,
            creative=0.1
        )
        result = weights.to_dict()
        
        assert result == {
            "Analytical": 0.5,
            "Empathic": 0.25,
            "Pragmatic": 0.15,
            "Creative": 0.1
        }
    
    def test_dominant_facette(self):
        """Test dominant facette detection"""
        weights = FacetteWeights(
            analytical=0.1,
            empathic=0.6,
            pragmatic=0.2,
            creative=0.1
        )
        assert weights.dominant_facette() == "Empathic"


class TestFacetteDetector:
    """Test FacetteDetector keyword and sentiment detection"""
    
    @pytest.fixture
    def detector(self):
        return FacetteDetector()
    
    def test_analytical_keywords(self, detector):
        """Test detection of analytical keywords (Q2 Answer)"""
        query = "Can you analyze the metrics and explain how the system works?"
        result = detector.detect(query)
        
        # Should have high analytical weight
        assert result.analytical > 0.3
    
    def test_empathic_keywords(self, detector):
        """Test detection of empathic keywords (Q2 Answer: stress → +Empathic)"""
        query = "I'm feeling overwhelmed and stressed, too much to handle"
        result = detector.detect(query)
        
        # Should have high empathic weight (Q2: stress → +Empathic +Pragmatic)
        assert result.empathic > 0.3
    
    def test_pragmatic_keywords(self, detector):
        """Test detection of pragmatic keywords (Q2 Answer: action → +Pragmatic)"""
        query = "What should I do next? What's the next step to fix this?"
        result = detector.detect(query)
        
        # Should have high pragmatic weight
        assert result.pragmatic > 0.3
    
    def test_creative_keywords(self, detector):
        """Test detection of creative keywords (Q2 Answer: open → +Creative)"""
        query = "What if we tried a different approach? Any creative ideas?"
        result = detector.detect(query)
        
        # Should have high creative weight
        assert result.creative > 0.2
    
    def test_stress_sentiment_boost(self, detector):
        """Test Q2 Answer example: stress → +Empathic +Pragmatic"""
        query = "I'm stressed and overwhelmed, what should I do?"
        result = detector.detect(query)
        
        # Should boost both empathic and pragmatic
        assert result.empathic > 0.3
        assert result.pragmatic > 0.2
    
    def test_question_marks_boost_analytical(self, detector):
        """Test sentiment: multiple questions → boost Analytical"""
        query = "Why does this happen? How does it work? What causes it?"
        result = detector.detect(query)
        
        assert result.analytical > 0.3
    
    def test_enthusiasm_boost_creative(self, detector):
        """Test sentiment: enthusiasm → boost Creative"""
        query = "What if we could build something amazing! Let's explore new ideas!"
        result = detector.detect(query)
        
        assert result.creative > 0.2
    
    def test_action_imperative_boost_pragmatic(self, detector):
        """Test sentiment: imperative → boost Pragmatic"""
        query = "Fix this bug now and deploy the changes"
        result = detector.detect(query)
        
        assert result.pragmatic > 0.4
    
    def test_fitness_analytical_blend(self, detector):
        """
        Test Q1 Answer example:
        Fitness + Analytical = 'Let's track metrics, optimize splits'
        """
        query = "Let's analyze my training metrics and optimize my workout splits"
        result = detector.detect(query)
        
        # Should detect both analytical (optimize, metrics) and fitness domain
        assert result.analytical > 0.3
        domain = detector.detect_domain(query)
        assert domain == "Fitness"
    
    def test_fitness_empathic_blend(self, detector):
        """
        Test Q1 Answer example:
        Fitness + Empathic = 'How does your body feel? Energy levels?'
        """
        query = "How does my body feel after training? What are my energy levels?"
        result = detector.detect(query)
        
        # Should detect empathic (feel, energy)
        assert result.empathic > 0.2
        domain = detector.detect_domain(query)
        assert domain == "Fitness"
    
    def test_domain_detection_fitness(self, detector):
        """Test domain detection for Fitness"""
        queries = [
            "What's my workout schedule?",
            "How should I train today?",
            "Nutrition plan for muscle gain"
        ]
        for query in queries:
            domain = detector.detect_domain(query)
            assert domain == "Fitness", f"Failed for: {query}"
    
    def test_domain_detection_engineering(self, detector):
        """Test domain detection for Engineering"""
        queries = [
            "Fix this bug in the Python code",
            "Deploy the Docker container",
            "API endpoint is returning 500"
        ]
        for query in queries:
            domain = detector.detect_domain(query)
            assert domain == "Engineering", f"Failed for: {query}"
    
    def test_domain_detection_general(self, detector):
        """Test domain detection for General (fallback)"""
        query = "What's the weather like today?"
        domain = detector.detect_domain(query)
        assert domain == "General"
    
    def test_normalize_returns_sum_of_one(self, detector):
        """Test that all detections normalize to sum of 1.0"""
        queries = [
            "Analyze this data carefully",
            "I'm feeling stressed and overwhelmed",
            "What should I do next?",
            "Let's brainstorm creative ideas"
        ]
        for query in queries:
            result = detector.detect(query)
            total = sum(result.to_dict().values())
            assert abs(total - 1.0) < 0.01, f"Failed for: {query}, total={total}"
    
    def test_singleton_pattern(self):
        """Test that get_facette_detector returns same instance"""
        detector1 = get_facette_detector()
        detector2 = get_facette_detector()
        assert detector1 is detector2


class TestRealWorldQueries:
    """Test with real-world query examples"""
    
    @pytest.fixture
    def detector(self):
        return get_facette_detector()
    
    def test_complex_technical_query(self, detector):
        """Test complex technical query (should be Analytical + Pragmatic)"""
        query = "Why is the Docker container failing to start? Can you analyze the logs and tell me what to fix?"
        result = detector.detect(query)
        
        # Should be analytical (why, analyze) + pragmatic (fix)
        assert result.analytical + result.pragmatic > 0.6
        domain = detector.detect_domain(query)
        assert domain == "Engineering"
    
    def test_emotional_coaching_query(self, detector):
        """Test emotional coaching query (should be Empathic + Pragmatic)"""
        query = "I'm feeling stuck with my career goals. What should I do to move forward?"
        result = detector.detect(query)
        
        # Should be empathic (feeling, stuck) + pragmatic (what should I do)
        assert result.empathic + result.pragmatic > 0.6
        domain = detector.detect_domain(query)
        assert domain == "Coaching"
    
    def test_creative_brainstorming_query(self, detector):
        """Test creative brainstorming query (should be Creative dominant)"""
        query = "What if we could design a completely new approach? Let's explore innovative ideas!"
        result = detector.detect(query)
        
        # Should have high creative weight
        assert result.creative > 0.3
        assert result.dominant_facette() in ["Creative", "Analytical"]
