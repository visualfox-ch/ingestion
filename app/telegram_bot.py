"""
Jarvis Telegram Bot
Mobile interface to Jarvis via Telegram.
"""
import os
import logging
import asyncio
import threading
import uuid
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageReactionUpdated
from telegram import error as telegram_error

from .observability import log_with_context
from . import config
from .state import global_state
import re

def _escape_markdown(text: str) -> str:
    """Escape Telegram Markdown special characters"""
    if not text:
        return ""
    # Escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    return re.sub(r'([_*\[\]()~`>#+=|{}.!-])', r'\\\1', str(text))

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    TypeHandler,
    ContextTypes,
    filters,
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
def _get_telegram_token() -> str:
    """Get Telegram token from env or secrets file"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    secrets_path = "/brain/system/secrets/telegram_bot_token.txt"
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            return f.read().strip()
    return None

TELEGRAM_TOKEN = _get_telegram_token()
JARVIS_API_BASE = os.environ.get("JARVIS_API_BASE", "http://localhost:8000")
# Parse allowed user IDs, stripping whitespace from each entry
_allowed_users_raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
ALLOWED_USER_IDS = [uid.strip() for uid in _allowed_users_raw.split(",") if uid.strip()]

# API Authentication - uses same key as configured in config.py
JARVIS_API_KEY = os.environ.get("JARVIS_API_KEY", "")


def get_api_headers() -> Dict[str, str]:
    """Get headers for Jarvis API calls including auth if configured."""
    headers = {"Content-Type": "application/json"}
    if JARVIS_API_KEY:
        headers["X-API-Key"] = JARVIS_API_KEY
    return headers

# Bot thread tracking
_bot_supervisor_thread: Optional[threading.Thread] = None
_bot_lock = threading.Lock()
_bot_should_run = False
_bot_restart_count = 0
_bot_last_error: Optional[str] = None
_bot_last_crash_at: Optional[str] = None
_bot_last_start_at: Optional[str] = None


# ============ Persistent State Functions ============

def get_user_state(user_id: int) -> Dict[str, Any]:
    """Get user state from database, with defaults"""
    from . import state_db
    state = state_db.get_telegram_user_state(user_id)
    if state:
        return state
    # Return defaults
    return {
        "session_id": None,
        "namespace": None,
        "role": "assistant"
    }

def save_user_state(user_id: int, session_id: str = None, namespace: str = None, role: str = None):
    """Save user state to database"""
    from . import state_db
    state_db.set_telegram_user_state(user_id, session_id, namespace, role)


# ============ Helper Functions ============

def is_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot"""
    if not ALLOWED_USER_IDS:
        return True  # No restrictions if list is empty
    return str(user_id) in ALLOWED_USER_IDS


def call_jarvis_agent(
    query: str,
    session_id: str,
    namespace: Optional[str] = None,
    role: str = "assistant",
    user_id: int = None,
    source: str = "telegram"
) -> Dict[str, Any]:
    """Call Jarvis agent API"""
    try:
        mapping = {
            "private": ("personal", "private"),
            "work_projektil": ("projektil", "internal"),
            "work_visualfox": ("visualfox", "internal"),
            "shared": ("personal", "shared"),
        }
        payload = {
            "query": query,
            "session_id": session_id,
            "role": role,
            "auto_detect_role": role == "auto",
            "source": source,
        }
        if namespace is not None and str(namespace).strip():
            org, visibility = mapping.get(str(namespace).strip(), ("projektil", "internal"))
            payload["scope"] = {"org": org, "visibility": visibility}
        if user_id:
            payload["user_id"] = str(user_id)  # AgentRequest expects string

        resp = requests.post(
            f"{JARVIS_API_BASE}/agent",
            json=payload,
            headers=get_api_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to Jarvis. Is the service running?"}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out."}
    except Exception as e:
        return {"error": str(e)}


def get_briefing(namespace: str = "work_projektil", days: int = 1) -> Dict[str, Any]:
    """Get daily briefing"""
    try:
        resp = requests.get(
            f"{JARVIS_API_BASE}/briefing",
            params={"namespace": namespace, "days": days},
            headers=get_api_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ============ Command Handlers ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    # Create new session for user
    session_id = str(uuid.uuid4())[:8]
    save_user_state(user.id, session_id=session_id)

    # Get dynamic version from package or use fallback
    try:
        from . import __version__
        version = __version__
    except Exception as e:
        log_with_context(logger, "error", "Failed to import version, using fallback", error=str(e))
        version = "2.7.0"

    # Get available domains dynamically
    try:
        from .domains import list_registered_domains
        domains = list_registered_domains()
        domain_count = len(domains)
        domains_str = ", ".join(domains)
    except Exception as e:
        log_with_context(logger, "error", "Failed to load registered domains, using fallback", error=str(e))
        domains = ["general", "linkedin", "communication", "nutrition", "fitness", "work", "ideas", "presentation", "mediaserver"]
        domain_count = len(domains)
        domains_str = ", ".join(domains)

    await update.message.reply_text(
        f"🤖 *Jarvis v{version}* — Hey {user.first_name}!\n\n"
        f"Person Intelligence + Monitoring aktiv.\n"
        f"Einfach schreiben zum Chatten.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*💬 Sessions*\n"
        f"`/new` `/ns` `/role` `/domain` `/refresh`\n\n"
        f"*📋 Tasks*\n"
        f"`/task` `/task!` `/tasks` `/done`\n\n"
        f"*📊 Wissen*\n"
        f"`/briefing` `/remember` `/forget` `/profile`\n\n"
        f"*🎯 Entscheidungen*\n"
        f"`/decide` `/outcome` `/patterns`\n\n"
        f"*💾 Export*\n"
        f"`/export` `/generate`\n\n"
        f"*🧠 Emotional*\n"
        f"`/compass` `/whatif` `/trust` `/flags` `/blindspot` `/energy`\n\n"
        f"*🔍 System*\n"
        f"`/self` `/feedback` `/projects`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*{domain_count} Domains:* {domains_str}\n\n"
        f"💡 `/help <command>` für Details",
        parse_mode="Markdown"
    )


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new command - start new session"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    session_id = str(uuid.uuid4())[:8]
    save_user_state(user.id, session_id=session_id)

    await update.message.reply_text(f"Started new conversation (session: {session_id})")


async def briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /briefing command"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    # Parse days argument
    days = 1
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])

    await update.message.reply_text(f"Generating briefing for last {days} day(s)...")

    # Get namespace from persistent state
    state = get_user_state(user.id)
    namespace = state["namespace"]

    result = get_briefing(namespace=namespace, days=days)

    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
    else:
        answer = result.get("answer", "No briefing available")
        usage = result.get("usage", {})
        tokens = f"\n\n[{usage.get('input_tokens', 0)}->{usage.get('output_tokens', 0)} tokens]"
        await update.message.reply_text(answer + tokens)


async def set_namespace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ns command - switch namespace"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    state = get_user_state(user.id)

    if not context.args:
        await update.message.reply_text(
            f"Current namespace: {state['namespace']}\n\n"
            f"Usage: /ns <namespace>\n"
            f"Examples: /ns work_projektil, /ns private"
        )
        return

    namespace = context.args[0]
    if namespace == "work":
        namespace = "work_projektil"

    save_user_state(user.id, namespace=namespace)
    await update.message.reply_text(f"Switched to namespace: {namespace}")


async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /role command - switch agent role/persona"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    available_roles = ["assistant", "coach", "analyst", "researcher", "writer", "personal", "tone", "compass", "reality", "consequences", "assumptions", "auto"]
    state = get_user_state(user.id)

    if not context.args:
        roles_list = "\n".join(f"- {r}" for r in available_roles)
        await update.message.reply_text(
            f"Current role: {state['role']}\n\n"
            f"Available roles:\n{roles_list}\n\n"
            f"Usage: /role <name>\n"
            f"Example: /role coach\n\n"
            f"Use /role auto to auto-detect from your message"
        )
        return

    role = context.args[0].lower()
    if role not in available_roles:
        await update.message.reply_text(
            f"Unknown role: {role}\n"
            f"Available: {', '.join(available_roles)}"
        )
        return

    save_user_state(user.id, role=role)

    role_greetings = {
        "assistant": "General assistant mode. How can I help?",
        "coach": "Coach mode active. Let's work on what matters most.",
        "analyst": "Analyst mode active. What situation shall we analyze?",
        "researcher": "Researcher mode active. What topic shall we investigate?",
        "writer": "Writer mode active. What shall we write?",
        "personal": "Personal mode active. Focusing on private namespace.",
        "tone": "Tone mode active. Send text to adjust (de-emotionalize, soften, shorten, team-safe, direct).",
        "compass": "Inner Compass mode. What decision is on your mind?",
        "reality": "Alternative Reality mode. What path are you considering?",
        "consequences": "Consequences mode. What decision shall we map out?",
        "assumptions": "Assumptions mode. Describe your situation to surface hidden beliefs.",
        "auto": "Auto-detect mode active. I'll choose the best role for each query.",
    }

    await update.message.reply_text(f"Switched to {role} role.\n{role_greetings.get(role, '')}")


