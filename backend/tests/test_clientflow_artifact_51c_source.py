from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_step51c_backend_artifact_authority_is_deployment_and_dpop_bound():
    router = (ROOT / "backend/service1/routers/clientflow_update.py").read_text()
    auth = (ROOT / "backend/service1/clientflow_artifact_auth.py").read_text()
    artifacts = (ROOT / "backend/service1/clientflow_release_artifacts.py").read_text()

    assert 'scope="artifact:authorize"' in router
    assert '/clientflow-update/deployments/{deployment_id}/artifact-authorization' in router
    assert '/clientflow/release-artifacts/{release_id}' in router
    assert "authenticate_artifact_request" in router
    assert 'ARTIFACT_ACCESS_TOKEN_TYP = "clientflow-artifact-access+jwt"' in auth
    assert 'ARTIFACT_ACCESS_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:artifact"' in auth
    assert 'scheme.lower() != "dpop"' in auth
    assert "verify_dpop_proof" in auth
    assert "deployment.bundle_sha256" in auth
    assert "deployment.bundle_size" in auth
    assert 'os.getenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR")' in artifacts
    assert "verify_bundle_structure" in artifacts
    assert "required_install_mode=INSTALL_MODE_UPDATE" in artifacts


def test_legacy_system_agent_token_is_not_accepted_by_artifact_endpoint_contract():
    router = (ROOT / "backend/service1/routers/clientflow_update.py").read_text()
    legacy_downloader = (ROOT / "client/runtime/clientflow_runtime/release_download.py").read_text()
    assert 'Authorization: DPoP' in (ROOT / "backend/service1/clientflow_artifact_auth.py").read_text()
    assert '"Authorization": f"Bearer {transport.access_token()}"' in legacy_downloader
    assert "download_clientflow_release_artifact" in router


def test_publication_is_explicit_immutable_and_refuses_byte_replacement():
    source = (ROOT / "scripts/publish_clientflow_release.py").read_text()
    assert "--publish-release" in source
    assert "--expected-bundle-sha256" in source
    assert "--expected-approval-reference" in source
    assert "--expected-source-commit" in source
    assert "verify_bundle(" in source
    assert "required_install_mode=INSTALL_MODE_UPDATE" in source
    assert "os.link(temporary, destination" in source
    assert "Artifact-ID er allerede publiceret med andre bytes" in source
