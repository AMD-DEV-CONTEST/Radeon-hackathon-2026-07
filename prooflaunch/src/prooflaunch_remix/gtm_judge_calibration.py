from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .files import atomic_write_text
from .gtm_effect_eval import JudgeCalibration


PUBLIC_NAME = "judge-calibration-public.json"
PRIVATE_NAME = "judge-calibration-private.json"
AGGREGATE_NAME = "judge-calibration-aggregate.json"
HUMAN_ATTESTATION = (
    "I personally evaluated this blinded case without access to the model-judge "
    "prediction, provider identity, private mapping, or another reviewer's label."
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^judge-cal-[0-9a-f]{20}-reviewer-[1-5]$")


class JudgeCalibrationError(ValueError):
    pass


class JudgeCalibrationAuthorizationError(JudgeCalibrationError):
    pass


class JudgeCalibrationConflictError(JudgeCalibrationError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bounded(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise JudgeCalibrationError(f"{field} must be a string")
    normalized = re.sub(r"\s+", " ", value.strip())
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise JudgeCalibrationError(f"{field} must be a bounded non-empty value")
    return normalized


def _with_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def _verify_digest(payload: object, schema: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema") != schema:
        raise JudgeCalibrationError("judge calibration schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise JudgeCalibrationError("judge calibration content digest is invalid")
    return dict(payload)


def compile_judge_calibration_bundle(
    cases: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    assignment_seed: str,
) -> dict[str, Any]:
    """Freeze a 3-reviewer-per-case judge calibration queue.

    Model-judge predictions live only in the owner-readable private mapping.
    Public tasks contain no human label and never expose the prediction.
    """

    seed = _bounded(assignment_seed, "assignment_seed", 512)
    if len(seed) < 16:
        raise JudgeCalibrationError("assignment_seed must contain at least 16 characters")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise JudgeCalibrationError("calibration cases must be a sequence")
    if not 100 <= len(cases) <= 500:
        raise JudgeCalibrationError(
            "judge calibration requires between 100 and 500 distinct cases"
        )

    normalized: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    artifact_ids: set[str] = set()
    prediction_counts = {True: 0, False: 0}
    for raw in cases:
        if not isinstance(raw, Mapping):
            raise JudgeCalibrationError("calibration case must be an object")
        case_id = _bounded(raw.get("case_id"), "case_id", 128)
        if not _SAFE_ID.fullmatch(case_id) or case_id in case_ids:
            raise JudgeCalibrationError("calibration case identity is unsafe or duplicated")
        artifact_sha256 = str(raw.get("artifact_sha256", ""))
        if not _SHA256.fullmatch(artifact_sha256) or artifact_sha256 in artifact_ids:
            raise JudgeCalibrationError(
                "calibration artifact digest is invalid or not case-distinct"
            )
        prediction = raw.get("judge_prediction")
        if type(prediction) is not bool:
            raise JudgeCalibrationError("judge_prediction must be boolean")
        case_ids.add(case_id)
        artifact_ids.add(artifact_sha256)
        prediction_counts[prediction] += 1
        normalized.append(
            {
                "case_id": case_id,
                "artifact_sha256": artifact_sha256,
                "evaluation_prompt": _bounded(
                    raw.get("evaluation_prompt"), "evaluation_prompt", 2_000
                ),
                "evidence_locator": _bounded(
                    raw.get("evidence_locator"), "evidence_locator", 2_000
                ),
                "failure_slice": _bounded(
                    raw.get("failure_slice"), "failure_slice", 120
                ),
                "judge_prediction": prediction,
            }
        )
    if min(prediction_counts.values()) < 40:
        raise JudgeCalibrationError(
            "sealed judge predictions require at least 40 positive and 40 negative cases"
        )
    normalized.sort(key=lambda item: item["case_id"])

    public_cases: list[dict[str, Any]] = []
    private_cases: list[dict[str, Any]] = []
    review_tasks: list[dict[str, Any]] = []
    for case in normalized:
        start = int(
            hashlib.sha256(f"{seed}:{case['case_id']}".encode("utf-8")).hexdigest(),
            16,
        ) % 5
        slots = sorted({start + 1, ((start + 1) % 5) + 1, ((start + 3) % 5) + 1})
        if len(slots) != 3:
            raise JudgeCalibrationError("reviewer assignment did not produce three slots")
        public_case = {
            "case_id": case["case_id"],
            "artifact_sha256": case["artifact_sha256"],
            "evaluation_prompt": case["evaluation_prompt"],
            "evidence_locator": case["evidence_locator"],
            "failure_slice": case["failure_slice"],
            "reviewer_slots": slots,
            "judge_prediction_exposed": False,
        }
        public_case["case_sha256"] = _digest(public_case)
        public_cases.append(public_case)
        private_cases.append(
            {
                "case_id": case["case_id"],
                "case_sha256": public_case["case_sha256"],
                "judge_prediction": case["judge_prediction"],
            }
        )
        for slot in slots:
            task_id = "judge-cal-" + hashlib.sha256(
                f"{public_case['case_sha256']}:{slot}".encode("utf-8")
            ).hexdigest()[:20] + f"-reviewer-{slot}"
            review_tasks.append(
                {
                    "review_task_id": task_id,
                    "case_id": case["case_id"],
                    "case_sha256": public_case["case_sha256"],
                    "reviewer_slot": slot,
                    "reviewer_pseudonym": None,
                    "human_attestation": None,
                    "human_label": None,
                    "reason": None,
                    "reviewed_at": None,
                    "review_content_sha256": None,
                    "judge_prediction_exposed": False,
                }
            )
    review_tasks.sort(key=lambda item: item["review_task_id"])
    public = _with_digest(
        {
            "schema": "ProofLaunchJudgeCalibrationPublicV1",
            "case_count": len(public_cases),
            "distinct_artifact_count": len(artifact_ids),
            "reviewer_count": 5,
            "reviews_per_case": 3,
            "expected_review_count": len(review_tasks),
            "minimum_human_labeled_cases": 100,
            "minimum_true_positive_rate_exclusive": 0.80,
            "minimum_true_negative_rate_exclusive": 0.80,
            "minimum_reviewer_leave_two_out_agreement": 0.70,
            "minimum_reviewer_comparable_cases": 20,
            "cases": public_cases,
            "review_tasks": review_tasks,
            "judge_prediction_exposed": False,
            "provider_identity_exposed": False,
            "human_labels_present": False,
            "automatic_judge_promotion_enabled": False,
            "truth_boundary": (
                "This packet is an empty blinded human calibration queue. It contains "
                "no human labels and does not establish judge validity or 4A quality."
            ),
        }
    )
    private = _with_digest(
        {
            "schema": "ProofLaunchJudgeCalibrationPrivateV1",
            "public_content_sha256": public["content_sha256"],
            "cases": private_cases,
            "assignment_seed_sha256": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
            "raw_assignment_seed_persisted": False,
            "human_labels_present": False,
            "automatic_judge_promotion_enabled": False,
        }
    )
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise JudgeCalibrationError("judge calibration output directory must be empty")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    public_path = root / PUBLIC_NAME
    private_path = root / PRIVATE_NAME
    atomic_write_text(
        public_path,
        json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(
        private_path,
        json.dumps(private, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    public_path.chmod(0o600)
    private_path.chmod(0o600)
    return {
        "schema": "ProofLaunchJudgeCalibrationBundleReceiptV1",
        "root": str(root),
        "case_count": len(public_cases),
        "expected_review_count": len(review_tasks),
        "public_content_sha256": public["content_sha256"],
        "private_content_sha256": private["content_sha256"],
        "public_file_sha256": _file_digest(public_path),
        "private_file_sha256": _file_digest(private_path),
        "human_labels_present": False,
        "judge_calibrated": False,
    }


def calibration_review_digest(review: Mapping[str, Any]) -> str:
    unsigned = dict(review)
    unsigned["review_content_sha256"] = None
    return _digest(unsigned)


class JudgeCalibrationService:
    def __init__(
        self,
        bundle_root: str | Path,
        *,
        reviewer_tokens: Mapping[int, str],
    ) -> None:
        self.root = Path(bundle_root).expanduser().resolve(strict=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise JudgeCalibrationError("judge calibration root must be a real directory")
        self.public_path = self.root / PUBLIC_NAME
        self.private_path = self.root / PRIVATE_NAME
        if any(path.is_symlink() or not path.is_file() for path in (self.public_path, self.private_path)):
            raise JudgeCalibrationError("judge calibration bundle is incomplete")
        if self.private_path.stat().st_mode & 0o077:
            raise JudgeCalibrationError("judge calibration private mapping is not owner-only")
        self.public = _verify_digest(
            json.loads(self.public_path.read_text(encoding="utf-8")),
            "ProofLaunchJudgeCalibrationPublicV1",
        )
        self._private = _verify_digest(
            json.loads(self.private_path.read_text(encoding="utf-8")),
            "ProofLaunchJudgeCalibrationPrivateV1",
        )
        if self._private["public_content_sha256"] != self.public["content_sha256"]:
            raise JudgeCalibrationError("public/private calibration manifests drifted")
        self._cases = {str(item["case_id"]): item for item in self.public["cases"]}
        self._predictions = {
            str(item["case_id"]): bool(item["judge_prediction"])
            for item in self._private["cases"]
        }
        self._tasks = {
            str(item["review_task_id"]): item for item in self.public["review_tasks"]
        }
        self._validate_frozen_bundle()
        supplied = reviewer_tokens or {}
        self._token_sha256 = {
            int(slot): hashlib.sha256(str(token).encode("utf-8")).hexdigest()
            for slot, token in supplied.items()
            if int(slot) in range(1, 6) and len(str(token)) >= 24
        }
        self.review_root = self.root / "human-labels"
        self.review_root.mkdir(mode=0o700, exist_ok=True)
        self.review_root.chmod(0o700)
        self.aggregate_path = self.root / AGGREGATE_NAME
        self._lock = threading.RLock()

    def _validate_frozen_bundle(self) -> None:
        public_cases = self.public.get("cases")
        private_cases = self._private.get("cases")
        public_tasks = self.public.get("review_tasks")
        if not all(isinstance(value, list) for value in (public_cases, private_cases, public_tasks)):
            raise JudgeCalibrationError("calibration bundle collections are invalid")
        if not (
            len(self._cases) >= 100
            and len(self._cases) == len(public_cases)
            and len(self._cases) == len(self._predictions)
            and len(self._predictions) == len(private_cases)
            and len(self._tasks) == len(public_tasks) == len(self._cases) * 3
            and self.public.get("case_count") == len(self._cases)
            and self.public.get("distinct_artifact_count") == len(self._cases)
            and self.public.get("reviewer_count") == 5
            and self.public.get("reviews_per_case") == 3
            and self.public.get("expected_review_count") == len(self._tasks)
        ):
            raise JudgeCalibrationError("calibration case/task cardinality is invalid")
        artifact_ids: set[str] = set()
        private_by_case: dict[str, Mapping[str, Any]] = {}
        for row in private_cases:
            if not isinstance(row, Mapping):
                raise JudgeCalibrationError("private calibration case is invalid")
            case_id = str(row.get("case_id", ""))
            if case_id in private_by_case or type(row.get("judge_prediction")) is not bool:
                raise JudgeCalibrationError("private calibration prediction is invalid")
            private_by_case[case_id] = row
        tasks_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for task in public_tasks:
            if not isinstance(task, Mapping):
                raise JudgeCalibrationError("public calibration task is invalid")
            task_id = str(task.get("review_task_id", ""))
            if (
                not _TASK_ID.fullmatch(task_id)
                or type(task.get("reviewer_slot")) is not int
                or task.get("reviewer_slot") not in range(1, 6)
            ):
                raise JudgeCalibrationError("public calibration task identity is invalid")
            if any(
                task.get(field) is not None
                for field in (
                    "reviewer_pseudonym",
                    "human_attestation",
                    "human_label",
                    "reason",
                    "reviewed_at",
                    "review_content_sha256",
                )
            ):
                raise JudgeCalibrationError("public calibration task contains a human label")
            tasks_by_case[str(task.get("case_id", ""))].append(task)
        for case_id, case in self._cases.items():
            if not isinstance(case, Mapping):
                raise JudgeCalibrationError("public calibration case is invalid")
            artifact_sha256 = str(case.get("artifact_sha256", ""))
            if not _SHA256.fullmatch(artifact_sha256) or artifact_sha256 in artifact_ids:
                raise JudgeCalibrationError("public calibration artifacts are not distinct")
            artifact_ids.add(artifact_sha256)
            private = private_by_case.get(case_id)
            if (
                private is None
                or private.get("case_sha256") != case.get("case_sha256")
                or case.get("case_sha256")
                != _digest({key: value for key, value in case.items() if key != "case_sha256"})
            ):
                raise JudgeCalibrationError("public/private calibration case binding is invalid")
            slots = case.get("reviewer_slots")
            rows = tasks_by_case.get(case_id, [])
            if (
                not isinstance(slots, list)
                or len(slots) != 3
                or any(type(slot) is not int or slot not in range(1, 6) for slot in slots)
                or len(set(slots)) != 3
                or sorted(slots) != sorted(row["reviewer_slot"] for row in rows)
                or any(row.get("case_sha256") != case.get("case_sha256") for row in rows)
            ):
                raise JudgeCalibrationError("calibration reviewer assignment is invalid")
        if set(private_by_case) != set(self._cases) or set(tasks_by_case) != set(self._cases):
            raise JudgeCalibrationError("calibration case sets drifted")

    def _authorize(self, slot: int, token: str) -> None:
        expected = self._token_sha256.get(slot)
        observed = hashlib.sha256(token.encode("utf-8")).hexdigest() if isinstance(token, str) else ""
        if expected is None or not hmac.compare_digest(expected, observed):
            raise JudgeCalibrationAuthorizationError("reviewer invitation is invalid")

    def _review_path(self, task_id: str) -> Path:
        if task_id not in self._tasks or not _TASK_ID.fullmatch(task_id):
            raise JudgeCalibrationError("calibration task identity is invalid")
        return self.review_root / f"{task_id}.json"

    def _load_reviews(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.review_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise JudgeCalibrationError("calibration review store is unsafe")
            row = json.loads(path.read_text(encoding="utf-8"))
            failures = self.validate_review(row)
            if failures or path != self._review_path(str(row.get("review_task_id"))):
                raise JudgeCalibrationError("persisted calibration review is invalid")
            rows.append(row)
        return rows

    def _identity_bindings(self, reviews: Sequence[Mapping[str, Any]]) -> dict[int, str]:
        bindings: dict[int, str] = {}
        reverse: dict[str, int] = {}
        for row in reviews:
            slot = int(row["reviewer_slot"])
            name = str(row["reviewer_pseudonym"])
            if slot in bindings and bindings[slot] != name:
                raise JudgeCalibrationConflictError("reviewer identity drifted within slot")
            if name in reverse and reverse[name] != slot:
                raise JudgeCalibrationConflictError("reviewer identity reused across slots")
            bindings[slot] = name
            reverse[name] = slot
        return bindings

    def validate_review(self, review: object) -> tuple[str, ...]:
        if not isinstance(review, Mapping):
            return ("review_object",)
        failures: list[str] = []
        task = self._tasks.get(str(review.get("review_task_id", "")))
        if review.get("schema") != "ProofLaunchJudgeCalibrationHumanLabelV1":
            failures.append("schema")
        if task is None:
            failures.append("task_binding")
        else:
            for field in ("case_id", "case_sha256", "reviewer_slot"):
                if review.get(field) != task.get(field):
                    failures.append(field)
        if not _bounded_or_false(review.get("reviewer_pseudonym"), 120):
            failures.append("reviewer_pseudonym")
        if review.get("human_attestation") != HUMAN_ATTESTATION:
            failures.append("human_attestation")
        if type(review.get("human_label")) is not bool:
            failures.append("human_label")
        if not _bounded_or_false(review.get("reason"), 2_000):
            failures.append("reason")
        try:
            parsed = datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError):
            failures.append("reviewed_at")
        if any(key in review for key in ("judge_prediction", "provider_id", "model_id")):
            failures.append("partial_deblinding")
        if review.get("review_content_sha256") != calibration_review_digest(review):
            failures.append("review_content_sha256")
        return tuple(dict.fromkeys(failures))

    def tasks_for_slot(self, slot: int, *, reviewer_token: str) -> dict[str, Any]:
        if type(slot) is not int or slot not in range(1, 6):
            raise JudgeCalibrationError("reviewer slot must be in [1, 5]")
        self._authorize(slot, reviewer_token)
        with self._lock:
            completed = {str(row["review_task_id"]) for row in self._load_reviews()}
            tasks = []
            for task in self._tasks.values():
                if task["reviewer_slot"] != slot or task["review_task_id"] in completed:
                    continue
                case = self._cases[str(task["case_id"])]
                tasks.append({**dict(task), "case": dict(case)})
            return {
                "schema": "ProofLaunchJudgeCalibrationAssignmentV1",
                "public_content_sha256": self.public["content_sha256"],
                "reviewer_slot": slot,
                "task_count": len(tasks),
                "tasks": tasks,
                "judge_prediction_exposed": False,
                "provider_identity_exposed": False,
            }

    def submit(self, review: Mapping[str, Any], *, reviewer_token: str) -> dict[str, Any]:
        failures = self.validate_review(review)
        if failures:
            raise JudgeCalibrationError(
                "calibration review failed: " + ", ".join(failures)
            )
        slot = int(review["reviewer_slot"])
        self._authorize(slot, reviewer_token)
        task_id = str(review["review_task_id"])
        normalized = dict(review)
        with self._lock:
            reviews = self._load_reviews()
            self._identity_bindings([*reviews, normalized])
            path = self._review_path(task_id)
            replay = path.exists()
            if replay:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if _canonical(existing) != _canonical(normalized):
                    raise JudgeCalibrationConflictError(
                        "calibration task already has a different immutable label"
                    )
            else:
                atomic_write_text(
                    path,
                    json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                )
                path.chmod(0o600)
            status = self.status()
            return {
                **status,
                "schema": "ProofLaunchJudgeCalibrationSubmissionAckV1",
                "review_task_id": task_id,
                "review_content_sha256": normalized["review_content_sha256"],
                "idempotent_replay": replay,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            reviews = self._load_reviews()
            complete = len(reviews) == len(self._tasks)
            aggregate = self.aggregate() if complete else None
            per_slot = {
                str(slot): sum(row["reviewer_slot"] == slot for row in reviews)
                for slot in range(1, 6)
            }
            return {
                "schema": "ProofLaunchJudgeCalibrationStatusV1",
                "public_content_sha256": self.public["content_sha256"],
                "case_count": len(self._cases),
                "expected_review_count": len(self._tasks),
                "submitted_review_count": len(reviews),
                "remaining_review_count": len(self._tasks) - len(reviews),
                "per_reviewer_slot_submitted": per_slot,
                "configured_reviewer_slot_count": len(self._token_sha256),
                "review_complete": complete,
                "judge_calibrated": bool(aggregate and aggregate["judge_calibrated"]),
                "aggregate_content_sha256": aggregate["content_sha256"] if aggregate else None,
                "judge_prediction_exposed": False,
                "private_mapping_exposed": False,
                "automatic_judge_promotion_enabled": False,
                "judge_based_promotion_executed": False,
            }

    def aggregate(self) -> dict[str, Any]:
        with self._lock:
            reviews = self._load_reviews()
            if len(reviews) != len(self._tasks):
                raise JudgeCalibrationConflictError(
                    "judge calibration aggregate requires every frozen human label"
                )
            bindings = self._identity_bindings(reviews)
            by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in reviews:
                by_case[str(row["case_id"])].append(row)
            if any(len(rows) != 3 for rows in by_case.values()) or len(by_case) != len(self._cases):
                raise JudgeCalibrationConflictError(
                    "each calibration case requires exactly three human labels"
                )

            confusion = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
            disagreement_ids: list[str] = []
            reviewer_stats = {
                slot: {"comparable": 0, "agreement": 0} for slot in range(1, 6)
            }
            for case_id, rows in sorted(by_case.items()):
                positives = sum(row["human_label"] is True for row in rows)
                gold = positives >= 2
                if positives not in {0, 3}:
                    disagreement_ids.append(case_id)
                prediction = self._predictions[case_id]
                if prediction and gold:
                    confusion["true_positive"] += 1
                elif prediction and not gold:
                    confusion["false_positive"] += 1
                elif not prediction and not gold:
                    confusion["true_negative"] += 1
                else:
                    confusion["false_negative"] += 1
                for row in rows:
                    other = [
                        bool(item["human_label"])
                        for item in rows
                        if item["reviewer_slot"] != row["reviewer_slot"]
                    ]
                    if len(other) == 2 and other[0] == other[1]:
                        stats = reviewer_stats[int(row["reviewer_slot"])]
                        stats["comparable"] += 1
                        stats["agreement"] += int(bool(row["human_label"]) == other[0])

            calibration = JudgeCalibration(
                human_labeled_cases=len(self._cases),
                evidence_locator=f"calibration://{self.public['content_sha256']}",
                **confusion,
            )
            reviewer_rows = []
            for slot, stats in reviewer_stats.items():
                rate = (
                    stats["agreement"] / stats["comparable"]
                    if stats["comparable"]
                    else None
                )
                reviewer_rows.append(
                    {
                        "reviewer_slot": slot,
                        **stats,
                        "leave_two_out_agreement": round(rate, 6) if rate is not None else None,
                        "reliability_gate_passed": bool(
                            stats["comparable"]
                            >= self.public["minimum_reviewer_comparable_cases"]
                            and rate is not None
                            and rate >= self.public[
                                "minimum_reviewer_leave_two_out_agreement"
                            ]
                        ),
                    }
                )
            human_full_consensus_rate = 1 - len(disagreement_ids) / len(self._cases)
            reliability_passed = all(row["reliability_gate_passed"] for row in reviewer_rows)
            judge_calibrated = bool(
                calibration.promotion_eligible
                and len(bindings) == 5
                and reliability_passed
                and human_full_consensus_rate >= 0.80
            )
            receipt = _with_digest(
                {
                    "schema": "ProofLaunchJudgeCalibrationAggregateV1",
                    "public_content_sha256": self.public["content_sha256"],
                    "private_content_sha256": self._private["content_sha256"],
                    "human_labeled_case_count": len(self._cases),
                    "submitted_human_label_count": len(reviews),
                    "distinct_reviewer_count": len(bindings),
                    **confusion,
                    "true_positive_rate": round(calibration.true_positive_rate or 0.0, 6),
                    "true_negative_rate": round(calibration.true_negative_rate or 0.0, 6),
                    "human_full_consensus_rate": round(human_full_consensus_rate, 6),
                    "human_disagreement_case_count": len(disagreement_ids),
                    "human_disagreement_case_ids": disagreement_ids,
                    "reviewer_reliability": reviewer_rows,
                    "reviewer_reliability_gate_passed": reliability_passed,
                    "judge_calibration_metric_gate_passed": calibration.promotion_eligible,
                    "judge_calibrated": judge_calibrated,
                    "human_adjudication_required_for_disagreements": True,
                    "automatic_judge_promotion_enabled": False,
                    "judge_based_promotion_executed": False,
                    "external_publish_executed": False,
                    "truth_boundary": (
                        "This receipt calibrates one frozen binary judge against majority "
                        "labels from three blinded humans per distinct case. It does not "
                        "select creative, publish, prove causal lift, 4A quality or Top-1."
                    ),
                }
            )
            if self.aggregate_path.exists():
                existing = json.loads(self.aggregate_path.read_text(encoding="utf-8"))
                if _canonical(existing) != _canonical(receipt):
                    raise JudgeCalibrationConflictError(
                        "persisted calibration aggregate drifted"
                    )
            else:
                atomic_write_text(
                    self.aggregate_path,
                    json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                )
                self.aggregate_path.chmod(0o600)
            return receipt


def _bounded_or_false(value: object, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and "\x00" not in value


__all__ = [
    "AGGREGATE_NAME",
    "HUMAN_ATTESTATION",
    "JudgeCalibrationAuthorizationError",
    "JudgeCalibrationConflictError",
    "JudgeCalibrationError",
    "JudgeCalibrationService",
    "PRIVATE_NAME",
    "PUBLIC_NAME",
    "calibration_review_digest",
    "compile_judge_calibration_bundle",
]
