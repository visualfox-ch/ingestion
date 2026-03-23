"""
Admin Router

Extracted from main.py - Administration endpoints for:
- State migration (SQLite/JSON → Postgres)
- System reset
- Data inventory
- Configuration import (personas, modes, policies)
- Capabilities management
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from pathlib import Path
import json

from ..capability_paths import get_capabilities_json_path
from ..observability import get_logger
from ..auth import auth_dependency

logger = get_logger("jarvis.admin")
# All admin endpoints require authentication
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(auth_dependency)]
)


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class ResetOptions(BaseModel):
    """Options for resetting Jarvis to clean state"""
    clear_uploads: bool = True
    clear_profiles: bool = False  # Careful - deletes all person profiles!
    clear_self_model: bool = True
    clear_context_buffer: bool = True
    clear_qdrant: bool = False  # Careful - deletes all vector embeddings!
    dry_run: bool = True  # Preview what would be deleted


# =============================================================================
# STATE MIGRATION
# =============================================================================

@router.post("/migrate/sqlite")
def migrate_sqlite_to_postgres(
    sqlite_path: str = "/brain/index/ingest_state.db"
):
    """
    Migrate state data from SQLite to PostgreSQL.

    This migrates:
    - ingest_log → ingest_event
    - conversations
    - telegram_users

    Safe to run multiple times (uses upserts).
    """
    from .. import postgres_state

    try:
        result = postgres_state.migrate_from_sqlite(sqlite_path)
        return {"status": "success", "migrated": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/migrate/connectors")
def migrate_connectors_to_postgres(
    state_dir: str = "/brain/system/state/connectors"
):
    """
    Migrate connector state from JSON files to PostgreSQL.

    Safe to run multiple times (uses upserts).
    """
    from .. import postgres_state

    try:
        result = postgres_state.migrate_connector_json(state_dir)
        return {"status": "success", "migrated": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/init-schema")
def init_knowledge_schema():
    """Initialize/update knowledge database schema including all new tables."""
    from .. import knowledge_db
    try:
        knowledge_db.init_schema()
        return {"status": "success", "message": "Schema initialized"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/state/postgres")
def get_postgres_state_stats():
    """Get statistics about the PostgreSQL state tables."""
    from .. import postgres_state

    try:
        with postgres_state.get_cursor() as cur:
            stats = {}

            # Count records in each table
            tables = ["connector_state", "ingest_event", "conversation", "message",
                     "telegram_user", "working_state"]

            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                    stats[table] = cur.fetchone()["count"]
                except Exception:
                    stats[table] = "table_not_found"

            # Get connectors summary
            cur.execute("""
                SELECT connector_type, COUNT(*) as count,
                       SUM(CASE WHEN consecutive_errors = 0 THEN 1 ELSE 0 END) as healthy
                FROM connector_state
                GROUP BY connector_type
            """)
            stats["connectors_by_type"] = [dict(row) for row in cur.fetchall()]

            # Get ingest summary
            cur.execute("""
                SELECT ingest_type, COUNT(*) as count,
                       COUNT(*) FILTER (WHERE status = 'success') as success,
                       COUNT(*) FILTER (WHERE status = 'error') as error
                FROM ingest_event
                GROUP BY ingest_type
            """)
            stats["ingest_by_type"] = [dict(row) for row in cur.fetchall()]

        return {"status": "success", "stats": stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# =============================================================================
# RESET & INVENTORY
# =============================================================================

@router.post("/reset")
def admin_reset(options: ResetOptions):
    """
    Reset Jarvis to a clean state.

    CAREFUL: This deletes data! Use dry_run=true first to preview.

    Options:
    - clear_uploads: Remove all upload queue entries and files
    - clear_profiles: Remove all person profiles (DANGEROUS)
    - clear_self_model: Reset self-model to neutral state
    - clear_context_buffer: Clear active context buffer
    - clear_qdrant: Clear all vector collections (DANGEROUS)
    - dry_run: If True, only preview what would be deleted
    """
    from .. import knowledge_db, postgres_state
    from ..observability import log_with_context

    results = {
        "dry_run": options.dry_run,
        "actions": []
    }

    # 1. Upload Queue
    if options.clear_uploads:
        uploads = knowledge_db.get_upload_queue(limit=1000)
        results["actions"].append({
            "target": "upload_queue",
            "count": len(uploads),
            "items": [{"id": str(u["id"]), "filename": u["filename"]} for u in uploads[:10]],
            "truncated": len(uploads) > 10
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM upload_queue")
                # Also clean up files
                import shutil
                upload_dir = Path("/brain/uploads/incoming")
                if upload_dir.exists():
                    for subdir in upload_dir.iterdir():
                        if subdir.is_dir():
                            for f in subdir.glob("*"):
                                f.unlink()

    # 2. Person Profiles
    if options.clear_profiles:
        profiles = knowledge_db.get_all_person_profiles()
        results["actions"].append({
            "target": "person_profiles",
            "count": len(profiles),
            "items": [{"id": p["person_id"], "name": p["name"]} for p in profiles],
            "warning": "This deletes ALL person profiles!"
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM person_profile_version")
                cur.execute("DELETE FROM person_profile")

    # 3. Self-Model
    if options.clear_self_model:
        current_model = knowledge_db.get_self_model()
        results["actions"].append({
            "target": "self_model",
            "current_strengths": current_model.get("strengths", []) if current_model else [],
            "current_weaknesses": current_model.get("weaknesses", []) if current_model else [],
            "action": "Reset to neutral state"
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE jarvis_self_model SET
                        strengths = '[]'::jsonb,
                        weaknesses = '[]'::jsonb,
                        wishes = '[]'::jsonb,
                        user_patterns = '{}'::jsonb,
                        user_preferences = '{}'::jsonb,
                        current_feeling = 'Frisch initialisiert, bereit fuer echte Daten',
                        confidence_level = 0.3,
                        total_sessions = 0,
                        successful_interactions = 0,
                        frustrating_moments = 0,
                        updated_at = NOW()
                    WHERE id = 'default'
                """)

    # 4. Context Buffer
    if options.clear_context_buffer:
        buffer = postgres_state.get_active_buffer()
        stats = postgres_state.get_buffer_stats()
        results["actions"].append({
            "target": "context_buffer",
            "active_threads": len(buffer),
            "total_by_status": stats.get("by_status", {})
        })

        if not options.dry_run:
            postgres_state.clear_buffer(keep_completed=False)

    # 5. Qdrant Collections
    if options.clear_qdrant:
        try:
            from qdrant_client import QdrantClient
            import os
            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
            client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)
            collections = client.get_collections()

            results["actions"].append({
                "target": "qdrant",
                "collections": [c.name for c in collections.collections],
                "warning": "This deletes ALL vector embeddings!"
            })

            if not options.dry_run:
                for coll in collections.collections:
                    # Don't delete, just clear points
                    try:
                        client.delete(
                            collection_name=coll.name,
                            points_selector={"filter": {}}
                        )
                    except Exception:
                        pass  # Collection might be empty
        except Exception as e:
            results["actions"].append({
                "target": "qdrant",
                "error": str(e)
            })

    if options.dry_run:
        results["message"] = "DRY RUN - No changes made. Set dry_run=false to execute."
    else:
        results["message"] = "Reset completed. Jarvis is now in a clean state."

    return results


