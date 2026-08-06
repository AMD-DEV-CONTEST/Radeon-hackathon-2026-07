from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "scripts" / "verify_model_snapshot.py"


class ModelSnapshotVerifierTests(unittest.TestCase):
    def run_verifier(
        self,
        manifest: pathlib.Path,
        model_dir: pathlib.Path,
        *extra_args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(VERIFIER),
                "--manifest",
                str(manifest),
                "--model-dir",
                str(model_dir),
                *extra_args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def manifest_for(self, model_dir: pathlib.Path, files: list[dict]) -> dict:
        return {
            "schema_version": "1.0",
            "model_id": "fixture/model",
            "served_model_name": "fixture-model",
            "expected_directory_name": model_dir.name,
            "source": {
                "provider": "fixture",
                "repository": "fixture/model",
                "revision": "a" * 40,
            },
            "license": "Apache-2.0",
            "files": files,
        }

    def test_matching_snapshot_passes(self):
        payload = b"frozen model fixture\n"
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "config.json").write_bytes(payload)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [
                            {
                                "path": "config.json",
                                "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(manifest, model_dir)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("MODEL_SNAPSHOT_OK", completed.stdout)

    def test_explicit_full_sha256_mode_passes_and_hashes(self):
        payload = b"frozen model fixture\n"
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "config.json").write_bytes(payload)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [
                            {
                                "path": "config.json",
                                "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(
                manifest, model_dir, "--full-sha256"
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("mode=FULL_SHA256", completed.stdout)

    def test_quick_and_full_sha256_modes_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            manifest = root / "manifest.json"
            completed = self.run_verifier(
                manifest, model_dir, "--quick", "--full-sha256"
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("not allowed with argument", completed.stderr)

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "config.json").write_text("changed", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [{"path": "config.json", "size": 7, "sha256": "0" * 64}],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(manifest, model_dir)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("sha256 mismatch", completed.stderr)

    def test_unsafe_manifest_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [{"path": "../outside", "size": 0, "sha256": "0" * 64}],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(manifest, model_dir)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsafe manifest path", completed.stderr)

    def test_undeclared_file_is_rejected(self):
        payload = b"expected"
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "config.json").write_bytes(payload)
            (model_dir / "unexpected.py").write_text("pass\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [
                            {
                                "path": "config.json",
                                "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(manifest, model_dir)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("undeclared file: unexpected.py", completed.stderr)

    def test_manifest_symlink_is_rejected(self):
        payload = b"expected"
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            model_dir = root / "model"
            model_dir.mkdir()
            target = root / "outside.json"
            target.write_bytes(payload)
            (model_dir / "config.json").symlink_to(target)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    self.manifest_for(
                        model_dir,
                        [
                            {
                                "path": "config.json",
                                "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    )
                ),
                encoding="utf-8",
            )
            completed = self.run_verifier(manifest, model_dir)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must not be a symlink", completed.stderr)


if __name__ == "__main__":
    unittest.main()
