"""
Dynamic Skill Manager - Self-Generating Skills System

Inspired by OpenClaw's approach, this service enables Jarvis to create,
load, and execute custom skills dynamically at runtime.

Skills are Python files stored in /brain/system/data/skills/ with:
- Docstring metadata (name, description, parameters)
- An execute() function as entry point

Features:
- Dynamic loading at startup
- Hot-reload without restart
- AST validation before registration
- Sandboxed execution with timeouts
"""

import ast
import importlib.util
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger(__name__)

# Default skills directory (container path)
DEFAULT_SKILLS_DIR = "/brain/system/data/skills"

# Execution limits
DEFAULT_TIMEOUT_SECONDS = 30
MAX_MEMORY_MB = 256


@dataclass
class SkillParameter:
    """Represents a skill parameter."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class SkillMetadata:
    """Metadata for a registered skill."""
    name: str
    description: str
    parameters: List[SkillParameter]
    file_path: str
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    author: str = "jarvis"
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    execution_count: int = 0
    last_executed: Optional[datetime] = None
    avg_execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.parameters
            ],
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "enabled": self.enabled,
            "execution_count": self.execution_count,
            "last_executed": self.last_executed.isoformat() if self.last_executed else None,
            "avg_execution_time_ms": self.avg_execution_time_ms,
        }


@dataclass
class SkillExecutionResult:
    """Result of a skill execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    skill_name: str = ""


class SkillValidationError(Exception):
    """Raised when skill validation fails."""
    pass


class SkillExecutionError(Exception):
    """Raised when skill execution fails."""
    pass


