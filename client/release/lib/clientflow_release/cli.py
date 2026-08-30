from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import stat
import secrets
import subprocess
import sys
import uuid

from .bundle import verify_bundle
from .constants import DOMAIN_NAMES, INSTALL_MODE_FRESH, MAX_BUNDLE_BYTES
from .crypto import sha256_file
from .enrollment import (
    EnrollmentHTTPError,
    claim,
    complete,
    generate_system_key,
    persist_enrollment,
    prove_client_approval,
    validate_backend_url,
    validate_fresh_install_binding,
)
from .update_auth import generate_update_key, public_material as update_public_material
from .filesystem import atomic_write_bytes, atomic_write_json, ensure_real_directory, load_secure_json
from .transaction import (
    Layout,
    activate_release,
    install_stable_updater_host,
    install_staged_definitions,
    rollback_release,
    stage_bundle,
    status,
)
from .wipe import wipe

INSTALL_STATE_SCHEMA = 2


def _layout(value: str | None) -> Layout:
    return Layout(Path(value).resolve()) if value else Layout()


def _require_root(layout: Layout) -> None:
    if layout.root == Path("/") and os.geteuid() != 0:
        raise RuntimeError("ClientFlow-installation kræver root")


def _install_state_path(layout: Layout) -> Path:
    return layout.path("/var/lib/clientflow/release/install-state.json")


def _fresh_conflicts(layout: Layout) -> list[str]:
    conflicts: list[str] = []
    for absolute in (
        "/opt/clientflow",
        "/etc/clientflow",
        "/var/lib/clientflow",
        "/usr/lib/clientflow",
        "/usr/lib/sysusers.d/clientflow.conf",
        "/usr/lib/tmpfiles.d/clientflow.conf",
    ):
        if layout.path(absolute).exists() or layout.path(absolute).is_symlink():
            conflicts.append(absolute)
    unit_root = layout.path("/etc/systemd/system")
    if unit_root.is_dir() and not unit_root.is_symlink():
        for path in sorted(unit_root.glob("clientflow*")):
            conflicts.append(f"unit:{path.name}")
    sudoers_root = layout.path("/etc/sudoers.d")
    if sudoers_root.is_dir() and not sudoers_root.is_symlink():
        for path in sorted(sudoers_root.glob("clientflow*")):
            conflicts.append(f"sudoers:{path.name}")
    if layout.root == Path("/"):
        accounts = (
            "clientflow",
            "clientflow-status",
            "clientflow-display-agent",
            "clientflow-display",
            "clientflow-livestream-agent",
            "clientflow-livestream-runtime",
            "clientflow-livestream-uploader",
            "clientflow-remote-desktop-agent",
            "clientflow-terminal-agent",
            "clientflow-terminal-session",
            "clientflow-system-agent",
            "clientflow-updater",
            "cfadmin",
        )
        for user in accounts:
            try:
                pwd.getpwnam(user)
                conflicts.append(f"user:{user}")
            except KeyError:
                pass
        groups = (*accounts, "clientflow-display-control", "clientflow-livestream-control")
        for group in groups:
            try:
                grp.getgrnam(group)
                conflicts.append(f"group:{group}")
            except KeyError:
                pass
    return sorted(set(conflicts))


