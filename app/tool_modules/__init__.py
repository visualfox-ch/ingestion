"""
Jarvis Tools Package.

Contains tool modules that extend Jarvis's capabilities:
- model_management: Model registry management
- model_learning: Learning and optimization for model selection
- research_tools: Perplexity/Sonar Pro research pipeline
- monitoring_tools: DevOps self-monitoring (Prometheus, Loki, anomaly detection)
- self_knowledge_tools: Internal self-model (architecture, capabilities, issues)
- autonomy_tools: Autonomy levels 0-3 with guardrails and approval workflows
- rag_quality_tools: RAG quality evaluation from Langfuse traces
- anomaly_watcher_tools: Proactive anomaly alerts with deduplication and trends
- rag_maintenance_tools: Duplicate detection, reindexing, collection health
- impact_analyzer_tools: Dev-Co-Pilot for change impact analysis and deployment risk
- playbook_runner_tools: Tier 3 Autonomy - Safe automation with playbook execution
- pr_draft_agent_tools: Tier 3 Autonomy - Issue to PR draft with approval workflow
- linkedin_coach_tools: LinkedIn content generation with anti-AI-voice and coach mode
- saas_tools: SaaS Agent (Phase 22A-10) -- funnel metrics, growth experiments, ICP signals, pricing hypotheses
- knowledge_tools: API Context Pack access — list/read/search curated API packs (T-20260319-API-CONTEXT-PACK-READ-PATH)
- agent_coordination_tools: Multi-agent coordination, delegation, queues, consensus (Phase 22A-22B)
- search_tools: Knowledge search, email search, chat search, web search
- calendar_tools: Google Calendar integration, git events
- email_tools: Gmail reading and sending
- memory_tools: Fact storage, conversation context, person context
- file_tools: Project file read/write, source code access
- project_tools: Project and thread management
- introspection_tools: Self-knowledge, capabilities, validation
- label_tools: Label registry management
- decision_tools: Decision rules, outcomes, autonomy status
- utility_tools: Basic utility functions
- diagnostics_tools: System health, memory diagnostics, benchmarks
- generation_tools: Diagram and image generation
- causal_tools: Predictive context, causal patterns
- tool_meta_tools: Tool registry management, chains, performance
- deploy_tools: Self-deployment capabilities with safety guardrails
"""

# Utility Tools
from .utility_tools import (
    tool_get_version,
    tool_no_tool_needed,
    tool_request_out_of_scope,
    tool_complete_pending_action,
    tool_proactive_hint,
)

# Diagnostics Tools
from .diagnostics_tools import (
    tool_system_health_check,
    tool_memory_diagnostics,
    tool_context_window_analysis,
    tool_benchmark_tool_calls,
    tool_compare_code_versions,
    tool_conversation_continuity_test,
    tool_response_quality_metrics,
    tool_proactivity_score,
)

# Generation Tools
from .generation_tools import (
    tool_generate_diagram,
    tool_generate_image,
)

# Causal Tools
from .causal_tools import (
    tool_get_predictive_context,
    tool_record_causal_observation,
    tool_predict_from_cause,
    tool_get_causal_patterns,
)

# Tool Meta Tools
from .tool_meta_tools import (
    tool_list_available_tools,
    tool_manage_tool_registry,
    tool_get_execution_stats,
    tool_get_tool_chain_suggestions,
    tool_get_popular_tool_chains,
    tool_get_tool_performance,
    tool_get_tool_recommendations,
)

# Deploy Tools (Self-deployment capabilities)
from .deploy_tools import (
    tool_deploy_code_changes,
    tool_validate_deploy_readiness,
    tool_get_deploy_history,
)

# Introspection Tools
from .introspection_tools import (
    tool_introspect_capabilities,
    tool_get_development_status,
    tool_mind_snapshot,
    tool_self_validation_dashboard,
    tool_self_validation_pulse,
)

# Label Tools
from .label_tools import (
    tool_list_label_registry,
    tool_upsert_label_registry,
    tool_delete_label_registry,
    tool_label_hygiene,
)

# Decision Tools
from .decision_tools import (
    tool_record_decision_outcome,
    tool_add_decision_rule,
    tool_get_autonomy_status,
)

