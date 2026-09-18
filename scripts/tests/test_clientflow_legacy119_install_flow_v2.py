from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "client/bootstrap"
COMMON = BOOTSTRAP / "clientflow_bootstrap_common.py"
FACTORY = BOOTSTRAP / "clientflow-factory-prepare"
CUSTOMER = BOOTSTRAP / "clientflow-fresh-install"
USB_START = BOOTSTRAP / "usb/01_START_CLIENTFLOW_USB.sh"
USB_BUILDER = ROOT / "scripts/build_clientflow_usb_installer.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_factory_flow_preserves_legacy_customer_handoff_before_reboot():
    source = FACTORY.read_text(encoding="utf-8")
    body = source[source.index("def factory_prepare"):source.index("def main")]
    order = [
        'configure_network_interactive("klient-/factory-klargøring")',
        "prompt_client_name_confirmed(existing)",
        "write_factory_state(client_name=client_name, operator_user=operator, handoff_ready=False)",
        "provision_factory_human_accounts()",
        "prepare_factory_graphical_login()",
        "_install_customer_launcher(KIOSK_USER)",
        "install_customer_launcher_trust_helper(KIOSK_USER)",
        "install_customer_activation_sudoers()",
        "remove_desktop_install_icons(operator)",
        "forget_saved_networks()",
        "validate_factory_handoff(client_name=client_name, operator_user=operator)",
        'confirmed_reboot("klient klargøring gennemført", seconds=5)',
    ]
    positions = [body.index(token) for token in order]
    assert positions == sorted(positions)
    assert "01 Klient klargøring.desktop" in source
    assert "02 Aktiver ClientFlow.desktop" in source
    assert '"sudo -n /usr/local/lib/clientflow-bootstrap/clientflow-fresh-install; "' in source
    assert "cfadmin-password sættes først efter en gyldig backend-claim" not in source


def test_factory_cleanup_deletes_all_saved_shipping_network_profiles_fail_closed():
    source = COMMON.read_text(encoding="utf-8")
    cleanup = source[source.index("def forget_saved_networks"):source.index("def validate_factory_handoff")]
    assert '"wifi", "802-11-wireless", "ethernet", "802-3-ethernet", "gsm", "cdma", "vpn", "wireguard"' in cleanup
    assert '"connection", "delete", "uuid", connection_uuid' in cleanup
    assert "Gemte netværksprofiler findes stadig efter factory-cleanup" in cleanup
    factory = FACTORY.read_text(encoding="utf-8")
    body = factory[factory.index("def factory_prepare"):factory.index("def main")]
    assert body.index("forget_saved_networks()") < body.index("validate_factory_handoff(")



def test_product_resume_after_pending_crash_cannot_fall_back_to_old_manual_activation_path():
    source = CUSTOMER.read_text(encoding="utf-8")
    main = source[source.index("def main"):source.index('if __name__ == "__main__"')]
    product_resume = 'if existing is not None and load_factory_state() is not None:'
    assert product_resume in main
    product_pos = main.index(product_resume)
    customer_resume_pos = main.index("return _customer_install()", product_pos)
    old_manual_pos = main.index("activation_result = _activate_pending(existing)")
    assert product_pos < customer_resume_pos < old_manual_pos
    assert "approval waiter or the operator-confirmed reboot" in main

def test_customer_flow_matches_legacy_customer_order_and_removes_second_manual_activation_click():
    source = CUSTOMER.read_text(encoding="utf-8")
    body = source[source.index("def _customer_install"):source.index("def main")]
    assert body.index('configure_network_interactive("kundeaktivering")') < body.index("if existing is not None:")
    normal = body[body.index('    else:\n        phase("2/8 · Klientoplysninger")'):]
    order = [
        "prompt_locality()",
        "_interactive_bootstrap_binding()",
        "_download_exact_bundle(code, binding, directory)",
        "_cache_exact_bundle(downloaded, binding)",
        "_run_canonical_installer(",
        "remove_customer_activation_sudoers()",
        "cleanup_customer_launcher_trust_helper(KIOSK_USER)",
        "remove_desktop_install_icons(KIOSK_USER)",
        "_prepare_pre_activation_graphical_session()",
        "_install_activation_waiter()",
        'confirmed_reboot("kundeaktivering gennemført", seconds=5)',
    ]
    positions = [normal.index(token) for token in order]
    assert positions == sorted(positions)
    assert "Midlertidig bootstrap-netværksprofil UUID" not in source
    assert "CF-____-____-____" in source
    assert "kræves ikke et ekstra klik" in source
    assert "cfadmin er allerede defineret i 01 Klient klargøring" in source
    assert '"--factory-state"' in source


def test_cf_code_editor_matches_legacy_visible_contract_and_normalizes_paste():
    common = _load(COMMON, "clientflow_bootstrap_common_test")
    assert common.format_cf_code("") == "CF-____-____-____"
    assert common.format_cf_code("ab12 cd34 ef56") == "CF-AB12-CD34-EF56"
    assert common.final_cf_code("CF-ab12-cd34-ef56") == "CF-AB12-CD34-EF56"
    assert common.valid_cf_code("CF-AB12-CD34-EF56") is True
    assert common.valid_cf_code("CF-AB12-CD34") is False