def _ensure_cfadmin_account(layout: Layout) -> None:
    """Create the non-root local management account after committed claim.

    The account starts password-locked and receives no sudo/adm/root membership.
    Privileged support remains isolated in the canonical Root Terminal domain.
    """
    if layout.root != Path("/"):
        return
    try:
        pwd.getpwnam("cfadmin")
    except KeyError:
        subprocess.run(
            [
                "/usr/sbin/useradd",
                "--create-home",
                "--user-group",
                "--shell",
                "/bin/bash",
                "--password",
                "!",
                "cfadmin",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    account = pwd.getpwnam("cfadmin")
    primary_group = grp.getgrgid(account.pw_gid).gr_name
    group_names = {grp.getgrgid(gid).gr_name for gid in os.getgrouplist("cfadmin", account.pw_gid)}
    if (
        account.pw_uid == 0
        or account.pw_dir != "/home/cfadmin"
        or account.pw_shell != "/bin/bash"
        or primary_group != "cfadmin"
        or group_names.intersection({"root", "sudo", "adm"})
    ):
        raise RuntimeError("cfadmin matcher ikke canonical local-management account contract")


def _cleanup_new_install_preclaim_state(layout: Layout, *, install_id: str) -> None:
    # _fresh_conflicts() proves these roots did not exist before a brand-new
    # transaction. Verify ownership of the still-uncommitted local transaction
    # before deleting anything, so concurrent or externally replaced state is
    # never mistaken for cleanup material.
    state_path = _install_state_path(layout)
    state = load_secure_json(state_path)
    if str(state.get("install_id") or "") != str(install_id):
        raise RuntimeError("Pre-claim cleanup afviste install-state fra en anden transaction")
    for absolute in ("/etc/clientflow", "/var/lib/clientflow"):
        path = layout.path(absolute)
        if path.is_symlink():
            raise RuntimeError(f"Pre-claim cleanup afviste symlink: {path}")
        if path.exists():
            shutil.rmtree(path)


def _prepare_claim_ca(layout: Layout, ca_file: Path | None, *, new_install: bool) -> str | None:
    target = layout.path("/etc/clientflow/tls/ca.pem")
    if ca_file is not None:
        source = ca_file.resolve()
        raw = _secure_regular_file(source, max_bytes=1024 * 1024, secret=False)
        if b"BEGIN CERTIFICATE" not in raw:
            raise RuntimeError("CA-filen indeholder ikke et PEM-certifikat")
        if target.exists() or target.is_symlink():
            existing = _secure_regular_file(target, max_bytes=1024 * 1024, secret=False)
            if new_install:
                raise RuntimeError("Fresh install CA-target opstod efter clean-state preflight")
            if existing != raw:
                raise RuntimeError("Resume kræver samme gemte CA-fil som den oprindelige installation")
        atomic_write_bytes(target, raw, mode=0o644)
        return "/etc/clientflow/tls/ca.pem"
    if not target.exists() and not target.is_symlink():
        return None
    raw = _secure_regular_file(target, max_bytes=1024 * 1024, secret=False)
    if b"BEGIN CERTIFICATE" not in raw:
        raise RuntimeError("Den gemte CA-fil indeholder ikke et PEM-certifikat")
    return "/etc/clientflow/tls/ca.pem"


def _secure_regular_file(path: Path, *, max_bytes: int = 1024 * 1024, secret: bool = True) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Påkrævet installationsfil mangler: {path}") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"Installationsfil er ikke en almindelig fil: {path}")
    forbidden = 0o077 if secret else 0o022
    if metadata.st_mode & forbidden:
        raise RuntimeError(f"Installationsfil har for brede rettigheder: {path}")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise RuntimeError(f"Installationsfil har ugyldig størrelse: {path}")
    return path.read_bytes()


def _secure_json(path: Path, *, secret: bool = True) -> dict:
    raw = _secure_regular_file(path, secret=secret)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Installationsfil er ikke gyldig JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Installationsfil skal være et JSON-objekt: {path}")
    return value


def _validate_kiosk_user(name: str, layout: Layout) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name or ""):
        raise RuntimeError("kiosk-user er ugyldig")
    if name == "root" or name.startswith("clientflow"):
        raise RuntimeError("kiosk-user må ikke være root eller en ClientFlow-systembruger")
    if layout.root == Path("/"):
        try:
            account = pwd.getpwnam(name)
        except KeyError as exc:
            raise RuntimeError("kiosk-user findes ikke på systemet") from exc
        if account.pw_uid < 1000 or account.pw_uid == 0:
            raise RuntimeError("kiosk-user skal være en normal interaktiv ikke-systembruger")
    return name


def _all_credentials_present(layout: Layout) -> bool:
    etc = layout.path("/etc/clientflow")
    try:
        identity = _secure_json(etc / "identity.json")
        client_id = int(identity["client_id"])
        terminal_credential_id = str(uuid.UUID(str(identity["terminal_credential_id"])))
        kiosk_user = _validate_kiosk_user(str(identity["kiosk_user"]), layout)
        credential_ids: set[str] = set()
        for domain in DOMAIN_NAMES:
            row = _secure_json(etc / "credentials" / f"{domain}.json")
            if row.get("schema_version") != 1 or row.get("domain") != domain or int(row.get("client_id", 0)) != client_id:
                raise RuntimeError(f"Credentialkontrakten er ugyldig for {domain}")
            credential_id = str(uuid.UUID(str(row["credential_id"])))
            if credential_id in credential_ids:
                raise RuntimeError("Credential-ID'er skal være unikke")
            credential_ids.add(credential_id)
            secret = str(row.get("client_secret") or "")
            if not secret.startswith(f"cf_{domain}_") or len(secret) < 40:
                raise RuntimeError(f"Credential-secret er ugyldig for {domain}")
        terminal_row = _secure_json(etc / "credentials/terminal.json")
        if terminal_credential_id != str(terminal_row["credential_id"]):
            raise RuntimeError("Identity matcher ikke terminalcredential")
        root_grant = _secure_json(etc / "root-terminal/root-grant.json")
        if root_grant.get("schema_version") != 1 or not root_grant.get("verification_key_b64"):
            raise RuntimeError("Root-grant-konfiguration er ugyldig")
        _secure_regular_file(etc / "system-private-key.pem")
        _secure_regular_file(etc / "system-public-key.pem", secret=False)
        update_private_key = etc / "update/private-key.pem"
        _secure_regular_file(update_private_key)
        update_credential = _secure_json(etc / "update/credential.json")
        update_tls_ca = _secure_regular_file(etc / "update/tls-ca.pem")
        if (
            update_credential.get("schema_version") != 1
            or int(update_credential.get("client_id", 0)) != client_id
            or update_credential.get("algorithm") != "Ed25519"
            or not update_credential.get("credential_id")
            or not update_credential.get("key_id")
            or not update_credential.get("token_audience")
            or not update_credential.get("access_token_issuer")
            or not update_credential.get("access_token_audience")
        ):
            raise RuntimeError("Update-auth credentialkontrakten er ugyldig")
        _update_public_pem, local_update_key_id, _update_jwk, _update_jkt = update_public_material(update_private_key)
        if local_update_key_id != str(update_credential.get("key_id")):
            raise RuntimeError("Update-auth credential matcher ikke lokal private key")
        if update_credential.get("tls_ca_file") and b"BEGIN CERTIFICATE" not in update_tls_ca:
            raise RuntimeError("Update-auth custom CA credential er ugyldig")
        _secure_json(etc / "livestream.json")
        remote_desktop = _secure_json(etc / "remote-desktop.json")
        if remote_desktop != {
            "schema_version": 1,
            "capture_backend": "mutter-pipewire",
            "kiosk_user": kiosk_user,
        }:
            raise RuntimeError("Remote Desktop fresh-install konfiguration er ugyldig")
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False
    return True


def _copy_install_configuration(
    layout: Layout,
    release_id: str,
    *,
    ca_file: Path | None,
    kiosk_user: str,
) -> str | None:
    etc = layout.path("/etc/clientflow")
    release_root = layout.releases / release_id
    livestream_destination = etc / "livestream.json"
    if not livestream_destination.exists():
        livestream_source = release_root / "client-runtime/config-examples/livestream.json"
        _secure_regular_file(livestream_source, secret=False)
        atomic_write_bytes(livestream_destination, livestream_source.read_bytes(), mode=0o600)

    remote_source = release_root / "client-runtime/config-examples/remote-desktop.json"
    remote_template = _secure_json(remote_source, secret=False)
    expected_remote = {
        "schema_version": 1,
        "capture_backend": "mutter-pipewire",
        "kiosk_user": kiosk_user,
    }
    if remote_template != {"schema_version": 1, "capture_backend": "mutter-pipewire"}:
        raise RuntimeError("Releasepayloadens Remote Desktop template er ikke generic Wayland/Mutter")
    remote_destination = etc / "remote-desktop.json"
    if remote_destination.exists() or remote_destination.is_symlink():
        if _secure_json(remote_destination) != expected_remote:
            raise RuntimeError("Resume kræver samme materialiserede Remote Desktop-konfiguration")
    else:
        atomic_write_json(remote_destination, expected_remote, mode=0o600)
    target = etc / "tls/ca.pem"
    if ca_file is None:
        if not target.exists() and not target.is_symlink():
            return None
        raw = _secure_regular_file(target, max_bytes=1024 * 1024, secret=False)
        if b"BEGIN CERTIFICATE" not in raw:
            raise RuntimeError("Den gemte CA-fil indeholder ikke et PEM-certifikat")
        return "/etc/clientflow/tls/ca.pem"
    source = ca_file.resolve()
    raw = _secure_regular_file(source, max_bytes=1024 * 1024, secret=False)
    if b"BEGIN CERTIFICATE" not in raw:
        raise RuntimeError("CA-filen indeholder ikke et PEM-certifikat")
    atomic_write_bytes(target, raw, mode=0o644)
    return "/etc/clientflow/tls/ca.pem"


def _persist_updater_tls_ca(layout: Layout, stored_ca_path: str | None) -> None:
    destination = layout.path("/etc/clientflow/update/tls-ca.pem")
    if stored_ca_path:
        raw = _secure_regular_file(layout.path(stored_ca_path), max_bytes=1024 * 1024, secret=False)
        if b"BEGIN CERTIFICATE" not in raw:
            raise RuntimeError("Updaterens custom CA indeholder ikke et PEM-certifikat")
    else:
        raw = b"# ClientFlow updater uses the system trust store.\n"
    atomic_write_bytes(destination, raw, mode=0o600)


def _validate_stable_updater_install(layout: Layout, release_id: str) -> None:
    source = layout.releases / release_id / "release/updater/clientflow-updater.pyz"
    installed = layout.stable_updater_pyz
    try:
        source_meta = source.lstat()
        installed_meta = installed.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("Stable updater-host mangler efter installation") from exc
    if (
        source.is_symlink()
        or installed.is_symlink()
        or not stat.S_ISREG(source_meta.st_mode)
        or not stat.S_ISREG(installed_meta.st_mode)
    ):
        raise RuntimeError("Stable updater-host er ikke en almindelig fil")
    if stat.S_IMODE(installed_meta.st_mode) != 0o555:
        raise RuntimeError("Stable updater-host har forkert filmode")
    source_size, source_sha256 = sha256_file(source)
    installed_size, installed_sha256 = sha256_file(installed)
    if (source_size, source_sha256) != (installed_size, installed_sha256):
        raise RuntimeError("Stable updater-host matcher ikke staged release")
    if layout.root == Path("/"):
        if installed_meta.st_uid != 0 or installed_meta.st_gid != 0:
            raise RuntimeError("Stable updater-host er ikke root-owned")
        try:
            account = pwd.getpwnam("clientflow-updater")
        except KeyError as exc:
            raise RuntimeError("clientflow-updater systembruger mangler") from exc
        if account.pw_uid == 0:
            raise RuntimeError("clientflow-updater må ikke være root")
        enabled = subprocess.run(
            ["/usr/bin/systemctl", "is-enabled", "--quiet", "clientflow-updater.timer"],
            check=False,
        )
        active = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", "clientflow-updater.timer"],
            check=False,
        )
        if enabled.returncode != 0 or active.returncode != 0:
            raise RuntimeError("Stable updater-timer er ikke enabled og aktiv")


