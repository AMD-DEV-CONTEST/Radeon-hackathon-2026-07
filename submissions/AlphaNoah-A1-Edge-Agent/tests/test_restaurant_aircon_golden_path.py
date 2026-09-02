"""Task 05A restaurant-aircon golden-path tests."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.demo import (  # noqa: E402
    build_parser,
    run_restaurant_aircon_demo,
)
from alphanoah_a1.ai_reliability import (  # noqa: E402
    ModelOutputInvalidError,
)
from alphanoah_a1.exceptions import (  # noqa: E402
    InvalidStateTransition,
    ProviderTransportError,
    SkillResolutionError,
)
from alphanoah_a1.golden_path import (  # noqa: E402
    RestaurantAirconFakeAnalysisProvider,
    build_restaurant_aircon_golden_path,
    restaurant_aircon_event_metadata,
    restaurant_aircon_form_fields,
    restaurant_aircon_task_template,
)
from alphanoah_a1.knowledge import KnowledgeContext  # noqa: E402
from alphanoah_a1.models import (  # noqa: E402
    EventStatus,
    HumanReviewOutcome,
    PostReviewResult,
    TaskStatus,
)
from alphanoah_a1.qr_input import IncidentReportInputError  # noqa: E402
from alphanoah_a1.skills.demo import (  # noqa: E402
    INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL,
    RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL,
)
from alphanoah_a1.skills.resolver import (  # noqa: E402
    DeterministicSkillResolver,
)


class FailingRestaurantProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:failing-restaurant-provider"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        raise ProviderTransportError(
            "Synthetic unavailable provider.",
            code="connection_error",
        )


class InvalidRestaurantProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:invalid-restaurant-provider"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        return "not structured output"


class RestaurantAirconCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = (
            Path(self.temporary_directory.name) / "task05a.sqlite3"
        )

    def build_application(self, *, raw_provider=None):
        return build_restaurant_aircon_golden_path(
            self.database,
            raw_provider=raw_provider,
        )

    def test_01_scenario_defaults_are_stable_and_synthetic(self) -> None:
        first = restaurant_aircon_form_fields()
        second = restaurant_aircon_form_fields()

        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(first["event_type"], "equipment_fault_report")
        self.assertEqual(
            restaurant_aircon_event_metadata()["asset_type"],
            "air_conditioner",
        )
        self.assertTrue(first["reporter"].startswith("synthetic:"))
        self.assertTrue(
            restaurant_aircon_task_template()["assignee"].startswith("demo:")
        )

    def test_02_fake_provider_requires_the_existing_restaurant_skill(
        self,
    ) -> None:
        provider = RestaurantAirconFakeAnalysisProvider()
        context = RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL.to_context(
            resolution_reason=(
                "matched:event_type,asset_type;specificity=2"
            )
        )
        event = self.build_application().submit_incident()

        result = provider.analyze_with_contexts(
            event,
            context,
            KnowledgeContext(),
        )

        self.assertTrue(result.requires_human_review)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result.severity, "HIGH")

    def test_03_complete_path_uses_real_boundaries_and_closes(
        self,
    ) -> None:
        application = self.build_application()

        event = application.submit_incident()
        persisted = application.runtime.store.get_event(event.event_id)
        self.assertEqual(persisted.source, "qr_incident_report")
        self.assertEqual(persisted.status, EventStatus.NEW)
        self.assertEqual(persisted.metadata["asset_type"], "air_conditioner")

        analysis = application.analyze(event.event_id)
        self.assertEqual(
            analysis.selected_skill_id,
            "restaurant-aircon-troubleshooting",
        )
        self.assertEqual(analysis.validation_status, "VALID")
        self.assertEqual(
            analysis.event_status,
            EventStatus.PENDING_HUMAN_REVIEW.value,
        )
        self.assertEqual(len(analysis.knowledge_matches), 1)
        self.assertEqual(
            analysis.knowledge_matches[0].document_id,
            "synthetic_restaurant_aircon_troubleshooting_reference_v1",
        )
        self.assertEqual(
            application.runtime.store.list_tasks(analysis.decision_id),
            [],
        )

        application.submit_human_review(
            analysis.decision_id,
            outcome=HumanReviewOutcome.APPROVED,
            comment="Explicit synthetic approval.",
        )
        task = application.create_approved_task(analysis.decision_id)
        self.assertEqual(
            task.task_type,
            "restaurant_aircon_fault_inspection",
        )
        self.assertEqual(task.status, TaskStatus.CREATED)
        application.start_task(task.task_id)
        evidence = application.submit_synthetic_evidence(task.task_id)
        application.begin_evidence_review(task.task_id)
        review = application.review_evidence(
            task.task_id,
            result=PostReviewResult.PASSED,
            comment="Explicit synthetic evidence acceptance.",
        )

        self.assertTrue(review.closed)
        self.assertEqual(
            application.runtime.store.get_event(event.event_id).status,
            EventStatus.CLOSED,
        )
        self.assertEqual(
            application.runtime.store.get_evidence(
                evidence.evidence_id
            ).validation_status.value,
            "ACCEPTED",
        )
        timeline = application.timeline(event.event_id)
        self.assertEqual(
            [entry.sequence for entry in timeline],
            list(range(1, len(timeline) + 1)),
        )
        self.assertEqual(timeline[-1].status, EventStatus.CLOSED.value)

    def test_04_invalid_qr_input_does_not_create_event(self) -> None:
        application = self.build_application()
        invalid = restaurant_aircon_form_fields()
        invalid["description"] = ""

        with self.assertRaises(IncidentReportInputError):
            application.submit_incident(invalid)

        self.assertEqual(application.runtime.store.list_events(), [])

    def test_05_missing_skill_prevents_provider_call(self) -> None:
        raw_provider = RestaurantAirconFakeAnalysisProvider()
        application = self.build_application(raw_provider=raw_provider)
        application.skill_resolver = DeterministicSkillResolver(
            (INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL,)
        )
        event = application.submit_incident()

        with self.assertRaises(SkillResolutionError):
            application.analyze(event.event_id)

        self.assertEqual(raw_provider.calls, 0)
        self.assertEqual(
            application.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )

    def test_06_provider_failure_preserves_event_without_decision(
        self,
    ) -> None:
        provider = FailingRestaurantProvider()
        application = self.build_application(raw_provider=provider)
        event = application.submit_incident()

        with self.assertRaises(ProviderTransportError):
            application.analyze(event.event_id)

        self.assertEqual(provider.calls, 2)
        self.assertEqual(
            application.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(
            application.runtime.store.list_decisions(event.event_id),
            [],
        )

    def test_07_invalid_provider_output_creates_no_decision(self) -> None:
        application = self.build_application(
            raw_provider=InvalidRestaurantProvider()
        )
        event = application.submit_incident()

        with self.assertRaises(ModelOutputInvalidError):
            application.analyze(event.event_id)

        self.assertEqual(
            application.runtime.store.list_decisions(event.event_id),
            [],
        )
        self.assertEqual(
            application.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )

    def test_08_human_review_is_required_and_rejection_blocks_task(
        self,
    ) -> None:
        application = self.build_application()
        event = application.submit_incident()
        analysis = application.analyze(event.event_id)

        with self.assertRaises(InvalidStateTransition):
            application.create_approved_task(analysis.decision_id)

        application.submit_human_review(
            analysis.decision_id,
            outcome=HumanReviewOutcome.REJECTED,
            comment="Explicit synthetic rejection.",
        )
        with self.assertRaises(InvalidStateTransition):
            application.submit_human_review(
                analysis.decision_id,
                outcome=HumanReviewOutcome.APPROVED,
                comment="Invalid duplicate review.",
            )
        self.assertEqual(
            application.runtime.store.list_tasks(analysis.decision_id),
            [],
        )
        self.assertEqual(
            application.runtime.store.get_event(event.event_id).status,
            EventStatus.REJECTED,
        )

    def test_09_timeline_is_bounded_and_contains_no_private_payloads(
        self,
    ) -> None:
        application = self.build_application()
        event = application.submit_incident()
        application.analyze(event.event_id)

        rendered = repr(application.timeline(event.event_id))

        self.assertNotIn(str(REPOSITORY_ROOT), rendered)
        self.assertNotIn("analysis_instructions", rendered)
        self.assertNotIn("Synthetic closing reference:", rendered)
        self.assertNotIn("raw model", rendered.casefold())
        self.assertIn("restaurant-aircon-troubleshooting", rendered)
        self.assertIn(
            "synthetic_restaurant_aircon_troubleshooting_reference",
            rendered,
        )
        self.assertIn("VALID", rendered)

    def test_10_fake_mode_is_offline_and_repeat_runs_are_isolated(
        self,
    ) -> None:
        first = self.build_application()
        second = self.build_application()
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("network access is forbidden"),
        ):
            first_event = first.submit_incident()
            first_analysis = first.analyze(first_event.event_id)
            second_event = second.submit_incident()
            second_analysis = second.analyze(second_event.event_id)

        self.assertNotEqual(first_event.event_id, second_event.event_id)
        self.assertNotEqual(
            first_analysis.decision_id,
            second_analysis.decision_id,
        )
        self.assertEqual(
            len(second.runtime.store.list_events()),
            2,
        )

    def test_11_fake_cli_requires_explicit_actions_and_closes(self) -> None:
        args = build_parser().parse_args(
            [
                "--db",
                str(self.database),
                "restaurant-aircon",
                "--provider",
                "fake",
            ]
        )
        output = io.StringIO()
        with (
            patch("builtins.input", side_effect=["approve", "yes", "yes"]),
            redirect_stdout(output),
        ):
            result = run_restaurant_aircon_demo(args)

        self.assertEqual(result, 0)
        self.assertIn("restaurant-aircon-troubleshooting@1.0-demo", output.getvalue())
        self.assertIn("[FINAL               ] CLOSED", output.getvalue())

    def test_12_cli_default_cancel_keeps_human_review_pending(
        self,
    ) -> None:
        args = build_parser().parse_args(
            [
                "--db",
                str(self.database),
                "restaurant-aircon",
                "--provider",
                "fake",
            ]
        )
        output = io.StringIO()
        with (
            patch("builtins.input", return_value=""),
            redirect_stdout(output),
        ):
            result = run_restaurant_aircon_demo(args)

        application = self.build_application()
        events = application.runtime.store.list_events()
        decisions = application.runtime.store.list_decisions(
            events[0].event_id
        )
        self.assertEqual(result, 0)
        self.assertEqual(
            events[0].status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertEqual(
            application.runtime.store.list_tasks(
                decisions[0].decision_id
            ),
            [],
        )
        self.assertIn("cancelled; no task created", output.getvalue())

    def test_13_ollama_unavailable_is_controlled_without_traceback(
        self,
    ) -> None:
        args = build_parser().parse_args(
            [
                "--db",
                str(self.database),
                "restaurant-aircon",
                "--provider",
                "ollama",
                "--model",
                "synthetic-model",
                "--base-url",
                "http://127.0.0.1:9",
                "--connect-timeout",
                "0.1",
                "--total-timeout",
                "1",
                "--max-retry",
                "0",
            ]
        )
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = run_restaurant_aircon_demo(args)

        self.assertEqual(result, 1)
        self.assertIn("Golden-path demo failed", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())
        self.assertEqual(len(
            build_restaurant_aircon_golden_path(
                self.database
            ).runtime.store.list_events()
        ), 1)


if __name__ == "__main__":
    unittest.main()
