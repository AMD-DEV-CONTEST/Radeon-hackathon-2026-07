import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_DEVELOPMENT_ROLE,
    build_stage_panel,
    file_sha256,
)


try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_mobile_pi05_stage_panel.py"
SPEC = importlib.util.spec_from_file_location("build_mobile_pi05_stage_panel", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


@unittest.skipIf(pa is None or pq is None, "pyarrow is validated in the Radeon environment")
class BuildMobilePI05StagePanelTests(unittest.TestCase):
    def test_reads_labeled_lerobot_parquet_and_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/chunk-000"
            data.mkdir(parents=True)
            rows = {
                "index": [],
                "episode_index": [],
                "observation.stage_id": [],
                "action": [],
            }
            episodes = []
            index = 0
            for mode_index, mode in enumerate(MODULE.PI05_GRASP_MODES):
                for stage_index, _stage in enumerate(MODULE.MOBILE_STAGE_NAMES):
                    action = [0.0] * 23
                    action[19 + mode_index] = 1.0
                    rows["index"].append(index)
                    rows["episode_index"].append(index)
                    rows["observation.stage_id"].append(stage_index)
                    rows["action"].append(action)
                    episodes.append(
                        {
                            "episode_index": index,
                            "source_identity": f"heldout-{stage_index % 2}",
                            "grasp_modes": [mode],
                        }
                    )
                    index += 1
            pq.write_table(pa.table(rows), data / "episode_000000.parquet")
            manifest = {
                "action_contract": "absolute_v1",
                "episode_manifests": episodes,
            }
            manifest_path = root / "PI05_ABSOLUTE_DATASET_MANIFEST.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            digest = file_sha256(manifest_path)

            observations = MODULE.read_labeled_observations(root, manifest, digest)
            panel = build_stage_panel(
                observations,
                role=PI05_DEVELOPMENT_ROLE,
                dataset_root=root,
                dataset_manifest_sha256=digest,
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=2,
                training_source_identities={"training-a", "training-b"},
            )

        self.assertEqual(len(panel["observations"]), 18)
        self.assertEqual(panel["training_source_overlap_count"], 0)
        self.assertTrue(
            all(item["action_label_available"] for item in panel["observations"])
        )


if __name__ == "__main__":
    unittest.main()
