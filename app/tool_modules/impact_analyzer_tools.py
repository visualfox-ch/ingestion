"""
Dev-Co-Pilot: Impact Analyzer - Tier 2 #7 Jarvis Evolution

Analyzes code changes and predicts their impact:
- Dependency graph analysis
- Risk assessment for changes
- Affected components detection
- Breaking change warnings
- Test coverage suggestions
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

# Configuration
STATE_PATH = "/brain/system/state/impact_analyzer_state.json"
CODE_BASE_PATH = "/brain/system/ingestion/app"
DOCKER_APP_PATH = "/brain/system/docker/app"

# Risk weights for different types of changes
RISK_WEIGHTS = {
    "api_endpoint": 3.0,      # Changes to API endpoints are high risk
    "database": 4.0,          # Database changes are very high risk
    "authentication": 5.0,    # Auth changes are critical
    "core_service": 3.5,      # Core services are high risk
    "tool_module": 2.0,       # Tool modules are medium risk
    "utility": 1.0,           # Utilities are low risk
    "config": 2.5,            # Config changes can have wide impact
    "router": 3.0,            # Router changes affect API surface
    "test": 0.5,              # Test changes are low risk
}

# Patterns for detecting change types
CHANGE_PATTERNS = {
    "api_endpoint": [r"@router\.", r"@app\.(get|post|put|delete|patch)"],
    "database": [r"execute\(", r"\.query\(", r"CREATE TABLE", r"ALTER TABLE", r"psycopg", r"sqlalchemy"],
    "authentication": [r"verify_api_key", r"X-API-Key", r"authenticate", r"jwt", r"token"],
    "core_service": [r"class.*Service", r"def execute_tool", r"def process_"],
    "tool_module": [r"TOOL_DEFINITIONS", r"TOOL_REGISTRY", r"def.*\(.*\).*->.*Dict"],
    "config": [r"os\.getenv", r"\.env", r"config\[", r"settings\."],
    "router": [r"APIRouter", r"include_router", r"@router"],
}


def _load_state() -> Dict[str, Any]:
    """Load analyzer state from file."""
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state: {e}")

    return {
        "analysis_history": [],
        "known_dependencies": {},
        "statistics": {
            "total_analyses": 0,
            "high_risk_detected": 0,
            "breaking_changes_warned": 0
        }
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Save analyzer state to file."""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def _get_file_imports(file_path: str) -> List[str]:
    """Extract imports from a Python file."""
    imports = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match import statements
        import_patterns = [
            r"^import\s+(\S+)",
            r"^from\s+(\S+)\s+import",
        ]

        for pattern in import_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            imports.extend(matches)

    except Exception as e:
        logger.debug(f"Could not read imports from {file_path}: {e}")

    return imports


def _detect_change_type(content: str) -> List[str]:
    """Detect what types of changes are in the content."""
    detected_types = []

    for change_type, patterns in CHANGE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                if change_type not in detected_types:
                    detected_types.append(change_type)
                break

    return detected_types if detected_types else ["utility"]


def _calculate_risk_score(change_types: List[str], lines_changed: int) -> Tuple[float, str]:
    """Calculate risk score based on change types and scope."""
    base_score = sum(RISK_WEIGHTS.get(ct, 1.0) for ct in change_types)

    # Scale by lines changed (logarithmic)
    import math
    scope_multiplier = 1 + (math.log10(max(lines_changed, 1)) / 3)

    final_score = min(base_score * scope_multiplier, 10.0)

    if final_score >= 7:
        risk_level = "critical"
    elif final_score >= 5:
        risk_level = "high"
    elif final_score >= 3:
        risk_level = "medium"
    else:
        risk_level = "low"

    return round(final_score, 2), risk_level


