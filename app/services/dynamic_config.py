"""
Dynamic Configuration Service - Phase 21
Manages database-backed configurations for roles, patterns, skills, prompts, entities, and costs.
"""
import json
import sqlite3
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Database paths
STATE_DB = Path("/brain/system/state/jarvis_config.db")
MEMORY_DB = Path("/brain/system/state/jarvis_memory.db")

def _get_connection(db_path: Path = STATE_DB) -> sqlite3.Connection:
    """Get database connection with row factory."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_dynamic_config_tables():
    """Initialize all Phase 21 tables."""
    migration_path = Path("/brain/system/ingestion/migrations/060_phase_21_dynamic_config.sql")
    if not migration_path.exists():
        migration_path = Path("/Volumes/BRAIN/system/ingestion/migrations/060_phase_21_dynamic_config.sql")

    if migration_path.exists():
        conn = _get_connection()
        try:
            conn.executescript(migration_path.read_text())
            conn.commit()
            logger.info("Phase 21 dynamic config tables initialized")
        except Exception as e:
            logger.error(f"Failed to init Phase 21 tables: {e}")
        finally:
            conn.close()


# ============================================
# 1. ROLES MANAGEMENT
# ============================================

@dataclass
class DynamicRole:
    """Database-backed role definition."""
    name: str
    description: str
    system_prompt_addon: str
    greeting: str
    keywords: List[str]
    default_namespace: str = "work_projektil"
    enabled: bool = True
    usage_count: int = 0


def get_role_from_db(role_name: str) -> Optional[DynamicRole]:
    """Get a role from database."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM jarvis_roles WHERE name = ? AND enabled = 1",
            (role_name.lower(),)
        )
        row = cursor.fetchone()
        if row:
            return DynamicRole(
                name=row["name"],
                description=row["description"],
                system_prompt_addon=row["system_prompt_addon"] or "",
                greeting=row["greeting"] or "",
                keywords=json.loads(row["keywords"]) if row["keywords"] else [],
                default_namespace=row["default_namespace"] or "work_projektil",
                enabled=bool(row["enabled"]),
                usage_count=row["usage_count"] or 0
            )
    except Exception as e:
        logger.debug(f"Role not in DB: {role_name} - {e}")
    finally:
        conn.close()
    return None


def list_roles_from_db() -> List[Dict[str, Any]]:
    """List all enabled roles from database."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT name, description, greeting, usage_count FROM jarvis_roles WHERE enabled = 1 ORDER BY usage_count DESC"
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.debug(f"Failed to list roles: {e}")
        return []
    finally:
        conn.close()


def detect_role_from_db(query: str, current_role: str = "assistant") -> str:
    """Detect role based on keywords from database."""
    query_lower = query.lower()

    # Explicit role switch
    if query_lower.startswith("/role "):
        requested = query_lower.replace("/role ", "").strip()
        role = get_role_from_db(requested)
        if role:
            return requested
        return current_role

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT name, keywords FROM jarvis_roles WHERE enabled = 1"
        )

        best_match = current_role
        best_score = 0

        for row in cursor.fetchall():
            keywords = json.loads(row["keywords"]) if row["keywords"] else []
            score = sum(len(kw) for kw in keywords if kw in query_lower)

            if score > best_score:
                best_score = score
                best_match = row["name"]

        # Only switch on strong match
        if best_score >= 6:
            return best_match

    except Exception as e:
        logger.debug(f"Role detection failed: {e}")
    finally:
        conn.close()

    return current_role


def record_role_usage(role_name: str, success: bool = True, response_time_ms: int = 0):
    """Record role usage for analytics."""
    conn = _get_connection()
    try:
        conn.execute("""
            UPDATE jarvis_roles SET
                usage_count = usage_count + 1,
                success_rate = (success_rate * usage_count + ?) / (usage_count + 1),
                avg_response_time_ms = (avg_response_time_ms * usage_count + ?) / (usage_count + 1),
                updated_at = datetime('now')
            WHERE name = ?
        """, (1 if success else 0, response_time_ms, role_name))
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to record role usage: {e}")
    finally:
        conn.close()


def migrate_roles_to_db(roles_dict: Dict[str, Any]):
    """Migrate hardcoded roles to database."""
    conn = _get_connection()
    try:
        for name, role in roles_dict.items():
            conn.execute("""
                INSERT OR REPLACE INTO jarvis_roles
                (name, description, system_prompt_addon, greeting, keywords, default_namespace, enabled)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (
                name,
                role.description,
                role.system_prompt_addon,
                role.greeting,
                json.dumps(role.keywords),
                role.default_namespace
            ))
        conn.commit()
        logger.info(f"Migrated {len(roles_dict)} roles to database")
    except Exception as e:
        logger.error(f"Failed to migrate roles: {e}")
    finally:
        conn.close()


