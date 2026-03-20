"""
Agent Coordination Tools.

Extracted from tools.py - manages multi-agent coordination, delegation,
message queues, consensus voting, agent lifecycle, specialist agents,
fitness/work/comm agents, and context sharing.

Phase 22A-22B tools for the multi-agent system.
"""
from typing import Dict, Any, List, Callable
from datetime import datetime, timedelta

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.agent_coordination")


def tool_set_agent_state(
    agent_id: str,
    state_key: str,
    state_value: Any,
    expires_in_hours: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Store persistent agent state."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: set_agent_state",
                    agent=agent_id, key=state_key)
    metrics.inc("tool_set_agent_state")

    try:
        from app.services.agent_state_persistence import get_agent_state_persistence
        persistence = get_agent_state_persistence()
        return persistence.set_state(agent_id, user_id, state_key, state_value, expires_in_hours)
    except Exception as e:
        log_with_context(logger, "error", "set_agent_state failed", error=str(e))
        return {"error": str(e)}


def tool_get_agent_state(
    agent_id: str,
    state_key: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Retrieve agent state."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: get_agent_state",
                    agent=agent_id, key=state_key)
    metrics.inc("tool_get_agent_state")

    try:
        from app.services.agent_state_persistence import get_agent_state_persistence
        persistence = get_agent_state_persistence()
        result = persistence.get_state(agent_id, user_id, state_key)
        return result if result else {"message": "No state found"}
    except Exception as e:
        log_with_context(logger, "error", "get_agent_state failed", error=str(e))
        return {"error": str(e)}


def tool_create_agent_handoff(
    from_agent: str,
    to_agent: str,
    context: Dict[str, Any],
    files_involved: List[str] = None,
    reason: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Create an agent handoff."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: create_agent_handoff",
                    from_agent=from_agent, to_agent=to_agent)
    metrics.inc("tool_create_agent_handoff")

    try:
        from app.services.agent_state_persistence import get_agent_state_persistence
        persistence = get_agent_state_persistence()
        return persistence.create_handoff(from_agent, to_agent, user_id, context, files_involved, reason)
    except Exception as e:
        log_with_context(logger, "error", "create_agent_handoff failed", error=str(e))
        return {"error": str(e)}


