from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text
from .gtm_multimodal_seed_compiler import (
    compile_multimodal_seed,
    compile_multimodal_seed_files,
)
from .gtm_omnichannel_activation import (
    compile_omnichannel_activation,
    compile_omnichannel_activation_files,
    verify_omnichannel_activation,
)
from .gtm_text_challenger import verify_text_challenger_plan
from .gtm_text_challenger_runner import (
    aggregate_text_blind_reviews,
    validate_text_blind_review,
    verify_text_challenger_execution,
    verify_text_blind_review_bundle,
)


PUBLIC_NAME = "text-creative-blind-review-public.json"
PRIVATE_NAME = "text-creative-blind-review-private.json"
AGGREGATE_NAME = "text-creative-blind-review-aggregate.json"
EXECUTION_NAME = "text-creative-challenger-execution.json"
PLAN_NAME = "text-creative-challenger-plan.json"
MULTIMODAL_ADMISSION_NAME = "multimodal-production-admission.json"
OMNICHANNEL_ACTIVATION_NAME = "omnichannel-activation-plan.json"
MULTIMODAL_SELECTION_ATTESTATION = (
    "I explicitly select the completed blind-review recommendation as a multimodal "
    "production seed; this does not authorize GPU execution, spend, publication, or an effect claim."
)
_TASK_ID = re.compile(r"^blind-pair-[0-9a-f]{20}-reviewer-[1-5]$")


class BlindReviewServiceError(ValueError):
    pass


class BlindReviewAuthorizationError(BlindReviewServiceError):
    pass


