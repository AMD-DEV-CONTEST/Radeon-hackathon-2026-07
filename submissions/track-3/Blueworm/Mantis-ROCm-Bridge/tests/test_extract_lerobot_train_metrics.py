from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "tools" / "extract_lerobot_train_metrics.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "extract_lerobot_train_metrics_cli", CLI_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _line(step: str | int, *, loss: str = "2.0", smpl: str = "1K") -> str:
    return (
        f"step:{step} smpl:{smpl} ep:1 epch:0.20 loss:{loss} "
        "grdn:9.0 lr:1.0e-04 updt_s:0.2 data_s:0.1"
    )


MODULE = _load_module()
parse_metrics = MODULE.parse_metrics
summarize = MODULE.summarize
MetricsParseError = MODULE.MetricsParseError


class ExtractLeRobotTrainMetricsTests(unittest.TestCase):
    def test_canonical_record(self) -> None:
        record = parse_metrics(_line(700, loss="2.186", smpl="6K"))[0]
        self.assertEqual(record.step, 700)
        self.assertEqual(record.samples_text, "6K")
        self.assertAlmostEqual(record.loss, 2.186)

    def test_exact_tqdm_numerator_overrides_humanized_step(self) -> None:
        live = (
            "Training: 3%|...| 1800/60000 [09:34<4:50:23, 3.19step/s] "
            "INFO 2026-07-26 09:34:12 train "
            + _line("2K", loss="1.291", smpl="15K")
        )
        record = parse_metrics(live)[0]
        self.assertEqual(record.step, 1800)
        self.assertAlmostEqual(record.loss, 1.291)

    def test_humanized_fallback_and_exact_decimal_expansion(self) -> None:
        cases = (
            ("2K", 2000),
            ("1.8K", 1800),
            ("1M", 1_000_000),
            ("1.5B", 1_500_000_000),
        )
        for token, expected in cases:
            with self.subTest(token=token):
                self.assertEqual(parse_metrics(_line(token))[0].step, expected)

    def test_multiple_glued_records_use_nearest_numerator(self) -> None:
        segment = (
            "Training: 3%|...| 1800/60000 [09:34<4:50:23] "
            + _line("2K", loss="1.3")
            + " Training: 3%|...| 1900/60000 [10:05<4:45:00] "
            + _line("2K", loss="1.2")
        )
        records = parse_metrics(segment)
        self.assertEqual([record.step for record in records], [1800, 1900])
        self.assertEqual([record.loss for record in records], [1.3, 1.2])

    def test_progress_only_noise_is_not_a_record(self) -> None:
        progress = "Training: 3%|...| 1800/60000 [09:34<4:50:23]"
        with self.assertRaises(MetricsParseError):
            parse_metrics(progress)
        records = parse_metrics(progress + "\r" + _line("2K"))
        self.assertEqual([record.step for record in records], [2000])

    def test_fractional_expansion_fails_closed(self) -> None:
        for token in ("1.5", "1.2345K"):
            with self.subTest(token=token):
                with self.assertRaises(MetricsParseError):
                    parse_metrics(_line(token))

    def test_non_finite_record_fails_closed(self) -> None:
        with self.assertRaises(MetricsParseError):
            parse_metrics(_line(100, loss="nan"))

    def test_summary_keeps_no_convergence_boundary(self) -> None:
        summary = summarize(
            parse_metrics(_line(100, loss="3.0") + "\r" + _line(200, loss="2.0"))
        )
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["min_loss_step"], 200)
        self.assertIs(summary["claim_boundary"]["convergence_claimed"], False)
        self.assertIn(
            "NO CONVERGENCE CLAIM", summary["claim_boundary"]["statement"]
        )

    def test_cli_refuses_to_overwrite_any_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "train.log"
            csv_path = root / "metrics.csv"
            json_path = root / "metrics.json"
            png_path = root / "loss.png"
            log.write_text(_line(100), encoding="utf-8")
            json_path.write_text(json.dumps({"existing": True}), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                MODULE.main(
                    [
                        str(log),
                        "--csv",
                        str(csv_path),
                        "--json",
                        str(json_path),
                        "--png",
                        str(png_path),
                    ]
                )
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(csv_path.exists())
            self.assertFalse(png_path.exists())
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                {"existing": True},
            )


if __name__ == "__main__":
    unittest.main()
