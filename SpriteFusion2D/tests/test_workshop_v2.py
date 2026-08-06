"""V2 transforms, routing and asynchronous generation contracts."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from sprite_workshop.classify import classify_source
from sprite_workshop.daemon import Daemon
from sprite_workshop.generate.base import GenerationRequest
from sprite_workshop.generate.comfyui import ComfyUIProvider
from sprite_workshop.generate.fake import FakeProvider
from sprite_workshop.jobs import JobManager
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage
from sprite_workshop.outline import OutlineSpec, apply_outline
from sprite_workshop.pixelify import PixelifySpec, pixelify_frames
from sprite_workshop.project import Project


def frame_set(array: np.ndarray, name: str = "hero") -> FrameSet:
    image = RgbaImage(array)
    frame = Frame(
        name,
        image,
        image.size,
        Rect(0, 0, image.width, image.height),
        Point(0, 0),
        Point(image.width // 2, image.height - 1),
    )
    return FrameSet(name, (frame,), image.size)


class Classification(unittest.TestCase):
    def test_nearest_neighbour_blocks_are_pixel_art(self) -> None:
        cells = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
        rgb = np.repeat(np.repeat(cells, 6, axis=0), 6, axis=1)
        rgba = np.dstack((rgb, np.full(rgb.shape[:2], 255, np.uint8)))
        result = classify_source(RgbaImage(rgba))
        self.assertEqual(result.kind, "pixel-art")
        self.assertEqual(result.detected_step, 6)

    def test_gradient_is_not_pixel_art(self) -> None:
        x = np.linspace(0, 255, 80, dtype=np.uint8)
        rgb = np.broadcast_to(x[None, :, None], (40, 80, 3)).copy()
        rgba = np.dstack((rgb, np.full((40, 80), 255, np.uint8)))
        self.assertEqual(classify_source(RgbaImage(rgba)).kind, "illustration")


class Outline(unittest.TestCase):
    def test_outer_outline_changes_only_neighbours(self) -> None:
        rgba = np.zeros((7, 7, 4), np.uint8)
        rgba[3, 3] = (200, 80, 40, 255)
        result = apply_outline(frame_set(rgba), OutlineSpec(connectivity=4))
        alpha = result.frames.frames[0].image.array[:, :, 3]
        self.assertEqual(int((alpha > 0).sum()), 5)
        self.assertEqual(result.metrics["outline_pixels"], 4)

    def test_thick_outline_warns(self) -> None:
        rgba = np.zeros((9, 9, 4), np.uint8)
        rgba[4, 4] = 255
        result = apply_outline(frame_set(rgba), OutlineSpec(thickness=3))
        self.assertIn("outline.thick", {warning.code for warning in result.warnings})


class Pixelify(unittest.TestCase):
    def test_fixed_palette_and_shape(self) -> None:
        rng = np.random.default_rng(9)
        rgba = rng.integers(0, 256, (30, 60, 4), dtype=np.uint8)
        rgba[:, :, 3] = 255
        result = pixelify_frames(
            frame_set(rgba), PixelifySpec(target_width=20, palette="gameboy")
        )
        image = result.frames.frames[0].image
        self.assertEqual((image.width, image.height), (20, 10))
        self.assertLessEqual(
            len(np.unique(image.array[:, :, :3].reshape(-1, 3), axis=0)), 4
        )

    def test_auto_palette_is_deterministic(self) -> None:
        rng = np.random.default_rng(2)
        rgba = rng.integers(0, 256, (18, 24, 4), dtype=np.uint8)
        rgba[:, :, 3] = 255
        spec = PixelifySpec(target_width=16, colors=8)
        a = pixelify_frames(frame_set(rgba), spec).frames.frames[0].image.array
        b = pixelify_frames(frame_set(rgba), spec).frames.frames[0].image.array
        np.testing.assert_array_equal(a, b)


class Jobs(unittest.TestCase):
    def test_prepare_does_not_finish_before_start(self) -> None:
        notices = []
        manager = JobManager(lambda method, params: notices.append((method, params)))
        job = manager.prepare("fast", lambda context: {"answer": 42})
        self.assertEqual(notices, [])
        manager.start(job)
        for _ in range(100):
            if notices:
                break
            threading.Event().wait(0.01)
        self.assertEqual(notices[-1][0], "job.done")
        self.assertTrue(notices[-1][1]["ok"])
        manager.shutdown()


class ComfyWorkflow(unittest.TestCase):
    def test_turbo_clamps_generic_frontend_sampling_values(self) -> None:
        workflow = ComfyUIProvider._workflow(
            GenerationRequest(prompt="hero", steps=20, cfg=7),
            "sd_xl_turbo_fp16.safetensors",
            12,
            "test",
        )
        sampler = workflow["5"]["inputs"]
        self.assertEqual(sampler["steps"], 4)
        self.assertEqual(sampler["cfg"], 1.0)


class DaemonV2(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = Project.init(self.root / "v2.spritework")
        rgba = np.zeros((32, 32, 4), np.uint8)
        rgba[8:24, 10:22] = (220, 50, 80, 255)
        self.project.commit("seed", assets={"hero": frame_set(rgba)})
        self.notices = []
        self.daemon = Daemon(
            generation_provider=FakeProvider(),
            notify=lambda method, params: self.notices.append((method, params)),
        )
        self.daemon.handle(
            {
                "id": 1,
                "method": "project.open",
                "params": {"path": str(self.project.root)},
            }
        )

    def tearDown(self) -> None:
        self.daemon.jobs.shutdown()
        self.tmp.cleanup()

    def call(self, method: str, **params):
        return self.daemon.handle({"id": 2, "method": method, "params": params})

    def test_outline_and_pixelify_commit(self) -> None:
        preview = self.call("outline.analyze", asset="hero")
        self.assertTrue(Path(preview["result"]["frames"][0]["path"]).is_file())
        applied = self.call(
            "pixelify.apply", asset="hero", targetWidth=16, palette="pico8"
        )
        self.assertTrue(applied["ok"], applied)
        self.assertIn("hero_px", Project.open(self.project.root).asset_names())

    def test_generation_is_async_then_commits(self) -> None:
        provider = self.call("generate.providers")
        self.assertTrue(provider["ok"])
        submitted = self.call("generate.submit", prompt="red knight", count=2)
        job = submitted["result"]["job"]
        self.assertEqual(self.notices, [], "worker started before submit reply")
        self.daemon.start_pending_jobs()
        for _ in range(200):
            if any(method == "job.done" for method, _ in self.notices):
                break
            threading.Event().wait(0.01)
        done = next(params for method, params in self.notices if method == "job.done")
        self.assertEqual(done["job"], job)
        ids = [candidate["id"] for candidate in done["result"]["candidates"]]
        committed = self.call("generate.commit", candidates=ids, recover=True)
        self.assertTrue(committed["ok"], committed)
        self.assertEqual(len(committed["result"]["outputs"]), 2)


if __name__ == "__main__":
    unittest.main()
