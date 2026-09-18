# ClientFlow 1222 physical desktop-launcher fix

Date: 2026-09-18

## Physical finding

Canonical physical Ubuntu 26.04 fresh-install verification of the approved and
published `clientflow-1.3.21-seq-1222` reached the repo-owned USB preflight
successfully. The exact USB file set and both checksum manifests passed, the
backend was reachable, and `01 Klient klargøring.desktop` was created in the
active XDG Desktop directory.

Double-clicking `01 Klient klargøring` then appeared to do nothing.

Read-only physical diagnostics proved that the desktop entry itself was valid:

- owner `viborg2:viborg2`, mode `0755`;
- `desktop-file-validate` exit `0`;
- GIO `metadata::trusted: true`;
- `Exec=/usr/local/bin/clientflow-open-factory-prepare`;
- generated launcher owner `root:root`, mode `0755`;
- generated launcher passed `bash -n`;
- the Ubuntu 26.04 `x-terminal-emulator` alternative resolved to `/usr/bin/ptyxis`.

The user-session journal recorded the actual failure on each click:

```text
/usr/local/bin/clientflow-open-factory-prepare: line 3: rc: unbound variable
```

The physical 1.3.21/1222 run is therefore a canonical **FAIL** at the first
operator desktop-launcher transition. No local bypass is accepted as release
evidence.

## Root cause

`install_terminal_launcher()` generated a wrapper using:

```text
set -euo pipefail
RUN="... rc=$?; ... $rc ..."
```

The command text was serialized with `json.dumps()`. JSON double-quoted strings
do not protect shell `$` expansion. The outer launcher shell therefore expanded
`$?` and `$rc` while assigning `RUN`, before the inner `bash -lc` command had
run. Because the wrapper enables `set -u`, the undefined `rc` expansion aborted
the launcher immediately.

This affects both repo-owned operator launchers because both
`01 Klient klargøring` and `02 Aktiver ClientFlow` are generated through the
same helper and both runtime commands contain `rc=$?` / `$rc`.

A syntax-only check cannot detect this defect: the generated wrapper is valid
shell syntax and fails only when executed.

## Fix

The shared terminal-launcher generator now:

1. shell-quotes the title and complete inner command with `shlex.quote()`;
2. passes that quoted command directly as the single `bash -lc` command
   argument, eliminating the unsafe outer `RUN=...` assignment;
3. explicitly prefers Ptyxis when available and invokes it with its program
   argument contract:

   ```text
   ptyxis --title=<title> -- bash -lc <command>
   ```

4. retains the existing `x-terminal-emulator`, `gnome-terminal`, `kgx`, `xterm`
   and non-terminal fallbacks.

This keeps `$?` and `$rc` literal until the inner shell executes them and also
avoids relying on the legacy `x-terminal-emulator -e` path when the canonical
Ubuntu 26.04 host provides Ptyxis directly.

Livestream, Terminal and Remote Desktop implementation domains are untouched.

## Regression coverage

New executable regression tests cover the failure mode rather than only shell
syntax:

- a fake Ptyxis implementation validates the Ubuntu 26.04 `-- PROGRAM ARGS`
  contract and executes the generated inner `bash -lc` command;
- a fake generic `x-terminal-emulator` validates the retained fallback;
- both tests require runtime `$?` / `$rc` evaluation to reach the inner shell;
- the test suite explicitly proves that both operator desktop flows use the
  same fixed launcher generator.

Against the unmodified 1.3.21/1222 source, the new regression file fails 2/3
with `rc: unbound variable`. Against this fix, it passes 3/3.

Local validation on the fixed tree:

```text
python3 -m pytest -q scripts/tests/test_clientflow_terminal_launcher_1222.py
3 passed

python3 -m pytest -q \
  scripts/tests/test_clientflow_terminal_launcher_1222.py \
  scripts/tests/test_clientflow_legacy119_install_flow_v2.py \
  scripts/tests/test_clientflow_factory_network_preclaim.py \
  scripts/tests/test_clientflow_physical_failure_fixes_1221.py \
  scripts/tests/test_clientflow_code_only_fresh_install.py
48 passed

PYTHONPATH="backend:client/runtime:client/release/lib" \
  python3 -m pytest -q scripts/tests
233 passed
```

The deterministic USB builder was also executed twice from the fixed tree:

```text
USB_SIZE=21443
USB_SHA256=cf478abf4bf055ae7a0c21cc83d3fbfa52a1a9f95bddd2a6fc685827d1676351
USB_REPRODUCIBLE_OK
```

Both generated ZIPs were byte-identical and both embedded checksum manifests
verified successfully.

## Release discipline

This physical-failure patch deliberately does **not** modify `client/VERSION`,
`release_sequence`, runtime catalog selection, or any immutable 1.3.21/1222
release bytes. `clientflow-1.3.21-seq-1222` remains a physically failed
canonical release and is not hotfixed in place.

After this fix is merged and canonical GitHub CI is green, the normal release
process must allocate a new source/build identity and repeat build,
reproducibility, approval, immutable publication, separate catalog promotion,
clean Ubuntu 26.04 physical fresh-install, and GUI/process parity acceptance.
