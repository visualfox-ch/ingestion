#!/usr/bin/env python3
"""
Generate CAPABILITIES.json and update FEATURES.md
Auto-run after each deployment to keep Jarvis self-aware.
"""
import json
import sys
import ast
import re
import argparse
from pathlib import Path
from datetime import datetime
import subprocess
from typing import Iterable, List

# Paths
REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"
TOOLS_PY = APP_ROOT / "tools.py"
CONFIG_PY = APP_ROOT / "config.py"
MAIN_PY = APP_ROOT / "main.py"
OUTPUT_JSON = REPO_ROOT / "docs" / "CAPABILITIES.json"
FEATURES_MD = REPO_ROOT / "docs" / "FEATURES.md"
TOOL_MODULES_DIR = APP_ROOT / "tool_modules"
TOOLS_PACKAGE_DIR = APP_ROOT / "tools"
ROUTERS_DIR = APP_ROOT / "routers"
EXTRA_TOOL_SCHEMA_FILES = [
    APP_ROOT / "services" / "knowledge_retrieval.py",
    APP_ROOT / "services" / "knowledge_tools.py",
]


def get_git_info():
    """Get current git version info."""
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        commit_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        return {
            "commit": commit_hash,
            "message": commit_msg[:100]
        }
    except:
        return {"commit": "unknown", "message": ""}


