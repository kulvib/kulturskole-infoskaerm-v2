#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Kør som root, fx: sudo %s\n' "$0" >&2
  false
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_FILE="$(cd "$SCRIPT_DIR/.." && pwd)/ubuntu-packages.txt"
mapfile -t PACKAGES < <(grep -Ev '^[[:space:]]*(#|$)' "$PACKAGE_FILE")

apt-get -o DPkg::Lock::Timeout=120 update
apt-get -o DPkg::Lock::Timeout=120 install -y "${PACKAGES[@]}"

for element in pipewiresrc videoconvert videoscale x264enc h264parse mpegtsmux hlssink2; do
  gst-inspect-1.0 "$element" >/dev/null
  printf 'OK  %s\n' "$element"
done

python3 - <<'PY'
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
Gst.init(None)
print("OK  Python GI/GStreamer", Gst.version_string())
PY
