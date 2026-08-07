"""Export: staging safety, overwrite refusal, JSON shape, round trip."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from sprite_workshop.errors import RefusedError, UsageError
from sprite_workshop.export import ExportSpec, export_atlas, export_frames
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage
from sprite_workshop.packing import PackSpec, pack_frames


def make_frame(
    frame_id: str, color: tuple[int, int, int, int] = (200, 60, 80, 255)
) -> Frame:
    array = np.zeros((8, 8, 4), np.uint8)
    array[2:6, 2:6] = color
    image = RgbaImage(array)
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, 8, 8),
        trim_offset=Point(0, 0),
        anchor=Point(4, 8),
        tags={"action": "walk"},
    )


class ExportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.frames = FrameSet(
            id="walk", frames=(make_frame("walk_00"), make_frame("walk_01"))
        )
        self.atlas = pack_frames(self.frames, PackSpec(layout="horizontal", trim=True))

    def tearDown(self) -> None:
        self._tmp.cleanup()


class AtlasExport(ExportTestCase):
    def test_writes_pages_and_json(self) -> None:
        bundle = export_atlas(self.atlas, self.root / "out")
        names = {p.name for p in bundle.files}
        self.assertEqual(names, {"page_0.png", "atlas.json"})
        for path in bundle.files:
            self.assertTrue(path.is_file())

    def test_json_describes_every_frame(self) -> None:
        export_atlas(self.atlas, self.root / "out")
        payload = json.loads(
            (self.root / "out" / "atlas.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(payload["pages"][0]["file"], "page_0.png")
        entry = payload["frames"][0]
        self.assertEqual(entry["tags"], {"action": "walk"})
        self.assertEqual(len(entry["rect"]), 4)

    def test_page_dimensions_match_the_json(self) -> None:
        export_atlas(self.atlas, self.root / "out")
        payload = json.loads(
            (self.root / "out" / "atlas.json").read_text(encoding="utf-8")
        )
        with Image.open(self.root / "out" / "page_0.png") as handle:
            self.assertEqual(
                handle.size,
                (payload["pages"][0]["width"], payload["pages"][0]["height"]),
            )

    def test_atlas_round_trips_back_to_the_source_frames(self) -> None:
        """The point of the metadata: rebuild each frame from the atlas."""

        export_atlas(self.atlas, self.root / "out")
        payload = json.loads(
            (self.root / "out" / "atlas.json").read_text(encoding="utf-8")
        )
        page = np.array(Image.open(self.root / "out" / "page_0.png").convert("RGBA"))

        for entry, original in zip(payload["frames"], self.frames.frames):
            x, y, w, h = entry["rect"]
            ox, oy = entry["trim_offset"]
            sw, sh = entry["source_size"]
            rebuilt = np.zeros((sh, sw, 4), np.uint8)
            rebuilt[oy : oy + h, ox : ox + w] = page[y : y + h, x : x + w]
            np.testing.assert_array_equal(rebuilt, original.image.array)

    def test_custom_name(self) -> None:
        bundle = export_atlas(self.atlas, self.root / "out", ExportSpec(name="chouko"))
        self.assertIn("chouko.json", {p.name for p in bundle.files})

    def test_empty_name_is_rejected(self) -> None:
        with self.assertRaises(UsageError):
            ExportSpec(name="")


class FrameExport(ExportTestCase):
    def test_writes_one_png_per_frame(self) -> None:
        bundle = export_frames(self.frames, self.root / "seq")
        self.assertEqual({p.name for p in bundle.files}, {"walk_00.png", "walk_01.png"})

    def test_pixels_survive(self) -> None:
        export_frames(self.frames, self.root / "seq")
        written = np.array(
            Image.open(self.root / "seq" / "walk_00.png").convert("RGBA")
        )
        np.testing.assert_array_equal(written, self.frames.frames[0].image.array)

    def test_wrong_format_for_the_helper(self) -> None:
        with self.assertRaises(UsageError):
            export_frames(
                self.frames, self.root / "seq", ExportSpec(format="generic-json")
            )


class Safety(ExportTestCase):
    def test_refuses_to_overwrite(self) -> None:
        export_atlas(self.atlas, self.root / "out")
        with self.assertRaises(RefusedError):
            export_atlas(self.atlas, self.root / "out")

    def test_overwrite_replaces(self) -> None:
        export_atlas(self.atlas, self.root / "out")
        bundle = export_atlas(self.atlas, self.root / "out", ExportSpec(overwrite=True))
        self.assertEqual(len(bundle.files), 2)

    def test_unrelated_files_do_not_block_the_export(self) -> None:
        target = self.root / "out"
        target.mkdir()
        (target / "notes.txt").write_text("keep me", encoding="utf-8")

        export_atlas(self.atlas, target)
        self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "keep me")

    def test_failure_leaves_no_staging_directory(self) -> None:
        target = self.root / "out"

        broken = FrameSet(id="x", frames=(make_frame("ok"),))
        original = broken.frames[0].image

        class Exploding:
            width = original.width
            height = original.height
            size = original.size

            @property
            def array(self):
                raise RuntimeError("disk on fire")

            def normalized(self):
                raise RuntimeError("disk on fire")

        exploding = FrameSet(
            id="x",
            frames=(
                Frame(
                    id="boom",
                    image=Exploding(),  # type: ignore[arg-type]
                    source_size=original.size,
                    trim_rect=Rect(0, 0, 8, 8),
                    trim_offset=Point(0, 0),
                    anchor=Point(4, 8),
                ),
            ),
        )

        with self.assertRaises(RuntimeError):
            export_frames(exploding, target)

        staging = target.parent / f".{target.name}.staging"
        self.assertFalse(staging.exists(), "staging must be cleaned up on failure")

    def test_failure_does_not_touch_an_existing_export(self) -> None:
        target = self.root / "out"
        export_atlas(self.atlas, target)
        before = (target / "atlas.json").read_bytes()

        with self.assertRaises(RefusedError):
            export_atlas(self.atlas, target)
        self.assertEqual((target / "atlas.json").read_bytes(), before)

    def test_planned_presets_are_refused_by_name(self) -> None:
        for preset in ("godot", "unity", "rpgmaker"):
            with self.subTest(preset=preset):
                with self.assertRaises(UsageError) as ctx:
                    ExportSpec(format=preset)  # type: ignore[arg-type]
                self.assertIn("not implemented", ctx.exception.message)

    def test_unknown_format(self) -> None:
        with self.assertRaises(UsageError):
            ExportSpec(format="dds")  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
