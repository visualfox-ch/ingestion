#!/usr/bin/env python3
"""
Validate tool registration consistency.
Run before deploy to ensure all tools are properly registered.
"""
import sys
import ast
import re
from pathlib import Path
from typing import List, Tuple

# Paths
REPO_ROOT = Path(__file__).parent.parent.parent
INGESTION_ROOT = REPO_ROOT / "ingestion"
TOOLS_PY = INGESTION_ROOT / "app" / "tools.py"
PROMPT_ASSEMBLER = INGESTION_ROOT / "app" / "prompt_assembler.py"
CONNECTOR_DIR = INGESTION_ROOT / "app" / "connectors"

def extract_registry_tools(file_path: Path) -> set:
    """Extract tool names from TOOL_REGISTRY dict."""
    if not file_path.exists():
        return set()

    content = file_path.read_text()
    tools = set()

    # Find TOOL_REGISTRY definition line (not just mention in docstring)
    # Look for: TOOL_REGISTRY: or TOOL_REGISTRY =
    match = re.search(r'^TOOL_REGISTRY\s*[=:]', content, re.MULTILINE)
    if not match:
        return tools

    registry_start = match.start()

    # Get the TOOL_REGISTRY block (from start to next top-level assignment)
    # Look for lines like: "tool_name": tool_function,
    in_registry = True
    for line in content[registry_start:].splitlines()[1:]:  # Skip the header line

        # End when we hit another top-level definition (line starts with letter/underscore)
        if re.match(r'^[A-Za-z_]', line) and ":" not in line[:20]:
            break

        # Match: "tool_name": tool_something, or "tool_name": tool_something
        match = re.match(r'\s*"([a-z_]+)":\s*tool_', line)
        if match:
            tools.add(match.group(1))

    return tools


def extract_definition_tools(file_path: Path) -> set:
    """Extract tool names from TOOL_DEFINITIONS list."""
    if not file_path.exists():
        return set()

    content = file_path.read_text()
    tools = set()

    # Pattern: "name": "tool_name"
    pattern = r'"name":\s*"([^"]+)"'
    tools = set(re.findall(pattern, content))

    return tools


def extract_assembler_tools(file_path: Path) -> set:
    """Extract tool names referenced in prompt_assembler tool categories."""
    if not file_path.exists():
        return set()

    content = file_path.read_text()
    tools = set()

    # Find all "tools": [...] lists
    # Also find variable assignments like asana_tools = [...]
    patterns = [
        r'"tools":\s*\[([^\]]+)\]',
        r'asana_tools\s*=\s*\[([^\]]+)\]',
        r'reclaim_tools\s*=\s*\[([^\]]+)\]',
        r'project_tools\s*=\s*\[([^\]]+)\]',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            tool_names = re.findall(r'"([^"]+)"', match)
            tools.update(tool_names)

    return tools


def validate_tools() -> Tuple[bool, List[str]]:
    """Validate tool registration consistency."""
    errors = []
    warnings = []

    # Collect all registered tools
    main_registry = extract_registry_tools(TOOLS_PY)
    main_definitions = extract_definition_tools(TOOLS_PY)

    # Collect connector tools
    connector_registry = set()
    connector_definitions = set()

    for connector_file in CONNECTOR_DIR.glob("*.py"):
        if connector_file.name.startswith("_"):
            continue
        registry = extract_registry_tools(connector_file)
        definitions = extract_definition_tools(connector_file)
        connector_registry.update(registry)
        connector_definitions.update(definitions)

    all_registry = main_registry | connector_registry
    all_definitions = main_definitions | connector_definitions

    # Collect assembler references
    assembler_tools = extract_assembler_tools(PROMPT_ASSEMBLER)

    print(f"📊 Tool Summary:")
    print(f"   TOOL_REGISTRY (main):     {len(main_registry)} tools")
    print(f"   TOOL_REGISTRY (connectors): {len(connector_registry)} tools")
    print(f"   TOOL_DEFINITIONS (main):  {len(main_definitions)} tools")
    print(f"   TOOL_DEFINITIONS (connectors): {len(connector_definitions)} tools")
    print(f"   prompt_assembler refs:    {len(assembler_tools)} tools")
    print()

    # Check 1: Tools in assembler must exist in registry
    missing_in_registry = assembler_tools - all_registry
    if missing_in_registry:
        errors.append(f"Tools in prompt_assembler but NOT in any TOOL_REGISTRY: {missing_in_registry}")

    # Check 2: Tools in assembler must have definitions
    missing_definitions = assembler_tools - all_definitions
    if missing_definitions:
        errors.append(f"Tools in prompt_assembler but NOT in any TOOL_DEFINITIONS: {missing_definitions}")

    # Check 3: Registry should have definitions
    registry_without_def = all_registry - all_definitions
    if registry_without_def:
        warnings.append(f"Tools in REGISTRY but no DEFINITION (LLM can't use): {registry_without_def}")

    # Check 4: Definitions should be in registry
    def_without_registry = all_definitions - all_registry
    if def_without_registry:
        errors.append(f"Tools with DEFINITION but not in REGISTRY (will fail execution): {def_without_registry}")

    # Report
    if errors:
        print("❌ ERRORS (must fix before deploy):")
        for e in errors:
            print(f"   {e}")
        print()

    if warnings:
        print("⚠️  WARNINGS:")
        for w in warnings:
            print(f"   {w}")
        print()

    if not errors and not warnings:
        print("✅ All tools properly registered!")

    return len(errors) == 0, errors


def main():
    """Main execution."""
    print("🔍 Validating tool registration...\n")

    success, errors = validate_tools()

    if success:
        print("\n✅ Tool validation passed!")
        return 0
    else:
        print(f"\n❌ Tool validation failed with {len(errors)} error(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