# ============================================
# 2. QUERY PATTERNS
# ============================================

def classify_query_from_db(query: str) -> Tuple[str, float]:
    """Classify query using database patterns. Returns (type, confidence)."""
    query_lower = query.lower().strip()

    conn = _get_connection()
    try:
        # Check regex patterns first
        cursor = conn.execute(
            "SELECT pattern, pattern_type, confidence FROM query_patterns WHERE enabled = 1 AND is_regex = 1 ORDER BY confidence DESC"
        )
        for row in cursor.fetchall():
            try:
                if re.match(row["pattern"], query_lower):
                    _record_pattern_hit(conn, row["pattern"])
                    return (row["pattern_type"], row["confidence"])
            except re.error:
                continue

        # Check keyword patterns
        cursor = conn.execute(
            "SELECT pattern, pattern_type, confidence FROM query_patterns WHERE enabled = 1 AND is_regex = 0 ORDER BY confidence DESC"
        )
        for row in cursor.fetchall():
            if row["pattern"].lower() in query_lower:
                _record_pattern_hit(conn, row["pattern"])
                return (row["pattern_type"], row["confidence"])

    except Exception as e:
        logger.debug(f"Pattern classification failed: {e}")
    finally:
        conn.close()

    return ("standard", 0.5)  # Default


def _record_pattern_hit(conn: sqlite3.Connection, pattern: str):
    """Record pattern match for learning."""
    try:
        conn.execute("""
            UPDATE query_patterns SET
                hit_count = hit_count + 1,
                last_hit = datetime('now'),
                updated_at = datetime('now')
            WHERE pattern = ?
        """, (pattern,))
        conn.commit()
    except Exception:
        pass


def learn_query_pattern(query: str, pattern_type: str, confidence: float = 0.6):
    """Learn a new query pattern from successful classification."""
    conn = _get_connection()
    try:
        # Extract key phrase (first 50 chars, cleaned)
        pattern = re.sub(r'[^\w\s]', '', query.lower().strip())[:50]

        conn.execute("""
            INSERT OR IGNORE INTO query_patterns (pattern, pattern_type, confidence, source, is_regex)
            VALUES (?, ?, ?, 'learned', 0)
        """, (pattern, pattern_type, confidence))
        conn.commit()
        logger.debug(f"Learned pattern: {pattern} -> {pattern_type}")
    except Exception as e:
        logger.debug(f"Failed to learn pattern: {e}")
    finally:
        conn.close()


def migrate_query_patterns(simple_patterns: List[str], complex_keywords: List[str], standard_keywords: List[str]):
    """Migrate hardcoded patterns to database."""
    conn = _get_connection()
    try:
        # Simple patterns (regex)
        for pattern in simple_patterns:
            conn.execute("""
                INSERT OR IGNORE INTO query_patterns (pattern, pattern_type, is_regex, confidence, source)
                VALUES (?, 'simple', 1, 0.9, 'hardcoded')
            """, (pattern,))

        # Complex keywords
        for kw in complex_keywords:
            conn.execute("""
                INSERT OR IGNORE INTO query_patterns (pattern, pattern_type, is_regex, confidence, source, category)
                VALUES (?, 'complex', 0, 0.8, 'hardcoded', 'complex_indicator')
            """, (kw,))

        # Standard keywords
        for kw in standard_keywords:
            conn.execute("""
                INSERT OR IGNORE INTO query_patterns (pattern, pattern_type, is_regex, confidence, source, category)
                VALUES (?, 'standard', 0, 0.7, 'hardcoded', 'standard_indicator')
            """, (kw,))

        conn.commit()
        logger.info(f"Migrated {len(simple_patterns) + len(complex_keywords) + len(standard_keywords)} query patterns")
    except Exception as e:
        logger.error(f"Failed to migrate patterns: {e}")
    finally:
        conn.close()


# ============================================
# 3. SKILL REGISTRY
# ============================================