def analyze_file_impact(
    file_path: str,
    show_dependencies: bool = True
) -> Dict[str, Any]:
    """
    Analyze the impact of a specific file in the codebase.

    Args:
        file_path: Path to the file to analyze
        show_dependencies: Include dependency analysis

    Returns:
        Dict with file analysis, dependencies, and impact assessment
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "file": file_path,
        "exists": False,
        "analysis": {},
        "dependencies": {},
        "impact": {}
    }

    # Normalize path
    if not file_path.startswith("/"):
        file_path = os.path.join(CODE_BASE_PATH, file_path)

    if not os.path.exists(file_path):
        result["error"] = f"File not found: {file_path}"
        return result

    result["exists"] = True

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        result["analysis"] = {
            "lines_of_code": len(lines),
            "file_size_bytes": len(content),
            "change_types": _detect_change_type(content),
        }

        # Calculate risk
        risk_score, risk_level = _calculate_risk_score(
            result["analysis"]["change_types"],
            result["analysis"]["lines_of_code"]
        )
        result["analysis"]["risk_score"] = risk_score
        result["analysis"]["risk_level"] = risk_level

        # Find dependencies
        if show_dependencies:
            imports = _get_file_imports(file_path)
            result["dependencies"]["imports"] = imports

            # Find files that import this file
            file_name = os.path.basename(file_path).replace(".py", "")
            dependents = []

            for search_path in [CODE_BASE_PATH, DOCKER_APP_PATH]:
                if os.path.exists(search_path):
                    for root, _, files in os.walk(search_path):
                        for f in files:
                            if f.endswith(".py"):
                                check_path = os.path.join(root, f)
                                try:
                                    with open(check_path, "r") as check_file:
                                        if file_name in check_file.read():
                                            rel_path = os.path.relpath(check_path, search_path)
                                            if rel_path not in dependents:
                                                dependents.append(rel_path)
                                except Exception:
                                    pass

            result["dependencies"]["dependent_files"] = dependents[:20]  # Limit

        # Impact assessment
        result["impact"] = {
            "affected_areas": result["analysis"]["change_types"],
            "dependent_count": len(result["dependencies"].get("dependent_files", [])),
            "breaking_change_risk": risk_level in ["high", "critical"],
            "requires_testing": result["analysis"]["risk_score"] >= 3
        }

    except Exception as e:
        result["error"] = str(e)

    return result


def analyze_change_impact(
    changed_files: List[str],
    change_description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze impact of multiple file changes together.

    Args:
        changed_files: List of file paths that changed
        change_description: Optional description of the change

    Returns:
        Dict with overall impact analysis and recommendations
    """
    state = _load_state()
    state["statistics"]["total_analyses"] += 1

    result = {
        "timestamp": datetime.now().isoformat(),
        "description": change_description,
        "files_analyzed": len(changed_files),
        "file_analyses": [],
        "overall_risk": {},
        "affected_components": set(),
        "recommendations": [],
        "test_suggestions": []
    }

    total_risk = 0
    all_change_types = set()
    all_dependents = set()

    for file_path in changed_files:
        analysis = analyze_file_impact(file_path, show_dependencies=True)
        result["file_analyses"].append({
            "file": file_path,
            "risk_level": analysis.get("analysis", {}).get("risk_level", "unknown"),
            "risk_score": analysis.get("analysis", {}).get("risk_score", 0),
            "change_types": analysis.get("analysis", {}).get("change_types", [])
        })

        # Aggregate
        total_risk += analysis.get("analysis", {}).get("risk_score", 0)
        all_change_types.update(analysis.get("analysis", {}).get("change_types", []))
        all_dependents.update(analysis.get("dependencies", {}).get("dependent_files", []))

    # Calculate overall risk
    avg_risk = total_risk / max(len(changed_files), 1)
    if avg_risk >= 6:
        overall_level = "critical"
        state["statistics"]["high_risk_detected"] += 1
    elif avg_risk >= 4:
        overall_level = "high"
        state["statistics"]["high_risk_detected"] += 1
    elif avg_risk >= 2:
        overall_level = "medium"
    else:
        overall_level = "low"

    result["overall_risk"] = {
        "score": round(avg_risk, 2),
        "level": overall_level,
        "total_files": len(changed_files),
        "total_dependents": len(all_dependents)
    }

    result["affected_components"] = list(all_change_types)

    # Generate recommendations
    if "api_endpoint" in all_change_types:
        result["recommendations"].append("API changes detected - update API documentation")
        result["recommendations"].append("Consider backwards compatibility")
        result["test_suggestions"].append("Run API integration tests")

    if "database" in all_change_types:
        result["recommendations"].append("Database changes - create migration script")
        result["recommendations"].append("Backup database before deployment")
        result["test_suggestions"].append("Test migration on staging first")
        state["statistics"]["breaking_changes_warned"] += 1

    if "authentication" in all_change_types:
        result["recommendations"].append("Auth changes - verify security implications")
        result["recommendations"].append("Test all authentication flows")
        result["test_suggestions"].append("Security audit recommended")
        state["statistics"]["breaking_changes_warned"] += 1

    if "tool_module" in all_change_types:
        result["recommendations"].append("Tool changes - verify TOOL_REGISTRY is updated")
        result["recommendations"].append("Check prompt_assembler categories")
        result["test_suggestions"].append("Test tool execution via agent endpoint")

    if "core_service" in all_change_types:
        result["recommendations"].append("Core service changes - extensive testing needed")
        result["test_suggestions"].append("Run full integration test suite")

    if len(all_dependents) > 5:
        result["recommendations"].append(f"High impact: {len(all_dependents)} files depend on changed code")
        result["test_suggestions"].append("Consider regression testing dependent modules")

    # Record in history
    state["analysis_history"].append({
        "timestamp": result["timestamp"],
        "files": len(changed_files),
        "risk_level": overall_level,
        "change_types": list(all_change_types)
    })
    state["analysis_history"] = state["analysis_history"][-100:]

    _save_state(state)

    return result


