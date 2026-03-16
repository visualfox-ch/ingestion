"""
LinkedIn Coach Tools for Jarvis.

Enables Jarvis to generate LinkedIn content (posts, comments, reposts) with:
- Personal voice/style based on persona
- Anti-AI-Voice filtering
- Coach mode (ask questions first) or Auto-Draft mode
- Playbook-based phrase libraries for authentic content
"""

import logging
import re
import json
import random
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Database connection helper
def _get_db_connection():
    """Get database connection for playbook queries."""
    try:
        import asyncpg
        import asyncio
        import os

        async def _connect():
            return await asyncpg.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=int(os.getenv("POSTGRES_PORT", 5432)),
                user=os.getenv("POSTGRES_USER", "jarvis"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
                database=os.getenv("POSTGRES_DB", "jarvis")
            )

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_connect())
    except Exception as e:
        logger.warning(f"Could not connect to database: {e}")
        return None


async def _load_playbook_async(domain: str = "linkedin_comment") -> Optional[Dict[str, Any]]:
    """Load a playbook from database with all sections and phrases."""
    try:
        import asyncpg
        import os

        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "jarvis")
        )

        try:
            # Get playbook
            playbook = await conn.fetchrow(
                "SELECT * FROM content_playbooks WHERE domain = $1 AND is_active = true LIMIT 1",
                domain
            )

            if not playbook:
                return None

            playbook_id = playbook['id']

            # Get formula
            formula = await conn.fetchrow(
                "SELECT * FROM content_playbook_formulas WHERE playbook_id = $1 LIMIT 1",
                playbook_id
            )

            # Get sections with phrases
            sections = await conn.fetch(
                """
                SELECT s.*,
                    array_agg(json_build_object('phrase', p.phrase, 'category', p.category)) as phrases
                FROM content_playbook_sections s
                LEFT JOIN content_playbook_phrases p ON p.section_id = s.id AND p.is_active = true
                WHERE s.playbook_id = $1
                GROUP BY s.id
                ORDER BY s.sort_order
                """,
                playbook_id
            )

            # Get forbidden phrases
            forbidden = await conn.fetch(
                "SELECT phrase, reason FROM content_playbook_forbidden WHERE playbook_id = $1",
                playbook_id
            )

            # Get recommendations
            recommendations = await conn.fetch(
                "SELECT category, recommendation FROM content_playbook_recommendations WHERE playbook_id = $1",
                playbook_id
            )

            return {
                "name": playbook['name'],
                "domain": playbook['domain'],
                "version": playbook['version'],
                "description": playbook['description'],
                "purpose": playbook['purpose'],
                "golden_rule": playbook['golden_rule'],
                "formula": {
                    "name": formula['name'] if formula else None,
                    "formula": formula['formula'] if formula else None,
                    "example": formula['example'] if formula else None
                } if formula else None,
                "sections": {
                    s['section_key']: {
                        "name": s['section_name'],
                        "description": s['description'],
                        "usage_context": s['usage_context'],
                        "phrases": [p for p in s['phrases'] if p and p.get('phrase')]
                    }
                    for s in sections
                },
                "forbidden": [{"phrase": f['phrase'], "reason": f['reason']} for f in forbidden],
                "recommendations": {
                    r['category']: r['recommendation'] for r in recommendations
                }
            }

        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Could not load playbook: {e}")
        return None


def _load_playbook(domain: str = "linkedin_comment") -> Optional[Dict[str, Any]]:
    """Load playbook using sync psycopg2 connection."""
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "jarvis")
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Get playbook
            cur.execute(
                "SELECT * FROM content_playbooks WHERE domain = %s AND is_active = true LIMIT 1",
                (domain,)
            )
            playbook = cur.fetchone()

            if not playbook:
                return None

            playbook_id = playbook['id']

            # Get formula
            cur.execute(
                "SELECT * FROM content_playbook_formulas WHERE playbook_id = %s LIMIT 1",
                (playbook_id,)
            )
            formula = cur.fetchone()

            # Get sections
            cur.execute(
                "SELECT * FROM content_playbook_sections WHERE playbook_id = %s ORDER BY sort_order",
                (playbook_id,)
            )
            sections_raw = cur.fetchall()

            # Get phrases for each section
            sections = {}
            for s in sections_raw:
                cur.execute(
                    "SELECT phrase, category FROM content_playbook_phrases WHERE section_id = %s AND is_active = true",
                    (s['id'],)
                )
                phrases = cur.fetchall()
                sections[s['section_key']] = {
                    "name": s['section_name'],
                    "description": s['description'],
                    "usage_context": s['usage_context'],
                    "phrases": [{"phrase": p['phrase'], "category": p['category']} for p in phrases]
                }

            # Get forbidden phrases
            cur.execute(
                "SELECT phrase, reason FROM content_playbook_forbidden WHERE playbook_id = %s",
                (playbook_id,)
            )
            forbidden = cur.fetchall()

            # Get target groups with accounts
            targets = []
            cur.execute(
                "SELECT * FROM content_playbook_targets WHERE playbook_id = %s ORDER BY sort_order",
                (playbook_id,)
            )
            target_groups = cur.fetchall()
            for tg in target_groups:
                cur.execute(
                    "SELECT account_name, account_type, is_priority FROM content_playbook_target_accounts WHERE target_group_id = %s",
                    (tg['id'],)
                )
                accounts = cur.fetchall()
                targets.append({
                    "group_name": tg['group_name'],
                    "description": tg['group_description'],
                    "why_important": tg['why_important'],
                    "accounts": [{"name": a['account_name'], "type": a['account_type'], "priority": a['is_priority']} for a in accounts]
                })

            # Get post types
            cur.execute(
                "SELECT type_name, type_key, description, why_it_works, example_post FROM content_playbook_post_types WHERE playbook_id = %s ORDER BY sort_order",
                (playbook_id,)
            )
            post_types = cur.fetchall()

            # Get strategy guidelines
            cur.execute(
                "SELECT category, guideline, priority FROM content_playbook_strategy WHERE playbook_id = %s ORDER BY category, priority",
                (playbook_id,)
            )
            strategy_raw = cur.fetchall()
            strategy = {}
            for s in strategy_raw:
                cat = s['category']
                if cat not in strategy:
                    strategy[cat] = []
                strategy[cat].append(s['guideline'])

            # Get style elements (Micha-Style)
            cur.execute(
                "SELECT element_type, element_name, description, examples FROM content_playbook_style_elements WHERE playbook_id = %s ORDER BY element_type, sort_order",
                (playbook_id,)
            )
            style_raw = cur.fetchall()
            style_elements = {}
            for se in style_raw:
                et = se['element_type']
                if et not in style_elements:
                    style_elements[et] = []
                style_elements[et].append({
                    "name": se['element_name'],
                    "description": se['description'],
                    "examples": se['examples'] if se['examples'] else []
                })

            # Get comment examples
            cur.execute(
                "SELECT category, comment_text, is_favorite FROM content_playbook_comment_examples WHERE playbook_id = %s ORDER BY category",
                (playbook_id,)
            )
            examples_raw = cur.fetchall()
            comment_examples = {}
            for ex in examples_raw:
                cat = ex['category']
                if cat not in comment_examples:
                    comment_examples[cat] = []
                comment_examples[cat].append({
                    "text": ex['comment_text'],
                    "is_favorite": ex['is_favorite']
                })

            return {
                "name": playbook['name'],
                "domain": playbook['domain'],
                "version": playbook['version'],
                "description": playbook['description'],
                "purpose": playbook['purpose'],
                "golden_rule": playbook['golden_rule'],
                "formula": {
                    "name": formula['name'] if formula else None,
                    "formula": formula['formula'] if formula else None,
                    "example": formula['example'] if formula else None
                } if formula else None,
                "sections": sections,
                "forbidden": [{"phrase": f['phrase'], "reason": f['reason']} for f in forbidden],
                "targets": targets,
                "post_types": [
                    {
                        "name": pt['type_name'],
                        "key": pt['type_key'],
                        "description": pt['description'],
                        "why_it_works": pt['why_it_works'],
                        "example": pt['example_post']
                    }
                    for pt in post_types
                ],
                "strategy": strategy,
                "style_elements": style_elements,
                "comment_examples": comment_examples
            }

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.warning(f"Playbook load failed: {e}")
        return None


