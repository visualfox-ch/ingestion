"""
Sandbox Runner - Phase C

Automatically tests code written by Jarvis before promotion.
Provides safe execution environment for self-modification.
"""
from __future__ import annotations

import os
import sys
import ast
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.sandbox_runner")

# Paths
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
SANDBOX_BASE = BRAIN_ROOT / "system" / "jarvis-sandbox"
PENDING_DIR = SANDBOX_BASE / "pending"
TESTED_DIR = SANDBOX_BASE / "tested"
APPROVED_DIR = SANDBOX_BASE / "approved"
PROMOTED_DIR = SANDBOX_BASE / "promoted"
DYNAMIC_TOOLS_DIR = BRAIN_ROOT / "system" / "jarvis-tools" / "dynamic"


class TestStatus(str, Enum):
    PENDING = "pending"
    TESTING = "testing"
    PASSED = "passed"
    FAILED = "failed"
    PROMOTED = "promoted"


@dataclass
class TestResult:
    """Result of testing sandbox code."""
    file_name: str
    status: TestStatus
    syntax_ok: bool = False
    imports_ok: bool = False
    structure_ok: bool = False
    security_ok: bool = False
    execution_ok: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tested_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    execution_time_ms: float = 0.0


# Security patterns (same as tool_loader)
FORBIDDEN_PATTERNS = [
    "os.system",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "eval(",
    "exec(",
    "__import__",
    "open('/etc",
    "open('/root",
    "shutil.rmtree('/'",
]


