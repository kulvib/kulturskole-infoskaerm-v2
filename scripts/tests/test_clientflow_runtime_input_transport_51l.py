from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import os
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/build_clientflow_runtime_input_transport.py"
    spec = importlib.util.spec_from_file_location("runtime_transport_51l", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    contents = {
        "python-runtime-amd64.tar": b"python-runtime",
        "evdev.whl": b"evdev",
        "pip.whl": b"pip",
    }
    source = tmp_path / "inputs"
    (source / "wheelhouse").mkdir(parents=True)
    (source / "python-runtime-amd64.tar").write_bytes(contents["python-runtime-amd64.tar"])
    (source / "wheelhouse/evdev.whl").write_bytes(contents["evdev.whl"])
    (source / "wheelhouse/pip.whl").write_bytes(contents["pip.whl"])
    lock = {
        "schema_version": 1,
        "runtime_python": "3.13.14",
        "architecture": "amd64",
        "artifacts": [
            {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in contents.items()
        ],
    }
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return source, lock_path, contents


def test_transport_builder_is_byte_reproducible_and_uses_canonical_tar_metadata(tmp_path: Path):
    module = _load_module()
    source, lock, contents = _fixture(tmp_path)
    a = tmp_path / "a.tar"
    b = tmp_path / "b.tar"
    size_a, sha_a = module.build_transport(source, a, lock)
    size_b, sha_b = module.build_transport(source, b, lock)
    assert size_a == size_b
    assert sha_a == sha_b
    assert a.read_bytes() == b.read_bytes()

    with tarfile.open(a, "r:") as tf:
        members = tf.getmembers()
        assert [m.name for m in members] == ["wheelhouse", "wheelhouse/evdev.whl", "wheelhouse/pip.whl", "python-runtime-amd64.tar"]
        assert members[0].isdir() and members[0].mode == 0o700
        for member in members:
            assert member.mtime == 0
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == ""
            if member.isfile():
                assert member.mode == 0o400
        extracted = {
            m.name.split("/", 1)[-1]: tf.extractfile(m).read()
            for m in members
            if m.isfile()
        }
    assert extracted == contents


def test_transport_builder_rejects_tampered_missing_extra_and_symlink_inputs(tmp_path: Path):
    module = _load_module()
    source, lock, _ = _fixture(tmp_path)

    (source / "wheelhouse/pip.whl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match lock"):
        module.build_transport(source, tmp_path / "tampered.tar", lock)

    source, lock, _ = _fixture(tmp_path / "missing")
    (source / "wheelhouse/evdev.whl").unlink()
    with pytest.raises(ValueError, match="does not match lock"):
        module.build_transport(source, tmp_path / "missing.tar", lock)

    source, lock, _ = _fixture(tmp_path / "extra")
    (source / "wheelhouse/extra.whl").write_bytes(b"extra")
    with pytest.raises(ValueError, match="does not match lock"):
        module.build_transport(source, tmp_path / "extra.tar", lock)

    source, lock, _ = _fixture(tmp_path / "symlink")
    target = source / "wheelhouse/evdev.whl"
    target.unlink()
    target.symlink_to(source / "python-runtime-amd64.tar")
    with pytest.raises(ValueError, match="symlink"):
        module.build_transport(source, tmp_path / "symlink.tar", lock)


def test_transport_builder_is_no_replace_and_output_revalidates_against_lock(tmp_path: Path):
    module = _load_module()
    source, lock, _ = _fixture(tmp_path)
    output = tmp_path / "transport.tar"
    module.build_transport(source, output, lock)
    first = output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        module.build_transport(source, output, lock)
    assert output.read_bytes() == first

    materializer_path = ROOT / "scripts/materialize_clientflow_runtime_inputs.py"
    spec = importlib.util.spec_from_file_location("materialize_after_51l", materializer_path)
    assert spec and spec.loader
    materializer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(materializer)
    result = materializer.materialize(output, tmp_path / "materialized", lock)
    assert len(result["artifacts"]) == 3


def test_transport_builder_does_not_delete_concurrent_no_replace_winner(tmp_path: Path, monkeypatch):
    module = _load_module()
    source, lock, _ = _fixture(tmp_path)
    output = tmp_path / "transport.tar"
    winner = b"concurrent-winner"
    real_link = os.link

    def racing_link(src, dst, *, follow_symlinks=True):
        Path(dst).write_bytes(winner)
        return real_link(src, dst, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(module.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        module.build_transport(source, output, lock)
    assert output.read_bytes() == winner
