from __future__ import annotations

import unittest

from scripts.summarize_gpu_metrics import parse_metrics, summarize


class GpuSummaryTests(unittest.TestCase):
    def test_summarizes_two_samples(self) -> None:
        sample = """\
        GFX_ACTIVITY: 0 %
        SOCKET_POWER: 20 W
        EDGE: 30 °C
        HOTSPOT: 35 °C
        USED_VRAM: 44000 MB
        GFX_ACTIVITY: 100 %
        SOCKET_POWER: 180 W
        EDGE: 42 °C
        HOTSPOT: 52 °C
        USED_VRAM: 44246 MB
"""
        report = summarize(parse_metrics(sample))
        self.assertEqual(report["samples"], 2)
        self.assertEqual(report["metrics"]["gfx_activity_pct"]["mean"], 50)
        self.assertEqual(report["metrics"]["socket_power_w"]["max"], 180)
        self.assertEqual(report["metrics"]["used_vram_mb"]["max"], 44246)


if __name__ == "__main__":
    unittest.main()
