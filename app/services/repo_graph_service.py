"""Lightweight repo graph service for Python symbol and impact analysis."""

from __future__ import annotations

import ast
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, DefaultDict, Iterable

try:
    from ..observability import get_logger
except Exception:  # pragma: no cover - local test fallback when optional deps are absent
    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        return logger


logger = get_logger("jarvis.repo_graph")


@dataclass(frozen=True)
class SymbolDefinition:
    symbol: str
    symbol_type: str
    module_path: str
    file_path: str
    line: int
    column: int


@dataclass(frozen=True)
class SymbolReference:
    target_symbol: str
    source_symbol: str
    source_file: str
    kind: str
    line: int
    column: int


class _DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module_path: str, file_path: str) -> None:
        self._module_path = module_path
        self._file_path = file_path
        self.symbols: dict[str, SymbolDefinition] = {}
        self.local_defs: dict[str, str] = {}
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self.class_stack:
            self.generic_visit(node)
            return

        symbol = f"{self._module_path}.{node.name}"
        self.symbols[symbol] = SymbolDefinition(
            symbol=symbol,
            symbol_type="class",
            module_path=self._module_path,
            file_path=self._file_path,
            line=node.lineno,
            column=node.col_offset,
        )
        self.local_defs[node.name] = symbol
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.class_stack:
            symbol = f"{self._module_path}.{self.class_stack[-1]}.{node.name}"
            symbol_type = "method"
        else:
            symbol = f"{self._module_path}.{node.name}"
            symbol_type = "function"
            self.local_defs[node.name] = symbol

        self.symbols[symbol] = SymbolDefinition(
            symbol=symbol,
            symbol_type=symbol_type,
            module_path=self._module_path,
            file_path=self._file_path,
            line=node.lineno,
            column=node.col_offset,
        )
        self.generic_visit(node)


