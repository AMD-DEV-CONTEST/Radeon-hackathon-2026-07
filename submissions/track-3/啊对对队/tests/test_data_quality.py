import unittest

from parcel_sorter.data_quality import audit_lerobot_metadata
from parcel_sorter.dataset import DEPTH_RGB_KEY


def _info(include_depth_rgb: bool) -> dict:
    features = {
        "observation.state": {"shape": [20]},
        "action": {"shape": [8]},
        "observation.images.overhead_rgb": {"shape": [224, 224, 3]},
        "observation.images.overhead_depth": {
            "shape": [224, 224, 1],
            "info": {"is_depth_map": True, "depth_unit": "m"},
        },
    }
    if include_depth_rgb:
        features[DEPTH_RGB_KEY] = {
            "shape": [224, 224, 3],
            "info": {"derived_from": "observation.images.overhead_depth"},
        }
    return {"features": features, "total_episodes": 96, "total_frames": 11753}


class DatasetQualityTests(unittest.TestCase):
    def test_rgb_training_warns_but_does_not_fail_on_old_depth_scale(self) -> None:
        audit = audit_lerobot_metadata(
            _info(False),
            {"observation.images.overhead_depth": {"q50": [[[0.0012]]]}},
        )

        self.assertTrue(audit.passed)
        self.assertEqual(len(audit.warnings), 1)

    def test_rgbd_training_rejects_old_depth_scale_and_missing_view(self) -> None:
        audit = audit_lerobot_metadata(
            _info(False),
            {"observation.images.overhead_depth": {"q50": [[[0.0012]]]}},
            require_depth_rgb=True,
        )

        self.assertFalse(audit.passed)
        self.assertEqual(len(audit.errors), 2)

    def test_valid_rgbd_metadata_passes(self) -> None:
        info = _info(True)
        audit = audit_lerobot_metadata(
            info,
            {"observation.images.overhead_depth": {"q50": [[[1.2]]]}},
            require_depth_rgb=True,
        )

        self.assertTrue(audit.passed)

        info["features"]["observation.images.overhead_depth"]["info"]["depth_unit"] = "mm"
        info["features"][DEPTH_RGB_KEY]["info"]["derived_from"] = "unknown"
        invalid = audit_lerobot_metadata(
            info,
            {"observation.images.overhead_depth": {"q50": [[[1.2]]]}},
            require_depth_rgb=True,
        )

        self.assertFalse(invalid.passed)
        self.assertEqual(len(invalid.errors), 2)


if __name__ == "__main__":
    unittest.main()
