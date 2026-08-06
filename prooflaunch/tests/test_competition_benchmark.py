from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.competition_benchmark import (
    BASELINE_RESULT_SCHEMA,
    CASE_RESULT_SCHEMA,
    CASE_GATE_EVIDENCE_SCHEMA,
    COMPILED_EVIDENCE_SCHEMA,
    BaselineCaseJournal,
    CompetitionCaseJournal,
    CompetitionBenchmarkError,
    DeclaredBaseline,
    ProductSpec,
    build_frozen_manifest,
    compile_competition_evidence,
)
from prooflaunch_remix.quality_contract import QualityTier, contract_for


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dhash_png(path: Path, value: int) -> None:
    pixels: list[int] = []
    for row in range(8):
        current = 128
        pixels.append(current)
        for column in range(8):
            bit_index = 63 - (row * 8 + column)
            current += -8 if (value >> bit_index) & 1 else 8
            pixels.append(current)
    image = Image.new("L", (9, 8))
    image.putdata(pixels)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class CompetitionEvidenceCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        products = tuple(
            ProductSpec(
                product_id=f"product-{index:02d}",
                input_sha256=sha(f"input-{index}"),
                rights="owned",
                source_locator=f"fixture:product-{index:02d}",
            )
            for index in range(30)
        )
        self.manifest = build_frozen_manifest(
            benchmark_id="prooflaunch-2x-test",
            protocol_sha256=sha("benchmark-protocol-v1"),
            prooflaunch_build_sha256=sha("prooflaunch-build-v7"),
            baseline=DeclaredBaseline(
                name="Frozen One-Shot Ablation",
                version="v1",
                settings_sha256=sha("baseline-settings"),
                source_locator="fixture:baseline-settings.json",
            ),
            products=products,
        )
        self.manifest_path = self.root / "manifest.json"
        self.results_path = self.root / "results.jsonl"
        self.baseline_path = self.root / "baseline.jsonl"
        self.human_path = self.root / "human.csv"
        self.proof_dir = self.root / "proof"
        self.baseline_dir = self.root / "baseline"
        self.video_dir = self.root / "video"
        self.gate_dir = self.root / "gates"
        self.manifest_path.write_text(
            json.dumps(self.manifest.to_dict(), sort_keys=True),
            encoding="utf-8",
        )
        masks = (0x0, 0xFF, 0xFF00, 0xFF0000, 0xFF000000)
        seed_index = {
            seed: index for index, seed in enumerate(self.manifest.seeds)
        }
        self.results: list[dict] = []
        self.baseline: list[dict] = []
        for case in self.manifest.cases:
            base_hash = int(sha(f"{case.product_id}:{case.aspect_ratio}")[:16], 16)
            output_path = self.proof_dir / f"{case.case_id}.png"
            write_dhash_png(
                output_path,
                base_hash ^ masks[seed_index[case.seed]],
            )
            baseline_output_path = self.baseline_dir / f"{case.case_id}.png"
            write_dhash_png(
                baseline_output_path,
                int(sha(f"baseline:{case.case_id}")[:16], 16),
            )
            video_path = (
                self.video_dir / f"{case.case_id}.mp4"
                if case.video_required
                else None
            )
            if video_path:
                video_path.parent.mkdir(parents=True, exist_ok=True)
                video_path.write_bytes(f"video:{case.case_id}".encode("utf-8"))
            gate_path = self.gate_dir / f"{case.case_id}.json"
            gate_path.parent.mkdir(parents=True, exist_ok=True)
            gate = {
                "schema": CASE_GATE_EVIDENCE_SCHEMA,
                "manifest_hash": self.manifest.manifest_hash,
                "case_id": case.case_id,
                "completed": True,
                "crashed": False,
                "repairs": 1,
                "unsupported_claim_count": 0,
                "observation_count": 3,
                "located_observation_count": 3,
                "image_identity_pass": True,
                "preencode_video_identity_pass": (
                    True if case.video_required else None
                ),
                "encoded_video_identity_pass": (
                    True if case.video_required else None
                ),
                "audio_video_alignment_pass": (
                    True if case.video_required else None
                ),
                "cross_media_pass": True,
                "latency_seconds": 12.5,
                "peak_vram_gb": 19.0,
                "output_sha256": file_sha(output_path),
                "video_output_sha256": (
                    file_sha(video_path) if video_path else None
                ),
            }
            gate_path.write_text(
                json.dumps(gate, sort_keys=True),
                encoding="utf-8",
            )
            self.results.append(
                {
                    "schema": CASE_RESULT_SCHEMA,
                    "manifest_hash": self.manifest.manifest_hash,
                    "case_id": case.case_id,
                    "gate_evidence_sha256": file_sha(gate_path),
                    "gate_evidence_locator": gate_path.relative_to(
                        self.root
                    ).as_posix(),
                    "output_sha256": file_sha(output_path),
                    "output_locator": output_path.relative_to(
                        self.root
                    ).as_posix(),
                    "video_output_sha256": (
                        file_sha(video_path) if video_path else None
                    ),
                    "video_output_locator": (
                        video_path.relative_to(self.root).as_posix()
                        if video_path
                        else None
                    ),
                }
            )
            self.baseline.append(
                {
                    "schema": BASELINE_RESULT_SCHEMA,
                    "manifest_hash": self.manifest.manifest_hash,
                    "case_id": case.case_id,
                    "completed": True,
                    "crashed": False,
                    "output_sha256": file_sha(baseline_output_path),
                    "output_locator": baseline_output_path.relative_to(
                        self.root
                    ).as_posix(),
                }
            )
        self._write_jsonl(self.results_path, self.results)
        self._write_jsonl(self.baseline_path, self.baseline)
        self._write_human()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
            encoding="utf-8",
        )

    def _write_human(
        self,
        *,
        blinded: str = "true",
        bad_hash: bool = False,
    ) -> None:
        first_case_by_product = {}
        for case in self.manifest.cases:
            first_case_by_product.setdefault(case.product_id, case)
        result_by_id = {row["case_id"]: row for row in self.results}
        baseline_by_id = {row["case_id"]: row for row in self.baseline}
        with self.human_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                (
                    "comparison_id",
                    "rater_id",
                    "case_id",
                    "candidate_a_sha256",
                    "candidate_b_sha256",
                    "winner",
                    "blinded",
                )
            )
            comparison_index = 0
            for rater_index in range(5):
                for product_id in sorted(first_case_by_product):
                    case = first_case_by_product[product_id]
                    proof_hash = result_by_id[case.case_id]["output_sha256"]
                    baseline_hash = baseline_by_id[case.case_id]["output_sha256"]
                    proof_is_a = comparison_index % 2 == 0
                    candidate_a = proof_hash if proof_is_a else baseline_hash
                    candidate_b = baseline_hash if proof_is_a else proof_hash
                    if bad_hash and comparison_index == 0:
                        candidate_a = sha("tampered")
                    proof_wins = comparison_index < 105
                    winner = (
                        "candidate_a" if proof_is_a else "candidate_b"
                    ) if proof_wins else (
                        "candidate_b" if proof_is_a else "candidate_a"
                    )
                    writer.writerow(
                        (
                            f"comparison-{comparison_index:03d}",
                            f"rater-{rater_index + 1}",
                            case.case_id,
                            candidate_a,
                            candidate_b,
                            winner,
                            blinded,
                        )
                    )
                    comparison_index += 1

    def compile(self) -> dict:
        return compile_competition_evidence(
            manifest_path=self.manifest_path,
            results_path=self.results_path,
            baseline_results_path=self.baseline_path,
            human_comparisons_path=self.human_path,
        )

    def test_complete_case_level_evidence_passes_twenty_metric_gate(self) -> None:
        evidence = self.compile()
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
        self.assertEqual(evidence["schema"], COMPILED_EVIDENCE_SCHEMA)
        self.assertEqual(evidence["benchmark_case_count"], 450)
        self.assertEqual(evidence["video_case_count"], 30)
        self.assertEqual(evidence["seed_diversity_group_count"], 90)
        self.assertEqual(evidence["baseline_name"], "Frozen One-Shot Ablation")
        self.assertEqual(evidence["latency_seconds_p95"], 12.5)
        self.assertEqual(evidence["peak_vram_gb_max"], 19.0)
        self.assertEqual(evidence["publish_preferred_count"], 105)
        self.assertEqual(len(report.metrics), 20)
        self.assertTrue(report.passed)

    def test_one_missing_case_fails_before_aggregation(self) -> None:
        self._write_jsonl(self.results_path, self.results[:-1])
        with self.assertRaisesRegex(CompetitionBenchmarkError, "missing 1 case"):
            self.compile()

    def test_duplicate_case_fails_before_aggregation(self) -> None:
        self._write_jsonl(self.results_path, self.results + [self.results[0]])
        with self.assertRaisesRegex(CompetitionBenchmarkError, "duplicate case_id"):
            self.compile()

    def test_tampered_manifest_hash_fails(self) -> None:
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        payload["products"][0]["source_locator"] = "tampered"
        self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(CompetitionBenchmarkError, "manifest_hash"):
            self.compile()

    def test_human_candidate_hash_must_match_paired_outputs(self) -> None:
        self._write_human(bad_hash=True)
        with self.assertRaisesRegex(CompetitionBenchmarkError, "candidate hashes"):
            self.compile()

    def test_unblinded_human_row_is_rejected(self) -> None:
        self._write_human(blinded="false")
        with self.assertRaisesRegex(CompetitionBenchmarkError, "must be blinded"):
            self.compile()

    def test_tampered_output_artifact_is_rejected(self) -> None:
        output_path = self.root / self.results[0]["output_locator"]
        output_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            CompetitionBenchmarkError, "artifact hash mismatch"
        ):
            self.compile()

    def test_copied_seed_outputs_fail_diversity_metric(self) -> None:
        for row in self.results:
            case = next(
                item for item in self.manifest.cases if item.case_id == row["case_id"]
            )
            output_path = self.root / row["output_locator"]
            write_dhash_png(
                output_path,
                int(sha(f"{case.product_id}:{case.aspect_ratio}")[:16], 16),
            )
            row["output_sha256"] = file_sha(output_path)
            gate_path = self.root / row["gate_evidence_locator"]
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            gate["output_sha256"] = row["output_sha256"]
            gate_path.write_text(json.dumps(gate, sort_keys=True), encoding="utf-8")
            row["gate_evidence_sha256"] = file_sha(gate_path)
        self._write_jsonl(self.results_path, self.results)
        self._write_human()
        evidence = self.compile()
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
        self.assertEqual(evidence["seed_diversity_group_pass_rate"], 0.0)
        self.assertFalse(report.passed)

    def test_append_only_journals_resume_without_duplicate_cases(self) -> None:
        case = self.manifest.cases[0]
        source_row = self.results[0]
        journal_path = self.root / "journal-results.jsonl"
        journal = CompetitionCaseJournal(self.manifest_path, journal_path)
        journal.append(
            case_id=case.case_id,
            gate_evidence_path=self.root / source_row["gate_evidence_locator"],
            output_path=self.root / source_row["output_locator"],
            video_output_path=(
                self.root / source_row["video_output_locator"]
                if source_row["video_output_locator"]
                else None
            ),
        )
        resumed = CompetitionCaseJournal(self.manifest_path, journal_path)
        self.assertEqual(resumed.recorded_count, 1)
        self.assertEqual(len(resumed.pending_cases), 449)
        with self.assertRaisesRegex(
            CompetitionBenchmarkError, "already recorded"
        ):
            resumed.append(
                case_id=case.case_id,
                gate_evidence_path=self.root
                / source_row["gate_evidence_locator"],
                output_path=self.root / source_row["output_locator"],
                video_output_path=(
                    self.root / source_row["video_output_locator"]
                    if source_row["video_output_locator"]
                    else None
                ),
            )

        baseline_journal_path = self.root / "journal-baseline.jsonl"
        baseline_journal = BaselineCaseJournal(
            self.manifest_path, baseline_journal_path
        )
        baseline_journal.append(
            case_id=case.case_id,
            completed=True,
            crashed=False,
            output_path=self.root / self.baseline[0]["output_locator"],
        )
        self.assertEqual(
            len(
                BaselineCaseJournal(
                    self.manifest_path, baseline_journal_path
                ).pending_cases
            ),
            449,
        )

    def test_journal_resume_rehashes_already_recorded_artifacts(self) -> None:
        case = self.manifest.cases[0]
        source_row = self.results[0]
        journal_path = self.root / "tamper-journal.jsonl"
        CompetitionCaseJournal(self.manifest_path, journal_path).append(
            case_id=case.case_id,
            gate_evidence_path=self.root / source_row["gate_evidence_locator"],
            output_path=self.root / source_row["output_locator"],
            video_output_path=(
                self.root / source_row["video_output_locator"]
                if source_row["video_output_locator"]
                else None
            ),
        )
        (self.root / source_row["output_locator"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(
            CompetitionBenchmarkError, "artifact hash mismatch"
        ):
            CompetitionCaseJournal(self.manifest_path, journal_path)


if __name__ == "__main__":
    unittest.main()