def get_dependency_graph(
    module_path: Optional[str] = None,
    depth: int = 2
) -> Dict[str, Any]:
    """
    Generate dependency graph for modules.

    Args:
        module_path: Specific module to analyze, or None for overview
        depth: How deep to trace dependencies

    Returns:
        Dict with dependency graph and statistics
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "depth": depth,
        "modules": {},
        "statistics": {}
    }

    search_path = CODE_BASE_PATH
    if module_path:
        search_path = os.path.join(CODE_BASE_PATH, module_path)

    if not os.path.exists(search_path):
        result["error"] = f"Path not found: {search_path}"
        return result

    module_imports = {}
    total_files = 0

    # Scan Python files
    for root, _, files in os.walk(search_path):
        for f in files:
            if f.endswith(".py") and not f.startswith("__"):
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, CODE_BASE_PATH)
                imports = _get_file_imports(file_path)

                # Filter to local imports
                local_imports = [
                    imp for imp in imports
                    if imp.startswith(".") or imp.startswith("app")
                ]

                module_imports[rel_path] = local_imports
                total_files += 1

    result["modules"] = module_imports
    result["statistics"] = {
        "total_modules": total_files,
        "total_dependencies": sum(len(v) for v in module_imports.values()),
        "most_depended_on": [],
        "most_dependencies": []
    }

    # Find most imported modules
    import_counts = {}
    for imports in module_imports.values():
        for imp in imports:
            import_counts[imp] = import_counts.get(imp, 0) + 1

    result["statistics"]["most_depended_on"] = sorted(
        import_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    # Find modules with most dependencies
    result["statistics"]["most_dependencies"] = sorted(
        [(k, len(v)) for k, v in module_imports.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return result


def suggest_test_coverage(
    file_path: str
) -> Dict[str, Any]:
    """
    Suggest test coverage for a file based on its content.

    Args:
        file_path: File to analyze for test suggestions

    Returns:
        Dict with test coverage suggestions
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "file": file_path,
        "suggestions": [],
        "test_cases": [],
        "priority": "medium"
    }

    # Normalize path
    if not file_path.startswith("/"):
        file_path = os.path.join(CODE_BASE_PATH, file_path)

    if not os.path.exists(file_path):
        result["error"] = f"File not found: {file_path}"
        return result

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find functions and classes
        functions = re.findall(r"def\s+(\w+)\s*\(", content)
        classes = re.findall(r"class\s+(\w+)\s*[:\(]", content)

        change_types = _detect_change_type(content)

        # Generate suggestions based on content
        if "api_endpoint" in change_types:
            result["priority"] = "high"
            result["suggestions"].append("Create API endpoint tests")
            for func in functions:
                if func.startswith("_"):
                    continue
                result["test_cases"].append(f"test_{func}_success")
                result["test_cases"].append(f"test_{func}_validation_error")

        if "database" in change_types:
            result["priority"] = "high"
            result["suggestions"].append("Create database integration tests")
            result["suggestions"].append("Test transaction rollback scenarios")

        if "authentication" in change_types:
            result["priority"] = "critical"
            result["suggestions"].append("Test authentication success and failure")
            result["suggestions"].append("Test token expiration handling")
            result["suggestions"].append("Test unauthorized access prevention")

        if "tool_module" in change_types:
            result["suggestions"].append("Test tool execution with valid inputs")
            result["suggestions"].append("Test tool error handling")
            for func in functions:
                if not func.startswith("_"):
                    result["test_cases"].append(f"test_tool_{func}")

        # Add general suggestions
        for cls in classes:
            result["test_cases"].append(f"test_{cls}_instantiation")

        for func in functions:
            if not func.startswith("_") and func not in [
                "get", "post", "put", "delete", "patch"
            ]:
                if f"test_{func}_success" not in result["test_cases"]:
                    result["test_cases"].append(f"test_{func}_happy_path")

    except Exception as e:
        result["error"] = str(e)

    return result