class _ReferenceCollector(ast.NodeVisitor):
    def __init__(
        self,
        module_path: str,
        file_path: str,
        local_defs: dict[str, str],
    ) -> None:
        self._module_path = module_path
        self._file_path = file_path
        self._local_defs = local_defs
        self.references: list[SymbolReference] = []
        self._current_symbols: list[str] = []
        self._current_classes: list[str] = []
        self._import_aliases: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            alias_name = alias.asname or alias.name.split(".")[0]
            self._import_aliases[alias_name] = alias.name
            self._add_reference(alias.name, "import", node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base_module = self._resolve_relative_module(node.module, node.level)
        for alias in node.names:
            if alias.name == "*":
                continue
            target = f"{base_module}.{alias.name}" if base_module else alias.name
            self._import_aliases[alias.asname or alias.name] = target
            self._add_reference(target, "import", node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_symbol = f"{self._module_path}.{node.name}"
        self._current_symbols.append(class_symbol)
        self._current_classes.append(class_symbol)

        for base in node.bases:
            target = self._resolve_expr_to_symbol(base)
            if target:
                self._add_reference(target, "inherit", base)

        self.generic_visit(node)
        self._current_classes.pop()
        self._current_symbols.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def visit_Call(self, node: ast.Call) -> None:
        target = self._resolve_expr_to_symbol(node.func)
        if target:
            self._add_reference(target, "call", node.func)
        self.generic_visit(node)

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._current_classes:
            symbol = f"{self._current_classes[-1]}.{node.name}"
        else:
            symbol = f"{self._module_path}.{node.name}"

        self._current_symbols.append(symbol)
        self.generic_visit(node)
        self._current_symbols.pop()

    def _resolve_relative_module(self, module: str | None, level: int) -> str:
        if level <= 0:
            return module or ""

        parts = self._module_path.split(".")
        parent_parts = parts[:-level] if level <= len(parts) else []
        if module:
            parent_parts.extend(module.split("."))
        return ".".join(parent_parts)

    def _resolve_expr_to_symbol(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self._import_aliases:
                return self._import_aliases[node.id]
            if node.id in self._local_defs:
                return self._local_defs[node.id]
            if self._current_classes and node.id == "self":
                return self._current_classes[-1]
            return None

        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self" and self._current_classes:
                return f"{self._current_classes[-1]}.{node.attr}"

            base_symbol = self._resolve_expr_to_symbol(node.value)
            if base_symbol:
                return f"{base_symbol}.{node.attr}"

        return None

    def _add_reference(self, target_symbol: str, kind: str, node: ast.AST) -> None:
        self.references.append(
            SymbolReference(
                target_symbol=target_symbol,
                source_symbol=self._current_symbols[-1] if self._current_symbols else self._module_path,
                source_file=self._file_path,
                kind=kind,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
            )
        )


class RepoGraphService:
    """Small, read-only Python repo graph for symbol and impact lookups."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        scan_roots: Iterable[str] = ("app", "tests"),
    ) -> None:
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.scan_roots = tuple(scan_roots)
        self._lock = Lock()
        self._symbols: dict[str, SymbolDefinition] = {}
        self._references_by_target: DefaultDict[str, list[SymbolReference]] = defaultdict(list)
        self._callers_by_target: DefaultDict[str, set[str]] = defaultdict(set)
        self._built_at: str | None = None
        self._files_scanned = 0

    def get_health(self, force_rebuild: bool = False) -> dict[str, Any]:
        self._ensure_snapshot(force_rebuild=force_rebuild)
        return {
            "status": "ok",
            "repo_root": str(self.repo_root),
            "scan_roots": list(self.scan_roots),
            "files_scanned": self._files_scanned,
            "symbol_count": len(self._symbols),
            "reference_count": sum(len(items) for items in self._references_by_target.values()),
            "built_at": self._built_at,
        }

    def find_symbol_references(
        self,
        symbol_query: str,
        force_rebuild: bool = False,
        max_results: int = 100,
    ) -> dict[str, Any]:
        self._ensure_snapshot(force_rebuild=force_rebuild)
        resolved_symbols = self._resolve_symbols(symbol_query)
        references = self._gather_references(resolved_symbols, max_results=max_results)
        return {
            "status": "ok" if resolved_symbols else "not_found",
            "query": symbol_query,
            "resolved_symbols": resolved_symbols,
            "references": references,
            "reference_count": len(references),
            "built_at": self._built_at,
        }

    def estimate_change_impact(
        self,
        symbol_query: str,
        force_rebuild: bool = False,
        max_depth: int = 2,
        max_results: int = 100,
    ) -> dict[str, Any]:
        self._ensure_snapshot(force_rebuild=force_rebuild)
        resolved_symbols = self._resolve_symbols(symbol_query)
        impacted_symbols: list[dict[str, Any]] = []
        impacted_files: dict[str, dict[str, Any]] = {}
        visited = set(resolved_symbols)
        queue = deque((symbol, 0) for symbol in resolved_symbols)

        while queue and len(impacted_symbols) < max_results:
            target_symbol, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for caller_symbol in sorted(self._callers_by_target.get(target_symbol, set())):
                if caller_symbol in visited:
                    continue
                visited.add(caller_symbol)
                next_depth = depth + 1
                definition = self._symbols.get(caller_symbol)
                file_path = definition.file_path if definition else None
                impacted_symbols.append(
                    {
                        "symbol": caller_symbol,
                        "depth": next_depth,
                        "file_path": file_path,
                    }
                )
                if file_path and file_path not in impacted_files:
                    impacted_files[file_path] = {
                        "file_path": file_path,
                        "symbol_count": 0,
                    }
                if file_path:
                    impacted_files[file_path]["symbol_count"] += 1
                queue.append((caller_symbol, next_depth))

        return {
            "status": "ok" if resolved_symbols else "not_found",
            "query": symbol_query,
            "resolved_symbols": resolved_symbols,
            "impacted_symbols": impacted_symbols,
            "impacted_files": sorted(
                impacted_files.values(),
                key=lambda item: (-item["symbol_count"], item["file_path"]),
            ),
            "built_at": self._built_at,
        }

    def related_files_for_symbol(
        self,
        symbol_query: str,
        force_rebuild: bool = False,
        max_results: int = 20,
    ) -> dict[str, Any]:
        self._ensure_snapshot(force_rebuild=force_rebuild)
        resolved_symbols = self._resolve_symbols(symbol_query)
        file_scores: dict[str, dict[str, Any]] = {}

        for symbol in resolved_symbols:
            definition = self._symbols.get(symbol)
            if definition:
                entry = file_scores.setdefault(
                    definition.file_path,
                    {"file_path": definition.file_path, "roles": set(), "match_count": 0, "score": 0},
                )
                entry["roles"].add("definition")
                entry["match_count"] += 1
                entry["score"] += 100

            for reference in self._references_by_target.get(symbol, []):
                entry = file_scores.setdefault(
                    reference.source_file,
                    {"file_path": reference.source_file, "roles": set(), "match_count": 0, "score": 0},
                )
                entry["roles"].add(reference.kind)
                entry["match_count"] += 1
                entry["score"] += 5 if reference.kind == "call" else 2

        related_files = sorted(
            (
                {
                    "file_path": item["file_path"],
                    "roles": sorted(item["roles"]),
                    "match_count": item["match_count"],
                    "score": item["score"],
                }
                for item in file_scores.values()
            ),
            key=lambda item: (-item["score"], item["file_path"]),
        )[:max_results]

        return {
            "status": "ok" if resolved_symbols else "not_found",
            "query": symbol_query,
            "resolved_symbols": resolved_symbols,
            "related_files": related_files,
            "built_at": self._built_at,
        }

    def _ensure_snapshot(self, force_rebuild: bool = False) -> None:
        with self._lock:
            if self._built_at is not None and not force_rebuild:
                return
            self._build_snapshot()

    def _build_snapshot(self) -> None:
        symbols: dict[str, SymbolDefinition] = {}
        references_by_target: DefaultDict[str, list[SymbolReference]] = defaultdict(list)
        callers_by_target: DefaultDict[str, set[str]] = defaultdict(set)
        files_scanned = 0

        for file_path in self._iter_python_files():
            rel_path = file_path.relative_to(self.repo_root).as_posix()
            module_path = self._module_path_for(rel_path)
            if not module_path:
                continue

            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                logger.warning("Skipping %s: %s", rel_path, exc)
                continue

            files_scanned += 1
            definition_collector = _DefinitionCollector(module_path, rel_path)
            definition_collector.visit(tree)
            symbols.update(definition_collector.symbols)

            reference_collector = _ReferenceCollector(module_path, rel_path, definition_collector.local_defs)
            reference_collector.visit(tree)
            for reference in reference_collector.references:
                references_by_target[reference.target_symbol].append(reference)
                if reference.kind == "call" and reference.source_symbol:
                    callers_by_target[reference.target_symbol].add(reference.source_symbol)

        self._symbols = symbols
        self._references_by_target = references_by_target
        self._callers_by_target = callers_by_target
        self._files_scanned = files_scanned
        self._built_at = datetime.now(timezone.utc).isoformat()

    def _iter_python_files(self) -> Iterable[Path]:
        for scan_root in self.scan_roots:
            root = (self.repo_root / scan_root).resolve()
            if not root.exists():
                continue
            yield from sorted(
                path for path in root.rglob("*.py") if "__pycache__" not in path.parts
            )

    def _module_path_for(self, rel_path: str) -> str:
        path = Path(rel_path)
        parts = list(path.with_suffix("").parts)
        if not parts:
            return ""
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def _resolve_symbols(self, symbol_query: str) -> list[str]:
        if symbol_query in self._symbols or symbol_query in self._references_by_target:
            return [symbol_query]

        query_tail = symbol_query.split(".")[-1]
        matches = {
            symbol
            for symbol in set(self._symbols) | set(self._references_by_target)
            if symbol.endswith(f".{symbol_query}") or symbol.endswith(f".{query_tail}")
        }
        return sorted(matches)

    def _gather_references(self, symbols: Iterable[str], max_results: int) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for symbol in symbols:
            for reference in self._references_by_target.get(symbol, []):
                references.append(
                    {
                        "target_symbol": reference.target_symbol,
                        "source_symbol": reference.source_symbol,
                        "file_path": reference.source_file,
                        "kind": reference.kind,
                        "line": reference.line,
                        "column": reference.column,
                    }
                )

        references.sort(key=lambda item: (item["file_path"], item["line"], item["kind"], item["source_symbol"]))
        return references[:max_results]


_service: RepoGraphService | None = None


def get_service(force_rebuild: bool = False) -> RepoGraphService:
    global _service
    if _service is None:
        _service = RepoGraphService()
    if force_rebuild:
        _service.get_health(force_rebuild=True)
    return _service
