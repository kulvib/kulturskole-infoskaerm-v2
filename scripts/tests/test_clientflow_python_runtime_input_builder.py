from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/build_clientflow_python_runtime_input.py"
    spec = importlib.util.spec_from_file_location("clientflow_python_runtime_input", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runtime_fixture(tmp_path: Path, *, version: str = "3.13.15") -> Path:
    root = tmp_path / "source-runtime"
    (root / "bin").mkdir(parents=True)
    (root / "lib/python3.13/__pycache__").mkdir(parents=True)
    python3 = root / "bin/python3"
    python3.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
        f"printf '{{\"executable\":\"%s/bin/python3\",\"prefix\":\"%s\",\"version\":\"{version}\"}}\\n' \"$ROOT\" \"$ROOT\"\n",
        encoding="utf-8",
    )
    python3.chmod(0o755)
    (root / "bin/python").symlink_to("python3")
    (root / "lib/python3.13/os.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "lib/python3.13/skip.pyc").write_bytes(b"volatile-bytecode")
    (root / "lib/python3.13/__pycache__/skip.cpython.pyc").write_bytes(b"volatile-cache")
    return root


def test_builder_is_deterministic_normalizes_metadata_and_dereferences_internal_links(tmp_path: Path):
    module = _load_module()
    source = _runtime_fixture(tmp_path)
    first = tmp_path / "a" / "python-runtime-amd64.tar"
    second = tmp_path / "b" / "python-runtime-amd64.tar"

    manifest_a = module.build_runtime(source, first, version="3.13.15")
    manifest_b = module.build_runtime(source, second, version="3.13.15")

    assert first.read_bytes() == second.read_bytes()
    assert manifest_a == manifest_b
    assert manifest_a["version"] == "3.13.15"
    assert manifest_a["root"] == "python-3.13.15"
    assert manifest_a["size_bytes"] == first.stat().st_size
    assert manifest_a["sha256"] == module.sha256_file(first)[1]

    with tarfile.open(first, mode="r:") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        assert "python-3.13.15/bin/python3" in names
        assert "python-3.13.15/bin/python" in names
        assert not any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names)
        for member in members:
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == "root"
            assert member.mtime == 0
            assert not member.issym()
            assert not member.islnk()
        materialized_python = archive.getmember("python-3.13.15/bin/python")
        assert materialized_python.isfile()
        assert materialized_python.mode == 0o755


def test_builder_rejects_external_symlinks_directory_cycles_and_special_files(tmp_path: Path):
    module = _load_module()

    source = _runtime_fixture(tmp_path / "external")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (source / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes source root"):
        module.build_runtime(
            source,
            tmp_path / "external.tar",
            version="3.13.15",
        )

    source = _runtime_fixture(tmp_path / "cycle")
    (source / "loop").symlink_to(source)
    with pytest.raises(ValueError, match="cycle"):
        module.build_runtime(
            source,
            tmp_path / "cycle.tar",
            version="3.13.15",
        )

    if hasattr(os, "mkfifo"):
        source = _runtime_fixture(tmp_path / "fifo")
        os.mkfifo(source / "runtime.fifo")
        with pytest.raises(ValueError, match="special file"):
            module.build_runtime(
                source,
                tmp_path / "fifo.tar",
                version="3.13.15",
            )


def test_builder_requires_exact_version_required_python_and_no_replace_outputs(tmp_path: Path):
    module = _load_module()
    source = _runtime_fixture(tmp_path)

    with pytest.raises(ValueError, match="exact X.Y.Z"):
        module.build_runtime(source, tmp_path / "bad-version.tar", version="3.13")

    (source / "bin/python3").unlink()
    (source / "bin/python").unlink()
    with pytest.raises(ValueError, match="missing required files"):
        module.build_runtime(source, tmp_path / "missing-python.tar", version="3.13.15")

    source = _runtime_fixture(tmp_path / "replace")
    output = tmp_path / "existing" / "python-runtime-amd64.tar"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"winner")
    with pytest.raises(ValueError, match="already exists"):
        module.build_runtime(source, output, version="3.13.15")
    assert output.read_bytes() == b"winner"


def test_builder_does_not_delete_a_concurrent_no_replace_winner(tmp_path: Path, monkeypatch):
    module = _load_module()
    source = _runtime_fixture(tmp_path)
    output = tmp_path / "race/python-runtime-amd64.tar"
    winner = b"concurrent-winner"
    real_link = module.os.link

    def racing_link(src, dst, *, follow_symlinks=True):
        Path(dst).write_bytes(winner)
        return real_link(src, dst, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(module.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        module.build_runtime(source, output, version="3.13.15")
    assert output.read_bytes() == winner


def test_manifest_writer_is_no_replace_and_uses_lock_ready_fields(tmp_path: Path):
    module = _load_module()
    source = _runtime_fixture(tmp_path)
    output = tmp_path / "build/python-runtime-amd64.tar"
    manifest = module.build_runtime(source, output, version="3.13.15")
    manifest_path = tmp_path / "build/python-runtime-manifest.json"
    module._write_manifest(manifest_path, manifest)
    observed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert observed == manifest
    assert set(observed) == {
        "architecture",
        "file",
        "format",
        "root",
        "schema_version",
        "sha256",
        "size_bytes",
        "type",
        "version",
    }
    with pytest.raises(ValueError, match="already exists"):
        module._write_manifest(manifest_path, manifest)


def test_workflow_builds_python_31315_on_ubuntu_2604_twice_and_never_writes_repository():
    source = (ROOT / ".github/workflows/python-runtime-input-build.yml").read_text(encoding="utf-8")
    assert 'CLIENTFLOW_TARGET_PYTHON_VERSION: "3.13.15"' in source
    assert "runs-on: ubuntu-26.04" in source
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in source
    assert 'python-version: "3.13.15"' in source
    assert "python scripts/verify_github_ci_run.py" in source
    assert source.count("python scripts/build_clientflow_python_runtime_input.py") == 1
    assert "for build in a b; do" in source
    assert "runtime-a/python-runtime-amd64.tar" in source
    assert "runtime-b/python-runtime-amd64.tar" in source
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in source
    assert "contents: write" not in source
    assert "gh release create" not in source
