from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from .files import atomic_write_bytes, atomic_write_text, sha256_file
from .gtm_effect_eval import (
    BlindPair,
    Deliverable,
    DeliverableRole,
    EffectContractError,
    build_blind_pair,
)
from .quality_contract import wilson_lower_bound


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in {
        ".json",
        ".txt",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".mp4",
        ".webm",
        ".wav",
        ".mp3",
        ".pdf",
    }:
        raise EffectContractError(f"unsupported blind-review artifact type: {suffix}")
    return suffix


@dataclass(frozen=True)
class PacketArtifact:
    """A local artifact bound to one candidate/baseline comparison key."""

    deliverable: Deliverable
    source_path: str
    comparison_key: str

    def validate(self) -> Path:
        if not self.comparison_key.strip():
            raise EffectContractError("comparison_key is required")
        failures = self.deliverable.structural_failures()
        if failures:
            raise EffectContractError("; ".join(failures))
        path = Path(self.source_path).resolve()
        if not path.is_file():
            raise EffectContractError(f"blind-review source is missing: {path}")
        _safe_suffix(path)
        if sha256_file(path) != self.deliverable.content_sha256:
            raise EffectContractError(
                f"content hash mismatch for {self.deliverable.deliverable_id}"
            )
        return path


@dataclass(frozen=True)
class EffectReviewPacket:
    root: str
    manifest_path: str
    public_pairs_path: str
    private_mapping_path: str
    pair_count: int
    reviewer_count: int
    packet_sha256: str


@dataclass(frozen=True)
class EffectReviewVerificationReport:
    complete: bool
    effect_promotion_passed: bool
    pair_count: int
    reviewer_count: int
    completed_vote_count: int
    resolved_vote_count: int
    candidate_preferred_count: int
    candidate_preference_rate: float | None
    candidate_preference_wilson_lower_95: float | None
    candidate_publishable_rate: float | None
    candidate_major_rework_rate: float | None
    abstention_rate: float | None
    failures: tuple[str, ...]
    packet_sha256: str | None
    truth_boundary: str = (
        "A passing receipt proves only the declared blinded human-review gate for the "
        "content-addressed packet. It is not causal revenue lift, universal superiority, "
        "Top-1 standing, production publication, or Radeon-local inference evidence."
    )
    schema: str = "ProofLaunchEffectReviewVerificationReportV1"


