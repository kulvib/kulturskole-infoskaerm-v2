from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pending_client_publishes_readiness_only_after_real_reboot_and_gui_session() -> None:
    bootstrap = read("client/bootstrap/clientflow-fresh-install")
    publisher = bootstrap.index("def _publish_post_reboot_approval_readiness")
    waiter = bootstrap.index("def _activation_wait")
    assert publisher < waiter
    assert 'if boot_id == preclaim_boot_id:' in bootstrap
    assert "_canonical_kiosk_session() is None" in bootstrap[publisher:waiter]
    assert "not _preactivation_gui_active()" in bootstrap[publisher:waiter]
    assert "not _post_reboot_package_manager_healthy()" in bootstrap[publisher:waiter]
    assert "_publish_post_reboot_approval_readiness(state)" in bootstrap[waiter:]
    assert bootstrap[waiter:].index("_publish_post_reboot_approval_readiness(state)") < bootstrap[waiter:].index(
        "_canonical_staged_activation(release_id, approval)"
    )


def test_backend_readiness_endpoint_does_not_mint_pending_runtime_token() -> None:
    compat = read("backend/service1/routers/client_auth_compat.py")
    clients = read("backend/service1/routers/clients.py")
    assert '@router.post("/client-auth/approval-readiness")' in compat
    assert 'str(client.status or "").lower() != "pending"' in compat
    assert 'credential.domain != "status"' in compat
    assert 'observed_state="approval_ready"' in compat
    assert 'post_reboot_reboot_required' in compat
    assert 'client.enrollment_token_id is not None' in clients
    assert "_approval_readiness_from_status_row" in clients
    assert "Klienten afventer post-reboot readiness" in clients


def test_control_room_disables_approval_until_readiness_projection_exists() -> None:
    frontend = read("frontend/src/pages/ClientInfoPage.jsx")
    assert "const isApprovalReady = Boolean(client.approval_ready_at);" in frontend
    assert "disabled={isApproving || isRemoving || !isApprovalReady}" in frontend
    assert '"Afventer reboot"' in frontend


def test_host_update_is_non_removing_upgrade_and_chrome_is_not_live_updated() -> None:
    host = read("client/release/lib/clientflow_release/host_bootstrap.py")
    assert '"--with-new-pkgs",' in host
    assert '"upgrade",' in host
    assert '"dist-upgrade"' not in host
    assert '"full-upgrade"' not in host
    # Chrome stays release-owned; host bootstrap must not add Google repositories
    # or install an unpinned browser from the network.
    assert "google-chrome" not in host
    assert "dl.google.com" not in host
