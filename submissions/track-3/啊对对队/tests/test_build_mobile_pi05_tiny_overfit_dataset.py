import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TASK_STAGES,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
)


ROOT = Path(__file__).parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BUILDER = _load(
    "build_mobile_pi05_tiny_overfit_dataset",
    "build_mobile_pi05_tiny_overfit_dataset.py",
)
LAUNCH_AUDIT = _load(
    "audit_mobile_pi05_training_launch",
    "audit_mobile_pi05_training_launch.py",
)


def _panel(dataset_root: Path) -> dict:
    rows = []
    index = 0
    for mode in PI05_GRASP_MODES:
        for stage in PI05_TASK_STAGES:
            rows.append(
                {
                    "observation_id": f"source-{index}",
                    "dataset_index": index + 100,
                    "episode_index": index // len(PI05_TASK_STAGES),
                    "source_identity": f"source-{mode}",
                    "grasp_mode": mode,
                    "stage": stage,
                    "action_label_available": True,
                }
            )
            index += 1
    return build_stage_panel(
        rows,
        role=PI05_TINY_OVERFIT_ROLE,
        dataset_root=dataset_root,
        dataset_manifest_sha256="a" * 64,
        minimum_observations_per_mode_stage=1,
        minimum_independent_sources_per_mode=1,
    )


class BuildMobilePI05TinyOverfitDatasetTests(unittest.TestCase):
    def test_recomputes_global_quantiles_across_single_frame_episodes(self) -> None:
        stats = BUILDER.vector_stats(
            [np.asarray([0.0, 2.0]), np.asarray([1.0, 2.0])]
        )

        self.assertEqual(stats["count"], [2])
        self.assertEqual(stats["min"], [0.0, 2.0])
        self.assertEqual(stats["max"], [1.0, 2.0])
        self.assertGreater(stats["q99"][0] - stats["q01"][0], 0.0)
        self.assertEqual(stats["q99"][1] - stats["q01"][1], 0.0)

    def test_remaps_exact_cells_to_one_frame_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel = _panel(root)
            rows = BUILDER.validate_source_panel(panel, root)
            remapped = BUILDER.remap_tiny_observations(rows)

        self.assertEqual(len(remapped), 18)
        self.assertEqual([item["dataset_index"] for item in remapped], list(range(18)))
        self.assertEqual([item["episode_index"] for item in remapped], list(range(18)))
        self.assertEqual(remapped[0]["source_dataset_index"], 100)
        self.assertEqual(remapped[-1]["source_dataset_index"], 117)

    def test_training_gate_rejects_a_full_dataset_disguised_as_tiny(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text(
                json.dumps({"total_frames": 5871, "total_episodes": 10}),
                encoding="utf-8",
            )
            panel = _panel(root)
            manifest = {
                "dataset_role": "tiny_overfit_contract_only",
                "performance_data": False,
            }

            with self.assertRaisesRegex(ValueError, "exactly 18 frames"):
                LAUNCH_AUDIT.validate_tiny_overfit_dataset_binding(
                    root, manifest, panel
                )

    def test_training_gate_accepts_only_complete_18_row_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text(
                json.dumps({"total_frames": 18, "total_episodes": 18}),
                encoding="utf-8",
            )
            source_panel = _panel(root)
            remapped = BUILDER.remap_tiny_observations(
                list(source_panel["observations"])
            )
            panel = build_stage_panel(
                remapped,
                role=PI05_TINY_OVERFIT_ROLE,
                dataset_root=root,
                dataset_manifest_sha256="b" * 64,
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=1,
            )
            manifest = {
                "dataset_role": "tiny_overfit_contract_only",
                "performance_data": False,
            }

            LAUNCH_AUDIT.validate_tiny_overfit_dataset_binding(root, manifest, panel)


if __name__ == "__main__":
    unittest.main()
