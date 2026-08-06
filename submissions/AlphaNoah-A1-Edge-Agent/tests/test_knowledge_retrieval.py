"""Task 04.5B-2 deterministic knowledge retrieval evaluation tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.knowledge import (  # noqa: E402
    ContextBuilder,
    DeterministicKnowledgeRetriever,
    JsonKnowledgeRepository,
    KnowledgeContext,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeMatch,
    KnowledgeQuery,
)
from alphanoah_a1.models import Event  # noqa: E402

EVALUATION_PATH = (
    REPOSITORY_ROOT / "examples" / "knowledge_retrieval_evaluation.json"
)


def load_evaluation() -> dict[str, Any]:
    payload = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "knowledge-retrieval-evaluation-v1":
        raise AssertionError("unexpected retrieval evaluation schema")
    return payload


def build_repository(
    directory: Path,
    *,
    reverse_documents: bool = False,
) -> JsonKnowledgeRepository:
    payload = load_evaluation()
    documents = list(payload["documents"])
    if reverse_documents:
        documents.reverse()
    repository = JsonKnowledgeRepository(directory / "knowledge.json")
    for raw_document in documents:
        repository.add_document(KnowledgeDocument.from_dict(raw_document))
    return repository


def retrieve_case(
    repository: JsonKnowledgeRepository,
    case: dict[str, Any],
) -> list[str]:
    query = case["query"]
    return [
        match.document.id
        for match in DeterministicKnowledgeRetriever(repository).retrieve(
            KnowledgeQuery(
                event_type=query.get("event_type", ""),
                asset_id=query.get("asset_id", ""),
                asset_type=query.get("asset_type", ""),
                location=query.get("location", ""),
                keywords=tuple(query.get("keywords", [])),
                limit=case["top_k"],
            )
        )
    ]


def hit_at_k(case: dict[str, Any], document_ids: list[str]) -> bool:
    return set(case["expected_document_ids"]).issubset(document_ids)


def forbidden_hits(
    case: dict[str, Any],
    document_ids: list[str],
) -> set[str]:
    return set(case["forbidden_document_ids"]).intersection(document_ids)


class KnowledgeRetrievalEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.repository = build_repository(self.root)
        self.cases = {
            case["case_id"]: case for case in load_evaluation()["cases"]
        }

    def test_01_evaluation_dataset_covers_required_cases(self) -> None:
        required_case_ids = {
            "exact-structured-field-hit",
            "keyword-only-hit",
            "field-and-keyword-joint-hit",
            "no-related-knowledge",
            "similar-keyword-wrong-equipment",
            "similar-scene-wrong-event-type",
            "stable-tie-order",
            "repository-order-invariant",
            "repeatable-conveyor-result",
            "top-k-one",
        }

        self.assertEqual(set(self.cases), required_case_ids)
        for case in self.cases.values():
            self.assertTrue(case["description"])
            self.assertGreater(case["top_k"], 0)
            self.assertIsInstance(case["expected_document_ids"], list)
            self.assertIsInstance(case["forbidden_document_ids"], list)

    def test_02_all_cases_meet_hit_at_k_and_forbidden_hit_checks(self) -> None:
        for case_id, case in self.cases.items():
            with self.subTest(case_id=case_id):
                document_ids = retrieve_case(self.repository, case)
                self.assertTrue(hit_at_k(case, document_ids))
                self.assertEqual(forbidden_hits(case, document_ids), set())

    def test_03_equal_scores_have_stable_document_id_order(self) -> None:
        case = self.cases["stable-tie-order"]

        self.assertEqual(
            retrieve_case(self.repository, case),
            case["expected_document_ids"],
        )

    def test_04_repository_input_order_does_not_change_results(self) -> None:
        case = self.cases["repository-order-invariant"]
        reverse_repository = build_repository(
            self.root / "reversed",
            reverse_documents=True,
        )

        self.assertEqual(
            retrieve_case(self.repository, case),
            retrieve_case(reverse_repository, case),
        )

    def test_05_repeated_retrieval_is_identical(self) -> None:
        case = self.cases["repeatable-conveyor-result"]
        first = retrieve_case(self.repository, case)

        self.assertEqual(retrieve_case(self.repository, case), first)
        self.assertEqual(retrieve_case(self.repository, case), first)

    def test_06_top_k_is_applied_after_stable_ranking(self) -> None:
        case = self.cases["top-k-one"]

        self.assertEqual(
            retrieve_case(self.repository, case),
            ["synthetic_equipment_inspection_a_v1"],
        )

    def test_07_structured_conflicts_are_hard_filtered(self) -> None:
        wrong_equipment = self.cases["similar-keyword-wrong-equipment"]
        wrong_equipment["top_k"] = 10
        wrong_event = self.cases["similar-scene-wrong-event-type"]
        wrong_event["top_k"] = 10

        self.assertNotIn(
            "synthetic_ventilation_shutdown_sop_v1",
            retrieve_case(self.repository, wrong_equipment),
        )
        self.assertNotIn(
            "synthetic_aircon_energy_rule_v1",
            retrieve_case(self.repository, wrong_event),
        )

    def test_08_missing_optional_fields_are_supported(self) -> None:
        matches = self.repository.search_query(
            KnowledgeQuery(keywords=("pump_leak",), limit=2)
        )

        self.assertEqual(
            [match.id for match in matches],
            ["synthetic_pump_leak_sop_v1"],
        )

    def test_09_legacy_search_call_remains_compatible(self) -> None:
        matches = self.repository.search(
            event_type="equipment_issue_report",
            asset_type="conveyor",
            keywords=["abnormal_sound"],
            limit=1,
        )

        self.assertEqual(
            [match.id for match in matches],
            ["synthetic_conveyor_sound_sop_v1"],
        )

    def test_10_deprecated_version_is_excluded_in_favor_of_active(self) -> None:
        active = KnowledgeDocument(
            id="synthetic_revision_active",
            title="Synthetic active revision",
            content="Synthetic revision_term active content.",
            document_type="RULE",
            source="synthetic_revision_source",
            version="current-label",
            effective_date="2026-07-26",
            knowledge_key="synthetic_revision_family",
            status=KnowledgeDocumentStatus.ACTIVE,
            metadata={"keywords": ["revision_term"]},
        )
        deprecated = KnowledgeDocument(
            id="synthetic_revision_deprecated",
            title="Synthetic deprecated revision",
            content="Synthetic revision_term deprecated content.",
            document_type="RULE",
            source="synthetic_revision_source",
            version="older-unparsed-label",
            effective_date="2026-07-25",
            knowledge_key="synthetic_revision_family",
            status=KnowledgeDocumentStatus.DEPRECATED,
            metadata={"keywords": ["revision_term"]},
        )
        repository = JsonKnowledgeRepository(
            self.root / "versioned" / "knowledge.json"
        )
        repository.add_document(deprecated)
        repository.add_document(active)

        matches = repository.search_query(
            KnowledgeQuery(keywords=("revision_term",), limit=5)
        )

        self.assertEqual([match.id for match in matches], [active.id])

    def test_11_multiple_active_versions_fail_without_guessing(self) -> None:
        first = KnowledgeDocument(
            id="synthetic_conflict_one",
            title="Synthetic conflicting revision one",
            content="Synthetic conflict content one.",
            document_type="RULE",
            source="synthetic_conflict_source",
            version="release-blue",
            effective_date="2026-07-26",
            knowledge_key="synthetic_conflict_family",
        )
        second = KnowledgeDocument(
            id="synthetic_conflict_two",
            title="Synthetic conflicting revision two",
            content="Synthetic conflict content two.",
            document_type="RULE",
            source="synthetic_conflict_source",
            version="release-green",
            effective_date="2026-07-26",
            knowledge_key="synthetic_conflict_family",
        )
        repository = JsonKnowledgeRepository(
            self.root / "conflict" / "knowledge.json"
        )
        repository.add_document(first)

        with self.assertRaisesRegex(
            ValueError,
            "multiple active documents for knowledge_key",
        ):
            repository.add_document(second)
        self.assertEqual(
            [document.id for document in repository.list_documents()],
            [first.id],
        )

    def test_12_legacy_document_defaults_to_active_unique_family(self) -> None:
        raw_document = dict(load_evaluation()["documents"][0])
        raw_document.pop("knowledge_key", None)
        raw_document.pop("status", None)

        document = KnowledgeDocument.from_dict(raw_document)

        self.assertEqual(document.knowledge_key, document.id)
        self.assertIs(document.status, KnowledgeDocumentStatus.ACTIVE)

    def test_13_matches_explain_score_fields_and_keywords(self) -> None:
        matches = DeterministicKnowledgeRetriever(self.repository).retrieve(
            KnowledgeQuery(
                event_type="equipment_issue_report",
                asset_type="conveyor",
                keywords=("abnormal_sound",),
                limit=1,
            )
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].document.id, "synthetic_conveyor_sound_sop_v1")
        self.assertGreater(matches[0].score, 0)
        self.assertEqual(
            matches[0].matched_fields,
            ("event_type", "asset_type"),
        )
        self.assertEqual(matches[0].matched_keywords, ("abnormal_sound",))

    def test_14_context_builder_accepts_stub_retriever(self) -> None:
        document = KnowledgeDocument.from_dict(
            load_evaluation()["documents"][0]
        )

        class StubRetriever:
            def __init__(self) -> None:
                self.queries: list[KnowledgeQuery] = []

            def retrieve(
                self,
                query: KnowledgeQuery,
            ) -> list[KnowledgeMatch]:
                self.queries.append(query)
                return [
                    KnowledgeMatch(
                        document=document,
                        score=7,
                        matched_fields=("stub",),
                    )
                ]

        retriever = StubRetriever()
        builder = ContextBuilder(retriever)
        event = Event.from_dict(
            {
                "event_id": "evt_stub_retriever",
                "trace_id": "trace_stub_retriever",
                "event_type": "device_not_shutdown",
                "source": "synthetic_test",
                "timestamp": "2026-07-26T00:00:00+00:00",
                "raw_input_ref": "synthetic://stub-retriever",
                "normalized_input": {},
                "detected_issue": "",
                "confidence": 0.0,
                "severity": "",
                "status": "NEW",
                "location": "Synthetic-Room",
                "asset_id": "AC-001",
                "reporter": "tester",
                "description": "Synthetic air conditioner report.",
            }
        )

        context = builder.build(event)

        self.assertIsInstance(context, KnowledgeContext)
        self.assertEqual([item.id for item in context.documents], [document.id])
        self.assertEqual(len(retriever.queries), 1)
        self.assertEqual(
            retriever.queries[0].event_type,
            "device_not_shutdown",
        )

    def test_15_context_rejects_deprecated_or_conflicting_documents(
        self,
    ) -> None:
        active = KnowledgeDocument(
            id="synthetic_context_active",
            title="Synthetic active context",
            content="Synthetic active context content.",
            document_type="RULE",
            source="synthetic_context_source",
            version="active-label",
            effective_date="2026-07-26",
            knowledge_key="synthetic_context_family",
        )
        deprecated = KnowledgeDocument(
            id="synthetic_context_deprecated",
            title="Synthetic deprecated context",
            content="Synthetic deprecated context content.",
            document_type="RULE",
            source="synthetic_context_source",
            version="deprecated-label",
            effective_date="2026-07-25",
            knowledge_key="synthetic_context_family",
            status=KnowledgeDocumentStatus.DEPRECATED,
        )
        conflicting = KnowledgeDocument(
            id="synthetic_context_conflict",
            title="Synthetic conflicting context",
            content="Synthetic conflicting context content.",
            document_type="RULE",
            source="synthetic_context_source",
            version="conflict-label",
            effective_date="2026-07-26",
            knowledge_key="synthetic_context_family",
        )

        with self.assertRaisesRegex(ValueError, "only active"):
            KnowledgeContext(documents=(deprecated,))
        with self.assertRaisesRegex(ValueError, "multiple active"):
            KnowledgeContext(documents=(active, conflicting))

    def test_16_invalid_retrieval_metadata_is_not_silently_ignored(
        self,
    ) -> None:
        raw_document = dict(load_evaluation()["documents"][0])
        raw_document["metadata"] = {"asset_types": "air_conditioner"}

        with self.assertRaisesRegex(ValueError, "metadata.asset_types"):
            KnowledgeDocument.from_dict(raw_document)

    def test_17_context_builder_enforces_bound_on_custom_retriever(
        self,
    ) -> None:
        document = KnowledgeDocument.from_dict(
            load_evaluation()["documents"][0]
        )

        class UnboundedStubRetriever:
            def retrieve(
                self,
                query: KnowledgeQuery,
            ) -> list[KnowledgeMatch]:
                return [
                    KnowledgeMatch(document=document, score=5),
                    KnowledgeMatch(document=document, score=4),
                    KnowledgeMatch(document=document, score=3),
                ]

        event = Event.from_dict(
            {
                "event_id": "evt_bounded_stub",
                "trace_id": "trace_bounded_stub",
                "event_type": "device_not_shutdown",
                "source": "synthetic_test",
                "timestamp": "2026-07-26T00:00:00+00:00",
                "raw_input_ref": "synthetic://bounded-stub",
                "normalized_input": {},
                "detected_issue": "",
                "confidence": 0.0,
                "severity": "",
                "status": "NEW",
                "description": "Synthetic bounded retrieval report.",
            }
        )

        context = ContextBuilder(
            UnboundedStubRetriever(),
            max_documents=1,
        ).build(event)

        self.assertEqual([item.id for item in context.documents], [document.id])


if __name__ == "__main__":
    unittest.main()
