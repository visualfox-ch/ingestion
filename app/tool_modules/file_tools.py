"""
File Tools.

Project file read/write, source code access, roadmap reading.
Extracted from tools.py (Phase S4).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import os
import json
import glob
import shutil
import difflib

from ..capability_paths import (
    get_capability_catalog_path,
    get_capabilities_json_path,
    get_context_policy_path,
)
from ..observability import get_logger, log_with_context, metrics
from ..errors import JarvisException, ErrorCode, internal_error

logger = get_logger("jarvis.tools.file")

# Constants
BRAIN_PATH = os.getenv("BRAIN_PATH", "/brain")


def _core_tools():
    from .. import tools as core_tools
    return core_tools


def _allowed_file_paths() -> List[str]:
    return _core_tools().ALLOWED_FILE_PATHS


def _translate_path(file_path: str) -> str:
    return _core_tools()._translate_path(file_path)


def _is_allowed_path(file_path: str) -> bool:
    return _core_tools()._is_allowed_path(file_path)


def _is_blocked_path(file_path: str) -> bool:
    return _core_tools()._is_blocked_path(file_path)


def _get_audit_dir(file_path: str) -> str:
    return _core_tools()._get_audit_dir(file_path)


def _hash_content(content: str) -> str:
    return _core_tools()._hash_content(content)


def _read_single_file(file_path: str, max_lines: int) -> Dict[str, Any]:
    return _core_tools()._read_single_file(file_path, max_lines)


def _check_write_rate_limits(max_per_minute: int, max_per_hour: int) -> Dict[str, Any]:
    return _core_tools()._check_write_rate_limits(max_per_minute, max_per_hour)


def _requires_write_approval(file_path: str, approval_paths: List[str]) -> bool:
    return _core_tools()._requires_write_approval(file_path, approval_paths)


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
            "allowed_paths": _allowed_file_paths()
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
        "capability_catalog": str(get_capability_catalog_path()),
        "context_policy": str(get_context_policy_path()),
        "capabilities_json": str(get_capabilities_json_path()),
        "jarvis_self": "/brain/system/policies/JARVIS_SELF.md",
    }

    if file_key not in file_map:
        return {
            "error": "Unknown file_key",
            "allowed": sorted(list(file_map.keys()))
        }

    return tool_read_project_file(file_map[file_key], max_lines=max_lines)


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
            "allowed_paths": _allowed_file_paths()
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
    source_dir = "/brain/system/docker/app"

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

    source_dir = "/brain/system/docker/app"
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
