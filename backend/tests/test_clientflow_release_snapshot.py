import pytest

from service1.clientflow_releases import ClientFlowArtifactUnavailable, deployment_release_snapshot


def test_deployment_release_snapshot_accepts_backend_authoritative_nested_artifact():
    value = deployment_release_snapshot({
        "release_id": "clientflow-1.3.0-seq-1300",
        "revision": "ignored-legacy-revision",
        "artifact": {"sha256": "a" * 64, "size": 123456},
        "release_approval": {
            "reference": "approval-1300",
            "candidate_sha256": "b" * 64,
            "source_commit": "c" * 40,
        },
    })
    assert value == {
        "target_release_id": "clientflow-1.3.0-seq-1300",
        "bundle_sha256": "a" * 64,
        "bundle_size": 123456,
        "release_approval_reference": "approval-1300",
        "release_candidate_sha256": "b" * 64,
        "source_commit": "c" * 40,
    }


def test_deployment_release_snapshot_fails_closed_without_byte_identity():
    with pytest.raises(ClientFlowArtifactUnavailable) as raised:
        deployment_release_snapshot({
            "version": "1.2.0",
            "revision": "clientflow-1.2.0-seq-1200",
        })
    message = str(raised.value)
    assert "bundle_sha256" in message
    assert "bundle_size" in message
    assert "release_approval_reference" in message
