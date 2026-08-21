from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")
DISK_MOUNT = "/var/data/clientflow-release-artifacts"
ARTIFACT_DIR = f"{DISK_MOUNT}/store"


def _backend_block() -> str:
    marker = "  # ─── Frontend ─"
    assert marker in RENDER
    return RENDER.split(marker, 1)[0]


def test_51n_backend_is_new_frankfurt_single_instance_with_51m_authority():
    backend = _backend_block()
    assert "name: planiq-display-v2-backend" in backend
    assert re.search(r"(?m)^    region: frankfurt$", backend)
    assert re.search(r"(?m)^    plan: starter$", backend)
    assert re.search(r"(?m)^    numInstances: 1$", backend)
    assert "--workers 1" in backend
    assert "name: clientflow-release-artifacts" in backend
    assert f"mountPath: {DISK_MOUNT}" in backend
    assert (
        "- key: CLIENTFLOW_RELEASE_ARTIFACT_DIR\n"
        f'        value: "{ARTIFACT_DIR}"'
    ) in backend
    assert f"mkdir -p {ARTIFACT_DIR}" in backend
    assert f"chmod 0755 {ARTIFACT_DIR}" in backend
    assert 'preDeployCommand: "python scripts/run_migrations.py"' in backend
    assert "publish_clientflow_release" not in backend


def test_51n_uses_neon_secret_and_provisions_no_render_database():
    assert "databases:" not in RENDER
    backend = _backend_block()
    assert "- key: DATABASE_URL\n        sync: false" in backend
    assert '- key: MIGRATION_ALLOW_EMPTY_DATABASE\n        value: "false"' in backend


def test_51n_domains_and_static_runtime_are_canonical_and_legacy_hosts_are_absent():
    assert "api.display.planiq.dk" in RENDER
    assert "display.planiq.dk" in RENDER
    assert "name: planiq-display-v2-frontend" in RENDER
    assert re.search(r"(?m)^    runtime: static$", RENDER)
    assert "type: static" not in RENDER
    assert "kulturskole-infosk-rm.onrender.com" not in RENDER
    assert "infoskaerm-backend" not in RENDER
    assert "infoskaerm-frontend" not in RENDER


def test_51n_has_dedicated_fresh_auth_key_and_no_livestream_bootstrap_import_config():
    backend = _backend_block()
    assert "- key: CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64\n        generateValue: true" in backend
    assert "LIVESTREAM_V2_BOOTSTRAP_CLIENT_ID" not in backend
    assert "LIVESTREAM_V2_BOOTSTRAP_CREDENTIAL_ID" not in backend
    assert "LIVESTREAM_V2_BOOTSTRAP_SECRET_SHA256" not in backend
