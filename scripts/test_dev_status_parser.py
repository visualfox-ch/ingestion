"""Minimal dev_status parser smoke test (no deploy)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Point to docker docs by default for local tests
os.environ.setdefault("JARVIS_DOCS_ROOT", "/Volumes/BRAIN/system/docker")

from app import dev_status  # noqa: E402


def main():
    status = dev_status.get_development_status()
    print({
        "current_phase": status.get("current_phase"),
        "phase_status": status.get("phase_status"),
        "phase_completion": status.get("phase_completion"),
        "phase_completion_done": status.get("phase_completion_done"),
        "phase_completion_total": status.get("phase_completion_total"),
        "phase_completion_reason": status.get("phase_completion_reason"),
        "next_phase": status.get("next_phase"),
    })


if __name__ == "__main__":
    main()
