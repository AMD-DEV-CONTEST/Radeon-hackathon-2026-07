from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformPublicationRepairDurabilityTests(unittest.TestCase):
    def test_runner_checkpoints_before_strict_audit(self) -> None:
        source = (
            ROOT / "scripts/run_local_gemma3_platform_publication_repairs.py"
        ).read_text(encoding="utf-8")
        loop_checkpoint = source.index("checkpoint_trace()")
        strict_audit = source.index("strict_audit = compile_platform_native_publication_audit")
        receipt_write = source.index('json.dumps(receipt, ensure_ascii=False')
        self.assertLess(loop_checkpoint, strict_audit)
        self.assertLess(receipt_write, strict_audit)
        self.assertIn('"completed_surface_count": len(attempts)', source)

    def test_runner_supports_digest_bound_selective_resume(self) -> None:
        source = (
            ROOT / "scripts/run_local_gemma3_platform_publication_repairs.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"--resume-trace"', source)
        self.assertIn("resume trace digest is invalid", source)
        self.assertIn("prior_attempts = list(attempts.get(surface_id, ()))", source)
        self.assertIn("surface_attempts = prior_attempts + [first]", source)
        self.assertIn("surface_attempts[-1:]", source)
        self.assertIn("attempts_by_surface=receipt_attempts", source)


if __name__ == "__main__":
    unittest.main()
