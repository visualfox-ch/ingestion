"""
Tests for Context-Aware Decision Engine (AI-1).

Tests ContextAnalyzer, ContextVector, and ContextualBanditEngine.
"""
import pytest
import numpy as np
from datetime import datetime, timezone

from app.intelligence import (
    ContextDimension,
    ContextVector,
    ContextAnalyzer,
    DecisionOption,
    ContextualDecision,
    ContextualBanditEngine,
)


class TestContextDimension:
    """Tests for ContextDimension dataclass."""

    def test_basic_creation(self):
        """Test basic dimension creation."""
        dim = ContextDimension(name="energy_level", value=0.7, confidence=0.8)
        assert dim.name == "energy_level"
        assert dim.value == 0.7
        assert dim.confidence == 0.8

    def test_value_clamping(self):
        """Test values are clamped to 0-1."""
        dim_high = ContextDimension(name="test", value=1.5, confidence=0.5)
        assert dim_high.value == 1.0

        dim_low = ContextDimension(name="test", value=-0.5, confidence=0.5)
        assert dim_low.value == 0.0

    def test_confidence_clamping(self):
        """Test confidence is clamped to 0-1."""
        dim = ContextDimension(name="test", value=0.5, confidence=1.5)
        assert dim.confidence == 1.0


class TestContextVector:
    """Tests for ContextVector dataclass."""

    def test_empty_creation(self):
        """Test empty context vector."""
        cv = ContextVector()
        assert cv.dimension_count == 0
        assert len(cv.to_numpy()) == 0

    def test_with_dimensions(self):
        """Test context vector with dimensions."""
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8, confidence=0.7),
                "urgency": ContextDimension(name="urgency", value=0.5, confidence=0.9),
            },
            temporal_context={
                "time_of_day": ContextDimension(name="time_of_day", value=0.6, confidence=1.0),
            },
        )
        assert cv.dimension_count == 3
        arr = cv.to_numpy()
        assert len(arr) == 3
        assert arr[0] == 0.8  # energy
        assert arr[1] == 0.5  # urgency
        assert arr[2] == 0.6  # time_of_day

    def test_to_dict_and_from_dict(self):
        """Test serialization and deserialization."""
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8, confidence=0.7),
            },
            user_id="test_user",
        )
        d = cv.to_dict()
        assert d["user_context"]["energy"]["value"] == 0.8
        assert d["user_id"] == "test_user"

        # Reconstruct
        cv2 = ContextVector.from_dict(d)
        assert cv2.user_id == "test_user"
        assert cv2.user_context["energy"].value == 0.8

    def test_get_dimension_names(self):
        """Test dimension name extraction."""
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8),
            },
            temporal_context={
                "time": ContextDimension(name="time", value=0.5),
            },
        )
        names = cv.get_dimension_names()
        assert "user:energy" in names
        assert "temporal:time" in names

    def test_confidence_weights(self):
        """Test confidence weight extraction."""
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8, confidence=0.9),
                "urgency": ContextDimension(name="urgency", value=0.5, confidence=0.7),
            },
        )
        weights = cv.get_confidence_weights()
        assert len(weights) == 2
        assert weights[0] == 0.9
        assert weights[1] == 0.7


