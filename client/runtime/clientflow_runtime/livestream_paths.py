"""Livestream domain filesystem contract."""
from __future__ import annotations

import os
from pathlib import Path

STATE_DIR = Path(os.getenv("CLIENTFLOW_LIVESTREAM_STATE_DIR", "/var/lib/clientflow/livestream"))
RUNTIME_DIR = Path(os.getenv("CLIENTFLOW_LIVESTREAM_RUNTIME_DIR", "/run/clientflow/livestream"))
DESIRED_PATH = STATE_DIR / "desired-state.json"
BROKER_STATUS_PATH = STATE_DIR / "broker-status.json"
PRODUCER_STATUS_PATH = STATE_DIR / "producer-status.json"
UPLOADER_STATUS_PATH = Path(
    os.getenv("CLIENTFLOW_LIVESTREAM_UPLOADER_STATUS", "/var/lib/clientflow/livestream-uploader/status.json")
)
CONFIG_PATH = Path(os.getenv("CLIENTFLOW_LIVESTREAM_CONFIG_FILE", "/etc/clientflow/livestream.json"))
BROKER_SOCKET = str(RUNTIME_DIR / "broker.sock")
GENERATIONS_DIR = STATE_DIR / "generations"
