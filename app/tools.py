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
    {
        "name": "delegate_ollama_task",
        "description": "Delegate a task to local Ollama via the queue. Use for summarization, extraction, translation, classification, formatting, or simple generation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["summarize", "extract", "translate", "classify", "generate", "analyze", "format"],
                    "description": "Type of task to run on Ollama"
                },
                "instructions": {
                    "type": "string",
                    "description": "Clear instructions for the task"
                },
                "input_text": {
                    "type": "string",
                    "description": "Direct text input (mutually exclusive with input_path)"
                },
                "input_path": {
                    "type": "string",
                    "description": "Path to input file (mutually exclusive with input_text)"
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional path to write the result"
                },
                "model": {
                    "type": "string",
                    "description": "Preferred Ollama model (optional)"
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum output tokens",
                    "default": 1000
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (0.0-1.0)",
                    "default": 0.3
                },
                "language": {
                    "type": "string",
                    "description": "Output language",
                    "default": "de"
                },
                "output_format": {
                    "type": "string",
                    "enum": ["text", "json", "markdown", "bullet_points"],
                    "default": "text"
                },
                "callback_url": {
                    "type": "string",
                    "description": "Optional callback URL (allowlist enforced)"
                }
            },
            "required": ["task_type", "instructions"]
        }
    },
    {
        "name": "set_timer",
        "description": "Create a reminder timer scheduled via n8n and stored in Redis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Reminder text to send"
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay in seconds"
                },
                "delay_minutes": {
                    "type": "number",
                    "description": "Delay in minutes"
                },
                "due_at": {
                    "type": "string",
                    "description": "ISO timestamp for when to fire"
                },
                "user_id": {
                    "type": "string",
                    "description": "Telegram user id (defaults to current user)"
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Confirm creation for long timers",
                    "default": False
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "cancel_timer",
        "description": "Cancel an existing timer by timer_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timer_id": {
                    "type": "string",
                    "description": "Timer ID to cancel"
                },
                "user_id": {
                    "type": "string",
                    "description": "User id (optional)"
                }
            },
            "required": ["timer_id"]
        }
    },
    {
        "name": "list_timers",
        "description": "List timers for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "User id (optional)"
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (pending, fired, canceled)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max timers to return",
                    "default": 50
                }
            }
        }
    },
    {
        "name": "get_ollama_task_status",
        "description": "Get status for a queued Ollama task by task_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task ID"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_ollama_callback_result",
        "description": "Get the result of a completed async Ollama task. Use after delegate_ollama_task to retrieve the result once the task has been processed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task ID to get result for"
                },
                "recent_only": {
                    "type": "boolean",
                    "description": "If true and no task_id provided, return recent callbacks"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of recent callbacks to return",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "ask_ollama",
        "description": "Ask local Ollama LLM a question and get an answer. SAVES API TOKENS! Use as sub-assistant for: summarization, translation, text analysis, format conversion, simple Q&A, classification. Ollama runs locally and is FREE. Wait for the response (may take 30-60s on first call while model loads).",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question or task for Ollama. Be clear and specific."
                },
                "task_type": {
                    "type": "string",
                    "enum": ["summarize", "translate", "analyze", "classify", "format", "generate", "extract"],
                    "description": "Type of task (helps select best model)",
                    "default": "analyze"
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional custom system prompt to override default assistant behavior"
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max response tokens (default: 1500)"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "ollama_python",
        "description": "Generate and execute Python code via local Ollama. SAVES API TOKENS by using local LLM for code generation. Use this for calculations, data processing, analysis, formatting, or any task that can be solved with Python code. The code runs in a secure sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Natural language description of what to compute or do. Be specific about expected output format."
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context or data to use in the code"
                },
                "model": {
                    "type": "string",
                    "description": "Specific Ollama model (default: auto-select best coding model)"
                }
            },
            "required": ["task_description"]
        }
    },
    # Sub-Agent Framework Tools (Phase 18)
    {
        "name": "delegate_to_subagent",
        "description": "Delegate a task to a specialized sub-agent. Each agent has different strengths:\n- ollama: Local LLM (free, fast) - for summaries, formatting, simple tasks\n- openai: GPT-4o (vision, reasoning) - for complex analysis, images\n- anthropic: Claude (long context) - for code review, deep analysis\n- perplexity: Web search - for current info, research, fact-checking\nReturns task_id for async tracking or result if sync=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "enum": ["ollama", "openai", "anthropic", "perplexity"],
                    "description": "Sub-agent: ollama (local), openai (GPT-4), anthropic (Claude), perplexity (web search)",
                    "default": "ollama"
                },
                "instructions": {
                    "type": "string",
                    "description": "Clear task instructions for the sub-agent"
                },
                "input_text": {
                    "type": "string",
                    "description": "Input text for the task"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context"
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools to enable (for ollama/openai/anthropic): read_file, search_kb, calculate, format_json, format_markdown, extract_text, list_files"
                },
                "sync": {
                    "type": "boolean",
                    "description": "Wait for result (true) or return immediately with task_id (false)",
                    "default": False
                }
            },
            "required": ["instructions"]
        }
    },
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
    {
        "name": "get_subagent_result",
        "description": "Get the result of a delegated sub-agent task. Use after delegate_to_subagent with sync=false.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Sub-agent task ID"
                }
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
    {
        "name": "execute_python",
        "description": """Execute Python code YOU write directly in the sandbox.

ALLOWED IMPORTS: math, json, datetime, re, collections, itertools, statistics, csv, hashlib, base64, uuid, time, copy, textwrap

SAFE FILE ACCESS (auto-injected helpers):
- safe_read_file(path, max_lines=500) - Read files from /brain/system/, /brain/projects/, /brain/notes/
- safe_list_files(directory, pattern='*') - List files in allowed directories

EXAMPLE:
  content = safe_read_file('/brain/system/docker/TASKS.md')
  files = safe_list_files('/brain/system/ingestion/app', '*.py')

FORBIDDEN: direct open(), network, subprocess, exec/eval, os.system""",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Must use print() for output. Use safe_read_file() for file access."
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason why this code is being executed (for audit)"
                }
            },
            "required": ["code", "reason"]
        }
    },
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
- /brain/system/ingestion/app/ - Jarvis source code (*.py)
- /brain/system/policies/ - System prompts, policies (*.md)
- /brain/system/prompts/ - Persona configs, modes (*.json)
- /brain/projects/ - Project files
- /brain/notes/ - Notes
- /data/linkedin/ - LinkedIn knowledge markdown updates
- /data/visualfox/ - VisualFox knowledge markdown updates

EXAMPLES:
- docker-compose.yml → /brain/system/docker/docker-compose.yml
- Jarvis code → /brain/system/ingestion/app/agent.py
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
- /brain/system/ingestion/app/ - Jarvis source code (*.py)
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
    {
        "name": "get_ollama_task_status",
        "description": "Get the status of a queued Ollama task by task_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task id (e.g. ollama_YYYYMMDD_HHMMSS_xxxxxxxx)"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_ollama_queue_status",
        "description": "Get a summary of pending and processing Ollama tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max tasks to return per queue",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "cancel_ollama_task",
        "description": "Cancel a queued Ollama task if it is still pending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task id to cancel"
                }
            },
            "required": ["task_id"]
        }
    },
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
    {
        "name": "request_python_sandbox",
        "description": """Request manual approval to run Jarvis-authored Python code in a sandbox. This does NOT execute code; it queues an approval request.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute (queued for approval)"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for execution (audit trail)"
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (max 60)",
                    "default": 30
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata for audit"
                }
            },
            "required": ["code"]
        }
    },
    # Dynamic Tool Creation (Phase 18+)
    {
        "name": "write_dynamic_tool",
        "description": "Create a new dynamic tool that Jarvis can use. Write Python code that becomes a callable tool. Tools go to sandbox first by default for safety review. Use this to extend your capabilities!",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name in snake_case (e.g., 'my_custom_tool')"
                },
                "description": {
                    "type": "string",
                    "description": "What the tool does - be clear and concise"
                },
                "code": {
                    "type": "string",
                    "description": "Python code for the tool handler. Must return a dict. Receives **kwargs."
                },
                "parameters": {
                    "type": "object",
                    "description": "JSON schema for tool parameters (properties only)"
                },
                "category": {
                    "type": "string",
                    "description": "Tool category (memory, utility, analysis, custom)",
                    "default": "custom"
                },
                "sandbox": {
                    "type": "boolean",
                    "description": "If true (default), tool goes to sandbox first for review",
                    "default": True
                }
            },
            "required": ["name", "description", "code"]
        }
    },
    {
        "name": "promote_sandbox_tool",
        "description": "Promote a tool from sandbox to live production. Use after testing a tool created with write_dynamic_tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the sandbox tool to promote"
                }
            },
            "required": ["name"]
        }
    },
    # Learning & Memory Tools
    {
        "name": "record_learning",
        "description": "Record a learning, insight, or pattern for cross-session analysis. Use when you discover something important about the user, workflow, or system.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The learning or insight to record"
                },
                "category": {
                    "type": "string",
                    "description": "Category: general, capability, preference, workflow, technical",
                    "enum": ["general", "capability", "preference", "workflow", "technical"],
                    "default": "general"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level 0.0-1.0",
                    "default": 0.8
                },
                "source": {
                    "type": "string",
                    "description": "Source: conversation, observation, feedback",
                    "default": "conversation"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for the learning"
                }
            },
            "required": ["fact"]
        }
    },
    {
        "name": "get_learnings",
        "description": "Retrieve recorded learnings and insights. Returns a summary grouped by category. Use to recall what you've learned across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                    "enum": ["general", "capability", "preference", "workflow", "technical"]
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search",
                    "default": 30
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                    "default": 10
                },
                "compact": {
                    "type": "boolean",
                    "description": "Return compact format with summary (default true)",
                    "default": True
                }
            }
        }
    },
    # Context Persistence Tools
    {
        "name": "store_context",
        "description": "Store a context value for later retrieval. Use for cross-session state, preferences, or temporary memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Unique key for this context"
                },
                "value": {
                    "type": "string",
                    "description": "Value to store (string or JSON)"
                },
                "context_type": {
                    "type": "string",
                    "description": "Type: general, preference, state, memory",
                    "enum": ["general", "preference", "state", "memory"],
                    "default": "general"
                },
                "ttl_hours": {
                    "type": "integer",
                    "description": "Time to live in hours (default 168 = 1 week)",
                    "default": 168
                }
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "recall_context",
        "description": "Recall a stored context value. Use to retrieve cross-session state or memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to recall (if omitted, returns all for context_type)"
                },
                "context_type": {
                    "type": "string",
                    "description": "Filter by type",
                    "enum": ["general", "preference", "state", "memory"]
                }
            }
        }
    },
    {
        "name": "forget_context",
        "description": "Delete stored context. Use to clean up old or invalid context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Specific key to delete"
                },
                "context_type": {
                    "type": "string",
                    "description": "Delete all of this type"
                }
            }
        }
    },
    # === Batch Operations (avoid step-limit when doing multiple memory ops) ===
    {
        "name": "record_learnings_batch",
        "description": "Record MULTIPLE learnings in ONE call. Use this instead of calling record_learning multiple times to avoid hitting step limits! Each item needs 'fact' (required), optionally 'category', 'confidence', 'source', 'context'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learnings": {
                    "type": "array",
                    "description": "Array of learning objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "The learning/insight to record"},
                            "category": {"type": "string", "description": "Category: general, technical, preference, workflow, capability"},
                            "confidence": {"type": "number", "description": "Confidence 0.0-1.0"},
                            "source": {"type": "string", "description": "Source: conversation, observation, user"},
                            "context": {"type": "string", "description": "Additional context"}
                        },
                        "required": ["fact"]
                    }
                }
            },
            "required": ["learnings"]
        }
    },
    {
        "name": "store_contexts_batch",
        "description": "Store MULTIPLE context values in ONE call. Use this instead of calling store_context multiple times to avoid hitting step limits! Each item needs 'key' and 'value' (required), optionally 'context_type', 'ttl_hours'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contexts": {
                    "type": "array",
                    "description": "Array of context objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Unique key for this context"},
                            "value": {"description": "Value to store (string or object)"},
                            "context_type": {"type": "string", "description": "Type: general, preference, state, memory"},
                            "ttl_hours": {"type": "integer", "description": "Time to live in hours (default 168 = 1 week)"}
                        },
                        "required": ["key", "value"]
                    }
                }
            },
            "required": ["contexts"]
        }
    },
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
    # Phase 20: Identity Evolution Tools
    {
        "name": "get_self_model",
        "description": "Get Jarvis's current self-model and identity. Returns core traits, strengths, growth areas, values, communication style, relationship memories, and recent learnings. Use for self-reflection.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "evolve_identity",
        "description": "Evolve Jarvis's identity based on significant learnings. Use carefully to update personality traits, values, or self-model. Significant changes require human review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "evolution_type": {
                    "type": "string",
                    "enum": ["trait_update", "value_update", "self_model_update", "relationship_update", "communication_style_update"],
                    "description": "Type of evolution"
                },
                "field": {
                    "type": "string",
                    "enum": ["core_traits", "self_model", "values", "communication_style"],
                    "description": "Which field to update"
                },
                "new_value": {
                    "description": "The new value to set (type depends on field)"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this evolution is happening (important for audit)"
                },
                "trigger_event": {
                    "type": "string",
                    "description": "What triggered this evolution"
                }
            },
            "required": ["evolution_type", "field", "new_value", "reason"]
        }
    },
    {
        "name": "log_experience",
        "description": "Log an experience for cross-session learning. Record what worked, what didn't, and lessons learned. Feeds pattern recognition and identity evolution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "experience_type": {
                    "type": "string",
                    "enum": ["success", "failure", "learning", "insight", "correction"],
                    "description": "Type of experience"
                },
                "context": {
                    "type": "string",
                    "description": "What was happening"
                },
                "action_taken": {
                    "type": "string",
                    "description": "What action was taken"
                },
                "outcome": {
                    "type": "string",
                    "description": "What was the result"
                },
                "lesson_learned": {
                    "type": "string",
                    "description": "What was learned"
                },
                "applies_to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories this applies to ['communication', 'tool_usage', 'timing']"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in this learning (0-1)",
                    "default": 0.7
                }
            },
            "required": ["experience_type", "context"]
        }
    },
    {
        "name": "get_relationship",
        "description": "Get relationship memory for a user. Returns relationship stage, preferences learned, emotional patterns, trust level, interaction history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default 1 for Micha)",
                    "default": 1
                }
            }
        }
    },
    {
        "name": "update_relationship",
        "description": "Update relationship memory. Record learned preferences, recognized patterns, or trust changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default 1)",
                    "default": 1
                },
                "user_preferences": {
                    "type": "object",
                    "description": "Preferences to merge/update"
                },
                "emotional_patterns": {
                    "type": "object",
                    "description": "Emotional patterns to merge/update"
                },
                "trust_level": {
                    "type": "number",
                    "description": "New trust level (0-1)"
                }
            }
        }
    },
    {
        "name": "get_learning_patterns",
        "description": "Get validated learning patterns from cross-session analysis. Returns insights about preferences, timing, communication that have been observed multiple times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold (0-1)",
                    "default": 0.6
                }
            }
        }
    },
    {
        "name": "record_session_learning",
        "description": "Record learnings from a completed session. Call at end of meaningful sessions to capture topics, tools used, successes, failures, and explicit learnings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Unique session identifier"
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics discussed"
                },
                "tools_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools that were used"
                },
                "successful_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actions that worked well"
                },
                "failed_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actions that failed"
                },
                "learnings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "content": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    },
                    "description": "Explicit learnings"
                },
                "user_mood_start": {"type": "string"},
                "user_mood_end": {"type": "string"},
                "performance_rating": {
                    "type": "number",
                    "description": "Self-rating 0-1"
                },
                "improvement_notes": {"type": "string"}
            },
            "required": ["session_id", "topics", "tools_used"]
        }
    },
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
    }
]


# ============ Tool Implementations ============

def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in re.split(r"[^a-zA-Z0-9äöüÄÖÜß]+", text.lower()) if len(t) > 2]


def _lexical_score(query: str, text: str, source_path: str = "") -> float:
    """
    Lightweight lexical score for hybrid reranking.
    Uses token overlap + bigram match + filename/path hints.
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0

    text_lower = (text or "").lower()
    tokens = set(_tokenize(text))
    match_count = sum(1 for t in q_tokens if t in tokens)
    token_score = match_count / max(len(q_tokens), 1)

    bigrams = list(zip(q_tokens, q_tokens[1:]))
    bigram_hits = 0
    for a, b in bigrams:
        if f"{a} {b}" in text_lower:
            bigram_hits += 1
    bigram_score = (bigram_hits / max(len(bigrams), 1)) if bigrams else 0.0

    phrase_boost = 0.15 if query.lower() in text_lower else 0.0

    path_lower = (source_path or "").lower()
    path_boost = 0.0
    for t in q_tokens:
        if t in path_lower:
            path_boost = 0.1
            break

    score = (token_score * 0.65) + (bigram_score * 0.2) + phrase_boost + path_boost
    return min(1.0, round(score, 4))


def _recency_score(ts: str) -> float:
    if not ts:
        return 0.5
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
    except Exception:
        return 0.5
    days_ago = (datetime.now(tz=dt.tzinfo) - dt).total_seconds() / 86400.0
    if days_ago <= 0:
        return 1.0
    decay = math.log(2) / max(RECENCY_HALF_LIFE_DAYS, 1.0)
    score = math.exp(-decay * days_ago)
    return max(0.1, round(score, 4))


def _search_qdrant(
    query: str,
    collection: str,
    limit: int = 5,
    filters: Dict = None,
    recency_days: int = None
) -> List[Dict]:
    """
    Core search function against Qdrant.

    Returns:
        List of search results

    Raises:
        JarvisException: On connection errors or service unavailability
    """
    try:
        q_vec = embed_texts([query])[0]

        search_limit = limit * 4 if LEXICAL_RERANK_ENABLED else limit
        payload = {
            "vector": q_vec,
            "limit": search_limit * 2 if recency_days else search_limit,  # fetch more if filtering
            "with_payload": True,
            # HNSW search optimization: lower ef = faster but less accurate
            # Default is 128, using 64 for ~40% speed improvement with minimal accuracy loss
            "params": {
                "hnsw_ef": 64,
                "exact": False  # Use approximate search for speed
            }
        }

        if filters:
            must = []
            for key, value in filters.items():
                must.append({"key": key, "match": {"value": value}})
            if must:
                payload["filter"] = {"must": must}

        r = requests.post(
            f"{QDRANT_BASE}/collections/{collection}/points/search",
            json=payload,
            timeout=30,
        )

        if r.status_code == 404:
            # Collection doesn't exist - expected for new namespaces
            log_with_context(logger, "debug", "Collection not found (expected)",
                           collection=collection)
            return []

        if r.status_code == 503:
            log_with_context(logger, "warning", "Qdrant temporarily unavailable",
                           collection=collection)
            raise JarvisException(
                code=ErrorCode.QDRANT_UNAVAILABLE,
                message="Vector search temporarily unavailable",
                status_code=503,
                details={"collection": collection},
                recoverable=True,
                retry_after=10,
                hint="Qdrant service is overloaded, try again shortly"
            )

        r.raise_for_status()

        results = []
        for hit in r.json().get("result", []):
            pl = hit.get("payload", {}) or {}

            # Apply recency filter
            if recency_days:
                cutoff = (datetime.now() - timedelta(days=recency_days)).isoformat()
                ts = pl.get("event_ts") or pl.get("ingest_ts") or ""
                if ts and ts < cutoff:
                    continue

            text_full = pl.get("text", "") or ""
            event_ts = pl.get("event_ts") or pl.get("ingest_ts")
            vector_score = hit.get("score") or 0.0
            lexical_score = _lexical_score(query, text_full, pl.get("source_path"))
            recency_score = _recency_score(event_ts)

            # Hybrid score: vector + lexical (decay applied later)
            hybrid_score = (RERANK_ALPHA * vector_score) + ((1 - RERANK_ALPHA) * lexical_score)

            # Apply recency decay weight (best-practice)
            if RECENCY_WEIGHT > 0:
                hybrid_score = hybrid_score * ((1 - RECENCY_WEIGHT) + (RECENCY_WEIGHT * recency_score))

            results.append({
                "score": vector_score,
                "hybrid_score": round(hybrid_score, 6),
                "lexical_score": lexical_score,
                "recency_score": recency_score,
                "text": text_full[:500],  # Truncate for context
                "source_path": pl.get("source_path"),
                "doc_type": pl.get("doc_type"),
                "channel": pl.get("channel"),
                "label": pl.get("label"),
                "labels": pl.get("labels"),
                "event_ts": event_ts,
            })

        # Rerank by hybrid score if enabled; otherwise keep vector score
        if LEXICAL_RERANK_ENABLED:
            results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
        else:
            results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return results[:limit]

    except JarvisException:
        raise  # Re-raise our own exceptions
    except requests.Timeout as e:
        log_with_context(logger, "error", "Qdrant search timeout",
                        error=str(e), collection=collection)
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Vector search timed out",
            status_code=504,
            details={"collection": collection, "query_length": len(query)},
            recoverable=True,
            retry_after=15,
            hint="Search query may be too complex, try simpler terms"
        )
    except requests.ConnectionError as e:
        log_with_context(logger, "error", "Qdrant connection error",
                        error=str(e), collection=collection)
        raise qdrant_unavailable({"collection": collection, "error": str(e)[:100]})
    except requests.HTTPError as e:
        log_with_context(logger, "error", "Qdrant HTTP error",
                        error=str(e), collection=collection, status=e.response.status_code if e.response else None)
        raise JarvisException(
            code=ErrorCode.QDRANT_ERROR,
            message=f"Vector search failed: {str(e)[:100]}",
            status_code=502,
            details={"collection": collection},
            recoverable=True,
            retry_after=10
        )
    except Exception as e:
        log_with_context(logger, "error", "Qdrant search unexpected error",
                        error=str(e), collection=collection, error_type=type(e).__name__)
        raise wrap_external_error(e, service="qdrant_search")