# Memory Tools
from .memory_tools import (
    tool_remember_fact,
    tool_recall_facts,
    tool_remember_conversation_context,
    tool_recall_conversation_history,
    tool_get_person_context,
    tool_recall_with_timeframe,
)

# File Tools
from .file_tools import (
    tool_read_project_file,
    tool_read_my_source_files,
    tool_write_project_file,
    tool_read_own_code,
    tool_read_roadmap_and_tasks,
    tool_list_own_source_files,
)

# Project Tools
from .project_tools import (
    tool_add_project,
    tool_list_projects,
    tool_update_project_status,
    tool_manage_thread,
)

# Search Tools
from .search_tools import (
    tool_search_knowledge,
    tool_search_emails,
    tool_search_chats,
    tool_get_recent_activity,
    tool_web_search,
    tool_propose_knowledge_update,
)

# Calendar Tools
from .calendar_tools import (
    tool_get_calendar_events,
    tool_create_calendar_event,
    tool_get_git_events,
)

# Email Tools
from .email_tools import (
    tool_get_gmail_messages,
    tool_send_email,
)

# Agent Coordination Tools (Phase 22A-22B)
from .agent_coordination_tools import (
    # Agent State
    tool_set_agent_state,
    tool_get_agent_state,
    tool_get_agent_stats,
    # Handoffs
    tool_create_agent_handoff,
    tool_get_pending_handoffs,
    # Specialist Agents
    tool_list_specialist_agents,
    tool_get_specialist_routing,
    tool_generalize_pattern,
    tool_find_transfer_candidates,
    tool_get_cross_domain_insights,
    tool_get_pattern_generalization_stats,
    # Agent Registry & Lifecycle
    tool_register_agent,
    tool_deregister_agent,
    tool_start_agent,
    tool_stop_agent,
    tool_pause_agent,
    tool_resume_agent,
    tool_reset_agent,
    tool_agent_health_check,
    tool_update_agent_config,
    tool_get_agent_registry_stats,
    # Agent Context Isolation
    tool_create_agent_context,
    tool_get_agent_context,
    tool_store_agent_memory,
    tool_recall_agent_memory,
    tool_set_agent_boundary,
    tool_get_agent_boundaries,
    tool_check_tool_access,
    tool_get_isolation_stats,
    # FitJarvis
    tool_log_workout,
    tool_get_fitness_trends,
    tool_track_nutrition,
    tool_suggest_exercise,
    tool_get_fitness_stats,
    # WorkJarvis
    tool_prioritize_tasks,
    tool_estimate_effort,
    tool_track_focus_time,
    tool_suggest_breaks,
    tool_get_work_stats,
    # CommJarvis
    tool_triage_inbox,
    tool_draft_response,
    tool_track_relationship,
    tool_schedule_followup,
    tool_get_comm_stats,
    # Agent Routing
    tool_route_query,
    tool_classify_intent,
    tool_test_routing,
    tool_get_routing_stats,
    # Multi-Agent Collaboration
    tool_execute_collaboration,
    tool_get_collaboration_stats,
    # Agent Delegation
    tool_delegate_task,
    tool_get_delegation_status,
    tool_get_delegation_stats,
    # Message Queue
    tool_enqueue_message,
    tool_dequeue_message,
    tool_get_queue_stats,
    # Request/Response
    tool_agent_request,
    tool_scatter_gather,
    tool_get_circuit_status,
    # Agent Coordination
    tool_propose_agent_negotiation,
    tool_claim_agent_task,
    tool_submit_agent_bid,
    tool_resolve_agent_conflict,
    tool_record_consensus_vote,
    tool_get_coordination_status,
    tool_get_coordination_stats,
    # Shared Context Pool
    tool_publish_agent_context,
    tool_subscribe_agent_context,
    tool_read_agent_context,
    tool_set_context_privacy_boundary,
    tool_get_context_pool_stats,
)

# Knowledge Tools (API Context Packs)
from .knowledge_tools import (
    tool_list_api_context_packs,
    tool_read_api_context_pack,
    tool_search_api_context_packs,
)
