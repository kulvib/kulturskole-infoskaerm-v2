"""Process entry point for the stable ClientFlow updater host.

With no arguments this remains the unprivileged polling entry point used by
``clientflow-updater.service``.  The single explicit
``repair-first-activation`` operation is a root-only recovery entry point for
an approved client that has never had an active release.  Keeping that command
inside the already materialized stable updater PYZ makes the repair path survive
loss of the transient fresh-install bootstrap directory without enabling the
pending updater timer.
"""
from __future__ import annotations

import json
import sys

from .updater_client import StableUpdaterClient
from .updater_config import UpdaterConfig


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        if args != ["repair-first-activation"]:
            print("clientflow-updater: ukendt operation", file=sys.stderr)
            return 2
        try:
            from .repair_dispatch import exec_pre_first_activation_repair

            # Successful dispatch replaces this process with the immutable
            # original staged release transaction wrapper. It therefore does
            # not return here.
            exec_pre_first_activation_repair()
        except Exception as exc:  # process boundary: systemd/operator receives concise failure
            print(f"clientflow-updater: {exc}", file=sys.stderr)
            return 1
        return 0  # pragma: no cover - os.execv replaces the process

    try:
        config = UpdaterConfig.from_environment()
        result = StableUpdaterClient(config).run_once()
    except Exception as exc:  # process boundary: systemd records a concise failure
        print(f"clientflow-updater: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
