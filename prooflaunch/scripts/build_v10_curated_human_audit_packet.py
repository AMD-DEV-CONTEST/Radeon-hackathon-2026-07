from __future__ import annotations

import hashlib
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_curated_human_audit import (  # noqa: E402
    ATTESTATION,
    AUDIT_CASE_COUNT,
    AUDIT_STRATA,
    EXPECTED_REVIEW_COUNT,
    POSITIVE_MEAN_MINIMUM,
    ALPHA_MINIMUM,
    REVIEWER_COUNT,
    RUBRIC_DIMENSIONS,
    blind_case,
    review_template,
)
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    atomic_write_text(path, text)
    return hashlib.sha256(text.encode()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)
    return hashlib.sha256(text.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_select(rows: list[dict[str, Any]], *, count: int, stratum: str, id_key: str) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise RuntimeError(f"{stratum} has {len(rows)} records, below audit quota {count}")
    unique_ids = {str(row[id_key]) for row in rows}
    if len(unique_ids) != len(rows):
        raise RuntimeError(f"{stratum} identifier drift")
    return sorted(
        rows,
        key=lambda row: stable_sha256({"seed": "prooflaunch-v10-curated-audit", "stratum": stratum, "id": row[id_key]}),
    )[:count]


def _source_ids(row: Mapping[str, Any], stratum: str) -> list[str]:
    if stratum in {"sft", "preference", "repair"}:
        return [str(item) for item in row.get("source_ids", [])]
    if stratum in {"cpt", "region", "source"}:
        value = row.get("source_id")
        return [str(value)] if value else []
    return []


def _provider(row: Mapping[str, Any], stratum: str, source_map: Mapping[str, Mapping[str, Any]]) -> str:
    if stratum in {"cpt", "region", "source"}:
        return str(row.get("provider") or "unknown")
    if stratum == "trajectory":
        return "prooflaunch-project-owned"
    providers = sorted(
        {
            str(source_map[source_id].get("provider") or "unknown")
            for source_id in _source_ids(row, stratum)
            if source_id in source_map
        }
    )
    return "+".join(providers) if providers else "unknown"


def _license(row: Mapping[str, Any], stratum: str) -> str:
    if stratum == "cpt":
        return str(row.get("license_spdx") or "unknown")
    if stratum in {"sft", "repair"}:
        return "+".join(sorted(str(item) for item in row.get("license_ids", []))) or "unknown"
    if stratum == "region":
        return str(row.get("license_id") or "unknown")
    if stratum == "source":
        return str(row.get("license_id") or "unknown")
    if stratum == "trajectory":
        return str(row.get("rights_id") or "project-owned")
    return "source-bound-preference"


def _concepts(row: Mapping[str, Any], stratum: str) -> list[str]:
    values = [f"stratum:{stratum}"]
    if stratum == "cpt":
        values.extend((f"content:{row['content_class']}", "continual_pretraining"))
    elif stratum in {"sft", "preference", "repair"}:
        values.extend((f"stage:{row['stage']}", f"input:{row['input_kind']}"))
        if row.get("scenario_family_id"):
            values.append(f"scenario:{row['scenario_family_id']}")
        if stratum == "repair":
            values.append(f"failure:{row['failure_family']}")
    elif stratum == "region":
        values.extend(("modality:image", "visual_region_preference", "crop_quality"))
    elif stratum == "trajectory":
        values.extend(
            (
                f"lane:{row.get('lane') or row.get('stage') or 'source_bound'}",
                f"issue:{row.get('issue_kind') or row.get('input_kind') or 'source_bound_execution'}",
                f"outcome:{row['outcome_kind']}",
            )
        )
    elif stratum == "source":
        values.extend((f"kind:{row['kind']}", f"modality:{row['media_type']}", "source_provenance"))
    return sorted(set(values))


def _modality(row: Mapping[str, Any], stratum: str) -> str:
    if stratum == "region":
        return "image"
    if stratum == "trajectory":
        return "trajectory"
    if stratum == "source":
        return str(row.get("media_type") or "unknown")
    if stratum in {"sft", "preference", "repair"}:
        return str(row.get("input_kind") or "text")
    return "text"


def main() -> int:
    source_rows = _read(ROOT / "data/v10_source_bundle/sources.jsonl")
    source_map = {str(row["source_id"]): row for row in source_rows}
    rows_by_stratum: dict[str, list[dict[str, Any]]] = {
        "cpt": [
            row
            for path in sorted((ROOT / "data/v10_cpt_corpus/shards").glob("cpt-*.jsonl"))
            for row in _read(path)
        ],
        "sft": _read(ROOT / "data/v10_sft_corpus/episodes.jsonl"),
        "preference": _read(ROOT / "data/v10_preference_pairs/pairs.jsonl"),
        "region": _read(ROOT / "data/v10_region_preferences/pairs.jsonl"),
        "trajectory": _read(ROOT / "data/v10_agency_trajectories/trajectories.jsonl"),
        "repair": _read(ROOT / "data/v10_repair_corpus/repair-episodes.jsonl"),
        "source": source_rows,
    }
    id_keys = {
        "cpt": "record_id",
        "sft": "episode_id",
        "preference": "pair_id",
        "region": "pair_id",
        "trajectory": "trajectory_id",
        "repair": "repair_episode_id",
        "source": "source_id",
    }
    output = ROOT / "data/v10_curated_human_audit"
    templates = output / "review-templates"
    assets = output / "assets"
    output.mkdir(parents=True, exist_ok=True)
    templates.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    sequence = 0
    for stratum, quota in AUDIT_STRATA.items():
        selected = _stable_select(rows_by_stratum[stratum], count=quota, stratum=stratum, id_key=id_keys[stratum])
        for row in selected:
            sequence += 1
            audit_id = f"audit-{sequence:04d}"
            source_row_sha256 = stable_sha256(row)
            asset_ref = None
            if stratum == "region":
                source_asset = ROOT / str(row["asset_path"])
                if _sha256_file(source_asset) != row["asset_sha256"]:
                    raise RuntimeError(f"region asset hash drift: {source_asset}")
                target_asset = assets / f"{audit_id}.img"
                shutil.copyfile(source_asset, target_asset)
                asset_ref = f"assets/{target_asset.name}"
            case = blind_case(
                audit_id=audit_id,
                stratum=stratum,
                row=row,
                source_row_sha256=source_row_sha256,
                asset_ref=asset_ref,
            )
            cases.append(case)
            source_ids = _source_ids(row, stratum)
            provenance.append(
                {
                    "case_id": audit_id,
                    "case_sha256": case["case_sha256"],
                    "stratum": stratum,
                    "source_record_id_sha256": stable_sha256({"ids": source_ids, "record_id": row[id_keys[stratum]]}),
                    "source_row_sha256": source_row_sha256,
                    "provider": _provider(row, stratum, source_map),
                    "license": _license(row, stratum),
                    "modality": _modality(row, stratum),
                    "stage": str(row.get("stage") or "not_applicable"),
                    "content_class": str(row.get("content_class") or "not_applicable"),
                    "concept_tags": _concepts(row, stratum),
                    "asset_sha256": row.get("asset_sha256"),
                }
            )

    if len(cases) != AUDIT_CASE_COUNT or len({row["case_id"] for row in cases}) != AUDIT_CASE_COUNT:
        raise RuntimeError("1,500-case audit packet drift")
    observed_strata = Counter(row["stratum"] for row in cases)
    if dict(observed_strata) != AUDIT_STRATA:
        raise RuntimeError("audit stratum quota drift")

    cases_sha = _write_jsonl(output / "blind-cases.jsonl", cases)
    provenance_sha = _write_jsonl(output / "selection-provenance.jsonl", provenance)
    assignment_rows: list[dict[str, Any]] = []
    template_hashes: dict[str, str] = {}
    for reviewer_slot in range(1, REVIEWER_COUNT + 1):
        ordered = list(cases)
        random.Random(20_260_801 + reviewer_slot).shuffle(ordered)
        rows = [review_template(case, reviewer_slot) for case in ordered]
        name = f"reviewer-{reviewer_slot:02d}.jsonl"
        template_hashes[name] = _write_jsonl(templates / name, rows)
        assignment_rows.extend(
            {
                "reviewer_slot": reviewer_slot,
                "ordinal": ordinal,
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
            }
            for ordinal, case in enumerate(ordered, start=1)
        )
    assignments_sha = _write_jsonl(output / "assignments.jsonl", assignment_rows)

    dimensions = {
        "stratum": Counter(row["stratum"] for row in provenance),
        "provider": Counter(row["provider"] for row in provenance),
        "license": Counter(row["license"] for row in provenance),
        "modality": Counter(row["modality"] for row in provenance),
        "stage": Counter(row["stage"] for row in provenance),
        "content_class": Counter(row["content_class"] for row in provenance),
        "concept": Counter(tag for row in provenance for tag in row["concept_tags"]),
    }
    distribution = {
        "schema": "ProofLaunchCuratedCorpusAuditDistributionV1",
        "audit_case_count": AUDIT_CASE_COUNT,
        "dimensions": {
            name: dict(sorted(counter.items())) for name, counter in dimensions.items()
        },
        "dimension_totals": {
            name: sum(counter.values()) for name, counter in dimensions.items()
        },
        "selection_provenance_sha256": provenance_sha,
        "truth_boundary": "Counts describe the deterministic 1,500-record audit sample, not human quality outcomes.",
    }
    distribution["distribution_sha256"] = stable_sha256(distribution)
    distribution_file_sha = _write_json(output / "distributions.json", distribution)
    concept_long_tail = {
        "schema": "ProofLaunchCuratedCorpusConceptLongTailV1",
        "audit_case_count": AUDIT_CASE_COUNT,
        "unique_concept_count": len(dimensions["concept"]),
        "concepts_ascending_frequency": [
            {"concept": concept, "count": count}
            for concept, count in sorted(dimensions["concept"].items(), key=lambda item: (item[1], item[0]))
        ],
        "selection_provenance_sha256": provenance_sha,
    }
    concept_long_tail["concept_long_tail_sha256"] = stable_sha256(concept_long_tail)
    concept_file_sha = _write_json(output / "concept-long-tail.json", concept_long_tail)
    source_distribution = {
        "schema": "ProofLaunchCuratedCorpusSourceDistributionV1",
        "audit_case_count": AUDIT_CASE_COUNT,
        "providers": [
            {"provider": provider, "count": count, "rate": round(count / AUDIT_CASE_COUNT, 8)}
            for provider, count in sorted(dimensions["provider"].items(), key=lambda item: (-item[1], item[0]))
        ],
        "licenses": [
            {"license": license_id, "count": count, "rate": round(count / AUDIT_CASE_COUNT, 8)}
            for license_id, count in sorted(dimensions["license"].items(), key=lambda item: (-item[1], item[0]))
        ],
        "provider_count_total": sum(dimensions["provider"].values()),
        "license_count_total": sum(dimensions["license"].values()),
        "selection_provenance_sha256": provenance_sha,
        "review_payload_is_blind": True,
    }
    source_distribution["source_distribution_sha256"] = stable_sha256(source_distribution)
    source_file_sha = _write_json(output / "source-distribution.json", source_distribution)

    rubric = {
        "schema": "ProofLaunchCuratedCorpusHumanAuditRubricV1",
        "reviewer_count": REVIEWER_COUNT,
        "case_count": AUDIT_CASE_COUNT,
        "expected_review_count": EXPECTED_REVIEW_COUNT,
        "dimensions": list(RUBRIC_DIMENSIONS),
        "score_scale": {"1": "unusable", "2": "major rework", "3": "competent", "4": "strong", "5": "exceptional"},
        "instructions": [
            "Review independently in assigned order and do not coordinate scores.",
            "Use integer scores from 1 through 5 for every dimension.",
            "Do not use an AI model to generate ratings, comments, or attestations.",
            "Any score below 5 requires concrete required_rework.",
            "Difficulty judges execution complexity, not output quality.",
            "The verifier, not the reviewer, computes the final route.",
            "Set review_content_sha256 only after the row is complete.",
        ],
        "attestation_exact_text": ATTESTATION,
        "gates": {
            "all_4500_reviews_required": True,
            "all_1500_cases_need_three_distinct_reviewers": True,
            "krippendorff_alpha_ordinal_minimum": ALPHA_MINIMUM,
            "positive_case_mean_minimum": POSITIVE_MEAN_MINIMUM,
            "quality_below_3_route": "remove",
            "difficulty_at_least_4_route": "replay",
            "remaining_non_positive_route": "repair",
        },
    }
    rubric["rubric_sha256"] = stable_sha256(rubric)
    rubric_file_sha = _write_json(output / "rubric.json", rubric)
    manifest = {
        "schema": "ProofLaunchCuratedCorpusHumanAuditPacketManifestV1",
        "case_count": len(cases),
        "strata": AUDIT_STRATA,
        "reviewer_slot_count": REVIEWER_COUNT,
        "assignment_count": len(assignment_rows),
        "reviews_per_case_required": REVIEWER_COUNT,
        "cases_per_reviewer": AUDIT_CASE_COUNT,
        "blind_cases_sha256": cases_sha,
        "selection_provenance_sha256": provenance_sha,
        "assignments_sha256": assignments_sha,
        "template_hashes": template_hashes,
        "rubric_sha256": rubric["rubric_sha256"],
        "rubric_file_sha256": rubric_file_sha,
        "distribution_file_sha256": distribution_file_sha,
        "concept_long_tail_file_sha256": concept_file_sha,
        "source_distribution_file_sha256": source_file_sha,
        "region_asset_count": sum(row["stratum"] == "region" for row in cases),
        "source_provider_names_exposed_in_blind_cases": False,
        "source_urls_exposed_in_blind_cases": False,
        "human_reviews_observed": 0,
        "krippendorff_alpha_observed": None,
        "positive_mean_observed": None,
        "freeze_passed": False,
        "truth_boundary": "The deterministic 1,500-case sample and distributions are complete. Empty templates are not human reviews; agreement, score, routing, and Curated Corpus V2 freeze remain unobserved.",
    }
    manifest["manifest_sha256"] = stable_sha256(manifest)
    _write_json(output / "manifest.json", manifest)
    print(json.dumps({"status": "curated_1500_audit_packet_ready_no_reviews", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
