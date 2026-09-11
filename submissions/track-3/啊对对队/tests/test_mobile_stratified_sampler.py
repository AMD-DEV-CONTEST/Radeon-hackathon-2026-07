import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

from parcel_sorter.mobile_stratified_sampler import (
    build_sampling_manifest,
    install_stratified_sampler,
    make_stratified_sampler_class,
)


class MobileStratifiedSamplerTests(unittest.TestCase):
    def _split(self) -> dict:
        assignments = []
        episode_index = 0
        for mode in ("top_suction", "side_suction", "cooperative_cradle"):
            for cell_index in range(8):
                for _ in range(50):
                    assignments.append(
                        {
                            "dataset_episode_index": episode_index,
                            "grasp_mode": mode,
                            "design_cell": f"{mode}-cell-{cell_index:02d}",
                            "split": "train",
                        }
                    )
                    episode_index += 1
        return {"assignments": assignments}

    def _rows(self) -> list[dict[str, int]]:
        rows = []
        index = 0
        for episode_index in range(1200):
            for stage_id in range(6):
                for _ in range(4 + stage_id):
                    rows.append(
                        {
                            "index": index,
                            "episode_index": episode_index,
                            "stage_id": stage_id,
                        }
                    )
                    index += 1
        return rows

    def test_manifest_caps_stages_and_balances_cells(self) -> None:
        payload = build_sampling_manifest(
            frame_rows=self._rows(),
            split_manifest=self._split(),
            stage_frame_cap_per_episode=5,
        )

        self.assertEqual(payload["design_cell_count"], 24)
        self.assertEqual(
            len(set(payload["cell_unique_frame_counts"].values())), 1
        )
        self.assertEqual(
            payload["samples_per_epoch"],
            payload["samples_per_design_cell_per_epoch"] * 24,
        )
        self.assertTrue(
            all(
                value <= 5
                for counts in payload["episode_stage_unique_frame_counts"].values()
                for value in counts.values()
            )
        )

    def test_sampler_is_exactly_balanced_and_resume_deterministic(self) -> None:
        payload = build_sampling_manifest(
            frame_rows=self._rows(),
            split_manifest=self._split(),
            stage_frame_cap_per_episode=5,
        )
        unsigned = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        import hashlib

        payload["manifest_sha256"] = hashlib.sha256(unsigned).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sampling.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            sampler_class = make_stratified_sampler_class(path)
            starts = [index * 39 for index in range(1200)]
            ends = [(index + 1) * 39 for index in range(1200)]
            sampler = sampler_class(starts, ends, shuffle=True, seed=11)
            first = list(iter(sampler))
            repeated = sampler_class(starts, ends, shuffle=True, seed=11)

            self.assertEqual(first, list(iter(repeated)))
            self.assertEqual(len(first), len(sampler))
            self.assertEqual(len(first), len(set(first)))
            state = {"epoch": 0, "start_index": 17}
            resumed = sampler_class(starts, ends, shuffle=True, seed=11)
            resumed.load_state_dict(state)
            self.assertEqual(list(iter(resumed)), first[17:])

    def test_missing_stage_fails_closed(self) -> None:
        rows = self._rows()
        rows = [
            row
            for row in rows
            if not (row["episode_index"] == 0 and row["stage_id"] == 5)
        ]
        with self.assertRaisesRegex(ValueError, "lack task stages"):
            build_sampling_manifest(
                frame_rows=rows,
                split_manifest=self._split(),
                stage_frame_cap_per_episode=5,
            )

    def test_one_element_stage_vectors_are_supported(self) -> None:
        rows = self._rows()
        for row in rows:
            row["stage_id"] = [row["stage_id"]]
        payload = build_sampling_manifest(
            frame_rows=rows,
            split_manifest=self._split(),
            stage_frame_cap_per_episode=5,
        )
        self.assertEqual(payload["train_episode_count"], 1200)

    def test_installer_patches_lerobot_package_reexport(self) -> None:
        payload = build_sampling_manifest(
            frame_rows=self._rows(),
            split_manifest=self._split(),
            stage_frame_cap_per_episode=5,
        )
        import hashlib

        payload["manifest_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sampling.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            lerobot = ModuleType("lerobot")
            datasets = ModuleType("lerobot.datasets")
            sampler = ModuleType("lerobot.datasets.sampler")
            original = type("OriginalSampler", (), {})
            datasets.EpisodeAwareSampler = original
            datasets.sampler = sampler
            sampler.EpisodeAwareSampler = original
            lerobot.datasets = datasets
            previous = {
                name: sys.modules.get(name)
                for name in (
                    "lerobot",
                    "lerobot.datasets",
                    "lerobot.datasets.sampler",
                )
            }
            try:
                sys.modules["lerobot"] = lerobot
                sys.modules["lerobot.datasets"] = datasets
                sys.modules["lerobot.datasets.sampler"] = sampler
                installed = install_stratified_sampler(path)
            finally:
                for name, module in previous.items():
                    if module is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = module
            self.assertIs(datasets.EpisodeAwareSampler, installed)
            self.assertIs(sampler.EpisodeAwareSampler, installed)

    def test_installer_patches_real_lerobot_reexport_when_available(self) -> None:
        try:
            import lerobot.datasets as datasets
            from lerobot.datasets import sampler
        except ImportError:
            self.skipTest("LeRobot is required for the integration binding test")
        payload = build_sampling_manifest(
            frame_rows=self._rows(),
            split_manifest=self._split(),
            stage_frame_cap_per_episode=5,
        )
        import hashlib

        payload["manifest_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sampling.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            original_package = datasets.EpisodeAwareSampler
            original_submodule = sampler.EpisodeAwareSampler
            try:
                installed = install_stratified_sampler(path)
                self.assertIs(datasets.EpisodeAwareSampler, installed)
                self.assertIs(sampler.EpisodeAwareSampler, installed)
            finally:
                datasets.EpisodeAwareSampler = original_package
                sampler.EpisodeAwareSampler = original_submodule


if __name__ == "__main__":
    unittest.main()
