import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_mobile_pi05_droid_local.py"
SPEC = importlib.util.spec_from_file_location("prepare_pi05_droid_local", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareMobilePI05DroidLocalTests(unittest.TestCase):
    def test_builds_offline_bundle_without_copying_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            droid = root / "droid"
            base = root / "base"
            tokenizer = root / "tokenizer"
            output = root / "output"
            droid.mkdir()
            base.mkdir()
            tokenizer.mkdir()
            (droid / "model.safetensors").write_bytes(b"droid-model")
            (droid / "policy_preprocessor.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {
                                "registry_name": "tokenizer_processor",
                                "config": {"tokenizer_name": "remote/model"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (base / "config.json").write_text("{}", encoding="utf-8")
            (base / "policy_postprocessor.json").write_text("{}", encoding="utf-8")

            with mock.patch.object(Path, "symlink_to") as symlink_to:
                manifest = MODULE.prepare_droid_bundle(
                    droid_snapshot=droid,
                    base_bundle=base,
                    tokenizer=tokenizer,
                    output=output,
                )

            symlink_to.assert_called_once_with((droid / "model.safetensors").resolve())
            payload = json.loads(
                (output / "policy_preprocessor.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["steps"][0]["config"]["tokenizer_name"],
                str(tokenizer.resolve()),
            )
            self.assertEqual(manifest["protocol"], "pi05-droid-offline-bundle-v1")

    def test_refuses_to_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            droid = root / "droid"
            base = root / "base"
            tokenizer = root / "tokenizer"
            output = root / "output"
            for path in (droid, base, tokenizer, output):
                path.mkdir()
            (droid / "model.safetensors").write_bytes(b"droid-model")
            (droid / "policy_preprocessor.json").write_text(
                '{"steps": [{"registry_name": "tokenizer_processor", "config": {}}]}',
                encoding="utf-8",
            )
            (base / "config.json").write_text("{}", encoding="utf-8")
            (base / "policy_postprocessor.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output already exists"):
                MODULE.prepare_droid_bundle(
                    droid_snapshot=droid,
                    base_bundle=base,
                    tokenizer=tokenizer,
                    output=output,
                )


if __name__ == "__main__":
    unittest.main()