def _get_random_phrase(playbook: Dict[str, Any], section_key: str, category: Optional[str] = None) -> Optional[str]:
    """Get a random phrase from a playbook section."""
    if not playbook or 'sections' not in playbook:
        return None

    section = playbook.get('sections', {}).get(section_key)
    if not section or not section.get('phrases'):
        return None

    phrases = section['phrases']
    if category:
        phrases = [p for p in phrases if p.get('category') == category]

    if not phrases:
        return None

    return random.choice(phrases).get('phrase')

# Content pillars for topic suggestions
CONTENT_PILLARS = [
    "AI & Automation",
    "Media-Tech",
    "Entrepreneurship",
    "Tech Leadership"
]

# Forbidden AI-sounding phrases (loaded from persona, but kept here as fallback)
FORBIDDEN_PHRASES = [
    "let's dive in",
    "let's unpack",
    "game-changer",
    "game changer",
    "unlock your potential",
    "here's the thing",
    "i'm excited to announce",
    "thrilled to share",
    "leverage",
    "synergy",
    "thought leader",
    "passionate about",
    "at the end of the day",
    "circle back",
    "move the needle",
    "deep dive",
    "taking it to the next level",
    "paradigm shift",
    "disrupt",
    "ecosystem",
    "holistic approach",
    "best practices",
    "value proposition",
    "streamline",
    "optimize",
    "scalable",
    "robust",
    "cutting-edge",
    "innovative solution",
    "seamless integration",
    "empower",
    "facilitate",
    "utilize",
]

