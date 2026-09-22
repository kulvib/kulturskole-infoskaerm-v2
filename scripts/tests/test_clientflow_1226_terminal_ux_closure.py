from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "client/bootstrap/clientflow_bootstrap_common.py"
FACTORY = ROOT / "client/bootstrap/clientflow-factory-prepare"
CUSTOMER = ROOT / "client/bootstrap/clientflow-fresh-install"
CLI = ROOT / "client/release/lib/clientflow_release/cli.py"


def test_1226_factory_terminal_copy_is_concise_without_changing_security_calls() -> None:
    common = COMMON.read_text(encoding="utf-8")
    factory = FACTORY.read_text(encoding="utf-8")

    assert 'input("Klientnavn: ")' in common
    assert 'input("Er dette korrekt? [j/n]: ")' in common
    assert 'print("Adminbrugeren oprettes som: cfadmin")' in common
    assert 'ok("cfadmin og clientflow-kiosk er oprettet og valideret")' in common
    assert "Password vises ikke, gemmes ikke i ClientFlow-state" not in common

    # The underlying security operations remain present even though their
    # implementation detail is no longer printed to the normal operator.
    for token in (
        "provision_factory_human_accounts()",
        "install_customer_launcher_trust_helper(KIOSK_USER)",
        "install_customer_activation_sudoers()",
        "validate_factory_handoff(client_name=client_name, operator_user=operator)",
    ):
        assert token in factory

    assert 'ok("02 Aktiver ClientFlow er oprettet hos kiosk-brugeren.")' in factory
    assert 'phase("5/6 · Glem factory-netværk")' in factory
    assert "Ingen client secret er oprettet endnu" not in factory


def test_1226_customer_terminal_copy_matches_reviewed_document() -> None:
    common = COMMON.read_text(encoding="utf-8")
    customer = CUSTOMER.read_text(encoding="utf-8")

    assert 'input("Lokation/rum (valgfri, Enter = tom): ")' in common
    assert "Koden vises som: CF-____-____-____" not in customer
    assert 'ok("CF-koden er accepteret.")' in customer
    assert 'phase("8/8 · Aktivering færdig")' in customer
    assert 'ok("Aktivering færdig. Klienten kan genstartes efter bekræftelse.")' in customer
    assert "kræves ikke et ekstra klik" not in customer


def test_1226_reboot_copy_is_lowercase_and_grammatically_correct() -> None:
    common = COMMON.read_text(encoding="utf-8")
    reboot = common[common.index("def confirmed_reboot"):common.index("def install_persistent_bootstrap")]

    assert 'input("Vil du genstarte nu? [j/n]: ")' in reboot
    assert 'unit = "sekund" if remaining == 1 else "sekunder"' in reboot
    assert 'print(f"Genstarter om {remaining} {unit}...")' in reboot
    assert '[str(SYSTEMCTL), "--no-block", "--check-inhibitors=no", "reboot"]' in reboot
    assert "--force" not in reboot


def test_1226_normal_usb_flow_suppresses_only_final_installer_json() -> None:
    customer = CUSTOMER.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")

    runner = customer[customer.index("def _run_canonical_installer"):customer.index("def _materialize_installer")]
    assert 'command.append("--suppress-result-json")' in runner
    assert "Installationslinjer vises løbende nedenfor" in runner

    assert 'install.add_argument("--suppress-result-json", action="store_true", help=argparse.SUPPRESS)' in cli
    assert 'if not (args.operation == "install" and getattr(args, "suppress_result_json", False)):' in cli
    # Direct CLI engineering use still reaches the canonical JSON printer when
    # the hidden bootstrap-only suppression flag is absent.
    assert 'print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))' in cli