class TestContextAnalyzer:
    """Tests for ContextAnalyzer."""

    @pytest.mark.asyncio
    async def test_analyze_simple_message(self):
        """Test analysis of a simple message."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Hallo, wie geht's?",
            conversation_history=[],
            system_state={"cpu_usage": 30.0},
        )

        assert cv.user_id == "user1"
        assert cv.dimension_count >= 18  # 5+5+4+4 dimensions
        assert "energy_level" in cv.user_context
        assert "time_of_day" in cv.temporal_context
        assert "system_load" in cv.environmental_context

    @pytest.mark.asyncio
    async def test_urgency_detection_high(self):
        """Test high urgency detection."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="DRINGEND! Ich brauche das sofort!!!",
            conversation_history=[],
        )

        urgency = cv.user_context["urgency_perception"]
        assert urgency.value > 0.5  # Should detect high urgency

    @pytest.mark.asyncio
    async def test_urgency_detection_low(self):
        """Test low urgency detection."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Wenn du Zeit hast, keine Eile",
            conversation_history=[],
        )

        urgency = cv.user_context["urgency_perception"]
        assert urgency.value < 0.4  # Should detect low urgency

    @pytest.mark.asyncio
    async def test_energy_level_high(self):
        """Test high energy detection."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Super! Das ist toll! Fantastisch!!!",
            conversation_history=[],
        )

        energy = cv.user_context["energy_level"]
        assert energy.value > 0.6

    @pytest.mark.asyncio
    async def test_energy_level_low(self):
        """Test low energy detection."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Ich bin müde und erschöpft...",
            conversation_history=[],
        )

        energy = cv.user_context["energy_level"]
        assert energy.value < 0.5

    @pytest.mark.asyncio
    async def test_work_hours_detection(self):
        """Test work vs personal time detection."""
        analyzer = ContextAnalyzer()

        # Work hours: Tuesday 10am
        work_timestamp = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)  # Tuesday
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Test",
            system_state={"timestamp": work_timestamp},
        )

        work_time = cv.temporal_context["work_vs_personal_time"]
        assert work_time.value > 0.7  # Should be work time

    @pytest.mark.asyncio
    async def test_weekend_detection(self):
        """Test weekend detection."""
        analyzer = ContextAnalyzer()

        # Weekend: Saturday 10am
        weekend_timestamp = datetime(2026, 2, 7, 10, 0, tzinfo=timezone.utc)  # Saturday
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Test",
            system_state={"timestamp": weekend_timestamp},
        )

        work_time = cv.temporal_context["work_vs_personal_time"]
        assert work_time.value < 0.4  # Should be personal time

    @pytest.mark.asyncio
    async def test_cognitive_load_from_history(self):
        """Test cognitive load increases with conversation length."""
        analyzer = ContextAnalyzer()

        # Short conversation
        cv_short = await analyzer.analyze_context(
            user_id="user1",
            message="Test",
            conversation_history=[{"content": "msg"}] * 2,
        )

        # Long conversation
        cv_long = await analyzer.analyze_context(
            user_id="user1",
            message="Test",
            conversation_history=[{"content": "msg"}] * 15,
        )

        assert cv_long.user_context["cognitive_load"].value > cv_short.user_context["cognitive_load"].value

    @pytest.mark.asyncio
    async def test_system_load_from_state(self):
        """Test system load is extracted from system state."""
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="user1",
            message="Test",
            system_state={"cpu_usage": 80.0},
        )

        system_load = cv.environmental_context["system_load"]
        assert system_load.value == 0.8
        assert system_load.confidence == 1.0


class TestDecisionOption:
    """Tests for DecisionOption dataclass."""

    def test_basic_creation(self):
        """Test basic option creation."""
        option = DecisionOption(
            id="concise",
            type="response_style",
            parameters={"length": "short"},
        )
        assert option.id == "concise"
        assert option.type == "response_style"
        assert option.parameters["length"] == "short"


class TestContextualBanditEngine:
    """Tests for ContextualBanditEngine."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = ContextualBanditEngine(feature_dim=20, exploration_alpha=1.0)
        assert engine.feature_dim == 20
        assert engine.exploration_alpha == 1.0
        assert len(engine.theta_mean) == 0

    @pytest.mark.asyncio
    async def test_select_decision_single_option(self):
        """Test decision with single option."""
        engine = ContextualBanditEngine(feature_dim=10)
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8),
            },
        )
        options = [
            DecisionOption(id="default", type="style", parameters={}),
        ]

        decision = await engine.select_optimal_decision(
            context_vector=cv,
            available_options=options,
            decision_type="test",
        )

        assert decision.selected_option.id == "default"
        assert 0 <= decision.confidence <= 1
        assert decision.decision_type == "test"

    @pytest.mark.asyncio
    async def test_select_decision_multiple_options(self):
        """Test decision with multiple options."""
        engine = ContextualBanditEngine(feature_dim=10)
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8),
                "urgency": ContextDimension(name="urgency", value=0.5),
            },
        )
        options = [
            DecisionOption(id="concise", type="style", parameters={"length": "short"}),
            DecisionOption(id="detailed", type="style", parameters={"length": "long"}),
            DecisionOption(id="balanced", type="style", parameters={"length": "medium"}),
        ]

        decision = await engine.select_optimal_decision(
            context_vector=cv,
            available_options=options,
            decision_type="response_style",
        )

        assert decision.selected_option.id in ["concise", "detailed", "balanced"]
        assert len(decision.alternative_options) == 2
        assert decision.reasoning is not None

    @pytest.mark.asyncio
    async def test_update_with_outcome(self):
        """Test updating model with outcome."""
        engine = ContextualBanditEngine(feature_dim=10)

        # Initialize arm
        await engine._initialize_arm("test:option1")
        initial_count = engine.arm_update_count.get("test:option1", 0)

        # Update with positive reward
        context_features = np.random.rand(10)
        await engine.update_with_outcome(
            decision_id="dec_1",
            arm_id="test:option1",
            context_features=context_features,
            reward=0.8,
        )

        # Check update occurred
        assert engine.arm_update_count["test:option1"] == initial_count + 1

    @pytest.mark.asyncio
    async def test_learning_affects_selection(self):
        """Test that learning affects future selections."""
        np.random.seed(42)  # For reproducibility
        engine = ContextualBanditEngine(feature_dim=5, exploration_alpha=0.1)

        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.8),
            },
        )

        options = [
            DecisionOption(id="A", type="test", parameters={}),
            DecisionOption(id="B", type="test", parameters={}),
        ]

        # Give option A consistently high rewards
        context_features = engine._create_feature_vector(cv)
        for _ in range(20):
            await engine.update_with_outcome(
                decision_id="dec",
                arm_id="test:A",
                context_features=context_features,
                reward=0.9,
            )
            await engine.update_with_outcome(
                decision_id="dec",
                arm_id="test:B",
                context_features=context_features,
                reward=0.1,
            )

        # With low exploration, should prefer A
        a_count = 0
        for _ in range(10):
            decision = await engine.select_optimal_decision(
                context_vector=cv,
                available_options=options,
                decision_type="test",
            )
            if decision.selected_option.id == "A":
                a_count += 1

        # A should be selected most of the time
        assert a_count >= 7  # At least 70% of the time

    @pytest.mark.asyncio
    async def test_uncertainty_metrics(self):
        """Test uncertainty metrics calculation."""
        engine = ContextualBanditEngine(feature_dim=10)
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.5),
            },
        )
        options = [
            DecisionOption(id="A", type="test", parameters={}),
            DecisionOption(id="B", type="test", parameters={}),
        ]

        decision = await engine.select_optimal_decision(
            context_vector=cv,
            available_options=options,
            decision_type="test",
        )

        assert "reward_variance" in decision.uncertainty_metrics
        assert "entropy" in decision.uncertainty_metrics
        assert "model_uncertainty" in decision.uncertainty_metrics

    @pytest.mark.asyncio
    async def test_context_factors_extraction(self):
        """Test context factor influence extraction."""
        engine = ContextualBanditEngine(feature_dim=10)
        cv = ContextVector(
            user_context={
                "energy": ContextDimension(name="energy", value=0.9),
                "urgency": ContextDimension(name="urgency", value=0.3),
            },
            temporal_context={
                "time": ContextDimension(name="time", value=0.7),
            },
        )
        options = [
            DecisionOption(id="test", type="test", parameters={}),
        ]

        decision = await engine.select_optimal_decision(
            context_vector=cv,
            available_options=options,
            decision_type="test",
        )

        assert len(decision.context_factors) > 0
        # Each factor is (name, influence) tuple
        for name, influence in decision.context_factors:
            assert isinstance(name, str)
            assert isinstance(influence, float)

    def test_get_arm_statistics(self):
        """Test arm statistics retrieval."""
        engine = ContextualBanditEngine(feature_dim=10)
        engine.theta_mean["test:A"] = np.random.rand(10)
        engine.arm_update_count["test:A"] = 5
        engine.theta_mean["test:B"] = np.random.rand(10)
        engine.arm_update_count["test:B"] = 3
        engine.theta_mean["other:C"] = np.random.rand(10)
        engine.arm_update_count["other:C"] = 10

        stats = engine.get_arm_statistics("test")
        assert "A" in stats
        assert "B" in stats
        assert "C" not in stats
        assert stats["A"]["update_count"] == 5
        assert stats["B"]["update_count"] == 3


