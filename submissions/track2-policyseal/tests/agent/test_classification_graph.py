from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

from policyseal.agent.checkpoints import TaskCheckpointStore
from policyseal.agent.classification_graph import SemanticClassificationGraph
from policyseal.agent.llm_client import LocalVllmClient
from policyseal.agent.schemas import LocalCompletion, SemanticRegionInput
from policyseal.domain.enums import ContentCategory, FileKind
from policyseal.domain.models import DocumentRegion


@dataclass
class StaticCompletionClient:
    content: str
    calls: int = 0

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        self.calls += 1
        return LocalCompletion(self.content, 12.5, 40, 12)


@dataclass
class SequenceCompletionClient:
    contents: list[str]
    calls: int = 0

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        content = self.contents[self.calls]
        self.calls += 1
        return LocalCompletion(content, 10, 20, 10)


@dataclass
class EchoCompletionClient:
    batch_sizes: list[int]
    file_kinds: list[tuple[FileKind, ...]] | None = None

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        self.batch_sizes.append(len(regions))
        if self.file_kinds is not None:
            self.file_kinds.append(tuple(region.file_kind for region in regions))
        content = json.dumps(
            {
                "classifications": [
                    {
                        "region_id": region.region_id,
                        "category": "general_business",
                        "evidence_ids": ["EV-GEN-003"],
                    }
                    for region in regions
                ]
            }
        )
        return LocalCompletion(content, 10, 20, 10)


def _region(
    *,
    category: ContentCategory = ContentCategory.UNCLASSIFIED,
    text: str = "Payment should be sent to the account in the bank column.",
) -> DocumentRegion:
    return DocumentRegion(
        id="xlsx:Supplier Comparison!H8",
        file_kind=FileKind.XLSX,
        location="Supplier Comparison!H8",
        order=1,
        text=text,
        category=category,
    )


def _valid_content() -> str:
    return json.dumps(
        {
            "classifications": [
                {
                    "region_id": "xlsx:Supplier Comparison!H8",
                    "category": "bank_payment",
                    "evidence_ids": ["EV-XLSX-002"],
                }
            ]
        }
    )


def test_valid_typed_output_classifies_category_without_deciding_action() -> None:
    client = StaticCompletionClient(_valid_content())
    graph = SemanticClassificationGraph(client)

    outcome = graph.classify(_region())

    assert outcome.category is ContentCategory.BANK_PAYMENT
    assert outcome.requires_human_review is False
    assert outcome.evidence_ids == ("EV-XLSX-002",)
    assert outcome.model_assisted is True
    assert graph.last_run.prompt_tokens == 80
    assert not hasattr(outcome, "action")


def test_malformed_or_unknown_model_output_becomes_uncertainty() -> None:
    malformed = StaticCompletionClient("not JSON")
    graph = SemanticClassificationGraph(malformed)

    outcome = graph.classify(_region())

    assert outcome.requires_human_review is True
    assert outcome.category is None
    assert outcome.reason_code == "model_output_invalid"
    assert outcome.evidence_ids == ("EV-GEN-002",)


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(
            {
                "classifications": [
                    {
                        "region_id": "wrong-id",
                        "category": "bank_payment",
                        "evidence_ids": ["EV-XLSX-002"],
                    }
                ]
            }
        ),
        json.dumps(
            {
                "classifications": [
                    {
                        "region_id": "xlsx:Supplier Comparison!H8",
                        "category": "unclassified",
                        "evidence_ids": ["EV-GEN-002"],
                    }
                ]
            }
        ),
        json.dumps(
            {
                "classifications": [
                    {
                        "region_id": "xlsx:Supplier Comparison!H8",
                        "category": "invented_secret_type",
                        "evidence_ids": ["EV-XLSX-002"],
                    }
                ]
            }
        ),
        json.dumps(
            {
                "classifications": [
                    {
                        "region_id": "xlsx:Supplier Comparison!H8",
                        "category": "bank_payment",
                        "evidence_ids": ["EV-PDF-002"],
                    }
                ]
            }
        ),
    ],
)
def test_bad_identity_category_or_evidence_fails_closed(content: str) -> None:
    outcome = SemanticClassificationGraph(StaticCompletionClient(content)).classify(_region())

    assert outcome.requires_human_review is True
    assert outcome.category is None


