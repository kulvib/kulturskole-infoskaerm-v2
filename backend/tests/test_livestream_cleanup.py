from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from fastapi import Response

from service1.routers import livestream


class LivestreamCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.hls_dir_patch = patch.object(livestream, "HLS_DIR", self.temp_dir.name)
        self.hls_dir_patch.start()
        self.addCleanup(self.hls_dir_patch.stop)
        livestream._captured_at_store.clear()

    def _client_dir(self, client_id: str) -> str:
        path = livestream.safe_client_dir(client_id)
        os.makedirs(path, exist_ok=True)
        return path

    async def test_normal_cleanup_keeps_latest_manifest_segments(self) -> None:
        client_id = "client-20"
        client_dir = self._client_dir(client_id)
        for filename in ("segment_00001.ts", "segment_00002.ts"):
            with open(os.path.join(client_dir, filename), "wb") as handle:
                handle.write(b"segment")

        payload = livestream.HlsCleanupRequest(
            client_id=client_id,
            keep_files=["segment_00001.ts", "segment_00002.ts"],
            segment_duration=2,
        )
        response = Response()

        with patch.object(livestream, "require_hls_access"):
            result = await livestream.cleanup_hls_files(payload, response, keep_n=1, user=object())

        self.assertEqual(result["deleted"], [])
        self.assertEqual(result["kept"], ["segment_00002.ts"])
        self.assertEqual(response.headers["Cache-Control"], "no-cache, no-store, must-revalidate")
        with open(os.path.join(client_dir, "index.m3u8"), encoding="utf-8") as handle:
            manifest = handle.read()
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:2", manifest)
        self.assertIn("segment_00002.ts", manifest)
        self.assertNotIn("segment_00001.ts", manifest)

    async def test_segment_delete_failure_logs_correct_client_id(self) -> None:
        client_id = "client-21"
        client_dir = self._client_dir(client_id)
        stale = os.path.join(client_dir, "segment_00001.ts")
        kept = os.path.join(client_dir, "segment_00002.ts")
        for path in (stale, kept):
            with open(path, "wb") as handle:
                handle.write(b"segment")

        real_remove = os.remove

        def selective_remove(path: str) -> None:
            if path == stale:
                raise OSError("simulated delete failure")
            real_remove(path)

        payload = livestream.HlsCleanupRequest(
            client_id=client_id,
            keep_files=["segment_00002.ts"],
            segment_duration=2,
        )

        with (
            patch.object(livestream, "require_hls_access"),
            patch.object(livestream.os, "remove", side_effect=selective_remove),
            patch.object(livestream, "log_safe_exception") as safe_log,
        ):
            result = await livestream.cleanup_hls_files(payload, Response(), user=object())

        self.assertEqual(result["kept"], ["segment_00002.ts"])
        safe_log.assert_any_call(
            livestream.logger,
            ANY,
            event="hls_segment_cleanup_failed",
            level=livestream.logging.WARNING,
            client_id=client_id,
        )

    async def test_captured_at_failure_logs_correct_client_id(self) -> None:
        client_id = "client-22"
        self._client_dir(client_id)
        payload = livestream.HlsCleanupRequest(client_id=client_id, keep_files=[], segment_duration=2)

        with (
            patch.object(livestream, "require_hls_access"),
            patch.object(livestream, "_get_captured_at_map", side_effect=RuntimeError("simulated sidecar failure")),
            patch.object(livestream, "log_safe_exception") as safe_log,
        ):
            result = await livestream.cleanup_hls_files(payload, Response(), user=object())

        self.assertEqual(result, {"deleted": [], "kept": [], "segment_duration": 2, "generation": None})
        safe_log.assert_called_once_with(
            livestream.logger,
            ANY,
            event="hls_captured_at_cleanup_failed",
            level=livestream.logging.WARNING,
            client_id=client_id,
        )


if __name__ == "__main__":
    unittest.main()
