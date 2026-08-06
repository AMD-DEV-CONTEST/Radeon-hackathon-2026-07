import importlib.util
import re
import sys
import types
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_DEMO_PATH = ROOT / "tools" / "build_demo.py"
SWIFT_PATH = ROOT / "tools" / "rebuild_demo_caption_layer.swift"
EXPECTED_BOUNDARIES = [0, 9, 23, 38, 52, 64, 71, 89, 104, 119, 137, 152, 162]


def load_build_demo():
    spec = importlib.util.spec_from_file_location("build_demo_caption_contract", BUILD_DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageFont = object()
    with mock.patch.dict(sys.modules, {"PIL": pil_stub}):
        spec.loader.exec_module(module)
    return module


class DemoCaptionLayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_demo = load_build_demo()
        cls.swift_source = SWIFT_PATH.read_text(encoding="utf-8")

    def test_python_timing_and_subtitle_contract_is_frozen(self):
        segments = self.build_demo.SEG
        boundaries = [0]
        for _, _, duration, subtitle in segments:
            self.assertTrue(subtitle)
            boundaries.append(boundaries[-1] + duration)
        self.assertEqual(12, len(segments))
        self.assertEqual(EXPECTED_BOUNDARIES, boundaries)

    def test_swift_contract_matches_python_segments_exactly(self):
        matches = re.findall(
            r'SubtitleSegment\(start: ([0-9.]+), end: ([0-9.]+), text: "([^"]+)"\)',
            self.swift_source,
        )
        swift_segments = [(float(start), float(end), text) for start, end, text in matches]
        expected = []
        elapsed = 0.0
        for _, _, duration, subtitle in self.build_demo.SEG:
            expected.append((elapsed, elapsed + duration, subtitle))
            elapsed += duration
        self.assertEqual(expected, swift_segments)

    def test_future_card_footer_stays_above_subtitle_safe_region(self):
        self.assertLess(self.build_demo.FOOTER_Y, self.build_demo.SUBTITLE_SAFE_TOP)
        self.assertLessEqual(self.build_demo.FOOTER_Y + 20, self.build_demo.SUBTITLE_SAFE_TOP)
        self.assertIn("d.text((40, FOOTER_Y), sub", BUILD_DEMO_PATH.read_text(encoding="utf-8"))

    def test_swift_rebuilder_guards_input_identity_and_output_freshness(self):
        self.assertIn("expectedInputSHA256", self.swift_source)
        self.assertIn("guard !fileManager.fileExists(atPath: output.path)", self.swift_source)
        self.assertIn("expectedWidth = 640", self.swift_source)
        self.assertIn("expectedHeight = 480", self.swift_source)
        self.assertIn("expectedDuration = 162.0", self.swift_source)
        self.assertIn("maskHeight = 80.0", self.swift_source)
        self.assertIn("mask.frame = CGRect(x: 0, y: 0", self.swift_source)


if __name__ == "__main__":
    unittest.main()