def tool_get_pending_handoffs(
    agent_id: str,
    **kwargs
) -> Dict[str, Any]:
    """Get pending handoffs for an agent."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: get_pending_handoffs", agent=agent_id)
    metrics.inc("tool_get_pending_handoffs")

    try:
        from app.services.agent_state_persistence import get_agent_state_persistence
        persistence = get_agent_state_persistence()
        handoffs = persistence.get_pending_handoffs(agent_id, user_id)
        return {"handoffs": handoffs, "count": len(handoffs)}
    except Exception as e:
        log_with_context(logger, "error", "get_pending_handoffs failed", error=str(e))
        return {"error": str(e)}


def tool_get_agent_stats(
    agent_id: str = None,
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """Get agent usage statistics."""
    log_with_context(logger, "info", "Tool: get_agent_stats", agent=agent_id, days=days)
    metrics.inc("tool_get_agent_stats")

    try:
        from app.services.agent_state_persistence import get_agent_state_persistence
        persistence = get_agent_state_persistence()
        return persistence.get_agent_stats(agent_id, days)
    except Exception as e:
        log_with_context(logger, "error", "get_agent_stats failed", error=str(e))
        return {"error": str(e)}


# ============ Phase 22 Tool Implementations ============

def tool_list_specialist_agents(domain: str = None, active_only: bool = True) -> Dict[str, Any]:
    """List registered specialist agents."""
    try:
        from app.services.specialist_agent_service import get_specialist_registry, AgentDomain
        registry = get_specialist_registry()
        domain_enum = AgentDomain(domain) if domain else None
        return {"agents": registry.list_agents(domain=domain_enum, active_only=active_only)}
    except Exception as e:
        log_with_context(logger, "error", "list_specialist_agents failed", error=str(e))
        return {"error": str(e)}


def tool_get_specialist_routing(query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """Route a query to the most appropriate specialist."""
    try:
        from app.services.specialist_agent_service import get_specialist_registry
        registry = get_specialist_registry()
        return registry.route_query(query, user_id="micha", context=context)
    except Exception as e:
        log_with_context(logger, "error", "get_specialist_routing failed", error=str(e))
        return {"error": str(e)}


def tool_generalize_pattern(cause: str, effect: str, domain: str) -> Dict[str, Any]:
    """Extract domain-agnostic patterns from cause-effect observations."""
    try:
        from app.services.pattern_generalization_service import get_pattern_generalization_service
        service = get_pattern_generalization_service()
        return service.generalize_pattern(user_id="micha", cause=cause, effect=effect, domain=domain)
    except Exception as e:
        log_with_context(logger, "error", "generalize_pattern failed", error=str(e))
        return {"error": str(e)}


def tool_find_transfer_candidates(target_domain: str, min_confidence: float = 0.6, limit: int = 10) -> Dict[str, Any]:
    """Find patterns that could be transferred to a new domain."""
    try:
        from app.services.pattern_generalization_service import get_pattern_generalization_service
        service = get_pattern_generalization_service()
        candidates = service.find_transfer_candidates(domain=target_domain, min_confidence=min_confidence, limit=limit)
        return {"target_domain": target_domain, "candidates": candidates, "count": len(candidates)}
    except Exception as e:
        log_with_context(logger, "error", "find_transfer_candidates failed", error=str(e))
        return {"error": str(e)}


def tool_get_cross_domain_insights() -> Dict[str, Any]:
    """Get insights about cross-domain pattern learning."""
    try:
        from app.services.pattern_generalization_service import get_pattern_generalization_service
        service = get_pattern_generalization_service()
        return service.get_cross_domain_insights()
    except Exception as e:
        log_with_context(logger, "error", "get_cross_domain_insights failed", error=str(e))
        return {"error": str(e)}


def tool_get_pattern_generalization_stats() -> Dict[str, Any]:
    """Get statistics about pattern generalization."""
    try:
        from app.services.pattern_generalization_service import get_pattern_generalization_service
        service = get_pattern_generalization_service()
        return service.get_pattern_stats()
    except Exception as e:
        log_with_context(logger, "error", "get_pattern_generalization_stats failed", error=str(e))
        return {"error": str(e)}


# ============ Phase 22A-02: Agent Registry & Lifecycle ============

def tool_register_agent(
    agent_id: str,
    domain: str,
    display_name: str = None,
    tools: List[str] = None,
    identity_extension: Dict[str, Any] = None,
    confidence_threshold: float = 0.7,
    dependencies: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Register a new specialist agent."""
    log_with_context(logger, "info", "Tool: register_agent", agent_id=agent_id, domain=domain)
    metrics.inc("tool_register_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.register_agent(
            agent_id=agent_id,
            domain=domain,
            display_name=display_name,
            tools=tools,
            identity_extension=identity_extension,
            confidence_threshold=confidence_threshold,
            dependencies=dependencies
        )
    except Exception as e:
        log_with_context(logger, "error", "register_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_deregister_agent(agent_id: str, force: bool = False, **kwargs) -> Dict[str, Any]:
    """Remove an agent from the registry."""
    log_with_context(logger, "info", "Tool: deregister_agent", agent_id=agent_id)
    metrics.inc("tool_deregister_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.deregister_agent(agent_id, force=force)
    except Exception as e:
        log_with_context(logger, "error", "deregister_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_start_agent(agent_id: str, **kwargs) -> Dict[str, Any]:
    """Start a registered agent."""
    log_with_context(logger, "info", "Tool: start_agent", agent_id=agent_id)
    metrics.inc("tool_start_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.start_agent(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "start_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_stop_agent(agent_id: str, stop_dependents: bool = False, **kwargs) -> Dict[str, Any]:
    """Stop an active agent."""
    log_with_context(logger, "info", "Tool: stop_agent", agent_id=agent_id)
    metrics.inc("tool_stop_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.stop_agent(agent_id, stop_dependents=stop_dependents)
    except Exception as e:
        log_with_context(logger, "error", "stop_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_pause_agent(agent_id: str, **kwargs) -> Dict[str, Any]:
    """Pause an active agent."""
    log_with_context(logger, "info", "Tool: pause_agent", agent_id=agent_id)
    metrics.inc("tool_pause_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.pause_agent(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "pause_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_resume_agent(agent_id: str, **kwargs) -> Dict[str, Any]:
    """Resume a paused agent."""
    log_with_context(logger, "info", "Tool: resume_agent", agent_id=agent_id)
    metrics.inc("tool_resume_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.resume_agent(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "resume_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_reset_agent(agent_id: str, **kwargs) -> Dict[str, Any]:
    """Reset an agent from error state."""
    log_with_context(logger, "info", "Tool: reset_agent", agent_id=agent_id)
    metrics.inc("tool_reset_agent")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.reset_agent(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "reset_agent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_agent_health_check(agent_id: str = None, **kwargs) -> Dict[str, Any]:
    """Run health check on one or all agents."""
    log_with_context(logger, "info", "Tool: agent_health_check", agent_id=agent_id)
    metrics.inc("tool_agent_health_check")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.health_check(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "agent_health_check failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_update_agent_config(
    agent_id: str,
    tools: List[str] = None,
    identity_extension: Dict[str, Any] = None,
    confidence_threshold: float = None,
    **kwargs
) -> Dict[str, Any]:
    """Update agent configuration at runtime."""
    log_with_context(logger, "info", "Tool: update_agent_config", agent_id=agent_id)
    metrics.inc("tool_update_agent_config")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.update_config(
            agent_id=agent_id,
            tools=tools,
            identity_extension=identity_extension,
            confidence_threshold=confidence_threshold
        )
    except Exception as e:
        log_with_context(logger, "error", "update_agent_config failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_agent_registry_stats(**kwargs) -> Dict[str, Any]:
    """Get overall registry statistics."""
    log_with_context(logger, "info", "Tool: get_agent_registry_stats")
    metrics.inc("tool_get_agent_registry_stats")

    try:
        from app.services.agent_registry_service import get_agent_registry_service
        service = get_agent_registry_service()
        return service.get_registry_stats()
    except Exception as e:
        log_with_context(logger, "error", "get_agent_registry_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-03: Agent Context Isolation ============

def tool_create_agent_context(
    agent_id: str,
    session_id: str,
    allowed_tools: List[str] = None,
    blocked_tools: List[str] = None,
    ttl_minutes: int = 60,
    **kwargs
) -> Dict[str, Any]:
    """Create an isolated execution context for an agent."""
    log_with_context(logger, "info", "Tool: create_agent_context", agent_id=agent_id)
    metrics.inc("tool_create_agent_context")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        context = service.create_context(
            agent_id=agent_id,
            session_id=session_id,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            ttl_minutes=ttl_minutes
        )
        return {"success": True, "context": context.to_dict()}
    except Exception as e:
        log_with_context(logger, "error", "create_agent_context failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_agent_context(agent_id: str, session_id: str, **kwargs) -> Dict[str, Any]:
    """Get the current isolated context for an agent session."""
    log_with_context(logger, "info", "Tool: get_agent_context", agent_id=agent_id)
    metrics.inc("tool_get_agent_context")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        context = service.get_context(agent_id, session_id)
        if context:
            return {"success": True, "context": context.to_dict()}
        return {"success": False, "error": "No active context found"}
    except Exception as e:
        log_with_context(logger, "error", "get_agent_context failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_store_agent_memory(
    agent_id: str,
    key: str,
    value: Any,
    memory_type: str = "fact",
    sharing_policy: str = "private",
    **kwargs
) -> Dict[str, Any]:
    """Store a memory in the agent's isolated namespace."""
    log_with_context(logger, "info", "Tool: store_agent_memory", agent_id=agent_id, key=key)
    metrics.inc("tool_store_agent_memory")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service, SharingPolicy
        service = get_agent_context_isolation_service()
        policy = SharingPolicy(sharing_policy) if sharing_policy else SharingPolicy.PRIVATE
        return service.store_memory(
            agent_id=agent_id,
            key=key,
            value=value,
            memory_type=memory_type,
            sharing_policy=policy
        )
    except Exception as e:
        log_with_context(logger, "error", "store_agent_memory failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_recall_agent_memory(
    agent_id: str,
    key: str = None,
    memory_type: str = None,
    include_shared: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """Recall memories from the agent's isolated namespace."""
    log_with_context(logger, "info", "Tool: recall_agent_memory", agent_id=agent_id)
    metrics.inc("tool_recall_agent_memory")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        memories = service.recall_memory(
            agent_id=agent_id,
            key=key,
            memory_type=memory_type,
            include_shared=include_shared
        )
        return {"success": True, "memories": memories, "count": len(memories)}
    except Exception as e:
        log_with_context(logger, "error", "recall_agent_memory failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_set_agent_boundary(
    source_agent: str,
    target_agent: str,
    data_types: List[str] = None,
    direction: str = "read",
    **kwargs
) -> Dict[str, Any]:
    """Set a data sharing boundary between two agents."""
    log_with_context(logger, "info", "Tool: set_agent_boundary",
                    source=source_agent, target=target_agent)
    metrics.inc("tool_set_agent_boundary")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        return service.set_boundary(
            source_agent=source_agent,
            target_agent=target_agent,
            data_types=data_types or [],
            direction=direction
        )
    except Exception as e:
        log_with_context(logger, "error", "set_agent_boundary failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_agent_boundaries(agent_id: str, **kwargs) -> Dict[str, Any]:
    """Get all data sharing boundaries for an agent."""
    log_with_context(logger, "info", "Tool: get_agent_boundaries", agent_id=agent_id)
    metrics.inc("tool_get_agent_boundaries")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        return service.get_boundaries(agent_id)
    except Exception as e:
        log_with_context(logger, "error", "get_agent_boundaries failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_check_tool_access(
    agent_id: str,
    session_id: str,
    tool_name: str,
    **kwargs
) -> Dict[str, Any]:
    """Check if an agent is allowed to use a specific tool."""
    log_with_context(logger, "info", "Tool: check_tool_access",
                    agent_id=agent_id, tool=tool_name)
    metrics.inc("tool_check_tool_access")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        allowed = service.can_use_tool(agent_id, session_id, tool_name)
        return {"success": True, "agent_id": agent_id, "tool": tool_name, "allowed": allowed}
    except Exception as e:
        log_with_context(logger, "error", "check_tool_access failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_isolation_stats(**kwargs) -> Dict[str, Any]:
    """Get statistics about agent context isolation."""
    log_with_context(logger, "info", "Tool: get_isolation_stats")
    metrics.inc("tool_get_isolation_stats")

    try:
        from app.services.agent_context_isolation import get_agent_context_isolation_service
        service = get_agent_context_isolation_service()
        return service.get_isolation_stats()
    except Exception as e:
        log_with_context(logger, "error", "get_isolation_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-04: FitJarvis (Fitness Agent) ============

def tool_log_workout(
    workout_type: str,
    activity: str,
    duration_minutes: int = None,
    intensity: str = "moderate",
    calories_burned: int = None,
    distance_km: float = None,
    sets_reps: List[Dict[str, Any]] = None,
    notes: str = None,
    mood_before: str = None,
    mood_after: str = None,
    energy_level: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Log a workout session."""
    log_with_context(logger, "info", "Tool: log_workout", workout_type=workout_type, activity=activity)
    metrics.inc("tool_log_workout")

    try:
        from app.services.fitness_agent_service import get_fitness_agent_service
        service = get_fitness_agent_service()
        return service.log_workout(
            workout_type=workout_type,
            activity=activity,
            duration_minutes=duration_minutes,
            intensity=intensity,
            calories_burned=calories_burned,
            distance_km=distance_km,
            sets_reps=sets_reps,
            notes=notes,
            mood_before=mood_before,
            mood_after=mood_after,
            energy_level=energy_level
        )
    except Exception as e:
        log_with_context(logger, "error", "log_workout failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_fitness_trends(
    period: str = "week",
    trend_type: str = "all",
    **kwargs
) -> Dict[str, Any]:
    """Get fitness trends and analytics."""
    log_with_context(logger, "info", "Tool: get_fitness_trends", period=period)
    metrics.inc("tool_get_fitness_trends")

    try:
        from app.services.fitness_agent_service import get_fitness_agent_service
        service = get_fitness_agent_service()
        return service.get_fitness_trends(period=period, trend_type=trend_type)
    except Exception as e:
        log_with_context(logger, "error", "get_fitness_trends failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_track_nutrition(
    meal_type: str,
    food_items: List[Dict[str, Any]],
    notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Track a meal with nutritional info."""
    log_with_context(logger, "info", "Tool: track_nutrition", meal_type=meal_type)
    metrics.inc("tool_track_nutrition")

    try:
        from app.services.fitness_agent_service import get_fitness_agent_service
        service = get_fitness_agent_service()
        return service.track_nutrition(
            meal_type=meal_type,
            food_items=food_items,
            notes=notes
        )
    except Exception as e:
        log_with_context(logger, "error", "track_nutrition failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_suggest_exercise(
    category: str = None,
    muscle_groups: List[str] = None,
    difficulty: str = None,
    equipment: List[str] = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Get personalized exercise suggestions."""
    log_with_context(logger, "info", "Tool: suggest_exercise", category=category)
    metrics.inc("tool_suggest_exercise")

    try:
        from app.services.fitness_agent_service import get_fitness_agent_service
        service = get_fitness_agent_service()
        return service.suggest_exercise(
            category=category,
            muscle_groups=muscle_groups,
            difficulty=difficulty,
            equipment=equipment,
            limit=limit
        )
    except Exception as e:
        log_with_context(logger, "error", "suggest_exercise failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_fitness_stats(**kwargs) -> Dict[str, Any]:
    """Get overall fitness statistics."""
    log_with_context(logger, "info", "Tool: get_fitness_stats")
    metrics.inc("tool_get_fitness_stats")

    try:
        from app.services.fitness_agent_service import get_fitness_agent_service
        service = get_fitness_agent_service()
        return service.get_fitness_stats()
    except Exception as e:
        log_with_context(logger, "error", "get_fitness_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-05: WorkJarvis (Work Agent) ============

def tool_prioritize_tasks(
    tasks: List[Dict[str, Any]] = None,
    context: str = None,
    available_minutes: int = None,
    energy_level: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Prioritize tasks using Eisenhower matrix."""
    log_with_context(logger, "info", "Tool: prioritize_tasks")
    metrics.inc("tool_prioritize_tasks")

    try:
        from app.services.work_agent_service import get_work_agent_service
        service = get_work_agent_service()
        return service.prioritize_tasks(
            tasks=tasks,
            context=context,
            available_minutes=available_minutes,
            energy_level=energy_level
        )
    except Exception as e:
        log_with_context(logger, "error", "prioritize_tasks failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_estimate_effort(
    task_description: str,
    task_type: str = "general",
    complexity: str = "moderate",
    **kwargs
) -> Dict[str, Any]:
    """Estimate effort for a task."""
    log_with_context(logger, "info", "Tool: estimate_effort", task_type=task_type)
    metrics.inc("tool_estimate_effort")

    try:
        from app.services.work_agent_service import get_work_agent_service
        service = get_work_agent_service()
        return service.estimate_effort(
            task_description=task_description,
            task_type=task_type,
            complexity=complexity
        )
    except Exception as e:
        log_with_context(logger, "error", "estimate_effort failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_track_focus_time(
    action: str = "status",
    task_title: str = None,
    project: str = None,
    planned_minutes: int = 25,
    category: str = "deep_work",
    focus_quality: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Track focus sessions."""
    log_with_context(logger, "info", "Tool: track_focus_time", action=action)
    metrics.inc("tool_track_focus_time")

    try:
        from app.services.work_agent_service import get_work_agent_service
        service = get_work_agent_service()
        return service.track_focus_time(
            action=action,
            task_title=task_title,
            project=project,
            planned_minutes=planned_minutes,
            category=category,
            focus_quality=focus_quality
        )
    except Exception as e:
        log_with_context(logger, "error", "track_focus_time failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_suggest_breaks(
    current_focus_minutes: int = None,
    energy_level: int = None,
    last_break_minutes_ago: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Get break suggestions."""
    log_with_context(logger, "info", "Tool: suggest_breaks")
    metrics.inc("tool_suggest_breaks")

    try:
        from app.services.work_agent_service import get_work_agent_service
        service = get_work_agent_service()
        return service.suggest_breaks(
            current_focus_minutes=current_focus_minutes,
            energy_level=energy_level,
            last_break_minutes_ago=last_break_minutes_ago
        )
    except Exception as e:
        log_with_context(logger, "error", "suggest_breaks failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_work_stats(period: str = "today", **kwargs) -> Dict[str, Any]:
    """Get work/productivity statistics."""
    log_with_context(logger, "info", "Tool: get_work_stats", period=period)
    metrics.inc("tool_get_work_stats")

    try:
        from app.services.work_agent_service import get_work_agent_service
        service = get_work_agent_service()
        return service.get_work_stats(period=period)
    except Exception as e:
        log_with_context(logger, "error", "get_work_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-06: CommJarvis (Communication Agent) ============

def tool_triage_inbox(
    messages: List[Dict[str, Any]] = None,
    source: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """Triage inbox messages by priority."""
    log_with_context(logger, "info", "Tool: triage_inbox")
    metrics.inc("tool_triage_inbox")

    try:
        from app.services.comm_agent_service import get_comm_agent_service
        service = get_comm_agent_service()
        return service.triage_inbox(messages=messages, source=source, limit=limit)
    except Exception as e:
        log_with_context(logger, "error", "triage_inbox failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_draft_response(
    to: str,
    context: str,
    tone: str = "friendly",
    **kwargs
) -> Dict[str, Any]:
    """Draft a response with relationship context."""
    log_with_context(logger, "info", "Tool: draft_response", to=to)
    metrics.inc("tool_draft_response")

    try:
        from app.services.comm_agent_service import get_comm_agent_service
        service = get_comm_agent_service()
        return service.draft_response(to=to, context=context, tone=tone)
    except Exception as e:
        log_with_context(logger, "error", "draft_response failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_track_relationship(
    action: str = "list",
    contact_name: str = None,
    contact_email: str = None,
    relationship_type: str = None,
    company: str = None,
    importance: int = None,
    notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Track and manage relationships."""
    log_with_context(logger, "info", "Tool: track_relationship", action=action)
    metrics.inc("tool_track_relationship")

    try:
        from app.services.comm_agent_service import get_comm_agent_service
        service = get_comm_agent_service()
        return service.track_relationship(
            action=action,
            contact_name=contact_name,
            contact_email=contact_email,
            relationship_type=relationship_type,
            company=company,
            importance=importance,
            notes=notes
        )
    except Exception as e:
        log_with_context(logger, "error", "track_relationship failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_schedule_followup(
    contact_name: str,
    reason: str,
    due_date: str,
    followup_type: str = "check_in",
    channel: str = "email",
    **kwargs
) -> Dict[str, Any]:
    """Schedule a followup with a contact."""
    log_with_context(logger, "info", "Tool: schedule_followup", contact=contact_name)
    metrics.inc("tool_schedule_followup")

    try:
        from app.services.comm_agent_service import get_comm_agent_service
        service = get_comm_agent_service()
        return service.schedule_followup(
            contact_name=contact_name,
            reason=reason,
            due_date=due_date,
            followup_type=followup_type,
            channel=channel
        )
    except Exception as e:
        log_with_context(logger, "error", "schedule_followup failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_comm_stats(period: str = "week", **kwargs) -> Dict[str, Any]:
    """Get communication statistics."""
    log_with_context(logger, "info", "Tool: get_comm_stats", period=period)
    metrics.inc("tool_get_comm_stats")

    try:
        from app.services.comm_agent_service import get_comm_agent_service
        service = get_comm_agent_service()
        return service.get_comm_stats(period=period)
    except Exception as e:
        log_with_context(logger, "error", "get_comm_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-07: Intent-Based Agent Routing Tools ============

def tool_route_query(
    query: str,
    context: Dict[str, Any] = None,
    force_agent: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Route a query to the appropriate specialist agent."""
    log_with_context(logger, "info", "Tool: route_query", query_len=len(query))
    metrics.inc("tool_route_query")

    try:
        from app.services.agent_routing_service import get_agent_routing_service
        service = get_agent_routing_service()
        decision = service.route_query(query, context, force_agent)

        return {
            "success": True,
            "strategy": decision.strategy,
            "primary_agent": decision.primary_agent,
            "secondary_agents": decision.secondary_agents,
            "confidence": decision.confidence,
            "reasoning": decision.intent_classification.reasoning,
            "domain_scores": decision.intent_classification.confidence_scores,
            "detected_intents": decision.intent_classification.detected_intents,
            "requires_multi_agent": decision.intent_classification.requires_multi_agent
        }
    except Exception as e:
        log_with_context(logger, "error", "route_query failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_classify_intent(
    query: str,
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Classify query intent and get confidence scores."""
    log_with_context(logger, "info", "Tool: classify_intent", query_len=len(query))
    metrics.inc("tool_classify_intent")

    try:
        from app.services.agent_routing_service import get_agent_routing_service
        service = get_agent_routing_service()
        classification = service.classify_intent(query, context)

        return {
            "success": True,
            "primary_domain": classification.primary_domain.value,
            "confidence_scores": classification.confidence_scores,
            "detected_intents": classification.detected_intents,
            "keywords_matched": classification.keywords_matched,
            "requires_multi_agent": classification.requires_multi_agent,
            "reasoning": classification.reasoning
        }
    except Exception as e:
        log_with_context(logger, "error", "classify_intent failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_test_routing(queries: List[str], **kwargs) -> Dict[str, Any]:
    """Test routing for multiple queries (debugging)."""
    log_with_context(logger, "info", "Tool: test_routing", count=len(queries))
    metrics.inc("tool_test_routing")

    try:
        from app.services.agent_routing_service import get_agent_routing_service
        service = get_agent_routing_service()
        results = service.test_routing(queries)

        return {
            "success": True,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        log_with_context(logger, "error", "test_routing failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_routing_stats(days: int = 7, **kwargs) -> Dict[str, Any]:
    """Get routing statistics."""
    log_with_context(logger, "info", "Tool: get_routing_stats", days=days)
    metrics.inc("tool_get_routing_stats")

    try:
        from app.services.agent_routing_service import get_agent_routing_service
        service = get_agent_routing_service()
        return service.get_routing_stats(days=days)
    except Exception as e:
        log_with_context(logger, "error", "get_routing_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-08: Multi-Agent Collaboration Tools ============

def tool_execute_collaboration(
    query: str,
    agents: List[str],
    collaboration_type: str = "parallel",
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Execute multi-agent collaboration."""
    log_with_context(logger, "info", "Tool: execute_collaboration", agents=agents)
    metrics.inc("tool_execute_collaboration")

    try:
        from app.services.multi_agent_collaboration import (
            execute_collaboration_sync, CollaborationType
        )

        collab_type = CollaborationType(collaboration_type)
        return execute_collaboration_sync(
            query=query,
            agents=agents,
            collaboration_type=collab_type,
            context=context or {}
        )
    except Exception as e:
        log_with_context(logger, "error", "execute_collaboration failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_collaboration_stats(days: int = 7, **kwargs) -> Dict[str, Any]:
    """Get collaboration statistics."""
    log_with_context(logger, "info", "Tool: get_collaboration_stats", days=days)
    metrics.inc("tool_get_collaboration_stats")

    try:
        from app.services.multi_agent_collaboration import get_multi_agent_collaboration_service
        service = get_multi_agent_collaboration_service()
        return service.get_collaboration_stats(days=days)
    except Exception as e:
        log_with_context(logger, "error", "get_collaboration_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22A-09: Agent Delegation Tools ============

def tool_delegate_task(
    query: str,
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Delegate a complex task to specialist agents."""
    log_with_context(logger, "info", "Tool: delegate_task", query_len=len(query))
    metrics.inc("tool_delegate_task")

    try:
        from app.services.agent_delegation_service import get_agent_delegation_service
        service = get_agent_delegation_service()
        return service.delegate_all(query, context or {})
    except Exception as e:
        log_with_context(logger, "error", "delegate_task failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_delegation_status(session_id: int, **kwargs) -> Dict[str, Any]:
    """Get status of a delegation session."""
    log_with_context(logger, "info", "Tool: get_delegation_status", session_id=session_id)
    metrics.inc("tool_get_delegation_status")

    try:
        from app.services.agent_delegation_service import get_agent_delegation_service
        service = get_agent_delegation_service()
        return service.get_session_status(session_id)
    except Exception as e:
        log_with_context(logger, "error", "get_delegation_status failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_delegation_stats(days: int = 7, **kwargs) -> Dict[str, Any]:
    """Get delegation statistics."""
    log_with_context(logger, "info", "Tool: get_delegation_stats", days=days)
    metrics.inc("tool_get_delegation_stats")

    try:
        from app.services.agent_delegation_service import get_agent_delegation_service
        service = get_agent_delegation_service()
        return service.get_delegation_stats(days=days)
    except Exception as e:
        log_with_context(logger, "error", "get_delegation_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22B-02: Message Queue Tools ============

def tool_enqueue_message(
    queue_name: str,
    payload: Dict[str, Any],
    priority: str = "normal",
    delay_seconds: int = 0,
    **kwargs
) -> Dict[str, Any]:
    """Enqueue a message for async processing."""
    log_with_context(logger, "info", "Tool: enqueue_message", queue=queue_name)
    metrics.inc("tool_enqueue_message")

    try:
        from app.services.message_queue_service import get_message_queue_service
        service = get_message_queue_service()
        return service.enqueue(queue_name, payload, priority, delay_seconds)
    except Exception as e:
        log_with_context(logger, "error", "enqueue_message failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_dequeue_message(
    queue_name: str,
    limit: int = 1,
    **kwargs
) -> Dict[str, Any]:
    """Dequeue messages for processing."""
    log_with_context(logger, "info", "Tool: dequeue_message", queue=queue_name)
    metrics.inc("tool_dequeue_message")

    try:
        from app.services.message_queue_service import get_message_queue_service
        service = get_message_queue_service()
        return service.dequeue(queue_name, limit=limit)
    except Exception as e:
        log_with_context(logger, "error", "dequeue_message failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_queue_stats(queue_name: str = None, **kwargs) -> Dict[str, Any]:
    """Get message queue statistics."""
    log_with_context(logger, "info", "Tool: get_queue_stats", queue=queue_name)
    metrics.inc("tool_get_queue_stats")

    try:
        from app.services.message_queue_service import get_message_queue_service
        service = get_message_queue_service()
        return service.get_queue_stats(queue_name)
    except Exception as e:
        log_with_context(logger, "error", "get_queue_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22B-03: Request/Response Tools ============

def tool_agent_request(
    from_agent: str,
    to_agent: str,
    method: str,
    params: Dict[str, Any] = None,
    timeout_ms: int = 30000,
    **kwargs
) -> Dict[str, Any]:
    """Make synchronous request to another agent."""
    log_with_context(logger, "info", "Tool: agent_request", from_agent=from_agent, to_agent=to_agent)
    metrics.inc("tool_agent_request")

    try:
        from app.services.request_response_service import get_request_response_service
        service = get_request_response_service()
        return service.request(from_agent, to_agent, method, params, timeout_ms)
    except Exception as e:
        log_with_context(logger, "error", "agent_request failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_scatter_gather(
    from_agent: str,
    to_agents: List[str],
    method: str,
    params: Dict[str, Any] = None,
    timeout_ms: int = 30000,
    **kwargs
) -> Dict[str, Any]:
    """Send request to multiple agents and gather responses."""
    log_with_context(logger, "info", "Tool: scatter_gather", to_agents=to_agents)
    metrics.inc("tool_scatter_gather")

    try:
        from app.services.request_response_service import get_request_response_service
        service = get_request_response_service()
        return service.scatter_gather(from_agent, to_agents, method, params, timeout_ms)
    except Exception as e:
        log_with_context(logger, "error", "scatter_gather failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_circuit_status(agent_name: str = None, **kwargs) -> Dict[str, Any]:
    """Get circuit breaker status."""
    log_with_context(logger, "info", "Tool: get_circuit_status", agent=agent_name)
    metrics.inc("tool_get_circuit_status")

    try:
        from app.services.request_response_service import get_request_response_service
        service = get_request_response_service()
        return service.get_circuit_status(agent_name)
    except Exception as e:
        log_with_context(logger, "error", "get_circuit_status failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_propose_agent_negotiation(
    title: str,
    initiator_agent: str,
    candidate_agents: List[str],
    strategy: str = "capability_based",
    original_query: str = None,
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a new agent coordination negotiation."""
    log_with_context(logger, "info", "Tool: propose_agent_negotiation", initiator=initiator_agent, strategy=strategy)
    metrics.inc("tool_propose_agent_negotiation")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.propose_negotiation(title, initiator_agent, candidate_agents, strategy, original_query, context)
    except Exception as e:
        log_with_context(logger, "error", "propose_agent_negotiation failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_claim_agent_task(
    negotiation_id: str,
    agent_name: str,
    capability_score: float = None,
    rationale: str = None,
    metadata: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Submit an agent claim for a negotiated task."""
    log_with_context(logger, "info", "Tool: claim_agent_task", negotiation_id=negotiation_id, agent=agent_name)
    metrics.inc("tool_claim_agent_task")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.claim_task(negotiation_id, agent_name, capability_score, rationale, metadata)
    except Exception as e:
        log_with_context(logger, "error", "claim_agent_task failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_submit_agent_bid(
    negotiation_id: str,
    agent_name: str,
    bid_score: float,
    rationale: str = None,
    metadata: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """Submit an auction bid for a negotiation."""
    log_with_context(logger, "info", "Tool: submit_agent_bid", negotiation_id=negotiation_id, agent=agent_name)
    metrics.inc("tool_submit_agent_bid")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.submit_bid(negotiation_id, agent_name, bid_score, rationale, metadata)
    except Exception as e:
        log_with_context(logger, "error", "submit_agent_bid failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_resolve_agent_conflict(
    negotiation_id: str,
    arbitrator_agent: str = "jarvis_core",
    preferred_agent: str = None,
    resolution_note: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Resolve a contested negotiation."""
    log_with_context(logger, "info", "Tool: resolve_agent_conflict", negotiation_id=negotiation_id)
    metrics.inc("tool_resolve_agent_conflict")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.resolve_conflict(negotiation_id, arbitrator_agent, preferred_agent, resolution_note)
    except Exception as e:
        log_with_context(logger, "error", "resolve_agent_conflict failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_record_consensus_vote(
    negotiation_id: str,
    agent_name: str,
    vote_value: str,
    rationale: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Record a consensus vote for a negotiation."""
    log_with_context(logger, "info", "Tool: record_consensus_vote", negotiation_id=negotiation_id, agent=agent_name)
    metrics.inc("tool_record_consensus_vote")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.record_consensus_vote(negotiation_id, agent_name, vote_value, rationale)
    except Exception as e:
        log_with_context(logger, "error", "record_consensus_vote failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_coordination_status(negotiation_id: str, **kwargs) -> Dict[str, Any]:
    """Get full status for a negotiation."""
    log_with_context(logger, "info", "Tool: get_coordination_status", negotiation_id=negotiation_id)
    metrics.inc("tool_get_coordination_status")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.get_coordination_status(negotiation_id)
    except Exception as e:
        log_with_context(logger, "error", "get_coordination_status failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_coordination_stats(days: int = 7, **kwargs) -> Dict[str, Any]:
    """Get coordination statistics."""
    log_with_context(logger, "info", "Tool: get_coordination_stats", days=days)
    metrics.inc("tool_get_coordination_stats")

    try:
        from app.services.agent_coordination_service import get_agent_coordination_service
        service = get_agent_coordination_service()
        return service.get_coordination_stats(days=days)
    except Exception as e:
        log_with_context(logger, "error", "get_coordination_stats failed", error=str(e))
        return {"success": False, "error": str(e)}


# ============ Phase 22B-04/05/06: Shared Context + Subscriptions + Privacy ============

def tool_publish_agent_context(
    source_agent: str,
    context_key: str,
    context_value: Dict[str, Any],
    visibility: str = "domain",
    domain: str = None,
    tags: List[str] = None,
    metadata: Dict[str, Any] = None,
    session_id: str = None,
    ttl_minutes: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Publish context into the cross-agent context pool."""
    log_with_context(logger, "info", "Tool: publish_agent_context", source_agent=source_agent, key=context_key)
    metrics.inc("tool_publish_agent_context")

    try:
        from app.services.agent_context_pool_service import get_agent_context_pool_service
        service = get_agent_context_pool_service()
        return service.publish_context(
            source_agent=source_agent,
            context_key=context_key,
            context_value=context_value,
            visibility=visibility,
            domain=domain,
            tags=tags,
            metadata=metadata,
            session_id=session_id,
            ttl_minutes=ttl_minutes,
        )
    except Exception as e:
        log_with_context(logger, "error", "publish_agent_context failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_subscribe_agent_context(
    agent_id: str,
    visibility_levels: List[str] = None,
    domains: List[str] = None,
    source_agents: List[str] = None,
    tags: List[str] = None,
    include_temporary: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """Create or update a context subscription profile for an agent."""
    log_with_context(logger, "info", "Tool: subscribe_agent_context", agent_id=agent_id)
    metrics.inc("tool_subscribe_agent_context")

    try:
        from app.services.agent_context_pool_service import get_agent_context_pool_service
        service = get_agent_context_pool_service()
        return service.subscribe(
            agent_id=agent_id,
            visibility_levels=visibility_levels,
            domains=domains,
            source_agents=source_agents,
            tags=tags,
            include_temporary=include_temporary,
        )
    except Exception as e:
        log_with_context(logger, "error", "subscribe_agent_context failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_read_agent_context(
    agent_id: str,
    session_id: str = None,
    since_minutes: int = 1440,
    limit: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """Read visible entries from the shared context pool."""
    log_with_context(logger, "info", "Tool: read_agent_context", agent_id=agent_id)
    metrics.inc("tool_read_agent_context")

    try:
        from app.services.agent_context_pool_service import get_agent_context_pool_service
        service = get_agent_context_pool_service()
        return service.read_context(
            agent_id=agent_id,
            session_id=session_id,
            since_minutes=since_minutes,
            limit=limit,
        )
    except Exception as e:
        log_with_context(logger, "error", "read_agent_context failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_set_context_privacy_boundary(
    source_agent: str,
    target_agent: str,
    allowed_levels: List[str] = None,
    allowed_keys: List[str] = None,
    denied_keys: List[str] = None,
    active: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Set explicit privacy boundary for source->target context sharing."""
    log_with_context(logger, "info", "Tool: set_context_privacy_boundary", source=source_agent, target=target_agent)
    metrics.inc("tool_set_context_privacy_boundary")

    try:
        from app.services.agent_context_pool_service import get_agent_context_pool_service
        service = get_agent_context_pool_service()
        return service.set_privacy_boundary(
            source_agent=source_agent,
            target_agent=target_agent,
            allowed_levels=allowed_levels,
            allowed_keys=allowed_keys,
            denied_keys=denied_keys,
            active=active,
        )
    except Exception as e:
        log_with_context(logger, "error", "set_context_privacy_boundary failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_get_context_pool_stats(days: int = 7, **kwargs) -> Dict[str, Any]:
    """Get statistics for context pool, subscriptions, and privacy boundaries."""
    log_with_context(logger, "info", "Tool: get_context_pool_stats", days=days)
    metrics.inc("tool_get_context_pool_stats")

    try:
        from app.services.agent_context_pool_service import get_agent_context_pool_service
        service = get_agent_context_pool_service()
        return service.get_pool_stats(days=days)
    except Exception as e:
        log_with_context(logger, "error", "get_context_pool_stats failed", error=str(e))
        return {"success": False, "error": str(e)}

