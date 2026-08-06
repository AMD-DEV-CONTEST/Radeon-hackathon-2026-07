from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .campaign_pack_blind_review import DIMENSIONS, REVIEW_ATTESTATION
from .files import atomic_write_text, sha256_file


KIT_SCHEMA = "ProofLaunchGTMUnifiedOfflineReviewKitV2"
GENERIC_REVIEW_SCHEMA = "ProofLaunchGTMGenericHumanBlindReviewV2"
VISUAL_REVIEW_SCHEMA = "ProofLaunchGTMVisualHumanBlindReviewV2"
AGGREGATE_SCHEMA = "ProofLaunchGTMUnifiedOfflineReviewAggregateV2"
GENERIC_ATTESTATION = (
    "I independently reviewed this identity-hidden same-brief pair without candidate, "
    "provider, model, private-mapping, or other-reviewer information."
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PAIR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,160}$")


class UnifiedOfflineReviewError(ValueError):
    pass


class UnifiedOfflineReviewConflictError(UnifiedOfflineReviewError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = sha256_json(payload)
    return sealed


def verify_seal(payload: object, *, schema: str, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise UnifiedOfflineReviewError(f"{label} schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied) or sha256_json(unsigned) != supplied:
        raise UnifiedOfflineReviewError(f"{label} digest is invalid")
    return payload


def generic_pair_sha256(pair: Mapping[str, Any]) -> str:
    binding = {
        "stream_id": pair.get("stream_id"),
        "lane_id": pair.get("lane_id"),
        "pair_id": pair.get("pair_id"),
        "scenario_id": pair.get("scenario_id"),
        "capability": pair.get("capability"),
        "left_blind_id": pair.get("left_blind_id"),
        "right_blind_id": pair.get("right_blind_id"),
        "left_sha256": pair.get("left_sha256"),
        "right_sha256": pair.get("right_sha256"),
    }
    return sha256_json(binding)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise UnifiedOfflineReviewError(f"unsafe or missing JSON input: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UnifiedOfflineReviewError(f"invalid JSON input: {path}") from error
    if not isinstance(payload, dict):
        raise UnifiedOfflineReviewError(f"JSON input must be an object: {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise UnifiedOfflineReviewError(f"unsafe or missing JSONL input: {path}")
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise UnifiedOfflineReviewError(f"invalid JSONL input: {path}") from error
    if any(not isinstance(row, dict) for row in rows):
        raise UnifiedOfflineReviewError("every review row must be an object")
    return rows


def validate_kit_manifest(payload: object, *, kit_root: Path | None = None) -> dict[str, Any]:
    manifest = verify_seal(payload, schema=KIT_SCHEMA, label="unified offline review kit")
    generic = manifest.get("generic_pairs")
    visual = manifest.get("visual_tasks")
    generic_commitments = manifest.get("generic_private_mapping_commitments")
    if (
        manifest.get("reviewer_page_count") != 5
        or manifest.get("pair_count_per_reviewer") != 16
        or manifest.get("expected_human_review_count") != 80
        or manifest.get("submitted_human_review_count") != 0
        or not isinstance(generic, list)
        or len(generic) != 15
        or not isinstance(visual, list)
        or len(visual) != 5
        or manifest.get("private_mapping_included") is not False
        or manifest.get("network_submission_enabled") is not False
        or manifest.get("automatic_promotion_enabled") is not False
        or manifest.get("automatic_publish_enabled") is not False
        or not isinstance(generic_commitments, dict)
        or set(generic_commitments) != {"text-decision", "audio", "video"}
        or any(not isinstance(value, str) or not _DIGEST.fullmatch(value) for value in generic_commitments.values())
        or not _DIGEST.fullmatch(str(manifest.get("visual_private_mapping_commitment", "")))
    ):
        raise UnifiedOfflineReviewError("unified offline review kit contract is incomplete")
    pair_ids: set[str] = set()
    lanes: set[str] = set()
    for pair in generic:
        if not isinstance(pair, dict):
            raise UnifiedOfflineReviewError("generic pair binding is invalid")
        pair_id = pair.get("pair_id")
        if (
            not isinstance(pair_id, str)
            or not _PAIR_ID.fullmatch(pair_id)
            or pair_id in pair_ids
            or not _DIGEST.fullmatch(str(pair.get("pair_sha256", "")))
            or pair.get("pair_sha256") != generic_pair_sha256(pair)
            or not isinstance(pair.get("lane_id"), str)
            or not pair["lane_id"]
        ):
            raise UnifiedOfflineReviewError("generic pair binding is invalid")
        pair_ids.add(pair_id)
        lanes.add(pair["lane_id"])
    visual_slots: set[int] = set()
    visual_tasks: set[str] = set()
    for task in visual:
        if not isinstance(task, dict):
            raise UnifiedOfflineReviewError("visual task binding is invalid")
        slot = task.get("reviewer_slot")
        task_id = task.get("review_task_id")
        if (
            type(slot) is not int
            or slot not in range(1, 6)
            or slot in visual_slots
            or not isinstance(task_id, str)
            or not _PAIR_ID.fullmatch(task_id)
            or task_id in visual_tasks
            or not _DIGEST.fullmatch(str(task.get("pair_sha256", "")))
        ):
            raise UnifiedOfflineReviewError("visual task binding is invalid")
        visual_slots.add(slot)
        visual_tasks.add(task_id)
    if visual_slots != set(range(1, 6)) or len(lanes | {"visual-system"}) != 14:
        raise UnifiedOfflineReviewError("review lane or visual slot coverage drifted")
    if kit_root is not None:
        root = kit_root.resolve(strict=True)
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise UnifiedOfflineReviewError("kit file inventory is missing")
        for relative, metadata in files.items():
            if not isinstance(relative, str) or not isinstance(metadata, dict):
                raise UnifiedOfflineReviewError("kit file inventory is invalid")
            path = (root / relative).resolve(strict=True)
            try:
                path.relative_to(root)
            except ValueError as error:
                raise UnifiedOfflineReviewError("kit file escaped its root") from error
            if path.is_symlink() or not path.is_file():
                raise UnifiedOfflineReviewError("kit file is missing or unsafe")
            if path.stat().st_size != metadata.get("bytes") or sha256_file(path) != metadata.get("sha256"):
                raise UnifiedOfflineReviewError("kit file integrity check failed")
    return manifest


def _validate_timestamp(value: object) -> None:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise UnifiedOfflineReviewError("review timestamp is invalid") from error
    if timestamp.tzinfo is None:
        raise UnifiedOfflineReviewError("review timestamp must include a timezone")


def _validate_delivery_fields(review: Mapping[str, Any]) -> None:
    for side in ("left", "right"):
        publishable = review.get(f"{side}_directly_publishable")
        major = review.get(f"{side}_major_rework")
        if type(publishable) is not bool or type(major) is not bool or (publishable and major):
            raise UnifiedOfflineReviewError("delivery status fields are inconsistent")
    defect = review.get("blocking_defect_side")
    reason = review.get("blocking_defect_reason")
    if defect not in {"none", "left", "right", "both"} or not isinstance(reason, str) or len(reason) > 1200:
        raise UnifiedOfflineReviewError("blocking-defect fields are invalid")
    if defect != "none" and len(reason.strip()) < 16:
        raise UnifiedOfflineReviewError("a blocking defect requires a located explanation")


def _validate_review_digest(review: Mapping[str, Any]) -> None:
    supplied = review.get("review_content_sha256")
    unsigned = dict(review)
    unsigned.pop("review_content_sha256", None)
    if not isinstance(supplied, str) or supplied != sha256_json(unsigned):
        raise UnifiedOfflineReviewError("review content digest is invalid")


def validate_generic_reviews(
    rows: list[dict[str, Any]], *, manifest: Mapping[str, Any], reviewer_slot: int
) -> list[dict[str, Any]]:
    bindings = {row["pair_id"]: row for row in manifest["generic_pairs"]}
    if len(rows) != 15 or {row.get("pair_id") for row in rows} != set(bindings):
        raise UnifiedOfflineReviewError("generic review file must contain exactly the fifteen assigned pairs")
    required = {
        "schema", "reviewer_slot", "pair_id", "pair_sha256", "choice",
        "reviewer_pseudonym", "human_attestation", "independent_attestation",
        "conflict_disclosed", "reviewed_at", "left_directly_publishable",
        "right_directly_publishable", "left_major_rework", "right_major_rework",
        "blocking_defect_side", "blocking_defect_reason", "rationale",
        "review_content_sha256",
    }
    normalized: list[dict[str, Any]] = []
    for review in rows:
        if set(review) != required or review.get("schema") != GENERIC_REVIEW_SCHEMA:
            raise UnifiedOfflineReviewError("generic review schema or fields are invalid")
        pair = bindings[review["pair_id"]]
        pseudonym = review.get("reviewer_pseudonym")
        rationale = review.get("rationale")
        if (
            review.get("reviewer_slot") != reviewer_slot
            or review.get("pair_sha256") != pair["pair_sha256"]
            or review.get("choice") not in {"left", "right", "abstain"}
            or review.get("human_attestation") != GENERIC_ATTESTATION
            or review.get("independent_attestation") is not True
            or review.get("conflict_disclosed") is not True
            or not isinstance(pseudonym, str)
            or not 3 <= len(pseudonym.strip()) <= 120
            or not isinstance(rationale, str)
            or not 20 <= len(rationale.strip()) <= 2000
        ):
            raise UnifiedOfflineReviewError("generic review contract is invalid")
        _validate_delivery_fields(review)
        _validate_timestamp(review.get("reviewed_at"))
        _validate_review_digest(review)
        normalized.append(dict(review))
    if len({row["reviewer_pseudonym"] for row in normalized}) != 1:
        raise UnifiedOfflineReviewConflictError("reviewer pseudonym drifted inside the generic review file")
    return sorted(normalized, key=lambda row: row["pair_id"])


def validate_visual_review(
    review: dict[str, Any], *, manifest: Mapping[str, Any], reviewer_slot: int
) -> dict[str, Any]:
    required = {
        "schema", "review_task_id", "pair_id", "pair_sha256", "reviewer_slot",
        "reviewer_pseudonym", "human_attestation", "overall_winner",
        "dimension_winners", "left_directly_publishable", "right_directly_publishable",
        "left_major_rework", "right_major_rework", "blocking_defect_side",
        "blocking_defect_reason", "notes", "reviewed_at", "review_content_sha256",
    }
    if set(review) != required or review.get("schema") != VISUAL_REVIEW_SCHEMA:
        raise UnifiedOfflineReviewError("visual review schema or fields are invalid")
    task = next((row for row in manifest["visual_tasks"] if row["reviewer_slot"] == reviewer_slot), None)
    dimensions = review.get("dimension_winners")
    pseudonym = review.get("reviewer_pseudonym")
    notes = review.get("notes")
    if (
        task is None
        or review.get("review_task_id") != task["review_task_id"]
        or review.get("pair_id") != task["pair_id"]
        or review.get("pair_sha256") != task["pair_sha256"]
        or review.get("reviewer_slot") != reviewer_slot
        or review.get("human_attestation") != REVIEW_ATTESTATION
        or review.get("overall_winner") not in {"left", "right"}
        or not isinstance(dimensions, dict)
        or set(dimensions) != set(DIMENSIONS)
        or any(value not in {"left", "right", "tie"} for value in dimensions.values())
        or not isinstance(pseudonym, str)
        or not 3 <= len(pseudonym.strip()) <= 120
        or not isinstance(notes, str)
        or not 24 <= len(notes.strip()) <= 2000
    ):
        raise UnifiedOfflineReviewError("visual review contract is invalid")
    _validate_delivery_fields(review)
    _validate_timestamp(review.get("reviewed_at"))
    _validate_review_digest(review)
    return dict(review)


def _wilson_lower(successes: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator


def _load_generic_mappings(paths: list[Path]) -> dict[str, dict[str, Any]]:
    mappings: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = _load_json(path)
        if payload.get("schema") != "ProofLaunchPrivateBlindRoleMappingV1" or not isinstance(payload.get("pairs"), list):
            raise UnifiedOfflineReviewError("generic private role mapping is invalid")
        for pair in payload["pairs"]:
            if not isinstance(pair, dict) or pair.get("candidate_side") not in {"left", "right"}:
                raise UnifiedOfflineReviewError("generic private role mapping is malformed")
            pair_id = pair.get("pair_id")
            if not isinstance(pair_id, str) or pair_id in mappings:
                raise UnifiedOfflineReviewError("generic private pair mapping is duplicated")
            mappings[pair_id] = pair
    return mappings


def _pair_result(
    *, comparison_id: str, lane_id: str, stream_id: str, candidate_id: str,
    candidate_side_by_slot: Mapping[int, str], reviews: list[dict[str, Any]], gate: Mapping[str, Any]
) -> dict[str, Any]:
    total = len(reviews)
    preference = publishable = major = blocking = 0
    bindings: list[dict[str, Any]] = []
    for review in reviews:
        slot = int(review["reviewer_slot"])
        side = candidate_side_by_slot[slot]
        if review.get("choice", review.get("overall_winner")) == side:
            preference += 1
        if review[f"{side}_directly_publishable"]:
            publishable += 1
        if review[f"{side}_major_rework"]:
            major += 1
        if review["blocking_defect_side"] in {side, "both"}:
            blocking += 1
        bindings.append({
            "reviewer_slot": slot,
            "review_content_sha256": review["review_content_sha256"],
        })
    preference_rate = preference / total if total else 0.0
    publishable_rate = publishable / total if total else 0.0
    major_rate = major / total if total else 1.0
    wilson = _wilson_lower(preference, total)
    checks = {
        "reviewer_count": total >= int(gate["minimum_reviewers_per_pair"]),
        "candidate_preference_rate": preference_rate >= float(gate["minimum_candidate_preference_rate"]),
        "wilson_lower_95": wilson > float(gate["minimum_wilson_lower_95_exclusive"]),
        "candidate_publishable_rate": publishable_rate >= float(gate["minimum_candidate_publishable_rate"]),
        "candidate_major_rework_rate": major_rate <= float(gate["maximum_candidate_major_rework_rate"]),
        "candidate_blocking_defects": blocking <= int(gate["blocking_defects_allowed"]),
    }
    return {
        "comparison_id": comparison_id,
        "lane_id": lane_id,
        "stream_id": stream_id,
        "candidate_id": candidate_id,
        "review_count": total,
        "candidate_preference_votes": preference,
        "candidate_preference_rate": round(preference_rate, 6),
        "candidate_preference_wilson_lower_95": round(wilson, 6),
        "candidate_publishable_rate": round(publishable_rate, 6),
        "candidate_major_rework_rate": round(major_rate, 6),
        "candidate_blocking_defect_count": blocking,
        "gate_checks": checks,
        "gate_passed": all(checks.values()),
        "review_bindings": sorted(bindings, key=lambda row: row["reviewer_slot"]),
    }


class UnifiedOfflineReviewService:
    def __init__(
        self,
        *,
        kit_root: Path,
        store_root: Path,
        generic_mapping_paths: list[Path],
        visual_private_path: Path,
        unified_review_path: Path,
    ) -> None:
        self.kit_root = kit_root.resolve(strict=True)
        self.manifest_path = self.kit_root / "manifest.json"
        self.manifest = validate_kit_manifest(_load_json(self.manifest_path), kit_root=self.kit_root)
        self.store_root = store_root.resolve()
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.generic_mappings = _load_generic_mappings(generic_mapping_paths)
        expected_mapping_digests = set(self.manifest["generic_private_mapping_commitments"].values())
        if {sha256_file(path) for path in generic_mapping_paths} != expected_mapping_digests:
            raise UnifiedOfflineReviewError("generic private mapping commitment drifted")
        expected_pairs = {row["pair_id"] for row in self.manifest["generic_pairs"]}
        if set(self.generic_mappings) != expected_pairs:
            raise UnifiedOfflineReviewError("generic private mappings do not exactly cover the offline kit")
        visual_private = _load_json(visual_private_path)
        if visual_private.get("schema") != "ProofLaunchCampaignPackVisualBlindReviewPrivateV1":
            raise UnifiedOfflineReviewError("visual private mapping is invalid")
        if sha256_file(visual_private_path) != self.manifest.get("visual_private_mapping_commitment"):
            raise UnifiedOfflineReviewError("visual private mapping commitment drifted")
        self.visual_mapping = visual_private.get("private_core", {}).get("task_side_mapping", {})
        expected_tasks = {row["review_task_id"] for row in self.manifest["visual_tasks"]}
        if set(self.visual_mapping) != expected_tasks:
            raise UnifiedOfflineReviewError("visual private mappings do not exactly cover the offline kit")
        self.unified = verify_seal(
            _load_json(unified_review_path),
            schema="ProofLaunchGTMUnifiedLastMileReviewV1",
            label="unified review contract",
        )
        if self.manifest["source_unified_review_sha256"] != sha256_file(unified_review_path):
            raise UnifiedOfflineReviewError("offline kit is not bound to the unified review contract")
        self.aggregate_path = self.store_root / "aggregate.json"

    def _slot_path(self, slot: int) -> Path:
        return self.store_root / f"reviewer-{slot:02d}.json"

    def _load_bundles(self) -> list[dict[str, Any]]:
        bundles: list[dict[str, Any]] = []
        for path in sorted(self.store_root.glob("reviewer-*.json")):
            if path.is_symlink() or not path.is_file():
                raise UnifiedOfflineReviewError("review store contains an unsafe entry")
            bundle = _load_json(path)
            supplied = bundle.get("content_sha256")
            unsigned = dict(bundle)
            unsigned.pop("content_sha256", None)
            required = {
                "schema", "reviewer_slot", "reviewer_pseudonym", "generic_review_count",
                "visual_review_count", "review_count", "generic_reviews", "visual_review",
                "content_sha256",
            }
            slot = bundle.get("reviewer_slot")
            pseudonym = bundle.get("reviewer_pseudonym")
            if (
                set(bundle) != required
                or bundle.get("schema") != "ProofLaunchGTMUnifiedReviewerBundleV2"
                or supplied != sha256_json(unsigned)
                or type(slot) is not int
                or slot not in range(1, 6)
                or path != self._slot_path(slot)
                or bundle.get("generic_review_count") != 15
                or bundle.get("visual_review_count") != 1
                or bundle.get("review_count") != 16
                or not isinstance(bundle.get("generic_reviews"), list)
                or not isinstance(bundle.get("visual_review"), dict)
            ):
                raise UnifiedOfflineReviewError("persisted reviewer bundle is invalid")
            generic = validate_generic_reviews(
                bundle["generic_reviews"], manifest=self.manifest, reviewer_slot=slot
            )
            visual = validate_visual_review(
                bundle["visual_review"], manifest=self.manifest, reviewer_slot=slot
            )
            if generic[0]["reviewer_pseudonym"] != pseudonym or visual["reviewer_pseudonym"] != pseudonym:
                raise UnifiedOfflineReviewConflictError("persisted reviewer identity drifted")
            bundles.append(bundle)
        if len({row["reviewer_slot"] for row in bundles}) != len(bundles) or len(
            {row["reviewer_pseudonym"] for row in bundles}
        ) != len(bundles):
            raise UnifiedOfflineReviewConflictError("persisted reviewer slots or identities are duplicated")
        return bundles

    def import_reviewer(self, *, generic_reviews_path: Path, visual_review_path: Path) -> dict[str, Any]:
        generic_raw = _load_jsonl(generic_reviews_path)
        visual_raw = _load_json(visual_review_path)
        slot = visual_raw.get("reviewer_slot")
        if type(slot) is not int or slot not in range(1, 6):
            raise UnifiedOfflineReviewError("reviewer slot must be in [1, 5]")
        generic = validate_generic_reviews(generic_raw, manifest=self.manifest, reviewer_slot=slot)
        visual = validate_visual_review(visual_raw, manifest=self.manifest, reviewer_slot=slot)
        pseudonym = generic[0]["reviewer_pseudonym"]
        if visual["reviewer_pseudonym"] != pseudonym:
            raise UnifiedOfflineReviewConflictError("reviewer identity drifted between generic and visual files")
        bundle = seal({
            "schema": "ProofLaunchGTMUnifiedReviewerBundleV2",
            "reviewer_slot": slot,
            "reviewer_pseudonym": pseudonym,
            "generic_review_count": len(generic),
            "visual_review_count": 1,
            "review_count": 16,
            "generic_reviews": generic,
            "visual_review": visual,
        })
        path = self._slot_path(slot)
        existing_bundles = self._load_bundles()
        for existing in existing_bundles:
            if existing["reviewer_slot"] != slot and existing["reviewer_pseudonym"] == pseudonym:
                raise UnifiedOfflineReviewConflictError("one reviewer pseudonym cannot occupy multiple slots")
        if path.exists():
            existing = _load_json(path)
            if canonical_json_bytes(existing) != canonical_json_bytes(bundle):
                raise UnifiedOfflineReviewConflictError("reviewer bundle is immutable")
            idempotent = True
        else:
            atomic_write_text(path, json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            path.chmod(0o600)
            idempotent = False
        status = self.status()
        if status["review_complete"]:
            self.aggregate()
        return {"schema": "ProofLaunchGTMUnifiedReviewerImportReceiptV2", "idempotent": idempotent, **status}

    def _compute_aggregate(self, bundles: list[dict[str, Any]]) -> dict[str, Any]:
        gate = self.unified["predeclared_gate"]
        generic_by_pair: dict[str, list[dict[str, Any]]] = {row["pair_id"]: [] for row in self.manifest["generic_pairs"]}
        visual_reviews: list[dict[str, Any]] = []
        for bundle in bundles:
            for review in bundle["generic_reviews"]:
                generic_by_pair[review["pair_id"]].append(review)
            visual_reviews.append(bundle["visual_review"])
        results: list[dict[str, Any]] = []
        for binding in self.manifest["generic_pairs"]:
            mapping = self.generic_mappings[binding["pair_id"]]
            results.append(_pair_result(
                comparison_id=binding["pair_id"],
                lane_id=binding["lane_id"],
                stream_id=binding["stream_id"],
                candidate_id=mapping["candidate_id"],
                candidate_side_by_slot={slot: mapping["candidate_side"] for slot in range(1, 6)},
                reviews=generic_by_pair[binding["pair_id"]],
                gate=gate,
            ))
        visual_candidate = "campaign-pack-v6"
        visual_sides = {
            int(review["reviewer_slot"]): next(
                side for side, candidate in self.visual_mapping[review["review_task_id"]].items()
                if candidate == visual_candidate
            )
            for review in visual_reviews
        }
        results.append(_pair_result(
            comparison_id="visual-system",
            lane_id="visual-system",
            stream_id="visual-system",
            candidate_id=visual_candidate,
            candidate_side_by_slot=visual_sides,
            reviews=visual_reviews,
            gate=gate,
        ))
        lane_results = []
        for lane_id in sorted({row["lane_id"] for row in results}):
            pair_results = [row for row in results if row["lane_id"] == lane_id]
            lane_results.append({
                "lane_id": lane_id,
                "pair_count": len(pair_results),
                "passed_pair_count": sum(1 for row in pair_results if row["gate_passed"]),
                "gate_passed": all(row["gate_passed"] for row in pair_results),
            })
        recommendation = len(results) == 16 and len(lane_results) == 14 and all(row["gate_passed"] for row in results)
        return seal({
            "schema": AGGREGATE_SCHEMA,
            "kit_manifest_sha256": sha256_file(self.manifest_path),
            "source_unified_review_sha256": self.manifest["source_unified_review_sha256"],
            "review_complete": True,
            "submitted_human_review_count": 80,
            "distinct_reviewer_count": 5,
            "comparison_pair_count": 16,
            "lane_count": 14,
            "predeclared_gate": gate,
            "pair_results": sorted(results, key=lambda row: row["comparison_id"]),
            "lane_results": lane_results,
            "promotion_recommendation_eligible": recommendation,
            "failed_lane_action": "repair_and_rerun_same_brief",
            "automatic_runtime_switch_enabled": False,
            "automatic_strategy_mutation_enabled": False,
            "automatic_publish_enabled": False,
            "automatic_send_enabled": False,
            "automatic_spend_enabled": False,
            "named_product_baselines_present": False,
            "four_a_quality_proven": False,
            "top_product_effect_parity_proven": False,
            "causal_business_effect_proven": False,
            "truth_boundary": (
                "A passing aggregate is a qualified-human preference recommendation over the sealed "
                "internal same-brief opponents only. It cannot prove named-product parity, 4A quality, "
                "publication, causal lift, or revenue and cannot trigger an external action."
            ),
        })

    def aggregate(self) -> dict[str, Any]:
        bundles = self._load_bundles()
        if len(bundles) != 5 or {row["reviewer_slot"] for row in bundles} != set(range(1, 6)):
            raise UnifiedOfflineReviewConflictError("aggregate is unavailable until all five reviewer bundles are complete")
        aggregate = self._compute_aggregate(bundles)
        if self.aggregate_path.exists():
            existing = _load_json(self.aggregate_path)
            if canonical_json_bytes(existing) != canonical_json_bytes(aggregate):
                raise UnifiedOfflineReviewConflictError("aggregate drifted after sealing")
        else:
            atomic_write_text(self.aggregate_path, json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            self.aggregate_path.chmod(0o600)
        return aggregate

    def status(self) -> dict[str, Any]:
        bundles = self._load_bundles()
        slots = {int(row["reviewer_slot"]) for row in bundles}
        complete = len(bundles) == 5 and slots == set(range(1, 6))
        return {
            "kit_manifest_sha256": sha256_file(self.manifest_path),
            "expected_human_review_count": 80,
            "submitted_human_review_count": len(bundles) * 16,
            "remaining_human_review_count": 80 - len(bundles) * 16,
            "distinct_reviewer_count": len({row["reviewer_pseudonym"] for row in bundles}),
            "review_complete": complete,
            "promotion_recommendation_eligible": bool(complete and self._compute_aggregate(bundles)["promotion_recommendation_eligible"]),
            "automatic_external_actions": 0,
        }