def get_analyzer_status() -> Dict[str, Any]:
    """
    Get current status of the Impact Analyzer.

    Returns:
        Dict with analyzer statistics and recent analyses
    """
    state = _load_state()

    return {
        "timestamp": datetime.now().isoformat(),
        "statistics": state.get("statistics", {}),
        "recent_analyses": state.get("analysis_history", [])[-10:],
        "configuration": {
            "risk_weights": RISK_WEIGHTS,
            "code_paths": [CODE_BASE_PATH, DOCKER_APP_PATH]
        }
    }


def assess_deployment_risk(
    changed_files: List[str]
) -> Dict[str, Any]:
    """
    Assess risk level for deploying changes.

    Args:
        changed_files: List of files that will be deployed

    Returns:
        Dict with deployment risk assessment and checklist
    """
    # Get impact analysis
    impact = analyze_change_impact(changed_files)

    result = {
        "timestamp": datetime.now().isoformat(),
        "can_deploy": True,
        "risk_level": impact["overall_risk"]["level"],
        "risk_score": impact["overall_risk"]["score"],
        "blocking_issues": [],
        "warnings": [],
        "checklist": [],
        "rollback_plan": []
    }

    # Check for blocking issues
    if impact["overall_risk"]["level"] == "critical":
        result["blocking_issues"].append("Critical risk level - manual review required")
        result["can_deploy"] = False

    if "database" in impact["affected_components"]:
        result["warnings"].append("Database changes included")
        result["checklist"].append("[ ] Create database backup")
        result["checklist"].append("[ ] Test migration on staging")
        result["rollback_plan"].append("Restore database from backup")

    if "authentication" in impact["affected_components"]:
        result["warnings"].append("Authentication changes included")
        result["checklist"].append("[ ] Verify auth flows work correctly")
        result["checklist"].append("[ ] Check existing sessions")
        result["rollback_plan"].append("Rollback auth service to previous version")

    if "api_endpoint" in impact["affected_components"]:
        result["warnings"].append("API changes included")
        result["checklist"].append("[ ] Update API documentation")
        result["checklist"].append("[ ] Notify API consumers if breaking")
        result["rollback_plan"].append("Revert API routes to previous version")

    # Standard checklist items
    result["checklist"].extend([
        "[ ] Run build script successfully",
        "[ ] Verify health check passes",
        "[ ] Check container logs for errors",
        "[ ] Test primary functionality"
    ])

    result["rollback_plan"].extend([
        "Keep previous image available",
        "Document current state before deploy",
        "Have manual rollback commands ready"
    ])

    # Recommendations based on risk
    if impact["overall_risk"]["score"] >= 5:
        result["checklist"].insert(0, "[ ] Get manual approval before deploy")
        result["warnings"].append("High risk - consider staged rollout")

    return result


# Tool definitions for registration
IMPACT_ANALYZER_TOOLS = [
    {
        "name": "analyze_file_impact",
        "description": "Analyze the impact of a specific file in the codebase including dependencies and risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to analyze (relative to app/)"
                },
                "show_dependencies": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include dependency analysis"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "analyze_change_impact",
        "description": "Analyze impact of multiple file changes together with recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that changed"
                },
                "change_description": {
                    "type": "string",
                    "description": "Optional description of the change"
                }
            },
            "required": ["changed_files"]
        }
    },
    {
        "name": "get_dependency_graph",
        "description": "Generate dependency graph for modules showing what depends on what.",
        "input_schema": {
            "type": "object",
            "properties": {
                "module_path": {
                    "type": "string",
                    "description": "Specific module to analyze, or omit for overview"
                },
                "depth": {
                    "type": "integer",
                    "default": 2,
                    "description": "How deep to trace dependencies"
                }
            }
        }
    },
    {
        "name": "suggest_test_coverage",
        "description": "Suggest test coverage for a file based on its content and change types.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File to analyze for test suggestions"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "get_analyzer_status",
        "description": "Get current status of the Impact Analyzer including statistics.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "assess_deployment_risk",
        "description": "Assess risk level for deploying changes with checklist and rollback plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files that will be deployed"
                }
            },
            "required": ["changed_files"]
        }
    }
]
