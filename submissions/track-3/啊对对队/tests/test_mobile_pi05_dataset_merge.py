import importlib.util
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from parcel_sorter.mobile_dataset import mobile_policy_visual_keys


SCRIPT = Path(__file__).parents[1] / "scripts" / "merge_mobile_pi05_residual_datasets.py"
SPEC = importlib.util.spec_from_file_location("merge_mobile_pi05_residual_datasets", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MobilePI05DatasetMergeTests(unittest.TestCase):
    def test_visual_contract_is_derived_and_mismatch_is_rejected(self) -> None:
        features = {key: {} for key in mobile_policy_visual_keys("rgbd_wrist")}
        bound = MODULE._bind_visual_contract({}, features)

        self.assertEqual(bound["policy_visual_modality"], "rgbd_wrist")
        self.assertEqual(
            bound["policy_visual_keys"],
            list(mobile_policy_visual_keys("rgbd_wrist")),
        )
        with self.assertRaisesRegex(ValueError, "visual keys"):
            MODULE._bind_visual_contract(
                {"policy_visual_keys": list(mobile_policy_visual_keys("rgbd"))},
                features,
            )

    def test_mode_neutral_task_rewrites_task_and_episode_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "meta/episodes/chunk-000").mkdir(parents=True)
            tasks_path = root / "meta/tasks.parquet"
            episodes_path = root / "meta/episodes/chunk-000/file-000.parquet"
            pq.write_table(
                pa.table({"task_index": [0, 1], "task": ["use side suction", "use cradle"]}),
                tasks_path,
            )
            pq.write_table(
                pa.table({"episode_index": [0, 1], "tasks": [["side"], ["cradle"]]}),
                episodes_path,
            )

            MODULE._replace_task_text(root, "Recover and transport the parcel.")

            self.assertEqual(
                pq.read_table(tasks_path)["task"].to_pylist(),
                ["Recover and transport the parcel."] * 2,
            )
            self.assertEqual(
                pq.read_table(episodes_path)["tasks"].to_pylist(),
                [["Recover and transport the parcel."]] * 2,
            )


if __name__ == "__main__":
    unittest.main()
