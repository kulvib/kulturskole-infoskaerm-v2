from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "client/bootstrap/clientflow_bootstrap_common.py"
FRESH = ROOT / "client/bootstrap/clientflow-fresh-install"
USB_START = ROOT / "client/bootstrap/usb/01_START_CLIENTFLOW_USB.sh"
BRAND_MARK = ROOT / "frontend/public/brand/planiq-display/planiq-display-mark.png"
BRAND_WALLPAPER = ROOT / "frontend/public/brand/planiq-display/planiq-display-logo-on-dark.png"
USB_BUILDER = ROOT / "scripts/build_clientflow_usb_installer.py"


def test_desktop_launchers_use_repo_owned_planiq_display_mark() -> None:
    source = COMMON.read_text(encoding="utf-8")
    assert (
        'PLANIQ_DISPLAY_DESKTOP_ICON = PERSISTENT_ROOT / "planiq-display-mark.png"'
        in source
    )
    assert 'f"Icon={PLANIQ_DISPLAY_DESKTOP_ICON}"' in source
    assert '"Icon=utilities-terminal"' not in source
    assert '"planiq-display-mark.png": 0o444' in source
    assert 'PLANIQ_DISPLAY_WALLPAPER = PERSISTENT_ROOT / "planiq-display-logo-on-dark.png"' in source
    assert '"planiq-display-logo-on-dark.png": 0o444' in source


def test_brand_mark_is_persisted_and_removed_with_exact_bootstrap_cleanup() -> None:
    fresh = FRESH.read_text(encoding="utf-8")
    start = USB_START.read_text(encoding="utf-8")
    assert '"planiq-display-mark.png",' in fresh
    assert '"planiq-display-logo-on-dark.png",' in fresh
    assert (
        'expected=(clientflow-factory-prepare clientflow-fresh-install '
        'clientflow_bootstrap_common.py planiq-display-mark.png planiq-display-logo-on-dark.png)'
        in start
    )
    assert (
        "mapfile -t expected < <(printf '%s\\n' \"${expected[@]}\" | LC_ALL=C sort)"
        in start
    )
    assert (
        'sudo install -o root -g root -m 0444 '
        '"$PAYLOAD_DIR/planiq-display-mark.png" "$TARGET/planiq-display-mark.png"'
        in start
    )
    assert (
        'sudo install -o root -g root -m 0444 '
        '"$PAYLOAD_DIR/planiq-display-logo-on-dark.png" "$TARGET/planiq-display-logo-on-dark.png"'
        in start
    )


def test_usb_payload_fileset_contract_matches_builder_and_normalizes_order() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("clientflow_usb_contract_builder", USB_BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    start = USB_START.read_text(encoding="utf-8")
    contract_line = next(
        line for line in start.splitlines() if line.startswith("expected=(")
    )
    contract_names = contract_line.removeprefix("expected=(").removesuffix(")").split()

    assert sorted(contract_names) == sorted(module.PAYLOAD_SOURCES)
    assert (
        "mapfile -t expected < <(printf '%s\\n' \"${expected[@]}\" | LC_ALL=C sort)"
        in start
    )


def test_usb_builder_packages_exact_existing_brand_mark(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("clientflow_usb_brand_builder", USB_BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = tmp_path / "usb.zip"
    module.build(output)
    expected = BRAND_MARK.read_bytes()
    assert expected.startswith(b"\x89PNG\r\n\x1a\n")
    with zipfile.ZipFile(output) as archive:
        packaged = archive.read("payload/planiq-display-mark.png")
        wallpaper = archive.read("payload/planiq-display-logo-on-dark.png")
        manifest = archive.read("PAYLOAD_SHA256SUMS.txt").decode("utf-8")
    assert packaged == expected
    assert wallpaper == BRAND_WALLPAPER.read_bytes()
    digest = hashlib.sha256(expected).hexdigest()
    wallpaper_digest = hashlib.sha256(BRAND_WALLPAPER.read_bytes()).hexdigest()
    assert f"{digest}  payload/planiq-display-mark.png" in manifest
    assert f"{wallpaper_digest}  payload/planiq-display-logo-on-dark.png" in manifest


def test_runtime_builder_packages_canonical_display_brand_assets() -> None:
    builder = (ROOT / "client/release/lib/clientflow_release/builder.py").read_text(encoding="utf-8")
    assert 'Path("frontend/public/brand/planiq-display")' in builder
    assert 'PurePosixPath(root) / "client-runtime/brand/planiq-display"' in builder
