import re
import unittest
from pathlib import Path

from tests.test_demo_caption_layer import load_build_demo


ROOT = Path(__file__).resolve().parents[1]
SWIFT_PATH = ROOT / "tools" / "rebuild_demo_caption_layer_v3.swift"
EXPECTED_TIMESTAMPS = [1, 10, 24, 39, 53, 65, 72, 90, 105, 120, 138, 153]
EXPECTED_FILENAMES = [
    f"proof_{index:02d}_{seconds * 1000:09d}ms.png"
    for index, seconds in enumerate(EXPECTED_TIMESTAMPS, start=1)
]


class DemoCaptionLayerV3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_demo = load_build_demo()
        cls.source = SWIFT_PATH.read_text(encoding="utf-8")

    def test_exact_subtitle_strings_and_boundaries_match_frozen_python_source(self):
        matches = re.findall(
            r'SubtitleSegment\(start: ([0-9.]+), end: ([0-9.]+), text: "([^"]+)"\)',
            self.source,
        )
        swift_segments = [(float(start), float(end), text) for start, end, text in matches]
        expected = []
        elapsed = 0.0
        for _, _, duration, subtitle in self.build_demo.SEG:
            expected.append((elapsed, elapsed + duration, subtitle))
            elapsed += duration
        self.assertEqual(expected, swift_segments)

    def test_exact_proof_timestamps_and_names_are_frozen(self):
        matches = re.findall(
            r'ProofSpec\(index: ([0-9]+), seconds: ([0-9.]+), filename: "([^"]+)"\)',
            self.source,
        )
        self.assertEqual(EXPECTED_TIMESTAMPS, [int(float(seconds)) for _, seconds, _ in matches])
        self.assertEqual(EXPECTED_FILENAMES, [filename for _, _, filename in matches])
        self.assertEqual(list(range(1, 13)), [int(index) for index, _, _ in matches])

    def test_timestamp_selection_uses_half_open_segment_boundaries(self):
        self.assertIn("seconds >= $0.start && seconds < $0.end", self.source)
        segments = [(sum(item[2] for item in self.build_demo.SEG[:i]), item[2]) for i, item in enumerate(self.build_demo.SEG)]
        for proof_index, seconds in enumerate(EXPECTED_TIMESTAMPS):
            selected = next(index for index, (start, duration) in enumerate(segments) if start <= seconds < start + duration)
            self.assertEqual(proof_index, selected)

    def test_reader_writer_share_the_pixel_buffer_renderer_without_animation_timing(self):
        self.assertIn("AVAssetReader", self.source)
        self.assertIn("AVAssetWriter", self.source)
        self.assertIn("private func renderFrame(", self.source)
        self.assertEqual(3, self.source.count("renderFrame("))
        self.assertNotIn("QuartzCore", self.source)
        self.assertNotIn("CAKeyframeAnimation", self.source)
        self.assertNotIn("CATextLayer", self.source)
        self.assertNotIn("AVVideoCompositionCoreAnimationTool", self.source)

    def test_mask_geometry_and_proof_freshness_are_fail_closed(self):
        self.assertIn("private let maskHeight = 80", self.source)
        self.assertIn("context.fill(CGRect(x: 0, y: 0, width: expectedWidth, height: maskHeight))", self.source)
        self.assertIn('initialNames == Set(["rebuild_demo_caption_layer_v3"])', self.source)
        self.assertIn("options: .withoutOverwriting", self.source)
        self.assertIn("finalNames == expectedNames", self.source)

    def test_future_export_requires_hash_locked_proof_go_and_fresh_reserved_path(self):
        required = [
            'gate["decision"] as? String == "PROOF_GO"',
            'gate["p0"] as? Int == 0',
            'gate["p1"] as? Int == 0',
            'gate["protocol_sha256"] as? String == expectedProtocolSHA256',
            'gate["input_sha256"] as? String == expectedV1SHA256',
            'gate["renderer_source_sha256"] as? String == (try sha256(projectURL(sourcePath)))',
            '("proof_receipt_path", "proof_receipt_sha256")',
            '("proof_manifest_path", "proof_manifest_sha256")',
            "output.lastPathComponent == reservedV3Filename",
            "!FileManager.default.fileExists(atPath: output.path)",
            "AVVideoCodecType.h264",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.source)

    def test_proof_receipt_cannot_claim_acceptance(self):
        self.assertIn('"status": "proof_rendered_pending_independent_review"', self.source)
        self.assertIn('"decision": "NOT_REVIEWED"', self.source)
        self.assertIn('"PROOF_GO is not claimed."', self.source)


if __name__ == "__main__":
    unittest.main()
