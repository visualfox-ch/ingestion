"""
Agent Context Pool Service - Phase 22B-04/05/06

Implements shared context infrastructure for specialist agents:
- Cross-agent context pool (T-22B-04)
- Context subscriptions (T-22B-05)
- Privacy boundaries and visibility guards (T-22B-06)
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json
import uuid

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn, get_dict_cursor

logger = get_logger("jarvis.agent_context_pool")


class ContextVisibility(str, Enum):
    GLOBAL = "global"
    DOMAIN = "domain"
    PRIVATE = "private"
    TEMPORARY = "temporary"


@dataclass
class ContextEntry:
    context_id: str
    source_agent: str
    context_key: str
    context_value: Dict[str, Any]
    visibility: ContextVisibility
    domain: Optional[str]
    tags: List[str]
    metadata: Dict[str, Any]
    session_id: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime


@dataclass
class ContextSubscription:
    subscription_id: str
    agent_id: str
    visibility_levels: List[str]
    domains: List[str]
    source_agents: List[str]
    tags: List[str]
    include_temporary: bool


class AgentContextPoolService:
    """Shared context pool with subscriptions and privacy boundaries."""

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_shared_context_pool (
                            id SERIAL PRIMARY KEY,
                            context_id VARCHAR(50) UNIQUE NOT NULL,
                            source_agent VARCHAR(50) NOT NULL,
                            context_key VARCHAR(120) NOT NULL,
                            context_value JSONB NOT NULL,
                            visibility VARCHAR(20) NOT NULL DEFAULT 'domain',
                            domain VARCHAR(50),
                            tags JSONB DEFAULT '[]'::jsonb,
                            metadata JSONB DEFAULT '{}'::jsonb,
                            session_id VARCHAR(100),
                            expires_at TIMESTAMP,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_context_subscriptions (
                            id SERIAL PRIMARY KEY,
                            subscription_id VARCHAR(50) UNIQUE NOT NULL,
                            agent_id VARCHAR(50) NOT NULL,
                            visibility_levels JSONB DEFAULT '["global", "domain"]'::jsonb,
                            domains JSONB DEFAULT '[]'::jsonb,
                            source_agents JSONB DEFAULT '[]'::jsonb,
                            tags JSONB DEFAULT '[]'::jsonb,
                            include_temporary BOOLEAN DEFAULT FALSE,
                            active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(agent_id)
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jarvis_context_privacy_boundaries (
                            id SERIAL PRIMARY KEY,
                            source_agent VARCHAR(50) NOT NULL,
                            target_agent VARCHAR(50) NOT NULL,
                            allowed_levels JSONB DEFAULT '["global", "domain"]'::jsonb,
                            allowed_keys JSONB DEFAULT '[]'::jsonb,
                            denied_keys JSONB DEFAULT '[]'::jsonb,
                            active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(source_agent, target_agent)
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_context_pool_source_visibility
                        ON jarvis_shared_context_pool(source_agent, visibility, created_at DESC)
                        """
                    )

                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_context_pool_domain
                        ON jarvis_shared_context_pool(domain, created_at DESC)
                        WHERE domain IS NOT NULL
                        """
                    )

                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_context_pool_session
                        ON jarvis_shared_context_pool(session_id, created_at DESC)
                        WHERE session_id IS NOT NULL
                        """
                    )

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Context pool table creation failed", error=str(e))

    # ---------------------------------------------------------------------
    # Publish / Subscribe
    # ---------------------------------------------------------------------

    def publish_context(
        self,
        source_agent: str,
        context_key: str,
        context_value: Dict[str, Any],
        visibility: str = "domain",
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        ttl_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Publish a context fact to the shared context pool."""
        try:
            visibility_enum = ContextVisibility(visibility)
        except ValueError:
            return {"success": False, "error": f"Invalid visibility: {visibility}"}

        try:
            context_id = f"ctx_{uuid.uuid4().hex[:12]}"
            domain_value = domain or self._infer_domain(source_agent)
            expires_at = None
            if visibility_enum == ContextVisibility.TEMPORARY and ttl_minutes is None:
                ttl_minutes = 120
            if ttl_minutes and ttl_minutes > 0:
                expires_at = datetime.now() + timedelta(minutes=ttl_minutes)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_shared_context_pool
                        (context_id, source_agent, context_key, context_value, visibility,
                         domain, tags, metadata, session_id, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            context_id,
                            source_agent,
                            context_key,
                            json.dumps(context_value),
                            visibility_enum.value,
                            domain_value,
                            json.dumps(tags or []),
                            json.dumps(metadata or {}),
                            session_id,
                            expires_at,
                        ),
                    )
                    _ = cur.fetchone()
                    conn.commit()

            return {
                "success": True,
                "context_id": context_id,
                "visibility": visibility_enum.value,
                "domain": domain_value,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        except Exception as e:
            log_with_context(logger, "error", "publish_context failed", error=str(e))
            return {"success": False, "error": str(e)}

    def subscribe(
        self,
        agent_id: str,
        visibility_levels: Optional[List[str]] = None,
        domains: Optional[List[str]] = None,
        source_agents: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        include_temporary: bool = False,
    ) -> Dict[str, Any]:
        """Create or update an agent subscription profile."""
        levels = visibility_levels or [ContextVisibility.GLOBAL.value, ContextVisibility.DOMAIN.value]
        normalized = []
        for level in levels:
            try:
                normalized.append(ContextVisibility(level).value)
            except ValueError:
                return {"success": False, "error": f"Invalid visibility level: {level}"}

        try:
            subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_context_subscriptions
                        (subscription_id, agent_id, visibility_levels, domains,
                         source_agents, tags, include_temporary, active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT (agent_id)
                        DO UPDATE SET
                            visibility_levels = EXCLUDED.visibility_levels,
                            domains = EXCLUDED.domains,
                            source_agents = EXCLUDED.source_agents,
                            tags = EXCLUDED.tags,
                            include_temporary = EXCLUDED.include_temporary,
                            active = TRUE,
                            updated_at = NOW(),
                            subscription_id = EXCLUDED.subscription_id
                        RETURNING subscription_id
                        """,
                        (
                            subscription_id,
                            agent_id,
                            json.dumps(normalized),
                            json.dumps(domains or []),
                            json.dumps(source_agents or []),
                            json.dumps(tags or []),
                            include_temporary,
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()

            return {
                "success": True,
                "subscription_id": row[0] if row else subscription_id,
                "agent_id": agent_id,
                "visibility_levels": normalized,
            }
        except Exception as e:
            log_with_context(logger, "error", "subscribe failed", error=str(e))
            return {"success": False, "error": str(e)}

    def unsubscribe(self, agent_id: str) -> Dict[str, Any]:
        """Deactivate an agent subscription."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE jarvis_context_subscriptions
                        SET active = FALSE, updated_at = NOW()
                        WHERE agent_id = %s AND active = TRUE
                        RETURNING id
                        """,
                        (agent_id,),
                    )
                    row = cur.fetchone()
                    conn.commit()

            if not row:
                return {"success": False, "error": "No active subscription found"}
            return {"success": True, "agent_id": agent_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # Read / Filter
    # ---------------------------------------------------------------------

    def read_context(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        since_minutes: int = 1440,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Read context entries visible to an agent according to subscription and privacy boundaries."""
        subscription = self._get_subscription(agent_id)
        if not subscription:
            subscription = ContextSubscription(
                subscription_id="default",
                agent_id=agent_id,
                visibility_levels=[ContextVisibility.GLOBAL.value, ContextVisibility.DOMAIN.value],
                domains=[self._infer_domain(agent_id)],
                source_agents=[],
                tags=[],
                include_temporary=False,
            )

        try:
            since_ts = datetime.now() - timedelta(minutes=max(1, since_minutes))

            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT context_id, source_agent, context_key, context_value,
                           visibility, domain, tags, metadata, session_id,
                           expires_at, created_at
                    FROM jarvis_shared_context_pool
                    WHERE created_at >= %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (since_ts, max(1, limit * 3)),
                )
                rows = cur.fetchall()

            boundaries = self._get_boundaries_for_target(agent_id)
            visible = self._filter_entries(rows, agent_id, subscription, boundaries, session_id)

            return {
                "success": True,
                "agent_id": agent_id,
                "count": len(visible[:limit]),
                "entries": visible[:limit],
            }
        except Exception as e:
            log_with_context(logger, "error", "read_context failed", error=str(e))
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # Privacy Boundaries
    # ---------------------------------------------------------------------

    def set_privacy_boundary(
        self,
        source_agent: str,
        target_agent: str,
        allowed_levels: Optional[List[str]] = None,
        allowed_keys: Optional[List[str]] = None,
        denied_keys: Optional[List[str]] = None,
        active: bool = True,
    ) -> Dict[str, Any]:
        """Define explicit privacy boundary from source -> target."""
        levels = allowed_levels or [ContextVisibility.GLOBAL.value, ContextVisibility.DOMAIN.value]
        for level in levels:
            try:
                ContextVisibility(level)
            except ValueError:
                return {"success": False, "error": f"Invalid allowed level: {level}"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jarvis_context_privacy_boundaries
                        (source_agent, target_agent, allowed_levels, allowed_keys, denied_keys, active)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_agent, target_agent)
                        DO UPDATE SET
                            allowed_levels = EXCLUDED.allowed_levels,
                            allowed_keys = EXCLUDED.allowed_keys,
                            denied_keys = EXCLUDED.denied_keys,
                            active = EXCLUDED.active,
                            updated_at = NOW()
                        """,
                        (
                            source_agent,
                            target_agent,
                            json.dumps(levels),
                            json.dumps(allowed_keys or []),
                            json.dumps(denied_keys or []),
                            active,
                        ),
                    )
                    conn.commit()

            return {
                "success": True,
                "source_agent": source_agent,
                "target_agent": target_agent,
                "allowed_levels": levels,
                "active": active,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_privacy_boundaries(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return privacy boundaries, optionally filtered by agent."""
        try:
            with get_dict_cursor() as cur:
                if agent_id:
                    cur.execute(
                        """
                        SELECT source_agent, target_agent, allowed_levels, allowed_keys, denied_keys, active
                        FROM jarvis_context_privacy_boundaries
                        WHERE source_agent = %s OR target_agent = %s
                        ORDER BY source_agent, target_agent
                        """,
                        (agent_id, agent_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT source_agent, target_agent, allowed_levels, allowed_keys, denied_keys, active
                        FROM jarvis_context_privacy_boundaries
                        ORDER BY source_agent, target_agent
                        """
                    )
                rows = cur.fetchall()

            return {"success": True, "count": len(rows), "boundaries": rows}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_pool_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get usage metrics for context pool, subscriptions, and boundaries."""
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT visibility, COUNT(*) AS count
                    FROM jarvis_shared_context_pool
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY visibility
                    """,
                    (max(1, days),),
                )
                visibility_counts = {row["visibility"]: row["count"] for row in cur.fetchall()}

                cur.execute("SELECT COUNT(*) AS count FROM jarvis_context_subscriptions WHERE active = TRUE")
                active_subscriptions = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) AS count FROM jarvis_context_privacy_boundaries WHERE active = TRUE")
                active_boundaries = cur.fetchone()["count"]

            return {
                "success": True,
                "period_days": days,
                "visibility_counts": visibility_counts,
                "active_subscriptions": active_subscriptions,
                "active_boundaries": active_boundaries,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

    def _get_subscription(self, agent_id: str) -> Optional[ContextSubscription]:
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT subscription_id, visibility_levels, domains, source_agents, tags, include_temporary
                    FROM jarvis_context_subscriptions
                    WHERE agent_id = %s AND active = TRUE
                    LIMIT 1
                    """,
                    (agent_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return ContextSubscription(
                    subscription_id=row["subscription_id"],
                    agent_id=agent_id,
                    visibility_levels=row["visibility_levels"] or [],
                    domains=row["domains"] or [],
                    source_agents=row["source_agents"] or [],
                    tags=row["tags"] or [],
                    include_temporary=bool(row["include_temporary"]),
                )
        except Exception:
            return None

    def _get_boundaries_for_target(self, target_agent: str) -> Dict[str, Dict[str, Any]]:
        boundaries: Dict[str, Dict[str, Any]] = {}
        try:
            with get_dict_cursor() as cur:
                cur.execute(
                    """
                    SELECT source_agent, allowed_levels, allowed_keys, denied_keys
                    FROM jarvis_context_privacy_boundaries
                    WHERE target_agent = %s AND active = TRUE
                    """,
                    (target_agent,),
                )
                for row in cur.fetchall():
                    boundaries[row["source_agent"]] = {
                        "allowed_levels": row["allowed_levels"] or [],
                        "allowed_keys": row["allowed_keys"] or [],
                        "denied_keys": row["denied_keys"] or [],
                    }
        except Exception:
            return {}

        return boundaries

    def _filter_entries(
        self,
        rows: List[Dict[str, Any]],
        agent_id: str,
        subscription: ContextSubscription,
        boundaries: Dict[str, Dict[str, Any]],
        session_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        result = []
        viewer_domain = self._infer_domain(agent_id)

        for row in rows:
            if not self._entry_matches_subscription(row, subscription):
                continue

            if not self._visibility_allows(row, agent_id, viewer_domain, subscription, session_id):
                continue

            boundary = boundaries.get(row["source_agent"])
            if boundary and not self._boundary_allows(row, boundary):
                continue

            result.append(
                {
                    "context_id": row["context_id"],
                    "source_agent": row["source_agent"],
                    "context_key": row["context_key"],
                    "context_value": row["context_value"],
                    "visibility": row["visibility"],
                    "domain": row["domain"],
                    "tags": row["tags"] or [],
                    "metadata": row["metadata"] or {},
                    "session_id": row["session_id"],
                    "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )

        return result

    def _entry_matches_subscription(self, row: Dict[str, Any], subscription: ContextSubscription) -> bool:
        if subscription.source_agents and row["source_agent"] not in subscription.source_agents:
            return False

        if subscription.domains and row.get("domain") and row["domain"] not in subscription.domains:
            return False

        if subscription.tags:
            row_tags = set(row.get("tags") or [])
            if row_tags.isdisjoint(set(subscription.tags)):
                return False

        return True

    def _visibility_allows(
        self,
        row: Dict[str, Any],
        agent_id: str,
        viewer_domain: str,
        subscription: ContextSubscription,
        session_id: Optional[str],
    ) -> bool:
        source = row["source_agent"]
        visibility = row["visibility"]

        if source == agent_id:
            return True

        if visibility == ContextVisibility.PRIVATE.value:
            return False

        if visibility not in subscription.visibility_levels:
            return False

        if visibility == ContextVisibility.GLOBAL.value:
            return True

        if visibility == ContextVisibility.DOMAIN.value:
            return row.get("domain") == viewer_domain

        if visibility == ContextVisibility.TEMPORARY.value:
            if not subscription.include_temporary:
                return False
            if not session_id:
                return False
            return row.get("session_id") == session_id

        return False

    def _boundary_allows(self, row: Dict[str, Any], boundary: Dict[str, Any]) -> bool:
        level = row["visibility"]
        key = row["context_key"]

        allowed_levels = boundary.get("allowed_levels") or []
        if allowed_levels and level not in allowed_levels:
            return False

        denied_keys = boundary.get("denied_keys") or []
        if key in denied_keys:
            return False

        allowed_keys = boundary.get("allowed_keys") or []
        if allowed_keys and key not in allowed_keys:
            return False

        return True

    def _infer_domain(self, agent_id: str) -> str:
        lowered = (agent_id or "").lower()
        if "fit" in lowered:
            return "fitness"
        if "work" in lowered:
            return "work"
        if "comm" in lowered:
            return "communication"
        if "saas" in lowered:
            return "saas"
        return "general"


_service: Optional[AgentContextPoolService] = None


def get_agent_context_pool_service() -> AgentContextPoolService:
    global _service
    if _service is None:
        _service = AgentContextPoolService()
    return _service
