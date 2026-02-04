#!/usr/bin/env python3
"""
Generate CAPABILITIES.json and update FEATURES.md
Auto-run after each deployment to keep Jarvis self-aware.
"""
import json
import sys
import ast
import re
from pathlib import Path
from datetime import datetime
import subprocess

# Paths
REPO_ROOT = Path(__file__).parent.parent.parent
INGESTION_ROOT = REPO_ROOT / "ingestion"
TOOLS_PY = INGESTION_ROOT / "app" / "tools.py"
CONFIG_PY = INGESTION_ROOT / "app" / "config.py"
MAIN_PY = INGESTION_ROOT / "app" / "main.py"
OUTPUT_JSON = REPO_ROOT / "docs" / "CAPABILITIES.json"
FEATURES_MD = REPO_ROOT / "docs" / "FEATURES.md"


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


def extract_tools_from_file(file_path):
    """Parse tools.py and extract all tool functions."""
    tools = []
    
    if not file_path.exists():
        return tools
    
    content = file_path.read_text()
    tree = ast.parse(content)
    
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
    
    return sorted(tools, key=lambda x: x["name"])


def extract_version_from_file(file_path):
    """Extract VERSION from config.py or main.py."""
    if not file_path.exists():
        return "unknown"
    
    content = file_path.read_text()
    
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
    
    content = CONFIG_PY.read_text()
    
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


def extract_endpoints_from_main():
    """Extract API endpoints from main.py."""
    endpoints = []
    
    if not MAIN_PY.exists():
        return endpoints
    
    content = MAIN_PY.read_text()
    
    # Find @app.post, @app.get, etc.
    pattern = r'@app\.(get|post|put|delete)\(["\']([^"\']+)["\']\)'
    matches = re.findall(pattern, content)
    
    for method, path in matches:
        endpoints.append({
            "method": method.upper(),
            "path": path
        })
    
    return sorted(endpoints, key=lambda x: x["path"])


def generate_capabilities():
    """Generate complete capabilities JSON."""
    git_info = get_git_info()
    version = extract_version_from_file(CONFIG_PY)
    if version == "unknown":
        version = extract_version_from_file(MAIN_PY)
    
    capabilities = {
        "version": version,
        "build_timestamp": datetime.utcnow().isoformat() + "Z",
        "git": git_info,
        "tools": extract_tools_from_file(TOOLS_PY),
        "features": extract_features_from_config(),
        "endpoints": extract_endpoints_from_main(),
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


def main():
    """Main execution."""
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
    
    # Output to stdout for build script
    print(json.dumps(capabilities, indent=2))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