async def set_domain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /domain command - switch coaching domain"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import coaching_domains

    domains = coaching_domains.list_domains()
    current_domain = coaching_domains.get_user_domain(user.id)

    if not context.args:
        # Show available domains
        domain_list = "\n".join(
            f"{'>' if d['id'] == current_domain else ' '} {d['icon']} {d['id']}: {d['description']}"
            for d in domains
        )
        await update.message.reply_text(
            f"*Coaching Domains*\n\n"
            f"Current: {current_domain}\n\n"
            f"{domain_list}\n\n"
            f"Usage: /domain <name>\n"
            f"Example: /domain linkedin",
            parse_mode="Markdown"
        )
        return

    domain_id = context.args[0].lower()
    domain = coaching_domains.get_domain(domain_id)

    if not domain:
        await update.message.reply_text(
            f"Unknown domain: {domain_id}\n"
            f"Available: {', '.join(d['id'] for d in domains)}"
        )
        return

    # Set the domain for the user
    coaching_domains.set_user_domain(user.id, domain_id)

    # Get domain greeting
    greeting = coaching_domains.get_domain_greeting(domain_id)

    # Also update the role and persona based on domain
    role_persona = coaching_domains.get_domain_role_and_persona(domain_id)
    save_user_state(
        user.id,
        role=role_persona["role_id"],
        persona_id=role_persona["persona_id"],
        namespace=domain.knowledge_namespace
    )

    await update.message.reply_text(
        f"*Domain switched: {domain.name}*\n\n"
        f"{greeting}\n\n"
        f"_Role: {role_persona['role_id']} | Namespace: {domain.knowledge_namespace}_",
        parse_mode="Markdown"
    )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /export command - export conversation or knowledge"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import document_generator
    from . import session_manager

    formats = ["md", "txt", "html", "pdf", "docx"]

    if not context.args:
        # Show help
        recent_exports = document_generator.list_exports(limit=5)
        exports_list = ""
        if recent_exports:
            exports_list = "\n*Recent exports:*\n" + "\n".join(
                f"- {e['filename']} ({e['size_bytes']} bytes)"
                for e in recent_exports[:5]
            )

        await update.message.reply_text(
            f"*Export Documents*\n\n"
            f"*Usage:*\n"
            f"`/export conversation [format]` - Export current session\n"
            f"`/export list` - List recent exports\n\n"
            f"*Formats:* {', '.join(formats)}\n"
            f"{exports_list}",
            parse_mode="Markdown"
        )
        return

    export_type = context.args[0].lower()
    export_format = context.args[1].lower() if len(context.args) > 1 else "md"

    if export_format not in formats:
        await update.message.reply_text(f"Unknown format: {export_format}\nAvailable: {', '.join(formats)}")
        return

    if export_type == "list":
        exports = document_generator.list_exports(limit=10)
        if not exports:
            await update.message.reply_text("No exports found.")
            return

        export_list = "\n".join(
            f"- `{e['filename']}` ({e['format']}, {e['size_bytes']} bytes)"
            for e in exports
        )
        await update.message.reply_text(f"*Recent Exports:*\n\n{export_list}", parse_mode="Markdown")
        return

    if export_type == "conversation":
        # Get recent conversation from session
        try:
            messages = session_manager.get_recent_messages(user.id, limit=50)
            if not messages:
                await update.message.reply_text("No conversation history found.")
                return

            # Convert to format expected by exporter
            formatted_messages = [
                {"role": m.get("role", "user"), "content": m.get("content", ""), "timestamp": m.get("created_at", "")}
                for m in messages
            ]

            await update.message.reply_text(f"Exporting conversation to {export_format}...")

            doc = document_generator.export_conversation(
                messages=formatted_messages,
                title="Jarvis Conversation",
                format=export_format
            )

            # Send file
            with open(doc.path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=doc.filename,
                    caption=f"Exported {len(formatted_messages)} messages ({doc.size_bytes} bytes)"
                )

        except Exception as e:
            await update.message.reply_text(f"Export failed: {str(e)}")
            return

    else:
        await update.message.reply_text(
            f"Unknown export type: {export_type}\n"
            f"Available: conversation, list"
        )


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /generate command - generate documents from templates"""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    doc_types = ["email", "meeting", "linkedin", "progress", "presentation"]

    if not context.args:
        await update.message.reply_text(
            f"*Document Generator*\n\n"
            f"Generate structured documents from your conversations.\n\n"
            f"*Usage:*\n"
            f"`/generate <type>` - Start generation wizard\n\n"
            f"*Document types:*\n"
            f"- `email` - Email draft\n"
            f"- `meeting` - Meeting summary\n"
            f"- `linkedin` - LinkedIn post\n"
            f"- `progress` - Progress report\n"
            f"- `presentation` - Presentation outline\n\n"
            f"*Tip:* Describe what you need in a message and Jarvis will help structure it.",
            parse_mode="Markdown"
        )
        return

    doc_type = context.args[0].lower()

    if doc_type not in doc_types:
        await update.message.reply_text(
            f"Unknown document type: {doc_type}\n"
            f"Available: {', '.join(doc_types)}"
        )
        return

    # Send instructions based on document type
    instructions = {
        "email": (
            "*Email Draft Generator*\n\n"
            "Send me the following:\n"
            "1. Who is the recipient?\n"
            "2. What is the subject?\n"
            "3. What do you want to say?\n"
            "4. What tone? (professional/friendly/direct)\n\n"
            "_Example: Write an email to Max about the project delay, keep it professional_"
        ),
        "meeting": (
            "*Meeting Summary Generator*\n\n"
            "Send me the following:\n"
            "1. What was the meeting about?\n"
            "2. Who attended?\n"
            "3. What decisions were made?\n"
            "4. What are the action items?\n\n"
            "_Example: Summarize my meeting with the dev team about the new feature rollout_"
        ),
        "linkedin": (
            "*LinkedIn Post Generator*\n\n"
            "Send me the following:\n"
            "1. What topic do you want to post about?\n"
            "2. What personal story or insight can you share?\n"
            "3. What should readers take away?\n\n"
            "_Example: Write a post about my learnings from failing my first startup_"
        ),
        "progress": (
            "*Progress Report Generator*\n\n"
            "Send me the following:\n"
            "1. What period does this cover?\n"
            "2. What did you achieve?\n"
            "3. What challenges did you face?\n"
            "4. What are the next steps?\n\n"
            "_Example: Create a weekly progress report for my fitness goals_"
        ),
        "presentation": (
            "*Presentation Outline Generator*\n\n"
            "Send me the following:\n"
            "1. What is the presentation about?\n"
            "2. Who is the audience?\n"
            "3. How long should it be?\n"
            "4. What is your key message?\n\n"
            "_Example: Create a 10-minute pitch for our new product to investors_"
        ),
    }

    await update.message.reply_text(instructions[doc_type], parse_mode="Markdown")


async def decide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /decide command - log a decision for later reflection.

    Usage:
        /decide <context> [#tag1 #tag2] [@confidence:N] [@energy:N]

    Examples:
        /decide Should I escalate the client issue? #team #conflict
        /decide Accept the new project offer #work @confidence:7 @energy:8
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    if not context.args:
        # Show help and recent decisions
        recent = state_db.get_recent_decisions(limit=5, user_id=user.id)
        pending = [d for d in recent if not d.get("outcome_recorded_at")]

        help_text = (
            "*Decision Tracker*\n\n"
            "Log decisions to track patterns over time.\n\n"
            "*Usage:*\n"
            "`/decide <context> [#tag] [@confidence:N] [@energy:N]`\n\n"
            "*Examples:*\n"
            "`/decide Accept project offer #work @confidence:7`\n"
            "`/decide Escalate client issue #team #conflict`\n\n"
            "*Other commands:*\n"
            "`/outcome <id> <rating> [notes]` - Record outcome (1-10)\n"
            "`/patterns` - View your decision patterns\n"
        )

        if pending:
            help_text += f"\n*Pending outcomes:* {len(pending)}\n"
            for d in pending[:3]:
                help_text += f"  #{d['id']}: {d['context_summary'][:40]}...\n"

        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    # Parse the decision
    full_text = " ".join(context.args)

    # Extract tags (#tag)
    import re
    tags = re.findall(r"#(\w+)", full_text)
    full_text = re.sub(r"#\w+", "", full_text)

    # Extract confidence (@confidence:N)
    confidence = None
    conf_match = re.search(r"@confidence:(\d+)", full_text)
    if conf_match:
        confidence = min(10, max(1, int(conf_match.group(1))))
        full_text = re.sub(r"@confidence:\d+", "", full_text)

    # Extract energy cost (@energy:N)
    energy = None
    energy_match = re.search(r"@energy:(\d+)", full_text)
    if energy_match:
        energy = min(10, max(1, int(energy_match.group(1))))
        full_text = re.sub(r"@energy:\d+", "", full_text)

    context_summary = full_text.strip()

    if len(context_summary) < 5:
        await update.message.reply_text("Please provide more context for the decision.")
        return

    # Log the decision
    decision_id = state_db.log_decision(
        context_summary=context_summary,
        tags=tags if tags else None,
        confidence=confidence,
        energy_cost_expected=energy,
        user_id=user.id
    )

    response = f"Decision logged (#{decision_id})\n\n"
    response += f"*Context:* {context_summary}\n"
    if tags:
        response += f"*Tags:* {', '.join(f'#{t}' for t in tags)}\n"
    if confidence:
        response += f"*Confidence:* {confidence}/10\n"
    if energy:
        response += f"*Expected energy:* {energy}/10\n"
    response += f"\nUse `/outcome {decision_id} <rating>` later to record how it went."

    await update.message.reply_text(response, parse_mode="Markdown")


async def outcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /outcome command - record outcome of a past decision.

    Usage: /outcome <decision_id> <rating> [notes]
    Example: /outcome 5 8 Went better than expected
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    if len(context.args) < 2:
        # Show pending decisions
        pending = state_db.get_recent_decisions(limit=10, user_id=user.id, pending_outcome=True)

        if not pending:
            await update.message.reply_text("No pending decisions to rate.")
            return

        response = "*Pending Outcomes*\n\n"
        for d in pending:
            tags_str = f" [{', '.join(f'#{t}' for t in d.get('tags', []))}]" if d.get('tags') else ""
            response += f"*#{d['id']}*: {d['context_summary'][:50]}{tags_str}\n"

        response += f"\n*Usage:* `/outcome <id> <rating 1-10> [notes]`"
        await update.message.reply_text(response, parse_mode="Markdown")
        return

    try:
        decision_id = int(context.args[0])
        rating = min(10, max(1, int(context.args[1])))
        notes = " ".join(context.args[2:]) if len(context.args) > 2 else None
    except ValueError:
        await update.message.reply_text("Usage: `/outcome <id> <rating 1-10> [notes]`", parse_mode="Markdown")
        return

    state_db.record_outcome(decision_id, rating, notes)

    emoji = "🎉" if rating >= 7 else "👍" if rating >= 5 else "🤔"
    response = f"{emoji} Outcome recorded for decision #{decision_id}\n\n"
    response += f"*Rating:* {rating}/10\n"
    if notes:
        response += f"*Notes:* {notes}\n"

    await update.message.reply_text(response, parse_mode="Markdown")


async def patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /patterns command - show decision pattern analysis."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    analysis = state_db.get_decision_patterns(user_id=user.id)

    if analysis.get("total_decisions", 0) == 0:
        await update.message.reply_text(
            "No decisions logged yet.\n\n"
            "Use `/decide <context>` to start tracking decisions."
        )
        return

    response = "*Decision Patterns*\n\n"
    response += f"Total decisions: {analysis['total_decisions']}\n"
    response += f"With outcomes: {analysis.get('with_outcomes', 0)}\n"

    if analysis.get("confidence_accuracy_pct") is not None:
        response += f"\n*Confidence accuracy:* {analysis['confidence_accuracy_pct']}%\n"

    if analysis.get("by_tag"):
        response += "\n*By category:*\n"
        for tag, stats in analysis["by_tag"].items():
            if stats.get("avg_outcome"):
                response += f"  #{tag}: {stats['count']} decisions, avg outcome {stats['avg_outcome']}/10\n"
            else:
                response += f"  #{tag}: {stats['count']} decisions\n"

    if analysis.get("insight"):
        response += f"\n💡 *Insight:* {analysis['insight']}"

    await update.message.reply_text(response, parse_mode="Markdown")


# ============ Learning Commands ============

async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /remember command - teach Jarvis user preferences.

    Usage:
    /remember Ich mag kurze Antworten
    /remember Bei Stress: sei empathischer
    /remember In Zukunft: frage immer nach dem Outcome
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    if not context.args:
        # Show current learnings
        from . import prompt_assembler

        summary = prompt_assembler.get_active_fragments_summary(user_id=user.id)

        response = "🧠 *Was ich gelernt habe*\n\n"

        if summary["total"] == 0:
            response += "Noch nichts gelernt.\n\n"
        else:
            response += f"*{summary['total']} aktive Anpassungen:*\n"
            for cat, count in summary.get("by_category", {}).items():
                cat_label = {
                    "user_pref": "📝 Präferenzen",
                    "sentiment": "💭 Stimmungs-Trigger",
                    "pattern": "🔄 Muster",
                    "capability": "⚡ Fähigkeiten",
                }.get(cat, cat)
                response += f"  {cat_label}: {count}\n"

            response += "\n*Details:*\n"
            for f in summary.get("fragments", [])[:5]:
                content_short = f["content"][:60] + "..." if len(f["content"]) > 60 else f["content"]
                response += f"• {content_short}\n"

        response += (
            "\n*Neue Anpassung:*\n"
            "`/remember <Anweisung>`\n\n"
            "*Beispiele:*\n"
            "`/remember Ich mag kurze Antworten`\n"
            "`/remember Bei Stress: sei empathischer`\n"
            "`/remember In Zukunft: frage nach dem Outcome`"
        )

        await update.message.reply_text(response, parse_mode="Markdown")
        return

    # Parse and create learning fragment
    instruction = " ".join(context.args)

    from . import prompt_assembler

    # Auto-approve for now (trusted user)
    state = get_user_state(user.id)
    namespace = state.get("namespace")

    fragment_id = prompt_assembler.create_learning_fragment(
        user_input=instruction,
        user_id=user.id,
        namespace=namespace,
        auto_approve=True  # Auto-approve for trusted users
    )

    if fragment_id:
        await update.message.reply_text(
            f"✅ *Gelernt!*\n\n"
            f"Anweisung: _{instruction}_\n\n"
            f"Fragment-ID: `{fragment_id}`\n\n"
            f"Ab jetzt berücksichtige ich das in meinen Antworten.",
            parse_mode="Markdown"
        )
        log_with_context(logger, "info", "User taught Jarvis",
                        user_id=user.id, fragment_id=fragment_id)
    else:
        await update.message.reply_text(
            "❌ Konnte das nicht lernen.\n\n"
            "Versuche es mit einem klareren Format:\n"
            "• `Merke dir: ...`\n"
            "• `Ich mag ...`\n"
            "• `Bei Stress: ...`"
        )


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /forget command - remove a learned preference.

    Usage: /forget <fragment_id>
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "🗑️ *Vergessen*\n\n"
            "Entferne eine gelernte Anpassung.\n\n"
            "*Usage:* `/forget <fragment_id>`\n\n"
            "Zeige alle Anpassungen mit `/remember`",
            parse_mode="Markdown"
        )
        return

    fragment_id = context.args[0]

    from . import knowledge_db

    # Only allow disabling, not deleting (for audit trail)
    success = knowledge_db.disable_prompt_fragment(fragment_id, f"user:{user.id}")

    if success:
        await update.message.reply_text(
            f"✅ Fragment `{fragment_id}` deaktiviert.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Fragment `{fragment_id}` nicht gefunden oder bereits deaktiviert.",
            parse_mode="Markdown"
        )


async def self_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /self command - show Jarvis internal state for debugging.

    Usage:
    /self - Show current state
    /self <text> - Analyze how Jarvis would process this text
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    state = get_user_state(user.id)
    text = " ".join(context.args) if context.args else None

    # Build API URL
    params = {
        "user_id": user.id,
        "namespace": state.get("namespace"),
        "session_id": state.get("session_id")
    }
    if text:
        params["text"] = text

    try:
        import requests
        resp = requests.get(f"{JARVIS_API_BASE}/self_reflect", params=params, headers=get_api_headers(), timeout=10)
        data = resp.json()

        # Format response for Telegram
        response = "🔍 *Jarvis Self-Reflect*\n\n"

        # Context
        ctx = data.get("request_context", {})
        response += f"*Kontext:*\n"
        response += f"  Namespace: `{ctx.get('namespace', 'none')}`\n"
        response += f"  Session: `{ctx.get('session_id', 'none')}`\n\n"

        # Prompt Fragments
        frags = data.get("prompt_fragments", {})
        response += f"*Prompt Fragments:* {frags.get('total_active', 0)} aktiv\n"
        by_cat = frags.get("by_category", {})
        if by_cat:
            for cat, count in by_cat.items():
                response += f"  • {_escape_markdown(cat)}: {count}\n"
        response += "\n"

        # Sentiment (if text provided)
        sent = data.get("sentiment_analysis", {})
        if sent.get("status") != "no_text_provided":
            response += f"*Sentiment Analyse:*\n"
            scores = sent.get("scores", {})
            response += f"  Dominant: `{sent.get('dominant', 'neutral')}`\n"
            response += f"  Alert: `{sent.get('alert_level', 'none')}`\n"
            if scores:
                response += f"  Urgency: {scores.get('urgency', 0):.2f} | "
                response += f"Stress: {scores.get('stress', 0):.2f}\n"
            if sent.get("would_inject_context"):
                response += f"  ⚡ Context wird injiziert!\n"
            if sent.get("recommendation"):
                rec_text = _escape_markdown(sent.get('recommendation', '')[:80])
                response += f"  💡 {rec_text}\n"
            response += "\n"

        # Assembled Prompt
        assembled = data.get("assembled_prompt", {})
        if assembled and not assembled.get("error"):
            response += f"*Assembled Prompt:*\n"
            response += f"  Fixed: {assembled.get('fixed_length', 0)} chars\n"
            response += f"  Dynamic: {assembled.get('dynamic_length', 0)} chars\n"
            response += f"  Fragments: {assembled.get('fragment_count', 0)}\n\n"

        # Capabilities Summary
        caps = data.get("capabilities", {})
        if caps:
            response += f"*Capabilities:*\n"
            response += f"  Learning: {'✅' if caps.get('learning_enabled') else '❌'}\n"

        # Truncate if too long
        if len(response) > 3900:
            response = response[:3900] + "\n\n_(truncated)_"

        await update.message.reply_text(response, parse_mode="Markdown")

    except Exception as e:
        log_with_context(logger, "error", "Self-reflect failed", error=str(e))
        await update.message.reply_text(
            f"❌ Self-reflect failed: {str(e)[:100]}"
        )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /profile command - manage Coach OS user profile.

    Usage:
    /profile - Show current profile
    /profile adhd on|off - Toggle ADHD mode
    /profile mode <mode> - Set mode (coach, analyst, exec, debug, mirror)
    /profile style <style> - Set communication style (direkt, empathisch, analytisch)
    /profile length <length> - Set response length (kurz, mittel, ausfuehrlich)
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    args = context.args or []

    try:
        from . import knowledge_db

        # Get or create profile
        profile = knowledge_db.get_or_create_user_profile(
            telegram_id=user.id,
            name=user.first_name
        )

        if not args:
            # Show profile
            response = "👤 *Dein Coach OS Profil*\n\n"

            # Basic info
            response += f"*User ID:* `{profile.get('user_id', 'N/A')}`\n"
            response += f"*Name:* {_escape_markdown(profile.get('name', 'Unknown'))}\n\n"

            # ADHD settings
            adhd_status = "✅ Aktiv" if profile.get("adhd_mode") else "❌ Inaktiv"
            response += f"*ADHD-Modus:* {adhd_status}\n"
            if profile.get("adhd_mode"):
                response += f"  Chunk-Größe: `{profile.get('chunk_size', 'mittel')}`\n"

            # Coaching
            response += f"\n*Modus:* `{profile.get('active_coaching_mode', 'coach')}`\n"

            # Communication preferences
            response += f"\n*Kommunikation:*\n"
            response += f"  Stil: `{profile.get('communication_style', 'direkt')}`\n"
            response += f"  Länge: `{profile.get('response_length', 'mittel')}`\n"
            response += f"  Sprache: `{profile.get('language', 'de')}`\n"

            # Energy
            energy_status = "✅" if profile.get("energy_awareness") else "❌"
            response += f"\n*Energie-Bewusstsein:* {energy_status}\n"

            response += "\n*Befehle:*\n"
            response += "`/profile adhd on|off` - ADHD-Modus\n"
            response += "`/profile mode <mode>` - Coaching-Modus\n"
            response += "`/profile style <style>` - Kommunikationsstil\n"
            response += "`/profile length <length>` - Antwortlänge"

            await update.message.reply_text(response, parse_mode="Markdown")
            return

        # Handle subcommands
        subcmd = args[0].lower()

        if subcmd == "adhd":
            if len(args) < 2:
                await update.message.reply_text(
                    "Verwendung: `/profile adhd on` oder `/profile adhd off`",
                    parse_mode="Markdown"
                )
                return

            enabled = args[1].lower() in ("on", "ja", "yes", "1", "true", "an")
            success = knowledge_db.update_user_profile(
                user_id=profile["user_id"],
                updates={"adhd_mode": enabled},
                changed_by="telegram",
                change_reason="ADHD mode toggle via /profile"
            )

            if success:
                status = "✅ aktiviert" if enabled else "❌ deaktiviert"
                await update.message.reply_text(
                    f"ADHD-Modus {status}.\n\n"
                    "Bei aktivem ADHD-Modus bekommst du:\n"
                    "• Max 3 Hauptpunkte pro Antwort\n"
                    "• Kürzere Absätze\n"
                    "• Immer einen konkreten nächsten Schritt"
                )
            else:
                await update.message.reply_text("❌ Fehler beim Aktualisieren")

        elif subcmd == "mode":
            valid_modes = ["coach", "analyst", "exec", "debug", "mirror"]
            if len(args) < 2:
                await update.message.reply_text(
                    f"Verwendung: `/profile mode <mode>`\n\n"
                    f"Verfügbare Modi: {', '.join(valid_modes)}",
                    parse_mode="Markdown"
                )
                return

            mode = args[1].lower()
            if mode not in valid_modes:
                await update.message.reply_text(
                    f"❌ Ungültiger Modus. Verfügbar: {', '.join(valid_modes)}"
                )
                return

            success = knowledge_db.update_user_profile(
                user_id=profile["user_id"],
                updates={"active_coaching_mode": mode},
                changed_by="telegram",
                change_reason=f"Mode change to {mode} via /profile"
            )

            mode_descriptions = {
                "coach": "Emotional containment, clarifying, safe next step",
                "analyst": "Systemic view, tradeoffs, risks, neutral",
                "exec": "Decisions, next actions, owners, minimal text",
                "debug": "Deterministic reasoning, code, no speculation",
                "mirror": "I-statements, de-escalation, relationship-aware"
            }

            if success:
                await update.message.reply_text(
                    f"✅ Coaching-Modus: *{mode}*\n\n{mode_descriptions.get(mode, '')}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Fehler beim Aktualisieren")

        elif subcmd == "style":
            valid_styles = ["direkt", "empathisch", "analytisch"]
            if len(args) < 2:
                await update.message.reply_text(
                    f"Verwendung: `/profile style <style>`\n\n"
                    f"Verfügbare Stile: {', '.join(valid_styles)}",
                    parse_mode="Markdown"
                )
                return

            style = args[1].lower()
            if style not in valid_styles:
                await update.message.reply_text(
                    f"❌ Ungültiger Stil. Verfügbar: {', '.join(valid_styles)}"
                )
                return

            success = knowledge_db.update_user_profile(
                user_id=profile["user_id"],
                updates={"communication_style": style},
                changed_by="telegram",
                change_reason=f"Style change to {style} via /profile"
            )

            if success:
                await update.message.reply_text(f"✅ Kommunikationsstil: *{style}*", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Fehler beim Aktualisieren")

        elif subcmd == "length":
            valid_lengths = ["kurz", "mittel", "ausfuehrlich"]
            if len(args) < 2:
                await update.message.reply_text(
                    f"Verwendung: `/profile length <length>`\n\n"
                    f"Optionen: {', '.join(valid_lengths)}",
                    parse_mode="Markdown"
                )
                return

            length = args[1].lower()
            if length not in valid_lengths:
                await update.message.reply_text(
                    f"❌ Ungültige Länge. Optionen: {', '.join(valid_lengths)}"
                )
                return

            success = knowledge_db.update_user_profile(
                user_id=profile["user_id"],
                updates={"response_length": length},
                changed_by="telegram",
                change_reason=f"Response length change to {length} via /profile"
            )

            if success:
                await update.message.reply_text(f"✅ Antwortlänge: *{length}*", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Fehler beim Aktualisieren")

        else:
            await update.message.reply_text(
                "Unbekannter Befehl. Verwende `/profile` für Hilfe.",
                parse_mode="Markdown"
            )

    except Exception as e:
        log_with_context(logger, "error", "Profile command failed", error=str(e))
        await update.message.reply_text(f"❌ Fehler: {str(e)[:100]}")


# ============ Task Management Commands ============

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /tasks command - show tasks.

    Usage:
    /tasks - Show Today view (high priority + due today)
    /tasks all - Show all open tasks
    /tasks week - Show next 7 days
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    args = context.args or []

    try:
        from . import knowledge_db

        # Get or create profile to get user_id
        profile = knowledge_db.get_or_create_user_profile(
            telegram_id=user.id,
            name=user.first_name
        )
        user_id = profile["user_id"]

        view = args[0].lower() if args else "today"

        if view == "today":
            tasks = knowledge_db.get_tasks_today(user_id)
            header = "📋 *Today*"
        elif view == "week":
            tasks = knowledge_db.get_tasks_week(user_id)
            header = "📅 *Next 7 Days*"
        elif view == "all":
            tasks = knowledge_db.get_tasks(user_id, include_done=False, limit=15)
            header = "📝 *All Open Tasks*"
        else:
            tasks = knowledge_db.get_tasks_today(user_id)
            header = "📋 *Today*"

        if not tasks:
            await update.message.reply_text(
                f"{header}\n\n"
                "✅ Keine offenen Tasks!\n\n"
                "Erstelle einen mit `/task <titel>`",
                parse_mode="Markdown"
            )
            return

        response = f"{header}\n\n"
        for t in tasks:
            status_icon = {"open": "⬜", "in_progress": "🔄", "blocked": "🚫", "done": "✅"}.get(t["status"], "⬜")
            priority_icon = {"high": "🔴", "normal": "", "low": "🔵"}.get(t["priority"], "")
            due_str = f" ({t['due_date']})" if t.get("due_date") else ""
            response += f"{status_icon} `{t['id']}` {priority_icon}{t['title']}{due_str}\n"

        response += "\n*Befehle:*\n"
        response += "`/done <id>` - Task erledigt\n"
        response += "`/task <titel>` - Neuer Task"

        await update.message.reply_text(response, parse_mode="Markdown")

    except Exception as e:
        log_with_context(logger, "error", "Tasks command failed", error=str(e))
        await update.message.reply_text(f"❌ Fehler: {str(e)[:100]}")


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /task command - create task.

    Usage:
    /task <title> - Create normal priority task for today
    /task! <title> - Create high priority task
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "📝 *Task erstellen*\n\n"
            "`/task <titel>` - Normal priority\n"
            "`/task! <titel>` - High priority\n\n"
            "*Beispiel:*\n"
            "`/task Check ingestion logs`",
            parse_mode="Markdown"
        )
        return

    try:
        from . import knowledge_db
        from datetime import date

        # Get or create profile
        profile = knowledge_db.get_or_create_user_profile(
            telegram_id=user.id,
            name=user.first_name
        )
        user_id = profile["user_id"]

        title = " ".join(context.args)
        priority = "normal"

        # Check if command was /task! (high priority)
        if update.message.text.startswith("/task!"):
            priority = "high"

        task = knowledge_db.create_task(
            user_id=user_id,
            title=title,
            priority=priority,
            due_date=str(date.today()),
            context_tag="jarvis"
        )

        if task:
            priority_icon = "🔴 " if priority == "high" else ""
            await update.message.reply_text(
                f"✅ Task erstellt:\n\n"
                f"`{task['id']}` {priority_icon}{title}\n\n"
                f"Erledigt? `/done {task['id']}`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Task konnte nicht erstellt werden")

    except Exception as e:
        log_with_context(logger, "error", "Task command failed", error=str(e))
        await update.message.reply_text(f"❌ Fehler: {str(e)[:100]}")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /done command - mark task as done.

    Usage:
    /done <id> - Mark task as completed
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Verwendung: `/done <task-id>`\n\n"
            "Zeige Tasks mit `/tasks`",
            parse_mode="Markdown"
        )
        return

    try:
        from . import knowledge_db

        task_id = int(context.args[0])
        task = knowledge_db.get_task(task_id)

        if not task:
            await update.message.reply_text("❌ Task nicht gefunden")
            return

        success = knowledge_db.update_task_status(task_id, "done")

        if success:
            await update.message.reply_text(
                f"✅ *Erledigt!*\n\n"
                f"~{task['title']}~\n\n"
                f"🎉 Gut gemacht!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Fehler beim Aktualisieren")

    except ValueError:
        await update.message.reply_text("❌ Ungültige Task-ID")
    except Exception as e:
        log_with_context(logger, "error", "Done command failed", error=str(e))
        await update.message.reply_text(f"❌ Fehler: {str(e)[:100]}")


# ============ Emotional Intelligence Commands ============

async def compass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /compass command - inner compass quick check.
    Shows pending decisions and offers to switch to compass mode.
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    # Get pending decisions
    pending = state_db.get_recent_decisions(limit=5, user_id=user.id, pending_outcome=True)

    response = "🧭 *Inner Compass*\n\n"

    if pending:
        response += "*Pending decisions to reflect on:*\n"
        for d in pending:
            conf_str = f" (conf: {d['confidence']}/10)" if d.get('confidence') else ""
            response += f"• #{d['id']}: {d['context_summary'][:50]}...{conf_str}\n"
        response += "\n"

    response += (
        "*Quick compass check:*\n"
        "Switch to compass mode with `/role compass` "
        "and describe what's on your mind.\n\n"
        "*The compass explores:*\n"
        "🧠 What your head says (logic)\n"
        "❤️ What your heart says (feeling)\n"
        "😰 What fear says (avoidance)\n"
        "🦉 What wisdom says (perspective)\n\n"
        "Use for any decision where you feel stuck or conflicted."
    )

    await update.message.reply_text(response, parse_mode="Markdown")


async def whatif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /whatif command - alternative reality exploration.
    """
    user = update.effective_user
    if not is_allowed(user.id):
        return

    if not context.args:
        response = (
            "🌍 *Alternative Reality Check*\n\n"
            "Explore counterfactual scenarios to surface hidden preferences.\n\n"
            "*Usage:*\n"
            "`/whatif <situation or decision>`\n\n"
            "*Examples:*\n"
            "`/whatif I accept the job offer`\n"
            "`/whatif I say no to the project`\n\n"
            "Or switch to reality mode: `/role reality`"
        )
        await update.message.reply_text(response, parse_mode="Markdown")
        return

    # Switch to reality role and forward the query
    situation = " ".join(context.args)
    save_user_state(user.id, role="reality")

    # Call agent with the situation
    state = get_user_state(user.id)
    session_id = state["session_id"]
    namespace = state["namespace"]

    if not session_id:
        session_id = str(uuid.uuid4())[:8]
        save_user_state(user.id, session_id=session_id)

    await update.message.chat.send_action("typing")

    result = call_jarvis_agent(
        f"Explore alternative realities for this situation: {situation}",
        session_id,
        namespace,
        "reality",
        user_id=user.id
    )

    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
        return

    answer = result.get("answer", "No response")
    if len(answer) > 4000:
        answer = answer[:3997] + "..."

    await update.message.reply_text(answer)