def test_network_bootstrap_uses_interactive_secret_agent_and_exact_uuid_cleanup():
    source = COMMON.read_text(encoding="utf-8")
    connect = source[source.index("def _connect_wifi"):source.index("def configure_network_interactive")]
    cleanup = source[source.index("def forget_owned_connection"):source.index("def user_home")]
    assert '"--ask"' in connect
    assert '"password"' not in connect
    assert "_new_owned_connection(before, profile_name)" in connect
    assert '"connection", "delete", "uuid", connection_uuid' in cleanup
    assert 'current["name"] != expected_name or current["type"] != expected_type' in cleanup


def test_terminal_ux_keeps_legacy_network_help_and_visible_install_progress():
    common = COMMON.read_text(encoding="utf-8")
    assert "Denne fase kontrollerer altid kablet netværk først. Hvis Ethernet ikke virker, vises en WiFi-liste." in common
    assert 'print("[STATUS] NetworkManager-enheder")' in common
    assert 'print("[STATUS] IP-adresser")' in common
    customer = CUSTOMER.read_text(encoding="utf-8")
    assert "download:" in customer
    assert "Installationslinjer vises løbende nedenfor" in customer
    host = (ROOT / "client/release/lib/clientflow_release/host_bootstrap.py").read_text(encoding="utf-8")
    assert "visible=True" in host
    assert "almindelig apt-output vises under installationen" in host


def test_reboot_contract_is_confirmed_narrow_inhibitor_override_and_never_force():
    source = COMMON.read_text(encoding="utf-8")
    fn = source[source.index("def confirmed_reboot"):source.index("def install_persistent_bootstrap")]
    assert "Maskinen genstarter IKKE automatisk. Du skal bekræfte først." in fn
    assert 'input("Vil du genstarte nu? [j/N]: ")' in fn
    assert '[str(SYSTEMCTL), "--no-block", "--ignore-inhibitors", "reboot"]' in fn
    assert "timeout=10" in fn
    assert "--force" not in fn


def test_approval_waiter_retries_only_canonical_staged_activation_and_does_not_embed_frozen_domain_logic():
    source = CUSTOMER.read_text(encoding="utf-8")
    waiter = source[source.index("def _activation_wait"):source.index("def _factory_identity")]
    transaction = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    activate = transaction[transaction.index("def activate_release("):transaction.index("def rollback_release(")]
    assert "_canonical_staged_activation(release_id, approval)" in waiter
    assert "time.sleep(10)" in waiter
    assert "clientflow-first-activation.service" in source
    assert "first_activation_authorizer(layout)" in activate
    assert activate.index("first_activation_authorizer(layout)") < activate.index("return _activate_release(")
    for forbidden in ("remote_desktop", "livestream", "terminal_agent", "client_terminal"):
        assert forbidden not in waiter.lower()


def test_usb_builder_is_deterministic_and_packages_only_repo_owned_preclaim_bootstrap(tmp_path: Path):
    builder = _load(USB_BUILDER, "clientflow_usb_builder_test")
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    size_a, sha_a = builder.build(first)
    size_b, sha_b = builder.build(second)
    assert (size_a, sha_a) == (size_b, sha_b)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert names == {
            "00_START_HER_KORT.txt",
            "01_START_CLIENTFLOW_USB.sh",
            "PAYLOAD_SHA256SUMS.txt",
            "README_START_HER.txt",
            "USB_SHA256SUMS.txt",
            "payload/clientflow-factory-prepare",
            "payload/clientflow-fresh-install",
            "payload/clientflow_bootstrap_common.py",
            "payload/planiq-display-mark.png",
        }
        assert b"clientflow-factory-prepare" in archive.read("PAYLOAD_SHA256SUMS.txt")
        assert archive.read("payload/planiq-display-mark.png") == (
            ROOT / "frontend/public/brand/planiq-display/planiq-display-mark.png"
        ).read_bytes()


def test_usb_start_has_no_mutable_release_download_authority():
    source = USB_START.read_text(encoding="utf-8")
    assert "sha256sum --check --strict PAYLOAD_SHA256SUMS.txt" in source
    assert "clientflow-factory-prepare\" --usb-preflight" in source
    assert "curl " not in source
    assert "wget " not in source
    assert "github.com" not in source.lower()
    assert "onrender.com" not in source.lower()
    assert "api.display.planiq.dk" not in source.lower()