# Tool definitions for registration
LINKEDIN_COACH_TOOLS = [
    {
        "name": "linkedin_generate_content",
        "description": "Generate LinkedIn content (post, comment, or repost). Use coach_mode=true to first get questions about goal/audience, or coach_mode=false for direct draft generation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["post", "comment", "repost"],
                    "description": "Type of content: 'post' for original post, 'comment' for commenting on another post, 'repost' for sharing with own take"
                },
                "goal": {
                    "type": "string",
                    "description": "What do you want to achieve with this content? (e.g., 'share learnings', 'start discussion', 'build authority')"
                },
                "audience": {
                    "type": "string",
                    "description": "Who is the target audience? (e.g., 'tech founders', 'developers', 'business leaders')"
                },
                "source_post": {
                    "type": "string",
                    "description": "For comment/repost: the original post content to respond to"
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Main points or ideas to include"
                },
                "coach_mode": {
                    "type": "boolean",
                    "description": "If true, first ask clarifying questions. If false, generate draft directly.",
                    "default": True
                },
                "language": {
                    "type": "string",
                    "enum": ["de", "en", "auto"],
                    "description": "Language for content: 'de' for German, 'en' for English, 'auto' to match source_post or default to German",
                    "default": "auto"
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional constraints (e.g., 'max 100 words', 'no emojis', 'include question')"
                }
            },
            "required": ["mode"]
        }
    },
    {
        "name": "linkedin_improve_draft",
        "description": "Improve an existing LinkedIn draft - make it more engaging, fix AI-sounding phrases, optimize structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "draft": {
                    "type": "string",
                    "description": "The draft text to improve"
                },
                "focus": {
                    "type": "string",
                    "enum": ["hook", "engagement", "clarity", "anti_ai", "all"],
                    "description": "What to focus on: 'hook' for better opening, 'engagement' for more interaction, 'clarity' for clearer message, 'anti_ai' to remove AI phrases, 'all' for comprehensive improvement",
                    "default": "all"
                }
            },
            "required": ["draft"]
        }
    },
    {
        "name": "linkedin_check_ai_voice",
        "description": "Check a text for AI-sounding phrases and suggest replacements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to check for AI-sounding phrases"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "linkedin_suggest_topics",
        "description": "Get topic suggestions for LinkedIn posts based on content pillars.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pillar": {
                    "type": "string",
                    "enum": ["AI & Automation", "Media-Tech", "Entrepreneurship", "Tech Leadership", "all"],
                    "description": "Content pillar to get suggestions for, or 'all' for mix",
                    "default": "all"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of topic suggestions to return",
                    "default": 5
                }
            }
        }
    },
    {
        "name": "linkedin_get_style_examples",
        "description": "Get example posts/comments from the style library for reference. (Note: RAG collection needs content first)",
        "input_schema": {
            "type": "object",
            "properties": {
                "content_type": {
                    "type": "string",
                    "enum": ["post", "comment", "repost", "any"],
                    "description": "Type of content to get examples for",
                    "default": "any"
                },
                "topic": {
                    "type": "string",
                    "description": "Topic to filter examples by (optional)"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of examples to return",
                    "default": 3
                }
            }
        }
    },
    {
        "name": "linkedin_get_playbook",
        "description": "Get the LinkedIn playbook with phrase libraries, target accounts, post types and strategy. Use section parameter to get specific parts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["all", "einstieg", "praxis", "immersive", "mapping", "venue", "respekt", "persoenlich", "abschluss", "formula", "forbidden", "targets", "post_types", "strategy", "style", "comment_formula", "usps", "avoid", "examples"],
                    "description": "Which section: 'all' complete, 'targets' accounts, 'post_types' formats, 'strategy' guidelines, 'style' Micha-Style elements, 'examples' ready-to-use comment examples by category",
                    "default": "all"
                },
                "example_category": {
                    "type": "string",
                    "enum": ["project_launch", "immersive", "mapping", "technology", "venue", "collegial", "personal", "signature"],
                    "description": "When section='examples', filter by category"
                },
                "include_random_combo": {
                    "type": "boolean",
                    "description": "If true, also returns a random Einstieg+Praxis+Respekt combo as example",
                    "default": True
                }
            }
        }
    },
    {
        "name": "linkedin_save_to_playbook",
        "description": "Save a learning about Micha's LinkedIn style to the playbook database. Use this when you learn something new about his content patterns, brand positioning, signature phrases, or real post examples.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learning_type": {
                    "type": "string",
                    "enum": ["style_element", "example", "signature_phrase", "forbidden", "network_contact"],
                    "description": "Type of learning: 'style_element' for content patterns/USPs/brand, 'example' for real post examples, 'signature_phrase' for memorable phrases, 'forbidden' for things to avoid, 'network_contact' for important contacts"
                },
                "category": {
                    "type": "string",
                    "description": "Category within type. For style_element: brand_position/content_pattern/repost_style/usp/avoid. For example: post_event_recap/repost_tech_nostalgia/repost_proud_colleague etc."
                },
                "name": {
                    "type": "string",
                    "description": "Short name/title for this learning"
                },
                "content": {
                    "type": "string",
                    "description": "The actual content - description for style elements, full text for examples/phrases"
                },
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Example phrases that demonstrate this pattern (for style_element type)"
                },
                "is_favorite": {
                    "type": "boolean",
                    "description": "Mark as favorite/important",
                    "default": False
                }
            },
            "required": ["learning_type", "category", "name", "content"]
        }
    },
    {
        "name": "linkedin_check_save_confidence",
        "description": "Check if Jarvis should auto-save a learning or ask the user first. Returns confidence score and recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learning_type": {
                    "type": "string",
                    "enum": ["style_element", "example", "signature_phrase", "forbidden", "network_contact"],
                    "description": "Type of learning to check confidence for"
                },
                "context_pattern": {
                    "type": "string",
                    "enum": ["user_shared_own_post", "user_corrected", "user_mentioned_contact", "user_feedback", "pattern_detected", "user_dislikes_phrase", "user_uses_repeatedly", "inferred_preference"],
                    "description": "What triggered this potential learning"
                }
            },
            "required": ["learning_type", "context_pattern"]
        }
    },
    {
        "name": "linkedin_record_save_feedback",
        "description": "Record user's response when asked 'Soll ich das speichern?'. This helps Jarvis learn when to auto-save vs. ask.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learning_type": {
                    "type": "string",
                    "description": "Type of learning that was proposed"
                },
                "context_pattern": {
                    "type": "string",
                    "description": "What triggered the question"
                },
                "user_response": {
                    "type": "string",
                    "enum": ["yes", "no", "later", "always", "never"],
                    "description": "User's response: 'yes'=save this, 'no'=don't save, 'always'=always auto-save this type, 'never'=never save this type"
                }
            },
            "required": ["learning_type", "context_pattern", "user_response"]
        }
    }
]


