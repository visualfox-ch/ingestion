"""
Dynamic Tool Loader - Phase A: Hot-Swap Architecture

Allows loading/reloading tools without container restart.
Tools in tools_dynamic/ can be modified and reloaded via API.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Callable, Optional, List
from dataclasses import dataclass, field

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_loader")

# Dynamic tools directory (mounted volume - persists across restarts)
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
TOOLS_DYNAMIC_DIR = BRAIN_ROOT / "system" / "jarvis-tools" / "dynamic"
TOOLS_SANDBOX_DIR = BRAIN_ROOT / "system" / "jarvis-sandbox" / "pending"

# Security: Forbidden imports/patterns in dynamic tools
FORBIDDEN_PATTERNS = [
    "os.system",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "eval(",
    "exec(",
    "__import__",
    "importlib.import_module",
    "open('/etc",
    "open('/root",
    "shutil.rmtree('/'",
]


@dataclass
class DynamicTool:
    """Metadata for a dynamically loaded tool."""
    name: str
    handler: Callable
    schema: Dict[str, Any]
    category: str
    version: str = "1.0"
    source_file: Optional[Path] = None
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    reload_count: int = 0
    last_error: Optional[str] = None


class DynamicToolLoader:
    """
    Load and reload tools dynamically without restart.

    Usage:
        # Load all dynamic tools at startup
        DynamicToolLoader.load_all()

        # Hot-reload a specific tool
        DynamicToolLoader.reload("my_custom_tool")

        # Get all dynamic tools for TOOL_REGISTRY
        tools = DynamicToolLoader.get_all_tools()
    """

    _tools: Dict[str, DynamicTool] = {}
    _initialized: bool = False

    @classmethod
    def initialize(cls) -> Dict[str, Any]:
        """Initialize the dynamic tool system."""
        results = {"created_dirs": [], "errors": []}

        # Create directories if they don't exist
        for dir_path in [TOOLS_DYNAMIC_DIR, TOOLS_SANDBOX_DIR]:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                results["created_dirs"].append(str(dir_path))
            except Exception as e:
                results["errors"].append(f"Failed to create {dir_path}: {e}")

        # Create __init__.py if missing
        init_file = TOOLS_DYNAMIC_DIR / "__init__.py"
        if not init_file.exists():
            try:
                init_file.write_text('"""Dynamic tools loaded at runtime."""\n')
            except Exception as e:
                results["errors"].append(f"Failed to create __init__.py: {e}")

        cls._initialized = True
        log_with_context(logger, "info", "Dynamic tool loader initialized",
                        tools_dir=str(TOOLS_DYNAMIC_DIR),
                        sandbox_dir=str(TOOLS_SANDBOX_DIR))

        return results

    @classmethod
    def _validate_code(cls, code: str, filename: str) -> List[str]:
        """
        Security validation for dynamic tool code.
        Returns list of security violations found.

        Note: Strips string literals before checking to avoid false positives
        from security pattern definitions inside the code itself.
        """
        import re
        violations = []

        # Remove string literals to avoid false positives
        # (e.g., pattern definitions in security validation code)
        code_no_strings = re.sub(r'"""[\s\S]*?"""', '""', code)  # triple double
        code_no_strings = re.sub(r"'''[\s\S]*?'''", "''", code_no_strings)  # triple single
        code_no_strings = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', code_no_strings)  # double
        code_no_strings = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", code_no_strings)  # single

        for pattern in FORBIDDEN_PATTERNS:
            if pattern in code_no_strings:
                violations.append(f"Forbidden pattern '{pattern}' found in {filename}")

        return violations

    @classmethod
    def _load_module_from_file(cls, file_path: Path) -> Optional[Any]:
        """Load a Python module from a file path."""
        module_name = f"jarvis_dynamic_{file_path.stem}"

        try:
            # Read and validate code
            code = file_path.read_text()
            violations = cls._validate_code(code, file_path.name)

            if violations:
                log_with_context(logger, "error", "Security violations in dynamic tool",
                               file=str(file_path), violations=violations)
                return None

            # Remove old module if exists (for reload)
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Load module
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            log_with_context(logger, "error", "Failed to load dynamic tool",
                           file=str(file_path), error=str(e))
            return None

    @classmethod
    def load_tool(cls, tool_name: str) -> bool:
        """
        Load or reload a single dynamic tool.

        The tool file must define:
        - TOOL_NAME: str
        - TOOL_SCHEMA: dict
        - TOOL_CATEGORY: str
        - TOOL_VERSION: str (optional, default "1.0")
        - tool_handler(params) -> dict: The actual tool function
        """
        file_path = TOOLS_DYNAMIC_DIR / f"{tool_name}.py"

        if not file_path.exists():
            log_with_context(logger, "warning", "Dynamic tool file not found",
                           tool=tool_name, path=str(file_path))
            return False

        module = cls._load_module_from_file(file_path)
        if module is None:
            return False

        # Extract tool definition
        try:
            name = getattr(module, "TOOL_NAME", tool_name)
            handler = getattr(module, "tool_handler", None)
            schema = getattr(module, "TOOL_SCHEMA", {})
            category = getattr(module, "TOOL_CATEGORY", "dynamic")
            version = getattr(module, "TOOL_VERSION", "1.0")

            if handler is None:
                log_with_context(logger, "error", "No tool_handler in dynamic tool",
                               tool=tool_name)
                return False

            # Check if reloading
            reload_count = 0
            if name in cls._tools:
                reload_count = cls._tools[name].reload_count + 1

            # Register tool
            cls._tools[name] = DynamicTool(
                name=name,
                handler=handler,
                schema=schema,
                category=category,
                version=version,
                source_file=file_path,
                loaded_at=datetime.utcnow(),
                reload_count=reload_count
            )

            log_with_context(logger, "info", "Dynamic tool loaded",
                           tool=name, version=version, category=category,
                           reload_count=reload_count)
            return True

        except Exception as e:
            log_with_context(logger, "error", "Failed to register dynamic tool",
                           tool=tool_name, error=str(e))
            if tool_name in cls._tools:
                cls._tools[tool_name].last_error = str(e)
            return False

    @classmethod
    def load_all(cls) -> Dict[str, bool]:
        """Load all dynamic tools from the tools directory."""
        if not cls._initialized:
            cls.initialize()

        results = {}

        if not TOOLS_DYNAMIC_DIR.exists():
            return results

        for py_file in TOOLS_DYNAMIC_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            tool_name = py_file.stem
            results[tool_name] = cls.load_tool(tool_name)

        log_with_context(logger, "info", "Dynamic tools loaded",
                        total=len(results),
                        success=sum(results.values()),
                        failed=len(results) - sum(results.values()))

        return results

    @classmethod
    def reload(cls, tool_name: str = None, update_registry: bool = True) -> Dict[str, Any]:
        """
        Reload dynamic tool(s) and optionally update TOOL_REGISTRY.

        Args:
            tool_name: Specific tool to reload, or None for all
            update_registry: If True, also update tools.TOOL_REGISTRY (default: True)

        Returns:
            Dict with reload results
        """
        if tool_name:
            success = cls.load_tool(tool_name)
            result = {
                "tool": tool_name,
                "success": success,
                "timestamp": datetime.utcnow().isoformat()
            }
            # Hot-update TOOL_REGISTRY if successful
            if success and update_registry:
                try:
                    from . import tools
                    tool = cls._tools.get(tool_name)
                    if tool:
                        tools.TOOL_REGISTRY[tool_name] = tool.handler
                        # Also add schema to TOOL_DEFINITIONS
                        tools.TOOL_DEFINITIONS.append(tool.schema)
                        result["registry_updated"] = True
                        log_with_context(logger, "info", "TOOL_REGISTRY updated",
                                       tool=tool_name)
                except Exception as e:
                    result["registry_updated"] = False
                    result["registry_error"] = str(e)
                    log_with_context(logger, "warning", "Failed to update TOOL_REGISTRY",
                                   tool=tool_name, error=str(e))
            return result
        else:
            results = cls.load_all()
            reload_result = {
                "reloaded": results,
                "success_count": sum(results.values()),
                "total": len(results),
                "timestamp": datetime.utcnow().isoformat()
            }
            # Hot-update all tools in registry
            if update_registry:
                try:
                    from . import tools
                    handlers = cls.get_all_tools()
                    schemas = cls.get_all_schemas()
                    tools.TOOL_REGISTRY.update(handlers)
                    tools.TOOL_DEFINITIONS.extend(schemas)
                    reload_result["registry_updated"] = True
                except Exception as e:
                    reload_result["registry_updated"] = False
                    reload_result["registry_error"] = str(e)
            return reload_result

    @classmethod
    def unload(cls, tool_name: str) -> bool:
        """Remove a dynamic tool from registry."""
        if tool_name in cls._tools:
            del cls._tools[tool_name]
            log_with_context(logger, "info", "Dynamic tool unloaded", tool=tool_name)
            return True
        return False

    @classmethod
    def get_tool(cls, name: str) -> Optional[DynamicTool]:
        """Get a specific dynamic tool."""
        return cls._tools.get(name)

    @classmethod
    def get_handler(cls, name: str) -> Optional[Callable]:
        """Get just the handler function for a tool."""
        tool = cls._tools.get(name)
        return tool.handler if tool else None

    @classmethod
    def get_all_tools(cls) -> Dict[str, DynamicTool]:
        """Get all loaded dynamic tools."""
        return cls._tools.copy()

    @classmethod
    def get_all_handlers(cls) -> Dict[str, Callable]:
        """Get all handlers (for merging into TOOL_REGISTRY)."""
        return {name: tool.handler for name, tool in cls._tools.items()}

    @classmethod
    def get_all_schemas(cls) -> List[Dict[str, Any]]:
        """Get all tool schemas (for merging into TOOL_DEFINITIONS)."""
        schemas = []
        for name, tool in cls._tools.items():
            if tool.schema:
                schemas.append(tool.schema)
        return schemas

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get status of the dynamic tool system."""
        return {
            "initialized": cls._initialized,
            "tools_dir": str(TOOLS_DYNAMIC_DIR),
            "sandbox_dir": str(TOOLS_SANDBOX_DIR),
            "tools_dir_exists": TOOLS_DYNAMIC_DIR.exists(),
            "loaded_tools": len(cls._tools),
            "tools": {
                name: {
                    "category": tool.category,
                    "version": tool.version,
                    "loaded_at": tool.loaded_at.isoformat(),
                    "reload_count": tool.reload_count,
                    "source_file": str(tool.source_file) if tool.source_file else None,
                    "has_error": tool.last_error is not None
                }
                for name, tool in cls._tools.items()
            }
        }


# Convenience functions for tools.py integration
def get_dynamic_tools() -> Dict[str, Callable]:
    """Get all dynamic tool handlers for TOOL_REGISTRY merge."""
    return DynamicToolLoader.get_all_handlers()


def initialize_dynamic_tools() -> Dict[str, Any]:
    """Initialize and load all dynamic tools."""
    DynamicToolLoader.initialize()
    return DynamicToolLoader.load_all()
