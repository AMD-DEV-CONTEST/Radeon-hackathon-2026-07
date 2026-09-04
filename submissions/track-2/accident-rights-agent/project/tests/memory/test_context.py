from __future__ import annotations

from app.memory.context_builder import ContextBuilder
from app.memory.service import bootstrap_case_memory


def test_context_builder_selects_task_context_and_keeps_protected_values(
    demo_case, legal_retriever
):
    workspace, case_id = demo_case
    memory, capsule = bootstrap_case_memory(workspace, case_id)
    base_facts = workspace.store(case_id).list_facts(case_id)
    facts = base_facts + [
        {
            "fact_id": f"FACT-LONG-{index:03d}",
            "statement": "与当前任务无关的冗长历史记录" * 20,
            "source_node_ids": ["NODE-TEST-001"],
        }
        for index in range(30)
    ]
    citations = legal_retriever.citations("事故认定复核期限", top_k=10)
    bundle = ContextBuilder(memory).build(
        task="复核期限与证据",
        capsule=capsule,
        facts=facts,
        citations=citations,
        top_k_facts=5,
        top_k_citations=4,
        node_name="context_test",
    )
    assert len(bundle.facts) == 5
    assert len(bundle.citations) == 4
    assert bundle.after_token_count < bundle.before_token_count
    assert bundle.protected_fields
    assert bundle.protected_field_retention == 1.0
    assert bundle.prompt_payload()["protected_values"]
