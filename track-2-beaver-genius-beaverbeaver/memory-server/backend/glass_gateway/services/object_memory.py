from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


OBSERVATION_KINDS = {"semantic_confirmed", "detector_candidate", "user_confirmed"}
OBSERVATION_STATES = {"detector_only", "semantic_only", "fused"}
MEMORY_VALUES = {"memory_critical", "context_only", "ignore"}
ANSWER_STATUSES = {
    "reliable",
    "reliable_with_later_uncertain",
    "uncertain_only",
    "multiple_candidates",
    "not_found",
}
DEFAULT_RELIABLE_CONFIDENCE = 0.75
PROJECTION_VERSION = 3


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


class ObjectAliasRegistry:
    def __init__(self, *, version: str, aliases: dict[str, list[str]]) -> None:
        self.version = version
        self.aliases = {
            str(key): tuple(dict.fromkeys(_text(item) for item in [key, *values] if _text(item)))
            for key, values in aliases.items()
        }
        self._frozen_lookup = {
            alias: key for key, values in self.aliases.items() for alias in values
        }

    @classmethod
    def default(cls) -> "ObjectAliasRegistry":
        path = Path(__file__).with_name("object_aliases.v1.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(version=str(payload["version"]), aliases=dict(payload["aliases"]))

    def normalize(
        self,
        label: str,
        *,
        user_objects: Iterable[dict[str, Any]] = (),
    ) -> tuple[str, str]:
        needle = _text(label)
        for item in user_objects:
            names = [item.get("label"), item.get("prompt"), *(item.get("aliases") or [])]
            if needle not in {_text(value) for value in names if _text(value)}:
                continue
            personal_id = _text(item.get("personal_object_id"))
            if personal_id:
                return personal_id, "user_alias"
            canonical = _text(item.get("normalized_label") or item.get("prompt") or item.get("label"))
            return self._frozen_lookup.get(canonical, canonical), "user_alias"
        if needle in self._frozen_lookup:
            return self._frozen_lookup[needle], "frozen_alias"
        return needle.replace(" ", "_"), "source_label"


def build_semantic_observation(
    *,
    object_label_raw: str,
    normalized_label: str,
    captured_at_ms: int,
    boot_session_id: str,
    window_id: str,
    evidence_ids: list[str],
    memory_value: str,
    semantic_confidence: float,
    location_hint: str | None,
    source_model: str,
    source_prompt_version: str,
    alias_version: str,
    personal_object_id: str | None = None,
    visible_description: str | None = None,
    relation: str | None = None,
    evidence_uris: list[str] | None = None,
    evidence_available: bool = True,
    source_capsule_id: str | None = None,
    detector_job_ids: list[str] | None = None,
    instance_ambiguity: bool = False,
    correction_source_id: str | None = None,
    created_at_ms: int | None = None,
    state: str | None = None,
    object_identity_id: str | None = None,
    aliases: list[str] | None = None,
    bbox_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if memory_value not in MEMORY_VALUES:
        raise ValueError(f"invalid memory_value: {memory_value}")
    if not object_label_raw.strip() or not normalized_label.strip():
        raise ValueError("object labels must not be empty")
    if captured_at_ms < 0:
        raise ValueError("captured_at_ms must be non-negative")
    confidence = float(semantic_confidence)
    if not 0 <= confidence <= 1:
        raise ValueError("semantic_confidence must be between 0 and 1")
    refs = sorted(dict.fromkeys(str(value) for value in evidence_ids if str(value)))
    resolved_state = state or ("fused" if detector_job_ids else "semantic_only")
    if resolved_state not in {"semantic_only", "fused"}:
        raise ValueError(f"invalid semantic observation state: {resolved_state}")
    identity = "\n".join(
        [
            resolved_state,
            str(captured_at_ms),
            normalized_label,
            personal_object_id or "",
            boot_session_id,
            window_id,
            *refs,
        ]
    )
    observation_id = "objobs:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    audit_status = "ready" if evidence_available else "evidence_missing"
    return {
        "observation_id": observation_id,
        "id": observation_id,
        "observation_kind": "semantic_confirmed",
        "state": resolved_state,
        "object_identity_id": object_identity_id or f"object:{observation_id.split(':', 1)[-1][:20]}",
        "canonical_name": object_label_raw,
        "aliases": list(dict.fromkeys(aliases or [])),
        "object_label_raw": object_label_raw,
        "object_label": object_label_raw,
        "normalized_label": normalized_label,
        "personal_object_id": personal_object_id,
        "visible_description": visible_description,
        "relation": relation,
        "location_hint": location_hint.strip() if isinstance(location_hint, str) and location_hint.strip() else None,
        "memory_value": memory_value,
        "semantic_confidence": confidence,
        "confidence": confidence,
        "captured_at_ms": int(captured_at_ms),
        "boot_session_id": boot_session_id,
        "session_id": boot_session_id,
        "window_id": window_id,
        "evidence_ids": refs,
        "evidence_id": refs[0] if refs else None,
        "evidence_uris": list(dict.fromkeys(evidence_uris or [])),
        "image_uri": (evidence_uris or [None])[0],
        "evidence_available": bool(evidence_available),
        "audit_status": audit_status,
        "source_capsule_id": source_capsule_id,
        "source_model": source_model,
        "source_prompt_version": source_prompt_version,
        "alias_version": alias_version,
        "detector_job_ids": sorted(dict.fromkeys(detector_job_ids or [])),
        "bbox_evidence": list(bbox_evidence or []),
        "instance_ambiguity": bool(instance_ambiguity),
        "correction_source_id": correction_source_id,
        "created_at_ms": int(created_at_ms if created_at_ms is not None else time.time() * 1000),
    }


def build_detector_observation(
    *,
    object_label_raw: str,
    normalized_label: str,
    confidence: float,
    captured_at_ms: int,
    boot_session_id: str,
    window_id: str,
    evidence_ids: list[str],
    evidence_uris: list[str],
    detector_job_ids: list[str],
    bbox_evidence: list[dict[str, Any]],
    source_model: str,
    vocabulary_hash: str | None = None,
    late: bool = False,
) -> dict[str, Any]:
    confidence = max(0.0, min(1.0, float(confidence)))
    refs = sorted(dict.fromkeys(str(value) for value in evidence_ids if str(value)))
    jobs = sorted(dict.fromkeys(str(value) for value in detector_job_ids if str(value)))
    identity = "\n".join(
        ["detector_only", boot_session_id, window_id, normalized_label, *refs, *jobs]
    )
    observation_id = "objobs:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return {
        "observation_id": observation_id,
        "id": observation_id,
        "observation_kind": "detector_candidate",
        "state": "detector_only",
        "object_identity_id": f"candidate:{observation_id.split(':', 1)[-1][:20]}",
        "canonical_name": object_label_raw,
        "aliases": [],
        "object_label_raw": object_label_raw,
        "object_label": object_label_raw,
        "normalized_label": normalized_label,
        "personal_object_id": None,
        "visible_description": None,
        "relation": None,
        "location_hint": None,
        "memory_value": "context_only",
        "semantic_confidence": confidence,
        "confidence": confidence,
        "captured_at_ms": int(captured_at_ms),
        "boot_session_id": boot_session_id,
        "session_id": boot_session_id,
        "window_id": window_id,
        "window_ids": [window_id],
        "capsule_ids": [],
        "evidence_ids": refs,
        "evidence_id": refs[0] if refs else None,
        "evidence_uris": list(dict.fromkeys(evidence_uris)),
        "image_uri": evidence_uris[0] if evidence_uris else None,
        "evidence_available": bool(refs and evidence_uris),
        "audit_status": "candidate",
        "source_capsule_id": None,
        "source_model": source_model,
        "source_prompt_version": "detector-only-v1",
        "alias_version": ObjectAliasRegistry.default().version,
        "detector_job_ids": jobs,
        "bbox_evidence": list(bbox_evidence),
        "vocabulary_hash": vocabulary_hash,
        "late": bool(late),
        "instance_ambiguity": True,
        "correction_source_id": None,
        "created_at_ms": int(time.time() * 1000),
        "updated_at_ms": int(time.time() * 1000),
        "version_history": [],
    }


def _beijing_text(epoch_ms: int) -> str:
    value = datetime.fromtimestamp(epoch_ms / 1000, tz=ZoneInfo("Asia/Shanghai"))
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _public_observation(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["captured_at_beijing"] = _beijing_text(int(item.get("captured_at_ms") or 0))
    result["uncertainty"] = (
        "low"
        if float(item.get("semantic_confidence") or item.get("confidence") or 0) >= 0.85
        else "medium"
        if float(item.get("semantic_confidence") or item.get("confidence") or 0) >= 0.6
        else "high"
    )
    return result


def build_last_seen_result(
    observations: Iterable[dict[str, Any]],
    *,
    query: str,
    query_key: str,
    alias_version: str,
    reliable_confidence: float = DEFAULT_RELIABLE_CONFIDENCE,
) -> dict[str, Any]:
    matches = [
        dict(item)
        for item in observations
        if item.get("normalized_label") == query_key
        and (
            item.get("memory_value", "memory_critical") == "memory_critical"
            or item.get("state") == "detector_only"
        )
    ]
    matches.sort(key=lambda item: (int(item.get("captured_at_ms") or 0), str(item.get("observation_id") or item.get("id"))), reverse=True)
    reliable = [
        item
        for item in matches
        if item.get("state", "semantic_only") in {"semantic_only", "fused"}
        if bool(item.get("evidence_available", True))
        and item.get("audit_status", "ready") == "ready"
        and float(item.get("semantic_confidence") or item.get("confidence") or 0) >= reliable_confidence
    ]
    uncertain = [item for item in matches if item not in reliable]
    latest = reliable[0] if reliable else None
    later_uncertain = [
        item
        for item in uncertain
        if latest is None or int(item.get("captured_at_ms") or 0) > int(latest.get("captured_at_ms") or 0)
    ]
    ambiguous = bool(latest and latest.get("instance_ambiguity"))
    other_candidates = reliable[1:] if ambiguous else []

    if ambiguous:
        status = "multiple_candidates"
    elif latest and later_uncertain:
        status = "reliable_with_later_uncertain"
    elif latest:
        status = "reliable"
    elif uncertain:
        status = "uncertain_only"
        later_uncertain = uncertain
    else:
        status = "not_found"

    if latest:
        label = str(latest.get("object_label_raw") or query)
        location = latest.get("location_hint")
        if location:
            answer = f"{label}最近的可靠证据是在{location}。"
        else:
            answer = f"最近有{label}的可靠视觉证据，但位置没有可靠描述。"
        if ambiguous:
            answer += " 画面中有多个同类物品候选，无法确认是同一个实例。"
        elif later_uncertain:
            possible = later_uncertain[0].get("location_hint")
            answer += f" 之后可能在{possible}出现，但证据不足。" if possible else " 之后可能再次出现，但证据不足。"
    elif uncertain:
        location = uncertain[0].get("location_hint")
        answer = f"{query}可能在{location}出现，但只有不确定证据。" if location else f"可能看到了{query}，但证据不足且没有可靠位置。"
    else:
        answer = f"尚未找到{query}的相关证据。"

    personal_ids = {str(item.get("personal_object_id")) for item in matches if item.get("personal_object_id")}
    instance_status = "confirmed_personal_object" if len(personal_ids) == 1 and not ambiguous else "class_level_only"
    return {
        "query": query,
        "normalized_query": query_key,
        "answer_status": status,
        "answer": answer,
        "latest_reliable": _public_observation(latest) if latest else None,
        "later_uncertain": [_public_observation(item) for item in later_uncertain],
        "other_candidates": [_public_observation(item) for item in other_candidates],
        "instance_status": instance_status,
        "alias_version": alias_version,
        "projection_version": PROJECTION_VERSION,
    }


def projection_from_result(result: dict[str, Any], *, rebuilt_at_ms: int | None = None) -> dict[str, Any]:
    latest = result.get("latest_reliable") or {}
    return {
        "query_key": result["normalized_query"],
        "personal_object_id": latest.get("personal_object_id"),
        "latest_reliable_observation_id": latest.get("observation_id"),
        "later_uncertain_observation_ids": [item["observation_id"] for item in result.get("later_uncertain", [])],
        "candidate_observation_ids": [item["observation_id"] for item in result.get("other_candidates", [])],
        "answer_status": result["answer_status"],
        "projection_version": PROJECTION_VERSION,
        "rebuilt_at_ms": int(rebuilt_at_ms if rebuilt_at_ms is not None else time.time() * 1000),
    }
