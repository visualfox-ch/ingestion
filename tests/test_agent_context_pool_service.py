from app.services.agent_context_pool_service import (
    AgentContextPoolService,
    ContextSubscription,
    ContextVisibility,
)


def _service_no_db() -> AgentContextPoolService:
    # Bypass DB setup for pure logic tests.
    return AgentContextPoolService.__new__(AgentContextPoolService)


def _subscription(**overrides) -> ContextSubscription:
    base = ContextSubscription(
        subscription_id="sub_1",
        agent_id="work_jarvis",
        visibility_levels=[ContextVisibility.GLOBAL.value, ContextVisibility.DOMAIN.value],
        domains=["work"],
        source_agents=[],
        tags=[],
        include_temporary=False,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_visibility_allows_global_and_same_domain():
    service = _service_no_db()
    sub = _subscription()

    global_row = {
        "source_agent": "fit_jarvis",
        "visibility": "global",
        "domain": "fitness",
        "session_id": None,
    }
    assert service._visibility_allows(global_row, "work_jarvis", "work", sub, None)

    domain_row = {
        "source_agent": "other_work_agent",
        "visibility": "domain",
        "domain": "work",
        "session_id": None,
    }
    assert service._visibility_allows(domain_row, "work_jarvis", "work", sub, None)


def test_visibility_blocks_private_and_other_domain():
    service = _service_no_db()
    sub = _subscription()

    private_row = {
        "source_agent": "fit_jarvis",
        "visibility": "private",
        "domain": "fitness",
        "session_id": None,
    }
    assert not service._visibility_allows(private_row, "work_jarvis", "work", sub, None)

    other_domain_row = {
        "source_agent": "fit_jarvis",
        "visibility": "domain",
        "domain": "fitness",
        "session_id": None,
    }
    assert not service._visibility_allows(other_domain_row, "work_jarvis", "work", sub, None)


def test_visibility_temporary_requires_opt_in_and_session_match():
    service = _service_no_db()
    sub = _subscription(include_temporary=True, visibility_levels=["global", "domain", "temporary"])

    row = {
        "source_agent": "fit_jarvis",
        "visibility": "temporary",
        "domain": "fitness",
        "session_id": "sess-1",
    }
    assert service._visibility_allows(row, "work_jarvis", "work", sub, "sess-1")
    assert not service._visibility_allows(row, "work_jarvis", "work", sub, "sess-2")


def test_entry_matches_subscription_filters_source_domain_and_tags():
    service = _service_no_db()
    sub = _subscription(source_agents=["fit_jarvis"], domains=["fitness"], tags=["energy"])

    row_ok = {
        "source_agent": "fit_jarvis",
        "domain": "fitness",
        "tags": ["energy", "morning"],
    }
    assert service._entry_matches_subscription(row_ok, sub)

    row_bad_source = {"source_agent": "work_jarvis", "domain": "fitness", "tags": ["energy"]}
    assert not service._entry_matches_subscription(row_bad_source, sub)

    row_bad_domain = {"source_agent": "fit_jarvis", "domain": "work", "tags": ["energy"]}
    assert not service._entry_matches_subscription(row_bad_domain, sub)

    row_bad_tag = {"source_agent": "fit_jarvis", "domain": "fitness", "tags": ["sleep"]}
    assert not service._entry_matches_subscription(row_bad_tag, sub)


def test_boundary_allows_and_denies_keys_and_levels():
    service = _service_no_db()

    row = {"visibility": "domain", "context_key": "energy_state"}
    boundary = {
        "allowed_levels": ["domain", "global"],
        "allowed_keys": ["energy_state", "fatigue_score"],
        "denied_keys": [],
    }
    assert service._boundary_allows(row, boundary)

    denied_key = {
        "allowed_levels": ["domain", "global"],
        "allowed_keys": [],
        "denied_keys": ["energy_state"],
    }
    assert not service._boundary_allows(row, denied_key)

    denied_level = {
        "allowed_levels": ["global"],
        "allowed_keys": [],
        "denied_keys": [],
    }
    assert not service._boundary_allows(row, denied_level)


def test_infer_domain_mapping():
    service = _service_no_db()

    assert service._infer_domain("fit_jarvis") == "fitness"
    assert service._infer_domain("work_jarvis") == "work"
    assert service._infer_domain("comm_jarvis") == "communication"
    assert service._infer_domain("saas_jarvis") == "saas"
    assert service._infer_domain("jarvis_core") == "general"
