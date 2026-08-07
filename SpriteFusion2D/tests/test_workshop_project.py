"""Project transactions, asset versions, revision tree, undo/redo and forking."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from sprite_workshop.errors import (
    NotFoundError,
    OperationError,
    RefusedError,
    UsageError,
)
from sprite_workshop.model import Frame, FrameSet, Point, Rect, RgbaImage
from sprite_workshop.project import Project, ProjectLock


def make_frame_set(set_id: str, value: int, count: int = 2) -> FrameSet:
    frames = []
    for index in range(count):
        array = np.zeros((3, 4, 4), dtype=np.uint8)
        array[:, :, :3] = value
        array[:, :, 3] = 255
        image = RgbaImage(array)
        frames.append(
            Frame(
                id=f"{set_id}_{index:02d}",
                image=image,
                source_size=image.size,
                trim_rect=Rect(0, 0, image.width, image.height),
                trim_offset=Point(0, 0),
                anchor=Point(2, 3),
                label="蝶子",
                tags={"action": "walk"},
            )
        )
    return FrameSet(id=set_id, frames=tuple(frames))


class ProjectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # A Chinese display name over an ASCII id is the intended split.
        self.project = Project.init(self.root / "chouko.spritework", name="蝶子")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class Initialisation(ProjectTestCase):
    def test_creates_the_documented_layout(self) -> None:
        for sub in ("sources", "assets", "revisions", "recipes", "cache", "exports"):
            self.assertTrue((self.project.root / sub).is_dir(), sub)
        self.assertTrue((self.project.root / "manifest.json").is_file())

    def test_manifest_fields(self) -> None:
        manifest = self.project.manifest
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["project_id"], "chouko")
        self.assertEqual(manifest["name"], "蝶子")
        self.assertEqual(manifest["head_revision"], 0)
        self.assertEqual(manifest["redo_stack"], [])

    def test_manifest_is_utf8_json(self) -> None:
        text = (self.project.root / "manifest.json").read_text(encoding="utf-8")
        self.assertIn("蝶子", text)
        json.loads(text)

    def test_refuses_non_empty_directory(self) -> None:
        busy = self.root / "busy"
        busy.mkdir()
        (busy / "x.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(RefusedError):
            Project.init(busy)

    def test_open_rejects_a_plain_directory(self) -> None:
        with self.assertRaises(NotFoundError):
            Project.open(self.root)

    def test_rejects_unknown_schema_version(self) -> None:
        manifest_path = self.project.root / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 999
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(OperationError):
            Project.open(self.project.root)


class Commits(ProjectTestCase):
    def test_commit_creates_revision_and_asset(self) -> None:
        report = self.project.commit(
            "recover", assets={"hero": make_frame_set("hero", 10)}
        )
        self.assertEqual(report.revision, 1)
        self.assertEqual(report.outputs, ("hero",))
        self.assertEqual(self.project.head_revision, 1)
        self.assertEqual(self.project.assets["hero"].version, 1)
        self.assertTrue(self.project.revision_path(1).is_file())

    def test_asset_round_trips_including_metadata(self) -> None:
        original = make_frame_set("hero", 42)
        self.project.commit("recover", assets={"hero": original})
        loaded = self.project.load_asset("hero")

        self.assertEqual(len(loaded), len(original))
        for before, after in zip(original.frames, loaded.frames):
            self.assertEqual(after.id, before.id)
            self.assertEqual(after.label, before.label)
            self.assertEqual(dict(after.tags), dict(before.tags))
            self.assertEqual(after.anchor, before.anchor)
            self.assertEqual(after.trim_rect, before.trim_rect)
            np.testing.assert_array_equal(after.image.array, before.image.array)

    def test_second_write_bumps_the_version(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 20)})
        self.assertEqual(self.project.assets["hero"].version, 2)
        # Old version is still on disk and still loadable.
        self.assertEqual(
            int(self.project.load_asset("hero", 1).frames[0].image.array[0, 0, 0]), 10
        )
        self.assertEqual(
            int(self.project.load_asset("hero", 2).frames[0].image.array[0, 0, 0]), 20
        )

    def test_revision_record_has_parent_and_asset_state(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 20)})

        first = self.project.read_revision(1)
        second = self.project.read_revision(2)
        self.assertIsNone(first.parent_revision)
        self.assertEqual(second.parent_revision, 1)
        self.assertEqual(first.assets_after, {"hero": 1})
        self.assertEqual(second.assets_after, {"hero": 2})

    def test_revision_records_device_and_dependencies(self) -> None:
        self.project.commit(
            "recover", assets={"hero": make_frame_set("hero", 1)}, device="cpu"
        )
        record = self.project.read_revision(1)
        self.assertEqual(record.device, "cpu")
        self.assertIn("numpy", record.dependencies)

    def test_transparent_rgb_normalised_on_write(self) -> None:
        array = np.zeros((2, 2, 4), dtype=np.uint8)
        array[:, :, :3] = 200  # hidden colour under full transparency
        image = RgbaImage(array)
        frame_set = FrameSet(
            id="mask",
            frames=(
                Frame(
                    id="mask_00",
                    image=image,
                    source_size=image.size,
                    trim_rect=Rect(0, 0, 2, 2),
                    trim_offset=Point(0, 0),
                    anchor=Point(1, 2),
                ),
            ),
        )
        self.project.commit("import", assets={"mask": frame_set})
        loaded = self.project.load_asset("mask")
        self.assertFalse(loaded.frames[0].image.has_hidden_color())

    def test_rejects_invalid_asset_name(self) -> None:
        with self.assertRaises(UsageError):
            self.project.commit("x", assets={"Hero Walk": make_frame_set("h", 1)})

    def test_missing_asset_reports_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.project.load_asset("nope")


class Sources(ProjectTestCase):
    def test_import_keeps_original_bytes(self) -> None:
        origin = self.root / "in.png"
        payload = b"\x89PNG\r\n\x1a\n not-really-a-png but bytes must survive"
        origin.write_bytes(payload)

        target = self.project.import_source(origin, as_name="hero_source")
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(self.project.find_source("hero_source"), target)

    def test_import_refuses_to_overwrite(self) -> None:
        origin = self.root / "in.png"
        origin.write_bytes(b"data")
        self.project.import_source(origin, as_name="hero_source")
        with self.assertRaises(RefusedError):
            self.project.import_source(origin, as_name="hero_source")

    def test_missing_file(self) -> None:
        with self.assertRaises(NotFoundError):
            self.project.import_source(self.root / "absent.png", as_name="x")


class UndoRedo(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 20)})
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 30)})

    def test_undo_moves_head_and_asset_version(self) -> None:
        self.project.undo()
        self.assertEqual(self.project.head_revision, 2)
        self.assertEqual(self.project.assets["hero"].version, 2)
        self.assertEqual(
            int(self.project.load_asset("hero").frames[0].image.array[0, 0, 0]), 20
        )

    def test_redo_restores(self) -> None:
        self.project.undo()
        self.project.redo()
        self.assertEqual(self.project.head_revision, 3)
        self.assertEqual(
            int(self.project.load_asset("hero").frames[0].image.array[0, 0, 0]), 30
        )

    def test_multi_step(self) -> None:
        self.project.undo(steps=2)
        self.assertEqual(self.project.head_revision, 1)
        self.project.redo(steps=2)
        self.assertEqual(self.project.head_revision, 3)

    def test_undo_past_the_start_warns_and_stops(self) -> None:
        report = self.project.undo(steps=99)
        self.assertEqual(self.project.head_revision, 0)
        self.assertEqual(report.metrics["undone"], 3)
        self.assertTrue(any(w.code == "history.at_start" for w in report.warnings))
        self.assertEqual(self.project.assets, {})

    def test_redo_past_the_end_warns(self) -> None:
        report = self.project.redo()
        self.assertTrue(any(w.code == "history.at_end" for w in report.warnings))

    def test_history_walks_the_ancestry_chain(self) -> None:
        revisions = [r.revision for r in self.project.history()]
        self.assertEqual(revisions, [3, 2, 1])
        self.project.undo()
        self.assertEqual([r.revision for r in self.project.history()], [2, 1])

    def test_committing_from_history_forks_and_warns(self) -> None:
        self.project.undo(steps=2)
        self.assertEqual(self.project.redo_stack, [3, 2])

        report = self.project.commit(
            "edit", assets={"hero": make_frame_set("hero", 99)}
        )

        self.assertTrue(any(w.code == "history.forked" for w in report.warnings))
        self.assertEqual(self.project.redo_stack, [])
        # The new revision descends from where the head actually was.
        self.assertEqual(self.project.read_revision(report.revision).parent_revision, 1)
        # Abandoned revisions are unreachable but not deleted.
        self.assertTrue(self.project.revision_path(3).is_file())

    def test_forking_does_not_rewrite_the_abandoned_branch_pixels(self) -> None:
        """A revision record must keep pointing at the pixels it committed.

        Versions used to be allocated as `manifest version + 1`, but undo moves
        the manifest back, so the fork re-used a version number the abandoned
        branch already owned and overwrote its PNGs in place.  Revision 3 then
        described bytes that no longer existed.
        """

        abandoned = self.project.read_revision(3).assets_after["hero"]
        self.project.undo(steps=2)
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 99)})

        forked = self.project.assets["hero"].version
        self.assertNotEqual(forked, abandoned)

        # Revision 3 is unreachable through undo/redo once the branch is
        # abandoned, so read its payload the way a recovery tool would: by the
        # version the record itself names.  It must still say 30, not 99.
        self.assertTrue((self.project.asset_dir("hero", abandoned)).is_dir())
        self.assertEqual(
            int(
                self.project.load_asset("hero", abandoned)
                .frames[0]
                .image.array[0, 0, 0]
            ),
            30,
        )

    def test_asset_versions_never_decrease_across_forks(self) -> None:
        seen = {self.project.assets["hero"].version}
        for value in (40, 50, 60):
            self.project.undo()
            self.project.commit("edit", assets={"hero": make_frame_set("hero", value)})
            version = self.project.assets["hero"].version
            self.assertNotIn(version, seen)
            seen.add(version)

    def test_steps_must_be_positive(self) -> None:
        with self.assertRaises(UsageError):
            self.project.undo(steps=0)
        with self.assertRaises(UsageError):
            self.project.redo(steps=-1)


class Locking(ProjectTestCase):
    """RefusedError has documented a lock since v1; now one exists."""

    def test_a_held_lock_refuses_a_concurrent_commit(self) -> None:
        with ProjectLock(self.project.root):
            with self.assertRaises(RefusedError) as caught:
                self.project.commit(
                    "recover", assets={"hero": make_frame_set("hero", 10)}
                )
        self.assertIn("locked", caught.exception.message)
        # Nothing was written while the lock was held.
        self.assertEqual(self.project.head_revision, 0)

    def test_a_held_lock_refuses_undo(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        with ProjectLock(self.project.root):
            with self.assertRaises(RefusedError):
                self.project.undo()

    def test_the_lock_is_released_after_a_commit(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        self.assertFalse((self.project.root / ".lock").exists())
        # A second commit must therefore succeed.
        self.project.commit("edit", assets={"hero": make_frame_set("hero", 20)})
        self.assertEqual(self.project.head_revision, 2)

    def test_the_lock_is_released_when_a_commit_fails(self) -> None:
        with self.assertRaises(UsageError):
            self.project.commit("bad", assets={"Not-An-Id": make_frame_set("x", 1)})
        self.assertFalse((self.project.root / ".lock").exists())

    def test_a_stale_lock_from_a_dead_process_is_broken(self) -> None:
        """A crash must not leave the project permanently unusable."""

        lock_path = self.project.root / ".lock"
        # A pid that cannot be running: os.getpid() is never 2**31 - 1.
        lock_path.write_text(
            json.dumps({"pid": 2**31 - 1, "at": "2026-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        report = self.project.commit(
            "recover", assets={"hero": make_frame_set("hero", 10)}
        )
        self.assertEqual(report.revision, 1)
        self.assertFalse(lock_path.exists())


class PathSafety(ProjectTestCase):
    def test_asset_meta_rejects_traversal(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        meta_path = self.project.asset_dir("hero", 1) / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["frames"][0]["file"] = "../../../../etc/passwd"
        meta_path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(RefusedError):
            self.project.load_asset("hero")

    def test_asset_meta_rejects_a_traversing_frame_id(self) -> None:
        """A frame id is a filename component in three places downstream.

        `file` was guarded but `id` was not, so a hand-edited meta.json could
        keep a perfectly valid `file` and still steer _write_asset_version, the
        frames exporter and the daemon's preview path outside the project.
        """

        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        meta_path = self.project.asset_dir("hero", 1) / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["frames"][0]["id"] = "../../../../etc/passwd"
        meta_path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(UsageError):
            self.project.load_asset("hero")

    def test_asset_meta_rejects_an_absolute_frame_id(self) -> None:
        self.project.commit("recover", assets={"hero": make_frame_set("hero", 10)})
        meta_path = self.project.asset_dir("hero", 1) / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["frames"][0]["id"] = "C:/Windows/System32/config/SAM"
        meta_path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(UsageError):
            self.project.load_asset("hero")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
