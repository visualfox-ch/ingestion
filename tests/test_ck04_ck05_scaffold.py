"""
CK04/CK05 scaffold sanity checks.
"""


def test_ck04_ck05_routes_exist():
    from app.main import app

    routes = {route.path for route in app.routes}
    assert "/causal/insights" in routes
    assert "/causal/recommendations" in routes
