"""Authentication and credential lifecycle for the stable ClientFlow updater.

The updater has its own asymmetric Ed25519 identity.  This trust boundary is
intentionally disjoint from shared-domain credentials, Terminal/RD credentials,
and the system RSA-OAEP encryption key.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Iterable
import uuid

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from fastapi import HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import ALGORITHM as PLATFORM_JWT_ALGORITHM, SECRET_KEY
from .clientflow_update_models import (
    ClientFlowUpdateCredential,
    ClientFlowUpdateProvisioningToken,
    ClientFlowUpdateReplay,
)
from .models import Client

UPDATE_CREDENTIAL_ALGORITHM = "Ed25519"
UPDATE_CLIENT_ASSERTION_TYP = "clientflow-update-client-auth+jwt"
UPDATE_ACCESS_TOKEN_TYP = "clientflow-update-access+jwt"
UPDATE_DPOP_TYP = "dpop+jwt"
UPDATE_KEY_ROTATION_TYP = "clientflow-update-key-rotation+jwt"
UPDATE_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:token"
UPDATE_ACCESS_TOKEN_ISSUER = "planiq-clientflow-update"
UPDATE_ACCESS_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:resource"
UPDATE_ACCESS_TOKEN_TTL_SECONDS = 300
UPDATE_CLIENT_ASSERTION_MAX_SECONDS = 90
UPDATE_DPOP_MAX_AGE_SECONDS = 120
UPDATE_CLOCK_SKEW_SECONDS = 30
UPDATE_PROVISIONING_TTL_SECONDS = 600
UPDATE_SCOPES = frozenset({
    "deployment:read",
    "deployment:report",
    "artifact:authorize",
    "credential:rotate",
})
DEFAULT_UPDATE_SCOPES = frozenset({"deployment:read", "deployment:report"})


class ClientFlowUpdateAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdatePrincipal:
    client: Client
    credential: ClientFlowUpdateCredential
    scopes: frozenset[str]
    access_token: str
    dpop_thumbprint: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _public_key_material(public_key_pem: str) -> tuple[Ed25519PublicKey, str, str, dict[str, str], str]:
    try:
        raw_pem = str(public_key_pem or "").strip().encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise ClientFlowUpdateAuthError("Update public key er ugyldig") from exc
    if len(raw_pem) > 4096:
        raise ClientFlowUpdateAuthError("Update public key er for stor")
    try:
        key = load_pem_public_key(raw_pem)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ClientFlowUpdateAuthError("Update public key er ugyldig") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ClientFlowUpdateAuthError("Update public key skal være Ed25519")
    canonical_pem = key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = hashlib.sha256(der).hexdigest()[:32]
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}
    thumbprint_json = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": jwk["x"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    thumbprint = _b64url(hashlib.sha256(thumbprint_json).digest())
    return key, canonical_pem, key_id, jwk, thumbprint


def canonical_update_public_key(public_key_pem: str) -> tuple[str, str, dict[str, str], str]:
    _key, canonical_pem, key_id, jwk, thumbprint = _public_key_material(public_key_pem)
    return canonical_pem, key_id, jwk, thumbprint


def active_update_credential(
    session: Session,
    *,
    client_id: int,
    for_update: bool = False,
) -> ClientFlowUpdateCredential | None:
    statement = select(ClientFlowUpdateCredential).where(
        ClientFlowUpdateCredential.client_id == client_id,
        ClientFlowUpdateCredential.revoked_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def create_update_credential(
    session: Session,
    *,
    client_id: int,
    public_key_pem: str,
    rotated_from_credential_id: str | None = None,
) -> ClientFlowUpdateCredential:
    canonical_pem, key_id, _jwk, _thumbprint = canonical_update_public_key(public_key_pem)
    existing = active_update_credential(session, client_id=client_id, for_update=True)
    if existing is not None:
        raise ClientFlowUpdateAuthError("Klienten har allerede en aktiv update credential")
    row = ClientFlowUpdateCredential(
        id=str(uuid.uuid4()),
        client_id=client_id,
        key_id=key_id,
        public_key_pem=canonical_pem,
        algorithm=UPDATE_CREDENTIAL_ALGORITHM,
        created_at=utcnow(),
        rotated_from_credential_id=rotated_from_credential_id,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ClientFlowUpdateAuthError("Update credential kunne ikke oprettes entydigt") from exc
    return row


def require_update_client_active(session: Session, credential: ClientFlowUpdateCredential) -> Client:
    client = session.get(Client, credential.client_id)
    if (
        client is None
        or getattr(client, "deleted_at", None) is not None
        or str(getattr(client, "status", "")) != "approved"
        or credential.revoked_at is not None
    ):
        raise ClientFlowUpdateAuthError("Update credential er ikke aktiv for en godkendt klient")
    return client


def _require_jti(value: object) -> str:
    jti = str(value or "").strip()
    if not jti or len(jti) > 200:
        raise ClientFlowUpdateAuthError("JWT jti mangler eller er ugyldig")
    return jti


def _replay_hash(kind: str, jti: str) -> str:
    return hashlib.sha256(f"clientflow-update-replay-v1:{kind}:{jti}".encode("utf-8")).hexdigest()


def consume_replay(
    session: Session,
    *,
    credential_id: str,
    kind: str,
    jti: str,
    expires_at: datetime,
) -> None:
    now = utcnow()
    session.exec(delete(ClientFlowUpdateReplay).where(ClientFlowUpdateReplay.expires_at < now))
    row = ClientFlowUpdateReplay(
        id=str(uuid.uuid4()),
        credential_id=credential_id,
        kind=kind,
        jti_hash=_replay_hash(kind, _require_jti(jti)),
        created_at=now,
        expires_at=expires_at,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ClientFlowUpdateAuthError("JWT proof er allerede brugt") from exc


def _numeric_date(value: object, *, claim: str) -> int:
    if isinstance(value, bool):
        raise ClientFlowUpdateAuthError(f"JWT {claim} er ugyldig")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ClientFlowUpdateAuthError(f"JWT {claim} er ugyldig") from exc
    return result


def _request_htu(request: Request) -> str:
    url = request.url.replace(query="", fragment="")
    return str(url)


def verify_client_assertion(
    session: Session,
    *,
    assertion: str,
) -> tuple[ClientFlowUpdateCredential, Client, str, datetime]:
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Client assertion er ugyldig") from exc
    if header.get("typ") != UPDATE_CLIENT_ASSERTION_TYP or header.get("alg") != "EdDSA":
        raise ClientFlowUpdateAuthError("Client assertion har forkert JWT type/algoritme")
    if "jwk" in header or "jku" in header or "x5u" in header:
        raise ClientFlowUpdateAuthError("Client assertion må kun referere den provisionerede key via kid")
    key_id = str(header.get("kid") or "").strip()
    if not key_id or len(key_id) > 64:
        raise ClientFlowUpdateAuthError("Client assertion kid mangler eller er ugyldig")
    credential = session.exec(
        select(ClientFlowUpdateCredential).where(
            ClientFlowUpdateCredential.key_id == key_id,
            ClientFlowUpdateCredential.revoked_at.is_(None),
        )
    ).one_or_none()
    if credential is None or credential.algorithm != UPDATE_CREDENTIAL_ALGORITHM:
        raise ClientFlowUpdateAuthError("Update credential blev ikke fundet")
    client = require_update_client_active(session, credential)
    public_key, _pem, _kid, _jwk, _jkt = _public_key_material(credential.public_key_pem)
    try:
        claims = jwt.decode(
            assertion,
            public_key,
            algorithms=["EdDSA"],
            audience=UPDATE_TOKEN_AUDIENCE,
            issuer=credential.id,
            leeway=UPDATE_CLOCK_SKEW_SECONDS,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nbf", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Client assertion kunne ikke valideres") from exc
    if claims.get("sub") != credential.id:
        raise ClientFlowUpdateAuthError("Client assertion subject matcher ikke credential")
    iat = _numeric_date(claims.get("iat"), claim="iat")
    exp = _numeric_date(claims.get("exp"), claim="exp")
    if exp <= iat or exp - iat > UPDATE_CLIENT_ASSERTION_MAX_SECONDS:
        raise ClientFlowUpdateAuthError("Client assertion har for langt gyldighedsvindue")
    jti = _require_jti(claims.get("jti"))
    return credential, client, jti, datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)


def _decode_dpop_jwk(header: dict) -> tuple[Ed25519PublicKey, dict[str, str], str]:
    if header.get("typ") != UPDATE_DPOP_TYP or header.get("alg") != "EdDSA":
        raise ClientFlowUpdateAuthError("DPoP proof har forkert JWT type/algoritme")
    jwk = header.get("jwk")
    if not isinstance(jwk, dict):
        raise ClientFlowUpdateAuthError("DPoP proof mangler public JWK")
    if set(jwk) - {"kty", "crv", "x"} or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise ClientFlowUpdateAuthError("DPoP JWK er ugyldig")
    x = str(jwk.get("x") or "")
    try:
        raw = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
        key = Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise ClientFlowUpdateAuthError("DPoP JWK er ugyldig") from exc
    canonical = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}
    thumbprint_json = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": canonical["x"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return key, canonical, _b64url(hashlib.sha256(thumbprint_json).digest())


def verify_dpop_proof(
    session: Session,
    *,
    request: Request,
    proof: str,
    credential: ClientFlowUpdateCredential,
    access_token: str | None,
    expected_thumbprint: str | None = None,
) -> str:
    try:
        header = jwt.get_unverified_header(proof)
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("DPoP proof er ugyldig") from exc
    proof_key, proof_jwk, thumbprint = _decode_dpop_jwk(header)
    _stored_key, _pem, _key_id, stored_jwk, stored_thumbprint = _public_key_material(credential.public_key_pem)
    if proof_jwk != stored_jwk or thumbprint != stored_thumbprint:
        raise ClientFlowUpdateAuthError("DPoP proof bruger ikke den provisionerede update key")
    if expected_thumbprint is not None and thumbprint != expected_thumbprint:
        raise ClientFlowUpdateAuthError("DPoP proof matcher ikke access-token binding")
    try:
        claims = jwt.decode(
            proof,
            proof_key,
            algorithms=["EdDSA"],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_nbf": False,
                "require": ["jti", "htm", "htu", "iat"],
            },
        )
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("DPoP proof-signaturen er ugyldig") from exc
    if str(claims.get("htm") or "").upper() != request.method.upper():
        raise ClientFlowUpdateAuthError("DPoP htm matcher ikke request")
    if str(claims.get("htu") or "") != _request_htu(request):
        raise ClientFlowUpdateAuthError("DPoP htu matcher ikke request")
    iat = _numeric_date(claims.get("iat"), claim="iat")
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if iat > now_ts + UPDATE_CLOCK_SKEW_SECONDS or iat < now_ts - UPDATE_DPOP_MAX_AGE_SECONDS:
        raise ClientFlowUpdateAuthError("DPoP proof ligger uden for gyldighedsvinduet")
    if access_token is None:
        if "ath" in claims:
            raise ClientFlowUpdateAuthError("Token-endpoint DPoP proof må ikke indeholde ath")
    else:
        expected_ath = _b64url(hashlib.sha256(access_token.encode("ascii")).digest())
        if not secrets.compare_digest(str(claims.get("ath") or ""), expected_ath):
            raise ClientFlowUpdateAuthError("DPoP ath matcher ikke access-token")
    jti = _require_jti(claims.get("jti"))
    expires_at = datetime.fromtimestamp(iat + UPDATE_DPOP_MAX_AGE_SECONDS, tz=timezone.utc).replace(tzinfo=None)
    consume_replay(
        session,
        credential_id=credential.id,
        kind="dpop",
        jti=jti,
        expires_at=expires_at,
    )
    return thumbprint


def verify_new_key_proof(
    *,
    request: Request,
    proof: str,
    new_public_key_pem: str,
    current_credential_id: str,
) -> None:
    try:
        header = jwt.get_unverified_header(proof)
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Ny update-key proof er ugyldig") from exc
    if header.get("typ") != UPDATE_KEY_ROTATION_TYP or header.get("alg") != "EdDSA":
        raise ClientFlowUpdateAuthError("Ny update-key proof har forkert JWT type/algoritme")
    if "jwk" in header or "jku" in header or "x5u" in header:
        raise ClientFlowUpdateAuthError("Ny update-key proof må ikke levere alternativ key-reference")
    key, _pem, key_id, _jwk, _jkt = _public_key_material(new_public_key_pem)
    if str(header.get("kid") or "") != key_id:
        raise ClientFlowUpdateAuthError("Ny update-key proof kid matcher ikke public key")
    try:
        claims = jwt.decode(
            proof,
            key,
            algorithms=["EdDSA"],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_nbf": False,
                "require": ["jti", "htm", "htu", "iat", "current_credential_id"],
            },
        )
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Ny update-key proof-signatur er ugyldig") from exc
    if str(claims.get("current_credential_id") or "") != current_credential_id:
        raise ClientFlowUpdateAuthError("Ny update-key proof matcher ikke aktiv credential")
    if str(claims.get("htm") or "").upper() != request.method.upper():
        raise ClientFlowUpdateAuthError("Ny update-key proof htm matcher ikke request")
    if str(claims.get("htu") or "") != _request_htu(request):
        raise ClientFlowUpdateAuthError("Ny update-key proof htu matcher ikke request")
    iat = _numeric_date(claims.get("iat"), claim="iat")
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if iat > now_ts + UPDATE_CLOCK_SKEW_SECONDS or iat < now_ts - UPDATE_DPOP_MAX_AGE_SECONDS:
        raise ClientFlowUpdateAuthError("Ny update-key proof ligger uden for gyldighedsvinduet")
    _require_jti(claims.get("jti"))


def normalize_scopes(scope: str | Iterable[str] | None) -> frozenset[str]:
    if scope is None:
        return DEFAULT_UPDATE_SCOPES
    values = scope.split() if isinstance(scope, str) else list(scope)
    result = frozenset(str(item).strip() for item in values if str(item).strip())
    if not result:
        return DEFAULT_UPDATE_SCOPES
    unknown = result - UPDATE_SCOPES
    if unknown:
        raise ClientFlowUpdateAuthError(f"Ukendte update scopes: {sorted(unknown)}")
    return result


def _access_token_scopes(value: object) -> frozenset[str]:
    raw = str(value or "").strip()
    if not raw:
        raise ClientFlowUpdateAuthError("Update access-token mangler scopes")
    scopes = frozenset(item for item in raw.split() if item)
    unknown = scopes - UPDATE_SCOPES
    if unknown:
        raise ClientFlowUpdateAuthError(f"Update access-token har ukendte scopes: {sorted(unknown)}")
    return scopes


def issue_update_access_token(
    *,
    credential: ClientFlowUpdateCredential,
    client: Client,
    scopes: frozenset[str],
    dpop_thumbprint: str,
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=UPDATE_ACCESS_TOKEN_TTL_SECONDS)
    claims = {
        "iss": UPDATE_ACCESS_TOKEN_ISSUER,
        "sub": f"clientflow-update:{credential.id}",
        "aud": UPDATE_ACCESS_TOKEN_AUDIENCE,
        "principal": "clientflow-update",
        "client_id": int(client.id),
        "credential_id": credential.id,
        "key_id": credential.key_id,
        "scope": " ".join(sorted(scopes)),
        "cnf": {"jkt": dpop_thumbprint},
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        claims,
        SECRET_KEY,
        algorithm=PLATFORM_JWT_ALGORITHM,
        headers={"typ": UPDATE_ACCESS_TOKEN_TYP},
    )
    return token, UPDATE_ACCESS_TOKEN_TTL_SECONDS


def authenticate_update_request(
    session: Session,
    *,
    request: Request,
    required_scope: str,
) -> UpdatePrincipal:
    authorization = str(request.headers.get("authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "dpop" or not token:
        raise ClientFlowUpdateAuthError("Update endpoint kræver Authorization: DPoP")
    dpop = str(request.headers.get("dpop") or "").strip()
    if not dpop:
        raise ClientFlowUpdateAuthError("Update endpoint mangler DPoP proof")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Update access-token er ugyldigt") from exc
    if header.get("typ") != UPDATE_ACCESS_TOKEN_TYP or header.get("alg") != PLATFORM_JWT_ALGORITHM:
        raise ClientFlowUpdateAuthError("Update access-token har forkert JWT type/algoritme")
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[PLATFORM_JWT_ALGORITHM],
            audience=UPDATE_ACCESS_TOKEN_AUDIENCE,
            issuer=UPDATE_ACCESS_TOKEN_ISSUER,
            options={
                "require": [
                    "iss", "sub", "aud", "principal", "client_id", "credential_id",
                    "key_id", "scope", "cnf", "iat", "nbf", "exp", "jti",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise ClientFlowUpdateAuthError("Update access-token kunne ikke valideres") from exc
    if claims.get("principal") != "clientflow-update":
        raise ClientFlowUpdateAuthError("Update access-token har forkert principal")
    credential_id = str(claims.get("credential_id") or "")
    credential = session.get(ClientFlowUpdateCredential, credential_id)
    if credential is None or credential.revoked_at is not None:
        raise ClientFlowUpdateAuthError("Update credential er revoked eller mangler")
    client = require_update_client_active(session, credential)
    if int(claims.get("client_id") or 0) != int(client.id):
        raise ClientFlowUpdateAuthError("Update access-token client_id matcher ikke credential")
    if claims.get("sub") != f"clientflow-update:{credential.id}" or claims.get("key_id") != credential.key_id:
        raise ClientFlowUpdateAuthError("Update access-token identity matcher ikke credential")
    scopes = _access_token_scopes(claims.get("scope"))
    if required_scope not in scopes:
        raise ClientFlowUpdateAuthError(f"Update access-token mangler scope {required_scope}")
    cnf = claims.get("cnf")
    if not isinstance(cnf, dict) or not str(cnf.get("jkt") or ""):
        raise ClientFlowUpdateAuthError("Update access-token mangler DPoP binding")
    thumbprint = verify_dpop_proof(
        session,
        request=request,
        proof=dpop,
        credential=credential,
        access_token=token,
        expected_thumbprint=str(cnf["jkt"]),
    )
    credential.last_used_at = utcnow()
    session.add(credential)
    return UpdatePrincipal(
        client=client,
        credential=credential,
        scopes=scopes,
        access_token=token,
        dpop_thumbprint=thumbprint,
    )


def provisioning_code_hash(code: str) -> str:
    value = str(code or "").strip()
    return hashlib.sha256(f"clientflow-update-provision-v1:{value}".encode("utf-8")).hexdigest()


def create_provisioning_token(
    session: Session,
    *,
    client: Client,
    created_by_user_id: int | None,
) -> tuple[ClientFlowUpdateProvisioningToken, str]:
    now = utcnow()
    existing_tokens = session.exec(
        select(ClientFlowUpdateProvisioningToken).where(
            ClientFlowUpdateProvisioningToken.client_id == int(client.id),
            ClientFlowUpdateProvisioningToken.used_at.is_(None),
            ClientFlowUpdateProvisioningToken.revoked_at.is_(None),
        ).with_for_update()
    ).all()
    for old in existing_tokens:
        old.revoked_at = now
        session.add(old)
    # Serialize provisioning against credential rotation/recovery even though
    # this code path only needs the row-lock side effect, not the returned row.
    active_update_credential(session, client_id=int(client.id), for_update=True)
    has_credential_history = session.exec(
        select(ClientFlowUpdateCredential.id)
        .where(ClientFlowUpdateCredential.client_id == int(client.id))
        .limit(1)
    ).first() is not None
    purpose = "recovery" if has_credential_history else "bootstrap"
    code = "cfup_" + secrets.token_urlsafe(32)
    token = ClientFlowUpdateProvisioningToken(
        id=str(uuid.uuid4()),
        client_id=int(client.id),
        code_hash=provisioning_code_hash(code),
        purpose=purpose,
        created_by_user_id=created_by_user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=UPDATE_PROVISIONING_TTL_SECONDS),
    )
    session.add(token)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ClientFlowUpdateAuthError(
            "Klienten har allerede en aktiv update provisioning-kode"
        ) from exc
    return token, code


def consume_provisioning_token(
    session: Session,
    *,
    code: str,
    public_key_pem: str,
) -> tuple[ClientFlowUpdateCredential, ClientFlowUpdateProvisioningToken, Client]:
    now = utcnow()
    code_hash = provisioning_code_hash(code)
    token = session.exec(
        select(ClientFlowUpdateProvisioningToken)
        .where(ClientFlowUpdateProvisioningToken.code_hash == code_hash)
        .with_for_update()
    ).one_or_none()
    if (
        token is None
        or token.used_at is not None
        or token.revoked_at is not None
        or token.expires_at < now
    ):
        raise ClientFlowUpdateAuthError("Update provisioning-koden er ugyldig, brugt eller udløbet")
    client = session.get(Client, token.client_id)
    if client is None or getattr(client, "deleted_at", None) is not None or str(client.status) != "approved":
        raise ClientFlowUpdateAuthError("Update provisioning kræver en aktiv godkendt klient")
    old = active_update_credential(session, client_id=int(client.id), for_update=True)
    if token.purpose == "bootstrap" and old is not None:
        raise ClientFlowUpdateAuthError("Bootstrap-token kan ikke erstatte en eksisterende update credential")
    predecessor = old
    if predecessor is None and token.purpose == "recovery":
        predecessor = session.exec(
            select(ClientFlowUpdateCredential)
            .where(ClientFlowUpdateCredential.client_id == int(client.id))
            .order_by(ClientFlowUpdateCredential.created_at.desc())
            .limit(1)
        ).first()
    old_id = predecessor.id if predecessor is not None else None
    if old is not None:
        old.revoked_at = now
        session.add(old)
        session.flush()
    credential = create_update_credential(
        session,
        client_id=int(client.id),
        public_key_pem=public_key_pem,
        rotated_from_credential_id=old_id,
    )
    token.used_at = now
    session.add(token)
    return credential, token, client


def rotate_update_credential(
    session: Session,
    *,
    current: ClientFlowUpdateCredential,
    new_public_key_pem: str,
) -> ClientFlowUpdateCredential:
    now = utcnow()
    locked = session.exec(
        select(ClientFlowUpdateCredential)
        .where(ClientFlowUpdateCredential.id == current.id)
        .with_for_update()
    ).one_or_none()
    if locked is None or locked.revoked_at is not None:
        raise ClientFlowUpdateAuthError("Update credential er ikke længere aktiv")
    canonical_pem, key_id, _jwk, _thumbprint = canonical_update_public_key(new_public_key_pem)
    if key_id == locked.key_id:
        raise ClientFlowUpdateAuthError("Ny update key skal være forskellig fra den aktive key")
    locked.revoked_at = now
    session.add(locked)
    session.flush()
    successor = ClientFlowUpdateCredential(
        id=str(uuid.uuid4()),
        client_id=locked.client_id,
        key_id=key_id,
        public_key_pem=canonical_pem,
        algorithm=UPDATE_CREDENTIAL_ALGORITHM,
        created_at=now,
        rotated_from_credential_id=locked.id,
    )
    session.add(successor)
    session.flush()
    return successor


def http_auth_error(exc: ClientFlowUpdateAuthError, *, scheme: str = "DPoP") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=str(exc),
        headers={"WWW-Authenticate": scheme},
    )