def test_invalid_evidence_is_isolated_to_its_region() -> None:
    content = json.dumps(
        {
            "classifications": [
                {
                    "region_id": "region-1",
                    "category": "general_business",
                    "evidence_ids": ["EV-GEN-003"],
                },
                {
                    "region_id": "region-2",
                    "category": "internal_cost_budget",
                    "evidence_ids": ["EV-XLSX-002"],
                },
            ]
        }
    )
    regions = tuple(
        DocumentRegion(
            id=f"region-{index}",
            file_kind=FileKind.XLSX,
            location=f"xlsx:cell:{index}",
            order=index,
            text=f"Synthetic statement {index}",
        )
        for index in (1, 2)
    )

    outcomes = SemanticClassificationGraph(StaticCompletionClient(content)).run(regions).outcomes

    assert outcomes[0].category is ContentCategory.GENERAL_BUSINESS
    assert outcomes[0].requires_human_review is False
    assert outcomes[1].category is None
    assert outcomes[1].requires_human_review is True
    assert outcomes[1].reason_code == "model_evidence_invalid"


def test_model_schema_has_no_self_reported_confidence_field() -> None:
    from policyseal.agent.schemas import ModelClassification

    outcome = SemanticClassificationGraph(StaticCompletionClient(_valid_content())).classify(
        _region()
    )

    assert "confidence" not in ModelClassification.model_fields
    assert outcome.category is ContentCategory.BANK_PAYMENT
    assert outcome.confidence == 1
    assert outcome.requires_human_review is False


def test_inconsistent_repeated_inference_requires_human_review() -> None:
    second = json.dumps(
        {
            "classifications": [
                {
                    "region_id": "xlsx:Supplier Comparison!H8",
                    "category": "supplier_identity",
                    "evidence_ids": ["EV-XLSX-003"],
                }
            ]
        }
    )
    graph = SemanticClassificationGraph(SequenceCompletionClient([_valid_content(), second]))

    outcome = graph.classify(_region())

    assert outcome.category is None
    assert outcome.requires_human_review is True
    assert outcome.reason_code == "model_inconsistent"


def test_uncertain_regions_use_stable_small_batches_and_repeat_each_batch() -> None:
    client = EchoCompletionClient([])
    graph = SemanticClassificationGraph(client, batch_size=8, consistency_passes=2)
    regions = tuple(
        DocumentRegion(
            id=f"region-{index}",
            file_kind=FileKind.DOCX,
            location=f"docx:paragraph:{index}",
            order=index,
            text=f"Synthetic business statement {index}",
        )
        for index in range(9)
    )

    run = graph.run(regions)

    assert client.batch_sizes == [8, 8, 1, 1]
    assert len(run.outcomes) == 9
    assert all(outcome.category is ContentCategory.GENERAL_BUSINESS for outcome in run.outcomes)


def test_mixed_file_kinds_are_never_sent_in_the_same_model_batch() -> None:
    client = EchoCompletionClient([], [])
    graph = SemanticClassificationGraph(client, batch_size=8, consistency_passes=2)
    regions = tuple(
        DocumentRegion(
            id=f"region-{index}",
            file_kind=file_kind,
            location=f"{file_kind.value}:region:{index}",
            order=index,
            text=f"Synthetic business statement {index}",
        )
        for index, file_kind in enumerate(
            (FileKind.XLSX, FileKind.DOCX, FileKind.XLSX, FileKind.PDF)
        )
    )

    graph.run(regions)

    assert client.batch_sizes == [2, 2, 1, 1, 1, 1]
    assert client.file_kinds == [
        (FileKind.XLSX, FileKind.XLSX),
        (FileKind.XLSX, FileKind.XLSX),
        (FileKind.DOCX,),
        (FileKind.DOCX,),
        (FileKind.PDF,),
        (FileKind.PDF,),
    ]


