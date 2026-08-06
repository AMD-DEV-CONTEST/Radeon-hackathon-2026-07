"""CLI end-to-end through real subprocesses.

Covers what only a subprocess can prove: exit codes, stdout/stderr separation,
strict JSON parseability, and Chinese paths on Windows
(BACKEND_CLI_PLAN.md 11.7).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from PIL import Image

    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_PILLOW = False


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sprite_workshop.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def write_pixel_art(
    path: Path, block: int = 8, cells_x: int = 20, cells_y: int = 16
) -> None:
    rng = np.random.default_rng(20260803)
    palette = rng.integers(0, 256, size=(12, 3), dtype=np.uint8)
    indices = rng.integers(0, len(palette), size=(cells_y, cells_x))
    rgb = np.kron(palette[indices], np.ones((block, block, 1), dtype=np.uint8))
    rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, dtype=np.uint8)])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required for CLI image tests")
class CliEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Chinese directory name on purpose: this is the Windows path case.
        self.project = self.root / "蝶子项目" / "chouko.spritework"
        self.source = self.root / "素材" / "hero.png"
        write_pixel_art(self.source)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def init_project(self) -> None:
        result = run_cli("init", str(self.project), "--name", "蝶子")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_exits_zero(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("sprite-workshop", result.stdout)

    def test_init_with_chinese_name_and_path(self) -> None:
        self.init_project()
        manifest = json.loads(
            (self.project / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "蝶子")
        self.assertEqual(manifest["project_id"], "chouko")

    def test_json_stdout_is_exactly_one_object(self) -> None:
        self.init_project()
        result = run_cli("--project", str(self.project), "--json", "inspect")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)  # strict: no logs mixed in
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "inspect")

    def test_full_pipeline_import_recover_inspect(self) -> None:
        self.init_project()

        imported = run_cli(
            "--project",
            str(self.project),
            "--json",
            "import",
            str(self.source),
            "--as",
            "hero_source",
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(json.loads(imported.stdout)["revision"], 1)

        recovered = run_cli(
            "--project",
            str(self.project),
            "--json",
            "recover",
            "hero_source",
            "--device",
            "cpu",
            "--as",
            "hero_recovered",
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        payload = json.loads(recovered.stdout)
        self.assertEqual(payload["outputs"], ["hero_recovered"])
        self.assertIn("grid_columns", payload["metrics"])

        inspected = run_cli("--project", str(self.project), "--json", "inspect")
        assets = {a["name"] for a in json.loads(inspected.stdout)["result"]["assets"]}
        self.assertIn("hero_recovered", assets)

    def test_both_algorithms_reachable_from_cli(self) -> None:
        self.init_project()
        run_cli(
            "--project", str(self.project), "import", str(self.source), "--as", "src"
        )

        for algorithm in ("optimized", "legacy_exact"):
            with self.subTest(algorithm=algorithm):
                result = run_cli(
                    "--project",
                    str(self.project),
                    "--json",
                    "recover",
                    "src",
                    "--algorithm",
                    algorithm,
                    "--device",
                    "cpu",
                    "--as",
                    f"out_{algorithm}",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout)["metrics"]["algorithm"], algorithm
                )

    def test_dry_run_changes_nothing(self) -> None:
        self.init_project()
        run_cli(
            "--project", str(self.project), "import", str(self.source), "--as", "src"
        )
        before = (self.project / "manifest.json").read_bytes()

        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "--dry-run",
            "recover",
            "src",
            "--device",
            "cpu",
            "--as",
            "never_written",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)
        self.assertFalse((self.project / "assets" / "never_written").exists())

    def test_dry_run_init_creates_nothing(self) -> None:
        target = self.root / "预演" / "chouko.spritework"
        result = run_cli("--json", "--dry-run", "init", str(target), "--name", "蝶子")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["project_id"], "chouko")
        self.assertFalse(target.exists(), "--dry-run init created the project")

    def test_dry_run_init_still_refuses_a_bad_id(self) -> None:
        # The dry run must fail for the same reasons the real one would.
        result = run_cli("--dry-run", "init", str(self.root / "蝶子.spritework"))
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_dry_run_history_does_not_move_the_head(self) -> None:
        self.init_project()
        run_cli(
            "--project", str(self.project), "import", str(self.source), "--as", "src"
        )
        before = (self.project / "manifest.json").read_bytes()

        preview = run_cli(
            "--project", str(self.project), "--json", "--dry-run", "history", "undo"
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        payload = json.loads(preview.stdout)
        # It still reports where the head *would* land.
        self.assertEqual(payload["metrics"]["target_revision"], 0)
        self.assertEqual(payload["metrics"]["steps"], 1)
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

        # And redo is equally inert.
        run_cli("--project", str(self.project), "--dry-run", "history", "redo")
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

    def test_undo_redo_round_trip(self) -> None:
        self.init_project()
        run_cli(
            "--project", str(self.project), "import", str(self.source), "--as", "src"
        )
        run_cli(
            "--project",
            str(self.project),
            "recover",
            "src",
            "--device",
            "cpu",
            "--as",
            "hero",
        )

        undone = run_cli("--project", str(self.project), "--json", "history", "undo")
        self.assertEqual(undone.returncode, 0, undone.stderr)
        self.assertEqual(json.loads(undone.stdout)["revision"], 1)

        redone = run_cli("--project", str(self.project), "--json", "history", "redo")
        self.assertEqual(json.loads(redone.stdout)["revision"], 2)

    def test_history_list_reports_chain(self) -> None:
        self.init_project()
        run_cli(
            "--project", str(self.project), "import", str(self.source), "--as", "src"
        )
        result = run_cli("--project", str(self.project), "--json", "history", "list")
        entries = json.loads(result.stdout)["result"]["entries"]
        self.assertEqual(entries[0]["operation"], "import")

    def test_doctor_json(self) -> None:
        result = run_cli("--json", "doctor")
        payload = json.loads(result.stdout)
        names = {c["name"] for c in payload["result"]["checks"]}
        self.assertIn("pillow", names)
        self.assertIn("torch", names)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required for CLI image tests")
class CliBackground(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "bg.spritework"

        # A blob on a flat field, with a field-coloured pixel inside it.
        rgb = np.zeros((64, 64, 3), np.uint8)
        rgb[:, :] = (39, 154, 63)
        rgb[16:48, 16:48] = (154, 48, 74)
        rgb[32, 32] = (39, 154, 63)
        rgba = np.dstack([rgb, np.full((64, 64), 255, np.uint8)])
        source = self.root / "flat.png"
        Image.fromarray(rgba, mode="RGBA").save(source)

        run_cli("init", str(self.project), "--id", "bg")
        run_cli("--project", str(self.project), "import", str(source), "--as", "src")
        # Import the source straight into an asset via a mask-free path: recover
        # would resample it, and this test is about background only.
        self.source = source

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_asset(self) -> None:
        run_cli(
            "--project",
            str(self.project),
            "recover",
            "src",
            "--device",
            "cpu",
            "--as",
            "hero",
        )

    def test_analyze_reports_the_field_colour(self) -> None:
        self._make_asset()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "background",
            "analyze",
            "hero",
            "--mode",
            "lab",
            "--tolerance",
            "10",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)["result"]
        self.assertEqual(payload["chosen"]["rgb"], [39, 154, 63])
        self.assertGreater(payload["erased_pixels"], 0)

    def test_analyze_does_not_change_the_project(self) -> None:
        self._make_asset()
        before = (self.project / "manifest.json").read_bytes()
        run_cli(
            "--project",
            str(self.project),
            "background",
            "analyze",
            "hero",
            "--tolerance",
            "10",
        )
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

    def test_remove_writes_frames_and_a_mask(self) -> None:
        self._make_asset()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "background",
            "remove",
            "hero",
            "--mode",
            "lab",
            "--tolerance",
            "10",
            "--as",
            "clean",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = json.loads(result.stdout)["outputs"]
        self.assertIn("clean", outputs)
        self.assertIn("clean_mask", outputs)

    def test_mask_round_trips_through_apply_mask(self) -> None:
        self._make_asset()
        run_cli(
            "--project",
            str(self.project),
            "background",
            "remove",
            "hero",
            "--tolerance",
            "10",
            "--as",
            "clean",
        )
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "background",
            "apply-mask",
            "hero",
            "--mask",
            "clean_mask",
            "--as",
            "reapplied",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        clean = Image.open(
            next((self.project / "assets" / "clean").rglob("*.png"))
        ).convert("RGBA")
        reapplied = Image.open(
            next((self.project / "assets" / "reapplied").rglob("*.png"))
        ).convert("RGBA")
        np.testing.assert_array_equal(np.array(clean), np.array(reapplied))

    def test_explicit_colour_flag(self) -> None:
        self._make_asset()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "background",
            "analyze",
            "hero",
            "--color",
            "#279A3F",
            "--mode",
            "exact",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_colour_is_usage_error(self) -> None:
        self._make_asset()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "background",
            "analyze",
            "hero",
            "--color",
            "nope",
        )
        self.assertEqual(result.returncode, 2)

    def test_dry_run_writes_nothing(self) -> None:
        self._make_asset()
        before = (self.project / "manifest.json").read_bytes()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "--dry-run",
            "background",
            "remove",
            "hero",
            "--tolerance",
            "10",
            "--as",
            "never",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)
        self.assertFalse((self.project / "assets" / "never").exists())


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required for CLI image tests")
class CliSplit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "s.spritework"
        run_cli("init", str(self.project), "--id", "s")

        # A 4x2 sheet of blobs, already transparent: straight into an asset via
        # the project API would need Python, so go through import + recover.
        rgba = np.zeros((64, 128, 4), np.uint8)
        for r in range(2):
            for c in range(4):
                y, x = r * 32 + 6, c * 32 + 6
                rgba[y : y + 20, x : x + 20, :3] = (40 + r * 80, 60 + c * 40, 120)
                rgba[y : y + 20, x : x + 20, 3] = 255
        source = self.root / "sheet.png"
        Image.fromarray(rgba, mode="RGBA").save(source)
        run_cli("--project", str(self.project), "import", str(source), "--as", "src")

        # Recovery would resample; for a slicing test we want the sheet as-is,
        # so recover with a forced 1:1 by using the already-1x image.
        run_cli(
            "--project",
            str(self.project),
            "recover",
            "src",
            "--device",
            "cpu",
            "--as",
            "sheet",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _sheet_size(self) -> tuple[int, int]:
        result = run_cli("--project", str(self.project), "--json", "inspect")
        assets = json.loads(result.stdout)["result"]["assets"]
        return next(a for a in assets if a["name"] == "sheet")["frames"], 0

    def test_grid_split_names_and_tags(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "split",
            "sheet",
            "--mode",
            "grid",
            "--columns",
            "4",
            "--rows",
            "2",
            "--tail",
            "crop",
            "--tag",
            "action=walk",
            "--tag-row",
            "0:direction=south",
            "--tag-row",
            "1:direction=north",
            "--name-template",
            "{tag:action}_{tag:direction}_{index:02d}",
            "--as",
            "walk",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outputs"], ["walk"])

        inspected = run_cli("--project", str(self.project), "--json", "inspect")
        walk = next(
            a
            for a in json.loads(inspected.stdout)["result"]["assets"]
            if a["name"] == "walk"
        )
        self.assertEqual(walk["frames"], 8)
        self.assertEqual(walk["frame_ids"][0], "walk_south_00")
        self.assertEqual(walk["frame_ids"][4], "walk_north_04")
        self.assertEqual(walk["tags"], ["action", "direction"])

    def test_dry_run_reports_boxes_without_committing(self) -> None:
        before = (self.project / "manifest.json").read_bytes()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "--dry-run",
            "split",
            "sheet",
            "--columns",
            "4",
            "--rows",
            "2",
            "--tail",
            "crop",
            "--as",
            "never",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)["result"]
        self.assertEqual(payload["count"], 8)
        self.assertEqual(len(payload["frames"][0]["rect"]), 4)
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

    def test_components_mode(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "split",
            "sheet",
            "--mode",
            "components",
            "--min-area",
            "20",
            "--as",
            "parts",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        inspected = run_cli("--project", str(self.project), "--json", "inspect")
        parts = next(
            a
            for a in json.loads(inspected.stdout)["result"]["assets"]
            if a["name"] == "parts"
        )
        self.assertEqual(parts["frames"], 8)

    def test_non_divisible_without_tail_policy_is_usage_error(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "split",
            "sheet",
            "--columns",
            "7",
            "--rows",
            "2",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 2)

    def test_bad_tag_syntax_is_usage_error(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "split",
            "sheet",
            "--columns",
            "4",
            "--rows",
            "2",
            "--tail",
            "crop",
            "--tag",
            "nokeyvalue",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 2)

    def test_split_of_a_multi_frame_asset_is_rejected(self) -> None:
        run_cli(
            "--project",
            str(self.project),
            "split",
            "sheet",
            "--columns",
            "4",
            "--rows",
            "2",
            "--tail",
            "crop",
            "--as",
            "walk",
        )
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "split",
            "walk",
            "--columns",
            "2",
            "--rows",
            "1",
            "--as",
            "again",
        )
        self.assertEqual(result.returncode, 2)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required for CLI image tests")
class CliAlign(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "a.spritework"
        run_cli("init", str(self.project), "--id", "a")

        # Four cells whose blobs sit at different heights: the bobbing case.
        rgba = np.zeros((32, 128, 4), np.uint8)
        for c, top in enumerate((4, 6, 5, 7)):
            x = c * 32 + 8
            rgba[top : top + 18, x : x + 14, :3] = (200, 60, 80)
            rgba[top : top + 18, x : x + 14, 3] = 255
        source = self.root / "walk.png"
        Image.fromarray(rgba, mode="RGBA").save(source)

        run_cli("--project", str(self.project), "import", str(source), "--as", "src")
        run_cli(
            "--project",
            str(self.project),
            "recover",
            "src",
            "--device",
            "cpu",
            "--as",
            "sheet",
        )
        run_cli(
            "--project",
            str(self.project),
            "split",
            "sheet",
            "--columns",
            "4",
            "--rows",
            "1",
            "--tail",
            "crop",
            "--as",
            "walk",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _baselines(self, asset: str) -> set[int]:
        bottoms = set()
        for path in sorted((self.project / "assets" / asset).rglob("*.png")):
            array = np.array(Image.open(path).convert("RGBA"))
            rows = np.flatnonzero((array[:, :, 3] > 0).any(axis=1))
            bottoms.add(int(rows[-1]))
        return bottoms

    def test_feet_alignment_unifies_baselines(self) -> None:
        self.assertGreater(
            len(self._baselines("walk")), 1, "fixture should start uneven"
        )

        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "align",
            "walk",
            "--mode",
            "feet",
            "--as",
            "aligned",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self._baselines("aligned")), 1)

    def test_dry_run_reports_offsets_without_committing(self) -> None:
        before = (self.project / "manifest.json").read_bytes()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "--dry-run",
            "align",
            "walk",
            "--mode",
            "feet",
            "--as",
            "never",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)["result"]
        self.assertEqual(len(payload["canvas"]), 2)
        self.assertIn("offset", payload["frames"][0])
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

    def test_fixed_canvas(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "align",
            "walk",
            "--mode",
            "center",
            "--canvas",
            "64x64",
            "--as",
            "fixed",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in (self.project / "assets" / "fixed").rglob("*.png"):
            with Image.open(path) as handle:
                self.assertEqual(handle.size, (64, 64))

    def test_canvas_too_small_is_usage_error(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "align",
            "walk",
            "--mode",
            "center",
            "--canvas",
            "4x4",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 2)

    def test_bad_canvas_syntax_is_usage_error(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "align",
            "walk",
            "--canvas",
            "sixty",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 2)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required for CLI image tests")
class CliCompose(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "c.spritework"
        run_cli("init", str(self.project), "--id", "c")

        # Already-1x art: adopt it rather than sending it through recovery.
        self._write("body.png", (200, 60, 80, 255), (2, 2, 12, 12))
        self._write("cloth.png", (60, 80, 200, 255), (4, 8, 8, 6))
        for name in ("body", "cloth"):
            run_cli(
                "--project",
                str(self.project),
                "import",
                str(self.root / f"{name}.png"),
                "--as",
                name,
                "--adopt",
                "--anchor",
                "8",
                "16",
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, color: tuple, rect: tuple) -> None:
        array = np.zeros((16, 16, 4), np.uint8)
        x, y, w, h = rect
        array[y : y + h, x : x + w] = color
        Image.fromarray(array, mode="RGBA").save(self.root / name)

    def test_adopt_creates_a_1x_asset(self) -> None:
        result = run_cli("--project", str(self.project), "--json", "inspect")
        assets = {a["name"] for a in json.loads(result.stdout)["result"]["assets"]}
        self.assertEqual({"body", "cloth"}, assets)

        with Image.open(
            next((self.project / "assets" / "body").rglob("*.png"))
        ) as handle:
            self.assertEqual(handle.size, (16, 16), "adopt must not resample")

    def test_compose_stacks_layers(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "compose",
            "--layer",
            "body=body",
            "--layer",
            "cloth=cloth",
            "--match",
            "by-index",
            "--as",
            "dressed",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outputs"], ["dressed"])

        path = next((self.project / "assets" / "dressed").rglob("*.png"))
        array = np.array(Image.open(path).convert("RGBA"))
        # Where the cloth covers the body, the cloth colour wins.
        self.assertEqual(tuple(array[10, 8].tolist()), (60, 80, 200, 255))
        # Where only the body is, the body colour survives.
        self.assertEqual(tuple(array[3, 3].tolist()), (200, 60, 80, 255))

    def test_dry_run_reports_matches_without_committing(self) -> None:
        before = (self.project / "manifest.json").read_bytes()
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "--dry-run",
            "compose",
            "--layer",
            "body=body",
            "--layer",
            "cloth=cloth",
            "--as",
            "never",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)["result"]
        self.assertEqual(
            [entry["layer"] for entry in payload["frames"][0]["layers"]],
            ["body", "cloth"],
        )
        self.assertEqual((self.project / "manifest.json").read_bytes(), before)

    def test_fixed_canvas(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "compose",
            "--layer",
            "body=body",
            "--canvas",
            "40x40",
            "--as",
            "big",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(
            next((self.project / "assets" / "big").rglob("*.png"))
        ) as handle:
            self.assertEqual(handle.size, (40, 40))

    def test_bad_layer_syntax_is_usage_error(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "compose",
            "--layer",
            "justaname",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_layer_asset_is_not_found(self) -> None:
        result = run_cli(
            "--project",
            str(self.project),
            "--json",
            "compose",
            "--layer",
            "body=nope",
            "--as",
            "bad",
        )
        self.assertEqual(result.returncode, 3)


class CliExitCodes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_project_is_usage_error(self) -> None:
        result = run_cli("--json", "inspect")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertEqual(json.loads(result.stdout)["error"]["code"], 2)

    def test_unknown_project_is_not_found(self) -> None:
        result = run_cli("--project", str(self.root / "absent"), "--json", "inspect")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], 3)

    def test_init_into_non_empty_directory_is_refused(self) -> None:
        busy = self.root / "busy"
        busy.mkdir()
        (busy / "f.txt").write_text("x", encoding="utf-8")
        result = run_cli("--json", "init", str(busy))
        self.assertEqual(result.returncode, 7)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], 7)

    def test_bad_argument_is_argparse_usage(self) -> None:
        result = run_cli("recover")  # missing --as and project
        self.assertEqual(result.returncode, 2)

    def test_errors_go_to_stderr_and_json_stays_clean(self) -> None:
        result = run_cli("--project", str(self.root / "absent"), "--json", "inspect")
        self.assertIn("error[3]", result.stderr)
        json.loads(result.stdout)  # stdout must still be a single valid object


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
