"""
Pre-deployment validation for Jarvis ingestion system.

This module provides validation utilities to prevent deploying corrupted or
invalid Python code. It checks:
- Python syntax correctness
- File integrity (no null bytes, proper encoding)
- Import availability
- Common Python errors

Usage:
    from validators import CodeValidator
    
    validator = CodeValidator()
    if validator.validate_file('app/main.py'):
        print("✓ Safe to deploy")
    else:
        print("✗ Validation failed")
"""

import ast
import hashlib
import os
import sys
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of a validation check."""
    
    file: str
    valid: bool
    errors: List[str]
    warnings: List[str]
    
    def __bool__(self) -> bool:
        """Return True if validation passed (no errors)."""
        return self.valid and len(self.errors) == 0


class CodeValidator:
    """Validates Python code before deployment."""
    
    def __init__(self, verbose: bool = False):
        """
        Initialize validator.
        
        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose
        self.results: List[ValidationResult] = []
    
    def validate_file(self, filepath: str) -> bool:
        """
        Validate a single Python file.
        
        Args:
            filepath: Path to Python file
            
        Returns:
            True if validation passed, False otherwise
        """
        file_path = Path(filepath)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        if not file_path.suffix == '.py':
            raise ValueError(f"Not a Python file: {filepath}")
        
        errors = []
        warnings = []
        
        # Check integrity
        try:
            self._check_integrity(file_path)
        except ValueError as e:
            errors.append(str(e))
        
        # Check syntax
        try:
            self._check_syntax(file_path)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
        
        # Check imports
        try:
            self._check_imports(file_path)
        except Exception as e:
            warnings.append(f"Import warning: {e}")
        
        # Check common errors
        try:
            common_errors = self._check_common_errors(file_path)
            warnings.extend(common_errors)
        except Exception as e:
            warnings.append(f"Error checking common issues: {e}")
        
        result = ValidationResult(
            file=filepath,
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
        
        self.results.append(result)
        return result.valid
    
    def validate_directory(self, dirpath: str, recursive: bool = True) -> bool:
        """
        Validate all Python files in a directory.
        
        Args:
            dirpath: Path to directory
            recursive: If True, search subdirectories recursively
            
        Returns:
            True if all files passed validation
        """
        dir_path = Path(dirpath)
        
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dirpath}")
        
        pattern = "**/*.py" if recursive else "*.py"
        py_files = list(dir_path.glob(pattern))
        
        if not py_files:
            raise ValueError(f"No Python files found in {dirpath}")
        
        all_valid = True
        for py_file in sorted(py_files):
            try:
                if not self.validate_file(str(py_file)):
                    all_valid = False
            except Exception as e:
                if self.verbose:
                    print(f"Error validating {py_file}: {e}", file=sys.stderr)
                all_valid = False
        
        return all_valid
    
    def get_report(self) -> str:
        """
        Get a formatted validation report.
        
        Returns:
            Formatted report string
        """
        lines = [
            "═" * 60,
            "Pre-Deployment Validation Report",
            "═" * 60,
            f"Total files checked: {len(self.results)}",
            f"Valid files: {sum(1 for r in self.results if r.valid)}",
            f"Files with errors: {sum(1 for r in self.results if r.errors)}",
            f"Warnings: {sum(len(r.warnings) for r in self.results)}",
            "",
        ]
        
        # Show errors
        errors_found = [r for r in self.results if r.errors]
        if errors_found:
            lines.append("❌ Files with errors:")
            for result in errors_found:
                lines.append(f"\n  {result.file}:")
                for error in result.errors:
                    lines.append(f"    • {error}")
        
        # Show warnings
        warnings_found = [r for r in self.results if r.warnings]
        if warnings_found:
            lines.append("\n⚠️  Warnings:")
            for result in warnings_found:
                if result.warnings:
                    lines.append(f"\n  {result.file}:")
                    for warning in result.warnings:
                        lines.append(f"    • {warning}")
        
        # Summary
        lines.append("\n" + "═" * 60)
        all_valid = all(r.valid for r in self.results)
        if all_valid and not any(r.warnings for r in self.results):
            lines.append("✅ All validations passed - Safe to deploy")
        elif all_valid:
            lines.append("⚠️  Passed but with warnings - Review before deploy")
        else:
            lines.append("❌ Validation failed - Address errors before deployment")
        lines.append("═" * 60)
        
        return "\n".join(lines)
    
    @staticmethod
    def _check_integrity(filepath: Path) -> None:
        """
        Check file integrity.
        
        Args:
            filepath: Path to file
            
        Raises:
            ValueError: If file is corrupted
        """
        # Check file exists and has content
        if not filepath.exists():
            raise ValueError(f"File does not exist: {filepath}")
        
        if filepath.stat().st_size == 0:
            raise ValueError(f"File is empty: {filepath}")
        
        # Check for null bytes (corruption indicator)
        with open(filepath, 'rb') as f:
            content = f.read()
            if b'\x00' in content:
                raise ValueError(f"Null bytes detected (corruption): {filepath}")
        
        # Check encoding
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                f.read()
        except UnicodeDecodeError as e:
            raise ValueError(f"File has invalid UTF-8 encoding: {e}")
    
    @staticmethod
    def _check_syntax(filepath: Path) -> None:
        """
        Check Python syntax.
        
        Args:
            filepath: Path to Python file
            
        Raises:
            SyntaxError: If syntax is invalid
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
            ast.parse(source)
        except SyntaxError as e:
            raise SyntaxError(f"{filepath}:{e.lineno}: {e.msg}")
    
    @staticmethod
    def _check_imports(filepath: Path) -> None:
        """
        Check if imports are resolvable.
        
        Args:
            filepath: Path to Python file
            
        Raises:
            ImportError: If import resolution fails
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # This is a simple check; full import validation
                    # requires runtime environment
                    if not _is_valid_module_name(alias.name):
                        raise ImportError(f"Invalid module name: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and not _is_valid_module_name(node.module):
                    raise ImportError(f"Invalid module name: {node.module}")
    
    @staticmethod
    def _check_common_errors(filepath: Path) -> List[str]:
        """
        Check for common Python errors.
        
        Args:
            filepath: Path to Python file
            
        Returns:
            List of warning strings
        """
        warnings = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for i, line in enumerate(lines, 1):
            # Check for double-space imports
            if line.lstrip().startswith('import  ') or \
               line.lstrip().startswith('from  '):
                warnings.append(f"Line {i}: Double space in import statement")
            
            # Check for trailing whitespace
            if line.rstrip() != line.rstrip('\n'):
                warnings.append(f"Line {i}: Trailing whitespace")
        
        return warnings
    
    @staticmethod
    def calculate_checksum(filepath: str) -> str:
        """
        Calculate MD5 checksum of file.
        
        Args:
            filepath: Path to file
            
        Returns:
            MD5 checksum hex string
        """
        hash_md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    @staticmethod
    def save_checksum(filepath: str, checksum_dir: str = '.checksums') -> str:
        """
        Save checksum for file.
        
        Args:
            filepath: Path to file
            checksum_dir: Directory to store checksums
            
        Returns:
            Checksum value
        """
        checksum = CodeValidator.calculate_checksum(filepath)
        
        os.makedirs(checksum_dir, exist_ok=True)
        checksum_file = os.path.join(
            checksum_dir,
            f"{os.path.basename(filepath)}.md5"
        )
        
        with open(checksum_file, 'w') as f:
            f.write(f"{checksum}  {filepath}\n")
        
        return checksum
    
    @staticmethod
    def verify_checksum(
        filepath: str,
        checksum_dir: str = '.checksums'
    ) -> Tuple[bool, str]:
        """
        Verify file checksum against saved value.
        
        Args:
            filepath: Path to file
            checksum_dir: Directory with stored checksums
            
        Returns:
            Tuple of (match: bool, message: str)
        """
        checksum_file = os.path.join(
            checksum_dir,
            f"{os.path.basename(filepath)}.md5"
        )
        
        if not os.path.exists(checksum_file):
            return False, f"No stored checksum for {filepath}"
        
        with open(checksum_file, 'r') as f:
            stored_checksum = f.read().split()[0]
        
        current_checksum = CodeValidator.calculate_checksum(filepath)
        
        if stored_checksum == current_checksum:
            return True, f"Checksum verified: {filepath}"
        else:
            return False, (
                f"Checksum mismatch: {filepath}\n"
                f"  Expected: {stored_checksum}\n"
                f"  Found:    {current_checksum}"
            )


def _is_valid_module_name(name: str) -> bool:
    """Check if string is a valid Python module name."""
    if not name:
        return False
    # Simple validation; full validation would be more complex
    return all(c.isalnum() or c in '._' for c in name)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate Python code before deployment'
    )
    parser.add_argument('target', nargs='?', default='.',
                        help='File or directory to validate')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('--checksum', action='store_true',
                        help='Save checksums for files')
    
    args = parser.parse_args()
    
    validator = CodeValidator(verbose=args.verbose)
    target_path = Path(args.target)
    
    try:
        if target_path.is_file():
            validator.validate_file(str(target_path))
        elif target_path.is_dir():
            validator.validate_directory(str(target_path))
        else:
            print(f"Error: {args.target} is neither file nor directory")
            sys.exit(1)
        
        print(validator.get_report())
        sys.exit(0 if all(r.valid for r in validator.results) else 1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
