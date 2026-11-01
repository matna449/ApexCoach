"""F21.2: default-deny API auth (F21 spec §3.3). Reloads web.backend.main under
each environment, the same way the other web backend tests do."""

import importlib
import os
import re
from unittest.mock import patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

KEY = "the-right-key"


def _app(tmp_path, **env):
    full_env = {
        "APEX_ENCRYPTION_KEY": "test",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        **env,
    }
    with patch.dict(os.environ, full_env, clear=True):
        import web.backend.main as main_module

        importlib.reload(main_module)
    return main_module.app


@pytest.fixture
def protected_app(tmp_path):
    return _app(tmp_path, APEX_API_KEY=KEY)


def _add_route(app, path):
    @app.get(path)
    def route():
        return {"reached": True}


def _protected_routes(app):
    from web.backend.auth import PUBLIC_PATHS

    for route in app.routes:
        if route.path not in PUBLIC_PATHS:
            path = re.sub(r"\{[^}]+\}", "x", route.path)
            for method in route.methods:
                yield method, path


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-key"},
        {"Authorization": f"Basic {KEY}"},
        {"Authorization": KEY},
        {"Authorization": "Bearer "},
    ],
    ids=["no-key", "wrong-key", "wrong-scheme", "no-scheme", "empty-key"],
)
def test_every_non_public_route_is_401_without_the_right_key(protected_app, headers):
    client = TestClient(protected_app)
    routes = list(_protected_routes(protected_app))

    assert ("POST", "/api/plan/week/push") in routes
    assert ("GET", "/api/trends/hrv") in routes
    for method, path in routes:
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401, f"{method} {path}"


def test_only_api_routes_exist_so_nothing_sidesteps_the_dependency(protected_app):
    assert all(isinstance(route, APIRoute) for route in protected_app.routes)


def test_liveness_probe_is_public(protected_app):
    response = TestClient(protected_app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_right_key_reaches_the_route(protected_app):
    _add_route(protected_app, "/api/added-later")
    client = TestClient(protected_app)

    assert client.get("/api/added-later").status_code == 401
    assert client.get(
        "/api/added-later", headers={"Authorization": f"Bearer {KEY}"}
    ).json() == {"reached": True}


def test_public_paths_match_exactly_never_by_prefix(protected_app):
    _add_route(protected_app, "/api/health/daily")

    assert TestClient(protected_app).get("/api/health/daily").status_code == 401


def test_a_non_ascii_key_is_rejected_rather_than_crashing(protected_app):
    response = TestClient(protected_app).get(
        "/api/trends/hrv", headers={"Authorization": "Bearer nyckel-å".encode("latin-1")}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("env", [{}, {"APEX_API_KEY": ""}], ids=["unset", "empty"])
def test_missing_key_configuration_fails_closed(tmp_path, env):
    client = TestClient(_app(tmp_path, **env))

    assert client.get("/api/trends/hrv").status_code == 503
    assert client.get("/api/health").status_code == 200


def test_opt_out_opens_the_api_when_no_key_is_set(tmp_path):
    app = _app(tmp_path, APEX_ALLOW_UNAUTHENTICATED="true")
    _add_route(app, "/api/added-later")

    assert TestClient(app).get("/api/added-later").status_code == 200


def test_opt_out_is_ignored_on_vercel(tmp_path):
    client = TestClient(_app(tmp_path, APEX_ALLOW_UNAUTHENTICATED="true", VERCEL="1"))

    assert client.get("/api/trends/hrv").status_code == 503
    assert client.get("/docs").status_code == 404


def test_a_configured_key_is_enforced_even_with_the_opt_out(tmp_path):
    client = TestClient(_app(tmp_path, APEX_API_KEY=KEY, APEX_ALLOW_UNAUTHENTICATED="true"))

    assert client.get("/api/trends/hrv").status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_404_without_the_opt_out(protected_app, path):
    client = TestClient(protected_app)

    assert client.get(path).status_code == 404
    assert client.get(path, headers={"Authorization": f"Bearer {KEY}"}).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_stay_available_locally_with_the_opt_out(tmp_path, path):
    client = TestClient(_app(tmp_path, APEX_ALLOW_UNAUTHENTICATED="true"))

    assert client.get(path).status_code == 200


def test_browser_preflight_still_works_for_the_local_frontend(tmp_path):
    client = TestClient(_app(tmp_path, APEX_ALLOW_UNAUTHENTICATED="true"))

    response = client.options(
        "/api/plan/week/push",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
