from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_grasp_candidate_dataset import manifest_label_paths
from parcel_sorter.grasp_scoring import sha256_file


class GraspDatasetManifestTests(unittest.TestCase):
    def _write_manifest(
        self,
        directory: str,
        *,
        status: str = "complete",
        source_status: str = "complete",
        source_sha256: str | None = None,
    ) -> tuple[Path, Path]:
        root = Path(directory)
        source = root / "episode.json"
        source.write_text('{"status": "complete"}\n', encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "protocol_sha256": "protocol-sha",
                    "runs": [
                        {
                            "status": status,
                            "source_status": source_status,
                            "output": str(source),
                            "sha256": source_sha256 or sha256_file(source),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return manifest, source

    def test_selects_complete_hash_verified_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, source = self._write_manifest(directory)

            result = manifest_label_paths(manifest, "protocol-sha")

            self.assertEqual(result, [source])

    def test_ignores_structured_inactive_gate_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self._write_manifest(
                directory,
                status="skipped_inactive_gate",
                source_status="skipped_inactive_reset_gate",
            )
            complete = Path(directory) / "complete.json"
            complete.write_text('{"status": "complete"}\n', encoding="utf-8")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["runs"].append(
                {
                    "status": "reused",
                    "source_status": "complete",
                    "output": str(complete),
                    "sha256": sha256_file(complete),
                }
            )
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            result = manifest_label_paths(manifest, "protocol-sha")

            self.assertEqual(result, [complete])

    def test_rejects_incomplete_or_hash_mismatched_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self._write_manifest(directory, status="running")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                manifest_label_paths(manifest, "protocol-sha")

            manifest, _ = self._write_manifest(
                directory,
                source_sha256="0" * 64,
            )
            with self.assertRaisesRegex(ValueError, "hash"):
                manifest_label_paths(manifest, "protocol-sha")

    def test_rejects_protocol_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self._write_manifest(directory)

            with self.assertRaisesRegex(ValueError, "protocol"):
                manifest_label_paths(manifest, "different-protocol")


if __name__ == "__main__":
    unittest.main()
