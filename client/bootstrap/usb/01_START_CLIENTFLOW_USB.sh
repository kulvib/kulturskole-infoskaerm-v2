#!/usr/bin/env bash
set -euo pipefail

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PAYLOAD_DIR="$SELF_DIR/payload"
CHECKSUMS="$SELF_DIR/PAYLOAD_SHA256SUMS.txt"
TOP_CHECKSUMS="$SELF_DIR/USB_SHA256SUMS.txt"
TARGET="/usr/local/lib/clientflow-bootstrap"

fail(){ printf '[FEJL] %s\n' "$*" >&2; exit 1; }
ok(){ printf '[OK] %s\n' "$*"; }

HOLD_OPEN=0
if [[ "${1:-}" == "--hold-open" ]]; then
  HOLD_OPEN=1
  shift
fi
[[ "$#" -eq 0 ]] || fail "Ukendt argument til ClientFlow USB-start: $1"

hold_open_on_exit(){
  local rc=$?
  trap - EXIT
  if [[ "$HOLD_OPEN" == "1" ]]; then
    printf '\n'
    if [[ "$rc" -ne 0 ]]; then
      printf '[FEJL] USB-klargøringen stoppede med exit-kode %d. Se fejlen ovenfor.\n' "$rc" >&2
    fi
    printf '%s' 'Tryk Enter for at lukke terminalvinduet...'
    IFS= read -r _ || true
    printf '\n'
  fi
  exit "$rc"
}

if [[ "$HOLD_OPEN" == "1" ]]; then
  trap hold_open_on_exit EXIT
fi

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  fail "Start USB-flowet som den normale Ubuntu-installationsbruger, ikke som root. Scriptet bruger selv sudo, når det er nødvendigt."
fi
command -v sudo >/dev/null 2>&1 || fail "sudo mangler på Ubuntu-klienten."
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum mangler på Ubuntu-klienten."
[[ -d "$PAYLOAD_DIR" && -f "$CHECKSUMS" && -f "$TOP_CHECKSUMS" ]] || fail "USB-payload eller checksum-manifest mangler."

mapfile -t actual < <(find "$PAYLOAD_DIR" -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)
expected=(clientflow-factory-prepare clientflow-fresh-install clientflow_bootstrap_common.py planiq-display-mark.png)
[[ "${actual[*]}" == "${expected[*]}" ]] || fail "USB-payloadens filset matcher ikke den canonical ClientFlow-kontrakt."

(
  cd "$SELF_DIR"
  sha256sum --check --strict USB_SHA256SUMS.txt
  sha256sum --check --strict PAYLOAD_SHA256SUMS.txt
) || fail "USB-mediets SHA-256-integritet fejlede."
ok "USB-mediets og bootstrap-payloadens SHA-256-integritet er verificeret."

sudo -v
sudo install -d -o root -g root -m 0755 "$TARGET"
sudo install -o root -g root -m 0444 "$PAYLOAD_DIR/clientflow_bootstrap_common.py" "$TARGET/clientflow_bootstrap_common.py"
sudo install -o root -g root -m 0555 "$PAYLOAD_DIR/clientflow-factory-prepare" "$TARGET/clientflow-factory-prepare"
sudo install -o root -g root -m 0555 "$PAYLOAD_DIR/clientflow-fresh-install" "$TARGET/clientflow-fresh-install"
sudo install -o root -g root -m 0444 "$PAYLOAD_DIR/planiq-display-mark.png" "$TARGET/planiq-display-mark.png"

printf '\n'
printf '%s\n' '============================================================'
printf '%s\n' 'CLIENTFLOW USB · netværkskontrol og 01 Klient klargøring'
printf '%s\n' '============================================================'
printf '\n'
sudo "$TARGET/clientflow-factory-prepare" --usb-preflight

printf '\n'
ok "USB-klargøring færdig. Åbn nu '01 Klient klargøring' på skrivebordet."