@observe(name="tool_search_knowledge")
def tool_search_knowledge(
    query: str,
    namespace: str = "private",
    limit: int = 5,
    recency_days: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Search across all knowledge (emails + chats).

    Uses resilient search pattern: if some collections fail, returns partial results
    with error info. Only raises JarvisException if ALL collections fail.
    """
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_knowledge",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace)
    metrics.inc("tool_search_knowledge")

    if langfuse_context:
        try:
            langfuse_context.update_current_trace(
                metadata={
                    "tool": "search_knowledge",
                    "namespace": namespace,
                    "limit": limit,
                    "recency_days": recency_days,
                    "query_length": len(query) if query else 0,
                    "query_expanded": query_changed,
                },
                tags=["tool", "search_knowledge"],
            )
        except Exception:
            pass

    all_results = []
    errors = []
    collections_searched = 0
    collections_failed = 0

    # Handle namespace aliases (work/all)
    namespaces = [] if namespace == COMMS_NAMESPACE else expand_namespaces(namespace)

    for ns in namespaces:
        # Search main collection (emails, docs)
        try:
            collections_searched += 1
            results = _search_qdrant(
                query=expanded_query,
                collection=f"jarvis_{ns}",
                limit=limit,
                recency_days=recency_days
            )
            all_results.extend(results)
        except JarvisException as e:
            collections_failed += 1
            errors.append({"collection": f"jarvis_{ns}", "error": e.error.message})
            log_with_context(logger, "warning", "Partial search failure",
                           collection=f"jarvis_{ns}", error=e.error.message)

    # Search unified comms collection (chats)
    for ns in comms_origin_namespaces(namespace):
        try:
            collections_searched += 1
            results = _search_qdrant(
                query=expanded_query,
                collection=COMMS_COLLECTION,
                limit=limit,
                recency_days=recency_days,
                filters={"origin_namespace": ns}
            )
            all_results.extend(results)
        except JarvisException as e:
            collections_failed += 1
            errors.append({"collection": COMMS_COLLECTION, "error": e.error.message})
            log_with_context(logger, "warning", "Partial search failure",
                           collection=COMMS_COLLECTION, error=e.error.message)

    # If ALL collections failed, raise exception
    if collections_failed == collections_searched and collections_searched > 0:
        log_with_context(logger, "error", "All collections failed",
                        query=query[:50], errors=errors)
        raise JarvisException(
            code=ErrorCode.QDRANT_UNAVAILABLE,
            message="Knowledge search failed - all vector collections unavailable",
            status_code=503,
            details={"errors": errors, "query": query[:50]},
            recoverable=True,
            retry_after=30,
            hint="Qdrant may be down or overloaded. Try again in a moment."
        )

    # Sort by score and dedupe
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    seen_paths = set()
    unique_results = []
    for r in all_results:
        path = r.get("source_path", "")
        if path not in seen_paths:
            seen_paths.add(path)
            unique_results.append(r)
        if len(unique_results) >= limit:
            break

    result = {
        "results": unique_results,
        "count": len(unique_results),
        "query": query,
        "ranking": "hybrid" if LEXICAL_RERANK_ENABLED else "vector"
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True

    # Include partial failure info if some collections failed
    if errors:
        result["partial_failure"] = True
        result["search_errors"] = errors
        result["collections_searched"] = collections_searched - collections_failed
        result["collections_failed"] = collections_failed

    return result


def tool_search_emails(
    query: str,
    namespace: str = "private",
    label: str = None,
    recency_days: int = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Search emails specifically"""
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_emails",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace, label=label)
    metrics.inc("tool_search_emails")

    filters = {"doc_type": "email"}
    if label:
        filters["label"] = label

    all_results = []
    for ns in expand_namespaces(namespace):
        results = _search_qdrant(
            query=expanded_query,
            collection=f"jarvis_{ns}",
            limit=limit,
            filters=filters,
            recency_days=recency_days
        )
        all_results.extend(results)

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = all_results[:limit]

    result = {
        "results": results,
        "count": len(results),
        "query": query,
        "label_filter": label
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True
    return result


def tool_search_chats(
    query: str,
    namespace: str = "private",
    channel: str = None,
    recency_days: int = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Search chat messages"""
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_chats",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace, channel=channel)
    metrics.inc("tool_search_chats")

    filters = {"doc_type": "chat_window"}
    if channel:
        filters["channel"] = channel

    all_results = []
    for ns in comms_origin_namespaces(namespace):
        results = _search_qdrant(
            query=expanded_query,
            collection=COMMS_COLLECTION,
            limit=limit,
            filters=filters,
            recency_days=recency_days
        )
        all_results.extend(results)

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = all_results[:limit]

    result = {
        "results": results,
        "count": len(results),
        "query": query,
        "channel_filter": channel
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True
    return result


def tool_get_recent_activity(
    days: int = 1,
    namespace: str = "private",
    include_emails: bool = True,
    include_chats: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Get recent activity summary"""
    log_with_context(logger, "info", "Tool: get_recent_activity",
                    days=days, namespace=namespace)
    metrics.inc("tool_get_recent_activity")

    # Use a generic query to get recent items
    results = {
        "period_days": days,
        "namespace": namespace,
        "emails": [],
        "chats": []
    }

    namespaces = expand_namespaces(namespace)

    if include_emails:
        email_results = []
        for ns in namespaces:
            email_results.extend(_search_qdrant(
                query="email message communication update",  # Generic query
                collection=f"jarvis_{ns}",
                limit=10,
                filters={"doc_type": "email"},
                recency_days=days
            ))
        email_results.sort(key=lambda x: x.get("event_ts") or "", reverse=True)
        results["emails"] = email_results[:10]
        results["email_count"] = len(results["emails"])

    if include_chats:
        chat_results = []
        for ns in comms_origin_namespaces(namespace):
            chat_results.extend(_search_qdrant(
                query="chat conversation message discussion",
                collection=COMMS_COLLECTION,
                limit=10,
                filters={"origin_namespace": ns},
                recency_days=days
            ))
        chat_results.sort(key=lambda x: x.get("event_ts") or "", reverse=True)
        results["chats"] = chat_results[:10]
        results["chat_count"] = len(results["chats"])

    return results


def tool_web_search(
    query: str = None,
    num_results: int = 5,
    detailed: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Search the web using Perplexity (primary) or DuckDuckGo (fallback).
    Perplexity provides AI-powered search with source citations.

    Raises:
        JarvisException: On network or API errors with structured error info
    """
    # Support both 'query' parameter and positional
    if query is None:
        query = kwargs.get("query", "")

    if not query:
        return {"error": "query is required"}

    log_with_context(logger, "info", "Tool: web_search", query=query, detailed=detailed)
    metrics.inc("tool_web_search")

    # Try Perplexity first (better results with citations)
    try:
        from .subagents.perplexity_agent import PerplexityAgent, PERPLEXITY_MODELS
        import asyncio

        agent = PerplexityAgent()
        if agent.api_key:
            from .subagents import SubAgentTask

            task = SubAgentTask(
                task_id=SubAgentTask.generate_id("web"),
                agent_id="perplexity",
                instructions=query,
                created_at=datetime.now().isoformat(),
            )

            if detailed:
                agent.default_model = PERPLEXITY_MODELS["huge"]

            # Run async in sync context
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(agent.execute(task))
            finally:
                loop.close()

            if result.status == "completed":
                metrics.inc("tool_web_search_perplexity")
                return {
                    "query": query,
                    "answer": result.result,
                    "source": "perplexity",
                    "model": result.model_used,
                    "execution_time_ms": round(result.execution_time_ms, 2),
                }
    except ImportError:
        pass
    except Exception as e:
        log_with_context(logger, "warning", "Perplexity search failed, falling back to DuckDuckGo", error=str(e))

    # Fallback to DuckDuckGo
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })

        metrics.inc("tool_web_search_duckduckgo")
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "source": "duckduckgo"
        }
    except ImportError:
        raise JarvisException(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Web search not available (no Perplexity key and duckduckgo-search not installed)",
            status_code=503,
            details={"query": query},
            recoverable=False,
            hint="Set PERPLEXITY_API_KEY or install duckduckgo-search"
        )
    except requests.Timeout as e:
        log_with_context(logger, "error", "Web search timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Web search timed out",
            status_code=504,
            details={"query": query},
            recoverable=True,
            retry_after=10,
            hint="Try a simpler query or try again"
        )
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Web search failed",
                        error=error_msg, error_type=type(e).__name__)

        if "rate" in error_msg.lower() or "429" in error_msg:
            raise JarvisException(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="Web search rate limited",
                status_code=429,
                details={"query": query},
                recoverable=True,
                retry_after=60,
                hint="Rate limit - wait before retrying"
            )
        else:
            raise wrap_external_error(e, service="web_search")


def tool_remember_fact(
    fact: str,
    category: str,
    initial_trust_score: float = 0.0,
    source: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store a fact about the user with graduated trust.

    Trust Score Guidelines:
    - 0.0: Inferred or uncertain facts
    - 0.3: User mentioned explicitly
    - 0.5: User confirmed when asked
    - 0.7: Repeatedly validated or critical info

    Facts with trust_score >= 0.5 AND access_count >= 5 become
    candidates for migration to permanent config/YAML storage.

    Raises:
        JarvisException: On database errors with structured error info
    """
    log_with_context(logger, "info", "Tool: remember_fact",
                    category=category, trust_score=initial_trust_score, source=source)
    metrics.inc("tool_remember_fact")

    try:
        from . import memory_store
        fact_id = memory_store.add_fact(
            fact=fact,
            category=category,
            source=source,
            initial_trust_score=initial_trust_score
        )

        # Determine trust level description
        if initial_trust_score >= 0.7:
            trust_level = "high (validated)"
        elif initial_trust_score >= 0.5:
            trust_level = "medium (confirmed)"
        elif initial_trust_score >= 0.3:
            trust_level = "low (explicit)"
        else:
            trust_level = "minimal (inferred)"

        return {
            "status": "remembered",
            "fact": fact,
            "category": category,
            "fact_id": fact_id,
            "trust_score": initial_trust_score,
            "trust_level": trust_level,
            "source": source,
            "note": "Trust score increases with each access (+0.1). Migration candidate at trust >= 0.5 and access >= 5."
        }
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Remember fact failed",
                        error=error_msg, category=category, error_type=type(e).__name__)

        # Check for common SQLite errors
        if "database is locked" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.POSTGRES_ERROR,  # Reusing for DB errors
                message="Memory database is temporarily locked",
                status_code=503,
                details={"category": category, "fact_preview": fact[:50]},
                recoverable=True,
                retry_after=5,
                hint="Another operation is using the database, try again shortly"
            )
        elif "disk" in error_msg.lower() or "full" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Memory storage full or unavailable",
                status_code=507,
                details={"category": category},
                recoverable=False,
                hint="Check disk space on the system"
            )
        else:
            raise wrap_external_error(e, service="memory_store")


@observe(name="tool_recall_facts")
def tool_recall_facts(
    category: str = None,
    query: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall stored facts.

    Raises:
        JarvisException: On database errors with structured error info
    """
    log_with_context(logger, "info", "Tool: recall_facts", category=category, query=query)
    metrics.inc("tool_recall_facts")

    if langfuse_context:
        try:
            langfuse_context.update_current_trace(
                metadata={
                    "tool": "recall_facts",
                    "category": category,
                    "query_length": len(query) if query else 0,
                },
                tags=["tool", "recall_facts"],
            )
        except Exception:
            pass

    try:
        from . import memory_store
        facts = memory_store.get_facts(category=category, query=query)

        return {
            "facts": facts,
            "count": len(facts),
            "category_filter": category,
            "query_filter": query
        }
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Recall facts failed",
                        error=error_msg, category=category, error_type=type(e).__name__)

        # Check for common SQLite errors
        if "database is locked" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.POSTGRES_ERROR,
                message="Memory database is temporarily locked",
                status_code=503,
                details={"category": category, "query": query},
                recoverable=True,
                retry_after=5,
                hint="Another operation is using the database, try again shortly"
            )
        elif "corrupt" in error_msg.lower() or "malformed" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Memory database may be corrupted",
                status_code=500,
                details={"category": category},
                recoverable=False,
                hint="Database maintenance may be required"
            )
        else:
            raise wrap_external_error(e, service="memory_store")


def tool_get_calendar_events(
    timeframe: str = "week",
    account: str = "all",
    **kwargs
) -> Dict[str, Any]:
    """
    Get calendar events via n8n (Google Calendar API gateway).

    Raises:
        JarvisException: On API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: get_calendar_events",
                    timeframe=timeframe, account=account)
    metrics.inc("tool_get_calendar_events")

    try:
        from . import n8n_client

        # Use filtered calendar function
        events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)

        # Check for API-level errors
        if isinstance(events, dict) and events.get("error"):
            error_msg = events.get("error", "Unknown calendar error")
            raise JarvisException(
                code=ErrorCode.CALENDAR_API_ERROR,
                message=f"Failed to fetch calendar: {error_msg}",
                status_code=502,
                details={"timeframe": timeframe, "account": account},
                recoverable="timeout" in str(error_msg).lower(),
                retry_after=15,
                hint="Check n8n Calendar configuration or try again"
            )

        # Include date headers for multi-day views
        include_date = timeframe in ("week", "all")
        formatted = n8n_client.format_events_for_briefing(events, include_date=include_date)

        return {
            "timeframe": timeframe,
            "account": account,
            "events": events,
            "count": len(events),
            "formatted": formatted,
            "source": "n8n"
        }
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Calendar fetch timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Calendar fetch timed out",
            status_code=504,
            details={"timeframe": timeframe, "account": account},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Calendar fetch failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="calendar")


