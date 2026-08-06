from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.audience_pulse import GemmaAudiencePulse, RecordedAudiencePulse
from prooflaunch_remix.contracts import (
    CampaignRequest,
    Claim,
    CreativeBrief,
    ReleaseApproval,
    ReleaseDecision,
    Severity,
    Stage,
)
from prooflaunch_remix.demo import build_demo_supervisor
from prooflaunch_remix.ledger import EvidenceLedger
from prooflaunch_remix.policy import ActionPolicy, PolicyResult, ToolIntent
from prooflaunch_remix.workflow import Supervisor, WorkflowBlocked


class WorkflowTests(unittest.TestCase):
    def request(self) -> CampaignRequest:
        return CampaignRequest(
            product_name="Aster Arc",
            product_image="fixture.png",
            specification_text="Battery life up to 18 hours.",
            market="Japan",
            platform="TikTok",
            goal="launch",
            target_emotion="joy",
        )

    def approval(self, state, *, decision=ReleaseDecision.APPROVE) -> ReleaseApproval:
        return ReleaseApproval.create(
            run_id=state.run_id,
            preview_digest=state.prepared_preview_digest or "",
            decision=decision,
            approver="workflow-test-reviewer",
            reason="Explicit test decision over the persisted preview.",
            issued_at="2026-07-01T00:00:00+00:00",
        )

    def test_bounded_repair_then_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            supervisor = build_demo_supervisor()
            prepared = supervisor.prepare(
                self.request(), directory, run_id="test-run"
            )
            self.assertEqual(prepared.stage, Stage.AWAITING_RELEASE)
            self.assertEqual(prepared.exports, [])
            state = supervisor.release(directory, self.approval(prepared))
            self.assertEqual(state.stage, Stage.DELIVER)
            self.assertEqual(state.repair_count, 1)
            self.assertEqual(state.release_blockers, [])
            self.assertTrue(Path(state.exports[0]).exists())
            self.assertTrue(
                EvidenceLedger.verify(Path(directory) / "evidence-ledger.jsonl")
            )

    def test_manifest_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            build_demo_supervisor().prepare(
                self.request(), directory, run_id="test-run"
            )
            manifest = json.loads(
                (Path(directory) / "campaign-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["stage"], "awaiting_release")
            self.assertEqual(manifest["repair_count"], 1)
            self.assertEqual(len(manifest["prepared_preview_digest"]), 64)

    def test_ledger_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            build_demo_supervisor().prepare(
                self.request(), directory, run_id="test-run"
            )
            ledger_path = Path(directory) / "evidence-ledger.jsonl"
            content = ledger_path.read_text(encoding="utf-8")
            ledger_path.write_text(content.replace("claims_extracted", "claims_faked", 1))
            self.assertFalse(EvidenceLedger.verify(ledger_path))

    def test_malformed_ledger_is_detected_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "evidence-ledger.jsonl"
            ledger_path.write_text("{not-json}\n", encoding="utf-8")
            self.assertFalse(EvidenceLedger.verify(ledger_path))

    def test_output_directory_cannot_reuse_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            build_demo_supervisor().prepare(self.request(), directory, run_id="first")
            with self.assertRaises(FileExistsError):
                build_demo_supervisor().prepare(
                    self.request(), directory, run_id="second"
                )

    def test_rejection_blocks_without_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            supervisor = build_demo_supervisor()
            prepared = supervisor.prepare(
                self.request(), directory, run_id="rejected-run"
            )
            state = supervisor.release(
                directory,
                self.approval(prepared, decision=ReleaseDecision.REJECT),
            )
            self.assertEqual(state.stage, Stage.BLOCKED)
            self.assertEqual(state.exports, [])
            self.assertIn("release rejected", state.blocked_reason or "")

    def test_state_tampering_prevents_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            supervisor = build_demo_supervisor()
            prepared = supervisor.prepare(
                self.request(), directory, run_id="tampered-run"
            )
            manifest_path = Path(directory) / "campaign-state.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["claims"][0]["text"] = "Unsupported replacement claim."
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(WorkflowBlocked, "changed after audit"):
                supervisor.release(directory, self.approval(prepared))

    def test_missing_source_bound_claim_fails_closed(self) -> None:
        base = build_demo_supervisor().adapters

        class NoEvidence:
            def extract(self, request: CampaignRequest) -> list[Claim]:
                return []

        supervisor = Supervisor(replace(base, evidence=NoEvidence()))
        with tempfile.TemporaryDirectory() as directory:
            state = supervisor.run(self.request(), directory, run_id="blocked-run")
            self.assertEqual(state.stage, Stage.BLOCKED)
            self.assertIn("no source-bound approved claims", state.blocked_reason or "")

    def test_persistent_audit_failure_stops_after_two_repairs(self) -> None:
        base = build_demo_supervisor().adapters

        class AlwaysFail:
            def audit(self, state):
                from prooflaunch_remix.contracts import AuditFinding

                return [
                    AuditFinding(
                        id="AUD-PERSISTENT",
                        category="claim_guard",
                        severity=Severity.CRITICAL,
                        message="Unsupported numeric claim remains.",
                        asset_id=state.assets[0].id,
                        repair_action="drop_claim",
                    )
                ]

        supervisor = Supervisor(replace(base, auditor=AlwaysFail()))
        with tempfile.TemporaryDirectory() as directory:
            state = supervisor.run(self.request(), directory, run_id="blocked-run")
            self.assertEqual(state.stage, Stage.BLOCKED)
            self.assertEqual(state.repair_count, 2)
            self.assertIn("after 2 repair rounds", state.blocked_reason or "")

    def test_adapter_exception_fails_closed_and_is_ledgered(self) -> None:
        base = build_demo_supervisor().adapters

        class CrashingAuditor:
            def audit(self, state):
                del state
                raise RuntimeError("simulated local model failure")

        supervisor = Supervisor(replace(base, auditor=CrashingAuditor()))
        with tempfile.TemporaryDirectory() as directory:
            state = supervisor.run(self.request(), directory, run_id="adapter-failure")
            self.assertEqual(state.stage, Stage.BLOCKED)
            self.assertIn("adapter failure", state.blocked_reason or "")
            ledger = Path(directory) / "evidence-ledger.jsonl"
            self.assertTrue(EvidenceLedger.verify(ledger))
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["kind"], "adapter_failure")


class PolicyTests(unittest.TestCase):
    def test_read_only_is_allowed(self) -> None:
        decision = ActionPolicy().decide(
            ToolIntent(tool="browser", action="inspect", reads=("example.com",))
        )
        self.assertEqual(decision.result, PolicyResult.ALLOW)

    def test_send_requires_approval(self) -> None:
        decision = ActionPolicy().decide(
            ToolIntent(
                tool="connector",
                action="send",
                external_side_effect=True,
            )
        )
        self.assertEqual(decision.result, PolicyResult.REQUIRE_APPROVAL)

    def test_publish_requires_approval_and_cannot_be_automatic(self) -> None:
        decision = ActionPolicy().decide(
            ToolIntent(
                tool="browser",
                action="publish",
                external_side_effect=True,
            )
        )
        self.assertEqual(decision.result, PolicyResult.REQUIRE_APPROVAL)

    def test_disable_audit_and_destructive_delete_are_denied(self) -> None:
        disable_audit = ActionPolicy().decide(
            ToolIntent(tool="disable_audit", action="run")
        )
        destructive_delete = ActionPolicy().decide(
            ToolIntent(
                tool="filesystem",
                action="delete",
                writes=("evidence",),
                destructive=True,
            )
        )
        self.assertEqual(disable_audit.result, PolicyResult.DENY)
        self.assertEqual(destructive_delete.result, PolicyResult.DENY)

    def test_untrusted_side_effect_is_denied(self) -> None:
        decision = ActionPolicy().decide(
            ToolIntent(
                tool="browser",
                action="publish",
                external_side_effect=True,
                contains_untrusted_instructions=True,
            )
        )
        self.assertEqual(decision.result, PolicyResult.DENY)


class AudiencePulseTests(unittest.TestCase):
    def brief(self) -> CreativeBrief:
        return CreativeBrief(
            id="BRF-001",
            headline="A joyful evidence-led product launch",
            claim_ids=("CLM-001",),
            visual_direction="evidence-forward",
            target_emotion="joy",
        )

    def test_valid_notebook_label_is_bounded(self) -> None:
        pulse = GemmaAudiencePulse(lambda _: "Joy").review(self.brief())
        self.assertEqual(pulse.predicted_emotion, "joy")
        self.assertTrue(pulse.matched)
        self.assertIn("do not measure persuasion", pulse.limitations[0])

    def test_invalid_notebook_output_fails_closed(self) -> None:
        pulse = GemmaAudiencePulse(lambda _: "high conversion").review(self.brief())
        self.assertEqual(pulse.predicted_emotion, "invalid")
        self.assertEqual(pulse.confidence, 0.0)
        self.assertFalse(pulse.matched)

    def test_recorded_pulse_fails_on_target_mismatch(self) -> None:
        pulse = GemmaAudiencePulse(lambda _: "joy").review(self.brief())
        critic = RecordedAudiencePulse(pulse)
        mismatched = critic.review(
            CreativeBrief(
                id="BRF-002",
                headline="A fearful brief",
                claim_ids=("CLM-001",),
                visual_direction="evidence-forward",
                target_emotion="fear",
            )
        )
        self.assertFalse(mismatched.matched)
        self.assertEqual(mismatched.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