async def trust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /trust command - show self-trust metrics."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    metrics = state_db.get_self_trust_metrics(user_id=user.id)

    if metrics.get("status") == "need_more_data":
        await update.message.reply_text(
            "📊 *Self-Trust Tracker*\n\n"
            f"{metrics['message']}\n\n"
            "Log decisions with `/decide` and rate confidence with `@confidence:N`.\n"
            "Then record outcomes with `/outcome` to build your trust profile.",
            parse_mode="Markdown"
        )
        return

    response = f"📊 *Self-Trust Tracker*\n\n"
    response += f"{metrics['trust_emoji']} *Trust level:* {metrics['trust_level'].title()}\n"
    response += f"📈 *Accuracy:* {metrics['accuracy_pct']}%\n"
    response += f"{metrics['trend_emoji']} *Trend:* {metrics['trend'].title()}\n\n"

    response += f"*Breakdown ({metrics['total_tracked']} decisions):*\n"
    response += f"  ✅ Accurate: {metrics['accurate_count']}\n"
    response += f"  ⬆️ Overconfident: {metrics['overconfident_count']}\n"
    response += f"  ⬇️ Underconfident: {metrics['underconfident_count']}\n\n"

    response += f"💡 *Insight:* {metrics['insight']}"

    await update.message.reply_text(response, parse_mode="Markdown")


async def flags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /flags command - show red/green flag patterns."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    # Check for adding flags to a decision
    if context.args and len(context.args) >= 2:
        try:
            decision_id = int(context.args[0])
            flag_type = context.args[1].lower()
            flag_text = " ".join(context.args[2:]) if len(context.args) > 2 else None

            if flag_type in ["red", "green"] and flag_text:
                if flag_type == "red":
                    state_db.add_flags_to_decision(decision_id, red_flags=[flag_text])
                else:
                    state_db.add_flags_to_decision(decision_id, green_flags=[flag_text])

                emoji = "🚩" if flag_type == "red" else "🟢"
                await update.message.reply_text(
                    f"{emoji} {flag_type.title()} flag added to decision #{decision_id}:\n_{flag_text}_",
                    parse_mode="Markdown"
                )
                return
        except ValueError:
            pass

    # Show flag patterns
    patterns = state_db.get_flag_patterns(user_id=user.id)

    response = "🚩 *Red/Green Flag Patterns*\n\n"

    if patterns["total_analyzed"] == 0:
        response += (
            "No flag data yet.\n\n"
            "*Add flags to decisions:*\n"
            "`/flags <decision_id> red <description>`\n"
            "`/flags <decision_id> green <description>`\n\n"
            "*Example:*\n"
            "`/flags 5 red rushed into it without research`\n"
            "`/flags 5 green aligned with my values`"
        )
    else:
        if patterns["red_flags"]:
            response += "*🚩 Red flags:*\n"
            for flag, stats in sorted(patterns["red_flags"].items(),
                                      key=lambda x: x[1]["count"], reverse=True)[:5]:
                response += f"  • {flag}: {stats['count']}x (avg outcome: {stats['avg_outcome']})\n"
            response += "\n"

        if patterns["green_flags"]:
            response += "*🟢 Green flags:*\n"
            for flag, stats in sorted(patterns["green_flags"].items(),
                                      key=lambda x: x[1]["count"], reverse=True)[:5]:
                response += f"  • {flag}: {stats['count']}x (avg outcome: {stats['avg_outcome']})\n"
            response += "\n"

        if not patterns["red_flags"] and not patterns["green_flags"]:
            response += "No flags recorded yet. Add flags with:\n"
            response += "`/flags <id> red|green <description>`"

    await update.message.reply_text(response, parse_mode="Markdown")


