from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PROCEDURE = ROOT / "CLIENTFLOW_RELEASE_PROCEDURE.md"
RELEASE_LITERAL_RE = re.compile(r"clientflow-\d+\.\d+\.\d+-seq-\d+")
INSTALLER_LITERAL_RE = re.compile(r"clientflow-installer-\d+\.\d+\.\d+\.pyz")


def _section(source: str, number: int) -> str:
    match = re.search(
        rf"^## {number}\. .*?$(.*?)(?=^## \d+\. |\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing procedure section {number}"
    return match.group(1)


def _bash_blocks(source: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)\n```", source, flags=re.DOTALL)


def test_active_release_shell_blocks_do_not_hardcode_release_identity():
    source = PROCEDURE.read_text(encoding="utf-8")
    active_source = "\n".join(_section(source, number) for number in (3, 4, 5, 6, 7))
    active_shell = "\n".join(_bash_blocks(active_source))

    assert not RELEASE_LITERAL_RE.search(active_shell)
    assert not INSTALLER_LITERAL_RE.search(active_shell)


def test_fresh_install_bootstrap_carries_manifest_identity_forward():
    source = PROCEDURE.read_text(encoding="utf-8")
    bootstrap = _section(source, 5)
    activation = _section(source, 7)

    assert 'm["release_id"]' in bootstrap
    assert 'm["fresh_installer"]' in bootstrap
    assert 'PRIVATE_INSTALLER="$BOOTSTRAP_DIR/$INSTALLER_FILE"' in bootstrap
    assert 'BOOTSTRAP_RELEASE_ID="${BOOTSTRAP_RESULT[0]}"' in bootstrap
    assert 'BOOTSTRAP_INSTALLER="${BOOTSTRAP_RESULT[2]}"' in bootstrap
    assert '--release-id "$BOOTSTRAP_RELEASE_ID"' in activation


def test_procedure_does_not_reintroduce_the_stale_131_bootstrap_assignment():
    source = PROCEDURE.read_text(encoding="utf-8")

    assert 'BOOTSTRAP_INSTALLER="$BOOTSTRAP_DIR/clientflow-installer-1.3.1.pyz"' not in source
    assert "current source/build identity is `1.3.1` / `1202`" not in source
