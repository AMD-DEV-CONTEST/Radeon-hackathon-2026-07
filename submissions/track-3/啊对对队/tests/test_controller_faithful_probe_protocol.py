from __future__ import annotations

from pathlib import Path
import unittest

from scripts.audit_controller_faithful_probe_protocol import audit_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/controller_faithful_probe_v4.toml"


class ControllerFaithfulProbeProtocolTests(unittest.TestCase):
    def test_frozen_protocol_validates_before_any_real_run(self) -> None:
        result = audit_protocol(PROTOCOL)
        self.assertEqual(result["status"], "protocol_valid")
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["development_forbidden"])
        self.assertTrue(result["holdout_forbidden"])


if __name__ == "__main__":
    unittest.main()
