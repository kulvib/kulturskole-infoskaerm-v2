from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
RENDER_YAML = ROOT / "render.yaml"
AUTHORITY_DOC = ROOT / "RENDER_RELEASE_ARTIFACT_AUTHORITY.md"
DISK_MOUNT = "/var/data/clientflow-release-artifacts"
ARTIFACT_DIR = f"{DISK_MOUNT}/store"


def backend_block() -> str:
    text = RENDER_YAML.read_text(encoding="utf-8")
    marker = "  # ─── Frontend ─"
    if marker not in text:
        raise AssertionError("render.yaml mangler frontend-markør")
    return text.split(marker, 1)[0]


class RenderReleaseArtifactAuthority51MTests(unittest.TestCase):
    def test_backend_is_paid_single_instance(self) -> None:
        backend = backend_block()
        self.assertRegex(backend, r"(?m)^    plan: starter$")
        self.assertRegex(backend, r"(?m)^    numInstances: 1$")
        self.assertNotRegex(backend, r"(?m)^    scaling:")

    def test_persistent_disk_is_exactly_wired(self) -> None:
        backend = backend_block()
        expected = (
            "    disk:\n"
            "      name: clientflow-release-artifacts\n"
            f"      mountPath: {DISK_MOUNT}\n"
            "      sizeGB: 1\n"
        )
        self.assertIn(expected, backend)
        self.assertEqual(backend.count("    disk:\n"), 1)
        self.assertEqual(backend.count(f"      mountPath: {DISK_MOUNT}\n"), 1)

    def test_runtime_artifact_env_uses_secure_child_inside_disk_mount(self) -> None:
        backend = backend_block()
        expected = (
            "      - key: CLIENTFLOW_RELEASE_ARTIFACT_DIR\n"
            f'        value: "{ARTIFACT_DIR}"\n'
        )
        self.assertIn(expected, backend)
        self.assertEqual(backend.count("CLIENTFLOW_RELEASE_ARTIFACT_DIR"), 1)

    def test_runtime_start_prepares_secure_child_before_uvicorn(self) -> None:
        backend = backend_block()
        match = re.search(r'(?m)^    startCommand: "([^"]+)"$', backend)
        self.assertIsNotNone(match)
        command = match.group(1)
        expected_prefix = (
            f"mkdir -p {ARTIFACT_DIR} && "
            f"chmod 0755 {ARTIFACT_DIR} && "
            "exec python -m uvicorn "
        )
        self.assertTrue(command.startswith(expected_prefix))
        self.assertIn("service1.main:app", command)
        self.assertIn("--workers 1", command)

    def test_predeploy_does_not_touch_runtime_disk(self) -> None:
        backend = backend_block()
        match = re.search(r'(?m)^    preDeployCommand: "([^"]+)"$', backend)
        self.assertIsNotNone(match)
        command = match.group(1)
        self.assertEqual(command, "python scripts/run_migrations.py")
        self.assertNotIn(DISK_MOUNT, command)
        self.assertNotIn("publish_clientflow_release", command)

    def test_backend_process_model_remains_single_worker(self) -> None:
        backend = backend_block()
        self.assertIn("--workers 1", backend)

    def test_authority_document_matches_runtime_contract(self) -> None:
        doc = AUTHORITY_DOC.read_text(encoding="utf-8")
        self.assertIn("CLIENTFLOW_RELEASE_ARTIFACT_DIR", doc)
        self.assertIn(DISK_MOUNT, doc)
        self.assertIn(ARTIFACT_DIR, doc)
        self.assertIn("secure child", doc.lower())
        self.assertIn("pre-deploy", doc.lower())
        self.assertIn("single-instance", doc.lower())


if __name__ == "__main__":
    unittest.main()
