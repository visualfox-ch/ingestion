"""
Jarvis Tool Definitions
Tools that the agent can use to accomplish tasks.
"""
from typing import Dict, Any, List, Callable
from collections import Counter, defaultdict
import requests
import os
import glob
import shutil
import hashlib
import json
import time
import difflib
import re
import math
from datetime import datetime, timedelta

from .embed import embed_texts
from .observability import get_logger, log_with_context, metrics
from .langfuse_integration import observe, langfuse_context
from .errors import (
    JarvisException, ErrorCode, wrap_external_error,
    internal_error, qdrant_unavailable
)
try:
    from .connectors.registry import load_connector_tools
except ImportError:
    def load_connector_tools():
        return [], {}

# namespace_constants module does not exist in current ingestion app.
# Functions are implemented here directly using domain_separation.
COMMS_COLLECTION = "jarvis_comms"
COMMS_NAMESPACE = "comms"


def expand_namespaces(namespace: str) -> List[str]:
    """Expand a namespace to all related Qdrant collections."""
    from .domain_separation import get_allowed_collections
    collections = get_allowed_collections(namespace or "work_projektil")
    return collections if collections else [namespace or "work_projektil"]


def comms_origin_namespaces(namespace: str) -> List[str]:
    """Return namespaces used for communication lookups."""
    return [namespace or "work_projektil"]


# jarvis_config VALUE_ALIASES does not exist in current ingestion app.
VALUE_ALIASES = {}

# label_registry module does not exist; tools use the label_registry DB table directly
# via knowledge_db. Provide no-op stubs for any legacy call sites.
def get_registry_entries(status: str = None):
    return []


def upsert_registry_entry(**kwargs):
    return kwargs


def delete_registry_entry(key: str, hard: bool = False) -> bool:
    return False

try:
    from .label_schema import refresh_label_schema_cache, get_label_schema
except ImportError:
    def refresh_label_schema_cache() -> None:
        return None

    def get_label_schema() -> Dict[str, Any]:
        return {}

logger = get_logger("jarvis.tools")