def _prove_backend_client_approved(layout: Layout) -> None:
    credential = _secure_json(layout.path("/etc/clientflow/credentials/status.json"))
    if credential.get("schema_version") != 1 or credential.get("domain") != "status":
        raise RuntimeError("Status credential kan ikke bruges som backend approval-proof")
    ca_file = None
    stored_ca = str(credential.get("tls_ca_file") or "").strip()
    if stored_ca:
        if not stored_ca.startswith("/"):
            raise RuntimeError("Status credential har ugyldig CA-path")
        ca_file = layout.path(stored_ca)
        raw = _secure_regular_file(ca_file, max_bytes=1024 * 1024, secret=False)
        if b"BEGIN CERTIFICATE" not in raw:
            raise RuntimeError("Status credential CA er ugyldig")
    prove_client_approval(
        backend_url=str(credential.get("backend_url") or ""),
        client_id=int(credential.get("client_id") or 0),
        credential_id=str(credential.get("credential_id") or ""),
        client_secret=str(credential.get("client_secret") or ""),
        token_issuer=str(credential.get("token_issuer") or ""),
        ca_file=ca_file,
    )


def _validate_inactive_install(layout: Layout, release_id: str) -> None:
    state = status(layout)
    if release_id not in state.get("installed", {}):
        raise RuntimeError("Staged release mangler efter installation")
    if layout.active.exists() or layout.active.is_symlink():
        raise RuntimeError("Fresh install må ikke have active-symlink før manuel aktivering")
    if not _all_credentials_present(layout):
        raise RuntimeError("Fresh install mangler credentials eller identity")
    _validate_stable_updater_install(layout, release_id)
    if layout.root == Path("/"):
        active = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", "clientflow.target"],
            check=False,
        )
        if active.returncode == 0:
            raise RuntimeError("clientflow.target må ikke være aktiv før manuel godkendelse")