def register_skill(skill_data: Dict[str, Any]) -> bool:
    """Register a skill in the database."""
    conn = _get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO skill_registry
            (name, category, description, triggers, not_triggers, required_tools,
             time_triggers, auto_trigger_condition, skill_level, skill_path, version, author)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill_data.get("name"),
            skill_data.get("category"),
            skill_data.get("description"),
            json.dumps(skill_data.get("triggers", [])),
            json.dumps(skill_data.get("not_triggers", [])),
            json.dumps(skill_data.get("required_tools", [])),
            json.dumps(skill_data.get("time_triggers")),
            skill_data.get("auto_trigger_condition"),
            skill_data.get("level", 1),
            skill_data.get("path"),
            skill_data.get("version", "1.0"),
            skill_data.get("author")
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to register skill: {e}")
        return False
    finally:
        conn.close()


def get_skill(skill_name: str) -> Optional[Dict[str, Any]]:
    """Get skill from database."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM skill_registry WHERE name = ? AND enabled = 1",
            (skill_name,)
        )
        row = cursor.fetchone()
        if row:
            skill = dict(row)
            skill["triggers"] = json.loads(skill["triggers"]) if skill["triggers"] else []
            skill["not_triggers"] = json.loads(skill["not_triggers"]) if skill["not_triggers"] else []
            skill["required_tools"] = json.loads(skill["required_tools"]) if skill["required_tools"] else []
            return skill
    except Exception as e:
        logger.debug(f"Skill not found: {skill_name} - {e}")
    finally:
        conn.close()
    return None


def detect_skill_from_query(query: str) -> Optional[Dict[str, Any]]:
    """Detect which skill matches the query."""
    query_lower = query.lower()

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM skill_registry WHERE enabled = 1"
        )

        for row in cursor.fetchall():
            triggers = json.loads(row["triggers"]) if row["triggers"] else []
            not_triggers = json.loads(row["not_triggers"]) if row["not_triggers"] else []

            # Check not_triggers first
            if any(nt.lower() in query_lower for nt in not_triggers):
                continue

            # Check triggers
            if any(t.lower() in query_lower for t in triggers):
                skill = dict(row)
                skill["triggers"] = triggers
                skill["not_triggers"] = not_triggers
                skill["required_tools"] = json.loads(skill["required_tools"]) if skill["required_tools"] else []
                return skill

    except Exception as e:
        logger.debug(f"Skill detection failed: {e}")
    finally:
        conn.close()

    return None


def record_skill_execution(skill_name: str, session_id: str, user_id: str,
                          trigger_phrase: str, tools_used: List[str],
                          duration_ms: int, success: bool, error: str = None):
    """Record skill execution for analytics."""
    conn = _get_connection()
    try:
        conn.execute("""
            INSERT INTO skill_executions
            (skill_name, session_id, user_id, trigger_phrase, tools_used, duration_ms, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (skill_name, session_id, user_id, trigger_phrase, json.dumps(tools_used), duration_ms, 1 if success else 0, error))

        # Update skill stats
        conn.execute("""
            UPDATE skill_registry SET
                usage_count = usage_count + 1,
                success_count = success_count + ?,
                avg_duration_ms = (avg_duration_ms * usage_count + ?) / (usage_count + 1),
                last_used = datetime('now'),
                updated_at = datetime('now')
            WHERE name = ?
        """, (1 if success else 0, duration_ms, skill_name))

        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to record skill execution: {e}")
    finally:
        conn.close()


def load_skills_from_files(skills_dir: Path = None) -> int:
    """Load all SKILL.md files into database."""
    import yaml

    if skills_dir is None:
        skills_dir = Path("/brain/system/jarvis-skills")
    if not skills_dir.exists():
        skills_dir = Path("/Volumes/BRAIN/system/jarvis-skills")

    loaded = 0
    for skill_path in skills_dir.glob("*/SKILL.md"):
        try:
            content = skill_path.read_text()

            # Parse YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])

                    skill_data = {
                        "name": skill_path.parent.name,
                        "category": frontmatter.get("category"),
                        "description": frontmatter.get("description"),
                        "triggers": frontmatter.get("triggers", []),
                        "not_triggers": frontmatter.get("not_triggers", []),
                        "required_tools": frontmatter.get("required_tools", []),
                        "time_triggers": frontmatter.get("time_triggers"),
                        "auto_trigger_condition": frontmatter.get("auto_trigger"),
                        "level": frontmatter.get("level", 1),
                        "version": frontmatter.get("version", "1.0"),
                        "author": frontmatter.get("author"),
                        "path": str(skill_path)
                    }

                    if register_skill(skill_data):
                        loaded += 1

        except Exception as e:
            logger.warning(f"Failed to load skill {skill_path}: {e}")

    logger.info(f"Loaded {loaded} skills from {skills_dir}")
    return loaded