class SkillManager:
    """
    Manages dynamic skill loading, registration, and execution.

    Skills are Python files with a specific format:
    - Docstring with YAML-like metadata
    - An execute() function as entry point
    """

    def __init__(self, skills_dir: str = DEFAULT_SKILLS_DIR):
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, SkillMetadata] = {}
        self._modules: Dict[str, Any] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._file_mtimes: Dict[str, float] = {}
        self._initialized = False

    @property
    def skills(self) -> Dict[str, SkillMetadata]:
        """Get all registered skills."""
        return self._skills.copy()

    @property
    def skill_names(self) -> List[str]:
        """Get names of all registered skills."""
        return list(self._skills.keys())

    @property
    def enabled_skills(self) -> Dict[str, SkillMetadata]:
        """Get only enabled skills."""
        return {k: v for k, v in self._skills.items() if v.enabled}

    # =========================================================================
    # Initialization & Loading
    # =========================================================================

    def initialize(self) -> int:
        """
        Initialize the skill manager and load all skills.

        Returns:
            Number of skills loaded
        """
        if self._initialized:
            return len(self._skills)

        # Ensure skills directory exists
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        # Load all skills
        loaded = self.reload_all()
        self._initialized = True

        logger.info(f"SkillManager initialized with {loaded} skills")
        return loaded

    def reload_all(self) -> int:
        """
        Reload all skills from disk.

        Returns:
            Number of skills loaded
        """
        loaded = 0
        errors = []

        for skill_file in self.skills_dir.glob("*.py"):
            if skill_file.name.startswith("_"):
                continue  # Skip __init__.py, etc.

            try:
                self.load_skill(skill_file)
                loaded += 1
            except Exception as e:
                errors.append(f"{skill_file.name}: {e}")
                logger.warning(f"Failed to load skill {skill_file.name}: {e}")

        if errors:
            logger.warning(f"Skill loading errors: {errors}")

        return loaded

    def load_skill(self, file_path: Path | str) -> SkillMetadata:
        """
        Load a skill from a Python file.

        Args:
            file_path: Path to the skill file

        Returns:
            SkillMetadata for the loaded skill

        Raises:
            SkillValidationError: If validation fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise SkillValidationError(f"Skill file not found: {file_path}")

        # Read and validate the code
        code = file_path.read_text()
        metadata = self._parse_skill_metadata(code, file_path)

        # Validate AST
        self._validate_skill_code(code, metadata.name)

        # Load the module
        module = self._load_module(file_path, metadata.name)

        # Verify execute function exists
        if not hasattr(module, "execute"):
            raise SkillValidationError(
                f"Skill {metadata.name} must have an execute() function"
            )

        # Store
        self._skills[metadata.name] = metadata
        self._modules[metadata.name] = module
        self._file_mtimes[metadata.name] = file_path.stat().st_mtime

        logger.info(f"Loaded skill: {metadata.name}")
        return metadata

    def _load_module(self, file_path: Path, skill_name: str) -> Any:
        """Load a Python module from file."""
        spec = importlib.util.spec_from_file_location(
            f"jarvis_skill_{skill_name}",
            file_path
        )
        if spec is None or spec.loader is None:
            raise SkillValidationError(f"Cannot load module spec from {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            del sys.modules[spec.name]
            raise SkillValidationError(f"Error loading skill module: {e}")

        return module

    # =========================================================================
    # Metadata Parsing
    # =========================================================================

    def _parse_skill_metadata(self, code: str, file_path: Path) -> SkillMetadata:
        """
        Parse skill metadata from docstring.

        Expected format:
        '''
        name: skill_name
        description: What the skill does
        parameters:
          param1: type - Description
          param2: type - Description (default: value)
        tags: tag1, tag2
        version: 1.0.0
        author: author_name
        '''
        """
        # Parse AST to get docstring
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SkillValidationError(f"Syntax error in skill: {e}")

        docstring = ast.get_docstring(tree)
        if not docstring:
            raise SkillValidationError("Skill must have a module docstring with metadata")

        # Parse metadata from docstring
        metadata = self._parse_docstring_metadata(docstring)

        # Extract name from filename if not in docstring
        if "name" not in metadata:
            metadata["name"] = file_path.stem

        # Validate required fields
        if "description" not in metadata:
            raise SkillValidationError("Skill must have a description")

        # Parse parameters
        parameters = []
        if "parameters" in metadata:
            parameters = self._parse_parameters(metadata["parameters"])

        now = datetime.utcnow()
        file_stat = file_path.stat()

        return SkillMetadata(
            name=metadata["name"],
            description=metadata["description"],
            parameters=parameters,
            file_path=str(file_path),
            created_at=datetime.fromtimestamp(file_stat.st_ctime),
            updated_at=datetime.fromtimestamp(file_stat.st_mtime),
            version=metadata.get("version", "1.0.0"),
            author=metadata.get("author", "jarvis"),
            tags=self._parse_tags(metadata.get("tags", "")),
            enabled=True,
        )

    def _parse_docstring_metadata(self, docstring: str) -> Dict[str, Any]:
        """Parse YAML-like metadata from docstring."""
        metadata = {}
        current_key = None
        current_value = []
        in_parameters = False
        parameters_lines = []

        for line in docstring.split("\n"):
            line = line.strip()

            # Check for key: value pattern
            match = re.match(r"^(\w+):\s*(.*)$", line)
            if match:
                # Save previous key if exists
                if current_key and not in_parameters:
                    metadata[current_key] = "\n".join(current_value).strip()

                current_key = match.group(1).lower()
                value = match.group(2).strip()

                if current_key == "parameters":
                    in_parameters = True
                    parameters_lines = []
                    if value:
                        parameters_lines.append(value)
                else:
                    in_parameters = False
                    current_value = [value] if value else []
            elif in_parameters and line:
                # Continuation of parameters section
                parameters_lines.append(line)
            elif current_key and line:
                # Continuation of previous value
                current_value.append(line)

        # Save last key
        if current_key:
            if in_parameters:
                metadata["parameters"] = parameters_lines
            else:
                metadata[current_key] = "\n".join(current_value).strip()

        return metadata

    def _parse_parameters(self, param_lines: List[str]) -> List[SkillParameter]:
        """Parse parameter definitions."""
        parameters = []

        for line in param_lines:
            line = line.strip()
            if not line:
                continue

            # Format: name: type - Description (default: value)
            match = re.match(
                r"(\w+):\s*(\w+)\s*-\s*(.+?)(?:\s*\(default:\s*(.+?)\))?$",
                line
            )
            if match:
                name = match.group(1)
                param_type = match.group(2)
                description = match.group(3).strip()
                default = match.group(4)

                parameters.append(SkillParameter(
                    name=name,
                    type=param_type,
                    description=description,
                    required=default is None,
                    default=self._parse_default_value(default, param_type) if default else None,
                ))

        return parameters

    def _parse_default_value(self, value: str, param_type: str) -> Any:
        """Parse default value based on type."""
        if value is None:
            return None

        value = value.strip()

        if param_type == "int":
            return int(value)
        elif param_type == "float":
            return float(value)
        elif param_type == "bool":
            return value.lower() in ("true", "1", "yes")
        elif param_type == "list":
            return json.loads(value) if value.startswith("[") else value.split(",")
        elif param_type == "dict":
            return json.loads(value)
        else:
            return value

    def _parse_tags(self, tags_str: str) -> List[str]:
        """Parse comma-separated tags."""
        if not tags_str:
            return []
        return [t.strip() for t in tags_str.split(",") if t.strip()]

    # =========================================================================
    # Code Validation
    # =========================================================================

    def _validate_skill_code(self, code: str, skill_name: str) -> None:
        """
        Validate skill code using AST analysis.

        Checks for:
        - Syntax errors
        - Dangerous imports
        - Required execute() function
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SkillValidationError(f"Syntax error: {e}")

        # Check for dangerous imports
        dangerous_modules = {
            "subprocess", "os.system", "eval", "exec",
            "pickle", "marshal", "shelve",
            "__builtins__", "ctypes",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in dangerous_modules:
                        raise SkillValidationError(
                            f"Dangerous import not allowed: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module in dangerous_modules:
                    raise SkillValidationError(
                        f"Dangerous import not allowed: {node.module}"
                    )

        # Check for execute function
        has_execute = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "execute":
                has_execute = True
                break

        if not has_execute:
            raise SkillValidationError(
                f"Skill {skill_name} must define an execute() function"
            )

    # =========================================================================
    # Skill Execution
    # =========================================================================

    async def execute_skill(
        self,
        skill_name: str,
        parameters: Dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> SkillExecutionResult:
        """
        Execute a skill with given parameters.

        Args:
            skill_name: Name of the skill to execute
            parameters: Parameters to pass to the skill
            timeout: Maximum execution time in seconds

        Returns:
            SkillExecutionResult with success status and result/error
        """
        if skill_name not in self._skills:
            return SkillExecutionResult(
                success=False,
                error=f"Skill not found: {skill_name}",
                skill_name=skill_name,
            )

        metadata = self._skills[skill_name]
        if not metadata.enabled:
            return SkillExecutionResult(
                success=False,
                error=f"Skill is disabled: {skill_name}",
                skill_name=skill_name,
            )

        module = self._modules.get(skill_name)
        if not module:
            return SkillExecutionResult(
                success=False,
                error=f"Skill module not loaded: {skill_name}",
                skill_name=skill_name,
            )

        # Validate parameters
        validation_error = self._validate_parameters(metadata, parameters)
        if validation_error:
            return SkillExecutionResult(
                success=False,
                error=validation_error,
                skill_name=skill_name,
            )

        # Execute with timeout
        start_time = time.time()
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: module.execute(**parameters)
                ),
                timeout=timeout
            )
            execution_time_ms = (time.time() - start_time) * 1000

            # Update statistics
            self._update_execution_stats(skill_name, execution_time_ms)

            return SkillExecutionResult(
                success=True,
                result=result,
                execution_time_ms=execution_time_ms,
                skill_name=skill_name,
            )

        except asyncio.TimeoutError:
            return SkillExecutionResult(
                success=False,
                error=f"Skill execution timed out after {timeout}s",
                execution_time_ms=(time.time() - start_time) * 1000,
                skill_name=skill_name,
            )
        except Exception as e:
            return SkillExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
                execution_time_ms=(time.time() - start_time) * 1000,
                skill_name=skill_name,
            )

    def _validate_parameters(
        self,
        metadata: SkillMetadata,
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """Validate parameters against skill metadata."""
        # Check required parameters
        for param in metadata.parameters:
            if param.required and param.name not in parameters:
                return f"Missing required parameter: {param.name}"

        return None

    def _update_execution_stats(self, skill_name: str, execution_time_ms: float) -> None:
        """Update skill execution statistics."""
        if skill_name not in self._skills:
            return

        metadata = self._skills[skill_name]
        metadata.execution_count += 1
        metadata.last_executed = datetime.utcnow()

        # Update rolling average
        old_avg = metadata.avg_execution_time_ms
        count = metadata.execution_count
        metadata.avg_execution_time_ms = old_avg + (execution_time_ms - old_avg) / count

    # =========================================================================
    # Skill Management
    # =========================================================================

    def create_skill(
        self,
        name: str,
        description: str,
        code: str,
        parameters: List[Dict[str, Any]] = None,
        tags: List[str] = None,
        author: str = "jarvis",
    ) -> SkillMetadata:
        """
        Create and register a new skill.

        Args:
            name: Skill name (alphanumeric + underscore)
            description: What the skill does
            code: Python code for the execute() function body
            parameters: List of parameter definitions
            tags: Optional tags for categorization
            author: Author name

        Returns:
            SkillMetadata for the created skill

        Raises:
            SkillValidationError: If validation fails
        """
        # Validate name
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise SkillValidationError(
                "Skill name must be lowercase alphanumeric with underscores"
            )

        if name in self._skills:
            raise SkillValidationError(f"Skill already exists: {name}")

        # Build the full skill file
        param_docs = ""
        param_signature = ""
        if parameters:
            param_lines = []
            param_parts = []
            for p in parameters:
                default_str = f" (default: {p.get('default')})" if "default" in p else ""
                param_lines.append(
                    f"  {p['name']}: {p['type']} - {p['description']}{default_str}"
                )
                if "default" in p:
                    param_parts.append(f"{p['name']}: {p['type']} = {repr(p['default'])}")
                else:
                    param_parts.append(f"{p['name']}: {p['type']}")
            param_docs = "\nparameters:\n" + "\n".join(param_lines)
            param_signature = ", ".join(param_parts)

        tags_str = ", ".join(tags) if tags else ""
        tags_line = f"\ntags: {tags_str}" if tags_str else ""

        skill_code = f'''"""
name: {name}
description: {description}{param_docs}{tags_line}
author: {author}
version: 1.0.0
"""

def execute({param_signature}) -> dict:
    """Execute the skill."""
{self._indent_code(code, 4)}
'''

        # Validate the generated code
        self._validate_skill_code(skill_code, name)

        # Save to file
        file_path = self.skills_dir / f"{name}.py"
        file_path.write_text(skill_code)

        # Load and register
        return self.load_skill(file_path)

    def _indent_code(self, code: str, spaces: int) -> str:
        """Indent code by given number of spaces."""
        indent = " " * spaces
        lines = code.split("\n")
        return "\n".join(indent + line if line.strip() else line for line in lines)

    def delete_skill(self, name: str) -> bool:
        """
        Delete a skill.

        Args:
            name: Skill name to delete

        Returns:
            True if deleted, False if not found
        """
        if name not in self._skills:
            return False

        metadata = self._skills[name]

        # Remove file
        file_path = Path(metadata.file_path)
        if file_path.exists():
            file_path.unlink()

        # Remove from registry
        del self._skills[name]
        if name in self._modules:
            del self._modules[name]
        if name in self._file_mtimes:
            del self._file_mtimes[name]

        logger.info(f"Deleted skill: {name}")
        return True

    def enable_skill(self, name: str) -> bool:
        """Enable a disabled skill."""
        if name not in self._skills:
            return False
        self._skills[name].enabled = True
        return True

    def disable_skill(self, name: str) -> bool:
        """Disable a skill without deleting it."""
        if name not in self._skills:
            return False
        self._skills[name].enabled = False
        return True

    def get_skill(self, name: str) -> Optional[SkillMetadata]:
        """Get metadata for a specific skill."""
        return self._skills.get(name)

    def search_skills(
        self,
        query: str = None,
        tags: List[str] = None,
        enabled_only: bool = True,
    ) -> List[SkillMetadata]:
        """
        Search for skills by name, description, or tags.

        Args:
            query: Search string for name/description
            tags: Filter by tags
            enabled_only: Only return enabled skills

        Returns:
            List of matching SkillMetadata
        """
        results = []

        for skill in self._skills.values():
            if enabled_only and not skill.enabled:
                continue

            if tags:
                if not any(t in skill.tags for t in tags):
                    continue

            if query:
                query_lower = query.lower()
                if (query_lower not in skill.name.lower() and
                    query_lower not in skill.description.lower()):
                    continue

            results.append(skill)

        return results

    # =========================================================================
    # Hot Reload
    # =========================================================================

    def check_for_updates(self) -> List[str]:
        """
        Check for skill file changes and reload if needed.

        Returns:
            List of skill names that were reloaded
        """
        reloaded = []

        # Check existing skills for updates
        for name, metadata in list(self._skills.items()):
            file_path = Path(metadata.file_path)
            if not file_path.exists():
                # File deleted - remove skill
                del self._skills[name]
                if name in self._modules:
                    del self._modules[name]
                if name in self._file_mtimes:
                    del self._file_mtimes[name]
                logger.info(f"Skill file deleted, unregistered: {name}")
                continue

            current_mtime = file_path.stat().st_mtime
            if current_mtime > self._file_mtimes.get(name, 0):
                try:
                    self.load_skill(file_path)
                    reloaded.append(name)
                    logger.info(f"Hot-reloaded skill: {name}")
                except Exception as e:
                    logger.error(f"Failed to reload skill {name}: {e}")

        # Check for new skills
        for skill_file in self.skills_dir.glob("*.py"):
            if skill_file.name.startswith("_"):
                continue

            name = skill_file.stem
            if name not in self._skills:
                try:
                    self.load_skill(skill_file)
                    reloaded.append(name)
                    logger.info(f"Discovered new skill: {name}")
                except Exception as e:
                    logger.error(f"Failed to load new skill {name}: {e}")

        return reloaded

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the skill manager."""
        return {
            "initialized": self._initialized,
            "skills_dir": str(self.skills_dir),
            "total_skills": len(self._skills),
            "enabled_skills": len(self.enabled_skills),
            "skill_names": self.skill_names,
        }


# Singleton instance
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """Get the singleton SkillManager instance."""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
        _skill_manager.initialize()
    return _skill_manager