class TestIntegration:
    """Integration tests for the full decision flow."""

    @pytest.mark.asyncio
    async def test_full_decision_flow(self):
        """Test complete flow from context analysis to decision."""
        # 1. Analyze context
        analyzer = ContextAnalyzer()
        cv = await analyzer.analyze_context(
            user_id="micha",
            message="Ich brauche dringend eine kurze Zusammenfassung",
            conversation_history=[],
            system_state={"cpu_usage": 20.0},
        )

        # 2. Make decision
        engine = ContextualBanditEngine(feature_dim=20)
        options = [
            DecisionOption(
                id="detailed",
                type="response_strategy",
                parameters={"length": "long", "depth": "comprehensive"},
            ),
            DecisionOption(
                id="concise",
                type="response_strategy",
                parameters={"length": "short", "depth": "summary"},
            ),
        ]

        decision = await engine.select_optimal_decision(
            context_vector=cv,
            available_options=options,
            decision_type="response_strategy",
            user_id="micha",
        )

        # 3. Verify decision
        assert decision.user_id == "micha"
        assert decision.decision_type == "response_strategy"
        assert decision.selected_option.id in ["detailed", "concise"]
        assert decision.context_vector is not None
        assert decision.expected_outcome is not None

        # 4. Record outcome
        context_features = engine._create_feature_vector(cv)
        await engine.update_with_outcome(
            decision_id=decision.decision_id,
            arm_id=f"response_strategy:{decision.selected_option.id}",
            context_features=context_features,
            reward=0.85,  # Good outcome
        )

        # 5. Verify learning occurred
        arm_id = f"response_strategy:{decision.selected_option.id}"
        assert engine.arm_update_count[arm_id] == 1
