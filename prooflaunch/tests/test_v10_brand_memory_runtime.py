from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.v10_brand_memory import (
    BrandGenomeMemory,
    EdgeKind,
    EntityKind,
    MemoryEdge,
    MemoryAtom,
    MemoryKind,
    MemorySource,
    PolicyVerdict,
    PrivacyClass,
)
from prooflaunch_remix.v10_brand_memory_benchmark import (
    build_memory_card,
    build_memory_benchmark_fixture,
    run_memory_only_benchmark,
    run_streaming_benchmark,
)
from prooflaunch_remix.v10_brand_memory_retrieval import (
    BrandMemoryRetriever,
    DenseEmbeddingIndex,
    HybridFusionConfig,
    RetrievalMode,
)
from prooflaunch_remix.v10_contracts import V10ContractError, stable_digest


NOW = "2026-07-31T12:00:00+00:00"
LATER = "2026-08-01T12:00:00+00:00"


def source(*, revision: str = "seed-v1") -> MemorySource:
    return MemorySource(
        locator="project://brand-memory-runtime/fixture",
        revision=revision,
        sha256=stable_digest({"fixture": "runtime", "revision": revision}),
        rights_profile="project_owned_synthetic",
        storage_allowed=True,
        training_allowed=True,
    )


def atom(
    atom_id: str,
    *,
    kind: MemoryKind = MemoryKind.ENTITY,
    entity_kind: EntityKind | None = EntityKind.PRODUCT,
    subject_id: str = "product:alpha",
    payload: dict[str, object] | None = None,
    confidence: float = 0.95,
    utility: float = 0.9,
    version: int = 1,
    valid_until: str | None = LATER,
    permanent: bool = False,
    memory_source: MemorySource | None = None,
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
    access_roles: tuple[str, ...] = ("*",),
    token_cost: int = 1,
) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        kind=kind,
        entity_kind=entity_kind,
        subject_id=subject_id,
        payload=payload or {"name": atom_id},
        source=memory_source or source(),
        created_at=NOW,
        valid_until=valid_until,
        confidence=confidence,
        utility=utility,
        approved=True,
        version=version,
        permanent=permanent,
        privacy_class=privacy_class,
        access_roles=access_roles,
        token_cost=token_cost,
    )


