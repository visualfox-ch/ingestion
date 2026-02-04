"""
Jarvis Tool Definitions
Tools that the agent can use to accomplish tasks.
"""
from typing import Dict, Any, List, Callable
import requests
import os
import shutil
import hashlib
import json
import time
import difflib
from datetime import datetime, timedelta

from .embed import embed_texts
from .observability import get_logger, log_with_context, metrics
from .langfuse_integration import observe, langfuse_context
from .errors import (
    JarvisException, ErrorCode, wrap_external_error,
    internal_error, qdrant_unavailable
)

logger = get_logger("jarvis.tools")


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
                    "description": "Which namespace to search: 'work_projektil', 'private', or 'all'",
                    "default": "work_projektil"
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
                    "description": "Which namespace: 'work_projektil' or 'private'",
                    "default": "work_projektil"
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
                    "default": "work_projektil"
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
                    "default": "work_projektil"
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
        "description": """Read a file directly from allowed project directories. Use for inspecting code, configs, or documentation.

ALLOWED PATHS:
- /brain/system/docker/ - Docker configs (docker-compose.yml)
- /brain/system/ingestion/app/ - Jarvis source code (*.py)
- /brain/system/policies/ - System prompts, policies (*.md)
- /brain/system/prompts/ - Persona configs, modes (*.json)
- /brain/projects/ - Project files
- /brain/notes/ - Notes

EXAMPLES:
- docker-compose.yml → /brain/system/docker/docker-compose.yml
- Jarvis code → /brain/system/ingestion/app/agent.py
- System prompt → /brain/system/policies/JARVIS_SYSTEM_PROMPT.md

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
    }
]


# ============ Tool Implementations ============

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

        payload = {
            "vector": q_vec,
            "limit": limit * 2 if recency_days else limit,  # fetch more if filtering
            "with_payload": True,
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

            results.append({
                "score": hit.get("score"),
                "text": pl.get("text", "")[:500],  # Truncate for context
                "source_path": pl.get("source_path"),
                "doc_type": pl.get("doc_type"),
                "channel": pl.get("channel"),
                "label": pl.get("label"),
                "event_ts": pl.get("event_ts") or pl.get("ingest_ts"),
            })

            if len(results) >= limit:
                break

        return results

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
    namespace: str = "work_projektil",
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

    # Handle 'all' namespace
    namespaces = ["work_projektil", "private"] if namespace == "all" else [namespace]

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

        # Search comms collection (chats)
        try:
            collections_searched += 1
            results = _search_qdrant(
                query=expanded_query,
                collection=f"jarvis_{ns}_comms",
                limit=limit,
                recency_days=recency_days
            )
            all_results.extend(results)
        except JarvisException as e:
            collections_failed += 1
            errors.append({"collection": f"jarvis_{ns}_comms", "error": e.error.message})
            log_with_context(logger, "warning", "Partial search failure",
                           collection=f"jarvis_{ns}_comms", error=e.error.message)

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
        "query": query
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
    namespace: str = "work_projektil",
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

    results = _search_qdrant(
        query=expanded_query,
        collection=f"jarvis_{namespace}",
        limit=limit,
        filters=filters,
        recency_days=recency_days
    )

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
    namespace: str = "work_projektil",
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

    results = _search_qdrant(
        query=expanded_query,
        collection=f"jarvis_{namespace}_comms",
        limit=limit,
        filters=filters,
        recency_days=recency_days
    )

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
    namespace: str = "work_projektil",
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

    if include_emails:
        email_results = _search_qdrant(
            query="email message communication update",  # Generic query
            collection=f"jarvis_{namespace}",
            limit=10,
            filters={"doc_type": "email"},
            recency_days=days
        )
        results["emails"] = email_results
        results["email_count"] = len(email_results)

    if include_chats:
        chat_results = _search_qdrant(
            query="chat conversation message discussion",
            collection=f"jarvis_{namespace}_comms",
            limit=10,
            recency_days=days
        )
        results["chats"] = chat_results
        results["chat_count"] = len(chat_results)

    return results


def tool_web_search(
    query: str,
    num_results: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Search the web using DuckDuckGo.

    Raises:
        JarvisException: On network or API errors with structured error info
    """
    log_with_context(logger, "info", "Tool: web_search", query=query)
    metrics.inc("tool_web_search")

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

        return {
            "query": query,
            "results": results,
            "count": len(results)
        }
    except ImportError:
        raise JarvisException(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Web search not available (duckduckgo-search not installed)",
            status_code=503,
            details={"query": query},
            recoverable=False,
            hint="Web search dependency is missing"
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

        # Check for rate limiting
        if "rate" in error_msg.lower() or "429" in error_msg:
            raise JarvisException(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="Web search rate limited",
                status_code=429,
                details={"query": query},
                recoverable=True,
                retry_after=60,
                hint="DuckDuckGo rate limit - wait before retrying"
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
    namespace: str = "work_projektil",
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
    for ctx in history:
        formatted_history.append({
            "date": ctx["start_time"][:10] if ctx.get("start_time") else "unknown",
            "summary": ctx.get("conversation_summary", ""),
            "topics": ctx.get("key_topics", []),
            "pending": ctx.get("pending_actions", []),
            "mood": ctx.get("emotional_indicators", {}).get("dominant", "neutral")
        })

    return {
        "conversations": formatted_history,
        "conversation_count": len(formatted_history),
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

    # Store the hint as a fact for future reference
    from . import memory_store
    hint_fact = f"[Proactive Hint] {observation}"
    memory_store.add_fact(hint_fact, category="insight", confidence=conf_score)

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
    "/Volumes/BRAIN/projects/",    # Project files
    "/Volumes/BRAIN/notes/",       # Notes
    # Docker paths (inside container)
    "/brain/system/",              # Main system folder
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

    if running_in_docker and file_path.startswith("/Volumes/BRAIN/"):
        return file_path.replace("/Volumes/BRAIN/", f"{brain_root}/")
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

    # Check if file exists
    if not os.path.isfile(file_path):
        return {
            "error": "Datei nicht gefunden",
            "file_path": file_path
        }

    # Limit max_lines
    max_lines = min(max_lines, 500)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip())

        # Get file info
        stat = os.stat(file_path)
        file_size = stat.st_size
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Determine file type
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        return {
            "success": True,
            "file_path": file_path,
            "content": "\n".join(lines),
            "lines_read": len(lines),
            "truncated": len(lines) >= max_lines,
            "file_size": file_size,
            "modified": modified,
            "extension": ext
        }

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
    # Proactive Initiative
    "proactive_hint": tool_proactive_hint,
    # Phase 18.3: Self-Optimization Tools
    "optimize_system_prompt": tool_optimize_system_prompt,
    "enable_experimental_feature": tool_enable_experimental_feature,
    "introspect_capabilities": tool_introspect_capabilities,
    "analyze_cross_session_patterns": tool_analyze_cross_session_patterns,
    "system_health_check": tool_system_health_check,
}


def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    trace_id: str = None,
    actor: str = "jarvis",
    reason: str = None
) -> Dict[str, Any]:
    """Execute a tool by name with given input.

    Gate A: All executions are logged to tool_audit table for traceability.
    """
    import time
    start_time = time.time()

    if tool_name not in TOOL_REGISTRY:
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

    try:
        result = TOOL_REGISTRY[tool_name](**tool_input)
        duration_ms = int((time.time() - start_time) * 1000)

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
    """Get tool definitions for Anthropic API"""
    return TOOL_DEFINITIONS