class BlindReviewConflictError(BlindReviewServiceError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class BlindReviewService:
    """Durable five-human review queue that never exposes the private deblinding map."""

    def __init__(
        self,
        bundle_root: str | Path,
        *,
        reviewer_tokens: Mapping[int, str] | None = None,
        execution_bindings_path: str | Path | None = None,
        gpu_handoff_path: str | Path | None = None,
        multimodal_compilation_path: str | Path | None = None,
        omnichannel_activation_path: str | Path | None = None,
    ) -> None:
        root = Path(bundle_root).expanduser().resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise BlindReviewServiceError("blind-review root must be a real directory")
        self.root = root
        self.public_path = root / PUBLIC_NAME
        self.private_path = root / PRIVATE_NAME
        self.execution_path = root / EXECUTION_NAME
        self.plan_path = root / PLAN_NAME
        if any(
            path.is_symlink() or not path.is_file()
            for path in (
                self.public_path,
                self.private_path,
                self.execution_path,
                self.plan_path,
            )
        ):
            raise BlindReviewServiceError("blind-review bundle is incomplete")
        self.public_packet = json.loads(self.public_path.read_text(encoding="utf-8"))
        self._private_mapping = json.loads(self.private_path.read_text(encoding="utf-8"))
        verify_text_blind_review_bundle(self.public_packet, self._private_mapping)
        self.execution = json.loads(self.execution_path.read_text(encoding="utf-8"))
        verify_text_challenger_execution(self.execution)
        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        verify_text_challenger_plan(self.plan)
        if not (
            self.execution.get("plan_sha256") == self.plan.get("content_sha256")
            and self.public_packet.get("plan_sha256")
            == self.plan.get("content_sha256")
            and self.execution.get("strategy_id") == self.plan.get("strategy_id")
            and self.public_packet.get("strategy_id") == self.plan.get("strategy_id")
        ):
            raise BlindReviewServiceError(
                "blind-review packet, execution and campaign plan are not identity-bound"
            )
        self._expected_tasks = {
            str(task["review_task_id"]): task for task in self.public_packet["review_tasks"]
        }
        self._pairs = {str(pair["pair_id"]): pair for pair in self.public_packet["pairs"]}
        self.review_root = root / "human-reviews"
        self.review_root.mkdir(mode=0o700, exist_ok=True)
        self.review_root.chmod(0o700)
        self.multimodal_admission_path = root / MULTIMODAL_ADMISSION_NAME
        if (execution_bindings_path is None) != (gpu_handoff_path is None):
            raise BlindReviewServiceError(
                "execution bindings and GPU handoff must be configured together"
            )
        self.execution_bindings_path = (
            Path(execution_bindings_path).expanduser().resolve(strict=True)
            if execution_bindings_path is not None
            else None
        )
        self.gpu_handoff_path = (
            Path(gpu_handoff_path).expanduser().resolve(strict=True)
            if gpu_handoff_path is not None
            else None
        )
        if any(
            path is not None and (path.is_symlink() or not path.is_file())
            for path in (self.execution_bindings_path, self.gpu_handoff_path)
        ):
            raise BlindReviewServiceError("multimodal compiler inputs must be real files")
        self.multimodal_compilation_path = (
            Path(multimodal_compilation_path).expanduser().resolve()
            if multimodal_compilation_path is not None
            else root / "multimodal-seed-compilation.json"
        )
        self.omnichannel_activation_path = (
            Path(omnichannel_activation_path).expanduser().resolve()
            if omnichannel_activation_path is not None
            else root / OMNICHANNEL_ACTIVATION_NAME
        )
        supplied = reviewer_tokens or {}
        self._reviewer_token_sha256 = {
            int(slot): _sha256_text(str(token))
            for slot, token in supplied.items()
            if int(slot) in range(1, 6) and len(str(token)) >= 24
        }
        self._lock = threading.RLock()

    def _authorize(self, slot: int, token: str) -> None:
        expected = self._reviewer_token_sha256.get(slot)
        observed = _sha256_text(token) if isinstance(token, str) else ""
        if expected is None or not hmac.compare_digest(expected, observed):
            raise BlindReviewAuthorizationError("reviewer invitation is invalid for this slot")

    def _review_path(self, task_id: str) -> Path:
        if task_id not in self._expected_tasks or not _TASK_ID.fullmatch(task_id):
            raise BlindReviewServiceError("review task identity is invalid")
        return self.review_root / f"{task_id}.json"

    def _load_reviews(self) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        for path in sorted(self.review_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise BlindReviewServiceError("review store contains an unsafe entry")
            review = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(review, dict):
                raise BlindReviewServiceError("persisted review must be an object")
            if validate_text_blind_review(review, self.public_packet):
                raise BlindReviewServiceError("persisted review failed integrity validation")
            if path != self._review_path(str(review["review_task_id"])):
                raise BlindReviewServiceError("persisted review path is not task-bound")
            reviews.append(review)
        return reviews

    def reviewer_identity_bindings(self) -> dict[int, str]:
        """Return only slot-to-pseudonym bindings for portfolio-wide drift checks."""

        with self._lock:
            bindings: dict[int, str] = {}
            for review in self._load_reviews():
                slot = int(review["reviewer_slot"])
                pseudonym = str(review["reviewer_pseudonym"])
                existing = bindings.get(slot)
                if existing is not None and existing != pseudonym:
                    raise BlindReviewServiceError(
                        "reviewer identity drifted within its slot"
                    )
                bindings[slot] = pseudonym
            if len(set(bindings.values())) != len(bindings):
                raise BlindReviewServiceError(
                    "reviewer identity is bound to more than one slot"
                )
            return bindings

    @property
    def expected_task_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._expected_tasks))

    @property
    def private_mapping_content_sha256(self) -> str:
        return str(self._private_mapping["content_sha256"])

    @property
    def configured_reviewer_slot_count(self) -> int:
        return len(self._reviewer_token_sha256)

    def status(self) -> dict[str, Any]:
        with self._lock:
            reviews = self._load_reviews()
            completed_ids = {str(row["review_task_id"]) for row in reviews}
            per_slot = {
                str(slot): sum(1 for row in reviews if row["reviewer_slot"] == slot)
                for slot in range(1, 6)
            }
            complete = len(reviews) == len(self._expected_tasks)
            aggregate = (
                aggregate_text_blind_reviews(
                    self.public_packet,
                    self._private_mapping,
                    reviews,
                )
                if complete
                else None
            )
            admission = self._load_multimodal_admission()
            if admission is not None:
                if aggregate is None:
                    raise BlindReviewServiceError(
                        "multimodal admission exists without a complete blind aggregate"
                    )
                if (
                    admission.get("blind_review_aggregate_sha256")
                    != aggregate.get("content_sha256")
                    or admission.get("selected_territory_id")
                    != aggregate.get("recommended_territory_id")
                ):
                    raise BlindReviewServiceError(
                        "multimodal admission drifted from the current blind aggregate"
                    )
            compilation = self._load_compilation(admission)
            activation = self._load_omnichannel_activation(admission, compilation)
            return {
                "schema": "ProofLaunchBlindReviewQueueStatusV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "campaign_id": self.plan["campaign_id"],
                "strategy_id": self.plan["strategy_id"],
                "challenger_plan_sha256": self.plan["content_sha256"],
                "pair_count": self.public_packet["pair_count"],
                "expected_review_count": len(self._expected_tasks),
                "submitted_review_count": len(reviews),
                "remaining_review_count": len(self._expected_tasks) - len(reviews),
                "completed_task_ids": sorted(completed_ids),
                "per_reviewer_slot_submitted": per_slot,
                "configured_reviewer_slot_count": len(self._reviewer_token_sha256),
                "review_complete": bool(aggregate and aggregate["review_complete"]),
                "human_selection_eligible": bool(
                    aggregate and aggregate["human_selection_eligible"]
                ),
                "recommended_territory_id": (
                    aggregate["recommended_territory_id"]
                    if aggregate and aggregate["review_complete"]
                    else None
                ),
                "blind_review_aggregate_sha256": (
                    aggregate["content_sha256"]
                    if aggregate and aggregate["review_complete"]
                    else None
                ),
                "multimodal_production_entry_created": admission is not None,
                "multimodal_production_entry_sha256": (
                    admission["content_sha256"] if admission else None
                ),
                "multimodal_seed_compilation_created": compilation is not None,
                "multimodal_seed_compilation_sha256": (
                    compilation["content_sha256"] if compilation else None
                ),
                "omnichannel_activation_plan_created": activation is not None,
                "omnichannel_activation_plan_sha256": (
                    activation["content_sha256"] if activation else None
                ),
                "omnichannel_activation_lane_count": (
                    activation["lane_count"] if activation else 0
                ),
                "selected_territory_id": (
                    admission["selected_territory_id"] if admission else None
                ),
                "winner_selected": admission is not None,
                "gpu_execution_authorized": False,
                "external_publish_executed": False,
                "private_mapping_exposed": False,
            }

    def _load_multimodal_admission(self) -> dict[str, Any] | None:
        path = self.multimodal_admission_path
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise BlindReviewServiceError("multimodal admission store is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "ProofLaunchMultimodalProductionAdmissionV1"
            or payload.get("content_sha256")
            != _sha256_text(_canonical({**payload, "content_sha256": None}))
        ):
            raise BlindReviewServiceError("multimodal admission failed integrity validation")
        return payload

    def _load_compilation(
        self, admission: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        path = self.multimodal_compilation_path
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or admission is None:
            raise BlindReviewServiceError("multimodal compilation store is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        supplied = payload.get("content_sha256")
        if (
            payload.get("schema") != "ProofLaunchMultimodalSeedCompilationV1"
            or not isinstance(supplied, str)
            or supplied != _sha256_text(_canonical({**payload, "content_sha256": None}))
            or payload.get("multimodal_admission_sha256")
            != admission.get("content_sha256")
        ):
            raise BlindReviewServiceError("multimodal compilation drifted from its admission")
        if self.execution_bindings_path is not None and self.gpu_handoff_path is not None:
            expected = compile_multimodal_seed(
                admission,
                json.loads(self.execution_bindings_path.read_text(encoding="utf-8")),
                json.loads(self.gpu_handoff_path.read_text(encoding="utf-8")),
            )
            if _canonical(payload) != _canonical(expected):
                raise BlindReviewServiceError("multimodal compilation failed integrity validation")
        return payload

    def _ensure_compilation(self, admission: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.execution_bindings_path is None or self.gpu_handoff_path is None:
            return None
        existing = self._load_compilation(admission)
        if existing is not None:
            return existing
        return compile_multimodal_seed_files(
            self.multimodal_admission_path,
            self.execution_bindings_path,
            self.gpu_handoff_path,
            self.multimodal_compilation_path,
        )

    def _load_omnichannel_activation(
        self,
        admission: Mapping[str, Any] | None,
        compilation: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        path = self.omnichannel_activation_path
        if not path.exists():
            return None
        if (
            path.is_symlink()
            or not path.is_file()
            or admission is None
            or compilation is None
        ):
            raise BlindReviewServiceError("omnichannel activation store is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            verify_omnichannel_activation(payload)
            expected = compile_omnichannel_activation(admission, compilation)
        except ValueError as error:
            raise BlindReviewServiceError(
                f"omnichannel activation failed integrity validation: {error}"
            ) from error
        if _canonical(payload) != _canonical(expected):
            raise BlindReviewServiceError(
                "omnichannel activation drifted from the selected territory"
            )
        return payload

    def _ensure_omnichannel_activation(
        self,
        admission: Mapping[str, Any],
        compilation: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if compilation is None:
            return None
        existing = self._load_omnichannel_activation(admission, compilation)
        if existing is not None:
            return existing
        return compile_omnichannel_activation_files(
            self.multimodal_admission_path,
            self.multimodal_compilation_path,
            self.omnichannel_activation_path,
        )

    def aggregate(self) -> dict[str, Any]:
        """Return a deblinded aggregate only after every human task is complete."""

        with self._lock:
            reviews = self._load_reviews()
            if len(reviews) != len(self._expected_tasks):
                raise BlindReviewConflictError(
                    "blind review aggregate is unavailable until all 30 tasks are submitted"
                )
            aggregate = aggregate_text_blind_reviews(
                self.public_packet,
                self._private_mapping,
                reviews,
            )
            if not aggregate["review_complete"]:
                raise BlindReviewConflictError(
                    "blind review aggregate failed the five-human integrity gate"
                )
            return aggregate

    def omnichannel_activation(self) -> dict[str, Any]:
        """Return the selected-territory activation only after human admission."""

        with self._lock:
            admission = self._load_multimodal_admission()
            compilation = self._load_compilation(admission)
            activation = self._load_omnichannel_activation(admission, compilation)
            if activation is None:
                raise BlindReviewConflictError(
                    "omnichannel activation is unavailable before human selection"
                )
            return activation

    def select_multimodal_seed(
        self,
        request: Mapping[str, Any],
        *,
        authenticated_approver: str,
    ) -> dict[str, Any]:
        """Bind a complete human recommendation to the next production stage."""

        if not isinstance(request, Mapping):
            raise BlindReviewServiceError("multimodal selection must be an object")
        approver = authenticated_approver.strip()
        if not approver:
            raise BlindReviewAuthorizationError("a named authenticated approver is required")
        aggregate = self.aggregate()
        recommended = aggregate.get("recommended_territory_id")
        if not aggregate.get("human_selection_eligible") or not isinstance(recommended, str):
            raise BlindReviewConflictError(
                "the completed blind review did not produce an eligible recommendation"
            )
        if request.get("aggregate_content_sha256") != aggregate.get("content_sha256"):
            raise BlindReviewConflictError("blind review aggregate binding drifted")
        if request.get("selected_territory_id") != recommended:
            raise BlindReviewConflictError(
                "selected territory must match the completed blind recommendation"
            )
        reason = str(request.get("reason") or "").strip()
        if len(reason) < 32 or len(reason) > 1200:
            raise BlindReviewServiceError("selection reason must contain 32 to 1200 characters")
        if request.get("human_attestation") != MULTIMODAL_SELECTION_ATTESTATION:
            raise BlindReviewServiceError("multimodal selection attestation is invalid")
        idempotency_key = str(request.get("idempotency_key") or "").strip()
        if len(idempotency_key) < 16 or len(idempotency_key) > 160:
            raise BlindReviewServiceError("selection idempotency key is invalid")
        candidate_rows = [
            row
            for row in self.execution["candidates"]
            if row.get("territory_id") == recommended
        ]
        if len(candidate_rows) != 1:
            raise BlindReviewServiceError("recommended candidate is absent or duplicated")
        candidate = candidate_rows[0].get("candidate")
        if not isinstance(candidate, Mapping):
            raise BlindReviewServiceError("recommended candidate payload is invalid")
        candidate_sha = candidate.get("candidate_content_sha256")
        unsigned_candidate = dict(candidate)
        unsigned_candidate.pop("candidate_content_sha256", None)
        if (
            not isinstance(candidate_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", candidate_sha)
            or candidate_sha != _sha256_text(_canonical(unsigned_candidate))
        ):
            raise BlindReviewServiceError("recommended candidate digest is invalid")
        with self._lock:
            existing = self._load_multimodal_admission()
            request_binding = {
                "aggregate_content_sha256": aggregate["content_sha256"],
                "selected_territory_id": recommended,
                "reason": reason,
                "human_attestation": MULTIMODAL_SELECTION_ATTESTATION,
                "idempotency_key": idempotency_key,
                "authenticated_approver": approver,
            }
            request_sha = _sha256_text(_canonical(request_binding))
            if existing is not None:
                if existing.get("selection_request_sha256") != request_sha:
                    raise BlindReviewConflictError(
                        "a different immutable multimodal selection already exists"
                    )
                compilation = self._ensure_compilation(existing)
                activation = self._ensure_omnichannel_activation(
                    existing, compilation
                )
                return {
                    **existing,
                    "idempotent_replay": True,
                    "multimodal_seed_compilation_sha256": (
                        compilation["content_sha256"] if compilation else None
                    ),
                    "omnichannel_activation_plan_sha256": (
                        activation["content_sha256"] if activation else None
                    ),
                }
            receipt: dict[str, Any] = {
                "schema": "ProofLaunchMultimodalProductionAdmissionV1",
                "campaign_id": self.plan["campaign_id"],
                "strategy_id": self.plan["strategy_id"],
                "challenger_plan_sha256": self.plan["content_sha256"],
                "proof_claim_id": self.plan["proof_claim_id"],
                "public_packet_sha256": self.public_packet["content_sha256"],
                "blind_review_aggregate_sha256": aggregate["content_sha256"],
                "text_challenger_execution_sha256": self.execution["content_sha256"],
                "selection_request_sha256": request_sha,
                "selected_territory_id": recommended,
                "selected_candidate_content_sha256": candidate_sha,
                "selected_candidate": dict(candidate),
                "authenticated_approver": approver,
                "selected_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "human_attestation": MULTIMODAL_SELECTION_ATTESTATION,
                "prompt_compilation_authorized": True,
                "gpu_execution_authorized": False,
                "spend_authorized": False,
                "external_publish_authorized": False,
                "effect_claim_eligible": False,
                "automatic_winner_selection_enabled": False,
                "truth_boundary": (
                    "This receipt admits one human-selected text territory as an immutable "
                    "prompt seed for the image/video/music/speech funnel. It is not GPU "
                    "execution, a finished media asset, publication, causal lift, revenue "
                    "proof, universal 4A quality, or Top-1 evidence."
                ),
                "content_sha256": None,
            }
            receipt["content_sha256"] = _sha256_text(_canonical(receipt))
            atomic_write_text(
                self.multimodal_admission_path,
                json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            self.multimodal_admission_path.chmod(0o600)
            compilation = self._ensure_compilation(receipt)
            activation = self._ensure_omnichannel_activation(receipt, compilation)
            return {
                **receipt,
                "idempotent_replay": False,
                "multimodal_seed_compilation_sha256": (
                    compilation["content_sha256"] if compilation else None
                ),
                "omnichannel_activation_plan_sha256": (
                    activation["content_sha256"] if activation else None
                ),
            }

    def tasks_for_slot(self, slot: int, *, reviewer_token: str) -> dict[str, Any]:
        if slot not in range(1, 6):
            raise BlindReviewServiceError("reviewer slot must be in [1, 5]")
        self._authorize(slot, reviewer_token)
        with self._lock:
            reviews = self._load_reviews()
            completed_ids = {str(row["review_task_id"]) for row in reviews}
            tasks = []
            for task in self.public_packet["review_tasks"]:
                if task["reviewer_slot"] != slot:
                    continue
                pair = self._pairs[str(task["pair_id"])]
                tasks.append(
                    {
                        "review_task_id": task["review_task_id"],
                        "pair_id": task["pair_id"],
                        "pair_sha256": task["pair_sha256"],
                        "reviewer_slot": slot,
                        "pair": pair,
                        "submitted": task["review_task_id"] in completed_ids,
                    }
                )
            return {
                "schema": "ProofLaunchBlindReviewAssignmentV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "reviewer_slot": slot,
                "task_count": len(tasks),
                "tasks": tasks,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
            }

    def submit(self, review: Mapping[str, Any], *, reviewer_token: str) -> dict[str, Any]:
        if not isinstance(review, Mapping):
            raise BlindReviewServiceError("review must be an object")
        slot = review.get("reviewer_slot")
        if type(slot) is not int or slot not in range(1, 6):
            raise BlindReviewServiceError("reviewer slot must be in [1, 5]")
        self._authorize(slot, reviewer_token)
        normalized = dict(review)
        failures = validate_text_blind_review(normalized, self.public_packet)
        if failures:
            raise BlindReviewServiceError(
                "review contract failed: " + ", ".join(failures)
            )
        task_id = str(normalized["review_task_id"])
        path = self._review_path(task_id)
        serialized = _canonical(normalized)
        with self._lock:
            existing_reviews = self._load_reviews()
            for existing in existing_reviews:
                if existing["reviewer_slot"] == slot and existing["reviewer_pseudonym"] != normalized["reviewer_pseudonym"]:
                    raise BlindReviewConflictError("reviewer identity drifted within its slot")
                if existing["reviewer_slot"] != slot and existing["reviewer_pseudonym"] == normalized["reviewer_pseudonym"]:
                    raise BlindReviewConflictError("reviewer identity is already bound to another slot")
            if path.exists():
                if path.read_text(encoding="utf-8").strip() != serialized:
                    raise BlindReviewConflictError("review task already has a different immutable submission")
                status = self.status()
                return {
                    **status,
                    "schema": "ProofLaunchBlindReviewSubmissionAckV1",
                    "review_task_id": task_id,
                    "review_content_sha256": normalized["review_content_sha256"],
                    "idempotent_replay": True,
                }
            atomic_write_text(path, serialized + "\n")
            path.chmod(0o600)
            status = self.status()
            if status["review_complete"]:
                aggregate = aggregate_text_blind_reviews(
                    self.public_packet,
                    self._private_mapping,
                    self._load_reviews(),
                )
                aggregate_path = self.root / AGGREGATE_NAME
                atomic_write_text(
                    aggregate_path,
                    json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                )
                aggregate_path.chmod(0o600)
            return {
                **status,
                "schema": "ProofLaunchBlindReviewSubmissionAckV1",
                "review_task_id": task_id,
                "review_content_sha256": normalized["review_content_sha256"],
                "idempotent_replay": False,
            }
