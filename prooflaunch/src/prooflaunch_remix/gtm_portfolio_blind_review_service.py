from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text
from .gtm_blind_review_service import (
    BlindReviewConflictError,
    BlindReviewService,
    BlindReviewServiceError,
)


PUBLIC_NAME = "portfolio-blind-review-public.json"
PRIVATE_NAME = "portfolio-blind-review-private.json"
AGGREGATE_NAME = "portfolio-blind-review-aggregate.json"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_content_digest(payload: Mapping[str, Any], schema: str) -> None:
    if payload.get("schema") != schema:
        raise BlindReviewServiceError("portfolio blind-review schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise BlindReviewServiceError(
            "portfolio blind-review content digest is invalid"
        )


class PortfolioBlindReviewService:
    """Durable 9-case/270-task HITL queue with portfolio-wide deblinding."""

    def __init__(
        self,
        bundle_root: str | Path,
        *,
        reviewer_tokens: Mapping[int, str] | None = None,
    ) -> None:
        root = Path(bundle_root).expanduser().resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise BlindReviewServiceError(
                "portfolio blind-review root must be a real directory"
            )
        self.root = root
        self.public_path = root / PUBLIC_NAME
        self.private_path = root / PRIVATE_NAME
        if any(
            path.is_symlink() or not path.is_file()
            for path in (self.public_path, self.private_path)
        ):
            raise BlindReviewServiceError(
                "portfolio blind-review manifest is incomplete"
            )
        if self.private_path.stat().st_mode & 0o077:
            raise BlindReviewServiceError(
                "portfolio private manifest must be owner-readable only"
            )
        self.public_packet = json.loads(self.public_path.read_text(encoding="utf-8"))
        self._private_manifest = json.loads(
            self.private_path.read_text(encoding="utf-8")
        )
        _verify_content_digest(
            self.public_packet,
            "ProofLaunchLocalGTMPortfolioBlindReviewPacketV1",
        )
        _verify_content_digest(
            self._private_manifest,
            "ProofLaunchLocalGTMPortfolioBlindReviewPrivateManifestV1",
        )
        if not (
            self._private_manifest.get("public_packet_content_sha256")
            == self.public_packet.get("content_sha256")
            and self._private_manifest.get("public_packet_file_sha256")
            == _file_digest(self.public_path)
        ):
            raise BlindReviewServiceError(
                "portfolio public and private manifests are not identity-bound"
            )
        public_rows = self.public_packet.get("cases")
        private_rows = self._private_manifest.get("cases")
        if not isinstance(public_rows, list) or not isinstance(private_rows, list):
            raise BlindReviewServiceError("portfolio case manifests are invalid")
        private_by_case = {
            str(row.get("case_id")): row
            for row in private_rows
            if isinstance(row, Mapping)
        }
        self._case_metadata: dict[str, dict[str, Any]] = {}
        self._services: dict[str, BlindReviewService] = {}
        self._task_to_case: dict[str, str] = {}
        for row in public_rows:
            if not isinstance(row, Mapping):
                raise BlindReviewServiceError("portfolio public case row is invalid")
            case_id = str(row.get("case_id") or "")
            private_row = private_by_case.get(case_id)
            if not case_id or private_row is None:
                raise BlindReviewServiceError(
                    "portfolio public/private case identities drifted"
                )
            public_case_path = self._safe_relative_file(
                str(row.get("public_packet_path") or "")
            )
            private_case_path = self._safe_relative_file(
                str(private_row.get("private_mapping_path") or "")
            )
            if public_case_path.parent != private_case_path.parent:
                raise BlindReviewServiceError(
                    "portfolio case public/private paths do not share a root"
                )
            if not (
                row.get("public_packet_file_sha256") == _file_digest(public_case_path)
                and private_row.get("private_mapping_file_sha256")
                == _file_digest(private_case_path)
            ):
                raise BlindReviewServiceError("portfolio case file digest drifted")
            service = BlindReviewService(
                public_case_path.parent,
                reviewer_tokens=reviewer_tokens,
            )
            if not (
                service.public_packet.get("content_sha256")
                == row.get("public_packet_content_sha256")
                == private_row.get("public_packet_content_sha256")
                and service.private_mapping_content_sha256
                == private_row.get("private_mapping_content_sha256")
            ):
                raise BlindReviewServiceError(
                    "portfolio case content digest drifted"
                )
            metadata = {
                field: row[field]
                for field in (
                    "case_id",
                    "business_model",
                    "lifecycle",
                    "budget",
                    "industry_risk",
                    "pair_count",
                    "expected_review_count",
                )
            }
            self._case_metadata[case_id] = metadata
            self._services[case_id] = service
            for task_id in service.expected_task_ids:
                if task_id in self._task_to_case:
                    raise BlindReviewServiceError(
                        "portfolio review task identities are not globally unique"
                    )
                self._task_to_case[task_id] = case_id
        if not (
            len(self._services) == self.public_packet.get("case_count") == 9
            and len(self._task_to_case)
            == self.public_packet.get("expected_review_count")
            == 270
        ):
            raise BlindReviewServiceError(
                "portfolio case or task cardinality is invalid"
            )
        self.aggregate_path = root / AGGREGATE_NAME
        self._lock = threading.RLock()

    def _safe_relative_file(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve(strict=True)
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise BlindReviewServiceError(
                "portfolio manifest path escaped its root"
            ) from error
        if candidate.is_symlink() or not candidate.is_file():
            raise BlindReviewServiceError(
                "portfolio manifest path must reference a real file"
            )
        return candidate

    def _identity_bindings(self) -> dict[int, str]:
        bindings: dict[int, str] = {}
        pseudonym_to_slot: dict[str, int] = {}
        for service in self._services.values():
            for slot, pseudonym in service.reviewer_identity_bindings().items():
                existing = bindings.get(slot)
                if existing is not None and existing != pseudonym:
                    raise BlindReviewConflictError(
                        "reviewer identity drifted across portfolio cases"
                    )
                other_slot = pseudonym_to_slot.get(pseudonym)
                if other_slot is not None and other_slot != slot:
                    raise BlindReviewConflictError(
                        "reviewer identity is bound to another portfolio slot"
                    )
                bindings[slot] = pseudonym
                pseudonym_to_slot[pseudonym] = slot
        return bindings

    def _case_statuses(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (case_id, self._services[case_id].status())
            for case_id in self._case_metadata
        ]

    def status(self) -> dict[str, Any]:
        with self._lock:
            case_statuses = self._case_statuses()
            submitted = sum(row[1]["submitted_review_count"] for row in case_statuses)
            expected = len(self._task_to_case)
            complete = submitted == expected and all(
                row[1]["review_complete"] for row in case_statuses
            )
            per_slot = {
                str(slot): sum(
                    int(status["per_reviewer_slot_submitted"][str(slot)])
                    for _, status in case_statuses
                )
                for slot in range(1, 6)
            }
            aggregate = self.aggregate() if complete else None
            case_rows = []
            for case_id, case_status in case_statuses:
                metadata = self._case_metadata[case_id]
                case_rows.append(
                    {
                        **metadata,
                        "submitted_review_count": case_status[
                            "submitted_review_count"
                        ],
                        "remaining_review_count": case_status[
                            "remaining_review_count"
                        ],
                        "review_complete": case_status["review_complete"],
                        "human_selection_eligible": (
                            case_status["human_selection_eligible"] if complete else False
                        ),
                        "recommended_territory_id": (
                            case_status["recommended_territory_id"] if complete else None
                        ),
                    }
                )
            return {
                "schema": "ProofLaunchPortfolioBlindReviewQueueStatusV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "case_count": len(self._services),
                "pair_count": self.public_packet["pair_count"],
                "expected_review_count": expected,
                "submitted_review_count": submitted,
                "remaining_review_count": expected - submitted,
                "per_reviewer_slot_submitted": per_slot,
                "configured_reviewer_slot_count": self._services[
                    next(iter(self._services))
                ].configured_reviewer_slot_count,
                "review_complete": complete,
                "portfolio_promotion_passed": bool(
                    aggregate and aggregate["portfolio_promotion_passed"]
                ),
                "human_preference_observed": complete,
                "portfolio_aggregate_sha256": (
                    aggregate["content_sha256"] if aggregate else None
                ),
                "cases": case_rows,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
                "private_mapping_exposed": False,
                "automatic_winner_selection_enabled": False,
                "winner_selected": False,
                "external_publish_executed": False,
            }

    def tasks_for_slot(self, slot: int, *, reviewer_token: str) -> dict[str, Any]:
        with self._lock:
            tasks: list[dict[str, Any]] = []
            for case_id, service in self._services.items():
                assignment = service.tasks_for_slot(
                    slot, reviewer_token=reviewer_token
                )
                metadata = self._case_metadata[case_id]
                for task in assignment["tasks"]:
                    tasks.append({**task, "portfolio_case": metadata})
            return {
                "schema": "ProofLaunchPortfolioBlindReviewAssignmentV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "reviewer_slot": slot,
                "task_count": len(tasks),
                "tasks": tasks,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
            }

    def submit(
        self, review: Mapping[str, Any], *, reviewer_token: str
    ) -> dict[str, Any]:
        task_id = str(review.get("review_task_id") or "")
        case_id = self._task_to_case.get(task_id)
        if case_id is None:
            raise BlindReviewServiceError("portfolio review task identity is invalid")
        slot = review.get("reviewer_slot")
        pseudonym = str(review.get("reviewer_pseudonym") or "")
        with self._lock:
            bindings = self._identity_bindings()
            if type(slot) is int:
                existing = bindings.get(slot)
                if existing is not None and existing != pseudonym:
                    raise BlindReviewConflictError(
                        "reviewer identity drifted across portfolio cases"
                    )
                if any(
                    bound_slot != slot and bound_name == pseudonym
                    for bound_slot, bound_name in bindings.items()
                ):
                    raise BlindReviewConflictError(
                        "reviewer identity is bound to another portfolio slot"
                    )
            acknowledgement = self._services[case_id].submit(
                review, reviewer_token=reviewer_token
            )
            status = self.status()
            return {
                **status,
                "schema": "ProofLaunchPortfolioBlindReviewSubmissionAckV1",
                "case_id": case_id,
                "review_task_id": task_id,
                "review_content_sha256": review.get("review_content_sha256"),
                "idempotent_replay": acknowledgement["idempotent_replay"],
            }

    def aggregate(self) -> dict[str, Any]:
        """Deblind all cases only after every one of the 270 reviews exists."""

        with self._lock:
            statuses = self._case_statuses()
            if not all(status["review_complete"] for _, status in statuses):
                raise BlindReviewConflictError(
                    "portfolio aggregate is unavailable until all 270 tasks are submitted"
                )
            case_aggregates = []
            for case_id, service in self._services.items():
                aggregate = service.aggregate()
                case_aggregates.append(
                    {
                        **self._case_metadata[case_id],
                        "aggregate_content_sha256": aggregate["content_sha256"],
                        "human_selection_eligible": aggregate[
                            "human_selection_eligible"
                        ],
                        "recommended_territory_id": aggregate[
                            "recommended_territory_id"
                        ],
                    }
                )
            recommendations = [
                row for row in case_aggregates if row["human_selection_eligible"]
            ]
            gate = self.public_packet["portfolio_promotion_gate"]
            counts = {
                "all": len(recommendations),
                "b2b": sum(row["business_model"] == "b2b" for row in recommendations),
                "b2c": sum(row["business_model"] == "b2c" for row in recommendations),
                "zero_budget": sum(row["budget"] == "zero" for row in recommendations),
                "high_regulation": sum(
                    row["industry_risk"] == "high_regulation"
                    for row in recommendations
                ),
            }
            checks = {
                "minimum_case_recommendations": counts["all"]
                >= gate["minimum_case_recommendations"],
                "minimum_b2b_case_recommendations": counts["b2b"]
                >= gate["minimum_b2b_case_recommendations"],
                "minimum_b2c_case_recommendations": counts["b2c"]
                >= gate["minimum_b2c_case_recommendations"],
                "minimum_zero_budget_case_recommendations": counts["zero_budget"]
                >= gate["minimum_zero_budget_case_recommendations"],
                "required_high_regulation_case_recommendations": counts[
                    "high_regulation"
                ]
                >= gate["required_high_regulation_case_recommendations"],
            }
            receipt: dict[str, Any] = {
                "schema": "ProofLaunchPortfolioBlindReviewAggregateV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "submitted_review_count": len(self._task_to_case),
                "expected_review_count": len(self._task_to_case),
                "reviewer_identity_count": len(self._identity_bindings()),
                "review_complete": True,
                "case_aggregates": case_aggregates,
                "recommendation_counts": counts,
                "promotion_checks": checks,
                "portfolio_promotion_passed": all(checks.values()),
                "human_preference_observed": True,
                "automatic_winner_selection_enabled": False,
                "winner_selected": False,
                "external_publish_executed": False,
                "truth_boundary": (
                    "A complete portfolio aggregate proves blinded preference across the "
                    "nine frozen scenarios only. It is not automatic selection, publication, "
                    "causal lift, revenue proof, universal 4A quality or Top-1 standing."
                ),
            }
            receipt["content_sha256"] = _digest(receipt)
            if self.aggregate_path.exists():
                existing = json.loads(
                    self.aggregate_path.read_text(encoding="utf-8")
                )
                if _canonical(existing) != _canonical(receipt):
                    raise BlindReviewConflictError(
                        "persisted portfolio aggregate drifted from submitted reviews"
                    )
            else:
                atomic_write_text(
                    self.aggregate_path,
                    json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                )
                self.aggregate_path.chmod(0o600)
            return receipt


__all__ = [
    "AGGREGATE_NAME",
    "PRIVATE_NAME",
    "PUBLIC_NAME",
    "PortfolioBlindReviewService",
]
