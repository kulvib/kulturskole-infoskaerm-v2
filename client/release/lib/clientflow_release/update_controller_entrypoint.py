"""Process entry point for the privileged ClientFlow update controller."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .update_controller import UpdateController
from .updater_config import UpdaterConfig


def _state_directory() -> Path:
    raw = str(os.getenv("STATE_DIRECTORY") or "/var/lib/clientflow/update-controller").strip()
    return Path(raw.split(":", 1)[0])


def main() -> int:
    try:
        config = UpdaterConfig.from_environment()
        source_state_root = Path(
            os.getenv("CLIENTFLOW_UPDATE_SOURCE_STATE_DIR")
            or "/var/lib/clientflow/updater"
        )
        result = UpdateController(
            config,
            source_state_root=source_state_root,
            controller_state_root=_state_directory(),
        ).run_once()
    except Exception as exc:  # process boundary: systemd records concise failure
        print(f"clientflow-update-controller: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
