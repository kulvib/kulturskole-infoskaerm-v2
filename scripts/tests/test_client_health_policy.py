from types import SimpleNamespace

from service1.client_health_policy import (
    build_client_health_issues,
    build_client_health_issues_for_principal,
    principal_can_view_client_health,
)


def _client(**values):
    defaults = {
        "chrome_color": "green",
        "chrome_status": "Browser kører",
        "display_resolution_status": "applied",
        "display_resolution_error": None,
        "livestream_last_error": None,
        "ubuntu_update_status": "ready",
        "ubuntu_update_error": None,
        "firmware_update_status": "ready",
        "firmware_update_error": None,
        "client_update_status": "ready",
        "client_update_error": None,
        "local_management_status": "ready",
        "local_management_error": None,
        "desktop_lockdown_status": "applied",
        "time_sync_status": "ok",
        "service_clientflow_status": "active",
        "service_calendar_status": "active",
        "service_browser_guard_status": "active",
        "service_remote_desktop_status": "active",
        "service_remote_terminal_status": "active",
        "service_admin_terminal_status": "active",
        "service_livestream_status": "inactive",
        "service_selfupdate_status": "active",
        "service_ubuntu_update_status": "active",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_healthy_or_offline_like_state_does_not_invent_faults():
    assert build_client_health_issues(_client()) == []


def test_admin_actionable_and_superadmin_only_issues_are_classified():
    issues = build_client_health_issues(
        _client(
            chrome_color="red",
            chrome_status="Browser Guard kunne ikke starte Chrome",
            ubuntu_update_status="failed",
            ubuntu_update_error="apt transaction failed",
        )
    )
    by_code = {issue["code"]: issue for issue in issues}
    assert by_code["browser_runtime_error"]["required_role"] == "admin"
    assert by_code["ubuntu_update_error"]["required_role"] == "superadmin"
    assert "apt transaction failed" in by_code["ubuntu_update_error"]["message"]


def test_explicit_service_failure_is_reported_but_idle_livestream_is_not_part_of_policy():
    issues = build_client_health_issues(_client(service_browser_guard_status="failed"))
    assert [issue["code"] for issue in issues] == ["service_service_browser_guard_status_error"]


def test_all_canonical_operator_failures_are_classified_without_truncation():
    issues = build_client_health_issues(
        _client(
            firmware_update_status="error",
            firmware_update_error="fwupd failed",
            service_calendar_status="failed",
            service_admin_terminal_status="failed",
            service_livestream_status="failed",
            service_selfupdate_status="failed",
            service_ubuntu_update_status="failed",
        )
    )
    by_code = {issue["code"]: issue for issue in issues}
    assert by_code["firmware_update_error"]["required_role"] == "superadmin"
    assert "service_service_calendar_status_error" in by_code
    assert "service_service_admin_terminal_status_error" in by_code
    assert "service_service_livestream_status_error" in by_code
    assert "service_service_selfupdate_status_error" in by_code
    assert "service_service_ubuntu_update_status_error" in by_code
    assert len(issues) == 6


def test_health_details_are_exposed_only_to_admin_and_superadmin():
    admin = SimpleNamespace(is_admin=True, is_superadmin=False)
    superadmin = SimpleNamespace(is_admin=False, is_superadmin=True)
    viewer = SimpleNamespace(is_admin=False, is_superadmin=False, role="viewer")
    user = SimpleNamespace(is_admin=False, is_superadmin=False, role="bruger")
    client_principal = SimpleNamespace(is_admin=False, is_superadmin=False, role="client")
    failing = _client(service_calendar_status="failed")

    assert principal_can_view_client_health(admin) is True
    assert principal_can_view_client_health(superadmin) is True
    assert principal_can_view_client_health(viewer) is False
    assert principal_can_view_client_health(user) is False
    assert principal_can_view_client_health(client_principal) is False
    assert build_client_health_issues_for_principal(failing, admin)
    assert build_client_health_issues_for_principal(failing, superadmin)
    assert build_client_health_issues_for_principal(failing, viewer) == []
    assert build_client_health_issues_for_principal(failing, user) == []
    assert build_client_health_issues_for_principal(failing, client_principal) == []
