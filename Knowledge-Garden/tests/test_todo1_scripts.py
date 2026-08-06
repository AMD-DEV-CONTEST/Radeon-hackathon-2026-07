"""Tests for Todo 1 model-experiment controller scripts.

Covers: find_listener_pid.sh port->PID resolution, service-descriptor schema
validity, capture/verify round-trip on a live endpoint, and negative revision
mismatch detection. Uses the live :8000 14B endpoint (read-only).
"""
from __future__ import annotations

import json
import subprocess
import unittest


ROOT = "/persistent/learning-companion"


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=60)


class TestTodo1Scripts(unittest.TestCase):
    def test_schema_is_valid_json_with_required_fields(self) -> None:
        with open(f"{ROOT}/docs/service-descriptor.schema.json") as f:
            schema = json.load(f)
        self.assertEqual(schema["properties"]["descriptor_schema_version"]["const"], 1)
        for f in ["executable", "argv", "cwd", "checkpoint_path", "checkpoint_revision",
                  "env", "port", "served_model_id", "log_path", "launcher_method", "captured_at"]:
            self.assertIn(f, schema["required"], f"missing required field {f}")

    def test_find_listener_pid_resolves_live_port(self) -> None:
        # :8000 hosts the running Qwen2.5-14B service
        r = sh("bash", "scripts/find_listener_pid.sh", "8000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().isdigit(), r.stdout)
        # that PID must be a vLLM api_server
        ps = sh("bash", "-c", f"tr '\\0' ' ' < /proc/{r.stdout.strip()}/cmdline")
        self.assertIn("openai.api_server", ps.stdout)

    def test_capture_then_verify_round_trip(self) -> None:
        desc = "/tmp/lc-todo1-desc.json"
        r = sh("bash", "scripts/capture_service_descriptor.sh",
               "--model-port", "8000", "--served-name", "Qwen2.5-14B-AWQ", "--out", desc)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(desc) as f:
            d = json.load(f)
        self.assertEqual(d["served_model_id"], "Qwen2.5-14B-AWQ")
        self.assertEqual(d["port"], 8000)
        v = sh("bash", "scripts/verify_restoration.sh", "--port", "8000", "--descriptor", desc)
        self.assertEqual(v.returncode, 0, v.stderr)
        self.assertIn("VERIFY_RESTORATION_OK", v.stdout)

    def test_verify_rejects_revision_mismatch(self) -> None:
        desc = "/tmp/lc-todo1-desc.json"
        bad = "/tmp/lc-todo1-bad.json"
        sh("bash", "scripts/capture_service_descriptor.sh",
           "--model-port", "8000", "--served-name", "Qwen2.5-14B-AWQ", "--out", desc)
        with open(desc) as f:
            d = json.load(f)
        d["checkpoint_revision"] = "0" * 64
        with open(bad, "w") as f:
            json.dump(d, f)
        v = sh("bash", "scripts/verify_restoration.sh", "--port", "8000", "--descriptor", bad)
        self.assertNotEqual(v.returncode, 0)
        self.assertIn("checkpoint revision mismatch", v.stderr)

    def test_dry_run_makes_no_process_changes(self) -> None:
        before = sh("bash", "scripts/find_listener_pid.sh", "8000").stdout.strip()
        r = sh("bash", "scripts/qwen3_experiment.sh", "run", "--dry-run", "--model-port", "8000")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = sh("bash", "scripts/find_listener_pid.sh", "8000").stdout.strip()
        self.assertEqual(before, after, "dry-run must not change the serving process")


if __name__ == "__main__":
    unittest.main()
