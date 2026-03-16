"""
Skill Loader - Workflow Orchestration Layer

Skills are high-level workflows that orchestrate multiple tools.
Unlike tools (single actions), skills define multi-step processes.

Based on Anthropic's Agent Skills specification:
- SKILL.md with YAML frontmatter
- Progressive disclosure (3 levels)
- Trigger-based activation
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

import yaml

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.skill_loader")

# Skills directory (mounted volume - persists across restarts)
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
SKILLS_DIR = BRAIN_ROOT / "system" / "jarvis-skills"


@dataclass
class Skill:
    """A loaded skill with metadata and content."""
    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    not_triggers: List[str] = field(default_factory=list)
    time_trigger: Optional[str] = None  # e.g., "08:00" for scheduled skills
    tools_required: List[str] = field(default_factory=list)

    # Content levels (progressive disclosure)
    summary: str = ""  # Level 1: Always available (from frontmatter)
    instructions: str = ""  # Level 2: Loaded when skill is activated
    references: Dict[str, str] = field(default_factory=dict)  # Level 3: On-demand

    # Metadata
    source_dir: Optional[Path] = None
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    version: str = "1.0"
    author: str = ""

    # Runtime
    activation_count: int = 0
    last_activated: Optional[datetime] = None


class SkillLoader:
    """
    Load and manage workflow skills.

    Skills differ from tools:
    - Tools = single actions (what Jarvis CAN do)
    - Skills = workflows (HOW Jarvis should do complex tasks)

    Usage:
        # Load all skills at startup
        SkillLoader.load_all()

        # Find relevant skill for a query
        skill = SkillLoader.find_skill_for_query("was steht heute an?")

        # Get skill instructions for agent context
        context = SkillLoader.get_skill_context(skill.name)
    """

    _skills: Dict[str, Skill] = {}
    _initialized: bool = False

    @classmethod
    def initialize(cls) -> Dict[str, Any]:
        """Initialize the skill system."""
        results = {"created_dirs": [], "errors": []}

        try:
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            results["created_dirs"].append(str(SKILLS_DIR))
        except Exception as e:
            results["errors"].append(f"Failed to create {SKILLS_DIR}: {e}")

        cls._initialized = True
        log_with_context(logger, "info", "Skill loader initialized",
                        skills_dir=str(SKILLS_DIR))

        return results

    @classmethod
    def _parse_skill_md(cls, skill_dir: Path) -> Optional[Tuple[Dict[str, Any], str]]:
        """
        Parse a SKILL.md file.

        Returns:
            Tuple of (frontmatter_dict, markdown_body) or None on error
        """
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")

            # Extract YAML frontmatter
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$',
                                         content, re.DOTALL)

            if not frontmatter_match:
                log_with_context(logger, "warning",
                               "No valid frontmatter in SKILL.md",
                               skill_dir=str(skill_dir))
                return None

            yaml_content = frontmatter_match.group(1)
            markdown_body = frontmatter_match.group(2)

            frontmatter = yaml.safe_load(yaml_content)

            return frontmatter, markdown_body

        except yaml.YAMLError as e:
            log_with_context(logger, "error", "YAML parse error in SKILL.md",
                           skill_dir=str(skill_dir), error=str(e))
            return None
        except Exception as e:
            log_with_context(logger, "error", "Failed to parse SKILL.md",
                           skill_dir=str(skill_dir), error=str(e))
            return None

    @classmethod
    def _extract_triggers(cls, description: str) -> List[str]:
        """
        Extract trigger phrases from description.

        Looks for patterns like:
        - "Use when user says X"
        - "Trigger: X, Y, Z"
        - Quoted phrases
        """
        triggers = []

        # Extract quoted phrases
        quoted = re.findall(r'"([^"]+)"', description)
        triggers.extend(quoted)

        # Extract from "Use when" patterns
        use_when = re.search(r'[Uu]se when[^.]*?["\']([^"\']+)["\']', description)
        if use_when:
            triggers.append(use_when.group(1))

        return triggers

    @classmethod
    def load_skill(cls, skill_name: str) -> bool:
        """Load a single skill from its directory."""
        skill_dir = SKILLS_DIR / skill_name

        if not skill_dir.is_dir():
            log_with_context(logger, "warning", "Skill directory not found",
                           skill=skill_name, path=str(skill_dir))
            return False

        parsed = cls._parse_skill_md(skill_dir)
        if parsed is None:
            return False

        frontmatter, body = parsed

        # Extract required fields
        name = frontmatter.get("name", skill_name)
        description = frontmatter.get("description", "")

        if not description:
            log_with_context(logger, "warning", "Skill has no description",
                           skill=skill_name)

        # Extract triggers
        triggers = frontmatter.get("triggers", [])
        if not triggers:
            triggers = cls._extract_triggers(description)

        not_triggers = frontmatter.get("not_triggers", [])

        # Extract metadata
        metadata = frontmatter.get("metadata", {})

        # Load references (Level 3 content)
        references = {}
        refs_dir = skill_dir / "references"
        if refs_dir.exists():
            for ref_file in refs_dir.glob("*.md"):
                references[ref_file.stem] = ref_file.read_text(encoding="utf-8")

        # Create skill object
        skill = Skill(
            name=name,
            description=description,
            triggers=triggers if isinstance(triggers, list) else [triggers],
            not_triggers=not_triggers if isinstance(not_triggers, list) else [not_triggers],
            time_trigger=frontmatter.get("time_trigger"),
            tools_required=frontmatter.get("tools_required", []),
            summary=description,  # Level 1
            instructions=body,  # Level 2
            references=references,  # Level 3
            source_dir=skill_dir,
            version=metadata.get("version", "1.0"),
            author=metadata.get("author", "")
        )

        cls._skills[name] = skill

        log_with_context(logger, "info", "Skill loaded",
                        skill=name, triggers=len(triggers),
                        tools_required=skill.tools_required)

        return True

    @classmethod
    def load_all(cls) -> Dict[str, bool]:
        """Load all skills from the skills directory."""
        if not cls._initialized:
            cls.initialize()

        results = {}

        if not SKILLS_DIR.exists():
            return results

        for skill_dir in SKILLS_DIR.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                results[skill_dir.name] = cls.load_skill(skill_dir.name)

        log_with_context(logger, "info", "Skills loaded",
                        total=len(results),
                        success=sum(results.values()),
                        failed=len(results) - sum(results.values()))

        return results

    @classmethod
    def find_skill_for_query(cls, query: str) -> Optional[Skill]:
        """
        Find the most relevant skill for a query.

        Uses trigger matching and returns the best match.
        Returns None if no skill matches.
        """
        query_lower = query.lower()

        best_match: Optional[Skill] = None
        best_score = 0

        for skill in cls._skills.values():
            # Check not_triggers first (exclusion)
            excluded = False
            for not_trigger in skill.not_triggers:
                if not_trigger.lower() in query_lower:
                    excluded = True
                    break

            if excluded:
                continue

            # Score triggers
            score = 0
            for trigger in skill.triggers:
                trigger_lower = trigger.lower()
                if trigger_lower in query_lower:
                    # Longer matches are better
                    score += len(trigger_lower)

            # Also check description keywords
            desc_words = skill.description.lower().split()
            for word in desc_words:
                if len(word) > 4 and word in query_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = skill

        if best_match:
            best_match.activation_count += 1
            best_match.last_activated = datetime.utcnow()
            log_with_context(logger, "info", "Skill matched for query",
                           skill=best_match.name, score=best_score,
                           query_preview=query[:50])

        return best_match

    @classmethod
    def get_skill_context(cls, skill_name: str, level: int = 2) -> str:
        """
        Get skill context for injection into agent prompt.

        Levels:
            1: Summary only (description)
            2: Full instructions (SKILL.md body)
            3: All including references
        """
        skill = cls._skills.get(skill_name)
        if not skill:
            return ""

        context_parts = []

        # Level 1: Always include summary
        context_parts.append(f"## Active Skill: {skill.name}\n")
        context_parts.append(f"{skill.description}\n")

        if level >= 2:
            # Level 2: Include full instructions
            context_parts.append("\n### Instructions\n")
            context_parts.append(skill.instructions)

        if level >= 3 and skill.references:
            # Level 3: Include references
            context_parts.append("\n### References\n")
            for ref_name, ref_content in skill.references.items():
                context_parts.append(f"\n#### {ref_name}\n{ref_content}\n")

        return "\n".join(context_parts)

    @classmethod
    def get_skills_summary(cls) -> str:
        """
        Get a summary of all available skills for system prompt.
        This is the Level 1 progressive disclosure.
        """
        if not cls._skills:
            return ""

        lines = ["## Available Workflow Skills\n"]

        for skill in cls._skills.values():
            triggers_str = ", ".join(skill.triggers[:3])
            lines.append(f"- **{skill.name}**: {skill.description[:100]}...")
            if triggers_str:
                lines.append(f"  - Triggers: {triggers_str}")

        return "\n".join(lines)

    @classmethod
    def get_skill(cls, name: str) -> Optional[Skill]:
        """Get a specific skill."""
        return cls._skills.get(name)

    @classmethod
    def get_all_skills(cls) -> Dict[str, Skill]:
        """Get all loaded skills."""
        return cls._skills.copy()

    @classmethod
    def get_scheduled_skills(cls, time_str: str) -> List[Skill]:
        """
        Get skills scheduled for a specific time.

        Args:
            time_str: Time in HH:MM format
        """
        return [
            skill for skill in cls._skills.values()
            if skill.time_trigger == time_str
        ]

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get status of the skill system."""
        return {
            "initialized": cls._initialized,
            "skills_dir": str(SKILLS_DIR),
            "skills_dir_exists": SKILLS_DIR.exists(),
            "loaded_skills": len(cls._skills),
            "skills": {
                name: {
                    "description": skill.description[:100],
                    "triggers": skill.triggers,
                    "tools_required": skill.tools_required,
                    "time_trigger": skill.time_trigger,
                    "activation_count": skill.activation_count,
                    "last_activated": skill.last_activated.isoformat() if skill.last_activated else None,
                    "loaded_at": skill.loaded_at.isoformat(),
                    "version": skill.version
                }
                for name, skill in cls._skills.items()
            }
        }

    @classmethod
    def reload(cls, skill_name: str = None) -> Dict[str, Any]:
        """Reload skill(s)."""
        if skill_name:
            success = cls.load_skill(skill_name)
            return {
                "skill": skill_name,
                "success": success,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            results = cls.load_all()
            return {
                "reloaded": results,
                "success_count": sum(results.values()),
                "total": len(results),
                "timestamp": datetime.utcnow().isoformat()
            }


# Convenience functions
def get_skill_for_query(query: str) -> Optional[Skill]:
    """Find relevant skill for a query."""
    return SkillLoader.find_skill_for_query(query)


def initialize_skills() -> Dict[str, Any]:
    """Initialize and load all skills."""
    SkillLoader.initialize()
    return SkillLoader.load_all()


def get_active_skill_context(query: str) -> str:
    """Get skill context if a skill matches the query."""
    skill = SkillLoader.find_skill_for_query(query)
    if skill:
        return SkillLoader.get_skill_context(skill.name, level=2)
    return ""
