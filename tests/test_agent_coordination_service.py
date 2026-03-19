from datetime import datetime, timedelta

from app.services.agent_coordination_service import (
    AgentCoordinationService,
    CoordinationPosition,
    CoordinationState,
    CoordinationStrategy,
)


def _service_no_db() -> AgentCoordinationService:
    return AgentCoordinationService.__new__(AgentCoordinationService)


def _claim(agent_name: str, capability_score=None, seconds_offset: int = 0) -> CoordinationPosition:
    return CoordinationPosition(
        agent_name=agent_name,
        position_type="claim",
        capability_score=capability_score,
        created_at=datetime(2026, 3, 19, 12, 0, 0) + timedelta(seconds=seconds_offset),
    )


def _bid(agent_name: str, bid_score: float, seconds_offset: int = 0) -> CoordinationPosition:
    return CoordinationPosition(
        agent_name=agent_name,
        position_type="bid",
        bid_score=bid_score,
        created_at=datetime(2026, 3, 19, 12, 0, 0) + timedelta(seconds=seconds_offset),
    )


def _vote(agent_name: str, vote_value: str) -> CoordinationPosition:
    return CoordinationPosition(
        agent_name=agent_name,
        position_type="vote",
        vote_value=vote_value,
        created_at=datetime(2026, 3, 19, 12, 0, 0),
    )


def test_claim_based_first_claim_then_contested():
    service = _service_no_db()

    first = service._evaluate_claims(CoordinationStrategy.CLAIM_BASED.value, [_claim("fit_jarvis")])
    assert first["state"] == CoordinationState.CLAIMED.value
    assert first["chosen_agent"] == "fit_jarvis"

    contested = service._evaluate_claims(
        CoordinationStrategy.CLAIM_BASED.value,
        [_claim("fit_jarvis"), _claim("work_jarvis", seconds_offset=1)],
    )
    assert contested["state"] == CoordinationState.CONTESTED.value
    assert contested["chosen_agent"] == "fit_jarvis"


def test_capability_based_highest_score_wins():
    service = _service_no_db()
    result = service._evaluate_claims(
        CoordinationStrategy.CAPABILITY_BASED.value,
        [_claim("fit_jarvis", 0.71), _claim("work_jarvis", 0.88), _claim("comm_jarvis", 0.64)],
    )
    assert result["state"] == CoordinationState.CLAIMED.value
    assert result["chosen_agent"] == "work_jarvis"


def test_capability_based_tie_becomes_contested():
    service = _service_no_db()
    result = service._evaluate_claims(
        CoordinationStrategy.CAPABILITY_BASED.value,
        [_claim("fit_jarvis", 0.8), _claim("work_jarvis", 0.8)],
    )
    assert result["state"] == CoordinationState.CONTESTED.value
    assert result["chosen_agent"] is None


def test_auction_based_highest_bid_wins():
    service = _service_no_db()
    result = service._evaluate_bids(
        CoordinationStrategy.AUCTION_BASED.value,
        [_bid("fit_jarvis", 0.55), _bid("work_jarvis", 0.91), _bid("comm_jarvis", 0.73)],
    )
    assert result["state"] == CoordinationState.CLAIMED.value
    assert result["chosen_agent"] == "work_jarvis"


def test_auction_tie_becomes_contested():
    service = _service_no_db()
    result = service._evaluate_bids(
        CoordinationStrategy.AUCTION_BASED.value,
        [_bid("fit_jarvis", 0.77), _bid("work_jarvis", 0.77)],
    )
    assert result["state"] == CoordinationState.CONTESTED.value


def test_consensus_majority_reaches_consensus():
    service = _service_no_db()
    summary = service._compute_consensus_summary(
        ["fit_jarvis", "work_jarvis", "comm_jarvis"],
        [_vote("fit_jarvis", "approve"), _vote("work_jarvis", "approve"), _vote("comm_jarvis", "reject")],
    )
    assert summary["state"] == CoordinationState.CONSENSUS_REACHED.value
    assert summary["approve"] == 2
    assert summary["threshold"] == 2


def test_consensus_rejection_escalates():
    service = _service_no_db()
    summary = service._compute_consensus_summary(
        ["fit_jarvis", "work_jarvis", "comm_jarvis"],
        [_vote("fit_jarvis", "reject"), _vote("work_jarvis", "reject")],
    )
    assert summary["state"] == CoordinationState.ESCALATED.value


def test_hierarchical_falls_back_to_contested_for_claims_without_scores():
    service = _service_no_db()
    result = service._evaluate_claims(
        CoordinationStrategy.HIERARCHICAL.value,
        [_claim("fit_jarvis"), _claim("work_jarvis")],
    )
    assert result["state"] == CoordinationState.CONTESTED.value