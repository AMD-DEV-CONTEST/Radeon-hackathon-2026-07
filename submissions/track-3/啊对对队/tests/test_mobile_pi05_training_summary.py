import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_mobile_pi05_training.py"
SPEC = importlib.util.spec_from_file_location("summarize_mobile_pi05_training", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MobilePI05TrainingSummaryTests(unittest.TestCase):
    def test_parses_every_record_by_order_when_displayed_steps_are_abbreviated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "train.log"
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            adapter = checkpoint / "adapter_model.safetensors"
            adapter.write_bytes(b"adapter")
            log.write_text(
                "step:999 loss:0.400 grdn:1.200 lr:2.5e-05\n"
                "step:1K loss:0.200 grdn:0.800 lr:2.4e-05\n"
                "End of training\n",
                encoding="utf-8",
            )

            summary = MODULE.summarize_training_log(
                log, expected_steps=2, checkpoint=checkpoint, adapter=adapter
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual([row["step"] for row in summary["records"]], [1, 2])
            self.assertEqual(summary["metrics"]["loss_min"], 0.2)
            self.assertTrue(summary["metrics"]["all_loss_and_gradient_values_finite"])
            self.assertEqual(
                summary["adapter_sha256"],
                "ae1eae1d76e5b7c865c4122ce366a08025842566d2d96c75cc13e6353a73db0d",
            )

    def test_requires_step_count_end_marker_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "train.log"
            log.write_text("step:1 loss:0.4 grdn:0.8 lr:1e-5\n", encoding="utf-8")

            summary = MODULE.summarize_training_log(
                log, expected_steps=2, checkpoint=root / "missing"
            )

            self.assertEqual(summary["status"], "in_progress_or_failed")
            self.assertFalse(summary["completed_marker"])
            self.assertFalse(summary["checkpoint_exists"])

    def test_numbers_resumed_records_from_starting_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "resume.log"
            log.write_text(
                "loss:0.3 grdn:0.7 lr:2.5e-6\n"
                "loss:0.2 grdn:0.6 lr:2.5e-6\n"
                "End of training\n",
                encoding="utf-8",
            )

            summary = MODULE.summarize_training_log(
                log, expected_steps=2, starting_step=3000
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["starting_step"], 3000)
            self.assertEqual(summary["ending_step"], 3002)
            self.assertEqual([row["step"] for row in summary["records"]], [3001, 3002])
            self.assertEqual(summary["metrics"]["blocks"][0]["start_step"], 3001)

    def test_preserves_high_noise_mode_training_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "weighted.log"
            log.write_text(
                "loss:3.0 grdn:2.0 lr:1e-5 mode_cross_entropy:1.2 "
                "mode_accuracy:0.4 mode_margin:-0.2 "
                "mode_cross_entropy_weight:2.0 mode_cross_entropy_time:1.0 "
                "stage_selected_weight_mean:2.0 stage_unweighted_loss:0.3 "
                "stage_weighted_loss:0.6 mode_flow_loss_population_normalizer:1.01 "
                "mode_flow_selected_weight_mean:1.5 mode_flow_input_loss:0.6 "
                "mode_flow_weighted_loss:0.9 flow_loss_unweighted:0.3 flow_loss:0.9\n"
                "loss:1.0 grdn:1.0 lr:2e-5 mode_cross_entropy:0.2 "
                "mode_accuracy:1.0 mode_margin:1.5 "
                "mode_cross_entropy_weight:2.0 mode_cross_entropy_time:1.0 "
                "stage_selected_weight_mean:0.4 stage_unweighted_loss:1.5 "
                "stage_weighted_loss:0.6 mode_flow_loss_population_normalizer:1.01 "
                "mode_flow_selected_weight_mean:0.75 mode_flow_input_loss:0.6 "
                "mode_flow_weighted_loss:0.45 flow_loss_unweighted:1.5 flow_loss:0.45\n"
                "End of training\n",
                encoding="utf-8",
            )

            summary = MODULE.summarize_training_log(log, expected_steps=2)

            auxiliary = summary["metrics"]["auxiliary"]
            self.assertEqual(auxiliary["mode_accuracy"]["records"], 2)
            self.assertAlmostEqual(auxiliary["mode_accuracy"]["mean"], 0.7)
            self.assertEqual(auxiliary["mode_margin"]["last"], 1.5)
            self.assertEqual(summary["records"][0]["flow_loss"], 0.9)
            self.assertAlmostEqual(
                auxiliary["stage_selected_weight_mean"]["mean"], 1.2
            )
            self.assertEqual(auxiliary["flow_loss_unweighted"]["last"], 1.5)
            self.assertAlmostEqual(
                auxiliary["mode_flow_selected_weight_mean"]["mean"], 1.125
            )
            self.assertEqual(auxiliary["mode_flow_weighted_loss"]["last"], 0.45)
            self.assertAlmostEqual(
                summary["metrics"]["blocks"][0]["stage_unweighted_loss_mean"],
                0.9,
            )
            self.assertEqual(
                summary["metrics"]["blocks"][0]["stage_weighted_loss_mean"],
                0.6,
            )
            self.assertAlmostEqual(
                summary["metrics"]["blocks"][0]["mode_cross_entropy_mean"],
                0.7,
            )

    def test_reports_isolated_loss_and_gradient_spikes(self) -> None:
        records = [
            {"step": index + 1, "loss": 0.1, "gradient_norm": 1.0}
            for index in range(20)
        ]
        records.append({"step": 21, "loss": 3.0, "gradient_norm": 100.0})

        loss = MODULE._robust_outliers(records, "loss")
        gradient = MODULE._robust_outliers(records, "gradient_norm")

        self.assertEqual(loss["count"], 1)
        self.assertEqual(loss["records"][0]["step"], 21)
        self.assertEqual(gradient["count"], 1)
        self.assertEqual(gradient["records"][0]["value"], 100.0)


if __name__ == "__main__":
    unittest.main()
