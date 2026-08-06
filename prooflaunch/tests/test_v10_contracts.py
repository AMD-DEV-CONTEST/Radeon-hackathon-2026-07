from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import (
    AgencyRole,
    AgencyRoleKind,
    AgencyTopology,
    BreakthroughDecision,
    BreakthroughEvidenceBundle,
    BreakthroughMeasurement,
    BreakthroughBetSpec,
    BreakthroughVerdict,
    ClaimProof,
    EvidenceAxis,
    EvidenceClass,
    EvidencePointer,
    OutcomeEvent,
    ProofManifest,
    TodoStatus,
    TransformProof,
    V10ContractError,
)
from prooflaunch_remix.v10_program import CortexProgram


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SPEC = ROOT / "docs" / "CORTEX_X_V10_1500_TODO.md"


def pointer(axis: EvidenceAxis, suffix: str = "a") -> EvidencePointer:
    return EvidencePointer(
        axis=axis,
        locator=f"evidence/v10/{axis.value}.json",
        sha256=suffix * 64,
        evidence_class=EvidenceClass.OBSERVED,
        note=f"measured {axis.value} evidence",
    )


class CortexProgramTests(unittest.TestCase):
    def test_canonical_program_has_exact_1500_ordered_atomic_items(self) -> None:
        program = CortexProgram.from_files((CANONICAL_SPEC,))
        self.assertEqual(len(program.todos), 1500)
        self.assertEqual(program.todos[0].todo_id, "0001")
        self.assertEqual(program.todos[-1].todo_id, "1500")
        self.assertEqual(len(program.ordered_workstreams()), 36)
        self.assertEqual(program.summary["not_started"], 1500)

    def test_breakthrough_items_require_one_additional_axis(self) -> None:
        program = CortexProgram.from_files((CANONICAL_SPEC,))
        base = program.todos[1199]
        breakthrough = program.todos[1200]
        self.assertEqual(len(base.required_axes), 4)
        self.assertEqual(len(breakthrough.required_axes), 5)
        self.assertIn(EvidenceAxis.TECHNICAL, breakthrough.required_axes)

    def test_todo_cannot_close_without_every_evidence_axis(self) -> None:
        program = CortexProgram.from_files((CANONICAL_SPEC,))
        todo = program.todos[0]
        todo.attach(pointer(EvidenceAxis.DISTILLATION))
        with self.assertRaises(V10ContractError):
            todo.close(TodoStatus.PASSED, conclusion="incomplete evidence")
        for axis in todo.required_axes[1:]:
            todo.attach(pointer(axis))
        todo.close(TodoStatus.PASSED, conclusion="all four axes verified")
        self.assertEqual(todo.status, TodoStatus.PASSED)

    def test_generated_manifest_round_trips(self) -> None:
        program = CortexProgram.from_files((CANONICAL_SPEC,))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            program.write(target)
            self.assertIn(
                '"schema": "ProofLaunchCortexXV10ProgramV1"',
                target.read_text(encoding="utf-8"),
            )

    def test_research_ledger_has_twelve_primary_hypotheses_without_fake_validation(
        self,
    ) -> None:
        ledger = json.loads(
            (
                ROOT / "evidence" / "v10" / "research-ledger.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(ledger["entryCount"], 12)
        self.assertEqual(
            [entry["id"] for entry in ledger["entries"]],
            [f"R{number:02d}" for number in range(1, 13)],
        )
        self.assertTrue(
            all(entry["source"].startswith("https://") for entry in ledger["entries"])
        )
        self.assertTrue(
            all(
                "validated" not in entry["status"]
                and entry["status"] not in {"passed", "promoted"}
                for entry in ledger["entries"]
            )
        )


class TruthBoundaryTests(unittest.TestCase):
    def test_simulated_outcome_is_labeled_predicted_and_not_claimable(self) -> None:
        outcome = OutcomeEvent(
            event_id="out-1",
            metric="conversion_rate",
            value=0.12,
            unit="ratio",
            occurred_at="2026-07-29T12:00:00Z",
            evidence_class=EvidenceClass.SIMULATED,
            source_locator="twin://run-1",
        )
        self.assertEqual(outcome.display_label, "predicted conversion_rate")
        with self.assertRaises(V10ContractError):
            outcome.assert_business_claimable()

    def test_causal_outcome_requires_design_identity(self) -> None:
        with self.assertRaises(V10ContractError):
            OutcomeEvent(
                event_id="out-2",
                metric="revenue",
                value=100.0,
                unit="USD",
                occurred_at="2026-07-29T12:00:00Z",
                evidence_class=EvidenceClass.CAUSAL,
                source_locator="experiment://exp-1",
            )

    def test_one_supervisor_owns_authoritative_state(self) -> None:
        topology = AgencyTopology(
            roles=(
                AgencyRole(
                    "supervisor",
                    AgencyRoleKind.SUPERVISOR,
                    frozenset({"route", "approve"}),
                    owns_state=True,
                    max_actions=5,
                ),
                AgencyRole(
                    "strategist",
                    AgencyRoleKind.SPECIALIST,
                    frozenset({"propose"}),
                ),
            ),
            max_parallel_specialists=2,
            max_total_actions=8,
            stop_conditions=("budget exhausted", "human approval required"),
        )
        self.assertTrue(topology.can("supervisor", "approve"))
        with self.assertRaises(V10ContractError):
            AgencyTopology(
                roles=(
                    AgencyRole(
                        "a",
                        AgencyRoleKind.SUPERVISOR,
                        frozenset(),
                        owns_state=True,
                    ),
                    AgencyRole(
                        "b",
                        AgencyRoleKind.SUPERVISOR,
                        frozenset(),
                        owns_state=True,
                    ),
                ),
                max_parallel_specialists=1,
                max_total_actions=2,
                stop_conditions=("stop",),
            )

    def test_proof_manifest_rejects_unknown_transform(self) -> None:
        transform = TransformProof(
            transform_id="t1",
            operation="master",
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            tool_ref="ffmpeg@7",
        )
        with self.assertRaises(V10ContractError):
            ProofManifest(
                campaign_id="campaign-1",
                claims=(
                    ClaimProof(
                        claim_id="c1",
                        claim_text="Measured claim",
                        source_locator="source.pdf#page=2",
                        source_sha256="c" * 64,
                        asset_id="asset-1",
                        region_or_frame="frame:24",
                        transform_ids=("unknown",),
                        approval_id="approval-1",
                    ),
                ),
                transforms=(transform,),
                asset_hashes={"asset-1": "d" * 64},
            )

    def test_proof_manifest_binds_claim_source_region_transform_and_approval(
        self,
    ) -> None:
        transform = TransformProof(
            transform_id="t1",
            operation="master",
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            tool_ref="ffmpeg@7",
            parameters={"codec": "h264"},
        )
        manifest = ProofManifest(
            campaign_id="campaign-1",
            claims=(
                ClaimProof(
                    claim_id="c1",
                    claim_text="Measured claim",
                    source_locator="source.pdf#page=2",
                    source_sha256="c" * 64,
                    asset_id="asset-1",
                    region_or_frame="frames:24-48",
                    transform_ids=("t1",),
                    approval_id="approval-1",
                ),
            ),
            transforms=(transform,),
            asset_hashes={"asset-1": "d" * 64},
        )
        self.assertEqual(len(manifest.digest), 64)
        self.assertEqual(manifest.claims[0].region_or_frame, "frames:24-48")
        self.assertEqual(manifest.claims[0].approval_id, "approval-1")


class BreakthroughGateTests(unittest.TestCase):
    @staticmethod
    def spec() -> BreakthroughBetSpec:
        return BreakthroughBetSpec(
            bet_id="BT25",
            hypothesis="causal ranking beats correlation",
            baseline_ids=("v9", "correlation"),
            success_thresholds={"auuc_gain": 0.1},
            gpu_budget_hours=4,
            elimination_rules=("negative controls fail",),
            evidence_root="evidence/v10/bt25",
        )

    @staticmethod
    def bundle(*, negative: bool = False) -> BreakthroughEvidenceBundle:
        observed = (pointer(EvidenceAxis.EVIDENCE),)
        return BreakthroughEvidenceBundle(
            bet_id="BT25",
            code=observed,
            configuration=observed,
            data_rights=observed,
            logs=observed,
            ablations=observed,
            radeon_traces=observed,
            product_tests=observed,
            effect_tests=observed,
            negative_results=observed if negative else (),
        )

    def test_bet_promotes_only_when_all_three_axes_pass(self) -> None:
        measurement = BreakthroughMeasurement(
            metric="gain",
            actual=0.2,
            threshold=0.1,
            higher_is_better=True,
            evidence=pointer(EvidenceAxis.EVIDENCE),
        )
        decision = BreakthroughDecision.evaluate(
            self.spec(),
            self.bundle(),
            technical=(measurement,),
            product=(measurement,),
            effect=(measurement,),
        )
        self.assertEqual(decision.verdict, BreakthroughVerdict.PROMOTE)

    def test_negative_failed_bet_is_rejected_not_promoted(self) -> None:
        failed = BreakthroughMeasurement(
            metric="gain",
            actual=0.0,
            threshold=0.1,
            higher_is_better=True,
            evidence=pointer(EvidenceAxis.EVIDENCE),
        )
        decision = BreakthroughDecision.evaluate(
            self.spec(),
            self.bundle(negative=True),
            technical=(failed,),
            product=(failed,),
            effect=(failed,),
        )
        self.assertEqual(decision.verdict, BreakthroughVerdict.REJECT)


if __name__ == "__main__":
    unittest.main()