class MemoryGovernanceRuntimeTests(unittest.TestCase):
    def test_source_revision_is_required_and_update_preserves_revision_lineage(self) -> None:
        graph = BrandGenomeMemory()
        first = atom("revision-v1", memory_source=source(revision="r1"))
        graph.store(first)
        unchanged = replace(first, atom_id="revision-same", version=2)
        self.assertEqual(graph.update(first.atom_id, unchanged).verdict, PolicyVerdict.REJECT)
        revised = replace(
            first,
            atom_id="revision-v2",
            version=2,
            source=source(revision="r2"),
        )
        self.assertEqual(graph.update(first.atom_id, revised).verdict, PolicyVerdict.ACCEPT)
        self.assertEqual(
            [item.source.revision for item in graph.atoms],
            ["r1", "r2"],
        )

    def test_permanent_brand_rule_layer_is_separate_and_deletion_is_review_gated(self) -> None:
        graph = BrandGenomeMemory()
        rule = atom(
            "permanent-rule",
            kind=MemoryKind.SYMBOLIC_RULE,
            entity_kind=None,
            permanent=True,
            valid_until=None,
        )
        graph.store(rule)
        self.assertEqual(graph.permanent_rules, (rule,))
        self.assertEqual(
            graph.discard(rule.atom_id, occurred_at=NOW).verdict,
            PolicyVerdict.HUMAN_REVIEW,
        )

    def test_conflict_resolution_requires_approval_and_releases_only_winner(self) -> None:
        graph = BrandGenomeMemory()
        left = atom("conflict-left", kind=MemoryKind.SEMANTIC, entity_kind=None)
        right = replace(
            left,
            atom_id="conflict-right",
            payload={"name": "other"},
            source=source(revision="r2"),
        )
        graph.store(left)
        graph.store(right)
        graph.add_edge(
            MemoryEdge(
                "conflict-edge",
                EdgeKind.CONFLICT,
                left.atom_id,
                right.atom_id,
                "project://conflict",
                True,
                NOW,
            )
        )
        with self.assertRaises(V10ContractError):
            graph.resolve_conflict(
                "conflict-edge",
                winner_atom_id=right.atom_id,
                approval_id="",
                occurred_at=NOW,
            )
        graph.resolve_conflict(
            "conflict-edge",
            winner_atom_id=right.atom_id,
            approval_id="approval:1",
            occurred_at=NOW,
        )
        self.assertEqual(
            {item.atom_id for item in graph.retrieve(now=NOW)},
            {right.atom_id},
        )
        resolved = graph.edges[0]
        self.assertEqual(resolved.resolution_atom_id, right.atom_id)
        self.assertEqual(resolved.approval_id, "approval:1")

    def test_utility_and_token_cost_drive_bounded_context_selection(self) -> None:
        graph = BrandGenomeMemory()
        high_value = atom("high", utility=1.0, confidence=1.0, token_cost=4)
        low_value = atom("low", utility=0.2, confidence=0.8, token_cost=1)
        graph.store(high_value)
        graph.store(low_value)
        selected = graph.retrieve(now=NOW, max_context_tokens=4)
        self.assertEqual(tuple(item.atom_id for item in selected), ("high",))

    def test_privacy_ceiling_and_role_acl_fail_closed(self) -> None:
        graph = BrandGenomeMemory()
        public = atom("public", privacy_class=PrivacyClass.PUBLIC)
        secret = atom(
            "secret",
            privacy_class=PrivacyClass.RESTRICTED,
            access_roles=("supervisor",),
        )
        graph.store(public)
        graph.store(secret)
        worker = graph.retrieve(
            now=NOW,
            requester_role="worker",
            maximum_privacy=PrivacyClass.RESTRICTED,
        )
        supervisor = graph.retrieve(
            now=NOW,
            requester_role="supervisor",
            maximum_privacy=PrivacyClass.RESTRICTED,
        )
        self.assertEqual({item.atom_id for item in worker}, {"public"})
        self.assertEqual({item.atom_id for item in supervisor}, {"public", "secret"})
        with self.assertRaises(V10ContractError):
            atom(
                "bad-secret",
                privacy_class=PrivacyClass.CONFIDENTIAL,
                access_roles=("*",),
            )

    def test_entity_and_symbolic_retrieval_are_distinct_policy_paths(self) -> None:
        graph = BrandGenomeMemory()
        product = atom("product", entity_kind=EntityKind.PRODUCT)
        rule = atom(
            "rule",
            kind=MemoryKind.SYMBOLIC_RULE,
            entity_kind=None,
            permanent=True,
            valid_until=None,
        )
        graph.store(product)
        graph.store(rule)
        self.assertEqual(graph.retrieve_entities((EntityKind.PRODUCT,), now=NOW), (product,))
        self.assertEqual(graph.retrieve_symbolic(now=NOW), (rule,))

    def test_rollback_to_arbitrary_event_restores_atoms_edges_and_chain(self) -> None:
        graph = BrandGenomeMemory()
        first = atom("rollback-a")
        second = atom("rollback-b", subject_id="product:beta")
        first_receipt = graph.store(first)
        graph.store(second)
        graph.add_edge(
            MemoryEdge(
                "applies",
                EdgeKind.APPLIES_TO,
                first.atom_id,
                second.atom_id,
                "project://rollback-edge",
                True,
                NOW,
            )
        )
        graph.rollback_to_event(first_receipt.event_hash)
        self.assertEqual(graph.atoms, (first,))
        self.assertEqual(graph.edges, ())
        self.assertEqual(len(graph.events), 1)
        self.assertTrue(graph.verify_event_chain())


