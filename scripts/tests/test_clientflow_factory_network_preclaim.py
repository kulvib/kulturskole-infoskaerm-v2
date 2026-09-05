from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import cli, enrollment, network_bootstrap  # noqa: E402


BOOTSTRAP_UUID = "11111111-2222-4333-8444-555555555555"


def test_explicit_client_name_and_locality_contract() -> None:
    assert network_bootstrap.normalize_client_name("  Viborg 12  ") == "Viborg 12"
    assert network_bootstrap.normalize_locality("  Hovedbibliotek  ") == "Hovedbibliotek"
    assert network_bootstrap.normalize_locality("  ") is None

    with pytest.raises(network_bootstrap.NetworkBootstrapError, match="eksplicit klientnavn"):
        network_bootstrap.normalize_client_name("")
    with pytest.raises(network_bootstrap.NetworkBootstrapError, match="ugyldigt"):
        network_bootstrap.normalize_client_name("bad\nname")


def test_preclaim_network_requires_connection_and_backend_health(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(network_bootstrap, "_require_networkmanager", lambda: calls.append("nm"))
    monkeypatch.setattr(
        network_bootstrap,
        "_device_rows",
        lambda: [
            {
                "device": "enp1s0",
                "type": "ethernet",
                "state": "connected",
                "connection": "Wired connection 1",
            }
        ],
    )
    monkeypatch.setattr(
        network_bootstrap,
        "_probe_backend_health",
        lambda backend_url, **_kwargs: calls.append(f"health:{backend_url}"),
    )

    result = network_bootstrap.ensure_preclaim_network_readiness(
        "https://api.display.planiq.dk"
    )

    assert calls == ["nm", "health:https://api.display.planiq.dk"]
    assert result["backend_health"] == "ok"
    assert result["bootstrap_connection"] is None
    assert result["connected_devices"][0]["device"] == "enp1s0"


def test_preclaim_network_rejects_no_active_connection(monkeypatch) -> None:
    monkeypatch.setattr(network_bootstrap, "_require_networkmanager", lambda: None)
    monkeypatch.setattr(
        network_bootstrap,
        "_device_rows",
        lambda: [
            {
                "device": "wlp2s0",
                "type": "wifi",
                "state": "disconnected",
                "connection": "",
            }
        ],
    )
    monkeypatch.setattr(
        network_bootstrap,
        "_probe_backend_health",
        lambda *_args, **_kwargs: pytest.fail("health must not run without connectivity"),
    )

    with pytest.raises(network_bootstrap.NetworkBootstrapError, match="Ingen aktiv"):
        network_bootstrap.ensure_preclaim_network_readiness(
            "https://api.display.planiq.dk"
        )


def test_only_active_explicit_wifi_or_ethernet_can_be_marked(monkeypatch) -> None:
    marker = {"uuid": BOOTSTRAP_UUID, "type": "wifi", "name": "Factory WiFi"}
    monkeypatch.setattr(network_bootstrap, "_require_networkmanager", lambda: None)
    monkeypatch.setattr(
        network_bootstrap,
        "_device_rows",
        lambda: [
            {
                "device": "wlp2s0",
                "type": "wifi",
                "state": "connected",
                "connection": "Factory WiFi",
            }
        ],
    )
    monkeypatch.setattr(network_bootstrap, "_probe_backend_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(network_bootstrap, "_active_connections", lambda: {BOOTSTRAP_UUID: marker})

    result = network_bootstrap.ensure_preclaim_network_readiness(
        "https://api.display.planiq.dk",
        bootstrap_connection_uuid=BOOTSTRAP_UUID,
    )
    assert result["bootstrap_connection"] == marker

    monkeypatch.setattr(
        network_bootstrap,
        "_active_connections",
        lambda: {
            BOOTSTRAP_UUID: {
                "uuid": BOOTSTRAP_UUID,
                "type": "vpn",
                "name": "Do not own",
            }
        },
    )
    with pytest.raises(network_bootstrap.NetworkBootstrapError, match="WiFi/Ethernet"):
        network_bootstrap.ensure_preclaim_network_readiness(
            "https://api.display.planiq.dk",
            bootstrap_connection_uuid=BOOTSTRAP_UUID,
        )


def test_cleanup_deletes_only_exact_recorded_profile(monkeypatch) -> None:
    marker = {"uuid": BOOTSTRAP_UUID, "type": "wifi", "name": "Factory WiFi"}
    snapshots = [
        {
            BOOTSTRAP_UUID: marker,
            "99999999-8888-4777-8666-555555555555": {
                "uuid": "99999999-8888-4777-8666-555555555555",
                "type": "ethernet",
                "name": "Customer LAN",
            },
        },
        {
            "99999999-8888-4777-8666-555555555555": {
                "uuid": "99999999-8888-4777-8666-555555555555",
                "type": "ethernet",
                "name": "Customer LAN",
            }
        },
    ]
    calls: list[list[str]] = []
    monkeypatch.setattr(network_bootstrap, "_require_networkmanager", lambda: None)
    monkeypatch.setattr(network_bootstrap, "_all_connections", lambda: snapshots.pop(0))
    monkeypatch.setattr(
        network_bootstrap,
        "_run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(stdout="", returncode=0),
    )

    result = network_bootstrap.cleanup_bootstrap_connection(marker)

    assert result == {"status": "deleted", "uuid": BOOTSTRAP_UUID}
    assert calls == [
        [str(network_bootstrap.NMCLI), "connection", "delete", "uuid", BOOTSTRAP_UUID]
    ]


def test_cleanup_refuses_uuid_reuse_or_profile_drift(monkeypatch) -> None:
    marker = {"uuid": BOOTSTRAP_UUID, "type": "wifi", "name": "Factory WiFi"}
    deleted: list[list[str]] = []
    monkeypatch.setattr(network_bootstrap, "_require_networkmanager", lambda: None)
    monkeypatch.setattr(
        network_bootstrap,
        "_all_connections",
        lambda: {
            BOOTSTRAP_UUID: {
                "uuid": BOOTSTRAP_UUID,
                "type": "wifi",
                "name": "Customer WiFi",
            }
        },
    )
    monkeypatch.setattr(network_bootstrap, "_run", lambda command, **_kwargs: deleted.append(command))

    with pytest.raises(network_bootstrap.NetworkBootstrapError, match="matcher ikke længere"):
        network_bootstrap.cleanup_bootstrap_connection(marker)
    assert deleted == []


def test_pending_state_preserves_explicit_identity_and_network_marker() -> None:
    binding = {
        "release_id": "clientflow-1.3.18-seq-1219",
        "version": "1.3.18",
        "release_sequence": 1219,
        "bundle_sha256": "a" * 64,
        "bundle_size": 123,
        "release_approval_reference": "approval/ref",
        "release_candidate_sha256": "b" * 64,
        "source_commit": "c" * 40,
    }
    marker = {"uuid": BOOTSTRAP_UUID, "type": "wifi", "name": "Factory WiFi"}
    final = cli._pending_manual_activation_state(
        {"bootstrap_user": "ubuntu-bootstrap"},
        binding=binding,
        install_id="11111111-1111-4111-8111-111111111111",
        backend_url="https://api.display.planiq.dk",
        kiosk_user="clientflow-kiosk",
        client_name="Viborg 12",
        locality="Hovedbibliotek",
        bootstrap_network_connection=marker,
    )
    assert final["client_name"] == "Viborg 12"
    assert final["locality"] == "Hovedbibliotek"
    assert final["bootstrap_network_connection"] == marker


def test_enrollment_host_facts_include_bounded_wifi_lan_projection(monkeypatch) -> None:
    network = {
        "wifi_ip_address": "192.0.2.10",
        "wifi_mac_address": "00:11:22:33:44:55",
        "lan_ip_address": "198.51.100.10",
        "lan_mac_address": "66:77:88:99:aa:bb",
    }
    monkeypatch.setattr(enrollment, "collect_network_facts", lambda: network)
    facts = enrollment.host_facts()
    for key, value in network.items():
        assert facts[key] == value


def test_install_order_is_network_ready_before_enrollment_authorities_and_claim() -> None:
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index("def install_fresh(")
    end = source.index("def _common_transaction_parser", start)
    install = source[start:end]
    host = install.index("ensure_preclaim_host_readiness(")
    network = install.index("ensure_preclaim_network_readiness(")
    authorities = install.index("_fresh_install_authorities(args)")
    state_mutation = install.index("ensure_real_directory(layout.state_root")
    claim = install.index("response = claim(")
    assert host < network < authorities < state_mutation < claim
    assert 'name=client_name' in install
    assert 'locality=locality' in install


def test_install_parser_exposes_only_explicit_bootstrap_profile_marker() -> None:
    args = cli.build_parser().parse_args(
        [
            "install",
            "--bundle",
            "/tmp/bundle.tar",
            "--expected-bundle-sha256",
            "a" * 64,
            "--backend-url",
            "https://api.display.planiq.dk",
            "--name",
            "Viborg 12",
            "--locality",
            "Hovedbibliotek",
            "--bootstrap-network-connection-uuid",
            BOOTSTRAP_UUID,
        ]
    )
    assert args.name == "Viborg 12"
    assert args.locality == "Hovedbibliotek"
    assert args.bootstrap_network_connection_uuid == BOOTSTRAP_UUID
