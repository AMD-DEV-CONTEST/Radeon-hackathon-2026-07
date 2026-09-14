from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from glass_gateway.services.object_memory import (
    ObjectAliasRegistry,
    build_detector_observation,
    build_last_seen_result,
    build_semantic_observation,
    projection_from_result,
)


class MemoryReviewStore:
    """Bridge-local business store for review state.

    This is not the memory system. EverOS remains the source for extracted
    memories; this store keeps Web review decisions that the bridge needs for
    correction, person confirmation, and noisy-candidate freezing.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.correction_path = self.path.with_name(
            f"{self.path.stem}-corrections.json"
        )
        self._data_lock = threading.RLock()
        self._correction_lock = threading.RLock()

    def snapshot(
        self,
        *,
        include_event_entries: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        data = self._read()
        data = self._apply_snapshot_corrections(data)
        data["corrections"] = self._read_correction_ledger()["corrections"]
        public = self._public_data(data)
        # Compatibility view only. The durable source is the single
        # object_observations ledger.
        public["object_candidate_observations"] = [
            item
            for item in public.get("object_observations", [])
            if item.get("state") == "detector_only"
        ]
        if not include_event_entries:
            public["event_queues"] = [
                self._event_queue_summary(item) for item in public.get("event_queues", [])
            ]
        return public

    def overview_snapshot(self) -> dict[str, Any]:
        """Return the small review projection needed by the overview page.

        The full snapshot applies corrections to every Capsule, object
        observation, report, and commitment.  The overview only needs review
        counters plus unresolved person candidates, so avoid constructing and
        serializing the complete ledger for each browser refresh.
        """

        data = self._read()
        corrections = self._read_correction_ledger()["corrections"]
        return {
            "corrections": [
                self._public_item(item) for item in corrections
            ],
            "person_drafts": [
                self._public_item(item) for item in data.get("person_drafts", [])
            ],
            "identity_candidates": [
                self._public_item(item)
                for item in data.get("identity_candidates", [])
            ],
            "counts": {
                "capsules": len(data.get("capsules", [])),
                "object_observations": len(data.get("object_observations", [])),
                "profiles": len(data.get("profiles", [])),
                "daily_reports": len(data.get("daily_reports", [])),
                "commitments": len(data.get("commitments", [])),
            },
        }

    def current_boot_session(
        self,
        *,
        user_id: str,
        captured_at_ms: int,
        timezone_name: str = "Asia/Shanghai",
        boot_key: str | None = None,
    ) -> dict[str, Any]:
        data = self._read()
        local_date = self._local_date(captured_at_ms, timezone_name)
        existing = [
            item
            for item in data["boot_sessions"]
            if item.get("user_id") == user_id
            and item.get("local_date") == local_date
            and item.get("status") == "active"
            and (boot_key is None or item.get("boot_key") == boot_key)
        ]
        if existing:
            existing.sort(key=lambda item: int(item.get("boot_index") or 0), reverse=True)
            return existing[0]

        boot_index = 1 + max(
            [
                int(item.get("boot_index") or 0)
                for item in data["boot_sessions"]
                if item.get("user_id") == user_id and item.get("local_date") == local_date
            ]
            or [0]
        )
        session = {
            "id": f"glasses-{user_id}-{local_date}-boot-{boot_index:03d}",
            "user_id": user_id,
            "local_date": local_date,
            "boot_index": boot_index,
            "status": "active",
            "boot_key": boot_key,
            "started_at_ms": captured_at_ms,
            "last_capsule_at_ms": captured_at_ms,
            "last_flush_at_ms": captured_at_ms,
            "created_at": self._now(),
        }
        data["boot_sessions"].insert(0, session)
        self._write(data)
        return session

    def active_boot_session(self, *, user_id: str) -> dict[str, Any] | None:
        sessions = [
            item
            for item in self._read()["boot_sessions"]
            if item.get("user_id") == user_id and item.get("status") == "active"
        ]
        sessions.sort(key=lambda item: int(item.get("last_capsule_at_ms") or 0), reverse=True)
        return sessions[0] if sessions else None

    def touch_boot_session(self, *, session_id: str, captured_at_ms: int) -> dict[str, Any] | None:
        data = self._read()
        touched = None
        for item in data["boot_sessions"]:
            if item.get("id") == session_id:
                item["last_capsule_at_ms"] = max(
                    int(item.get("last_capsule_at_ms") or 0),
                    captured_at_ms,
                )
                item["updated_at"] = self._now()
                touched = item
                break
        if touched:
            self._write(data)
        return touched

    def mark_boot_session_flushed(
        self,
        *,
        session_id: str,
        flushed_at_ms: int,
    ) -> dict[str, Any] | None:
        data = self._read()
        marked = None
        for item in data["boot_sessions"]:
            if item.get("id") == session_id:
                item["last_flush_at_ms"] = max(
                    int(item.get("last_flush_at_ms") or 0),
                    flushed_at_ms,
                )
                item["updated_at"] = self._now()
                marked = item
                break
        if marked:
            self._write(data)
        return marked

    def add_capsule(self, capsule: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        item = {
            "id": capsule.get("id") or f"cap-{uuid.uuid4().hex[:12]}",
            "boot_session_id": capsule["boot_session_id"],
            "window_id": capsule["window_id"],
            "captured_at_ms": capsule["captured_at_ms"],
            "duration_ms": capsule.get("duration_ms"),
            "scene": capsule.get("scene"),
            "activity": capsule.get("activity"),
            "scene_inference": capsule.get("scene_inference") or {},
            "activity_inference": capsule.get("activity_inference") or {},
            "observations": capsule.get("observations") or [],
            "uncertainties": capsule.get("uncertainties") or [],
            "input_usage": capsule.get("input_usage") or {},
            "interpretation": capsule.get("interpretation") or {},
            "window_interpretation": capsule.get("window_interpretation")
            or capsule.get("interpretation")
            or {},
            "stabilized_projection": capsule.get("stabilized_projection") or {},
            "stabilization_status": capsule.get("stabilization_status") or "not_requested",
            "event_queue_id": capsule.get("event_queue_id"),
            "event_type": capsule.get("event_type") or "daily",
            "meeting_likelihood": capsule.get("meeting_likelihood"),
            "text": capsule.get("text") or "",
            "visible_people": capsule.get("visible_people") or [],
            "audio_speakers": capsule.get("audio_speakers") or [],
            "voice_perception": capsule.get("voice_perception") or {},
            "objects": capsule.get("objects") or [],
            "commitments": capsule.get("commitments") or [],
            "evidence": capsule.get("evidence") or [],
            "manifest": capsule.get("manifest"),
            "dataset_source": capsule.get("dataset_source"),
            "evaluation_proxy": bool(capsule.get("evaluation_proxy", False)),
            "clock": capsule.get("clock") or {},
            "technical_window": capsule.get("technical_window") or {},
            "evidence_status": capsule.get("evidence_status") or {},
            "audio_presence": capsule.get("audio_presence") or {},
            "audio_presence_runs": capsule.get("audio_presence_runs") or [],
            "asr": capsule.get("asr") or {},
            "asr_runs": capsule.get("asr_runs") or [],
            "everos_writeback": capsule.get("everos_writeback") or {},
            "created_at": self._now(),
        }
        data["capsules"] = [
            existing for existing in data["capsules"] if existing.get("window_id") != item["window_id"]
        ]
        data["capsules"].insert(0, item)
        data["capsules"].sort(
            key=lambda value: int(value.get("captured_at_ms") or 0),
            reverse=True,
        )
        self._write(data)
        return item

    def add_object_candidate_observation(
        self,
        *,
        object_label: str,
        confidence: float,
        bbox_normalized: list[float] | None,
        job_id: str,
        evidence_id: str,
        window_id: str | None,
        captured_at_ms: int | None,
        vocabulary_hash: str | None,
        source: str,
        late: bool,
    ) -> dict[str, Any]:
        """Upsert a detector-only row into the unified Observation ledger."""
        data = self._read()
        registry = ObjectAliasRegistry.default()
        normalized, alias_source = registry.normalize(object_label)
        item = build_detector_observation(
            object_label_raw=object_label,
            normalized_label=normalized,
            confidence=confidence,
            captured_at_ms=int(captured_at_ms or 0),
            boot_session_id="detector-unassigned",
            window_id=str(window_id or evidence_id),
            evidence_ids=[evidence_id],
            evidence_uris=[],
            detector_job_ids=[job_id],
            bbox_evidence=[
                {"evidence_id": evidence_id, "bbox_normalized": bbox_normalized}
            ],
            source_model=source,
            vocabulary_hash=vocabulary_hash,
            late=late,
        )
        item["alias_source"] = alias_source
        item_id = item["observation_id"]
        existing = next(
            (
                value
                for value in data["object_observations"]
                if (value.get("observation_id") or value.get("id")) == item_id
            ),
            None,
        )
        if existing is not None:
            return existing
        data["object_observations"].append(item)
        data["object_observations"].sort(
            key=lambda value: int(value.get("captured_at_ms") or 0), reverse=True
        )
        self._write(data)
        return item

    def upsert_detector_object_observation(
        self,
        *,
        object_label_raw: str,
        confidence: float,
        captured_at_ms: int,
        boot_session_id: str,
        window_id: str,
        evidence_ids: list[str],
        evidence_uris: list[str],
        detector_job_ids: list[str],
        bbox_evidence: list[dict[str, Any]],
        source_model: str,
        vocabulary_hash: str | None,
        late: bool = False,
    ) -> dict[str, Any]:
        data = self._read()
        registry = ObjectAliasRegistry.default()
        normalized, alias_source = registry.normalize(
            object_label_raw, user_objects=data.get("confirmed_objects", [])
        )
        item = build_detector_observation(
            object_label_raw=object_label_raw,
            normalized_label=normalized,
            confidence=confidence,
            captured_at_ms=captured_at_ms,
            boot_session_id=boot_session_id,
            window_id=window_id,
            evidence_ids=evidence_ids,
            evidence_uris=evidence_uris,
            detector_job_ids=detector_job_ids,
            bbox_evidence=bbox_evidence,
            source_model=source_model,
            vocabulary_hash=vocabulary_hash,
            late=late,
        )
        item["alias_source"] = alias_source
        existing = next(
            (
                value
                for value in data["object_observations"]
                if (value.get("observation_id") or value.get("id"))
                == item["observation_id"]
            ),
            None,
        )
        if existing is not None:
            return existing
        data["object_observations"].append(item)
        data["object_observations"].sort(
            key=lambda value: int(value.get("captured_at_ms") or 0), reverse=True
        )
        self._write(data)
        return item

    def promote_object_observation(
        self,
        *,
        observation_id: str,
        card: dict[str, Any],
        source_capsule_id: str,
        source_model: str,
        source_prompt_version: str,
        object_identity_id: str | None = None,
    ) -> dict[str, Any] | None:
        data = self._read()
        item = next(
            (
                value
                for value in data["object_observations"]
                if (value.get("observation_id") or value.get("id")) == observation_id
            ),
            None,
        )
        if item is None or item.get("state") != "detector_only":
            return None
        previous = {
            key: item.get(key)
            for key in (
                "state",
                "canonical_name",
                "visible_description",
                "location_hint",
                "relation",
                "memory_value",
                "semantic_confidence",
                "updated_at_ms",
            )
        }
        item.update(
            {
                "state": "fused",
                "observation_kind": "semantic_confirmed",
                "canonical_name": str(card.get("canonical_name") or item.get("canonical_name")),
                "object_label_raw": str(card.get("canonical_name") or item.get("object_label_raw")),
                "object_label": str(card.get("canonical_name") or item.get("object_label")),
                "visible_description": card.get("visible_description"),
                "location_hint": card.get("location_hint"),
                "relation": card.get("relation_to_wearer"),
                "memory_value": card.get("memory_value") or "context_only",
                "semantic_confidence": float(card.get("semantic_confidence") or item.get("confidence") or 0),
                "confidence": float(card.get("semantic_confidence") or item.get("confidence") or 0),
                "instance_ambiguity": card.get("merge_decision") == "uncertain",
                "uncertainty": card.get("uncertainty"),
                "source_capsule_id": source_capsule_id,
                "capsule_ids": list(dict.fromkeys([*item.get("capsule_ids", []), source_capsule_id])),
                "source_model": source_model,
                "source_prompt_version": source_prompt_version,
                "object_identity_id": object_identity_id or item.get("object_identity_id"),
                "merge_decision": card.get("merge_decision"),
                "merge_target_observation_id": card.get("merge_target_observation_id"),
                "audit_status": "ready" if item.get("evidence_available") else "evidence_missing",
                "updated_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
        )
        item.setdefault("version_history", []).append(previous)
        self._write(data)
        return item

    def reject_object_observation(self, observation_id: str, *, reason: str) -> None:
        data = self._read()
        for item in data["object_observations"]:
            if (item.get("observation_id") or item.get("id")) != observation_id:
                continue
            item["memory_value"] = "ignore"
            item["audit_status"] = "semantic_rejected"
            item["uncertainty"] = reason
            item["updated_at_ms"] = int(datetime.now(timezone.utc).timestamp() * 1000)
            self._write(data)
            return

    def upsert_confirmed_object(
        self,
        *,
        label: str,
        prompt: str,
        aliases: list[str] | None = None,
        personal_object_id: str | None = None,
        visible_description: str | None = None,
    ) -> dict[str, Any]:
        normalized_label = label.strip()
        normalized_prompt = prompt.strip()
        if not normalized_label or not normalized_prompt:
            raise ValueError("confirmed object label and prompt are required")
        data = self._read()
        item_id = f"confirmed-object-{self._slug(normalized_label)}"
        item = {
            "id": item_id,
            "label": normalized_label,
            "prompt": normalized_prompt,
            "aliases": [str(value).strip() for value in aliases or [] if str(value).strip()],
            "personal_object_id": personal_object_id.strip()
            if isinstance(personal_object_id, str) and personal_object_id.strip()
            else None,
            "visible_description": visible_description.strip()
            if isinstance(visible_description, str) and visible_description.strip()
            else None,
            "status": "confirmed",
            "updated_at": self._now(),
        }
        data["confirmed_objects"] = [
            existing
            for existing in data["confirmed_objects"]
            if existing.get("id") != item_id
        ]
        data["confirmed_objects"].insert(0, item)
        self._write(data)
        return item

    def confirmed_object_prompts(self) -> list[dict[str, Any]]:
        return [
            self._public_item(item)
            for item in self._read()["confirmed_objects"]
            if item.get("status") == "confirmed" and item.get("prompt")
        ]

    def recent_stable_object_labels(self, *, limit: int = 80) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for item in self._read()["object_observations"]:
            if item.get("state") not in {"semantic_only", "fused"}:
                continue
            if item.get("memory_value") == "ignore":
                continue
            label = str(
                item.get("canonical_name")
                or item.get("object_label_raw")
                or item.get("object_label")
                or ""
            ).strip()
            key = label.casefold()
            if not label or key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) >= max(0, limit):
                return labels
        return labels

    def capsule_for_window(self, window_id: str) -> dict[str, Any] | None:
        for item in self._read()["capsules"]:
            if item.get("window_id") == window_id:
                return self._public_item(item)
        return None

    def update_capsule_everos_writeback(
        self,
        *,
        window_id: str,
        writeback: dict[str, Any],
    ) -> dict[str, Any] | None:
        data = self._read()
        updated = None
        for item in data["capsules"]:
            if item.get("window_id") != window_id:
                continue
            item["everos_writeback"] = writeback
            item["updated_at"] = self._now()
            updated = item
            break
        if updated is not None:
            self._write(data)
            return self._public_item(updated)
        return None

    def update_capsule_voice_projection(
        self,
        *,
        window_id: str,
        audio_speakers: list[dict[str, Any]],
        voice_perception: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Attach a late voice result without rewriting historical MiMo input."""

        data = self._read()
        updated = None
        for item in data["capsules"]:
            if item.get("window_id") != window_id:
                continue
            item["audio_speakers"] = [
                self._public_item(value)
                for value in audio_speakers
                if isinstance(value, dict)
            ]
            item["voice_perception"] = self._public_item(voice_perception)
            item["voice_projection_late"] = True
            item["updated_at"] = self._now()
            updated = item
            break
        if updated is not None:
            self._write(data)
            return self._public_item(updated)
        return None

    def update_capsule_context_projection(
        self,
        *,
        window_id: str,
        projection: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Write a repaired boundary result back to its durable Capsule."""

        data = self._read()
        updated = None
        event_queue_id = str(projection.get("event_queue_id") or "")
        for item in data["capsules"]:
            if item.get("window_id") != window_id:
                continue
            item["stabilized_projection"] = self._public_item(projection)
            item["stabilization_status"] = str(
                projection.get("status") or "failed"
            )
            item["event_queue_id"] = event_queue_id or None
            if projection.get("status") == "completed" and event_queue_id:
                item["everos_writeback"] = {
                    "status": "waiting_event_boundary",
                    "stage": "event_queue",
                    "session_id": str(item.get("boot_session_id") or ""),
                    "event_queue_id": event_queue_id,
                    "attempt_count": 0,
                }
            item["updated_at"] = self._now()
            updated = item
            break
        if updated is None:
            return None
        self._write(data)
        return self._public_item(updated)

    def active_event_queue(self, *, boot_session_id: str) -> dict[str, Any] | None:
        queues = [
            item
            for item in self._read()["event_queues"]
            if item.get("boot_session_id") == boot_session_id
            and item.get("status") == "active"
        ]
        queues.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return queues[0] if queues else None

    def event_queue_for_window(
        self,
        *,
        boot_session_id: str,
        window_id: str,
    ) -> dict[str, Any] | None:
        for queue in self._read()["event_queues"]:
            if queue.get("boot_session_id") != boot_session_id:
                continue
            if window_id in queue.get("window_ids", []):
                return queue
        return None

    def context_pending_entries(
        self,
        *,
        boot_session_id: str,
    ) -> list[dict[str, Any]]:
        active = self.active_event_queue(boot_session_id=boot_session_id)
        if active is None:
            return []
        return [
            dict(item)
            for item in active.get("context_pending_entries", [])
            if isinstance(item, dict)
        ]

    def record_context_pending(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        window_interpretation: dict[str, Any],
        projection: dict[str, Any],
    ) -> None:
        """Keep a failed decision outside committed semantic-session members."""

        data = self._read()
        active = next(
            (
                item
                for item in data["event_queues"]
                if item.get("boot_session_id") == boot_session_id
                and item.get("status") == "active"
            ),
            None,
        )
        if active is None:
            return
        pending = active.setdefault("context_pending_entries", [])
        replacement = {
            "window_id": window_id,
            "captured_at_ms": captured_at_ms,
            "window_interpretation": window_interpretation,
            "stabilized_projection": projection,
            "updated_at": self._now(),
        }
        for index, item in enumerate(pending):
            if item.get("window_id") == window_id:
                pending[index] = replacement
                break
        else:
            pending.append(replacement)
            pending.sort(key=lambda item: int(item.get("captured_at_ms") or 0))
        active["updated_at"] = self._now()
        self._write(data)

    def sealed_event_queues_pending(
        self,
        *,
        boot_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        queues = []
        for queue in self._read()["event_queues"]:
            if queue.get("status") != "sealed":
                continue
            if boot_session_id and queue.get("boot_session_id") != boot_session_id:
                continue
            writeback = (
                queue.get("everos_writeback")
                if isinstance(queue.get("everos_writeback"), dict)
                else {}
            )
            if writeback.get("status") not in {
                "pending",
                "pending_retry",
                "added",
            }:
                continue
            queues.append(queue)
        queues.sort(key=lambda item: int(item.get("started_at_ms") or 0))
        return queues

    def seal_active_event_queue(
        self,
        *,
        boot_session_id: str,
        sealed_at_ms: int,
        reason: str,
    ) -> dict[str, Any] | None:
        data = self._read()
        active = next(
            (
                item
                for item in data["event_queues"]
                if item.get("boot_session_id") == boot_session_id
                and item.get("status") == "active"
            ),
            None,
        )
        if active is None:
            return None
        active["status"] = "sealed"
        active["sealed_at_ms"] = sealed_at_ms
        active["ended_at_ms"] = int(active.get("updated_at_ms") or sealed_at_ms)
        active["boundary_after_window_id"] = (
            active.get("window_ids", [])[-1] if active.get("window_ids") else None
        )
        active["boundary_reason"] = reason
        active["everos_writeback"] = {
            "status": "pending",
            "stage": "event_boundary",
            "attempt_count": 0,
        }
        active["updated_at"] = self._now()
        self._write(data)
        return self._public_item(active)

    def update_active_event_summary(
        self,
        *,
        boot_session_id: str,
        summary: str,
    ) -> dict[str, Any] | None:
        """Persist the one-time seal summary without changing event members."""

        normalized = summary.strip()
        if not normalized:
            raise ValueError("event summary is required")
        data = self._read()
        active = next(
            (
                item
                for item in data["event_queues"]
                if item.get("boot_session_id") == boot_session_id
                and item.get("status") == "active"
            ),
            None,
        )
        if active is None:
            return None
        active["rolling_summary"] = normalized
        active["cumulative_state"] = {"summary": normalized}
        active["updated_at"] = self._now()
        self._write(data)
        return self._public_item(active)

    def update_event_queue_everos_writeback(
        self,
        *,
        event_queue_id: str,
        writeback: dict[str, Any],
    ) -> dict[str, Any] | None:
        data = self._read()
        updated = None
        source_window_ids: set[str] = set()
        for queue in data["event_queues"]:
            if queue.get("id") != event_queue_id:
                continue
            queue["everos_writeback"] = writeback
            queue["updated_at"] = self._now()
            source_window_ids = {
                str(value) for value in queue.get("window_ids", []) if value
            }
            updated = queue
            break
        if updated is None:
            return None
        for capsule in data["capsules"]:
            if str(capsule.get("window_id") or "") not in source_window_ids:
                continue
            capsule["everos_writeback"] = writeback
            capsule["updated_at"] = self._now()
        self._write(data)
        return self._public_item(updated)

    def apply_event_projection(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        window_interpretation: dict[str, Any],
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically append a window to the open working-event queue.

        Semantic boundary decisions belong to the stabilizer model. This method
        only performs idempotent queue bookkeeping and never invents a boundary.
        """

        data = self._read()
        for queue in data["event_queues"]:
            if queue.get("boot_session_id") != boot_session_id:
                continue
            if window_id not in queue.get("window_ids", []):
                continue
            entry = next(
                (
                    item
                    for item in queue.get("entries", [])
                    if item.get("window_id") == window_id
                ),
                {},
            )
            return {
                "queue": queue,
                "projection": entry.get("stabilized_projection") or projection,
                "idempotent_replay": True,
            }

        active = next(
            (
                item
                for item in data["event_queues"]
                if item.get("boot_session_id") == boot_session_id
                and item.get("status") == "active"
            ),
            None,
        )
        action = str(projection.get("queue_action") or "pending_repair")
        sealed_queue = None
        carried_pending_entries: list[dict[str, Any]] = []
        if action == "boundary_before_current" and active is not None:
            # The boundary classifier summarizes the event being closed. The
            # current window belongs to the next semantic session and must
            # never leak into this sealed summary.
            sealed_summary = str(
                projection.get("sealed_event_summary") or ""
            ).strip()
            if sealed_summary:
                active["rolling_summary"] = sealed_summary
                active["cumulative_state"] = {"summary": sealed_summary}
            carried_pending_entries = [
                item
                for item in active.get("context_pending_entries", [])
                if item.get("window_id") != window_id
            ]
            active["context_pending_entries"] = []
            if projection.get("status") == "completed":
                active["provisional_window_ids"] = []
                for prior_entry in active.get("entries", []):
                    prior_entry["provisional"] = False
            active["status"] = "sealed"
            active["sealed_at_ms"] = captured_at_ms
            active["ended_at_ms"] = int(active.get("updated_at_ms") or captured_at_ms)
            active["boundary_after_window_id"] = (
                active.get("window_ids", [])[-1] if active.get("window_ids") else None
            )
            active["boundary_reason"] = projection.get("boundary_reason") or projection.get(
                "context_change"
            )
            active["everos_writeback"] = {
                "status": "pending",
                "stage": "event_boundary",
                "attempt_count": 0,
            }
            active["updated_at"] = self._now()
            sealed_queue = active
            active = None

        created_new_queue = active is None
        if active is None:
            queue_id = f"event-queue-{uuid.uuid4().hex[:12]}"
            active = {
                "id": queue_id,
                "context_thread_id": queue_id,
                "boot_session_id": boot_session_id,
                "status": "active",
                "started_at_ms": captured_at_ms,
                "updated_at_ms": captured_at_ms,
                "window_ids": [],
                "provisional_window_ids": [],
                "entries": [],
                "rolling_summary": "",
                "cumulative_state": {},
                "context_pending_entries": carried_pending_entries,
                "created_at": self._now(),
            }
            data["event_queues"].insert(0, active)

        projection = dict(projection)
        projection["event_queue_id"] = active["id"]
        projection["context_thread_id"] = active["context_thread_id"]
        if sealed_queue is not None:
            projection["sealed_event_queue_id"] = sealed_queue["id"]
        source_ids = [
            str(item)
            for item in projection.get("source_window_ids", [])
            if str(item).strip()
        ]
        if window_id not in source_ids:
            source_ids.append(window_id)
        projection["source_window_ids"] = list(dict.fromkeys(source_ids))
        active["context_pending_entries"] = [
            item
            for item in active.get("context_pending_entries", [])
            if item.get("window_id") != window_id
        ]
        entry = {
            "window_id": window_id,
            "captured_at_ms": captured_at_ms,
            "window_interpretation": window_interpretation,
            "stabilized_projection": projection,
            "provisional": action == "uncertain" or projection.get("status") != "completed",
            "created_at": self._now(),
        }
        active["entries"].append(entry)
        active["window_ids"].append(window_id)
        if entry["provisional"]:
            active["provisional_window_ids"].append(window_id)
        elif action == "continue" and projection.get("status") == "completed":
            # The model saw the provisional tail in its input and has now
            # explicitly kept it in the current event.
            active["provisional_window_ids"] = []
            for prior_entry in active.get("entries", []):
                prior_entry["provisional"] = False
        active["updated_at_ms"] = max(int(active.get("updated_at_ms") or 0), captured_at_ms)
        # Semantic sessions are append-only. They do not ask the boundary
        # model to rewrite a rolling summary on every window. A new session is
        # initialized from its first immutable Scene caption; the complete
        # summary is generated exactly once when the session is sealed.
        if created_new_queue:
            first_caption = str(
                projection.get("corrected_caption")
                or window_interpretation.get("first_person_caption")
                or ""
            ).strip()
            if first_caption:
                active["rolling_summary"] = first_caption
        # Read-only compatibility for old queue consumers. New writes carry no
        # scene, activity, people, object or commitment ledgers.
        active["cumulative_state"] = {"summary": active.get("rolling_summary") or ""}
        active["updated_at"] = self._now()
        self._write(data)
        return {
            "queue": active,
            "sealed_queue": sealed_queue,
            "projection": projection,
            "idempotent_replay": False,
        }

    def add_identity_observation(
        self,
        *,
        name: str,
        channel: str,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        confidence: float | None,
        source: str | None,
        evidence_id: str | None,
    ) -> dict[str, Any]:
        data = self._read()
        item = {
            "id": f"identity-{channel}-{self._slug(name)}-{uuid.uuid4().hex[:8]}",
            "name": name,
            "channel": channel,
            "boot_session_id": boot_session_id,
            "window_id": window_id,
            "captured_at_ms": captured_at_ms,
            "confidence": confidence,
            "source": source,
            "evidence_id": evidence_id,
            "created_at": self._now(),
        }
        data["identity_observations"].insert(0, item)
        self._write(data)
        return item

    def upsert_identity_candidate(
        self,
        *,
        modality: str,
        observation: dict[str, Any],
        match_threshold: float,
    ) -> dict[str, Any]:
        data = self._read()
        embedding = self._embedding(observation.get("embedding"))
        label = str(observation.get("name") or observation.get("label") or "").strip()
        candidate = self._match_identity_candidate(
            data["identity_candidates"],
            modality=modality,
            label=label,
            embedding=embedding,
            match_threshold=match_threshold,
        )
        now = self._now()
        if candidate is None:
            candidate = {
                "id": f"cand_{modality}_{uuid.uuid4().hex[:10]}",
                "modality": modality,
                "display_name": label or f"{'人脸' if modality == 'face' else '声纹'}候选",
                "aliases": [] if not label else [label],
                "status": "candidate",
                "observation_count": 0,
                "first_seen_at_ms": observation["captured_at_ms"],
                "last_seen_at_ms": observation["captured_at_ms"],
                "last_confidence": None,
                "embedding": embedding,
                "evidence_ids": [],
                "window_ids": [],
                "created_at": now,
                "updated_at": now,
            }
            data["identity_candidates"].insert(0, candidate)
        else:
            if label and label not in candidate.get("aliases", []):
                candidate.setdefault("aliases", []).append(label)
            if label and str(candidate.get("display_name", "")).endswith("候选"):
                candidate["display_name"] = label
            if embedding:
                candidate["embedding"] = self._centroid(
                    candidate.get("embedding"),
                    embedding,
                    int(candidate.get("observation_count") or 0),
                )

        candidate["observation_count"] = int(candidate.get("observation_count") or 0) + 1
        candidate["last_seen_at_ms"] = max(
            int(candidate.get("last_seen_at_ms") or 0),
            int(observation["captured_at_ms"]),
        )
        candidate["last_confidence"] = observation.get("confidence")
        candidate["updated_at"] = now
        evidence_id = observation.get("evidence_id")
        if evidence_id and evidence_id not in candidate.get("evidence_ids", []):
            candidate.setdefault("evidence_ids", []).append(evidence_id)
        window_id = observation.get("window_id")
        if window_id and window_id not in candidate.get("window_ids", []):
            candidate.setdefault("window_ids", []).append(window_id)
        self._write(data)
        return candidate

    def upsert_person_draft(
        self,
        *,
        display_name: str,
        face_candidate_ids: list[str],
        voice_candidate_ids: list[str],
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
    ) -> dict[str, Any] | None:
        display_name = display_name.strip()
        if not display_name:
            return None
        data = self._read()
        draft = next(
            (
                item
                for item in data["person_drafts"]
                if display_name.lower() in [str(item.get("display_name", "")).lower(), *[str(alias).lower() for alias in item.get("aliases", [])]]
            ),
            None,
        )
        now = self._now()
        if draft is None:
            draft = {
                "id": f"person_draft_{self._slug(display_name)}_{uuid.uuid4().hex[:8]}",
                "display_name": display_name,
                "aliases": [display_name],
                "status": "candidate",
                "face_candidate_ids": [],
                "voice_candidate_ids": [],
                "boot_session_ids": [],
                "window_ids": [],
                "first_seen_at_ms": captured_at_ms,
                "last_seen_at_ms": captured_at_ms,
                "created_at": now,
                "updated_at": now,
            }
            data["person_drafts"].insert(0, draft)
        for candidate_id in face_candidate_ids:
            if candidate_id and candidate_id not in draft["face_candidate_ids"]:
                draft["face_candidate_ids"].append(candidate_id)
        for candidate_id in voice_candidate_ids:
            if candidate_id and candidate_id not in draft["voice_candidate_ids"]:
                draft["voice_candidate_ids"].append(candidate_id)
        if boot_session_id not in draft["boot_session_ids"]:
            draft["boot_session_ids"].append(boot_session_id)
        if window_id not in draft["window_ids"]:
            draft["window_ids"].append(window_id)
        draft["last_seen_at_ms"] = max(int(draft.get("last_seen_at_ms") or 0), captured_at_ms)
        draft["updated_at"] = now
        self._write(data)
        return draft

    def add_meeting_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        meeting = {
            "id": item.get("id") or f"meeting-evidence-{uuid.uuid4().hex[:12]}",
            **item,
            "created_at": self._now(),
        }
        data["meeting_evidence"] = [
            existing
            for existing in data["meeting_evidence"]
            if existing.get("window_id") != meeting.get("window_id")
        ]
        data["meeting_evidence"].insert(0, meeting)
        self._write(data)
        return meeting

    def add_correction(
        self,
        *,
        source_id: str,
        session_id: str | None,
        original_content: str,
        corrected_content: str,
        status: str,
        note: str | None,
        everos_session_id: str,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "source_id": source_id,
                "session_id": session_id,
                "corrected_content": corrected_content,
                "status": status,
                "note": note,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return self.upsert_correction(
            idempotency_key="legacy:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            target_type="episode",
            target_id=source_id,
            field_path="content" if status != "rejected" else "$",
            old_value=original_content,
            new_value=corrected_content if status != "rejected" else None,
            decision_status=status,
            evidence_refs=[
                f"everos://episode/{source_id}",
                *([f"capsule://{session_id}"] if session_id else []),
            ],
            note=note,
            session_id=session_id,
            everos_session_id=everos_session_id,
        )

    def upsert_correction(
        self,
        *,
        idempotency_key: str,
        target_type: str,
        target_id: str,
        field_path: str,
        old_value: Any,
        new_value: Any,
        decision_status: str,
        evidence_refs: list[str],
        note: str | None,
        session_id: str | None = None,
        everos_session_id: str | None = None,
        action: str = "set",
        reverts_id: str | None = None,
    ) -> dict[str, Any]:
        """Create one durable, versioned correction or return its idempotent twin."""

        key = str(idempotency_key or "").strip()
        target_type = str(target_type or "").strip()
        target_id = str(target_id or "").strip()
        field_path = str(field_path or "").strip()
        if not key or not target_id:
            raise ValueError("idempotency_key and target_id are required")
        if decision_status not in {"confirmed", "rejected"}:
            raise ValueError("decision_status must be confirmed or rejected")
        if action not in {"set", "revert"}:
            raise ValueError("correction action must be set or revert")
        self._validate_correction_field(target_type, field_path, decision_status)
        refs = list(dict.fromkeys(str(item).strip() for item in evidence_refs if str(item).strip()))
        if not refs:
            raise ValueError("evidence_refs must contain at least one source")
        if self._contains_private_vector(old_value) or self._contains_private_vector(new_value):
            raise ValueError("correction values cannot contain embedding or vector data")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "field_path": field_path,
                    "old_value": old_value,
                    "new_value": new_value,
                    "decision_status": decision_status,
                    "evidence_refs": refs,
                    "note": note,
                    "action": action,
                    "reverts_id": reverts_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        with self._correction_lock:
            ledger = self._read_correction_ledger()
            existing = next(
                (
                    item
                    for item in ledger["corrections"]
                    if item.get("idempotency_key") == key
                ),
                None,
            )
            if existing is not None:
                if existing.get("request_fingerprint") != fingerprint:
                    raise ValueError("idempotency_key conflicts with another correction payload")
                return {**deepcopy(existing), "idempotent": True}
            same_field = [
                item
                for item in ledger["corrections"]
                if item.get("target_type") == target_type
                and item.get("target_id") == target_id
                and item.get("field_path") == field_path
            ]
            same_field.sort(key=lambda item: int(item.get("version") or 0))
            correction_id = "corr-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            version = 1 + max([int(item.get("version") or 0) for item in same_field] or [0])
            now = self._now()
            item = {
                "id": correction_id,
                "correction_id": correction_id,
                "idempotency_key": key,
                "request_fingerprint": fingerprint,
                "target_type": target_type,
                "target_id": target_id,
                "source_id": target_id,
                "session_id": session_id,
                "field_path": field_path,
                "old_value": deepcopy(old_value),
                "new_value": deepcopy(new_value),
                "original_content": old_value if isinstance(old_value, str) else "",
                "corrected_content": new_value if isinstance(new_value, str) else "",
                "decision_status": decision_status,
                "status": decision_status,
                "action": action,
                "reverts_id": reverts_id,
                "version": version,
                "supersedes_id": same_field[-1]["id"] if same_field else None,
                "evidence_refs": refs,
                "note": note,
                "writeback_status": "pending_writeback",
                "writeback_stage": "pending_add",
                "attempt_count": 0,
                "next_retry_at_ms": 0,
                "last_error": None,
                "everos_session_id": everos_session_id or f"correction-{correction_id}",
                "created_at": now,
                "updated_at": now,
                "applied_at": None,
            }
            ledger["corrections"].insert(0, item)
            self._write_correction_ledger(ledger)
            return {**deepcopy(item), "idempotent": False}

    def correction_by_id(self, correction_id: str) -> dict[str, Any] | None:
        with self._correction_lock:
            item = next(
                (
                    value
                    for value in self._read_correction_ledger()["corrections"]
                    if value.get("id") == correction_id
                ),
                None,
            )
            return deepcopy(item) if item is not None else None

    def pending_corrections(
        self,
        *,
        now_ms: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._correction_lock:
            values = [
                deepcopy(item)
                for item in self._read_correction_ledger()["corrections"]
                if item.get("writeback_status") in {"pending_writeback", "failed_retryable"}
                and int(item.get("next_retry_at_ms") or 0) <= int(now_ms)
            ]
            values.sort(key=lambda item: (int(item.get("next_retry_at_ms") or 0), str(item.get("created_at") or "")))
            return values[: max(0, int(limit))]

    def mark_correction_writeback(
        self,
        correction_id: str,
        *,
        writeback_status: str,
        writeback_stage: str,
        error: str | None = None,
        next_retry_at_ms: int = 0,
        increment_attempt: bool = False,
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if writeback_status not in {"pending_writeback", "failed_retryable", "applied"}:
            raise ValueError("invalid correction writeback status")
        if writeback_stage not in {"pending_add", "pending_flush", "applied"}:
            raise ValueError("invalid correction writeback stage")
        with self._correction_lock:
            ledger = self._read_correction_ledger()
            item = next(
                (value for value in ledger["corrections"] if value.get("id") == correction_id),
                None,
            )
            if item is None:
                raise KeyError(correction_id)
            item["writeback_status"] = writeback_status
            item["writeback_stage"] = writeback_stage
            item["last_error"] = str(error)[:1000] if error else None
            item["next_retry_at_ms"] = int(next_retry_at_ms)
            if increment_attempt:
                item["attempt_count"] = int(item.get("attempt_count") or 0) + 1
            if response is not None:
                item["last_writeback_response"] = self._public_item(response)
            item["updated_at"] = self._now()
            if writeback_status == "applied":
                item["applied_at"] = item["updated_at"]
            self._write_correction_ledger(ledger)
            return deepcopy(item)

    def revert_correction(
        self,
        correction_id: str,
        *,
        idempotency_key: str,
        note: str | None,
    ) -> dict[str, Any]:
        target = self.correction_by_id(correction_id)
        if target is None:
            raise KeyError(correction_id)
        if target.get("action") == "revert":
            raise ValueError("cannot revert a revert action")
        return self.upsert_correction(
            idempotency_key=idempotency_key,
            target_type=str(target["target_type"]),
            target_id=str(target["target_id"]),
            field_path=str(target["field_path"]),
            old_value=target.get("new_value"),
            new_value=None,
            decision_status="confirmed",
            evidence_refs=list(target.get("evidence_refs") or []),
            note=note,
            session_id=target.get("session_id"),
            action="revert",
            reverts_id=correction_id,
        )

    def apply_corrections(
        self,
        *,
        target_type: str,
        target_id: str,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._apply_corrections_from_ledger(
            target_type=target_type,
            target_id=target_id,
            source=source,
            corrections=self._read_correction_ledger()["corrections"],
        )

    def _apply_corrections_from_ledger(
        self,
        *,
        target_type: str,
        target_id: str,
        source: dict[str, Any],
        corrections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        values = [
            item
            for item in corrections
            if item.get("target_type") == target_type
            and item.get("target_id") == target_id
        ]
        values.sort(key=lambda item: int(item.get("version") or 0))
        reverted = {
            str(item.get("reverts_id") or "")
            for item in values
            if item.get("action") == "revert"
        }
        active = [
            item
            for item in values
            if item.get("action") == "set" and item.get("id") not in reverted
        ]
        whole = [item for item in active if item.get("field_path") == "$"]
        if whole and whole[-1].get("decision_status") == "rejected":
            return None
        latest_by_field: dict[str, dict[str, Any]] = {}
        for item in active:
            field = str(item.get("field_path") or "")
            if field != "$" and item.get("decision_status") == "confirmed":
                latest_by_field[field] = item
        result = deepcopy(source)
        for field, item in latest_by_field.items():
            self._set_projection_field(result, field, deepcopy(item.get("new_value")))
        result["correction_projection"] = {
            "status": "corrected" if latest_by_field else "original",
            "corrected_fields": sorted(latest_by_field),
            "correction_ids": [
                latest_by_field[field]["id"] for field in sorted(latest_by_field)
            ],
        }
        return result

    def _apply_snapshot_corrections(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Build the read model without mutating the bridge source document."""

        result = deepcopy(data)
        corrections = self._read_correction_ledger()["corrections"]
        collections = (
            ("capsules", "capsule", ("id", "window_id")),
            ("profiles", "person", ("person_id", "id")),
            (
                "object_observations",
                "object",
                ("observation_id", "id", "object_identity_id"),
            ),
            ("daily_reports", "daily_report", ("id",)),
            ("commitments", "commitment", ("commitment_id", "id")),
        )
        for collection, target_type, id_fields in collections:
            projected: list[dict[str, Any]] = []
            for source in result.get(collection, []):
                target_id = next(
                    (
                        str(source.get(field))
                        for field in id_fields
                        if source.get(field)
                    ),
                    "",
                )
                item = (
                    self._apply_corrections_from_ledger(
                        target_type=target_type,
                        target_id=target_id,
                        source=source,
                        corrections=corrections,
                    )
                    if target_id
                    else source
                )
                if item is not None:
                    projected.append(item)
            result[collection] = projected

        for meeting in result.get("meetings", []):
            commitments: list[dict[str, Any]] = []
            for source in meeting.get("commitments", []):
                if not isinstance(source, dict):
                    continue
                target_id = str(source.get("id") or "")
                item = (
                    self._apply_corrections_from_ledger(
                        target_type="commitment",
                        target_id=target_id,
                        source=source,
                        corrections=corrections,
                    )
                    if target_id
                    else source
                )
                if item is not None:
                    commitments.append(item)
            meeting["commitments"] = commitments
        return result

    def confirm_person(
        self,
        *,
        candidate_name: str,
        confirmed_name: str,
        relation: str | None,
        notes: str | None,
        source_session_ids: list[str],
        everos_session_id: str,
    ) -> dict[str, Any]:
        data = self._read()
        aliases = [] if candidate_name == confirmed_name else [candidate_name]
        profile = {
            "id": f"person-{self._slug(confirmed_name)}-{uuid.uuid4().hex[:8]}",
            "name": confirmed_name,
            "aliases": aliases,
            "relation": relation,
            "notes": notes,
            "source_session_ids": source_session_ids,
            "status": "confirmed",
            "everos_session_id": everos_session_id,
            "updated_at": self._now(),
        }
        data["profiles"] = [
            item for item in data["profiles"] if item.get("name") != confirmed_name
        ]
        data["profiles"].insert(0, profile)
        data["frozen_candidates"] = [
            item
            for item in data["frozen_candidates"]
            if item.get("candidate_name") != candidate_name
        ]
        self._write(data)
        return profile

    def upsert_identity_profile(
        self,
        *,
        person_id: str,
        name: str,
        aliases: list[str],
        relation: str | None,
        organization: str | None,
        role: str | None,
        notes: str | None,
        face_candidate_ids: list[str],
        voice_candidate_ids: list[str],
        source_refs: list[str],
        source: str,
        everos_session_id: str,
    ) -> dict[str, Any]:
        """Create or version a user-controlled profile for the identity directory."""

        person_id = person_id.strip()
        name = name.strip()
        if not person_id or not name:
            raise ValueError("person_id and name are required")
        data = self._read()
        existing = next(
            (item for item in data["profiles"] if item.get("person_id") == person_id),
            None,
        )
        now = self._now()
        previous_versions = list((existing or {}).get("versions") or [])
        if existing is not None:
            previous_versions.insert(
                0,
                {
                    "name": existing.get("name"),
                    "aliases": list(existing.get("aliases") or []),
                    "relation": existing.get("relation"),
                    "organization": existing.get("organization"),
                    "role": existing.get("role"),
                    "notes": existing.get("notes"),
                    "status": existing.get("status"),
                    "updated_at": existing.get("updated_at"),
                    "change_source": source,
                },
            )
        profile = {
            **(existing or {}),
            "id": (existing or {}).get("id") or person_id,
            "person_id": person_id,
            "name": name,
            "aliases": _unique_text([*(existing or {}).get("aliases", []), *aliases]),
            "relation": relation if relation is not None else (existing or {}).get("relation"),
            "organization": (
                organization
                if organization is not None
                else (existing or {}).get("organization")
            ),
            "role": role if role is not None else (existing or {}).get("role"),
            "notes": notes if notes is not None else (existing or {}).get("notes"),
            "face_candidate_ids": _unique_text(
                [
                    *(existing or {}).get("face_candidate_ids", []),
                    *face_candidate_ids,
                ]
            ),
            "voice_candidate_ids": _unique_text(
                [
                    *(existing or {}).get("voice_candidate_ids", []),
                    *voice_candidate_ids,
                ]
            ),
            "source_refs": _unique_text(
                [*(existing or {}).get("source_refs", []), *source_refs]
            ),
            "status": "confirmed",
            "source": source,
            "everos_session_id": everos_session_id,
            "confirmed_at": (existing or {}).get("confirmed_at") or now,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
            "versions": previous_versions[:50],
        }
        data["profiles"] = [
            item
            for item in data["profiles"]
            if item.get("person_id") != person_id and item.get("id") != person_id
        ]
        data["profiles"].insert(0, profile)
        self._write(data)
        return profile

    def set_identity_profile_status(
        self,
        *,
        person_id: str,
        status: str,
        source: str,
    ) -> dict[str, Any]:
        if status not in {"confirmed", "frozen", "deleted"}:
            raise ValueError("invalid identity profile status")
        data = self._read()
        profile = next(
            (item for item in data["profiles"] if item.get("person_id") == person_id),
            None,
        )
        if profile is None:
            raise KeyError(person_id)
        profile.setdefault("versions", []).insert(
            0,
            {
                "name": profile.get("name"),
                "status": profile.get("status"),
                "updated_at": profile.get("updated_at"),
                "change_source": source,
            },
        )
        profile["versions"] = profile["versions"][:50]
        profile["status"] = status
        profile["updated_at"] = self._now()
        self._write(data)
        return profile

    def delete_identity_profile(self, *, person_id: str) -> dict[str, Any]:
        """Remove user-entered identity fields instead of keeping a deleted profile."""

        person_id = person_id.strip()
        if not person_id:
            raise ValueError("person_id is required")
        data = self._read()
        existing = next(
            (item for item in data["profiles"] if item.get("person_id") == person_id),
            None,
        )
        if existing is None:
            return {"person_id": person_id, "deleted": True, "removed": False}
        data["profiles"] = [
            item for item in data["profiles"] if item.get("person_id") != person_id
        ]
        self._write(data)
        return {"person_id": person_id, "deleted": True, "removed": True}

    def remove_identity_candidate_link(
        self,
        *,
        person_id: str,
        candidate_id: str,
        modality: str,
        source: str,
    ) -> dict[str, Any]:
        """Remove one candidate relationship while preserving the person profile."""

        if modality not in {"face", "voice"}:
            raise ValueError("identity candidate modality must be face or voice")
        data = self._read()
        profile = next(
            (item for item in data["profiles"] if item.get("person_id") == person_id),
            None,
        )
        if profile is None:
            raise KeyError(person_id)
        key = f"{modality}_candidate_ids"
        previous = list(profile.get(key) or [])
        profile.setdefault("versions", []).insert(
            0,
            {
                "name": profile.get("name"),
                "face_candidate_ids": list(profile.get("face_candidate_ids") or []),
                "voice_candidate_ids": list(profile.get("voice_candidate_ids") or []),
                "status": profile.get("status"),
                "updated_at": profile.get("updated_at"),
                "change_source": source,
            },
        )
        profile["versions"] = profile["versions"][:50]
        profile[key] = [item for item in previous if item != candidate_id]
        profile["updated_at"] = self._now()
        self._write(data)
        return profile

    def delete_candidate_review(self, *, candidate_name: str) -> dict[str, Any]:
        """Remove bridge-local review state for a permanently deleted candidate."""

        data = self._read()
        before = len(data["frozen_candidates"])
        data["frozen_candidates"] = [
            item
            for item in data["frozen_candidates"]
            if item.get("candidate_name") != candidate_name
        ]
        self._write(data)
        return {
            "candidate_name": candidate_name,
            "deleted": True,
            "removed_review_count": before - len(data["frozen_candidates"]),
        }

    def freeze_candidate(
        self,
        *,
        candidate_name: str,
        reason: str,
        source_session_ids: list[str],
    ) -> dict[str, Any]:
        data = self._read()
        frozen = {
            "id": f"freeze-{self._slug(candidate_name)}-{uuid.uuid4().hex[:8]}",
            "candidate_name": candidate_name,
            "reason": reason,
            "source_session_ids": source_session_ids,
            "status": "frozen",
            "created_at": self._now(),
        }
        data["frozen_candidates"] = [
            item
            for item in data["frozen_candidates"]
            if item.get("candidate_name") != candidate_name
        ]
        data["frozen_candidates"].insert(0, frozen)
        data["profiles"] = [
            item
            for item in data["profiles"]
            if candidate_name not in [item.get("name"), *item.get("aliases", [])]
        ]
        self._write(data)
        return frozen

    def restore_candidate(self, *, candidate_name: str) -> dict[str, Any]:
        data = self._read()
        existing = next(
            (
                item
                for item in data["frozen_candidates"]
                if item.get("candidate_name") == candidate_name
            ),
            None,
        )
        data["frozen_candidates"] = [
            item
            for item in data["frozen_candidates"]
            if item.get("candidate_name") != candidate_name
        ]
        self._write(data)
        return {
            "candidate_name": candidate_name,
            "status": "active",
            "restored_from": existing,
            "restored_at": self._now(),
        }

    def add_object_observation(
        self,
        *,
        object_label: str,
        session_id: str,
        evidence_id: str,
        image_uri: str,
        captured_at_ms: int,
        confidence: float,
        sequence: int | None,
        location_hint: str | None,
    ) -> dict[str, Any]:
        return self.add_semantic_object_observation(
            object_label_raw=object_label,
            normalized_label=None,
            personal_object_id=None,
            visible_description=None,
            relation="visible_at",
            location_hint=location_hint,
            memory_value="memory_critical",
            semantic_confidence=confidence,
            captured_at_ms=captured_at_ms,
            boot_session_id=session_id,
            window_id=session_id,
            evidence_ids=[evidence_id],
            evidence_uris=[image_uri] if image_uri else [],
            evidence_available=True,
            source_capsule_id=None,
            source_model="legacy-bridge",
            source_prompt_version="legacy-object-observation-v1",
            detector_job_ids=[],
            sequence=sequence,
        )

    def add_semantic_object_observation(
        self,
        *,
        object_label_raw: str,
        normalized_label: str | None,
        personal_object_id: str | None,
        visible_description: str | None,
        relation: str | None,
        location_hint: str | None,
        memory_value: str,
        semantic_confidence: float,
        captured_at_ms: int,
        boot_session_id: str,
        window_id: str,
        evidence_ids: list[str],
        evidence_uris: list[str],
        evidence_available: bool,
        source_capsule_id: str | None,
        source_model: str,
        source_prompt_version: str,
        detector_job_ids: list[str],
        aliases: list[str] | None = None,
        object_identity_id: str | None = None,
        merge_decision: str | None = None,
        merge_target_observation_id: str | None = None,
        instance_ambiguity: bool = False,
        correction_source_id: str | None = None,
        created_at_ms: int | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        data = self._read()
        registry = ObjectAliasRegistry.default()
        if personal_object_id:
            query_key = personal_object_id.strip().casefold()
            alias_source = "personal_object_id"
        else:
            query_key, alias_source = registry.normalize(
                normalized_label or object_label_raw,
            )
        item = build_semantic_observation(
            object_label_raw=object_label_raw,
            normalized_label=query_key,
            personal_object_id=personal_object_id,
            visible_description=visible_description,
            relation=relation,
            location_hint=location_hint,
            memory_value=memory_value,
            semantic_confidence=semantic_confidence,
            captured_at_ms=captured_at_ms,
            boot_session_id=boot_session_id,
            window_id=window_id,
            evidence_ids=evidence_ids,
            evidence_uris=evidence_uris,
            evidence_available=evidence_available,
            source_capsule_id=source_capsule_id,
            source_model=source_model,
            source_prompt_version=source_prompt_version,
            alias_version=registry.version,
            detector_job_ids=detector_job_ids,
            aliases=aliases,
            object_identity_id=object_identity_id,
            instance_ambiguity=instance_ambiguity,
            correction_source_id=correction_source_id,
            created_at_ms=created_at_ms,
        )
        item["alias_source"] = alias_source
        item["sequence"] = sequence
        item["merge_decision"] = merge_decision
        item["merge_target_observation_id"] = merge_target_observation_id
        semantic_matches = [
            value
            for value in data["object_observations"]
            if value.get("state") in {"semantic_only", "fused"}
            and value.get("window_id") == window_id
            and value.get("normalized_label") == query_key
            and value.get("source_capsule_id") == source_capsule_id
        ]
        semantic_matches.sort(key=lambda value: int(value.get("created_at_ms") or 0))
        existing = semantic_matches[0] if semantic_matches else None
        if existing is not None:
            mutable_keys = (
                "canonical_name",
                "aliases",
                "object_label_raw",
                "object_label",
                "evidence_ids",
                "evidence_uris",
                "evidence_id",
                "image_uri",
                "visible_description",
                "relation",
                "location_hint",
                "memory_value",
                "semantic_confidence",
                "confidence",
                "source_capsule_id",
                "source_model",
                "source_prompt_version",
                "alias_version",
                "alias_source",
                "merge_decision",
                "merge_target_observation_id",
                "instance_ambiguity",
            )
            item["aliases"] = list(dict.fromkeys([
                *item.get("aliases", []),
                *(
                    alias
                    for match in semantic_matches
                    for alias in match.get("aliases", [])
                ),
            ]))
            item["evidence_ids"] = sorted(dict.fromkeys([
                *item.get("evidence_ids", []),
                *(
                    evidence_id
                    for match in semantic_matches
                    for evidence_id in match.get("evidence_ids", [])
                ),
            ]))
            item["evidence_uris"] = list(dict.fromkeys([
                *item.get("evidence_uris", []),
                *(
                    uri
                    for match in semantic_matches
                    for uri in match.get("evidence_uris", [])
                ),
            ]))
            item["evidence_id"] = item["evidence_ids"][0] if item["evidence_ids"] else None
            item["image_uri"] = item["evidence_uris"][0] if item["evidence_uris"] else None
            previous = {key: existing.get(key) for key in mutable_keys}
            changed = any(existing.get(key) != item.get(key) for key in mutable_keys)
            if changed:
                history = list(existing.get("version_history") or [])
                history.append(previous)
                preserved = {
                    "observation_id": existing.get("observation_id"),
                    "id": existing.get("id"),
                    "object_identity_id": existing.get("object_identity_id"),
                    "created_at_ms": existing.get("created_at_ms"),
                    "correction_source_id": existing.get("correction_source_id"),
                }
                existing.update(item)
                existing.update({key: value for key, value in preserved.items() if value})
                existing["version_history"] = history
                existing["updated_at_ms"] = int(
                    datetime.now(timezone.utc).timestamp() * 1000
                )
            duplicate_rows = semantic_matches[1:]
            if duplicate_rows:
                duplicate_refs = {id(value) for value in duplicate_rows}
                data["object_observations"] = [
                    value
                    for value in data["object_observations"]
                    if id(value) not in duplicate_refs
                ]
            if changed or duplicate_rows:
                self._write(data)
            return existing
        data["object_observations"].append(item)
        data["object_observations"].sort(
            key=lambda value: int(value.get("captured_at_ms") or 0),
            reverse=True,
        )
        self._write(data)
        return item

    def query_last_seen_object(self, query: str) -> dict[str, Any]:
        data = self._read()
        registry = ObjectAliasRegistry.default()
        query_key, _ = registry.normalize(query, user_objects=data.get("confirmed_objects", []))
        observations = self._compatible_object_observations(data, registry)
        result = build_last_seen_result(
            observations,
            query=query,
            query_key=query_key,
            alias_version=registry.version,
        )
        projection = projection_from_result(result)
        data["object_last_seen_projections"] = [
            item for item in data["object_last_seen_projections"] if item.get("query_key") != query_key
        ]
        data["object_last_seen_projections"].append(projection)
        self._write(data)
        return result

    def clear_object_last_seen_projections(self) -> None:
        data = self._read()
        data["object_last_seen_projections"] = []
        self._write(data)

    def rebuild_object_last_seen_projections(self) -> list[dict[str, Any]]:
        data = self._read()
        registry = ObjectAliasRegistry.default()
        observations = self._compatible_object_observations(data, registry)
        keys = sorted(
            {
                str(item.get("normalized_label"))
                for item in observations
                if item.get("normalized_label")
                and item.get("memory_value", "memory_critical") == "memory_critical"
            }
        )
        projections = []
        for key in keys:
            result = build_last_seen_result(
                observations,
                query=key,
                query_key=key,
                alias_version=registry.version,
            )
            projections.append(projection_from_result(result))
        data["object_last_seen_projections"] = projections
        self._write(data)
        return projections

    def last_seen_object(self, query: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        result = self.query_last_seen_object(query)
        latest = result.get("latest_reliable")
        if latest is None:
            return None, []
        data = self._read()
        registry = ObjectAliasRegistry.default()
        sequence = [
            item
            for item in self._compatible_object_observations(data, registry)
            if item.get("normalized_label") == result["normalized_query"]
            and item.get("boot_session_id") == latest.get("boot_session_id")
        ]
        sequence.sort(key=lambda value: int(value.get("captured_at_ms") or 0))
        return latest, sequence[-4:]

    @staticmethod
    def _compatible_object_observations(
        data: dict[str, list[dict[str, Any]]],
        registry: ObjectAliasRegistry,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for original in data.get("object_observations", []):
            if original.get("normalized_label"):
                observations.append(original)
                continue
            item = dict(original)
            normalized, _ = registry.normalize(
                str(item.get("object_label") or ""),
            )
            if not normalized:
                continue
            item.update(
                {
                    "observation_id": item.get("id"),
                    "observation_kind": "semantic_confirmed",
                    "object_label_raw": item.get("object_label"),
                    "normalized_label": normalized,
                    "personal_object_id": None,
                    "memory_value": "memory_critical",
                    "semantic_confidence": float(item.get("confidence") or 0),
                    "boot_session_id": item.get("session_id"),
                    "window_id": item.get("session_id"),
                    "evidence_ids": [item["evidence_id"]]
                    if item.get("evidence_id")
                    else [],
                    "evidence_uris": [item["image_uri"]]
                    if item.get("image_uri")
                    else [],
                    "evidence_available": True,
                    "audit_status": "ready",
                    "source_model": "legacy-bridge",
                    "source_prompt_version": "legacy-object-observation-v1",
                    "alias_version": registry.version,
                }
            )
            observations.append(item)
        return observations

    def add_meeting(self, meeting: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        data["meetings"] = [
            item for item in data["meetings"] if item.get("session_id") != meeting.get("session_id")
        ]
        data["meetings"].insert(0, meeting)
        self._write(data)
        return meeting

    def upsert_commitment_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Insert an evidence-backed model candidate or merge a repeated mention."""

        text = " ".join(str(candidate.get("text") or "").split()).strip()
        quote = " ".join(str(candidate.get("source_quote") or "").split()).strip()
        evidence_refs = list(
            dict.fromkeys(
                str(value).strip()
                for value in candidate.get("evidence_refs") or []
                if str(value).strip()
            )
        )
        if not text or not quote:
            raise ValueError("commitment text and source_quote are required")
        if not evidence_refs:
            raise ValueError("commitment evidence_refs are required")
        owner_key = str(
            candidate.get("owner_person_id")
            or candidate.get("owner_candidate_id")
            or candidate.get("owner_display")
            or "unknown"
        ).strip().casefold()
        normalized_text = re.sub(
            r"[^a-z0-9\u4e00-\u9fff]+", "", text.casefold()
        )
        if not normalized_text:
            raise ValueError("commitment text has no searchable content")
        dedupe_key = hashlib.sha256(
            f"{owner_key}|{normalized_text}".encode("utf-8")
        ).hexdigest()
        data = self._read()
        existing = next(
            (
                item
                for item in data["commitments"]
                if item.get("dedupe_key") == dedupe_key
            ),
            None,
        )
        windows = list(
            dict.fromkeys(
                str(value).strip()
                for value in candidate.get("source_window_ids") or []
                if str(value).strip()
            )
        )
        if existing is not None:
            existing["evidence_refs"] = list(
                dict.fromkeys([*existing.get("evidence_refs", []), *evidence_refs])
            )
            existing["source_window_ids"] = list(
                dict.fromkeys([*existing.get("source_window_ids", []), *windows])
            )
            existing["source_quotes"] = list(
                dict.fromkeys([*existing.get("source_quotes", []), quote])
            )
            existing["mention_count"] = int(existing.get("mention_count") or 1) + 1
            existing["updated_at"] = self._now()
            for key in (
                "owner_person_id",
                "owner_candidate_id",
                "owner_display",
                "due_hint",
                "normalized_due_at",
            ):
                if not existing.get(key) and candidate.get(key):
                    existing[key] = candidate.get(key)
            self._write(data)
            return {**self._public_item(existing), "deduplicated": True}

        commitment_id = f"commitment-{dedupe_key[:20]}"
        confidence = candidate.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        item = {
            "id": commitment_id,
            "commitment_id": commitment_id,
            "dedupe_key": dedupe_key,
            "owner_person_id": candidate.get("owner_person_id"),
            "owner_candidate_id": candidate.get("owner_candidate_id"),
            "owner_display": str(candidate.get("owner_display") or "未知说话人")[:120],
            "text": text[:800],
            "due_hint": str(candidate.get("due_hint") or "").strip()[:160] or None,
            "normalized_due_at": str(
                candidate.get("normalized_due_at") or ""
            ).strip()[:80]
            or None,
            "status": "candidate",
            "source_quote": quote[:1200],
            "source_quotes": [quote[:1200]],
            "evidence_refs": evidence_refs,
            "meeting_id": candidate.get("meeting_id"),
            "capsule_id": candidate.get("capsule_id"),
            "source_window_ids": windows,
            "mention_count": 1,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "source_model": str(candidate.get("source_model") or "unknown")[:160],
            "contract_version": str(
                candidate.get("contract_version") or "commitment-extraction-v1"
            )[:120],
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        data["commitments"].insert(0, item)
        self._write(data)
        return {**self._public_item(item), "deduplicated": False}

    def preupload_person(
        self,
        *,
        name: str,
        aliases: list[str],
        relation: str | None,
        notes: str | None,
        reminder_threshold: float,
        quiet_hours: dict[str, str] | None,
        everos_session_id: str,
    ) -> dict[str, Any]:
        data = self._read()
        profile = {
            "id": f"person-{self._slug(name)}-{uuid.uuid4().hex[:8]}",
            "name": name,
            "aliases": aliases,
            "relation": relation,
            "notes": notes,
            "source_session_ids": [],
            "status": "confirmed",
            "source": "preupload",
            "reminder_threshold": reminder_threshold,
            "quiet_hours": quiet_hours or {},
            "everos_session_id": everos_session_id,
            "updated_at": self._now(),
        }
        data["profiles"] = [
            item
            for item in data["profiles"]
            if item.get("name") != name and name not in item.get("aliases", [])
        ]
        data["profiles"].insert(0, profile)
        self._write(data)
        return profile

    def find_person(self, person_name: str) -> dict[str, Any] | None:
        target = person_name.strip().lower()
        for profile in self._read()["profiles"]:
            names = [profile.get("name"), *profile.get("aliases", [])]
            if any(str(name).strip().lower() == target for name in names):
                return profile
        return None

    def add_reminder_evaluation(self, item: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        data["reminder_evaluations"].insert(0, item)
        self._write(data)
        return item

    def daily_report_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        value = next(
            (
                item
                for item in self._read()["daily_reports"]
                if item.get("idempotency_key") == key
            ),
            None,
        )
        return self._public_item(value) if value is not None else None

    def daily_report_job(self, report_id: str) -> dict[str, Any] | None:
        value = next(
            (
                item
                for item in self._read()["daily_reports"]
                if str(item.get("id") or "") == report_id
            ),
            None,
        )
        return self._public_item(value) if value is not None else None

    def daily_report_versions(self, date: str) -> list[dict[str, Any]]:
        values = [
            self._public_item(item)
            for item in self._read()["daily_reports"]
            if item.get("date") == date
        ]
        values.sort(key=lambda item: int(item.get("version") or 0), reverse=True)
        return values

    def daily_report_days(self, *, limit: int = 90) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for source in self._read()["daily_reports"]:
            report_date = str(source.get("date") or "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
                continue
            grouped.setdefault(report_date, []).append(self._public_item(source))
        days: list[dict[str, Any]] = []
        for report_date, versions in grouped.items():
            versions.sort(key=lambda item: int(item.get("version") or 0), reverse=True)
            current = next(
                (
                    item
                    for item in versions
                    if item.get("is_current")
                    and item.get("status") in {"ready", "closed"}
                ),
                None,
            ) or next(
                (
                    item
                    for item in versions
                    if item.get("status") in {"ready", "closed"}
                ),
                versions[0],
            )
            content = (
                current.get("content")
                if isinstance(current.get("content"), dict)
                else {}
            )
            days.append(
                {
                    "date": report_date,
                    "status": current.get("status"),
                    "current_report_id": current.get("id"),
                    "current_version": int(current.get("version") or 0),
                    "version_count": len(versions),
                    "generation_type": current.get("generation_type"),
                    "aggregation_status": current.get("aggregation_status"),
                    "generated_at": current.get("completed_at")
                    or current.get("updated_at")
                    or current.get("created_at"),
                    "overview": str(content.get("overview") or current.get("summary") or "")[
                        :240
                    ],
                    "timeline_count": len(content.get("timeline") or []),
                    "notable_count": len(content.get("notable_items") or []),
                    "special_moment_count": len(content.get("special_moments") or []),
                    "todo_change_count": len(content.get("todo_changes") or []),
                }
            )
        days.sort(key=lambda item: item["date"], reverse=True)
        return days[: max(1, min(366, int(limit)))]

    def current_daily_report(self, date: str) -> dict[str, Any] | None:
        versions = self.daily_report_versions(date)
        current = next(
            (
                item
                for item in versions
                if item.get("is_current") and item.get("status") in {"ready", "closed"}
            ),
            None,
        )
        if current is not None:
            return self.apply_corrections(
                target_type="daily_report",
                target_id=str(current["id"]),
                source=current,
            )
        return next(
            (item for item in versions if item.get("status") in {"ready", "closed"}),
            None,
        )

    def start_daily_report_version(
        self,
        *,
        date: str,
        generation_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            existing = next(
                (
                    item
                    for item in data["daily_reports"]
                    if item.get("idempotency_key") == idempotency_key
                ),
                None,
            )
            if existing is not None:
                return self._public_item(existing)
            version = 1 + max(
                [
                    int(item.get("version") or 0)
                    for item in data["daily_reports"]
                    if item.get("date") == date
                ]
                or [0]
            )
            digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
            now = self._now()
            report = {
                "id": f"daily-{date}-v{version}-{digest}",
                "date": date,
                "version": version,
                "idempotency_key": idempotency_key,
                "generation_type": generation_type,
                "status": "generating",
                "aggregation_status": "final",
                "is_current": False,
                "content": {},
                "summary": "",
                "created_at": now,
                "updated_at": now,
            }
            data["daily_reports"].insert(0, report)
            self._write(data)
            return self._public_item(report)

    def complete_daily_report_version(
        self,
        report_id: str,
        *,
        content: dict[str, Any],
        input_snapshot: dict[str, Any],
        input_fingerprint: str,
        aggregation_status: str,
        model: str,
        prompt_version: str,
    ) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            report = next(
                (
                    item
                    for item in data["daily_reports"]
                    if str(item.get("id") or "") == report_id
                ),
                None,
            )
            if report is None:
                raise KeyError(report_id)
            for item in data["daily_reports"]:
                if item.get("date") == report.get("date"):
                    item["is_current"] = False
            report.update(
                {
                    "status": "ready",
                    "aggregation_status": aggregation_status,
                    "is_current": True,
                    "content": deepcopy(content),
                    "summary": str(content.get("overview") or ""),
                    "input_snapshot": deepcopy(input_snapshot),
                    "input_fingerprint": input_fingerprint,
                    "model": model,
                    "prompt_version": prompt_version,
                    "error": None,
                    "completed_at": self._now(),
                    "updated_at": self._now(),
                }
            )
            self._write(data)
            return self._public_item(report)

    def fail_daily_report_version(self, report_id: str, *, error: str) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            report = next(
                (
                    item
                    for item in data["daily_reports"]
                    if str(item.get("id") or "") == report_id
                ),
                None,
            )
            if report is None:
                raise KeyError(report_id)
            report.update(
                {
                    "status": "failed",
                    "is_current": False,
                    "error": str(error)[:2000],
                    "updated_at": self._now(),
                }
            )
            self._write(data)
            return self._public_item(report)

    def list_todos(self) -> list[dict[str, Any]]:
        values = self.snapshot().get("commitments", [])
        values.sort(
            key=lambda item: (
                str(item.get("status") or ""),
                str(item.get("normalized_due_at") or "9999"),
                str(item.get("created_at") or ""),
            )
        )
        return values

    def create_user_todo(
        self,
        *,
        text: str,
        due_at: str | None = None,
        priority: str = "normal",
        owner_person_id: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_text = " ".join(str(text or "").split()).strip()
        if not clean_text:
            raise ValueError("todo text is required")
        with self._data_lock:
            data = self._read()
            existing = next(
                (
                    item
                    for item in data["commitments"]
                    if item.get("creation_idempotency_key") == idempotency_key
                ),
                None,
            )
            if existing is not None:
                return {**self._public_item(existing), "idempotent": True}
            digest = hashlib.sha256(
                f"{idempotency_key}|{clean_text}".encode("utf-8")
            ).hexdigest()
            todo_id = f"todo-{digest[:20]}"
            now = self._now()
            item = {
                "id": todo_id,
                "commitment_id": todo_id,
                "creation_idempotency_key": idempotency_key,
                "source_type": "user_created",
                "owner_person_id": owner_person_id,
                "owner_display": "我",
                "text": clean_text[:800],
                "due_hint": None,
                "normalized_due_at": due_at,
                "priority": priority,
                "status": "open",
                "source_quote": clean_text[:1200],
                "source_quotes": [clean_text[:1200]],
                "evidence_refs": [f"todo://user/{todo_id}"],
                "source_window_ids": [],
                "progress_events": [],
                "mention_count": 1,
                "confidence": 1.0,
                "source_model": "user",
                "contract_version": "todo-ledger-v1",
                "created_at": now,
                "updated_at": now,
            }
            data["commitments"].insert(0, item)
            event = self._todo_event(
                todo_id=todo_id,
                event_type="created",
                occurred_at=now,
                source_episode_id=None,
                evidence_text="",
                confidence=1.0,
            )
            data["todo_events"].insert(0, event)
            self._write(data)
            return {**self._public_item(item), "idempotent": False}

    def todo_by_id(self, todo_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.list_todos()
                if str(item.get("id") or item.get("commitment_id") or "") == todo_id
            ),
            None,
        )

    def record_todo_progress(
        self,
        *,
        todo_id: str,
        decision: str,
        episode_id: str,
        evidence_text: str,
        confidence: float,
        occurred_at: str,
    ) -> dict[str, Any]:
        if decision not in {"progress", "suspected_completed"}:
            raise ValueError("invalid todo progress decision")
        projected_before = self.todo_by_id(todo_id)
        if projected_before is None:
            raise KeyError(todo_id)
        with self._data_lock:
            data = self._read()
            todo = next(
                (
                    item
                    for item in data["commitments"]
                    if str(item.get("id") or item.get("commitment_id") or "") == todo_id
                ),
                None,
            )
            if todo is None:
                raise KeyError(todo_id)
            dedupe_key = hashlib.sha256(
                f"{todo_id}|{decision}|{episode_id}|{evidence_text}".encode("utf-8")
            ).hexdigest()
            existing = next(
                (
                    item
                    for item in data["todo_events"]
                    if item.get("dedupe_key") == dedupe_key
                ),
                None,
            )
            if existing is not None:
                return self._public_item(existing)
            event = self._todo_event(
                todo_id=todo_id,
                event_type=decision,
                occurred_at=occurred_at,
                source_episode_id=episode_id,
                evidence_text=evidence_text,
                confidence=confidence,
            )
            event["dedupe_key"] = dedupe_key
            todo.setdefault("progress_events", []).insert(0, event)
            todo["updated_at"] = self._now()
            todo["evidence_refs"] = list(
                dict.fromkeys(
                    [*todo.get("evidence_refs", []), f"everos://episode/{episode_id}"]
                )
            )
            data["todo_events"].insert(0, event)
            self._write(data)
        old_status = str(projected_before.get("status") or "candidate")
        next_status = (
            "suspected_completed"
            if decision == "suspected_completed"
            else (
                "in_progress"
                if old_status in {"confirmed", "open"}
                else old_status
            )
        )
        if next_status != old_status:
            self.upsert_correction(
                idempotency_key=f"todo-progress:{dedupe_key}:status",
                target_type="commitment",
                target_id=todo_id,
                field_path="status",
                old_value=old_status,
                new_value=next_status,
                decision_status="confirmed",
                evidence_refs=[f"everos://episode/{episode_id}"],
                note=f"Episode-derived todo state: {decision}",
            )
        return self._public_item(event)

    def record_todo_user_event(
        self,
        *,
        todo_id: str,
        event_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            existing = next(
                (
                    item
                    for item in data["todo_events"]
                    if item.get("idempotency_key") == idempotency_key
                ),
                None,
            )
            if existing is not None:
                return self._public_item(existing)
            event = self._todo_event(
                todo_id=todo_id,
                event_type=event_type,
                occurred_at=self._now(),
                source_episode_id=None,
                evidence_text="",
                confidence=1.0,
            )
            event["idempotency_key"] = idempotency_key
            data["todo_events"].insert(0, event)
            self._write(data)
            return self._public_item(event)

    def delete_todo(self, todo_id: str, *, idempotency_key: str) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            tombstone = next(
                (
                    item
                    for item in data["deleted_todos"]
                    if item.get("idempotency_key") == idempotency_key
                ),
                None,
            )
            if tombstone is not None:
                return self._public_item(tombstone)
            before = len(data["commitments"])
            data["commitments"] = [
                item
                for item in data["commitments"]
                if str(item.get("id") or item.get("commitment_id") or "") != todo_id
            ]
            if len(data["commitments"]) == before:
                raise KeyError(todo_id)
            tombstone = {
                "id": f"deleted-{uuid.uuid4().hex}",
                "todo_id": todo_id,
                "idempotency_key": idempotency_key,
                "deleted_at": self._now(),
            }
            data["deleted_todos"].insert(0, tombstone)
            data["todo_events"] = [
                item for item in data["todo_events"] if item.get("todo_id") != todo_id
            ]
            self._write(data)
            return self._public_item(tombstone)

    def todo_events_for_date(
        self,
        date: str,
        *,
        timezone_name: str = "Asia/Shanghai",
    ) -> list[dict[str, Any]]:
        zone = ZoneInfo(timezone_name)
        values: list[dict[str, Any]] = []
        for item in self._read()["todo_events"]:
            try:
                parsed = datetime.fromisoformat(
                    str(item.get("occurred_at") or "").replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.astimezone(zone).date().isoformat() == date:
                values.append(self._public_item(item))
        values.sort(key=lambda item: str(item.get("occurred_at") or ""))
        return values

    def todo_episode_processed(self, episode_id: str, fingerprint: str) -> bool:
        return any(
            item.get("episode_id") == episode_id
            and item.get("fingerprint") == fingerprint
            for item in self._read()["processed_todo_episodes"]
        )

    def mark_todo_episode_processed(self, episode_id: str, fingerprint: str) -> None:
        with self._data_lock:
            data = self._read()
            data["processed_todo_episodes"] = [
                item
                for item in data["processed_todo_episodes"]
                if item.get("episode_id") != episode_id
            ]
            data["processed_todo_episodes"].insert(
                0,
                {
                    "episode_id": episode_id,
                    "fingerprint": fingerprint,
                    "processed_at": self._now(),
                },
            )
            data["processed_todo_episodes"] = data["processed_todo_episodes"][:5000]
            self._write(data)

    @staticmethod
    def _todo_event(
        *,
        todo_id: str,
        event_type: str,
        occurred_at: str,
        source_episode_id: str | None,
        evidence_text: str,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "id": f"todo-event-{uuid.uuid4().hex}",
            "todo_id": todo_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "source_episode_id": source_episode_id,
            "source_episode_ids": [source_episode_id] if source_episode_id else [],
            "evidence_text": evidence_text,
            "confidence": max(0.0, min(1.0, float(confidence))),
        }

    def daily_report(self, date: str) -> dict[str, Any]:
        current = self.current_daily_report(date)
        if current is not None:
            content = current.get("content") if isinstance(current.get("content"), dict) else {}
            return {
                **current,
                "confirmed_events": [
                    item.get("text")
                    for item in content.get("timeline", [])
                    if isinstance(item, dict) and item.get("text")
                ],
                "commitments": [
                    item
                    for item in self.list_todos()
                    if item.get("status")
                    in {"confirmed", "open", "in_progress", "suspected_completed"}
                ],
                "object_events": [],
                "people_updates": [],
                "frozen_candidates": self.snapshot().get("frozen_candidates", []),
            }
        data = self._apply_snapshot_corrections(self._read())
        corrections = self._read_correction_ledger()["corrections"]
        corrections.sort(key=lambda item: int(item.get("version") or 0))
        reverted = {
            str(item.get("reverts_id") or "")
            for item in corrections
            if item.get("action") == "revert"
        }
        effective_events: dict[str, str] = {}
        for item in corrections:
            if (
                item.get("action") != "set"
                or item.get("id") in reverted
                or item.get("target_type") != "episode"
                or item.get("field_path") != "content"
                or item.get("decision_status") != "confirmed"
            ):
                continue
            value = str(item.get("new_value") or "").strip()
            if value:
                effective_events[str(item.get("target_id") or "")] = value
        confirmed_events = list(effective_events.values())
        legacy_commitments = [
            commitment
            for meeting in data["meetings"]
            for commitment in meeting.get("commitments", [])
            if isinstance(commitment, dict)
        ]
        commitments = [
            item
            for item in data.get("commitments", [])
            if item.get("status") == "confirmed"
        ]
        known_ids = {str(item.get("id") or "") for item in commitments}
        commitments.extend(
            item
            for item in legacy_commitments
            if not item.get("id") or str(item.get("id")) not in known_ids
        )
        object_events = data["object_observations"][:10]
        people_updates = data["profiles"][:10]
        existing = next(
            (item for item in data["daily_reports"] if item.get("date") == date),
            None,
        )
        report = {
            **(existing or {}),
            "id": str((existing or {}).get("id") or f"daily-{date}"),
            "date": date,
            "summary": str((existing or {}).get("summary") or ""),
            "status": str((existing or {}).get("status") or "open"),
            "confirmed_events": confirmed_events,
            "commitments": commitments,
            "object_events": object_events,
            "people_updates": people_updates,
            "frozen_candidates": data["frozen_candidates"],
        }
        return self.apply_corrections(
            target_type="daily_report",
            target_id=str(report["id"]),
            source=report,
        ) or report

    def close_daily_report(
        self,
        *,
        date: str,
        corrections: list[str],
        everos_session_id: str,
    ) -> dict[str, Any]:
        with self._data_lock:
            data = self._read()
            existing = next(
                (
                    item
                    for item in data["daily_reports"]
                    if item.get("date") == date and item.get("is_current")
                ),
                None,
            ) or next(
                (item for item in data["daily_reports"] if item.get("date") == date),
                None,
            )
            if existing is None:
                existing = {
                    "id": f"daily-{date}",
                    "date": date,
                    "version": 1,
                    "generation_type": "legacy",
                    "is_current": True,
                    "content": {},
                    "summary": "",
                    "created_at": self._now(),
                }
                data["daily_reports"].insert(0, existing)
            existing.update(
                {
                    "corrections": corrections,
                    "status": "closed",
                    "everos_session_id": everos_session_id,
                    "closed_at": self._now(),
                    "updated_at": self._now(),
                }
            )
            self._write(data)
            return self._public_item(existing)

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        return {
            "corrections": self._list(payload.get("corrections")),
            "profiles": self._list(payload.get("profiles")),
            "frozen_candidates": self._list(payload.get("frozen_candidates")),
            "object_observations": self._list(payload.get("object_observations")),
            "object_candidate_observations": self._list(
                payload.get("object_candidate_observations")
            ),
            "confirmed_objects": self._list(payload.get("confirmed_objects")),
            "object_last_seen_projections": self._list(
                payload.get("object_last_seen_projections")
            ),
            "meetings": self._list(payload.get("meetings")),
            "reminder_evaluations": self._list(payload.get("reminder_evaluations")),
            "daily_reports": self._list(payload.get("daily_reports")),
            "todo_events": self._list(payload.get("todo_events")),
            "deleted_todos": self._list(payload.get("deleted_todos")),
            "processed_todo_episodes": self._list(
                payload.get("processed_todo_episodes")
            ),
            "boot_sessions": self._list(payload.get("boot_sessions")),
            "capsules": self._list(payload.get("capsules")),
            "identity_observations": self._list(payload.get("identity_observations")),
            "meeting_evidence": self._list(payload.get("meeting_evidence")),
            "commitments": self._list(payload.get("commitments")),
            "identity_candidates": self._list(payload.get("identity_candidates")),
            "person_drafts": self._list(payload.get("person_drafts")),
            "event_queues": self._list(payload.get("event_queues")),
        }

    def _write(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _read_correction_ledger(self) -> dict[str, Any]:
        """Read the correction sidecar, migrating legacy rows when necessary."""

        if self.correction_path.exists():
            try:
                payload = json.loads(self.correction_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            return {
                "schema_version": "mvp16-v1",
                "corrections": self._list(payload.get("corrections")),
            }

        legacy = self._read().get("corrections", [])
        migrated: list[dict[str, Any]] = []
        for index, row in enumerate(legacy):
            source_id = str(row.get("source_id") or row.get("target_id") or "").strip()
            if not source_id:
                continue
            correction_id = str(row.get("id") or f"legacy-correction-{index + 1}")
            status = str(row.get("status") or "confirmed")
            migrated.append(
                {
                    **deepcopy(row),
                    "id": correction_id,
                    "correction_id": correction_id,
                    "idempotency_key": str(
                        row.get("idempotency_key") or f"legacy-import:{correction_id}"
                    ),
                    "request_fingerprint": row.get("request_fingerprint"),
                    "target_type": str(row.get("target_type") or "episode"),
                    "target_id": source_id,
                    "source_id": source_id,
                    "field_path": str(
                        row.get("field_path")
                        or ("$" if status == "rejected" else "content")
                    ),
                    "old_value": row.get("old_value", row.get("original_content")),
                    "new_value": row.get("new_value", row.get("corrected_content")),
                    "decision_status": str(row.get("decision_status") or status),
                    "status": status,
                    "action": str(row.get("action") or "set"),
                    "version": int(row.get("version") or 1),
                    "evidence_refs": list(
                        row.get("evidence_refs") or [f"everos://episode/{source_id}"]
                    ),
                    "writeback_status": str(row.get("writeback_status") or "applied"),
                    "writeback_stage": str(row.get("writeback_stage") or "applied"),
                    "attempt_count": int(row.get("attempt_count") or 0),
                    "next_retry_at_ms": int(row.get("next_retry_at_ms") or 0),
                    "last_error": row.get("last_error"),
                    "created_at": row.get("created_at") or self._now(),
                    "updated_at": row.get("updated_at") or self._now(),
                    "applied_at": row.get("applied_at") or row.get("updated_at"),
                }
            )
        ledger = {"schema_version": "mvp16-v1", "corrections": migrated}
        if migrated:
            self._write_correction_ledger(ledger)
        return ledger

    def _write_correction_ledger(self, ledger: dict[str, Any]) -> None:
        self.correction_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.correction_path.with_suffix(f"{self.correction_path.suffix}.tmp")
        payload = {
            "schema_version": "mvp16-v1",
            "corrections": self._list(ledger.get("corrections")),
        }
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.correction_path)

    @staticmethod
    def _validate_correction_field(
        target_type: str,
        field_path: str,
        decision_status: str,
    ) -> None:
        fields = {
            "capsule": {"text", "event_type"},
            "episode": {"content", "title", "summary"},
            "person": {"name", "relation", "organization", "role", "notes"},
            "object": {"canonical_name", "visible_description", "location_hint"},
            "commitment": {
                "owner_person_id",
                "text",
                "due_hint",
                "normalized_due_at",
                "priority",
                "status",
            },
            "daily_report": {"summary", "status", "title", "content.overview"},
        }
        if target_type not in fields:
            raise ValueError(f"unsupported target_type: {target_type}")
        if field_path == "$" and decision_status == "rejected":
            return
        if field_path not in fields[target_type]:
            raise ValueError(
                f"unsupported field_path for {target_type}: {field_path}"
            )

    @classmethod
    def _contains_private_vector(cls, value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold()
                if "embedding" in normalized or normalized in {
                    "vector",
                    "vectors",
                    "feature_vector",
                }:
                    return True
                if cls._contains_private_vector(child):
                    return True
        if isinstance(value, list):
            return any(cls._contains_private_vector(child) for child in value)
        return False

    @staticmethod
    def _set_projection_field(target: dict[str, Any], field_path: str, value: Any) -> None:
        parts = [part for part in field_path.split(".") if part]
        if not parts:
            raise ValueError("field_path cannot be empty")
        cursor = target
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = value

    @staticmethod
    def _empty() -> dict[str, list[dict[str, Any]]]:
        return {
            "corrections": [],
            "profiles": [],
            "frozen_candidates": [],
            "object_observations": [],
            "object_candidate_observations": [],
            "confirmed_objects": [],
            "object_last_seen_projections": [],
            "meetings": [],
            "reminder_evaluations": [],
            "daily_reports": [],
            "todo_events": [],
            "deleted_todos": [],
            "processed_todo_episodes": [],
            "boot_sessions": [],
            "capsules": [],
            "identity_observations": [],
            "meeting_evidence": [],
            "commitments": [],
            "identity_candidates": [],
            "person_drafts": [],
            "event_queues": [],
        }

    @staticmethod
    def _list(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
        return slug.lower() or "unknown"

    @staticmethod
    def _uncertainty(confidence: float) -> str:
        if confidence >= 0.85:
            return "low"
        if confidence >= 0.65:
            return "medium"
        return "high"

    @staticmethod
    def _local_date(captured_at_ms: int, timezone_name: str) -> str:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = timezone.utc
        return datetime.fromtimestamp(captured_at_ms / 1000, tz=tz).strftime("%Y-%m-%d")

    @classmethod
    def _public_data(cls, data: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
        return {key: [cls._public_item(item) for item in values] for key, values in data.items()}

    @classmethod
    def _public_item(cls, item: dict[str, Any]) -> dict[str, Any]:
        public: dict[str, Any] = {}
        for key, value in item.items():
            if key in {"embedding", "face_embedding", "voice_embedding"}:
                public["embedding_dim"] = len(cls._embedding(value))
                continue
            if isinstance(value, list):
                public[key] = [
                    cls._public_item(child) if isinstance(child, dict) else child
                    for child in value
                ]
            elif isinstance(value, dict):
                public[key] = cls._public_item(value)
            else:
                public[key] = value
        return public

    @staticmethod
    def _event_queue_summary(item: dict[str, Any]) -> dict[str, Any]:
        entries = item.get("entries", []) if isinstance(item.get("entries"), list) else []
        latest = entries[-1].get("stabilized_projection", {}) if entries else {}
        return {
            key: value
            for key, value in item.items()
            if key not in {"entries", "window_ids", "cumulative_state"}
        } | {
            "window_count": len(item.get("window_ids", [])),
            "latest_window_ids": list(item.get("window_ids", []))[-10:],
            "latest_projection": latest if isinstance(latest, dict) else {},
        }

    @classmethod
    def _match_identity_candidate(
        cls,
        candidates: list[dict[str, Any]],
        *,
        modality: str,
        label: str,
        embedding: list[float],
        match_threshold: float,
    ) -> dict[str, Any] | None:
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in candidates:
            if candidate.get("modality") != modality or candidate.get("status") == "frozen":
                continue
            score = cls._cosine(candidate.get("embedding"), embedding) if embedding else 0.0
            aliases = [candidate.get("display_name"), *candidate.get("aliases", [])]
            label_match = bool(label) and any(str(alias).lower() == label.lower() for alias in aliases)
            if score >= match_threshold or label_match:
                rank = max(score, 0.75 if label_match else 0.0)
                if best is None or rank > best[0]:
                    best = (rank, candidate)
        return best[1] if best else None

    @staticmethod
    def _embedding(value: Any) -> list[float]:
        if not isinstance(value, list):
            return []
        output: list[float] = []
        for item in value[:1024]:
            if isinstance(item, (int, float)):
                output.append(float(item))
        return output

    @staticmethod
    def _cosine(left: Any, right: Any) -> float:
        left_vec = MemoryReviewStore._embedding(left)
        right_vec = MemoryReviewStore._embedding(right)
        if not left_vec or not right_vec or len(left_vec) != len(right_vec):
            return 0.0
        dot = sum(a * b for a, b in zip(left_vec, right_vec))
        left_norm = sum(a * a for a in left_vec) ** 0.5
        right_norm = sum(b * b for b in right_vec) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _centroid(existing: Any, new: list[float], existing_count: int) -> list[float]:
        current = MemoryReviewStore._embedding(existing)
        if not current or len(current) != len(new):
            return new
        total = max(existing_count, 0) + 1
        return [
            ((value * max(existing_count, 0)) + new_value) / total
            for value, new_value in zip(current, new)
        ]


def _unique_text(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output