def test_claim_retry_and_crash_resume_are_explicit_fail_closed_contracts():
    helper = CUSTOMER.read_text(encoding="utf-8")
    cli = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    customer = helper[helper.index("def _customer_install"):helper.index("def main", helper.index("def _customer_install"))]
    runner = helper[helper.index("def _run_canonical_installer"):helper.index("def _materialize_installer")]
    cache = helper[helper.index("def _cache_exact_bundle"):helper.index("def _cached_exact_bundle")]

    assert 'PENDING_BUNDLE = BOOTSTRAP_ROOT / "pending-approved-bundle.tar"' in helper
    assert 'FIRST_CLAIM_REJECTED_EXIT = 20' in helper
    assert 'FIRST_CLAIM_REJECTED_EXIT = 20' in cli
    assert 'raise FirstClaimRejected(exc.status_code, exc.detail) from exc' in cli
    assert '"status": "first_claim_rejected"' in cli
    assert 'return FIRST_CLAIM_REJECTED_EXIT' in cli

    # A definite pre-commit rejection clears only the cached exact artifact and
    # returns to the CF-code loop; name/locality stay outside that loop.
    assert 'if result == FIRST_CLAIM_REJECTED_EXIT:' in customer
    rejection = customer[customer.index('if result == FIRST_CLAIM_REJECTED_EXIT:'):customer.index('if result != 0:', customer.index('if result == FIRST_CLAIM_REJECTED_EXIT:'))]
    assert '_clear_cached_bundle()' in rejection
    assert 'continue' in rejection
    assert customer.index('locality = prompt_locality()') < customer.index('while True:')

    # Ambiguous post-request failures remain resumable with the same exact
    # locally verified artifact and never ask for a consumed one-time code.
    resume = customer[customer.index('if existing is not None:'):customer.index('else:', customer.index('if existing is not None:'))]
    assert '_resume_binding(existing)' in resume
    assert '_cached_exact_bundle(binding)' in resume
    assert 'authorities=None' in resume
    assert '_interactive_bootstrap_binding()' not in resume

    assert 'os.fchmod(fd, 0o400)' in cache
    assert 'digest.hexdigest() != expected_sha' in cache
    assert 'os.fsync(output.fileno())' in cache
    assert 'os.replace(temporary, PENDING_BUNDLE)' in cache
    assert 'subprocess.run(command, input=authorities, check=False)' in runner



def test_privileged_desktop_write_does_not_follow_precreated_symlink(monkeypatch, tmp_path: Path):
    common = _load(COMMON, "clientflow_bootstrap_common_symlink_test")
    monkeypatch.setattr(common, "validate_local_user", lambda value: value)
    monkeypatch.setattr(
        common.pwd,
        "getpwnam",
        lambda _user: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(tmp_path)),
    )
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("KEEP", encoding="utf-8")
    target = desktop / "01 Klient klargøring.desktop"
    target.symlink_to(victim)

    common._write_user_file_no_follow(target, "SAFE\n", user="tester", mode=0o755)

    assert victim.read_text(encoding="utf-8") == "KEEP"
    assert target.is_file()
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "SAFE\n"


def test_desktop_directory_rejects_xdg_symlink_escape(monkeypatch, tmp_path: Path):
    common = _load(COMMON, "clientflow_bootstrap_common_desktop_escape_test")
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    candidate = home / "Desktop"
    candidate.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(common, "validate_local_user", lambda value: value)
    monkeypatch.setattr(
        common.pwd,
        "getpwnam",
        lambda _user: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(home)),
    )

    try:
        common._prepare_desktop_directory("tester", candidate)
    except common.BootstrapError as exc:
        assert "uden for brugerens home" in str(exc) or "ikke et reelt katalog" in str(exc)
    else:  # pragma: no cover - security regression guard
        raise AssertionError("XDG Desktop symlink escape blev ikke afvist")


def test_failed_clientflow_owned_wifi_profile_is_cleaned_before_retry():
    source = COMMON.read_text(encoding="utf-8")
    network = source[source.index("def configure_network_interactive"):source.index("def forget_owned_connection")]
    assert network.count("forget_owned_connection(marker)") == 2
    assert "Den ClientFlow-oprettede WiFi-profil blev fjernet igen" in network


def test_successful_first_activation_removes_only_exact_bootstrap_artifacts():
    source = CUSTOMER.read_text(encoding="utf-8")
    cleanup = source[source.index("def _cleanup_completed_bootstrap"):source.index("def _activation_wait")]
    assert "BOOTSTRAP_LAUNCHERS" in cleanup
    assert "FACTORY_STATE" in cleanup
    assert "USB_STATE" in cleanup
    assert "PENDING_BUNDLE" in cleanup
    assert "BOOTSTRAP_FILES" in cleanup
    assert ".rmdir()" in cleanup
    assert "rmtree" not in cleanup
    waiter = source[source.index("def _activation_wait"):source.index("def _factory_identity")]
    assert waiter.count("_cleanup_completed_bootstrap()") == 2


def test_usb_start_verifies_top_level_and_payload_manifests_before_sudo_install():
    source = USB_START.read_text(encoding="utf-8")
    top = source.index("sha256sum --check --strict USB_SHA256SUMS.txt")
    payload = source.index("sha256sum --check --strict PAYLOAD_SHA256SUMS.txt")
    install = source.index("sudo install -d")
    assert top < payload < install