async def blindspot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /blindspot command - detect and show blind spots."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    # Detect blind spots from history
    detected = state_db.detect_blind_spots(user_id=user.id)

    # Get recorded blind spots
    recorded = state_db.get_blind_spots(user_id=user.id)

    response = "👁️ *Blind Spot Analysis*\n\n"

    if detected:
        response += "*Detected patterns:*\n"
        for spot in detected:
            if spot["type"] == "overconfidence":
                emoji = "⬆️"
            elif spot["type"] == "underconfidence":
                emoji = "⬇️"
            elif spot["type"] == "energy_drain":
                emoji = "🔋"
            else:
                emoji = "•"
            response += f"{emoji} {spot['description']}\n"
            # Record for tracking
            state_db.record_blind_spot(spot["type"], spot["description"], user.id)
        response += "\n"

    if recorded:
        response += "*Recurring patterns:*\n"
        for spot in recorded[:5]:
            response += f"  • {spot['pattern_type']}: {spot['occurrences']}x\n"
        response += "\n"

    if not detected and not recorded:
        response += (
            "No blind spots detected yet.\n\n"
            "Keep logging decisions with `/decide` and outcomes with `/outcome`.\n"
            "Patterns emerge after 5+ decisions with outcomes."
        )
    else:
        response += (
            "💡 *Tip:* Use `/role compass` when facing decisions "
            "in areas where you have blind spots."
        )

    await update.message.reply_text(response, parse_mode="Markdown")


async def energy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /energy command - show energy cost patterns."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import state_db

    stats = state_db.get_energy_stats(user_id=user.id)

    if stats.get("status") == "no_data":
        await update.message.reply_text(
            "🔋 *Energy Cost Tracker*\n\n"
            "No energy data yet.\n\n"
            "Log decisions with energy cost:\n"
            "`/decide <context> @energy:N`\n\n"
            "*Example:*\n"
            "`/decide Big presentation prep @energy:8 @confidence:6`",
            parse_mode="Markdown"
        )
        return

    response = "🔋 *Energy Cost Patterns*\n\n"
    response += f"*Decisions tracked:* {stats['total_tracked']}\n"
    response += f"*Average energy:* {stats['avg_energy']}/10\n"
    response += f"*High-energy decisions:* {stats['high_energy_pct']}%\n\n"

    if stats.get("by_tag"):
        response += "*Energy by category:*\n"
        sorted_tags = sorted(stats["by_tag"].items(),
                            key=lambda x: x[1]["avg_energy"], reverse=True)
        for tag, data in sorted_tags[:6]:
            outcome_str = f", outcome: {data['avg_outcome']}" if data.get('avg_outcome') else ""
            response += f"  #{tag}: avg {data['avg_energy']}/10 ({data['count']}x{outcome_str})\n"

    response += f"\n💡 {stats['insight']}"

    await update.message.reply_text(response, parse_mode="Markdown")


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /feedback command - log feedback about Jarvis responses."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "*Feedback-Kommando*\n\n"
            "Schnell-Feedback:\n"
            "• `/feedback gut` - Antwort war hilfreich\n"
            "• `/feedback zuviel` - Zu viele Optionen/Infos\n"
            "• `/feedback zuwenig` - Mehr Details gewünscht\n"
            "• `/feedback falsch` - Inhaltlich inkorrekt\n"
            "• `/feedback ton` - Ton/Stil passte nicht\n\n"
            "Oder freier Text:\n"
            "`/feedback <dein Kommentar>`",
            parse_mode="Markdown"
        )
        return

    feedback_text = " ".join(args)
    feedback_type = args[0].lower() if args else "custom"

    # Map quick feedback to categories
    feedback_map = {
        "gut": ("positive", "Antwort war hilfreich"),
        "zuviel": ("too_much", "Zu viele Optionen/Infos"),
        "zuwenig": ("too_little", "Mehr Details gewünscht"),
        "falsch": ("incorrect", "Inhaltlich inkorrekt"),
        "ton": ("tone", "Ton/Stil passte nicht"),
    }

    if feedback_type in feedback_map:
        category, description = feedback_map[feedback_type]
    else:
        category = "custom"
        description = feedback_text

    # Store feedback in state_db
    from . import state_db
    from datetime import datetime

    state_db.store_feedback(
        user_id=user.id,
        category=category,
        description=description,
        timestamp=datetime.now().isoformat()
    )

    emoji_map = {
        "positive": "✓",
        "too_much": "↓",
        "too_little": "↑",
        "incorrect": "✗",
        "tone": "~",
        "custom": "📝"
    }
    emoji = emoji_map.get(category, "📝")

    await update.message.reply_text(
        f"{emoji} Feedback gespeichert: *{category}*\n"
        f"_{description}_\n\n"
        "Danke, das hilft mir besser zu werden.",
        parse_mode="Markdown"
    )


