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


class VoiceCandidateDirectory:
    """Anonymous cross-window voice candidates with protected vectors."""

    def __init__(
        self,
        public_path: str | Path,
        *,
        protected_path: str | Path,
        config_path: str | Path,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.public_path = Path(public_path)
        self.protected_path = Path(protected_path)
        self.config_path = Path(config_path)
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if config.get("status") != "production_locked":
            raise ValueError("voice directory requires production_locked config")
        self.config_version = str(config["config_version"])
        self.candidate_threshold = float(config["candidate_threshold"])
        gallery_threshold = config.get("gallery_threshold")
        self.gallery_threshold = (
            float(gallery_threshold) if gallery_threshold is not None else None
        )
        margin = config.get("ambiguity_margin")
        self.gallery_margin = float(margin) if margin is not None else None
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()

    def enroll_gallery_suggestion_source(
        self,
        *,
        person_id: str,
        display_name: str,
        embedding: list[float],
        evidence_ref: str,
        model_revision: str,
    ) -> dict[str, Any]:
        """Store a protected, user-supplied voice template for suggestions only."""

        person_id = str(person_id or "").strip()
        display_name = str(display_name or "").strip()
        evidence_ref = str(evidence_ref or "").strip()
        model_revision = str(model_revision or "").strip()
        if not all((person_id, display_name, evidence_ref, model_revision)):
            raise ValueError("voice gallery source requires person, evidence and revision")
        vector = _normalize(embedding)
        entry_id = "voice-gallery:" + hashlib.sha256(
            f"{person_id}\n{evidence_ref}\n{model_revision}".encode("utf-8")
        ).hexdigest()
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
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
            entry = {
                "entry_id": entry_id,
                "person_id": person_id,
                "display_name": display_name,
                "evidence_ref": evidence_ref,
                "embedding_ref": f"protected://voice-gallery/{entry_id}",
                "model_revision": model_revision,
                "status": "active",
                "suggestion_only": True,
                "created_at_ms": self.now_ms(),
            }
            public["gallery_entries"].append(entry)
            protected["gallery_embeddings"][entry_id] = vector
            self._write_protected(protected)
            self._write_public(public)
            return deepcopy(entry)

    def ingest_local_speaker(
        self,
        *,
        job: dict[str, Any],
        speaker_local_id: str,
        turns: list[dict[str, Any]],
        embeddings: list[tuple[list[float], int]],
    ) -> dict[str, Any]:
        if not embeddings:
            return {
                "status": "unassigned_missing_embedding",
                "candidate_id": None,
                "confirmed_person_id": None,
                "match_confidence": None,
                "gallery_suggestion": None,
            }
        observation_id = _voice_observation_id(str(job["job_id"]), speaker_local_id)
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
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
            vector = _weighted_centroid(embeddings)
            candidates_used_in_job = {
                str(item.get("candidate_id"))
                for item in public["assignments"]
                if item.get("job_id") == job["job_id"] and item.get("candidate_id")
            }
            ranked: list[tuple[float, dict[str, Any]]] = []
            for candidate in public["candidates"]:
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate.get("status") not in {"active", "confirmed"}:
                    continue
                if candidate_id in candidates_used_in_job:
                    continue
                if str(job["model_revision"]) not in candidate.get("model_revisions", []):
                    continue
                centroid = protected["candidate_centroids"].get(candidate_id)
                members = protected["candidate_members"].get(candidate_id) or {}
                if not centroid or not members:
                    continue
                score = _cosine(vector, centroid)
                if score < self.candidate_threshold:
                    continue
                if min(_cosine(vector, member) for member in members.values()) < self.candidate_threshold:
                    continue
                ranked.append((score, candidate))
            if ranked:
                match_score, candidate = max(ranked, key=lambda item: item[0])
            else:
                match_score = 1.0
                candidate_id = "voice-candidate:" + hashlib.sha256(
                    observation_id.encode("utf-8")
                ).hexdigest()[:20]
                candidate = {
                    "candidate_id": candidate_id,
                    "display_name": f"匿名说话人 {len(public['candidates']) + 1}",
                    "status": "active",
                    "confirmed_person_id": None,
                    "observation_ids": [],
                    "job_ids": [],
                    "window_ids": [],
                    "evidence_ids": [],
                    "model_revisions": [str(job["model_revision"])],
                    "config_versions": [str(job["config_version"])],
                    "first_heard_at_ms": int(job["captured_at_ms"]),
                    "last_heard_at_ms": int(job["captured_at_ms"]),
                    "representative_turns": [],
                    "gallery_suggestion": None,
                    "created_at_ms": self.now_ms(),
                    "updated_at_ms": self.now_ms(),
                }
                public["candidates"].append(candidate)
                protected["candidate_members"][candidate_id] = {}
            candidate_id = str(candidate["candidate_id"])
            protected["candidate_members"].setdefault(candidate_id, {})[
                observation_id
            ] = vector
            protected["candidate_centroids"][candidate_id] = _centroid(
                list(protected["candidate_members"][candidate_id].values())
            )
            candidate["observation_ids"].append(observation_id)
            for key, value in (
                ("job_ids", str(job["job_id"])),
                ("window_ids", str(job.get("window_id") or "")),
                ("evidence_ids", str(job.get("audio_evidence_id") or "")),
            ):
                if value and value not in candidate[key]:
                    candidate[key].append(value)
            captured_at_ms = int(job["captured_at_ms"])
            candidate["first_heard_at_ms"] = min(
                int(candidate.get("first_heard_at_ms") or captured_at_ms), captured_at_ms
            )
            candidate["last_heard_at_ms"] = max(
                int(candidate.get("last_heard_at_ms") or 0), captured_at_ms
            )
            candidate["observation_count"] = len(candidate["observation_ids"])
            candidate["updated_at_ms"] = self.now_ms()
            candidate["embedding_ref"] = f"protected://voice-candidate/{candidate_id}"
            representative = _representative_turn(turns)
            if representative and not any(
                item.get("turn_id") == representative.get("turn_id")
                for item in candidate["representative_turns"]
            ):
                candidate["representative_turns"].append(representative)
                candidate["representative_turns"] = sorted(
                    candidate["representative_turns"],
                    key=lambda item: int(item.get("duration_ms") or 0),
                    reverse=True,
                )[:5]
            candidate["gallery_suggestion"] = self._gallery_suggestion(
                public, protected, vector, model_revision=str(job["model_revision"])
            )
            confirmed_person_id = str(candidate.get("confirmed_person_id") or "") or None
            assignment = {
                "observation_id": observation_id,
                "job_id": str(job["job_id"]),
                "window_id": str(job.get("window_id") or ""),
                "audio_evidence_id": str(job.get("audio_evidence_id") or ""),
                "speaker_local_id": speaker_local_id,
                "status": (
                    "confirmed_identity" if confirmed_person_id else "anonymous_candidate"
                ),
                "candidate_id": candidate_id,
                "display_name": str(candidate["display_name"]),
                "confirmed_person_id": confirmed_person_id,
                "match_confidence": round(match_score, 6),
                "gallery_suggestion": deepcopy(candidate["gallery_suggestion"]),
                "turn_ids": [str(item["turn_id"]) for item in turns],
                "captured_at_ms": captured_at_ms,
                "model_revision": str(job["model_revision"]),
                "config_version": str(job["config_version"]),
                "created_at_ms": self.now_ms(),
            }
            public["assignments"].append(assignment)
            self._write_protected(protected)
            self._write_public(public)
            return deepcopy(assignment)

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read_public())

    def confirm_candidate(
        self,
        *,
        candidate_id: str,
        person_id: str,
        display_name: str,
        actor: str,
    ) -> dict[str, Any]:
        """Bind one voice candidate to a user-confirmed person without vector fusion."""

        candidate_id = _required_text(candidate_id, "candidate_id")
        person_id = _required_text(person_id, "person_id")
        display_name = _required_text(display_name, "display_name")
        actor = _required_text(actor, "actor")
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
            candidate = next(
                (
                    item
                    for item in public["candidates"]
                    if item.get("candidate_id") == candidate_id
                ),
                None,
            )
            if candidate is None or candidate.get("status") == "deleted":
                raise KeyError(candidate_id)
            existing_person_id = str(candidate.get("confirmed_person_id") or "")
            if existing_person_id:
                if existing_person_id != person_id:
                    raise ValueError(
                        "voice candidate is already bound; unbind it before rebinding"
                    )
                link = next(
                    (
                        item
                        for item in public["identity_links"]
                        if item.get("candidate_id") == candidate_id
                        and item.get("person_id") == person_id
                    ),
                    None,
                )
                if link is None:
                    raise RuntimeError("confirmed voice candidate is missing identity link")
                return {
                    "candidate": deepcopy(candidate),
                    "link": deepcopy(link),
                    "idempotent": True,
                }

            now = self.now_ms()
            link_id = "identity-link:" + hashlib.sha256(
                f"voice\n{candidate_id}\n{person_id}".encode("utf-8")
            ).hexdigest()
            link_version = 1 + sum(
                1
                for item in public["link_audit"]
                if item.get("candidate_id") == candidate_id
                and item.get("action") == "bind"
            )
            link = {
                "link_id": link_id,
                "modality": "voice",
                "candidate_id": candidate_id,
                "person_id": person_id,
                "display_name": display_name,
                "status": "active",
                "version": link_version,
                "confirmed_by": actor,
                "confirmed_at_ms": now,
                "updated_at_ms": now,
            }
            public["identity_links"].append(link)
            candidate.update(
                {
                    "status": "confirmed",
                    "confirmed_person_id": person_id,
                    "display_name": display_name,
                    "updated_at_ms": now,
                }
            )
            for assignment in public["assignments"]:
                if assignment.get("candidate_id") != candidate_id:
                    continue
                assignment.update(
                    {
                        "status": "confirmed_identity",
                        "confirmed_person_id": person_id,
                        "display_name": display_name,
                    }
                )

            centroid = protected["candidate_centroids"].get(candidate_id)
            if not centroid:
                raise ValueError("voice candidate has no protected centroid")
            model_revisions = [
                str(item)
                for item in candidate.get("model_revisions") or []
                if str(item).strip()
            ]
            if not model_revisions:
                raise ValueError("voice candidate has no model revision")
            gallery_entry_id = "voice-gallery:" + hashlib.sha256(
                f"{person_id}\n{candidate_id}\n{model_revisions[0]}".encode("utf-8")
            ).hexdigest()
            gallery_entry = {
                "entry_id": gallery_entry_id,
                "person_id": person_id,
                "display_name": display_name,
                "evidence_ref": candidate_id,
                "source_candidate_id": candidate_id,
                "embedding_ref": f"protected://voice-gallery/{gallery_entry_id}",
                "model_revision": model_revisions[0],
                "status": "active",
                "suggestion_only": True,
                "created_at_ms": now,
            }
            public["gallery_entries"] = [
                item
                for item in public["gallery_entries"]
                if item.get("entry_id") != gallery_entry_id
            ]
            public["gallery_entries"].append(gallery_entry)
            protected["gallery_embeddings"][gallery_entry_id] = list(centroid)
            public["link_audit"].append(
                {
                    "audit_id": "identity-audit:" + hashlib.sha256(
                        f"bind\n{link_id}\n{now}".encode("utf-8")
                    ).hexdigest(),
                    "action": "bind",
                    "link_id": link_id,
                    "candidate_id": candidate_id,
                    "person_id": person_id,
                    "version": link_version,
                    "actor": actor,
                    "reason": "user_confirmation",
                    "created_at_ms": now,
                }
            )
            self._write_protected(protected)
            self._write_public(public)
            return {
                "candidate": deepcopy(candidate),
                "link": deepcopy(link),
                "gallery_entry": deepcopy(gallery_entry),
                "idempotent": False,
            }

    def unbind_candidate(
        self,
        *,
        candidate_id: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        """Detach only the voice relationship and keep source observations intact."""

        candidate_id = _required_text(candidate_id, "candidate_id")
        actor = _required_text(actor, "actor")
        reason = _required_text(reason, "reason")
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
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
            person_id = str(candidate.get("confirmed_person_id") or "")
            if not person_id:
                raise ValueError("voice candidate is not bound")
            active_link = next(
                (
                    item
                    for item in public["identity_links"]
                    if item.get("candidate_id") == candidate_id
                    and item.get("person_id") == person_id
                ),
                None,
            )
            now = self.now_ms()
            public["identity_links"] = [
                item
                for item in public["identity_links"]
                if item.get("candidate_id") != candidate_id
            ]
            anonymous_name = str(
                candidate.get("anonymous_display_name")
                or f"匿名说话人 {public['candidates'].index(candidate) + 1}"
            )
            candidate.update(
                {
                    "status": "active",
                    "confirmed_person_id": None,
                    "display_name": anonymous_name,
                    "updated_at_ms": now,
                }
            )
            for assignment in public["assignments"]:
                if assignment.get("candidate_id") != candidate_id:
                    continue
                assignment.update(
                    {
                        "status": "anonymous_candidate",
                        "confirmed_person_id": None,
                        "display_name": anonymous_name,
                    }
                )
            for entry in public["gallery_entries"]:
                if entry.get("source_candidate_id") != candidate_id:
                    continue
                entry["status"] = "revoked"
                protected["gallery_embeddings"].pop(str(entry.get("entry_id") or ""), None)
            link_id = str((active_link or {}).get("link_id") or "")
            public["link_audit"].append(
                {
                    "audit_id": "identity-audit:" + hashlib.sha256(
                        f"unbind\n{candidate_id}\n{person_id}\n{now}".encode("utf-8")
                    ).hexdigest(),
                    "action": "unbind",
                    "link_id": link_id,
                    "candidate_id": candidate_id,
                    "person_id": person_id,
                    "actor": actor,
                    "reason": reason,
                    "created_at_ms": now,
                }
            )
            self._write_protected(protected)
            self._write_public(public)
            return {
                "candidate": deepcopy(candidate),
                "removed_link": deepcopy(active_link),
                "raw_audio_deleted": False,
            }

    def resolve_audio_speakers(
        self,
        speakers: list[dict[str, Any]],
        *,
        people: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Resolve current names at read time so corrections update history safely."""

        links = {
            str(item.get("candidate_id") or ""): str(item.get("person_id") or "")
            for item in self.public_snapshot()["identity_links"]
            if item.get("status") == "active"
        }
        output = []
        for source in speakers:
            item = deepcopy(source)
            candidate_id = str(item.get("candidate_id") or "")
            person_id = links.get(candidate_id)
            display_name = people.get(person_id or "")
            if person_id and display_name:
                item.update(
                    {
                        "confirmed_person_id": person_id,
                        "name": display_name,
                        "candidate_status": "confirmed",
                        "identity_resolution": "user_confirmed_voice_link",
                    }
                )
            else:
                item["confirmed_person_id"] = None
                item["identity_resolution"] = "anonymous_voice_candidate"
            output.append(item)
        return output

    def split_candidate(
        self,
        *,
        candidate_id: str,
        observation_ids: list[str],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        """Move selected observations into a new anonymous candidate."""

        candidate_id = _required_text(candidate_id, "candidate_id")
        actor = _required_text(actor, "actor")
        reason = _required_text(reason, "reason")
        selected = {str(item).strip() for item in observation_ids if str(item).strip()}
        if not selected:
            raise ValueError("split requires observation_ids")
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
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
            current = {str(item) for item in candidate.get("observation_ids") or []}
            if not selected.issubset(current):
                raise ValueError("split contains observations outside candidate")
            if selected == current:
                raise ValueError("split must leave at least one observation in source candidate")
            source_members = protected["candidate_members"].get(candidate_id) or {}
            if any(item not in source_members for item in selected):
                raise ValueError("split observation is missing protected embedding")
            now = self.now_ms()
            new_candidate_id = "voice-candidate:" + hashlib.sha256(
                f"split\n{candidate_id}\n{'|'.join(sorted(selected))}".encode("utf-8")
            ).hexdigest()[:20]
            existing_new = next(
                (
                    item
                    for item in public["candidates"]
                    if item.get("candidate_id") == new_candidate_id
                ),
                None,
            )
            if existing_new is not None:
                return {
                    "source_candidate_id": candidate_id,
                    "new_candidate_id": new_candidate_id,
                    "idempotent": True,
                }
            moved_assignments = [
                item
                for item in public["assignments"]
                if item.get("candidate_id") == candidate_id
                and item.get("observation_id") in selected
            ]
            if len(moved_assignments) != len(selected):
                raise ValueError("split assignment inventory is incomplete")
            anonymous_name = f"匿名说话人 {len(public['candidates']) + 1}"
            new_candidate = {
                "candidate_id": new_candidate_id,
                "display_name": anonymous_name,
                "anonymous_display_name": anonymous_name,
                "status": "active",
                "confirmed_person_id": None,
                "observation_ids": sorted(selected),
                "job_ids": list(
                    dict.fromkeys(str(item.get("job_id") or "") for item in moved_assignments)
                ),
                "window_ids": list(
                    dict.fromkeys(str(item.get("window_id") or "") for item in moved_assignments)
                ),
                "evidence_ids": list(
                    dict.fromkeys(
                        str(item.get("audio_evidence_id") or "")
                        for item in moved_assignments
                    )
                ),
                "model_revisions": list(candidate.get("model_revisions") or []),
                "config_versions": list(candidate.get("config_versions") or []),
                "first_heard_at_ms": min(
                    int(item.get("captured_at_ms") or 0) for item in moved_assignments
                ),
                "last_heard_at_ms": max(
                    int(item.get("captured_at_ms") or 0) for item in moved_assignments
                ),
                "representative_turns": [
                    deepcopy(turn)
                    for turn in candidate.get("representative_turns") or []
                    if any(
                        str(turn.get("turn_id") or "") in (item.get("turn_ids") or [])
                        for item in moved_assignments
                    )
                ][:5],
                "gallery_suggestion": None,
                "observation_count": len(selected),
                "embedding_ref": f"protected://voice-candidate/{new_candidate_id}",
                "created_at_ms": now,
                "updated_at_ms": now,
            }
            new_candidate["job_ids"] = [item for item in new_candidate["job_ids"] if item]
            new_candidate["window_ids"] = [item for item in new_candidate["window_ids"] if item]
            new_candidate["evidence_ids"] = [item for item in new_candidate["evidence_ids"] if item]
            moved_turn_ids = {
                str(turn_id)
                for item in moved_assignments
                for turn_id in item.get("turn_ids") or []
            }
            candidate["observation_ids"] = [
                item for item in candidate.get("observation_ids") or [] if item not in selected
            ]
            candidate["observation_count"] = len(candidate["observation_ids"])
            candidate["representative_turns"] = [
                item
                for item in candidate.get("representative_turns") or []
                if str(item.get("turn_id") or "") not in moved_turn_ids
            ]
            candidate["updated_at_ms"] = now
            for assignment in moved_assignments:
                assignment.update(
                    {
                        "candidate_id": new_candidate_id,
                        "display_name": anonymous_name,
                        "status": "anonymous_candidate",
                        "confirmed_person_id": None,
                    }
                )
            remaining_assignments = [
                item
                for item in public["assignments"]
                if item.get("candidate_id") == candidate_id
            ]
            candidate["job_ids"] = list(
                dict.fromkeys(
                    str(item.get("job_id") or "") for item in remaining_assignments
                )
            )
            candidate["window_ids"] = list(
                dict.fromkeys(
                    str(item.get("window_id") or "") for item in remaining_assignments
                )
            )
            candidate["evidence_ids"] = list(
                dict.fromkeys(
                    str(item.get("audio_evidence_id") or "")
                    for item in remaining_assignments
                )
            )
            candidate["job_ids"] = [item for item in candidate["job_ids"] if item]
            candidate["window_ids"] = [item for item in candidate["window_ids"] if item]
            candidate["evidence_ids"] = [item for item in candidate["evidence_ids"] if item]
            candidate["first_heard_at_ms"] = min(
                int(item.get("captured_at_ms") or 0) for item in remaining_assignments
            )
            candidate["last_heard_at_ms"] = max(
                int(item.get("captured_at_ms") or 0) for item in remaining_assignments
            )
            new_members = {
                observation_id: source_members.pop(observation_id)
                for observation_id in sorted(selected)
            }
            protected["candidate_members"][new_candidate_id] = new_members
            protected["candidate_centroids"][candidate_id] = _centroid(
                list(source_members.values())
            )
            protected["candidate_centroids"][new_candidate_id] = _centroid(
                list(new_members.values())
            )
            public["candidates"].append(new_candidate)
            public["link_audit"].append(
                {
                    "audit_id": "identity-audit:" + hashlib.sha256(
                        f"split\n{candidate_id}\n{new_candidate_id}\n{now}".encode("utf-8")
                    ).hexdigest(),
                    "action": "split",
                    "candidate_id": candidate_id,
                    "new_candidate_id": new_candidate_id,
                    "observation_ids": sorted(selected),
                    "actor": actor,
                    "reason": reason,
                    "created_at_ms": now,
                }
            )
            self._write_protected(protected)
            self._write_public(public)
            return {
                "source_candidate_id": candidate_id,
                "new_candidate_id": new_candidate_id,
                "moved_observation_ids": sorted(selected),
                "idempotent": False,
            }

    def delete_candidate(self, candidate_id: str, *, actor: str) -> dict[str, Any]:
        candidate_id = _required_text(candidate_id, "candidate_id")
        actor = _required_text(actor, "actor")
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
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
            if candidate.get("confirmed_person_id"):
                raise ValueError("unbind confirmed voice candidate before deletion")
            observation_ids = list(candidate.get("observation_ids") or [])
            removed_assignments = [
                item
                for item in public["assignments"]
                if item.get("candidate_id") == candidate_id
            ]
            turn_ids = list(
                dict.fromkeys(
                    str(turn_id)
                    for item in removed_assignments
                    for turn_id in item.get("turn_ids") or []
                    if turn_id
                )
            )
            gallery_entry_ids = [
                str(item.get("entry_id") or "")
                for item in public["gallery_entries"]
                if item.get("source_candidate_id") == candidate_id
            ]
            public["candidates"] = [
                item for item in public["candidates"] if item.get("candidate_id") != candidate_id
            ]
            public["assignments"] = [
                item for item in public["assignments"] if item.get("candidate_id") != candidate_id
            ]
            public["identity_links"] = [
                item for item in public["identity_links"] if item.get("candidate_id") != candidate_id
            ]
            public["gallery_entries"] = [
                item
                for item in public["gallery_entries"]
                if item.get("source_candidate_id") != candidate_id
            ]
            protected["candidate_members"].pop(candidate_id, None)
            protected["candidate_centroids"].pop(candidate_id, None)
            for entry_id in gallery_entry_ids:
                protected["gallery_embeddings"].pop(entry_id, None)
            now = self.now_ms()
            public["link_audit"].append(
                {
                    "audit_id": "identity-audit:" + hashlib.sha256(
                        f"delete-candidate\n{candidate_id}\n{now}".encode("utf-8")
                    ).hexdigest(),
                    "action": "delete_candidate",
                    "candidate_id": candidate_id,
                    "actor": actor,
                    "created_at_ms": now,
                }
            )
            self._write_protected(protected)
            self._write_public(public)
            return {
                "candidate_id": candidate_id,
                "deleted": True,
                "removed_observation_count": len(observation_ids),
                "removed_turn_ids": turn_ids,
                "raw_audio_deleted": False,
            }

    def delete_person(self, person_id: str, *, actor: str) -> dict[str, Any]:
        person_id = _required_text(person_id, "person_id")
        actor = _required_text(actor, "actor")
        with self._lock:
            public = self._read_public()
            candidate_ids = [
                str(item.get("candidate_id") or "")
                for item in public["candidates"]
                if item.get("confirmed_person_id") == person_id
            ]
            has_gallery = any(
                item.get("person_id") == person_id
                for item in public["gallery_entries"]
            )
            has_link = any(
                item.get("person_id") == person_id for item in public["identity_links"]
            )
            if not candidate_ids and not has_gallery and not has_link:
                return {
                    "person_id": person_id,
                    "deleted": True,
                    "removed_candidate_count": 0,
                    "removed_turn_ids": [],
                    "raw_audio_deleted": False,
                }
            protected = self._read_protected()
            removed_assignments = [
                item
                for item in public["assignments"]
                if item.get("candidate_id") in candidate_ids
            ]
            turn_ids = list(
                dict.fromkeys(
                    str(turn_id)
                    for item in removed_assignments
                    for turn_id in item.get("turn_ids") or []
                    if turn_id
                )
            )
            gallery_entry_ids = [
                str(item.get("entry_id") or "")
                for item in public["gallery_entries"]
                if item.get("person_id") == person_id
                or item.get("source_candidate_id") in candidate_ids
            ]
            public["candidates"] = [
                item
                for item in public["candidates"]
                if item.get("candidate_id") not in candidate_ids
            ]
            public["assignments"] = [
                item
                for item in public["assignments"]
                if item.get("candidate_id") not in candidate_ids
            ]
            public["gallery_entries"] = [
                item
                for item in public["gallery_entries"]
                if item.get("person_id") != person_id
                and item.get("source_candidate_id") not in candidate_ids
            ]
            public["identity_links"] = [
                item
                for item in public["identity_links"]
                if item.get("person_id") != person_id
                and item.get("candidate_id") not in candidate_ids
            ]
            for candidate_id in candidate_ids:
                protected["candidate_members"].pop(candidate_id, None)
                protected["candidate_centroids"].pop(candidate_id, None)
            for entry_id in gallery_entry_ids:
                protected["gallery_embeddings"].pop(entry_id, None)
            now = self.now_ms()
            public["link_audit"].append(
                {
                    "audit_id": "identity-audit:" + hashlib.sha256(
                        f"delete-person\n{person_id}\n{now}".encode("utf-8")
                    ).hexdigest(),
                    "action": "delete_person",
                    "person_id": person_id,
                    "candidate_ids": candidate_ids,
                    "actor": actor,
                    "created_at_ms": now,
                }
            )
            self._write_protected(protected)
            self._write_public(public)
            return {
                "person_id": person_id,
                "deleted": True,
                "removed_candidate_count": len(candidate_ids),
                "removed_turn_ids": turn_ids,
                "raw_audio_deleted": False,
            }

    def set_person_status(self, person_id: str, status: str) -> dict[str, Any]:
        """Pause or restore future voice matching without removing identity history."""

        person_id = _required_text(person_id, "person_id")
        if status not in {"active", "frozen"}:
            raise ValueError("invalid voice person status")
        with self._lock:
            public = self._read_public()
            candidates = [
                item
                for item in public["candidates"]
                if item.get("confirmed_person_id") == person_id
            ]
            gallery = [
                item
                for item in public["gallery_entries"]
                if item.get("person_id") == person_id
            ]
            if not candidates and not gallery:
                return {
                    "person_id": person_id,
                    "status": status,
                    "updated_candidate_count": 0,
                    "updated_gallery_entry_count": 0,
                }
            now = self.now_ms()
            for candidate in candidates:
                candidate["status"] = "confirmed" if status == "active" else "frozen_confirmed"
                candidate["updated_at_ms"] = now
            for entry in gallery:
                entry["status"] = status
            self._write_public(public)
            return {
                "person_id": person_id,
                "status": status,
                "updated_candidate_count": len(candidates),
                "updated_gallery_entry_count": len(gallery),
            }

    def summary(self) -> dict[str, Any]:
        public = self.public_snapshot()
        status_counts: dict[str, int] = {}
        for item in public["candidates"]:
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "candidate_count": len(public["candidates"]),
            "candidate_status_counts": status_counts,
            "assignment_count": len(public["assignments"]),
            "gallery_entry_count": len(public["gallery_entries"]),
            "gallery_enabled": self.gallery_threshold is not None,
            "config_version": self.config_version,
        }

    def set_candidate_status(self, candidate_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "frozen", "deleted"}:
            raise ValueError("invalid voice candidate status")
        with self._lock:
            public = self._read_public()
            protected = self._read_protected()
            candidate = next(
                (item for item in public["candidates"] if item.get("candidate_id") == candidate_id),
                None,
            )
            if candidate is None:
                raise KeyError(candidate_id)
            candidate["status"] = status
            candidate["updated_at_ms"] = self.now_ms()
            if status == "deleted":
                protected["candidate_members"].pop(candidate_id, None)
                protected["candidate_centroids"].pop(candidate_id, None)
                candidate["embedding_ref"] = None
                self._write_protected(protected)
            self._write_public(public)
            return deepcopy(candidate)

    def _gallery_suggestion(
        self,
        public: dict[str, Any],
        protected: dict[str, Any],
        vector: list[float],
        *,
        model_revision: str,
    ) -> dict[str, Any]:
        if self.gallery_threshold is None:
            return {
                "status": "disabled_by_locked_config",
                "suggested_person_id": None,
                "confidence": None,
                "margin": None,
            }
        scores: dict[str, float] = {}
        for entry in public["gallery_entries"]:
            if entry.get("status") != "active" or entry.get("model_revision") != model_revision:
                continue
            gallery = protected["gallery_embeddings"].get(entry.get("entry_id"))
            if gallery:
                person_id = str(entry.get("person_id") or "")
                scores[person_id] = max(scores.get(person_id, -1.0), _cosine(vector, gallery))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < self.gallery_threshold:
            return {"status": "no_match", "suggested_person_id": None, "confidence": None, "margin": None}
        margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else 2.0
        if self.gallery_margin is not None and margin < self.gallery_margin:
            return {"status": "ambiguous", "suggested_person_id": None, "confidence": round(ranked[0][1], 6), "margin": round(margin, 6)}
        return {"status": "suggested", "suggested_person_id": ranked[0][0], "confidence": round(ranked[0][1], 6), "margin": round(margin, 6)}

    def _read_public(self) -> dict[str, Any]:
        defaults = {
            "candidates": [],
            "assignments": [],
            "gallery_entries": [],
            "identity_links": [],
            "link_audit": [],
        }
        return _read_object(self.public_path, defaults)

    def _read_protected(self) -> dict[str, Any]:
        defaults = {
            "candidate_members": {},
            "candidate_centroids": {},
            "gallery_embeddings": {},
        }
        return _read_object(self.protected_path, defaults)

    def _write_public(self, data: dict[str, Any]) -> None:
        _write_json(self.public_path, data, protected=False)

    def _write_protected(self, data: dict[str, Any]) -> None:
        _write_json(self.protected_path, data, protected=True)


def _voice_observation_id(job_id: str, speaker_local_id: str) -> str:
    return "voice-observation:" + hashlib.sha256(
        f"{job_id}\n{speaker_local_id}".encode("utf-8")
    ).hexdigest()


def _required_text(value: str, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _representative_turn(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [
        item for item in turns if (item.get("quality") or {}).get("eligible_for_match")
    ]
    if not eligible:
        return None
    item = max(eligible, key=lambda value: int(value["end_ms"]) - int(value["start_ms"]))
    return {
        "turn_id": str(item["turn_id"]),
        "audio_evidence_id": str(item.get("audio_evidence_id") or ""),
        "start_ms": int(item["start_ms"]),
        "end_ms": int(item["end_ms"]),
        "duration_ms": int(item["end_ms"]) - int(item["start_ms"]),
    }


def _weighted_centroid(values: list[tuple[list[float], int]]) -> list[float]:
    if not values:
        return []
    dimension = len(values[0][0])
    if not dimension or any(len(vector) != dimension for vector, _ in values):
        raise ValueError("voice embeddings must have one stable dimension")
    summed = [0.0] * dimension
    for vector, duration_ms in values:
        weight = max(1, int(duration_ms))
        normalized = _normalize(vector)
        for index, item in enumerate(normalized):
            summed[index] += item * weight
    return _normalize(summed)


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    return _normalize([sum(values) for values in zip(*vectors)])


def _normalize(vector: list[float]) -> list[float]:
    values = [float(item) for item in vector]
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 0 or not all(math.isfinite(item) for item in values):
        raise ValueError("voice embedding must be finite with positive norm")
    return [item / norm for item in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    normalized_left, normalized_right = _normalize(left), _normalize(right)
    return sum(a * b for a, b in zip(normalized_left, normalized_right))


def _read_object(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return deepcopy(defaults)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(defaults)
    if not isinstance(value, dict):
        return deepcopy(defaults)
    return {key: value.get(key, deepcopy(default)) for key, default in defaults.items()}


def _write_json(path: Path, value: dict[str, Any], *, protected: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if protected:
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    if protected:
        os.chmod(path, 0o600)