def _verify_expected_bundle_identity(bundle: Path, expected_sha256: str) -> tuple[int, str]:
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("expected_bundle_sha256 skal være præcis SHA-256")
    try:
        size, actual = sha256_file(bundle, max_bytes=MAX_BUNDLE_BYTES)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Releasebundlen kunne ikke hashes sikkert: {exc}") from exc
    if actual != expected:
        raise RuntimeError("Releasebundlens SHA-256 matcher ikke den eksplicit forventede hash")
    return size, actual


def _verify_expected_bundle_hash(bundle: Path, expected_sha256: str) -> str:
    return _verify_expected_bundle_identity(bundle, expected_sha256)[1]


def _fresh_install_binding(manifest: dict, *, bundle_size: int, bundle_sha256: str) -> dict:
    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    return validate_fresh_install_binding(
        {
            "release_id": manifest.get("release_id"),
            "version": manifest.get("version"),
            "release_sequence": manifest.get("release_sequence"),
            "bundle_sha256": bundle_sha256,
            "bundle_size": bundle_size,
            "release_approval_reference": approval.get("reference"),
            "release_candidate_sha256": approval.get("candidate_sha256"),
            "source_commit": source.get("commit"),
        }
    )


def _state_fresh_install_binding(install_state: dict) -> dict:
    try:
        binding = install_state["fresh_install_binding"]
    except KeyError as exc:
        raise RuntimeError(
            "Uafsluttet installation mangler canonical fresh-install release-binding"
        ) from exc
    try:
        return validate_fresh_install_binding(binding)
    except Exception as exc:
        raise RuntimeError("Uafsluttet installation har ugyldig fresh-install release-binding") from exc


