from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

from .store import IdentityJobStore


def read_legacy_candidate_inventory(path: str | Path) -> list[dict[str, Any]]:
    """Return a non-biometric, read-only inventory of the pre-11B candidate store.

    Old candidates used different thresholds and kept vectors in a generic
    review file, so importing them into the protected directory would silently
    mix incompatible contracts. They remain auditable but never participate in
    new matching.
    """

    source = Path(path)
    if not source.is_file():
        return []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read legacy candidate store: {source}") from exc
    candidates = payload.get("identity_candidates") if isinstance(payload, dict) else []
    return [
        {
            "legacy_candidate_id": str(item.get("id") or ""),
            "modality": str(item.get("modality") or ""),
            "status": str(item.get("status") or "candidate"),
            "observation_count": int(item.get("observation_count") or 0),
            "first_seen_at_ms": item.get("first_seen_at_ms"),
            "last_seen_at_ms": item.get("last_seen_at_ms"),
            "evidence_ids": list(item.get("evidence_ids") or []),
            "window_ids": list(item.get("window_ids") or []),
            "migration_status": "read_only_not_imported_incompatible_contract",
        }
        for item in candidates or []
        if isinstance(item, dict)
    ]


class IdentityDirectoryStore:
    """Persistent gallery, anonymous candidates and observation projections.

    Public identity metadata and biometric vectors are deliberately stored in
    different files. Matching is fail-closed: malformed protected state raises
    instead of silently replacing the gallery with an empty one.
    """

    def __init__(
        self,
        public_path: str | Path,
        *,
        protected_path: str | Path,
        config_path: str | Path,
        gallery_policy_path: str | Path | None = None,
        now_ms: Callable[[], int] | None = None,
        max_representatives: int = 3,
        representative_spacing_ms: int = 30_000,
    ) -> None:
        self.public_path = Path(public_path)
        self.protected_path = Path(protected_path)
        self.config_path = Path(config_path)
        self.gallery_policy_path = Path(gallery_policy_path) if gallery_policy_path else None
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        matching = dict(config.get("matching") or {})
        model = dict(config.get("model") or {})
        self.max_representatives = max(
            1,
            int(matching.get("anonymous_max_representatives") or max_representatives),
        )
        # Kept in the constructor for callers that still pass it. Representative
        # selection is intentionally quality-only and no longer time-spaced.
        _ = representative_spacing_ms
        self.config_version = str(config.get("config_id") or "")
        self.embedding_dimension = int(model.get("embedding_dimension") or 0)
        self.anonymous_threshold = float(matching["anonymous_candidate_threshold"])
        self.anonymous_discard_reason_codes = {
            str(item)
            for item in matching.get(
                "anonymous_discard_reason_codes",
                ["face_too_small", "face_too_small_pixels", "face_too_small_ratio"],
            )
        }
        self.gallery_threshold = float(matching["confirmed_gallery_threshold"])
        self.gallery_margin = float(matching.get("gallery_minimum_margin") or 0.0)
        policy = (
            json.loads(self.gallery_policy_path.read_text(encoding="utf-8"))
            if self.gallery_policy_path is not None
            else None
        )
        if policy is not None:
            expected_config_id = str(policy.get("base_production_config") or "")
            expected_config_hash = str(policy.get("base_production_config_sha256") or "")
            actual_config_hash = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
            if expected_config_id and expected_config_id != self.config_version:
                raise ValueError("gallery policy base production config id mismatch")
            if expected_config_hash and expected_config_hash != actual_config_hash:
                raise ValueError("gallery policy base production config hash mismatch")
        self.gallery_policy = policy
        self.gallery_policy_id = str((policy or {}).get("policy_id") or "single-frame-v1")
        candidate_policy = dict((policy or {}).get("candidate_template") or {})
        gallery_policy = dict((policy or {}).get("gallery_templates") or {})
        decision_policy = dict((policy or {}).get("decision") or {})
        self.candidate_gallery_min_observations = int(
            candidate_policy.get("minimum_observations") or 1
        )
        self.candidate_gallery_min_evidence = int(
            candidate_policy.get("minimum_distinct_evidence") or 1
        )
        self.candidate_gallery_min_span_ms = int(
            candidate_policy.get("minimum_time_span_ms") or 0
        )
        self.gallery_top_k = max(1, int(gallery_policy.get("top_k_per_person") or 1))
        self.gallery_suggestion_threshold = float(
            decision_policy.get("suggestion_threshold") or self.gallery_threshold
        )
        self.gallery_threshold = float(
            decision_policy.get("high_confidence_threshold") or self.gallery_threshold
        )
        self.gallery_margin = float(
            decision_policy.get("minimum_margin") or self.gallery_margin
        )
        self.single_frame_automatic_confirmation = bool(
            decision_policy.get("single_frame_automatic_confirmation", True)
        )
        self.candidate_level_requires_confirmation = bool(
            decision_policy.get("candidate_level_requires_user_confirmation", False)
        )

    def upsert_confirmed_person(
        self,
        *,
        person_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        person_id = _required_id(person_id, "person_id")
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("display_name is required")
        with self._lock:
            public = self._read_public_unlocked()
            person = next(
                (item for item in public["people"] if item.get("person_id") == person_id),
                None,
            )
            now = self.now_ms()
            if person is None:
                person = {
                    "person_id": person_id,
                    "display_name": display_name,
                    "status": "active",
                    "created_at_ms": now,
                    "updated_at_ms": now,
                }
                public["people"].append(person)
            else:
                person.update(
                    {
                        "display_name": display_name,
                        "status": "active",
                        "updated_at_ms": now,
                    }
                )
            self._write_public_unlocked(public)
            return deepcopy(person)

    def enroll_gallery(
        self,
        *,
        person_id: str,
        embedding: list[float],
        evidence_ref: str,
        model_revision: str,
        pose_bucket: str = "unknown",
        quality_score: float = 1.0,
    ) -> dict[str, Any]:
        person_id = _required_id(person_id, "person_id")
        evidence_ref = _required_id(evidence_ref, "evidence_ref")
        vector = self._validated_vector(embedding)
        entry_id = "face-gallery:" + hashlib.sha256(
            f"{person_id}\n{evidence_ref}\n{model_revision}".encode("utf-8")
        ).hexdigest()
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            person = next(
                (item for item in public["people"] if item.get("person_id") == person_id),
                None,
            )
            if person is None or person.get("status") != "active":
                raise ValueError("gallery person must exist and be active")
            existing = next(
                (
                    item
                    for item in public["gallery_entries"]
                    if item.get("entry_id") == entry_id
                ),
                None,
            )
            if existing is not None:
                return deepcopy(existing)
            item = {
                "entry_id": entry_id,
                "person_id": person_id,
                "evidence_ref": evidence_ref,
                "embedding_ref": f"protected://face-gallery/{entry_id}",
                "model_revision": str(model_revision),
                "pose_bucket": str(pose_bucket or "unknown"),
                "quality_score": round(max(0.01, min(1.0, float(quality_score))), 6),
                "status": "active",
                "created_at_ms": self.now_ms(),
            }
            protected["gallery_embeddings"][entry_id] = vector
            public["gallery_entries"].append(item)
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return deepcopy(item)

    def confirm_candidate(
        self,
        *,
        candidate_id: str,
        person_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        """Bind an anonymous candidate to a user-confirmed person and gallery.

        Candidate member vectors never leave the protected store. Confirmation
        copies at most the selected representative vectors into the protected
        gallery and updates only public references and audit state.
        """

        candidate_id = _required_id(candidate_id, "candidate_id")
        person_id = _required_id(person_id, "person_id")
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("display_name is required")
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            candidate = next(
                (
                    item
                    for item in public["candidates"]
                    if item.get("candidate_id") == candidate_id
                ),
                None,
            )
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate.get("status") in {"frozen", "deleted"}:
                raise ValueError("candidate must be active before confirmation")
            existing_person_id = str(candidate.get("confirmed_person_id") or "")
            if candidate.get("status") == "confirmed" and existing_person_id:
                if existing_person_id != person_id:
                    raise ValueError("candidate is already confirmed as another person")
                return self._candidate_confirmation_result(public, candidate)

            now = self.now_ms()
            person = next(
                (item for item in public["people"] if item.get("person_id") == person_id),
                None,
            )
            if person is None:
                person = {
                    "person_id": person_id,
                    "display_name": display_name,
                    "status": "active",
                    "created_at_ms": now,
                    "updated_at_ms": now,
                }
                public["people"].append(person)
            else:
                person.update(
                    {
                        "display_name": display_name,
                        "status": "active",
                        "updated_at_ms": now,
                    }
                )

            members = protected["candidate_members"].get(candidate_id) or {}
            representatives = list(candidate.get("representatives") or [])
            representative_ids = [
                str(item.get("observation_id") or "")
                for item in representatives
                if item.get("observation_id")
            ]
            if not representative_ids:
                raise ValueError("candidate has no high-quality representative embedding")
            assignments = {
                str(item.get("observation_id") or ""): item
                for item in public["assignments"]
            }
            enrolled_entry_ids: list[str] = []
            for observation_id in representative_ids[: self.max_representatives]:
                vector = members.get(observation_id)
                assignment = assignments.get(observation_id) or {}
                if not vector or not assignment:
                    continue
                evidence_ref = str(assignment.get("evidence_id") or observation_id)
                model_revision = str(assignment.get("model_revision") or "")
                entry_id = "face-gallery:" + hashlib.sha256(
                    f"{person_id}\n{evidence_ref}\n{model_revision}".encode("utf-8")
                ).hexdigest()
                existing_entry = next(
                    (
                        item
                        for item in public["gallery_entries"]
                        if item.get("entry_id") == entry_id
                    ),
                    None,
                )
                if existing_entry is None:
                    representative = next(
                        (
                            item
                            for item in representatives
                            if item.get("observation_id") == observation_id
                        ),
                        {},
                    )
                    existing_entry = {
                        "entry_id": entry_id,
                        "person_id": person_id,
                        "evidence_ref": evidence_ref,
                        "embedding_ref": f"protected://face-gallery/{entry_id}",
                        "model_revision": model_revision,
                        "pose_bucket": "unknown",
                        "quality_score": round(
                            max(
                                0.01,
                                min(
                                    1.0,
                                    float(representative.get("quality_score") or 1.0),
                                ),
                            ),
                            6,
                        ),
                        "status": "active",
                        "source_candidate_id": candidate_id,
                        "created_at_ms": now,
                    }
                    public["gallery_entries"].append(existing_entry)
                    protected["gallery_embeddings"][entry_id] = vector
                enrolled_entry_ids.append(entry_id)

            if not enrolled_entry_ids:
                raise ValueError("candidate has no protected representative embedding")
            candidate.update(
                {
                    "status": "confirmed",
                    "confirmed_person_id": person_id,
                    "confirmed_at_ms": now,
                    "updated_at_ms": now,
                    "gallery_entry_ids": enrolled_entry_ids,
                    "gallery_decision": {
                        "status": "confirmed_by_user",
                        "person_id": person_id,
                        "score": None,
                        "policy_id": self.gallery_policy_id,
                        "requires_user_confirmation": False,
                    },
                }
            )
            candidate_observation_ids = set(candidate.get("observation_ids") or [])
            for assignment in public["assignments"]:
                if assignment.get("observation_id") not in candidate_observation_ids:
                    continue
                assignment.update(
                    {
                        "status": "confirmed_by_user",
                        "candidate_id": candidate_id,
                        "confirmed_person_id": person_id,
                        "gallery_decision_status": "confirmed_by_user",
                        "suggested_person_id": person_id,
                        "reason_codes": ["user_confirmed_candidate"],
                    }
                )
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return self._candidate_confirmation_result(public, candidate)

    @staticmethod
    def _candidate_confirmation_result(
        public: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        person_id = str(candidate.get("confirmed_person_id") or "")
        person = next(
            (item for item in public["people"] if item.get("person_id") == person_id),
            None,
        )
        return {
            "candidate": deepcopy(candidate),
            "person": deepcopy(person),
            "gallery_entries": [
                deepcopy(item)
                for item in public["gallery_entries"]
                if item.get("entry_id") in (candidate.get("gallery_entry_ids") or [])
            ],
        }

    def set_person_status(self, person_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "frozen", "deleted"}:
            raise ValueError("person status must be active, frozen or deleted")
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            person = next(
                (item for item in public["people"] if item.get("person_id") == person_id),
                None,
            )
            if person is None:
                raise KeyError(person_id)
            person["status"] = status
            person["updated_at_ms"] = self.now_ms()
            affected_entries = [
                item
                for item in public["gallery_entries"]
                if item.get("person_id") == person_id
            ]
            if status == "deleted":
                entry_ids = {str(item["entry_id"]) for item in affected_entries}
                public["gallery_entries"] = [
                    item
                    for item in public["gallery_entries"]
                    if item.get("person_id") != person_id
                ]
                for entry_id in entry_ids:
                    protected["gallery_embeddings"].pop(entry_id, None)
                person.pop("display_name", None)
                for assignment in public["assignments"]:
                    if assignment.get("confirmed_person_id") == person_id:
                        assignment.update(
                            {
                                "status": "unassigned_person_deleted",
                                "confirmed_person_id": None,
                                "match_confidence": None,
                                "match_margin": None,
                                "reason_codes": ["confirmed_person_deleted"],
                            }
                        )
            else:
                for entry in affected_entries:
                    entry["status"] = status
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return deepcopy(person)

    def set_candidate_status(self, candidate_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "frozen", "deleted"}:
            raise ValueError("candidate status must be active, frozen or deleted")
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            candidate = next(
                (
                    item
                    for item in public["candidates"]
                    if item.get("candidate_id") == candidate_id
                ),
                None,
            )
            if candidate is None:
                raise KeyError(candidate_id)
            candidate["status"] = status
            candidate["updated_at_ms"] = self.now_ms()
            if status == "deleted":
                protected["candidate_members"].pop(candidate_id, None)
                protected["candidate_weights"].pop(candidate_id, None)
                protected["candidate_centroids"].pop(candidate_id, None)
                for observation_id in candidate.get("observation_ids") or []:
                    if observation_id not in public["candidate_tombstones"]:
                        public["candidate_tombstones"].append(observation_id)
                for assignment in public["assignments"]:
                    if assignment.get("candidate_id") == candidate_id:
                        assignment.update(
                            {
                                "status": "unassigned_candidate_deleted",
                                "candidate_id": None,
                                "match_confidence": None,
                                "reason_codes": ["candidate_deleted"],
                            }
                        )
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return deepcopy(candidate)

    def delete_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Permanently remove an unconfirmed candidate and its biometric state."""

        candidate_id = _required_id(candidate_id, "candidate_id")
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            candidate = next(
                (
                    item
                    for item in public["candidates"]
                    if item.get("candidate_id") == candidate_id
                ),
                None,
            )
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate.get("status") == "confirmed" or candidate.get(
                "confirmed_person_id"
            ):
                raise ValueError(
                    "confirmed candidate must be deleted through its person profile"
                )

            observation_ids = {
                str(item) for item in candidate.get("observation_ids") or [] if item
            }
            public["candidates"] = [
                item
                for item in public["candidates"]
                if item.get("candidate_id") != candidate_id
            ]
            protected["candidate_members"].pop(candidate_id, None)
            protected["candidate_weights"].pop(candidate_id, None)
            protected["candidate_centroids"].pop(candidate_id, None)
            self._anonymize_deleted_assignments(
                public,
                candidate_id=candidate_id,
                person_id=None,
                observation_ids=observation_ids,
                reason="candidate_deleted_by_user",
            )
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return {
                "candidate_id": candidate_id,
                "deleted": True,
                "removed_observation_count": len(observation_ids),
                "removed_gallery_entry_count": 0,
            }

    def delete_person(self, person_id: str) -> dict[str, Any]:
        """Permanently remove a person, linked candidates and gallery vectors."""

        person_id = _required_id(person_id, "person_id")
        with self._lock:
            public = self._read_public_unlocked()
            protected = self._read_protected_unlocked()
            person = next(
                (item for item in public["people"] if item.get("person_id") == person_id),
                None,
            )
            if person is None:
                raise KeyError(person_id)

            linked_candidates = [
                item
                for item in public["candidates"]
                if item.get("confirmed_person_id") == person_id
            ]
            linked_candidate_ids = {
                str(item["candidate_id"])
                for item in linked_candidates
                if item.get("candidate_id")
            }
            observation_ids = {
                str(observation_id)
                for candidate in linked_candidates
                for observation_id in candidate.get("observation_ids") or []
                if observation_id
            }
            gallery_entry_ids = {
                str(item["entry_id"])
                for item in public["gallery_entries"]
                if item.get("person_id") == person_id and item.get("entry_id")
            }

            public["people"] = [
                item for item in public["people"] if item.get("person_id") != person_id
            ]
            public["gallery_entries"] = [
                item
                for item in public["gallery_entries"]
                if item.get("person_id") != person_id
            ]
            public["candidates"] = [
                item
                for item in public["candidates"]
                if item.get("candidate_id") not in linked_candidate_ids
            ]
            for entry_id in gallery_entry_ids:
                protected["gallery_embeddings"].pop(entry_id, None)
            for candidate_id in linked_candidate_ids:
                protected["candidate_members"].pop(candidate_id, None)
                protected["candidate_weights"].pop(candidate_id, None)
                protected["candidate_centroids"].pop(candidate_id, None)
            self._anonymize_deleted_assignments(
                public,
                candidate_id=None,
                person_id=person_id,
                observation_ids=observation_ids,
                reason="person_deleted_by_user",
            )
            for candidate in public["candidates"]:
                decision = candidate.get("gallery_decision") or {}
                if decision.get("person_id") == person_id:
                    candidate["gallery_decision"] = {
                        "status": "person_deleted",
                        "requires_user_confirmation": True,
                    }
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return {
                "person_id": person_id,
                "deleted": True,
                "removed_candidate_count": len(linked_candidate_ids),
                "removed_observation_count": len(observation_ids),
                "removed_gallery_entry_count": len(gallery_entry_ids),
            }

    @staticmethod
    def _anonymize_deleted_assignments(
        public: dict[str, Any],
        *,
        candidate_id: str | None,
        person_id: str | None,
        observation_ids: set[str],
        reason: str,
    ) -> None:
        for observation_id in observation_ids:
            if observation_id not in public["candidate_tombstones"]:
                public["candidate_tombstones"].append(observation_id)
        for assignment in public["assignments"]:
            matches_candidate = bool(
                candidate_id and assignment.get("candidate_id") == candidate_id
            )
            matches_person = bool(
                person_id
                and (
                    assignment.get("confirmed_person_id") == person_id
                    or assignment.get("suggested_person_id") == person_id
                )
            )
            if not (
                matches_candidate
                or matches_person
                or assignment.get("observation_id") in observation_ids
            ):
                continue
            assignment.update(
                {
                    "status": "unassigned_identity_deleted",
                    "candidate_id": None,
                    "confirmed_person_id": None,
                    "suggested_person_id": None,
                    "gallery_decision_status": None,
                    "match_confidence": None,
                    "match_margin": None,
                    "reason_codes": [reason],
                }
            )

    def assign_observation(
        self,
        observation: dict[str, Any],
        embedding: list[float] | None,
    ) -> dict[str, Any]:
        observation_id = _required_id(observation.get("observation_id"), "observation_id")
        with self._lock:
            public = self._read_public_unlocked()
            existing = next(
                (
                    item
                    for item in public["assignments"]
                    if item.get("observation_id") == observation_id
                ),
                None,
            )
            if existing is not None:
                return deepcopy(existing)
            protected = self._read_protected_unlocked()
            base = self._assignment_base(observation)
            quality = dict(observation.get("quality") or {})
            quality_reason_codes = list(quality.get("reason_codes") or [])
            representative_eligible = bool(quality.get("eligible_for_match"))
            discard_reason_codes = [
                reason
                for reason in quality_reason_codes
                if reason in self.anonymous_discard_reason_codes
            ]
            if observation_id in public["candidate_tombstones"]:
                assignment = {
                    **base,
                    "status": "unassigned_candidate_deleted",
                    "candidate_id": None,
                    "confirmed_person_id": None,
                    "match_confidence": None,
                    "match_margin": None,
                    "reason_codes": ["candidate_deleted"],
                }
            elif discard_reason_codes:
                assignment = {
                    **base,
                    "status": "unassigned_low_quality",
                    "candidate_id": None,
                    "confirmed_person_id": None,
                    "match_confidence": None,
                    "match_margin": None,
                    "reason_codes": discard_reason_codes,
                }
            elif not embedding:
                assignment = {
                    **base,
                    "status": "unassigned_missing_embedding",
                    "candidate_id": None,
                    "confirmed_person_id": None,
                    "match_confidence": None,
                    "match_margin": None,
                    "reason_codes": ["missing_protected_embedding"],
                }
            else:
                vector = self._validated_vector(embedding)
                gallery = (
                    self._gallery_match(public, protected, observation, vector)
                    if representative_eligible and self.single_frame_automatic_confirmation
                    else {
                        "status": "anonymous_candidate",
                        "confirmed_person_id": None,
                        "match_confidence": None,
                        "match_margin": None,
                        "reason_codes": (
                            ["candidate_evidence_required"]
                            if representative_eligible
                            else quality_reason_codes or ["candidate_only_low_quality"]
                        ),
                    }
                )
                if gallery["confirmed_person_id"]:
                    assignment = {**base, **gallery, "candidate_id": None}
                else:
                    assignment = self._assign_anonymous(
                        public,
                        protected,
                        observation,
                        vector,
                        base=base,
                        gallery=gallery,
                        representative_eligible=representative_eligible,
                    )
            public["assignments"].append(assignment)
            self._write_protected_unlocked(protected)
            self._write_public_unlocked(public)
            return deepcopy(assignment)

    def assignment_for_observation(self, observation_id: str) -> dict[str, Any] | None:
        with self._lock:
            assignment = next(
                (
                    item
                    for item in self._read_public_unlocked()["assignments"]
                    if item.get("observation_id") == observation_id
                ),
                None,
            )
            return deepcopy(assignment) if assignment is not None else None

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read_public_unlocked())

    def summary(self) -> dict[str, Any]:
        public = self.public_snapshot()
        counts: dict[str, int] = {}
        for item in public["assignments"]:
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "people": len([item for item in public["people"] if item.get("status") != "deleted"]),
            "gallery_entries": len(public["gallery_entries"]),
            "active_candidates": len(
                [item for item in public["candidates"] if item.get("status") == "active"]
            ),
            "assignments": len(public["assignments"]),
            "assignment_counts": counts,
            "config_version": self.config_version,
            "gallery_policy_id": self.gallery_policy_id,
        }

    def _gallery_match(
        self,
        public: dict[str, Any],
        protected: dict[str, Any],
        observation: dict[str, Any],
        vector: list[float],
    ) -> dict[str, Any]:
        active_people = {
            str(item["person_id"])
            for item in public["people"]
            if item.get("status") == "active"
        }
        scores: dict[str, float] = {}
        for entry in public["gallery_entries"]:
            if entry.get("status") != "active":
                continue
            if entry.get("model_revision") != observation.get("model_revision"):
                continue
            person_id = str(entry.get("person_id") or "")
            if person_id not in active_people:
                continue
            gallery_vector = protected["gallery_embeddings"].get(entry.get("entry_id"))
            if not gallery_vector:
                continue
            score = _cosine(vector, gallery_vector)
            scores[person_id] = max(scores.get(person_id, -1.0), score)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < self.gallery_threshold:
            return {
                "status": "anonymous_candidate",
                "confirmed_person_id": None,
                "match_confidence": None,
                "match_margin": None,
                "reason_codes": ["gallery_no_match"],
            }
        best_person, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else -1.0
        margin = best_score - second_score if len(ranked) > 1 else 2.0
        if margin < self.gallery_margin:
            return {
                "status": "anonymous_candidate",
                "confirmed_person_id": None,
                "match_confidence": round(best_score, 6),
                "match_margin": round(margin, 6),
                "reason_codes": ["gallery_ambiguous"],
            }
        return {
            "status": "confirmed_gallery",
            "confirmed_person_id": best_person,
            "match_confidence": round(best_score, 6),
            "match_margin": round(margin, 6),
            "reason_codes": [],
        }

    def _assign_anonymous(
        self,
        public: dict[str, Any],
        protected: dict[str, Any],
        observation: dict[str, Any],
        vector: list[float],
        *,
        base: dict[str, Any],
        gallery: dict[str, Any],
        representative_eligible: bool,
    ) -> dict[str, Any]:
        evidence_id = str(observation.get("evidence_id") or "")
        model_revision = str(observation.get("model_revision") or "")
        ranked: list[tuple[float, dict[str, Any], str, str]] = []
        for candidate in public["candidates"]:
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate.get("status") != "active":
                continue
            if model_revision not in (candidate.get("model_revisions") or []):
                continue
            if evidence_id and evidence_id in (candidate.get("evidence_ids") or []):
                continue
            members = protected["candidate_members"].get(candidate_id) or {}
            templates = self._candidate_matching_templates(candidate, members)
            if not templates:
                continue
            score, matched_observation_id, match_basis = max(
                (
                    _cosine(vector, template_vector),
                    template_observation_id,
                    template_basis,
                )
                for template_observation_id, template_vector, template_basis in templates
            )
            if score >= self.anonymous_threshold:
                ranked.append(
                    (score, candidate, matched_observation_id, match_basis)
                )
        if ranked:
            score, candidate, matched_observation_id, match_basis = max(
                ranked, key=lambda item: item[0]
            )
        else:
            score = None
            matched_observation_id = None
            match_basis = "new_candidate"
            candidate_id = "face-candidate:" + hashlib.sha256(
                str(observation["observation_id"]).encode("utf-8")
            ).hexdigest()[:20]
            candidate = {
                "candidate_id": candidate_id,
                "status": "active",
                "seed_observation_id": str(observation["observation_id"]),
                "observation_ids": [],
                "evidence_ids": [],
                "first_seen_at_ms": int(observation.get("captured_at_ms") or 0),
                "last_seen_at_ms": int(observation.get("captured_at_ms") or 0),
                "model_revisions": [model_revision],
                "config_versions": [str(observation.get("config_version") or "")],
                "pose_buckets": [],
                "representatives": [],
                "representative_evidence_id": None,
                "gallery_decision": {"status": "insufficient_evidence"},
                "created_at_ms": self.now_ms(),
                "updated_at_ms": self.now_ms(),
            }
            public["candidates"].append(candidate)
            protected["candidate_members"][candidate_id] = {}
            protected["candidate_weights"][candidate_id] = {}
        candidate_id = str(candidate["candidate_id"])
        protected["candidate_members"].setdefault(candidate_id, {})[
            str(observation["observation_id"])
        ] = vector
        protected["candidate_weights"].setdefault(candidate_id, {})[
            str(observation["observation_id"])
        ] = max(0.05, _representative_quality(observation))
        observation_id = str(observation["observation_id"])
        if observation_id not in candidate["observation_ids"]:
            candidate["observation_ids"].append(observation_id)
        if evidence_id and evidence_id not in candidate["evidence_ids"]:
            candidate["evidence_ids"].append(evidence_id)
        captured_at_ms = int(observation.get("captured_at_ms") or 0)
        existing_first_seen = candidate.get("first_seen_at_ms")
        candidate["first_seen_at_ms"] = (
            captured_at_ms
            if existing_first_seen is None
            else min(int(existing_first_seen), captured_at_ms)
        )
        candidate["last_seen_at_ms"] = max(
            int(candidate.get("last_seen_at_ms") or 0), captured_at_ms
        )
        candidate["observation_count"] = len(candidate["observation_ids"])
        pose_bucket = str((observation.get("quality") or {}).get("pose_bucket") or "unknown")
        pose_buckets = candidate.setdefault("pose_buckets", [])
        if pose_bucket not in pose_buckets:
            pose_buckets.append(pose_bucket)
        candidate["updated_at_ms"] = self.now_ms()
        if representative_eligible:
            self._update_representatives(candidate, observation)
        self._refresh_candidate_centroid(candidate, protected)
        candidate["gallery_decision"] = self._candidate_gallery_decision(
            public,
            protected,
            candidate,
        )
        reasons = list(gallery.get("reason_codes") or [])
        decision = dict(candidate.get("gallery_decision") or {})
        return {
            **base,
            "status": "anonymous_candidate",
            "candidate_id": candidate_id,
            "confirmed_person_id": None,
            "match_confidence": round(float(score), 6) if score is not None else None,
            "match_margin": gallery.get("match_margin"),
            "match_basis": match_basis,
            "matched_representative_observation_id": matched_observation_id,
            "representative_eligible": representative_eligible,
            "gallery_decision_status": decision.get("status"),
            "suggested_person_id": decision.get("person_id"),
            "suggestion_confidence": decision.get("score"),
            "reason_codes": reasons,
        }

    def _candidate_gallery_decision(
        self,
        public: dict[str, Any],
        protected: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        count = int(candidate.get("observation_count") or 0)
        evidence_count = len(candidate.get("evidence_ids") or [])
        span_ms = max(
            0,
            int(candidate.get("last_seen_at_ms") or 0)
            - int(candidate.get("first_seen_at_ms") or 0),
        )
        support = {
            "observation_count": count,
            "distinct_evidence_count": evidence_count,
            "time_span_ms": span_ms,
        }
        if (
            count < self.candidate_gallery_min_observations
            or evidence_count < self.candidate_gallery_min_evidence
            or span_ms < self.candidate_gallery_min_span_ms
        ):
            return {
                "status": "insufficient_evidence",
                "person_id": None,
                "policy_id": self.gallery_policy_id,
                "support": support,
            }
        vector = self._candidate_representative_vector(candidate, protected)
        if not vector:
            return {
                "status": "no_match",
                "person_id": None,
                "policy_id": self.gallery_policy_id,
                "support": support,
            }
        active_people = {
            str(item["person_id"])
            for item in public["people"]
            if item.get("status") == "active"
        }
        scores_by_person: dict[str, list[tuple[float, float]]] = {}
        model_revisions = set(candidate.get("model_revisions") or [])
        for entry in public["gallery_entries"]:
            person_id = str(entry.get("person_id") or "")
            if entry.get("status") != "active" or person_id not in active_people:
                continue
            if entry.get("model_revision") not in model_revisions:
                continue
            gallery_vector = protected["gallery_embeddings"].get(entry.get("entry_id"))
            if not gallery_vector:
                continue
            scores_by_person.setdefault(person_id, []).append(
                (
                    _cosine(vector, gallery_vector),
                    max(0.01, float(entry.get("quality_score") or 1.0)),
                )
            )
        ranked = sorted(
            (
                (_top_k_weighted_score(values, self.gallery_top_k), person_id)
                for person_id, values in scores_by_person.items()
            ),
            reverse=True,
        )
        if not ranked or ranked[0][0] < self.gallery_suggestion_threshold:
            return {
                "status": "no_match",
                "person_id": None,
                "score": round(ranked[0][0], 6) if ranked else None,
                "policy_id": self.gallery_policy_id,
                "support": support,
            }
        best_score, best_person = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else -1.0
        margin = best_score - second_score if len(ranked) > 1 else 2.0
        if margin < self.gallery_margin:
            return {
                "status": "ambiguous",
                "person_id": None,
                "score": round(best_score, 6),
                "margin": round(margin, 6),
                "policy_id": self.gallery_policy_id,
                "support": support,
            }
        tier = "suggested_high" if best_score >= self.gallery_threshold else "suggested_gray"
        return {
            "status": tier,
            "person_id": best_person,
            "score": round(best_score, 6),
            "margin": round(margin, 6),
            "requires_user_confirmation": self.candidate_level_requires_confirmation,
            "policy_id": self.gallery_policy_id,
            "support": support,
        }

    def _update_representatives(
        self,
        candidate: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        row = {
            "observation_id": str(observation["observation_id"]),
            "evidence_id": str(observation.get("evidence_id") or ""),
            "captured_at_ms": int(observation.get("captured_at_ms") or 0),
            "bbox": list(observation.get("bbox") or []),
            "quality_score": round(_representative_quality(observation), 6),
        }
        pool = [
            item
            for item in candidate.get("representative_pool") or []
            if item.get("observation_id") != row["observation_id"]
        ]
        pool.append(row)
        pool.sort(
            key=lambda item: (
                float(item.get("quality_score") or 0.0),
                -int(item.get("captured_at_ms") or 0),
            ),
            reverse=True,
        )
        candidate["representative_pool"] = pool[:20]
        selected: list[dict[str, Any]] = []
        for item in pool:
            if any(item.get("evidence_id") == other.get("evidence_id") for other in selected):
                continue
            selected.append(item)
            if len(selected) >= self.max_representatives:
                break
        candidate["representatives"] = selected
        candidate["representative_evidence_id"] = (
            selected[0].get("evidence_id") if selected else None
        )

    @staticmethod
    def _candidate_matching_templates(
        candidate: dict[str, Any],
        members: dict[str, list[float]],
    ) -> list[tuple[str, list[float], str]]:
        representatives = [
            str(item.get("observation_id") or "")
            for item in candidate.get("representatives") or []
            if item.get("observation_id")
        ]
        templates = [
            (observation_id, members[observation_id], "representative")
            for observation_id in representatives
            if members.get(observation_id)
        ]
        if templates:
            return templates

        # A low-quality-but-matchable first face may start a provisional
        # candidate. Its immutable seed is the only fallback until a qualified
        # representative joins; later low-quality members never become templates.
        seed_observation_id = str(candidate.get("seed_observation_id") or "")
        if not seed_observation_id:
            seed_observation_id = str((candidate.get("observation_ids") or [""])[0])
        seed_vector = members.get(seed_observation_id)
        return (
            [(seed_observation_id, seed_vector, "provisional_seed")]
            if seed_observation_id and seed_vector
            else []
        )

    def _candidate_representative_vector(
        self,
        candidate: dict[str, Any],
        protected: dict[str, Any],
    ) -> list[float] | None:
        candidate_id = str(candidate.get("candidate_id") or "")
        members = protected["candidate_members"].get(candidate_id) or {}
        representative_ids = [
            str(item.get("observation_id") or "")
            for item in candidate.get("representatives") or []
            if item.get("observation_id") and members.get(item.get("observation_id"))
        ]
        if not representative_ids:
            return None
        weights = protected["candidate_weights"].get(candidate_id) or {}
        representative_members = {
            observation_id: members[observation_id]
            for observation_id in representative_ids
        }
        representative_weights = {
            observation_id: weights.get(observation_id, 1.0)
            for observation_id in representative_ids
        }
        return _weighted_centroid(representative_members, representative_weights)

    def _refresh_candidate_centroid(
        self,
        candidate: dict[str, Any],
        protected: dict[str, Any],
    ) -> None:
        candidate_id = str(candidate["candidate_id"])
        vector = self._candidate_representative_vector(candidate, protected)
        if vector is None:
            members = protected["candidate_members"].get(candidate_id) or {}
            seed_id = str(candidate.get("seed_observation_id") or "")
            vector = members.get(seed_id)
        if vector:
            protected["candidate_centroids"][candidate_id] = vector
        else:
            protected["candidate_centroids"].pop(candidate_id, None)

    def _assignment_base(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": str(observation["observation_id"]),
            "job_id": str(observation.get("job_id") or ""),
            "evidence_id": str(observation.get("evidence_id") or ""),
            "captured_at_ms": int(observation.get("captured_at_ms") or 0),
            "model_revision": str(observation.get("model_revision") or ""),
            "config_version": str(observation.get("config_version") or ""),
            "boot_session_id": str(observation.get("boot_session_id") or ""),
            "window_id": str(observation.get("window_id") or ""),
            "assigned_at_ms": self.now_ms(),
        }

    def _validated_vector(self, value: list[float]) -> list[float]:
        vector = [float(item) for item in value]
        if self.embedding_dimension and len(vector) != self.embedding_dimension:
            raise ValueError(
                f"face embedding dimension {len(vector)} != {self.embedding_dimension}"
            )
        if not vector or any(not math.isfinite(item) for item in vector):
            raise ValueError("face embedding must contain finite values")
        norm = math.sqrt(sum(item * item for item in vector))
        if norm <= 0:
            raise ValueError("face embedding norm must be positive")
        return [item / norm for item in vector]

    def _read_public_unlocked(self) -> dict[str, Any]:
        empty = {
            "contract_version": 1,
            "people": [],
            "gallery_entries": [],
            "candidates": [],
            "assignments": [],
            "candidate_tombstones": [],
        }
        return self._read_json(self.public_path, empty, protected=False)

    def _read_protected_unlocked(self) -> dict[str, Any]:
        empty = {
            "contract_version": 1,
            "gallery_embeddings": {},
            "candidate_members": {},
            "candidate_weights": {},
            "candidate_centroids": {},
        }
        return self._read_json(self.protected_path, empty, protected=True)

    @staticmethod
    def _read_json(path: Path, empty: dict[str, Any], *, protected: bool) -> dict[str, Any]:
        if not path.is_file():
            return deepcopy(empty)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            kind = "protected identity" if protected else "identity directory"
            raise RuntimeError(f"cannot read {kind} store: {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"identity store root must be an object: {path}")
        return {**deepcopy(empty), **value}

    def _write_public_unlocked(self, value: dict[str, Any]) -> None:
        _atomic_json(self.public_path, value, protected=False)

    def _write_protected_unlocked(self, value: dict[str, Any]) -> None:
        _atomic_json(self.protected_path, value, protected=True)


class IdentityCandidateProcessor:
    """Projects immutable worker observations into gallery/candidate assignments."""

    def __init__(self, *, job_store: IdentityJobStore, directory: IdentityDirectoryStore) -> None:
        self.job_store = job_store
        self.directory = directory

    def process_job(self, job_id: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for observation in self.job_store.observations_for_job(job_id):
            output.append(self.process_observation(observation))
        return output

    def process_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        observation_id = str(observation["observation_id"])
        embedding = self.job_store.protected_embedding(observation_id)
        return self.directory.assign_observation(observation, embedding)

    def recover_unassigned(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for observation in self.job_store.recent_observations(limit=limit):
            if self.directory.assignment_for_observation(str(observation["observation_id"])):
                continue
            output.append(self.process_observation(observation))
        return output

    def summary(self) -> dict[str, Any]:
        return self.directory.summary()


def _required_id(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} is required")
    return result


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    return sum(a * b for a, b in zip(left, right))


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    summed = [sum(values) for values in zip(*vectors)]
    norm = math.sqrt(sum(item * item for item in summed))
    return [item / norm for item in summed] if norm > 0 else []


def _weighted_centroid(
    vectors: dict[str, list[float]],
    weights: dict[str, float],
) -> list[float]:
    if not vectors:
        return []
    dimension = len(next(iter(vectors.values())))
    summed = [0.0] * dimension
    for observation_id, vector in vectors.items():
        visual_weight = max(0.01, float(weights.get(observation_id) or 1.0))
        others = [
            other
            for other_id, other in vectors.items()
            if other_id != observation_id
        ]
        agreement_weight = (
            max(0.05, sum(_cosine(vector, other) for other in others) / len(others))
            if others
            else 1.0
        )
        weight = visual_weight * agreement_weight
        for index, value in enumerate(vector):
            summed[index] += value * weight
    norm = math.sqrt(sum(item * item for item in summed))
    return [item / norm for item in summed] if norm > 0 else []


def _top_k_weighted_score(values: list[tuple[float, float]], top_k: int) -> float:
    selected = sorted(values, key=lambda item: item[0], reverse=True)[: max(1, top_k)]
    total_weight = sum(weight for _, weight in selected)
    if total_weight <= 0:
        return -1.0
    return sum(score * weight for score, weight in selected) / total_weight


def _representative_quality(observation: dict[str, Any]) -> float:
    quality = dict(observation.get("quality") or {})
    detection = max(0.0, min(1.0, float(observation.get("detection_score") or 0.0)))
    ratio = max(0.0, float(quality.get("face_frame_ratio") or 0.0))
    sharpness = max(0.0, float(quality.get("laplacian_variance") or 0.0))
    landmarks = 1.0 if quality.get("five_landmarks_available") else 0.0
    return (
        0.45 * detection
        + 0.25 * min(1.0, ratio / 0.10)
        + 0.20 * min(1.0, sharpness / 200.0)
        + 0.10 * landmarks
    )


def _atomic_json(path: Path, value: dict[str, Any], *, protected: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    if protected:
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    if protected:
        os.chmod(path, 0o600)