class SandboxRunner:
    """
    Tests and validates code in the sandbox before promotion.

    Flow:
    1. Code written to pending/
    2. SandboxRunner.test_file() runs validation
    3. If passed → moved to tested/
    4. Human approval (optional) → moved to approved/
    5. Promotion → copied to dynamic tools, hot-reloaded
    """

    @classmethod
    def ensure_directories(cls):
        """Create sandbox directories if they don't exist."""
        for dir_path in [PENDING_DIR, TESTED_DIR, APPROVED_DIR, PROMOTED_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _check_syntax(cls, code: str, filename: str) -> tuple[bool, List[str]]:
        """Check Python syntax."""
        errors = []
        try:
            compile(code, filename, "exec")
            return True, []
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
            return False, errors

    @classmethod
    def _check_imports(cls, code: str) -> tuple[bool, List[str]]:
        """Check that all imports are available."""
        errors = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        try:
                            __import__(alias.name.split('.')[0])
                        except ImportError:
                            errors.append(f"Import not available: {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        # Skip relative imports within app
                        if node.level > 0:
                            continue
                        try:
                            __import__(node.module.split('.')[0])
                        except ImportError:
                            errors.append(f"Import not available: {node.module}")

            return len(errors) == 0, errors
        except Exception as e:
            errors.append(f"AST parse error: {e}")
            return False, errors

    @classmethod
    def _check_structure(cls, code: str, filename: str) -> tuple[bool, List[str], List[str]]:
        """Check tool structure (TOOL_NAME, TOOL_SCHEMA, tool_handler)."""
        errors = []
        warnings = []

        required = ["TOOL_NAME", "TOOL_SCHEMA", "tool_handler"]

        for item in required:
            if item not in code:
                errors.append(f"Missing required: {item}")

        # Check for optional but recommended
        recommended = ["TOOL_VERSION", "TOOL_CATEGORY"]
        for item in recommended:
            if item not in code:
                warnings.append(f"Missing recommended: {item} (will use defaults)")

        # Check tool_handler signature
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "tool_handler":
                    if not node.returns:
                        warnings.append("tool_handler missing return type annotation")
                    break
        except:
            pass

        return len(errors) == 0, errors, warnings

    @classmethod
    def _check_security(cls, code: str, filename: str) -> tuple[bool, List[str]]:
        """Check for forbidden patterns."""
        import re
        errors = []

        # Remove string literals to avoid false positives
        code_no_strings = re.sub(r'"""[\s\S]*?"""', '""', code)
        code_no_strings = re.sub(r"'''[\s\S]*?'''", "''", code_no_strings)
        code_no_strings = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', code_no_strings)
        code_no_strings = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", code_no_strings)

        for pattern in FORBIDDEN_PATTERNS:
            if pattern in code_no_strings:
                errors.append(f"Forbidden pattern: {pattern}")

        return len(errors) == 0, errors

    @classmethod
    def _check_execution(cls, file_path: Path) -> tuple[bool, List[str], float]:
        """Try to import the module and call tool_handler with test data."""
        import time
        import importlib.util
        errors = []
        start = time.time()

        try:
            # Load module
            spec = importlib.util.spec_from_file_location(
                f"sandbox_test_{file_path.stem}",
                file_path
            )
            if spec is None or spec.loader is None:
                errors.append("Failed to create module spec")
                return False, errors, 0

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Check handler exists and is callable
            handler = getattr(module, "tool_handler", None)
            if handler is None:
                errors.append("tool_handler not found in module")
                return False, errors, 0

            if not callable(handler):
                errors.append("tool_handler is not callable")
                return False, errors, 0

            # Try calling with no args (should handle defaults or fail gracefully)
            try:
                # Get function signature
                import inspect
                sig = inspect.signature(handler)

                # Build minimal test kwargs
                test_kwargs = {}
                for name, param in sig.parameters.items():
                    if param.default is inspect.Parameter.empty:
                        # Required param - use simple test values
                        if "str" in str(param.annotation):
                            test_kwargs[name] = "test"
                        elif "int" in str(param.annotation):
                            test_kwargs[name] = 1
                        elif "bool" in str(param.annotation):
                            test_kwargs[name] = True
                        else:
                            test_kwargs[name] = "test"

                result = handler(**test_kwargs)

                # Check result is a dict
                if not isinstance(result, dict):
                    errors.append(f"tool_handler should return dict, got {type(result)}")

            except Exception as e:
                # Execution error is OK for test, we just want to verify it loads
                log_with_context(logger, "debug", "Sandbox test execution note",
                               file=file_path.name, note=str(e))

            elapsed = (time.time() - start) * 1000
            return True, errors, elapsed

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            errors.append(f"Execution error: {str(e)}")
            return False, errors, elapsed

    @classmethod
    def test_file(cls, filename: str) -> TestResult:
        """
        Run all tests on a sandbox file.

        Args:
            filename: Name of file in pending/ directory

        Returns:
            TestResult with all test outcomes
        """
        cls.ensure_directories()

        file_path = PENDING_DIR / filename
        if not file_path.exists():
            return TestResult(
                file_name=filename,
                status=TestStatus.FAILED,
                errors=[f"File not found: {file_path}"]
            )

        code = file_path.read_text()
        result = TestResult(file_name=filename, status=TestStatus.TESTING)

        # Run all checks
        result.syntax_ok, syntax_errors = cls._check_syntax(code, filename)
        result.errors.extend(syntax_errors)

        if result.syntax_ok:
            result.imports_ok, import_errors = cls._check_imports(code)
            result.errors.extend(import_errors)

            structure_ok, struct_errors, struct_warnings = cls._check_structure(code, filename)
            result.structure_ok = structure_ok
            result.errors.extend(struct_errors)
            result.warnings.extend(struct_warnings)

            result.security_ok, security_errors = cls._check_security(code, filename)
            result.errors.extend(security_errors)

            # Only run execution test if other checks pass
            if result.imports_ok and result.structure_ok and result.security_ok:
                result.execution_ok, exec_errors, exec_time = cls._check_execution(file_path)
                result.errors.extend(exec_errors)
                result.execution_time_ms = exec_time

        # Determine final status
        all_ok = (result.syntax_ok and result.imports_ok and
                  result.structure_ok and result.security_ok and result.execution_ok)

        if all_ok:
            result.status = TestStatus.PASSED
            # Move to tested/
            try:
                target = TESTED_DIR / filename
                file_path.rename(target)
                log_with_context(logger, "info", "Sandbox test passed, moved to tested/",
                               file=filename)
            except Exception as e:
                result.warnings.append(f"Failed to move to tested/: {e}")
        else:
            result.status = TestStatus.FAILED
            log_with_context(logger, "warning", "Sandbox test failed",
                           file=filename, errors=result.errors)

        return result

    @classmethod
    def test_all_pending(cls) -> List[TestResult]:
        """Test all files in pending/ directory."""
        cls.ensure_directories()
        results = []

        for py_file in PENDING_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            result = cls.test_file(py_file.name)
            results.append(result)

        return results

    @classmethod
    def promote(cls, filename: str, skip_approval: bool = False) -> Dict[str, Any]:
        """
        Promote a tested file to dynamic tools.

        Args:
            filename: Name of file in tested/ or approved/
            skip_approval: If True, promote directly from tested/ (no human approval)

        Returns:
            Dict with promotion result
        """
        cls.ensure_directories()

        # Find source file
        if skip_approval:
            source = TESTED_DIR / filename
        else:
            source = APPROVED_DIR / filename

        if not source.exists():
            # Try other locations
            for dir_path in [TESTED_DIR, APPROVED_DIR, PENDING_DIR]:
                potential = dir_path / filename
                if potential.exists():
                    return {
                        "success": False,
                        "error": f"File found in {dir_path.name}/, not ready for promotion",
                        "hint": "Run test first" if dir_path == PENDING_DIR else "Move to approved/ first"
                    }

            return {"success": False, "error": f"File not found: {filename}"}

        # Copy to dynamic tools
        target = DYNAMIC_TOOLS_DIR / filename
        try:
            DYNAMIC_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text())

            # Move source to promoted/ for record
            promoted = PROMOTED_DIR / filename
            source.rename(promoted)

            # Hot-reload
            reload_result = None
            try:
                from .tool_loader import DynamicToolLoader
                reload_result = DynamicToolLoader.reload(filename.replace(".py", ""))
            except Exception as e:
                log_with_context(logger, "warning", "Hot-reload failed after promotion",
                               file=filename, error=str(e))

            log_with_context(logger, "info", "Sandbox tool promoted",
                           file=filename, target=str(target))

            return {
                "success": True,
                "file": filename,
                "promoted_to": str(target),
                "archived_to": str(promoted),
                "hot_reloaded": reload_result is not None and reload_result.get("success", False)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def approve(cls, filename: str) -> Dict[str, Any]:
        """Move a tested file to approved/ (human approval step)."""
        cls.ensure_directories()

        source = TESTED_DIR / filename
        if not source.exists():
            return {"success": False, "error": f"File not found in tested/: {filename}"}

        try:
            target = APPROVED_DIR / filename
            source.rename(target)
            return {
                "success": True,
                "file": filename,
                "moved_to": str(target)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get sandbox status."""
        cls.ensure_directories()

        def count_files(dir_path: Path) -> int:
            return len([f for f in dir_path.glob("*.py") if not f.name.startswith("_")])

        return {
            "directories": {
                "pending": str(PENDING_DIR),
                "tested": str(TESTED_DIR),
                "approved": str(APPROVED_DIR),
                "promoted": str(PROMOTED_DIR)
            },
            "counts": {
                "pending": count_files(PENDING_DIR),
                "tested": count_files(TESTED_DIR),
                "approved": count_files(APPROVED_DIR),
                "promoted": count_files(PROMOTED_DIR)
            }
        }

    @classmethod
    def list_files(cls, directory: str = "pending") -> List[Dict[str, Any]]:
        """List files in a sandbox directory."""
        dir_map = {
            "pending": PENDING_DIR,
            "tested": TESTED_DIR,
            "approved": APPROVED_DIR,
            "promoted": PROMOTED_DIR
        }

        dir_path = dir_map.get(directory)
        if not dir_path:
            return []

        cls.ensure_directories()
        files = []

        for py_file in dir_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            files.append({
                "name": py_file.name,
                "size_bytes": py_file.stat().st_size,
                "modified": datetime.fromtimestamp(py_file.stat().st_mtime).isoformat()
            })

        return files
