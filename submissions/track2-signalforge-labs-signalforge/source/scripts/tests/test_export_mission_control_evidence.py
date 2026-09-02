import importlib.util
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "export_mission_control_evidence.py"
SPEC = importlib.util.spec_from_file_location("export_mission_control_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class MissionControlEvidenceTests(unittest.TestCase):
    def test_exports_only_public_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit = root / "audit"
            audit.mkdir()
            (audit / "run-1.metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": "signalforge/intelligence-lineage/v1",
                        "run_id": "run-1",
                        "model_calls": [{"request_payload_sha256": "a" * 64}],
                    }
                ),
                encoding="utf-8",
            )
            (audit / "run-1.protected.json").write_text(
                json.dumps({"question": "private", "raw_output": "private"}),
                encoding="utf-8",
            )
            output = root / "evidence.tar.gz"

            manifest = MODULE.export(audit, output)

            self.assertEqual(manifest["record_count"], 1)
            with tarfile.open(output, "r:gz") as archive:
                names = archive.getnames()
                self.assertEqual(names, ["manifest.json", "records/run-1.metadata.json"])
                payload = archive.extractfile("records/run-1.metadata.json").read()
                self.assertNotIn(b"private", payload)

    def test_rejects_protected_fields_in_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit = Path(temporary)
            (audit / "run-2.metadata.json").write_text(
                json.dumps({"run_id": "run-2", "prompt": "do not export"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                MODULE.collect(audit)


if __name__ == "__main__":
    unittest.main()
