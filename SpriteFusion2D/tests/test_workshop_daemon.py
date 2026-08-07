"""Daemon RPC contract: envelopes, error codes, previews, writes, undo.

Exercised through ``Daemon.handle`` rather than a subprocess: the transport is
already covered by the frontend's own contract tests, and this keeps the
behaviour tests fast.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from sprite_workshop.daemon import PROTOCOL_VERSION, Daemon
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage
from sprite_workshop.project import Project

GREEN = (39, 154, 63)
ROBE = (154, 48, 74)
# A quarter-blend of the two: Lab distance ~22 from GREEN, ~80 from ROBE.  It
# gives the tolerance slider something to actually cross.
EDGE = (67, 127, 65)


def make_frame_set() -> FrameSet:
    rgb = np.zeros((16, 16, 3), np.uint8)
    rgb[:, :] = GREEN
    rgb[4:12, 4:12] = ROBE
    rgb[7, 7] = GREEN  # interior pixel that border connectivity must keep
    rgb[0, 5] = EDGE  # anti-aliased edge pixel on the border
    rgba = np.dstack([rgb, np.full((16, 16), 255, np.uint8)])
    image = RgbaImage(rgba)
    frame = Frame(
        id="f0",
        image=image,
        source_size=image.size,
        trim_rect=Rect(0, 0, 16, 16),
        trim_offset=Point(0, 0),
        anchor=Point(8, 16),
    )
    return FrameSet(id="hero", frames=(frame,))


class DaemonTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = Project.init(
            self.root / "d.spritework", name="蝶子", project_id="d"
        )
        self.project.commit("recover", assets={"hero": make_frame_set()})
        self.daemon = Daemon()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, method: str, **params):
        return self.daemon.handle({"id": 1, "method": method, "params": params})

    def open_project(self):
        return self.call("project.open", path=str(self.project.root))


class Envelope(DaemonTestCase):
    def test_hello_shape(self) -> None:
        reply = self.call("app.hello")
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["result"]["schema_version"], PROTOCOL_VERSION)
        self.assertTrue(reply["result"]["real_backend"])
        for key in ("command", "project", "revision", "outputs", "warnings", "metrics"):
            self.assertIn(key, reply)

    def test_unknown_method_is_code_2(self) -> None:
        reply = self.call("no.such.thing")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 2)

    def test_missing_project_is_code_3(self) -> None:
        reply = self.call("project.tree")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 3)

    def test_cancel_is_accepted_silently(self) -> None:
        self.assertIsNone(
            self.daemon.handle({"method": "$cancel", "params": {"request": 1}})
        )

    def test_unexpected_failure_maps_to_code_4(self) -> None:
        def boom(_params):
            raise RuntimeError("kaboom")

        self.daemon.methods["boom"] = boom
        reply = self.call("boom")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 4)
        self.assertIn("kaboom", reply["error"]["message"])


class ProjectMethods(DaemonTestCase):
    def test_open_reports_manifest(self) -> None:
        reply = self.open_project()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["result"]["name"], "蝶子")
        self.assertEqual(reply["result"]["head_revision"], 1)

    def test_tree_groups(self) -> None:
        self.open_project()
        groups = {g["id"]: g for g in self.call("project.tree")["result"]["groups"]}
        self.assertEqual({"sources", "assets", "framesets", "clips"}, set(groups))
        names = [i["id"] for i in groups["assets"]["items"]]
        self.assertIn("hero", names)

    def test_asset_frames_serves_committed_pngs(self) -> None:
        self.open_project()
        frames = self.call("asset.frames", asset="hero")["result"]["frames"]
        self.assertEqual(len(frames), 1)
        self.assertTrue(Path(frames[0]["path"]).is_file())
        self.assertEqual((frames[0]["width"], frames[0]["height"]), (16, 16))

    def test_missing_asset_is_code_3(self) -> None:
        self.open_project()
        reply = self.call("asset.frames", asset="nope")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 3)

    def test_doctor_lists_checks(self) -> None:
        names = {c["name"] for c in self.call("doctor")["result"]["checks"]}
        self.assertIn("Pillow", names)
        self.assertIn("RPC 契约", names)


class BackgroundPreview(DaemonTestCase):
    def test_analyze_writes_previews_to_cache_not_assets(self) -> None:
        self.open_project()
        reply = self.call("background.analyze", asset="hero", mode="exact", tolerance=0)
        self.assertTrue(reply["ok"])

        result = reply["result"]
        self.assertEqual(result["analysis"]["chosen"]["rgb"], list(GREEN))
        frame = result["frames"][0]
        for key in ("path", "maskPath"):
            path = Path(frame[key])
            self.assertTrue(path.is_file(), key)
            self.assertIn("cache", path.parts)

        # A preview must never touch the committed state.
        self.assertEqual(Project.open(self.project.root).head_revision, 1)
        self.assertEqual(
            sorted(Project.open(self.project.root).asset_names()), ["hero"]
        )

    def test_analyze_reacts_to_tolerance(self) -> None:
        """Crossing the edge pixel's distance must change the result."""

        self.open_project()
        low = self.call("background.analyze", asset="hero", mode="lab", tolerance=1)
        high = self.call("background.analyze", asset="hero", mode="lab", tolerance=40)
        self.assertEqual(
            high["result"]["analysis"]["erased_pixels"],
            low["result"]["analysis"]["erased_pixels"] + 1,
            "raising tolerance past the edge pixel should catch exactly it",
        )

    def test_preview_cache_is_reused(self) -> None:
        self.open_project()
        first = self.call("background.analyze", asset="hero", tolerance=10)
        second = self.call("background.analyze", asset="hero", tolerance=10)
        self.assertEqual(
            first["result"]["frames"][0]["path"], second["result"]["frames"][0]["path"]
        )

    def test_every_accepted_setting_changes_the_cache_key(self) -> None:
        """The key used to name only mode/tolerance/connectivity.

        Every other setting the RPC accepts silently re-served the previous
        PNG, so toggling border-only or switching to soft alpha showed the
        user a preview of the settings they had just moved away from.
        """

        self.open_project()
        base = dict(asset="hero", mode="lab", tolerance=10)
        baseline = self.call("background.analyze", **base)["result"]["frames"][0][
            "path"
        ]

        variants = {
            "samples": "border",
            "borderOnly": False,
            "minIslandArea": 4,
            "maxHoleArea": 4,
            "alpha": "soft",
            "softRange": 9.0,
            "connectivity": 4,
        }
        for key, value in variants.items():
            with self.subTest(setting=key):
                reply = self.call("background.analyze", **{**base, key: value})
                self.assertTrue(reply["ok"], reply)
                self.assertNotEqual(
                    reply["result"]["frames"][0]["path"],
                    baseline,
                    f"changing {key} reused the previous preview file",
                )

    def test_preview_cache_is_pruned(self) -> None:
        self.open_project()
        cache = self.project.root / "cache" / "prev"
        cache.mkdir(parents=True, exist_ok=True)
        for index in range(450):
            (cache / f"stale_{index:04d}.png").write_bytes(b"")

        self.call("background.analyze", asset="hero", tolerance=10)
        self.assertLessEqual(len(list(cache.glob("*.png"))), 400)

    def test_a_new_asset_version_invalidates_the_preview(self) -> None:
        self.open_project()
        before = self.call("background.analyze", asset="hero", tolerance=10)
        self.call("background.apply", asset="hero", tolerance=10, **{"as": "hero"})
        after = self.call("background.analyze", asset="hero", tolerance=10)
        self.assertNotEqual(
            before["result"]["frames"][0]["path"],
            after["result"]["frames"][0]["path"],
        )


