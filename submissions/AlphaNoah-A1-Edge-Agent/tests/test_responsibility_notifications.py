from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.models import (  # noqa: E402
    AnalysisResult,
    EventStatus,
)
from alphanoah_a1.demo import build_parser, run_read_only  # noqa: E402
from alphanoah_a1.notifications import NotificationStatus  # noqa: E402
from alphanoah_a1.responsibility import (  # noqa: E402
    ResponsibilityDirectory,
)
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402


class FakeAnalysisProvider:
    provider_id = "fake:task04-analysis"

    def analyze(self, event: object) -> AnalysisResult:
        return AnalysisResult(
            detected_issue="Preliminary industrial issue",
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary="Possible cause; not a confirmed diagnosis.",
            evidence=["Synthetic operator report"],
            model_or_rule="fake:model",
            confidence=0.8,
            requires_human_review=True,
            severity="HIGH",
        )


class ResponsibilityNotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "runtime.sqlite3"
        self.runtime = AlphaNoahRuntime(str(self.database))
        self.directory = ResponsibilityDirectory.from_file(
            REPOSITORY_ROOT / "examples" / "responsibility_directory.json"
        )

    def create_event(
        self,
        *,
        asset_id: str = "PACK-003",
        location: str = "Packaging-Line-A",
        event_type: str = "equipment_issue_report",
    ):
        return self.runtime.create_event(
            source="manual_report",
            actor="adapter:test-task04",
            event_type=event_type,
            location=location,
            asset_id=asset_id,
            reporter="synthetic_operator",
            description="Synthetic abnormal sound report.",
            metadata={
                "data_classification": "Synthetic demo data",
                "incident_notice": "Not a real production incident",
            },
        )

    def create_decision(self, event):
        decision, _ = self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=FakeAnalysisProvider(),
        )
        return decision

    def test_01_asset_match_has_highest_priority(self) -> None:
        assignment = self.directory.resolve(self.create_event())

        self.assertEqual(assignment.owner_id, "maintenance_001")
        self.assertEqual(assignment.owner_name, "Equipment Maintenance")
        self.assertEqual(assignment.match_type, "asset")
        self.assertEqual(assignment.matched_key, "PACK-003")

    def test_02_location_match_is_used_without_asset_match(self) -> None:
        event = self.create_event(asset_id="UNKNOWN-ASSET")
        assignment = self.directory.resolve(event)

        self.assertEqual(assignment.owner_id, "line_owner_001")
        self.assertEqual(assignment.match_type, "location")
        self.assertEqual(assignment.matched_key, "Packaging-Line-A")

    def test_03_event_type_default_is_used_after_location(self) -> None:
        event = self.create_event(
            asset_id="UNKNOWN-ASSET",
            location="Unknown-Line",
        )
        assignment = self.directory.resolve(event)

        self.assertEqual(assignment.owner_id, "maintenance_triage")
        self.assertEqual(assignment.match_type, "event_type")
        self.assertEqual(assignment.matched_key, "equipment_issue_report")

    def test_04_unmatched_event_is_preserved_as_unassigned(self) -> None:
        event = self.create_event(
            asset_id="UNKNOWN-ASSET",
            location="Unknown-Line",
            event_type="unmapped_incident",
        )
        assignment = self.directory.resolve(event)

        self.assertEqual(assignment.owner_id, "UNASSIGNED")
        self.assertEqual(assignment.owner_name, "Unassigned")
        self.assertEqual(assignment.match_type, "unassigned")
        self.assertEqual(assignment.matched_key, "")
        decision = self.create_decision(event)
        notification = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=self.directory,
        )
        self.assertEqual(notification.recipient_id, "UNASSIGNED")
        self.assertEqual(
            len(self.runtime.store.list_notifications(event.event_id)), 1
        )

    def test_05_decision_creates_local_notification_and_audit(self) -> None:
        event = self.create_event()
        decision = self.create_decision(event)
        notification = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=self.directory,
        )

        self.assertEqual(notification.event_id, event.event_id)
        self.assertEqual(notification.trace_id, event.trace_id)
        self.assertEqual(notification.decision_id, decision.decision_id)
        self.assertEqual(notification.recipient_id, "maintenance_001")
        self.assertEqual(notification.channel, "local_outbox")
        self.assertEqual(notification.status, NotificationStatus.CREATED)
        self.assertNotIn(decision.reasoning_summary, notification.content)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertEqual(
            self.runtime.store.list_human_reviews(decision.decision_id), []
        )
        self.assertEqual(self.runtime.store.list_tasks(decision.decision_id), [])
        creation_audits = [
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "notification_created"
        ]
        self.assertEqual(len(creation_audits), 1)
        self.assertEqual(
            creation_audits[0].details["match_type"], "asset"
        )
        trace_args = build_parser().parse_args(
            ["--db", str(self.database), "show", "trace", event.trace_id]
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run_read_only(trace_args), 0)
        self.assertIn("notification_created", output.getvalue())

    def test_06_duplicate_decision_creates_one_notification(self) -> None:
        event = self.create_event()
        decision = self.create_decision(event)

        first = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=self.directory,
        )
        second = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=ResponsibilityDirectory(),
        )

        self.assertEqual(first.notification_id, second.notification_id)
        self.assertEqual(
            len(self.runtime.store.list_notifications(event.event_id)), 1
        )
        self.assertEqual(
            sum(
                record.action == "notification_created"
                for record in self.runtime.store.list_audit(event.trace_id)
            ),
            1,
        )

    def test_07_notification_survives_restart_and_enters_snapshot(self) -> None:
        event = self.create_event()
        decision = self.create_decision(event)
        created = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=self.directory,
        )

        restarted = AlphaNoahRuntime(str(self.database))
        recovered = restarted.store.get_notification(created.notification_id)
        snapshot = restarted.snapshot(event.event_id)

        self.assertEqual(recovered.to_dict(), created.to_dict())
        self.assertEqual(len(snapshot["notifications"]), 1)
        self.assertEqual(
            snapshot["notifications"][0]["status"],
            NotificationStatus.CREATED,
        )


if __name__ == "__main__":
    unittest.main()
