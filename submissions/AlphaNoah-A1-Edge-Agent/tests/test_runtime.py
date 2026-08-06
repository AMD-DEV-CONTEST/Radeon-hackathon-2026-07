from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.exceptions import (  # noqa: E402
    DuplicateSubmissionError,
    HumanActorRequired,
    InvalidAnalysisOutput,
    InvalidEventInput,
    InvalidStateTransition,
)
from alphanoah_a1.models import (  # noqa: E402
    Event,
    EventStatus,
    HumanReviewOutcome,
    PostReviewResult,
)
from alphanoah_a1.demo import build_parser, load_json, run_read_only  # noqa: E402
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402


class AlphaNoahRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_directory.name) / "runtime.sqlite3"
        self.runtime = AlphaNoahRuntime(str(self.database))

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    @staticmethod
    def input_fixture() -> dict[str, object]:
        return {
            "data_classification": "Synthetic demo data",
            "location": "Demo Kitchen / Cold Holding Unit A",
            "observed_temperature_c": 9.2,
            "demo_max_temperature_c": 5.0,
            "observation": "Synthetic reading above demo threshold.",
            "not_operational_guidance": True,
        }

    @staticmethod
    def factory_fixture() -> dict[str, object]:
        return load_json(
            REPOSITORY_ROOT / "examples" / "synthetic_factory_incident.json"
        )

    def create_factory_event(self):
        fixture = self.factory_fixture()
        event = self.runtime.create_event(
            event_type=fixture["event_type"],
            source=fixture["source"],
            location=fixture["location"],
            asset_id=fixture["asset_id"],
            reporter=fixture["reporter"],
            description=fixture["description"],
            timestamp=fixture["timestamp"],
            raw_input_ref=fixture["raw_input_ref"],
            attachments=fixture["attachments"],
            metadata=fixture["metadata"],
            actor="system:test-industrial-ingest",
        )
        return event, fixture

    def create_pending_review(self):
        event = self.runtime.create_event(
            source="test:structured-observation",
            raw_input_ref="synthetic://test/event",
            normalized_input=self.input_fixture(),
            actor="system:test",
        )
        decision, _ = self.runtime.analyze_event(event.event_id)
        return event, decision

    def create_in_progress_task(self):
        event, decision = self.create_pending_review()
        self.runtime.submit_human_review(
            decision.decision_id,
            reviewer="human:test-reviewer",
            outcome=HumanReviewOutcome.APPROVED,
            comment="Approved by test operator.",
        )
        task = self.runtime.create_task(
            decision.decision_id,
            actor="human:test-reviewer",
            deadline="2099-01-01T00:00:00+00:00",
        )
        self.runtime.start_task(task.task_id, actor=task.assignee)
        return event, decision, task

    def submit_and_begin_review(self, task, key="evidence-1"):
        evidence = self.runtime.submit_evidence(
            task.task_id,
            evidence_type="structured_temperature_record",
            file_or_data_ref=f"synthetic://test/{key}",
            submitted_by=task.assignee,
            description="Synthetic follow-up reading.",
            idempotency_key=key,
        )
        self.runtime.begin_review(
            task.task_id, actor="rule:synthetic-evidence-review-v1"
        )
        return evidence

    def test_01_normal_closed_loop(self):
        event, decision, task = self.create_in_progress_task()
        evidence = self.submit_and_begin_review(task)
        review = self.runtime.review_task(
            task.task_id,
            reviewer_or_model="rule:synthetic-evidence-review-v1",
            result=PostReviewResult.PASSED,
            comment="Synthetic evidence accepted.",
        )

        self.assertTrue(review.closed)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.CLOSED,
        )
        self.assertEqual(
            self.runtime.store.get_evidence(evidence.evidence_id)
            .validation_status.value,
            "ACCEPTED",
        )
        snapshot = self.runtime.snapshot(event.event_id)
        self.assertEqual(len(snapshot["decisions"]), 1)
        self.assertEqual(len(snapshot["human_reviews"]), 1)
        self.assertEqual(len(snapshot["tasks"]), 1)
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertEqual(len(snapshot["reviews"]), 1)

    def test_02_human_rejection_stops_the_workflow(self):
        event, decision = self.create_pending_review()
        self.runtime.submit_human_review(
            decision.decision_id,
            reviewer="human:test-reviewer",
            outcome=HumanReviewOutcome.REJECTED,
            comment="Rejected by test operator.",
        )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.REJECTED,
        )
        self.assertEqual(
            self.runtime.store.list_tasks(decision.decision_id), []
        )

    def test_03_more_evidence_branch_can_recover_and_close(self):
        event, _, task = self.create_in_progress_task()
        self.submit_and_begin_review(task, "first-evidence")
        first_review = self.runtime.review_task(
            task.task_id,
            reviewer_or_model="rule:synthetic-evidence-review-v1",
            result=PostReviewResult.NEEDS_MORE_EVIDENCE,
            comment="Follow-up record lacks the synthetic confirmation field.",
        )
        self.assertFalse(first_review.closed)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.NEEDS_MORE_EVIDENCE,
        )

        self.runtime.resume_task(task.task_id, actor=task.assignee)
        self.submit_and_begin_review(task, "second-evidence")
        second_review = self.runtime.review_task(
            task.task_id,
            reviewer_or_model="rule:synthetic-evidence-review-v1",
            result=PostReviewResult.PASSED,
            comment="Additional synthetic evidence accepted.",
        )
        self.assertTrue(second_review.closed)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.CLOSED,
        )

    def test_04_illegal_state_transition_is_rejected_and_audited(self):
        event, decision = self.create_pending_review()
        with self.assertRaises(InvalidStateTransition):
            self.runtime.create_task(
                decision.decision_id,
                actor="human:test-reviewer",
                deadline="2099-01-01T00:00:00+00:00",
            )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertEqual(
            self.runtime.store.list_audit(event.trace_id)[-1].action,
            "operation_rejected",
        )

    def test_05_restart_recovers_persisted_state_and_timeline(self):
        event, _ = self.create_pending_review()
        initial_count = len(self.runtime.store.list_audit(event.trace_id))
        restarted = AlphaNoahRuntime(str(self.database))
        recovered = restarted.store.get_event(event.event_id)
        self.assertEqual(recovered.status, EventStatus.PENDING_HUMAN_REVIEW)
        self.assertEqual(
            len(restarted.store.list_audit(event.trace_id)), initial_count
        )

    def test_06_duplicate_evidence_submission_is_blocked(self):
        event, _, task = self.create_in_progress_task()
        self.runtime.submit_evidence(
            task.task_id,
            evidence_type="structured_temperature_record",
            file_or_data_ref="synthetic://test/evidence",
            submitted_by=task.assignee,
            description="Synthetic evidence.",
            idempotency_key="same-key",
        )
        with self.assertRaises(DuplicateSubmissionError):
            self.runtime.submit_evidence(
                task.task_id,
                evidence_type="structured_temperature_record",
                file_or_data_ref="synthetic://test/evidence",
                submitted_by=task.assignee,
                description="Synthetic evidence.",
                idempotency_key="same-key",
            )
        self.assertEqual(
            len(self.runtime.store.list_evidence(task.task_id)), 1
        )
        self.assertEqual(
            self.runtime.store.list_audit(event.trace_id)[-1].action,
            "operation_rejected",
        )

    def test_07_invalid_model_shaped_output_fails_explicitly(self):
        event = self.runtime.create_event(
            source="test:malformed-analysis",
            raw_input_ref="synthetic://test/malformed",
            normalized_input=self.input_fixture(),
            actor="system:test",
        )
        with self.assertRaises(InvalidAnalysisOutput):
            self.runtime.analyze_event(
                event.event_id,
                analysis_payload={"detected_issue": "missing other fields"},
            )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.runtime.retry_failed_event(
            event.event_id, actor="human:test-operator"
        )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.NEW,
        )

    def test_08_audit_chain_has_trace_and_contiguous_event_states(self):
        event, _, task = self.create_in_progress_task()
        self.submit_and_begin_review(task)
        self.runtime.review_task(
            task.task_id,
            reviewer_or_model="rule:synthetic-evidence-review-v1",
            result=PostReviewResult.PASSED,
            comment="Synthetic evidence accepted.",
        )
        records = self.runtime.store.list_audit(event.trace_id)
        self.assertGreaterEqual(len(records), 15)
        self.assertTrue(all(record.trace_id == event.trace_id for record in records))
        event_transitions = [
            record
            for record in records
            if record.object_type == "Event"
            and record.action != "operation_rejected"
        ]
        for previous, current in zip(event_transitions, event_transitions[1:]):
            self.assertEqual(previous.new_state, current.previous_state)
        self.assertEqual(event_transitions[0].new_state, EventStatus.NEW.value)
        self.assertEqual(event_transitions[-1].new_state, EventStatus.CLOSED.value)

    def test_09_no_issue_auto_closes_without_task(self):
        fixture = self.input_fixture()
        fixture["observed_temperature_c"] = 4.4
        event = self.runtime.create_event(
            source="test:no-issue",
            raw_input_ref="synthetic://test/no-issue",
            normalized_input=fixture,
            actor="system:test",
        )
        decision, hook = self.runtime.analyze_event(event.event_id)
        self.assertEqual(hook.action.value, "AUTO_APPROVE")
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.CLOSED,
        )
        self.assertEqual(
            self.runtime.store.list_tasks(decision.decision_id), []
        )

    def test_10_non_human_actor_cannot_submit_human_review(self):
        event, decision = self.create_pending_review()
        with self.assertRaises(HumanActorRequired):
            self.runtime.submit_human_review(
                decision.decision_id,
                reviewer="model:pretending-to-be-human",
                outcome=HumanReviewOutcome.APPROVED,
                comment="This must not be accepted.",
            )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )

    def test_11_list_events_is_read_only(self):
        event, _ = self.create_pending_review()
        before_snapshot = self.runtime.snapshot(event.event_id)
        before_database = self.database.read_bytes()
        output = io.StringIO()
        args = build_parser().parse_args(
            ["--db", str(self.database), "list", "events"]
        )

        with redirect_stdout(output):
            result = run_read_only(args)

        self.assertEqual(result, 0)
        self.assertIn(event.event_id, output.getvalue())
        self.assertIn(event.trace_id, output.getvalue())
        self.assertEqual(self.database.read_bytes(), before_database)
        self.assertEqual(self.runtime.snapshot(event.event_id), before_snapshot)

    def test_12_show_event_and_trace_are_read_only(self):
        event, _ = self.create_pending_review()
        before_snapshot = self.runtime.snapshot(event.event_id)
        before_database = self.database.read_bytes()

        event_output = io.StringIO()
        event_args = build_parser().parse_args(
            ["--db", str(self.database), "show", "event", event.event_id]
        )
        with redirect_stdout(event_output):
            event_result = run_read_only(event_args)

        trace_output = io.StringIO()
        trace_args = build_parser().parse_args(
            ["--db", str(self.database), "show", "trace", event.trace_id]
        )
        with redirect_stdout(trace_output):
            trace_result = run_read_only(trace_args)

        self.assertEqual(event_result, 0)
        self.assertEqual(trace_result, 0)
        self.assertIn(event.event_id, event_output.getvalue())
        self.assertIn(f"Audit timeline ({event.trace_id})", trace_output.getvalue())
        self.assertIn("event_created", trace_output.getvalue())
        self.assertEqual(self.database.read_bytes(), before_database)
        self.assertEqual(self.runtime.snapshot(event.event_id), before_snapshot)

    def test_13_read_only_command_does_not_create_missing_database(self):
        missing_database = Path(self.temp_directory.name) / "missing.sqlite3"
        output = io.StringIO()
        args = build_parser().parse_args(
            ["--db", str(missing_database), "list", "events"]
        )

        with redirect_stderr(output):
            result = run_read_only(args)

        self.assertEqual(result, 2)
        self.assertIn("does not exist", output.getvalue())
        self.assertFalse(missing_database.exists())

    def test_14_industrial_event_creation_and_v01_payload_recovery(self):
        fixture = self.factory_fixture()
        attachments = list(fixture["attachments"])
        metadata = {
            **fixture["metadata"],
            "source_context": {"shift": "A"},
        }
        event = self.runtime.create_event(
            event_type=fixture["event_type"],
            source=fixture["source"],
            location=fixture["location"],
            asset_id=fixture["asset_id"],
            reporter=fixture["reporter"],
            description=fixture["description"],
            timestamp=fixture["timestamp"],
            raw_input_ref=fixture["raw_input_ref"],
            attachments=attachments,
            metadata=metadata,
            actor="system:test-industrial-ingest",
        )
        attachments.append("synthetic://factory/late-mutation")
        metadata["source_context"]["shift"] = "B"
        self.assertEqual(event.attachments, [])
        self.assertEqual(event.metadata["source_context"]["shift"], "A")

        restarted = AlphaNoahRuntime(str(self.database))
        recovered = restarted.store.get_event(event.event_id)
        self.assertEqual(recovered.event_type, "equipment_fault")
        self.assertEqual(recovered.location, "production_line_A")
        self.assertEqual(recovered.asset_id, "machine_001")
        self.assertEqual(recovered.reporter, "operator_001")
        self.assertEqual(recovered.description, "设备出现异常声音")
        self.assertEqual(recovered.attachments, [])
        self.assertEqual(recovered.metadata["source_context"]["shift"], "A")
        self.assertEqual(
            restarted.store.list_audit(event.trace_id)[0].details["event_type"],
            "equipment_fault",
        )

        legacy_payload = {
            "event_id": "event_v01",
            "source": "demo:structured-observation",
            "timestamp": "2026-07-23T00:00:00+00:00",
            "raw_input_ref": "synthetic://v01/event",
            "normalized_input": {
                "location": "Legacy Demo Kitchen",
                "observation": "Legacy synthetic observation.",
            },
            "detected_issue": "",
            "confidence": 0.0,
            "severity": "UNKNOWN",
            "status": "NEW",
            "trace_id": "trace_v01",
        }
        legacy_event = Event.from_dict(legacy_payload)
        self.assertEqual(legacy_event.event_type, "legacy_observation")
        self.assertEqual(legacy_event.location, "Legacy Demo Kitchen")
        self.assertEqual(
            legacy_event.description, "Legacy synthetic observation."
        )
        self.assertEqual(legacy_event.attachments, [])
        self.assertEqual(legacy_event.metadata, {})

        before_count = len(self.runtime.store.list_events())
        with self.assertRaisesRegex(InvalidEventInput, "JSON serializable"):
            self.runtime.create_event(
                event_type="equipment_fault",
                source="manual_report",
                description="Invalid synthetic metadata.",
                metadata={"not_json": object()},
                actor="system:test-industrial-ingest",
            )
        invalid_inputs = (
            {
                "event_type": "",
                "source": "manual_report",
                "description": "Synthetic observation.",
            },
            {
                "event_type": "equipment_fault",
                "source": "",
                "description": "Synthetic observation.",
            },
            {
                "event_type": "equipment_fault",
                "source": "manual_report",
                "description": "",
            },
            {
                "event_type": "equipment_fault",
                "source": "manual_report",
                "description": "Synthetic observation.",
                "metadata": [],
            },
            {
                "event_type": "equipment_fault",
                "source": "manual_report",
                "description": "Synthetic observation.",
                "location": 0,
            },
        )
        for invalid_input in invalid_inputs:
            with self.subTest(invalid_input=invalid_input):
                with self.assertRaises(InvalidEventInput):
                    self.runtime.create_event(
                        **invalid_input,
                        actor="system:test-industrial-ingest",
                    )
        self.assertEqual(len(self.runtime.store.list_events()), before_count)

    def test_15_industrial_event_enters_decision_hook(self):
        event, _ = self.create_factory_event()
        decision, hook = self.runtime.analyze_event(
            event.event_id,
            analysis_payload={
                "detected_issue": "synthetic_abnormal_equipment_sound",
                "decision_type": "human_inspection_required",
                "reasoning_summary": (
                    "Synthetic structured analysis requests human inspection."
                ),
                "evidence": ["reporter_observation=abnormal_sound"],
                "model_or_rule": "test:synthetic-industrial-analysis-v1",
                "confidence": 0.9,
                "requires_human_review": True,
                "severity": "HIGH",
            },
        )

        self.assertEqual(decision.event_id, event.event_id)
        self.assertEqual(hook.action.value, "REQUEST_HUMAN_REVIEW")
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertNotIn("food", hook.reason.lower())

    def test_16_food_skill_accepts_industrial_event_envelope(self):
        fixture = load_json(
            REPOSITORY_ROOT / "examples" / "synthetic_food_sop_event.json"
        )
        event = self.runtime.create_event(
            event_type=fixture["event_type"],
            source=fixture["source"],
            location=fixture["location"],
            asset_id=fixture["asset_id"],
            reporter=fixture["reporter"],
            description=fixture["description"],
            attachments=fixture["attachments"],
            metadata=fixture["metadata"],
            raw_input_ref=fixture["raw_input_ref"],
            normalized_input=fixture["normalized_input"],
            actor="system:test-food-ingest",
        )

        decision, hook = self.runtime.analyze_event(event.event_id)

        self.assertEqual(event.event_type, "food_safety_observation")
        self.assertEqual(event.normalized_input, fixture["normalized_input"])
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).detected_issue,
            "synthetic_cold_holding_temperature_anomaly",
        )
        self.assertEqual(
            decision.decision_type, "corrective_action_required"
        )
        self.assertEqual(
            decision.model_or_rule,
            "rule:synthetic-cold-holding-v1",
        )
        self.assertEqual(decision.confidence, 1.0)
        self.assertEqual(decision.risk_level, "HIGH")
        self.assertEqual(hook.action.value, "REQUEST_HUMAN_REVIEW")
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )


if __name__ == "__main__":
    unittest.main()