# ============================================
# 4. SYSTEM PROMPTS
# ============================================

def get_active_prompt(prompt_name: str) -> Optional[str]:
    """Get active prompt content by name."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT content FROM system_prompts WHERE name = ? AND active = 1 ORDER BY version DESC LIMIT 1",
            (prompt_name,)
        )
        row = cursor.fetchone()
        if row:
            return row["content"]
    except Exception as e:
        logger.debug(f"Prompt not found: {prompt_name} - {e}")
    finally:
        conn.close()
    return None


def save_prompt_version(name: str, content: str, description: str = None,
                       make_active: bool = False, created_by: str = "system") -> int:
    """Save a new prompt version. Returns version number."""
    conn = _get_connection()
    try:
        # Get next version
        cursor = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM system_prompts WHERE name = ?",
            (name,)
        )
        version = cursor.fetchone()[0]

        # Estimate tokens (rough: 4 chars per token)
        token_estimate = len(content) // 4

        # Deactivate other versions if making this active
        if make_active:
            conn.execute("UPDATE system_prompts SET active = 0 WHERE name = ?", (name,))

        conn.execute("""
            INSERT INTO system_prompts (name, version, content, description, token_estimate, active, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, version, content, description, token_estimate, 1 if make_active else 0, created_by))

        conn.commit()
        logger.info(f"Saved prompt {name} v{version}")
        return version
    except Exception as e:
        logger.error(f"Failed to save prompt: {e}")
        return 0
    finally:
        conn.close()


def list_prompt_versions(name: str) -> List[Dict[str, Any]]:
    """List all versions of a prompt."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT version, active, token_estimate, usage_count, created_at FROM system_prompts WHERE name = ? ORDER BY version DESC",
            (name,)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.debug(f"Failed to list prompts: {e}")
        return []
    finally:
        conn.close()


def activate_prompt_version(name: str, version: int) -> bool:
    """Activate a specific prompt version."""
    conn = _get_connection()
    try:
        conn.execute("UPDATE system_prompts SET active = 0 WHERE name = ?", (name,))
        conn.execute("UPDATE system_prompts SET active = 1 WHERE name = ? AND version = ?", (name, version))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to activate prompt: {e}")
        return False
    finally:
        conn.close()


def record_prompt_usage(name: str, quality_score: float = None):
    """Record prompt usage for analytics."""
    conn = _get_connection()
    try:
        if quality_score is not None:
            conn.execute("""
                UPDATE system_prompts SET
                    usage_count = usage_count + 1,
                    avg_quality_score = (COALESCE(avg_quality_score, 0) * usage_count + ?) / (usage_count + 1)
                WHERE name = ? AND active = 1
            """, (quality_score, name))
        else:
            conn.execute("""
                UPDATE system_prompts SET usage_count = usage_count + 1
                WHERE name = ? AND active = 1
            """, (name,))
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to record prompt usage: {e}")
    finally:
        conn.close()


# ============================================
# 5. ENTITIES (Person Intelligence)
# ============================================

def _ensure_entities_schema(conn: sqlite3.Connection):
    """Ensure entities table has all required columns."""
    try:
        # Check if aliases column exists
        cursor = conn.execute("PRAGMA table_info(entities)")
        columns = [row[1] for row in cursor.fetchall()]

        if "aliases" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN aliases TEXT")
        if "namespace" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN namespace TEXT DEFAULT 'shared'")
        if "importance" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN importance TEXT DEFAULT 'medium'")
        if "last_mentioned" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN last_mentioned TEXT")
        if "mention_count" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN mention_count INTEGER DEFAULT 0")
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE entities ADD COLUMN updated_at TEXT")

        conn.commit()
    except Exception as e:
        logger.debug(f"Schema update skipped: {e}")


def add_entity(name: str, entity_type: str, metadata: Dict[str, Any] = None,
               namespace: str = "shared", importance: str = "medium",
               aliases: List[str] = None) -> bool:
    """Add or update an entity."""
    conn = _get_connection(MEMORY_DB)
    try:
        # Ensure schema is up to date
        _ensure_entities_schema(conn)

        # Generate entity ID and timestamps
        import uuid
        now = datetime.utcnow().isoformat()
        entity_id = f"ent_{uuid.uuid4().hex[:8]}"

        # Try with full schema first (compatible with existing jarvis_memory.db entities table)
        try:
            conn.execute("""
                INSERT INTO entities (id, name, entity_type, aliases, metadata, namespace, importance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entity_id,
                name,
                entity_type,
                json.dumps(aliases) if aliases else None,
                json.dumps(metadata) if metadata else None,
                namespace,
                importance,
                now,
                now
            ))
        except sqlite3.OperationalError as e:
            # Fallback: simpler insert with both timestamps
            logger.debug(f"Full insert failed, trying fallback: {e}")
            import uuid
            entity_id = f"ent_{uuid.uuid4().hex[:8]}"
            conn.execute("""
                INSERT OR REPLACE INTO entities (id, name, entity_type, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entity_id, name, entity_type, json.dumps(metadata) if metadata else None, now, now))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to add entity: {e}")
        return False
    finally:
        conn.close()


def get_entity(name: str, entity_type: str = None) -> Optional[Dict[str, Any]]:
    """Get entity by name (and optionally type)."""
    conn = _get_connection(MEMORY_DB)
    try:
        if entity_type:
            cursor = conn.execute(
                "SELECT * FROM entities WHERE name = ? AND entity_type = ?",
                (name, entity_type)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM entities WHERE name = ? OR ? IN (SELECT value FROM json_each(aliases))",
                (name, name)
            )
        row = cursor.fetchone()
        if row:
            entity = dict(row)
            entity["aliases"] = json.loads(entity["aliases"]) if entity["aliases"] else []
            entity["metadata"] = json.loads(entity["metadata"]) if entity["metadata"] else {}
            return entity
    except Exception as e:
        logger.debug(f"Entity not found: {name} - {e}")
    finally:
        conn.close()
    return None


def search_entities(query: str, entity_type: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Search entities by name or alias."""
    conn = _get_connection(MEMORY_DB)
    try:
        query_pattern = f"%{query}%"
        if entity_type:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE entity_type = ? AND (name LIKE ? OR aliases LIKE ?)
                ORDER BY mention_count DESC LIMIT ?
            """, (entity_type, query_pattern, query_pattern, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE name LIKE ? OR aliases LIKE ?
                ORDER BY mention_count DESC LIMIT ?
            """, (query_pattern, query_pattern, limit))

        results = []
        for row in cursor.fetchall():
            entity = dict(row)
            entity["aliases"] = json.loads(entity["aliases"]) if entity["aliases"] else []
            entity["metadata"] = json.loads(entity["metadata"]) if entity["metadata"] else {}
            results.append(entity)
        return results
    except Exception as e:
        logger.debug(f"Entity search failed: {e}")
        return []
    finally:
        conn.close()


