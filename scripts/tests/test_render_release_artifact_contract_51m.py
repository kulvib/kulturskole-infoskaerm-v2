from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
RENDER_YAML = ROOT / "render.yaml"
AUTHORITY_DOC = ROOT / "RENDER_RELEASE_ARTIFACT_AUTHORITY.md"
ARTIFACT_DIR = "/var/data/clientflow-release-artifacts"


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
            f"      mountPath: {ARTIFACT_DIR}\n"
            "      sizeGB: 1\n"
        )
        self.assertIn(expected, backend)
        self.assertEqual(backend.count("    disk:\n"), 1)
        self.assertEqual(backend.count(f"      mountPath: {ARTIFACT_DIR}\n"), 1)

    def test_runtime_artifact_env_matches_disk_mount(self) -> None:
        backend = backend_block()
        expected = (
            "      - key: CLIENTFLOW_RELEASE_ARTIFACT_DIR\n"
            f'        value: "{ARTIFACT_DIR}"\n'
        )
        self.assertIn(expected, backend)
        self.assertEqual(backend.count("CLIENTFLOW_RELEASE_ARTIFACT_DIR"), 1)

    def test_predeploy_does_not_touch_runtime_disk(self) -> None:
        backend = backend_block()
        match = re.search(r'(?m)^    preDeployCommand: "([^"]+)"$', backend)
        self.assertIsNotNone(match)
        command = match.group(1)
        self.assertEqual(command, "python scripts/run_migrations.py")
        self.assertNotIn(ARTIFACT_DIR, command)
        self.assertNotIn("publish_clientflow_release", command)

    def test_backend_process_model_remains_single_worker(self) -> None:
        backend = backend_block()
        self.assertIn("--workers 1", backend)

    def test_authority_document_matches_runtime_contract(self) -> None:
        doc = AUTHORITY_DOC.read_text(encoding="utf-8")
        self.assertIn("CLIENTFLOW_RELEASE_ARTIFACT_DIR", doc)
        self.assertIn(ARTIFACT_DIR, doc)
        self.assertIn("pre-deploy", doc.lower())
        self.assertIn("single-instance", doc.lower())


if __name__ == "__main__":
    unittest.main()
