from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import shlex
import stat


class SystemdContractError(RuntimeError):
    pass


_EXEC_DIRECTIVES = {
    "ExecCondition",
    "ExecStart",
    "ExecStartPre",
    "ExecStartPost",
    "ExecStop",
    "ExecStopPost",
    "ExecReload",
}
_USER_DIRECTIVES = {"User", "SocketUser"}
_GROUP_DIRECTIVES = {"Group", "SocketGroup"}
_MULTI_GROUP_DIRECTIVES = {"SupplementaryGroups"}
_UNIT_REFERENCE_DIRECTIVES = {
    "Requires",
    "Requisite",
    "Wants",
    "BindsTo",
    "PartOf",
    "Conflicts",
    "Before",
    "After",
    "OnSuccess",
    "OnFailure",
    "Unit",
    "Service",
}
_COMMAND_PREFIXES = "-+!:@|"
_ACTIVE_PREFIX = "/opt/clientflow/active/"
_STABLE_UPDATER = "/usr/lib/clientflow/updater/clientflow-updater.pyz"
_ALLOWED_HOST_ACCOUNTS = {
    "root",
    "input",
    "video",
    "render",
    "audio",
}
_PLACEHOLDER_RE = re.compile(r"@[A-Z0-9_]+@")


@dataclass(frozen=True)
class UnitDirective:
    unit: str
    section: str
    key: str
    value: str
    line_number: int


def _read_directives(path: Path) -> list[UnitDirective]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemdContractError(f"Systemd unit kunne ikke læses som UTF-8: {path}") from exc
    rows: list[UnitDirective] = []
    section = ""
    pending = ""
    pending_line = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if pending:
            stripped = pending + stripped
            line_number = pending_line
            pending = ""
        if stripped.endswith("\\"):
            pending = stripped[:-1]
            pending_line = line_number
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            continue
        if "=" not in stripped:
            raise SystemdContractError(f"Ugyldig systemd-linje: {path.name}:{line_number}")
        key, value = stripped.split("=", 1)
        rows.append(UnitDirective(path.name, section, key.strip(), value.strip(), line_number))
    if pending:
        raise SystemdContractError(f"Uafsluttet systemd line continuation: {path.name}:{pending_line}")
    return rows


def _parse_sysusers(path: Path) -> tuple[set[str], set[str]]:
    users: set[str] = set()
    groups: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemdContractError("Canonical sysusers-definition kunne ikke læses") from exc
    for line_number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parts = shlex.split(stripped, comments=False, posix=True)
        except ValueError as exc:
            raise SystemdContractError(f"Ugyldig sysusers-linje {line_number}") from exc
        if len(parts) < 2 or parts[0] not in {"u", "g", "m"}:
            raise SystemdContractError(f"Uventet sysusers-kontrakt på linje {line_number}")
        if parts[0] == "u":
            users.add(parts[1])
            groups.add(parts[1])
        elif parts[0] == "g":
            groups.add(parts[1])
        elif len(parts) >= 3:
            groups.add(parts[2])
    return users, groups


def _resolve_release_path(release_root: Path, absolute: str) -> Path | None:
    if not absolute.startswith(_ACTIVE_PREFIX):
        return None
    relative = absolute[len(_ACTIVE_PREFIX):]
    if not relative or relative.startswith("/"):
        raise SystemdContractError(f"Ugyldig active-release path i systemd: {absolute}")
    candidate = release_root / relative
    try:
        candidate.relative_to(release_root)
    except ValueError as exc:
        raise SystemdContractError(f"Systemd-path undslipper active release: {absolute}") from exc
    return candidate


