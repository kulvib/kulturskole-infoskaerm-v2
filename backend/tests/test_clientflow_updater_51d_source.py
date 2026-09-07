from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_step51d_is_separate_from_legacy_system_domain_and_root_activation():
    client = read("client/release/lib/clientflow_release/updater_client.py")
    transport = read("client/release/lib/clientflow_release/updater_transport.py")
    state = read("client/release/lib/clientflow_release/updater_state.py")

    combined = client + transport + state
    assert "Domain.SYSTEM" not in combined
    assert "system_agent" not in combined
    assert "system_broker" not in combined
    assert "/var/lib/clientflow/system-agent" not in combined
    assert "/opt/clientflow/active" not in combined
    assert "systemctl" not in combined
    assert "journal" not in combined
    assert '"Authorization"] = f"DPoP {access_token}"' in transport
    assert '"Authorization": f"DPoP {artifact_token}"' in transport


def test_step51d_uses_backend_deployment_snapshot_and_exact_artifact_identity():
    state = read("client/release/lib/clientflow_release/updater_state.py")
    client = read("client/release/lib/clientflow_release/updater_client.py")
    transport = read("client/release/lib/clientflow_release/updater_transport.py")

    for field in (
        "target_release_id",
        "target_version",
        "target_release_sequence",
        "bundle_sha256",
        "bundle_size",
        "release_approval_reference",
        "release_candidate_sha256",
        "source_commit",
    ):
        assert field in state
    assert "Backend ændrede et immutable deployment snapshot" in state
    assert "observed_size != snapshot.bundle_size" in state
    assert "observed_sha256 != snapshot.bundle_sha256" in state
    assert "artifact-authorization" in transport
    assert "release-artifacts" in transport
    assert 'event_type="download_started"' in client
    assert 'event_type="bundle_verified"' in client


def test_step51d_event_id_is_persisted_before_report_and_redirects_are_disabled():
    client = read("client/release/lib/clientflow_release/updater_client.py")
    state = read("client/release/lib/clientflow_release/updater_state.py")
    transport = read("client/release/lib/clientflow_release/updater_transport.py")

    ensure_index = client.index("ensure_pending_event")
    report_index = client.index("self.transport.report_event", ensure_index)
    assert ensure_index < report_index
    assert '"event_id": str(uuid.uuid4())' in state
    assert "self._save()" in state[state.index("def ensure_pending_event"):state.index("def acknowledge_event")]
    assert "class _NoRedirectHandler" in transport
    assert "HTTP redirects er ikke tilladt" in transport