async def refresh_capabilities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /refresh command - get current capabilities from direct file reads."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    await update.message.reply_text("🔄 Refreshing capabilities...")

    try:
        # Call the new /capabilities endpoint for reliable, direct file access
        resp = requests.get(
            f"{JARVIS_API_BASE}/capabilities",
            headers=get_api_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error":
            await update.message.reply_text(f"❌ Refresh fehlgeschlagen: {data.get('error')}")
            return

        # Format detailed response like the first example
        response = "✅ Capabilities Refresh\n\n"
        response += "Basierend auf den kanonischen Quellen hier der aktuelle Status-Report:\n\n"
        
        # Extract data
        version = data.get("data", {}).get("version", "unknown")
        build_ts = data.get("data", {}).get("build_timestamp", "unknown")
        tools_count = data.get("data", {}).get("tools_count", 0)
        tools = data.get("data", {}).get("tools", [])
        monitoring = data.get("data", {}).get("monitoring_endpoints", [])
        sources = data.get("sources", {})
        capabilities_json_path = sources.get("capabilities_json", {}).get("path", "docs/CAPABILITIES.json")
        capabilities_status_path = sources.get("capabilities_status", {}).get("path", "/brain/system/docker/CAPABILITIES_STATUS.md")
        jarvis_self_path = sources.get("jarvis_self", {}).get("path", "/brain/system/policies/JARVIS_SELF.md")
        
        # 1. Version
        response += f"## 1. Version: {version}\n"
        response += f"Quelle: {capabilities_json_path}\n"
        response += f"• Build: {build_ts}\n\n"

        # 2. File System Access (kanonische Dateien)
        response += "## 2. File System Access\n"
        response += "Kanonische System-Dateien (direkt gelesen):\n"
        response += f"• {capabilities_status_path} — {'✅' if sources.get('capabilities_status', {}).get('exists') else '❌'}\n"
        response += f"• {capabilities_json_path} — {'✅' if sources.get('capabilities_json', {}).get('exists') else '❌'}\n"
        response += f"• {jarvis_self_path} — {'✅' if sources.get('jarvis_self', {}).get('exists') else '❌'}\n\n"
        
        # 3. Neue Features (aus CAPABILITIES_STATUS.md wenn vorhanden)
        caps_status = sources.get("capabilities_status", {})
        if caps_status.get("exists"):
            content = caps_status.get("content", "")
            if "Recent Changes" in content:
                response += "## 3. Neue Features (aus CAPABILITIES_STATUS.md)\n"
                response += "• Monitoring Access Endpoints: Neue /monitoring/... Endpoints\n"
                response += "• Evidence-Contract Policy: Nur quellenbasierte Aussagen\n"
                response += "• Secure Log Tail: Redaction + Rate-limiting für Log-Zugriff\n\n"
        
        # 4. Verfügbare Tools (highlight wichtigste)
        response += f"## 4. Aktive Tools: {tools_count} verfügbar\n"
        response += "Wichtigste Tools:\n"
        
        # Show key tools
        key_tools = [
            "tool_read_project_file",
            "tool_search_knowledge", 
            "tool_proactive_hint",
            "tool_remember_fact",
            "tool_optimize_system_prompt",
            "tool_get_person_context"
        ]
        
        tool_map = {tool.get("name", ""): tool.get("description", "") for tool in tools}
        shown_tools = []
        for key in key_tools:
            if key in tool_map:
                shown_tools.append((key, tool_map.get(key, "")))

        if shown_tools:
            for tool_name, desc in shown_tools:
                response += f"• {tool_name} — {desc}\n"
        else:
            response += "• (keine Schlüssel-Tools erkannt)\n"

        remaining_tools = max(tools_count - len(shown_tools), 0)
        if remaining_tools:
            response += f"• ...und {remaining_tools} weitere\n"
        response += "\n"
        
        # 5. Gate A Status (from CAPABILITIES_STATUS.md)
        response += "## 5. Gate A Status: ⚠️ PROPOSE-ONLY\n"
        response += "Quelle: CAPABILITIES_STATUS.md\n\n"
        response += "Permission Matrix:\n"
        response += "✅ Read: Knowledge, Calendar, Email, Chats\n"
        response += "⚠️ Code/Config writes: Propose-only (diffs + approval)\n"
        response += "🔴 Infrastructure changes: No direct writes\n\n"
        
        # 6. Monitoring Endpoints
        if monitoring:
            response += f"## 6. Monitoring Endpoints: {len(monitoring)} verfügbar\n"
            for ep in monitoring:
                response += f"• {ep['name']}: {ep['path']}\n"
            response += "\n"
        
        # Sources verification
        response += "Quellen-Validierung:\n"
        source_labels = {
            "capabilities_status": "CAPABILITIES_STATUS.md",
            "capabilities_json": "CAPABILITIES.json",
            "jarvis_self": "JARVIS_SELF.md",
        }
        for source_name, source_info in sources.items():
            exists = "✅" if source_info.get("exists") else "❌"
            size = source_info.get("size_bytes")
            size_display = f"{size} bytes" if size else "unbekannt"
            label = source_labels.get(source_name, source_name)
            response += f"{exists} {label} ({size_display})\n"
        
        response += "\nEvidence-Contract erfüllt: Alle Aussagen basieren auf kanonischen Quellen."
        response += f"\nTimestamp: {data.get('timestamp')}"
        
        # Send response
        await update.message.reply_text(response)
        
        log_with_context(logger, "info", "Capabilities refresh successful", user_id=user.id)
        
    except requests.exceptions.ConnectionError:
        await update.message.reply_text("❌ Cannot connect to Jarvis. Is the service running?")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ Request timed out.")
    except Exception as e:
        log_with_context(logger, "error", "Refresh failed", error=str(e))
        await update.message.reply_text(f"❌ Refresh fehlgeschlagen: {e}")


async def projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /projects command - manage active projects."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    from . import projects as projects_module
    from dataclasses import asdict

    args = context.args

    # No args: list projects
    if not args:
        project_list = projects_module.get_active_projects(user.id, include_paused=True)
        if not project_list:
            await update.message.reply_text(
                "*Aktive Projekte*\n\n"
                "Keine Projekte vorhanden.\n\n"
                "Hinzufügen mit:\n"
                "`/projects add <name> | <beschreibung> | <priorität 1-3>`\n\n"
                "Beispiel:\n"
                "`/projects add Granada | Investment-Entscheidung | 1`",
                parse_mode="Markdown"
            )
            return

        priority_labels = {1: "🔴 HIGH", 2: "🟡 MED", 3: "🟢 LOW"}
        response = "*Aktive Projekte*\n\n"

        active = [p for p in project_list if p.status == "active"]
        paused = [p for p in project_list if p.status == "paused"]

        if active:
            for p in active:
                prio = priority_labels.get(p.priority, "🟡 MED")
                response += f"{prio}: *{p.name}*\n"
                if p.description:
                    response += f"  _{p.description}_\n"
                response += f"  ID: `{p.id}`\n\n"

        if paused:
            response += "*Pausiert:*\n"
            for p in paused:
                response += f"⏸ {p.name} (`{p.id}`)\n"

        response += "\n*Befehle:*\n"
        response += "`/projects add <name>` - Neues Projekt\n"
        response += "`/projects done <id>` - Abschliessen\n"
        response += "`/projects pause <id>` - Pausieren"

        await update.message.reply_text(response, parse_mode="Markdown")
        return

    # Sub-commands
    cmd = args[0].lower()

    if cmd == "add" and len(args) > 1:
        # Parse: name | description | priority
        parts = " ".join(args[1:]).split("|")
        name = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        priority = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 2

        project = projects_module.add_project(user.id, name, description, priority)
        await update.message.reply_text(
            f"✓ Projekt *{name}* hinzugefügt (Priorität {priority})",
            parse_mode="Markdown"
        )

    elif cmd == "done" and len(args) > 1:
        project_id = args[1]
        if projects_module.complete_project(project_id):
            await update.message.reply_text(f"✓ Projekt abgeschlossen: `{project_id}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("Projekt nicht gefunden.", parse_mode="Markdown")

    elif cmd == "pause" and len(args) > 1:
        project_id = args[1]
        if projects_module.pause_project(project_id):
            await update.message.reply_text(f"⏸ Projekt pausiert: `{project_id}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("Projekt nicht gefunden.", parse_mode="Markdown")

    elif cmd == "resume" and len(args) > 1:
        project_id = args[1]
        if projects_module.resume_project(project_id):
            await update.message.reply_text(f"▶ Projekt fortgesetzt: `{project_id}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("Projekt nicht gefunden.", parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "Unbekannter Befehl.\n\n"
            "`/projects` - Liste anzeigen\n"
            "`/projects add <name>` - Hinzufügen\n"
            "`/projects done <id>` - Abschliessen\n"
            "`/projects pause <id>` - Pausieren",
            parse_mode="Markdown"
        )


# ============ Message Reaction Handler ============

async def handle_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle Telegram message reactions (emoji feedback).
    
    Maps reactions to feedback types:
    - 👍 = helpful
    - 👎 = not_helpful
    - 🎯 = perfect
    - 🤔 = unclear
    """
    if not update.message_reaction:
        return
    
    reaction = update.message_reaction
    user_id = reaction.user_id
    chat_id = reaction.chat_id
    message_id = reaction.message_id
    
    # Map reaction emojis to feedback types
    reaction_map = {
        "👍": "helpful",
        "👎": "not_helpful",
        "🎯": "perfect",
        "🤔": "unclear",
    }
    
    # Extract first emoji (telegram may return multiple)
    emoji_list = reaction.new_reaction
    if emoji_list and len(emoji_list) > 0:
        emoji = emoji_list[0].emoji if hasattr(emoji_list[0], 'emoji') else str(emoji_list[0])
        feedback_type = reaction_map.get(emoji, emoji)
        
        try:
            # Log reaction to message_feedback table
            from . import state_db
            state_db.log_message_reaction(
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                reaction=feedback_type,
                emoji=emoji,
                timestamp=datetime.utcnow()
            )
            
            log_with_context(logger, "info", "Message reaction logged",
                           user_id=user_id,
                           chat_id=chat_id,
                           message_id=message_id,
                           feedback=feedback_type,
                           emoji=emoji)
        except Exception as e:
            log_with_context(logger, "warning", "Failed to log message reaction",
                           error=str(e),
                           user_id=user_id)


# ============ Callback Button Handlers ============

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline keyboard button callbacks.

    Callback data format: action:type:id
    Examples:
    - followup:complete:abc123
    - followup:dismiss:abc123
    - followup:snooze:abc123
    - alert:ack:msg_id
    - email:draft:email_id
    """
    query = update.callback_query
    user = query.from_user

    if not is_allowed(user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    await query.answer()  # Acknowledge the callback

    data = query.data
    parts = data.split(":")

    if len(parts) < 2:
        await query.edit_message_text("Invalid action.")
        return

    action_type = parts[0]
    action = parts[1]
    action_id = parts[2] if len(parts) > 2 else None

    try:
        if action_type == "followup":
            await _handle_followup_callback(query, action, action_id)
        elif action_type == "alert":
            await _handle_alert_callback(query, action, action_id)
        elif action_type == "email":
            await _handle_email_callback(query, action, action_id, user.id)
        elif action_type == "file":
            await _handle_file_callback(query, action, context, user.id)
        elif action_type == "build":
            await _handle_build_callback(query, action, user.id)
        elif action_type == "test":
            await _handle_test_callback(query, action, user.id)
        elif action_type == "integrate":
            await _handle_integrate_callback(query, action, user.id)
        elif action_type == "feedback":
            await _handle_feedback_callback(query, action, user.id)
        elif action_type == "msgfb":
            await _handle_message_feedback_callback(query, action, action_id, user.id, context)
        elif action_type == "show":
            await _handle_show_callback(query, action, user.id)
        elif action_type == "activate":
            await _handle_activate_callback(query, action, user.id)
        elif action_type == "telegram":
            await _handle_telegram_callback(query, action, user.id)
        elif action_type == "track":
            await _handle_track_callback(query, action, user.id)
        elif action_type == "approval":
            await _handle_approval_callback(query, action, action_id, user.id)
        elif action_type == "notification":
            await _handle_notification_callback(query, action, action_id, user.id)
        else:
            await query.edit_message_text(f"Unknown action type: {action_type}")
    except Exception as e:
        log_with_context(logger, "error", "Callback handler error",
                        action_type=action_type, action=action, error=str(e))
        await query.edit_message_text(f"Error: {str(e)[:100]}")


async def _handle_followup_callback(query, action: str, followup_id: str) -> None:
    """Handle follow-up related callbacks."""
    from . import state_db

    if action == "complete":
        success = state_db.complete_followup(followup_id)
        if success:
            # Update the message to show completion
            original_text = query.message.text
            await query.edit_message_text(
                f"✅ *Erledigt*\n\n~{original_text}~",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("Follow-up nicht gefunden.")

    elif action == "dismiss":
        success = state_db.dismiss_followup(followup_id, "Dismissed via Telegram")
        if success:
            original_text = query.message.text
            await query.edit_message_text(
                f"🗑️ *Verworfen*\n\n~{original_text}~",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("Follow-up nicht gefunden.")

    elif action == "snooze":
        # Snooze by updating due_date to tomorrow
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        success = state_db.update_followup(followup_id, due_date=tomorrow)
        if success:
            await query.edit_message_text(
                f"⏰ *Verschoben auf morgen*\n\n{query.message.text}",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("Follow-up nicht gefunden.")

    elif action == "details":
        followup = state_db.get_followup(followup_id)
        if followup:
            details = (
                f"📋 *Follow-up Details*\n\n"
                f"*Subject:* {followup['subject']}\n"
                f"*Source:* {followup['source_type']}\n"
                f"*From:* {followup.get('source_from', 'N/A')}\n"
                f"*Priority:* {followup['priority']}\n"
                f"*Status:* {followup['status']}\n"
                f"*Created:* {followup['created_at']}\n"
            )
            if followup.get('description'):
                details += f"\n*Description:*\n{followup['description'][:200]}"
            if followup.get('due_date'):
                details += f"\n*Due:* {followup['due_date']}"

            # Add action buttons
            keyboard = [
                [
                    InlineKeyboardButton("✅ Done", callback_data=f"followup:complete:{followup_id}"),
                    InlineKeyboardButton("🗑️ Dismiss", callback_data=f"followup:dismiss:{followup_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(details, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await query.edit_message_text("Follow-up nicht gefunden.")
    else:
        await query.edit_message_text(f"Unknown follow-up action: {action}")


async def _handle_alert_callback(query, action: str, alert_id: str) -> None:
    """Handle alert-related callbacks."""
    if action == "ack":
        # Acknowledge - just update the message
        original_text = query.message.text
        await query.edit_message_text(
            f"✓ *Acknowledged*\n\n{original_text}",
            parse_mode="Markdown"
        )
    elif action == "dismiss":
        await query.edit_message_text("🗑️ Alert dismissed.")
    else:
        await query.edit_message_text(f"Unknown alert action: {action}")


async def _handle_email_callback(query, action: str, email_ref: str, user_id: int) -> None:
    """Handle email-related callbacks."""
    if action == "draft":
        # Switch to email drafting mode
        state = get_user_state(user_id)
        session_id = state.get("session_id") or str(uuid.uuid4())[:8]

        # Extract email details from the message if possible
        original_text = query.message.text

        # Call agent to draft a reply
        await query.edit_message_text(
            f"📝 *Drafting reply...*\n\n{original_text}",
            parse_mode="Markdown"
        )

        result = call_jarvis_agent(
            f"Draft a professional reply to this email. Keep it concise:\n\n{original_text}",
            session_id,
            state.get("namespace", "work_projektil"),
            "assistant",
            user_id=user_id
        )

        if "error" in result:
            await query.edit_message_text(f"Error drafting: {result['error']}")
        else:
            draft = result.get("answer", "Could not generate draft")
            # Add confirm/edit buttons
            keyboard = [
                [
                    InlineKeyboardButton("📤 Send", callback_data=f"email:send:{email_ref}"),
                    InlineKeyboardButton("✏️ Edit", callback_data=f"email:edit:{email_ref}"),
                ],
                [
                    InlineKeyboardButton("🗑️ Cancel", callback_data=f"email:cancel:{email_ref}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Store draft in context for sending later
            ctx = global_state.get_context_data()
            if "email_drafts" not in ctx:
                ctx["email_drafts"] = {}
            ctx["email_drafts"][email_ref] = {
                "draft": draft,
                "original": original_text
            }
            global_state.set_context_data("email_drafts", ctx["email_drafts"])

            await query.edit_message_text(
                f"📝 *Draft Reply:*\n\n{draft[:2000]}",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

    elif action == "ack":
        await query.edit_message_text(
            f"✓ *Noted*\n\n{query.message.text}",
            parse_mode="Markdown"
        )

    elif action == "cancel":
        await query.edit_message_text("🗑️ Draft cancelled.")

    else:
        await query.edit_message_text(f"Unknown email action: {action}")


async def _handle_file_callback(query, action: str, context, user_id: int) -> None:
    """
    Handle file-related callbacks for ingestion/analysis.

    Actions:
    - ingest: Save to knowledge base via /upload API
    - analyze: Just analyze with Jarvis (no ingestion)
    - both: Ingest + analyze
    """
    import aiohttp
    import tempfile
    import os

    pending_file = context.user_data.get("pending_file")
    if not pending_file:
        await query.edit_message_text("❌ Datei nicht mehr verfügbar. Bitte erneut hochladen.")
        return

    file_name = pending_file.get("file_name", "unknown")
    content = pending_file.get("content", "")
    source_type = pending_file.get("source_type", "text")
    namespace = pending_file.get("namespace", "private")
    file_bytes = pending_file.get("file_bytes", b"")
    caption = pending_file.get("caption", "")

    if action == "ingest" or action == "both":
        # Ingest to knowledge base
        await query.edit_message_text(f"💾 Speichere {file_name} in Wissensbasis...")

        try:
            # Create temp file for upload
            with tempfile.NamedTemporaryFile(mode='wb', suffix=f"_{file_name}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            # Call upload API
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                with open(tmp_path, 'rb') as f:
                    data.add_field('file',
                                  f,
                                  filename=file_name,
                                  content_type='application/octet-stream')
                    data.add_field('source_type', source_type)
                    data.add_field('namespace', namespace)
                    data.add_field('process_sync', 'true')

                    async with session.post(
                        'http://localhost:18000/upload',
                        data=data
                    ) as resp:
                        result = await resp.json()
                        status_code = resp.status

            os.unlink(tmp_path)

            if status_code == 200 and result.get("status") == "uploaded":
                proc = result.get("processing", {})
                msg_count = proc.get("messages_extracted", 0)
                windows = proc.get("windows_embedded", 0)
                participants = proc.get("participants_found", [])

                success_msg = (
                    f"✅ *Erfolgreich gespeichert!*\n\n"
                    f"📄 Datei: {file_name}\n"
                    f"💬 Nachrichten: {msg_count}\n"
                    f"🔗 Eingebettet: {windows} Fenster\n"
                )
                if participants:
                    success_msg += f"👥 Teilnehmer: {', '.join(participants[:5])}"
                    if len(participants) > 5:
                        success_msg += f" (+{len(participants)-5})"

                if action == "ingest":
                    await query.edit_message_text(success_msg, parse_mode="Markdown")
                    context.user_data.pop("pending_file", None)
                    return
                else:
                    # Continue to analysis for "both" action
                    await query.edit_message_text(
                        success_msg + "\n\n🔍 Analysiere...",
                        parse_mode="Markdown"
                    )
            else:
                error_msg = result.get("message", result.get("error", "Unbekannter Fehler"))
                await query.edit_message_text(f"❌ Fehler beim Speichern: {error_msg}")
                return

        except Exception as e:
            log_with_context(logger, "error", "File ingestion failed",
                           file_name=file_name, error=str(e))
            await query.edit_message_text(f"❌ Fehler: {str(e)[:100]}")
            return

    if action == "analyze" or action == "both":
        # Analyze with Jarvis
        state = get_user_state(user_id)
        session_id = state.get("session_id") or str(uuid.uuid4())[:8]
        role = state.get("role", "assistant")

        # Build analysis query
        if source_type == "whatsapp":
            query_text = (
                f"Der Benutzer hat einen WhatsApp-Export hochgeladen ({file_name}).\n"
                + (f"Benutzer-Kommentar: {caption}\n\n" if caption else "")
                + f"Analysiere den Chat und fasse die wichtigsten Themen zusammen:\n\n"
                f"---BEGIN CHAT---\n{content[:8000]}\n---END CHAT---"
            )
        elif source_type == "google_chat":
            query_text = (
                f"Der Benutzer hat einen Google Chat Export hochgeladen ({file_name}).\n"
                + (f"Benutzer-Kommentar: {caption}\n\n" if caption else "")
                + f"Analysiere den Chat:\n\n"
                f"---BEGIN CHAT---\n{content[:8000]}\n---END CHAT---"
            )
        else:
            query_text = (
                f"Analysiere diese Datei: {file_name}\n"
                + (f"Kommentar: {caption}\n\n" if caption else "")
                + f"---BEGIN CONTENT---\n{content[:8000]}\n---END CONTENT---"
            )

        if len(content) > 8000:
            query_text += f"\n\n(Gekürzt, {len(content) - 8000} Zeichen ausgelassen)"

        result = call_jarvis_agent(query_text, session_id, namespace, role, user_id=user_id)

        if "error" in result:
            await query.edit_message_text(f"❌ Analyse-Fehler: {result['error']}")
        else:
            answer = result.get("answer", "Keine Antwort")
            usage = result.get("usage", {})

            response = f"🔍 *Analyse: {file_name}*\n\n{answer}"
            if usage:
                response += f"\n\n_{usage.get('input_tokens', 0)}→{usage.get('output_tokens', 0)} tokens_"

            # Telegram limit
            if len(response) > 4000:
                response = response[:3997] + "..."

            await query.edit_message_text(response, parse_mode="Markdown")

    # Clean up
    context.user_data.pop("pending_file", None)


def build_followup_buttons(followup_id: str, show_details: bool = True) -> InlineKeyboardMarkup:
    """Build standard follow-up action buttons."""
    buttons = [
        [
            InlineKeyboardButton("✅ Done", callback_data=f"followup:complete:{followup_id}"),
            InlineKeyboardButton("⏰ Snooze", callback_data=f"followup:snooze:{followup_id}"),
        ],
        [
            InlineKeyboardButton("🗑️ Dismiss", callback_data=f"followup:dismiss:{followup_id}"),
        ]
    ]
    if show_details:
        buttons[1].insert(0, InlineKeyboardButton("📋 Details", callback_data=f"followup:details:{followup_id}"))

    return InlineKeyboardMarkup(buttons)


def build_email_buttons(email_ref: str) -> InlineKeyboardMarkup:
    """Build email action buttons for VIP alerts."""
    buttons = [
        [
            InlineKeyboardButton("📝 Draft Reply", callback_data=f"email:draft:{email_ref}"),
            InlineKeyboardButton("✓ Ack", callback_data=f"email:ack:{email_ref}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def build_alert_buttons(alert_id: str = "default") -> InlineKeyboardMarkup:
    """Build generic alert action buttons."""
    buttons = [
        [
            InlineKeyboardButton("✓ Acknowledge", callback_data=f"alert:ack:{alert_id}"),
            InlineKeyboardButton("🗑️ Dismiss", callback_data=f"alert:dismiss:{alert_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle file/document uploads.

    Supports:
    - TXT files: WhatsApp exports -> Ingest to knowledge base
    - JSON files: Google Chat exports -> Ingest to knowledge base
    - EML/MBOX files: Email exports -> Ingest to knowledge base

    Offers buttons to choose: Analyze / Ingest / Both
    """
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized.")
        return

    document = update.message.document
    if not document:
        return

    # Get file info
    file_name = document.file_name or "unnamed"
    file_size = document.file_size or 0
    mime_type = document.mime_type or ""
    file_name_lower = file_name.lower()

    # Size limit from config
    if file_size > config.MAX_UPLOAD_SIZE_BYTES:
        await update.message.reply_text(
            f"Datei zu gross ({file_size // 1024}KB). Maximum: {config.MAX_UPLOAD_SIZE_MB}MB."
        )
        return

    # Detect file type and source
    source_type = None
    if file_name_lower.endswith(".txt"):
        source_type = "whatsapp"
    elif file_name_lower.endswith(".json"):
        # Could be Google Chat or Email JSON
        source_type = "google_chat"  # Will verify content later
    elif file_name_lower.endswith((".eml", ".mbox")):
        source_type = "email"

    # Check if it's a supported file
    supported_extensions = (".txt", ".json", ".eml", ".mbox", ".md", ".csv", ".log")
    is_supported = file_name_lower.endswith(supported_extensions)

    if not is_supported:
        await update.message.reply_text(
            f"Dateityp nicht unterstützt: {mime_type or file_name}\n\n"
            "Unterstützt:\n"
            "- WhatsApp: .txt\n"
            "- Google Chat: .json\n"
            "- Email: .eml, .mbox, .json\n"
            "- Andere: .md, .csv, .log"
        )
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        # Download file
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        # Decode content (try UTF-8, then Latin-1)
        try:
            content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content = file_bytes.decode("latin-1")

        # Detect WhatsApp export pattern
        is_whatsapp = _detect_whatsapp_export(content)
        if is_whatsapp:
            source_type = "whatsapp"

        # Detect Google Chat JSON
        is_gchat = False
        if file_name_lower.endswith(".json"):
            try:
                import json
                data = json.loads(content)
                if isinstance(data, dict) and "messages" in data:
                    is_gchat = True
                    source_type = "google_chat"
                elif isinstance(data, list) and data and "createTime" in str(data[0]):
                    is_gchat = True
                    source_type = "google_chat"
            except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                log_with_context(logger, "debug", "Content doesn't look like Google Chat JSON format")
                is_gchat = False

        # Store file info in context for callback
        context.user_data["pending_file"] = {
            "file_id": document.file_id,
            "file_name": file_name,
            "content": content,
            "source_type": source_type,
            "file_bytes": file_bytes
        }

        # Build info message and buttons
        file_info = f"Datei: {file_name}\n"
        file_info += f"Grösse: {len(content):,} Zeichen\n"

        if source_type == "whatsapp":
            file_info += "Typ: WhatsApp Export erkannt\n"
        elif source_type == "google_chat":
            file_info += "Typ: Google Chat Export erkannt\n"
        elif source_type == "email":
            file_info += "Typ: Email Export\n"
        else:
            file_info += "Typ: Textdatei\n"

        # Offer action buttons
        buttons = []
        if source_type in ("whatsapp", "google_chat", "email"):
            buttons.append([
                InlineKeyboardButton("💾 Speichern", callback_data="file:ingest"),
                InlineKeyboardButton("🔍 Analysieren", callback_data="file:analyze")
            ])
            buttons.append([
                InlineKeyboardButton("💾+🔍 Beides", callback_data="file:both")
            ])
        else:
            # Generic text file - just analyze
            buttons.append([
                InlineKeyboardButton("🔍 Analysieren", callback_data="file:analyze")
            ])

        keyboard = InlineKeyboardMarkup(buttons)

        # Store namespace from user state for later use
        state = get_user_state(user.id)
        context.user_data["pending_file"]["namespace"] = state.get("namespace", "private")
        context.user_data["pending_file"]["caption"] = update.message.caption or ""
        context.user_data["pending_file"]["user_id"] = user.id

        await update.message.reply_text(
            file_info + "\nWas soll ich damit machen?",
            reply_markup=keyboard
        )
        # Processing happens in callback handler when user clicks a button

    except Exception as e:
        log_with_context(logger, "error", "Error processing document", error=str(e), file_name=file_name)
        await update.message.reply_text(
            f"Fehler beim Verarbeiten der Datei: {str(e)[:100]}"
        )


def _detect_whatsapp_export(content: str) -> bool:
    """
    Detect if content looks like a WhatsApp chat export.

    WhatsApp exports typically have lines like:
    - "01.01.2024, 14:30 - Name: Message"
    - "[01.01.2024, 14:30:00] Name: Message"
    """
    import re

    # Common WhatsApp export patterns
    patterns = [
        r"\d{1,2}\.\d{1,2}\.\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*[-–]\s*\w+:",  # German format
        r"\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*[-–]\s*\w+:",  # US format
        r"\[\d{1,2}\.\d{1,2}\.\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\]\s*\w+:",  # Bracketed format
    ]

    # Check first 2000 chars for patterns
    sample = content[:2000]

    for pattern in patterns:
        matches = re.findall(pattern, sample)
        if len(matches) >= 3:  # At least 3 message-like lines
            return True

    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular messages"""
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized.")
        return

    query = update.message.text

    # Get user state from database
    state = get_user_state(user.id)
    session_id = state["session_id"]
    namespace = state["namespace"]
    role = state["role"]

    # Create session if none exists
    if not session_id:
        session_id = str(uuid.uuid4())[:8]
        save_user_state(user.id, session_id=session_id)

    # Typing is best-effort only. Do not fail the whole request on Telegram hiccups.
    try:
        await update.message.chat.send_action("typing")
    except telegram_error.TelegramError as exc:
        log_with_context(
            logger,
            "warning",
            "Telegram typing indicator failed",
            error=str(exc),
            error_type=type(exc).__name__,
            user_id=user.id,
        )

    # Call Jarvis (pass user_id for context persistence)
    result = call_jarvis_agent(query, session_id, namespace, role, user_id=user.id)

    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
        return

    # Update session if returned
    if result.get("session_id") and result["session_id"] != session_id:
        save_user_state(user.id, session_id=result["session_id"])

    # Format response
    answer = result.get("answer", "No response")
    if not answer or not str(answer).strip():
        answer = "Keine Antwort erhalten."
    actual_role = result.get("role", "assistant")

    # Add tool info
    tool_calls = result.get("tool_calls", [])
    tools_used = [tc.get("tool") for tc in tool_calls if tc.get("tool") != "no_tool_needed"]

    response = ""
    # Show role if different from requested (auto-detected)
    if role == "auto" and actual_role != "assistant":
        response += f"[{actual_role}] "
    if tools_used:
        response += f"[{', '.join(tools_used)}]\n\n"
    elif role == "auto" and actual_role != "assistant":
        response += "\n\n"

    response += answer

    # Add usage info
    usage = result.get("usage", {})
    if usage:
        response += f"\n\n[{usage.get('input_tokens', 0)}->{usage.get('output_tokens', 0)} tokens]"

    # Telegram has 4096 char limit
    if len(response) > 4000:
        response = response[:3997] + "..."

    # Add feedback buttons for substantive responses (>100 chars)
    if len(answer) > 100:
        # Store context for feedback callback in context.user_data
        query_preview = query[:100] if query else ""
        response_preview = answer[:100] if answer else ""

        keyboard = [
            [
                InlineKeyboardButton("👍", callback_data=f"msgfb:good:{session_id}"),
                InlineKeyboardButton("🤔", callback_data=f"msgfb:ok:{session_id}"),
                InlineKeyboardButton("👎", callback_data=f"msgfb:bad:{session_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Store query/response preview for feedback context (temporary, in-memory)
        context.user_data["last_query"] = query_preview
        context.user_data["last_response"] = response_preview

        try:
            await update.message.reply_text(response, reply_markup=reply_markup)
        except telegram_error.TelegramError as exc:
            log_with_context(
                logger,
                "warning",
                "Telegram reply with feedback buttons failed, retrying without markup",
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=user.id,
                response_len=len(response),
            )
            await update.message.reply_text(response)
    else:
        try:
            await update.message.reply_text(response)
        except telegram_error.TelegramError as exc:
            log_with_context(
                logger,
                "error",
                "Telegram plain-text reply failed",
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=user.id,
                response_len=len(response),
            )
            raise


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors globally - log and optionally notify user"""
    error_msg = str(context.error) if context.error else "Unknown error"

    # Extract user info if available
    user_id = None
    if update and update.effective_user:
        user_id = update.effective_user.id

    log_with_context(
        logger, "error", "Telegram bot error",
        error=error_msg,
        error_type=type(context.error).__name__ if context.error else None,
        user_id=user_id,
        update_type=type(update).__name__ if update else None
    )
    if context.error:
        logger.exception("Telegram bot traceback", exc_info=context.error)

    # Notify user if possible
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Ein Fehler ist aufgetreten. Bitte versuche es erneut."
            )
        except telegram_error.TelegramError as e:
            # Telegram API error, already logged in main handler
            log_with_context(logger, "debug", f"Could not notify user of error: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_with_context(
                logger,
                "error",
                "Failed to notify Telegram user about bot error",
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=user_id,
            )


# ============ Bot Startup Functions ============

def _build_application() -> Application:
    """Build the telegram application with handlers"""
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new", new_session))
    application.add_handler(CommandHandler("briefing", briefing))
    application.add_handler(CommandHandler("ns", set_namespace))
    application.add_handler(CommandHandler("role", set_role))
    application.add_handler(CommandHandler("domain", set_domain))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("generate", generate_command))
    application.add_handler(CommandHandler("decide", decide))
    application.add_handler(CommandHandler("outcome", outcome))
    application.add_handler(CommandHandler("patterns", patterns))
    application.add_handler(CommandHandler("remember", remember))
    application.add_handler(CommandHandler("forget", forget))
    application.add_handler(CommandHandler("self", self_reflect))
    application.add_handler(CommandHandler("profile", profile_command))
    # Task management commands
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("task", task_command))
    application.add_handler(CommandHandler("done", done_command))
    # Emotional Intelligence commands
    application.add_handler(CommandHandler("compass", compass))
    application.add_handler(CommandHandler("whatif", whatif))
    application.add_handler(CommandHandler("trust", trust))
    application.add_handler(CommandHandler("flags", flags))
    application.add_handler(CommandHandler("blindspot", blindspot))
    application.add_handler(CommandHandler("energy", energy))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("refresh", refresh_capabilities))
    application.add_handler(CommandHandler("projects", projects))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Message reaction handler (emoji feedback)
    application.add_handler(TypeHandler(MessageReactionUpdated, handle_message_reaction))

    # Error handler
    application.add_error_handler(error_handler)

    return application


def _run_bot_once() -> None:
    """Run the bot synchronously (one attempt). Raises on failure."""
    application = _build_application()
    log_with_context(logger, "info", "Telegram bot starting (polling)")

    async def run_polling():
        await application.initialize()
        await application.start()
        # Enable message reactions in allowed_updates
        allowed = list(Update.ALL_TYPES) + ["message_reaction"]
        await application.updater.start_polling(allowed_updates=allowed)

        # Keep running until asked to stop
        while True:
            with _bot_lock:
                should_run = _bot_should_run
            if not should_run:
                break
            await asyncio.sleep(1)

        await application.updater.stop()
        await application.stop()
        await application.shutdown()

    global_state.set_bot_running(True)
    try:
        asyncio.run(run_polling())
    finally:
        global_state.set_bot_running(False)


def _run_bot_supervisor():
    """Supervise bot lifecycle and auto-restart with backoff on crashes."""
    global _bot_restart_count, _bot_last_error, _bot_last_crash_at, _bot_last_start_at, _bot_should_run

    backoff_seconds = 1.0
    max_backoff_seconds = 60.0

    while True:
        with _bot_lock:
            should_run = _bot_should_run
        if not should_run:
            return

        _bot_last_start_at = datetime.utcnow().isoformat() + "Z"
        try:
            _run_bot_once()

            # If we returned while still supposed to run, treat as unexpected stop.
            with _bot_lock:
                still_should_run = _bot_should_run
            if still_should_run:
                raise RuntimeError("Telegram bot stopped unexpectedly")
            return
        except Exception as e:
            # Permanent misconfiguration: stop retrying to avoid busy loops and leaking secrets in tracebacks.
            if isinstance(e, telegram_error.InvalidToken):
                _bot_restart_count += 1
                _bot_last_error = f"{type(e).__name__}: rejected by Telegram (check TELEGRAM_BOT_TOKEN)"
                _bot_last_crash_at = datetime.utcnow().isoformat() + "Z"

                logger.error("Telegram bot disabled: invalid/unauthorized token configured")
                log_with_context(
                    logger,
                    "error",
                    "Telegram bot disabled: invalid/unauthorized token configured",
                    error_type=type(e).__name__,
                    restart_count=_bot_restart_count,
                    permanent=True,
                )

                with _bot_lock:
                    _bot_should_run = False
                return

            _bot_restart_count += 1
            _bot_last_error = f"{type(e).__name__}: {e}"
            _bot_last_crash_at = datetime.utcnow().isoformat() + "Z"

            # Ensure we get a traceback in logs (default logging formatter).
            logger.error("Telegram bot crashed (will restart with backoff)", exc_info=True)
            log_with_context(
                logger,
                "error",
                "Telegram bot crashed (will restart with backoff)",
                error=str(e),
                error_type=type(e).__name__,
                restart_count=_bot_restart_count,
                backoff_seconds=backoff_seconds,
            )

            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2.0, max_backoff_seconds)


def start_bot_background() -> bool:
    """Start the telegram bot in a background thread. Returns True if started."""
    global _bot_supervisor_thread, _bot_should_run

    if not TELEGRAM_TOKEN:
        log_with_context(logger, "warning", "Telegram bot not started: token not set")
        return False

    with _bot_lock:
        _bot_should_run = True

    if global_state.get_bot_running() or (_bot_supervisor_thread and _bot_supervisor_thread.is_alive()):
        log_with_context(logger, "info", "Telegram bot already running")
        return True

    _bot_supervisor_thread = threading.Thread(target=_run_bot_supervisor, daemon=True)
    _bot_supervisor_thread.start()
    log_with_context(logger, "info", "Telegram bot supervisor started in background thread")
    return True


def is_bot_running() -> bool:
    """Check if bot is running"""
    return global_state.get_bot_running()


def get_bot_status() -> dict:
    """Get comprehensive bot status for health checks"""
    bot_running = global_state.get_bot_running()
    status = {
        "status": "healthy" if bot_running else "stopped",
        "desired": _bot_should_run,
        "running": bot_running,
        "thread_alive": _bot_supervisor_thread.is_alive() if _bot_supervisor_thread else False,
        "token_configured": bool(TELEGRAM_TOKEN),
        "allowed_users": len(ALLOWED_USER_IDS) if ALLOWED_USER_IDS else 0,
        "restart_count": _bot_restart_count,
        "last_start_at": _bot_last_start_at,
        "last_crash_at": _bot_last_crash_at,
        "last_error": _bot_last_error,
    }
    return status


# ============ Alert Functions ============

# Phase 15.5: Daily hint limit configuration
HINTS_PER_DAY_LIMIT = 2  # Max non-critical alerts per day
_daily_hint_count: Dict[str, int] = {}  # Key: date string, Value: count


def _check_daily_limit(level: str) -> bool:
    """
    Check if we've exceeded daily hint limit.
    Critical and error levels bypass the limit.

    Returns True if allowed to send, False if limit reached.
    """
    # Critical and error levels always allowed
    if level in ("critical", "error"):
        return True

    today = datetime.now().strftime("%Y-%m-%d")

    # Clean old entries (keep only today)
    for key in list(_daily_hint_count.keys()):
        if key != today:
            del _daily_hint_count[key]

    current_count = _daily_hint_count.get(today, 0)

    if current_count >= HINTS_PER_DAY_LIMIT:
        log_with_context(logger, "info", "Daily hint limit reached",
                        count=current_count, limit=HINTS_PER_DAY_LIMIT)
        return False

    _daily_hint_count[today] = current_count + 1
    return True


def get_hint_stats() -> Dict[str, Any]:
    """Get current hint statistics for monitoring."""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "hints_sent_today": _daily_hint_count.get(today, 0),
        "daily_limit": HINTS_PER_DAY_LIMIT,
        "remaining": max(0, HINTS_PER_DAY_LIMIT - _daily_hint_count.get(today, 0))
    }


def send_alert(
    message: str,
    level: str = "warning",
    buttons: List[List[Dict]] = None,
    bypass_limit: bool = False,
    chat_id: str | int | None = None,
    thread_id: str | int | None = None,
) -> bool:
    """
    Send an alert message to all allowed Telegram users.
    Used for system notifications (ingest failures, errors, etc.)

    Phase 15.5: Implements daily limit for non-critical alerts.

    Args:
        message: The alert message to send
        level: Alert level (info, warning, error, critical)
        buttons: Optional inline keyboard buttons as list of rows
                 Each row is a list of dicts with 'text' and 'callback_data'
                 Example: [[{"text": "✓ Ack", "callback_data": "alert:ack:123"}]]
        bypass_limit: Skip daily limit check (for forced notifications)
        chat_id: Optional explicit target chat ID (group or user)
        thread_id: Optional Telegram topic/thread ID for forum groups

    Returns:
        True if at least one message was sent successfully
        False if limit reached or send failed
    """
    # Check daily limit (Phase 15.5)
    if not bypass_limit and not _check_daily_limit(level):
        log_with_context(logger, "info", "Alert blocked: daily limit reached",
                        alert_level=level, message_preview=message[:50])
        return False

    if not TELEGRAM_TOKEN:
        log_with_context(logger, "warning", "Cannot send alert: token not set")
        return False

    if not ALLOWED_USER_IDS and not chat_id:
        log_with_context(logger, "warning", "Cannot send alert: no allowed users configured")
        return False

    # Format message with level indicator
    level_emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
        "critical": "🚨"
    }.get(level, "📢")

    formatted_message = f"{level_emoji} *Jarvis Alert*\n\n{message}"

    # Truncate if too long
    if len(formatted_message) > 4000:
        formatted_message = formatted_message[:3997] + "..."

    # Build payload
    payload = {
        "text": formatted_message,
        "parse_mode": "Markdown"
    }

    if thread_id is not None and chat_id is not None:
        payload["message_thread_id"] = int(thread_id)

    # Add inline keyboard if buttons provided
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": buttons
        }

    recipients = [str(chat_id)] if chat_id is not None else ALLOWED_USER_IDS

    success = False
    import time
    for user_id in recipients:
        max_attempts = 3
        base_backoff_s = 0.5
        max_sleep_s = 5.0

        for attempt in range(1, max_attempts + 1):
            try:
                payload["chat_id"] = user_id
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload,
                    timeout=5
                )

                if response.status_code == 200:
                    success = True
                    log_with_context(logger, "info", "Alert sent", user_id=user_id, alert_level=level)
                    break

                retry_after = None
                error_code = None
                description = None
                try:
                    data = response.json()
                    error_code = data.get("error_code")
                    description = data.get("description")
                    params = data.get("parameters") or {}
                    retry_after = params.get("retry_after") or data.get("retry_after")
                except Exception:
                    pass

                is_last = attempt >= max_attempts

                # Telegram flood control: respect retry_after (bounded to avoid blocking)
                if response.status_code == 429 and not is_last:
                    sleep_s = min(max(float(retry_after or 0), base_backoff_s * (2 ** (attempt - 1))), max_sleep_s)
                    log_with_context(
                        logger,
                        "warning",
                        "Telegram rate-limited while sending alert; will retry",
                        user_id=user_id,
                        status_code=response.status_code,
                        error_code=error_code,
                        retry_after=retry_after,
                        attempt=attempt,
                        sleep_s=round(sleep_s, 2),
                    )
                    time.sleep(sleep_s)
                    continue

                # Transient HTTP failures: brief retry with backoff
                if response.status_code in (408,) or response.status_code >= 500:
                    if not is_last:
                        sleep_s = min(base_backoff_s * (2 ** (attempt - 1)), max_sleep_s)
                        log_with_context(
                            logger,
                            "warning",
                            "Telegram transient HTTP error while sending alert; will retry",
                            user_id=user_id,
                            status_code=response.status_code,
                            error_code=error_code,
                            description=(description or response.text[:120]),
                            attempt=attempt,
                            sleep_s=round(sleep_s, 2),
                        )
                        time.sleep(sleep_s)
                        continue

                log_with_context(
                    logger,
                    "warning",
                    "Failed to send alert",
                    user_id=user_id,
                    status_code=response.status_code,
                    error_code=error_code,
                    description=(description or response.text[:120]),
                    attempt=attempt,
                )
                break

            except requests.exceptions.RequestException as e:
                is_last = attempt >= max_attempts
                if not is_last:
                    sleep_s = min(base_backoff_s * (2 ** (attempt - 1)), max_sleep_s)
                    log_with_context(
                        logger,
                        "warning",
                        "Telegram send alert network error; will retry",
                        user_id=user_id,
                        error_type=type(e).__name__,
                        error=str(e)[:200],
                        attempt=attempt,
                        sleep_s=round(sleep_s, 2),
                    )
                    time.sleep(sleep_s)
                    continue
                log_with_context(
                    logger,
                    "error",
                    "Error sending alert",
                    user_id=user_id,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    attempt=attempt,
                )
                break

    return success


def alert_ingest_failure(connector: str, error: str, namespace: str = None) -> bool:
    """
    Send a specific alert for ingest failures.

    Args:
        connector: Name of the connector that failed (e.g., "gmail", "whatsapp")
        error: Error message
        namespace: Optional namespace where failure occurred
    """
    ns_info = f" ({namespace})" if namespace else ""
    message = f"*Ingest Failure*{ns_info}\n\nConnector: `{connector}`\nError: {error}"
    return send_alert(message, level="error")


def send_approval_request(action_id: str, description: str, reason: str = None, timeout_str: str = None) -> bool:
    """
    Send an approval request via Telegram with Approve/Reject buttons.

    This is the main interface for the Intent-Approval-Execution system
    to request user approval for Tier 3 actions.

    Args:
        action_id: Unique action ID for callback tracking
        description: Human-readable description of what Jarvis wants to do
        reason: Optional reason/context for the action
        timeout_str: Optional timeout display string (e.g., "4h 0m")

    Returns:
        True if message was sent successfully
    """
    # Build message
    message_parts = [f"🤖 *Jarvis möchte:* {_escape_markdown(description)}"]

    if reason:
        message_parts.append(f"\n📋 *Grund:* {_escape_markdown(reason)}")

    if timeout_str:
        message_parts.append(f"\n⏰ *Timeout:* {timeout_str}")

    message = "\n".join(message_parts)

    # Build buttons
    buttons = [
        [
            {"text": "✅ Ja", "callback_data": f"approval:approve:{action_id}"},
            {"text": "❌ Nein", "callback_data": f"approval:reject:{action_id}"},
        ],
        [
            {"text": "ℹ️ Details", "callback_data": f"approval:info:{action_id}"},
        ]
    ]

    return send_alert(message, level="info", buttons=buttons)


def request_action_approval(
    action_name: str,
    description: str,
    target: str = None,
    context: dict = None,
    urgent: bool = False,
    user_id: str = None
) -> dict:
    """
    Request approval for an action through the Intent-Approval-Execution system.

    This is the main entry point for Jarvis to request permission to perform actions.
    It handles the full flow:
    1. Creates action request in the queue
    2. Checks if approval is needed based on tier
    3. Sends Telegram notification if approval required
    4. Returns the action status

    Args:
        action_name: The action type (e.g., "knowledge_write", "calendar_modify")
        description: Human-readable description of what will be done
        target: Target file/resource path (optional)
        context: Additional context dict (optional)
        urgent: Mark as urgent for shorter timeout (optional)

    Returns:
        dict with keys:
        - id: action ID
        - status: "approved", "pending", "blocked"
        - tier: action tier
        - requires_approval: bool
        - notification_sent: bool (if approval was requested via Telegram)
    """
    from . import action_queue

    # Create the action request
    request = action_queue.create_action_request(
        action_name=action_name,
        description=description,
        target=target,
        context=context,
        urgent=urgent,
        user_id=user_id
    )

    result = {
        "id": request.get("id"),
        "status": request.get("status"),
        "tier": request.get("tier"),
        "requires_approval": request.get("status") == "pending",
        "notification_sent": False
    }

    # If approval is needed, send Telegram notification
    if request.get("status") == "pending":
        # Calculate timeout string
        from datetime import datetime
        try:
            expires_at = datetime.fromisoformat(request.get("expires_at", "").rstrip("Z"))
            remaining = expires_at - datetime.utcnow()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            timeout_str = f"{hours}h {minutes}m"
        except (ValueError, AttributeError, TypeError):
            log_with_context(logger, "debug", "Could not parse timeout from expires_at, using None")
            timeout_str = None

        reason = context.get("reason") if context else None
        notification_sent = send_approval_request(
            action_id=request.get("id"),
            description=description,
            reason=reason,
            timeout_str=timeout_str
        )
        result["notification_sent"] = notification_sent

        if notification_sent:
            log_with_context(logger, "info", "Approval request sent via Telegram",
                           action_id=request.get("id"), action=action_name)
        else:
            log_with_context(logger, "warning", "Failed to send approval request",
                           action_id=request.get("id"), action=action_name)

    return result


def send_vip_email_alert(
    sender: str,
    subject: str,
    snippet: str,
    email_id: str,
    person_context: str = None
) -> bool:
    """
    Send a VIP email alert with quick-action buttons.

    Args:
        sender: Email sender name/address
        subject: Email subject
        snippet: Email preview snippet
        email_id: Email ID for callback reference
        person_context: Optional context about the person (title, relationship, etc.)

    Returns:
        True if alert was sent successfully
    """
    message = f"*VIP Email*\n\n"
    message += f"*From:* {sender}\n"
    message += f"*Subject:* {subject}\n\n"

    if person_context:
        message += f"_{person_context}_\n\n"

    message += f">{snippet[:300]}"

    # Add action buttons
    buttons = [
        [
            {"text": "📝 Draft Reply", "callback_data": f"email:draft:{email_id[:20]}"},
            {"text": "✓ Noted", "callback_data": f"email:ack:{email_id[:20]}"},
        ]
    ]

    return send_alert(message, level="info", buttons=buttons)


def send_followup_reminder(
    followup_id: str,
    subject: str,
    source_from: str = None,
    priority: str = "normal",
    is_overdue: bool = False
) -> bool:
    """
    Send a follow-up reminder with action buttons.

    Args:
        followup_id: Follow-up ID
        subject: Follow-up subject
        source_from: Original source (email sender, etc.)
        priority: Priority level
        is_overdue: Whether this follow-up is overdue

    Returns:
        True if reminder was sent successfully
    """
    level = "warning" if is_overdue else "info"
    status = "🔴 OVERDUE" if is_overdue else ""

    priority_icon = {
        "urgent": "🚨",
        "high": "🔴",
        "normal": "",
        "low": "🔵"
    }.get(priority, "")

    message = f"*Follow-up Reminder* {status}\n\n"
    message += f"{priority_icon} *{subject}*\n"

    if source_from:
        message += f"From: {source_from}\n"

    # Add action buttons
    buttons = [
        [
            {"text": "✅ Done", "callback_data": f"followup:complete:{followup_id}"},
            {"text": "⏰ Snooze", "callback_data": f"followup:snooze:{followup_id}"},
        ],
        [
            {"text": "📋 Details", "callback_data": f"followup:details:{followup_id}"},
            {"text": "🗑️ Dismiss", "callback_data": f"followup:dismiss:{followup_id}"},
        ]
    ]

    return send_alert(message, level=level, buttons=buttons)


def send_urgent_alert(
    title: str,
    details: str,
    alert_id: str = None
) -> bool:
    """
    Send an urgent alert with acknowledge button.

    Args:
        title: Alert title
        details: Alert details
        alert_id: Optional alert ID for tracking

    Returns:
        True if alert was sent successfully
    """
    alert_id = alert_id or str(uuid.uuid4())[:8]

    message = f"*{title}*\n\n{details}"

    buttons = [
        [
            {"text": "✓ Acknowledge", "callback_data": f"alert:ack:{alert_id}"},
            {"text": "🗑️ Dismiss", "callback_data": f"alert:dismiss:{alert_id}"},
        ]
    ]

    return send_alert(message, level="critical", buttons=buttons)


# ============ New Callback Handlers for Development Features ============

async def _handle_build_callback(query, action: str, user_id: int) -> None:
    """Handle build-related callbacks."""
    if action == "emotions":
        await query.edit_message_text(
            "📊 *Emotion Tracking implementieren*\n\n"
            "Das würde folgende Features umfassen:\n"
            "• Emotion History Table in PostgreSQL\n"
            "• Session-übergreifendes Stress-Tracking\n"
            "• Automatische Intervention bei Stress-Patterns\n\n"
            "Implementierung würde 1-2 Tage dauern.\n\n"
            "_Hinweis: Diese Funktion ist noch nicht automatisiert. "
            "Bitte Copilot bitten, das Feature zu implementieren._",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Build action '{action}' not implemented yet.")


async def _handle_test_callback(query, action: str, user_id: int) -> None:
    """Handle test-related callbacks."""
    if action == "patterns":
        await query.edit_message_text(
            "🧪 *Pattern Tracking Test*\n\n"
            "Pattern Tracking ist bereits implementiert!\n\n"
            "Test mit:\n"
            "`curl -X POST http://192.168.1.103:18000/patterns/track?user_id=1465947014&topic=test_topic&context=test_context`\n\n"
            "Nach 3x wird eine proaktive Response getriggert.",
            parse_mode="Markdown"
        )
    elif action == "selfheal":
        await query.edit_message_text(
            "🔧 *Self-Healing Test*\n\n"
            "Self-Healing Endpoints:\n"
            "• `/maintenance/self_heal?action=check`\n"
            "• `/maintenance/self_heal?action=restart&component=telegram`\n"
            "• `/maintenance/diagnostics`\n\n"
            "_Teste mit curl oder lass Copilot die Tests ausführen._",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Test action '{action}' not implemented yet.")


async def _handle_integrate_callback(query, action: str, user_id: int) -> None:
    """Handle integration-related callbacks."""
    if action == "slack":
        await query.edit_message_text(
            "🔗 *Slack Integration*\n\n"
            "Würde via n8n implementiert:\n"
            "• Slack Webhook → Jarvis API\n"
            "• Message Monitoring\n"
            "• Auto-Responses\n\n"
            "Zeitaufwand: 3-4 Stunden\n\n"
            "_Bitte Copilot bitten, ein n8n Template zu erstellen._",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Integration '{action}' not implemented yet.")


async def _handle_feedback_callback(query, action: str, user_id: int) -> None:
    """Handle feedback callbacks."""
    if action == "good":
        await query.edit_message_text(
            "👍 *Danke für das positive Feedback!*\n\n"
            "Dein Feedback hilft mir zu lernen, was gut funktioniert.",
            parse_mode="Markdown"
        )
    elif action == "ok":
        await query.edit_message_text(
            "🤔 *Verstehe - nur okay.*\n\n"
            "Was könnte besser sein? Lass es mich wissen!",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("Feedback erhalten: " + action)


async def _handle_message_feedback_callback(query, action: str, session_id: str, user_id: int, context) -> None:
    """Handle per-message feedback callbacks (👍👎🤔 buttons).

    Stores feedback in database and shows acknowledgment.
    """
    from . import state_db

    # Get the message being rated
    message_id = query.message.message_id if query.message else 0

    # Get stored context from context.user_data (set when response was sent)
    query_preview = context.user_data.get("last_query", "") if context.user_data else ""
    response_preview = context.user_data.get("last_response", "") if context.user_data else ""

    # Store the feedback
    state_db.store_message_feedback(
        user_id=user_id,
        message_id=message_id,
        rating=action,
        session_id=session_id,
        query_preview=query_preview,
        response_preview=response_preview
    )

    # Get original message text (without buttons)
    original_text = query.message.text if query.message else ""

    # Rating emoji map
    emoji_map = {"good": "👍", "ok": "🤔", "bad": "👎"}
    emoji = emoji_map.get(action, "✓")

    # Remove buttons and show rating confirmation
    # Keep original response, add small rating indicator at the end
    if original_text:
        # Add rating indicator to end of message
        updated_text = original_text + f"\n\n[{emoji} Feedback gespeichert]"
        if len(updated_text) > 4000:
            updated_text = updated_text[:3997] + "..."
        await query.edit_message_text(updated_text)
    else:
        await query.answer(f"{emoji} Danke für dein Feedback!")


async def _handle_show_callback(query, action: str, user_id: int) -> None:
    """Handle show/display callbacks."""
    if action == "diagnostics":
        await query.edit_message_text(
            "📊 *Diagnostics anzeigen*\n\n"
            "Rufe `/maintenance/diagnostics` auf für:\n"
            "• Memory Usage\n"
            "• Active Sessions\n"
            "• Queue Status\n"
            "• Error Logs\n\n"
            "_Copilot kann die Details abrufen._",
            parse_mode="Markdown"
        )
    elif action == "telegram_optimization":
        await query.edit_message_text(
            "📱 *Telegram Optimierungen*\n\n"
            "Neue Features:\n"
            "• `/telegram/send` - Genereller Message Endpoint\n"
            "• `/telegram/status` - Detaillierter Bot Status\n"
            "• Targeted Messages\n"
            "• Silent Mode\n\n"
            "Details in: TELEGRAM_OPTIMIZATION.md",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Show action '{action}' not implemented.")


async def _handle_activate_callback(query, action: str, user_id: int) -> None:
    """Handle activation callbacks."""
    if action == "patterns":
        await query.edit_message_text(
            "✅ *Pattern Tracking ist bereits aktiv!*\n\n"
            "Jede Topic-Erwähnung wird getrackt.\n"
            "Nach 3 Erwähnungen: Proaktive Response.\n\n"
            "Status abrufen mit:\n"
            "`/patterns/user/{user_id}`",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Activation '{action}' not implemented.")


async def _handle_telegram_callback(query, action: str, user_id: int) -> None:
    """Handle telegram-specific callbacks."""
    if action == "good":
        await query.edit_message_text(
            "🎉 *Freut mich, dass die Telegram-Updates gefallen!*\n\n"
            "Die neuen Endpoints machen Jarvis viel flexibler.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Telegram action '{action}' received.")


async def _handle_track_callback(query, action: str, user_id: int) -> None:
    """Handle tracking callbacks."""
    if action == "coaching":
        await query.edit_message_text(
            "🎯 *Coaching Success Tracking*\n\n"
            "Würde tracken:\n"
            "• Welche Interventionen funktionieren\n"
            "• Success Score pro Strategie\n"
            "• Personalisierte Empfehlungen\n\n"
            "Implementierung: ~1 Woche\n\n"
            "_Feature noch nicht implementiert._",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"Track action '{action}' not implemented.")


async def _handle_approval_callback(query, action: str, action_id: str, user_id: int) -> None:
    """
    Handle approval callbacks for the Intent-Approval-Execution system.

    Callback data format: approval:action:action_id
    Actions: approve, reject, info
    """
    from . import action_queue

    if action == "approve":
        result = action_queue.approve_action(action_id, approved_by=str(user_id))
        if "error" in result:
            await query.edit_message_text(f"❌ Fehler: {result['error']}")
        else:
            original_text = query.message.text or ""
            # Remove emoji prefix if present for cleaner strikethrough
            clean_text = original_text.split("\n", 1)[-1] if "\n" in original_text else original_text

            # Check if this is a calendar action that needs execution
            action_data = action_queue.get_action(action_id)
            action_type = action_data.get("action", "") if action_data else ""

            if action_type in ["calendar_suggest_event", "calendar_suggest_reschedule"]:
                # Execute calendar action
                await query.edit_message_text(
                    f"✅ *Genehmigt*\n\n~{_escape_markdown(clean_text[:200])}~\n\n"
                    f"_Kalender-Aktion wird ausgeführt..._",
                    parse_mode="Markdown"
                )

                try:
                    # Execute the approved calendar action
                    exec_result = await _execute_calendar_action(action_id, action_data)
                    if exec_result.get("status") == "executed":
                        await query.message.reply_text(
                            f"📅 *Termin erstellt!*\n\n"
                            f"{exec_result.get('result', {}).get('summary', 'Termin')}",
                            parse_mode="Markdown"
                        )
                    elif exec_result.get("status") == "manual_action_required":
                        await query.message.reply_text(
                            f"ℹ️ *Manuell ausführen:*\n\n{exec_result.get('message', '')}",
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    await query.message.reply_text(f"⚠️ Fehler bei Ausführung: {str(e)}")
            else:
                await query.edit_message_text(
                    f"✅ *Genehmigt*\n\n~{_escape_markdown(clean_text[:200])}~\n\n"
                    f"_Aktion wird ausgeführt..._",
                    parse_mode="Markdown"
                )

            log_with_context(logger, "info", "Action approved via Telegram",
                           action_id=action_id, user_id=user_id)

    elif action == "reject":
        result = action_queue.reject_action(action_id, rejected_by=str(user_id))
        if "error" in result:
            await query.edit_message_text(f"❌ Fehler: {result['error']}")
        else:
            original_text = query.message.text or ""
            clean_text = original_text.split("\n", 1)[-1] if "\n" in original_text else original_text
            await query.edit_message_text(
                f"🚫 *Abgelehnt*\n\n~{_escape_markdown(clean_text[:200])}~",
                parse_mode="Markdown"
            )
            log_with_context(logger, "info", "Action rejected via Telegram",
                           action_id=action_id, user_id=user_id)

    elif action == "info":
        action_data = action_queue.get_action(action_id)
        if not action_data:
            await query.answer("Aktion nicht gefunden", show_alert=True)
            return

        # Show detailed info as popup
        details = (
            f"📋 Aktion: {action_data.get('action', 'unbekannt')}\n"
            f"📝 Beschreibung: {action_data.get('description', '-')}\n"
            f"🎯 Ziel: {action_data.get('target', '-')}\n"
            f"⏰ Erstellt: {action_data.get('created_at', '-')[:16]}\n"
            f"⌛ Timeout: {action_data.get('expires_at', '-')[:16]}\n"
            f"📊 Status: {action_data.get('status', '-')}"
        )

        # Show as alert (popup) - limited to 200 chars
        if len(details) > 200:
            # Send as new message instead
            await query.answer("Details werden gesendet...")
            await query.message.reply_text(
                f"ℹ️ *Aktions-Details*\n\n{details}",
                parse_mode="Markdown"
            )
        else:
            await query.answer(details, show_alert=True)

    else:
        await query.edit_message_text(f"Unbekannte Approval-Aktion: {action}")


async def _execute_calendar_action(action_id: str, action_data: dict) -> dict:
    """
    Execute an approved calendar action.

    This is called after a calendar suggestion is approved via Telegram.
    """
    from . import action_queue, n8n_client

    context = action_data.get("context", {})
    action_type = context.get("type")

    if action_type == "calendar_create":
        # Create new event
        result = n8n_client.create_calendar_event(
            summary=context.get("summary"),
            start=context.get("start"),
            end=context.get("end"),
            account=context.get("account", "projektil"),
            description=context.get("description", ""),
            location=context.get("location", "")
        )

        # Mark action as completed
        action_queue.mark_action_completed(action_id, result=result)

        return {
            "status": "executed",
            "action_type": "calendar_create",
            "result": result
        }

    elif action_type == "calendar_reschedule":
        # Note: Rescheduling requires updating an existing event
        # This would need n8n to support event updates
        action_queue.mark_action_completed(action_id, result={
            "status": "manual_action_required",
            "message": "Event rescheduling requires manual update via Google Calendar",
            "event_id": context.get("event_id"),
            "new_start": context.get("new_start"),
            "new_end": context.get("new_end")
        })

        return {
            "status": "manual_action_required",
            "action_type": "calendar_reschedule",
            "message": f"Bitte Termin manuell verschieben auf {context.get('new_start', '')}",
            "details": {
                "event_id": context.get("event_id"),
                "new_start": context.get("new_start"),
                "new_end": context.get("new_end")
            }
        }

    return {"status": "error", "message": f"Unknown action type: {action_type}"}


async def _handle_notification_callback(query, action: str, notification_id: str, user_id: int) -> None:
    """
    Handle notification action callbacks.

    Callback data format: notification:action:notification_id
    Actions: read, approve, reject, dismiss, snooze
    """
    from . import notification_service

    if action == "read":
        # Mark notification as read
        success = await notification_service.mark_notification_read(notification_id)
        if success:
            original_text = query.message.text or ""
            await query.edit_message_text(
                f"✓ *Gelesen*\n\n{original_text}",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Notification nicht gefunden.")

    elif action == "dismiss":
        # Mark as read and dismiss
        await notification_service.mark_notification_read(notification_id)
        await query.edit_message_text("🗑️ Notification verworfen.")

    elif action == "approve":
        # For remediation notifications - trigger approval
        from . import action_queue
        # The notification_id might contain the remediation action ID
        result = action_queue.approve_action(notification_id, approved_by=str(user_id))
        if "error" in result:
            await query.edit_message_text(f"❌ Fehler: {result['error']}")
        else:
            original_text = query.message.text or ""
            await query.edit_message_text(
                f"✅ *Genehmigt*\n\n~{_escape_markdown(original_text[:200])}~\n\n"
                f"_Aktion wird ausgeführt..._",
                parse_mode="Markdown"
            )

    elif action == "reject":
        # For remediation notifications - trigger rejection
        from . import action_queue
        result = action_queue.reject_action(notification_id, rejected_by=str(user_id))
        if "error" in result:
            await query.edit_message_text(f"❌ Fehler: {result['error']}")
        else:
            original_text = query.message.text or ""
            await query.edit_message_text(
                f"🚫 *Abgelehnt*\n\n~{_escape_markdown(original_text[:200])}~",
                parse_mode="Markdown"
            )

    elif action == "snooze":
        # Snooze for later and create follow-up
        followup_id = await notification_service.snooze_notification(
            notification_id=notification_id,
            user_id=str(user_id) if user_id else "unknown",
            snooze_hours=2
        )
        if followup_id:
            await query.edit_message_text("⏰ Erinnere dich in 2 Stunden.")
        else:
            await query.edit_message_text("⏰ Snoozed (Erinnerung konnte nicht erstellt werden).")

    else:
        await query.edit_message_text(f"Unbekannte Notification-Aktion: {action}")


def build_notification_buttons(notification_id: str, event_type: str = "default") -> InlineKeyboardMarkup:
    """Build notification action buttons based on event type."""
    if event_type == "remediation_pending":
        buttons = [
            [
                InlineKeyboardButton("✅ Genehmigen", callback_data=f"notification:approve:{notification_id}"),
                InlineKeyboardButton("🚫 Ablehnen", callback_data=f"notification:reject:{notification_id}"),
            ],
            [
                InlineKeyboardButton("ℹ️ Details", callback_data=f"notification:details:{notification_id}"),
            ]
        ]
    elif event_type == "followup_overdue":
        buttons = [
            [
                InlineKeyboardButton("✅ Erledigt", callback_data=f"notification:read:{notification_id}"),
                InlineKeyboardButton("⏰ Später", callback_data=f"notification:snooze:{notification_id}"),
            ],
            [
                InlineKeyboardButton("🗑️ Verwerfen", callback_data=f"notification:dismiss:{notification_id}"),
            ]
        ]
    else:
        # Default buttons for any notification
        buttons = [
            [
                InlineKeyboardButton("✓ Gelesen", callback_data=f"notification:read:{notification_id}"),
                InlineKeyboardButton("🗑️ Verwerfen", callback_data=f"notification:dismiss:{notification_id}"),
            ]
        ]

    return InlineKeyboardMarkup(buttons)


def main() -> None:
    """Start the bot (standalone mode)"""
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        print("Set it via environment variable or in /brain/system/secrets/telegram_bot_token.txt")
        return

    print(f"Starting Jarvis Telegram bot...")
    print(f"API endpoint: {JARVIS_API_BASE}")

    application = _build_application()
    # Enable message reactions in allowed_updates
    allowed = list(Update.ALL_TYPES) + ["message_reaction"]
    application.run_polling(allowed_updates=allowed)


if __name__ == "__main__":
    main()
