#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Kør som root, fx: sudo %s\n' "$0" >&2
  false
fi

RELEASE_ID="clientflow-1.2.0-seq-1200"
TARGET="/opt/clientflow/releases/$RELEASE_ID"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OVERLAY="$ROOT/overlay/opt/clientflow/releases/$RELEASE_ID"

[[ -d "$TARGET" ]] || { printf 'Forventet release mangler: %s\n' "$TARGET" >&2; false; }
[[ -d "$OVERLAY" ]] || { printf 'Overlay mangler: %s\n' "$OVERLAY" >&2; false; }

DESIRED="/var/lib/clientflow/livestream/desired-state.json"
if [[ -s "$DESIRED" ]]; then
  state="$(python3 - "$DESIRED" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("desired", ""))
except Exception:
    print("")
PY
)"
  [[ "$state" == "stopped" ]] || {
    printf 'Livestream skal være stopped før overlay-installation. Aktuel desired=%s\n' "$state" >&2
    false
  }
fi

BACKUP="/var/backups/clientflow-livestream-v2-$(date +%Y%m%d-%H%M%S)"
install -d -m 0750 "$BACKUP"

systemctl stop clientflow-livestream-producer.service
systemctl stop clientflow-livestream-uploader.service

cp -a /etc/clientflow/livestream.json "$BACKUP/" 2>/dev/null || true
cp -a /etc/systemd/system/clientflow-livestream-producer.service "$BACKUP/" 2>/dev/null || true
for name in livestream_producer.py livestream_wayland_capture.py livestream_uploader.py; do
  cp -a "$TARGET/runtime/lib/python3.13/site-packages/clientflow_runtime/$name" "$BACKUP/" 2>/dev/null || true
done

install -m 0640 -o root -g clientflow-livestream-control \
  "$OVERLAY/client-runtime/config-examples/livestream.json" \
  /etc/clientflow/livestream.json
install -m 0644 -o root -g root \
  "$OVERLAY/client-runtime/systemd/clientflow-livestream-producer.service" \
  /etc/systemd/system/clientflow-livestream-producer.service
for name in livestream_producer.py livestream_wayland_capture.py livestream_uploader.py; do
  install -m 0444 -o root -g root \
    "$OVERLAY/runtime/lib/python3.13/site-packages/clientflow_runtime/$name" \
    "$TARGET/runtime/lib/python3.13/site-packages/clientflow_runtime/$name"
done

systemctl daemon-reload
systemctl start clientflow-livestream-uploader.service
systemctl start clientflow-livestream-producer.service
printf 'Installeret. Backup: %s\n' "$BACKUP"
