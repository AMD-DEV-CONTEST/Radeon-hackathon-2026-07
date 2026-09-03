import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "build_submission_demo.py"
SPEC = importlib.util.spec_from_file_location("build_submission_demo", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BuildSubmissionDemoTest(unittest.TestCase):
    def test_timeline_and_video_contract(self):
        self.assertEqual(168, MODULE.TOTAL_DURATION)
        self.assertTrue(160 <= MODULE.TOTAL_DURATION <= 180)
        self.assertEqual(1280, MODULE.WIDTH)
        self.assertEqual(720, MODULE.HEIGHT)
        self.assertEqual(30, MODULE.FPS)
        self.assertEqual(636, MODULE.SUBTITLE_BAND_TOP)
        self.assertEqual("live", MODULE.SEGMENTS[0].kind)
        self.assertEqual("live", MODULE.SEGMENTS[7].kind)
        self.assertEqual("live", MODULE.SEGMENTS[-1].kind)

    def test_honesty_boundaries_are_visible_and_narrated(self):
        text = "\n".join(
            segment.narration + "\n" + segment.caption
            for segment in MODULE.SEGMENTS
        ).lower()
        for required in (
            "task not completed",
            "zero successes out of ten",
            "eight timeouts",
            "two collision-safety",
            "not policy results",
            "not physical calibrations",
            "loss and finite actions do not prove task success",
        ):
            self.assertIn(required, text)

    def test_card_renderers_cover_every_card_segment(self):
        expected = {segment.key for segment in MODULE.SEGMENTS if segment.kind == "card"}
        self.assertEqual(expected, set(MODULE.CARD_RENDERERS))
        if MODULE.Image is None:
            self.skipTest("Pillow is unavailable in the local source-contract runtime")
        for key in expected:
            with self.subTest(key=key):
                self.assertEqual((1280, 720), MODULE.CARD_RENDERERS[key]().size)

    def test_srt_uses_exact_segment_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "captions.srt"
            MODULE.write_srt(path)
            rendered = path.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:10,000", rendered)
        self.assertIn("00:02:40,000 --> 00:02:48,000", rendered)
        self.assertEqual(len(MODULE.SEGMENTS), rendered.count(" --> "))

    def test_source_is_non_overwriting_and_encodes_submission_format(self):
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn("output_dir.exists()", source)
        self.assertIn('"-c:v", "libx264"', source)
        self.assertIn('"-pix_fmt", "yuv420p"', source)
        self.assertIn("drawbox=x=0:y={SUBTITLE_BAND_TOP}", source)
        self.assertIn("FontSize=12", source)
        self.assertIn("MarginV=18", source)
        self.assertIn("Mantis_ROCm_Bridge_submission_demo_20260806_v2.mp4", source)
        self.assertIn('"BUILT_PENDING_VISUAL_REVIEW"', source)
        self.assertNotIn("Mantis_ROCM_Bridge_demo_20260805_v3.mp4", source)


if __name__ == "__main__":
    unittest.main()