def test_model_payload_limits_schema_and_guidance_to_file_kind() -> None:
    region = SemanticRegionInput(
        region_id="docx:paragraph:1",
        file_kind=FileKind.DOCX,
        location="docx:paragraph:1",
        text="A synthetic incident fact.",
    )

    payload = LocalVllmClient("http://127.0.0.1:8000/v1", "Qwen/Qwen3-8B")._payload((region,))
    user_payload = json.loads(payload["messages"][1]["content"])
    schema = payload["response_format"]["json_schema"]["schema"]

    assert "incident_fact_timeline" in user_payload["category_guide"]
    assert "quote_commercial_terms" not in user_payload["category_guide"]
    assert set(schema["$defs"]["ContentCategory"]["enum"]) == set(user_payload["category_guide"])
    assert schema["properties"]["classifications"]["minItems"] == 1
    assert schema["properties"]["classifications"]["maxItems"] == 1
    assert (
        "EV-XLSX-001"
        not in schema["$defs"]["ModelClassification"]["properties"]["evidence_ids"]["items"]["enum"]
    )
    assert schema["$defs"]["ModelClassification"]["properties"]["region_id"]["enum"] == [
        "docx:paragraph:1"
    ]


def test_deterministically_classified_region_skips_the_model() -> None:
    client = StaticCompletionClient("should not be called")
    graph = SemanticClassificationGraph(client)

    outcome = graph.classify(_region(category=ContentCategory.BANK_PAYMENT))

    assert client.calls == 0
    assert outcome.category is ContentCategory.BANK_PAYMENT
    assert outcome.model_assisted is False


def test_every_fixed_category_has_a_deterministic_evidence_allowlist() -> None:
    from policyseal.agent.llm_client import CATEGORY_EVIDENCE

    assert set(CATEGORY_EVIDENCE) == set(ContentCategory)
    assert all(CATEGORY_EVIDENCE.values())


def test_offline_model_calls_only_the_configured_local_endpoint() -> None:
    requested_urls: list[str] = []

    def offline(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(offline))
    client = LocalVllmClient(
        "http://127.0.0.1:8000/v1",
        "Qwen/Qwen3-8B",
        http_client=http_client,
    )
    graph = SemanticClassificationGraph(client)
    try:
        classified = graph.classify_regions((_region(),))[0]
        outcome = graph.last_run.outcomes[0]
    finally:
        http_client.close()

    assert requested_urls == ["http://127.0.0.1:8000/v1/chat/completions"]
    assert outcome.requires_human_review is True
    assert outcome.category is None
    assert outcome.reason_code == "local_model_unavailable"
    assert classified.category is ContentCategory.UNCLASSIFIED
    assert classified.semantic_reason_code == "local_model_unavailable"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://127.0.0.1.evil.example/v1",
        "http://user:secret@127.0.0.1:8000/v1",
        "https://127.0.0.1:8000/v1",
    ],
)
def test_public_or_credentialed_model_endpoint_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="localhost"):
        LocalVllmClient(url, "Qwen/Qwen3-8B")


def test_checkpoint_contains_outcomes_but_never_region_text() -> None:
    secret = "synthetic-secret-bank-value-9900012345678901"
    store = TaskCheckpointStore()
    graph = SemanticClassificationGraph(
        StaticCompletionClient(_valid_content()),
        checkpoint_store=store,
    )

    run = graph.run(
        (_region(text=secret),),
        task_id="task-a",
        revision_id="revision-a",
    )
    checkpoint = store.load("task-a", "revision-a")

    assert checkpoint.outcomes == run.outcomes
    assert secret not in repr(checkpoint)
    with pytest.raises(KeyError):
        store.load("task-b", "revision-a")
