#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
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
    build_policy_supervision_corpus,
)
from prooflaunch_remix.v10_contracts import stable_digest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_brand_memory"
AUDIT = ROOT / "evidence/v10/brand-memory-seed-audit.json"
NOW = "2026-07-31T12:00:00+00:00"
VALID_UNTIL = "2027-07-31T12:00:00+00:00"


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def source(name: str) -> MemorySource:
    return MemorySource(
        locator=f"project://brand-genome/{name}",
        revision="brand-genome-seed-v1",
        sha256=stable_digest({"fixture": name, "revision": "v1"}),
        rights_profile="project_owned_synthetic",
        storage_allowed=True,
        training_allowed=True,
    )


def entity(kind: EntityKind, payload: dict[str, Any]) -> MemoryAtom:
    return MemoryAtom(
        atom_id=f"entity:{kind.value}:v1",
        kind=MemoryKind.ENTITY,
        entity_kind=kind,
        subject_id=f"{kind.value}:alpha",
        payload=payload,
        source=source(f"entity-{kind.value}"),
        created_at=NOW,
        valid_until=VALID_UNTIL,
        confidence=0.96,
        utility=0.92,
        approved=True,
    )


def non_entity(
    atom_id: str,
    kind: MemoryKind,
    subject_id: str,
    payload: dict[str, Any],
    *,
    permanent: bool = False,
) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        kind=kind,
        entity_kind=None,
        subject_id=subject_id,
        payload=payload,
        source=source(atom_id.replace(":", "-")),
        created_at=NOW,
        valid_until=None if permanent else VALID_UNTIL,
        confidence=0.94,
        utility=0.88,
        approved=True,
        permanent=permanent,
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(
        path,
        "".join(
            json.dumps(normalize(row), ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    graph = BrandGenomeMemory()
    entities = (
        entity(EntityKind.PRODUCT, {"name": "Alpha", "sku": "A-1"}),
        entity(EntityKind.BRAND, {"name": "ProofLaunch", "tone": "precise"}),
        entity(EntityKind.AUDIENCE, {"segment": "evidence-led growth teams"}),
        entity(EntityKind.CLAIM, {"text": "Exports are source-bound", "status": "substantiated"}),
        entity(EntityKind.CHANNEL, {"name": "paid-social", "market": "north-america"}),
        entity(EntityKind.ASSET, {"name": "launch-key-visual", "format": "image"}),
        entity(EntityKind.CREATIVE_CONCEPT, {"name": "Proof Before Publish"}),
    )
    for item in entities:
        receipt = graph.store(item)
        if receipt.verdict != PolicyVerdict.ACCEPT:
            raise SystemExit(f"failed to store seed entity: {item.atom_id}")

    episodic_a = non_entity(
        "episode:launch-review:a",
        MemoryKind.EPISODIC,
        "campaign:alpha",
        {"event": "review", "outcome": "logo safe-zone passed"},
    )
    episodic_b = non_entity(
        "episode:launch-review:b",
        MemoryKind.EPISODIC,
        "campaign:alpha",
        {"event": "review", "outcome": "logo safe-zone failed"},
    )
    semantic_evidence = non_entity(
        "semantic:claim-evidence",
        MemoryKind.SEMANTIC,
        "claim:alpha",
        {"fact": "Every exported claim has a source locator and digest"},
    )
    semantic_audience = non_entity(
        "semantic:audience-insight",
        MemoryKind.SEMANTIC,
        "audience:alpha",
        {"insight": "Evidence visibility reduces review friction"},
    )
    rule = non_entity(
        "rule:no-auto-publish",
        MemoryKind.SYMBOLIC_RULE,
        "rule:release",
        {"predicate": "publish", "effect": "requires_human_approval"},
        permanent=True,
    )
    for item in (episodic_a, episodic_b, semantic_evidence, semantic_audience, rule):
        if graph.store(item).verdict != PolicyVerdict.ACCEPT:
            raise SystemExit(f"failed to store seed memory: {item.atom_id}")

    product_v2 = replace(
        entities[0],
        atom_id="entity:product:v2",
        payload={"name": "Alpha", "sku": "A-1", "status": "launch-ready"},
        source=source("entity-product-v2"),
        version=2,
    )
    if graph.update(entities[0].atom_id, product_v2).verdict != PolicyVerdict.ACCEPT:
        raise SystemExit("failed to create product supersede edge")

    extra_edges = (
        MemoryEdge(
            "edge:evidence:claim",
            EdgeKind.EVIDENCE,
            "entity:claim:v1",
            semantic_evidence.atom_id,
            "project://brand-genome/evidence-edge",
            True,
            NOW,
        ),
        MemoryEdge(
            "edge:conflict:launch-review",
            EdgeKind.CONFLICT,
            episodic_a.atom_id,
            episodic_b.atom_id,
            "project://brand-genome/conflict-edge",
            True,
            NOW,
        ),
        MemoryEdge(
            "edge:applies-to:audience",
            EdgeKind.APPLIES_TO,
            semantic_audience.atom_id,
            "entity:audience:v1",
            "project://brand-genome/applies-to-edge",
            True,
            NOW,
        ),
        MemoryEdge(
            "edge:prohibited:auto-publish",
            EdgeKind.PROHIBITED,
            rule.atom_id,
            "entity:channel:v1",
            "project://brand-genome/prohibited-edge",
            True,
            NOW,
        ),
    )
    for edge in extra_edges:
        graph.add_edge(edge)

    policy_rows = list(build_policy_supervision_corpus())
    atom_rows = [
        {
            **normalize(asdict(item)),
            "content_sha256": item.content_sha256,
        }
        for item in graph.atoms
    ]
    edge_rows = [
        {
            **normalize(asdict(item)),
            "content_sha256": item.content_sha256,
        }
        for item in graph.edges
    ]
    event_rows = [normalize(asdict(item)) for item in graph.events]

    DATA.mkdir(parents=True, exist_ok=True)
    atoms_path = DATA / "atoms.jsonl"
    edges_path = DATA / "edges.jsonl"
    policy_path = DATA / "policy_examples.jsonl"
    events_path = DATA / "event_log.jsonl"
    write_jsonl(atoms_path, atom_rows)
    write_jsonl(edges_path, edge_rows)
    write_jsonl(policy_path, policy_rows)
    write_jsonl(events_path, event_rows)

    entity_coverage = sorted(
        item.entity_kind.value
        for item in graph.atoms
        if item.entity_kind is not None
    )
    kind_counts = {
        kind.value: sum(item.kind == kind for item in graph.atoms)
        for kind in MemoryKind
    }
    edge_counts = {
        kind.value: sum(item.kind == kind for item in graph.edges)
        for kind in EdgeKind
    }
    policy_counts = {
        action.value: sum(
            row["input"]["action"] == action.value for row in policy_rows
        )
        for action in PolicyAction
    }
    checks = {
        "all_four_memory_kinds_present": all(kind_counts.values()),
        "all_seven_entity_kinds_present": set(entity_coverage)
        == {item.value for item in EntityKind},
        "all_five_edge_kinds_present": all(edge_counts.values()),
        "exact_two_balanced_examples_per_policy": all(
            count == 2 for count in policy_counts.values()
        ),
        "all_policy_examples_are_project_owned": all(
            row["rights_profile"] == "project_owned_synthetic"
            for row in policy_rows
        ),
        "zero_hidden_reasoning": all(
            not row["input"]["hidden_reasoning_present"] for row in policy_rows
        ),
        "model_training_remains_unclaimed": all(
            row["model_training_observed"] is False for row in policy_rows
        ),
        "event_chain_valid": graph.verify_event_chain(),
    }
    files = {
        path.name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in (atoms_path, edges_path, policy_path, events_path)
    }
    manifest = {
        "schema": "ProofLaunchBrandGenomeMemorySeedManifestV1",
        "generated_at": NOW,
        "atom_count": len(atom_rows),
        "edge_count": len(edge_rows),
        "policy_example_count": len(policy_rows),
        "event_count": len(event_rows),
        "memory_kind_counts": kind_counts,
        "entity_kind_coverage": sorted(set(entity_coverage)),
        "edge_kind_counts": edge_counts,
        "policy_action_counts": policy_counts,
        "files": files,
        "rights_profile": "project_owned_synthetic",
        "trained_model_metrics": None,
        "model_training_observed": False,
        "promotion_eligible": False,
        "truth_boundary": (
            "This is a deterministic local Brand Genome schema, policy runtime, "
            "and supervision seed. It is not trained-weight, Radeon, human 4A, "
            "or production-quality evidence."
        ),
        "content_sha256": None,
    }
    manifest["content_sha256"] = stable_digest(
        {key: value for key, value in manifest.items() if key != "content_sha256"}
    )
    manifest_path = DATA / "manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    checks["manifest_is_content_addressed"] = len(manifest["content_sha256"]) == 64
    files[manifest_path.name] = {
        "path": str(manifest_path.relative_to(ROOT)),
        "sha256": sha256(manifest_path),
        "bytes": manifest_path.stat().st_size,
    }
    audit = {
        "schema": "ProofLaunchBrandGenomeMemorySeedAuditV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed_as_local_mechanical_seed_not_model_training"
        if all(checks.values())
        else "failed",
        "checks": checks,
        "counts": {
            "atoms": len(atom_rows),
            "edges": len(edge_rows),
            "policy_examples": len(policy_rows),
            "events": len(event_rows),
        },
        "files": files,
        "model_training_observed": False,
        "trained_checkpoint_receipts": 0,
        "human_4a_evaluations": 0,
        "radeon_execution_receipts": 0,
        "promotion_eligible": False,
        "truth_boundary": manifest["truth_boundary"],
    }
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(AUDIT, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    if not all(checks.values()):
        raise SystemExit("Brand Genome seed checks failed")
    print(
        json.dumps(
            {
                "status": audit["status"],
                "atoms": len(atom_rows),
                "edges": len(edge_rows),
                "policy_examples": len(policy_rows),
                "events": len(event_rows),
                "manifest_sha256": manifest["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
