from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.gtm_effect_eval import (
    Capability,
    Deliverable,
    DeliverableRole,
    EffectContractError,
)
from prooflaunch_remix.gtm_effect_packet import (
    EffectReviewPacketBuilder,
    EffectReviewPacketVerifier,
    PacketArtifact,
)


def _entry(
    root: Path,
    *,
    role: DeliverableRole,
    index: int = 1,
    comparison_key: str = "case-1",
    capability: Capability = Capability.COPY,
    scenario_id: str = "b2b-launch",
) -> PacketArtifact:
    content = f"{role.value}-{index}-{capability.value}-{scenario_id}".encode()
    source = root / f"{role.value}-{index}.json"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    deliverable = Deliverable(
        deliverable_id=f"{role.value}-{index}-{capability.value}",
        scenario_id=scenario_id,
        capability=capability,
        role=role,
        content_sha256=digest,
        blind_artifact_locator=f"source://{role.value}/{index}",
        rights_locator=f"rights://{role.value}/{index}",
        evidence_locators=(f"evidence://{index}",),
        claim_ids=(f"claim-{index}",),
        brand_profile_id="brand-v1",
        channel="linkedin_organic",
        accessibility_locator=f"a11y://{role.value}/{index}",
        experiment_trace_id=f"exp-{index}",
        clean_room_attested=True,
        method_reference_locators=("https://official.example/method",),
    )
    return PacketArtifact(deliverable, str(source), comparison_key)


class EffectReviewPacketBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.builder = EffectReviewPacketBuilder()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, entries=None, **kwargs):
        entries = entries or [
            _entry(self.root, role=DeliverableRole.CANDIDATE),
            _entry(self.root, role=DeliverableRole.BASELINE),
        ]
        return self.builder.build(
            entries,
            self.root / "packet",
            randomization_key=kwargs.pop("randomization_key", "private-key-123456789"),
            **kwargs,
        )

    def test_builds_role_blind_packet_and_empty_templates(self) -> None:
        packet = self.build()
        self.assertEqual(packet.pair_count, 1)
        rows = [
            json.loads(line)
            for line in Path(packet.public_pairs_path).read_text().splitlines()
        ]
        serialized = json.dumps(rows)
        self.assertNotIn("candidate", serialized)
        self.assertNotIn("baseline", serialized)
        self.assertIsNone(rows[0]["choice"])
        templates = list((Path(packet.root) / "public" / "reviewers").glob("*.jsonl"))
        self.assertEqual(len(templates), 3)
        self.assertTrue(all('"choice":null' in path.read_text() for path in templates))

    def test_private_mapping_holds_roles_but_not_randomization_key(self) -> None:
        packet = self.build()
        raw = Path(packet.private_mapping_path).read_text()
        self.assertIn('"role": "candidate"', raw)
        self.assertIn('"role": "baseline"', raw)
        self.assertNotIn("private-key-123456789", raw)
        self.assertFalse(json.loads(raw)["randomization_key_persisted"])

    def test_manifest_truthfully_marks_zero_votes_and_no_promotion(self) -> None:
        packet = self.build()
        manifest = json.loads(Path(packet.manifest_path).read_text())
        self.assertEqual(manifest["review_votes_completed"], 0)
        self.assertFalse(manifest["effect_promotion_passed"])
        self.assertIn("not human observations", manifest["truth_boundary"])

    def test_blind_assets_preserve_content_hashes(self) -> None:
        packet = self.build()
        rows = [json.loads(Path(packet.public_pairs_path).read_text().splitlines()[0])]
        assets = Path(packet.root) / "public"
        copied = {hashlib.sha256((assets / rows[0][side]).read_bytes()).hexdigest() for side in ("left_artifact", "right_artifact")}
        expected = {
            _entry(self.root, role=DeliverableRole.CANDIDATE).deliverable.content_sha256,
            _entry(self.root, role=DeliverableRole.BASELINE).deliverable.content_sha256,
        }
        self.assertEqual(copied, expected)

    def test_randomization_is_stable_for_same_key(self) -> None:
        first = self.build()
        first_public = Path(first.public_pairs_path).read_text()
        second_root = self.root / "second"
        second_root.mkdir()
        entries = [
            _entry(second_root, role=DeliverableRole.CANDIDATE),
            _entry(second_root, role=DeliverableRole.BASELINE),
        ]
        second = self.builder.build(
            entries,
            second_root / "packet",
            randomization_key="private-key-123456789",
        )
        self.assertEqual(first_public, Path(second.public_pairs_path).read_text())

    def test_different_private_key_can_change_commitment(self) -> None:
        first = self.build()
        first_private = json.loads(Path(first.private_mapping_path).read_text())
        second_root = self.root / "second"
        second_root.mkdir()
        second = self.builder.build(
            [
                _entry(second_root, role=DeliverableRole.CANDIDATE),
                _entry(second_root, role=DeliverableRole.BASELINE),
            ],
            second_root / "packet",
            randomization_key="different-private-key-987654",
        )
        second_private = json.loads(Path(second.private_mapping_path).read_text())
        self.assertNotEqual(
            first_private["pairs"][0]["randomization_commitment"],
            second_private["pairs"][0]["randomization_commitment"],
        )

    def test_hash_mismatch_fails_closed(self) -> None:
        item = _entry(self.root, role=DeliverableRole.CANDIDATE)
        Path(item.source_path).write_text("tampered")
        with self.assertRaisesRegex(EffectContractError, "content hash mismatch"):
            self.build([item, _entry(self.root, role=DeliverableRole.BASELINE)])

    def test_missing_source_fails_closed(self) -> None:
        item = _entry(self.root, role=DeliverableRole.CANDIDATE)
        Path(item.source_path).unlink()
        with self.assertRaisesRegex(EffectContractError, "source is missing"):
            self.build([item, _entry(self.root, role=DeliverableRole.BASELINE)])

    def test_requires_one_candidate_and_one_baseline_per_comparison(self) -> None:
        with self.assertRaisesRegex(EffectContractError, "exactly one candidate"):
            self.build([_entry(self.root, role=DeliverableRole.CANDIDATE)])

    def test_duplicate_deliverable_id_is_rejected(self) -> None:
        first = _entry(self.root, role=DeliverableRole.CANDIDATE, comparison_key="one")
        duplicate = replace(first, comparison_key="two")
        with self.assertRaisesRegex(EffectContractError, "duplicate deliverable_id"):
            self.build([first, duplicate])

    def test_duplicate_content_pair_cannot_inflate_size(self) -> None:
        candidate = _entry(self.root, role=DeliverableRole.CANDIDATE, comparison_key="one")
        baseline = _entry(self.root, role=DeliverableRole.BASELINE, comparison_key="one")
        second_candidate = replace(
            candidate,
            deliverable=replace(candidate.deliverable, deliverable_id="candidate-second"),
            comparison_key="two",
        )
        second_baseline = replace(
            baseline,
            deliverable=replace(baseline.deliverable, deliverable_id="baseline-second"),
            comparison_key="two",
        )
        with self.assertRaisesRegex(EffectContractError, "duplicate content pair"):
            self.build([candidate, baseline, second_candidate, second_baseline])

    def test_candidate_and_baseline_exact_duplicate_is_rejected(self) -> None:
        candidate = _entry(self.root, role=DeliverableRole.CANDIDATE)
        baseline = _entry(self.root, role=DeliverableRole.BASELINE)
        baseline = replace(
            baseline,
            source_path=candidate.source_path,
            deliverable=replace(
                baseline.deliverable,
                content_sha256=candidate.deliverable.content_sha256,
            ),
        )
        with self.assertRaises(EffectContractError):
            self.build([candidate, baseline])

    def test_copied_reference_asset_is_rejected(self) -> None:
        item = _entry(self.root, role=DeliverableRole.CANDIDATE)
        item = replace(
            item,
            deliverable=replace(
                item.deliverable,
                copied_reference_asset_ids=("protected-work",),
            ),
        )
        with self.assertRaisesRegex(EffectContractError, "may not be copied"):
            self.build([item, _entry(self.root, role=DeliverableRole.BASELINE)])

    def test_short_randomization_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(EffectContractError, "at least 16"):
            self.build(randomization_key="short")

    def test_reviewer_count_is_bounded(self) -> None:
        with self.assertRaisesRegex(EffectContractError, r"\[2, 9\]"):
            self.build(reviewer_count=1)

    def test_nonempty_output_directory_is_rejected(self) -> None:
        destination = self.root / "packet"
        destination.mkdir()
        (destination / "old.txt").write_text("old")
        with self.assertRaisesRegex(EffectContractError, "must be empty"):
            self.builder.build(
                [
                    _entry(self.root, role=DeliverableRole.CANDIDATE),
                    _entry(self.root, role=DeliverableRole.BASELINE),
                ],
                destination,
                randomization_key="private-key-123456789",
            )

    def test_private_files_are_owner_only(self) -> None:
        packet = self.build()
        mode = stat.S_IMODE(Path(packet.private_mapping_path).stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_multiple_capabilities_and_scenarios_are_manifested(self) -> None:
        entries = []
        for index, capability in enumerate((Capability.COPY, Capability.VIDEO), start=1):
            scenario = f"scenario-{index}"
            entries.extend(
                [
                    _entry(
                        self.root,
                        role=DeliverableRole.CANDIDATE,
                        index=index,
                        comparison_key=f"key-{index}",
                        capability=capability,
                        scenario_id=scenario,
                    ),
                    _entry(
                        self.root,
                        role=DeliverableRole.BASELINE,
                        index=index,
                        comparison_key=f"key-{index}",
                        capability=capability,
                        scenario_id=scenario,
                    ),
                ]
            )
        packet = self.build(entries)
        manifest = json.loads(Path(packet.manifest_path).read_text())
        self.assertEqual(manifest["capabilities"], ["copy", "video"])
        self.assertEqual(manifest["scenarios"], ["scenario-1", "scenario-2"])
        self.assertEqual(packet.pair_count, 2)

    def test_empty_templates_never_count_as_completed_human_review(self) -> None:
        packet = self.build()
        report = EffectReviewPacketVerifier().verify(packet.root)
        self.assertFalse(report.complete)
        self.assertFalse(report.effect_promotion_passed)
        self.assertEqual(report.reviewer_count, 0)
        self.assertTrue(any("choice must be" in item for item in report.failures))

    def _complete_reviews(
        self,
        packet,
        *,
        duplicate_rater: bool = False,
        contradictory_rating: bool = False,
    ) -> str:
        private = json.loads(Path(packet.private_mapping_path).read_text())
        candidate_side = private["pairs"][0]["candidate_side"]
        other_side = "right" if candidate_side == "left" else "left"
        reviewer_paths = sorted(
            (Path(packet.root) / "public" / "reviewers").glob("*.jsonl")
        )
        for index, reviewer_path in enumerate(reviewer_paths, start=1):
            rows = [json.loads(line) for line in reviewer_path.read_text().splitlines()]
            for row in rows:
                row.update(
                    {
                        "choice": candidate_side,
                        "rater_id": "human-01" if duplicate_rater else f"human-{index:02d}",
                        "independent_attestation": True,
                        "conflict_disclosed": True,
                        "reviewed_at": f"2026-08-01T12:3{index}:00Z",
                        f"{candidate_side}_directly_publishable": True,
                        f"{candidate_side}_major_rework": contradictory_rating,
                        f"{other_side}_directly_publishable": False,
                        f"{other_side}_major_rework": True,
                        "rationale": "Candidate is clearer, more specific, and ready for channel use.",
                    }
                )
            reviewer_path.write_text(
                "".join(f"{json.dumps(row, sort_keys=True)}\n" for row in rows)
            )
        return candidate_side

    def test_completed_reviews_are_verified_but_small_sample_cannot_promote(self) -> None:
        packet = self.build()
        self._complete_reviews(packet)
        report = EffectReviewPacketVerifier().verify(packet.root)
        self.assertTrue(report.complete)
        self.assertFalse(report.effect_promotion_passed)
        self.assertEqual(report.reviewer_count, 3)
        self.assertEqual(report.completed_vote_count, 3)
        self.assertEqual(report.candidate_preferred_count, 3)
        self.assertEqual(report.candidate_preference_rate, 1.0)
        self.assertEqual(report.candidate_publishable_rate, 1.0)
        self.assertEqual(report.candidate_major_rework_rate, 0.0)
        self.assertTrue(
            any("Wilson lower bound" in item for item in report.failures)
        )

    def test_duplicate_human_identity_fails_independence_gate(self) -> None:
        packet = self.build()
        self._complete_reviews(packet, duplicate_rater=True)
        report = EffectReviewPacketVerifier().verify(packet.root)
        self.assertFalse(report.complete)
        self.assertFalse(report.effect_promotion_passed)
        self.assertTrue(any("duplicate rater_id" in item for item in report.failures))

    def test_contradictory_publishability_rating_fails_closed(self) -> None:
        packet = self.build()
        self._complete_reviews(packet, contradictory_rating=True)
        report = EffectReviewPacketVerifier().verify(packet.root)
        self.assertFalse(report.complete)
        self.assertFalse(report.effect_promotion_passed)
        self.assertTrue(any("publishable and major rework" in item for item in report.failures))

    def test_packet_hash_tampering_fails_closed(self) -> None:
        packet = self.build()
        self._complete_reviews(packet)
        with Path(packet.public_pairs_path).open("a", encoding="utf-8") as handle:
            handle.write("{}\n")
        report = EffectReviewPacketVerifier().verify(packet.root)
        self.assertFalse(report.complete)
        self.assertFalse(report.effect_promotion_passed)
        self.assertIn("public pairs hash mismatch", report.failures)


if __name__ == "__main__":
    unittest.main()
