#!/usr/bin/env python3
"""Approve one exact canonical ClientFlow release candidate."""
from __future__ import annotations

from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))
from clientflow_release.approval import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
