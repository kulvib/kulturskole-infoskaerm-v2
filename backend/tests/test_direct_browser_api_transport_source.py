from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_render_production_frontend_targets_direct_backend_but_keeps_api_rewrite():
    render = read("render.yaml")
    assert 'key: VITE_API_URL\n        value: "https://api.display.planiq.dk"' in render
    assert "source: /api/*" in render
    assert "destination: https://api.display.planiq.dk/api/*" in render


def test_refresh_cookie_auth_transport_remains_same_origin():
    config = read("frontend/src/config/apiConfig.js")
    api = read("frontend/src/api/api.js")
    assert 'export const AUTH_API_URL = `${API_PREFIX}/auth`;' in config
    assert "const authApiBase = AUTH_API_URL;" in api
    assert 'buildApiUrl("/auth")' not in api


def test_backend_cors_contract_allows_direct_frontend_and_exposes_observability():
    main = read("backend/service1/main.py")
    assert '"https://display.planiq.dk"' in main
    assert "allow_credentials=True" in main
    assert '"Authorization"' in main
    assert 'expose_headers=[REQUEST_ID_HEADER, "Server-Timing"]' in main
