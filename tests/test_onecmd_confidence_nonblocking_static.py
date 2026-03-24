from pathlib import Path


def test_onecmd_confidence_uses_smoke_only_not_standalone_reality_gate():
    script = Path("scripts/jarvis_onecmd_cli.sh").read_text(encoding="utf-8")
    confidence_line = next(
        line for line in script.splitlines() if "jarvis.confidence)" in line
    )

    assert "jarvis_post_deploy_smoke.sh" in confidence_line
    assert "jarvis_reality_check.sh" not in confidence_line
