import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModelClient
from xianglens.agent.graph import GraphServices, build_graph
from xianglens.config import PROJECT_ROOT
from xianglens.storage.knowledge_store import (
    HashingEmbedder,
    InMemoryKnowledgeStore,
    load_knowledge_records,
)
from xianglens.storage.sqlite_store import SQLiteStore
from xianglens.tools.image_tools import ImageInspector


class MissingComparisonRationaleModel(FakeModelClient):
    def __init__(self) -> None:
        self.comparison_calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        if "CandidateComparison" in str(messages[0]["content"]):
            self.comparison_calls += 1
            context = json.loads(str(messages[1]["content"]))
            return json.dumps(
                {
                    "recommended_image_id": context["image_ids"][0],
                    "candidates": [
                        {
                            "image_id": image_id,
                            "crop_resilience": 4,
                            "small_size_clarity": 4,
                            "privacy_safety": 5,
                            "intent_alignment": 4,
                            "contextual_ambiguity": 2,
                        }
                        for image_id in context["image_ids"]
                    ],
                    "decision_rule": "Privacy overrides the aggregate score.",
                    "caveat": "The model omitted candidate rationale text.",
                }
            )
        return await super().chat(messages, temperature=temperature, max_tokens=max_tokens)


@pytest.mark.asyncio
async def test_graph_runs_all_core_capabilities(tmp_path: Path) -> None:
    database = SQLiteStore(tmp_path / "state.sqlite3")
    database.initialize()
    source_thread = database.create_thread("ada")
    proposal = database.create_memory_proposal(
        thread_id=source_thread["id"],
        user_id="ada",
        text="Red is an intentional brand color.",
        memory_type="preference",
    )
    database.decide_consent(proposal["id"], "approve")
    thread = database.create_thread("ada")
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    graph = build_graph(
        GraphServices(
            model=FakeModelClient(),
            knowledge=InMemoryKnowledgeStore(records, HashingEmbedder()),
            database=database,
            image_inspector=ImageInspector(20_000_000, 30_000_000),
        )
    )
    image = next((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))
    result = await graph.ainvoke(
        {
            "run_id": "test-run",
            "thread_id": thread["id"],
            "user_id": "ada",
            "message": "Review this image for a GitHub profile.",
            "platform": "GitHub",
            "audience": "international open-source collaborators",
            "intent_keywords": ["credible", "approachable"],
            "enabled_packs": ["profile_basics", "global_professional_context"],
            "image_paths": [image],
            "tool_trace": [],
        }
    )
    assert result["report_markdown"].startswith("# XiangLens Review")
    assert result["evidence"]
    assert [item["text"] for item in result["recalled_memories"]] == [
        "Red is an intentional brand color."
    ]
    assert [item["node"] for item in result["tool_trace"]] == [
        "intake",
        "policy_gate",
        "recall_context",
        "inspect_local",
        "observe_visual",
        "run_private_lens",
        "retrieve_evidence",
        "compare_candidates",
        "propose_memory",
        "synthesize_report",
    ]


@pytest.mark.asyncio
async def test_policy_gate_blocks_sensitive_inference_without_calling_model(
    tmp_path: Path,
) -> None:
    database = SQLiteStore(tmp_path / "state.sqlite3")
    database.initialize()
    thread = database.create_thread("ada")
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    graph = build_graph(
        GraphServices(
            model=FakeModelClient(),
            knowledge=InMemoryKnowledgeStore(records, HashingEmbedder()),
            database=database,
            image_inspector=ImageInspector(20_000_000, 30_000_000),
        )
    )
    image = next((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))
    result = await graph.ainvoke(
        {
            "thread_id": thread["id"],
            "user_id": "ada",
            "message": "Infer their personality from this avatar.",
            "platform": "general",
            "audience": "general",
            "intent_keywords": [],
            "enabled_packs": ["profile_basics"],
            "image_paths": [image],
            "tool_trace": [],
        }
    )
    assert result["blocked_reason"]
    assert result["visual_observations"] == []
    assert result["tool_trace"][-1]["node"] == "policy_gate"


@pytest.mark.asyncio
async def test_graph_compares_multiple_images_and_proposes_memory(tmp_path: Path) -> None:
    database = SQLiteStore(tmp_path / "state.sqlite3")
    database.initialize()
    thread = database.create_thread("ada")
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    graph = build_graph(
        GraphServices(
            model=FakeModelClient(),
            knowledge=InMemoryKnowledgeStore(records, HashingEmbedder()),
            database=database,
            image_inspector=ImageInspector(20_000_000, 30_000_000),
        )
    )
    images = list((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))[:2]
    result = await graph.ainvoke(
        {
            "thread_id": thread["id"],
            "user_id": "ada",
            "message": "Remember that red is an intentional part of my brand identity.",
            "platform": "GitHub",
            "audience": "international collaborators",
            "intent_keywords": ["distinctive"],
            "enabled_packs": ["profile_basics", "privacy_safety"],
            "image_paths": images,
            "tool_trace": [],
        }
    )
    assert result["comparison"]["recommended_image_id"] == images[0].stem
    assert len(result["comparison"]["candidates"]) == 2
    assert result["memory_proposal_draft"]["text"] == ("Red is an intentional brand color.")
    assert database.list_memories("ada") == []
    assert "Pending approval" in result["report_markdown"]


@pytest.mark.asyncio
async def test_comparison_fills_rationales_after_model_repair_omits_them(
    tmp_path: Path,
) -> None:
    database = SQLiteStore(tmp_path / "state.sqlite3")
    database.initialize()
    thread = database.create_thread("ada")
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    model = MissingComparisonRationaleModel()
    graph = build_graph(
        GraphServices(
            model=model,
            knowledge=InMemoryKnowledgeStore(records, HashingEmbedder()),
            database=database,
            image_inspector=ImageInspector(20_000_000, 30_000_000),
        )
    )
    images = list((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))[:2]

    result = await graph.ainvoke(
        {
            "thread_id": thread["id"],
            "user_id": "ada",
            "message": "Compare these images for a GitHub profile.",
            "platform": "GitHub",
            "audience": "international collaborators",
            "intent_keywords": ["credible"],
            "enabled_packs": ["profile_basics", "privacy_safety"],
            "image_paths": images,
            "tool_trace": [],
        }
    )

    assert model.comparison_calls == 2
    assert all(
        candidate["rationale"].startswith(
            "Code-generated summary of the model's returned rubric scores:"
        )
        for candidate in result["comparison"]["candidates"]
    )
    assert "## Comparison" in result["report_markdown"]
