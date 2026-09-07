from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine

from service1.clientflow_artifact_auth import (
    ARTIFACT_ACCESS_TOKEN_AUDIENCE,
    ARTIFACT_ACCESS_TOKEN_TYP,
    ClientFlowArtifactAuthorizationError,
    authenticate_artifact_request,
    issue_artifact_access_token,
)
from service1.clientflow_deployments import create_authorized_deployment
from service1.clientflow_update_auth import (
    UPDATE_DPOP_TYP,
    UpdatePrincipal,
    canonical_update_public_key,
    create_update_credential,
)
from service1.models import Client


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _request(method: str, path: str, headers: dict[str, str]) -> Request:
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
        "headers": [(k.lower().encode("ascii"), v.encode("ascii")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
    })


def _dpop(private, jwk, *, method: str, htu: str, access_token: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    return jwt.encode(
        {
            "jti": str(uuid.uuid4()),
            "htm": method,
            "htu": htu,
            "iat": now,
            "ath": _b64url(hashlib.sha256(access_token.encode("ascii")).digest()),
        },
        private,
        algorithm="EdDSA",
        headers={"typ": UPDATE_DPOP_TYP, "jwk": jwk},
    )


def test_artifact_token_is_bound_to_exact_deployment_bytes_and_dpop():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        client = Client(name="artifact-client", status="approved")
        session.add(client)
        session.commit()
        session.refresh(client)

        private = Ed25519PrivateKey.generate()
        public_pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        canonical_pem, _key_id, jwk, thumbprint = canonical_update_public_key(public_pem)
        credential = create_update_credential(session, client_id=int(client.id), public_key_pem=canonical_pem)
        deployment = create_authorized_deployment(
            session,
            client_id=int(client.id),
            requested_by_user_id=None,
            target_release_id="clientflow-1.3.0-seq-1300",
            target_version="1.3.0",
            target_release_sequence=1300,
            bundle_sha256="a" * 64,
            bundle_size=12345,
            release_approval_reference="approval-1300",
            release_candidate_sha256="b" * 64,
            source_commit="c" * 40,
            allow_downgrade=False,
            reason=None,
        )
        session.commit()
        principal = UpdatePrincipal(
            client=client,
            credential=credential,
            scopes=frozenset({"artifact:authorize"}),
            access_token="upstream-update-token",
            dpop_thumbprint=thumbprint,
        )
        artifact_token, ttl = issue_artifact_access_token(principal=principal, deployment=deployment)
        assert ttl > 0
        assert jwt.get_unverified_header(artifact_token)["typ"] == ARTIFACT_ACCESS_TOKEN_TYP
        claims = jwt.decode(artifact_token, options={"verify_signature": False})
        assert claims["aud"] == ARTIFACT_ACCESS_TOKEN_AUDIENCE
        assert claims["deployment_id"] == deployment.id
        assert claims["release_id"] == deployment.target_release_id
        assert claims["bundle_sha256"] == deployment.bundle_sha256
        assert claims["bundle_size"] == deployment.bundle_size

        path = f"/api/clientflow/release-artifacts/{deployment.target_release_id}"
        proof = _dpop(
            private,
            jwk,
            method="GET",
            htu=f"https://testserver{path}",
            access_token=artifact_token,
        )
        request = _request("GET", path, {"Authorization": f"DPoP {artifact_token}", "DPoP": proof})
        verified = authenticate_artifact_request(
            session,
            request=request,
            release_id=deployment.target_release_id,
        )
        assert verified.client_id == client.id
        assert verified.deployment.id == deployment.id


def test_artifact_authorization_stops_at_activation_boundary():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        client = Client(name="artifact-client-activation", status="approved")
        session.add(client)
        session.commit()
        session.refresh(client)
        private = Ed25519PrivateKey.generate()
        public_pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        canonical_pem, _key_id, _jwk, thumbprint = canonical_update_public_key(public_pem)
        credential = create_update_credential(session, client_id=int(client.id), public_key_pem=canonical_pem)
        deployment = create_authorized_deployment(
            session,
            client_id=int(client.id),
            requested_by_user_id=None,
            target_release_id="clientflow-1.3.0-seq-1300",
            target_version="1.3.0",
            target_release_sequence=1300,
            bundle_sha256="a" * 64,
            bundle_size=12345,
            release_approval_reference="approval-1300",
            allow_downgrade=False,
            reason=None,
        )
        deployment.state = "activating"
        session.add(deployment)
        session.commit()
        principal = UpdatePrincipal(
            client=client,
            credential=credential,
            scopes=frozenset({"artifact:authorize"}),
            access_token="upstream-update-token",
            dpop_thumbprint=thumbprint,
        )
        with pytest.raises(ClientFlowArtifactAuthorizationError, match="før deploymentens activation-start"):
            issue_artifact_access_token(principal=principal, deployment=deployment)