class BackgroundApply(DaemonTestCase):
    def test_apply_commits_frames_and_mask(self) -> None:
        self.open_project()
        reply = self.call("background.apply", asset="hero", mode="exact", tolerance=0)
        self.assertTrue(reply["ok"], reply.get("error"))

        result = reply["result"]
        self.assertEqual(result["revision"], 2)
        self.assertEqual(sorted(result["outputs"]), ["hero_clean", "hero_clean_mask"])

        reopened = Project.open(self.project.root)
        self.assertEqual(reopened.head_revision, 2)
        cleaned = reopened.load_asset("hero_clean")
        alpha = cleaned.frames[0].image.array[:, :, 3]
        self.assertEqual(int(alpha[0, 0]), 0, "background erased")
        self.assertEqual(int(alpha[7, 7]), 255, "interior colour kept")

    def test_apply_honours_a_custom_name(self) -> None:
        self.open_project()
        reply = self.call(
            "background.apply", asset="hero", tolerance=10, **{"as": "cut"}
        )
        self.assertEqual(sorted(reply["result"]["outputs"]), ["cut", "cut_mask"])

    def test_apply_without_a_project_is_code_3(self) -> None:
        reply = self.call("background.apply", asset="hero")
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 3)

    def test_invalid_spec_is_code_2(self) -> None:
        self.open_project()
        reply = self.call("background.apply", asset="hero", tolerance=-5)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], 2)


class History(DaemonTestCase):
    def test_undo_and_redo_move_the_head(self) -> None:
        self.open_project()
        self.call("background.apply", asset="hero", mode="exact", tolerance=0)

        undone = self.call("history.undo", steps=1)
        self.assertTrue(undone["ok"])
        self.assertEqual(undone["result"]["revision"], 1)
        self.assertTrue(undone["result"]["changed"])
        self.assertEqual(Project.open(self.project.root).asset_names(), ["hero"])

        redone = self.call("history.redo", steps=1)
        self.assertEqual(redone["result"]["revision"], 2)
        self.assertIn("hero_clean", Project.open(self.project.root).asset_names())

    def test_undo_past_the_start_reports_a_warning(self) -> None:
        self.open_project()
        reply = self.call("history.undo", steps=99)
        codes = {w["code"] for w in reply["result"]["warnings"]}
        self.assertIn("history.at_start", codes)

    def test_list_reports_the_chain(self) -> None:
        self.open_project()
        self.call("background.apply", asset="hero", tolerance=10)
        entries = self.call("history.list")["result"]["entries"]
        self.assertEqual(entries[0]["operation"], "background.remove")
        self.assertEqual(entries[1]["operation"], "recover")

    def test_committing_after_undo_reports_the_fork(self) -> None:
        self.open_project()
        self.call("background.apply", asset="hero", tolerance=10)
        self.call("history.undo", steps=1)

        reply = self.call("background.apply", asset="hero", tolerance=20)
        codes = {w["code"] for w in reply["result"]["warnings"]}
        self.assertIn("history.forked", codes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
