from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping


SCHEMA = "ProofLaunchGTMNamedCapabilityDistillationV1"
LEDGER_SCHEMA = "ProofLaunchConcreteProductEffectPKLedgerV1"


class GTMNamedCapabilityDistillationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _verify_ledger(ledger: Mapping[str, Any]) -> None:
    unsigned = dict(ledger)
    supplied = unsigned.pop("content_sha256", None)
    if ledger.get("schema") != LEDGER_SCHEMA or supplied != _digest(unsigned):
        raise GTMNamedCapabilityDistillationError("named-product ledger seal is invalid")
    rows = ledger.get("product_pk_rows")
    if not isinstance(rows, list) or len(rows) != 130:
        raise GTMNamedCapabilityDistillationError("named-product ledger must contain 130 rows")


def compile_named_capability_distillation(ledger: Mapping[str, Any]) -> dict[str, Any]:
    _verify_ledger(ledger)
    rows_by_category: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    atoms = []
    seen_atom_ids: set[str] = set()
    for index, row in enumerate(ledger["product_pk_rows"]):
        category = row.get("category_id")
        product = row.get("reference_product")
        capability = row.get("reference_capability")
        quality_axes = row.get("quality_axes")
        if not all(isinstance(value, str) and value.strip() for value in (category, product, capability)):
            raise GTMNamedCapabilityDistillationError(f"ledger row {index} lacks a named capability")
        if not isinstance(quality_axes, list) or not quality_axes or any(not isinstance(axis, str) or not axis.strip() for axis in quality_axes):
            raise GTMNamedCapabilityDistillationError(f"ledger row {index} lacks quality axes")
        atom_id = _digest({"category": category, "product": product, "capability": capability})
        if atom_id in seen_atom_ids:
            raise GTMNamedCapabilityDistillationError("named capability atom duplicated")
        seen_atom_ids.add(atom_id)
        rows_by_category[category].append(row)
        atoms.append({
            "atom_id": atom_id,
            "category_id": category,
            "reference_product": product,
            "mechanism_to_absorb": capability,
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": list(quality_axes),
            "pinned_oss_candidates": [
                {
                    "project_id": item["project_id"], "repo": item["repo"], "revision": item["revision"],
                    "license": item["license"], "decision": item["decision"],
                }
                for item in row.get("open_source_reuse", [])
            ],
            "candidate_artifact_bindings": list(row.get("candidate_artifacts", [])),
            "comparison_status": row.get("comparison_status"),
            "named_product_baseline_present": row.get("named_product_baseline_present") is True,
            "effect_alignment_achieved": row.get("effect_alignment_achieved") is True,
            "distillation_boundary": {
                "transfer_mechanism_only": True,
                "copy_product_expression": False,
                "copy_product_interface": False,
                "copy_source_output": False,
                "claim_superiority_before_blind_pk": False,
            },
        })
    if set(map(len, rows_by_category.values())) != {10} or len(rows_by_category) != 13:
        raise GTMNamedCapabilityDistillationError("distillation requires 13 categories with 10 products each")
    categories = []
    for category_id in sorted(rows_by_category):
        rows = rows_by_category[category_id]
        oss = {}
        for row in rows:
            for item in row.get("open_source_reuse", []):
                oss[(item["repo"], item["revision"])] = {
                    "project_id": item["project_id"], "repo": item["repo"], "revision": item["revision"],
                    "license": item["license"], "decision": item["decision"],
                }
        categories.append({
            "category_id": category_id,
            "reference_products": [row["reference_product"] for row in rows],
            "reference_product_count": len(rows),
            "mechanism_repertoire": [row["reference_capability"] for row in rows],
            "quality_axes": sorted({axis for row in rows for axis in row["quality_axes"]}),
            "same_brief_task": rows[0]["same_brief_task"],
            "effect_pk_question": rows[0]["effect_pk_question"],
            "pinned_oss_candidates": sorted(oss.values(), key=lambda item: (item["project_id"], item["revision"])),
            "training_curriculum": [
                "observe the named capability and source boundary",
                "abstract the transferable mechanism without copying expression or interface",
                "instantiate the mechanism against the frozen owner brief",
                "run the same-brief candidate through category quality axes",
                "shadow-compare against an authorized named baseline",
                "admit only named-human source-hidden review and observed effect evidence into learning memory",
            ],
            "completed_named_product_comparison_count": sum(row.get("comparison_status") == "completed" for row in rows),
            "effect_aligned_row_count": sum(row.get("effect_alignment_achieved") is True for row in rows),
        })
    payload = {
        "schema": SCHEMA,
        "source_ledger_sha256": ledger["content_sha256"],
        "category_count": len(categories),
        "named_product_count": len(atoms),
        "capability_atom_count": len(atoms),
        "categories": categories,
        "capability_atoms": atoms,
        "portfolio_curriculum": {
            "frozen_owner_brief_required": True,
            "same_brief_comparison_required": True,
            "authorized_named_baseline_required": True,
            "source_hidden_human_review_required": True,
            "observed_organic_effect_required_for_effect_claim": True,
            "automatic_component_promotion": False,
            "automatic_winner_selection": False,
        },
        "completed_named_product_comparison_count": sum(row.get("comparison_status") == "completed" for row in ledger["product_pk_rows"]),
        "effect_aligned_row_count": sum(row.get("effect_alignment_achieved") is True for row in ledger["product_pk_rows"]),
        "truth_boundary": "This artifact distills named-product capabilities into transferable mechanisms and same-brief tasks. It does not contain authorized baselines, completed comparisons, product copying or proof of superiority.",
    }
    payload["content_sha256"] = _digest(payload)
    verify_named_capability_distillation(payload)
    return payload


def verify_named_capability_distillation(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMNamedCapabilityDistillationError("capability distillation seal is invalid")
    if payload.get("category_count") != 13 or payload.get("named_product_count") != 130:
        raise GTMNamedCapabilityDistillationError("capability distillation coverage drifted")
    atoms = payload.get("capability_atoms", [])
    if len(atoms) != 130 or len({row.get("atom_id") for row in atoms}) != 130:
        raise GTMNamedCapabilityDistillationError("capability atom coverage drifted")
    if payload.get("portfolio_curriculum", {}).get("automatic_winner_selection") is not False:
        raise GTMNamedCapabilityDistillationError("distillation enabled automatic selection")


__all__ = [
    "GTMNamedCapabilityDistillationError", "SCHEMA", "compile_named_capability_distillation",
    "verify_named_capability_distillation",
]
