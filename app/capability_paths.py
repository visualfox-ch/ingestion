"""
Helpers for resolving Jarvis capability artifact paths across local and NAS runtimes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]


def _brain_root() -> Path:
    return Path(os.getenv("BRAIN_ROOT", os.getenv("BRAIN_PATH", "/brain")))


def _dedupe(paths: Iterable[Path]) -> List[Path]:
    unique: List[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def candidate_docs_dirs() -> List[Path]:
    brain_root = _brain_root()
    return _dedupe(
        [
            brain_root / "system" / "docker" / "docs",
            brain_root / "system" / "ingestion" / "docs",
            brain_root / "system" / "docs",
            REPO_ROOT / "docs",
        ]
    )


def resolve_docs_path(filename: str) -> Path:
    candidates = [docs_dir / filename for docs_dir in candidate_docs_dirs()]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return (REPO_ROOT / "docs" / filename).resolve()


def get_capabilities_json_path() -> Path:
    return resolve_docs_path("CAPABILITIES.json")


def get_capability_catalog_path() -> Path:
    return resolve_docs_path("CAPABILITY_CATALOG.md")


def get_context_policy_path() -> Path:
    return resolve_docs_path("CONTEXT_POLICY.md")
