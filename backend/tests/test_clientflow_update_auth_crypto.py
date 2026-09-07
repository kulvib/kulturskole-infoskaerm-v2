from __future__ import annotations

from datetime import datetime, timezone
import base64
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine

from service1.clientflow_update_auth import (
    ClientFlowUpdateAuthError,
    UPDATE_ACCESS_TOKEN_AUDIENCE,
    UPDATE_ACCESS_TOKEN_ISSUER,
    UPDATE_ACCESS_TOKEN_TYP,
    UPDATE_CLIENT_ASSERTION_TYP,
    UPDATE_DPOP_TYP,
    UPDATE_TOKEN_AUDIENCE,
    authenticate_update_request,
    canonical_update_public_key,
    consume_provisioning_token,
    consume_replay,
    create_provisioning_token,
    create_update_credential,
    issue_update_access_token,
    normalize_scopes,
    utcnow,
    verify_client_assertion,
)
from service1.clientflow_update_models import ClientFlowUpdateCredential
from service1.models import Client, User


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _request(method: str, path: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("ascii"), value.encode("ascii")))
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "server": ("testserver", 443),
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
    })


def _key_material():
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    canonical, key_id, jwk, thumbprint = canonical_update_public_key(public_pem)
    return private, canonical, key_id, jwk, thumbprint


def _client_assertion(private, credential: ClientFlowUpdateCredential, key_id: str, *, jti: str | None = None):
    now = int(datetime.now(timezone.utc).timestamp())
    return jwt.encode(
        {
            "iss": credential.id,
            "sub": credential.id,
            "aud": UPDATE_TOKEN_AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": now + 60,
            "jti": jti or str(uuid.uuid4()),
        },
        private,
        algorithm="EdDSA",
        headers={"typ": UPDATE_CLIENT_ASSERTION_TYP, "kid": key_id},
    )


def _dpop(private, jwk, *, method: str, htu: str, access_token: str | None = None, jti: str | None = None):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"jti": jti or str(uuid.uuid4()), "htm": method, "htu": htu, "iat": now}
    if access_token is not None:
        import hashlib
        claims["ath"] = _b64url(hashlib.sha256(access_token.encode("ascii")).digest())
    return jwt.encode(
        claims,
        private,
        algorithm="EdDSA",
        headers={"typ": UPDATE_DPOP_TYP, "jwk": jwk},
    )


@pytest.fixture()
def auth_session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            username="update-auth-admin",
            email="update-auth-admin@example.invalid",
            hashed_password="hashed",
            role="superadmin",
            is_active=True,
            must_change_password=False,
        )
        client = Client(name="update-auth-client", status="approved")
        session.add(user)
        session.add(client)
        session.commit()
        session.refresh(user)
        session.refresh(client)
        yield session, client, user


def test_private_key_assertion_is_bound_to_stored_update_credential_and_replay_is_persistent(auth_session):
    session, client, _user = auth_session
    private, public_pem, key_id, _jwk, _thumbprint = _key_material()
    credential = create_update_credential(session, client_id=int(client.id), public_key_pem=public_pem)
    session.commit()

    assertion = _client_assertion(private, credential, key_id, jti="assertion-replay-test")
    verified, verified_client, jti, expires_at = verify_client_assertion(session, assertion=assertion)
    assert verified.id == credential.id
    assert verified_client.id == client.id
    consume_replay(session, credential_id=credential.id, kind="client_assertion", jti=jti, expires_at=expires_at)
    session.commit()

    with pytest.raises(ClientFlowUpdateAuthError, match="allerede brugt"):
        consume_replay(session, credential_id=credential.id, kind="client_assertion", jti=jti, expires_at=expires_at)
    session.rollback()


def test_dpop_access_token_has_distinct_type_audience_scope_and_ath_binding(auth_session):
    session, client, _user = auth_session
    private, public_pem, key_id, jwk, thumbprint = _key_material()
    credential = create_update_credential(session, client_id=int(client.id), public_key_pem=public_pem)
    session.commit()

    scopes = normalize_scopes("deployment:read deployment:report")
    access_token, _ttl = issue_update_access_token(
        credential=credential,
        client=client,
        scopes=scopes,
        dpop_thumbprint=thumbprint,
    )
    header = jwt.get_unverified_header(access_token)
    assert header["typ"] == UPDATE_ACCESS_TOKEN_TYP
    unverified = jwt.decode(access_token, options={"verify_signature": False})
    assert unverified["iss"] == UPDATE_ACCESS_TOKEN_ISSUER
    assert unverified["aud"] == UPDATE_ACCESS_TOKEN_AUDIENCE
    assert unverified["cnf"] == {"jkt": thumbprint}

    path = "/api/clientflow-update/deployments/active"
    htu = f"https://testserver{path}"
    proof = _dpop(private, jwk, method="GET", htu=htu, access_token=access_token)
    request = _request("GET", path, {"Authorization": f"DPoP {access_token}", "DPoP": proof})
    principal = authenticate_update_request(session, request=request, required_scope="deployment:read")
    assert principal.client.id == client.id
    assert principal.credential.id == credential.id

    bad_proof = _dpop(private, jwk, method="POST", htu=htu, access_token=access_token)
    bad_request = _request("GET", path, {"Authorization": f"DPoP {access_token}", "DPoP": bad_proof})
    with pytest.raises(ClientFlowUpdateAuthError, match="htm"):
        authenticate_update_request(session, request=bad_request, required_scope="deployment:read")
    session.rollback()


def test_provisioning_bootstrap_then_recovery_rotates_without_exporting_private_key(auth_session):
    session, client, user = auth_session
    private1, public1, key1, _jwk1, _jkt1 = _key_material()
    token1, code1 = create_provisioning_token(session, client=client, created_by_user_id=int(user.id))
    assert token1.purpose == "bootstrap"
    credential1, consumed1, _client = consume_provisioning_token(session, code=code1, public_key_pem=public1)
    session.commit()
    assert consumed1.used_at is not None
    assert credential1.key_id == key1

    _private2, public2, key2, _jwk2, _jkt2 = _key_material()
    token2, code2 = create_provisioning_token(session, client=client, created_by_user_id=int(user.id))
    assert token2.purpose == "recovery"
    credential2, consumed2, _client = consume_provisioning_token(session, code=code2, public_key_pem=public2)
    session.commit()
    session.refresh(credential1)
    assert consumed2.used_at is not None
    assert credential1.revoked_at is not None
    assert credential2.rotated_from_credential_id == credential1.id
    assert credential2.key_id == key2
    assert "PRIVATE KEY" not in credential2.public_key_pem

def test_recovery_after_explicit_revocation_keeps_credential_lineage(auth_session):
    session, client, user = auth_session
    _private1, public1, key1, _jwk1, _jkt1 = _key_material()
    credential1 = create_update_credential(session, client_id=int(client.id), public_key_pem=public1)
    session.commit()
    assert credential1.key_id == key1

    credential1.revoked_at = utcnow()
    session.add(credential1)
    session.commit()

    token, code = create_provisioning_token(session, client=client, created_by_user_id=int(user.id))
    assert token.purpose == "recovery"
    _private2, public2, key2, _jwk2, _jkt2 = _key_material()
    credential2, consumed, _client = consume_provisioning_token(session, code=code, public_key_pem=public2)
    session.commit()
    assert consumed.used_at is not None
    assert credential2.rotated_from_credential_id == credential1.id
    assert credential2.key_id == key2

