#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' '=== ClientFlow Livestream v2 validation ==='

for element in pipewiresrc videoconvert videoscale x264enc h264parse mpegtsmux hlssink2; do
  if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
    printf 'OK  gst:%s\n' "$element"
  else
    printf 'MANGLER  gst:%s\n' "$element"
  fi
done

printf '\n--- config ---\n'
cat /etc/clientflow/livestream.json 2>/dev/null || true
printf '\n--- services ---\n'
for u in clientflow-livestream-agent.service clientflow-livestream-broker.service clientflow-livestream-producer.service clientflow-livestream-uploader.service; do
  printf '%-48s ' "$u"
  systemctl is-active "$u" 2>/dev/null || true
done
printf '\n--- producer status ---\n'
cat /var/lib/clientflow/livestream/producer-status.json 2>/dev/null || true
printf '\n--- uploader status ---\n'
cat /var/lib/clientflow/livestream-uploader/status.json 2>/dev/null || true
