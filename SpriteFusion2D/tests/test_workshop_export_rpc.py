"""export.apply RPC contract: strict types, path safety, packing options.

Exercised through ``Daemon.handle`` like the other daemon behaviour tests; the
deep-module semantics (staging, atlas JSON shape, pixel round trip) are covered
by tests/test_workshop_export.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from sprite_workshop.daemon import Daemon
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage
from sprite_workshop.project import Project


def _frame(frame_id: str, color: tuple[int, int, int]) -> Frame:
    rgba = np.zeros((16, 16, 4), np.uint8)
    rgba[:, :, 3] = 255
    rgba[4:12, 4:12] = (*color, 255)
    image = RgbaImage(rgba)
    return Frame(
        id=frame_id,
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, 16, 16),
        trim_offset=Point(0, 0),
        anchor=Point(8, 16),
    )


def make_frame_set() -> FrameSet:
    return FrameSet(
        id="hero",
        frames=(_frame("f0", (200, 60, 80)), _frame("f1", (40, 120, 200))),
    )


class ExportRpcTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = Project.init(
            self.root / "d.spritework", name="??", project_id="d"
        )
        self.project.commit("import", assets={"hero": make_frame_set()})
        self.project.commit("empty", assets={"empty": FrameSet(id="empty", frames=())})
        self.daemon = Daemon()
        opened = self.daemon.handle(
            {
                "id": 1,
                "method": "project.open",
                "params": {"path": str(self.project.root)},
            }
        )
        self.assertTrue(opened["ok"])
        self.out = self.root / "out"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, method: str, **params) -> dict:
        return self.daemon.handle({"id": 1, "method": method, "params": params})


class Envelope(ExportRpcTestCase):
    def test_no_project_is_code_3(self) -> None:
        reply = Daemon().handle(
            {
                "id": 1,
                "method": "export.apply",
                "params": {"asset": "hero", "output": "out"},
            }
        )
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 3)
        self.assertIn("no project", reply["error"]["message"])

    def test_missing_asset_or_output_is_code_2(self) -> None:
        for params in ({"output": str(self.out)}, {"asset": "hero"}):
            reply = self.call("export.apply", **params)
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"]["code"], 2, params)

    def test_unknown_asset_is_code_3(self) -> None:
        reply = self.call("export.apply", asset="nope", output=str(self.out))
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 3)
        self.assertIn("asset not found", reply["error"]["message"])


class StrictTypes(ExportRpcTestCase):
    def test_string_false_is_rejected_not_truthy(self) -> None:
        reply = self.call(
            "export.apply", asset="hero", output=str(self.out), overwrite="false"
        )
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 2)
        self.assertIn("overwrite", reply["error"]["message"])

    def test_bool_float_and_string_rejected_for_integer_fields(self) -> None:
        for key, value in (("columns", True), ("padding", "2"), ("extrude", 1.5)):
            reply = self.call(
                "export.apply", asset="hero", output=str(self.out), **{key: value}
            )
            self.assertEqual(reply["error"]["code"], 2, (key, value))

    def test_non_boolean_rejected_for_flags(self) -> None:
        for key, value in (("overwrite", 1), ("trim", "yes"), ("multiPage", 0)):
            reply = self.call(
                "export.apply", asset="hero", output=str(self.out), **{key: value}
            )
            self.assertEqual(reply["error"]["code"], 2, (key, value))

    def test_illegal_format_type_and_unknown_format(self) -> None:
        for fmt in (5, "dds", "godot"):
            reply = self.call(
                "export.apply", asset="hero", output=str(self.out), format=fmt
            )
            self.assertEqual(reply["error"]["code"], 2, fmt)

    def test_illegal_max_size(self) -> None:
        for bad in ("abc", "2048", "2048x2048x1", 2048, [2048, 2048]):
            reply = self.call(
                "export.apply", asset="hero", output=str(self.out), maxSize=bad
            )
            self.assertEqual(reply["error"]["code"], 2, bad)
        reply = self.call(
            "export.apply", asset="hero", output=str(self.out), maxSize="9000x9000"
        )
        self.assertEqual(reply["error"]["code"], 2)
        self.assertIn("page size", reply["error"]["message"])


class NameSafety(ExportRpcTestCase):
    def test_path_traversal_names_are_rejected(self) -> None:
        for bad in ("../evil", "..", "a/b", "a\\b", "C:/evil", "/abs"):
            reply = self.call(
                "export.apply", asset="hero", output=str(self.out), name=bad
            )
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"]["code"], 2, bad)

    def test_empty_name_is_rejected(self) -> None:
        reply = self.call("export.apply", asset="hero", output=str(self.out), name="")
        self.assertEqual(reply["error"]["code"], 2)

    def test_traversal_name_writes_nothing(self) -> None:
        self.call("export.apply", asset="hero", output=str(self.out), name="../evil")
        self.assertFalse((self.root / "evil.json").exists())
        self.assertFalse((self.root.parent / "evil.json").exists())


class EmptyFrames(ExportRpcTestCase):
    def test_empty_frame_set_is_refused_for_both_formats(self) -> None:
        for fmt in ("generic-json", "frames"):
            reply = self.call(
                "export.apply", asset="empty", format=fmt, output=str(self.out)
            )
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"]["code"], 2, fmt)
            self.assertIn("empty", reply["error"]["message"])


class Overwrite(ExportRpcTestCase):
    def test_refuses_then_overwrites(self) -> None:
        first = self.call("export.apply", asset="hero", output=str(self.out))
        self.assertTrue(first["ok"])
        self.assertEqual(len(first["result"]["files"]), 2)

        refused = self.call("export.apply", asset="hero", output=str(self.out))
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["error"]["code"], 7)
        self.assertIn("overwrite", refused["error"]["message"])

        accepted = self.call(
            "export.apply", asset="hero", output=str(self.out), overwrite=True
        )
        self.assertTrue(accepted["ok"])


class Success(ExportRpcTestCase):
    def test_frames_export_writes_one_png_per_frame(self) -> None:
        reply = self.call(
            "export.apply", asset="hero", format="frames", output=str(self.out)
        )
        self.assertTrue(reply["ok"])
        result = reply["result"]
        self.assertEqual(result["asset"], "hero")
        self.assertEqual(result["format"], "frames")
        self.assertEqual(result["revision"], self.project.head_revision)
        self.assertEqual(
            {entry["name"] for entry in result["files"]}, {"f0.png", "f1.png"}
        )
        for path in (self.out / "f0.png", self.out / "f1.png"):
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

    def test_atlas_export_with_pack_options(self) -> None:
        reply = self.call(
            "export.apply",
            asset="hero",
            format="generic-json",
            name="chouko",
            layout="horizontal",
            columns=2,
            padding=2,
            extrude=1,
            trim=True,
            maxSize="512x512",
            multiPage=False,
            output=str(self.out),
        )
        self.assertTrue(reply["ok"])
        result = reply["result"]
        self.assertEqual(
            {entry["name"] for entry in result["files"]},
            {"chouko.json", "page_0.png"},
        )
        payload = json.loads((self.out / "chouko.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(payload["pages"][0]["file"], "page_0.png")

    def test_grid_layout_needs_columns(self) -> None:
        reply = self.call(
            "export.apply",
            asset="hero",
            format="generic-json",
            layout="grid",
            output=str(self.out),
        )
        self.assertEqual(reply["error"]["code"], 2)

    def test_export_does_not_change_project_state(self) -> None:
        before = self.project.head_revision
        reply = self.call("export.apply", asset="hero", output=str(self.out))
        self.assertTrue(reply["ok"])
        reopened = Project.open(self.project.root)
        self.assertEqual(reopened.head_revision, before)
        self.assertEqual(sorted(reopened.asset_names()), ["empty", "hero"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