# Re-export agent coordination tools from tool_modules
from .tool_modules.agent_coordination_tools import (
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

# Re-export search, calendar, email tools from tool_modules
from .tool_modules.search_tools import (
    tool_search_knowledge,
    tool_search_emails,
    tool_search_chats,
    tool_get_recent_activity,
    tool_web_search,
    tool_propose_knowledge_update,
)
from .tool_modules.calendar_tools import (
    tool_get_calendar_events,
    tool_create_calendar_event,
    tool_get_git_events,
)
from .tool_modules.email_tools import (
    tool_get_gmail_messages,
    tool_send_email,
)
from .tool_modules.memory_tools import (
    tool_remember_fact,
    tool_recall_facts,
    tool_remember_conversation_context,
    tool_recall_conversation_history,
    tool_get_person_context,
    tool_recall_with_timeframe,
)
from .tool_modules.file_tools import (
    tool_read_project_file,
    tool_read_my_source_files,
    tool_write_project_file,
    tool_read_own_code,
    tool_read_roadmap_and_tasks,
    tool_list_own_source_files,
)
from .tool_modules.project_tools import (
    tool_add_project,
    tool_list_projects,
    tool_update_project_status,
    tool_manage_thread,
)
from .tool_modules.introspection_tools import (
    tool_introspect_capabilities,
    tool_get_development_status,
    tool_mind_snapshot,
    tool_self_validation_dashboard,
    tool_self_validation_pulse,
)
from .tool_modules.label_tools import (
    tool_list_label_registry,
    tool_upsert_label_registry,
    tool_delete_label_registry,
    tool_label_hygiene,
)
from .tool_modules.decision_tools import (
    tool_record_decision_outcome,
    tool_add_decision_rule,
    tool_get_autonomy_status,
)
from .tool_modules.utility_tools import (
    tool_no_tool_needed,
    tool_request_out_of_scope,
    tool_complete_pending_action,
    tool_proactive_hint,
)
from .tool_modules.diagnostics_tools import (
    tool_system_health_check,
    tool_memory_diagnostics,
    tool_context_window_analysis,
    tool_benchmark_tool_calls,
    tool_compare_code_versions,
    tool_conversation_continuity_test,
    tool_response_quality_metrics,
    tool_proactivity_score,
)
from .tool_modules.generation_tools import (
    tool_generate_diagram,
    tool_generate_image,
)
from .tool_modules.causal_tools import (
    tool_get_predictive_context,
    tool_record_causal_observation,
    tool_predict_from_cause,
    tool_get_causal_patterns,
)
from .tool_modules.tool_meta_tools import (
    tool_list_available_tools,
    tool_manage_tool_registry,
    tool_get_execution_stats,
    tool_get_tool_chain_suggestions,
    tool_get_popular_tool_chains,
    tool_get_tool_performance,
    tool_get_tool_recommendations,
)

# Retrieval tuning (best-practice defaults)
RERANK_ALPHA = float(os.getenv("JARVIS_RERANK_ALPHA", "0.7"))  # vector weight
LEXICAL_RERANK_ENABLED = os.getenv("JARVIS_LEXICAL_RERANK", "true").lower() in ("1", "true", "yes", "on")
RECENCY_WEIGHT = float(os.getenv("JARVIS_RECENCY_WEIGHT", "0.15"))  # applied in decay step
RECENCY_HALF_LIFE_DAYS = float(os.getenv("JARVIS_RECENCY_HALF_LIFE_DAYS", "30"))


# ============ Fuzzy Name Matching ============

# Constants for name matching (suggested by Jarvis self-analysis v1.6)
ALIAS_SIMILARITY_SCORE = 0.95  # Score for known aliases
DEFAULT_SIMILARITY_THRESHOLD = 0.7  # Min threshold for fuzzy matches

# Known name aliases (normalized lowercase)
NAME_ALIASES: Dict[str, List[str]] = {
    "patrik": ["patrick", "pat"],
    "patrick": ["patrik", "pat"],
    "philippe": ["philip", "phil"],
    "philip": ["philippe", "phil"],
    "micha": ["michael", "mike"],
    "michael": ["micha", "mike"],
    "mike": ["michael", "micha"],
    "anna": ["anne", "anni"],
    "thomas": ["tom", "thom"],
    "sebastian": ["basti", "seb"],
    "matthias": ["matze", "matt"],
    "andreas": ["andi", "andy"],
    "stefan": ["steffen", "steve"],
    "martin": ["martina"],  # Note: different genders but common confusion
    "martina": ["martin"],
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    # Input validation (fix suggested by Jarvis self-analysis v1.6)
    if s1 is None or s2 is None:
        return max(len(s1 or ""), len(s2 or ""))

    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def name_similarity(name1: str, name2: str) -> float:
    """Calculate similarity ratio between two names (0.0 to 1.0)."""
    # Input validation (fix suggested by Jarvis self-analysis v1.6)
    if not name1 or not name2:
        return 0.0

    name1 = name1.lower().strip()
    name2 = name2.lower().strip()

    if name1 == name2:
        return 1.0

    # Check aliases first
    if name1 in NAME_ALIASES and name2 in NAME_ALIASES.get(name1, []):
        return ALIAS_SIMILARITY_SCORE

    # Levenshtein-based similarity
    max_len = max(len(name1), len(name2))
    if max_len == 0:
        return 1.0

    distance = levenshtein_distance(name1, name2)
    return 1.0 - (distance / max_len)


def expand_name_variants(name: str) -> List[str]:
    """
    Expand a name to include known aliases and variants.

    Args:
        name: Original name to expand

    Returns:
        List of name variants including original
    """
    name_lower = name.lower().strip()
    variants = [name]  # Keep original casing

    # Add known aliases
    if name_lower in NAME_ALIASES:
        for alias in NAME_ALIASES[name_lower]:
            # Preserve original casing style
            if name[0].isupper():
                variants.append(alias.capitalize())
            else:
                variants.append(alias)

    return list(set(variants))


def fuzzy_match_name(query_name: str, candidate_names: List[str], threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    Find fuzzy matches for a name in a list of candidates.

    Args:
        query_name: Name to search for
        candidate_names: List of names to match against
        threshold: Minimum similarity score (0.0 to 1.0)

    Returns:
        List of matches with name and score, sorted by score descending
    """
    matches = []
    query_lower = query_name.lower().strip()

    for candidate in candidate_names:
        similarity = name_similarity(query_lower, candidate.lower().strip())
        if similarity >= threshold:
            matches.append({
                "name": candidate,
                "score": similarity,
                "is_alias": query_lower in NAME_ALIASES and candidate.lower() in NAME_ALIASES.get(query_lower, [])
            })

    # Sort by score descending
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def expand_query_with_name_variants(query: str) -> str:
    """
    Expand a search query by adding name variants.

    If the query contains a known name, adds OR clauses for aliases.
    Example: "Philippe Budget" -> "Philippe OR Philip Budget"

    Args:
        query: Original search query

    Returns:
        Expanded query with name variants
    """
    words = query.split()
    expanded_words = []

    for word in words:
        word_lower = word.lower().strip(".,!?")
        if word_lower in NAME_ALIASES and len(NAME_ALIASES[word_lower]) > 0:
            # Add OR clause with first alias
            alias = NAME_ALIASES[word_lower][0]
            if word[0].isupper():
                alias = alias.capitalize()
            expanded_words.append(f"({word} OR {alias})")
        else:
            expanded_words.append(word)

    return " ".join(expanded_words)


QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"


# ============ Tool Definitions (Anthropic format) ============

TOOL_DEFINITIONS = [

    {
        "name": "get_development_status",
        "description": "Get current development status (phase, next phase, active team).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_label_registry",
        "description": "List label registry entries, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Status filter such as active, archived, or all",
                    "default": "active"
                }
            }
        }
    },
    {
        "name": "upsert_label_registry",
        "description": "Create or update a label registry entry with optional description, allowed values, status, and source metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Registry key to create or update"
                },
                "description": {
                    "type": "string",
                    "description": "Optional human-readable description"
                },
                "allowed_values": {
                    "description": "Optional list of allowed values for the key",
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        {
                            "type": "string"
                        }
                    ]
                },
                "status": {
                    "type": "string",
                    "description": "Registry status",
                    "default": "active"
                },
                "source": {
                    "type": "string",
                    "description": "Source of the registry entry",
                    "default": "jarvis"
                }
            },
            "required": ["key"]
        }
    },
    {
        "name": "delete_label_registry",
        "description": "Delete a label registry entry. By default this is a soft delete unless hard is true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Registry key to delete"
                },
                "hard": {
                    "type": "boolean",
                    "description": "If true, perform a hard delete",
                    "default": False
                }
            },
            "required": ["key"]
        }
    },
    {
        "name": "label_hygiene",
        "description": "Scan Qdrant label usage against the base plus registry schema, report unknown keys or values, and optionally apply registry updates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collections": {
                    "type": "string",
                    "description": "Comma-separated Qdrant collections to scan",
                    "default": "jarvis_work,jarvis_private,jarvis_comms"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of points to scan",
                    "default": 2000
                },
                "apply": {
                    "type": "boolean",
                    "description": "Apply suggested registry updates when the guard env var is enabled",
                    "default": False
                },
                "allow_values": {
                    "type": "boolean",
                    "description": "When applying updates, also extend allowed values on existing keys",
                    "default": True
                },
                "min_count": {
                    "type": "integer",
                    "description": "Minimum observation count before suggesting a key or value",
                    "default": 3
                },
                "max_values": {
                    "type": "integer",
                    "description": "Maximum suggested values to keep per key",
                    "default": 20
                },
                "max_value_length": {
                    "type": "integer",
                    "description": "Maximum string length for tracked values",
                    "default": 64
                }
            }
        }
    },
    {
        "name": "mind_snapshot",
        "description": "Get a quick internal snapshot of collection counts, label schema state, registry keys, and current tool count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collections": {
                    "type": "string",
                    "description": "Comma-separated Qdrant collections to inspect",
                    "default": "jarvis_work,jarvis_private,jarvis_comms"
                }
            }
        }
    },
    {
        "name": "validate_tool_registry",
        "description": "Validate all tools in TOOL_REGISTRY and report configuration issues or missing definitions.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_response_metrics",
        "description": "Get response performance metrics such as latency, token usage, and tool distribution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to analyze",
                    "default": 24
                }
            }
        }
    },
    {
        "name": "memory_diagnostics",
        "description": "Inspect session persistence and memory/context storage health.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "context_window_analysis",
        "description": "Analyze context window usage patterns and token pressure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "Optional specific user to analyze"
                }
            }
        }
    },
    {
        "name": "benchmark_tool_calls",
        "description": "Benchmark tool call latency, usage, and success rates over time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to analyze",
                    "default": 24
                }
            }
        }
    },
    {
        "name": "compare_code_versions",
        "description": "Compare current code with recent git history for a module such as main, agent, tools, or config.",
        "input_schema": {
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "description": "Module to compare",
                    "default": "main"
                }
            }
        }
    },
    {
        "name": "conversation_continuity_test",
        "description": "Test cross-session continuity and memory recall quality for a specific user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID to analyze"
                }
            },
            "required": ["user_id"]
        }
    },
    {
        "name": "response_quality_metrics",
        "description": "Analyze response quality, feedback patterns, and output consistency over time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to analyze",
                    "default": 168
                }
            }
        }
    },
    {
        "name": "proactivity_score",
        "description": "Measure effectiveness of proactive hints and related timing or acceptance signals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "Optional specific user"
                },
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to analyze",
                    "default": 168
                }
            }
        }
    },
    {
        "name": "self_validation_dashboard",
        "description": "Get a combined self-validation dashboard with health, tool, memory, quality, and performance metrics.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "self_validation_pulse",
        "description": "Quick health pulse for real-time monitoring. Returns essential metrics in <50ms. Use for frequent status checks.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_available_tools",
        "description": "List all available tools. USE THIS FIRST if you're unsure what tools exist! Prevents hallucinating non-existent tools like 'create_tool'. Filter by category (memory, calendar, email, system, dynamic, self_improvement) or search by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category: memory, calendar, email, chat, project, file, system, dynamic, ollama, python, self_improvement"
                },
                "search": {
                    "type": "string",
                    "description": "Search tools by name"
                }
            }
        }
    },
    # MOVED to tool_modules/timer_tools.py (T006 refactor)
    # MOVED to tool_modules/ollama_tools.py (T006 refactor)
    # MOVED to tool_modules/subagent_tools.py (T006 refactor)
    {
        "name": "web_search",
        "description": "Search the web for current information using Perplexity. Returns results with source citations. Use for: current events, fact-checking, research, news, looking up recent information. This is a shortcut for delegate_to_subagent with agent_id='perplexity'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - be specific for better results"
                },
                "detailed": {
                    "type": "boolean",
                    "description": "Use larger model for more detailed research (slower but better)",
                    "default": False
                }
            },
            "required": ["query"]
        }
    },
    # execute_python MOVED to tool_modules/sandbox_tools.py (T006 refactor)
    {
        "name": "get_git_events",
        "description": "Query git commits by time range and optional keywords for causal analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "ISO timestamp (e.g., 2026-02-05T00:00:00Z)"
                },
                "end_time": {
                    "type": "string",
                    "description": "ISO timestamp (e.g., 2026-02-06T00:00:00Z)"
                },
                "keywords": {
                    "type": "string",
                    "description": "Comma-separated keywords to filter commit messages"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (1-1000)",
                    "default": 100
                }
            }
        }
    },
    {
        "name": "search_knowledge",
        "description": "Search the user's knowledge base (emails, chats, documents) using semantic search. Use this when you need to find information about a topic, person, project, or event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query - be specific and descriptive"
                },
                "namespace": {
                    "type": "string",
                    "description": "Which namespace to search: 'private' (default, includes work), 'work', or 'all'",
                    "default": "private"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results to return (1-20)",
                    "default": 5
                },
                "recency_days": {
                    "type": "integer",
                    "description": "Only return results from the last N days. Omit for all time."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_emails",
        "description": "Search specifically through emails. Use when the user asks about emails, messages from specific people, or email-related topics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in emails"
                },
                "namespace": {
                    "type": "string",
                    "description": "Which namespace: 'private' (default, includes work) or 'work'",
                    "default": "private"
                },
                "label": {
                    "type": "string",
                    "description": "Filter by label: 'inbox' or 'sent'",
                    "enum": ["inbox", "sent"]
                },
                "recency_days": {
                    "type": "integer",
                    "description": "Only emails from last N days"
                },
                "limit": {
                    "type": "integer",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_chats",
        "description": "Search through chat messages (WhatsApp, Google Chat). Use when looking for conversations or chat history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in chats"
                },
                "namespace": {
                    "type": "string",
                    "default": "private"
                },
                "channel": {
                    "type": "string",
                    "description": "Filter by channel: 'whatsapp' or 'google_chat'",
                    "enum": ["whatsapp", "google_chat"]
                },
                "recency_days": {
                    "type": "integer"
                },
                "limit": {
                    "type": "integer",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_recent_activity",
        "description": "Get a summary of recent activity - emails, chats from the last N days. Good for daily briefings or catching up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days back to look (1-30)",
                    "default": 1
                },
                "namespace": {
                    "type": "string",
                    "default": "private"
                },
                "include_emails": {
                    "type": "boolean",
                    "default": True
                },
                "include_chats": {
                    "type": "boolean",
                    "default": True
                }
            }
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current information, news, or topics not in the user's personal data. Use when asked about external topics, current events, or general knowledge questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (1-10)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "remember_fact",
        "description": """Store an important fact about the user for future reference. Use when the user tells you something you should remember permanently (preferences, relationships, important info).

Facts start with a trust_score that increases with usage (+0.1 per access).
Once trust_score >= 0.5 AND access_count >= 5, facts become migration candidates
for permanent storage in config/YAML files (reviewed by Claude Code).

Trust Score Guidelines:
- 0.0: Inferred or uncertain facts
- 0.3: User mentioned explicitly ("I prefer...")
- 0.5: User confirmed when asked
- 0.7: Repeatedly validated or critical info""",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The fact to remember"
                },
                "category": {
                    "type": "string",
                    "description": "Category: preference, relationship, project, personal, work",
                    "enum": ["preference", "relationship", "project", "personal", "work"]
                },
                "initial_trust_score": {
                    "type": "number",
                    "description": "Starting trust score (0.0-1.0). Use 0.0 for inferred, 0.3 for explicit, 0.5 for confirmed, 0.7 for validated.",
                    "default": 0.0,
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "source": {
                    "type": "string",
                    "description": "Where this fact came from: 'user_explicit', 'inferred', 'confirmed', 'observed'",
                    "enum": ["user_explicit", "inferred", "confirmed", "observed"]
                }
            },
            "required": ["fact", "category"]
        }
    },
    {
        "name": "recall_facts",
        "description": "Recall stored facts about the user. Use when you need context about the user's preferences, relationships, or past information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (optional)",
                    "enum": ["preference", "relationship", "project", "personal", "work"]
                },
                "query": {
                    "type": "string",
                    "description": "Search query to filter facts (optional)"
                }
            }
        }
    },
    {
        "name": "get_calendar_events",
        "description": "Get calendar events from Google Calendar. Supports filtering by timeframe (today/tomorrow/week) and account (visualfox/projektil/all).",
        "input_schema": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "enum": ["today", "tomorrow", "week", "all"],
                    "description": "Time range: today, tomorrow, week (next 7 days), or all",
                    "default": "week"
                },
                "account": {
                    "type": "string",
                    "enum": ["all", "visualfox", "projektil"],
                    "description": "Which calendar account to query",
                    "default": "all"
                }
            }
        }
    },
    {
        "name": "create_calendar_event",
        "description": "Create a new calendar event. Supports both Projektil and Visualfox calendars. Use ISO 8601 format for dates (e.g., 2026-01-30T14:00:00+01:00).",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title"
                },
                "start": {
                    "type": "string",
                    "description": "Start time in ISO 8601 format (e.g., 2026-01-30T14:00:00+01:00)"
                },
                "end": {
                    "type": "string",
                    "description": "End time in ISO 8601 format"
                },
                "account": {
                    "type": "string",
                    "enum": ["projektil", "visualfox"],
                    "description": "Which calendar account to create the event in",
                    "default": "projektil"
                },
                "description": {
                    "type": "string",
                    "description": "Event description (optional)"
                },
                "location": {
                    "type": "string",
                    "description": "Event location (optional)"
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of email addresses to invite (optional)"
                }
            },
            "required": ["summary", "start", "end"]
        }
    },
    {
        "name": "get_gmail_messages",
        "description": "Get recent emails from Projektil Gmail inbox via live API (not search). Use for checking latest emails or when user asks 'what emails do I have'. Note: Only Projektil has Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to fetch (1-20)",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "send_email",
        "description": "Send an email via Projektil Gmail account. Note: Only Projektil has Gmail configured, Visualfox has no Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject"
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or HTML)"
                },
                "cc": {
                    "type": "string",
                    "description": "CC recipients (comma-separated, optional)"
                },
                "bcc": {
                    "type": "string",
                    "description": "BCC recipients (comma-separated, optional)"
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "no_tool_needed",
        "description": "Use this when you can answer the question from your general knowledge without searching the user's data. For greetings, general questions, or follow-up clarifications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason why no search is needed"
                }
            }
        }
    },
    {
        "name": "request_out_of_scope",
        "description": "Use when the request requires capabilities you don't have. Examples: code analysis, file system access, running commands, modifying external systems, creating files. Be honest about limitations and suggest alternatives.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why this request is outside your capabilities"
                },
                "suggestion": {
                    "type": "string",
                    "description": "What the user could do instead (e.g., 'Use Claude Code for this', 'Ask me about your calendar instead')"
                }
            },
            "required": ["reason", "suggestion"]
        }
    },
    {
        "name": "remember_conversation_context",
        "description": "Store conversation context at end of session for future reference. Use this when a conversation is wrapping up and contains important context, follow-ups, or learnings that should be remembered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_summary": {
                    "type": "string",
                    "description": "Brief summary of what was discussed in this conversation"
                },
                "key_topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of main topics discussed (e.g., 'Project X', 'budget review', 'API migration')"
                },
                "pending_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any follow-up tasks, commitments, or things to remember for next time"
                },
                "emotional_context": {
                    "type": "string",
                    "description": "User mood/tone indicators (e.g., 'stressed about deadline', 'excited about launch')"
                },
                "relationship_insights": {
                    "type": "string",
                    "description": "New learnings about user preferences, relationships, or working style"
                }
            },
            "required": ["session_summary", "key_topics"]
        }
    },
    {
        "name": "recall_conversation_history",
        "description": "Retrieve relevant conversation context from previous sessions. Use this at the start of a conversation or when the user references something from a past discussion.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "How many days to look back (default: 7)",
                    "default": 7
                },
                "topic_filter": {
                    "type": "string",
                    "description": "Optional: filter by specific topic or keyword"
                },
                "include_pending_actions": {
                    "type": "boolean",
                    "description": "Include unresolved tasks from past conversations (default: true)",
                    "default": True
                }
            }
        }
    },
    {
        "name": "complete_pending_action",
        "description": "Mark a pending action from a previous conversation as completed. Use when the user confirms they've done something that was a follow-up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "integer",
                    "description": "The ID of the pending action to mark as complete"
                },
                "action_text": {
                    "type": "string",
                    "description": "Alternative: the text of the action (will match closest)"
                }
            }
        }
    },
    # Knowledge Layer tools
    {
        "name": "propose_knowledge_update",
        "description": "Propose an update to Jarvis's knowledge about a person or topic. Use when you learn something new about someone that should be remembered. The proposal goes to human review before being applied.",
        "input_schema": {
            "type": "object",
            "properties": {
                "update_type": {
                    "type": "string",
                    "description": "Type of knowledge: 'person_insight', 'persona_adjustment', 'rule'",
                    "enum": ["person_insight", "persona_adjustment", "rule"]
                },
                "subject_id": {
                    "type": "string",
                    "description": "Who/what this is about (e.g., 'patrik', 'philippe', 'micha_default')"
                },
                "insight": {
                    "type": "string",
                    "description": "The insight or update to propose"
                },
                "confidence": {
                    "type": "string",
                    "description": "How confident you are: low, medium, high",
                    "enum": ["low", "medium", "high"],
                    "default": "medium"
                },
                "evidence_source": {
                    "type": "string",
                    "description": "Source path or description of evidence for this insight"
                },
                "evidence_note": {
                    "type": "string",
                    "description": "Brief note about the evidence"
                }
            },
            "required": ["update_type", "subject_id", "insight"]
        }
    },
    {
        "name": "get_person_context",
        "description": "Get the stored knowledge profile for a person. Use this when you need to understand how to communicate with someone or recall their preferences and communication style.",
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {
                    "type": "string",
                    "description": "The person's ID (e.g., 'patrik', 'philippe')"
                }
            },
            "required": ["person_id"]
        }
    },
    # Project Management tools
    {
        "name": "add_project",
        "description": "Add a new active project to track. Use when user mentions starting a new project or priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short project name"
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what the project involves"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority level: 1=high, 2=medium, 3=low",
                    "default": 2
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_projects",
        "description": "List all active projects for the user. Use to understand current workload and priorities.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "update_project_status",
        "description": "Update a project's status (complete, pause, or resume).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project ID"
                },
                "status": {
                    "type": "string",
                    "description": "New status: 'active', 'paused', or 'completed'",
                    "enum": ["active", "paused", "completed"]
                }
            },
            "required": ["project_id", "status"]
        }
    },
    # Thread Management tools (ADHD support)
    {
        "name": "manage_thread",
        "description": "Manage conversation threads for ADHD support. Use to open, close, or pause topics. Helps user maintain focus by tracking active discussions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "What to do: 'open' (start/resume), 'close' (complete), 'pause' (temporarily set aside), 'list' (show all)",
                    "enum": ["open", "close", "pause", "list"]
                },
                "topic": {
                    "type": "string",
                    "description": "The topic name (required for open/close/pause, ignored for list)"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes when closing a thread"
                }
            },
            "required": ["action"]
        }
    },
    # Direct File Access (Project Files)
    {
        "name": "proactive_hint",
        "description": "Share a proactive observation or pattern you've noticed. Use this when you recognize something useful the user might want to know about, WITHOUT being asked. This is Tier 2 (Notify) - you can do this autonomously but user will be notified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "observation": {
                    "type": "string",
                    "description": "The pattern or observation you want to share"
                },
                "context": {
                    "type": "string",
                    "description": "Why you think this is relevant right now"
                },
                "suggested_action": {
                    "type": "string",
                    "description": "Optional: What action you'd suggest based on this observation"
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "How confident you are in this observation",
                    "default": "medium"
                }
            },
            "required": ["observation", "context"]
        }
    },
    {
        "name": "read_project_file",
        "description": """Read files from allowed project directories. Supports single files, directory listing for markdown files, and wildcard patterns (e.g. *.md).

ALLOWED PATHS:
- /brain/system/docker/ - Docker configs (docker-compose.yml)
- /brain/system/docker/app/ - Jarvis source code (*.py)
- /brain/system/policies/ - System prompts, policies (*.md)
- /brain/system/prompts/ - Persona configs, modes (*.json)
- /brain/projects/ - Project files
- /brain/notes/ - Notes
- /data/linkedin/ - LinkedIn knowledge markdown updates
- /data/visualfox/ - VisualFox knowledge markdown updates

EXAMPLES:
- docker-compose.yml → /brain/system/docker/docker-compose.yml
- Jarvis code → /brain/system/docker/app/agent.py
- System prompt → /brain/system/policies/JARVIS_SYSTEM_PROMPT.md
- LinkedIn updates → /data/linkedin/*.md
- VisualFox updates → /data/visualfox/*.md
- List markdown files in a folder → /data/linkedin

BLOCKED: .env, credentials, secrets, passwords, .key, .pem, id_rsa, .ssh""",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full file path (e.g. /brain/system/docker/docker-compose.yml)"
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 200, max 500)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write_project_file",
        "description": """Write or append to a file in allowed project directories. Use for updating code, configs, or docs.

ALLOWED PATHS:
- /brain/system/docker/ - Docker configs (docker-compose.yml)
- /brain/system/docker/app/ - Jarvis source code (*.py)
- /brain/system/policies/ - System prompts, policies (*.md)
- /brain/system/prompts/ - Persona configs, modes (*.json)
- /brain/projects/ - Project files
- /brain/notes/ - Notes
- /data/linkedin/ - LinkedIn knowledge markdown updates
- /data/visualfox/ - VisualFox knowledge markdown updates

BLOCKED: .env, credentials, secrets, passwords, .key, .pem, id_rsa, .ssh

LIMITS: size and rate limits enforced via JARVIS_WRITE_MAX_BYTES / JARVIS_WRITE_MAX_PER_MINUTE / JARVIS_WRITE_MAX_PER_HOUR
APPROVAL: certain paths require approved=true (see JARVIS_WRITE_APPROVAL_PATHS).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full file path (e.g. /brain/system/docker/docker-compose.yml)"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write"
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "append"],
                    "description": "Write mode",
                    "default": "replace"
                },
                "create_backup": {
                    "type": "boolean",
                    "description": "Create a backup before writing",
                    "default": True
                },
                "preview_only": {
                    "type": "boolean",
                    "description": "Return a diff preview without writing",
                    "default": False
                },
                "approved": {
                    "type": "boolean",
                    "description": "Explicit approval for critical paths",
                    "default": False
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the change (audit trail)"
                }
            },
            "required": ["file_path", "content"]
        }
    },
    # Phase 18.3: Self-Optimization Tools
    {
        "name": "optimize_system_prompt",
        "description": """Analyze and suggest improvements to a system prompt based on interaction patterns and feedback.
Use this when the user asks about improving prompt effectiveness, or when you notice patterns that could be optimized.
Returns specific suggestions for prompt modifications with confidence scores.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt_section": {
                    "type": "string",
                    "description": "Which prompt section to analyze: 'agent', 'chat', 'coaching', 'search'",
                    "enum": ["agent", "chat", "coaching", "search"]
                },
                "focus_area": {
                    "type": "string",
                    "description": "What aspect to optimize: 'clarity', 'conciseness', 'tone', 'effectiveness', 'all'",
                    "default": "all"
                },
                "include_metrics": {
                    "type": "boolean",
                    "description": "Include usage metrics in analysis",
                    "default": True
                }
            },
            "required": ["prompt_section"]
        }
    },
    {
        "name": "enable_experimental_feature",
        "description": """Enable or disable an experimental feature flag. Use this for A/B testing or gradual rollout of new features.
Feature flags take effect immediately without restart (hot-reload).
Includes audit trail for all changes.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "flag_name": {
                    "type": "string",
                    "description": "Name of the feature flag (snake_case)"
                },
                "action": {
                    "type": "string",
                    "description": "Action to take: 'enable', 'disable', 'check', 'create'",
                    "enum": ["enable", "disable", "check", "create"]
                },
                "rollout_percent": {
                    "type": "integer",
                    "description": "Percentage of users to enable for (0-100, only for 'enable' action)",
                    "default": 100
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the change (audit trail)"
                }
            },
            "required": ["flag_name", "action"]
        }
    },
    {
        "name": "introspect_capabilities",
        "description": """Return Jarvis self-capabilities from canonical files (CAPABILITIES.json + CAPABILITY_CATALOG.md). Use for self-awareness and debugging.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_catalog": {
                    "type": "boolean",
                    "description": "Include CAPABILITY_CATALOG.md preview",
                    "default": False
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Max lines to return from catalog preview",
                    "default": 120
                }
            }
        }
    },
    {
        "name": "analyze_cross_session_patterns",
        "description": """Analyze cross-session learning patterns (lessons + decision insights) for a user.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (defaults to 0 if unknown)",
                    "default": 0
                },
                "days": {
                    "type": "integer",
                    "description": "Window for decision insights",
                    "default": 30
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum lesson confidence",
                    "default": 0.5
                }
            }
        }
    },
    {
        "name": "system_health_check",
        "description": """Return internal health status for core services (qdrant, postgres, sqlite, meilisearch).""",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "read_my_source_files",
        "description": """Read canonical self-source files (capability catalog, context policy, capabilities json, jarvis self).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_key": {
                    "type": "string",
                    "description": "Which file to read",
                    "enum": ["capability_catalog", "context_policy", "capabilities_json", "jarvis_self"]
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Max lines to return",
                    "default": 200
                }
            },
            "required": ["file_key"]
        }
    },
    # Self-Inspection Tools (Phase 6 - Self-Awareness)
    {
        "name": "read_own_code",
        "description": """Read Jarvis' own source code files. Use this to inspect your own implementation.

AVAILABLE FILES:
- agent.py - Main agent loop and tool routing
- tools.py - All tool definitions and implementations
- main.py - FastAPI endpoints and startup
- prompt_assembler.py - System prompt construction
- embed.py - Embedding and vector operations
- knowledge_db.py - Knowledge base operations
- python_executor.py - Python sandbox execution

Use file_name parameter (e.g., 'agent.py') - no path needed.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Python file name (e.g., 'agent.py', 'tools.py')"
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Max lines to return (default 200)",
                    "default": 200
                },
                "search_term": {
                    "type": "string",
                    "description": "Optional: search for specific function/class and show context"
                }
            },
            "required": ["file_name"]
        }
    },
    {
        "name": "read_roadmap_and_tasks",
        "description": """Read current roadmap, tasks, and development documentation.

AVAILABLE DOCUMENTS:
- tasks - Current TASKS.md board (active work, sprint, deploy queue)
- roadmap - ROADMAP_UNIFIED_LATEST.md (phase planning)
- agents - AGENTS.md (team member roles)
- agent_routing - AGENT_ROUTING.md (assignment rules)
- review_plan - JARVIS_REVIEW_PLAN.md (current review status)

Use this to understand what's currently being worked on and what's planned.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "document": {
                    "type": "string",
                    "enum": ["tasks", "roadmap", "agents", "agent_routing", "review_plan"],
                    "description": "Which document to read"
                },
                "section": {
                    "type": "string",
                    "description": "Optional: search for specific section heading"
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Max lines to return",
                    "default": 300
                }
            },
            "required": ["document"]
        }
    },
    {
        "name": "list_own_source_files",
        "description": """List all Python source files in Jarvis' codebase with basic info (size, modified date).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_routers": {
                    "type": "boolean",
                    "description": "Include files in routers/ subdirectory",
                    "default": True
                },
                "include_subagents": {
                    "type": "boolean",
                    "description": "Include files in subagents/ subdirectory",
                    "default": True
                }
            }
        }
    },
    # Ollama tools MOVED to tool_modules/ollama_tools.py (T006 refactor)
    {
        "name": "record_decision_outcome",
        "description": "Record outcome/feedback for a Jarvis decision_id (used for learning loop).",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision_id": {
                    "type": "string",
                    "description": "decision_id from a prior response"
                },
                "outcome": {
                    "type": "string",
                    "description": "Outcome label (success, partial, failed, not_tried)",
                    "enum": ["success", "partial", "failed", "not_tried"]
                },
                "feedback_score": {
                    "type": "number",
                    "description": "Optional feedback score (1-5)",
                    "minimum": 1,
                    "maximum": 5
                },
                "source_channel": {
                    "type": "string",
                    "description": "Where feedback came from (user, ui, system)",
                    "default": "user"
                },
                "strategy_id": {
                    "type": "string",
                    "description": "Optional strategy identifier"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Primary tool used, if any"
                },
                "details": {
                    "type": "object",
                    "description": "Optional details payload for audit"
                }
            },
            "required": ["decision_id", "outcome"]
        }
    },
    # Sandbox tools MOVED to tool_modules/sandbox_tools.py (T006 refactor)
    # Learning & Memory tools MOVED to tool_modules/learning_memory_tools.py (T006 refactor)
    # === Tool Autonomy (Phase 19.6) ===
    {
        "name": "manage_tool_registry",
        "description": "Manage your own tool registry - enable/disable tools, update descriptions, assign categories. Use this to optimize your capabilities!",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action: enable, disable, update_description, assign_category, get_stats",
                    "enum": ["enable", "disable", "update_description", "assign_category", "get_stats"]
                },
                "tool_name": {"type": "string", "description": "Name of the tool to manage"},
                "enabled": {"type": "boolean", "description": "For enable/disable actions"},
                "description": {"type": "string", "description": "New description for update_description"},
                "category": {"type": "string", "description": "Category name for assign_category"},
                "reason": {"type": "string", "description": "Why this change is being made"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "add_decision_rule",
        "description": "Add a rule for when to use which tools. Learn patterns and optimize tool selection automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for this rule"},
                "condition_type": {
                    "type": "string",
                    "description": "Type of condition",
                    "enum": ["keyword", "intent", "context", "pattern", "time_of_day", "user_id", "source"]
                },
                "condition_value": {"description": "The condition (keywords list, intent name, context dict, regex)"},
                "action_type": {
                    "type": "string",
                    "description": "What to do when matched",
                    "enum": ["include_tools", "exclude_tools", "set_priority", "require_approval"]
                },
                "action_value": {"description": "The action value (tool names, priority, etc.)"},
                "description": {"type": "string", "description": "Human-readable description"},
                "priority": {"type": "integer", "description": "Higher priority rules checked first", "default": 50}
            },
            "required": ["name", "condition_type", "condition_value", "action_type", "action_value"]
        }
    },
    {
        "name": "get_autonomy_status",
        "description": "Get your autonomy dashboard - enabled tools, categories, recent self-modifications. Understand your current capabilities.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_execution_stats",
        "description": "Get tool execution statistics - latency, success rates, most used tools, slowest tools, most failing tools. Analyze your performance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days to analyze (default 7)", "default": 7},
                "limit": {"type": "integer", "description": "Max tools to show in rankings (default 20)", "default": 20}
            }
        }
    },
    # Jarvis Wishes: Visual Thinking & Deep Memory
    {
        "name": "generate_diagram",
        "description": "Generate visual diagrams (flowchart, mindmap, sequence, timeline). Returns Mermaid code that can be rendered in Obsidian, GitHub, or mermaid.live. Use this to visualize processes, ideas, relationships, or timelines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "diagram_type": {
                    "type": "string",
                    "enum": ["flowchart", "mindmap", "sequence", "timeline"],
                    "description": "Type of diagram to generate"
                },
                "content": {
                    "type": "object",
                    "description": "Diagram content. For flowchart: {nodes: [{id, label, type}], edges: [{from, to, label}]}. For mindmap: {root: 'Topic', children: [{label, children}]}. For sequence: {actors: [], messages: [{from, to, text}]}. For timeline: {events: [{date, label}]}"
                },
                "title": {
                    "type": "string",
                    "description": "Optional diagram title"
                },
                "render_image": {
                    "type": "boolean",
                    "description": "If true, render to PNG image (returns base64)",
                    "default": False
                }
            },
            "required": ["diagram_type", "content"]
        }
    },
    {
        "name": "recall_with_timeframe",
        "description": "Recall memories, patterns, and emotional context from a specific timeframe. Use this for cross-session awareness - understanding what happened yesterday, last week, or last month. Includes pattern detection and emotional trends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search query to filter memories"
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month", "quarter"],
                    "description": "Time period to recall from",
                    "default": "week"
                },
                "include_patterns": {
                    "type": "boolean",
                    "description": "Include detected patterns and recurring themes",
                    "default": True
                },
                "include_emotional_context": {
                    "type": "boolean",
                    "description": "Include emotional/mood patterns",
                    "default": True
                }
            }
        }
    },
    {
        "name": "get_predictive_context",
        "description": "Get predictive insights based on patterns and upcoming events. Anticipate user needs based on calendar, historical patterns (e.g., 'Mondays are busy'), and recent energy/mood trends. Use this proactively to prepare for the day ahead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context_type": {
                    "type": "string",
                    "enum": ["day_ahead", "week_ahead", "meeting_prep"],
                    "description": "Type of prediction to generate",
                    "default": "day_ahead"
                }
            }
        }
    },
    # Jarvis Wishes: Image Generation (Tier 3)
    {
        "name": "generate_image",
        "description": "Generate images using DALL-E 3. Create images from text descriptions for concept visualization, creative projects, mood boards, or quick mockups. Detailed prompts work best. URL expires after ~1 hour.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate. Be specific about style, mood, composition, colors, etc."
                },
                "style": {
                    "type": "string",
                    "enum": ["natural", "vivid"],
                    "description": "'natural' for photorealistic, 'vivid' for artistic/dramatic",
                    "default": "natural"
                },
                "size": {
                    "type": "string",
                    "enum": ["1024x1024", "1792x1024", "1024x1792"],
                    "description": "Image dimensions. 1024x1024 (square), 1792x1024 (landscape), 1024x1792 (portrait)",
                    "default": "1024x1024"
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "'standard' or 'hd' (more detail, higher cost)",
                    "default": "standard"
                }
            },
            "required": ["prompt"]
        }
    },
    # Phase 20: Identity Evolution Tools MOVED to tool_modules/identity_tools.py (T006 refactor)
    # Phase 21: Intelligent System Evolution
    # T-21A-01: Smart Tool Chains
    {
        "name": "get_tool_chain_suggestions",
        "description": "Get suggestions for next tool based on current tool sequence. Analyzes patterns of tools used together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools used so far in current sequence"
                },
                "context": {
                    "type": "string",
                    "description": "Optional context about current task"
                }
            },
            "required": ["current_tools"]
        }
    },
    {
        "name": "get_popular_tool_chains",
        "description": "Get the most popular and effective tool chains based on usage patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum times chain must be observed",
                    "default": 3
                },
                "limit": {
                    "type": "integer",
                    "description": "Max chains to return",
                    "default": 10
                }
            }
        }
    },
    # T-21A-04: Tool Performance Learning
    {
        "name": "get_tool_performance",
        "description": "Get performance statistics for tools. Shows success rates, avg duration, best contexts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Specific tool to get stats for (or omit for all)"
                }
            }
        }
    },
    {
        "name": "get_tool_recommendations",
        "description": "Get recommended tools based on current context and historical performance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_context": {
                    "type": "string",
                    "description": "Current query or task context"
                }
            }
        }
    },
    # T-21B-01: CK-Track (Causal Knowledge)
    {
        "name": "record_causal_observation",
        "description": "Record a cause-effect observation. Example: 'late_night_work' causes 'morning_tiredness'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cause_event": {
                    "type": "string",
                    "description": "What happened first (the cause)"
                },
                "effect_event": {
                    "type": "string",
                    "description": "What resulted (the effect)"
                },
                "cause_type": {
                    "type": "string",
                    "enum": ["behavior", "event", "state", "action", "time", "external"],
                    "default": "event"
                },
                "effect_type": {
                    "type": "string",
                    "enum": ["need", "outcome", "state", "recommendation", "warning", "opportunity"],
                    "default": "outcome"
                }
            },
            "required": ["cause_event", "effect_event"]
        }
    },
    {
        "name": "predict_from_cause",
        "description": "Predict likely effects given a cause. Example: What happens when user works late?",
        "input_schema": {
            "type": "object",
            "properties": {
                "cause": {
                    "type": "string",
                    "description": "The cause/trigger to predict from"
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence for predictions",
                    "default": 0.6
                }
            },
            "required": ["cause"]
        }
    },
    {
        "name": "get_causal_patterns",
        "description": "Get all learned causal patterns for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold",
                    "default": 0.5
                },
                "limit": {
                    "type": "integer",
                    "default": 50
                }
            }
        }
    },
    # T-21C-01: Agent State Persistence
    {
        "name": "set_agent_state",
        "description": "Store persistent state for an AI agent that survives across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent identifier (e.g., 'claude_code', 'copilot', 'codex')"
                },
                "state_key": {
                    "type": "string",
                    "description": "Key for the state (e.g., 'current_task', 'preferences')"
                },
                "state_value": {
                    "type": "object",
                    "description": "The state to store"
                },
                "expires_in_hours": {
                    "type": "integer",
                    "description": "Optional expiration time in hours"
                }
            },
            "required": ["agent_id", "state_key", "state_value"]
        }
    },
    {
        "name": "get_agent_state",
        "description": "Retrieve persistent state for an AI agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent identifier"
                },
                "state_key": {
                    "type": "string",
                    "description": "Specific key to retrieve (or omit for all)"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "create_agent_handoff",
        "description": "Create a handoff from one agent to another with context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_agent": {
                    "type": "string",
                    "description": "Agent creating the handoff"
                },
                "to_agent": {
                    "type": "string",
                    "description": "Agent receiving the handoff"
                },
                "context": {
                    "type": "object",
                    "description": "Context to pass"
                },
                "files_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files relevant to the handoff"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this handoff is needed"
                }
            },
            "required": ["from_agent", "to_agent", "context"]
        }
    },
    {
        "name": "get_pending_handoffs",
        "description": "Get pending handoffs waiting for an agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to check handoffs for"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "get_agent_stats",
        "description": "Get statistics about agent usage and sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Specific agent (or omit for all)"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze",
                    "default": 30
                }
            }
        }
    },
    # Phase 22: Emergent Intelligence
    # T-22A-01: Specialist Agent Registry
    {
        "name": "list_specialist_agents",
        "description": "List registered specialist agents (FitJarvis, WorkJarvis, CommJarvis).",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by domain (fitness, work, communication)"
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only show active agents",
                    "default": True
                }
            }
        }
    },
    {
        "name": "get_specialist_routing",
        "description": "Route a query to the most appropriate specialist agent based on content analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to route"
                },
                "context": {
                    "type": "object",
                    "description": "Optional context (recent_domain, etc.)"
                }
            },
            "required": ["query"]
        }
    },
    # T-22C-01: Pattern Generalization Engine
    {
        "name": "generalize_pattern",
        "description": "Extract domain-agnostic patterns from cause-effect observations for cross-domain learning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cause": {
                    "type": "string",
                    "description": "The cause event"
                },
                "effect": {
                    "type": "string",
                    "description": "The effect event"
                },
                "domain": {
                    "type": "string",
                    "description": "Source domain (fitness, work, communication)"
                }
            },
            "required": ["cause", "effect", "domain"]
        }
    },
    {
        "name": "find_transfer_candidates",
        "description": "Find patterns that could be transferred to a new domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_domain": {
                    "type": "string",
                    "description": "Domain to find transfer candidates for"
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold",
                    "default": 0.6
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidates",
                    "default": 10
                }
            },
            "required": ["target_domain"]
        }
    },
    {
        "name": "get_cross_domain_insights",
        "description": "Get insights about cross-domain pattern learning and knowledge transfer.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_pattern_generalization_stats",
        "description": "Get statistics about pattern generalization and cross-domain transfers.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # ============ Phase 22A-02: Agent Registry & Lifecycle ============
    {
        "name": "register_agent",
        "description": "Register a new specialist agent in the registry. Creates or updates an agent with specified domain, tools, and configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Unique identifier (e.g., 'fit_jarvis', 'work_jarvis')"
                },
                "domain": {
                    "type": "string",
                    "description": "Primary domain (e.g., 'fitness', 'work', 'communication')"
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name (e.g., 'FitJarvis')"
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tool names this agent can use"
                },
                "identity_extension": {
                    "type": "object",
                    "description": "Persona/style configuration (expertise, tone, traits)"
                },
                "confidence_threshold": {
                    "type": "number",
                    "description": "Minimum confidence for activation (0.0-1.0)"
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Other agent_ids this agent depends on"
                }
            },
            "required": ["agent_id", "domain"]
        }
    },
    {
        "name": "deregister_agent",
        "description": "Remove an agent from the registry. Fails if other agents depend on it unless force=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to remove"
                },
                "force": {
                    "type": "boolean",
                    "description": "Remove even if other agents depend on it"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "start_agent",
        "description": "Start a registered agent. Automatically starts dependencies first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to start"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "stop_agent",
        "description": "Stop an active agent. Fails if other agents depend on it unless stop_dependents=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to stop"
                },
                "stop_dependents": {
                    "type": "boolean",
                    "description": "Also stop agents that depend on this one"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "pause_agent",
        "description": "Pause an active agent (won't receive new requests but can be resumed quickly).",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to pause"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "resume_agent",
        "description": "Resume a paused agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to resume"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "reset_agent",
        "description": "Reset an agent from error state (clears error count, restarts).",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to reset"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "agent_health_check",
        "description": "Run health check on one or all agents. Returns state, error count, dependencies status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Specific agent to check (omit for all agents)"
                }
            }
        }
    },
    {
        "name": "update_agent_config",
        "description": "Update agent configuration at runtime (tools, identity, confidence threshold).",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to update"
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New tool list"
                },
                "identity_extension": {
                    "type": "object",
                    "description": "New persona/style configuration"
                },
                "confidence_threshold": {
                    "type": "number",
                    "description": "New confidence threshold"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "get_agent_registry_stats",
        "description": "Get overall registry statistics (agents by state, domain, total activations).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # ============ Phase 22A-03: Agent Context Isolation ============
    {
        "name": "create_agent_context",
        "description": "Create an isolated execution context for a specialist agent. Defines tool access, memory namespace, and session boundaries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The specialist agent ID (e.g., 'fit_jarvis')"
                },
                "session_id": {
                    "type": "string",
                    "description": "Current session/conversation ID"
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Whitelist of tools this agent can use"
                },
                "blocked_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Blacklist of tools to block"
                },
                "ttl_minutes": {
                    "type": "integer",
                    "description": "Context lifetime in minutes (default: 60)"
                }
            },
            "required": ["agent_id", "session_id"]
        }
    },
    {
        "name": "get_agent_context",
        "description": "Get the current isolated context for an agent session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The specialist agent ID"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID"
                }
            },
            "required": ["agent_id", "session_id"]
        }
    },
    {
        "name": "store_agent_memory",
        "description": "Store a memory in the agent's isolated namespace. Memories are private by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The specialist agent ID"
                },
                "key": {
                    "type": "string",
                    "description": "Memory key/identifier"
                },
                "value": {
                    "type": "object",
                    "description": "Memory value (any JSON)"
                },
                "memory_type": {
                    "type": "string",
                    "description": "Type: fact, preference, goal, observation"
                },
                "sharing_policy": {
                    "type": "string",
                    "enum": ["private", "domain", "cross", "public"],
                    "description": "Who can access this memory"
                }
            },
            "required": ["agent_id", "key", "value"]
        }
    },
    {
        "name": "recall_agent_memory",
        "description": "Recall memories from the agent's isolated namespace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The specialist agent ID"
                },
                "key": {
                    "type": "string",
                    "description": "Specific memory key (optional)"
                },
                "memory_type": {
                    "type": "string",
                    "description": "Filter by type"
                },
                "include_shared": {
                    "type": "boolean",
                    "description": "Include memories shared by other agents"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "set_agent_boundary",
        "description": "Set a data sharing boundary between two agents. Controls what data can be shared.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_agent": {
                    "type": "string",
                    "description": "Agent sharing the data"
                },
                "target_agent": {
                    "type": "string",
                    "description": "Agent receiving access"
                },
                "data_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Types of data that can be shared"
                },
                "direction": {
                    "type": "string",
                    "enum": ["read", "write", "both"],
                    "description": "Access direction"
                }
            },
            "required": ["source_agent", "target_agent"]
        }
    },
    {
        "name": "get_agent_boundaries",
        "description": "Get all data sharing boundaries for an agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent to check boundaries for"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "check_tool_access",
        "description": "Check if an agent is allowed to use a specific tool in current context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The specialist agent ID"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Tool to check access for"
                }
            },
            "required": ["agent_id", "session_id", "tool_name"]
        }
    },
    {
        "name": "get_isolation_stats",
        "description": "Get statistics about agent context isolation (contexts, memories, boundaries).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # ============ Phase 22A-04: FitJarvis (Fitness Agent) ============
    {
        "name": "log_workout",
        "description": "Log a workout session. Tracks type, duration, intensity, calories, and optionally strength training details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_type": {
                    "type": "string",
                    "enum": ["strength", "cardio", "hiit", "yoga", "stretching", "sports"],
                    "description": "Type of workout"
                },
                "activity": {
                    "type": "string",
                    "description": "Specific activity (e.g., 'running', 'bench press', 'swimming')"
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes"
                },
                "intensity": {
                    "type": "string",
                    "enum": ["low", "moderate", "high", "max"],
                    "description": "Workout intensity"
                },
                "calories_burned": {
                    "type": "integer",
                    "description": "Calories burned (auto-estimated if not provided)"
                },
                "distance_km": {
                    "type": "number",
                    "description": "Distance for cardio workouts"
                },
                "sets_reps": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Strength training details: [{exercise, sets, reps, weight_kg}]"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes"
                },
                "mood_before": {
                    "type": "string",
                    "description": "Mood before workout"
                },
                "mood_after": {
                    "type": "string",
                    "description": "Mood after workout"
                },
                "energy_level": {
                    "type": "integer",
                    "description": "Energy level 1-10"
                }
            },
            "required": ["workout_type", "activity"]
        }
    },
    {
        "name": "get_fitness_trends",
        "description": "Get fitness trends and analytics over a period. Shows workout stats, calories, nutrition, and body metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["week", "month", "quarter", "year"],
                    "description": "Time period for trends"
                },
                "trend_type": {
                    "type": "string",
                    "enum": ["workouts", "calories", "nutrition", "weight", "all"],
                    "description": "Type of trends to show"
                }
            }
        }
    },
    {
        "name": "track_nutrition",
        "description": "Track a meal with food items and macros. Calculates totals and shows daily progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                    "description": "Type of meal"
                },
                "food_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "calories": {"type": "integer"},
                            "protein_g": {"type": "number"},
                            "carbs_g": {"type": "number"},
                            "fat_g": {"type": "number"}
                        }
                    },
                    "description": "List of food items with nutritional info"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes"
                }
            },
            "required": ["meal_type", "food_items"]
        }
    },
    {
        "name": "suggest_exercise",
        "description": "Get personalized exercise suggestions based on criteria and recent workout history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["strength", "cardio", "flexibility", "balance"],
                    "description": "Exercise category"
                },
                "muscle_groups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target muscle groups (e.g., ['chest', 'triceps'])"
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["beginner", "intermediate", "advanced"],
                    "description": "Difficulty level"
                },
                "equipment": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Available equipment"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of suggestions (default: 5)"
                }
            }
        }
    },
    {
        "name": "get_fitness_stats",
        "description": "Get overall fitness statistics including total workouts, calories, streak, and active goals.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # ============ Phase 22A-05: WorkJarvis (Work Agent) ============
    {
        "name": "prioritize_tasks",
        "description": "Prioritize tasks using Eisenhower matrix. Returns DO/SCHEDULE/DELEGATE/ELIMINATE quadrants.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "importance": {"type": "integer", "description": "1-100"},
                            "urgency": {"type": "integer", "description": "1-100"},
                            "estimated_minutes": {"type": "integer"},
                            "due_date": {"type": "string"},
                            "energy_required": {"type": "string", "enum": ["low", "medium", "high"]}
                        }
                    },
                    "description": "Tasks to add/update before prioritizing"
                },
                "context": {
                    "type": "string",
                    "description": "Current context (home, office, calls, etc.)"
                },
                "available_minutes": {
                    "type": "integer",
                    "description": "Time available for work"
                },
                "energy_level": {
                    "type": "integer",
                    "description": "Current energy 1-10"
                }
            }
        }
    },
    {
        "name": "estimate_effort",
        "description": "Estimate effort for a task with learning from past estimates. Returns calibrated estimate with confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "What needs to be done"
                },
                "task_type": {
                    "type": "string",
                    "enum": ["coding", "writing", "review", "meeting", "admin", "general"],
                    "description": "Type of task"
                },
                "complexity": {
                    "type": "string",
                    "enum": ["simple", "moderate", "complex", "unknown"],
                    "description": "Task complexity"
                }
            },
            "required": ["task_description"]
        }
    },
    {
        "name": "track_focus_time",
        "description": "Track focus sessions (Pomodoro-style). Start, end, or check status of focus sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "end", "status"],
                    "description": "Action to perform"
                },
                "task_title": {
                    "type": "string",
                    "description": "What you're working on (for start)"
                },
                "project": {
                    "type": "string",
                    "description": "Project name"
                },
                "planned_minutes": {
                    "type": "integer",
                    "description": "How long you plan to focus (default: 25)"
                },
                "category": {
                    "type": "string",
                    "enum": ["deep_work", "meetings", "admin", "creative", "learning"],
                    "description": "Session category"
                },
                "focus_quality": {
                    "type": "integer",
                    "description": "1-10 self-assessment (for end)"
                }
            }
        }
    },
    {
        "name": "suggest_breaks",
        "description": "Get break suggestions based on focus time and energy patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_focus_minutes": {
                    "type": "integer",
                    "description": "How long you've been focusing"
                },
                "energy_level": {
                    "type": "integer",
                    "description": "Current energy 1-10"
                },
                "last_break_minutes_ago": {
                    "type": "integer",
                    "description": "Minutes since last break"
                }
            }
        }
    },
    {
        "name": "get_work_stats",
        "description": "Get work/productivity statistics for today, week, or month.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period"
                }
            }
        }
    },
    # ============ Phase 22A-06: CommJarvis (Communication Agent) ============
    {
        "name": "triage_inbox",
        "description": "Triage inbox messages by priority. Categorizes as urgent/important/fyi and suggests actions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "New messages to triage [{source, sender_name, sender_email, subject, preview}]"
                },
                "source": {
                    "type": "string",
                    "description": "Filter by source (gmail, telegram, etc.)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max items to return"
                }
            }
        }
    },
    {
        "name": "draft_response",
        "description": "Draft a response with relationship context. Uses past interactions to personalize.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient name or email"
                },
                "context": {
                    "type": "string",
                    "description": "What to respond about"
                },
                "tone": {
                    "type": "string",
                    "enum": ["formal", "friendly", "brief", "detailed"],
                    "description": "Response tone"
                }
            },
            "required": ["to", "context"]
        }
    },
    {
        "name": "track_relationship",
        "description": "Track and manage relationships. Add, update, get, list, or search contacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "get", "list", "search"],
                    "description": "Action to perform"
                },
                "contact_name": {
                    "type": "string",
                    "description": "Contact's name"
                },
                "contact_email": {
                    "type": "string",
                    "description": "Contact's email"
                },
                "relationship_type": {
                    "type": "string",
                    "enum": ["friend", "family", "colleague", "client", "mentor", "acquaintance"],
                    "description": "Type of relationship"
                },
                "company": {
                    "type": "string",
                    "description": "Company name"
                },
                "importance": {
                    "type": "integer",
                    "description": "Importance 1-100"
                },
                "notes": {
                    "type": "string",
                    "description": "Notes about relationship"
                }
            }
        }
    },
    {
        "name": "schedule_followup",
        "description": "Schedule a followup with a contact. Sets reminder for check-in, thank you, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_name": {
                    "type": "string",
                    "description": "Who to follow up with"
                },
                "reason": {
                    "type": "string",
                    "description": "Why following up"
                },
                "due_date": {
                    "type": "string",
                    "description": "When (YYYY-MM-DD)"
                },
                "followup_type": {
                    "type": "string",
                    "enum": ["check_in", "thank_you", "request", "reminder", "birthday"],
                    "description": "Type of followup"
                },
                "channel": {
                    "type": "string",
                    "enum": ["email", "call", "message"],
                    "description": "How to follow up"
                }
            },
            "required": ["contact_name", "reason", "due_date"]
        }
    },
    {
        "name": "get_comm_stats",
        "description": "Get communication statistics - interactions, inbox, relationships, pending followups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period"
                }
            }
        }
    },
    # Phase 22A-07: Intent-Based Agent Routing
    {
        "name": "route_query",
        "description": "Route a query to the appropriate specialist agent based on intent classification. Returns routing decision with strategy, agent assignment, and confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "User query to route"
                },
                "context": {
                    "type": "object",
                    "description": "Optional context (session_id, time_of_day, recent_agent)"
                },
                "force_agent": {
                    "type": "string",
                    "description": "Force routing to specific agent (fit_jarvis, work_jarvis, comm_jarvis, jarvis_core)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "classify_intent",
        "description": "Classify a query's intent and get confidence scores for each domain (fitness, work, communication, general).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query to classify"
                },
                "context": {
                    "type": "object",
                    "description": "Optional context for classification"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "test_routing",
        "description": "Test routing for multiple queries (for debugging). Returns routing decisions for each query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of queries to test"
                }
            },
            "required": ["queries"]
        }
    },
    {
        "name": "get_routing_stats",
        "description": "Get routing statistics - strategies used, agents routed to, average confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)"
                }
            }
        }
    },
    # Phase 22A-08: Multi-Agent Collaboration
    {
        "name": "execute_collaboration",
        "description": "Execute a multi-agent collaboration where multiple specialists work together on a query. Use for complex tasks spanning multiple domains.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query for agents to collaborate on"
                },
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of agent names (fit_jarvis, work_jarvis, comm_jarvis)"
                },
                "collaboration_type": {
                    "type": "string",
                    "enum": ["parallel", "sequential", "primary_secondary"],
                    "description": "How agents should collaborate"
                },
                "context": {
                    "type": "object",
                    "description": "Optional shared context"
                }
            },
            "required": ["query", "agents"]
        }
    },
    {
        "name": "get_collaboration_stats",
        "description": "Get statistics on multi-agent collaborations - types, success rates, timing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)"
                }
            }
        }
    },
    # Phase 22A-09: Agent Delegation Protocol
    {
        "name": "delegate_task",
        "description": "Delegate a complex task to specialist agents. Jarvis decomposes the task into subtasks and delegates each to the appropriate specialist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Complex query to delegate"
                },
                "context": {
                    "type": "object",
                    "description": "Optional context for delegation"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_delegation_status",
        "description": "Get status of a delegation session including all subtask results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "integer",
                    "description": "Delegation session ID"
                }
            },
            "required": ["session_id"]
        }
    },
    {
        "name": "get_delegation_stats",
        "description": "Get delegation statistics - sessions, subtasks, agent usage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)"
                }
            }
        }
    },
    # Phase 22B-02: Message Queue System
    {
        "name": "enqueue_message",
        "description": "Add a message to an agent's queue for async processing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queue_name": {
                    "type": "string",
                    "description": "Target queue (agent name)"
                },
                "payload": {
                    "type": "object",
                    "description": "Message content"
                },
                "priority": {
                    "type": "string",
                    "enum": ["urgent", "high", "normal", "low", "batch"],
                    "description": "Message priority"
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay before processing"
                }
            },
            "required": ["queue_name", "payload"]
        }
    },
    {
        "name": "dequeue_message",
        "description": "Get messages from a queue for processing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queue_name": {
                    "type": "string",
                    "description": "Queue to read from"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to fetch"
                }
            },
            "required": ["queue_name"]
        }
    },
    {
        "name": "get_queue_stats",
        "description": "Get message queue statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queue_name": {
                    "type": "string",
                    "description": "Queue name (optional, all queues if omitted)"
                }
            }
        }
    },
    # Phase 22B-03: Request/Response Patterns
    {
        "name": "agent_request",
        "description": "Make a synchronous request to another agent and wait for response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_agent": {
                    "type": "string",
                    "description": "Requesting agent"
                },
                "to_agent": {
                    "type": "string",
                    "description": "Target agent"
                },
                "method": {
                    "type": "string",
                    "description": "Method to call"
                },
                "params": {
                    "type": "object",
                    "description": "Method parameters"
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Timeout in milliseconds"
                }
            },
            "required": ["from_agent", "to_agent", "method"]
        }
    },
    {
        "name": "scatter_gather",
        "description": "Send request to multiple agents and gather all responses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_agent": {
                    "type": "string",
                    "description": "Requesting agent"
                },
                "to_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of target agents"
                },
                "method": {
                    "type": "string",
                    "description": "Method to call"
                },
                "params": {
                    "type": "object",
                    "description": "Shared parameters"
                }
            },
            "required": ["from_agent", "to_agents", "method"]
        }
    },
    {
        "name": "get_circuit_status",
        "description": "Get circuit breaker status for agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Agent name (optional, all if omitted)"
                }
            }
        }
    },
    # Phase 22B-07/08/09: Coordination Protocols
    {
        "name": "propose_agent_negotiation",
        "description": "Create a coordination negotiation for a task across candidate agents using claim, capability, auction, or hierarchical strategy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the negotiation"},
                "initiator_agent": {"type": "string", "description": "Agent starting the negotiation"},
                "candidate_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Candidate agents for this task"
                },
                "strategy": {
                    "type": "string",
                    "enum": ["claim_based", "capability_based", "auction_based", "hierarchical"],
                    "description": "Negotiation strategy"
                },
                "original_query": {"type": "string", "description": "Optional source query"},
                "context": {"type": "object", "description": "Optional negotiation context"}
            },
            "required": ["title", "initiator_agent", "candidate_agents"]
        }
    },
    {
        "name": "claim_agent_task",
        "description": "Submit a claim for an agent to handle a negotiated task, optionally with a capability score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "string", "description": "Negotiation ID"},
                "agent_name": {"type": "string", "description": "Claiming agent"},
                "capability_score": {"type": "number", "description": "Optional capability score"},
                "rationale": {"type": "string", "description": "Optional rationale"},
                "metadata": {"type": "object", "description": "Optional metadata"}
            },
            "required": ["negotiation_id", "agent_name"]
        }
    },
    {
        "name": "submit_agent_bid",
        "description": "Submit an auction bid score for an agent negotiation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "string", "description": "Negotiation ID"},
                "agent_name": {"type": "string", "description": "Bidding agent"},
                "bid_score": {"type": "number", "description": "Bid score"},
                "rationale": {"type": "string", "description": "Optional rationale"},
                "metadata": {"type": "object", "description": "Optional metadata"}
            },
            "required": ["negotiation_id", "agent_name", "bid_score"]
        }
    },
    {
        "name": "resolve_agent_conflict",
        "description": "Resolve a contested negotiation via core arbitration or explicit preferred agent selection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "string", "description": "Negotiation ID"},
                "arbitrator_agent": {"type": "string", "description": "Arbitrating agent"},
                "preferred_agent": {"type": "string", "description": "Optional selected winner"},
                "resolution_note": {"type": "string", "description": "Optional note"}
            },
            "required": ["negotiation_id"]
        }
    },
    {
        "name": "record_consensus_vote",
        "description": "Record an approve/reject/abstain vote toward consensus on a negotiation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "string", "description": "Negotiation ID"},
                "agent_name": {"type": "string", "description": "Voting agent"},
                "vote_value": {
                    "type": "string",
                    "enum": ["approve", "reject", "abstain"],
                    "description": "Vote value"
                },
                "rationale": {"type": "string", "description": "Optional rationale"}
            },
            "required": ["negotiation_id", "agent_name", "vote_value"]
        }
    },
    {
        "name": "get_coordination_status",
        "description": "Get negotiation status including claims, bids, votes, and current resolution state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "string", "description": "Negotiation ID"}
            },
            "required": ["negotiation_id"]
        }
    },
    {
        "name": "get_coordination_stats",
        "description": "Get aggregate stats for negotiation, conflict resolution, and consensus activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days to analyze (default: 7)"}
            }
        }
    },
    # Phase 22B-04/05/06: Shared Context + Subscriptions + Privacy Boundaries
    {
        "name": "publish_agent_context",
        "description": "Publish context to the cross-agent shared context pool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_agent": {
                    "type": "string",
                    "description": "Publishing agent"
                },
                "context_key": {
                    "type": "string",
                    "description": "Context key"
                },
                "context_value": {
                    "type": "object",
                    "description": "Context payload"
                },
                "visibility": {
                    "type": "string",
                    "enum": ["global", "domain", "private", "temporary"],
                    "description": "Visibility level"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain hint (optional)"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session scope for temporary context"
                },
                "ttl_minutes": {
                    "type": "integer",
                    "description": "Optional time-to-live in minutes"
                }
            },
            "required": ["source_agent", "context_key", "context_value"]
        }
    },
    {
        "name": "subscribe_agent_context",
        "description": "Create or update an agent context subscription profile.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Subscriber agent"
                },
                "visibility_levels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed visibility levels"
                },
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Domain filters"
                },
                "source_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source-agent filters"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tag filters"
                },
                "include_temporary": {
                    "type": "boolean",
                    "description": "Whether temporary context should be included"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "read_agent_context",
        "description": "Read shared context visible to an agent based on subscriptions and privacy boundaries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Reader agent"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (for temporary visibility)"
                },
                "since_minutes": {
                    "type": "integer",
                    "description": "How far back to read"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries"
                }
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "set_context_privacy_boundary",
        "description": "Set explicit source->target privacy boundaries for context sharing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_agent": {
                    "type": "string",
                    "description": "Source agent"
                },
                "target_agent": {
                    "type": "string",
                    "description": "Target agent"
                },
                "allowed_levels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed visibility levels"
                },
                "allowed_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional key allowlist"
                },
                "denied_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional key denylist"
                },
                "active": {
                    "type": "boolean",
                    "description": "Whether boundary is active"
                }
            },
            "required": ["source_agent", "target_agent"]
        }
    },
    {
        "name": "get_context_pool_stats",
        "description": "Get context pool/subscription/privacy statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)"
                }
            }
        }
    }
,
    # ============ AUTO-GENERATED DEFINITIONS (T-020 Phase 2) ============
    
    # Ollama Tools
    {
        "name": "ask_ollama",
        "description": "Ask Ollama a question and get an answer. Jarvis's free local sub-assistant for simple tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The question or prompt to send to Ollama"},
                "task_type": {"type": "string", "description": "Type of task (analyze, summarize, etc.)", "default": "analyze"},
                "system_prompt": {"type": "string", "description": "Optional system prompt"},
                "max_tokens": {"type": "integer", "description": "Maximum tokens in response"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "delegate_ollama_task",
        "description": "Queue a task for local Ollama execution (async).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "Type of task"},
                "instructions": {"type": "string", "description": "Task instructions"},
                "input_text": {"type": "string", "description": "Input text to process"},
                "model": {"type": "string", "description": "Ollama model to use"},
                "max_tokens": {"type": "integer", "description": "Max tokens", "default": 1000}
            },
            "required": ["task_type", "instructions"]
        }
    },
    {
        "name": "get_ollama_task_status",
        "description": "Get status of a queued Ollama task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to check"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "cancel_ollama_task",
        "description": "Cancel a pending Ollama task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to cancel"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_ollama_queue_status",
        "description": "Get summary of pending Ollama tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max tasks to return", "default": 10}
            }
        }
    },
    {
        "name": "get_ollama_callback_result",
        "description": "Get result of a completed async Ollama task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
                "recent_only": {"type": "boolean", "description": "Only recent results", "default": False}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "ollama_python",
        "description": "Generate and execute Python code via local Ollama.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "What the code should do"},
                "context": {"type": "string", "description": "Additional context"}
            },
            "required": ["task_description"]
        }
    },
    
    # Timer Tools
    {
        "name": "set_timer",
        "description": "Create a reminder timer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "delay_minutes": {"type": "integer", "description": "Minutes until reminder"},
                "delay_seconds": {"type": "integer", "description": "Seconds until reminder"},
                "due_at": {"type": "string", "description": "ISO datetime for reminder"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "list_timers",
        "description": "List active timers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
                "limit": {"type": "integer", "description": "Max timers to return", "default": 50}
            }
        }
    },
    {
        "name": "cancel_timer",
        "description": "Cancel an existing timer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timer_id": {"type": "string", "description": "The timer ID to cancel"}
            },
            "required": ["timer_id"]
        }
    },
    
    # Subagent Tools
    {
        "name": "delegate_to_subagent",
        "description": "Delegate a task to a sub-agent with tool access.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Sub-agent to use", "default": "ollama"},
                "instructions": {"type": "string", "description": "Task instructions"},
                "input_text": {"type": "string", "description": "Input to process"},
                "tools": {"type": "array", "description": "Tools the sub-agent can use"},
                "sync": {"type": "boolean", "description": "Wait for result", "default": False}
            },
            "required": ["instructions"]
        }
    },
    {
        "name": "get_subagent_result",
        "description": "Get result of a delegated sub-agent task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "list_subagents",
        "description": "List available sub-agents and their capabilities.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    
    # Identity Tools
    {
        "name": "get_self_model",
        "description": "Get Jarvis's current self-model and identity.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "evolve_identity",
        "description": "Evolve Jarvis's identity based on learnings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "evolution_type": {"type": "string", "description": "Type of evolution"},
                "field": {"type": "string", "description": "Field to evolve"},
                "new_value": {"type": "string", "description": "New value"},
                "reason": {"type": "string", "description": "Why this evolution"}
            },
            "required": ["evolution_type", "field", "new_value", "reason"]
        }
    },
    {
        "name": "get_relationship",
        "description": "Get relationship memory for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "User ID", "default": 1}
            }
        }
    },
    {
        "name": "update_relationship",
        "description": "Update relationship memory for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "User ID"},
                "updates": {"type": "object", "description": "Fields to update"}
            },
            "required": ["updates"]
        }
    },
    {
        "name": "get_learning_patterns",
        "description": "Get validated learning patterns from cross-session analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_confidence": {"type": "number", "description": "Minimum confidence", "default": 0.6}
            }
        }
    },
    {
        "name": "log_experience",
        "description": "Log an experience for cross-session learning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "experience_type": {"type": "string", "description": "Type of experience"},
                "content": {"type": "string", "description": "Experience content"},
                "outcome": {"type": "string", "description": "Outcome of experience"}
            },
            "required": ["experience_type", "content"]
        }
    },
    {
        "name": "record_session_learning",
        "description": "Record learnings from a completed session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "learnings": {"type": "array", "description": "List of learnings"}
            }
        }
    },
    
    # Learning/Memory Tools
    {
        "name": "store_context",
        "description": "Store a context value for later retrieval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Context key"},
                "value": {"type": "string", "description": "Context value"},
                "context_type": {"type": "string", "description": "Type of context", "default": "general"}
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "recall_context",
        "description": "Recall a stored context value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Context key"},
                "context_type": {"type": "string", "description": "Type of context"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "forget_context",
        "description": "Delete stored context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Context key"},
                "context_type": {"type": "string", "description": "Type of context"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "store_contexts_batch",
        "description": "Store multiple context values at once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contexts": {"type": "array", "description": "List of {key, value, type} objects"}
            },
            "required": ["contexts"]
        }
    },
    {
        "name": "record_learning",
        "description": "Record a learning/insight for pattern analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Learning category"},
                "content": {"type": "string", "description": "What was learned"},
                "confidence": {"type": "number", "description": "Confidence level", "default": 0.8}
            },
            "required": ["category", "content"]
        }
    },
    {
        "name": "record_learnings_batch",
        "description": "Record multiple learnings at once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learnings": {"type": "array", "description": "List of learning objects"}
            },
            "required": ["learnings"]
        }
    },
    {
        "name": "get_learnings",
        "description": "Retrieve recorded learnings/insights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category"},
                "days_back": {"type": "integer", "description": "Days to look back", "default": 30},
                "limit": {"type": "integer", "description": "Max results", "default": 20}
            }
        }
    },
    
    # Sandbox Tools
    {
        "name": "execute_python",
        "description": "Execute Python code in the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "reason": {"type": "string", "description": "Why this code is needed"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "request_python_sandbox",
        "description": "Queue a sandbox request for manual approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code"},
                "reason": {"type": "string", "description": "Purpose of the code"},
                "timeout_seconds": {"type": "integer", "description": "Execution timeout", "default": 30}
            },
            "required": ["code", "reason"]
        }
    },
    {
        "name": "promote_sandbox_tool",
        "description": "Promote a sandbox tool to production.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Tool to promote"},
                "reason": {"type": "string", "description": "Why promote"}
            },
            "required": ["tool_name"]
        }
    },
    {
        "name": "write_dynamic_tool",
        "description": "Create a new dynamic tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tool name"},
                "code": {"type": "string", "description": "Tool implementation"},
                "description": {"type": "string", "description": "Tool description"}
            },
            "required": ["name", "code", "description"]
        }
    },
    
    # API Context Tools
    {
        "name": "list_api_context_packs",
        "description": "List available API context packs.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "read_api_context_pack",
        "description": "Read an API context pack.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pack_name": {"type": "string", "description": "Name of the pack"}
            },
            "required": ["pack_name"]
        }
    },
    {
        "name": "search_api_context_packs",
        "description": "Search API context packs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }

]


# ============ Tool Implementations ============


def set_current_user_id(user_id: int):
    """Set current user ID for project tools"""
    global _current_user_id
    _current_user_id = user_id


def _is_quiet_hours() -> bool:
    """Check if current time falls within quiet hours (local TZ)."""
    import pytz
    from . import config

    tz = pytz.timezone(os.environ.get("TZ", "Europe/Zurich"))
    now = datetime.now(tz)

    def _parse_hhmm(value: str) -> int:
        try:
            parts = value.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0

    start_min = _parse_hhmm(config.PROACTIVE_QUIET_HOURS_START)
    end_min = _parse_hhmm(config.PROACTIVE_QUIET_HOURS_END)
    now_min = now.hour * 60 + now.minute

    if start_min == end_min:
        return False

    # Quiet hours can wrap over midnight
    if start_min < end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def _proactive_level_threshold(level: int, base_threshold: float) -> float:
    """Map proactivity level to confidence threshold."""
    if level <= 1:
        return 1.01  # effectively disabled
    if level == 2:
        return 0.9
    if level == 3:
        return base_threshold
    if level == 4:
        return 0.5
    return 0.3


def _check_proactive_rate_limits(now: datetime, max_per_day: int, cooldown_minutes: int) -> Dict[str, Any]:
    """Simple per-process rate limits for proactive hints."""
    global _proactive_daily_count, _proactive_daily_date, _proactive_last_hint_ts

    today = now.date().isoformat()
    if _proactive_daily_date != today:
        _proactive_daily_date = today
        _proactive_daily_count = 0

    if max_per_day > 0 and _proactive_daily_count >= max_per_day:
        return {
            "allowed": False,
            "reason": "daily_limit",
            "message": f"Daily proactive limit reached ({max_per_day})."
        }

    if _proactive_last_hint_ts is not None and cooldown_minutes > 0:
        delta_min = (now.timestamp() - _proactive_last_hint_ts) / 60.0
        if delta_min < cooldown_minutes:
            return {
                "allowed": False,
                "reason": "cooldown",
                "message": f"Cooldown active ({cooldown_minutes} min)."
            }

    return {"allowed": True}


def _get_confidence_score(confidence: str) -> float:
    """Map confidence string to float score."""
    confidence_map = {"low": 0.5, "medium": 0.7, "high": 0.9}
    return confidence_map.get(confidence.lower(), 0.7)


def _translate_path(file_path: str) -> str:
    file_path = os.path.normpath(file_path)
    brain_root = os.environ.get("BRAIN_ROOT", "/brain")
    running_in_docker = os.path.exists("/.dockerenv") or brain_root.startswith("/brain")

    if running_in_docker and file_path.startswith("/data/"):
        translated_candidates = [
            file_path.replace("/data/", f"{brain_root}/system/data/", 1),
            file_path.replace("/data/", f"{brain_root}/data/", 1),
        ]
        for translated in translated_candidates:
            if os.path.exists(os.path.dirname(translated)):
                return translated
        if not os.path.exists("/data"):
            return translated_candidates[0]
        return file_path

    if running_in_docker and file_path.startswith("/Volumes/BRAIN/"):
        translated = file_path.replace("/Volumes/BRAIN/", f"{brain_root}/")
        if translated.startswith(f"{brain_root}/data/") and not os.path.exists(f"{brain_root}/data"):
            return translated.replace(f"{brain_root}/data/", f"{brain_root}/system/data/", 1)
        return translated

    if not running_in_docker and file_path.startswith("/data/"):
        translated_candidates = [
            file_path.replace("/data/", "/Volumes/BRAIN/system/data/", 1),
            file_path.replace("/data/", "/Volumes/BRAIN/data/", 1),
        ]
        for translated in translated_candidates:
            if os.path.exists(os.path.dirname(translated)):
                return translated
        return translated_candidates[0]

    if not running_in_docker and file_path.startswith("/brain/"):
        return file_path.replace("/brain/", "/Volumes/BRAIN/")

    return file_path


def _is_allowed_path(file_path: str) -> bool:
    try:
        abs_path = os.path.abspath(file_path)
    except Exception:
        return False

    for allowed in ALLOWED_FILE_PATHS:
        try:
            allowed_abs = os.path.abspath(allowed)
            if os.path.commonpath([abs_path, allowed_abs]) == allowed_abs:
                return True
        except ValueError:
            continue

    return False


def _is_blocked_path(file_path: str) -> bool:
    file_lower = file_path.lower()
    return any(blocked in file_lower for blocked in BLOCKED_PATTERNS)


def _get_audit_dir(file_path: str) -> str:
    if file_path.startswith("/brain/"):
        return AUDIT_DIR_DOCKER
    return AUDIT_DIR_MAC


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _requires_write_approval(file_path: str, approval_paths: List[str]) -> bool:
    if not approval_paths:
        return False
    for path in approval_paths:
        if path and file_path.startswith(path):
            return True
    return False


_write_minute_window = None
_write_hour_window = None
_write_minute_count = 0
_write_hour_count = 0


def _check_write_rate_limits(max_per_minute: int, max_per_hour: int) -> Dict[str, Any]:
    """Simple per-process rate limits for file writes."""
    global _write_minute_window, _write_hour_window, _write_minute_count, _write_hour_count

    now = time.time()
    minute_window = int(now // 60)
    hour_window = int(now // 3600)

    if _write_minute_window != minute_window:
        _write_minute_window = minute_window
        _write_minute_count = 0

    if _write_hour_window != hour_window:
        _write_hour_window = hour_window
        _write_hour_count = 0

    if max_per_minute > 0 and _write_minute_count >= max_per_minute:
        return {
            "allowed": False,
            "reason": "minute_limit",
            "message": f"Write rate limit reached ({max_per_minute}/min)."
        }

    if max_per_hour > 0 and _write_hour_count >= max_per_hour:
        return {
            "allowed": False,
            "reason": "hour_limit",
            "message": f"Write rate limit reached ({max_per_hour}/hour)."
        }

    _write_minute_count += 1
    _write_hour_count += 1

    return {"allowed": True}


def _read_single_file(file_path: str, max_lines: int) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = []
        for i, line in enumerate(f):
            if i >= max_lines:
                break
            lines.append(line.rstrip())

    stat = os.stat(file_path)
    file_size = stat.st_size
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    _, ext = os.path.splitext(file_path)

    return {
        "success": True,
        "file_path": file_path,
        "content": "\n".join(lines),
        "lines_read": len(lines),
        "truncated": len(lines) >= max_lines,
        "file_size": file_size,
        "modified": modified,
        "extension": ext.lower(),
    }


# Phase 18.3 & 6 tools MOVED to tool_modules/self_inspection_tools.py (T-020 refactor)
# Implementations: tool_analyze_cross_session_patterns, tool_optimize_system_prompt, tool_enable_experimental_feature



def _tool_ollama_unavailable(**kwargs) -> Dict[str, Any]:
    return {"error": "ollama tools unavailable"}


tool_delegate_ollama_task = _tool_ollama_unavailable
tool_get_ollama_task_status = _tool_ollama_unavailable
tool_get_ollama_queue_status = _tool_ollama_unavailable
tool_cancel_ollama_task = _tool_ollama_unavailable
tool_get_ollama_callback_result = _tool_ollama_unavailable
tool_ask_ollama = _tool_ollama_unavailable
tool_ollama_python = _tool_ollama_unavailable

# Timer tools MOVED to tool_modules/timer_tools.py (T006 refactor)
# Implementations: tool_set_timer, tool_cancel_timer, tool_list_timers


# Sandbox tools MOVED to tool_modules/sandbox_tools.py (T006 refactor)
# Implementations: tool_request_python_sandbox, tool_execute_python


# Sub-Agent Framework Tools MOVED to tool_modules/subagent_tools.py (T006 refactor)
# Implementations: tool_delegate_to_subagent, tool_get_subagent_result, tool_list_subagents

# Self-Inspection Tools (Phase 6) MOVED to tool_modules/self_inspection_tools.py (T-020 refactor)
# Implementations: tool_validate_tool_registry, tool_get_response_metrics


# ============ Tool Registry ============

TOOL_REGISTRY: Dict[str, Callable] = {
    "search_knowledge": tool_search_knowledge,
    "search_emails": tool_search_emails,
    "search_chats": tool_search_chats,
    "get_recent_activity": tool_get_recent_activity,
    "web_search": tool_web_search,
    "remember_fact": tool_remember_fact,
    "recall_facts": tool_recall_facts,
    "get_calendar_events": tool_get_calendar_events,
    "create_calendar_event": tool_create_calendar_event,
    "get_gmail_messages": tool_get_gmail_messages,
    "send_email": tool_send_email,
    "no_tool_needed": tool_no_tool_needed,
    "request_out_of_scope": tool_request_out_of_scope,
    # Context Persistence tools
    "remember_conversation_context": tool_remember_conversation_context,
    "recall_conversation_history": tool_recall_conversation_history,
    "complete_pending_action": tool_complete_pending_action,
    # Knowledge Layer tools
    "propose_knowledge_update": tool_propose_knowledge_update,
    "get_person_context": tool_get_person_context,
    # Project Management tools
    "add_project": tool_add_project,
    "list_projects": tool_list_projects,
    "update_project_status": tool_update_project_status,
    # Thread Management tools (ADHD)
    "manage_thread": tool_manage_thread,
    # Direct File Access
    "read_project_file": tool_read_project_file,
    "write_project_file": tool_write_project_file,
    "read_my_source_files": tool_read_my_source_files,
    # Self-Inspection Tools (Phase 6)
    "read_own_code": tool_read_own_code,
    "read_roadmap_and_tasks": tool_read_roadmap_and_tasks,
    "list_own_source_files": tool_list_own_source_files,
    # Proactive Initiative
    "proactive_hint": tool_proactive_hint,
    # Phase 18.3: Self-Optimization Tools
    # optimize_system_prompt, enable_experimental_feature, analyze_cross_session_patterns
    # MOVED to tool_modules/self_inspection_tools.py (T-020 refactor) - loaded via module loader
    "introspect_capabilities": tool_introspect_capabilities,
    "system_health_check": tool_system_health_check,
    "get_development_status": tool_get_development_status,
    "list_label_registry": tool_list_label_registry,
    "upsert_label_registry": tool_upsert_label_registry,
    "delete_label_registry": tool_delete_label_registry,
    "label_hygiene": tool_label_hygiene,
    "mind_snapshot": tool_mind_snapshot,
    # validate_tool_registry, get_response_metrics MOVED to tool_modules/self_inspection_tools.py (T-020 refactor)
    "memory_diagnostics": tool_memory_diagnostics,
    "context_window_analysis": tool_context_window_analysis,
    "benchmark_tool_calls": tool_benchmark_tool_calls,
    "compare_code_versions": tool_compare_code_versions,
    "conversation_continuity_test": tool_conversation_continuity_test,
    "response_quality_metrics": tool_response_quality_metrics,
    "proactivity_score": tool_proactivity_score,
    "self_validation_dashboard": tool_self_validation_dashboard,
    "self_validation_pulse": tool_self_validation_pulse,
    "list_available_tools": tool_list_available_tools,
    "record_decision_outcome": tool_record_decision_outcome,
    "get_git_events": tool_get_git_events,
    # Ollama tools MOVED to tool_modules/ollama_tools.py (T006 refactor)
    # Timer tools MOVED to tool_modules/timer_tools.py (T006 refactor)
    # Subagent tools MOVED to tool_modules/subagent_tools.py (T006 refactor)
    # Sandbox tools MOVED to tool_modules/sandbox_tools.py (T006 refactor)
    # Learning & Memory tools MOVED to tool_modules/learning_memory_tools.py (T006 refactor)
    # Tool Autonomy (Phase 19.6)
    "manage_tool_registry": tool_manage_tool_registry,
    "add_decision_rule": tool_add_decision_rule,
    "get_autonomy_status": tool_get_autonomy_status,
    "get_execution_stats": tool_get_execution_stats,
    # Jarvis Wishes: Visual Thinking & Deep Memory
    "generate_diagram": tool_generate_diagram,
    "recall_with_timeframe": tool_recall_with_timeframe,
    "get_predictive_context": tool_get_predictive_context,
    # Jarvis Wishes: Image Generation (Tier 3)
    "generate_image": tool_generate_image,
    # Phase 20: Identity Evolution MOVED to tool_modules/identity_tools.py (T006 refactor)
    # Phase 21: Intelligent System Evolution
    # T-21A-01: Smart Tool Chains
    "get_tool_chain_suggestions": tool_get_tool_chain_suggestions,
    "get_popular_tool_chains": tool_get_popular_tool_chains,
    # T-21A-04: Tool Performance Learning
    "get_tool_performance": tool_get_tool_performance,
    "get_tool_recommendations": tool_get_tool_recommendations,
    # T-21B-01: CK-Track (Causal Knowledge)
    "record_causal_observation": tool_record_causal_observation,
    "predict_from_cause": tool_predict_from_cause,
    "get_causal_patterns": tool_get_causal_patterns,
    # T-21C-01: Agent State Persistence
    "set_agent_state": tool_set_agent_state,
    "get_agent_state": tool_get_agent_state,
    "create_agent_handoff": tool_create_agent_handoff,
    "get_pending_handoffs": tool_get_pending_handoffs,
    "get_agent_stats": tool_get_agent_stats,
    # Phase 22: Emergent Intelligence
    # T-22A-01: Specialist Agent Registry
    "list_specialist_agents": tool_list_specialist_agents,
    "get_specialist_routing": tool_get_specialist_routing,
    # T-22C-01: Pattern Generalization Engine
    "generalize_pattern": tool_generalize_pattern,
    "find_transfer_candidates": tool_find_transfer_candidates,
    "get_cross_domain_insights": tool_get_cross_domain_insights,
    "get_pattern_generalization_stats": tool_get_pattern_generalization_stats,
    # Phase 22A-02: Agent Registry & Lifecycle
    "register_agent": tool_register_agent,
    "deregister_agent": tool_deregister_agent,
    "start_agent": tool_start_agent,
    "stop_agent": tool_stop_agent,
    "pause_agent": tool_pause_agent,
    "resume_agent": tool_resume_agent,
    "reset_agent": tool_reset_agent,
    "agent_health_check": tool_agent_health_check,
    "update_agent_config": tool_update_agent_config,
    "get_agent_registry_stats": tool_get_agent_registry_stats,
    # Phase 22A-03: Agent Context Isolation
    "create_agent_context": tool_create_agent_context,
    "get_agent_context": tool_get_agent_context,
    "store_agent_memory": tool_store_agent_memory,
    "recall_agent_memory": tool_recall_agent_memory,
    "set_agent_boundary": tool_set_agent_boundary,
    "get_agent_boundaries": tool_get_agent_boundaries,
    "check_tool_access": tool_check_tool_access,
    "get_isolation_stats": tool_get_isolation_stats,
    # Phase 22A-04: FitJarvis (Fitness Agent)
    "log_workout": tool_log_workout,
    "get_fitness_trends": tool_get_fitness_trends,
    "track_nutrition": tool_track_nutrition,
    "suggest_exercise": tool_suggest_exercise,
    "get_fitness_stats": tool_get_fitness_stats,
    # Phase 22A-05: WorkJarvis (Work Agent)
    "prioritize_tasks": tool_prioritize_tasks,
    "estimate_effort": tool_estimate_effort,
    "track_focus_time": tool_track_focus_time,
    "suggest_breaks": tool_suggest_breaks,
    "get_work_stats": tool_get_work_stats,
    # Phase 22A-06: CommJarvis (Communication Agent)
    "triage_inbox": tool_triage_inbox,
    "draft_response": tool_draft_response,
    "track_relationship": tool_track_relationship,
    "schedule_followup": tool_schedule_followup,
    "get_comm_stats": tool_get_comm_stats,
    # Phase 22A-07: Intent-Based Agent Routing
    "route_query": tool_route_query,
    "classify_intent": tool_classify_intent,
    "test_routing": tool_test_routing,
    "get_routing_stats": tool_get_routing_stats,
    # Phase 22A-08: Multi-Agent Collaboration
    "execute_collaboration": tool_execute_collaboration,
    "get_collaboration_stats": tool_get_collaboration_stats,
    # Phase 22A-09: Agent Delegation Protocol
    "delegate_task": tool_delegate_task,
    "get_delegation_status": tool_get_delegation_status,
    "get_delegation_stats": tool_get_delegation_stats,
    # Phase 22B-02: Message Queue
    "enqueue_message": tool_enqueue_message,
    "dequeue_message": tool_dequeue_message,
    "get_queue_stats": tool_get_queue_stats,
    # Phase 22B-03: Request/Response
    "agent_request": tool_agent_request,
    "scatter_gather": tool_scatter_gather,
    "get_circuit_status": tool_get_circuit_status,
    "propose_agent_negotiation": tool_propose_agent_negotiation,
    "claim_agent_task": tool_claim_agent_task,
    "submit_agent_bid": tool_submit_agent_bid,
    "resolve_agent_conflict": tool_resolve_agent_conflict,
    "record_consensus_vote": tool_record_consensus_vote,
    "get_coordination_status": tool_get_coordination_status,
    "get_coordination_stats": tool_get_coordination_stats,
    # Phase 22B-04/05/06: Shared Context + Subscriptions + Privacy Boundaries
    "publish_agent_context": tool_publish_agent_context,
    "subscribe_agent_context": tool_subscribe_agent_context,
    "read_agent_context": tool_read_agent_context,
    "set_context_privacy_boundary": tool_set_context_privacy_boundary,
    "get_context_pool_stats": tool_get_context_pool_stats,
}

# Load connector-provided tools (auto-discovery in app/connectors)
try:
    connector_definitions, connector_registry = load_connector_tools()
    if connector_definitions:
        TOOL_DEFINITIONS.extend(connector_definitions)
    if connector_registry:
        TOOL_REGISTRY.update(connector_registry)
except Exception as e:
    log_with_context(logger, "warning", "Connector load failed", error=str(e))

# Load dynamic tools (hot-swappable without restart)
try:
    from .tool_loader import initialize_dynamic_tools, get_dynamic_tools, DynamicToolLoader
    dynamic_results = initialize_dynamic_tools()
    dynamic_handlers = get_dynamic_tools()
    if dynamic_handlers:
        TOOL_REGISTRY.update(dynamic_handlers)
        # Also add schemas to TOOL_DEFINITIONS so Claude knows about them
        dynamic_schemas = DynamicToolLoader.get_all_schemas()
        if dynamic_schemas:
            TOOL_DEFINITIONS.extend(dynamic_schemas)
        log_with_context(logger, "info", "Dynamic tools loaded",
                        count=len(dynamic_handlers),
                        schemas=len(dynamic_schemas),
                        tools=list(dynamic_handlers.keys()))
except Exception as e:
    log_with_context(logger, "warning", "Dynamic tools load failed", error=str(e))

# Load workflow skills (orchestration layer above tools)
try:
    from .skill_loader import initialize_skills, SkillLoader
    skill_results = initialize_skills()
    skill_count = len(SkillLoader.get_all_skills())
    if skill_count > 0:
        log_with_context(logger, "info", "Workflow skills loaded",
                        count=skill_count,
                        skills=list(SkillLoader.get_all_skills().keys()))
except Exception as e:
    log_with_context(logger, "warning", "Skills load failed", error=str(e))

# Load model management tools (Phase 21 - Multi-Provider Model Routing)
try:
    from .tool_modules.model_management import (
        MODEL_MANAGEMENT_TOOLS,
        list_available_models,
        get_model_details,
        update_model_settings,
        override_task_model,
        get_model_usage_stats,
        list_task_types,
        add_model,
    )
    TOOL_DEFINITIONS.extend(MODEL_MANAGEMENT_TOOLS)
    TOOL_REGISTRY.update({
        "list_available_models": list_available_models,
        "get_model_details": get_model_details,
        "update_model_settings": update_model_settings,
        "override_task_model": override_task_model,
        "get_model_usage_stats": get_model_usage_stats,
        "list_task_types": list_task_types,
        "add_model": add_model,
    })
    log_with_context(logger, "info", "Model management tools loaded", count=len(MODEL_MANAGEMENT_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Model management tools load failed", error=str(e))

# Load model learning tools (Phase 21+ - Dynamic Learning)
try:
    from .tool_modules.model_learning import (
        MODEL_LEARNING_TOOLS,
        learn_task_pattern,
        adjust_model_priority,
        report_model_performance,
        get_model_recommendations,
        disable_pattern,
        add_selection_rule,
    )
    TOOL_DEFINITIONS.extend(MODEL_LEARNING_TOOLS)
    TOOL_REGISTRY.update({
        "learn_task_pattern": learn_task_pattern,
        "adjust_model_priority": adjust_model_priority,
        "report_model_performance": report_model_performance,
        "get_model_recommendations": get_model_recommendations,
        "disable_pattern": disable_pattern,
        "add_selection_rule": add_selection_rule,
    })
    log_with_context(logger, "info", "Model learning tools loaded", count=len(MODEL_LEARNING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Model learning tools load failed", error=str(e))

# Load research tools (Perplexity/Sonar Pro integration)
try:
    from .tool_modules.research_tools import (
        RESEARCH_TOOLS,
        run_research,
        get_research_items,
        get_research_item_detail,
        list_research_domains,
        list_research_topics,
        add_research_topic,
        add_research_domain,
        tag_research_item,
        get_perplexity_status,
        get_research_providers,
    )
    TOOL_DEFINITIONS.extend(RESEARCH_TOOLS)
    TOOL_REGISTRY.update({
        "run_research": run_research,
        "get_research_items": get_research_items,
        "get_research_item_detail": get_research_item_detail,
        "list_research_domains": list_research_domains,
        "list_research_topics": list_research_topics,
        "add_research_topic": add_research_topic,
        "add_research_domain": add_research_domain,
        "tag_research_item": tag_research_item,
        "get_perplexity_status": get_perplexity_status,
        "get_research_providers": get_research_providers,
    })
    log_with_context(logger, "info", "Research tools loaded", count=len(RESEARCH_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Research tools load failed", error=str(e))

# Load DevOps monitoring tools (Prometheus, Loki, anomaly detection)
try:
    from .tool_modules.monitoring_tools import (
        MONITORING_TOOLS,
        query_prometheus,
        query_loki,
        get_system_health,
        analyze_anomalies,
        create_improvement_ticket,
        get_monitoring_status,
    )
    TOOL_DEFINITIONS.extend(MONITORING_TOOLS)
    TOOL_REGISTRY.update({
        "query_prometheus": query_prometheus,
        "query_loki": query_loki,
        "get_system_health": get_system_health,
        "analyze_anomalies": analyze_anomalies,
        "create_improvement_ticket": create_improvement_ticket,
        "get_monitoring_status": get_monitoring_status,
    })
    log_with_context(logger, "info", "DevOps monitoring tools loaded", count=len(MONITORING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "DevOps monitoring tools load failed", error=str(e))

# Load Self-Knowledge tools (Jarvis internal self-model)
try:
    from .tool_modules.self_knowledge_tools import (
        SELF_KNOWLEDGE_TOOLS,
        get_self_knowledge,
        update_self_knowledge,
        query_architecture,
        get_known_issues,
        record_observation,
    )
    TOOL_DEFINITIONS.extend(SELF_KNOWLEDGE_TOOLS)
    TOOL_REGISTRY.update({
        "get_self_knowledge": get_self_knowledge,
        "update_self_knowledge": update_self_knowledge,
        "query_architecture": query_architecture,
        "get_known_issues": get_known_issues,
        "record_observation": record_observation,
    })
    log_with_context(logger, "info", "Self-knowledge tools loaded", count=len(SELF_KNOWLEDGE_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Self-knowledge tools load failed", error=str(e))

# Load Autonomy tools (Level 0-3 guardrails)
try:
    from .tool_modules.autonomy_tools import (
        AUTONOMY_TOOLS,
        get_autonomy_level,
        set_autonomy_level,
        check_action_allowed,
        assess_risk_impact,
        run_safe_playbook,
        request_approval,
        process_approval,
        get_pending_approvals,
    )
    TOOL_DEFINITIONS.extend(AUTONOMY_TOOLS)
    TOOL_REGISTRY.update({
        "get_autonomy_level": get_autonomy_level,
        "set_autonomy_level": set_autonomy_level,
        "check_action_allowed": check_action_allowed,
        "assess_risk_impact": assess_risk_impact,
        "run_safe_playbook": run_safe_playbook,
        "request_approval": request_approval,
        "process_approval": process_approval,
        "get_pending_approvals": get_pending_approvals,
    })
    log_with_context(logger, "info", "Autonomy tools loaded", count=len(AUTONOMY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Autonomy tools load failed", error=str(e))

# Load RAG Quality tools (Langfuse trace analysis)
try:
    from .tool_modules.rag_quality_tools import (
        RAG_QUALITY_TOOLS,
        evaluate_rag_quality,
        get_rag_quality_metrics,
        get_prometheus_rag_metrics,
        get_quality_issues,
    )
    TOOL_DEFINITIONS.extend(RAG_QUALITY_TOOLS)
    TOOL_REGISTRY.update({
        "evaluate_rag_quality": evaluate_rag_quality,
        "get_rag_quality_metrics": get_rag_quality_metrics,
        "get_prometheus_rag_metrics": get_prometheus_rag_metrics,
        "get_quality_issues": get_quality_issues,
    })
    log_with_context(logger, "info", "RAG quality tools loaded", count=len(RAG_QUALITY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "RAG quality tools load failed", error=str(e))

# Load Anomaly Watcher tools (proactive alerts)
try:
    from .tool_modules.anomaly_watcher_tools import (
        ANOMALY_WATCHER_TOOLS,
        watch_anomalies,
        get_watcher_status,
        reset_alert_cooldowns,
        configure_watcher,
        get_anomaly_history,
    )
    TOOL_DEFINITIONS.extend(ANOMALY_WATCHER_TOOLS)
    TOOL_REGISTRY.update({
        "watch_anomalies": watch_anomalies,
        "get_watcher_status": get_watcher_status,
        "reset_alert_cooldowns": reset_alert_cooldowns,
        "configure_watcher": configure_watcher,
        "get_anomaly_history": get_anomaly_history,
    })
    log_with_context(logger, "info", "Anomaly watcher tools loaded", count=len(ANOMALY_WATCHER_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Anomaly watcher tools load failed", error=str(e))

# Load RAG Maintenance tools (duplicate detection, reindexing)
try:
    from .tool_modules.rag_maintenance_tools import (
        RAG_MAINTENANCE_TOOLS,
        get_collection_health,
        find_duplicates,
        cleanup_duplicates,
        analyze_embedding_drift,
        trigger_reindex,
        get_maintenance_status,
        run_maintenance,
    )
    TOOL_DEFINITIONS.extend(RAG_MAINTENANCE_TOOLS)
    TOOL_REGISTRY.update({
        "get_collection_health": get_collection_health,
        "find_duplicates": find_duplicates,
        "cleanup_duplicates": cleanup_duplicates,
        "analyze_embedding_drift": analyze_embedding_drift,
        "trigger_reindex": trigger_reindex,
        "get_maintenance_status": get_maintenance_status,
        "run_maintenance": run_maintenance,
    })
    log_with_context(logger, "info", "RAG maintenance tools loaded", count=len(RAG_MAINTENANCE_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "RAG maintenance tools load failed", error=str(e))

# Load Impact Analyzer tools (Dev-Co-Pilot)
try:
    from .tool_modules.impact_analyzer_tools import (
        IMPACT_ANALYZER_TOOLS,
        analyze_file_impact,
        analyze_change_impact,
        get_dependency_graph,
        suggest_test_coverage,
        get_analyzer_status,
        assess_deployment_risk,
    )
    TOOL_DEFINITIONS.extend(IMPACT_ANALYZER_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_file_impact": analyze_file_impact,
        "analyze_change_impact": analyze_change_impact,
        "get_dependency_graph": get_dependency_graph,
        "suggest_test_coverage": suggest_test_coverage,
        "get_analyzer_status": get_analyzer_status,
        "assess_deployment_risk": assess_deployment_risk,
    })
    log_with_context(logger, "info", "Impact analyzer tools loaded", count=len(IMPACT_ANALYZER_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Impact analyzer tools load failed", error=str(e))

# Load Playbook Runner tools (Tier 3 Autonomy #8)
try:
    from .tool_modules.playbook_runner_tools import (
        PLAYBOOK_RUNNER_TOOLS,
        list_playbooks,
        get_playbook_details,
        run_playbook,
        schedule_playbook,
        get_playbook_status,
        get_playbook_history,
        cancel_scheduled_playbook,
    )
    TOOL_DEFINITIONS.extend(PLAYBOOK_RUNNER_TOOLS)
    TOOL_REGISTRY.update({
        "list_playbooks": list_playbooks,
        "get_playbook_details": get_playbook_details,
        "run_playbook": run_playbook,
        "schedule_playbook": schedule_playbook,
        "get_playbook_status": get_playbook_status,
        "get_playbook_history": get_playbook_history,
        "cancel_scheduled_playbook": cancel_scheduled_playbook,
    })
    log_with_context(logger, "info", "Playbook runner tools loaded", count=len(PLAYBOOK_RUNNER_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Playbook runner tools load failed", error=str(e))

# Load PR Draft Agent tools (Tier 3 Autonomy #9)
try:
    from .tool_modules.pr_draft_agent_tools import (
        PR_DRAFT_AGENT_TOOLS,
        analyze_issue,
        create_pr_draft,
        get_draft_details,
        list_pr_drafts,
        approve_pr_draft,
        reject_pr_draft,
        get_pr_draft_history,
        generate_change_proposal,
    )
    TOOL_DEFINITIONS.extend(PR_DRAFT_AGENT_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_issue": analyze_issue,
        "create_pr_draft": create_pr_draft,
        "get_draft_details": get_draft_details,
        "list_pr_drafts": list_pr_drafts,
        "approve_pr_draft": approve_pr_draft,
        "reject_pr_draft": reject_pr_draft,
        "get_pr_draft_history": get_pr_draft_history,
        "generate_change_proposal": generate_change_proposal,
    })
    log_with_context(logger, "info", "PR draft agent tools loaded", count=len(PR_DRAFT_AGENT_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "PR draft agent tools load failed", error=str(e))

# Load LinkedIn Coach tools
try:
    from .tool_modules.linkedin_coach_tools import (
        LINKEDIN_COACH_TOOLS,
        linkedin_generate_content,
        linkedin_improve_draft,
        linkedin_check_ai_voice,
        linkedin_suggest_topics,
        linkedin_get_style_examples,
        linkedin_get_playbook,
        linkedin_save_to_playbook,
        linkedin_check_save_confidence,
        linkedin_record_save_feedback,
    )
    TOOL_DEFINITIONS.extend(LINKEDIN_COACH_TOOLS)
    TOOL_REGISTRY.update({
        "linkedin_generate_content": linkedin_generate_content,
        "linkedin_improve_draft": linkedin_improve_draft,
        "linkedin_check_ai_voice": linkedin_check_ai_voice,
        "linkedin_suggest_topics": linkedin_suggest_topics,
        "linkedin_get_style_examples": linkedin_get_style_examples,
        "linkedin_get_playbook": linkedin_get_playbook,
        "linkedin_save_to_playbook": linkedin_save_to_playbook,
        "linkedin_check_save_confidence": linkedin_check_save_confidence,
        "linkedin_record_save_feedback": linkedin_record_save_feedback,
    })
    log_with_context(logger, "info", "LinkedIn coach tools loaded", count=len(LINKEDIN_COACH_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "LinkedIn coach tools load failed", error=str(e))

# Load Smart Home tools (Home Assistant integration)
try:
    from .tool_modules.smart_home_tools import (
        SMART_HOME_TOOLS,
        control_smart_home,
        get_smart_home_status,
        list_smart_home_devices,
        trigger_smart_home_scene,
        get_smart_home_history,
        get_smart_home_connection_status,
    )
    TOOL_DEFINITIONS.extend(SMART_HOME_TOOLS)
    TOOL_REGISTRY.update({
        "control_smart_home": control_smart_home,
        "get_smart_home_status": get_smart_home_status,
        "list_smart_home_devices": list_smart_home_devices,
        "trigger_smart_home_scene": trigger_smart_home_scene,
        "get_smart_home_history": get_smart_home_history,
        "get_smart_home_connection_status": get_smart_home_connection_status,
    })
    log_with_context(logger, "info", "Smart Home tools loaded", count=len(SMART_HOME_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Smart Home tools load failed", error=str(e))

# Load Autonomous Research tools (proactive background research)
try:
    from .tool_modules.autonomous_research_tools import (
        AUTONOMOUS_RESEARCH_TOOLS,
        run_autonomous_research,
        get_research_schedule,
        update_research_schedule,
        get_research_insights,
        track_user_interest,
        get_research_run_history,
    )
    TOOL_DEFINITIONS.extend(AUTONOMOUS_RESEARCH_TOOLS)
    TOOL_REGISTRY.update({
        "run_autonomous_research": run_autonomous_research,
        "get_research_schedule": get_research_schedule,
        "update_research_schedule": update_research_schedule,
        "get_research_insights": get_research_insights,
        "track_user_interest": track_user_interest,
        "get_research_run_history": get_research_run_history,
    })
    log_with_context(logger, "info", "Autonomous research tools loaded", count=len(AUTONOMOUS_RESEARCH_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Autonomous research tools load failed", error=str(e))

# Load Tool Analytics tools (Context-Pattern Memory System Phase 1.1)
try:
    from .tool_modules.tool_analytics_tools import (
        TOOL_ANALYTICS_TOOLS,
        get_my_tool_usage,
        get_my_time_patterns,
        get_context_tool_patterns,
        get_my_tool_chains,
        get_my_failure_analysis,
        get_tool_recommendations,
        refresh_tool_stats,
        get_tool_usage_summary,
    )
    TOOL_DEFINITIONS.extend(TOOL_ANALYTICS_TOOLS)
    TOOL_REGISTRY.update({
        "get_my_tool_usage": get_my_tool_usage,
        "get_my_time_patterns": get_my_time_patterns,
        "get_context_tool_patterns": get_context_tool_patterns,
        "get_my_tool_chains": get_my_tool_chains,
        "get_my_failure_analysis": get_my_failure_analysis,
        # "get_tool_recommendations" - removed, conflicts with tool_meta_tools version (line 3885)
        "refresh_tool_stats": refresh_tool_stats,
        "get_tool_usage_summary": get_tool_usage_summary,
    })
    log_with_context(logger, "info", "Tool analytics tools loaded", count=len(TOOL_ANALYTICS_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Tool analytics tools load failed", error=str(e))

# Load Context Learning tools (Context-Pattern Memory System Phase 1.2)
try:
    from .tool_modules.context_learning_tools import (
        CONTEXT_LEARNING_TOOLS,
        learn_from_tool_history,
        suggest_tools_for_query,
        record_tool_outcome,
        get_learned_mappings,
        get_tool_trigger_contexts,
        detect_current_session_type,
    )
    TOOL_DEFINITIONS.extend(CONTEXT_LEARNING_TOOLS)
    TOOL_REGISTRY.update({
        "learn_from_tool_history": learn_from_tool_history,
        "suggest_tools_for_query": suggest_tools_for_query,
        "record_tool_outcome": record_tool_outcome,
        "get_learned_mappings": get_learned_mappings,
        "get_tool_trigger_contexts": get_tool_trigger_contexts,
        "detect_current_session_type": detect_current_session_type,
    })
    log_with_context(logger, "info", "Context learning tools loaded", count=len(CONTEXT_LEARNING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Context learning tools load failed", error=str(e))

# Load Session Pattern tools (Context-Pattern Memory System Phase 1.3)
try:
    from .tool_modules.session_pattern_tools import (
        SESSION_PATTERN_TOOLS,
        get_current_session,
        get_session_summary,
        predict_next_tools,
        get_session_history,
        get_session_transitions,
        record_session_activity,
    )
    TOOL_DEFINITIONS.extend(SESSION_PATTERN_TOOLS)
    TOOL_REGISTRY.update({
        "get_current_session": get_current_session,
        "get_session_summary": get_session_summary,
        "predict_next_tools": predict_next_tools,
        "get_session_history": get_session_history,
        "get_session_transitions": get_session_transitions,
        "record_session_activity": record_session_activity,
    })
    log_with_context(logger, "info", "Session pattern tools loaded", count=len(SESSION_PATTERN_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Session pattern tools load failed", error=str(e))

# Load Proactive Context tools (Context-Pattern Memory System Phase 2.1)
try:
    from .tool_modules.proactive_context_tools import (
        PROACTIVE_CONTEXT_TOOLS,
        analyze_context_needs,
        load_proactive_context,
        mark_context_useful,
        get_context_effectiveness,
        build_context_prompt,
    )
    TOOL_DEFINITIONS.extend(PROACTIVE_CONTEXT_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_context_needs": analyze_context_needs,
        "load_proactive_context": load_proactive_context,
        "mark_context_useful": mark_context_useful,
        "get_context_effectiveness": get_context_effectiveness,
        "build_context_prompt": build_context_prompt,
    })
    log_with_context(logger, "info", "Proactive context tools loaded", count=len(PROACTIVE_CONTEXT_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Proactive context tools load failed", error=str(e))

# Load Tool Chain tools (Context-Pattern Memory System Phase 2.2)
try:
    from .tool_modules.tool_chain_tools import (
        TOOL_CHAIN_TOOLS,
        learn_tool_chains,
        suggest_tool_chain,
        get_top_tool_chains,
        get_chains_for_tool,
        record_tool_chain,
        # Tier 2: Intelligence tools
        recommend_tool_chains,
        get_chain_intelligence_stats,
        learn_chain_intent_clusters,
    )
    TOOL_DEFINITIONS.extend(TOOL_CHAIN_TOOLS)
    TOOL_REGISTRY.update({
        "learn_tool_chains": learn_tool_chains,
        "suggest_tool_chain": suggest_tool_chain,
        "get_top_tool_chains": get_top_tool_chains,
        "get_chains_for_tool": get_chains_for_tool,
        "record_tool_chain": record_tool_chain,
        # Tier 2: Intelligence tools
        "recommend_tool_chains": recommend_tool_chains,
        "get_chain_intelligence_stats": get_chain_intelligence_stats,
        "learn_chain_intent_clusters": learn_chain_intent_clusters,
    })
    log_with_context(logger, "info", "Tool chain tools loaded", count=len(TOOL_CHAIN_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Tool chain tools load failed", error=str(e))

# Phase 3.1: Contextual Tool Routing
try:
    from .tool_modules.contextual_routing_tools import (
        CONTEXTUAL_ROUTING_TOOLS,
        create_routing_rule,
        route_tool_selection,
        record_routing_outcome,
        get_routing_rules,
        get_tool_affinities,
    )
    TOOL_DEFINITIONS.extend(CONTEXTUAL_ROUTING_TOOLS)
    TOOL_REGISTRY.update({
        "create_routing_rule": create_routing_rule,
        "route_tool_selection": route_tool_selection,
        "record_routing_outcome": record_routing_outcome,
        "get_routing_rules": get_routing_rules,
        "get_tool_affinities": get_tool_affinities,
    })
    log_with_context(logger, "info", "Contextual routing tools loaded", count=len(CONTEXTUAL_ROUTING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Contextual routing tools load failed", error=str(e))

# Phase 3.2: Decision Tracking
try:
    from .tool_modules.decision_tracking_tools import (
        DECISION_TRACKING_TOOLS,
        record_decision,
        record_decision_outcome,
        get_decision_history,
        get_decision_stats,
        suggest_decision,
    )
    TOOL_DEFINITIONS.extend(DECISION_TRACKING_TOOLS)
    TOOL_REGISTRY.update({
        "record_decision": record_decision,
        # "record_decision_outcome" - removed, conflicts with decision_tools version (line 3860)
        "get_decision_history": get_decision_history,
        "get_decision_stats": get_decision_stats,
        "suggest_decision": suggest_decision,
    })
    log_with_context(logger, "info", "Decision tracking tools loaded", count=len(DECISION_TRACKING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Decision tracking tools load failed", error=str(e))

# Phase 3.3: Pattern Recognition
try:
    from .tool_modules.pattern_recognition_tools import (
        PATTERN_RECOGNITION_TOOLS,
        analyze_temporal_patterns,
        analyze_tool_cooccurrence,
        cluster_queries,
        detect_usage_anomalies,
        predict_next_tool,
        get_recognized_patterns,
    )
    TOOL_DEFINITIONS.extend(PATTERN_RECOGNITION_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_temporal_patterns": analyze_temporal_patterns,
        "analyze_tool_cooccurrence": analyze_tool_cooccurrence,
        "cluster_queries": cluster_queries,
        "detect_usage_anomalies": detect_usage_anomalies,
        "predict_next_tool": predict_next_tool,
        "get_recognized_patterns": get_recognized_patterns,
    })
    log_with_context(logger, "info", "Pattern recognition tools loaded", count=len(PATTERN_RECOGNITION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Pattern recognition tools load failed", error=str(e))

# Phase 4: Auto-Integration Tools
try:
    from .tool_modules.auto_integration_tools import (
        AUTO_INTEGRATION_TOOLS,
        trigger_pattern_learning,
        get_learning_status,
        get_learning_insights,
        configure_auto_learning,
    )
    TOOL_DEFINITIONS.extend(AUTO_INTEGRATION_TOOLS)
    TOOL_REGISTRY.update({
        "trigger_pattern_learning": trigger_pattern_learning,
        "get_learning_status": get_learning_status,
        "get_learning_insights": get_learning_insights,
        "configure_auto_learning": configure_auto_learning,
    })
    log_with_context(logger, "info", "Auto-integration tools loaded", count=len(AUTO_INTEGRATION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Auto-integration tools load failed", error=str(e))

# Load LinkedIn & visualfox Knowledge Base search tools (Phase 2A: unified knowledge_retrieval)
try:
    from .services.knowledge_retrieval import (
        LINKEDIN_KNOWLEDGE_TOOL_SCHEMA,
        VISUALFOX_KNOWLEDGE_TOOL_SCHEMA,
        handle_search_linkedin_knowledge,
        handle_search_visualfox_knowledge,
    )
    TOOL_DEFINITIONS.append(LINKEDIN_KNOWLEDGE_TOOL_SCHEMA)
    TOOL_DEFINITIONS.append(VISUALFOX_KNOWLEDGE_TOOL_SCHEMA)
    TOOL_REGISTRY["search_linkedin_knowledge"] = handle_search_linkedin_knowledge
    TOOL_REGISTRY["search_visualfox_knowledge"] = handle_search_visualfox_knowledge
    log_with_context(logger, "info", "LinkedIn + visualfox knowledge search tools loaded", count=2)
except Exception as e:
    log_with_context(logger, "warning", "Knowledge search tools load failed", error=str(e))

# Load Knowledge Base Management tools (DB-driven)
try:
    from .services.knowledge_tools import (
        MANAGE_KNOWLEDGE_SOURCES_SCHEMA,
        INGEST_KNOWLEDGE_SCHEMA,
        SEARCH_KNOWLEDGE_SCHEMA,
        handle_manage_knowledge_sources,
        handle_ingest_knowledge,
        handle_search_knowledge,
    )
    TOOL_DEFINITIONS.append(MANAGE_KNOWLEDGE_SOURCES_SCHEMA)
    TOOL_DEFINITIONS.append(INGEST_KNOWLEDGE_SCHEMA)
    TOOL_DEFINITIONS.append(SEARCH_KNOWLEDGE_SCHEMA)
    TOOL_REGISTRY["manage_knowledge_sources"] = handle_manage_knowledge_sources
    TOOL_REGISTRY["ingest_knowledge"] = handle_ingest_knowledge
    TOOL_REGISTRY["search_knowledge_base"] = handle_search_knowledge
    log_with_context(logger, "info", "Knowledge Base management tools loaded", count=3)
except Exception as e:
    log_with_context(logger, "warning", "Knowledge Base management tools load failed", error=str(e))

# Phase A1: Self-Reflection Engine (AGI Evolution)
try:
    from .tool_modules.reflection_tools import (
        REFLECTION_TOOLS,
        evaluate_my_response,
        reflect_on_response,
        get_my_learnings,
        get_improvement_progress,
        get_pending_improvements,
        apply_improvement,
        run_self_reflection,
        add_critique_rule,
        get_critique_rules,
    )
    TOOL_DEFINITIONS.extend(REFLECTION_TOOLS)
    TOOL_REGISTRY.update({
        "evaluate_my_response": evaluate_my_response,
        "reflect_on_response": reflect_on_response,
        "get_my_learnings": get_my_learnings,
        "get_improvement_progress": get_improvement_progress,
        "get_pending_improvements": get_pending_improvements,
        "apply_improvement": apply_improvement,
        "run_self_reflection": run_self_reflection,
        "add_critique_rule": add_critique_rule,
        "get_critique_rules": get_critique_rules,
    })
    log_with_context(logger, "info", "Self-Reflection Engine tools loaded (Phase A1)", count=len(REFLECTION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Self-Reflection Engine tools load failed", error=str(e))

# Phase A2: Uncertainty Quantification (AGI Evolution)
try:
    from .tool_modules.uncertainty_tools import (
        UNCERTAINTY_TOOLS,
        assess_my_confidence,
        get_my_knowledge_gaps,
        resolve_knowledge_gap,
        update_confidence_calibration,
        get_calibration_stats,
        get_confidence_summary,
        add_uncertainty_signal,
        get_uncertainty_signals,
    )
    TOOL_DEFINITIONS.extend(UNCERTAINTY_TOOLS)
    TOOL_REGISTRY.update({
        "assess_my_confidence": assess_my_confidence,
        "get_my_knowledge_gaps": get_my_knowledge_gaps,
        "resolve_knowledge_gap": resolve_knowledge_gap,
        "update_confidence_calibration": update_confidence_calibration,
        "get_calibration_stats": get_calibration_stats,
        "get_confidence_summary": get_confidence_summary,
        "add_uncertainty_signal": add_uncertainty_signal,
        "get_uncertainty_signals": get_uncertainty_signals,
    })
    log_with_context(logger, "info", "Uncertainty Quantification tools loaded (Phase A2)", count=len(UNCERTAINTY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Uncertainty Quantification tools load failed", error=str(e))

# Phase A3: Causal Knowledge Graph (AGI Evolution)
try:
    from .tool_modules.causal_tools import (
        CAUSAL_TOOLS,
        learn_causal_relationship,
        why_does,
        what_if,
        how_to_achieve,
        get_causal_chain,
        record_intervention,
        verify_intervention_outcome,
        find_causal_nodes,
        get_causal_summary,
        add_causal_node,
    )
    TOOL_DEFINITIONS.extend(CAUSAL_TOOLS)
    TOOL_REGISTRY.update({
        "learn_causal_relationship": learn_causal_relationship,
        "why_does": why_does,
        "what_if": what_if,
        "how_to_achieve": how_to_achieve,
        "get_causal_chain": get_causal_chain,
        "record_intervention": record_intervention,
        "verify_intervention_outcome": verify_intervention_outcome,
        "find_causal_nodes": find_causal_nodes,
        "get_causal_summary": get_causal_summary,
        "add_causal_node": add_causal_node,
    })
    log_with_context(logger, "info", "Causal Knowledge Graph tools loaded (Phase A3)", count=len(CAUSAL_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Causal Knowledge Graph tools load failed", error=str(e))

# Phase B1: Memory Hierarchy (AGI Evolution)
try:
    from .tool_modules.memory_hierarchy_tools import (
        MEMORY_HIERARCHY_TOOLS,
        store_memory,
        recall_memory,
        search_memories,
        promote_to_working,
        get_working_context,
        clear_working_context,
        demote_memory,
        archive_memory,
        run_memory_maintenance,
        get_memory_stats,
        create_session_summary,
    )
    TOOL_DEFINITIONS.extend(MEMORY_HIERARCHY_TOOLS)
    TOOL_REGISTRY.update({
        "store_memory": store_memory,
        "recall_memory": recall_memory,
        "search_memories": search_memories,
        "promote_to_working": promote_to_working,
        "get_working_context": get_working_context,
        "clear_working_context": clear_working_context,
        "demote_memory": demote_memory,
        "archive_memory": archive_memory,
        "run_memory_maintenance": run_memory_maintenance,
        "get_memory_stats": get_memory_stats,
        "create_session_summary": create_session_summary,
    })
    log_with_context(logger, "info", "Memory Hierarchy tools loaded (Phase B1)", count=len(MEMORY_HIERARCHY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Memory Hierarchy tools load failed", error=str(e))

# Phase B2: Importance Scoring (AGI Evolution)
try:
    from .tool_modules.importance_scoring_tools import (
        IMPORTANCE_SCORING_TOOLS,
        score_content_importance,
        retrieve_by_relevance,
        update_entity_importance,
        get_important_entities,
        add_importance_factor,
        get_importance_factors,
        decay_memory_recency,
        get_scoring_stats,
    )
    TOOL_DEFINITIONS.extend(IMPORTANCE_SCORING_TOOLS)
    TOOL_REGISTRY.update({
        "score_content_importance": score_content_importance,
        "retrieve_by_relevance": retrieve_by_relevance,
        "update_entity_importance": update_entity_importance,
        "get_important_entities": get_important_entities,
        "add_importance_factor": add_importance_factor,
        "get_importance_factors": get_importance_factors,
        "decay_memory_recency": decay_memory_recency,
        "get_scoring_stats": get_scoring_stats,
    })
    log_with_context(logger, "info", "Importance Scoring tools loaded (Phase B2)", count=len(IMPORTANCE_SCORING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Importance Scoring tools load failed", error=str(e))

# Phase L0: Guardrails System (Leitplanken)
try:
    from .tool_modules.guardrails_tools import (
        GUARDRAILS_TOOLS,
        check_guardrails,
        get_guardrails,
        add_guardrail,
        update_guardrail,
        request_override,
        revoke_override,
        get_audit_log,
        add_guardrail_feedback,
        get_guardrails_summary,
        # L0.1 Risk Tier Tools
        get_tool_risk_tiers,
        set_tool_risk_tier,
        get_tier_definitions,
        get_risk_tier_summary,
    )
    TOOL_DEFINITIONS.extend(GUARDRAILS_TOOLS)
    TOOL_REGISTRY.update({
        "check_guardrails": check_guardrails,
        "get_guardrails": get_guardrails,
        "add_guardrail": add_guardrail,
        "update_guardrail": update_guardrail,
        "request_override": request_override,
        "revoke_override": revoke_override,
        "get_audit_log": get_audit_log,
        "add_guardrail_feedback": add_guardrail_feedback,
        "get_guardrails_summary": get_guardrails_summary,
        # L0.1 Risk Tier Tools
        "get_tool_risk_tiers": get_tool_risk_tiers,
        "set_tool_risk_tier": set_tool_risk_tier,
        "get_tier_definitions": get_tier_definitions,
        "get_risk_tier_summary": get_risk_tier_summary,
    })
    log_with_context(logger, "info", "Guardrails + Risk Tier tools loaded (Phase L0/L0.1)", count=len(GUARDRAILS_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Guardrails tools load failed", error=str(e))

# Phase S1: Citation Grounding (Anti-Halluzination)
try:
    from .tool_modules.citation_tools import (
        CITATION_TOOLS,
        cite_fact,
        get_fact_citations,
        verify_fact,
        get_verification_status,
        request_fact_verification,
        get_unverified_facts,
        get_conflicting_facts,
        register_citation_source,
        get_citation_stats,
        search_citations,
    )
    TOOL_DEFINITIONS.extend(CITATION_TOOLS)
    TOOL_REGISTRY.update({
        "cite_fact": cite_fact,
        "get_fact_citations": get_fact_citations,
        "verify_fact": verify_fact,
        "get_verification_status": get_verification_status,
        "request_fact_verification": request_fact_verification,
        "get_unverified_facts": get_unverified_facts,
        "get_conflicting_facts": get_conflicting_facts,
        "register_citation_source": register_citation_source,
        "get_citation_stats": get_citation_stats,
        "search_citations": search_citations,
    })
    log_with_context(logger, "info", "Citation Grounding tools loaded (Phase S1)", count=len(CITATION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Citation tools load failed", error=str(e))

# Phase S2: Verify-Before-Act (Reliability)
try:
    from .tool_modules.verify_tools import (
        VERIFY_TOOLS,
        create_action_plan,
        get_action_plan,
        start_action_execution,
        record_action_result,
        verify_action,
        trigger_action_rollback,
        get_active_plans,
        get_failed_verifications,
        get_verification_stats,
        mark_verification_reviewed,
    )
    TOOL_DEFINITIONS.extend(VERIFY_TOOLS)
    TOOL_REGISTRY.update({
        "create_action_plan": create_action_plan,
        "get_action_plan": get_action_plan,
        "start_action_execution": start_action_execution,
        "record_action_result": record_action_result,
        "verify_action": verify_action,
        "trigger_action_rollback": trigger_action_rollback,
        "get_active_plans": get_active_plans,
        "get_failed_verifications": get_failed_verifications,
        "get_verification_stats": get_verification_stats,
        "mark_verification_reviewed": mark_verification_reviewed,
    })
    log_with_context(logger, "info", "Verify-Before-Act tools loaded (Phase S2)", count=len(VERIFY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Verify tools load failed", error=str(e))

# Phase O1: Batch API Integration (Cost Optimization)
try:
    from .tool_modules.batch_tools import (
        BATCH_TOOLS,
        submit_batch_job,
        get_batch_status,
        retrieve_batch_results,
        list_batch_jobs,
        cancel_batch_job,
        get_batch_stats,
        queue_batch_task,
        process_batch_queue,
        get_batch_queue_status,
    )
    TOOL_DEFINITIONS.extend(BATCH_TOOLS)
    TOOL_REGISTRY.update({
        "submit_batch_job": submit_batch_job,
        "get_batch_status": get_batch_status,
        "retrieve_batch_results": retrieve_batch_results,
        "list_batch_jobs": list_batch_jobs,
        "cancel_batch_job": cancel_batch_job,
        "get_batch_stats": get_batch_stats,
        "queue_batch_task": queue_batch_task,
        "process_batch_queue": process_batch_queue,
        "get_batch_queue_status": get_batch_queue_status,
    })
    log_with_context(logger, "info", "Batch API tools loaded (Tier 4 #13)", count=len(BATCH_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Batch tools load failed", error=str(e))

# Tier 4 #14: ML Pattern Recognition
try:
    from .tool_modules.ml_pattern_tools import (
        ML_PATTERN_TOOLS,
        record_metric,
        analyze_seasonality,
        forecast_metric,
        detect_anomalies_ml,
        correlate_metrics,
        generate_predictive_alerts,
        get_pattern_alerts,
        get_pattern_summary,
        get_time_series,
    )
    TOOL_DEFINITIONS.extend(ML_PATTERN_TOOLS)
    TOOL_REGISTRY.update({
        "record_metric": record_metric,
        "analyze_seasonality": analyze_seasonality,
        "forecast_metric": forecast_metric,
        "detect_anomalies_ml": detect_anomalies_ml,
        "correlate_metrics": correlate_metrics,
        "generate_predictive_alerts": generate_predictive_alerts,
        "get_pattern_alerts": get_pattern_alerts,
        "get_pattern_summary": get_pattern_summary,
        "get_time_series": get_time_series,
    })
    log_with_context(logger, "info", "ML Pattern tools loaded (Tier 4 #14)", count=len(ML_PATTERN_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "ML Pattern tools load failed", error=str(e))

# Tier 4 #15: Auto-Refactoring
try:
    from .tool_modules.auto_refactor_tools import (
        AUTO_REFACTOR_TOOLS,
        analyze_code_quality,
        get_refactoring_suggestions,
        get_file_issues,
        update_refactor_status,
        get_refactor_stats,
        analyze_single_file,
        get_complexity_hotspots,
        generate_refactor_plan,
    )
    TOOL_DEFINITIONS.extend(AUTO_REFACTOR_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_code_quality": analyze_code_quality,
        "get_refactoring_suggestions": get_refactoring_suggestions,
        "get_file_issues": get_file_issues,
        "update_refactor_status": update_refactor_status,
        "get_refactor_stats": get_refactor_stats,
        "analyze_single_file": analyze_single_file,
        "get_complexity_hotspots": get_complexity_hotspots,
        "generate_refactor_plan": generate_refactor_plan,
    })
    log_with_context(logger, "info", "Auto-Refactor tools loaded (Tier 4 #15)", count=len(AUTO_REFACTOR_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Auto-Refactor tools load failed", error=str(e))

# Learning from Corrections
try:
    from .tool_modules.correction_tools import (
        CORRECTION_TOOLS,
        detect_correction,
        process_correction,
        check_corrections,
        store_correction,
        get_correction_stats,
    )
    TOOL_DEFINITIONS.extend(CORRECTION_TOOLS)
    TOOL_REGISTRY.update({
        "detect_correction": detect_correction,
        "process_correction": process_correction,
        "check_corrections": check_corrections,
        "store_correction": store_correction,
        "get_correction_stats": get_correction_stats,
    })
    log_with_context(logger, "info", "Correction Learning tools loaded", count=len(CORRECTION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Correction Learning tools load failed", error=str(e))

# Tier 1 Quick Win: Decision Support Tools
try:
    from .tools.decision_support_tools import (
        get_decision_support_tools,
        execute_decision_support_tool,
        is_decision_support_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_decision_support_tools())

    # Create wrapper handlers for each tool
    def _make_decision_handler(name):
        async def handler(**kwargs):
            import asyncio
            result = await execute_decision_support_tool(name, kwargs)
            return result

        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_decision_support_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_decision_support_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "analyze_decision": _make_decision_handler("analyze_decision"),
        "find_similar_situations": _make_decision_handler("find_similar_situations"),
        "get_decision_stats": _make_decision_handler("get_decision_stats"),
        # Note: record_decision_outcome already exists, using new causal version
        "record_causal_outcome": _make_decision_handler("record_decision_outcome"),
    })
    log_with_context(logger, "info", "Decision Support tools loaded (Tier 1 Quick Win)", count=4)
except Exception as e:
    log_with_context(logger, "warning", "Decision Support tools load failed", error=str(e))

# Tier 2: Goal Decomposition Tools
try:
    from .tools.goal_tools import (
        get_goal_tools,
        execute_goal_tool,
        is_goal_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_goal_tools())

    # Create wrapper handlers for each tool
    def _make_goal_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_goal_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_goal_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "create_goal": _make_goal_handler("create_goal"),
        "get_active_goals": _make_goal_handler("get_active_goals"),
        "get_goal_status": _make_goal_handler("get_goal_status"),
        "record_goal_progress": _make_goal_handler("record_goal_progress"),
        "get_goal_reminders": _make_goal_handler("get_goal_reminders"),
        "update_goal_status": _make_goal_handler("update_goal_status"),
    })
    log_with_context(logger, "info", "Goal Decomposition tools loaded (Tier 2)", count=6)
except Exception as e:
    log_with_context(logger, "warning", "Goal tools load failed", error=str(e))

# Tier 2: KB Analytics Tools
try:
    from .tools.kb_analytics_tools import (
        get_kb_analytics_tools,
        execute_kb_analytics_tool,
        is_kb_analytics_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_kb_analytics_tools())

    # Create wrapper handlers
    def _make_kb_analytics_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_kb_analytics_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_kb_analytics_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "get_kb_health": _make_kb_analytics_handler("get_kb_health"),
        "get_source_rankings": _make_kb_analytics_handler("get_source_rankings"),
        "get_knowledge_gaps": _make_kb_analytics_handler("get_knowledge_gaps"),
        "mark_gap_resolved": _make_kb_analytics_handler("mark_gap_resolved"),
    })
    log_with_context(logger, "info", "KB Analytics tools loaded (Tier 2)", count=4)
except Exception as e:
    log_with_context(logger, "warning", "KB Analytics tools load failed", error=str(e))

# Tier 3: Specialist Agent Tools
try:
    from .tools.specialist_tools import (
        get_specialist_tools,
        execute_specialist_tool,
        is_specialist_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_specialist_tools())

    # Create wrapper handlers
    def _make_specialist_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_specialist_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_specialist_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "list_specialists": _make_specialist_handler("list_specialists"),
        "get_specialist_info": _make_specialist_handler("get_specialist_info"),
        "activate_specialist": _make_specialist_handler("activate_specialist"),
        "get_specialist_stats": _make_specialist_handler("get_specialist_stats"),
        "save_specialist_memory": _make_specialist_handler("save_specialist_memory"),
        "get_specialist_memory": _make_specialist_handler("get_specialist_memory"),
    })
    log_with_context(logger, "info", "Specialist Agent tools loaded (Tier 3)", count=6)
except Exception as e:
    log_with_context(logger, "warning", "Specialist Agent tools load failed", error=str(e))

# Tier 3: Agent Message Tools
try:
    from .tools.agent_message_tools import (
        get_agent_message_tools,
        execute_agent_message_tool,
        is_agent_message_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_agent_message_tools())

    # Create wrapper handlers
    def _make_agent_message_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_agent_message_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_agent_message_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "send_agent_message": _make_agent_message_handler("send_agent_message"),
        "get_agent_messages": _make_agent_message_handler("get_agent_messages"),
        "reply_agent_message": _make_agent_message_handler("reply_agent_message"),
        "handoff_to_specialist": _make_agent_message_handler("handoff_to_specialist"),
        "broadcast_message": _make_agent_message_handler("broadcast_message"),
        "get_message_stats": _make_agent_message_handler("get_message_stats"),
    })
    log_with_context(logger, "info", "Agent Message tools loaded (Tier 3)", count=6)
except Exception as e:
    log_with_context(logger, "warning", "Agent Message tools load failed", error=str(e))

# Tier 3: Context Engine Tools
try:
    from .tools.context_tools import (
        get_context_tools,
        execute_context_tool,
        is_context_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_context_tools())

    # Create wrapper handlers
    def _make_context_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_context_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_context_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "get_context": _make_context_handler("get_context"),
        "record_context_signal": _make_context_handler("record_context_signal"),
        "get_context_rules": _make_context_handler("get_context_rules"),
        "get_context_stats": _make_context_handler("get_context_stats"),
    })
    log_with_context(logger, "info", "Context Engine tools loaded (Tier 3)", count=4)
except Exception as e:
    log_with_context(logger, "warning", "Context Engine tools load failed", error=str(e))

# Tier 3: Cross-Session Continuity Tools
try:
    from .tools.cross_session_tools import (
        get_cross_session_tools,
        execute_cross_session_tool,
        is_cross_session_tool,
    )

    # Add tool definitions
    TOOL_DEFINITIONS.extend(get_cross_session_tools())

    # Create wrapper handlers
    def _make_cross_session_handler(name):
        def sync_handler(**kwargs):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, execute_cross_session_tool(name, kwargs))
                    return future.result()
            else:
                return asyncio.run(execute_cross_session_tool(name, kwargs))
        return sync_handler

    TOOL_REGISTRY.update({
        "get_session_context": _make_cross_session_handler("get_session_context"),
        "create_conversation_thread": _make_cross_session_handler("create_conversation_thread"),
        "update_conversation_thread": _make_cross_session_handler("update_conversation_thread"),
        "create_session_handoff": _make_cross_session_handler("create_session_handoff"),
        "list_active_threads": _make_cross_session_handler("list_active_threads"),
        "get_session_stats": _make_cross_session_handler("get_session_stats"),
    })
    log_with_context(logger, "info", "Cross-Session tools loaded (Tier 3)", count=6)
except Exception as e:
    log_with_context(logger, "warning", "Cross-Session tools load failed", error=str(e))

# U4: AI Assistant Handoff Tools
try:
    from .tool_modules.handoff_tools import (
        HANDOFF_TOOLS,
        create_handoff,
        get_pending_handoffs,
        complete_handoff,
        get_handoff_context,
        suggest_assistant,
    )
    TOOL_DEFINITIONS.extend(HANDOFF_TOOLS)
    TOOL_REGISTRY.update({
        "create_handoff": create_handoff,
        "get_assistant_handoffs": get_pending_handoffs,  # renamed from get_pending_handoffs to avoid conflict with agent_coordination (line 3894)
        "complete_handoff": complete_handoff,
        "get_handoff_context": get_handoff_context,
        "suggest_assistant": suggest_assistant,
    })
    log_with_context(logger, "info", "AI Assistant Handoff tools loaded (U4)", count=len(HANDOFF_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Handoff tools load failed", error=str(e))

# U3: Smart Memory Retrieval Tools
try:
    from .tool_modules.smart_retrieval_tools import (
        SMART_RETRIEVAL_TOOLS,
        smart_recall,
        get_retrieval_strategies,
        analyze_query_for_retrieval,
        get_memory_stats,
    )
    TOOL_DEFINITIONS.extend(SMART_RETRIEVAL_TOOLS)
    TOOL_REGISTRY.update({
        "smart_recall": smart_recall,
        "get_retrieval_strategies": get_retrieval_strategies,
        "analyze_query_for_retrieval": analyze_query_for_retrieval,
        "get_memory_stats": get_memory_stats,
    })
    log_with_context(logger, "info", "Smart Retrieval tools loaded (U3)", count=len(SMART_RETRIEVAL_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Smart Retrieval tools load failed", error=str(e))

# T006: Timer Tools (extracted from inline)
try:
    from .tool_modules.timer_tools import (
        TIMER_TOOLS,
        tool_set_timer,
        tool_cancel_timer,
        tool_list_timers,
    )
    TOOL_DEFINITIONS.extend(TIMER_TOOLS)
    TOOL_REGISTRY.update({
        "set_timer": tool_set_timer,
        "cancel_timer": tool_cancel_timer,
        "list_timers": tool_list_timers,
    })
    log_with_context(logger, "info", "Timer tools loaded (T006 refactor)", count=len(TIMER_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Timer tools load failed", error=str(e))

# T006: Ollama Tools (extracted from inline)
try:
    from .tool_modules.ollama_tools import (
        OLLAMA_TOOLS,
        tool_delegate_ollama_task,
        tool_get_ollama_task_status,
        tool_get_ollama_queue_status,
        tool_cancel_ollama_task,
        tool_get_ollama_callback_result,
        tool_ask_ollama,
        tool_ollama_python,
    )
    TOOL_DEFINITIONS.extend(OLLAMA_TOOLS)
    TOOL_REGISTRY.update({
        "delegate_ollama_task": tool_delegate_ollama_task,
        "get_ollama_task_status": tool_get_ollama_task_status,
        "get_ollama_queue_status": tool_get_ollama_queue_status,
        "cancel_ollama_task": tool_cancel_ollama_task,
        "get_ollama_callback_result": tool_get_ollama_callback_result,
        "ask_ollama": tool_ask_ollama,
        "ollama_python": tool_ollama_python,
    })
    log_with_context(logger, "info", "Ollama tools loaded (T006 refactor)", count=len(OLLAMA_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Ollama tools load failed", error=str(e))

# T006: Subagent Tools (extracted from inline)
try:
    from .tool_modules.subagent_tools import (
        SUBAGENT_TOOLS,
        tool_delegate_to_subagent,
        tool_get_subagent_result,
        tool_list_subagents,
    )
    TOOL_DEFINITIONS.extend(SUBAGENT_TOOLS)
    TOOL_REGISTRY.update({
        "delegate_to_subagent": tool_delegate_to_subagent,
        "get_subagent_result": tool_get_subagent_result,
        "list_subagents": tool_list_subagents,
    })
    log_with_context(logger, "info", "Subagent tools loaded (T006 refactor)", count=len(SUBAGENT_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Subagent tools load failed", error=str(e))

# T006: Sandbox Tools (extracted from inline)
try:
    from .tool_modules.sandbox_tools import (
        SANDBOX_TOOLS,
        tool_request_python_sandbox,
        tool_execute_python,
        tool_write_dynamic_tool,
        tool_promote_sandbox_tool,
    )
    TOOL_DEFINITIONS.extend(SANDBOX_TOOLS)
    TOOL_REGISTRY.update({
        "request_python_sandbox": tool_request_python_sandbox,
        "execute_python": tool_execute_python,
        "write_dynamic_tool": tool_write_dynamic_tool,
        "promote_sandbox_tool": tool_promote_sandbox_tool,
    })
    log_with_context(logger, "info", "Sandbox tools loaded (T006 refactor)", count=len(SANDBOX_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Sandbox tools load failed", error=str(e))

# T006: Learning & Memory Tools (extracted from inline)
try:
    from .tool_modules.learning_memory_tools import (
        LEARNING_MEMORY_TOOLS,
        tool_record_learning,
        tool_get_learnings,
        tool_store_context,
        tool_recall_context,
        tool_forget_context,
        tool_record_learnings_batch,
        tool_store_contexts_batch,
    )
    TOOL_DEFINITIONS.extend(LEARNING_MEMORY_TOOLS)
    TOOL_REGISTRY.update({
        "record_learning": tool_record_learning,
        "get_learnings": tool_get_learnings,
        "store_context": tool_store_context,
        "recall_context": tool_recall_context,
        "forget_context": tool_forget_context,
        "record_learnings_batch": tool_record_learnings_batch,
        "store_contexts_batch": tool_store_contexts_batch,
    })
    log_with_context(logger, "info", "Learning & Memory tools loaded (T006 refactor)", count=len(LEARNING_MEMORY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Learning & Memory tools load failed", error=str(e))

# T006: Identity Evolution Tools (extracted from inline)
try:
    from .tool_modules.identity_tools import (
        IDENTITY_TOOLS,
        tool_get_self_model,
        tool_evolve_identity,
        tool_log_experience,
        tool_get_relationship,
        tool_update_relationship,
        tool_get_learning_patterns,
        tool_record_session_learning,
    )
    TOOL_DEFINITIONS.extend(IDENTITY_TOOLS)
    TOOL_REGISTRY.update({
        "get_self_model": tool_get_self_model,
        "evolve_identity": tool_evolve_identity,
        "log_experience": tool_log_experience,
        "get_relationship": tool_get_relationship,
        "update_relationship": tool_update_relationship,
        "get_learning_patterns": tool_get_learning_patterns,
        "record_session_learning": tool_record_session_learning,
    })
    log_with_context(logger, "info", "Identity tools loaded (T006 refactor)", count=len(IDENTITY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Identity tools load failed", error=str(e))

# Phase 21: Tool Suggestions (2B - Smart Tool Discovery)
try:
    from .tool_modules.suggestion_tools import (
        TOOLS as SUGGESTION_TOOLS,
        get_tool_suggestions,
        record_suggestion_feedback,
        get_suggestion_stats,
        list_underused_tools,
    )
    TOOL_DEFINITIONS.extend(SUGGESTION_TOOLS)
    TOOL_REGISTRY.update({
        "get_tool_suggestions": get_tool_suggestions,
        "record_suggestion_feedback": record_suggestion_feedback,
        "get_suggestion_stats": get_suggestion_stats,
        "list_underused_tools": list_underused_tools,
    })
    log_with_context(logger, "info", "Tool Suggestion tools loaded (Phase 21 2B)", count=len(SUGGESTION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Tool Suggestion tools load failed", error=str(e))

# Phase 21: Tool Categories (2C - Tool Discovery by Category)
try:
    from .tool_modules.category_tools import (
        TOOLS as CATEGORY_TOOLS,
        list_category_tools,
        get_tool_categories,
        search_tools,
        get_recommended_tools,
    )
    TOOL_DEFINITIONS.extend(CATEGORY_TOOLS)
    TOOL_REGISTRY.update({
        "list_category_tools": list_category_tools,
        "get_tool_categories": get_tool_categories,
        "search_tools": search_tools,
        "get_recommended_tools": get_recommended_tools,
    })
    log_with_context(logger, "info", "Tool Category tools loaded (Phase 21 2C)", count=len(CATEGORY_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Tool Category tools load failed", error=str(e))

# Phase 21: Self-Optimization (3C - Proactive Self-Monitoring)
try:
    from .tool_modules.self_optimization_tools import (
        TOOLS as SELF_OPTIMIZATION_TOOLS,
        run_self_optimization_analysis,
        get_my_health_summary,
        propose_self_improvement,
        track_improvement_outcome,
        get_improvement_history,
    )
    TOOL_DEFINITIONS.extend(SELF_OPTIMIZATION_TOOLS)
    TOOL_REGISTRY.update({
        "run_self_optimization_analysis": run_self_optimization_analysis,
        "get_my_health_summary": get_my_health_summary,
        "propose_self_improvement": propose_self_improvement,
        "track_improvement_outcome": track_improvement_outcome,
        "get_improvement_history": get_improvement_history,
    })
    log_with_context(logger, "info", "Self-Optimization tools loaded (Phase 21 3C)", count=len(SELF_OPTIMIZATION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Self-Optimization tools load failed", error=str(e))

# Phase 21: Advanced Reasoning (3B - Multi-Step Reasoning)
try:
    from .tool_modules.advanced_reasoning_tools import (
        TOOLS as ADVANCED_REASONING_TOOLS,
        decompose_complex_question,
        execute_reasoning_plan,
        reason_step_by_step,
        validate_my_reasoning,
    )
    TOOL_DEFINITIONS.extend(ADVANCED_REASONING_TOOLS)
    TOOL_REGISTRY.update({
        "decompose_complex_question": decompose_complex_question,
        "execute_reasoning_plan": execute_reasoning_plan,
        "reason_step_by_step": reason_step_by_step,
        "validate_my_reasoning": validate_my_reasoning,
    })
    log_with_context(logger, "info", "Advanced Reasoning tools loaded (Phase 21 3B)", count=len(ADVANCED_REASONING_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Advanced Reasoning tools load failed", error=str(e))



# Load SaaS Agent tools (Phase 22A-10 -- T-20260319-006)
try:
    from .tool_modules.saas_tools import (
        SAAS_TOOLS,
        saas_review_funnel_metrics,
        saas_prioritize_growth_experiments,
        saas_summarize_icp_signals,
        saas_review_pricing_hypotheses,
    )
    TOOL_DEFINITIONS.extend(SAAS_TOOLS)
    TOOL_REGISTRY.update({
        "saas_review_funnel_metrics": saas_review_funnel_metrics,
        "saas_prioritize_growth_experiments": saas_prioritize_growth_experiments,
        "saas_summarize_icp_signals": saas_summarize_icp_signals,
        "saas_review_pricing_hypotheses": saas_review_pricing_hypotheses,
    })
    log_with_context(logger, "info", "SaaS Agent tools loaded (Phase 22A-10)", count=len(SAAS_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "SaaS Agent tools load failed", error=str(e))


# Load Figma tools (Phase 22A-11)
try:
    from .tool_modules.figma_tools import (
        FIGMA_TOOLS,
        figma_get_file_metadata,
        figma_get_nodes,
        figma_list_comments,
        figma_post_comment,
        figma_list_dev_resources,
        figma_create_dev_resources,
        figma_update_dev_resources,
        figma_delete_dev_resource,
        figma_list_project_files,
        figma_register_webhook,
        figma_list_webhooks,
        figma_update_webhook,
        figma_delete_webhook,
    )
    TOOL_DEFINITIONS.extend(FIGMA_TOOLS)
    TOOL_REGISTRY.update({
        "figma_get_file_metadata": figma_get_file_metadata,
        "figma_get_nodes": figma_get_nodes,
        "figma_list_comments": figma_list_comments,
        "figma_post_comment": figma_post_comment,
        "figma_list_dev_resources": figma_list_dev_resources,
        "figma_create_dev_resources": figma_create_dev_resources,
        "figma_update_dev_resources": figma_update_dev_resources,
        "figma_delete_dev_resource": figma_delete_dev_resource,
        "figma_list_project_files": figma_list_project_files,
        "figma_register_webhook": figma_register_webhook,
        "figma_list_webhooks": figma_list_webhooks,
        "figma_update_webhook": figma_update_webhook,
        "figma_delete_webhook": figma_delete_webhook,
    })
    log_with_context(logger, "info", "Figma tools loaded (Phase 22A-11)", count=len(FIGMA_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Figma tools load failed", error=str(e))

# T-020: Self-Inspection Tools (extracted from inline)
try:
    from .tool_modules.self_inspection_tools import (
        SELF_INSPECTION_TOOLS,
        tool_analyze_cross_session_patterns,
        tool_optimize_system_prompt,
        tool_enable_experimental_feature,
        tool_validate_tool_registry,
        tool_get_response_metrics,
    )
    TOOL_DEFINITIONS.extend(SELF_INSPECTION_TOOLS)
    TOOL_REGISTRY.update({
        "analyze_cross_session_patterns": tool_analyze_cross_session_patterns,
        "optimize_system_prompt": tool_optimize_system_prompt,
        "enable_experimental_feature": tool_enable_experimental_feature,
        "validate_tool_registry": tool_validate_tool_registry,
        "get_response_metrics": tool_get_response_metrics,
    })
    log_with_context(logger, "info", "Self-Inspection tools loaded (T-020 refactor)", count=len(SELF_INSPECTION_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Self-Inspection tools load failed", error=str(e))

# T-020: Knowledge Tools (API Context Packs - previously unregistered)
try:
    from .tool_modules.knowledge_tools import (
        KNOWLEDGE_TOOLS,
        tool_list_api_context_packs,
        tool_read_api_context_pack,
        tool_search_api_context_packs,
    )
    TOOL_DEFINITIONS.extend(KNOWLEDGE_TOOLS)
    TOOL_REGISTRY.update({
        "list_api_context_packs": tool_list_api_context_packs,
        "read_api_context_pack": tool_read_api_context_pack,
        "search_api_context_packs": tool_search_api_context_packs,
    })
    log_with_context(logger, "info", "Knowledge tools loaded (T-020 fix)", count=len(KNOWLEDGE_TOOLS))
except Exception as e:
    log_with_context(logger, "warning", "Knowledge tools load failed", error=str(e))

# T-020: Deploy Tools (Self-deployment - previously unregistered)
try:
    from .tool_modules.deploy_tools import (
        tool_deploy_code_changes,
        tool_validate_deploy_readiness,
        tool_get_deploy_history,
    )
    # Define schemas inline since no DEPLOY_TOOLS constant exists
    DEPLOY_TOOL_SCHEMAS = [
        {
            "name": "deploy_code_changes",
            "description": "Deploy code changes to production (Jarvis self-deploy). Requires autonomy level >= 2.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "validate_only": {"type": "boolean", "description": "Only validate without deploying"},
                    "skip_critical_check": {"type": "boolean", "description": "Skip critical file warning"},
                    "reason": {"type": "string", "description": "Reason for deployment"}
                }
            }
        },
        {
            "name": "validate_deploy_readiness",
            "description": "Check if code is ready for deployment (syntax, imports, health).",
            "input_schema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_deploy_history",
            "description": "Get recent deployment history.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of entries to return", "default": 10}
                }
            }
        }
    ]
    TOOL_DEFINITIONS.extend(DEPLOY_TOOL_SCHEMAS)
    TOOL_REGISTRY.update({
        "deploy_code_changes": tool_deploy_code_changes,
        "validate_deploy_readiness": tool_validate_deploy_readiness,
        "get_deploy_history": tool_get_deploy_history,
    })
    log_with_context(logger, "info", "Deploy tools loaded (T-020 fix)", count=3)
except Exception as e:
    log_with_context(logger, "warning", "Deploy tools load failed", error=str(e))

def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    trace_id: str = None,
    actor: str = "jarvis",
    reason: str = None,
    session_id: str = None,
    domain: str = None,
    skip_guardrails: bool = False
) -> Dict[str, Any]:
    """Execute a tool by name with given input.

    Gate A: All executions are logged to tool_audit table for traceability.
    Gate B (L0): Guardrails check before execution for autonomous actions.
    """
    import time
    start_time = time.time()
    metrics_available = False
    try:
        from .metrics import (
            TOOL_CALLS_TOTAL,
            TOOL_DURATION_SECONDS,
            TOOL_SUCCESS_TOTAL,
            TOOL_ERRORS_TOTAL,
        )
        metrics_available = True
    except Exception:
        metrics_available = False

    if metrics_available:
        TOOL_CALLS_TOTAL.labels(tool=tool_name).inc()

    if tool_name not in TOOL_REGISTRY:
        duration_ms = int((time.time() - start_time) * 1000)
        if metrics_available:
            TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration_ms / 1000.0)
            TOOL_ERRORS_TOTAL.labels(tool=tool_name, error_type="unknown_tool").inc()
        _log_tool_audit(
            trace_id=trace_id,
            actor=actor,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output={"error": f"Unknown tool: {tool_name}"},
            reason=reason,
            duration_ms=0,
            success=False,
            error_message=f"Unknown tool: {tool_name}"
        )
        return {"error": f"Unknown tool: {tool_name}"}

    # Gate B (L0): Guardrails check for autonomous actions
    # Skip for: guardrails tools (avoid recursion), explicit skip, or user-initiated
    guardrails_tools = {"check_guardrails", "get_guardrails", "add_guardrail",
                        "update_guardrail", "request_override", "revoke_override",
                        "get_audit_log", "add_guardrail_feedback", "get_guardrails_summary"}
    read_only_safe_tools = {
        "search_knowledge",
        "search_emails",
        "search_chats",
        "get_recent_activity",
        "get_calendar_events",
        "get_gmail_messages",
        "recall_facts",
        "recall_conversation_history",
        "system_health_check",
        "self_validation_pulse",
        "introspect_capabilities",
    }
    if (
        not skip_guardrails
        and actor == "jarvis"
        and tool_name not in guardrails_tools
        and tool_name not in read_only_safe_tools
    ):
        try:
            from .services.guardrails_service import get_guardrails_service
            guardrails_service = get_guardrails_service()
            allowed, results, audit_id = guardrails_service.check_before_action(
                action_type="tool_call",
                action_details={"tool_name": tool_name, "input": tool_input},
                tool_name=tool_name,
                domain=domain,
                session_id=session_id,
                source="execute_tool"
            )
            if not allowed:
                blocking_reasons = [r.reason for r in results if not r.passed]
                duration_ms = int((time.time() - start_time) * 1000)
                if metrics_available:
                    TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration_ms / 1000.0)
                    TOOL_ERRORS_TOTAL.labels(tool=tool_name, error_type="guardrails_blocked").inc()
                _log_tool_audit(
                    trace_id=trace_id,
                    actor=actor,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output={"blocked": True, "reasons": blocking_reasons, "audit_id": audit_id},
                    reason=reason,
                    duration_ms=duration_ms,
                    success=False,
                    error_message=f"Blocked by guardrails: {'; '.join(blocking_reasons)}"
                )
                return {
                    "blocked": True,
                    "error": "Action blocked by guardrails",
                    "reasons": blocking_reasons,
                    "audit_id": audit_id,
                    "can_override": any(r.override_allowed for r in results if not r.passed)
                }
        except Exception as e:
            log_with_context(logger, "warning", "Guardrails check failed, proceeding cautiously",
                           tool=tool_name, error=str(e))

    try:
        result = TOOL_REGISTRY[tool_name](**tool_input)
        duration_ms = int((time.time() - start_time) * 1000)
        if metrics_available:
            TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration_ms / 1000.0)
            TOOL_SUCCESS_TOTAL.labels(tool=tool_name).inc()

        _log_tool_audit(
            trace_id=trace_id,
            actor=actor,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=result,
            reason=reason,
            duration_ms=duration_ms,
            success=True
        )
        return result
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        if metrics_available:
            TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration_ms / 1000.0)
            TOOL_ERRORS_TOTAL.labels(tool=tool_name, error_type=type(e).__name__).inc()
        log_with_context(logger, "error", "Tool execution failed",
                        tool=tool_name, error=str(e))

        _log_tool_audit(
            trace_id=trace_id,
            actor=actor,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output={"error": str(e)},
            reason=reason,
            duration_ms=duration_ms,
            success=False,
            error_message=str(e)
        )
        return {"error": str(e)}


def _log_tool_audit(
    trace_id: str,
    actor: str,
    tool_name: str,
    tool_input: Dict,
    tool_output: Dict,
    reason: str,
    duration_ms: int,
    success: bool,
    error_message: str = None
):
    """Log tool execution to audit table."""
    try:
        from .postgres_state import get_cursor
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO tool_audit
                (trace_id, actor, tool_name, tool_input, tool_output, reason, duration_ms, success, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                trace_id,
                actor,
                tool_name,
                json.dumps(tool_input) if tool_input else '{}',
                json.dumps(tool_output) if tool_output else '{}',
                reason,
                duration_ms,
                success,
                error_message
            ))
    except Exception as e:
        log_with_context(logger, "warning", "Failed to log tool audit", error=str(e))


def get_tool_definitions() -> List[Dict]:
    """Get tool definitions for Anthropic API (deduplicated by name, normalized schema)."""
    seen = set()
    unique: List[Dict] = []
    for tool in TOOL_DEFINITIONS:
        name = tool.get("name")
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)

        # Normalize: Anthropic API expects 'input_schema', not 'parameters'
        normalized = {
            "name": name,
            "description": tool.get("description", "")
        }

        # Get schema from either 'parameters' or 'input_schema'
        schema = tool.get("input_schema") or tool.get("parameters") or {}

        # Ensure schema has required 'type' field
        if not schema.get("type"):
            schema = {"type": "object", "properties": schema.get("properties", {})}

        normalized["input_schema"] = schema
        unique.append(normalized)
    return unique
