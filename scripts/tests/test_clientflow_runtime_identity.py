from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "clientflow-autoinstall-site/clientflow_clean_ubuntu_installer_v1_1_19.zip"


def load_resolver():
    with zipfile.ZipFile(INSTALLER) as outer:
        payload = outer.read("payload_clientflow_v1_0_0.tar.gz")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as inner:
        source = inner.extractfile("usr/local/lib/clientflow-root/clientflow_graphical_session.py").read()
    temp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
    temp.write(source); temp.close()
    spec = importlib.util.spec_from_file_location("clientflow_graphical_session_test", temp.name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class RuntimeIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_resolver()

    def test_xwayland_cmdline_keeps_display_and_cookie_together(self):
        display, auth = self.module.parse_xwayland_cmdline([
            "/usr/bin/Xwayland", ":2", "-rootless", "-auth", "/run/user/1001/.mutter-Xwaylandauth.test"
        ])
        self.assertEqual(display, ":2")
        self.assertEqual(auth, "/run/user/1001/.mutter-Xwaylandauth.test")

    def test_resolver_never_mixes_other_xwayland_display_with_active_cookie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            uid = os.getuid()
            proc = base / "proc"; runtime = base / f"run/user/{uid}"
            proc.mkdir(); runtime.mkdir(parents=True)
            active_auth = runtime / ".mutter-Xwaylandauth.active"; active_auth.write_text("active")
            stale_auth = runtime / ".mutter-Xwaylandauth.stale"; stale_auth.write_text("stale")

            def process(pid: int, ppid: int, argv: list[str]):
                folder = proc / str(pid); folder.mkdir()
                folder.joinpath("status").write_text(f"Name:\ttest\nUid:\t{uid} {uid} {uid} {uid}\nPPid:\t{ppid}\n")
                folder.joinpath("cmdline").write_bytes(b"\0".join(value.encode() for value in argv) + b"\0")

            process(100, 1, ["gdm-session-worker"])
            process(200, 100, ["/usr/bin/Xwayland", ":2", "-auth", str(active_auth)])
            process(300, 1, ["/usr/bin/Xwayland", ":0", "-auth", str(stale_auth)])
            selected = self.module.find_xwayland(uid, runtime, 100, proc)
            self.assertEqual(selected["display"], ":2")
            self.assertEqual(selected["xauthority"], str(active_auth))

    def test_shell_output_contains_one_fingerprint(self):
        identity = {
            "session_id":"4", "user":"cfadmin", "uid":1001, "gid":1001,
            "home":"/home/cfadmin", "runtime_dir":"/run/user/1001",
            "dbus_session_bus_address":"unix:path=/run/user/1001/bus", "display":":2",
            "wayland_display":"wayland-0", "xauthority":"/run/user/1001/.mutter-Xwaylandauth.test",
            "fingerprint":"abc",
        }
        output = self.module.shell_assignments(identity)
        self.assertIn("CLIENTFLOW_GRAPHICAL_DISPLAY=:2", output)
        self.assertIn("CLIENTFLOW_GRAPHICAL_XAUTHORITY=/run/user/1001/.mutter-Xwaylandauth.test", output)
        self.assertEqual(output.count("CLIENTFLOW_GRAPHICAL_FINGERPRINT="), 1)

    def test_installer_uses_dedicated_capture_service(self):
        with zipfile.ZipFile(INSTALLER) as outer:
            payload = outer.read("payload_clientflow_v1_0_0.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as inner:
            service = inner.extractfile("etc/systemd/system/client_remote_desktop_capture.service").read().decode()
            dropin = inner.extractfile("etc/systemd/system/client_remote_desktop_agent.service.d/50-wayland-capture.conf").read().decode()
            shout = inner.extractfile("usr/local/bin/clientflow-shout-overlay").read().decode()
            agent = inner.extractfile("opt/clientflow/api/client_remote_desktop_agent.py").read().decode()
        self.assertIn("ExecStart=/usr/local/sbin/clientflow-rd-capture-launcher", service)
        self.assertIn("KillMode=control-group", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("Wants=client_remote_desktop_capture.service", dropin)
        self.assertNotIn("clientflow-rd-wayland-daemon-start.sh", dropin)
        self.assertIn("clientflow-resolve-graphical-session", shout)
        self.assertNotIn("prøver legacy feh direkte", agent)

    def test_capture_waits_for_unlocked_graphical_session(self):
        with zipfile.ZipFile(INSTALLER) as outer:
            payload = outer.read("payload_clientflow_v1_0_0.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as inner:
            resolver = inner.extractfile("usr/local/lib/clientflow-root/clientflow_graphical_session.py").read().decode()
            launcher = inner.extractfile("usr/local/sbin/clientflow-rd-capture-launcher").read().decode()
        self.assertIn('"LockedHint"', resolver)
        self.assertIn("Aktiv grafisk session er låst", resolver)
        self.assertIn("while True", launcher)
        self.assertIn("waiting_session", launcher)


if __name__ == "__main__":
    unittest.main()