def record_entity_mention(entity_id: int):
    """Record that an entity was mentioned."""
    conn = _get_connection(MEMORY_DB)
    try:
        conn.execute("""
            UPDATE entities SET
                mention_count = mention_count + 1,
                last_mentioned = datetime('now')
            WHERE id = ?
        """, (entity_id,))
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to record mention: {e}")
    finally:
        conn.close()


def seed_known_entities():
    """Seed database with known entities from hardcoded lists."""
    entities = [
        # People (from pattern_detector.py KNOWN_PERSONS)
        {"name": "Philippe", "type": "person", "metadata": {"role": "colleague"}, "namespace": "work_projektil"},
        {"name": "Patrik", "type": "person", "metadata": {"role": "colleague"}, "namespace": "work_projektil"},
        {"name": "Martina", "type": "person", "metadata": {"role": "colleague"}, "namespace": "work_projektil"},
        {"name": "Micha", "type": "person", "metadata": {"role": "user", "is_primary_user": True}, "namespace": "shared", "importance": "critical"},
        {"name": "Michael", "type": "person", "metadata": {"role": "user", "is_primary_user": True}, "namespace": "shared", "importance": "critical", "aliases": ["Micha"]},
        # Companies
        {"name": "Projektil", "type": "company", "metadata": {"type": "employer"}, "namespace": "work_projektil", "importance": "high"},
        {"name": "VisualFox", "type": "company", "metadata": {"type": "employer"}, "namespace": "work_visualfox", "importance": "high"},
    ]

    for e in entities:
        add_entity(
            name=e["name"],
            entity_type=e["type"],
            metadata=e.get("metadata"),
            namespace=e.get("namespace", "shared"),
            importance=e.get("importance", "medium"),
            aliases=e.get("aliases")
        )

    logger.info(f"Seeded {len(entities)} entities")