class EffectReviewPacketBuilder:
    """Materialize role-blind review assets and empty human review templates.

    The private randomization key is used in-memory only. Candidate/baseline
    identities and rights locators are written exclusively to the private map;
    reviewer files contain no pre-filled votes or model-generated judgements.
    """

    def build(
        self,
        artifacts: Sequence[PacketArtifact],
        output_dir: str | Path,
        *,
        randomization_key: str,
        reviewer_count: int = 3,
    ) -> EffectReviewPacket:
        if not randomization_key.strip() or len(randomization_key) < 16:
            raise EffectContractError(
                "randomization_key must be a private value of at least 16 characters"
            )
        if type(reviewer_count) is not int or not 2 <= reviewer_count <= 9:
            raise EffectContractError("reviewer_count must be an integer in [2, 9]")
        if not artifacts:
            raise EffectContractError("at least one comparison is required")

        root = Path(output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise EffectContractError("review packet output directory must be empty")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        public_root = root / "public"
        assets_root = public_root / "assets"
        reviewer_root = public_root / "reviewers"
        private_root = root / "private"
        for directory in (public_root, assets_root, reviewer_root, private_root):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)

        grouped: dict[tuple[str, str, str], list[tuple[PacketArtifact, Path]]] = {}
        ids: set[str] = set()
        for item in artifacts:
            if item.deliverable.deliverable_id in ids:
                raise EffectContractError(
                    f"duplicate deliverable_id: {item.deliverable.deliverable_id}"
                )
            ids.add(item.deliverable.deliverable_id)
            source = item.validate()
            key = (
                item.deliverable.capability.value,
                item.deliverable.scenario_id,
                item.comparison_key,
            )
            grouped.setdefault(key, []).append((item, source))

        pairs: list[BlindPair] = []
        public_rows: list[dict[str, object]] = []
        private_rows: list[dict[str, object]] = []
        compared_content: set[tuple[str, str]] = set()
        for key, entries in sorted(grouped.items()):
            candidates = [
                entry for entry in entries
                if entry[0].deliverable.role is DeliverableRole.CANDIDATE
            ]
            baselines = [
                entry for entry in entries
                if entry[0].deliverable.role is DeliverableRole.BASELINE
            ]
            if len(candidates) != 1 or len(baselines) != 1 or len(entries) != 2:
                raise EffectContractError(
                    f"comparison {key} requires exactly one candidate and one baseline"
                )
            (candidate_item, candidate_source) = candidates[0]
            (baseline_item, baseline_source) = baselines[0]
            content_pair = (
                candidate_item.deliverable.content_sha256,
                baseline_item.deliverable.content_sha256,
            )
            if content_pair in compared_content:
                raise EffectContractError("duplicate content pair cannot inflate review size")
            compared_content.add(content_pair)
            pair_seed = _canonical_json(
                {
                    "capability": key[0],
                    "scenario_id": key[1],
                    "comparison_key": key[2],
                    "candidate_sha256": content_pair[0],
                    "baseline_sha256": content_pair[1],
                }
            )
            pair_id = f"pair-{hashlib.sha256(pair_seed.encode('utf-8')).hexdigest()[:24]}"
            pair = build_blind_pair(
                pair_id=pair_id,
                candidate=candidate_item.deliverable,
                baseline=baseline_item.deliverable,
                randomization_key=randomization_key,
            )
            pairs.append(pair)
            candidate_public = self._copy_blind_asset(
                assets_root,
                candidate_source,
                pair.left_blind_id
                if pair.candidate_side.value == "left"
                else pair.right_blind_id,
            )
            baseline_public = self._copy_blind_asset(
                assets_root,
                baseline_source,
                pair.right_blind_id
                if pair.candidate_side.value == "left"
                else pair.left_blind_id,
            )
            if pair.candidate_side.value == "left":
                left_asset, right_asset = candidate_public, baseline_public
            else:
                left_asset, right_asset = baseline_public, candidate_public
            public_rows.append(
                {
                    **pair.public_packet(),
                    "left_artifact": left_asset,
                    "right_artifact": right_asset,
                    "choice": None,
                    "rationale": None,
                }
            )
            private_rows.append(
                {
                    **asdict(pair),
                    "candidate_side": pair.candidate_side.value,
                    "comparison_key": key[2],
                    "candidate": self._private_deliverable(candidate_item.deliverable),
                    "baseline": self._private_deliverable(baseline_item.deliverable),
                }
            )

        public_pairs_path = public_root / "blind-pairs.jsonl"
        atomic_write_text(
            public_pairs_path,
            "".join(f"{_canonical_json(row)}\n" for row in public_rows),
        )
        public_pairs_path.chmod(0o600)
        for reviewer_slot in range(1, reviewer_count + 1):
            template_path = reviewer_root / f"reviewer-{reviewer_slot:02d}.jsonl"
            templates = [
                {
                    "schema": "ProofLaunchBlindPreferenceVoteTemplateV1",
                    "reviewer_slot": reviewer_slot,
                    "pair_id": row["pair_id"],
                    "choice": None,
                    "rater_id": None,
                    "independent_attestation": None,
                    "conflict_disclosed": None,
                    "reviewed_at": None,
                    "left_directly_publishable": None,
                    "right_directly_publishable": None,
                    "left_major_rework": None,
                    "right_major_rework": None,
                    "rationale": None,
                }
                for row in public_rows
            ]
            atomic_write_text(
                template_path,
                "".join(f"{_canonical_json(row)}\n" for row in templates),
            )
            template_path.chmod(0o600)

        private_mapping_path = private_root / "role-mapping.json"
        private_payload = {
            "schema": "ProofLaunchPrivateBlindRoleMappingV1",
            "randomization_key_persisted": False,
            "pairs": private_rows,
        }
        atomic_write_text(
            private_mapping_path,
            json.dumps(private_payload, ensure_ascii=False, indent=2, sort_keys=True),
        )
        private_mapping_path.chmod(0o600)

        manifest = {
            "schema": "ProofLaunchEffectReviewPacketManifestV1",
            "pair_count": len(pairs),
            "reviewer_count": reviewer_count,
            "capabilities": sorted({pair.capability.value for pair in pairs}),
            "scenarios": sorted({pair.scenario_id for pair in pairs}),
            "public_pairs_sha256": sha256_file(public_pairs_path),
            "private_mapping_sha256": sha256_file(private_mapping_path),
            "randomization_key_persisted": False,
            "review_votes_completed": 0,
            "effect_promotion_passed": False,
            "truth_boundary": (
                "This packet randomizes and blinds content-addressed artifacts. Empty "
                "review templates are not human observations and provide no 4A, causal, "
                "production-lift, Top-1, or universal superiority evidence."
            ),
        }
        packet_sha256 = hashlib.sha256(
            _canonical_json(manifest).encode("utf-8")
        ).hexdigest()
        manifest["packet_sha256"] = packet_sha256
        manifest_path = root / "manifest.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        )
        manifest_path.chmod(0o600)
        return EffectReviewPacket(
            root=str(root),
            manifest_path=str(manifest_path),
            public_pairs_path=str(public_pairs_path),
            private_mapping_path=str(private_mapping_path),
            pair_count=len(pairs),
            reviewer_count=reviewer_count,
            packet_sha256=packet_sha256,
        )

    @staticmethod
    def _copy_blind_asset(root: Path, source: Path, blind_id: str) -> str:
        destination = root / f"{blind_id}{_safe_suffix(source)}"
        if destination.exists():
            raise EffectContractError("blind asset identity collision")
        atomic_write_bytes(destination, source.read_bytes())
        destination.chmod(0o600)
        return f"assets/{destination.name}"

    @staticmethod
    def _private_deliverable(item: Deliverable) -> dict[str, object]:
        payload = asdict(item)
        payload["capability"] = item.capability.value
        payload["role"] = item.role.value
        return payload


