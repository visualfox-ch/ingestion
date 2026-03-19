"""
Agent Coordination Service - Phase 22B-07/08/09

Negotiation, conflict resolution, and consensus support for multi-agent work.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import uuid
from typing import Any, Dict, List, Optional

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn, get_dict_cursor

logger = get_logger("jarvis.agent_coordination")


class CoordinationStrategy(str, Enum):
    CLAIM_BASED = "claim_based"
    CAPABILITY_BASED = "capability_based"
    AUCTION_BASED = "auction_based"
    HIERARCHICAL = "hierarchical"


class CoordinationState(str, Enum):
    PROPOSED = "proposed"
    CLAIMED = "claimed"
    BIDDING = "bidding"
    CONTESTED = "contested"
    RESOLVED = "resolved"
    CONSENSUS_REACHED = "consensus_reached"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class PositionType(str, Enum):
    CLAIM = "claim"
    BID = "bid"
    VOTE = "vote"


@dataclass
class CoordinationPosition:
    agent_name: str
    position_type: str
    capability_score: Optional[float] = None
    bid_score: Optional[float] = None
    vote_value: Optional[str] = None
    rationale: Optional[str] = None
    created_at: Optional[datetime] = None


class AgentCoordinationService:
    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_agent_negotiations (
                            id SERIAL PRIMARY KEY,
                            negotiation_id VARCHAR(50) UNIQUE NOT NULL,
                            title TEXT NOT NULL,
                            original_query TEXT,
                            initiator_agent VARCHAR(50) NOT NULL,
                            strategy VARCHAR(30) NOT NULL,
                            state VARCHAR(30) NOT NULL DEFAULT 'proposed',
                            candidate_agents JSONB DEFAULT '[]'::jsonb,
                            context JSONB DEFAULT '{}'::jsonb,
                            chosen_agent VARCHAR(50),
                            arbitration_agent VARCHAR(50),
                            conflict_reason TEXT,
                            consensus_summary JSONB DEFAULT '{}'::jsonb,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            resolved_at TIMESTAMP
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_agent_negotiation_positions (
                            id SERIAL PRIMARY KEY,
                            negotiation_id VARCHAR(50) NOT NULL,
                            agent_name VARCHAR(50) NOT NULL,
                            position_type VARCHAR(20) NOT NULL,
                            capability_score REAL,
                            bid_score REAL,
                            vote_value VARCHAR(20),
                            rationale TEXT,
                            metadata JSONB DEFAULT '{}'::jsonb,
                            created_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(negotiation_id, agent_name, position_type)
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_agent_coordination_events (
                            id SERIAL PRIMARY KEY,
                            negotiation_id VARCHAR(50) NOT NULL,
                            event_type VARCHAR(30) NOT NULL,
                            actor_agent VARCHAR(50),
                            payload JSONB DEFAULT '{}'::jsonb,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_negotiations_state_strategy
                        ON jarvis_agent_negotiations(state, strategy, created_at DESC)
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_negotiation_positions_lookup
                        ON jarvis_agent_negotiation_positions(negotiation_id, position_type, created_at)
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_coordination_events_lookup
                        ON jarvis_agent_coordination_events(negotiation_id, created_at)
                        """
                    )
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Coordination table creation failed", error=str(e))

    def propose_negotiation(
        self,
        title: str,
        initiator_agent: str,
        candidate_agents: List[str],
        strategy: str = "capability_based",
        original_query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            strategy_enum = CoordinationStrategy(strategy)
        except ValueError:
            return {"success": False, "error": f"Invalid strategy: {strategy}"}

        negotiation_id = f"neg_{uuid.uuid4().hex[:12]}"

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_agent_negotiations
                        (negotiation_id, title, original_query, initiator_agent, strategy, candidate_agents, context)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            negotiation_id,
                            title,
                            original_query,
                            initiator_agent,
                            strategy_enum.value,
                            json.dumps(candidate_agents or []),
                            json.dumps(context or {}),
                        ),
                    )
                    conn.commit()

            self._record_event(negotiation_id, "proposed", initiator_agent, {"strategy": strategy_enum.value})
            return {
                "success": True,
                "negotiation_id": negotiation_id,
                "strategy": strategy_enum.value,
                "state": CoordinationState.PROPOSED.value,
                "candidate_agents": candidate_agents,
            }
        except Exception as e:
            log_with_context(logger, "error", "propose_negotiation failed", error=str(e))
            return {"success": False, "error": str(e)}

    def claim_task(
        self,
        negotiation_id: str,
        agent_name: str,
        capability_score: Optional[float] = None,
        rationale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        negotiation = self._get_negotiation(negotiation_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        strategy = negotiation["strategy"]
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_agent_negotiation_positions
                        (negotiation_id, agent_name, position_type, capability_score, rationale, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (negotiation_id, agent_name, position_type)
                        DO UPDATE SET
                            capability_score = EXCLUDED.capability_score,
                            rationale = EXCLUDED.rationale,
                            metadata = EXCLUDED.metadata,
                            created_at = NOW()
                        """,
                        (
                            negotiation_id,
                            agent_name,
                            PositionType.CLAIM.value,
                            capability_score,
                            rationale,
                            json.dumps(metadata or {}),
                        ),
                    )
                    conn.commit()

            self._record_event(negotiation_id, "claim_submitted", agent_name, {"capability_score": capability_score})
            claims = self._get_positions(negotiation_id, PositionType.CLAIM.value)
            evaluation = self._evaluate_claims(strategy, claims)
            self._apply_evaluation(negotiation_id, evaluation)
            return {"success": True, "negotiation_id": negotiation_id, **evaluation}
        except Exception as e:
            log_with_context(logger, "error", "claim_task failed", error=str(e))
            return {"success": False, "error": str(e)}

    def submit_bid(
        self,
        negotiation_id: str,
        agent_name: str,
        bid_score: float,
        rationale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        negotiation = self._get_negotiation(negotiation_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_agent_negotiation_positions
                        (negotiation_id, agent_name, position_type, bid_score, rationale, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (negotiation_id, agent_name, position_type)
                        DO UPDATE SET
                            bid_score = EXCLUDED.bid_score,
                            rationale = EXCLUDED.rationale,
                            metadata = EXCLUDED.metadata,
                            created_at = NOW()
                        """,
                        (
                            negotiation_id,
                            agent_name,
                            PositionType.BID.value,
                            bid_score,
                            rationale,
                            json.dumps(metadata or {}),
                        ),
                    )
                    cur.execute(
                        """
                        UPDATE jarvis_agent_negotiations
                        SET state = %s, updated_at = NOW()
                        WHERE negotiation_id = %s AND state = %s
                        """,
                        (CoordinationState.BIDDING.value, negotiation_id, CoordinationState.PROPOSED.value),
                    )
                    conn.commit()

            self._record_event(negotiation_id, "bid_submitted", agent_name, {"bid_score": bid_score})
            bids = self._get_positions(negotiation_id, PositionType.BID.value)
            evaluation = self._evaluate_bids(negotiation["strategy"], bids)
            self._apply_evaluation(negotiation_id, evaluation)
            return {"success": True, "negotiation_id": negotiation_id, **evaluation}
        except Exception as e:
            log_with_context(logger, "error", "submit_bid failed", error=str(e))
            return {"success": False, "error": str(e)}

    def resolve_conflict(
        self,
        negotiation_id: str,
        arbitrator_agent: str = "jarvis_core",
        preferred_agent: Optional[str] = None,
        resolution_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        negotiation = self._get_negotiation(negotiation_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        claims = self._get_positions(negotiation_id, PositionType.CLAIM.value)
        bids = self._get_positions(negotiation_id, PositionType.BID.value)

        resolved_agent = preferred_agent
        if not resolved_agent:
            if negotiation["strategy"] == CoordinationStrategy.AUCTION_BASED.value:
                evaluation = self._evaluate_ranked_positions(bids, "bid_score")
            elif negotiation["strategy"] == CoordinationStrategy.CLAIM_BASED.value:
                evaluation = self._evaluate_ranked_positions(claims, "created_at")
            else:
                evaluation = self._evaluate_ranked_positions(claims, "capability_score")
            resolved_agent = evaluation.get("chosen_agent")

        if not resolved_agent:
            self._update_negotiation_state(
                negotiation_id,
                CoordinationState.ESCALATED.value,
                None,
                arbitrator_agent,
                resolution_note or "No unique winner available",
            )
            self._record_event(negotiation_id, "escalated", arbitrator_agent, {"note": resolution_note})
            return {
                "success": True,
                "negotiation_id": negotiation_id,
                "state": CoordinationState.ESCALATED.value,
                "chosen_agent": None,
            }

        self._update_negotiation_state(
            negotiation_id,
            CoordinationState.RESOLVED.value,
            resolved_agent,
            arbitrator_agent,
            resolution_note,
        )
        self._record_event(negotiation_id, "resolved", arbitrator_agent, {"chosen_agent": resolved_agent})
        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "state": CoordinationState.RESOLVED.value,
            "chosen_agent": resolved_agent,
            "arbitrator_agent": arbitrator_agent,
        }

    def record_consensus_vote(
        self,
        negotiation_id: str,
        agent_name: str,
        vote_value: str,
        rationale: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_vote = (vote_value or "").lower()
        if normalized_vote not in {"approve", "reject", "abstain"}:
            return {"success": False, "error": f"Invalid vote_value: {vote_value}"}

        negotiation = self._get_negotiation(negotiation_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_agent_negotiation_positions
                        (negotiation_id, agent_name, position_type, vote_value, rationale)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (negotiation_id, agent_name, position_type)
                        DO UPDATE SET
                            vote_value = EXCLUDED.vote_value,
                            rationale = EXCLUDED.rationale,
                            created_at = NOW()
                        """,
                        (negotiation_id, agent_name, PositionType.VOTE.value, normalized_vote, rationale),
                    )
                    conn.commit()

            self._record_event(negotiation_id, "vote_recorded", agent_name, {"vote": normalized_vote})
            votes = self._get_positions(negotiation_id, PositionType.VOTE.value)
            summary = self._compute_consensus_summary(negotiation.get("candidate_agents") or [], votes)
            if summary["state"] == CoordinationState.CONSENSUS_REACHED.value:
                self._update_consensus(negotiation_id, summary)
            return {"success": True, "negotiation_id": negotiation_id, **summary}
        except Exception as e:
            log_with_context(logger, "error", "record_consensus_vote failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_coordination_status(self, negotiation_id: str) -> Dict[str, Any]:
        negotiation = self._get_negotiation(negotiation_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        claims = self._get_positions(negotiation_id, PositionType.CLAIM.value)
        bids = self._get_positions(negotiation_id, PositionType.BID.value)
        votes = self._get_positions(negotiation_id, PositionType.VOTE.value)

        return {
            "success": True,
            "negotiation": negotiation,
            "claims": [self._serialize_position(position) for position in claims],
            "bids": [self._serialize_position(position) for position in bids],
            "votes": [self._serialize_position(position) for position in votes],
        }

    def get_coordination_stats(self, days: int = 7) -> Dict[str, Any]:
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT strategy, state, COUNT(*) AS count
                    FROM jarvis_agent_negotiations
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY strategy, state
                    ORDER BY strategy, state
                    """,
                    (max(1, days),),
                )
                rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT position_type, COUNT(*) AS count
                    FROM jarvis_agent_negotiation_positions
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY position_type
                    ORDER BY position_type
                    """,
                    (max(1, days),),
                )
                position_rows = cur.fetchall()

            return {
                "success": True,
                "period_days": days,
                "negotiations": rows,
                "position_counts": position_rows,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_negotiation(self, negotiation_id: str) -> Optional[Dict[str, Any]]:
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT negotiation_id, title, original_query, initiator_agent, strategy,
                           state, candidate_agents, context, chosen_agent, arbitration_agent,
                           conflict_reason, consensus_summary, created_at, updated_at, resolved_at
                    FROM jarvis_agent_negotiations
                    WHERE negotiation_id = %s
                    LIMIT 1
                    """,
                    (negotiation_id,),
                )
                return cur.fetchone()
        except Exception:
            return None

    def _get_positions(self, negotiation_id: str, position_type: str) -> List[CoordinationPosition]:
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT agent_name, position_type, capability_score, bid_score, vote_value,
                           rationale, created_at
                    FROM jarvis_agent_negotiation_positions
                    WHERE negotiation_id = %s AND position_type = %s
                    ORDER BY created_at ASC
                    """,
                    (negotiation_id, position_type),
                )
                rows = cur.fetchall()
            return [
                CoordinationPosition(
                    agent_name=row["agent_name"],
                    position_type=row["position_type"],
                    capability_score=row["capability_score"],
                    bid_score=row["bid_score"],
                    vote_value=row["vote_value"],
                    rationale=row["rationale"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
        except Exception:
            return []

    def _evaluate_claims(self, strategy: str, claims: List[CoordinationPosition]) -> Dict[str, Any]:
        if not claims:
            return {"state": CoordinationState.PROPOSED.value, "chosen_agent": None}

        if strategy == CoordinationStrategy.CLAIM_BASED.value:
            if len(claims) == 1:
                return {"state": CoordinationState.CLAIMED.value, "chosen_agent": claims[0].agent_name}
            return {
                "state": CoordinationState.CONTESTED.value,
                "chosen_agent": claims[0].agent_name,
                "conflict_reason": "Multiple agents claimed the same task",
            }

        return self._evaluate_ranked_positions(claims, "capability_score")

    def _evaluate_bids(self, strategy: str, bids: List[CoordinationPosition]) -> Dict[str, Any]:
        if strategy != CoordinationStrategy.AUCTION_BASED.value:
            return {
                "state": CoordinationState.CONTESTED.value,
                "chosen_agent": None,
                "conflict_reason": "Bids submitted for non-auction strategy",
            }
        return self._evaluate_ranked_positions(bids, "bid_score")

    def _evaluate_ranked_positions(self, positions: List[CoordinationPosition], rank_field: str) -> Dict[str, Any]:
        if not positions:
            return {"state": CoordinationState.PROPOSED.value, "chosen_agent": None}

        if rank_field == "created_at":
            ordered = sorted(positions, key=lambda item: item.created_at or datetime.min)
            return {"state": CoordinationState.RESOLVED.value, "chosen_agent": ordered[0].agent_name}

        ordered = sorted(
            positions,
            key=lambda item: (getattr(item, rank_field) if getattr(item, rank_field) is not None else -1.0),
            reverse=True,
        )
        top_value = getattr(ordered[0], rank_field)
        if top_value is None:
            return {
                "state": CoordinationState.CONTESTED.value,
                "chosen_agent": None,
                "conflict_reason": f"Missing {rank_field} for ranking",
            }

        tied = [item for item in ordered if getattr(item, rank_field) == top_value]
        if len(tied) > 1:
            return {
                "state": CoordinationState.CONTESTED.value,
                "chosen_agent": None,
                "conflict_reason": f"Tie on {rank_field}",
            }

        return {"state": CoordinationState.CLAIMED.value, "chosen_agent": ordered[0].agent_name}

    def _compute_consensus_summary(
        self,
        candidate_agents: List[str],
        votes: List[CoordinationPosition],
    ) -> Dict[str, Any]:
        approve = sum(1 for vote in votes if vote.vote_value == "approve")
        reject = sum(1 for vote in votes if vote.vote_value == "reject")
        abstain = sum(1 for vote in votes if vote.vote_value == "abstain")
        total_voters = len(candidate_agents) or len(votes)
        threshold = max(1, (total_voters // 2) + 1)

        if approve >= threshold:
            state = CoordinationState.CONSENSUS_REACHED.value
        elif reject >= threshold:
            state = CoordinationState.ESCALATED.value
        else:
            state = CoordinationState.CONTESTED.value

        return {
            "state": state,
            "approve": approve,
            "reject": reject,
            "abstain": abstain,
            "threshold": threshold,
            "votes_recorded": len(votes),
        }

    def _apply_evaluation(self, negotiation_id: str, evaluation: Dict[str, Any]) -> None:
        self._update_negotiation_state(
            negotiation_id,
            evaluation.get("state", CoordinationState.PROPOSED.value),
            evaluation.get("chosen_agent"),
            None,
            evaluation.get("conflict_reason"),
        )

    def _update_negotiation_state(
        self,
        negotiation_id: str,
        state: str,
        chosen_agent: Optional[str],
        arbitration_agent: Optional[str],
        conflict_reason: Optional[str],
    ) -> None:
        resolved_at = datetime.now() if state in {
            CoordinationState.RESOLVED.value,
            CoordinationState.CONSENSUS_REACHED.value,
        } else None

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jarvis_agent_negotiations
                    SET state = %s,
                        chosen_agent = COALESCE(%s, chosen_agent),
                        arbitration_agent = COALESCE(%s, arbitration_agent),
                        conflict_reason = %s,
                        updated_at = NOW(),
                        resolved_at = COALESCE(%s, resolved_at)
                    WHERE negotiation_id = %s
                    """,
                    (state, chosen_agent, arbitration_agent, conflict_reason, resolved_at, negotiation_id),
                )
                conn.commit()

    def _update_consensus(self, negotiation_id: str, summary: Dict[str, Any]) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jarvis_agent_negotiations
                    SET state = %s,
                        consensus_summary = %s,
                        updated_at = NOW(),
                        resolved_at = NOW()
                    WHERE negotiation_id = %s
                    """,
                    (CoordinationState.CONSENSUS_REACHED.value, json.dumps(summary), negotiation_id),
                )
                conn.commit()

    def _record_event(
        self,
        negotiation_id: str,
        event_type: str,
        actor_agent: Optional[str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_agent_coordination_events
                        (negotiation_id, event_type, actor_agent, payload)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (negotiation_id, event_type, actor_agent, json.dumps(payload or {})),
                    )
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "record_event failed", error=str(e))

    def _serialize_position(self, position: CoordinationPosition) -> Dict[str, Any]:
        return {
            "agent_name": position.agent_name,
            "position_type": position.position_type,
            "capability_score": position.capability_score,
            "bid_score": position.bid_score,
            "vote_value": position.vote_value,
            "rationale": position.rationale,
            "created_at": position.created_at.isoformat() if position.created_at else None,
        }


_service: Optional[AgentCoordinationService] = None


def get_agent_coordination_service() -> AgentCoordinationService:
    global _service
    if _service is None:
        _service = AgentCoordinationService()
    return _service