# ============================================
# 6. COST TRACKING
# ============================================

def record_api_cost(model: str, provider: str, feature: str,
                   tokens_in: int, tokens_out: int,
                   session_id: str = None, user_id: str = None,
                   namespace: str = None, latency_ms: int = None,
                   success: bool = True):
    """Record API usage cost."""
    conn = _get_connection()
    try:
        # Get model pricing
        cursor = conn.execute(
            "SELECT input_cost_per_1k, output_cost_per_1k FROM model_costs WHERE model = ?",
            (model,)
        )
        row = cursor.fetchone()

        if row:
            cost_usd = (tokens_in / 1000 * row["input_cost_per_1k"]) + \
                      (tokens_out / 1000 * row["output_cost_per_1k"])
        else:
            # Default fallback pricing
            cost_usd = (tokens_in / 1000 * 0.003) + (tokens_out / 1000 * 0.015)

        conn.execute("""
            INSERT INTO cost_entries
            (model, provider, feature, tokens_in, tokens_out, cost_usd, session_id, user_id, namespace, latency_ms, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (model, provider, feature, tokens_in, tokens_out, cost_usd, session_id, user_id, namespace, latency_ms, 1 if success else 0))

        # Update daily aggregate
        today = datetime.utcnow().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO cost_daily_aggregates (date, model, feature, total_requests, total_tokens_in, total_tokens_out, total_cost_usd)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(date, model, feature) DO UPDATE SET
                total_requests = total_requests + 1,
                total_tokens_in = total_tokens_in + excluded.total_tokens_in,
                total_tokens_out = total_tokens_out + excluded.total_tokens_out,
                total_cost_usd = total_cost_usd + excluded.total_cost_usd
        """, (today, model, feature, tokens_in, tokens_out, cost_usd))

        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to record cost: {e}")
    finally:
        conn.close()


def get_cost_summary(days: int = 7) -> Dict[str, Any]:
    """Get cost summary for recent days."""
    conn = _get_connection()
    try:
        cursor = conn.execute("""
            SELECT
                SUM(total_cost_usd) as total_cost,
                SUM(total_requests) as total_requests,
                SUM(total_tokens_in) as total_tokens_in,
                SUM(total_tokens_out) as total_tokens_out
            FROM cost_daily_aggregates
            WHERE date >= date('now', ?)
        """, (f"-{days} days",))

        row = cursor.fetchone()
        if row:
            return {
                "total_cost_usd": row["total_cost"] or 0,
                "total_requests": row["total_requests"] or 0,
                "total_tokens": (row["total_tokens_in"] or 0) + (row["total_tokens_out"] or 0),
                "days": days
            }
    except Exception as e:
        logger.debug(f"Failed to get cost summary: {e}")
    finally:
        conn.close()

    return {"total_cost_usd": 0, "total_requests": 0, "total_tokens": 0, "days": days}


def get_model_costs() -> Dict[str, Dict[str, float]]:
    """Get all model costs from database."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT model, provider, input_cost_per_1k, output_cost_per_1k FROM model_costs WHERE enabled = 1"
        )
        return {
            row["model"]: {
                "provider": row["provider"],
                "input": row["input_cost_per_1k"],
                "output": row["output_cost_per_1k"]
            }
            for row in cursor.fetchall()
        }
    except Exception as e:
        logger.debug(f"Failed to get model costs: {e}")
        return {}
    finally:
        conn.close()


def update_model_cost(model: str, input_cost: float, output_cost: float):
    """Update model pricing."""
    conn = _get_connection()
    try:
        conn.execute("""
            UPDATE model_costs SET
                input_cost_per_1k = ?,
                output_cost_per_1k = ?,
                updated_at = datetime('now')
            WHERE model = ?
        """, (input_cost, output_cost, model))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to update model cost: {e}")
    finally:
        conn.close()


# ============================================
# INITIALIZATION
# ============================================

def initialize_all():
    """Initialize all Phase 21 components."""
    init_dynamic_config_tables()

    # Check if roles need migration
    conn = _get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM jarvis_roles")
    if cursor.fetchone()[0] == 0:
        # Import and migrate roles
        try:
            from ..roles import ROLES
            migrate_roles_to_db(ROLES)
        except Exception as e:
            logger.warning(f"Could not migrate roles: {e}")
    conn.close()

    # Load skills from files
    load_skills_from_files()

    # Seed entities
    seed_known_entities()

    logger.info("Phase 21 Dynamic Config initialized")