class EffectReviewPacketVerifier:
    """Fail closed when review templates are empty, duplicated, or deblinded early."""

    def __init__(
        self,
        *,
        minimum_reviewers_per_pair: int = 3,
        minimum_candidate_preference_rate: float = 0.75,
        minimum_wilson_lower_95_exclusive: float = 0.50,
        minimum_candidate_publishable_rate: float = 0.95,
        maximum_candidate_major_rework_rate: float = 0.05,
        maximum_abstention_rate: float = 0.20,
    ) -> None:
        if minimum_reviewers_per_pair < 3:
            raise EffectContractError("at least three independent reviewers are required")
        self.minimum_reviewers_per_pair = minimum_reviewers_per_pair
        self.minimum_candidate_preference_rate = minimum_candidate_preference_rate
        self.minimum_wilson_lower_95_exclusive = minimum_wilson_lower_95_exclusive
        self.minimum_candidate_publishable_rate = minimum_candidate_publishable_rate
        self.maximum_candidate_major_rework_rate = maximum_candidate_major_rework_rate
        self.maximum_abstention_rate = maximum_abstention_rate

    def verify(self, packet_root: str | Path) -> EffectReviewVerificationReport:
        root = Path(packet_root).resolve()
        failures: list[str] = []
        manifest_path = root / "manifest.json"
        public_path = root / "public" / "blind-pairs.jsonl"
        private_path = root / "private" / "role-mapping.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise EffectContractError(f"invalid review packet manifest: {error}") from error

        packet_sha256 = manifest.get("packet_sha256")
        unhashed_manifest = dict(manifest)
        unhashed_manifest.pop("packet_sha256", None)
        expected_packet_sha256 = hashlib.sha256(
            _canonical_json(unhashed_manifest).encode("utf-8")
        ).hexdigest()
        if packet_sha256 != expected_packet_sha256:
            failures.append("manifest packet_sha256 mismatch")
        for label, path, digest in (
            ("public pairs", public_path, manifest.get("public_pairs_sha256")),
            ("private mapping", private_path, manifest.get("private_mapping_sha256")),
        ):
            if not path.is_file() or digest != sha256_file(path):
                failures.append(f"{label} hash mismatch")

        public_rows = self._read_jsonl(public_path, "public blind pairs", failures)
        try:
            private_payload = json.loads(private_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            private_payload = {}
            failures.append("private role mapping is invalid")
        private_rows = private_payload.get("pairs", [])
        if not isinstance(private_rows, list):
            private_rows = []
            failures.append("private role mapping pairs are invalid")

        public_by_id = self._index_unique(public_rows, "pair_id", "public pair", failures)
        private_by_id = self._index_unique(private_rows, "pair_id", "private pair", failures)
        declared_pair_count = manifest.get("pair_count")
        if declared_pair_count != len(public_by_id) or set(public_by_id) != set(private_by_id):
            failures.append("public/private pair inventory mismatch")

        reviewer_root = root / "public" / "reviewers"
        review_paths = sorted(reviewer_root.glob("reviewer-*.jsonl"))
        if len(review_paths) != manifest.get("reviewer_count"):
            failures.append("reviewer file count mismatch")

        all_reviews: list[dict[str, object]] = []
        seen_raters: set[str] = set()
        for slot, review_path in enumerate(review_paths, start=1):
            rows = self._read_jsonl(review_path, review_path.name, failures)
            by_pair = self._index_unique(rows, "pair_id", review_path.name, failures)
            if set(by_pair) != set(public_by_id):
                failures.append(f"{review_path.name}: pair coverage mismatch")
            slot_raters = {
                row["rater_id"].strip()
                for row in rows
                if isinstance(row.get("rater_id"), str)
                and row["rater_id"].strip()
            }
            if len(slot_raters) != 1:
                failures.append(f"{review_path.name}: exactly one stable rater_id is required")
            else:
                rater_id = next(iter(slot_raters))
                if rater_id in seen_raters:
                    failures.append(f"duplicate rater_id across reviewer files: {rater_id}")
                seen_raters.add(rater_id)
            for row in rows:
                if row.get("reviewer_slot") != slot:
                    failures.append(f"{review_path.name}: reviewer_slot mismatch")
                failures.extend(self._row_failures(row, review_path.name))
            all_reviews.extend(rows)

        completed_vote_count = len(all_reviews)
        expected_votes = len(public_by_id) * len(review_paths)
        if completed_vote_count != expected_votes:
            failures.append("completed vote inventory mismatch")

        resolved_vote_count = 0
        candidate_preferred_count = 0
        candidate_publishable_count = 0
        candidate_major_rework_count = 0
        abstentions = 0
        candidate_rating_count = 0
        votes_by_pair: dict[str, list[dict[str, object]]] = {
            pair_id: [] for pair_id in public_by_id
        }
        for row in all_reviews:
            pair_id = str(row.get("pair_id", ""))
            if pair_id in votes_by_pair:
                votes_by_pair[pair_id].append(row)
            choice = row.get("choice")
            if choice == "abstain":
                abstentions += 1
            elif choice in {"left", "right"}:
                resolved_vote_count += 1
                private = private_by_id.get(pair_id, {})
                candidate_side = private.get("candidate_side")
                if choice == candidate_side:
                    candidate_preferred_count += 1
            private = private_by_id.get(pair_id, {})
            candidate_side = private.get("candidate_side")
            if candidate_side in {"left", "right"}:
                candidate_rating_count += 1
                candidate_publishable_count += row.get(
                    f"{candidate_side}_directly_publishable"
                ) is True
                candidate_major_rework_count += row.get(
                    f"{candidate_side}_major_rework"
                ) is True

        for pair_id, rows in votes_by_pair.items():
            eligible_raters = {
                str(row.get("rater_id"))
                for row in rows
                if row.get("independent_attestation") is True
                and row.get("conflict_disclosed") is True
            }
            if len(eligible_raters) < self.minimum_reviewers_per_pair:
                failures.append(
                    f"{pair_id}: fewer than {self.minimum_reviewers_per_pair} independent reviewers"
                )

        preference_rate = (
            candidate_preferred_count / resolved_vote_count
            if resolved_vote_count else None
        )
        preference_lower = (
            wilson_lower_bound(candidate_preferred_count, resolved_vote_count)
            if resolved_vote_count else None
        )
        publishable_rate = (
            candidate_publishable_count / candidate_rating_count
            if candidate_rating_count else None
        )
        major_rework_rate = (
            candidate_major_rework_count / candidate_rating_count
            if candidate_rating_count else None
        )
        abstention_rate = (
            abstentions / completed_vote_count if completed_vote_count else None
        )
        metric_checks = (
            (preference_rate is not None and preference_rate >= self.minimum_candidate_preference_rate,
             "candidate preference rate below threshold"),
            (preference_lower is not None and preference_lower > self.minimum_wilson_lower_95_exclusive,
             "candidate preference Wilson lower bound did not clear threshold"),
            (publishable_rate is not None and publishable_rate >= self.minimum_candidate_publishable_rate,
             "candidate directly-publishable rate below threshold"),
            (major_rework_rate is not None and major_rework_rate <= self.maximum_candidate_major_rework_rate,
             "candidate major-rework rate above threshold"),
            (abstention_rate is not None and abstention_rate <= self.maximum_abstention_rate,
             "abstention rate above threshold"),
        )
        for passed, reason in metric_checks:
            if not passed:
                failures.append(reason)

        failures = list(dict.fromkeys(failures))
        complete = not any(
            "threshold" not in failure and "rate above" not in failure
            for failure in failures
        )
        promoted = complete and not failures
        return EffectReviewVerificationReport(
            complete=complete,
            effect_promotion_passed=promoted,
            pair_count=len(public_by_id),
            reviewer_count=len(seen_raters),
            completed_vote_count=completed_vote_count,
            resolved_vote_count=resolved_vote_count,
            candidate_preferred_count=candidate_preferred_count,
            candidate_preference_rate=preference_rate,
            candidate_preference_wilson_lower_95=preference_lower,
            candidate_publishable_rate=publishable_rate,
            candidate_major_rework_rate=major_rework_rate,
            abstention_rate=abstention_rate,
            failures=tuple(failures),
            packet_sha256=packet_sha256 if isinstance(packet_sha256, str) else None,
        )

    @staticmethod
    def _read_jsonl(
        path: Path,
        label: str,
        failures: list[str],
    ) -> list[dict[str, object]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            failures.append(f"{label} is missing")
            return []
        rows: list[dict[str, object]] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"{label}:{line_number}: invalid JSON")
                continue
            if not isinstance(value, dict):
                failures.append(f"{label}:{line_number}: row must be an object")
                continue
            rows.append(value)
        return rows

    @staticmethod
    def _index_unique(
        rows: Sequence[Mapping[str, object]],
        key: str,
        label: str,
        failures: list[str],
    ) -> dict[str, Mapping[str, object]]:
        indexed: dict[str, Mapping[str, object]] = {}
        for row in rows:
            value = str(row.get(key, "")).strip()
            if not value:
                failures.append(f"{label}: {key} is required")
            elif value in indexed:
                failures.append(f"{label}: duplicate {key} {value}")
            else:
                indexed[value] = row
        return indexed

    @staticmethod
    def _row_failures(row: Mapping[str, object], label: str) -> list[str]:
        failures: list[str] = []
        choice = row.get("choice")
        if choice not in {"left", "right", "abstain"}:
            failures.append(f"{label}: choice must be left, right, or abstain")
        if row.get("independent_attestation") is not True:
            failures.append(f"{label}: independent_attestation must be true")
        if row.get("conflict_disclosed") is not True:
            failures.append(f"{label}: conflict_disclosed must be true")
        for field in (
            "left_directly_publishable",
            "right_directly_publishable",
            "left_major_rework",
            "right_major_rework",
        ):
            if not isinstance(row.get(field), bool):
                failures.append(f"{label}: {field} must be boolean")
        for side in ("left", "right"):
            if row.get(f"{side}_directly_publishable") is True and row.get(
                f"{side}_major_rework"
            ) is True:
                failures.append(f"{label}: {side} cannot be publishable and major rework")
        rationale = row.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 20:
            failures.append(f"{label}: rationale must contain at least 20 characters")
        reviewed_at = row.get("reviewed_at")
        if not isinstance(reviewed_at, str):
            failures.append(f"{label}: reviewed_at must be an aware ISO-8601 timestamp")
        else:
            try:
                parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
                failures.append(f"{label}: reviewed_at must be an aware ISO-8601 timestamp")
        return failures
