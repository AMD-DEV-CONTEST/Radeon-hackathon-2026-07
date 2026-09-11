import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "contextualize_mobile_pi05_dataset.py"
)
SPEC = importlib.util.spec_from_file_location(
    "contextualize_mobile_pi05_dataset", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ContextualizeMobilePI05DatasetTests(unittest.TestCase):
    def test_hard_link_copy_does_not_modify_source_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            (source / "data/chunk-000").mkdir(parents=True)
            (source / "meta/episodes/chunk-000").mkdir(parents=True)

            state = [0.0] * 80
            state[46] = 1.0
            state[48:52] = [0.12, 0.08, 0.05, 0.4]
            state[56] = 1.0
            pq.write_table(
                pa.table(
                    {
                        "episode_index": [0],
                        "task_index": [0],
                        "observation.state": [state],
                    }
                ),
                source / "data/chunk-000/file-000.parquet",
            )
            pq.write_table(
                pa.table({"task_index": [0], "task": ["Move the parcel."]}),
                source / "meta/tasks.parquet",
            )
            pq.write_table(
                pa.table({"episode_index": [0], "tasks": [["Move the parcel."]]}),
                source / "meta/episodes/chunk-000/file-000.parquet",
            )
            (source / "meta/info.json").write_text(
                json.dumps({"total_tasks": 1}), encoding="utf-8"
            )
            (source / "meta/stats.json").write_text(
                json.dumps({"task_index": {}}), encoding="utf-8"
            )
            (source / "PI05_RESIDUAL_DATASET_MANIFEST.json").write_text(
                json.dumps({"schema_version": 1, "protocol": "source-v1"}),
                encoding="utf-8",
            )
            before = _tree_hashes(source)

            result = MODULE.build(source, destination)

            self.assertEqual(_tree_hashes(source), before)
            self.assertEqual(
                result["task_language_policy"], "observable_context_mode_blind_v1"
            )
            manifest = json.loads(
                (destination / "PI05_RESIDUAL_DATASET_MANIFEST.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["source_integrity"]["status"], "passed")
            destination_task = pq.read_table(destination / "meta/tasks.parquet")[
                "task"
            ][0].as_py()
            self.assertIn("Observable parcel context", destination_task)
            self.assertEqual(
                pq.read_table(source / "meta/tasks.parquet")["task"][0].as_py(),
                "Move the parcel.",
            )


if __name__ == "__main__":
    unittest.main()
