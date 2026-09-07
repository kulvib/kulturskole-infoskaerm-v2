from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_token_boundary_restores_only_retained_domains():
    source = _read("service1/routers/client_auth_compat.py")
    shared = _read("service1/shared_domain.py")

    assert 'SHARED_DOMAINS = frozenset({"status", "display", "system"})' in shared
    assert 'if body.domain in SHARED_DOMAINS' in source
    assert 'if body.domain == "livestream"' in source
    assert '"terminal"' not in shared.split("SHARED_DOMAINS", 1)[1].split("\n", 1)[0]
    assert '"remote_desktop"' not in shared.split("SHARED_DOMAINS", 1)[1].split("\n", 1)[0]


def test_shared_agent_routes_match_installed_1200_contract():
    source = _read("service1/routers/shared_domain.py")

    for domain in ("status", "display", "system"):
        assert f'@router.put("/{domain}-agent/clients/{{client_id}}/status")' in source
    for domain in ("display", "system"):
        for action in ("renew", "complete", "fail"):
            assert f'/{domain}-agent/clients/{{client_id}}/commands/{{command_id}}/{action}' in source
        assert f'@router.post("/{domain}-agent/clients/{{client_id}}/commands/claim")' in source

    assert '/livestream-agent/' not in source
    assert '/terminal-agent/' not in source
    assert '/remote-desktop-agent/' not in source


def test_shared_command_queue_never_claims_livestream():
    source = _read("service1/shared_domain.py")

    assert 'COMMAND_DOMAINS = frozenset({"display", "system"})' in source
    assert 'ClientCommand.domain == domain' in source
    assert '_validate_domain(credential.domain, commands=True)' in source


def test_shared_tokens_are_bound_to_domain_client_credential_and_version():
    source = _read("service1/shared_domain.py")

    for marker in (
        '"principal": "client_domain"',
        '"client_id": credential.client_id',
        '"credential_id": credential.id',
        '"domain": credential.domain',
        '"token_version": credential.token_version',
        'audience=f"clientflow-domain:{domain}"',
        'credential.token_version != int(claims["token_version"])',
    ):
        assert marker in source


def test_main_mounts_shared_domain_router():
    source = _read("service1/main.py")
    assert 'from .routers.shared_domain import router as shared_domain_router' in source
    assert 'app.include_router(shared_domain_router, prefix="/api")' in source


def test_client_command_model_matches_canonical_shared_vocabulary():
    source = _read("service1/client_domain_models.py")

    assert 'class ClientCommand(SQLModel, table=True):' in source
    assert 'domain IN (\'display\',\'system\')' in source
    assert "'queued','claimed','succeeded','failed','expired','cancelled'" in source
    for field in (
        "claim_token_hash",
        "claimed_by_credential_id",
        "lease_expires_at",
        "attempt_count",
        "max_attempts",
        "completed_at",
    ):
        assert field in source

def test_shared_agent_token_preserves_zero_token_version():
    source = (ROOT / "service1" / "shared_domain.py").read_text(encoding="utf-8")
    assert 'credential.token_version != int(claims["token_version"])' in source
    assert 'claims.get("token_version") or -1' not in source