MAX_FRESH_INSTALL_AUTHORITY_STDIN_BYTES = 64 * 1024


def _fresh_install_authorities(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Read one-time fresh-install authorities without putting secrets in argv.

    A brand-new install uses exactly two newline-delimited values on stdin:
    enrollment code, then signed fresh-install authorization. Receipt resume
    omits the flag and therefore consumes no stdin and requires no one-time
    authority.
    """
    if not bool(getattr(args, "fresh_install_authority_stdin", False)):
        # Programmatic callers may provide authorities directly; the canonical
        # CLI parser deliberately exposes no secret-bearing argv options.
        return (
            getattr(args, "enrollment_code", None),
            getattr(args, "fresh_install_authorization", None),
        )
    raw = sys.stdin.buffer.read(MAX_FRESH_INSTALL_AUTHORITY_STDIN_BYTES + 1)
    if len(raw) > MAX_FRESH_INSTALL_AUTHORITY_STDIN_BYTES:
        raise RuntimeError("Fresh-install authority input er for stor")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Fresh-install authority input er ikke UTF-8") from exc
    lines = text.splitlines()
    if len(lines) != 2:
        raise RuntimeError("Fresh-install authority input skal indeholde præcis to linjer")
    enrollment_code, fresh_install_authorization = (line.strip() for line in lines)
    if not enrollment_code:
        raise RuntimeError("Ny fresh install kræver en one-time enrollment code")
    if not fresh_install_authorization:
        raise RuntimeError("Ny fresh install kræver fresh-install authorization")
    return enrollment_code, fresh_install_authorization


def install_fresh(args: argparse.Namespace) -> dict:
    layout = _layout(args.root)
    _require_root(layout)
    kiosk_user = _validate_kiosk_user(args.kiosk_user, layout)
    backend_url = validate_backend_url(args.backend_url)
    bundle_size, approved_bundle_sha256 = _verify_expected_bundle_identity(
        args.bundle, args.expected_bundle_sha256
    )
    manifest, _bundle_size, _bundle_sha256 = verify_bundle(
        args.bundle, require_deployable=True, required_install_mode=INSTALL_MODE_FRESH
    )
    binding = _fresh_install_binding(
        manifest,
        bundle_size=bundle_size,
        bundle_sha256=approved_bundle_sha256,
    )
    release_id = str(binding["release_id"])
    state_path = _install_state_path(layout)
    new_install = not state_path.exists()
    enrollment_code, fresh_install_authorization = _fresh_install_authorities(args)

    if not new_install:
        install_state = load_secure_json(state_path)
        if install_state.get("schema_version") != INSTALL_STATE_SCHEMA:
            raise RuntimeError(
                "Uafsluttet ClientFlow-installation bruger et ældre ubundet install-state schema; "
                "den kan ikke resumes sikkert af denne installer"
            )
        state_binding = _state_fresh_install_binding(install_state)
        if state_binding != binding:
            raise RuntimeError("Resume kræver præcis samme godkendte fresh-install release-binding")
        if install_state.get("backend_url") != backend_url or install_state.get("kiosk_user") != kiosk_user:
            raise RuntimeError("Resume kræver samme backend_url og kiosk-user som den oprindelige installation")
        if install_state.get("status") == "pending_manual_activation":
            install_stable_updater_host(release_id, layout=layout)
            _validate_inactive_install(layout, release_id)
            return {
                "status": "pending_manual_activation",
                "release_id": release_id,
                "next_command": f"clientflow-installer activate --release-id {release_id} --expected-release-approval-reference <release-approval-reference>",
                "automatic_reboot": False,
            }
    else:
        # A brand-new consuming transaction must have both one-time authorities
        # before any ClientFlow filesystem state is created. They are never
        # persisted locally; only the non-secret verified release binding is.
        if not enrollment_code:
            raise RuntimeError("Ny fresh install kræver en one-time enrollment code via stdin")
        if not fresh_install_authorization:
            raise RuntimeError("Ny fresh install kræver fresh-install authorization via stdin")
        conflicts = _fresh_conflicts(layout)
        if conflicts:
            raise RuntimeError(
                "Fresh install afviste eksisterende ClientFlow-spor: " + ", ".join(conflicts)
                + ". Brug den separate eksplicitte wipe-procedure."
            )
        ensure_real_directory(layout.state_root, mode=0o700)
        seed = secrets.token_bytes(32)
        install_state = {
            "schema_version": INSTALL_STATE_SCHEMA,
            "fresh_install_binding": binding,
            "install_id": str(uuid.uuid4()),
            "credential_seed_b64": base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii"),
            "backend_url": backend_url,
            "kiosk_user": kiosk_user,
            "status": "initialized",
        }
        atomic_write_json(state_path, install_state, mode=0o600)

    seed_text = str(install_state["credential_seed_b64"])
    seed = base64.urlsafe_b64decode(seed_text + "=" * (-len(seed_text) % 4))
    install_id = str(install_state["install_id"])
    etc_root = layout.path("/etc/clientflow")

    # Only minimal crash-resume material may exist before the consuming claim:
    # install-id/seed, optional pinned CA, and the exact system/update key pair
    # whose public material is committed by the receipt. Staged release files,
    # managed definitions, sysusers and tmpfiles are deliberately deferred until
    # after the backend trust gate succeeds.
    try:
        ensure_real_directory(etc_root, mode=0o750)
        stored_ca_path = _prepare_claim_ca(layout, args.ca_file, new_install=new_install)
        request_ca_file = layout.path(stored_ca_path) if stored_ca_path else None

        private_key = etc_root / "system-private-key.pem"
        if not private_key.exists():
            public_key_pem, _key_id = generate_system_key(private_key)
            atomic_write_bytes(etc_root / "system-public-key.pem", public_key_pem.encode("ascii"), mode=0o644)
        else:
            public_key_pem = (etc_root / "system-public-key.pem").read_text(encoding="ascii")

        update_private_key = etc_root / "update/private-key.pem"
        if not update_private_key.exists():
            update_public_key_pem, _update_key_id, _update_jwk, _update_jkt = generate_update_key(update_private_key)
        else:
            update_public_key_pem, _update_key_id, _update_jwk, _update_jkt = update_public_material(update_private_key)
    except Exception:
        if new_install:
            _cleanup_new_install_preclaim_state(layout, install_id=install_id)
        raise

    if not _all_credentials_present(layout):
        try:
            response = claim(
                backend_url=backend_url,
                enrollment_code=enrollment_code,
                fresh_install_authorization=fresh_install_authorization,
                fresh_install_binding=binding,
                install_id=install_id,
                seed=seed,
                public_key_pem=public_key_pem,
                update_auth_public_key_pem=update_public_key_pem,
                name=args.name,
                locality=args.locality,
                ca_file=request_ca_file,
            )
        except EnrollmentHTTPError as exc:
            # A definite 4xx response from the first claim is a fail-closed,
            # pre-commit rejection. Restore the original clean-machine state so
            # an authorization/release mismatch cannot strand partial local state.
            # 5xx/transport/invalid-response failures remain resumable because
            # the backend may already have committed the receipt.
            if new_install and 400 <= exc.status_code < 500:
                _cleanup_new_install_preclaim_state(layout, install_id=install_id)
            raise

        stage_bundle(
            args.bundle,
            release_id=release_id,
            expected_bundle_sha256=approved_bundle_sha256,
            install_mode=INSTALL_MODE_FRESH,
            layout=layout,
        )
        install_staged_definitions(release_id, layout=layout, kiosk_user=kiosk_user, client_id=int(response["client_id"]))
        _ensure_cfadmin_account(layout)
        stored_ca_path = _copy_install_configuration(layout, release_id, ca_file=None, kiosk_user=kiosk_user)
        request_ca_file = layout.path(stored_ca_path) if stored_ca_path else None
        _persist_updater_tls_ca(layout, stored_ca_path)
        install_state["status"] = "staged_inactive"
        atomic_write_json(state_path, install_state, mode=0o600)

        persist_enrollment(
            response,
            seed=seed,
            backend_url=backend_url,
            kiosk_user=kiosk_user,
            etc_root=etc_root,
            private_key=private_key,
            update_private_key=update_private_key,
            tls_ca_file=stored_ca_path,
        )
        install_state["status"] = "credentials_persisted"
        atomic_write_json(state_path, install_state, mode=0o600)
    else:
        # A resumed transaction with already-persisted credentials must already
        # have its exact release staged and definitions materialized. Validation
        # below fails closed if that durable post-claim state is incomplete.
        stored_ca_path = _copy_install_configuration(layout, release_id, ca_file=None, kiosk_user=kiosk_user)
        request_ca_file = layout.path(stored_ca_path) if stored_ca_path else None
        _persist_updater_tls_ca(layout, stored_ca_path)

    if install_state.get("status") != "enrollment_completed":
        complete(
            backend_url=backend_url,
            install_id=install_id,
            seed=seed,
            fresh_install_binding=binding,
            ca_file=request_ca_file,
        )
        install_state["status"] = "enrollment_completed"
        atomic_write_json(state_path, install_state, mode=0o600)

    install_stable_updater_host(release_id, layout=layout)
    _validate_inactive_install(layout, release_id)
    final_state = {
        "schema_version": INSTALL_STATE_SCHEMA,
        "fresh_install_binding": binding,
        "install_id": install_id,
        "backend_url": backend_url,
        "kiosk_user": kiosk_user,
        "status": "pending_manual_activation",
    }
    atomic_write_json(state_path, final_state, mode=0o600)
    return {
        "status": "pending_manual_activation",
        "release_id": release_id,
        "next_command": f"clientflow-installer activate --release-id {release_id} --expected-release-approval-reference <release-approval-reference>",
        "automatic_reboot": False,
    }

def _common_transaction_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ClientFlow trusted runtime-release installer")
    sub = parser.add_subparsers(dest="operation", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--expected-bundle-sha256", required=True)
    install = sub.add_parser("install")
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--expected-bundle-sha256", required=True)
    install.add_argument("--backend-url", required=True)
    # A new consuming claim reads the two one-time authorities from stdin so
    # sudo/audit process argv never persists them. Receipt resume omits this
    # flag and therefore requires no consumed/expired one-time authority.
    install.add_argument("--fresh-install-authority-stdin", action="store_true")
    install.add_argument("--kiosk-user", required=True)
    install.add_argument("--name")
    install.add_argument("--locality")
    install.add_argument("--ca-file", type=Path)
    _common_transaction_parser(install)
    activate = sub.add_parser("activate")
    activate.add_argument("--release-id", required=True)
    activate.add_argument("--expected-release-approval-reference", required=True)
    _common_transaction_parser(activate)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--release-id")
    rollback.add_argument("--expected-release-approval-reference", required=True)
    rollback.add_argument("--reason", required=True)
    _common_transaction_parser(rollback)
    status_parser = sub.add_parser("status")
    _common_transaction_parser(status_parser)
    wipe_parser = sub.add_parser("wipe")
    wipe_parser.add_argument("--reason", required=True)
    wipe_parser.add_argument("--confirm", required=True)
    _common_transaction_parser(wipe_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.operation == "verify":
        bundle_sha256 = _verify_expected_bundle_hash(args.bundle, args.expected_bundle_sha256)
        manifest, _bundle_size, _bundle_sha256 = verify_bundle(
            args.bundle, require_deployable=True, required_install_mode=INSTALL_MODE_FRESH
        )
        result = {
            "status": "verified",
            "release_id": manifest["release_id"],
            "bundle_sha256": bundle_sha256,
        }
    elif args.operation == "install":
        result = install_fresh(args)
    elif args.operation == "activate":
        result = activate_release(
            args.release_id,
            expected_release_approval_reference=args.expected_release_approval_reference,
            layout=_layout(args.root),
            first_activation_authorizer=_prove_backend_client_approved,
        )
    elif args.operation == "rollback":
        result = rollback_release(
            release_id=args.release_id,
            expected_release_approval_reference=args.expected_release_approval_reference,
            reason=args.reason,
            layout=_layout(args.root),
        )
    elif args.operation == "status":
        result = status(_layout(args.root))
    elif args.operation == "wipe":
        wipe(reason=args.reason, confirm=args.confirm, layout=_layout(args.root))
        result = {"status": "wiped"}
    else:  # pragma: no cover
        raise RuntimeError("Ukendt operation")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def transaction_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientFlow root-owned release transaction")
    sub = parser.add_subparsers(dest="operation", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("--release-id", required=True)
    stage.add_argument("--bundle", type=Path, required=True)
    stage.add_argument("--expected-bundle-sha256", required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--release-id", required=True)
    activate.add_argument("--expected-release-approval-reference", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--release-id")
    rollback.add_argument("--expected-release-approval-reference", required=True)
    rollback.add_argument("--reason", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.operation == "stage":
        result = stage_bundle(
            args.bundle,
            release_id=args.release_id,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    elif args.operation == "activate":
        result = activate_release(
            args.release_id,
            expected_release_approval_reference=args.expected_release_approval_reference,
        )
    elif args.operation == "rollback":
        result = rollback_release(
            release_id=args.release_id,
            expected_release_approval_reference=args.expected_release_approval_reference,
            reason=args.reason,
        )
    else:
        result = status()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0