class MemoryRetrievalAndBenchmarkTests(unittest.TestCase):
    def test_dense_index_is_revisioned_and_fixture_does_not_claim_neural_inference(self) -> None:
        graph, index, cases = build_memory_benchmark_fixture()
        self.assertEqual(index.dimension, 3)
        self.assertFalse(index.observed_neural_inference)
        self.assertEqual(len(index.content_sha256), 64)
        request = cases[0].request
        result = BrandMemoryRetriever(graph, index).retrieve(
            request, RetrievalMode.NEURAL
        )
        self.assertFalse(result.neural_inference_observed)
        self.assertEqual(result.dense_index_sha256, index.content_sha256)
        with self.assertRaises(V10ContractError):
            DenseEmbeddingIndex("bad", "r1", {"x": (0.0, 0.0)}, False)

    def test_hybrid_retrieval_fuses_entity_symbolic_and_dense_under_scope(self) -> None:
        graph, index, cases = build_memory_benchmark_fixture()
        retriever = BrandMemoryRetriever(graph, index, HybridFusionConfig())
        result = retriever.retrieve(cases[0].request, RetrievalMode.HYBRID)
        self.assertEqual(set(result.atom_ids), set(cases[0].relevant_atom_ids))
        self.assertTrue(any("symbolic" in item.channels for item in result.ranked))
        self.assertTrue(any("dense" in item.channels for item in result.ranked))
        self.assertGreater(result.context_saving_rate, 0)
        self.assertEqual(len(result.fusion_config_sha256 or ""), 64)

    def test_memory_only_benchmark_measures_precision_staleness_saving_transfer_and_pollution(self) -> None:
        report = run_memory_only_benchmark()
        self.assertTrue(report.memory_only)
        self.assertFalse(report.raw_input_available_to_answerer)
        self.assertEqual(report.case_count, 12)
        hybrid = next(
            item for item in report.mode_metrics if item.mode == RetrievalMode.HYBRID
        )
        self.assertEqual(hybrid.retrieval_precision, 1.0)
        self.assertEqual(hybrid.stale_recall, 0.0)
        self.assertGreater(hybrid.mean_context_saving_rate, 0.0)
        self.assertEqual(hybrid.cross_campaign_transfer_rate, 1.0)
        self.assertEqual(hybrid.brand_contamination_rate, 0.0)
        self.assertFalse(hybrid.neural_inference_observed)

    def test_vector_only_and_no_memory_are_executable_inferior_ablations(self) -> None:
        report = run_memory_only_benchmark()
        metrics = {item.mode: item for item in report.mode_metrics}
        hybrid = metrics[RetrievalMode.HYBRID]
        vector_only = metrics[RetrievalMode.VECTOR_ONLY]
        no_memory = metrics[RetrievalMode.NO_MEMORY]
        self.assertGreater(hybrid.complete_case_rate, vector_only.complete_case_rate)
        self.assertGreater(hybrid.complete_case_rate, no_memory.complete_case_rate)
        self.assertGreater(vector_only.brand_contamination_rate, 0.0)
        self.assertEqual(no_memory.retrieved_count, 0)

    def test_streaming_benchmark_exercises_revision_expiry_conflict_and_rollback(self) -> None:
        report = run_streaming_benchmark()
        self.assertEqual(report.source_revisions, ("stream-r1", "stream-r2"))
        self.assertTrue(report.old_revision_excluded_after_update)
        self.assertTrue(report.expired_fact_excluded)
        self.assertTrue(report.conflict_winner_retrieved)
        self.assertTrue(report.conflict_loser_quarantined)
        self.assertTrue(report.rollback_restored_prior_revision)
        self.assertTrue(report.event_chain_valid)

    def test_memory_card_freezes_mechanical_v1_without_promoting_model_quality(self) -> None:
        card = build_memory_card(
            run_memory_only_benchmark(),
            run_streaming_benchmark(),
        )
        self.assertTrue(card["frozen"])
        self.assertTrue(card["mechanical_v1_passed"])
        self.assertFalse(card["promotion_eligible"])
        self.assertIsNone(card["trained_model_metrics"])
        self.assertFalse(card["observed_neural_embedding_inference"])
        self.assertEqual(len(card["content_sha256"]), 64)
        self.assertEqual(len(card["reuse_or_justify"]), 3)


if __name__ == "__main__":
    unittest.main()
