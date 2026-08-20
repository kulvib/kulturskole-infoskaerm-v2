"""Process entry point for the stable, unprivileged ClientFlow updater host."""
from __future__ import annotations

import json
import sys

from .updater_client import StableUpdaterClient
from .updater_config import UpdaterConfig


def main() -> int:
    try:
        config = UpdaterConfig.from_environment()
        result = StableUpdaterClient(config).run_once()
    except Exception as exc:  # process boundary: systemd records a concise failure
        print(f"clientflow-updater: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
