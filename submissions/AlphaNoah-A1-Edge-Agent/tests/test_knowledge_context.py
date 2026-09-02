"""Task 04.5B-1 knowledge object, context and integration tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.ai_reliability import (  # noqa: E402
    ReliabilityPolicy,
    ReliableAnalysisProvider,
)
from alphanoah_a1.knowledge import (  # noqa: E402
    ContextBuilder,
    JsonKnowledgeRepository,
    KnowledgeContext,
    KnowledgeDocument,
    KnowledgeDocumentType,
)
from alphanoah_a1.models import (  # noqa: E402
    AnalysisResult,
    EventStatus,
    HumanReviewOutcome,
    PostReviewResult,
)
from alphanoah_a1.notifications import NotificationStatus  # noqa: E402
from alphanoah_a1.providers import OllamaAnalysisProvider  # noqa: E402
from alphanoah_a1.responsibility import (  # noqa: E402
    ResponsibilityDirectory,
)
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402


def knowledge_document(
    *,
    document_id: str = "synthetic_packaging_sop_v1",
    event_type: str | None = "equipment_issue_report",
    keyword: str = "abnormal sound",
    asset_id: str | None = "PACK-003",
) -> KnowledgeDocument:
    metadata = {
        "keywords": [keyword],
        "private_note": "must-not-enter-model-prompt",
    }
    if event_type is not None:
        metadata["event_types"] = [event_type]
    if asset_id is not None:
        metadata["asset_ids"] = [asset_id]
    return KnowledgeDocument(
        id=document_id,
        title="Synthetic abnormal-condition reference",
        content=(
            "Preserve the synthetic report and request authorized human "
            f"inspection for {keyword}. This is not a diagnosis."
        ),
        document_type=KnowledgeDocumentType.SOP,
        source="synthetic_reviewed_reference",
        version="1.0-demo",
        effective_date="2026-07-25",
        metadata=metadata,
    )


def analysis_result() -> AnalysisResult:
    return AnalysisResult(
        detected_issue="Preliminary industrial issue",
        decision_type="ai_assisted_incident_analysis",
        reasoning_summary="Possible cause; not a confirmed diagnosis.",
        evidence=["Synthetic operator report"],
        model_or_rule="fake:knowledge-context",
        confidence=0.76,
        requires_human_review=True,
        severity="HIGH",
    )


class ContextAwareFakeProvider:
    provider_id = "fake:knowledge-context"
    model = "fixture-model:v1"
    prompt_version = "fixture-knowledge-prompt-v1"
    model_digest = None

    def __init__(self):
        self.contexts: list[KnowledgeContext] = []

    def analyze(self, event: object) -> AnalysisResult:
        raise AssertionError("context-aware path must be used")

    def analyze_with_context(
        self,
        event: object,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        self.contexts.append(knowledge_context)
        return analysis_result()


class KnowledgeContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.repository_path = root / "knowledge.json"
        self.database_path = root / "runtime.sqlite3"
        self.runtime = AlphaNoahRuntime(str(self.database_path))

    def create_event(
        self,
        *,
        event_type: str = "equipment_issue_report",
        asset_id: str = "PACK-003",
        location: str = "Packaging-Line-A",
        description: str = "Synthetic abnormal sound report.",
    ):
        return self.runtime.create_event(
            source="manual_report",
            actor="test:knowledge-context",
            event_type=event_type,
            asset_id=asset_id,
            location=location,
            description=description,
            metadata={
                "data_classification": "Synthetic demo data",
                "incident_notice": "Not a real production incident",
            },
        )

    @staticmethod
    def reliable(
        raw_provider: ContextAwareFakeProvider,
        builder: ContextBuilder,
    ) -> ReliableAnalysisProvider:
        return ReliableAnalysisProvider(
            raw_provider,
            policy=ReliabilityPolicy(
                timeout_seconds=1.0,
                max_retry=0,
            ),
            context_builder=builder,
        )

    def test_01_knowledge_document_is_saved_and_reloaded(self) -> None:
        original_metadata = {
            "event_types": ["equipment_issue_report"],
            "keywords": ["abnormal sound"],
        }
        document = KnowledgeDocument(
            id="synthetic_document_v1",
            title="Synthetic reference",
            content="Synthetic reviewed content.",
            document_type=KnowledgeDocumentType.OTHER,
            source="synthetic_source",
            version="1.0-demo",
            effective_date="2026-07-25",
            metadata=original_metadata,
        )
        original_metadata["event_types"].append("mutated_after_creation")
        repository = JsonKnowledgeRepository(self.repository_path)
        repository.add_document(document)

        reloaded = JsonKnowledgeRepository(self.repository_path)
        recovered = reloaded.get_document(document.id)

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.to_dict(), document.to_dict())
        self.assertNotIn(
            "mutated_after_creation",
            recovered.metadata["event_types"],
        )
        self.assertEqual(len(reloaded.list_documents()), 1)

    def test_02_repository_keyword_and_field_search_is_deterministic(
        self,
    ) -> None:
        repository = JsonKnowledgeRepository(self.repository_path)
        repository.add_document(knowledge_document())
        repository.add_document(
            knowledge_document(
                document_id="synthetic_unrelated_case",
                event_type="food_safety_observation",
                keyword="cold storage temperature",
                asset_id="COLD-001",
            )
        )

        keyword_matches = repository.search(
            keywords=["abnormal sound"],
        )
        field_matches = repository.search(
            event_type="equipment_issue_report",
            asset_id="PACK-003",
        )

        self.assertEqual(
            [item.id for item in keyword_matches],
            ["synthetic_packaging_sop_v1"],
        )
        self.assertEqual(
            [item.id for item in field_matches],
            ["synthetic_packaging_sop_v1"],
        )

    def test_03_context_builder_selects_matching_industrial_knowledge(
        self,
    ) -> None:
        repository = JsonKnowledgeRepository(self.repository_path)
        repository.add_document(
            knowledge_document(
                event_type=None,
                asset_id=None,
                keyword="异常声音",
            )
        )
        builder = ContextBuilder(repository)

        context = builder.build(
            self.create_event(
                event_type="unmapped_incident",
                asset_id="UNKNOWN-ASSET",
                location="Unknown-Line",
                description="设备出现异常声音",
            )
        )

        self.assertEqual(len(context.documents), 1)
        self.assertEqual(
            context.documents[0].id,
            "synthetic_packaging_sop_v1",
        )
        self.assertEqual(
            context.audit_metadata(),
            {
                "knowledge_sources": [
                    "synthetic_reviewed_reference@1.0-demo"
                ],
                "knowledge_version": "knowledge-context-v1",
                "context_count": 1,
                "knowledge_statuses": [
                    "synthetic_packaging_sop_v1:active"
                ],
            },
        )

    def test_04_no_match_still_completes_guarded_analysis(self) -> None:
        repository = JsonKnowledgeRepository(self.repository_path)
        repository.add_document(
            knowledge_document(
                document_id="synthetic_food_only",
                event_type="food_safety_observation",
                keyword="cold storage temperature",
            )
        )
        raw_provider = ContextAwareFakeProvider()
        event = self.create_event(
            asset_id="UNKNOWN-ASSET",
            location="Unknown-Line",
            description="Synthetic unrelated signal.",
        )

        decision, _ = self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=self.reliable(
                raw_provider,
                ContextBuilder(repository),
            ),
        )

        self.assertTrue(decision.requires_human_review)
        self.assertEqual(len(raw_provider.contexts), 1)
        self.assertEqual(raw_provider.contexts[0].documents, ())
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        model_metadata = decision_audit.details["model_metadata"]
        self.assertEqual(model_metadata["context_count"], 0)
        self.assertEqual(model_metadata["knowledge_sources"], [])
        self.assertEqual(
            model_metadata["knowledge_version"],
            "knowledge-context-v1",
        )
        self.assertEqual(model_metadata["knowledge_statuses"], [])

    def test_05_ollama_prompt_receives_bounded_context_not_metadata(
        self,
    ) -> None:
        document = knowledge_document()
        context = KnowledgeContext(documents=(document,))
        event = self.create_event()
        provider = OllamaAnalysisProvider(
            base_url="http://127.0.0.1:11434",
            model="fixture-model:v1",
        )

        request_payload = json.loads(
            provider._build_request(event, context).decode("utf-8")
        )
        prompt = request_payload["prompt"]

        self.assertIn(document.content, prompt)
        self.assertIn(document.source, prompt)
        self.assertIn(document.version, prompt)
        self.assertNotIn("must-not-enter-model-prompt", prompt)
        self.assertNotIn("private_note", prompt)

    def test_06_task04_closed_loop_remains_unchanged(self) -> None:
        repository = JsonKnowledgeRepository(self.repository_path)
        repository.add_document(
            knowledge_document(
                document_id="synthetic_food_context",
                event_type="food_safety_observation",
                keyword="temperature observation",
                asset_id="COLD-001",
            )
        )
        raw_provider = ContextAwareFakeProvider()
        event = self.create_event(
            event_type="food_safety_observation",
            asset_id="COLD-001",
            location="Cold-Storage-A",
            description="Synthetic temperature observation.",
        )
        decision, _ = self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=self.reliable(
                raw_provider,
                ContextBuilder(repository),
            ),
        )
        notification = self.runtime.create_notification_for_decision(
            decision.decision_id,
            directory=ResponsibilityDirectory(),
        )
        self.runtime.submit_human_review(
            decision.decision_id,
            reviewer="human:knowledge-reviewer",
            outcome=HumanReviewOutcome.APPROVED,
            comment="Synthetic approval for regression testing.",
        )
        task = self.runtime.create_task(
            decision.decision_id,
            actor="human:knowledge-reviewer",
            deadline="2099-01-01T00:00:00+00:00",
        )
        self.runtime.start_task(task.task_id, actor=task.assignee)
        evidence = self.runtime.submit_evidence(
            task.task_id,
            evidence_type="synthetic_structured_record",
            file_or_data_ref="synthetic://knowledge-regression/evidence",
            submitted_by=task.assignee,
            description="Synthetic follow-up evidence.",
            idempotency_key="knowledge-regression-evidence-1",
        )
        self.runtime.begin_review(
            task.task_id,
            actor="rule:synthetic-knowledge-review-v1",
        )
        review = self.runtime.review_task(
            task.task_id,
            reviewer_or_model="rule:synthetic-knowledge-review-v1",
            result=PostReviewResult.PASSED,
            comment="Synthetic evidence accepted.",
        )

        self.assertEqual(notification.status, NotificationStatus.CREATED)
        self.assertEqual(notification.recipient_id, "UNASSIGNED")
        self.assertTrue(review.closed)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.CLOSED,
        )
        snapshot = self.runtime.snapshot(event.event_id)
        self.assertEqual(len(snapshot["notifications"]), 1)
        self.assertEqual(len(snapshot["human_reviews"]), 1)
        self.assertEqual(len(snapshot["tasks"]), 1)
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertEqual(
            snapshot["evidence"][0]["evidence_id"],
            evidence.evidence_id,
        )
        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        self.assertEqual(
            decision_audit.details["model_metadata"]["context_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