@router.get("/data-inventory")
def get_data_inventory():
    """
    Get a complete inventory of all data stored in Jarvis.
    Useful for understanding what exists before reset.
    """
    from .. import knowledge_db, postgres_state
    import os

    inventory = {
        "knowledge_layer": {},
        "state_layer": {},
        "vector_store": {},
        "file_system": {}
    }

    # Knowledge Layer (Postgres)
    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Person profiles
            cur.execute("SELECT COUNT(*) as count FROM person_profile")
            inventory["knowledge_layer"]["person_profiles"] = cur.fetchone()["count"]

            # Profile versions
            cur.execute("SELECT COUNT(*) as count FROM person_profile_version")
            inventory["knowledge_layer"]["profile_versions"] = cur.fetchone()["count"]

            # Uploads
            cur.execute("SELECT status, COUNT(*) as count FROM upload_queue GROUP BY status")
            inventory["knowledge_layer"]["uploads"] = {row["status"]: row["count"] for row in cur.fetchall()}

            # Sync states
            cur.execute("SELECT COUNT(*) as count FROM chat_sync_state")
            inventory["knowledge_layer"]["sync_states"] = cur.fetchone()["count"]

            # Self-model
            model = knowledge_db.get_self_model()
            if model:
                inventory["knowledge_layer"]["self_model"] = {
                    "strengths_count": len(model.get("strengths", [])),
                    "weaknesses_count": len(model.get("weaknesses", [])),
                    "wishes_count": len(model.get("wishes", [])),
                    "sessions": model.get("total_sessions", 0),
                    "last_updated": str(model.get("updated_at", "never"))
                }
    except Exception as e:
        inventory["knowledge_layer"]["error"] = str(e)

    # State Layer (Postgres)
    try:
        with postgres_state.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM connector_state")
            inventory["state_layer"]["connectors"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM conversation")
            inventory["state_layer"]["conversations"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM message")
            inventory["state_layer"]["messages"] = cur.fetchone()["count"]

            cur.execute("SELECT status, COUNT(*) as count FROM active_context_buffer GROUP BY status")
            inventory["state_layer"]["context_buffer"] = {row["status"]: row["count"] for row in cur.fetchall()}
    except Exception as e:
        inventory["state_layer"]["error"] = str(e)

    # Vector Store (Qdrant)
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)
        collections = client.get_collections()

        inventory["vector_store"]["collections"] = {}
        for coll in collections.collections:
            try:
                info = client.get_collection(coll.name)
                inventory["vector_store"]["collections"][coll.name] = {
                    "vectors_count": info.vectors_count,
                    "points_count": info.points_count
                }
            except Exception:
                inventory["vector_store"]["collections"][coll.name] = "error"
    except Exception as e:
        inventory["vector_store"]["error"] = str(e)

    # File System
    try:
        upload_dir = Path("/brain/uploads/incoming")
        if upload_dir.exists():
            file_count = 0
            for subdir in upload_dir.iterdir():
                if subdir.is_dir():
                    file_count += len(list(subdir.glob("*")))
            inventory["file_system"]["upload_files"] = file_count

        # Secrets (just count, not content)
        secrets_dir = Path("/brain/system/secrets")
        if secrets_dir.exists():
            inventory["file_system"]["secrets_files"] = len(list(secrets_dir.glob("*")))
    except Exception as e:
        inventory["file_system"]["error"] = str(e)

    return inventory


# =============================================================================
# CONFIGURATION IMPORT
# =============================================================================

@router.post("/import/personas")
def import_personas(file_path: str = "/brain/system/prompts/persona_profiles.json"):
    """
    Import personas from JSON file into database.
    File format: {"personas": [...]}
    """
    from .. import knowledge_db

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        personas = data.get("personas", [])
        imported = []
        errors = []

        for p in personas:
            try:
                result = knowledge_db.upsert_persona(
                    persona_id=p.get("id"),
                    name=p.get("name"),
                    intent=p.get("intent"),
                    tone=p.get("tone"),
                    format_config=p.get("format"),
                    requirements=p.get("requirements"),
                    forbidden=p.get("forbidden"),
                    example=p.get("one_liner_example")
                )
                if result:
                    imported.append(p.get("id"))
            except Exception as e:
                errors.append({"id": p.get("id"), "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "errors": errors,
            "source_file": file_path
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/import/modes")
def import_modes(file_path: str = "/brain/system/prompts/modes.json"):
    """
    Import modes from JSON file into database.
    File format: {"modes": {...}}
    """
    from .. import knowledge_db

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        modes = data.get("modes", {})
        default_mode = data.get("default_mode", "analyst")
        imported = []
        errors = []

        for mode_id, m in modes.items():
            try:
                result = knowledge_db.upsert_mode(
                    mode_id=mode_id,
                    name=m.get("name"),
                    purpose=m.get("purpose"),
                    output_contract=m.get("output_contract"),
                    tone=m.get("tone"),
                    forbidden=m.get("forbidden"),
                    citation_style=m.get("citation_style"),
                    unknown_response=m.get("unknown_response"),
                    is_default=(mode_id == default_mode)
                )
                if result:
                    imported.append(mode_id)
            except Exception as e:
                errors.append({"id": mode_id, "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "default_mode": default_mode,
            "errors": errors,
            "source_file": file_path
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/import/policies")
def import_policies(policy_dir: str = "/brain/system/policies"):
    """
    Import policies from markdown files into database.
    Each .md file becomes a policy.
    """
    from .. import knowledge_db

    try:
        policy_path = Path(policy_dir)
        if not policy_path.exists():
            return {"status": "error", "error": f"Directory not found: {policy_dir}"}

        imported = []
        errors = []

        # Priority mapping based on filename
        priority_map = {
            "JARVIS_SYSTEM_PROMPT": 1000,
            "JARVIS_SELF": 900,
            "GOVERNANCE": 800,
            "COACH_OS": 700,
            "TASK_SYSTEM": 600
        }

        # Category mapping based on filename
        category_map = {
            "JARVIS_SYSTEM_PROMPT": "system",
            "JARVIS_SELF": "self",
            "GOVERNANCE": "governance",
            "COACH_OS": "coaching",
            "TASK_SYSTEM": "tasks"
        }

        for md_file in policy_path.glob("*.md"):
            try:
                policy_id = md_file.stem.lower().replace("_", "-")
                name = md_file.stem.replace("_", " ").title()

                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Get priority and category from mapping
                base_name = md_file.stem
                priority = priority_map.get(base_name, 100)
                category = category_map.get(base_name, "general")

                result = knowledge_db.upsert_policy(
                    policy_id=policy_id,
                    name=name,
                    content=content,
                    category=category,
                    priority=priority,
                    inject_in_prompt=True
                )
                if result:
                    imported.append(policy_id)
            except Exception as e:
                errors.append({"file": str(md_file), "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "errors": errors,
            "source_dir": policy_dir
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# =============================================================================
# CAPABILITIES MANAGEMENT
# =============================================================================

@router.get("/capabilities")
def get_capabilities():
    """
    Get current Jarvis capabilities (tools, features, version).
    Used for self-introspection and dynamic capability discovery.
    """
    try:
        # Try to load CAPABILITIES.json
        cap_file = get_capabilities_json_path()
        if cap_file.exists():
            with cap_file.open("r", encoding="utf-8") as f:
                capabilities = json.load(f)
                capabilities["source"] = "capabilities_json"
                return capabilities

        # Fallback: Generate runtime capabilities
        from .. import tools
        from .. import config

        tool_names = [name for name in dir(tools) if name.startswith("tool_")]

        return {
            "version": config.VERSION,
            "build_timestamp": config.BUILD_TIMESTAMP,
            "tools": [{"name": name, "status": "active"} for name in tool_names],
            "features": {
                "session_memory": {"enabled": True, "ttl_days": 30},
                "cross_session_learning": {"enabled": True},
                "proactive_hints": {"enabled": config.PROACTIVE_LEVEL > 1}
            },
            "source": "runtime_fallback"
        }
    except Exception as e:
        return {"error": str(e), "version": "unknown"}


@router.post("/refresh")
def refresh_capabilities():
    """
    Refresh capabilities cache (post-deploy hook).
    Triggers reload of CAPABILITIES.json and clears any cached state.
    """
    from ..observability import log_with_context

    try:
        cap_file = get_capabilities_json_path()

        if cap_file.exists():
            # Validate JSON
            with cap_file.open("r", encoding="utf-8") as f:
                capabilities = json.load(f)

            log_with_context(logger, "info", "Capabilities refreshed",
                           version=capabilities.get("version"),
                           tools_count=len(capabilities.get("tools", [])))

            return {
                "status": "success",
                "version": capabilities.get("version"),
                "tools_count": len(capabilities.get("tools", [])),
                "timestamp": capabilities.get("build_timestamp")
            }
        else:
            return {
                "status": "warning",
                "message": "CAPABILITIES.json not found, using runtime fallback"
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to refresh capabilities", error=str(e))
        return {"status": "error", "error": str(e)}


# =============================================================================
# DYNAMIC TOOL HOT-SWAP (Phase A)
# =============================================================================

@router.get("/tools/dynamic/status")
def get_dynamic_tools_status():
    """
    Get status of the dynamic tool system.

    Returns info about loaded dynamic tools, directories, and reload counts.
    """
    from ..tool_loader import DynamicToolLoader
    return DynamicToolLoader.get_status()


@router.post("/tools/dynamic/reload")
def reload_dynamic_tools(tool_name: Optional[str] = None):
    """
    Hot-reload dynamic tools without container restart.

    Args:
        tool_name: Specific tool to reload, or None/omit to reload all

    Example:
        POST /admin/tools/dynamic/reload              # Reload all
        POST /admin/tools/dynamic/reload?tool_name=my_tool  # Reload specific
    """
    from ..tool_loader import DynamicToolLoader
    from ..observability import log_with_context

    try:
        result = DynamicToolLoader.reload(tool_name)

        # Also update TOOL_REGISTRY with new handlers
        from .. import tools
        dynamic_handlers = DynamicToolLoader.get_all_handlers()
        tools.TOOL_REGISTRY.update(dynamic_handlers)

        # Update TOOL_DEFINITIONS with schemas so Claude knows about them
        dynamic_schemas = DynamicToolLoader.get_all_schemas()
        # Remove old dynamic tool schemas and add new ones
        # Handle both Anthropic format (name at top) and OpenAI format (name inside function)
        dynamic_tool_names = set(dynamic_handlers.keys())
        tools.TOOL_DEFINITIONS = [
            t for t in tools.TOOL_DEFINITIONS
            if (t.get("name") or t.get("function", {}).get("name")) not in dynamic_tool_names
        ]
        tools.TOOL_DEFINITIONS.extend(dynamic_schemas)

        log_with_context(logger, "info", "Dynamic tools reloaded",
                        tool_name=tool_name or "all",
                        success=result.get("success", result.get("success_count", 0)),
                        schemas_updated=len(dynamic_schemas))

        return {
            "status": "success",
            **result,
            "registry_updated": True,
            "definitions_updated": len(dynamic_schemas),
            "total_tools_in_registry": len(tools.TOOL_REGISTRY)
        }
    except Exception as e:
        log_with_context(logger, "error", "Failed to reload dynamic tools", error=str(e))
        return {"status": "error", "error": str(e)}


@router.post("/tools/dynamic/unload/{tool_name}")
def unload_dynamic_tool(tool_name: str):
    """
    Unload a dynamic tool from the registry.

    The tool file remains on disk but is no longer available.
    """
    from ..tool_loader import DynamicToolLoader
    from .. import tools

    try:
        # Remove from dynamic loader
        success = DynamicToolLoader.unload(tool_name)

        # Remove from TOOL_REGISTRY if present
        if tool_name in tools.TOOL_REGISTRY:
            del tools.TOOL_REGISTRY[tool_name]

        return {
            "status": "success" if success else "not_found",
            "tool": tool_name,
            "removed_from_registry": tool_name not in tools.TOOL_REGISTRY
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/tools/dynamic/list")
def list_dynamic_tool_files():
    """
    List available dynamic tool files (including not-yet-loaded).
    """
    from ..tool_loader import TOOLS_DYNAMIC_DIR, DynamicToolLoader

    files = []
    if TOOLS_DYNAMIC_DIR.exists():
        for py_file in TOOLS_DYNAMIC_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            tool_name = py_file.stem
            loaded = DynamicToolLoader.get_tool(tool_name) is not None
            files.append({
                "name": tool_name,
                "file": py_file.name,
                "loaded": loaded,
                "size_bytes": py_file.stat().st_size,
                "modified": py_file.stat().st_mtime
            })

    return {
        "directory": str(TOOLS_DYNAMIC_DIR),
        "exists": TOOLS_DYNAMIC_DIR.exists(),
        "files": files,
        "count": len(files)
    }


# =============================================================================
# DEPLOY HISTORY (Multi-Agent Coordination)
# =============================================================================

class DeployHistoryEntry(BaseModel):
    """Record of a deployment"""
    agent: str
    git_sha: str
    tier: int
    status: str
    elapsed_seconds: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/deploy-history")
def record_deploy_history(entry: DeployHistoryEntry):
    """
    Record a deployment in history.
    Called by deploy-smart.sh after each successful deploy.
    """
    from ..tool_modules.postgres_state import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO deploy_history
                        (agent, git_sha, tier, status, elapsed_seconds, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    entry.agent,
                    entry.git_sha,
                    entry.tier,
                    entry.status,
                    entry.elapsed_seconds,
                    json.dumps(entry.metadata or {})
                ))
                deploy_id = cur.fetchone()["id"]
                conn.commit()

        logger.info(f"Deploy recorded: {entry.agent} tier={entry.tier} sha={entry.git_sha}")
        return {"status": "recorded", "deploy_id": deploy_id}

    except Exception as e:
        logger.error(f"Failed to record deploy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deploy-history")
def get_deploy_history(limit: int = 20, agent: Optional[str] = None):
    """
    Get recent deployment history.
    Useful for debugging multi-agent deploy issues.
    """
    from ..tool_modules.postgres_state import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if agent:
                    cur.execute("""
                        SELECT id, agent, git_sha, tier, status, elapsed_seconds,
                               started_at, completed_at
                        FROM deploy_history
                        WHERE agent = %s
                        ORDER BY started_at DESC
                        LIMIT %s
                    """, (agent, limit))
                else:
                    cur.execute("""
                        SELECT id, agent, git_sha, tier, status, elapsed_seconds,
                               started_at, completed_at
                        FROM deploy_history
                        ORDER BY started_at DESC
                        LIMIT %s
                    """, (limit,))

                rows = cur.fetchall()

        return {
            "deploys": [dict(r) for r in rows],
            "count": len(rows),
            "filter_agent": agent
        }

    except Exception as e:
        logger.error(f"Failed to get deploy history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