def _regular(path: Path, *, executable: bool, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SystemdContractError(f"{description} mangler: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemdContractError(f"{description} er ikke en regulær fil: {path}")
    if executable and not (metadata.st_mode & stat.S_IXUSR):
        raise SystemdContractError(f"{description} er ikke executable: {path}")


def _command_tokens(row: UnitDirective) -> list[str]:
    value = row.value.lstrip(_COMMAND_PREFIXES).strip()
    if not value:
        raise SystemdContractError(f"Tom {row.key}: {row.unit}:{row.line_number}")
    try:
        tokens = shlex.split(value, posix=True)
    except ValueError as exc:
        raise SystemdContractError(f"Ugyldig {row.key}: {row.unit}:{row.line_number}") from exc
    if not tokens or not tokens[0].startswith("/"):
        raise SystemdContractError(
            f"{row.key} skal bruge absolut executable path: {row.unit}:{row.line_number}"
        )
    return tokens


def _validate_command(row: UnitDirective, release_root: Path) -> None:
    tokens = _command_tokens(row)
    executable = tokens[0]
    mapped_executable = _resolve_release_path(release_root, executable)
    if mapped_executable is not None:
        _regular(mapped_executable, executable=True, description=f"{row.unit} {row.key} executable")

    # Any active-release path passed as an argument is part of the same immutable
    # payload contract. Shell/Python arguments need to exist, but do not need an
    # executable bit because their interpreter owns execution.
    for token in tokens[1:]:
        if not token.startswith(_ACTIVE_PREFIX):
            continue
        mapped = _resolve_release_path(release_root, token)
        assert mapped is not None
        _regular(mapped, executable=False, description=f"{row.unit} {row.key} payload argument")

    if executable == "/usr/bin/python3" and _STABLE_UPDATER in tokens[1:]:
        source = release_root / "release/updater/clientflow-updater.pyz"
        _regular(source, executable=False, description="Stable updater source PYZ")


def _unit_references(value: str) -> list[str]:
    refs: list[str] = []
    for token in value.split():
        token = token.strip()
        if token.startswith("clientflow") and token.endswith((".service", ".socket", ".target", ".timer")):
            refs.append(token)
    return refs


def _service_directive_values(path: Path, key: str) -> list[str]:
    return [
        row.value
        for row in _read_directives(path)
        if row.section == "Service" and row.key == key
    ]


def _require_single_service_value(units: dict[str, Path], unit: str, key: str, expected: str) -> None:
    path = units.get(unit)
    if path is None:
        raise SystemdContractError(f"Release mangler operational systemd unit: {unit}")
    values = _service_directive_values(path, key)
    if values != [expected]:
        observed = ", ".join(values) if values else "<missing>"
        raise SystemdContractError(
            f"Operational systemd-kontrakt driftede: {unit} {key}={observed}, forventet {expected}"
        )


def _require_address_families(units: dict[str, Path], unit: str, required: set[str]) -> None:
    path = units.get(unit)
    if path is None:
        raise SystemdContractError(f"Release mangler operational systemd unit: {unit}")
    values = _service_directive_values(path, "RestrictAddressFamilies")
    if len(values) != 1:
        raise SystemdContractError(
            f"Operational systemd-kontrakt driftede: {unit} RestrictAddressFamilies skal forekomme præcis én gang"
        )
    observed = set(values[0].split())
    missing = sorted(required - observed)
    if missing:
        raise SystemdContractError(
            f"Operational systemd-kontrakt mangler address families for {unit}: {', '.join(missing)}"
        )


def _validate_operational_service_contracts(units: dict[str, Path]) -> None:
    # /etc/clientflow/activated is not a canonical lifecycle authority. Fresh
    # activation is owned by the durable release transaction + active symlink,
    # so a service gated on this orphan marker can be skipped while activation
    # health requires the same WantedBy=clientflow.target service to be active.
    for unit_name, path in units.items():
        for row in _read_directives(path):
            if row.key == "ConditionPathExists" and row.value == "/etc/clientflow/activated":
                raise SystemdContractError(
                    f"Obsolete parallel activation marker er ikke tilladt: {unit_name}:{row.line_number}"
                )

    # These root-owned paths intentionally execute package-management helpers.
    # Ubuntu 26.04 systemd removes CAP_SETUID from the effective/permitted set in
    # the observed NoNewPrivileges=yes sandbox, which prevents APT from dropping
    # to _apt. Keep the required exception explicit and release-gated.
    _require_single_service_value(
        units, "clientflow-platform-prepare.service", "NoNewPrivileges", "no"
    )
    _require_single_service_value(
        units, "clientflow-system-broker.service", "NoNewPrivileges", "no"
    )

    # Both real runtime paths invoke /usr/sbin/ip and therefore require netlink
    # route/address access inside their systemd sandboxes.
    for unit in ("clientflow-status-agent.service", "clientflow-display-runtime.service"):
        _require_address_families(units, unit, {"AF_UNIX", "AF_NETLINK", "AF_INET", "AF_INET6"})

    # Frozen Livestream deliberately retains NNP while explicitly carrying the
    # capability pair needed by setpriv --reuid/--regid. Guard that isolation
    # while the Ubuntu executable host gate proves it works under real systemd.
    _require_single_service_value(
        units, "clientflow-livestream-producer.service", "NoNewPrivileges", "yes"
    )
    for key in ("CapabilityBoundingSet", "AmbientCapabilities"):
        path = units["clientflow-livestream-producer.service"]
        values = _service_directive_values(path, key)
        if len(values) != 1 or not {"CAP_SETUID", "CAP_SETGID"} <= set(values[0].split()):
            raise SystemdContractError(
                f"Frozen Livestream privilege-drop contract mangler CAP_SETUID/CAP_SETGID i {key}"
            )


def validate_release_systemd_contract(
    release_root: Path,
    *,
    kiosk_user: str | None = None,
    require_resolved_placeholders: bool = False,
) -> dict[str, object]:
    """Validate systemd definitions against the materialized release payload.

    This is intentionally independent of a running systemd manager. It proves
    that release-owned command paths, ClientFlow users/groups, and ClientFlow
    unit references are internally coherent before activation can start.
    """
    release_root = release_root.resolve()
    systemd_root = release_root / "client-runtime/systemd"
    sysusers_path = release_root / "client-runtime/sysusers.d/clientflow.conf"
    if not systemd_root.is_dir() or systemd_root.is_symlink():
        raise SystemdContractError("Release mangler canonical client-runtime/systemd")
    users, groups = _parse_sysusers(sysusers_path)
    units = {
        path.name: path
        for path in sorted(systemd_root.iterdir())
        if path.is_file() and not path.is_symlink() and path.suffix in {".service", ".socket", ".target", ".timer"}
    }
    if not units or "clientflow.target" not in units:
        raise SystemdContractError("Release mangler canonical clientflow.target")
    if any(not name.startswith("clientflow") for name in units):
        raise SystemdContractError("Release indeholder ikke-ClientFlow managed unit")

    executable_paths: set[str] = set()
    clientflow_references: set[str] = set()
    for unit_name, path in units.items():
        text = path.read_text(encoding="utf-8")
        if require_resolved_placeholders and _PLACEHOLDER_RE.search(text):
            raise SystemdContractError(f"Managed unit har uløst placeholder: {unit_name}")
        directives = _read_directives(path)
        for row in directives:
            if row.key in _EXEC_DIRECTIVES:
                tokens = _command_tokens(row)
                executable_paths.add(tokens[0])
                _validate_command(row, release_root)
            elif row.key in (_USER_DIRECTIVES | _GROUP_DIRECTIVES):
                value = row.value
                if _PLACEHOLDER_RE.fullmatch(value):
                    if require_resolved_placeholders:
                        raise SystemdContractError(f"Uløst account-placeholder: {unit_name}:{row.line_number}")
                    continue
                canonical = users if row.key in _USER_DIRECTIVES else groups
                allowed = canonical | _ALLOWED_HOST_ACCOUNTS
                if kiosk_user:
                    allowed.add(kiosk_user)
                if value not in allowed:
                    kind = "user" if row.key in _USER_DIRECTIVES else "group"
                    raise SystemdContractError(
                        f"Systemd {kind} er ikke ejet af sysusers/host-kontrakten: {unit_name} {row.key}={value}"
                    )
            elif row.key in _MULTI_GROUP_DIRECTIVES:
                allowed = groups | _ALLOWED_HOST_ACCOUNTS
                if kiosk_user:
                    allowed.add(kiosk_user)
                for group in row.value.split():
                    if _PLACEHOLDER_RE.fullmatch(group):
                        if require_resolved_placeholders:
                            raise SystemdContractError(
                                f"Uløst group-placeholder: {unit_name}:{row.line_number}"
                            )
                        continue
                    if group not in allowed:
                        raise SystemdContractError(
                            f"SupplementaryGroup mangler canonical owner: {unit_name} {group}"
                        )
            if row.key in _UNIT_REFERENCE_DIRECTIVES:
                clientflow_references.update(_unit_references(row.value))

    missing_units = sorted(clientflow_references.difference(units))
    if missing_units:
        raise SystemdContractError(
            "Systemd refererer ClientFlow units, som ikke findes i payloaden: " + ", ".join(missing_units)
        )

    _validate_operational_service_contracts(units)

    return {
        "unit_count": len(units),
        "clientflow_user_count": len(users),
        "clientflow_group_count": len(groups),
        "exec_paths": sorted(executable_paths),
    }
