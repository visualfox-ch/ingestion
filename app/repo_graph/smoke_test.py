"""Small smoke test for the embedded repo graph spike."""

from __future__ import annotations

import json

from ..services.repo_graph_service import RepoGraphService


def main() -> None:
    service = RepoGraphService()
    health = service.get_health(force_rebuild=True)
    available_symbols = sorted(service._symbols)  # internal use for a lightweight smoke test
    preferred_symbols = [
        "app.services.skill_manager.SkillManager",
        "app.routers.code_router.router",
    ]
    sample_symbol = next(
        (symbol for symbol in preferred_symbols if symbol in service._symbols),
        available_symbols[0] if available_symbols else "",
    )

    payload = {
        "health": health,
        "sample_symbol": sample_symbol,
        "references": service.find_symbol_references(sample_symbol, max_results=5) if sample_symbol else {},
        "impact": service.estimate_change_impact(sample_symbol, max_depth=2, max_results=5) if sample_symbol else {},
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
