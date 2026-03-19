from unittest.mock import patch

from app.services.dynamic_model_router import DynamicModelRouter, Provider


def test_general_chat_routes_to_ollama_when_local_first_enabled():
    router = DynamicModelRouter()
    models = router._get_fallback_models()

    with patch.object(router, "classify_task", return_value=("general_chat", 0.92, 0.22)):
        with patch.object(router, "_get_models", return_value=models):
            with patch.object(router, "_get_selection_rules", return_value=[]):
                with patch.object(router, "_select_from_mapping", return_value=(None, "")):
                    selection = router.select_model("Kurze Zusammenfassung bitte")

    assert selection.provider == Provider.OLLAMA
    assert selection.model_id in models
    assert "local_first_capability_router" in selection.rules_applied


def test_force_provider_ollama_uses_local_default_model_when_db_lookup_fails():
    router = DynamicModelRouter()
    models = router._get_fallback_models()

    with patch.object(router, "classify_task", return_value=("research", 0.81, 0.91)):
        with patch.object(router, "_get_models", return_value=models):
            with patch.object(router, "_get_selection_rules", return_value=[]):
                with patch.object(router, "_select_from_mapping", return_value=(None, "")):
                    selection = router.select_model("Nutze lokal", force_provider="ollama")

    assert selection.provider == Provider.OLLAMA
    assert selection.model_id in models