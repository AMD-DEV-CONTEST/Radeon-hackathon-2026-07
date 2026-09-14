from __future__ import annotations

from typing import Any

from glass_gateway.services.memory_review_store import MemoryReviewStore


class IdentityCandidateAggregator:
    """Auto-cluster identity observations before the user reviews them.

    Face and voice chains stay separate. A person draft can link candidates
    when the evidence carries the same name/hint, but it remains a candidate
    until the user confirms it.
    """

    def __init__(
        self,
        store: MemoryReviewStore,
        *,
        face_threshold: float = 0.78,
        voice_threshold: float = 0.72,
    ) -> None:
        self.store = store
        self.face_threshold = face_threshold
        self.voice_threshold = voice_threshold

    def ingest_window(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        visible = [
            self._ingest_observation(
                modality="face",
                channel="visible",
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                item=item,
            )
            for item in visible_people
        ]
        speakers = [
            self._ingest_observation(
                modality="voice",
                channel="audio",
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                item=item,
            )
            for item in audio_speakers
        ]
        self._upsert_person_drafts(
            boot_session_id=boot_session_id,
            window_id=window_id,
            captured_at_ms=captured_at_ms,
            visible_people=visible,
            audio_speakers=speakers,
        )
        return {"visible_people": visible, "audio_speakers": speakers}

    def _ingest_observation(
        self,
        *,
        modality: str,
        channel: str,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        observation = {
            **item,
            "boot_session_id": boot_session_id,
            "window_id": window_id,
            "captured_at_ms": captured_at_ms,
        }
        if item.get("identity_preassigned"):
            return self._ingest_preassigned(
                channel=channel,
                modality=modality,
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                item=item,
            )
        candidate = self.store.upsert_identity_candidate(
            modality=modality,
            observation=observation,
            match_threshold=self.face_threshold if modality == "face" else self.voice_threshold,
        )
        name = self._name(item) or candidate.get("display_name") or candidate["id"]
        identity = self.store.add_identity_observation(
            name=name,
            channel=channel,
            boot_session_id=boot_session_id,
            window_id=window_id,
            captured_at_ms=captured_at_ms,
            confidence=self._confidence(item),
            source=item.get("source") or modality,
            evidence_id=item.get("evidence_id"),
        )
        return {
            **self._public_item(item),
            "name": name,
            "candidate_id": candidate["id"],
            "candidate_status": candidate.get("status", "candidate"),
            "identity_observation_id": identity["id"],
            "observation_count": candidate.get("observation_count", 1),
        }

    def _ingest_preassigned(
        self,
        *,
        channel: str,
        modality: str,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """Record a production projection without creating a legacy duplicate."""

        candidate_id = str(item.get("candidate_id") or "").strip()
        name = self._name(item) or candidate_id or (
            "未分配人脸" if modality == "face" else "未分配说话人"
        )
        identity = self.store.add_identity_observation(
            name=name,
            channel=channel,
            boot_session_id=boot_session_id,
            window_id=window_id,
            captured_at_ms=captured_at_ms,
            confidence=self._confidence(item),
            source=item.get("source") or "identity_worker",
            evidence_id=item.get("evidence_id"),
        )
        return {
            **self._public_item(item),
            "name": name,
            "candidate_id": candidate_id or None,
            "candidate_status": item.get("candidate_status") or "candidate",
            "identity_observation_id": identity["id"],
        }

    def _upsert_person_drafts(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
    ) -> None:
        names = {
            self._draft_name(item)
            for item in [*visible_people, *audio_speakers]
            if self._draft_name(item)
        }
        for name in names:
            face_candidate_ids = [
                item["candidate_id"]
                for item in visible_people
                if self._draft_name(item) == name and item.get("candidate_id")
            ]
            voice_candidate_ids = [
                item["candidate_id"]
                for item in audio_speakers
                if self._draft_name(item) == name and item.get("candidate_id")
            ]
            self.store.upsert_person_draft(
                display_name=name,
                face_candidate_ids=face_candidate_ids,
                voice_candidate_ids=voice_candidate_ids,
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
            )

    @staticmethod
    def _name(item: dict[str, Any]) -> str:
        return str(
            item.get("name")
            or item.get("label")
            or item.get("candidate_name")
            or item.get("profile_hint")
            or ""
        ).strip()

    @classmethod
    def _draft_name(cls, item: dict[str, Any]) -> str:
        if item.get("identity_preassigned") and not item.get("confirmed_person_id"):
            return ""
        return cls._name(item)

    @staticmethod
    def _confidence(item: dict[str, Any]) -> float | None:
        value = item.get("confidence")
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return None

    @staticmethod
    def _public_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in {"embedding", "face_embedding", "voice_embedding"}
        }
