from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_main_uses_only_v2_remote_desktop_router():
    source = read("service1/main.py")
    assert "from .routers.remote_desktop_v2 import router as remote_desktop_v2_router" in source
    assert "from .routers.remote_desktop_auth import router as remote_desktop_auth_router" in source
    assert "app.include_router(remote_desktop_v2_router, prefix=\"/api\")" in source
    assert "app.include_router(remote_desktop_auth_router, prefix=\"/api\")" in source
    assert "from .routers.remote_desktop import router as remote_desktop_router" not in source
    assert "app.include_router(remote_desktop_router" not in source
    assert not (ROOT / "service1/routers/remote_desktop.py").exists()


def test_remote_desktop_auth_is_private_and_does_not_use_shared_domain_storage():
    domain = read("service1/remote_desktop_v2.py")
    models = read("service1/remote_desktop_v2_models.py")
    auth_router = read("service1/routers/remote_desktop_auth.py")
    broker = read("service1/routers/remote_desktop_v2.py")
    combined = "\n".join((domain, models, auth_router, broker))

    assert 'DOMAIN = "remote_desktop"' in domain
    assert "CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64" in domain
    assert '"aud": f"clientflow-domain:{DOMAIN}"' in domain
    assert '"scope": f"clientflow:{DOMAIN}"' in domain
    assert '@router.post("/remote-desktop-auth/token")' in auth_router
    assert '"/remote-desktop-agent/clients/{client_id}/control/ws"' in broker
    assert '"/remote-desktop-agent/clients/{client_id}/files/ws"' in broker
    assert '"/remote-desktop-agent/clients/{client_id}/status"' in broker
    assert "client_domain_credential" not in combined
    assert "client_domain_status" not in combined
    assert "/api/client-auth/token" not in combined
    assert "terminal_v2" not in combined
    assert "livestream_v2" not in combined


def test_remote_desktop_models_own_client_credential_status_and_event_fk():
    source = read("service1/remote_desktop_v2_models.py")
    assert '__tablename__ = "remote_desktop_client"' in source
    assert '__tablename__ = "remote_desktop_credential"' in source
    assert '__tablename__ = "remote_desktop_agent_status"' in source
    assert 'foreign_key="remote_desktop_client.id"' in source
    assert 'foreign_key="remote_desktop_credential.id"' in source
    session_source = read("service1/remote_desktop_session_models.py")
    assert '__tablename__ = "remote_desktop_session"' in session_source
    assert '__tablename__ = "remote_desktop_session_event"' in session_source
    assert 'foreign_key="remote_desktop_credential.id"' in session_source


def test_migration_preserves_ids_rehomes_fks_and_deletes_shared_rd_rows():
    source = read("migrations/versions/20260817_46a_remote_desktop_v2_isolation.py")
    assert 'down_revision = "20260816_45a_terminal_client"' in source
    assert '"remote_desktop_client"' in source
    assert '"remote_desktop_credential"' in source
    assert '"remote_desktop_agent_status"' in source
    assert "FROM client_domain_credential\n        WHERE domain = 'remote_desktop'" in source
    assert '"remote_desktop_session_event_credential_id_fkey"' in source
    assert '"remote_desktop_credential"' in source
    assert '"remote_desktop_session_client_id_fkey"' in source
    assert '"remote_desktop_client"' in source
    assert "DELETE FROM client_domain_status WHERE domain = 'remote_desktop'" in source
    assert "DELETE FROM client_domain_credential WHERE domain = 'remote_desktop'" in source
    assert "historical_claims" in source
    assert "UPDATE client_command" not in source


def test_browser_contract_is_retained_but_agent_contract_is_v2():
    source = read("service1/routers/remote_desktop_v2.py")
    assert '@router.websocket("/remote-desktop/browser/{client_id}/ws")' in source
    assert '@router.post("/remote-desktop/clients/{client_id}/files/upload-multiple")' in source
    assert '@router.get("/remote-desktop/clients/{client_id}/files/browser-download/{transfer_id}")' in source
    assert '"type": "session_open"' in source
    assert '"type": "session_close"' in source
    assert '"file_upload_offer"' in source
    assert '"file_upload_chunk"' in source
    assert '"file_upload_complete"' in source


def test_render_declares_private_remote_desktop_signing_key():
    render = (ROOT.parent / "render.yaml").read_text(encoding="utf-8")
    assert "CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64" in render
    assert "CLIENTFLOW_REMOTE_DESKTOP_TOKEN_ISSUER" in render
    assert "CLIENTFLOW_REMOTE_DESKTOP_TOKEN_TTL_SECONDS" in render


def test_schema_contract_and_migration_runner_advance_to_remote_desktop_head():
    contract = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'EXPECTED_HEAD_REVISION = "20260818_47a_client_activity"' in contract
    assert 'REVIEWED_REMOTE_DESKTOP_V2_REVISION = "20260817_46a_remote_desktop_v2"' in runner
    assert 'REVIEWED_CLIENT_ACTIVITY_REVISION = "20260818_47a_client_activity"' in runner
    assert "_without_remote_desktop_v2_schema" in runner


def test_file_list_errors_are_adapted_to_browser_contract():
    source = read("service1/routers/remote_desktop_v2.py")
    assert 'OperationExpectation("file_list_result", show_hidden=show_hidden)' in source
    assert 'queue[0].frontend_type == "file_list_result"' in source
    assert '"type": "file_list_result"' in source
    assert '"ok": False' in source


def test_live_remote_desktop_geometry_drives_input_not_stale_inventory():
    source = read("service1/routers/remote_desktop_v2.py")
    assert "screen_width: Optional[int] = None" in source
    assert "screen_height: Optional[int] = None" in source
    assert "browser.screen_width = live_width" in source
    assert "browser.screen_height = live_height" in source
    assert 'if not bool(payload.get("native", False)):' in source
    assert "width = browser.screen_width if browser else None" in source
    assert "height = browser.screen_height if browser else None" in source
    assert "_mouse_sequence(message, width, height)" in source


def test_shout_is_forwarded_only_over_private_v2_control_channel():
    source = read("service1/routers/remote_desktop_v2.py")
    assert 'if message_type == "shout":' in source
    assert '"type": "shout", "session_id": session_id' in source
    assert 'if message_type == "shout_result":' in source
    assert '"type": "shout_result"' in source
    assert "Shout out er ikke en del af den isolerede Remote Desktop v2-agent" not in source
