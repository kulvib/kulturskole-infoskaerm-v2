from types import SimpleNamespace

from service1.client_health_policy import build_client_health_issues


def _client(**values):
    defaults = {
        "chrome_color": "green",
        "chrome_status": "Browser kører",
        "display_resolution_status": "applied",
        "display_resolution_error": None,
        "livestream_last_error": None,
        "ubuntu_update_status": "ready",
        "ubuntu_update_error": None,
        "client_update_status": "ready",
        "client_update_error": None,
        "local_management_status": "ready",
        "local_management_error": None,
        "desktop_lockdown_status": "applied",
        "time_sync_status": "ok",
        "service_clientflow_status": "active",
        "service_browser_guard_status": "active",
        "service_remote_desktop_status": "active",
        "service_remote_terminal_status": "active",
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
