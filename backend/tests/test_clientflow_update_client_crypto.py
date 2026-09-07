from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import uuid

import jwt

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.update_auth import (  # noqa: E402
    UPDATE_CLIENT_ASSERTION_TYP,
    UPDATE_DPOP_TYP,
    UPDATE_KEY_ROTATION_TYP,
    build_client_assertion,
    build_dpop_proof,
    build_key_rotation_proof,
    canonical_htu,
    generate_update_key,
    public_material,
)


def test_openssl_ed25519_client_assertion_and_dpop_are_backend_verifiable():
    with tempfile.TemporaryDirectory() as tmp:
        private_key = Path(tmp) / "private-key.pem"
        public_pem, key_id, jwk, _thumbprint = generate_update_key(private_key)
        assert private_key.stat().st_mode & 0o077 == 0
        assert public_material(private_key)[1] == key_id

        now = datetime.now(timezone.utc)
        credential_id = str(uuid.uuid4())
        assertion = build_client_assertion(
            private_key,
            credential_id=credential_id,
            key_id=key_id,
            now=now,
        )
        assert jwt.get_unverified_header(assertion) == {
            "alg": "EdDSA",
            "kid": key_id,
            "typ": UPDATE_CLIENT_ASSERTION_TYP,
        }
        claims = jwt.decode(
            assertion,
            public_pem,
            algorithms=["EdDSA"],
            audience="urn:planiq:clientflow-update:token",
        )
        assert claims["iss"] == credential_id
        assert claims["sub"] == credential_id

        url = "https://display.example.invalid/api/clientflow-update/deployments/active?ignored=1"
        access_token = "test-access-token"
        proof = build_dpop_proof(
            private_key,
            method="get",
            url=url,
            access_token=access_token,
            now=now,
        )
        header = jwt.get_unverified_header(proof)
        assert header["typ"] == UPDATE_DPOP_TYP
        assert header["jwk"] == jwk
        proof_claims = jwt.decode(
            proof,
            public_pem,
            algorithms=["EdDSA"],
            options={"verify_aud": False, "verify_exp": False},
        )
        assert proof_claims["htm"] == "GET"
        assert proof_claims["htu"] == canonical_htu(url)
        assert "ath" in proof_claims


def test_rotation_proof_is_signed_by_successor_key_and_binds_current_credential():
    with tempfile.TemporaryDirectory() as tmp:
        private_key = Path(tmp) / "successor.pem"
        public_pem, key_id, _jwk, _thumbprint = generate_update_key(private_key)
        current_id = str(uuid.uuid4())
        url = "https://display.example.invalid/api/clientflow-update/credential/rotate"
        proof = build_key_rotation_proof(
            private_key,
            current_credential_id=current_id,
            method="POST",
            url=url,
        )
        header = jwt.get_unverified_header(proof)
        assert header == {"alg": "EdDSA", "kid": key_id, "typ": UPDATE_KEY_ROTATION_TYP}
        claims = jwt.decode(
            proof,
            public_pem,
            algorithms=["EdDSA"],
            options={"verify_aud": False, "verify_exp": False},
        )
        assert claims["current_credential_id"] == current_id
        assert claims["htm"] == "POST"
        assert claims["htu"] == url
