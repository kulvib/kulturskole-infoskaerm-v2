from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_lock(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    contents = {
        "python-runtime-amd64.tar": b"python-runtime",
        "evdev.whl": b"evdev",
        "pip.whl": b"pip",
    }
    artifacts = []
    for name, data in contents.items():
        artifacts.append(
            {
                "file": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    lock = {
        "schema_version": 1,
        "runtime_python": "3.13.14",
        "architecture": "amd64",
        "artifacts": artifacts,
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path, contents


def _transport(path: Path, contents: dict[str, bytes], *, extra: tuple[str, bytes] | None = None, symlink=False):
    with tarfile.open(path, mode="w") as tf:
        for name, data in contents.items():
            member_name = name if name == "python-runtime-amd64.tar" else f"wheelhouse/{name}"
            info = tarfile.TarInfo(member_name)
            if symlink and name == "evdev.whl":
                info.type = tarfile.SYMTYPE
                info.linkname = "../python-runtime-amd64.tar"
                info.size = 0
                tf.addfile(info)
                continue
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        if extra:
            info = tarfile.TarInfo(extra[0])
            info.size = len(extra[1])
            tf.addfile(info, io.BytesIO(extra[1]))


def test_current_platform_lock_is_source_independent_and_matches_physically_verified_inputs():
    data = json.loads((ROOT / "client/release/runtime-platform-inputs.lock.json").read_text())
    assert data["schema_version"] == 1
    assert data["runtime_python"] == "3.13.14"
    assert data["architecture"] == "amd64"
    actual = {item["file"]: (item["size"], item["sha256"]) for item in data["artifacts"]}
    assert actual == {
        "evdev-1.9.3-cp313-cp313-linux_x86_64.whl": (76711, "8fa20b121c58bf286520f65149d1dd9f37c1e8eedea3811a5e1e1f5755d8f71d"),
        "pip-26.1.2-py3-none-any.whl": (1813144, "382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"),
        "pyjwt-2.13.0-py3-none-any.whl": (31273, "aacb2c3c08263deeb6278cf9211cffcf835604346421f9fa1dc36d971762cb79"),
        "python-runtime-amd64.tar": (77547520, "a57cd52a31a466a9c3290cf05cf20bf10e293afae736526d76d3593ca3ea0d15"),
        "websockets-12.0-cp313-cp313-linux_x86_64.whl": (122647, "98b9b9088ca8dca67bf538fad84b14f69196a534f21d6a363ad1f4f1f50b0243"),
    }
    assert not any(name.startswith("clientflow_runtime-") for name in actual)
    platform = {item["file"]: item for item in data["platform_artifacts"]}
    assert platform == {
        "google-chrome-stable_151.0.7922.173-1_amd64.deb": {
            "file": "google-chrome-stable_151.0.7922.173-1_amd64.deb",
            "package": "google-chrome-stable",
            "version": "151.0.7922.173-1",
            "architecture": "amd64",
            "size": 140077524,
            "sha256": "878e5ab495b8a694980fca61bc09b37e651ccedce2291c73434d16e48a2646fd",
        }
    }


def test_runtime_input_materializer_accepts_only_hash_locked_regular_members(tmp_path: Path):
    module = _load_module("materialize_51k", ROOT / "scripts/materialize_clientflow_runtime_inputs.py")
    lock, contents = _tiny_lock(tmp_path)
    archive = tmp_path / "inputs.tar"
    _transport(archive, contents)
    out = tmp_path / "out"
    result = module.materialize(archive, out, lock)
    assert {item["file"] for item in result["artifacts"]} == set(contents)
    assert (out / "python-runtime-amd64.tar").read_bytes() == contents["python-runtime-amd64.tar"]
    assert (out / "wheelhouse/evdev.whl").read_bytes() == contents["evdev.whl"]
    assert (out / "wheelhouse/pip.whl").read_bytes() == contents["pip.whl"]

    extra_archive = tmp_path / "extra.tar"
    _transport(extra_archive, contents, extra=("wheelhouse/undeclared.whl", b"bad"))
    with pytest.raises(ValueError, match="Undeclared"):
        module.materialize(extra_archive, tmp_path / "extra-out", lock)

    symlink_archive = tmp_path / "symlink.tar"
    _transport(symlink_archive, contents, symlink=True)
    with pytest.raises(ValueError, match="regular file"):
        module.materialize(symlink_archive, tmp_path / "symlink-out", lock)


def test_runtime_input_materializer_rejects_tampered_bytes(tmp_path: Path):
    module = _load_module("materialize_51k_tamper", ROOT / "scripts/materialize_clientflow_runtime_inputs.py")
    lock, contents = _tiny_lock(tmp_path)
    tampered = dict(contents)
    tampered["pip.whl"] = b"PIP"
    archive = tmp_path / "tampered.tar"
    _transport(archive, tampered)
    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        module.materialize(archive, tmp_path / "out", lock)


def test_release_build_toolchain_is_single_pinned_contract_and_builder_checks_it():
    toolchain = json.loads((ROOT / "client/release/release-build-toolchain.json").read_text())
    assert toolchain == {
        "schema_version": 1,
        "python": "3.13.14",
        "pip": "26.1.2",
        "setuptools": "83.0.0",
    }
    pyproject = (ROOT / "client/runtime/pyproject.toml").read_text()
    assert 'requires = ["setuptools==83.0.0"]' in pyproject
    build_lock = (ROOT / "client/release/release-build-requirements.lock.txt").read_text()
    assert "setuptools==83.0.0" in build_lock
    assert "sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3" in build_lock
    build_source = (ROOT / "scripts/build_clientflow_release.py").read_text()
    assert "validate_toolchain(repo)" in build_source
    assert build_source.index("validate_toolchain(repo)") < build_source.index('"wheel"')
    assert '"--no-build-isolation"' in build_source


def test_release_build_workflow_is_manual_ci_gated_reproducible_and_non_publishing():
    path = ROOT / ".github/workflows/release-build.yml"
    source = path.read_text()
    workflow = yaml.safe_load(source)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"expected_source_sha", "runtime_inputs_url", "runtime_inputs_sha256"}
    assert "verify_github_ci_run.py" in source
    assert 'test "$GITHUB_SHA" = "$EXPECTED_SOURCE_SHA"' in source
    assert "matrix:" in source and "replica: [a, b]" in source
    assert "verify_clientflow_reproducible_builds.py" in source
    assert "candidate-runtime:" in source
    assert "runs-on: ubuntu-26.04" in source
    assert "verify_clientflow_release_candidate_runtime.py" in source
    assert "--display-platform-install-only" in source
    assert "Require exact embedded Display platform install on Ubuntu 26.04" in source
    assert "needs: [preflight, build, candidate-runtime]" in source
    assert "runtime-platform-inputs.lock.json" not in source  # materializer owns the canonical default
    assert "--require-hashes" in source
    assert "--only-binary=:all:" in source
    assert "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d" in source
    assert "approve_clientflow_release.py" not in source
    assert "publish_clientflow_release.py" not in source
    assert "secrets." not in source
    assert source.count("persist-credentials: false") == 4


def test_release_approval_workflow_is_manual_exact_source_target_host_and_non_publishing():
    path = ROOT / ".github/workflows/release-approve.yml"
    source = path.read_text()
    workflow = yaml.safe_load(source)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "expected_source_sha",
        "expected_candidate_sha256",
        "expected_installer_sha256",
        "approval_reference",
        "approve_release",
    }
    assert "runs-on: ubuntu-26.04" in source
    assert "ref: ${{ inputs.expected_source_sha }}" in source
    assert "clientflow-reproducible-unapproved-${{ inputs.expected_source_sha }}" in source
    assert "actions/workflows/release-build.yml/runs" in source
    assert "run-id: ${{ steps.release_run.outputs.run_id }}" in source
    approval_job = workflow["jobs"]["approve"]
    steps_by_name = {step["name"]: step for step in approval_job["steps"]}
    record_step = steps_by_name["Write immutable approval record"]
    assert record_step["env"]["RELEASE_BUILD_RUN_ID"] == "${{ steps.release_run.outputs.run_id }}"
    assert 'int(os.environ["RELEASE_BUILD_RUN_ID"])' in record_step["run"]
    assert "approve_clientflow_release.py" in source
    assert "--expected-candidate-sha256" in source
    assert "--expected-installer-sha256" in source
    assert "--expected-source-commit" in source
    assert "--approval-reference" in source
    assert "--approve-release" in source
    assert "publish_clientflow_release.py" not in source
    assert "--publish-release" not in source
    assert "secrets." not in source


def test_runtime_input_transport_roundtrips_locked_platform_artifact(tmp_path: Path):
    build_module = _load_module("build_transport_53a", ROOT / "scripts/build_clientflow_runtime_input_transport.py")
    materialize_module = _load_module("materialize_53a", ROOT / "scripts/materialize_clientflow_runtime_inputs.py")

    runtime_bytes = b"python-runtime"
    wheel_bytes = b"pip-wheel"
    chrome_bytes = b"exact-google-chrome-deb"
    chrome_name = "google-chrome-stable_test_amd64.deb"
    lock = {
        "schema_version": 1,
        "runtime_python": "3.13.14",
        "architecture": "amd64",
        "artifacts": [
            {
                "file": "python-runtime-amd64.tar",
                "size": len(runtime_bytes),
                "sha256": hashlib.sha256(runtime_bytes).hexdigest(),
            },
            {
                "file": "pip.whl",
                "size": len(wheel_bytes),
                "sha256": hashlib.sha256(wheel_bytes).hexdigest(),
            },
        ],
        "platform_artifacts": [
            {
                "file": chrome_name,
                "package": "google-chrome-stable",
                "version": "151.0.7922.173-1",
                "architecture": "amd64",
                "size": len(chrome_bytes),
                "sha256": hashlib.sha256(chrome_bytes).hexdigest(),
            }
        ],
    }
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    source = tmp_path / "source"
    (source / "wheelhouse").mkdir(parents=True)
    (source / "platform").mkdir()
    (source / "python-runtime-amd64.tar").write_bytes(runtime_bytes)
    (source / "wheelhouse/pip.whl").write_bytes(wheel_bytes)
    (source / "platform" / chrome_name).write_bytes(chrome_bytes)

    archive = tmp_path / "runtime-inputs.tar"
    build_module.build_transport(source, archive, lock_path)
    with tarfile.open(archive, mode="r:") as tf:
        names = {member.name for member in tf.getmembers() if member.isfile()}
    assert f"platform/{chrome_name}" in names

    output = tmp_path / "materialized"
    result = materialize_module.materialize(archive, output, lock_path)
    assert result["platform_artifacts"] == [
        {
            "file": chrome_name,
            "size": len(chrome_bytes),
            "sha256": hashlib.sha256(chrome_bytes).hexdigest(),
        }
    ]
    assert (output / "platform" / chrome_name).read_bytes() == chrome_bytes
