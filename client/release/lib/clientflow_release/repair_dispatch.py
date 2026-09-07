from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from .filesystem import load_secure_json

_INSTALL_STATE_SCHEMA = 2
_RELEASE_ID_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")


def resolve_repair_transaction(*, root: Path = Path("/")) -> Path:
    """Resolve the exact original staged release transaction wrapper.

    The stable updater is deliberately unprivileged/minimal and therefore does
    not embed installer/transaction code.  For the explicit root-only
    pre-first-activation repair command it dispatches into the immutable staged
    release that was bound by the original consuming fresh-install claim.
    """
    state_path = root / "var/lib/clientflow/release/install-state.json"
    try:
        install_state = load_secure_json(
            state_path,
            max_bytes=1024 * 1024,
            forbidden_mode_bits=0o077,
        )
    except Exception as exc:
        raise RuntimeError("Pre-first-activation repair mangler gyldig install-state") from exc
    if install_state.get("schema_version") != _INSTALL_STATE_SCHEMA:
        raise RuntimeError("Pre-first-activation repair har ugyldigt install-state schema")
    if install_state.get("status") != "pending_manual_activation":
        raise RuntimeError("Pre-first-activation repair kræver pending_manual_activation")
    binding = install_state.get("fresh_install_binding")
    if not isinstance(binding, dict):
        raise RuntimeError("Pre-first-activation repair mangler fresh-install binding")
    release_id = str(binding.get("release_id") or "").strip()
    if not _RELEASE_ID_RE.fullmatch(release_id):
        raise RuntimeError("Pre-first-activation repair har ugyldig original release-id")

    wrapper = (
        root
        / "opt/clientflow/releases"
        / release_id
        / "release/bin/clientflow-release-transaction"
    )
    try:
        metadata = wrapper.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("Original staged release mangler repair transaction-wrapper") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("Repair transaction-wrapper er ikke en almindelig fil")
    if root == Path("/") and (metadata.st_uid != 0 or metadata.st_gid != 0):
        raise RuntimeError("Repair transaction-wrapper skal være root-owned")
    return wrapper


def exec_pre_first_activation_repair(*, root: Path = Path("/")) -> None:
    if root == Path("/") and os.geteuid() != 0:
        raise RuntimeError("Pre-first-activation repair kræver root")
    wrapper = resolve_repair_transaction(root=root)
    os.execv(
        "/usr/bin/python3",
        [
            "/usr/bin/python3",
            "-I",
            str(wrapper),
            "repair-first-activation",
        ],
    )
