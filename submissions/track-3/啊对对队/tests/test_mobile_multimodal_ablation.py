import unittest

from parcel_sorter.mobile_multimodal_ablation import compare_mobile_modalities


def _result(*, harness_mae: float, latency_ms: float) -> dict:
    policies = {
        "raw_vla": {"mean_mae": 0.02, "envelope_pass_count": 0},
        "safety_clipped_vla": {"mean_mae": 0.01, "envelope_pass_count": 2},
        "harness_lite": {"mean_mae": harness_mae, "envelope_pass_count": 2},
    }
    return {
        "status": "passed_offline_action_requires_safety_clipping",
        "dataset_root": "/dataset",
        "offline_ablation": policies,
        "latency_ms": {"mean": latency_ms},
        "stages": [
            {"episode_index": 0, "stage": "pregrasp", "frame_index": 10, "seed": 1},
            {"episode_index": 0, "stage": "transport", "frame_index": 20, "seed": 2},
        ],
    }


class MobileMultimodalAblationTests(unittest.TestCase):
    def test_selects_improved_paired_rgbd_candidate(self) -> None:
        result = compare_mobile_modalities(
            _result(harness_mae=0.006, latency_ms=100),
            _result(harness_mae=0.005, latency_ms=120),
        )
        self.assertTrue(result["rgbd_selected"])
        self.assertTrue(result["closed_loop_campaign_authorized"])

    def test_retains_rgb_when_harness_error_regresses(self) -> None:
        result = compare_mobile_modalities(
            _result(harness_mae=0.005, latency_ms=100),
            _result(harness_mae=0.006, latency_ms=105),
        )
        self.assertFalse(result["rgbd_selected"])
        self.assertFalse(result["checks"]["harness_mae_improved"])

    def test_rejects_unpaired_samples(self) -> None:
        rgbd = _result(harness_mae=0.004, latency_ms=100)
        rgbd["stages"][0]["seed"] = 99
        result = compare_mobile_modalities(
            _result(harness_mae=0.005, latency_ms=100), rgbd
        )
        self.assertFalse(result["checks"]["same_paired_samples"])
        self.assertFalse(result["rgbd_selected"])


if __name__ == "__main__":
    unittest.main()
