from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB = "/tmp/clientflow-http-smoke.db"
HLS = "/tmp/clientflow-http-smoke-hls"
Path(DB).unlink(missing_ok=True)
shutil.rmtree(HLS, ignore_errors=True)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789-0123456789"
os.environ["CREDENTIAL_PEPPER"] = "test-credential-pepper-0123456789-012345"
os.environ["PUBLIC_BASE_URL"] = "https://testserver"
os.environ["HLS_ROOT"] = HLS
os.environ["ADMIN_EMAIL"] = "admin@example.test"
os.environ["ADMIN_PASSWORD"] = "correct-horse-battery-staple"
os.environ["ADMIN_ORG_NAME"] = "Test"
os.environ["VIEWER_HEARTBEAT_SECONDS"] = "1"
os.environ["VIEWER_LEASE_SECONDS"] = "3"
os.environ["VIEWER_STOP_GRACE_SECONDS"] = "1"
os.environ["VIEWER_RECONCILE_INTERVAL_SECONDS"] = "1"

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app

Base.metadata.create_all(engine)

with TestClient(app, base_url="https://testserver") as browser:
    response = browser.post("/api/auth/login", json={"email": "admin@example.test", "password": "correct-horse-battery-staple"})
    assert response.status_code == 200, response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    response = browser.post("/api/clients", json={"name": "NUC-23", "id": 23})
    assert response.status_code == 201, response.text
    client_id = response.json()["id"]
    assert client_id == 23

    response = browser.post(f"/api/clients/{client_id}/livestream/credential")
    assert response.status_code == 200, response.text
    credential = response.json()
    assert credential["domain"] == "livestream"

    response = browser.post("/api/client-auth/token", json=credential)
    assert response.status_code == 200, response.text
    access_token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    response = browser.post(f"/api/clients/{client_id}/livestream/viewers")
    assert response.status_code == 201, response.text
    viewer = response.json()
    viewer_id = viewer["viewer_id"]
    generation_id = viewer["generation"]["id"]
    assert viewer["heartbeat_seconds"] == 1
    assert viewer["lease_seconds"] == 3
    assert viewer["stop_grace_seconds"] == 1

    response = browser.post(f"/api/clients/{client_id}/livestream/viewers/{viewer_id}/heartbeat")
    assert response.status_code == 200, response.text

    response = browser.post(
        f"/api/livestream-agent/clients/{client_id}/commands/claim",
        json={"lease_seconds": 60},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    claim = response.json()["claimed"]
    assert claim["command"]["command_type"] == "start"
    assert claim["command"]["payload"]["generation_id"] == generation_id

    response = browser.post(
        f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/started",
        json={},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    segment = b"segment"
    segment_hash = hashlib.sha256(segment).hexdigest()
    response = browser.put(
        f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/files/segment-000000001.ts?sequence=1&sha256={segment_hash}",
        content=segment,
        headers={**headers, "Content-Type": "video/mp2t"},
    )
    assert response.status_code == 200, response.text

    manifest = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:2,\nsegment-000000001.ts\n"
    manifest_hash = hashlib.sha256(manifest).hexdigest()
    response = browser.put(
        f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/files/index.m3u8?sequence=1&sha256={manifest_hash}",
        content=manifest,
        headers={**headers, "Content-Type": "application/vnd.apple.mpegurl"},
    )
    assert response.status_code == 200, response.text

    response = browser.post(
        f"/api/livestream-agent/clients/{client_id}/commands/{claim['command']['id']}/complete",
        json={"claim_token": claim["claim_token"], "result": {"generation": {"id": generation_id}}},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = browser.put(
        f"/api/livestream-agent/clients/{client_id}/status",
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {
                "producer": {"state": "running", "generation_id": generation_id},
                "uploader": {"state": "uploading", "generation_id": generation_id},
            },
            "agent_version": "1.2.0",
            "boot_id": "00000000-0000-4000-8000-000000000023",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = browser.get(f"/api/clients/{client_id}/livestream")
    assert response.status_code == 200, response.text
    assert response.json()["playlist_ready"] is True
    assert response.json()["generation"]["state"] == "running"
    assert response.json()["viewers"]["active"] == 1

    response = browser.get(f"/api/clients/{client_id}/livestream/hls/index.m3u8")
    assert response.status_code == 200, response.text
    assert b"segment-000000001.ts" in response.content

    # Leaving and returning inside grace keeps the same generation.
    response = browser.post(f"/api/clients/{client_id}/livestream/viewers/{viewer_id}/leave")
    assert response.status_code == 200, response.text
    response = browser.post(f"/api/clients/{client_id}/livestream/viewers")
    assert response.status_code == 201, response.text
    viewer2 = response.json()
    assert viewer2["generation"]["id"] == generation_id
    assert viewer2["command_id"] is None

    # The last viewer leaving causes an automatic stop after grace.
    response = browser.post(f"/api/clients/{client_id}/livestream/viewers/{viewer2['viewer_id']}/leave")
    assert response.status_code == 200, response.text
    time.sleep(2.2)
    response = browser.post(
        f"/api/livestream-agent/clients/{client_id}/commands/claim",
        json={"lease_seconds": 60},
        headers=headers,
    )
    stop_claim = response.json()["claimed"]
    assert stop_claim["command"]["command_type"] == "stop"

print("HTTP contract smoke: OK")
