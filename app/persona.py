"""
Jarvis Personality Profile System
Defines response styles/personas that affect tone and formatting, not retrieval logic.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.persona")

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
PERSONA_CONFIG_PATH = BRAIN_ROOT / "system" / "prompts" / "persona_profiles.json"

# Cached config
_persona_cache: Optional[Dict] = None


@dataclass
class PersonaTone:
    """Tone configuration for a persona"""
    style: List[str] = field(default_factory=list)
    emoji_level: str = "none"
    directness: str = "medium"


@dataclass
class PersonaFormat:
    """Formatting configuration for a persona"""
    use_headings: bool = True
    use_bullets: bool = True
    max_sections: int = 6
    preferred_length: str = "medium"
    include_summary_top: bool = True


@dataclass
class Persona:
    """Represents a personality profile (v2 schema)"""
    id: str
    name: str
    intent: str
    tone: PersonaTone
    format: PersonaFormat
    requirements: List[str]
    forbidden: List[str]
    one_liner_example: str


def _load_config() -> Dict:
    """Load persona config from JSON file, with caching"""
    global _persona_cache
    if _persona_cache is not None:
        return _persona_cache

    if not PERSONA_CONFIG_PATH.exists():
        log_with_context(logger, "warning", "Persona config not found",
                        path=str(PERSONA_CONFIG_PATH))
        _persona_cache = {"personas": [], "default_persona_id": "micha_default"}
        return _persona_cache

    try:
        with open(PERSONA_CONFIG_PATH, "r", encoding="utf-8") as f:
            _persona_cache = json.load(f)
        personas = _persona_cache.get("personas", [])
        count = len(personas) if isinstance(personas, list) else len(personas.keys())
        log_with_context(logger, "info", "Persona config loaded", personas=count)
        return _persona_cache
    except json.JSONDecodeError as e:
        log_with_context(logger, "error", "Invalid persona config JSON", error=str(e))
        _persona_cache = {"personas": [], "default_persona_id": "micha_default"}
        return _persona_cache


def reload_config() -> None:
    """Force reload of persona config (for hot-reloading)"""
    global _persona_cache
    _persona_cache = None
    _load_config()


def get_default_persona_id() -> str:
    """Get the default persona ID"""
    config = _load_config()
    # Support both old and new key names
    return config.get("default_persona_id") or config.get("default_persona", "micha_default")


def _find_persona_data(persona_id: str) -> Optional[Dict]:
    """Find persona data by ID, supporting both array and dict formats"""
    config = _load_config()
    personas = config.get("personas", [])

    # New format: personas is an array
    if isinstance(personas, list):
        for p in personas:
            if p.get("id") == persona_id:
                return p
        return None

    # Old format: personas is a dict
    if isinstance(personas, dict):
        if persona_id in personas:
            data = personas[persona_id].copy()
            data["id"] = persona_id
            return data
        return None

    return None


def get_persona(persona_id: str) -> Optional[Persona]:
    """Get a persona by ID"""
    p = _find_persona_data(persona_id)
    if not p:
        return None

    # Parse tone (handles both old array and new object format)
    tone_data = p.get("tone", {})
    if isinstance(tone_data, list):
        # Old format: tone was a list of strings
        tone = PersonaTone(style=tone_data)
    else:
        # New format: tone is an object
        tone = PersonaTone(
            style=tone_data.get("style", []),
            emoji_level=tone_data.get("emoji_level", "none"),
            directness=tone_data.get("directness", "medium")
        )

    # Parse format (handles both old "formatting" and new "format" keys)
    fmt_data = p.get("format") or p.get("formatting", {})
    format_config = PersonaFormat(
        use_headings=fmt_data.get("use_headings", True),
        use_bullets=fmt_data.get("use_bullets", fmt_data.get("use_bullet_points", True)),
        max_sections=fmt_data.get("max_sections", 6),
        preferred_length=fmt_data.get("preferred_length", "medium"),
        include_summary_top=fmt_data.get("include_summary_top", True)
    )

    return Persona(
        id=p.get("id", persona_id),
        name=p.get("name", persona_id),
        intent=p.get("intent") or p.get("description", ""),
        tone=tone,
        format=format_config,
        requirements=p.get("requirements", []),
        forbidden=p.get("forbidden", []),
        one_liner_example=p.get("one_liner_example") or p.get("example", "")
    )


def list_personas() -> List[Dict[str, str]]:
    """List all available personas with ID and description"""
    config = _load_config()
    personas = config.get("personas", [])
    default_id = get_default_persona_id()

    result = []

    # New format: personas is an array
    if isinstance(personas, list):
        for p in personas:
            result.append({
                "id": p.get("id", ""),
                "name": p.get("name", p.get("id", "")),
                "intent": p.get("intent", ""),
                "is_default": p.get("id") == default_id
            })
    # Old format: personas is a dict
    elif isinstance(personas, dict):
        for pid, p in personas.items():
            result.append({
                "id": pid,
                "name": p.get("name", pid),
                "intent": p.get("description", ""),
                "is_default": pid == default_id
            })

    return result


def generate_style_prompt(persona_id: str) -> str:
    """
    Generate a system-style prompt string from persona config.
    This is appended to the main system prompt to influence response style.
    """
    persona = get_persona(persona_id)
    if not persona:
        # Fallback to default
        default_id = get_default_persona_id()
        persona = get_persona(default_id)
        if not persona:
            return ""

    lines = []
    lines.append("=== RESPONSE STYLE ===")
    lines.append(f"Persona: {persona.name}")
    lines.append("")

    # Intent
    if persona.intent:
        lines.append(f"Intent: {persona.intent}")
        lines.append("")

    # Tone
    if persona.tone.style:
        style_str = ", ".join(persona.tone.style)
        lines.append(f"Tone: {style_str}")
        if persona.tone.directness != "medium":
            lines.append(f"Directness: {persona.tone.directness}")
        if persona.tone.emoji_level != "none":
            lines.append(f"Emoji level: {persona.tone.emoji_level}")
        lines.append("")

    # Formatting rules
    fmt = persona.format
    lines.append("Formatting guidelines:")
    if fmt.use_headings:
        lines.append("- Use headings to structure responses")
    if fmt.use_bullets:
        lines.append("- Use bullet points for lists")
    if fmt.include_summary_top:
        lines.append("- Start with a brief summary")
    lines.append(f"- Max sections: {fmt.max_sections}")
    lines.append(f"- Preferred length: {fmt.preferred_length}")
    lines.append("")

    # Requirements
    if persona.requirements:
        lines.append("Requirements:")
        for req in persona.requirements:
            lines.append(f"- {req}")
        lines.append("")

    # Forbidden behaviors
    if persona.forbidden:
        lines.append("FORBIDDEN:")
        for item in persona.forbidden:
            # Don't add extra capitalization if it already starts with "No"
            if item.startswith("No "):
                lines.append(f"- {item}")
            else:
                lines.append(f"- {item}")
        lines.append("")

    # Example
    if persona.one_liner_example:
        lines.append(f"Example response style: \"{persona.one_liner_example}\"")

    return "\n".join(lines)


def apply_style_wrapper(persona_id: str, text: str) -> str:
    """
    Apply simple formatting wrapper based on persona.
    This is a lightweight preview - actual LLM responses will follow the style prompt.
    """
    persona = get_persona(persona_id)
    if not persona:
        default_id = get_default_persona_id()
        persona = get_persona(default_id)
        if not persona:
            return text

    # For preview purposes, add a simple style indicator
    style_hint = f"[Style: {persona.name}]"

    tone_str = ", ".join(persona.tone.style) if persona.tone.style else "neutral"

    # Build preview output
    output_lines = [
        style_hint,
        f"Intent: {persona.intent}",
        f"Tone: {tone_str} (directness: {persona.tone.directness})",
        "",
        "--- Content ---",
        text,
        "",
        "--- Format applied ---",
    ]

    fmt = persona.format
    if fmt.use_bullets:
        output_lines.append("- Bullets: enabled")
    if fmt.use_headings:
        output_lines.append("- Headings: enabled")
    if fmt.include_summary_top:
        output_lines.append("- Summary at top: enabled")
    output_lines.append(f"- Max sections: {fmt.max_sections}")
    output_lines.append(f"- Length: {fmt.preferred_length}")

    if persona.requirements:
        output_lines.append("")
        output_lines.append("--- Requirements ---")
        for req in persona.requirements[:3]:  # Show first 3
            output_lines.append(f"- {req}")

    return "\n".join(output_lines)


def get_persona_context(persona_id: str) -> Dict[str, Any]:
    """Get persona context for API response"""
    persona = get_persona(persona_id)
    if not persona:
        return {"persona_id": persona_id, "error": "not_found"}

    return {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "intent": persona.intent,
        "tone": {
            "style": persona.tone.style,
            "directness": persona.tone.directness,
            "emoji_level": persona.tone.emoji_level,
        },
    }


# ============ Channel Styles (v1.1) ============

def get_channel_style(channel: str) -> Optional[Dict[str, Any]]:
    """
    Get channel-specific style modifiers.
    Channels: email, whatsapp, google_chat, linkedin, presentation, document
    """
    config = _load_config()
    channel_styles = config.get("channel_styles", {})

    # Normalize channel name
    channel_lower = channel.lower().strip()

    # Direct match
    if channel_lower in channel_styles:
        return channel_styles[channel_lower]

    # Aliases
    aliases = {
        "mail": "email",
        "e-mail": "email",
        "wa": "whatsapp",
        "gchat": "google_chat",
        "hangouts": "google_chat",
        "li": "linkedin",
        "pptx": "presentation",
        "slides": "presentation",
        "doc": "document",
        "docs": "document",
        "md": "document",
    }

    if channel_lower in aliases:
        return channel_styles.get(aliases[channel_lower])

    return None


def list_channel_styles() -> List[Dict[str, str]]:
    """List all available channel styles"""
    config = _load_config()
    channel_styles = config.get("channel_styles", {})

    result = []
    for channel_id, style in channel_styles.items():
        result.append({
            "id": channel_id,
            "name": style.get("name", channel_id),
            "description": style.get("description", "")
        })

    return result


def generate_channel_style_prompt(channel: str) -> str:
    """
    Generate a prompt section for channel-specific communication style.
    This modifies tone and format based on the communication channel.
    """
    style = get_channel_style(channel)
    if not style:
        return ""

    lines = []
    lines.append(f"=== CHANNEL STYLE: {style.get('name', channel).upper()} ===")
    lines.append(f"Context: {style.get('description', '')}")
    lines.append("")

    # Tone modifiers
    tone_mods = style.get("tone_modifiers", {})
    if tone_mods:
        lines.append("Tone adjustments for this channel:")
        if tone_mods.get("formality"):
            lines.append(f"- Formality: {tone_mods['formality']}")
        if tone_mods.get("emoji_level"):
            lines.append(f"- Emoji usage: {tone_mods['emoji_level']}")
        if tone_mods.get("directness"):
            lines.append(f"- Directness: {tone_mods['directness']}")
        lines.append("")

    # Format
    fmt = style.get("format", {})
    if fmt:
        lines.append("Format for this channel:")
        if fmt.get("include_greeting"):
            lines.append("- Include appropriate greeting")
        if fmt.get("include_signature"):
            lines.append("- Include signature/closing")
        if fmt.get("preferred_length"):
            lines.append(f"- Preferred length: {fmt['preferred_length']}")
        lines.append("")

    # Guidelines
    guidelines = style.get("guidelines", [])
    if guidelines:
        lines.append("Channel-specific guidelines:")
        for g in guidelines:
            lines.append(f"- {g}")

    return "\n".join(lines)


def generate_combined_style_prompt(persona_id: str, channel: str = None) -> str:
    """
    Generate a combined style prompt with both persona and channel modifiers.
    Channel style overrides/augments persona settings where applicable.
    """
    # Get base persona prompt
    persona_prompt = generate_style_prompt(persona_id)

    # If no channel specified, return just the persona prompt
    if not channel:
        return persona_prompt

    # Get channel style prompt
    channel_prompt = generate_channel_style_prompt(channel)

    if not channel_prompt:
        return persona_prompt

    # Combine: persona first, then channel modifiers
    return f"{persona_prompt}\n\n{channel_prompt}"
