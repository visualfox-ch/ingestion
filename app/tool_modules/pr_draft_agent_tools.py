"""
Jarvis PR-Draft Agent - Tier 3 Autonomy (#9)

Transforms issues/tickets into PR-ready drafts:
- Issue analysis and requirement extraction
- Code change proposals with diffs
- Branch and commit creation
- Integration with approval workflow
- PR description generation

Requires Level 3 autonomy for actual PR creation.
"""

import os
import json
import logging
import hashlib
import subprocess
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# Configuration
PR_DRAFT_STATE_FILE = "/brain/system/state/pr_draft_state.json"
PR_DRAFT_HISTORY_FILE = "/brain/system/state/pr_draft_history.json"
PROPOSALS_DIR = "/brain/system/state/pr_proposals"
MAX_HISTORY_ENTRIES = 200

# Git configuration
GIT_AUTHOR_NAME = os.getenv("GIT_AUTHOR_NAME", "Jarvis")
GIT_AUTHOR_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "jarvis@projektil.ch")
DEFAULT_REPO_PATH = "/brain/system/ingestion"


class DraftStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    ABANDONED = "abandoned"


class ChangeType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    DOCS = "docs"
    TEST = "test"
    CHORE = "chore"


def _load_state() -> Dict[str, Any]:
    """Load PR draft state."""
    try:
        if os.path.exists(PR_DRAFT_STATE_FILE):
            with open(PR_DRAFT_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading PR draft state: {e}")

    return {
        "active_drafts": [],
        "statistics": {
            "total_drafts": 0,
            "approved": 0,
            "rejected": 0,
            "merged": 0
        }
    }


def _save_state(state: Dict[str, Any]) -> bool:
    """Save PR draft state."""
    try:
        os.makedirs(os.path.dirname(PR_DRAFT_STATE_FILE), exist_ok=True)
        with open(PR_DRAFT_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving PR draft state: {e}")
        return False


def _load_history() -> List[Dict[str, Any]]:
    """Load PR draft history."""
    try:
        if os.path.exists(PR_DRAFT_HISTORY_FILE):
            with open(PR_DRAFT_HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading PR history: {e}")
    return []


def _save_history(history: List[Dict[str, Any]]) -> bool:
    """Save PR draft history."""
    try:
        os.makedirs(os.path.dirname(PR_DRAFT_HISTORY_FILE), exist_ok=True)
        history = history[-MAX_HISTORY_ENTRIES:]
        with open(PR_DRAFT_HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving PR history: {e}")
        return False


def _generate_draft_id(issue_title: str) -> str:
    """Generate unique draft ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '-', issue_title.lower())[:30]
    hash_suffix = hashlib.md5(f"{issue_title}{timestamp}".encode()).hexdigest()[:6]
    return f"pr_{slug}_{hash_suffix}"


def _generate_branch_name(draft_id: str, change_type: str) -> str:
    """Generate git branch name."""
    prefix_map = {
        "feature": "feature",
        "bugfix": "fix",
        "refactor": "refactor",
        "docs": "docs",
        "test": "test",
        "chore": "chore"
    }
    prefix = prefix_map.get(change_type, "feature")
    clean_id = draft_id.replace("pr_", "")
    return f"{prefix}/{clean_id}"


def _run_git_command(cmd: List[str], repo_path: str = DEFAULT_REPO_PATH) -> Tuple[bool, str]:
    """Run a git command and return result."""
    try:
        result = subprocess.run(
            ["git"] + cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Git command timed out"
    except Exception as e:
        return False, str(e)


def _analyze_issue_requirements(
    issue_title: str,
    issue_description: str
) -> Dict[str, Any]:
    """Analyze issue to extract requirements and affected areas."""
    # Keywords for detecting change type
    feature_keywords = ["add", "implement", "create", "new", "feature", "support"]
    bugfix_keywords = ["fix", "bug", "error", "crash", "broken", "issue", "wrong"]
    refactor_keywords = ["refactor", "improve", "optimize", "clean", "restructure"]
    docs_keywords = ["document", "readme", "docs", "documentation", "comment"]
    test_keywords = ["test", "testing", "coverage", "spec"]

    combined = f"{issue_title} {issue_description}".lower()

    # Detect change type
    if any(kw in combined for kw in bugfix_keywords):
        change_type = "bugfix"
    elif any(kw in combined for kw in refactor_keywords):
        change_type = "refactor"
    elif any(kw in combined for kw in docs_keywords):
        change_type = "docs"
    elif any(kw in combined for kw in test_keywords):
        change_type = "test"
    elif any(kw in combined for kw in feature_keywords):
        change_type = "feature"
    else:
        change_type = "chore"

    # Extract potential file patterns
    file_patterns = []
    # Look for file mentions
    file_matches = re.findall(r'[\w/]+\.(py|js|ts|json|yaml|yml|md)', combined)
    file_patterns.extend(file_matches)

    # Look for module/component mentions
    module_patterns = re.findall(r'(tool_modules|routers|services|models|schemas)/\w+', combined)
    file_patterns.extend(module_patterns)

    # Extract potential dependencies
    dependencies = []
    dep_matches = re.findall(r'(import|require|dependency|depends on)\s+(\w+)', combined)
    dependencies = [m[1] for m in dep_matches]

    # Estimate complexity
    complexity = "low"
    if len(issue_description) > 500 or "multiple" in combined or "complex" in combined:
        complexity = "high"
    elif len(issue_description) > 200 or len(file_patterns) > 3:
        complexity = "medium"

    return {
        "change_type": change_type,
        "complexity": complexity,
        "file_patterns": list(set(file_patterns)),
        "dependencies": list(set(dependencies)),
        "keywords": [w for w in combined.split() if len(w) > 3][:20]
    }


def _generate_pr_description(
    issue_title: str,
    issue_description: str,
    analysis: Dict[str, Any],
    changes: List[Dict[str, Any]]
) -> str:
    """Generate PR description markdown."""
    change_emoji = {
        "feature": "sparkles",
        "bugfix": "bug",
        "refactor": "recycle",
        "docs": "memo",
        "test": "white_check_mark",
        "chore": "wrench"
    }
    emoji = change_emoji.get(analysis["change_type"], "gear")

    files_changed = [c["file"] for c in changes]

    description = f"""## :{emoji}: {analysis['change_type'].title()}: {issue_title}

### Summary
{issue_description}

### Changes
{chr(10).join(f"- `{f}`" for f in files_changed)}

### Analysis
- **Type:** {analysis['change_type']}
- **Complexity:** {analysis['complexity']}
- **Files affected:** {len(files_changed)}

### Checklist
- [ ] Code follows project style guidelines
- [ ] Tests added/updated as needed
- [ ] Documentation updated
- [ ] No breaking changes (or documented)

---
*Generated by Jarvis PR-Draft Agent*
"""
    return description


def analyze_issue(
    issue_title: str,
    issue_description: str,
    issue_id: Optional[str] = None,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze an issue and extract requirements for PR creation.

    Args:
        issue_title: Title of the issue
        issue_description: Full description of the issue
        issue_id: Optional external issue ID (e.g., from Linear, GitHub)
        source: Optional source system (linear, github, internal)

    Returns:
        Dict with analysis results and recommendations
    """
    analysis = _analyze_issue_requirements(issue_title, issue_description)

    # Generate draft ID
    draft_id = _generate_draft_id(issue_title)
    branch_name = _generate_branch_name(draft_id, analysis["change_type"])

    # Risk assessment
    risk_level = "low"
    risk_factors = []

    if analysis["complexity"] == "high":
        risk_level = "high"
        risk_factors.append("High complexity issue")
    elif analysis["complexity"] == "medium":
        risk_level = "medium"
        risk_factors.append("Medium complexity issue")

    if any("api" in f.lower() for f in analysis["file_patterns"]):
        risk_level = "high" if risk_level != "high" else risk_level
        risk_factors.append("API changes detected")

    if any("database" in kw or "migration" in kw for kw in analysis["keywords"]):
        risk_level = "high"
        risk_factors.append("Database changes may be involved")

    # Autonomy level needed
    autonomy_needed = 3 if risk_level == "high" else 2

    return {
        "success": True,
        "draft_id": draft_id,
        "branch_name": branch_name,
        "issue": {
            "title": issue_title,
            "description": issue_description[:500] + "..." if len(issue_description) > 500 else issue_description,
            "id": issue_id,
            "source": source
        },
        "analysis": analysis,
        "risk_assessment": {
            "level": risk_level,
            "factors": risk_factors
        },
        "autonomy_level_required": autonomy_needed,
        "recommendations": [
            f"Create branch: {branch_name}",
            f"Change type: {analysis['change_type']}",
            f"Estimated complexity: {analysis['complexity']}",
            "Review file patterns: " + ", ".join(analysis["file_patterns"][:5]) if analysis["file_patterns"] else "No specific files detected"
        ]
    }


def create_pr_draft(
    issue_title: str,
    issue_description: str,
    proposed_changes: List[Dict[str, Any]],
    issue_id: Optional[str] = None,
    auto_branch: bool = False
) -> Dict[str, Any]:
    """
    Create a PR draft with proposed changes.

    Args:
        issue_title: Title of the issue
        issue_description: Description of the issue
        proposed_changes: List of proposed changes [{file, action, content, description}]
        issue_id: Optional external issue ID
        auto_branch: If True, automatically create git branch

    Returns:
        Dict with draft details
    """
    # Analyze issue
    analysis_result = analyze_issue(issue_title, issue_description, issue_id)
    draft_id = analysis_result["draft_id"]
    branch_name = analysis_result["branch_name"]
    analysis = analysis_result["analysis"]

    # Validate proposed changes
    validated_changes = []
    for change in proposed_changes:
        if not change.get("file") or not change.get("action"):
            continue

        validated_change = {
            "file": change["file"],
            "action": change.get("action", "modify"),  # add, modify, delete
            "description": change.get("description", ""),
            "content": change.get("content", ""),
            "diff": change.get("diff", "")
        }
        validated_changes.append(validated_change)

    if not validated_changes:
        return {
            "success": False,
            "error": "No valid proposed changes provided"
        }

    # Generate PR description
    pr_description = _generate_pr_description(
        issue_title, issue_description, analysis, validated_changes
    )

    # Create draft record
    draft = {
        "draft_id": draft_id,
        "branch_name": branch_name,
        "status": DraftStatus.DRAFT.value,
        "created_at": datetime.now().isoformat(),
        "issue": {
            "title": issue_title,
            "description": issue_description,
            "id": issue_id
        },
        "analysis": analysis,
        "proposed_changes": validated_changes,
        "pr_description": pr_description,
        "branch_created": False,
        "commits": []
    }

    # Save proposal to file
    os.makedirs(PROPOSALS_DIR, exist_ok=True)
    proposal_file = f"{PROPOSALS_DIR}/{draft_id}.json"
    with open(proposal_file, "w") as f:
        json.dump(draft, f, indent=2)

    # Optionally create branch
    if auto_branch:
        success, message = _run_git_command(["checkout", "-b", branch_name])
        if success:
            draft["branch_created"] = True
            # Switch back to main
            _run_git_command(["checkout", "main"])
        else:
            draft["branch_error"] = message

    # Update state
    state = _load_state()
    state["active_drafts"].append({
        "draft_id": draft_id,
        "title": issue_title,
        "status": draft["status"],
        "created_at": draft["created_at"],
        "change_type": analysis["change_type"]
    })
    state["statistics"]["total_drafts"] += 1
    _save_state(state)

    return {
        "success": True,
        "draft_id": draft_id,
        "branch_name": branch_name,
        "status": draft["status"],
        "files_affected": len(validated_changes),
        "pr_description_preview": pr_description[:500] + "...",
        "proposal_file": proposal_file,
        "branch_created": draft.get("branch_created", False),
        "next_steps": [
            "Review proposed changes with get_draft_details",
            "Approve draft with approve_pr_draft",
            "Or modify changes and create new draft"
        ]
    }


def get_draft_details(draft_id: str) -> Dict[str, Any]:
    """
    Get full details of a PR draft.

    Args:
        draft_id: The draft ID to retrieve

    Returns:
        Dict with full draft details
    """
    proposal_file = f"{PROPOSALS_DIR}/{draft_id}.json"

    if not os.path.exists(proposal_file):
        return {
            "success": False,
            "error": f"Draft '{draft_id}' not found"
        }

    try:
        with open(proposal_file, "r") as f:
            draft = json.load(f)

        return {
            "success": True,
            "draft": draft
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def list_pr_drafts(
    status: Optional[str] = None,
    change_type: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    List all PR drafts with optional filtering.

    Args:
        status: Filter by status (draft, proposed, approved, etc.)
        change_type: Filter by change type (feature, bugfix, etc.)
        limit: Maximum number of results

    Returns:
        Dict with list of drafts
    """
    state = _load_state()
    drafts = state.get("active_drafts", [])

    # Filter
    if status:
        drafts = [d for d in drafts if d.get("status") == status]
    if change_type:
        drafts = [d for d in drafts if d.get("change_type") == change_type]

    # Sort by creation date (newest first)
    drafts = sorted(drafts, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]

    return {
        "success": True,
        "count": len(drafts),
        "drafts": drafts,
        "statistics": state.get("statistics", {})
    }


def approve_pr_draft(
    draft_id: str,
    approved_by: str,
    comment: Optional[str] = None,
    create_branch: bool = True,
    create_commits: bool = True
) -> Dict[str, Any]:
    """
    Approve a PR draft and optionally create branch/commits.

    Args:
        draft_id: The draft ID to approve
        approved_by: Who approved the draft
        comment: Optional approval comment
        create_branch: If True, create the git branch
        create_commits: If True, create commits for changes

    Returns:
        Dict with approval result
    """
    # Check autonomy level
    try:
        from .autonomy_tools import check_action_allowed, request_approval
        action_check = check_action_allowed("create_pr")
        if not action_check.get("allowed"):
            # Request approval through autonomy system
            from .autonomy_tools import assess_risk_impact
            risk = assess_risk_impact(
                action="create_pr_draft",
                description=f"Creating PR for draft {draft_id}",
                affected_components=["git", "codebase"],
                reversible=True,
                data_impact=False,
                user_facing=False
            )
            approval = request_approval(
                action="create_pr_draft",
                description=f"Create PR from draft {draft_id}",
                risk_assessment=risk,
                context={"draft_id": draft_id, "requested_by": approved_by}
            )
            return {
                "success": False,
                "requires_approval": True,
                "approval_request_id": approval.get("request_id"),
                "message": "PR creation requires human approval at current autonomy level"
            }
    except ImportError:
        logger.warning("Autonomy tools not available, proceeding without level check")

    # Load draft
    proposal_file = f"{PROPOSALS_DIR}/{draft_id}.json"
    if not os.path.exists(proposal_file):
        return {
            "success": False,
            "error": f"Draft '{draft_id}' not found"
        }

    with open(proposal_file, "r") as f:
        draft = json.load(f)

    if draft["status"] not in [DraftStatus.DRAFT.value, DraftStatus.PROPOSED.value]:
        return {
            "success": False,
            "error": f"Draft is in '{draft['status']}' status, cannot approve"
        }

    branch_name = draft["branch_name"]
    commits_created = []
    branch_created = False

    # Create branch if requested
    if create_branch and not draft.get("branch_created"):
        success, message = _run_git_command(["checkout", "-b", branch_name])
        if success:
            branch_created = True
        else:
            # Try to checkout existing branch
            success, _ = _run_git_command(["checkout", branch_name])
            branch_created = success

    # Create commits for changes if requested
    if create_commits and branch_created:
        for change in draft.get("proposed_changes", []):
            file_path = change.get("file")
            content = change.get("content")
            action = change.get("action")

            if action == "add" and content:
                # Write new file
                full_path = os.path.join(DEFAULT_REPO_PATH, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)

                # Git add
                _run_git_command(["add", file_path])
                commits_created.append({
                    "file": file_path,
                    "action": "added"
                })

            elif action == "modify" and content:
                # Modify existing file
                full_path = os.path.join(DEFAULT_REPO_PATH, file_path)
                if os.path.exists(full_path):
                    with open(full_path, "w") as f:
                        f.write(content)
                    _run_git_command(["add", file_path])
                    commits_created.append({
                        "file": file_path,
                        "action": "modified"
                    })

            elif action == "delete":
                # Delete file
                _run_git_command(["rm", file_path])
                commits_created.append({
                    "file": file_path,
                    "action": "deleted"
                })

        # Create commit if changes were made
        if commits_created:
            commit_msg = f"{draft['analysis']['change_type']}: {draft['issue']['title']}\n\nDraft ID: {draft_id}\nApproved by: {approved_by}"
            _run_git_command([
                "-c", f"user.name={GIT_AUTHOR_NAME}",
                "-c", f"user.email={GIT_AUTHOR_EMAIL}",
                "commit", "-m", commit_msg
            ])

        # Switch back to main
        _run_git_command(["checkout", "main"])

    # Update draft status
    draft["status"] = DraftStatus.APPROVED.value
    draft["approved_at"] = datetime.now().isoformat()
    draft["approved_by"] = approved_by
    draft["approval_comment"] = comment
    draft["branch_created"] = branch_created
    draft["commits"] = commits_created

    with open(proposal_file, "w") as f:
        json.dump(draft, f, indent=2)

    # Update state
    state = _load_state()
    for d in state.get("active_drafts", []):
        if d["draft_id"] == draft_id:
            d["status"] = DraftStatus.APPROVED.value
            break
    state["statistics"]["approved"] += 1
    _save_state(state)

    # Add to history
    history = _load_history()
    history.append({
        "draft_id": draft_id,
        "action": "approved",
        "approved_by": approved_by,
        "timestamp": datetime.now().isoformat(),
        "branch_created": branch_created,
        "commits_count": len(commits_created)
    })
    _save_history(history)

    return {
        "success": True,
        "draft_id": draft_id,
        "status": DraftStatus.APPROVED.value,
        "branch_name": branch_name,
        "branch_created": branch_created,
        "commits_created": len(commits_created),
        "approved_by": approved_by,
        "next_steps": [
            f"Push branch: git push -u origin {branch_name}",
            "Create PR in GitHub/GitLab",
            "Or use finalize_pr_draft to complete"
        ]
    }


def reject_pr_draft(
    draft_id: str,
    rejected_by: str,
    reason: str
) -> Dict[str, Any]:
    """
    Reject a PR draft.

    Args:
        draft_id: The draft ID to reject
        rejected_by: Who rejected the draft
        reason: Reason for rejection

    Returns:
        Dict with rejection result
    """
    proposal_file = f"{PROPOSALS_DIR}/{draft_id}.json"
    if not os.path.exists(proposal_file):
        return {
            "success": False,
            "error": f"Draft '{draft_id}' not found"
        }

    with open(proposal_file, "r") as f:
        draft = json.load(f)

    draft["status"] = DraftStatus.REJECTED.value
    draft["rejected_at"] = datetime.now().isoformat()
    draft["rejected_by"] = rejected_by
    draft["rejection_reason"] = reason

    with open(proposal_file, "w") as f:
        json.dump(draft, f, indent=2)

    # Update state
    state = _load_state()
    for d in state.get("active_drafts", []):
        if d["draft_id"] == draft_id:
            d["status"] = DraftStatus.REJECTED.value
            break
    state["statistics"]["rejected"] += 1
    _save_state(state)

    # Add to history
    history = _load_history()
    history.append({
        "draft_id": draft_id,
        "action": "rejected",
        "rejected_by": rejected_by,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })
    _save_history(history)

    return {
        "success": True,
        "draft_id": draft_id,
        "status": DraftStatus.REJECTED.value,
        "rejected_by": rejected_by,
        "reason": reason
    }


def get_pr_draft_history(
    draft_id: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Get PR draft history.

    Args:
        draft_id: Optional filter by draft ID
        limit: Maximum entries to return

    Returns:
        Dict with history entries
    """
    history = _load_history()

    if draft_id:
        history = [h for h in history if h.get("draft_id") == draft_id]

    history = sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]

    return {
        "success": True,
        "count": len(history),
        "history": history
    }


def generate_change_proposal(
    file_path: str,
    change_description: str,
    change_type: str = "modify"
) -> Dict[str, Any]:
    """
    Generate a change proposal for a specific file.

    Args:
        file_path: Path to the file to change
        change_description: What should be changed
        change_type: Type of change (add, modify, delete)

    Returns:
        Dict with change proposal
    """
    full_path = os.path.join(DEFAULT_REPO_PATH, file_path)
    current_content = ""
    file_exists = os.path.exists(full_path)

    if file_exists and change_type != "delete":
        try:
            with open(full_path, "r") as f:
                current_content = f.read()
        except Exception as e:
            return {
                "success": False,
                "error": f"Cannot read file: {e}"
            }

    proposal = {
        "file": file_path,
        "action": change_type,
        "description": change_description,
        "current_content_preview": current_content[:500] + "..." if len(current_content) > 500 else current_content,
        "file_exists": file_exists,
        "requires_manual_edit": True,
        "suggested_approach": []
    }

    # Add suggestions based on change type
    if change_type == "add":
        proposal["suggested_approach"] = [
            "Create new file with appropriate structure",
            "Add necessary imports",
            "Include docstrings and type hints",
            "Add to relevant __init__.py if module"
        ]
    elif change_type == "modify":
        proposal["suggested_approach"] = [
            "Review current implementation",
            "Identify exact lines to change",
            "Ensure backwards compatibility",
            "Update related tests"
        ]
    elif change_type == "delete":
        proposal["suggested_approach"] = [
            "Verify file is not imported elsewhere",
            "Remove from __init__.py if present",
            "Update any documentation references",
            "Check for orphaned tests"
        ]

    return {
        "success": True,
        "proposal": proposal
    }


# Tool definitions
PR_DRAFT_AGENT_TOOLS = [
    {
        "name": "analyze_issue",
        "description": "Analyze an issue/ticket to extract requirements and plan PR creation. Returns change type, complexity, affected files, and recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_title": {
                    "type": "string",
                    "description": "Title of the issue"
                },
                "issue_description": {
                    "type": "string",
                    "description": "Full description of the issue"
                },
                "issue_id": {
                    "type": "string",
                    "description": "Optional external issue ID"
                },
                "source": {
                    "type": "string",
                    "enum": ["linear", "github", "internal"],
                    "description": "Source system of the issue"
                }
            },
            "required": ["issue_title", "issue_description"]
        }
    },
    {
        "name": "create_pr_draft",
        "description": "Create a PR draft with proposed changes. Generates branch name, PR description, and saves proposal for review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_title": {
                    "type": "string",
                    "description": "Title of the issue"
                },
                "issue_description": {
                    "type": "string",
                    "description": "Description of the issue"
                },
                "proposed_changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "action": {"type": "string", "enum": ["add", "modify", "delete"]},
                            "content": {"type": "string"},
                            "description": {"type": "string"}
                        },
                        "required": ["file", "action"]
                    },
                    "description": "List of proposed file changes"
                },
                "issue_id": {
                    "type": "string",
                    "description": "Optional external issue ID"
                },
                "auto_branch": {
                    "type": "boolean",
                    "default": False,
                    "description": "Automatically create git branch"
                }
            },
            "required": ["issue_title", "issue_description", "proposed_changes"]
        }
    },
    {
        "name": "get_draft_details",
        "description": "Get full details of a PR draft including proposed changes and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "The draft ID to retrieve"
                }
            },
            "required": ["draft_id"]
        }
    },
    {
        "name": "list_pr_drafts",
        "description": "List all PR drafts with optional filtering by status or change type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "proposed", "approved", "rejected", "merged", "abandoned"],
                    "description": "Filter by status"
                },
                "change_type": {
                    "type": "string",
                    "enum": ["feature", "bugfix", "refactor", "docs", "test", "chore"],
                    "description": "Filter by change type"
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum results"
                }
            }
        }
    },
    {
        "name": "approve_pr_draft",
        "description": "Approve a PR draft and optionally create branch/commits. Requires appropriate autonomy level.",
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "The draft ID to approve"
                },
                "approved_by": {
                    "type": "string",
                    "description": "Who is approving"
                },
                "comment": {
                    "type": "string",
                    "description": "Optional approval comment"
                },
                "create_branch": {
                    "type": "boolean",
                    "default": True,
                    "description": "Create git branch"
                },
                "create_commits": {
                    "type": "boolean",
                    "default": True,
                    "description": "Create commits for changes"
                }
            },
            "required": ["draft_id", "approved_by"]
        }
    },
    {
        "name": "reject_pr_draft",
        "description": "Reject a PR draft with a reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "The draft ID to reject"
                },
                "rejected_by": {
                    "type": "string",
                    "description": "Who is rejecting"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for rejection"
                }
            },
            "required": ["draft_id", "rejected_by", "reason"]
        }
    },
    {
        "name": "get_pr_draft_history",
        "description": "Get history of PR draft actions (approvals, rejections, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "Optional filter by draft ID"
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum entries"
                }
            }
        }
    },
    {
        "name": "generate_change_proposal",
        "description": "Generate a change proposal for a specific file with suggestions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "change_description": {
                    "type": "string",
                    "description": "What should be changed"
                },
                "change_type": {
                    "type": "string",
                    "enum": ["add", "modify", "delete"],
                    "default": "modify",
                    "description": "Type of change"
                }
            },
            "required": ["file_path", "change_description"]
        }
    }
]
