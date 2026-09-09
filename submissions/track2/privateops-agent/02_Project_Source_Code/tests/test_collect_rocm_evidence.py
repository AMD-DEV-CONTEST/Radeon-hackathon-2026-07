from __future__ import annotations

import unittest

from scripts.collect_rocm_evidence import parse_gpu_proof


class CollectRocmEvidenceTests(unittest.TestCase):
    def test_selects_marketing_name_from_gpu_agent_not_cpu_agent(self):
        output = """
  Agent 1
    Name:                    AMD EPYC 9334 32-Core Processor
    Marketing Name:          AMD EPYC 9334 32-Core Processor
    Device Type:             CPU
  Agent 3
    Name:                    gfx1100
    Marketing Name:          AMD Radeon Graphics
    Device Type:             GPU
"""

        gpu_name, excerpt = parse_gpu_proof(output)

        self.assertEqual(gpu_name, "AMD Radeon Graphics")
        self.assertIn("Name:                    gfx1100", excerpt)
        self.assertNotIn("AMD EPYC", excerpt)


if __name__ == "__main__":
    unittest.main()
