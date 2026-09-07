from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.update_auth import (  # noqa: E402
    UPDATE_ALGORITHM,
    UPDATE_TOKEN_AUDIENCE,
    generate_update_key,
)
from clientflow_release.updater_config import UpdaterConfig, UpdaterConfigError  # noqa: E402
from clientflow_release.updater_transport import UPDATE_SCOPES, UpdaterTransport  # noqa: E402


class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self.status = 200
        self.headers = {}
        self._offset = 0

    def read(self, amount: int = -1):
        if amount < 0:
            amount = len(self._body) - self._offset
        start = self._offset
        end = min(len(self._body), start + amount)
        self._offset = end
        return self._body[start:end]

    def getcode(self):
        return self.status

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _Opener:
    def __init__(self, response: _Response):
        self.response = response
        self.requests = []

    def open(self, request, timeout=30):
        self.requests.append((request, timeout))
        return self.response


def _credential_fixture(root: Path, *, credential_mode: int = 0o440, key_mode: int = 0o440):
    root.mkdir(parents=True, mode=0o700)
    private_key = root / "update-private-key.pem"
    _pem, key_id, _jwk, _thumbprint = generate_update_key(private_key)
    os.chmod(private_key, key_mode)

    credential_id = str(uuid.uuid4())
    credential = {
        "schema_version": 1,
        "backend_url": "https://display.example.invalid",
        "client_id": 28,
        "credential_id": credential_id,
        "key_id": key_id,
        "algorithm": UPDATE_ALGORITHM,
        "token_audience": UPDATE_TOKEN_AUDIENCE,
        "access_token_issuer": "https://display.example.invalid",
        "access_token_audience": "urn:planiq:clientflow-update",
    }
    credential_file = root / "update-credential.json"
    credential_file.write_text(json.dumps(credential), encoding="utf-8")
    os.chmod(credential_file, credential_mode)
    return credential_file, private_key, credential_id


def _clear_overrides(monkeypatch):
    for name in (
        "CLIENTFLOW_UPDATE_CREDENTIAL_FILE",
        "CLIENTFLOW_UPDATE_PRIVATE_KEY_FILE",
        "CLIENTFLOW_UPDATE_STATE_DIR",
        "STATE_DIRECTORY",
        "CLIENTFLOW_UPDATE_CA_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_systemd_loadcredential_0440_is_accepted_and_can_sign(monkeypatch, tmp_path):
    credentials_root = tmp_path / "credentials"
    _credential_fixture(credentials_root)
    _clear_overrides(monkeypatch)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_root))

    config = UpdaterConfig.from_environment()

    assert config.client_id == 28
    assert config.private_key_forbidden_mode_bits == 0o007

    response = _Response(json.dumps({
        "access_token": "systemd-credential-test-token",
        "token_type": "DPoP",
        "expires_in": 300,
        "scope": " ".join(sorted(UPDATE_SCOPES)),
    }).encode())
    opener = _Opener(response)
    transport = UpdaterTransport(config, opener=opener)

    assert transport.issue_access_token() == "systemd-credential-test-token"
    assert len(opener.requests) == 1


def test_plain_at_rest_0440_credential_remains_rejected(tmp_path):
    credential_file, private_key, _credential_id = _credential_fixture(
        tmp_path / "plain",
        credential_mode=0o440,
        key_mode=0o600,
    )

    with pytest.raises(UpdaterConfigError, match="Update credential kunne ikke indlæses sikkert"):
        UpdaterConfig.from_paths(
            credential_file=credential_file,
            private_key=private_key,
            state_root=tmp_path / "state",
        )


def test_systemd_credential_with_other_read_bit_is_rejected(monkeypatch, tmp_path):
    credentials_root = tmp_path / "credentials"
    _credential_fixture(credentials_root, credential_mode=0o444, key_mode=0o440)
    _clear_overrides(monkeypatch)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_root))

    with pytest.raises(UpdaterConfigError, match="Update credential kunne ikke indlæses sikkert"):
        UpdaterConfig.from_environment()