def extract_tools_from_file(file_path: Path) -> List[dict]:
    """Parse a Python module and extract tool functions and tool schema definitions."""
    tools = []
    
    if not file_path.exists():
        return tools
    
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    def _extract_string(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        try:
            value = ast.literal_eval(node)
        except Exception:
            return None
        return value if isinstance(value, str) else None

    def _extract_parameter_names(schema_node: ast.AST | None) -> list[str]:
        if schema_node is None:
            return []

        if isinstance(schema_node, ast.Dict):
            for key_node, value_node in zip(schema_node.keys, schema_node.values):
                if not isinstance(key_node, ast.Constant) or key_node.value != "properties":
                    continue
                if isinstance(value_node, ast.Dict):
                    return sorted(
                        str(prop_key.value)
                        for prop_key in value_node.keys
                        if isinstance(prop_key, ast.Constant) and isinstance(prop_key.value, str)
                    )

        try:
            schema = ast.literal_eval(schema_node)
        except Exception:
            return []

        if not isinstance(schema, dict):
            return []

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return []

        return sorted(str(key) for key in properties.keys())

    def _normalize_tool_dict(dict_node: ast.AST) -> dict | None:
        if not isinstance(dict_node, ast.Dict):
            return None

        name = None
        description = ""
        params: list[str] = []

        for key_node, value_node in zip(dict_node.keys, dict_node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue

            key = key_node.value
            if key == "name":
                name = _extract_string(value_node)
            elif key == "description":
                description = (_extract_string(value_node) or "").split("\n")[0][:200]
            elif key in {"input_schema", "parameters"} and not params:
                params = _extract_parameter_names(value_node)

        if not name:
            return None

        return {
            "name": name,
            "description": description,
            "parameters": params,
            "status": "active",
        }

    def _extract_static_entries(value_node: ast.AST | None) -> list[dict]:
        if value_node is None:
            return []

        normalized = _normalize_tool_dict(value_node)
        if normalized:
            return [normalized]

        entries: list[dict] = []

        if isinstance(value_node, (ast.List, ast.Tuple)):
            for element in value_node.elts:
                normalized = _normalize_tool_dict(element)
                if normalized:
                    entries.append(normalized)
            return entries

        if isinstance(value_node, ast.Dict):
            for element in value_node.values:
                normalized = _normalize_tool_dict(element)
                if normalized:
                    entries.append(normalized)
            return entries

        return entries

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Tools start with "tool_" prefix
            if node.name.startswith("tool_"):
                docstring = ast.get_docstring(node) or ""
                
                # Extract parameters
                params = []
                for arg in node.args.args:
                    if arg.arg not in ['request_id', 'trace_id']:
                        params.append(arg.arg)
                
                tools.append({
                    "name": node.name,
                    "description": docstring.split("\n")[0][:200],
                    "parameters": params,
                    "status": "active"
                })
                continue

            if re.fullmatch(r"get_.*_tools", node.name):
                for child in node.body:
                    if not isinstance(child, ast.Return):
                        continue
                    tools.extend(_extract_static_entries(child.value))
                    break

    for node in tree.body:
        value_node = None
        target_names: list[str] = []

        if isinstance(node, ast.Assign):
            value_node = node.value
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value_node = node.value
            target_names = [node.target.id]

        if not value_node:
            continue
        if not any(
            name == "TOOLS"
            or name.endswith("_TOOLS")
            or name.endswith("_SCHEMA")
            or name.endswith("_SCHEMAS")
            for name in target_names
        ):
            continue

        tools.extend(_extract_static_entries(value_node))

    return sorted(tools, key=lambda x: x["name"])


def iter_tool_files() -> Iterable[Path]:
    yield TOOLS_PY
    if TOOL_MODULES_DIR.exists():
        for path in sorted(TOOL_MODULES_DIR.glob("*.py")):
            if path.name == "__init__.py":
                continue
            yield path
    if TOOLS_PACKAGE_DIR.exists():
        for path in sorted(TOOLS_PACKAGE_DIR.glob("*.py")):
            if path.name in {"__init__.py", "base.py"}:
                continue
            yield path
    for path in EXTRA_TOOL_SCHEMA_FILES:
        if path.exists():
            yield path


def extract_version_from_file(file_path):
    """Extract VERSION from config.py or main.py."""
    if not file_path.exists():
        return "unknown"
    
    content = file_path.read_text(encoding="utf-8")
    
    # Look for VERSION = "..."
    match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)
    
    # Look for version in docstring
    match = re.search(r'version[:\s]+([0-9.]+)', content, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return "unknown"


def extract_features_from_config():
    """Extract feature flags and config from config.py."""
    features = {}
    
    if not CONFIG_PY.exists():
        return features
    
    content = CONFIG_PY.read_text(encoding="utf-8")
    
    # Look for feature-related config variables
    patterns = {
        "session_memory": r'REDIS_SESSION_TTL\s*=\s*(\d+)',
        "cross_session_learning": r'ENABLE_CROSS_SESSION.*=\s*(True|False)',
        "proactive_hints": r'ENABLE_PROACTIVE.*=\s*(True|False)',
    }
    
    for feature, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            value = match.group(1)
            if value.isdigit():
                features[feature] = {"enabled": True, "value": int(value)}
            else:
                features[feature] = {"enabled": value == "True"}
    
    return features


def _extract_endpoints_from_file(file_path: Path) -> List[dict]:
    """Extract app/router endpoints from a Python module."""
    endpoints = []

    if not file_path.exists():
        return endpoints

    content = file_path.read_text(encoding="utf-8")

    pattern = r'@(app|router)\.(get|post|put|delete|patch|options|head)\(["\']([^"\']+)["\']\)'
    matches = re.findall(pattern, content)

    for _, method, path in matches:
        endpoints.append({
            "method": method.upper(),
            "path": path
        })

    return endpoints


def extract_endpoints() -> List[dict]:
    """Extract API endpoints from main.py and router modules."""
    endpoints: List[dict] = []
    for file_path in [MAIN_PY, *sorted(ROUTERS_DIR.glob("*.py"))]:
        endpoints.extend(_extract_endpoints_from_file(file_path))

    deduped = {(ep["method"], ep["path"]): ep for ep in endpoints}
    return sorted(deduped.values(), key=lambda x: (x["path"], x["method"]))


def generate_capabilities():
    """Generate complete capabilities JSON."""
    git_info = get_git_info()
    version = extract_version_from_file(CONFIG_PY)
    if version == "unknown":
        version = extract_version_from_file(MAIN_PY)

    all_tools: List[dict] = []
    for tool_file in iter_tool_files():
        module_tools = extract_tools_from_file(tool_file)
        module_name = tool_file.stem
        for tool in module_tools:
            tool["module"] = module_name
        all_tools.extend(module_tools)

    # Deduplicate by name (keep first occurrence)
    seen_names = set()
    unique_tools = []
    for tool in all_tools:
        if tool["name"] not in seen_names:
            seen_names.add(tool["name"])
            unique_tools.append(tool)

    capabilities = {
        "version": version,
        "build_timestamp": datetime.utcnow().isoformat() + "Z",
        "git": git_info,
        "tools": sorted(unique_tools, key=lambda x: x["name"]),
        "features": extract_features_from_config(),
        "endpoints": extract_endpoints(),
        "meta": {
            "generator": "scripts/generate_capabilities.py",
            "purpose": "Self-documentation for Jarvis agent awareness"
        }
    }

    return capabilities


def update_features_md(capabilities):
    """Update FEATURES.md with latest capabilities."""
    content = f"""# Jarvis Features & Capabilities

**Auto-generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  
**Version:** {capabilities['version']}  
**Commit:** {capabilities['git']['commit']}

---

## 🛠️ Available Tools ({len(capabilities['tools'])})

"""
    
    for tool in capabilities['tools']:
        content += f"### `{tool['name']}`\n"
        content += f"{tool['description']}\n"
        if tool['parameters']:
            content += f"**Parameters:** {', '.join(tool['parameters'])}\n"
        content += f"\n"
    
    content += f"\n---\n\n## ⚙️ Active Features\n\n"
    
    for feature, config in capabilities['features'].items():
        status = "✅" if config.get('enabled', True) else "❌"
        content += f"- {status} **{feature}**"
        if 'value' in config:
            content += f" (value: {config['value']})"
        content += "\n"
    
    content += f"\n---\n\n## 🌐 API Endpoints ({len(capabilities['endpoints'])})\n\n"
    
    for ep in capabilities['endpoints'][:20]:  # Limit to first 20
        content += f"- `{ep['method']} {ep['path']}`\n"
    
    if len(capabilities['endpoints']) > 20:
        content += f"\n... and {len(capabilities['endpoints']) - 20} more\n"
    
    return content


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate CAPABILITIES.json and related docs."
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Also print the generated capabilities JSON to stdout.",
    )
    return parser.parse_args()


def main():
    """Main execution."""
    args = parse_args()
    print("🔍 Generating capabilities...")
    
    # Generate capabilities
    capabilities = generate_capabilities()
    
    # Write JSON
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(capabilities, indent=2))
    print(f"✅ Generated: {OUTPUT_JSON}")
    print(f"   - Tools: {len(capabilities['tools'])}")
    print(f"   - Features: {len(capabilities['features'])}")
    print(f"   - Endpoints: {len(capabilities['endpoints'])}")
    
    # Update FEATURES.md
    features_content = update_features_md(capabilities)
    FEATURES_MD.write_text(features_content)
    print(f"✅ Updated: {FEATURES_MD}")

    catalog_script = REPO_ROOT / "scripts" / "generate_capability_catalog.py"
    subprocess.check_call([sys.executable, str(catalog_script)], cwd=REPO_ROOT)

    if args.print_json:
        print(json.dumps(capabilities, indent=2))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
