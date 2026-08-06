from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.v10_brand_memory import (
    BrandGenomeMemory,
    EdgeKind,
    EntityKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemorySource,
    PolicyAction,
    PolicyVerdict,
    PrivacyClass,
    build_policy_supervision_corpus,
)
from prooflaunch_remix.v10_contracts import V10ContractError, stable_digest


NOW = "2026-07-31T12:00:00+00:00"
LATER = "2026-08-01T12:00:00+00:00"
EXPIRED = "2026-07-31T13:00:00+00:00"


def source(*, storage_allowed: bool = True, revision: str = "seed-v1") -> MemorySource:
    return MemorySource(
        locator="project://brand-genome/fixture",
        revision=revision,
        sha256=stable_digest({"fixture": "brand-genome-fixture", "revision": revision}),
        rights_profile="project_owned_synthetic",
        storage_allowed=storage_allowed,
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
    approved: bool = True,
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
        approved=approved,
        version=version,
        permanent=permanent,
        privacy_class=privacy_class,
        access_roles=access_roles,
        token_cost=token_cost,
    )


class MemoryAtomContractTests(unittest.TestCase):
    def test_memory_atom_defines_entity_episodic_semantic_and_symbolic_rule(self) -> None:
        examples = (
            atom("entity"),
            atom("episode", kind=MemoryKind.EPISODIC, entity_kind=None),
            atom("semantic", kind=MemoryKind.SEMANTIC, entity_kind=None),
            atom(
                "rule",
                kind=MemoryKind.SYMBOLIC_RULE,
                entity_kind=None,
                permanent=True,
                valid_until=None,
            ),
        )
        self.assertEqual({item.kind for item in examples}, set(MemoryKind))
        self.assertTrue(all(len(item.content_sha256) == 64 for item in examples))
        with self.assertRaises(V10ContractError):
            atom(
                "hidden",
                payload={"hidden_reasoning": "private thought"},
            )

    def test_all_seven_brand_genome_entity_types_are_typed_and_valid(self) -> None:
        entities = {
            kind: atom(f"entity:{kind.value}", entity_kind=kind)
            for kind in EntityKind
        }
        self.assertEqual(set(entities), set(EntityKind))
        self.assertEqual(len(entities), 7)
        self.assertTrue(all(item.kind == MemoryKind.ENTITY for item in entities.values()))


class MemoryGraphEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = BrandGenomeMemory()
        self.claim = atom(
            "claim",
            entity_kind=EntityKind.CLAIM,
            subject_id="claim:one",
        )
        self.evidence = atom(
            "evidence",
            kind=MemoryKind.SEMANTIC,
            entity_kind=None,
            subject_id="evidence:one",
        )
        self.rule = atom(
            "rule",
            kind=MemoryKind.SYMBOLIC_RULE,
            entity_kind=None,
            subject_id="rule:logo",
            permanent=True,
            valid_until=None,
        )
        self.channel = atom(
            "channel",
            entity_kind=EntityKind.CHANNEL,
            subject_id="channel:social",
        )
        for item in (self.claim, self.evidence, self.rule, self.channel):
            self.assertEqual(self.graph.store(item).verdict, PolicyVerdict.ACCEPT)

    def edge(self, edge_id: str, kind: EdgeKind, left: str, right: str) -> MemoryEdge:
        return MemoryEdge(edge_id, kind, left, right, "project://edge", True, NOW)

    def test_evidence_applies_to_and_prohibited_edges_enforce_semantics(self) -> None:
        self.graph.add_edge(self.edge("e1", EdgeKind.EVIDENCE, "claim", "evidence"))
        self.graph.add_edge(self.edge("e2", EdgeKind.APPLIES_TO, "evidence", "channel"))
        self.graph.add_edge(self.edge("e3", EdgeKind.PROHIBITED, "rule", "channel"))
        self.assertEqual({edge.kind for edge in self.graph.edges}, {
            EdgeKind.EVIDENCE,
            EdgeKind.APPLIES_TO,
            EdgeKind.PROHIBITED,
        })
        with self.assertRaises(V10ContractError):
            self.graph.add_edge(
                self.edge("bad-evidence", EdgeKind.EVIDENCE, "channel", "evidence")
            )
        with self.assertRaises(V10ContractError):
            self.graph.add_edge(
                self.edge("bad-prohibition", EdgeKind.PROHIBITED, "evidence", "channel")
            )

    def test_conflict_quarantines_both_atoms_and_blocks_merge(self) -> None:
        second = atom(
            "evidence-conflict",
            kind=MemoryKind.SEMANTIC,
            entity_kind=None,
            subject_id="evidence:one",
            payload={"value": "contradiction"},
        )
        self.graph.store(second)
        self.graph.add_edge(
            self.edge("conflict", EdgeKind.CONFLICT, "evidence", "evidence-conflict")
        )
        merged = replace(second, atom_id="merged", version=2)
        receipt = self.graph.merge(("evidence", "evidence-conflict"), merged)
        self.assertEqual(receipt.verdict, PolicyVerdict.HUMAN_REVIEW)
        retrieved = self.graph.retrieve(now=NOW, subject_ids=("evidence:one",))
        self.assertEqual(retrieved, ())