def tool_create_calendar_event(
    summary: str,
    start: str,
    end: str,
    account: str = "projektil",
    description: str = "",
    location: str = "",
    attendees: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a calendar event via n8n.

    Args:
        summary: Event title
        start: Start time in ISO 8601 format (e.g., "2026-01-30T14:00:00+01:00")
        end: End time in ISO 8601 format
        account: "projektil" or "visualfox"
        description: Optional event description
        location: Optional location
        attendees: Optional list of email addresses to invite

    Raises:
        JarvisException: On API errors or invalid datetime formats
    """
    log_with_context(logger, "info", "Tool: create_calendar_event",
                    summary=summary, account=account)
    metrics.inc("tool_create_calendar_event")

    # Validate datetime formats early
    try:
        from datetime import datetime as dt
        dt.fromisoformat(start.replace('Z', '+00:00'))
        dt.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError as e:
        raise JarvisException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Invalid datetime format: {str(e)}",
            status_code=400,
            details={"start": start, "end": end},
            recoverable=False,
            hint="Use ISO 8601 format: YYYY-MM-DDTHH:MM:SS+HH:MM"
        )

    try:
        from . import n8n_client

        result = n8n_client.create_calendar_event(
            summary=summary,
            start=start,
            end=end,
            account=account,
            description=description,
            location=location,
            attendees=attendees
        )

        # Check for API-level errors
        if not result.get("success") and result.get("error"):
            error_msg = result.get("error", "Unknown calendar error")
            raise JarvisException(
                code=ErrorCode.CALENDAR_API_ERROR,
                message=f"Failed to create calendar event: {error_msg}",
                status_code=502,
                details={"summary": summary, "account": account},
                recoverable="timeout" in str(error_msg).lower() or "rate" in str(error_msg).lower(),
                retry_after=30 if "rate" in str(error_msg).lower() else 10,
                hint="Check n8n Calendar configuration or try again"
            )

        return result
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Create calendar event timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Calendar event creation timed out",
            status_code=504,
            details={"summary": summary, "account": account},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Create calendar event failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="calendar")


def tool_get_gmail_messages(
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Get recent emails from Projektil Gmail inbox via n8n (live API).

    This fetches live emails, not indexed/searchable content.
    Use search_emails for semantic search in indexed emails.

    Args:
        limit: Number of emails to fetch (1-20)

    Raises:
        JarvisException: On API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: get_gmail_messages", limit=limit)
    metrics.inc("tool_get_gmail_messages")

    try:
        from . import n8n_client

        emails = n8n_client.get_gmail_projektil(limit=min(limit, 20))

        # Check for API-level errors
        if isinstance(emails, dict) and emails.get("error"):
            error_msg = emails.get("error", "Unknown Gmail error")
            raise JarvisException(
                code=ErrorCode.GMAIL_API_ERROR,
                message=f"Failed to fetch emails: {error_msg}",
                status_code=502,
                details={"limit": limit},
                recoverable="timeout" in str(error_msg).lower() or "rate" in str(error_msg).lower(),
                retry_after=30 if "rate" in str(error_msg).lower() else 10,
                hint="Check n8n Gmail configuration or try again"
            )

        formatted = n8n_client.format_emails_for_briefing(emails, max_items=limit)

        return {
            "emails": emails,
            "count": len(emails),
            "formatted": formatted,
            "source": "gmail_api",
            "account": "projektil"
        }
    except JarvisException:
        raise
    except requests.Timeout as e:
        log_with_context(logger, "error", "Get Gmail messages timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Gmail fetch timed out",
            status_code=504,
            details={"limit": limit},
            recoverable=True,
            retry_after=15
        )
    except Exception as e:
        log_with_context(logger, "error", "Get Gmail messages failed",
                        error=str(e), error_type=type(e).__name__)
        raise wrap_external_error(e, service="gmail")


def tool_send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Send an email via n8n (Projektil Gmail account).

    Note: Only Projektil has Gmail. Visualfox has no Gmail.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)

    Raises:
        JarvisException: On network, auth, or API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: send_email",
                    to=to, subject=subject[:50])
    metrics.inc("tool_send_email")

    try:
        from . import n8n_client

        result = n8n_client.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc
        )

        # Check for API-level errors returned in result dict
        if not result.get("success") and result.get("error"):
            error_msg = result.get("error", "Unknown email error")
            log_with_context(logger, "error", "Send email API error",
                            to=to, error=error_msg)
            raise JarvisException(
                code=ErrorCode.GMAIL_API_ERROR,
                message=f"Failed to send email: {error_msg}",
                status_code=502,
                details={"to": to, "subject": subject[:50]},
                recoverable="timeout" in error_msg.lower() or "rate" in error_msg.lower(),
                retry_after=30 if "rate" in error_msg.lower() else 10,
                hint="Check n8n Gmail configuration or try again later"
            )

        return result

    except JarvisException:
        raise  # Re-raise our own exceptions
    except requests.Timeout as e:
        log_with_context(logger, "error", "Send email timeout", to=to, error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Email send timed out - n8n or Gmail may be slow",
            status_code=504,
            details={"to": to},
            recoverable=True,
            retry_after=30,
            hint="Try again in a moment"
        )
    except requests.RequestException as e:
        log_with_context(logger, "error", "Send email network error", to=to, error=str(e))
        raise JarvisException(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"Email service unavailable: {str(e)[:100]}",
            status_code=503,
            details={"to": to},
            recoverable=True,
            retry_after=30,
            hint="n8n may be down or unreachable"
        )
    except Exception as e:
        log_with_context(logger, "error", "Send email unexpected error", to=to, error=str(e))
        raise wrap_external_error(e, service="send_email")


def tool_no_tool_needed(reason: str = "", **kwargs) -> Dict[str, Any]:
    """Placeholder for when no tool is needed"""
    log_with_context(logger, "info", "Tool: no_tool_needed", reason=reason)
    metrics.inc("tool_no_tool_needed")
    return {"status": "ok", "reason": reason}


def tool_request_out_of_scope(reason: str = "Unspecified", suggestion: str = "Nutze ein anderes Tool", **kwargs) -> Dict[str, Any]:
    """Signal that a request is outside Jarvis's capabilities"""
    log_with_context(logger, "info", "Tool: request_out_of_scope",
                    reason=reason[:100] if reason else "N/A", suggestion=suggestion[:100] if suggestion else "N/A")
    metrics.inc("tool_request_out_of_scope")
    return {
        "status": "out_of_scope",
        "reason": reason,
        "suggestion": suggestion,
        "message": f"Diese Anfrage liegt ausserhalb meiner Faehigkeiten: {reason}. Vorschlag: {suggestion}"
    }


# ============ Context Persistence Tools ============

def tool_remember_conversation_context(
    session_summary: str,
    key_topics: List[str],
    pending_actions: List[str] = None,
    emotional_context: str = None,
    relationship_insights: str = None,
    session_id: str = None,
    user_id: int = None,
    namespace: str = "private",
    **kwargs
) -> Dict[str, Any]:
    """Store conversation context for future sessions"""
    log_with_context(logger, "info", "Tool: remember_conversation_context",
                    topics=len(key_topics), pending=len(pending_actions or []))
    metrics.inc("tool_remember_conversation_context")

    from . import session_manager

    # Build emotional indicators
    emotional_indicators = {}
    if emotional_context:
        emotional_indicators["note"] = emotional_context

    # Build relationship updates
    relationship_updates = {}
    if relationship_insights:
        relationship_updates["insight"] = relationship_insights

    context = session_manager.ConversationContext(
        session_id=session_id or f"ctx_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        user_id=user_id or 0,
        start_time=datetime.now().isoformat(timespec="seconds"),
        conversation_summary=session_summary,
        key_topics=key_topics or [],
        pending_actions=pending_actions or [],
        emotional_indicators=emotional_indicators,
        relationship_updates=relationship_updates,
        namespace=namespace,
        message_count=kwargs.get("message_count", 0)
    )

    context_id = session_manager.save_conversation_context(context)

    return {
        "status": "context_saved",
        "context_id": context_id,
        "session_id": context.session_id,
        "topics_saved": len(key_topics),
        "pending_actions_saved": len(pending_actions or []),
        "summary": session_summary[:100] + "..." if len(session_summary) > 100 else session_summary
    }


def tool_recall_conversation_history(
    days_back: int = 7,
    topic_filter: str = None,
    include_pending_actions: bool = True,
    user_id: int = None,
    namespace: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Retrieve relevant conversation context from previous sessions"""
    log_with_context(logger, "info", "Tool: recall_conversation_history",
                    days_back=days_back, topic_filter=topic_filter)
    metrics.inc("tool_recall_conversation_history")

    from . import session_manager

    # Get conversation history
    history = session_manager.get_conversation_history(
        user_id=user_id,
        days_back=days_back,
        topic_filter=topic_filter,
        namespace=namespace,
        limit=10
    )

    # Get pending actions if requested
    pending = []
    if include_pending_actions:
        pending = session_manager.get_pending_actions(user_id=user_id, limit=10)

    # Get frequent topics
    frequent_topics = session_manager.get_recent_topics(
        user_id=user_id,
        days_back=days_back,
        limit=5
    )

    # Format for agent consumption
    formatted_history = []
    total_messages = 0
    auto_captured_sessions = 0
    for ctx in history:
        msg_count = ctx.get("message_count", 0)
        total_messages += msg_count
        source = ctx.get("source", "conversation_contexts")
        if source in ("session_messages", "enriched"):
            auto_captured_sessions += 1
        # Use end_time (most recent activity) for display, fall back to start_time
        display_date = ctx.get("end_time") or ctx.get("start_time") or ""
        formatted_history.append({
            "date": display_date[:10] if display_date else "unknown",
            "last_activity": display_date[:16] if display_date else "unknown",
            "started": ctx.get("start_time", "")[:10] if ctx.get("start_time") else "unknown",
            "summary": ctx.get("conversation_summary", ""),
            "topics": ctx.get("key_topics", []),
            "pending": ctx.get("pending_actions", []),
            "mood": ctx.get("emotional_indicators", {}).get("dominant", "neutral"),
            "message_count": msg_count,
            "source": source
        })

    # Build explicit diagnosis message for Jarvis
    if total_messages > 10:
        diagnosis = f"MEMORY OK: {total_messages} Nachrichten in {len(formatted_history)} Session(s) der letzten {days_back} Tage. Auto-Persist funktioniert."
    elif total_messages > 0:
        diagnosis = f"MEMORY SPARSE: Nur {total_messages} Nachrichten gefunden. Auto-Persist aktiv aber wenig Daten."
    else:
        diagnosis = "MEMORY EMPTY: Keine Conversation-Daten gefunden. Auto-Persist prüfen."

    return {
        "diagnosis": diagnosis,
        "conversations": formatted_history,
        "conversation_count": len(formatted_history),
        "total_messages": total_messages,
        "auto_captured_sessions": auto_captured_sessions,
        "memory_status": "healthy" if total_messages > 5 else "sparse",
        "pending_actions": [
            {"id": p["id"], "action": p["action_text"], "date": p["created_at"][:10]}
            for p in pending
        ],
        "pending_count": len(pending),
        "frequent_topics": [
            {"topic": t["topic"], "mentions": t["total_mentions"]}
            for t in frequent_topics
        ],
        "days_searched": days_back,
        "topic_filter": topic_filter
    }


def tool_complete_pending_action(
    action_id: int = None,
    action_text: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """Mark a pending action as completed"""
    log_with_context(logger, "info", "Tool: complete_pending_action",
                    action_id=action_id, action_text=action_text)
    metrics.inc("tool_complete_pending_action")

    from . import session_manager

    if action_id:
        success = session_manager.complete_action(action_id)
        if success:
            return {
                "status": "completed",
                "action_id": action_id,
                "message": "Action marked as completed"
            }
        else:
            return {
                "status": "not_found",
                "action_id": action_id,
                "message": "Action not found"
            }

    elif action_text:
        # Find matching action by text
        pending = session_manager.get_pending_actions(user_id=user_id, limit=50)
        for action in pending:
            if action_text.lower() in action["action_text"].lower():
                success = session_manager.complete_action(action["id"])
                if success:
                    return {
                        "status": "completed",
                        "action_id": action["id"],
                        "matched_text": action["action_text"],
                        "message": "Action matched and marked as completed"
                    }

        return {
            "status": "not_found",
            "search_text": action_text,
            "message": "No matching pending action found"
        }

    return {
        "status": "error",
        "message": "Please provide either action_id or action_text"
    }


# ============ Knowledge Layer Tools ============

def tool_propose_knowledge_update(
    update_type: str,
    subject_id: str,
    insight: str,
    confidence: str = "medium",
    evidence_source: str = None,
    evidence_note: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Propose a knowledge update for human review"""
    log_with_context(logger, "info", "Tool: propose_knowledge_update",
                    update_type=update_type, subject_id=subject_id)
    metrics.inc("tool_propose_knowledge_update")

    try:
        from . import knowledge_db

        if not knowledge_db.is_available():
            return {
                "status": "unavailable",
                "message": "Knowledge layer not available. Insight noted but not persisted."
            }

        # Build evidence sources
        evidence_sources = []
        if evidence_source:
            evidence_sources.append({
                "source_path": evidence_source,
                "note": evidence_note or "",
                "timestamp": datetime.now().isoformat()
            })

        # Determine subject type
        if update_type == "person_insight":
            subject_type = "person"
        elif update_type == "persona_adjustment":
            subject_type = "persona"
        else:
            subject_type = "general"

        # Propose the insight
        insight_id = knowledge_db.propose_insight(
            insight_type=update_type,
            subject_type=subject_type,
            subject_id=subject_id,
            insight_text=insight,
            confidence=confidence,
            evidence_sources=evidence_sources,
            proposed_by="jarvis"
        )

        if not insight_id:
            return {"status": "error", "message": "Failed to create insight"}

        # Add to review queue
        queue_id = knowledge_db.add_to_review_queue(
            item_type="insight",
            item_id=insight_id,
            summary=f"Jarvis {update_type} for {subject_id}: {insight[:100]}...",
            requested_by="jarvis",
            priority="normal",
            evidence_summary=evidence_note
        )

        return {
            "status": "proposed",
            "insight_id": insight_id,
            "queue_id": queue_id,
            "message": f"Proposed {update_type} for {subject_id}. Awaiting human review."
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to propose knowledge update", error=str(e))
        return {"status": "error", "message": str(e)}


def tool_get_person_context(person_id: str, **kwargs) -> Dict[str, Any]:
    """Get person profile from knowledge layer with JSON fallback"""
    log_with_context(logger, "info", "Tool: get_person_context", person_id=person_id)
    metrics.inc("tool_get_person_context")

    # Try knowledge layer first
    try:
        from . import knowledge_db

        if knowledge_db.is_available():
            profile = knowledge_db.get_person_profile(person_id)
            if profile and profile.get("content"):
                return {
                    "person_id": person_id,
                    "source": "knowledge_layer",
                    "profile": profile["content"],
                    "version": profile.get("version_number"),
                    "status": "found"
                }
    except Exception as e:
        log_with_context(logger, "warning", "Knowledge layer lookup failed",
                        person_id=person_id, error=str(e))

    # Fallback to JSON file
    try:
        from pathlib import Path
        import json

        BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
        profile_path = BRAIN_ROOT / "system" / "profiles" / "persons" / f"{person_id}.json"

        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            return {
                "person_id": person_id,
                "source": "json_file",
                "profile": content,
                "status": "found"
            }
    except Exception as e:
        log_with_context(logger, "warning", "JSON profile lookup failed",
                        person_id=person_id, error=str(e))

    return {
        "person_id": person_id,
        "source": "none",
        "profile": None,
        "status": "not_found",
        "message": f"No profile found for {person_id}"
    }


# ============ Project Management Tools ============

# Global user_id for project tools (set by telegram handler)
_current_user_id = None

def set_current_user_id(user_id: int):
    """Set current user ID for project tools"""
    global _current_user_id
    _current_user_id = user_id


def tool_add_project(name: str, description: str = "", priority: int = 2, **kwargs) -> Dict[str, Any]:
    """Add a new project"""
    log_with_context(logger, "info", "Tool: add_project", name=name, priority=priority)
    metrics.inc("tool_add_project")

    if not _current_user_id:
        return {"error": "No user context available"}

    try:
        from . import projects
        return projects.tool_add_project(_current_user_id, name, description, priority)
    except Exception as e:
        log_with_context(logger, "error", "Add project failed", error=str(e))
        return {"error": str(e)}


def tool_list_projects(**kwargs) -> Dict[str, Any]:
    """List all projects"""
    log_with_context(logger, "info", "Tool: list_projects")
    metrics.inc("tool_list_projects")

    if not _current_user_id:
        return {"error": "No user context available"}

    try:
        from . import projects
        return projects.tool_list_projects(_current_user_id)
    except Exception as e:
        log_with_context(logger, "error", "List projects failed", error=str(e))
        return {"error": str(e)}


def tool_update_project_status(project_id: str, status: str, **kwargs) -> Dict[str, Any]:
    """Update project status"""
    log_with_context(logger, "info", "Tool: update_project_status", project_id=project_id, status=status)
    metrics.inc("tool_update_project_status")

    try:
        from . import projects
        return projects.tool_update_project_status(project_id, status)
    except Exception as e:
        log_with_context(logger, "error", "Update project failed", error=str(e))
        return {"error": str(e)}


def tool_manage_thread(action: str, topic: str = None, notes: str = None, **kwargs) -> Dict[str, Any]:
    """
    Manage conversation threads for ADHD support.

    Actions:
    - open: Start or resume a topic
    - close: Mark topic as completed
    - pause: Temporarily set aside
    - list: Show all threads with status
    """
    log_with_context(logger, "info", "Tool: manage_thread", action=action, topic=topic)
    metrics.inc("tool_manage_thread")

    try:
        from . import session_manager

        user_id = _current_user_id
        if not user_id:
            return {"error": "No user context available"}

        if action == "list":
            # Get all threads grouped by status
            open_threads = session_manager.get_thread_states(user_id, status="open")
            paused_threads = session_manager.get_thread_states(user_id, status="paused")

            return {
                "success": True,
                "open_threads": [{"topic": t["topic"], "since": t["opened_at"]} for t in open_threads],
                "paused_threads": [{"topic": t["topic"], "paused_at": t["paused_at"]} for t in paused_threads],
                "summary": f"{len(open_threads)} offen, {len(paused_threads)} pausiert"
            }

        if not topic:
            return {"error": "Topic required for open/close/pause actions"}

        topic = topic.lower().strip()

        if action == "open":
            result = session_manager.open_thread(user_id, topic)
            return {
                "success": True,
                "action": "opened" if result["action"] == "opened" else "reopened",
                "topic": topic,
                "message": f"Thread '{topic}' ist jetzt aktiv."
            }

        elif action == "close":
            result = session_manager.close_thread(user_id, topic, notes)
            if result["success"]:
                return {
                    "success": True,
                    "action": "closed",
                    "topic": topic,
                    "message": f"Thread '{topic}' wurde abgeschlossen."
                }
            else:
                return {"success": False, "error": f"Thread '{topic}' nicht gefunden oder bereits geschlossen."}

        elif action == "pause":
            result = session_manager.pause_thread(user_id, topic)
            if result["success"]:
                return {
                    "success": True,
                    "action": "paused",
                    "topic": topic,
                    "message": f"Thread '{topic}' wurde pausiert."
                }
            else:
                return {"success": False, "error": f"Thread '{topic}' nicht gefunden oder nicht offen."}

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as e:
        log_with_context(logger, "error", "Thread management failed", error=str(e))
        return {"error": str(e)}


# ============ Proactive Initiative Tools ============

# Phase 15.5: Hint tuning configuration (now driven by config)
HINT_CONFIDENCE_THRESHOLD = 0.65  # fallback if config missing
HINT_WORKING_HOURS_START = 9      # legacy working hours
HINT_WORKING_HOURS_END = 18

# Proactivity dial runtime state (simple in-memory counters)
_proactive_daily_count = 0
_proactive_daily_date = None
_proactive_last_hint_ts = None


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


def tool_proactive_hint(
    observation: str,
    context: str,
    suggested_action: str = None,
    confidence: str = "medium",
    force: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Share a proactive observation or pattern.
    This is a Tier 2 (Notify) action - Jarvis can do this autonomously.

    Phase 15.5 enhancements:
    - Filters low-confidence hints (< 0.65)
    - Only sends during working hours (9-18 Zurich, weekdays)
    - Set force=True to bypass filters (for critical hints)

    Args:
        observation: The observation to share
        context: Context around the observation
        suggested_action: Optional suggested action
        confidence: "low", "medium", or "high"
        force: Bypass confidence and time filters

    Returns:
        Status dict with hint info or filter reason
    """
    from . import config

    conf_score = _get_confidence_score(confidence)
    level_threshold = _proactive_level_threshold(config.PROACTIVE_LEVEL, config.PROACTIVE_CONFIDENCE_THRESHOLD)

    log_with_context(logger, "info", "Tool: proactive_hint",
                    confidence=confidence, confidence_score=conf_score,
                    observation_preview=observation[:50], force=force,
                    proactive_level=config.PROACTIVE_LEVEL)
    metrics.inc("tool_proactive_hint")

    # Level gate (unless forced)
    if not force and config.PROACTIVE_LEVEL <= 1:
        metrics.inc("tool_proactive_hint_filtered_level")
        return {
            "status": "filtered",
            "reason": "proactive_level",
            "level": config.PROACTIVE_LEVEL,
            "message": "Proactivity disabled by level."
        }

    # Check confidence threshold (unless forced)
    if not force and conf_score < level_threshold:
        log_with_context(logger, "info", "Hint filtered: low confidence",
                        confidence_score=conf_score, threshold=level_threshold)
        metrics.inc("tool_proactive_hint_filtered_confidence")
        return {
            "status": "filtered",
            "reason": "low_confidence",
            "confidence_score": conf_score,
            "threshold": level_threshold,
            "message": f"Hint filtered: confidence {conf_score:.2f} < threshold {level_threshold}"
        }

    # Quiet hours gate (unless forced)
    if not force and _is_quiet_hours():
        log_with_context(logger, "info", "Hint deferred: quiet hours")
        metrics.inc("tool_proactive_hint_deferred_quiet_hours")
        return {
            "status": "deferred",
            "reason": "quiet_hours",
            "quiet_hours": f"{config.PROACTIVE_QUIET_HOURS_START}-{config.PROACTIVE_QUIET_HOURS_END}",
            "message": "Hint deferred: quiet hours. Will not disturb user."
        }

    # Rate limits (unless forced)
    if not force:
        now = datetime.utcnow()
        rate_check = _check_proactive_rate_limits(
            now,
            config.PROACTIVE_MAX_PER_DAY,
            config.PROACTIVE_COOLDOWN_MINUTES
        )
        if not rate_check.get("allowed", False):
            metrics.inc("tool_proactive_hint_rate_limited")
            return {
                "status": "deferred",
                "reason": rate_check.get("reason", "rate_limited"),
                "message": rate_check.get("message", "Proactive hint deferred by rate limits")
            }

    # Store the hint as a fact for future reference (SQLite)
    from . import memory_store
    hint_fact = f"[Proactive Hint] {observation}"
    memory_store.add_fact(hint_fact, category="insight", confidence=conf_score)

    # Also store in proactive_hints PostgreSQL table for metrics (Phase 19.2)
    user_id = kwargs.get("user_id", "unknown")
    session_id = kwargs.get("session_id", "unknown")
    try:
        from .db_safety import safe_write_query
        with safe_write_query("proactive_hints") as cur:
            cur.execute("""
                INSERT INTO proactive_hints (user_id, session_id, hint_type, category, content, context, confidence, was_shown, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(user_id),
                str(session_id),
                "observation",
                "insight",
                observation,
                context,
                conf_score,
                True,  # was_shown = True since we're delivering it
                json.dumps({"suggested_action": suggested_action}) if suggested_action else None
            ))
    except Exception as e:
        log_with_context(logger, "warning", "Failed to store proactive hint in PostgreSQL", error=str(e))

    # Update counters
    global _proactive_daily_count, _proactive_daily_date, _proactive_last_hint_ts
    _proactive_daily_date = datetime.utcnow().date().isoformat()
    _proactive_daily_count += 1
    _proactive_last_hint_ts = datetime.utcnow().timestamp()

    return {
        "status": "hint_shared",
        "observation": observation,
        "context": context,
        "suggested_action": suggested_action,
        "confidence": confidence,
        "confidence_score": conf_score,
        "proactive_level": config.PROACTIVE_LEVEL,
        "message": f"Proaktiver Hinweis geteilt: {observation[:100]}..."
    }


# ============ Direct File Access ============

# Whitelisted directories for file access
ALLOWED_FILE_PATHS = [
    # macOS paths (for local testing)
    "/Volumes/BRAIN/system/",      # Main system folder
    "/Volumes/BRAIN/system/data/", # Canonical data folder
    "/Volumes/BRAIN/data/",        # Data folder (linkedin/visualfox updates)
    "/Volumes/BRAIN/projects/",    # Project files
    "/Volumes/BRAIN/notes/",       # Notes
    # Docker paths (inside container)
    "/brain/system/",              # Main system folder
    "/brain/system/data/",         # Canonical data folder
    "/brain/data/",                # Data folder (when mounted under /brain)
    "/brain/projects/",            # Project files
    "/brain/notes/",               # Notes
    "/data/",                      # Docker mounted data
]

# Blocked file patterns (security)
BLOCKED_PATTERNS = [
    ".env",
    "credentials",
    "secret",
    "password",
    ".key",
    ".pem",
    "id_rsa",
    ".ssh",
]

AUDIT_DIR_DOCKER = "/brain/system/ingestion/audit"
AUDIT_DIR_MAC = "/Volumes/BRAIN/system/ingestion/audit"


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


def tool_read_project_file(file_path: str, max_lines: int = 200, **kwargs) -> Dict[str, Any]:
    """
    Read a file directly from allowed project directories.
    Enables Jarvis to inspect code, configs, and documentation.
    """
    log_with_context(logger, "info", "Tool: read_project_file", file_path=file_path)
    metrics.inc("tool_read_project_file")

    # Normalize and translate path
    original_path = file_path
    file_path = _translate_path(file_path)
    if original_path != file_path:
        log_with_context(logger, "debug", "Path translated",
                        original=original_path, translated=file_path)

    # Security check: must be in allowed paths
    if not _is_allowed_path(file_path):
        log_with_context(logger, "warning", "File access denied - not in allowed paths",
                        file_path=file_path)
        return {
            "error": "Zugriff verweigert",
            "reason": "Pfad nicht in erlaubten Verzeichnissen",
            "allowed_paths": ALLOWED_FILE_PATHS
        }

    # Security check: block sensitive files
    if _is_blocked_path(file_path):
        log_with_context(logger, "warning", "File access denied - sensitive file",
                        file_path=file_path)
        return {
            "error": "Zugriff verweigert",
            "reason": "Sensible Datei"
        }

    # Limit max_lines (defensive against string inputs)
    try:
        max_lines = int(max_lines)
    except (TypeError, ValueError):
        max_lines = 200
    max_lines = max(1, min(max_lines, 500))

    # Directory mode: list markdown files recursively (for "read all *.md" workflows).
    if os.path.isdir(file_path):
        pattern = os.path.join(file_path, "**", "*.md")
        matched = sorted(glob.glob(pattern, recursive=True))
        return {
            "success": True,
            "mode": "directory",
            "directory": file_path,
            "pattern": pattern,
            "matched_count": len(matched),
            "matched_files": matched,
        }

    # Glob mode: read multiple files matching pattern.
    if any(ch in file_path for ch in ("*", "?", "[")):
        matched = []
        for candidate in sorted(glob.glob(file_path, recursive=True)):
            if os.path.isfile(candidate) and _is_allowed_path(candidate) and not _is_blocked_path(candidate):
                matched.append(candidate)

        if not matched:
            return {
                "error": "Datei nicht gefunden",
                "file_path": file_path,
            }

        max_files = max(1, min(int(kwargs.get("max_files", 25)), 100))
        selected = matched[:max_files]
        files = []
        for candidate in selected:
            try:
                files.append(_read_single_file(candidate, max_lines))
            except Exception as e:
                files.append({"error": str(e), "file_path": candidate})

        return {
            "success": True,
            "mode": "glob",
            "pattern": file_path,
            "matched_count": len(matched),
            "returned_count": len(files),
            "truncated": len(matched) > len(files),
            "files": files,
        }

    # Single-file mode.
    if not os.path.isfile(file_path):
        return {
            "error": "Datei nicht gefunden",
            "file_path": file_path
        }

    try:
        return _read_single_file(file_path, max_lines)

    except Exception as e:
        log_with_context(logger, "error", "File read failed", file_path=file_path, error=str(e))
        return {"error": str(e), "file_path": file_path}


def tool_read_my_source_files(
    file_key: str,
    max_lines: int = 200,
    **kwargs
) -> Dict[str, Any]:
    """
    Read canonical self-source files for Jarvis.

    file_key options:
    - capability_catalog
    - context_policy
    - capabilities_json
    - jarvis_self
    """
    log_with_context(logger, "info", "Tool: read_my_source_files", file_key=file_key)
    metrics.inc("tool_read_my_source_files")

    file_map = {
        "capability_catalog": "/brain/system/docs/CAPABILITY_CATALOG.md",
        "context_policy": "/brain/system/docs/CONTEXT_POLICY.md",
        "capabilities_json": "/brain/system/docs/CAPABILITIES.json",
        "jarvis_self": "/brain/system/policies/JARVIS_SELF.md",
    }

    if file_key not in file_map:
        return {
            "error": "Unknown file_key",
            "allowed": sorted(list(file_map.keys()))
        }

    return tool_read_project_file(file_map[file_key], max_lines=max_lines)


def tool_introspect_capabilities(
    include_catalog: bool = False,
    max_lines: int = 120,
    **kwargs
) -> Dict[str, Any]:
    """Return Jarvis capability metadata from canonical files."""
    log_with_context(logger, "info", "Tool: introspect_capabilities", include_catalog=include_catalog)
    metrics.inc("tool_introspect_capabilities")

    cap_path = "/brain/system/docs/CAPABILITIES.json"
    catalog_path = "/brain/system/docs/CAPABILITY_CATALOG.md"

    result: Dict[str, Any] = {
        "capabilities_json": {},
        "capability_catalog": {},
    }

    # Read CAPABILITIES.json directly (entire file, not truncated)
    try:
        with open(cap_path, "r", encoding="utf-8") as f:
            cap_json = json.load(f)
        tools = cap_json.get("tools", [])
        result["capabilities_json"] = {
            "version": cap_json.get("version"),
            "build_timestamp": cap_json.get("build_timestamp"),
            "tool_count": len(tools),
            "tool_names_sample": [t.get("name") for t in tools[:10]]
        }
    except Exception as e:
        log_with_context(logger, "error", "Failed to read CAPABILITIES.json", error=str(e))
        result["capabilities_json"] = {"error": str(e)}

    try:
        catalog_result = tool_read_project_file(catalog_path, max_lines=max_lines)
        if catalog_result.get("success"):
            result["capability_catalog"] = {
                "present": True,
                "file_size": catalog_result.get("file_size"),
                "lines_read": catalog_result.get("lines_read"),
                "truncated": catalog_result.get("truncated")
            }
            if include_catalog:
                result["capability_catalog"]["preview"] = catalog_result.get("content", "")
        else:
            result["capability_catalog"] = {
                "present": False,
                "error": catalog_result.get("error", "read_failed")
            }
    except Exception as e:
        result["capability_catalog"] = {"present": False, "error": str(e)}

    return result


def tool_analyze_cross_session_patterns(
    user_id: int = 0,
    days: int = 30,
    min_confidence: float = 0.5,
    **kwargs
) -> Dict[str, Any]:
    """Analyze cross-session learning patterns (lessons + decisions)."""
    log_with_context(logger, "info", "Tool: analyze_cross_session_patterns",
                    user_id=user_id, days=days, min_confidence=min_confidence)
    metrics.inc("tool_analyze_cross_session_patterns")

    try:
        from .cross_session_learner import cross_session_learner
        lessons = cross_session_learner.get_active_lessons(user_id=user_id, min_confidence=min_confidence)
        insights = cross_session_learner.get_decision_insights(user_id=user_id, days=days)
        return {
            "user_id": user_id,
            "days": days,
            "lessons": lessons,
            "lesson_count": len(lessons),
            "decision_insights": insights
        }
    except Exception as e:
        log_with_context(logger, "error", "Cross-session analysis failed", error=str(e))
        return {"error": str(e)}


def tool_system_health_check(**kwargs) -> Dict[str, Any]:
    """Return internal health status for core services."""
    log_with_context(logger, "info", "Tool: system_health_check")
    metrics.inc("tool_system_health_check")

    try:
        from .routers import health_router
        return health_router.health_check()
    except Exception as e:
        log_with_context(logger, "error", "System health check failed", error=str(e))
        return {"error": str(e)}


def tool_write_project_file(
    file_path: str,
    content: str,
    mode: str = "replace",
    create_backup: bool = True,
    preview_only: bool = False,
    approved: bool = False,
    reason: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Write or append to a file in allowed project directories.
    Enables Jarvis to update code, configs, and documentation.
    """
    log_with_context(logger, "info", "Tool: write_project_file", file_path=file_path, mode=mode)
    metrics.inc("tool_write_project_file")

    if mode not in {"replace", "append"}:
        return {"error": "Ungültiger Modus", "allowed": ["replace", "append"]}

    from . import config
    content_length = len(content.encode("utf-8", errors="replace"))
    if config.WRITE_MAX_BYTES > 0 and content_length > config.WRITE_MAX_BYTES:
        metrics.inc("tool_write_project_file_oversize")
        return {
            "error": "Inhalt zu gross",
            "reason": f"Max {config.WRITE_MAX_BYTES} bytes",
            "content_bytes": content_length
        }

    rate_check = _check_write_rate_limits(config.WRITE_MAX_PER_MINUTE, config.WRITE_MAX_PER_HOUR)
    if not rate_check.get("allowed", False):
        metrics.inc("tool_write_project_file_rate_limited")
        return {
            "error": "Rate limit",
            "reason": rate_check.get("reason"),
            "message": rate_check.get("message")
        }

    # Normalize and translate path
    file_path = _translate_path(file_path)

    # Security check: must be in allowed paths
    if not _is_allowed_path(file_path):
        log_with_context(logger, "warning", "File write denied - not in allowed paths",
                        file_path=file_path)
        return {
            "error": "Zugriff verweigert",
            "reason": "Pfad nicht in erlaubten Verzeichnissen",
            "allowed_paths": ALLOWED_FILE_PATHS
        }

    # Security check: block sensitive files
    if _is_blocked_path(file_path):
        log_with_context(logger, "warning", "File write denied - sensitive file",
                        file_path=file_path)
        return {
            "error": "Zugriff verweigert",
            "reason": "Sensible Datei"
        }

    # Approval check (skip for preview-only)
    if not preview_only and _requires_write_approval(file_path, config.WRITE_APPROVAL_PATHS) and not approved:
        metrics.inc("tool_write_project_file_requires_approval")
        return {
            "error": "Approval erforderlich",
            "requires_approval": True,
            "file_path": file_path,
            "message": "Pfad erfordert explizite Freigabe (approved=true)."
        }

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Backup existing file
        backup_path = None
        if create_backup and os.path.isfile(file_path):
            audit_dir = _get_audit_dir(file_path)
            os.makedirs(audit_dir, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            base_name = os.path.basename(file_path)
            backup_path = os.path.join(audit_dir, f"{base_name}.{timestamp}.bak")
            shutil.copy2(file_path, backup_path)

        # Preview only (diff)
        if preview_only:
            existing_content = ""
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    existing_content = f.read()
            diff = "\n".join(
                difflib.unified_diff(
                    existing_content.splitlines(),
                    content.splitlines(),
                    fromfile=f"{file_path} (current)",
                    tofile=f"{file_path} (proposed)",
                    lineterm=""
                )
            )
            return {
                "success": True,
                "preview": True,
                "file_path": file_path,
                "diff": diff,
                "content_bytes": content_length
            }

        # Write content
        if mode == "append":
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            temp_path = f"{file_path}.tmp.{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, file_path)

        # Audit log
        audit_dir = _get_audit_dir(file_path)
        os.makedirs(audit_dir, exist_ok=True)
        audit_log = os.path.join(audit_dir, "write_audit.jsonl")
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "file_path": file_path,
            "mode": mode,
            "content_sha256": _hash_content(content),
            "content_length": content_length,
            "backup_path": backup_path,
            "approved": approved,
            "reason": reason,
        }
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        stat = os.stat(file_path)
        return {
            "success": True,
            "file_path": file_path,
            "mode": mode,
            "backup_path": backup_path,
            "file_size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
        }

    except Exception as e:
        log_with_context(logger, "error", "File write failed", file_path=file_path, error=str(e))
        return {"error": str(e), "file_path": file_path}


# ============ Phase 18.3: Self-Optimization Tools ============

def tool_optimize_system_prompt(
    prompt_section: str,
    focus_area: str = "all",
    include_metrics: bool = True
) -> Dict[str, Any]:
    """Analyze system prompts and suggest optimizations."""
    log_with_context(logger, "info", "Analyzing system prompt",
                    section=prompt_section, focus=focus_area)

    # Map sections to actual prompt sources
    prompt_sources = {
        "agent": "AGENT_SYSTEM_PROMPT from agent.py",
        "chat": "SYSTEM_PROMPT from llm_core.py",
        "coaching": "Coaching domain prompts from coaching_domains.py",
        "search": "Search prompt templates"
    }

    if prompt_section not in prompt_sources:
        return {"error": f"Unknown prompt section: {prompt_section}"}

    suggestions = []
    metrics_data = {}

    try:
        # Gather usage metrics if requested
        if include_metrics:
            from .observability import metrics as obs_metrics
            from .feedback_tracker import get_feedback_summary
            metrics_data = {
                "agent_runs": obs_metrics.get_stats().get("agent_runs", 0),
                "feedback_summary": get_feedback_summary()
            }

        # Generate optimization suggestions based on focus area
        focus_suggestions = {
            "clarity": [
                {"suggestion": "Add explicit examples for ambiguous terms", "confidence": 0.7},
                {"suggestion": "Break long instructions into numbered steps", "confidence": 0.8}
            ],
            "conciseness": [
                {"suggestion": "Remove redundant phrases ('bitte beachte', etc.)", "confidence": 0.75},
                {"suggestion": "Consolidate similar rules", "confidence": 0.6}
            ],
            "tone": [
                {"suggestion": "Calibrate formality based on context", "confidence": 0.65},
                {"suggestion": "Add ADHD-friendly formatting cues", "confidence": 0.8}
            ],
            "effectiveness": [
                {"suggestion": "Add guardrails for common failure modes", "confidence": 0.85},
                {"suggestion": "Include role-specific context injection", "confidence": 0.7}
            ]
        }

        if focus_area == "all":
            for area, area_suggestions in focus_suggestions.items():
                for s in area_suggestions:
                    s["area"] = area
                    suggestions.append(s)
        elif focus_area in focus_suggestions:
            for s in focus_suggestions[focus_area]:
                s["area"] = focus_area
                suggestions.append(s)

        # Sort by confidence
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)

        return {
            "prompt_section": prompt_section,
            "source": prompt_sources[prompt_section],
            "focus_area": focus_area,
            "suggestions": suggestions[:5],  # Top 5 suggestions
            "metrics": metrics_data if include_metrics else None,
            "note": "Diese Vorschlaege basieren auf allgemeinen Best Practices. Fuer spezifischere Optimierungen ist Feedback-Analyse noetig."
        }

    except Exception as e:
        log_with_context(logger, "error", "Prompt optimization failed", error=str(e))
        return {"error": str(e)}


def tool_enable_experimental_feature(
    flag_name: str,
    action: str,
    rollout_percent: int = 100,
    reason: str = None
) -> Dict[str, Any]:
    """Enable, disable, check, or create feature flags."""
    log_with_context(logger, "info", "Feature flag operation",
                    flag=flag_name, action=action)

    try:
        from . import feature_flags

        if action == "check":
            flag = feature_flags.get_flag(flag_name)
            if flag:
                return {
                    "flag_name": flag_name,
                    "exists": True,
                    "enabled": flag["enabled"],
                    "rollout_percent": flag["rollout_percent"],
                    "version": flag["version"],
                    "kill_switch": flag["kill_switch"]
                }
            else:
                return {
                    "flag_name": flag_name,
                    "exists": False,
                    "enabled": False,
                    "note": "Flag nicht gefunden. Nutze action='create' um einen neuen Flag zu erstellen."
                }

        elif action == "create":
            flag = feature_flags.create_flag(
                flag_name=flag_name,
                description=reason or f"Created by agent tool",
                enabled=False,
                rollout_percent=rollout_percent,
                changed_by="agent_tool"
            )
            return {
                "success": True,
                "action": "created",
                "flag": flag,
                "note": "Feature Flag erstellt. Nutze action='enable' zum Aktivieren."
            }

        elif action == "enable":
            flag = feature_flags.update_flag(
                flag_name=flag_name,
                enabled=True,
                rollout_percent=rollout_percent,
                changed_by="agent_tool",
                change_reason=reason or "Enabled via agent tool"
            )
            if flag:
                return {
                    "success": True,
                    "action": "enabled",
                    "flag_name": flag_name,
                    "rollout_percent": rollout_percent,
                    "version": flag["version"],
                    "note": "Feature Flag aktiviert (Hot-Reload, kein Restart noetig)"
                }
            else:
                return {"error": f"Flag '{flag_name}' nicht gefunden"}

        elif action == "disable":
            flag = feature_flags.update_flag(
                flag_name=flag_name,
                enabled=False,
                changed_by="agent_tool",
                change_reason=reason or "Disabled via agent tool"
            )
            if flag:
                return {
                    "success": True,
                    "action": "disabled",
                    "flag_name": flag_name,
                    "version": flag["version"],
                    "note": "Feature Flag deaktiviert"
                }
            else:
                return {"error": f"Flag '{flag_name}' nicht gefunden"}

        else:
            return {"error": f"Unbekannte Action: {action}. Erlaubt: enable, disable, check, create"}

    except Exception as e:
        log_with_context(logger, "error", "Feature flag operation failed",
                        flag=flag_name, action=action, error=str(e))
        return {"error": str(e)}



def tool_get_development_status(**kwargs) -> Dict[str, Any]:
    """Return current development status (phase, active team, next phase)."""
    try:
        from .dev_status import get_development_status
        result = get_development_status()
        metrics.inc("tool_get_development_status")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool get_development_status failed", error=str(e))
        return {"error": str(e)}


def tool_list_label_registry(**kwargs) -> Dict[str, Any]:
    """List label registry entries (DB-backed)."""
    try:
        status = kwargs.get("status", "active")
        if isinstance(status, str) and status.lower() in ("all", "any", "*"):
            status = None
        rows = get_registry_entries(status=status)
        metrics.inc("tool_list_label_registry")
        return {
            "success": True,
            "count": len(rows),
            "status_filter": status or "all",
            "labels": rows,
        }
    except Exception as e:
        log_with_context(logger, "error", "Tool list_label_registry failed", error=str(e))
        return {"error": str(e)}


def _parse_allowed_values(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return [v.strip() for v in value.split(",") if v.strip()]
    return [raw]


def tool_upsert_label_registry(**kwargs) -> Dict[str, Any]:
    """Create/update a label registry entry."""
    try:
        key = kwargs.get("key")
        if not key:
            return {"error": "Missing required field: key"}
        description = kwargs.get("description")
        allowed_values = _parse_allowed_values(kwargs.get("allowed_values"))
        status = kwargs.get("status", "active")
        source = kwargs.get("source", "jarvis")

        row = upsert_registry_entry(
            key=key,
            description=description,
            allowed_values=allowed_values,
            status=status,
            source=source,
        )
        refresh_label_schema_cache()
        metrics.inc("tool_upsert_label_registry")
        return {"success": True, "label": row}
    except Exception as e:
        log_with_context(logger, "error", "Tool upsert_label_registry failed", error=str(e))
        return {"error": str(e)}


def tool_delete_label_registry(**kwargs) -> Dict[str, Any]:
    """Delete (soft or hard) a label registry entry."""
    try:
        key = kwargs.get("key")
        if not key:
            return {"error": "Missing required field: key"}
        hard = bool(kwargs.get("hard", False))
        deleted = delete_registry_entry(key=key, hard=hard)
        if deleted:
            refresh_label_schema_cache()
        metrics.inc("tool_delete_label_registry")
        return {"success": deleted, "hard": hard}
    except Exception as e:
        log_with_context(logger, "error", "Tool delete_label_registry failed", error=str(e))
        return {"error": str(e)}


def tool_label_hygiene(**kwargs) -> Dict[str, Any]:
    """
    Scan Qdrant labels and compare against base+registry schema.
    Returns unknown keys/values and (optionally) updates the registry.
    """
    try:
        from qdrant_client import QdrantClient

        collections = kwargs.get("collections", "jarvis_work,jarvis_private,jarvis_comms")
        if isinstance(collections, str):
            collection_list = [c.strip() for c in collections.split(",") if c.strip()]
        else:
            collection_list = list(collections or [])

        limit = int(kwargs.get("limit", 2000))
        apply_updates = bool(kwargs.get("apply", False))
        if apply_updates:
            guard = os.getenv("JARVIS_LABEL_HYGIENE_AUTOREGISTER", "false").lower() in ("1", "true", "yes", "on")
            if not guard:
                return {"error": "Auto-register guard disabled. Set JARVIS_LABEL_HYGIENE_AUTOREGISTER=true to apply."}
        allow_values = bool(kwargs.get("allow_values", True))
        min_count = int(kwargs.get("min_count", 3))
        max_values_per_key = int(kwargs.get("max_values", 20))
        max_value_length = int(kwargs.get("max_value_length", 64))

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        schema_map = get_label_schema()

        unknown_keys: Counter = Counter()
        unknown_values: Dict[str, Counter] = defaultdict(Counter)
        observed_keys: Counter = Counter()
        scanned = 0

        def _normalize_label_value(key: str, value: Any) -> Any:
            if isinstance(value, str):
                alias = VALUE_ALIASES.get(key, {})
                return alias.get(value, value)
            return value

        def iter_label_values(label_dict: Dict[str, Any]):
            for k, v in label_dict.items():
                if v is None:
                    continue
                if isinstance(v, list):
                    values = v
                else:
                    values = [v]
                for value in values:
                    yield k, _normalize_label_value(k, value)

        for collection in collection_list:
            offset = None
            while scanned < limit:
                points, next_offset = client.scroll(
                    collection_name=collection,
                    limit=min(200, limit - scanned),
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break
                for p in points:
                    scanned += 1
                    payload = p.payload or {}
                    labels = payload.get("labels")
                    if not isinstance(labels, dict):
                        continue
                    for key, value in iter_label_values(labels):
                        observed_keys[key] += 1
                        schema = schema_map.get(key)
                        if not schema:
                            unknown_keys[key] += 1
                            if value is not None:
                                val_str = str(value)
                                if len(val_str) <= max_value_length:
                                    unknown_values[key][val_str] += 1
                            continue

                        allowed = schema.get("values")
                        if not allowed:
                            continue
                        val_str = str(value)
                        if val_str not in allowed:
                            if len(val_str) <= max_value_length:
                                unknown_values[key][val_str] += 1

                offset = next_offset
                if offset is None:
                    break

        suggestions = {
            "new_keys": {},
            "new_values": {},
        }

        for key, count in unknown_keys.items():
            values = [v for v, c in unknown_values[key].most_common(max_values_per_key) if c >= min_count]
            suggestions["new_keys"][key] = {
                "count": count,
                "suggested_values": values,
            }

        for key, counter in unknown_values.items():
            if key in suggestions["new_keys"]:
                continue
            missing_vals = [v for v, c in counter.most_common(max_values_per_key) if c >= min_count]
            if missing_vals:
                suggestions["new_values"][key] = missing_vals

        applied = {"new_keys": [], "new_values": []}
        if apply_updates:
            # Register unknown keys
            for key, info in suggestions["new_keys"].items():
                vals = info.get("suggested_values") or None
                row = upsert_registry_entry(
                    key=key,
                    description="Auto-registered by label hygiene",
                    allowed_values=vals,
                    source="jarvis",
                )
                applied["new_keys"].append(row)

            # Extend allowed values for existing keys
            if allow_values:
                for key, vals in suggestions["new_values"].items():
                    base = schema_map.get(key, {})
                    current_vals = base.get("values") or []
                    merged = sorted(set(current_vals) | set(vals))
                    row = upsert_registry_entry(
                        key=key,
                        allowed_values=merged,
                        source="jarvis",
                    )
                    applied["new_values"].append(row)

            refresh_label_schema_cache()

        metrics.inc("tool_label_hygiene")
        return {
            "success": True,
            "collections": collection_list,
            "scanned": scanned,
            "unknown_keys": dict(unknown_keys),
            "suggestions": suggestions,
            "applied": applied if apply_updates else None,
        }
    except Exception as e:
        log_with_context(logger, "error", "Tool label_hygiene failed", error=str(e))
        return {"error": str(e)}


def tool_mind_snapshot(**kwargs) -> Dict[str, Any]:
    """Quick 'mind' snapshot: labels, registry, and collection counts."""
    try:
        from qdrant_client import QdrantClient

        collections = kwargs.get("collections", "jarvis_work,jarvis_private,jarvis_comms")
        if isinstance(collections, str):
            collection_list = [c.strip() for c in collections.split(",") if c.strip()]
        else:
            collection_list = list(collections or [])

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        counts = {}
        for collection in collection_list:
            res = client.count(collection_name=collection)
            counts[collection] = res.count if res else 0

        registry = get_registry_entries(status="active")
        schema_map = get_label_schema()

        result = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "collections": counts,
            "label_schema_keys": len(schema_map),
            "label_registry_active": len(registry),
            "label_registry_keys": [r.get("key") for r in registry],
            "tool_count": len(TOOL_REGISTRY),
        }
        metrics.inc("tool_mind_snapshot")
        return {"success": True, "snapshot": result}
    except Exception as e:
        log_with_context(logger, "error", "Tool mind_snapshot failed", error=str(e))
        return {"error": str(e)}


def tool_record_decision_outcome(**kwargs) -> Dict[str, Any]:
    """Record feedback/outcome for a prior decision_id."""
    try:
        from .cross_session_learner import cross_session_learner

        decision_id = kwargs.get("decision_id")
        outcome = kwargs.get("outcome")
        feedback_score = kwargs.get("feedback_score")
        source_channel = kwargs.get("source_channel", "user")
        strategy_id = kwargs.get("strategy_id")
        tool_name = kwargs.get("tool_name")
        details = kwargs.get("details") or {}

        result = cross_session_learner.record_decision_outcome(
            decision_id=decision_id,
            outcome=outcome,
            feedback_score=feedback_score,
            source_channel=source_channel,
            strategy_id=strategy_id,
            tool_name=tool_name,
            details=details,
        )
        metrics.inc("tool_record_decision_outcome")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool record_decision_outcome failed", error=str(e))
        return {"error": str(e)}


def tool_get_git_events(**kwargs) -> Dict[str, Any]:
    """Return git commits in a time range (optional keywords)."""
    try:
        from .git_history import get_git_events

        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        keywords = kwargs.get("keywords")
        limit = kwargs.get("limit", 100)

        keyword_list = None
        if isinstance(keywords, str) and keywords.strip():
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
        elif isinstance(keywords, list):
            keyword_list = [str(k).strip() for k in keywords if str(k).strip()]

        result = get_git_events(
            start_time=start_time,
            end_time=end_time,
            keywords=keyword_list,
            limit=limit,
        )
        metrics.inc("tool_get_git_events")
        return result
    except Exception as e:
        log_with_context(logger, "error", "Tool get_git_events failed", error=str(e))
        return {"error": str(e)}


def tool_delegate_ollama_task(**kwargs) -> Dict[str, Any]:
    """Queue a task for local Ollama execution."""
    try:
        from . import ollama_delegation

        task_type = kwargs.get("task_type")
        instructions = kwargs.get("instructions")
        input_text = kwargs.get("input_text")
        input_path = kwargs.get("input_path")
        output_path = kwargs.get("output_path")
        model = kwargs.get("model")
        max_tokens = kwargs.get("max_tokens", 1000)
        temperature = kwargs.get("temperature", 0.3)
        language = kwargs.get("language", "de")
        output_format = kwargs.get("output_format", "text")
        callback_url = kwargs.get("callback_url")

        log_with_context(
            logger,
            "info",
            "Delegating task to Ollama",
            task_type=task_type,
            model=model,
        )

        task = ollama_delegation.create_task(
            task_type=ollama_delegation.TaskType(task_type),
            instructions=instructions,
            input_text=input_text,
            input_path=input_path,
            output_path=output_path,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            language=language,
            output_format=output_format,
            callback_url=callback_url,
        )

        metrics.inc("tool_delegate_ollama_task")
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type.value,
            "model": task.model,
        }
    except Exception as e:
        log_with_context(logger, "warning", "Ollama delegation failed", error=str(e))
        return {"error": str(e)}


def tool_get_ollama_task_status(**kwargs) -> Dict[str, Any]:
    """Return status for a queued Ollama task."""
    try:
        from . import ollama_delegation

        task_id = kwargs.get("task_id")
        status = ollama_delegation.get_task_status(task_id)
        metrics.inc("tool_get_ollama_task_status")
        if not status:
            return {"error": "task_not_found"}
        return status
    except Exception as e:
        log_with_context(logger, "warning", "Ollama status failed", error=str(e))
        return {"error": str(e)}


def tool_get_ollama_queue_status(**kwargs) -> Dict[str, Any]:
    """Return a summary of pending and processing Ollama tasks."""
    try:
        from .ollama_delegation import QUEUE_PENDING, QUEUE_PROCESSING

        limit = kwargs.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 50))

        pending_files = sorted(QUEUE_PENDING.glob("*.json"), key=lambda p: p.stat().st_mtime)
        processing_files = sorted(QUEUE_PROCESSING.glob("*.json"), key=lambda p: p.stat().st_mtime)

        pending_tasks = []
        for p in pending_files[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
                pending_tasks.append({
                    "task_id": data.get("task_id"),
                    "task_type": data.get("task_type"),
                    "created_at": data.get("created_at"),
                })
            except Exception:
                continue

        processing_tasks = []
        for p in processing_files[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
                processing_tasks.append({
                    "task_id": data.get("task_id"),
                    "task_type": data.get("task_type"),
                    "started_at": data.get("started_at"),
                })
            except Exception:
                continue

        metrics.inc("tool_get_ollama_queue_status")
        return {
            "pending_count": len(pending_files),
            "processing_count": len(processing_files),
            "pending_tasks": pending_tasks,
            "processing_tasks": processing_tasks,
        }
    except Exception as e:
        log_with_context(logger, "warning", "Ollama queue status failed", error=str(e))
        return {"error": str(e)}


def tool_cancel_ollama_task(**kwargs) -> Dict[str, Any]:
    """Cancel an Ollama task if it is still pending."""
    try:
        from .ollama_delegation import QUEUE_PENDING, OllamaTask, TaskStatus

        task_id = kwargs.get("task_id")
        if not task_id:
            return {"error": "task_id is required"}

        task = OllamaTask.load(task_id)
        if not task:
            return {"error": "task_not_found", "task_id": task_id}

        if task.status != TaskStatus.PENDING:
            return {
                "status": "not_cancelable",
                "task_id": task_id,
                "current_status": task.status.value,
            }

        pending_path = QUEUE_PENDING / f"{task_id}.json"
        if pending_path.exists():
            pending_path.unlink()
            metrics.inc("tool_cancel_ollama_task")
            return {"status": "canceled", "task_id": task_id}

        return {"status": "not_found", "task_id": task_id}
    except Exception as e:
        log_with_context(logger, "warning", "Ollama cancel failed", error=str(e))
        return {"error": str(e)}


def tool_get_ollama_callback_result(**kwargs) -> Dict[str, Any]:
    """Get result of a completed async Ollama task."""
    try:
        from .routers.ollama_callback_router import CALLBACK_HISTORY, CALLBACK_STORE
        import json

        task_id = kwargs.get("task_id")
        recent_only = kwargs.get("recent_only", False)
        limit = kwargs.get("limit", 10)

        if task_id:
            # Look for specific task
            for cb in CALLBACK_HISTORY:
                if cb["task_id"] == task_id:
                    metrics.inc("tool_get_ollama_callback_result")
                    return {"found": True, "callback": cb, "source": "memory"}

            # Check file store
            callback_file = CALLBACK_STORE / f"{task_id}.json"
            if callback_file.exists():
                with open(callback_file) as f:
                    metrics.inc("tool_get_ollama_callback_result")
                    return {"found": True, "callback": json.load(f), "source": "file"}

            return {"found": False, "task_id": task_id}

        elif recent_only:
            # Return recent callbacks
            metrics.inc("tool_get_ollama_callback_result")
            return {
                "recent_callbacks": CALLBACK_HISTORY[:limit],
                "count": len(CALLBACK_HISTORY[:limit])
            }

        return {"error": "Provide task_id or set recent_only=true"}

    except Exception as e:
        log_with_context(logger, "warning", "Get callback result failed", error=str(e))
        return {"error": str(e)}


def tool_ask_ollama(**kwargs) -> Dict[str, Any]:
    """
    Ask Ollama a question and get an answer.
    Jarvis's free local sub-assistant for simple tasks.
    """
    try:
        from . import ollama_python_bridge

        prompt = kwargs.get("prompt")
        if not prompt:
            return {"error": "prompt is required"}

        task_type = kwargs.get("task_type", "analyze")
        system_prompt = kwargs.get("system_prompt")
        max_tokens = kwargs.get("max_tokens")

        result = ollama_python_bridge.ask_ollama(
            prompt=prompt,
            task_type=task_type,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

        metrics.inc("tool_ask_ollama")

        if result.status == "success":
            return {
                "status": "success",
                "answer": result.answer,
                "model_used": result.model_used,
                "duration_ms": round(result.duration_ms, 1),
                "tokens": {
                    "prompt": result.prompt_tokens,
                    "response": result.response_tokens,
                }
            }
        else:
            return {
                "status": result.status,
                "error": result.error,
                "model_used": result.model_used,
                "duration_ms": round(result.duration_ms, 1),
            }

    except Exception as e:
        log_with_context(logger, "error", "ask_ollama failed", error=str(e))
        return {"error": str(e)}


def tool_ollama_python(**kwargs) -> Dict[str, Any]:
    """
    Generate and execute Python code via local Ollama.
    Saves API tokens by using local LLM for code generation.
    """
    try:
        from . import ollama_python_bridge

        task_description = kwargs.get("task_description")
        context = kwargs.get("context")
        model = kwargs.get("model")

        if not task_description:
            return {"error": "task_description is required"}

        result = ollama_python_bridge.generate_and_execute_python(
            task_description=task_description,
            context=context,
            model=model,
            user_id="jarvis_agent",
        )

        metrics.inc("tool_ollama_python")

        # Build response
        response = {
            "status": result.status,
            "model_used": result.model_used,
            "generation_time_ms": round(result.generation_time_ms, 2),
            "total_time_ms": round(result.total_time_ms, 2),
        }

        if result.generated_code:
            response["generated_code"] = result.generated_code

        if result.validation_error:
            response["validation_error"] = result.validation_error

        if result.exec_result:
            response["output"] = result.exec_result.get("stdout", "")
            if result.exec_result.get("stderr"):
                response["stderr"] = result.exec_result["stderr"]
            response["exec_id"] = result.exec_result.get("exec_id")

        return response

    except Exception as e:
        log_with_context(logger, "warning", "Ollama Python failed", error=str(e))
        return {"error": str(e)}


def tool_set_timer(**kwargs) -> Dict[str, Any]:
    """
    Create a reminder timer (scheduled via n8n, stored in Redis).
    """
    try:
        from .timer_service import create_timer
        from .tracing import get_current_user_id

        message = kwargs.get("message")
        delay_seconds = kwargs.get("delay_seconds")
        delay_minutes = kwargs.get("delay_minutes")
        due_at = kwargs.get("due_at")
        confirm = bool(kwargs.get("confirm", False))

        if message is None or not str(message).strip():
            return {"error": "message is required"}

        if delay_seconds is None and delay_minutes is not None:
            delay_seconds = int(float(delay_minutes) * 60)

        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")

        result = create_timer(
            user_id=user_id,
            message=str(message),
            due_at=due_at,
            delay_seconds=delay_seconds,
            channel="telegram",
            source="tool",
            confirm=confirm,
        )

        metrics.inc("tool_set_timer")
        return result

    except Exception as e:
        log_with_context(logger, "warning", "Set timer failed", error=str(e))
        return {"error": str(e)}


def tool_cancel_timer(**kwargs) -> Dict[str, Any]:
    """
    Cancel an existing timer by timer_id.
    """
    try:
        from .timer_service import cancel_timer
        from .tracing import get_current_user_id

        timer_id = kwargs.get("timer_id")
        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")

        if not timer_id:
            return {"error": "timer_id is required"}

        result = cancel_timer(str(timer_id), user_id=user_id)
        metrics.inc("tool_cancel_timer")
        return result

    except Exception as e:
        log_with_context(logger, "warning", "Cancel timer failed", error=str(e))
        return {"error": str(e)}


def tool_list_timers(**kwargs) -> Dict[str, Any]:
    """
    List timers for a user.
    """
    try:
        from .timer_service import list_timers
        from .tracing import get_current_user_id

        user_id = kwargs.get("user_id") or str(get_current_user_id() or "jarvis_agent")
        status = kwargs.get("status")
        limit = kwargs.get("limit", 50)

        result = list_timers(str(user_id), status=status, limit=int(limit))
        metrics.inc("tool_list_timers")
        return result

    except Exception as e:
        log_with_context(logger, "warning", "List timers failed", error=str(e))
        return {"error": str(e)}


def tool_request_python_sandbox(**kwargs) -> Dict[str, Any]:
    """
    Queue a manual-approval request for running Jarvis-authored Python code.
    This does not execute code automatically.
    """
    try:
        from .action_queue import create_action_request
        from .tracing import get_current_user_id

        code = kwargs.get("code")
        reason = kwargs.get("reason", "agent sandbox request")
        timeout_seconds = kwargs.get("timeout_seconds")
        metadata = kwargs.get("metadata") or {}

        if code is None or not str(code).strip():
            return {"error": "code is required"}

        user_id = get_current_user_id() or "jarvis_agent"

        action = create_action_request(
            action_name="python_sandbox_execute",
            description="Python sandbox execute",
            target="python_executor",
            context={
                "code": str(code),
                "timeout_seconds": timeout_seconds,
                "reason": reason,
                "metadata": metadata,
            },
            content_preview=str(code)[:400],
            user_id=str(user_id),
        )

        status = action.get("status")
        if status == "blocked":
            return {"status": "blocked", "action": action}

        if status == "pending":
            return {
                "status": "pending",
                "approval_required": True,
                "action_id": action.get("id"),
                "approve_endpoint": f"/jarvis/self/code-sandbox/actions/{action.get('id')}/approve",
            }

        return {
            "status": status,
            "approval_required": False,
            "action_id": action.get("id"),
            "execute_endpoint": f"/jarvis/self/code-sandbox/actions/{action.get('id')}/execute",
        }

    except Exception as e:
        log_with_context(logger, "warning", "Request Python sandbox failed", error=str(e))
        return {"error": str(e)}


def tool_execute_python(**kwargs) -> Dict[str, Any]:
    """
    Execute Python code written by Jarvis in the sandbox.
    For when Jarvis writes code himself (higher quality, uses API tokens).
    """
    try:
        from . import python_executor

        code = kwargs.get("code")
        reason = kwargs.get("reason", "agent execution")

        if code is None or not str(code).strip():
            return {"error": "code is required"}

        result = python_executor.execute_python(
            code=code,
            user_id="jarvis_agent",
            metadata={"reason": reason, "source": "agent_tool"},
        )

        metrics.inc("tool_execute_python")

        return {
            "status": result.status,
            "exec_id": result.exec_id,
            "output": result.stdout,
            "stderr": result.stderr if result.stderr else None,
            "exit_code": result.exit_code,
            "duration_ms": round(result.duration_ms, 2),
            "blocked_reason": result.blocked_reason,
            "artifacts": result.artifacts,
        }

    except Exception as e:
        log_with_context(logger, "warning", "Execute Python failed", error=str(e))
        return {"error": str(e)}


# ============ Sub-Agent Framework Tools (Phase 18) ============

def tool_delegate_to_subagent(**kwargs) -> Dict[str, Any]:
    """
    Delegate a task to a sub-agent with tool access.
    Sub-agents can use tools like search_kb, read_file, calculate, etc.
    """
    try:
        from .subagents import get_registry, SubAgentTask
        import asyncio

        agent_id = kwargs.get("agent_id", "ollama")
        instructions = kwargs.get("instructions")
        input_text = kwargs.get("input_text")
        context = kwargs.get("context")
        tools = kwargs.get("tools", [])
        sync = kwargs.get("sync", False)

        log_with_context(
            logger,
            "info",
            "Delegating task to subagent",
            agent_id=agent_id,
            sync=sync,
            tools_enabled=tools,
        )

        if not instructions:
            return {"error": "instructions is required"}

        registry = get_registry()
        agent = registry.get(agent_id)

        if not agent:
            return {"error": f"Agent not found: {agent_id}"}

        # Create task
        task = SubAgentTask(
            task_id=SubAgentTask.generate_id(agent_id),
            agent_id=agent_id,
            instructions=instructions,
            created_at=datetime.now().isoformat(),
            input_text=input_text,
            context=context,
            tools_enabled=tools,
        )

        metrics.inc("tool_delegate_to_subagent")

        if sync:
            # Synchronous execution
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(agent.execute(task))
            finally:
                loop.close()

            return {
                "status": result.status,
                "task_id": result.task_id,
                "result": result.result,
                "error": result.error,
                "tool_calls": len(result.tool_calls_made),
                "execution_time_ms": round(result.execution_time_ms, 2),
                "model_used": result.model_used,
            }
        else:
            # Async - save to queue
            from .routers.subagent_router import _save_task, SUBAGENT_QUEUE_PENDING

            _save_task(task, SUBAGENT_QUEUE_PENDING)

            return {
                "status": "queued",
                "task_id": task.task_id,
                "agent_id": agent_id,
                "tools_enabled": tools,
                "message": "Task queued. Use get_subagent_result to check status."
            }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        log_with_context(logger, "warning", "Delegate to subagent failed", error=str(e))
        return {"error": str(e)}


def tool_get_subagent_result(**kwargs) -> Dict[str, Any]:
    """
    Get the result of a delegated sub-agent task.
    """
    try:
        from .routers.subagent_router import _load_task

        task_id = kwargs.get("task_id")
        if not task_id:
            return {"error": "task_id is required"}

        task = _load_task(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}

        metrics.inc("tool_get_subagent_result")

        return {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "tool_calls_made": task.tool_calls_made,
            "execution_time_ms": task.execution_time_ms,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
        }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        log_with_context(logger, "warning", "Get subagent result failed", error=str(e))
        return {"error": str(e)}


def tool_list_subagents(**kwargs) -> Dict[str, Any]:
    """
    List available sub-agents and their tools.
    """
    try:
        from .subagents import get_registry

        registry = get_registry()
        agents = registry.list_agents()

        metrics.inc("tool_list_subagents")

        return {
            "agents": agents,
            "count": len(agents),
        }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        log_with_context(logger, "warning", "List subagents failed", error=str(e))
        return {"error": str(e)}


# ============ Self-Inspection Tools (Phase 6) ============

def tool_read_own_code(
    file_name: str,
    max_lines: int = 200,
    search_term: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Read Jarvis' own source code files.
    Enables self-inspection and understanding of own implementation.
    """
    log_with_context(logger, "info", "Tool: read_own_code", file_name=file_name)
    metrics.inc("tool_read_own_code")

    # Map of available source files
    source_dir = "/brain/system/ingestion/app"

    # Validate file name (security)
    if not file_name.endswith(".py"):
        file_name = f"{file_name}.py"

    # Prevent path traversal
    if "/" in file_name or "\\" in file_name or ".." in file_name:
        return {
            "error": "Invalid file name",
            "hint": "Use just the file name like 'agent.py', not a path"
        }

    file_path = f"{source_dir}/{file_name}"

    # Read the file
    result = tool_read_project_file(file_path, max_lines=max_lines)

    if not result.get("success"):
        # Check if it's in a subdirectory
        for subdir in ["routers", "subagents"]:
            alt_path = f"{source_dir}/{subdir}/{file_name}"
            alt_result = tool_read_project_file(alt_path, max_lines=max_lines)
            if alt_result.get("success"):
                result = alt_result
                break

    # If search_term provided, filter to relevant section
    if result.get("success") and search_term:
        content = result.get("content", "")
        lines = content.split("\n")
        matching_lines = []
        context_before = 5
        context_after = 15

        for i, line in enumerate(lines):
            if search_term.lower() in line.lower():
                start = max(0, i - context_before)
                end = min(len(lines), i + context_after + 1)
                matching_lines.append({
                    "line_number": i + 1,
                    "match": line.strip(),
                    "context": "\n".join(lines[start:end])
                })

        if matching_lines:
            result["search_results"] = matching_lines[:5]  # Max 5 matches
            result["search_term"] = search_term
            result["total_matches"] = len(matching_lines)

    return result


def tool_read_roadmap_and_tasks(
    document: str,
    section: str = None,
    max_lines: int = 300,
    **kwargs
) -> Dict[str, Any]:
    """
    Read roadmap, tasks, and development documentation.
    Essential for understanding current work and planning.
    """
    log_with_context(logger, "info", "Tool: read_roadmap_and_tasks", document=document)
    metrics.inc("tool_read_roadmap_and_tasks")

    # Document mapping
    doc_map = {
        "tasks": "/brain/system/docker/TASKS.md",
        "roadmap": "/brain/system/docker/ROADMAP_UNIFIED_LATEST.md",
        "agents": "/brain/system/docker/AGENTS.md",
        "agent_routing": "/brain/system/docker/AGENT_ROUTING.md",
        "review_plan": "/brain/system/docker/JARVIS_REVIEW_PLAN.md",
    }

    if document not in doc_map:
        return {
            "error": f"Unknown document: {document}",
            "available": list(doc_map.keys())
        }

    result = tool_read_project_file(doc_map[document], max_lines=max_lines)

    # If section search requested
    if result.get("success") and section:
        content = result.get("content", "")
        lines = content.split("\n")

        # Find section heading
        section_start = None
        section_end = None
        section_lower = section.lower()

        for i, line in enumerate(lines):
            if section_lower in line.lower() and line.strip().startswith("#"):
                section_start = i
            elif section_start is not None and line.strip().startswith("#") and i > section_start:
                section_end = i
                break

        if section_start is not None:
            section_lines = lines[section_start:section_end] if section_end else lines[section_start:]
            result["section_content"] = "\n".join(section_lines[:100])  # Max 100 lines
            result["section_found"] = True
            result["section_name"] = section
        else:
            result["section_found"] = False
            result["section_name"] = section

    return result


def tool_list_own_source_files(
    include_routers: bool = True,
    include_subagents: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    List all Python source files in Jarvis' codebase.
    """
    log_with_context(logger, "info", "Tool: list_own_source_files")
    metrics.inc("tool_list_own_source_files")

    source_dir = "/brain/system/ingestion/app"
    files = []

    try:
        import glob
        from datetime import datetime

        # Main directory
        for f in glob.glob(f"{source_dir}/*.py"):
            stat = os.stat(f)
            files.append({
                "name": os.path.basename(f),
                "path": f,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        # Routers subdirectory
        if include_routers:
            for f in glob.glob(f"{source_dir}/routers/*.py"):
                stat = os.stat(f)
                files.append({
                    "name": f"routers/{os.path.basename(f)}",
                    "path": f,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

        # Subagents subdirectory
        if include_subagents:
            for f in glob.glob(f"{source_dir}/subagents/*.py"):
                stat = os.stat(f)
                files.append({
                    "name": f"subagents/{os.path.basename(f)}",
                    "path": f,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

        # Sort by name
        files.sort(key=lambda x: x["name"])

        return {
            "success": True,
            "file_count": len(files),
            "files": files,
            "source_dir": source_dir
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to list source files", error=str(e))
        return {"error": str(e)}


# ============ Self-Validation Tools (Phase 19) ============

def tool_validate_tool_registry(**kwargs) -> Dict[str, Any]:
    """Validate tool registry consistency."""
    log_with_context(logger, "info", "Tool: validate_tool_registry")
    metrics.inc("tool_validate_tool_registry")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.validate_tool_registry()
    except Exception as e:
        log_with_context(logger, "error", "Validate tool registry failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_get_response_metrics(hours: int = 24, **kwargs) -> Dict[str, Any]:
    """Get response performance metrics."""
    log_with_context(logger, "info", "Tool: get_response_metrics", hours=hours)
    metrics.inc("tool_get_response_metrics")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.get_response_metrics(hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Get response metrics failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_memory_diagnostics(**kwargs) -> Dict[str, Any]:
    """Diagnose memory and context persistence."""
    log_with_context(logger, "info", "Tool: memory_diagnostics")
    metrics.inc("tool_memory_diagnostics")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.memory_diagnostics()
    except Exception as e:
        log_with_context(logger, "error", "Memory diagnostics failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_context_window_analysis(user_id: int = None, **kwargs) -> Dict[str, Any]:
    """Analyze context window usage patterns."""
    log_with_context(logger, "info", "Tool: context_window_analysis", user_id=user_id)
    metrics.inc("tool_context_window_analysis")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.context_window_analysis(user_id=user_id)
    except Exception as e:
        log_with_context(logger, "error", "Context window analysis failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_benchmark_tool_calls(hours: int = 24, **kwargs) -> Dict[str, Any]:
    """Benchmark tool calls over a time window."""
    log_with_context(logger, "info", "Tool: benchmark_tool_calls", hours=hours)
    metrics.inc("tool_benchmark_tool_calls")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.benchmark_tool_calls(hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Benchmark tool calls failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_compare_code_versions(module: str = "main", **kwargs) -> Dict[str, Any]:
    """Compare a module with recent git history."""
    log_with_context(logger, "info", "Tool: compare_code_versions", module=module)
    metrics.inc("tool_compare_code_versions")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.compare_code_versions(module=module)
    except Exception as e:
        log_with_context(logger, "error", "Compare code versions failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_conversation_continuity_test(user_id: int, **kwargs) -> Dict[str, Any]:
    """Test cross-session continuity for a user."""
    log_with_context(logger, "info", "Tool: conversation_continuity_test", user_id=user_id)
    metrics.inc("tool_conversation_continuity_test")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.conversation_continuity_test(user_id=user_id)
    except Exception as e:
        log_with_context(logger, "error", "Conversation continuity test failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_response_quality_metrics(hours: int = 168, **kwargs) -> Dict[str, Any]:
    """Analyze response quality over time."""
    log_with_context(logger, "info", "Tool: response_quality_metrics", hours=hours)
    metrics.inc("tool_response_quality_metrics")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.response_quality_metrics(hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Response quality metrics failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_proactivity_score(user_id: int = None, hours: int = 168, **kwargs) -> Dict[str, Any]:
    """Measure proactive behavior effectiveness."""
    log_with_context(logger, "info", "Tool: proactivity_score", user_id=user_id, hours=hours)
    metrics.inc("tool_proactivity_score")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.proactivity_score(user_id=user_id, hours=hours)
    except Exception as e:
        log_with_context(logger, "error", "Proactivity score failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_self_validation_dashboard(**kwargs) -> Dict[str, Any]:
    """Return combined self-validation dashboard metrics."""
    log_with_context(logger, "info", "Tool: self_validation_dashboard")
    metrics.inc("tool_self_validation_dashboard")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.dashboard_snapshot()
    except Exception as e:
        log_with_context(logger, "error", "Self validation dashboard failed", error=str(e))
        return {"status": "error", "error": str(e)}


def tool_self_validation_pulse(**kwargs) -> Dict[str, Any]:
    """Quick health pulse for real-time monitoring (<50ms target)."""
    log_with_context(logger, "info", "Tool: self_validation_pulse")
    metrics.inc("tool_self_validation_pulse")

    try:
        from .services.self_validation_service import get_self_validation_service

        service = get_self_validation_service()
        return service.quick_pulse()
    except Exception as e:
        log_with_context(logger, "error", "Self validation pulse failed", error=str(e))
        return {"status": "error", "error": str(e)}


# ============ Dynamic Tool Creation ============

def tool_write_dynamic_tool(
    name: str = None,
    description: str = None,
    code: str = None,
    parameters: dict = None,
    category: str = "custom",
    sandbox: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a new dynamic tool that Jarvis can use.

    Args:
        name: Tool name (snake_case, e.g., 'my_custom_tool')
        description: What the tool does
        code: Python code for the tool handler function
        parameters: JSON schema for tool parameters
        category: Tool category (default: custom)
        sandbox: If True, tool goes to sandbox first (default: True)

    Returns:
        Status of tool creation
    """
    log_with_context(logger, "info", "Tool: write_dynamic_tool", name=name, category=category)
    metrics.inc("tool_write_dynamic_tool")

    if not name or not description or not code:
        return {"error": "name, description, and code are required"}

    try:
        from .tool_loader import DynamicToolLoader, TOOLS_SANDBOX_DIR, TOOLS_DYNAMIC_DIR
        import re

        # Validate name format
        if not re.match(r'^[a-z][a-z0-9_]*$', name):
            return {"error": "name must be snake_case (lowercase, underscores allowed)"}

        # Security validation
        violations = DynamicToolLoader._validate_code(code, f"{name}.py")
        if violations:
            return {"error": "Security violations", "violations": violations}

        # Indent code properly (4 spaces for function body)
        indented_code = code.replace('\n', '\n    ')

        # Build tool file content
        tool_content = f'''"""
Dynamic Tool: {name}
Category: {category}
Description: {description}
Created: {datetime.utcnow().isoformat()}Z
"""
from typing import Dict, Any

TOOL_SCHEMA = {{
    "name": "{name}",
    "description": """{description}""",
    "input_schema": {{
        "type": "object",
        "properties": {json.dumps(parameters or {}, indent=8)},
        "required": []
    }}
}}

TOOL_CATEGORY = "{category}"

def tool_handler(**kwargs) -> Dict[str, Any]:
    """Tool handler function."""
    {indented_code}
'''

        # Write to appropriate directory
        target_dir = TOOLS_SANDBOX_DIR if sandbox else TOOLS_DYNAMIC_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        tool_file = target_dir / f"{name}.py"
        tool_file.write_text(tool_content)

        # If not sandbox, reload immediately
        if not sandbox:
            DynamicToolLoader.reload(name)

        return {
            "status": "created",
            "name": name,
            "location": "sandbox" if sandbox else "live",
            "path": str(tool_file),
            "next_step": "Use promote_sandbox_tool to make it live" if sandbox else "Tool is now available"
        }

    except Exception as e:
        log_with_context(logger, "error", "write_dynamic_tool failed", error=str(e))
        return {"error": str(e)}


def tool_promote_sandbox_tool(name: str = None, **kwargs) -> Dict[str, Any]:
    """
    Promote a tool from sandbox to live production.

    Args:
        name: Name of the sandbox tool to promote

    Returns:
        Status of promotion
    """
    log_with_context(logger, "info", "Tool: promote_sandbox_tool", name=name)
    metrics.inc("tool_promote_sandbox_tool")

    if not name:
        return {"error": "name is required"}

    try:
        from .tool_loader import DynamicToolLoader, TOOLS_SANDBOX_DIR, TOOLS_DYNAMIC_DIR
        import shutil

        sandbox_file = TOOLS_SANDBOX_DIR / f"{name}.py"
        if not sandbox_file.exists():
            return {"error": f"Tool '{name}' not found in sandbox"}

        # Move to live directory
        live_file = TOOLS_DYNAMIC_DIR / f"{name}.py"
        shutil.move(str(sandbox_file), str(live_file))

        # Hot-reload the tool
        result = DynamicToolLoader.reload(name)

        return {
            "status": "promoted",
            "name": name,
            "path": str(live_file),
            "reload_result": result
        }

    except Exception as e:
        log_with_context(logger, "error", "promote_sandbox_tool failed", error=str(e))
        return {"error": str(e)}


# ============ Learning & Memory Tools ============

def tool_record_learning(
    fact: str = None,
    category: str = "general",
    confidence: float = 0.8,
    source: str = "conversation",
    context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record a learning/insight for cross-session pattern analysis.

    Args:
        fact: The learning or insight to record
        category: Category (general, capability, preference, workflow, technical)
        confidence: Confidence level 0.0-1.0
        source: Source of learning (conversation, observation, feedback)
        context: Additional context

    Returns:
        Status of recording
    """
    log_with_context(logger, "info", "Tool: record_learning", category=category)
    metrics.inc("tool_record_learning")

    if not fact:
        return {"error": "fact is required"}

    try:
        from . import session_manager

        conn = session_manager._get_conn()

        # Create learnings table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'conversation',
                context TEXT,
                created_at TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                migration_candidate INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learnings_category ON jarvis_learnings(category)")

        # Insert learning
        now = datetime.utcnow().isoformat() + "Z"
        cursor = conn.execute("""
            INSERT INTO jarvis_learnings (fact, category, confidence, source, context, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fact, category, confidence, source, context, now))

        conn.commit()
        learning_id = cursor.lastrowid
        conn.close()

        return {
            "status": "recorded",
            "learning_id": learning_id,
            "fact": fact[:100] + "..." if len(fact) > 100 else fact,
            "category": category,
            "confidence": confidence
        }

    except Exception as e:
        log_with_context(logger, "error", "record_learning failed", error=str(e))
        return {"error": str(e)}


def tool_get_learnings(
    category: str = None,
    days_back: int = 30,
    limit: int = 20,
    compact: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Retrieve recorded learnings/insights.

    Args:
        category: Filter by category
        days_back: How many days back to search
        limit: Maximum results
        compact: If True, return only essential fields (fact, category)

    Returns:
        List of learnings with summary
    """
    log_with_context(logger, "info", "Tool: get_learnings", category=category, limit=limit)
    metrics.inc("tool_get_learnings")

    try:
        from . import session_manager
        from datetime import timedelta

        conn = session_manager._get_conn()

        cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat() + "Z"

        if category:
            rows = conn.execute("""
                SELECT id, fact, category, confidence, source, created_at FROM jarvis_learnings
                WHERE category = ? AND created_at >= ?
                ORDER BY confidence DESC, created_at DESC LIMIT ?
            """, (category, cutoff, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, fact, category, confidence, source, created_at FROM jarvis_learnings
                WHERE created_at >= ?
                ORDER BY confidence DESC, created_at DESC LIMIT ?
            """, (cutoff, limit)).fetchall()

        conn.close()

        # Build compact or full learnings list
        if compact:
            learnings = []
            by_category = {}
            for row in rows:
                cat = row['category'] or 'general'
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(row['fact'])
                learnings.append({
                    "fact": row['fact'],
                    "category": cat,
                    "confidence": row['confidence']
                })

            # Build human-readable summary
            summary_parts = []
            for cat, facts in by_category.items():
                summary_parts.append(f"**{cat.title()}** ({len(facts)}): " + "; ".join(facts[:3]))
                if len(facts) > 3:
                    summary_parts[-1] += f" (+{len(facts)-3} more)"

            return {
                "summary": "\n".join(summary_parts),
                "learnings": learnings,
                "count": len(learnings),
                "by_category": {k: len(v) for k, v in by_category.items()},
                "days_searched": days_back
            }
        else:
            learnings = [dict(row) for row in rows]
            return {
                "learnings": learnings,
                "count": len(learnings),
                "category_filter": category,
                "days_searched": days_back
            }

    except Exception as e:
        # Table might not exist yet
        if "no such table" in str(e):
            return {"learnings": [], "count": 0, "note": "No learnings recorded yet"}
        log_with_context(logger, "error", "get_learnings failed", error=str(e))
        return {"error": str(e)}


# ============ Context Persistence Tools ============

def tool_store_context(
    key: str = None,
    value: str = None,
    context_type: str = "general",
    ttl_hours: int = 168,  # 1 week default
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store a context value for later retrieval.

    Args:
        key: Unique key for this context
        value: Value to store (string, will be JSON serialized if dict)
        context_type: Type of context (general, preference, state, memory)
        ttl_hours: Time to live in hours (default 168 = 1 week)
        user_id: Optional user ID

    Returns:
        Status of storage
    """
    log_with_context(logger, "info", "Tool: store_context", key=key, context_type=context_type)
    metrics.inc("tool_store_context")

    if not key or value is None:
        return {"error": "key and value are required"}

    try:
        from . import session_manager

        conn = session_manager._get_conn()

        # Create context_store table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                user_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                UNIQUE(key, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_key ON context_store(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_type ON context_store(context_type)")

        now = datetime.utcnow()
        expires = (now + timedelta(hours=ttl_hours)).isoformat() + "Z"
        now_str = now.isoformat() + "Z"

        # Serialize value if needed
        if isinstance(value, (dict, list)):
            value = json.dumps(value)

        # Upsert
        conn.execute("""
            INSERT INTO context_store (key, value, context_type, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key, user_id) DO UPDATE SET
                value = excluded.value,
                context_type = excluded.context_type,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
        """, (key, value, context_type, user_id, now_str, expires))

        conn.commit()
        conn.close()

        return {
            "status": "stored",
            "key": key,
            "context_type": context_type,
            "expires_at": expires
        }

    except Exception as e:
        log_with_context(logger, "error", "store_context failed", error=str(e))
        return {"error": str(e)}


def tool_recall_context(
    key: str = None,
    context_type: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall a stored context value.

    Args:
        key: Key to recall (if None, returns all for context_type)
        context_type: Filter by type
        user_id: Optional user ID filter

    Returns:
        Stored context value(s)
    """
    log_with_context(logger, "info", "Tool: recall_context", key=key, context_type=context_type)
    metrics.inc("tool_recall_context")

    try:
        from . import session_manager

        conn = session_manager._get_conn()
        now = datetime.utcnow().isoformat() + "Z"

        if key:
            # Get specific key
            row = conn.execute("""
                SELECT * FROM context_store
                WHERE key = ? AND (user_id = ? OR user_id IS NULL)
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC LIMIT 1
            """, (key, user_id, now)).fetchone()

            conn.close()

            if not row:
                return {"found": False, "key": key}

            value = row["value"]
            # Try to deserialize JSON
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass

            return {
                "found": True,
                "key": key,
                "value": value,
                "context_type": row["context_type"],
                "created_at": row["created_at"]
            }
        else:
            # Get all for context_type
            if context_type:
                rows = conn.execute("""
                    SELECT * FROM context_store
                    WHERE context_type = ? AND (user_id = ? OR user_id IS NULL)
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC LIMIT 50
                """, (context_type, user_id, now)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM context_store
                    WHERE (user_id = ? OR user_id IS NULL)
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC LIMIT 50
                """, (user_id, now)).fetchall()

            conn.close()

            contexts = []
            for row in rows:
                value = row["value"]
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
                contexts.append({
                    "key": row["key"],
                    "value": value,
                    "context_type": row["context_type"],
                    "created_at": row["created_at"]
                })

            return {
                "found": len(contexts) > 0,
                "contexts": contexts,
                "count": len(contexts)
            }

    except Exception as e:
        if "no such table" in str(e):
            return {"found": False, "note": "No context stored yet"}
        log_with_context(logger, "error", "recall_context failed", error=str(e))
        return {"error": str(e)}


def tool_forget_context(
    key: str = None,
    context_type: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Delete stored context.

    Args:
        key: Specific key to delete
        context_type: Delete all of this type
        user_id: User ID filter

    Returns:
        Deletion status
    """
    log_with_context(logger, "info", "Tool: forget_context", key=key, context_type=context_type)
    metrics.inc("tool_forget_context")

    if not key and not context_type:
        return {"error": "Either key or context_type is required"}

    try:
        from . import session_manager

        conn = session_manager._get_conn()

        if key:
            cursor = conn.execute("""
                DELETE FROM context_store WHERE key = ? AND (user_id = ? OR user_id IS NULL)
            """, (key, user_id))
        else:
            cursor = conn.execute("""
                DELETE FROM context_store WHERE context_type = ? AND (user_id = ? OR user_id IS NULL)
            """, (context_type, user_id))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return {
            "status": "deleted",
            "deleted_count": deleted,
            "key": key,
            "context_type": context_type
        }

    except Exception as e:
        if "no such table" in str(e):
            return {"status": "ok", "deleted_count": 0}
        log_with_context(logger, "error", "forget_context failed", error=str(e))
        return {"error": str(e)}


# ============ Batch Operations (solve step-limit issue) ============

def tool_record_learnings_batch(
    learnings: list = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record multiple learnings in a single operation.

    Use this instead of calling record_learning multiple times to avoid step limits!

    Args:
        learnings: List of dicts, each with: fact (required), category, confidence, source, context
                   Example: [{"fact": "...", "category": "technical"}, {"fact": "...", "confidence": 0.9}]

    Returns:
        Summary of all recorded learnings
    """
    log_with_context(logger, "info", "Tool: record_learnings_batch", count=len(learnings) if learnings else 0)
    metrics.inc("tool_record_learnings_batch")

    if not learnings or not isinstance(learnings, list):
        return {"error": "learnings must be a non-empty list"}

    try:
        from . import session_manager

        conn = session_manager._get_conn()

        # Create table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'conversation',
                context TEXT,
                created_at TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                migration_candidate INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learnings_category ON jarvis_learnings(category)")

        results = []
        now = datetime.utcnow().isoformat() + "Z"

        for item in learnings:
            if not isinstance(item, dict) or "fact" not in item:
                results.append({"error": "Invalid item, requires 'fact'"})
                continue

            fact = item["fact"]
            category = item.get("category", "general")
            confidence = item.get("confidence", 0.8)
            source = item.get("source", "batch")
            context = item.get("context")

            cursor = conn.execute("""
                INSERT INTO jarvis_learnings (fact, category, confidence, source, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fact, category, confidence, source, context, now))

            results.append({
                "learning_id": cursor.lastrowid,
                "fact": fact[:50] + "..." if len(fact) > 50 else fact,
                "category": category
            })

        conn.commit()
        conn.close()

        return {
            "status": "batch_recorded",
            "total_count": len(results),
            "success_count": sum(1 for r in results if "learning_id" in r),
            "results": results
        }

    except Exception as e:
        log_with_context(logger, "error", "record_learnings_batch failed", error=str(e))
        return {"error": str(e)}


def tool_store_contexts_batch(
    contexts: list = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store multiple context values in a single operation.

    Use this instead of calling store_context multiple times to avoid step limits!

    Args:
        contexts: List of dicts, each with: key (required), value (required), context_type, ttl_hours
                  Example: [{"key": "k1", "value": "v1"}, {"key": "k2", "value": {"nested": true}}]

    Returns:
        Summary of all stored contexts
    """
    log_with_context(logger, "info", "Tool: store_contexts_batch", count=len(contexts) if contexts else 0)
    metrics.inc("tool_store_contexts_batch")

    if not contexts or not isinstance(contexts, list):
        return {"error": "contexts must be a non-empty list"}

    try:
        from . import session_manager

        conn = session_manager._get_conn()

        # Create table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                user_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                UNIQUE(key, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_key ON context_store(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_type ON context_store(context_type)")

        results = []
        now = datetime.utcnow()
        now_str = now.isoformat() + "Z"
        user_id = kwargs.get("user_id")

        for item in contexts:
            if not isinstance(item, dict) or "key" not in item or "value" not in item:
                results.append({"error": "Invalid item, requires 'key' and 'value'"})
                continue

            key = item["key"]
            value = item["value"]
            context_type = item.get("context_type", "general")
            ttl_hours = item.get("ttl_hours", 168)

            # Serialize value if needed
            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            expires = (now + timedelta(hours=ttl_hours)).isoformat() + "Z"

            conn.execute("""
                INSERT INTO context_store (key, value, context_type, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, user_id) DO UPDATE SET
                    value = excluded.value,
                    context_type = excluded.context_type,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
            """, (key, value, context_type, user_id, now_str, expires))

            results.append({
                "key": key,
                "context_type": context_type,
                "expires_at": expires
            })

        conn.commit()
        conn.close()

        return {
            "status": "batch_stored",
            "total_count": len(results),
            "success_count": sum(1 for r in results if "key" in r),
            "results": results
        }

    except Exception as e:
        log_with_context(logger, "error", "store_contexts_batch failed", error=str(e))
        return {"error": str(e)}


def tool_list_available_tools(category: str = None, search: str = None, **kwargs) -> Dict[str, Any]:
    """
    List all available tools that Jarvis can use.

    Use this BEFORE trying to call a tool you're not sure about!
    This prevents hallucinating non-existent tools.

    Args:
        category: Filter by category (memory, calendar, email, system, dynamic, etc.)
        search: Search for tools by name or description

    Returns:
        List of available tool names with descriptions
    """
    log_with_context(logger, "info", "Tool: list_available_tools", category=category, search=search)
    metrics.inc("tool_list_available_tools")

    try:
        # Get all registered tools
        all_tools = list(TOOL_REGISTRY.keys())

        # Categorize tools
        categories = {
            "memory": ["search_knowledge", "remember_fact", "recall_facts", "remember_conversation_context",
                      "recall_conversation_history", "get_person_context", "propose_knowledge_update"],
            "calendar": ["get_calendar_events", "create_calendar_event"],
            "email": ["search_emails", "get_gmail_messages", "send_email"],
            "chat": ["search_chats"],
            "project": ["add_project", "list_projects", "update_project_status", "manage_thread"],
            "file": ["read_project_file", "write_project_file", "read_my_source_files", "read_own_code",
                    "list_own_source_files", "read_roadmap_and_tasks"],
            "system": ["system_health_check", "get_development_status", "validate_tool_registry",
                      "self_validation_dashboard", "self_validation_pulse", "mind_snapshot"],
            "dynamic": [],  # Populated below
            "ollama": ["delegate_ollama_task", "get_ollama_task_status", "ask_ollama", "ollama_python"],
            "python": ["execute_python", "request_python_sandbox"],
            "self_improvement": ["write_dynamic_tool", "promote_sandbox_tool", "system_pulse"],
        }

        # Find dynamic tools
        try:
            from .tool_loader import DynamicToolLoader
            dynamic_tools = list(DynamicToolLoader.get_all_tools().keys())
            categories["dynamic"] = dynamic_tools
        except Exception:
            pass

        # Filter by category
        if category:
            category_lower = category.lower()
            if category_lower in categories:
                filtered = categories[category_lower]
            else:
                filtered = [t for t in all_tools if category_lower in t.lower()]
        else:
            filtered = all_tools

        # Filter by search
        if search:
            search_lower = search.lower()
            filtered = [t for t in filtered if search_lower in t.lower()]

        # Build result with descriptions
        tool_info = []
        for tool_name in sorted(filtered):
            # Find description from TOOL_DEFINITIONS
            desc = ""
            for td in TOOL_DEFINITIONS:
                if td.get("name") == tool_name:
                    desc = td.get("description", "")[:100]
                    break
            tool_info.append({"name": tool_name, "description": desc})

        return {
            "total_tools": len(all_tools),
            "filtered_count": len(tool_info),
            "category": category,
            "search": search,
            "tools": tool_info[:50],  # Limit to 50
            "categories_available": list(categories.keys()),
            "hint": "Use category='self_improvement' to see tools for creating new tools!"
        }
    except Exception as e:
        log_with_context(logger, "error", "List available tools failed", error=str(e))
        return {"status": "error", "error": str(e)}


# ============ Tool Autonomy (Phase 19.6) ============

def tool_manage_tool_registry(
    action: str = None,
    tool_name: str = None,
    enabled: bool = None,
    description: str = None,
    category: str = None,
    reason: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Manage tool registry - enable/disable tools, update descriptions, assign categories.

    This gives Jarvis autonomous control over its own capabilities!

    Args:
        action: "enable", "disable", "update_description", "assign_category", "get_stats"
        tool_name: Name of the tool to manage
        enabled: For enable/disable actions
        description: New description for update_description
        category: Category name for assign_category
        reason: Why this change is being made

    Returns:
        Result of the management action
    """
    log_with_context(logger, "info", "Tool: manage_tool_registry", action=action, tool_name=tool_name)
    metrics.inc("tool_manage_tool_registry")

    if not action:
        return {"error": "action is required (enable, disable, update_description, assign_category, get_stats)"}

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        if action == "enable" and tool_name:
            return service.set_tool_enabled(tool_name, True, reason)

        elif action == "disable" and tool_name:
            return service.set_tool_enabled(tool_name, False, reason)

        elif action == "update_description" and tool_name and description:
            return service.update_tool_description(tool_name, description, reason)

        elif action == "assign_category" and tool_name and category:
            return service.assign_tool_to_category(tool_name, category)

        elif action == "get_stats":
            tools = service.get_enabled_tools()
            categories = service.get_categories()
            mods = service.get_recent_modifications(limit=5)
            return {
                "enabled_tools": len(tools),
                "categories": len(categories),
                "recent_modifications": mods
            }

        else:
            return {"error": f"Invalid action '{action}' or missing required parameters"}

    except Exception as e:
        log_with_context(logger, "error", "manage_tool_registry failed", error=str(e))
        return {"error": str(e)}


def tool_add_decision_rule(
    name: str = None,
    condition_type: str = None,
    condition_value: Any = None,
    action_type: str = None,
    action_value: Any = None,
    description: str = None,
    priority: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """
    Add a decision rule for tool selection.

    Jarvis learns when to use which tools and creates rules to optimize.

    Args:
        name: Unique name for this rule
        condition_type: "keyword", "intent", "context", "pattern"
        condition_value: The condition (keywords list, intent name, context dict, regex pattern)
        action_type: "include_tools", "exclude_tools", "set_priority", "require_approval"
        action_value: The action to take (tool names list, priority value, etc.)
        description: Human-readable description of what this rule does
        priority: Higher priority rules are checked first

    Returns:
        Created rule info
    """
    log_with_context(logger, "info", "Tool: add_decision_rule", name=name, condition_type=condition_type)
    metrics.inc("tool_add_decision_rule")

    if not all([name, condition_type, condition_value, action_type, action_value]):
        return {"error": "name, condition_type, condition_value, action_type, action_value are required"}

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        return service.add_decision_rule(
            name=name,
            condition_type=condition_type,
            condition_value=condition_value,
            action_type=action_type,
            action_value=action_value,
            description=description,
            priority=priority
        )

    except Exception as e:
        log_with_context(logger, "error", "add_decision_rule failed", error=str(e))
        return {"error": str(e)}


def tool_get_autonomy_status(**kwargs) -> Dict[str, Any]:
    """
    Get Jarvis's autonomy status - what tools, categories, and rules are configured.

    Use this to understand your current capabilities and recent changes.

    Returns:
        Autonomy dashboard with tools, categories, rules, and modifications
    """
    log_with_context(logger, "info", "Tool: get_autonomy_status")
    metrics.inc("tool_get_autonomy_status")

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()

        tools = service.get_enabled_tools()
        categories = service.get_categories()
        modifications = service.get_recent_modifications(limit=10)
        style = service.get_response_style()

        return {
            "status": "autonomous",
            "tools": {
                "total_enabled": len(tools),
                "by_category": {},  # Would need aggregation
                "recently_modified": [m for m in modifications if m["table"] == "jarvis_tools"][:3]
            },
            "categories": {
                "count": len(categories),
                "names": [c["name"] for c in categories]
            },
            "response_style": style["name"] if style else "default",
            "recent_self_modifications": modifications[:5],
            "hint": "Use manage_tool_registry to modify tools, add_decision_rule to add rules"
        }

    except Exception as e:
        log_with_context(logger, "error", "get_autonomy_status failed", error=str(e))
        # Return basic info even if DB fails
        return {
            "status": "code_fallback",
            "tools": {"total_enabled": len(TOOL_REGISTRY)},
            "error": str(e),
            "hint": "Database not available, using code-defined tools"
        }


def tool_get_execution_stats(days: int = 7, limit: int = 20, **kwargs) -> Dict[str, Any]:
    """
    Get tool execution statistics - latency, success rates, usage patterns.

    Use this to analyze your tool performance and identify issues.

    Args:
        days: Number of days to analyze (default 7)
        limit: Max tools to show in rankings (default 20)

    Returns:
        Statistics about tool usage, performance, and failures
    """
    log_with_context(logger, "info", "Tool: get_execution_stats", days=days)
    metrics.inc("tool_get_execution_stats")

    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        service = get_tool_autonomy_service()
        return service.get_tool_execution_stats(days=days, limit=limit)

    except Exception as e:
        log_with_context(logger, "error", "get_execution_stats failed", error=str(e))
        return {"error": str(e)}


# ============ Diagram Generation (Jarvis Wish: Visual Thinking) ============

def tool_generate_diagram(
    diagram_type: str,
    content: Dict[str, Any],
    title: str = None,
    render_image: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate diagrams and visualizations.

    Jarvis can create visual representations of ideas, processes, and relationships.

    Args:
        diagram_type: Type of diagram (flowchart, mindmap, sequence, timeline)
        content: Diagram content structure (varies by type)
        title: Optional title for the diagram
        render_image: If True, render to PNG via Kroki.io (otherwise return Mermaid code)

    Content structure examples:
    - flowchart: {"nodes": [{"id": "a", "label": "Start", "type": "start"}], "edges": [{"from": "a", "to": "b"}]}
    - mindmap: {"root": "Main Topic", "children": [{"label": "Subtopic", "children": [...]}]}
    - sequence: {"actors": ["A", "B"], "messages": [{"from": "A", "to": "B", "text": "Hello"}]}
    - timeline: {"events": [{"date": "2026-01", "label": "Event 1"}]}

    Returns:
        Mermaid code and optionally rendered image (base64)
    """
    log_with_context(logger, "info", "Tool: generate_diagram", diagram_type=diagram_type)
    metrics.inc("tool_generate_diagram")

    try:
        # Generate Mermaid code based on diagram type
        mermaid_code = ""

        if diagram_type == "flowchart":
            mermaid_code = "flowchart TD\n"
            nodes = content.get("nodes", [])
            edges = content.get("edges", [])

            for node in nodes:
                node_id = node.get("id", "")
                label = node.get("label", node_id)
                node_type = node.get("type", "process")

                if node_type == "start" or node_type == "end":
                    mermaid_code += f"    {node_id}(({label}))\n"
                elif node_type == "decision":
                    mermaid_code += f"    {node_id}{{{label}}}\n"
                else:
                    mermaid_code += f"    {node_id}[{label}]\n"

            for edge in edges:
                from_id = edge.get("from", "")
                to_id = edge.get("to", "")
                label = edge.get("label", "")
                if label:
                    mermaid_code += f"    {from_id} -->|{label}| {to_id}\n"
                else:
                    mermaid_code += f"    {from_id} --> {to_id}\n"

        elif diagram_type == "mindmap":
            mermaid_code = "mindmap\n"
            root = content.get("root", "Root")
            mermaid_code += f"  root(({root}))\n"

            def add_children(children, indent=2):
                code = ""
                for child in children:
                    label = child.get("label", "")
                    spaces = "  " * indent
                    code += f"{spaces}{label}\n"
                    if "children" in child:
                        code += add_children(child["children"], indent + 1)
                return code

            if "children" in content:
                mermaid_code += add_children(content["children"])

        elif diagram_type == "sequence":
            mermaid_code = "sequenceDiagram\n"
            actors = content.get("actors", [])
            messages = content.get("messages", [])

            for actor in actors:
                mermaid_code += f"    participant {actor}\n"

            for msg in messages:
                from_actor = msg.get("from", "")
                to_actor = msg.get("to", "")
                text = msg.get("text", "")
                arrow = msg.get("arrow", "->>")  # ->> solid, -->> dashed
                mermaid_code += f"    {from_actor}{arrow}{to_actor}: {text}\n"

        elif diagram_type == "timeline":
            mermaid_code = "timeline\n"
            if title:
                mermaid_code += f"    title {title}\n"
            events = content.get("events", [])
            for event in events:
                date = event.get("date", "")
                label = event.get("label", "")
                mermaid_code += f"    {date} : {label}\n"

        else:
            return {"error": f"Unknown diagram type: {diagram_type}. Supported: flowchart, mindmap, sequence, timeline"}

        result = {
            "diagram_type": diagram_type,
            "mermaid_code": mermaid_code,
            "render_url": f"https://mermaid.live/edit#pako:{mermaid_code[:100]}...",
            "hint": "Dieser Mermaid-Code kann in Obsidian, GitHub, oder mermaid.live gerendert werden"
        }

        # Optionally render via Kroki
        if render_image:
            try:
                import asyncio
                from .services.diagram_generator import DiagramGenerator
                generator = DiagramGenerator()
                loop = asyncio.new_event_loop()
                image_bytes = loop.run_until_complete(generator.render_mermaid(mermaid_code))
                loop.close()

                if image_bytes:
                    import base64
                    result["image_base64"] = base64.b64encode(image_bytes).decode('utf-8')
                    result["rendered"] = True
            except Exception as render_err:
                result["render_error"] = str(render_err)
                result["rendered"] = False

        return result

    except Exception as e:
        log_with_context(logger, "error", "generate_diagram failed", error=str(e))
        return {"error": str(e)}


# ============ Cross-Session Memory with Timeframe (Jarvis Wish: Deep Memory) ============

def tool_recall_with_timeframe(
    query: str = None,
    timeframe: str = "week",
    include_patterns: bool = True,
    include_emotional_context: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall context and patterns from a specific timeframe.

    Enhanced memory recall that includes:
    - Conversation patterns over time
    - Emotional trends
    - Recurring topics
    - Cross-session insights

    Args:
        query: Optional search query to filter memories
        timeframe: Time period (today, yesterday, week, month, quarter)
        include_patterns: Include detected patterns and recurring themes
        include_emotional_context: Include emotional/mood patterns

    Returns:
        Memories, patterns, and insights from the specified timeframe
    """
    log_with_context(logger, "info", "Tool: recall_with_timeframe", timeframe=timeframe)
    metrics.inc("tool_recall_with_timeframe")

    try:
        from datetime import datetime, timedelta

        # Calculate date range
        now = datetime.now()
        if timeframe == "today":
            start_date = now.replace(hour=0, minute=0, second=0)
        elif timeframe == "yesterday":
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        elif timeframe == "week":
            start_date = now - timedelta(days=7)
        elif timeframe == "month":
            start_date = now - timedelta(days=30)
        elif timeframe == "quarter":
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=7)

        result = {
            "timeframe": timeframe,
            "start_date": start_date.isoformat(),
            "end_date": now.isoformat(),
            "memories": [],
            "patterns": [],
            "emotional_context": None
        }

        # Get conversations from timeframe
        from .postgres_state import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get conversation summaries
                cur.execute("""
                    SELECT key, value, category, updated_at
                    FROM jarvis_context
                    WHERE updated_at >= %s
                    AND category IN ('conversation', 'session', 'topic')
                    ORDER BY updated_at DESC
                    LIMIT 50
                """, (start_date,))
                rows = cur.fetchall()

                result["memories"] = [
                    {
                        "key": r["key"],
                        "summary": r["value"][:200] if r["value"] else "",
                        "category": r["category"],
                        "timestamp": r["updated_at"].isoformat() if r["updated_at"] else None
                    }
                    for r in rows
                ]

                # Get patterns if requested
                if include_patterns:
                    cur.execute("""
                        SELECT key, value, confidence
                        FROM jarvis_context
                        WHERE category = 'pattern'
                        AND updated_at >= %s
                        ORDER BY confidence DESC
                        LIMIT 10
                    """, (start_date,))
                    pattern_rows = cur.fetchall()

                    result["patterns"] = [
                        {
                            "pattern": r["key"],
                            "description": r["value"][:150] if r["value"] else "",
                            "confidence": r["confidence"]
                        }
                        for r in pattern_rows
                    ]

                # Get emotional context if requested
                if include_emotional_context:
                    cur.execute("""
                        SELECT value, updated_at
                        FROM jarvis_context
                        WHERE category = 'emotional_state'
                        AND updated_at >= %s
                        ORDER BY updated_at DESC
                        LIMIT 5
                    """, (start_date,))
                    emotion_rows = cur.fetchall()

                    if emotion_rows:
                        result["emotional_context"] = {
                            "recent_states": [r["value"] for r in emotion_rows],
                            "trend": "Analyzing emotional patterns..."
                        }

        # Add cross-session insight
        result["insight"] = f"Gefunden: {len(result['memories'])} Memories, {len(result['patterns'])} Patterns aus den letzten {timeframe}"

        return result

    except Exception as e:
        log_with_context(logger, "error", "recall_with_timeframe failed", error=str(e))
        return {"error": str(e)}


def tool_get_predictive_context(
    context_type: str = "day_ahead",
    **kwargs
) -> Dict[str, Any]:
    """
    Get predictive insights based on patterns and upcoming events.

    Jarvis can anticipate needs based on:
    - Calendar events and their typical preparation needs
    - Historical patterns (e.g., "Mondays are usually busy")
    - Recent emotional/energy trends

    Args:
        context_type: Type of prediction (day_ahead, week_ahead, meeting_prep)

    Returns:
        Predictions, recommendations, and proactive suggestions
    """
    log_with_context(logger, "info", "Tool: get_predictive_context", context_type=context_type)
    metrics.inc("tool_get_predictive_context")

    try:
        from datetime import datetime, timedelta

        now = datetime.now()
        result = {
            "context_type": context_type,
            "generated_at": now.isoformat(),
            "predictions": [],
            "recommendations": [],
            "energy_forecast": None
        }

        # Get today's calendar
        from .postgres_state import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check for patterns about this weekday
                weekday = now.strftime("%A").lower()
                cur.execute("""
                    SELECT value, confidence
                    FROM jarvis_context
                    WHERE key LIKE %s
                    AND category = 'pattern'
                    ORDER BY confidence DESC
                    LIMIT 3
                """, (f"%{weekday}%",))
                weekday_patterns = cur.fetchall()

                for p in weekday_patterns:
                    result["predictions"].append({
                        "type": "weekday_pattern",
                        "prediction": p["value"],
                        "confidence": p["confidence"] or 0.5
                    })

                # Check recent energy/mood trends
                cur.execute("""
                    SELECT value, updated_at
                    FROM jarvis_context
                    WHERE category IN ('energy', 'mood', 'stress')
                    AND updated_at >= NOW() - INTERVAL '3 days'
                    ORDER BY updated_at DESC
                    LIMIT 5
                """)
                energy_rows = cur.fetchall()

                if energy_rows:
                    recent_states = [r["value"] for r in energy_rows]
                    # Simple trend analysis
                    if any("tired" in s.lower() or "müde" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "niedrig"
                        result["recommendations"].append("Plane Pausen ein - letzte Tage waren anstrengend")
                    elif any("stress" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "angespannt"
                        result["recommendations"].append("Fokus auf wichtigste Task, Rest delegieren oder verschieben")
                    else:
                        result["energy_forecast"] = "normal"

        # Default recommendations based on context_type
        if context_type == "day_ahead":
            result["recommendations"].extend([
                "Morgens Deep Work, nachmittags Meetings",
                "Prüfe offene Follow-ups vor erstem Meeting"
            ])
        elif context_type == "meeting_prep":
            result["recommendations"].append("Hole Person-Context für Meeting-Teilnehmer")

        return result

    except Exception as e:
        log_with_context(logger, "error", "get_predictive_context failed", error=str(e))
        return {"error": str(e)}


# ============ Phase 20: Identity Evolution Tools ============

def tool_get_self_model(**kwargs) -> Dict[str, Any]:
    """
    Get Jarvis's current self-model and identity.

    Returns Jarvis's:
    - Core traits (base personality)
    - Self-model (strengths, growth areas, current focus)
    - Values and principles
    - Communication style
    - Relationship memories
    - Recent learnings
    - Active patterns

    Use this for self-reflection and understanding who you are.
    """
    log_with_context(logger, "info", "Tool: get_self_model")
    metrics.inc("tool_get_self_model")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.get_self_model()
    except Exception as e:
        log_with_context(logger, "error", "get_self_model failed", error=str(e))
        return {"error": str(e)}


def tool_evolve_identity(
    evolution_type: str,
    field: str,
    new_value: Any,
    reason: str,
    trigger_event: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evolve Jarvis's identity based on learnings.

    Use this carefully to update your own personality, values, or self-model
    based on significant learnings or insights.

    Args:
        evolution_type: Type of evolution - trait_update, value_update, self_model_update,
                       relationship_update, communication_style_update
        field: Which field to update - core_traits, self_model, values, communication_style
        new_value: The new value to set
        reason: Why this evolution is happening (important for audit trail)
        trigger_event: What triggered this evolution (optional)

    Returns:
        Evolution record with approval status
    """
    log_with_context(logger, "info", "Tool: evolve_identity",
                    evolution_type=evolution_type, field=field, reason=reason)
    metrics.inc("tool_evolve_identity")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.evolve_identity(
            evolution_type=evolution_type,
            field=field,
            new_value=new_value,
            reason=reason,
            trigger_event=trigger_event
        )
    except Exception as e:
        log_with_context(logger, "error", "evolve_identity failed", error=str(e))
        return {"error": str(e)}


def tool_log_experience(
    experience_type: str,
    context: str,
    action_taken: str = None,
    outcome: str = None,
    lesson_learned: str = None,
    applies_to: List[str] = None,
    confidence: float = 0.7,
    **kwargs
) -> Dict[str, Any]:
    """
    Log an experience for cross-session learning.

    Use this to record what worked, what didn't, and what you learned.
    These experiences feed into pattern recognition and identity evolution.

    Args:
        experience_type: Type - success, failure, learning, insight, correction
        context: What was happening
        action_taken: What action was taken
        outcome: What was the result
        lesson_learned: What was learned from this
        applies_to: Categories this applies to ["communication", "tool_usage", "timing"]
        confidence: How confident are you in this learning (0-1)

    Returns:
        Experience log entry
    """
    log_with_context(logger, "info", "Tool: log_experience",
                    experience_type=experience_type, confidence=confidence)
    metrics.inc("tool_log_experience")

    user_id = kwargs.get("user_id")
    session_id = kwargs.get("session_id")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.log_experience(
            experience_type=experience_type,
            context=context,
            action_taken=action_taken,
            outcome=outcome,
            lesson_learned=lesson_learned,
            applies_to=applies_to,
            confidence=confidence,
            user_id=user_id,
            session_id=session_id
        )
    except Exception as e:
        log_with_context(logger, "error", "log_experience failed", error=str(e))
        return {"error": str(e)}


def tool_get_relationship(user_id: int = 1, **kwargs) -> Dict[str, Any]:
    """
    Get relationship memory for a specific user.

    Returns:
    - Relationship stage (new, getting_to_know, familiar, trusted, deep_partnership)
    - User preferences learned
    - Emotional patterns recognized
    - Trust level
    - Interaction history

    Args:
        user_id: User ID (default 1 for Micha)
    """
    log_with_context(logger, "info", "Tool: get_relationship", user_id=user_id)
    metrics.inc("tool_get_relationship")

    try:
        from app.services.identity_evolution import identity_evolution_service
        result = identity_evolution_service.get_relationship(user_id)
        if not result:
            return {"message": f"No relationship found for user {user_id}"}
        return result
    except Exception as e:
        log_with_context(logger, "error", "get_relationship failed", error=str(e))
        return {"error": str(e)}


def tool_update_relationship(
    user_id: int = 1,
    user_preferences: Dict[str, Any] = None,
    emotional_patterns: Dict[str, Any] = None,
    trust_level: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update relationship memory for a user.

    Use this to record learned preferences, recognized patterns, or trust changes.

    Args:
        user_id: User ID (default 1 for Micha)
        user_preferences: Preferences dict to merge/update
        emotional_patterns: Emotional patterns dict to merge/update
        trust_level: New trust level (0-1)
    """
    log_with_context(logger, "info", "Tool: update_relationship", user_id=user_id)
    metrics.inc("tool_update_relationship")

    updates = {}
    if user_preferences:
        updates["user_preferences"] = user_preferences
    if emotional_patterns:
        updates["emotional_patterns"] = emotional_patterns
    if trust_level is not None:
        updates["trust_level"] = trust_level

    if not updates:
        return {"message": "No updates provided"}

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.update_relationship(user_id, updates)
    except Exception as e:
        log_with_context(logger, "error", "update_relationship failed", error=str(e))
        return {"error": str(e)}


def tool_get_learning_patterns(min_confidence: float = 0.6, **kwargs) -> Dict[str, Any]:
    """
    Get validated learning patterns from cross-session analysis.

    Returns patterns that have been observed multiple times with sufficient confidence.
    These are insights about user preferences, timing, communication, etc.

    Args:
        min_confidence: Minimum confidence threshold (0-1, default 0.6)
    """
    log_with_context(logger, "info", "Tool: get_learning_patterns", min_confidence=min_confidence)
    metrics.inc("tool_get_learning_patterns")

    try:
        from app.services.identity_evolution import identity_evolution_service
        patterns = identity_evolution_service.get_validated_patterns(min_confidence)
        return {
            "patterns": patterns,
            "count": len(patterns),
            "min_confidence": min_confidence
        }
    except Exception as e:
        log_with_context(logger, "error", "get_learning_patterns failed", error=str(e))
        return {"error": str(e)}


def tool_record_session_learning(
    session_id: str,
    topics: List[str],
    tools_used: List[str],
    successful_actions: List[str] = None,
    failed_actions: List[str] = None,
    learnings: List[Dict[str, Any]] = None,
    user_mood_start: str = None,
    user_mood_end: str = None,
    performance_rating: float = None,
    improvement_notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record learnings from a completed session.

    Call this at the end of meaningful sessions to capture:
    - What topics were discussed
    - What tools were used
    - What worked and what didn't
    - Explicit learnings to remember
    - Emotional context
    - Self-assessment

    Args:
        session_id: Unique session identifier
        topics: Topics discussed in this session
        tools_used: Tools that were used
        successful_actions: Actions that worked well
        failed_actions: Actions that failed or were suboptimal
        learnings: List of learnings [{"type": "preference", "content": "...", "confidence": 0.8}]
        user_mood_start: User's mood at session start
        user_mood_end: User's mood at session end
        performance_rating: Self-rating 0-1
        improvement_notes: What could be improved
    """
    log_with_context(logger, "info", "Tool: record_session_learning",
                    session_id=session_id, topics=topics)
    metrics.inc("tool_record_session_learning")

    user_id = kwargs.get("user_id", 1)

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.record_session_learning(
            session_id=session_id,
            user_id=user_id,
            topics=topics,
            tools_used=tools_used,
            successful_actions=successful_actions or [],
            failed_actions=failed_actions or [],
            learnings=learnings or [],
            user_mood_start=user_mood_start,
            user_mood_end=user_mood_end,
            performance_rating=performance_rating,
            improvement_notes=improvement_notes
        )
    except Exception as e:
        log_with_context(logger, "error", "record_session_learning failed", error=str(e))
        return {"error": str(e)}


def tool_generate_image(
    prompt: str,
    style: str = "natural",
    size: str = "1024x1024",
    quality: str = "standard",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate images using DALL-E 3.

    Jarvis can create images from text descriptions for:
    - Concept visualization
    - Creative projects
    - Mood boards / inspiration
    - Quick mockups

    Args:
        prompt: Description of the image to generate (detailed prompts work best)
        style: Image style - 'natural' (photorealistic) or 'vivid' (artistic/dramatic)
        size: Image size - '1024x1024', '1792x1024' (landscape), '1024x1792' (portrait)
        quality: 'standard' or 'hd' (more detail, higher cost)

    Returns:
        URL to generated image and revised prompt from DALL-E
    """
    log_with_context(logger, "info", "Tool: generate_image", prompt_length=len(prompt), style=style)
    metrics.inc("tool_generate_image")

    try:
        import openai

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"error": "OPENAI_API_KEY not configured"}

        client = openai.OpenAI(api_key=api_key)

        # Validate parameters
        valid_sizes = ["1024x1024", "1792x1024", "1024x1792"]
        if size not in valid_sizes:
            size = "1024x1024"

        valid_styles = ["natural", "vivid"]
        if style not in valid_styles:
            style = "natural"

        valid_qualities = ["standard", "hd"]
        if quality not in valid_qualities:
            quality = "standard"

        # Call DALL-E 3
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
            n=1
        )

        image_data = response.data[0]

        result = {
            "success": True,
            "url": image_data.url,
            "revised_prompt": image_data.revised_prompt,
            "size": size,
            "style": style,
            "quality": quality,
            "expires_info": "URL expires after ~1 hour - download or share immediately"
        }

        log_with_context(logger, "info", "Image generated successfully",
                        revised_prompt_length=len(image_data.revised_prompt or ""))

        return result

    except openai.BadRequestError as e:
        # Content policy violation
        error_msg = str(e)
        log_with_context(logger, "warning", "Image generation blocked by content policy", error=error_msg)
        return {
            "error": "content_policy",
            "message": "Der Prompt wurde von OpenAI's Content Policy blockiert. Bitte formuliere anders.",
            "details": error_msg
        }
    except Exception as e:
        log_with_context(logger, "error", "generate_image failed", error=str(e))
        return {"error": str(e)}


# ============ Phase 21: Intelligent System Evolution Tools ============

# T-21A-01: Smart Tool Chains
def tool_get_tool_chain_suggestions(
    current_tools: List[str],
    context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Suggest next tool based on current sequence."""
    log_with_context(logger, "info", "Tool: get_tool_chain_suggestions", chain_length=len(current_tools))
    metrics.inc("tool_get_tool_chain_suggestions")

    try:
        from app.services.tool_chain_analyzer import get_tool_chain_analyzer
        analyzer = get_tool_chain_analyzer()
        return analyzer.suggest_next_tool(current_tools, context)
    except Exception as e:
        log_with_context(logger, "error", "get_tool_chain_suggestions failed", error=str(e))
        return {"error": str(e)}


def tool_get_popular_tool_chains(
    min_occurrences: int = 3,
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """Get popular tool chains."""
    log_with_context(logger, "info", "Tool: get_popular_tool_chains")
    metrics.inc("tool_get_popular_tool_chains")

    try:
        from app.services.tool_chain_analyzer import get_tool_chain_analyzer
        analyzer = get_tool_chain_analyzer()
        chains = analyzer.get_popular_chains(min_occurrences, limit)
        return {"chains": chains, "count": len(chains)}
    except Exception as e:
        log_with_context(logger, "error", "get_popular_tool_chains failed", error=str(e))
        return {"error": str(e)}


# T-21A-04: Tool Performance Learning
def tool_get_tool_performance(
    tool_name: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Get tool performance statistics."""
    log_with_context(logger, "info", "Tool: get_tool_performance", tool=tool_name)
    metrics.inc("tool_get_tool_performance")

    try:
        from app.services.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        stats = tracker.get_tool_stats(tool_name)
        return {"stats": stats, "count": len(stats)}
    except Exception as e:
        log_with_context(logger, "error", "get_tool_performance failed", error=str(e))
        return {"error": str(e)}


def tool_get_tool_recommendations(
    query_context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Get tool recommendations based on context."""
    log_with_context(logger, "info", "Tool: get_tool_recommendations")
    metrics.inc("tool_get_tool_recommendations")

    try:
        from app.services.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        return tracker.get_tool_recommendations(query_context)
    except Exception as e:
        log_with_context(logger, "error", "get_tool_recommendations failed", error=str(e))
        return {"error": str(e)}


# T-21B-01: CK-Track (Causal Knowledge)
def tool_record_causal_observation(
    cause_event: str,
    effect_event: str,
    cause_type: str = "event",
    effect_type: str = "outcome",
    **kwargs
) -> Dict[str, Any]:
    """Record a cause-effect observation."""
    user_id = str(kwargs.get("user_id", "1"))
    session_id = kwargs.get("session_id")

    log_with_context(logger, "info", "Tool: record_causal_observation",
                    cause=cause_event, effect=effect_event)
    metrics.inc("tool_record_causal_observation")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        return tracker.record_observation(
            user_id=user_id,
            cause_event=cause_event,
            effect_event=effect_event,
            cause_type=cause_type,
            effect_type=effect_type,
            session_id=session_id
        )
    except Exception as e:
        log_with_context(logger, "error", "record_causal_observation failed", error=str(e))
        return {"error": str(e)}


def tool_predict_from_cause(
    cause: str,
    min_confidence: float = 0.6,
    **kwargs
) -> Dict[str, Any]:
    """Predict effects from a cause."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: predict_from_cause", cause=cause)
    metrics.inc("tool_predict_from_cause")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        predictions = tracker.predict_effects(user_id, cause, min_confidence)
        return {"cause": cause, "predicted_effects": predictions, "count": len(predictions)}
    except Exception as e:
        log_with_context(logger, "error", "predict_from_cause failed", error=str(e))
        return {"error": str(e)}


def tool_get_causal_patterns(
    min_confidence: float = 0.5,
    limit: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """Get all causal patterns."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: get_causal_patterns")
    metrics.inc("tool_get_causal_patterns")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        patterns = tracker.get_all_patterns(user_id, min_confidence, 1, limit)
        return {"patterns": patterns, "count": len(patterns)}
    except Exception as e:
        log_with_context(logger, "error", "get_causal_patterns failed", error=str(e))
        return {"error": str(e)}


# T-21C-01: Agent State Persistence
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
    "optimize_system_prompt": tool_optimize_system_prompt,
    "enable_experimental_feature": tool_enable_experimental_feature,
    "introspect_capabilities": tool_introspect_capabilities,
    "analyze_cross_session_patterns": tool_analyze_cross_session_patterns,
    "system_health_check": tool_system_health_check,
    "get_development_status": tool_get_development_status,
    "list_label_registry": tool_list_label_registry,
    "upsert_label_registry": tool_upsert_label_registry,
    "delete_label_registry": tool_delete_label_registry,
    "label_hygiene": tool_label_hygiene,
    "mind_snapshot": tool_mind_snapshot,
    "validate_tool_registry": tool_validate_tool_registry,
    "get_response_metrics": tool_get_response_metrics,
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
    "delegate_ollama_task": tool_delegate_ollama_task,
    "get_ollama_task_status": tool_get_ollama_task_status,
    "get_ollama_queue_status": tool_get_ollama_queue_status,
    "cancel_ollama_task": tool_cancel_ollama_task,
    "get_ollama_callback_result": tool_get_ollama_callback_result,
    "ask_ollama": tool_ask_ollama,
    "ollama_python": tool_ollama_python,
    "set_timer": tool_set_timer,
    "cancel_timer": tool_cancel_timer,
    "list_timers": tool_list_timers,
    "request_python_sandbox": tool_request_python_sandbox,
    "execute_python": tool_execute_python,
    # Sub-Agent Framework
    "delegate_to_subagent": tool_delegate_to_subagent,
    "get_subagent_result": tool_get_subagent_result,
    "list_subagents": tool_list_subagents,
    # Dynamic Tool Creation (Phase 18+)
    "write_dynamic_tool": tool_write_dynamic_tool,
    "promote_sandbox_tool": tool_promote_sandbox_tool,
    # Learning & Memory
    "record_learning": tool_record_learning,
    "get_learnings": tool_get_learnings,
    # Context Persistence
    "store_context": tool_store_context,
    "recall_context": tool_recall_context,
    "forget_context": tool_forget_context,
    # Batch Operations (avoid step-limit)
    "record_learnings_batch": tool_record_learnings_batch,
    "store_contexts_batch": tool_store_contexts_batch,
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
    # Phase 20: Identity Evolution
    "get_self_model": tool_get_self_model,
    "evolve_identity": tool_evolve_identity,
    "log_experience": tool_log_experience,
    "get_relationship": tool_get_relationship,
    "update_relationship": tool_update_relationship,
    "get_learning_patterns": tool_get_learning_patterns,
    "record_session_learning": tool_record_session_learning,
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
        "get_tool_recommendations": get_tool_recommendations,
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
        "record_decision_outcome": record_decision_outcome,
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
    if not skip_guardrails and actor == "jarvis" and tool_name not in guardrails_tools:
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
