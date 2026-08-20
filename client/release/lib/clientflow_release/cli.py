from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import grp
import re
import stat
import secrets
import subprocess
import uuid

from .bundle import verify_bundle
from .constants import DOMAIN_NAMES, INSTALL_MODE_FRESH, MAX_BUNDLE_BYTES
from .crypto import sha256_file
from .enrollment import claim, complete, generate_system_key, persist_enrollment, validate_backend_url
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

INSTALL_STATE_SCHEMA = 1


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
            raise RuntimeError("kiosk-user skal være en uprivilegeret interaktiv bruger")
    return name


def _all_credentials_present(layout: Layout) -> bool:
    etc = layout.path("/etc/clientflow")
    try:
        identity = _secure_json(etc / "identity.json")
        client_id = int(identity["client_id"])
        terminal_credential_id = str(uuid.UUID(str(identity["terminal_credential_id"])))
        _validate_kiosk_user(str(identity["kiosk_user"]), layout)
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
        _secure_json(etc / "remote-desktop.json")
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False
    return True


def _copy_install_configuration(layout: Layout, release_id: str, *, ca_file: Path | None) -> str | None:
    etc = layout.path("/etc/clientflow")
    release_root = layout.releases / release_id
    for name in ("livestream.json", "remote-desktop.json"):
        destination = etc / name
        if not destination.exists():
            source = release_root / "client-runtime/config-examples" / name
            _secure_regular_file(source, secret=False)
            atomic_write_bytes(destination, source.read_bytes(), mode=0o600)
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


def _verify_expected_bundle_hash(bundle: Path, expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("expected_bundle_sha256 skal være præcis SHA-256")
    try:
        _size, actual = sha256_file(bundle, max_bytes=MAX_BUNDLE_BYTES)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Releasebundlen kunne ikke hashes sikkert: {exc}") from exc
    if actual != expected:
        raise RuntimeError("Releasebundlens SHA-256 matcher ikke den eksplicit forventede hash")
    return actual


def install_fresh(args: argparse.Namespace) -> dict:
    layout = _layout(args.root)
    _require_root(layout)
    kiosk_user = _validate_kiosk_user(args.kiosk_user, layout)
    backend_url = validate_backend_url(args.backend_url)
    approved_bundle_sha256 = _verify_expected_bundle_hash(args.bundle, args.expected_bundle_sha256)
    manifest, _payload = verify_bundle(
        args.bundle, require_deployable=True, required_install_mode=INSTALL_MODE_FRESH
    )
    release_id = manifest["release_id"]
    state_path = _install_state_path(layout)
    if state_path.exists():
        install_state = load_secure_json(state_path)
        if install_state.get("schema_version") != INSTALL_STATE_SCHEMA or install_state.get("release_id") != release_id:
            raise RuntimeError("En anden uafsluttet ClientFlow-installation findes allerede")
        if install_state.get("backend_url") != backend_url or install_state.get("kiosk_user") != kiosk_user:
            raise RuntimeError("Resume kræver samme backend_url og kiosk-user som den oprindelige installation")
        if install_state.get("bundle_sha256") != approved_bundle_sha256:
            raise RuntimeError("Resume kræver præcis samme godkendte releasebundle")
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
            "release_id": release_id,
            "install_id": str(uuid.uuid4()),
            "credential_seed_b64": base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii"),
            "backend_url": backend_url,
            "kiosk_user": kiosk_user,
            "bundle_sha256": approved_bundle_sha256,
            "status": "initialized",
        }
        atomic_write_json(state_path, install_state, mode=0o600)

    seed_text = str(install_state["credential_seed_b64"])
    seed = base64.urlsafe_b64decode(seed_text + "=" * (-len(seed_text) % 4))
    install_id = str(install_state["install_id"])
    etc_root = layout.path("/etc/clientflow")
    ensure_real_directory(etc_root, mode=0o750)
    stage_bundle(
        args.bundle,
        release_id=release_id,
        expected_bundle_sha256=approved_bundle_sha256,
        install_mode=INSTALL_MODE_FRESH,
        layout=layout,
    )
    install_staged_definitions(release_id, layout=layout, kiosk_user=kiosk_user)
    stored_ca_path = _copy_install_configuration(layout, release_id, ca_file=args.ca_file)
    request_ca_file = layout.path(stored_ca_path) if stored_ca_path else None
    install_state["status"] = "staged_inactive"
    atomic_write_json(state_path, install_state, mode=0o600)

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
    _persist_updater_tls_ca(layout, stored_ca_path)

    if not _all_credentials_present(layout):
        response = claim(
            backend_url=backend_url,
            enrollment_code=args.enrollment_code,
            install_id=install_id,
            seed=seed,
            public_key_pem=public_key_pem,
            update_auth_public_key_pem=update_public_key_pem,
            name=args.name,
            locality=args.locality,
            ca_file=request_ca_file,
        )
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
    if install_state.get("status") != "enrollment_completed":
        complete(backend_url=backend_url, install_id=install_id, seed=seed, ca_file=request_ca_file)
        install_state["status"] = "enrollment_completed"
        atomic_write_json(state_path, install_state, mode=0o600)

    install_stable_updater_host(release_id, layout=layout)
    _validate_inactive_install(layout, release_id)
    final_state = {
        "schema_version": INSTALL_STATE_SCHEMA,
        "release_id": release_id,
        "install_id": install_id,
        "backend_url": backend_url,
        "kiosk_user": kiosk_user,
        "bundle_sha256": approved_bundle_sha256,
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
    install.add_argument("--enrollment-code", required=True)
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
        manifest, _ = verify_bundle(
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