def linkedin_generate_content(
    mode: str,
    goal: Optional[str] = None,
    audience: Optional[str] = None,
    source_post: Optional[str] = None,
    key_points: Optional[List[str]] = None,
    coach_mode: bool = True,
    language: str = "auto",
    constraints: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate LinkedIn content (post, comment, or repost).

    In coach_mode=True, returns questions to clarify intent.
    In coach_mode=False, generates a draft based on inputs.
    """
    try:
        # Determine language
        detected_lang = language
        if language == "auto":
            # If source_post exists, try to detect language
            if source_post:
                # Simple heuristic: check for German words
                german_indicators = ["und", "der", "die", "das", "ist", "ein", "eine", "nicht", "aber"]
                source_lower = source_post.lower()
                german_count = sum(1 for word in german_indicators if f" {word} " in f" {source_lower} ")
                detected_lang = "de" if german_count >= 2 else "en"
            else:
                detected_lang = "de"  # Default to German

        if coach_mode:
            # Coach mode: return questions to clarify
            questions = _get_coaching_questions(mode, goal, audience, source_post, key_points)
            return {
                "status": "coaching",
                "mode": mode,
                "questions": questions,
                "message": "Bitte beantworte diese Fragen, damit ich den perfekten Content erstellen kann:" if detected_lang == "de" else "Please answer these questions so I can create the perfect content:",
                "next_step": "Call linkedin_generate_content again with coach_mode=false and the answers filled in"
            }

        # Auto-draft mode: generate content
        draft = _generate_draft(mode, goal, audience, source_post, key_points, detected_lang, constraints)

        # Check for AI voice
        ai_check = _check_ai_voice(draft["content"])

        return {
            "status": "draft_ready",
            "mode": mode,
            "language": detected_lang,
            "draft": draft,
            "ai_voice_check": ai_check,
            "tips": _get_mode_tips(mode, detected_lang)
        }

    except Exception as e:
        logger.error(f"Error generating LinkedIn content: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_improve_draft(
    draft: str,
    focus: str = "all"
) -> Dict[str, Any]:
    """
    Improve an existing LinkedIn draft.
    """
    try:
        improvements = []
        improved_text = draft

        # Check AI voice regardless of focus
        ai_check = _check_ai_voice(draft)
        if ai_check["found"]:
            improvements.append({
                "type": "ai_voice",
                "issues": ai_check["phrases_found"],
                "suggestion": "Diese Phrasen klingen zu generisch/AI-artig. Ersetze sie durch persoenlichere Formulierungen."
            })

        # Focus-specific improvements
        if focus in ["hook", "all"]:
            hook_analysis = _analyze_hook(draft)
            if not hook_analysis["strong"]:
                improvements.append({
                    "type": "hook",
                    "current": hook_analysis["current_hook"],
                    "suggestion": hook_analysis["suggestion"]
                })

        if focus in ["engagement", "all"]:
            engagement = _analyze_engagement(draft)
            if not engagement["has_cta"]:
                improvements.append({
                    "type": "engagement",
                    "issue": "Kein klarer Call-to-Action oder Frage am Ende",
                    "suggestion": "Fuege eine Frage oder Aufforderung hinzu, um Interaktion zu foerdern."
                })

        if focus in ["clarity", "all"]:
            clarity = _analyze_clarity(draft)
            if clarity["issues"]:
                improvements.append({
                    "type": "clarity",
                    "issues": clarity["issues"],
                    "suggestion": "Vereinfache diese Stellen fuer bessere Lesbarkeit."
                })

        return {
            "status": "analysis_complete",
            "original_length": len(draft),
            "improvements": improvements,
            "improvement_count": len(improvements),
            "ai_voice_clean": not ai_check["found"],
            "recommendation": "Ueberarbeite basierend auf den Vorschlaegen und pruefe erneut." if improvements else "Der Draft sieht gut aus!"
        }

    except Exception as e:
        logger.error(f"Error improving draft: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_check_ai_voice(text: str) -> Dict[str, Any]:
    """
    Check text for AI-sounding phrases.
    """
    try:
        result = _check_ai_voice(text)

        # Add replacement suggestions
        replacements = {}
        for phrase in result.get("phrases_found", []):
            replacements[phrase] = _get_replacement_suggestion(phrase)

        return {
            "status": "checked",
            "text_length": len(text),
            "ai_phrases_found": result["found"],
            "phrases": result.get("phrases_found", []),
            "count": result.get("count", 0),
            "replacements": replacements,
            "verdict": "Text klingt authentisch" if not result["found"] else f"{result['count']} AI-Phrasen gefunden - ersetzen empfohlen"
        }

    except Exception as e:
        logger.error(f"Error checking AI voice: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_suggest_topics(
    pillar: str = "all",
    count: int = 5
) -> Dict[str, Any]:
    """
    Suggest topics for LinkedIn posts.
    """
    try:
        topics = []

        topic_ideas = {
            "AI & Automation": [
                "Ein Tool, das meinen Workflow diese Woche veraendert hat",
                "Warum die meisten AI-Implementierungen scheitern (und wie es besser geht)",
                "3 Automatisierungen, die mir taeglich Zeit sparen",
                "Der Unterschied zwischen AI-Hype und echtem Nutzen",
                "Wie ich AI in meinem Team eingefuehrt habe - Lessons Learned",
                "Agent-basierte Workflows: Was funktioniert, was nicht",
                "Die unterschaetzte Rolle von Prompts in der AI-Nutzung"
            ],
            "Media-Tech": [
                "Behind the Scenes: Wie wir [Event/Produktion] technisch umgesetzt haben",
                "Die Evolution von Live-Streaming - wo wir heute stehen",
                "Warum Audio oft wichtiger ist als Video",
                "Tech-Stack fuer moderne Medienproduktion",
                "Fehler, die wir bei Live-Events gemacht haben",
                "Die Zukunft von hybridem Content"
            ],
            "Entrepreneurship": [
                "Eine Entscheidung, die mein Business veraendert hat",
                "Was ich ueber Hiring in 10 Jahren gelernt habe",
                "Der Unterschied zwischen Busy und Produktiv",
                "Warum ich diese Partnerschaft/Projekt abgelehnt habe",
                "Cashflow vs. Profit - was ich zu spaet verstanden habe",
                "Die beste Investition ins eigene Business"
            ],
            "Tech Leadership": [
                "Wie ich technische Schulden im Team adressiere",
                "Code Reviews: Was funktioniert, was nervt alle",
                "Remote-Fuehrung: Meine Learnings nach [X] Jahren",
                "Warum ich die beste technische Loesung nicht immer waehle",
                "Onboarding von Entwicklern - unser aktueller Prozess",
                "Meetings, die tatsaechlich nuetzlich sind"
            ]
        }

        if pillar == "all":
            # Mix from all pillars
            for p in CONTENT_PILLARS:
                if p in topic_ideas:
                    topics.extend([(p, t) for t in topic_ideas[p][:2]])
        elif pillar in topic_ideas:
            topics = [(pillar, t) for t in topic_ideas[pillar]]

        # Limit to count
        topics = topics[:count]

        return {
            "status": "suggestions_ready",
            "pillar_filter": pillar,
            "topics": [
                {"pillar": p, "topic": t, "format_suggestion": _get_format_for_topic(t)}
                for p, t in topics
            ],
            "count": len(topics),
            "tip": "Waehle ein Thema und ruf linkedin_generate_content mit key_points auf"
        }

    except Exception as e:
        logger.error(f"Error suggesting topics: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_get_style_examples(
    content_type: str = "any",
    topic: Optional[str] = None,
    count: int = 3
) -> Dict[str, Any]:
    """
    Get example posts from style library.
    Note: This is a stub until RAG collection has content.
    """
    try:
        # Placeholder - will be enhanced when RAG collection has content
        return {
            "status": "no_examples_yet",
            "message": "Die Style-Library ist noch leer. Fuege zuerst Beispiel-Posts hinzu.",
            "how_to_add": "Exportiere deine besten LinkedIn-Posts und lade sie in die linkedin_content Collection",
            "content_type_filter": content_type,
            "topic_filter": topic,
            "examples": []
        }

    except Exception as e:
        logger.error(f"Error getting style examples: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_get_playbook(
    section: str = "all",
    include_random_combo: bool = True,
    example_category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the LinkedIn playbook with phrase libraries, targets, post types, strategy, and comment examples.
    """
    try:
        playbook = _load_playbook("linkedin_comment")

        if not playbook:
            return {
                "status": "not_loaded",
                "message": "Playbook nicht gefunden. Migration 083_content_playbooks.sql ausfuehren.",
                "fallback_available": True,
                "formula": "Einstieg + Praxis + Respekt"
            }

        result = {
            "status": "loaded",
            "name": playbook.get("name"),
            "purpose": playbook.get("purpose"),
            "golden_rule": playbook.get("golden_rule")
        }

        # Add formula
        if playbook.get("formula"):
            result["formula"] = playbook["formula"]

        # Section filtering
        if section == "all":
            result["sections"] = playbook.get("sections", {})
            result["forbidden"] = playbook.get("forbidden", [])
            result["targets"] = playbook.get("targets", [])
            result["post_types"] = playbook.get("post_types", [])
            result["strategy"] = playbook.get("strategy", {})
            result["style_elements"] = playbook.get("style_elements", {})
            result["comment_examples"] = playbook.get("comment_examples", {})
        elif section == "formula":
            result["formula"] = playbook.get("formula")
        elif section == "forbidden":
            result["forbidden"] = playbook.get("forbidden", [])
        elif section == "targets":
            result["targets"] = playbook.get("targets", [])
            result["tip"] = "Kommentiere regelmaessig bei diesen Accounts fuer maximale Sichtbarkeit."
        elif section == "post_types":
            result["post_types"] = playbook.get("post_types", [])
            result["tip"] = "Waehle einen Post-Typ der zu deinem aktuellen Thema passt."
        elif section == "strategy":
            result["strategy"] = playbook.get("strategy", {})
            result["tip"] = "Routine einhalten: 1 Post/Woche, 4-6 Kommentare/Woche, 2-3 neue Kontakte."
        elif section == "style":
            result["style_elements"] = playbook.get("style_elements", {})
            result["tip"] = "4 Elemente: Lockerer Einstieg, Echte Anerkennung, Praxis-Perspektive, Lockerer Abschluss."
        elif section == "comment_formula":
            style = playbook.get("style_elements", {})
            result["comment_formula"] = style.get("comment_formula", [])
            result["comment_elements"] = style.get("comment_element", [])
            result["tip"] = "3-Satz-Formel: 1. Lockerer Einstieg, 2. Beobachtung aus der Praxis, 3. Respekt/Augenzwinkern."
        elif section == "usps":
            style = playbook.get("style_elements", {})
            result["usps"] = style.get("usp", [])
            result["tip"] = "Dein Vorteil: Techniker + Systemdenker + Production Reality. Das ist selten."
        elif section == "avoid":
            style = playbook.get("style_elements", {})
            result["avoid"] = style.get("avoid", [])
            result["tip"] = "Nicht dein Stil: Motivationsposts, Leadership Lessons, Buzzword Innovation, Selbstpromotion."
        elif section == "examples":
            examples = playbook.get("comment_examples", {})
            if example_category and example_category in examples:
                result["examples"] = {example_category: examples[example_category]}
                # Also provide a random example
                cat_examples = examples[example_category]
                if cat_examples:
                    result["random_example"] = random.choice(cat_examples)["text"]
            else:
                result["examples"] = examples
                result["categories"] = list(examples.keys())
            result["tip"] = "Nutze diese Kommentare als Vorlage. Passe sie leicht an den konkreten Post an."
        else:
            section_data = playbook.get("sections", {}).get(section)
            if section_data:
                result["section"] = {section: section_data}
            else:
                result["error"] = f"Section '{section}' nicht gefunden"

        # Random combo
        if include_random_combo:
            einstieg = _get_random_phrase(playbook, "einstieg")
            praxis = _get_random_phrase(playbook, "praxis")
            respekt = _get_random_phrase(playbook, "respekt")

            if einstieg and praxis and respekt:
                result["random_combo"] = {
                    "einstieg": einstieg,
                    "praxis": praxis,
                    "respekt": respekt,
                    "combined": f"{einstieg} {praxis} {respekt}"
                }

        return result

    except Exception as e:
        logger.error(f"Error loading playbook: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# --- Helper Functions ---

def _get_coaching_questions(
    mode: str,
    goal: Optional[str],
    audience: Optional[str],
    source_post: Optional[str],
    key_points: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """Generate coaching questions based on what's missing."""
    questions = []

    if mode in ["comment", "repost"] and not source_post:
        questions.append({
            "field": "source_post",
            "question": "Auf welchen Post moechtest du reagieren? (Kopiere den Inhalt hier)",
            "required": True
        })

    if not goal:
        questions.append({
            "field": "goal",
            "question": "Was ist dein Ziel mit diesem Content? (z.B. 'Expertise zeigen', 'Diskussion starten', 'Erfahrung teilen')",
            "required": True
        })

    if not audience:
        questions.append({
            "field": "audience",
            "question": "Wen moechtest du erreichen? (z.B. 'Tech-Gruender', 'Entwickler', 'Marketing-Leute')",
            "required": True
        })

    if not key_points:
        if mode == "post":
            questions.append({
                "field": "key_points",
                "question": "Was sind die 2-3 Hauptpunkte, die du vermitteln willst?",
                "required": True
            })
        elif mode == "comment":
            questions.append({
                "field": "key_points",
                "question": "Was ist dein Take zu dem Post? Was willst du hinzufuegen?",
                "required": False
            })

    # Add optional questions
    questions.append({
        "field": "constraints",
        "question": "Gibt es Einschraenkungen? (z.B. 'max 100 Woerter', 'formell', 'keine Emojis')",
        "required": False
    })

    return questions


def _generate_draft(
    mode: str,
    goal: Optional[str],
    audience: Optional[str],
    source_post: Optional[str],
    key_points: Optional[List[str]],
    language: str,
    constraints: Optional[List[str]]
) -> Dict[str, Any]:
    """Generate a content draft based on inputs."""

    # Build structure based on mode
    if mode == "post":
        structure = {
            "hook": "Opening that grabs attention",
            "body": "Main content with key points",
            "cta": "Call-to-action or question"
        }
        template = _get_post_template(goal, key_points, language)
    elif mode == "comment":
        structure = {
            "acknowledgment": "Brief acknowledgment of original point",
            "addition": "Your unique perspective or experience",
            "engagement": "Question or invitation for dialogue"
        }
        template = _get_comment_template(source_post, key_points, language)
    else:  # repost
        structure = {
            "frame": "Your take on why this matters",
            "context": "What it means for your audience"
        }
        template = _get_repost_template(source_post, key_points, language)

    return {
        "content": template,
        "structure": structure,
        "word_count": len(template.split()),
        "constraints_applied": constraints or [],
        "language": language
    }


def _get_post_template(goal: Optional[str], key_points: Optional[List[str]], language: str) -> str:
    """Generate a post template."""
    if language == "de":
        points_text = "\n".join([f"- {p}" for p in (key_points or ["[Punkt 1]", "[Punkt 2]"])])
        return f"""[HOOK: Eine Frage oder ueberraschende Aussage]

{points_text}

[DEINE ERFAHRUNG/BEISPIEL]

Was denkst du? [FRAGE AN DIE COMMUNITY]

#[relevante] #[hashtags]"""
    else:
        points_text = "\n".join([f"- {p}" for p in (key_points or ["[Point 1]", "[Point 2]"])])
        return f"""[HOOK: A question or surprising statement]

{points_text}

[YOUR EXPERIENCE/EXAMPLE]

What do you think? [QUESTION TO COMMUNITY]

#[relevant] #[hashtags]"""


def _get_comment_template(source_post: Optional[str], key_points: Optional[List[str]], language: str) -> str:
    """Generate a comment template using playbook phrases when available."""
    point = key_points[0] if key_points else "[Dein Punkt]"

    # Try to load playbook for authentic phrases
    playbook = _load_playbook("linkedin_comment")

    if playbook and language == "de":
        # Get random phrases from playbook
        einstieg = _get_random_phrase(playbook, "einstieg") or "Sehr spannend!"
        praxis = _get_random_phrase(playbook, "praxis") or "[EIGENE BEOBACHTUNG AUS DER PRAXIS]"

        # Detect category from source_post for better matching
        category = None
        if source_post:
            source_lower = source_post.lower()
            if any(w in source_lower for w in ["mapping", "projection"]):
                category = "mapping"
            elif any(w in source_lower for w in ["immersive", "experience", "installation"]):
                category = "immersive"
            elif any(w in source_lower for w in ["stadium", "venue", "arena", "stadion"]):
                category = "venue"

        # Try category-specific phrase
        if category:
            category_phrase = _get_random_phrase(playbook, category, category)
            if category_phrase:
                praxis = category_phrase

        return f"""{einstieg}

{praxis if key_points else '[EIGENE BEOBACHTUNG ODER ERFAHRUNG]'}

{_get_random_phrase(playbook, "abschluss") or 'Grossen Respekt!'}"""

    # Fallback to standard template
    if language == "de":
        return f"""Guter Punkt! {point}

Bei uns/mir war das so: [KURZE EIGENE ERFAHRUNG]

Wie gehst du mit [ASPEKT] um?"""
    else:
        return f"""Great point! {point}

In my experience: [BRIEF PERSONAL EXPERIENCE]

How do you handle [ASPECT]?"""


def _get_repost_template(source_post: Optional[str], key_points: Optional[List[str]], language: str) -> str:
    """Generate a repost template."""
    point = key_points[0] if key_points else "[Dein Take]"
    if language == "de":
        return f"""{point}

Warum das wichtig ist: [KURZE ERKLAERUNG]

[ORIGINAL POST WIRD GEREPOSTET]"""
    else:
        return f"""{point}

Why this matters: [BRIEF EXPLANATION]

[ORIGINAL POST IS REPOSTED]"""


def _check_ai_voice(text: str) -> Dict[str, Any]:
    """Check text for AI-sounding phrases, including playbook forbidden list."""
    text_lower = text.lower()
    found = []

    # Check hardcoded forbidden phrases
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            found.append(phrase)

    # Also check playbook forbidden phrases
    try:
        playbook = _load_playbook("linkedin_comment")
        if playbook and playbook.get("forbidden"):
            for item in playbook["forbidden"]:
                phrase = item.get("phrase", "").lower()
                if phrase and phrase in text_lower and phrase not in found:
                    found.append(phrase)
    except Exception:
        pass  # Ignore playbook errors, use hardcoded list

    return {
        "found": len(found) > 0,
        "phrases_found": found,
        "count": len(found)
    }


def _get_replacement_suggestion(phrase: str) -> str:
    """Get replacement suggestion for AI phrase."""
    replacements = {
        "let's dive in": "Schauen wir uns an / Here's what I learned",
        "game-changer": "hat viel veraendert / made a real difference",
        "leverage": "nutzen / use",
        "synergy": "Zusammenarbeit / working together",
        "thought leader": "jemand mit Erfahrung / someone with experience",
        "passionate about": "interessiert mich / I care about",
        "deep dive": "genauer anschauen / look closer at",
        "circle back": "spaeter nochmal besprechen / discuss later",
        "move the needle": "etwas bewirken / make a difference",
        "thrilled to share": "ich moechte euch zeigen / I want to show you",
        "i'm excited to announce": "Neuigkeit: / News:",
    }
    return replacements.get(phrase, f"[finde eine persoenlichere Alternative zu '{phrase}']")


def _analyze_hook(text: str) -> Dict[str, Any]:
    """Analyze the opening hook of the text."""
    lines = text.strip().split('\n')
    first_line = lines[0] if lines else ""

    # Check for strong hook indicators
    strong_indicators = ['?', '!', 'Warum', 'Wie', 'Was', 'Why', 'How', 'What', '%', 'Mio', 'Million']
    is_strong = any(ind in first_line for ind in strong_indicators)

    return {
        "current_hook": first_line[:100] + "..." if len(first_line) > 100 else first_line,
        "strong": is_strong,
        "suggestion": "Starte mit einer Frage, einer ueberraschenden Statistik, oder einer kontraeren Aussage" if not is_strong else None
    }


def _analyze_engagement(text: str) -> Dict[str, Any]:
    """Analyze engagement elements in text."""
    text_lower = text.lower()

    # Check for CTA
    cta_indicators = ['?', 'was denkst', 'what do you', 'teile', 'share', 'kommentier', 'comment', 'erzaehl', 'tell me']
    has_cta = any(ind in text_lower for ind in cta_indicators)

    # Check for hashtags
    hashtag_count = text.count('#')

    return {
        "has_cta": has_cta,
        "hashtag_count": hashtag_count,
        "hashtags_optimal": 3 <= hashtag_count <= 5
    }


def _analyze_clarity(text: str) -> Dict[str, Any]:
    """Analyze clarity of text."""
    issues = []

    # Check sentence length
    sentences = re.split(r'[.!?]', text)
    long_sentences = [s.strip() for s in sentences if len(s.split()) > 25]
    if long_sentences:
        issues.append(f"{len(long_sentences)} Saetze sind zu lang (>25 Woerter)")

    # Check for jargon density
    jargon = ['implement', 'utilize', 'facilitate', 'stakeholder', 'paradigm', 'synergize']
    jargon_found = [j for j in jargon if j in text.lower()]
    if len(jargon_found) > 2:
        issues.append(f"Viel Fachjargon: {', '.join(jargon_found)}")

    return {
        "issues": issues,
        "sentence_count": len([s for s in sentences if s.strip()]),
        "word_count": len(text.split())
    }


def _get_mode_tips(mode: str, language: str) -> List[str]:
    """Get tips for the specific content mode."""
    tips = {
        "post": {
            "de": [
                "Die ersten 2 Zeilen sind entscheidend - sie erscheinen vor 'mehr anzeigen'",
                "Zeilenumbrueche erhoehen die Lesbarkeit",
                "Persoenliche Geschichten performen besser als abstrakte Tipps",
                "Beende mit einer Frage fuer mehr Kommentare"
            ],
            "en": [
                "First 2 lines are crucial - they appear before 'see more'",
                "Line breaks improve readability",
                "Personal stories perform better than abstract tips",
                "End with a question for more comments"
            ]
        },
        "comment": {
            "de": [
                "Kommentare in den ersten 30-60 Minuten haben mehr Sichtbarkeit",
                "Fuege einen eigenen Gedanken hinzu, nicht nur 'Super Post!'",
                "Stelle eine Folgefrage fuer mehr Dialog"
            ],
            "en": [
                "Comments in the first 30-60 minutes get more visibility",
                "Add your own thought, not just 'Great post!'",
                "Ask a follow-up question for more dialogue"
            ]
        },
        "repost": {
            "de": [
                "Erklaere, warum du repostest - nicht nur 'Wichtig'",
                "Fuege deinen eigenen Take hinzu",
                "Tagge den Originalautor"
            ],
            "en": [
                "Explain why you're reposting - not just 'Important'",
                "Add your own take",
                "Tag the original author"
            ]
        }
    }

    return tips.get(mode, {}).get(language, tips.get(mode, {}).get("en", []))


def _get_format_for_topic(topic: str) -> str:
    """Suggest format based on topic."""
    if any(word in topic.lower() for word in ["fehler", "mistake", "learned", "gelernt"]):
        return "Story-Format: Problem -> Fehler -> Learning"
    elif any(word in topic.lower() for word in ["wie", "how", "prozess", "process"]):
        return "Step-by-Step oder Listicle"
    elif any(word in topic.lower() for word in ["warum", "why", "unterschied"]):
        return "Kontrastierung: A vs B oder Myth vs Reality"
    else:
        return "Hook + Story + Takeaway"


def linkedin_save_to_playbook(
    learning_type: str,
    category: str,
    name: str,
    content: str,
    examples: Optional[List[str]] = None,
    is_favorite: bool = False
) -> Dict[str, Any]:
    """
    Save a learning about Micha's LinkedIn style to the playbook database.

    This allows Jarvis to persistently store learnings from conversations
    so they can be used in future LinkedIn content generation.
    """
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "jarvis")
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Get playbook ID
            cur.execute(
                "SELECT id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1"
            )
            result = cur.fetchone()
            if not result:
                return {
                    "status": "error",
                    "error": "LinkedIn playbook not found"
                }

            playbook_id = result['id']
            saved_item = None

            if learning_type == "style_element":
                # Insert into style_elements table
                cur.execute("""
                    INSERT INTO content_playbook_style_elements
                    (playbook_id, element_type, element_name, description, examples, sort_order)
                    VALUES (%s, %s, %s, %s, %s,
                            COALESCE((SELECT MAX(sort_order) + 1 FROM content_playbook_style_elements WHERE playbook_id = %s), 200))
                    RETURNING id, element_name
                """, (playbook_id, category, name, content, examples or [], playbook_id))
                saved_item = cur.fetchone()

            elif learning_type == "example":
                # Insert into comment_examples table
                cur.execute("""
                    INSERT INTO content_playbook_comment_examples
                    (playbook_id, category, comment_text, is_favorite)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, category
                """, (playbook_id, category, content, is_favorite))
                saved_item = cur.fetchone()

            elif learning_type == "signature_phrase":
                # Insert as signature example
                cur.execute("""
                    INSERT INTO content_playbook_comment_examples
                    (playbook_id, category, comment_text, is_favorite)
                    VALUES (%s, 'signature', %s, %s)
                    RETURNING id, category
                """, (playbook_id, content, True))
                saved_item = cur.fetchone()

            elif learning_type == "forbidden":
                # Insert into forbidden phrases
                cur.execute("""
                    INSERT INTO content_playbook_forbidden
                    (playbook_id, phrase, reason)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id, phrase
                """, (playbook_id, name, content))
                saved_item = cur.fetchone()

            elif learning_type == "network_contact":
                # Find the appropriate target group and add contact
                cur.execute("""
                    SELECT id FROM content_playbook_targets
                    WHERE playbook_id = %s
                    ORDER BY sort_order
                    LIMIT 1
                """, (playbook_id,))
                target_group = cur.fetchone()

                if target_group:
                    cur.execute("""
                        INSERT INTO content_playbook_target_accounts
                        (target_group_id, account_name, account_type, notes, is_priority)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id, account_name
                    """, (target_group['id'], name, category, content, is_favorite))
                    saved_item = cur.fetchone()

            conn.commit()

            if saved_item:
                logger.info(f"Saved LinkedIn learning: {learning_type}/{category}/{name}")
                return {
                    "status": "saved",
                    "learning_type": learning_type,
                    "category": category,
                    "name": name,
                    "id": saved_item.get('id'),
                    "message": f"Learning gespeichert: {name}"
                }
            else:
                return {
                    "status": "skipped",
                    "reason": "Already exists or invalid type",
                    "learning_type": learning_type,
                    "name": name
                }

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.error(f"Error saving LinkedIn learning: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def linkedin_check_save_confidence(
    learning_type: str,
    context_pattern: str
) -> Dict[str, Any]:
    """
    Check if Jarvis should auto-save a learning or ask the user first.

    Returns confidence score (0-1) and recommendation:
    - confidence >= 0.7: auto-save without asking
    - confidence 0.4-0.7: ask user first
    - confidence < 0.4: probably don't save, but can ask
    """
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "jarvis")
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Check confidence for this specific pattern
            cur.execute("""
                SELECT auto_save_confidence, total_asks, total_yes, total_no
                FROM playbook_learning_confidence
                WHERE playbook_domain = 'linkedin_comment'
                  AND learning_type = %s
                  AND context_pattern = %s
            """, (learning_type, context_pattern))

            result = cur.fetchone()

            if result:
                confidence = result['auto_save_confidence']
                total = result['total_asks']
                yes_rate = result['total_yes'] / max(total, 1)
            else:
                # Default confidence for unknown patterns
                confidence = 0.5
                total = 0
                yes_rate = 0.5

            # Determine action
            if confidence >= 0.7:
                action = "auto_save"
                message = "Hohe Konfidenz - automatisch speichern"
            elif confidence >= 0.4:
                action = "ask_user"
                message = "Mittlere Konfidenz - User fragen"
            else:
                action = "probably_skip"
                message = "Niedrige Konfidenz - wahrscheinlich nicht speichern"

            return {
                "confidence": round(confidence, 2),
                "action": action,
                "message": message,
                "learning_type": learning_type,
                "context_pattern": context_pattern,
                "history": {
                    "total_asks": total,
                    "yes_rate": round(yes_rate, 2)
                }
            }

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.warning(f"Error checking save confidence: {e}")
        # Default to asking user on error
        return {
            "confidence": 0.5,
            "action": "ask_user",
            "message": "Konnte Konfidenz nicht pruefen - User fragen",
            "error": str(e)
        }


def linkedin_record_save_feedback(
    learning_type: str,
    context_pattern: str,
    user_response: str
) -> Dict[str, Any]:
    """
    Record user's response to "Soll ich das speichern?" question.

    This updates the confidence model so Jarvis learns when to auto-save vs. ask.

    user_response options:
    - 'yes': Save this specific learning
    - 'no': Don't save this one
    - 'always': Always auto-save this type in this context
    - 'never': Never save this type in this context
    - 'later': Skip for now, don't update confidence
    """
    try:
        import psycopg2
        import os

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "jarvis")
        )
        cur = conn.cursor()

        try:
            if user_response != "later":
                # Call the database function to update confidence
                cur.execute(
                    "SELECT update_learning_confidence(%s, %s, %s, %s)",
                    ('linkedin_comment', learning_type, context_pattern, user_response)
                )
                conn.commit()

                logger.info(f"Recorded learning feedback: {learning_type}/{context_pattern} -> {user_response}")

                return {
                    "status": "recorded",
                    "learning_type": learning_type,
                    "context_pattern": context_pattern,
                    "user_response": user_response,
                    "message": f"Feedback gespeichert. Ich lerne daraus fuer zukuenftige Situationen."
                }
            else:
                return {
                    "status": "skipped",
                    "message": "OK, uebersprungen. Ich frage spaeter nochmal."
                }

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        logger.error(f"Error recording save feedback: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
