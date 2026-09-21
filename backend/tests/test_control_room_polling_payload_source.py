from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_control_room_summary_is_narrow_and_reuses_canonical_list_projection() -> None:
    models = _read("backend/service1/models.py")
    clients = _read("backend/service1/routers/clients.py")

    assert "class ClientControlRoomListRead(ClientBase):" in models
    assert 'router.get("/clients/control-room-summary", response_model=List[ClientControlRoomListRead])' in clients
    assert "return get_clients_for_my_organization(session=session, user=user)" in clients
    assert "return get_clients(session=session, user=user)" in clients

    # Detail-only fields must stay out of the list response model.
    block = models.split("class ClientControlRoomListRead(ClientBase):", 1)[1].split("class ClientRead(ClientBase):", 1)[0]
    assert "presence: ClientPresenceRead" in block
    assert "pending_chrome_action" in block
    assert "pending_reboot" in block
    assert "pending_shutdown" in block
    assert "pending_os_update" in block
    assert "organization_id" in block
    assert "kiosk_url" not in block
    assert "ubuntu_update_status" not in block
    assert "display_detected_outputs" not in block
