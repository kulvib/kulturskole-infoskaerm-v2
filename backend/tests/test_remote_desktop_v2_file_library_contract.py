from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "service1/routers/remote_desktop_v2.py"


def source() -> str:
    return BROKER.read_text(encoding="utf-8")


def test_file_paths_reject_absolute_input_before_normalization():
    text = source()
    helper = text[text.index("def _safe_relative_path"):text.index("def _join_relative")]
    assert 'raw = str(value or "").replace("\\\\", "/")' in helper
    assert 'if raw.startswith("/"):' in helper
    assert '.strip("/")' not in helper


def test_hidden_file_contract_is_round_tripped_and_filtered():
    text = source()
    assert "show_hidden: bool = False" in text
    assert 'hidden = name.startswith(".")' in text
    assert "if hidden and not show_hidden:" in text
    assert '"hidden": hidden' in text
    assert '"show_hidden": show_hidden' in text


def test_file_channel_reconnect_fails_and_clears_pending_state():
    text = source()
    assert "async def _fail_file_channel_state" in text
    assert "_pop_session_operation_state(session_id)" in text
    assert 'if channel_name == "files" and old and old.websocket is not channel.websocket:' in text
    assert 'if channel_name == "files" and removed_current:' in text
    assert '"type": "file_error"' in text


def test_upload_http_response_is_final_agent_ack_and_batch_limit_is_server_side():
    text = source()
    endpoint = text[text.index('@router.post("/remote-desktop/clients/{client_id}/files/upload-multiple")'):text.index('@router.post("/remote-desktop/clients/{client_id}/files/upload")')]
    assert "_parse_upload_conflict_strategies" in endpoint
    assert "total_batch > MAX_TRANSFER_BYTES" in endpoint
    assert '"paths": uploaded_paths' in endpoint
    assert "uploadet og kvitteret af Remote Desktop-agenten" in endpoint
    assert '"type": "file_upload_result"' not in endpoint
    assert "del conflict_strategies_json" not in endpoint


def test_download_transfer_is_deleted_after_http_response_and_browser_disconnect():
    text = source()
    assert "def _release_transfer" in text
    assert "background=BackgroundTask(_release_transfer, transfer_id)" in text
    assert "if transfer.session_id == session_id:" in text
    assert "_release_transfer(transfer_id)" in text


def test_upload_filename_is_validated_without_silent_rewriting():
    text = source()
    helper = text[text.index("def _safe_filename"):text.index("def _safe_relative_path")]
    assert "_SAFE_NAME.fullmatch(name)" in helper
    assert "re.sub(" not in helper
    assert 'name in {".", ".."}' in helper
