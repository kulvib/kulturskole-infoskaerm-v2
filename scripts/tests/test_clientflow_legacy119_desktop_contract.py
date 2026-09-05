from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py"


def test_ding_keeps_nautilus_executable_and_hides_virtual_icons():
    source = SOURCE.read_text(encoding="utf-8")
    blocked_section = source.split("KIOSK_BLOCKED_BINARIES = (", 1)[1].split(")", 1)[0]
    assert '"/usr/bin/nautilus"' not in blocked_section
    assert '("org.gnome.shell.extensions.ding", "show-home", "false")' in source
    assert '("org.gnome.shell.extensions.ding", "show-trash", "false")' in source
