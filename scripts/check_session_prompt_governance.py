#!/usr/bin/env python3
"""Validate session prompt governance anchors for CI/CD and roadmap alignment.

This script mirrors the canonical docker check and can be used as a local
fallback when the canonical preflight script is not available.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

INGESTION_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = INGESTION_ROOT.parent
PROMPTS_ROOT = WORKSPACE_ROOT / "prompts"

CANONICAL_DOCKER_ROOT = Path(
    os.environ.get("JARVIS_CANONICAL_OPS_ROOT", "/Volumes/BRAIN/system/docker")
)
FALLBACK_DOCKER_ROOT = WORKSPACE_ROOT / "docker"


def _resolve_library_prompt() -> Path:
    candidates = (
        CANONICAL_DOCKER_ROOT / "docs" / "library" / "prompts" / "NEXT_SESSION_PROMPT.md",
        FALLBACK_DOCKER_ROOT / "docs" / "library" / "prompts" / "NEXT_SESSION_PROMPT.md",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


PROMPT_FILES = {
    "session_start": PROMPTS_ROOT / "session_start_prompt.md",
    "session_start_compact": PROMPTS_ROOT / "session_start_prompt_compact.md",
    "next_session": PROMPTS_ROOT / "NEXT_SESSION_PROMPT.md",
    "library_next_session": _resolve_library_prompt(),
}

REQUIRED_COMMON = (
    "docs/ROADMAP.md",
    "TASKS.md",
    "JARVIS_MASTER_PRIORITY_BOARD.md",
)

REQUIRED_GATE_HINTS = (
    "G1 -> G2",
    "G4",
)


def _contains_all(content: str, needles: Iterable[str]) -> list[str]:
    missing = []
    for needle in needles:
        if needle not in content:
            missing.append(needle)
    return missing


def main() -> int:
    errors: list[str] = []

    for name, path in PROMPT_FILES.items():
        if not path.exists():
            errors.append(f"missing-file:{name}:{path}")
            continue

        content = path.read_text(encoding="utf-8")

        missing_common = _contains_all(content, REQUIRED_COMMON)
        if missing_common:
            errors.append(
                f"missing-roadmap-anchors:{name}:{','.join(missing_common)}"
            )

        missing_gate_hints = _contains_all(content, REQUIRED_GATE_HINTS)
        if missing_gate_hints:
            errors.append(
                f"missing-gate-path:{name}:{','.join(missing_gate_hints)}"
            )

    if errors:
        for err in errors:
            print(f"FAIL:{err}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