class MemoryPolicyTests(unittest.TestCase):
    def test_store_policy_requires_rights_and_approval_for_high_impact_memory(self) -> None:
        graph = BrandGenomeMemory()
        denied = atom("denied", memory_source=source(storage_allowed=False))
        self.assertEqual(graph.store(denied).verdict, PolicyVerdict.REJECT)
        brand = atom("brand", entity_kind=EntityKind.BRAND, approved=False)
        self.assertEqual(graph.store(brand).verdict, PolicyVerdict.HUMAN_REVIEW)
        self.assertEqual(graph.store(atom("product")).verdict, PolicyVerdict.ACCEPT)

    def test_retrieve_policy_is_scoped_and_excludes_expired_unapproved_and_superseded(self) -> None:
        graph = BrandGenomeMemory()
        active = atom("active")
        old = atom("old", subject_id="product:versioned")
        new = atom(
            "new",
            subject_id="product:versioned",
            version=2,
            memory_source=source(revision="seed-v2"),
        )
        expired = atom("expired", valid_until=EXPIRED)
        for item in (active, old, expired):
            graph.store(item)
        self.assertEqual(graph.update("old", new).verdict, PolicyVerdict.ACCEPT)
        found = graph.retrieve(
            now="2026-07-31T14:00:00+00:00",
            entity_kinds=(EntityKind.PRODUCT,),
            minimum_confidence=0.9,
        )
        self.assertEqual({item.atom_id for item in found}, {"active", "new"})
        self.assertEqual(graph.retrieve_receipt(now=NOW).action, PolicyAction.RETRIEVE)

    def test_update_policy_is_append_only_and_creates_approved_supersede_edge(self) -> None:
        graph = BrandGenomeMemory()
        previous = atom("product-v1")
        graph.store(previous)
        replacement = replace(
            previous,
            atom_id="product-v2",
            version=2,
            payload={"name": "v2"},
            source=source(revision="seed-v2"),
        )
        receipt = graph.update(previous.atom_id, replacement)
        self.assertEqual(receipt.verdict, PolicyVerdict.ACCEPT)
        edge = next(item for item in graph.edges if item.kind == EdgeKind.SUPERSEDE)
        self.assertEqual((edge.source_atom_id, edge.target_atom_id), ("product-v1", "product-v2"))
        invalid = replace(replacement, atom_id="product-v4", version=4)
        self.assertEqual(graph.update("product-v2", invalid).verdict, PolicyVerdict.REJECT)

    def test_merge_policy_preserves_member_lineage_without_blending_scopes(self) -> None:
        graph = BrandGenomeMemory()
        first = atom("segment-a", kind=MemoryKind.SEMANTIC, entity_kind=None, subject_id="audience:a")
        second = atom("segment-b", kind=MemoryKind.SEMANTIC, entity_kind=None, subject_id="audience:a")
        graph.store(first)
        graph.store(second)
        merged = atom(
            "segment-merged",
            kind=MemoryKind.SEMANTIC,
            entity_kind=None,
            subject_id="audience:a",
            version=2,
            payload={"member_ids": [first.atom_id, second.atom_id]},
        )
        receipt = graph.merge((first.atom_id, second.atom_id), merged)
        self.assertEqual(receipt.verdict, PolicyVerdict.ACCEPT)
        mismatch = replace(merged, atom_id="wrong", subject_id="audience:b")
        self.assertEqual(
            graph.merge((first.atom_id, second.atom_id), mismatch).verdict,
            PolicyVerdict.REJECT,
        )

    def test_discard_policy_writes_recoverable_tombstone_and_rollback_restores(self) -> None:
        graph = BrandGenomeMemory()
        episode = atom("episode", kind=MemoryKind.EPISODIC, entity_kind=None)
        graph.store(episode)
        receipt = graph.discard(episode.atom_id, occurred_at=NOW)
        self.assertEqual(receipt.verdict, PolicyVerdict.ACCEPT)
        self.assertIn(episode.atom_id, graph.tombstones)
        graph.rollback_last()
        self.assertNotIn(episode.atom_id, graph.tombstones)
        self.assertTrue(graph.verify_event_chain())

    def test_summarize_policy_requires_content_addressed_members_and_semantic_output(self) -> None:
        graph = BrandGenomeMemory()
        first = atom("e1", kind=MemoryKind.EPISODIC, entity_kind=None)
        second = atom("e2", kind=MemoryKind.EPISODIC, entity_kind=None)
        graph.store(first)
        graph.store(second)
        summary = atom(
            "summary",
            kind=MemoryKind.SEMANTIC,
            entity_kind=None,
            payload={
                "summary": "Two visible launch observations.",
                "member_sha256": [first.content_sha256, second.content_sha256],
            },
        )
        self.assertEqual(
            graph.summarize((first.atom_id, second.atom_id), summary).verdict,
            PolicyVerdict.ACCEPT,
        )
        wrong = replace(summary, atom_id="wrong-summary", payload={"member_sha256": []})
        self.assertEqual(
            graph.summarize((first.atom_id, second.atom_id), wrong).verdict,
            PolicyVerdict.REJECT,
        )

    def test_what_to_remember_balances_rights_confidence_utility_and_permanence(self) -> None:
        graph = BrandGenomeMemory()
        useful = atom("useful", kind=MemoryKind.SEMANTIC, entity_kind=None)
        transient = atom(
            "transient",
            kind=MemoryKind.EPISODIC,
            entity_kind=None,
            utility=0.1,
        )
        unapproved_rule = atom(
            "rule",
            kind=MemoryKind.SYMBOLIC_RULE,
            entity_kind=None,
            permanent=True,
            valid_until=None,
            approved=False,
        )
        self.assertEqual(graph.what_to_remember(useful).verdict, PolicyVerdict.ACCEPT)
        self.assertEqual(graph.what_to_remember(transient).verdict, PolicyVerdict.REJECT)
        self.assertEqual(
            graph.what_to_remember(unapproved_rule).verdict,
            PolicyVerdict.HUMAN_REVIEW,
        )

    def test_when_to_forget_accepts_expiry_but_protects_live_and_permanent_memory(self) -> None:
        graph = BrandGenomeMemory()
        expired = atom("expired", valid_until=EXPIRED)
        live = atom("live")
        rule = atom(
            "rule",
            kind=MemoryKind.SYMBOLIC_RULE,
            entity_kind=None,
            permanent=True,
            valid_until=None,
        )
        for item in (expired, live, rule):
            graph.store(item)
        self.assertEqual(
            graph.when_to_forget("expired", now="2026-07-31T14:00:00+00:00").verdict,
            PolicyVerdict.ACCEPT,
        )
        self.assertEqual(graph.when_to_forget("live", now=NOW).verdict, PolicyVerdict.REJECT)
        self.assertEqual(graph.when_to_forget("rule", now=NOW).verdict, PolicyVerdict.HUMAN_REVIEW)

    def test_policy_supervision_is_balanced_source_labeled_and_never_claims_training(self) -> None:
        corpus = build_policy_supervision_corpus()
        self.assertEqual(len(corpus), 16)
        self.assertEqual({row["input"]["action"] for row in corpus}, {item.value for item in PolicyAction})
        for action in PolicyAction:
            rows = [row for row in corpus if row["input"]["action"] == action.value]
            self.assertEqual({row["target"]["verdict"] for row in rows}, {"accept", "reject"})
        self.assertTrue(all(row["rights_profile"] == "project_owned_synthetic" for row in corpus))
        self.assertTrue(all(row["model_training_observed"] is False for row in corpus))
        self.assertTrue(all(len(row["content_sha256"]) == 64 for row in corpus))


if __name__ == "__main__":
    unittest.main()
